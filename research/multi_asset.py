"""v13: SOL/ETH/XRP perps with BTC as anchor, HTF bars built from Binance 1m, trailing SL/TP exits.

Protocol: every (signal variant x exit cell) of a family is a config; search.walk_forward picks the best config on
each TRAIN window and trades it on the next TEST window. Nulls re-run the same selection on flipped and 1-bar-delayed
signals. `replay` re-trades the chosen configs on the 1m series so stops and trails fire in true minute order.

Usage: python3 -m research.multi_asset screen [TF ...]   -> research/results/v13-screen-{tf}.txt
       python3 -m research.multi_asset replay TF FAM ...  -> research/results/v13-replay-{tf}.txt
"""
import itertools
from bisect import bisect_left
import json
import statistics as st
import sys
from multiprocessing import Pool
from pathlib import Path

from research import binance_1m as b1m
from research.adaptive_st import vol_adaptive_st_sig
from research.engine import (FEE, SLIP, Result, Risk, Series, atr, delay_sig, donchian_sig, ema_gate, metrics, simulate,
                             tsmom_sig)
from research.ideas import taker_absorb
from research.search import Cfg, deflated_sharpe_ratio, fmt, walk_forward, block_bootstrap_sharpe, BPY
from research.engine import returns_from_levels

ALTS = ('SOLUSDT', 'ETHUSDT', 'XRPUSDT')
ANCHOR = 'BTCUSDT'
WINDOWS = {'1h': (2160, 720), '4h': (1080, 540), '1d': (365, 182)}   # train/test: 90d/30d, 180d/90d, 1y/6m
DAYS = {'1h': 24, '4h': 6, '1d': 1}
FAMILIES = {'1h': ('AST', 'ABSORB', 'BTCBRK'),
            '4h': ('DONENS', 'TSMOM', 'AST', 'ABSORB', 'BTCBRK', 'RATIO'),
            '1d': ('DONENS', 'TSMOM', 'RATIO')}
# Isolated-margin leverage per TF: low enough that a 3-ATR stop sits inside the liquidation buffer (else entries skip)
LEV = {'1h': 5.0, '4h': 3.0, '1d': 2.0}
RISK_PCT = 0.01
RESULTS = Path(__file__).resolve().parent / 'results'


def exit_grid(tf: str):
    """144 trailing-exit cells: initial stop, chandelier trail, activation, tightening, giveback, scale-out."""
    for sl, tr, act, tight, gb, tp in itertools.product((1.5, 2.0, 3.0), (2.0, 3.0, 4.0), (1.0, 2.0),
                                                       (None, (3.0, 1.5)), (None, 0.4), (None, (2.0, 0.5))):
        yield (f"sl{sl}/tr{tr}/act{act}/tight{tight and tight[0]}/gb{gb}/tp{tp and tp[0]}",
               Risk(sizing='risk', lev=LEV[tf], risk_pct=RISK_PCT, sl_mult=sl, trail_mult=tr, trail_act_r=act,
                    trail_tight_r=tight and tight[0], trail_tight_mult=tight and tight[1], giveback=gb,
                    tp_r=tp and tp[0], tp_frac=tp[1] if tp else 1.0))


def load_htf(sym: str) -> dict:
    """Resampled 1h/4h/1d series, cached as JSON next to the zips (parsing 3M 1m rows is the slow part)."""
    cache = b1m.ROOT / f'{sym}-htf.json'
    if not cache.exists():
        cols = b1m.load_1m(sym)
        out = {tf: b1m.resample(cols, tf).__dict__ for tf in WINDOWS}
        out['missing_1m'] = b1m.missing_minutes(cols)
        cache.write_text(json.dumps(out))
    raw = json.loads(cache.read_text())
    return {tf: Series(**raw[tf]) for tf in WINDOWS} | {'missing_1m': raw['missing_1m']}


def on_alt(vals: list, b: Series, s: Series) -> list:
    """Map values indexed on BTC bars onto alt bars by open time (latest BTC bar at or before the alt bar)."""
    out, j = [], -1
    for t in s.t:
        while j + 1 < len(b.t) and b.t[j + 1] <= t:
            j += 1
        out.append(vals[j] if j >= 0 else 0)
    return out


def zarattini_sig(s: Series, ns) -> list:
    """Donchian ensemble (Zarattini et al. 2025): per lookback, enter on a close beyond the prior n-bar close extreme,
    exit when the close crosses a stop ratcheted to the n-bar close midpoint. Side = majority of lookbacks."""
    votes = [0] * len(s)
    for n in ns:
        side, stop = 0, None
        for k in range(n, len(s)):
            win = s.c[k - n:k]
            hi, lo, c = max(win), min(win), s.c[k]
            mid = (max(hi, c) + min(lo, c)) / 2
            if side and (c - stop) * side < 0:
                side = 0
            if not side and (c > hi or c < lo):
                side, stop = (1 if c > hi else -1), mid
            if side:
                stop = max(stop, mid) if side > 0 else min(stop, mid)
            votes[k] += side
    half = len(ns) / 2
    return [1 if v >= half else (-1 if v <= -half else 0) for v in votes]


def ratio_series(s: Series, b: Series) -> Series:
    bc = on_alt(b.c, b, s)
    r = [c / x if x else 0.0 for c, x in zip(s.c, bc)]
    return Series(s.tf, s.t, r, r, r, r)


def family_sigs(fam: str, tf: str, s: Series, b: Series) -> dict:
    d = DAYS[tf]
    if fam == 'DONENS':
        return {'ens': zarattini_sig(s, [n * d for n in (5, 10, 20, 30, 60, 90)])}
    if fam == 'TSMOM':
        return {f'L{L}d': tsmom_sig(s, L * d) for L in (3, 5, 10, 20)}
    if fam == 'AST':
        return {'p20L100': vol_adaptive_st_sig(s, 20, 100, 1.5, 4.0)}
    if fam == 'ABSORB':
        return {'m6z2T4' if tf == '1h' else 'm18z2T4': taker_absorb(s, 6 if tf == '1h' else 18, 2.0, 4)}
    n = 3 * d if tf != '1d' else 20
    if fam == 'BTCBRK':
        return {f'n{n}': donchian_sig(s, n, gate=on_alt(donchian_sig(b, n), b, s))}
    if fam == 'RATIO':
        return {f'n{n}': donchian_sig(ratio_series(s, b), n)}
    raise ValueError(fam)


def configs(fam: str, tf: str, s: Series, b: Series, transform=lambda x: x) -> list:
    btc_gate = on_alt(ema_gate(b, 200), b, s)
    sigs = {}
    for name, sig in family_sigs(fam, tf, s, b).items():
        sigs[name] = sig
        if fam not in ('BTCBRK', 'RATIO'):
            sigs[name + '+btc'] = [x if x == g else 0 for x, g in zip(sig, btc_gate)]
    return [Cfg(f'{fam}:{sn}/{en}', transform(sig), risk, fam)
            for sn, sig in sigs.items() for en, risk in exit_grid(tf)]


def positions(trades: list) -> list:
    """Merge scale-out rows into positions: unlevered move (fraction) and equity return."""
    by_entry = {}
    for t in trades:
        by_entry.setdefault(t['k_in'], []).append(t)
    out = []
    for rows in by_entry.values():
        qty = sum(r['qty'] for r in rows)
        move = sum(r['side'] * (r['px'] - r['ep']) * r['qty'] for r in rows) / (rows[0]['ep'] * qty)
        out.append(dict(move=move, eq=sum(r['ret'] for r in rows)))
    return out


def trade_table(trades: list) -> str:
    ps = positions(trades)
    if not ps:
        return '    no positions'
    wins = sorted(p['move'] for p in ps if p['move'] > 0)
    losses = sorted(p['move'] for p in ps if p['move'] <= 0)
    q = lambda xs, f: xs[int(f * (len(xs) - 1))] * 100 if xs else 0.0
    band = sum(1 for w in wins if 0.01 <= w <= 0.10)
    cost = 2 * (FEE + SLIP)
    margin = lambda lev: st.fmean((p['move'] - cost) * lev for p in ps) * 100
    return (f"    positions {len(ps)}  win {len(wins) / len(ps) * 100:.0f}%  winners in 1-10%: {band}/{len(wins)}"
            f"  >10%: {sum(1 for w in wins if w > 0.10)}\n"
            f"    unlevered move  winners p25/50/75 {q(wins, .25):+.2f}/{q(wins, .5):+.2f}/{q(wins, .75):+.2f}%"
            f"  losers p25/50/75 {q(losses, .25):+.2f}/{q(losses, .5):+.2f}/{q(losses, .75):+.2f}%"
            f"  mean {st.fmean(p['move'] for p in ps) * 100:+.2f}%\n"
            f"    return on margin per trade (net of costs): 5x {margin(5):+.2f}%  10x {margin(10):+.2f}%\n"
            f"    equity per trade (1% risk sizing): mean {st.fmean(p['eq'] for p in ps) * 100:+.2f}%"
            f"  best {max(p['eq'] for p in ps) * 100:+.2f}%  worst {min(p['eq'] for p in ps) * 100:+.2f}%")


def run_family(job):
    alt, tf, fam = job
    s, b = load_htf(alt)[tf], load_htf(ANCHOR)[tf]
    ft, fr = b1m.load_funding(alt)
    train, test = WINDOWS[tf]
    rows = {}
    for label, tr in (('orig', lambda x: x), ('flip', lambda x: [-v for v in x]), ('delay1', lambda x: delay_sig(x, 1))):
        cfgs = configs(fam, tf, s, b, tr)
        res, folds = walk_forward(tf, s, cfgs, ft, fr, train, test)
        rows[label] = (res, folds, len(cfgs))
    return alt, tf, fam, rows


def report_family(alt, tf, fam, rows) -> tuple[str, bool]:
    res, folds, n_cfg = rows['orig']
    m = metrics(res, tf)
    rets = returns_from_levels(res.eq)
    lo, md, hi = block_bootstrap_sharpe(rets, BPY[tf], L=10 if tf == '1d' else 20)
    dsr = deflated_sharpe_ratio(rets, BPY[tf], n_trials=n_cfg)
    flip, delay = (metrics(rows[k][0], tf) for k in ('flip', 'delay1'))
    passed = m['exp'] > 0 and m['total'] > 0 and flip['total'] < m['total']
    chosen = {}
    for f in folds:
        chosen[f['chosen']] = chosen.get(f['chosen'], 0) + 1
    top = sorted(chosen.items(), key=lambda kv: -kv[1])[:3]
    text = (f"\n--- {alt} {tf} {fam}  ({n_cfg} configs, {len(folds)} folds)  {'PASS' if passed else 'fail'}\n"
            f"  [WF OOS] {fmt(m)}\n"
            f"    bootstrap Sh 5/50/95 {lo:+.2f}/{md:+.2f}/{hi:+.2f}  DSR {dsr['dsr'] * 100:.1f}%  "
            f"flip tot {flip['total'] * 100:+.1f}%  delay1 tot {delay['total'] * 100:+.1f}%\n"
            f"{trade_table(res.trades)}\n"
            f"    most chosen: " + '; '.join(f'{k} x{v}' for k, v in top))
    return text, passed


def screen(tfs):
    jobs = [(a, tf, fam) for tf in tfs for fam in FAMILIES[tf] for a in ALTS]
    with Pool(4) as pool:
        done = pool.map(run_family, jobs)
    for tf in tfs:
        lines = [f"v13 screen {tf}: walk-forward OOS, risk {RISK_PCT:.0%}/trade, isolated lev {LEV[tf]:.0f}x, "
                 f"fee {FEE} + slip {SLIP}/side, funding charged"]
        verdict = {}
        for alt, t, fam, rows in done:
            if t != tf:
                continue
            text, ok = report_family(alt, tf, fam, rows)
            lines.append(text)
            verdict.setdefault(fam, []).append(ok)
        lines.append('\nCross-asset verdict (PASS on >= 2 of 3 alts):')
        lines += [f"  {fam}: {sum(v)}/3 {'SURVIVES' if sum(v) >= 2 else ''}" for fam, v in verdict.items()]
        (RESULTS / f'v13-screen-{tf}.txt').write_text('\n'.join(lines) + '\n')
        print('\n'.join(lines))


def to_1m(htf_vals: list, s: Series, t1m) -> list:
    """Value of the last HTF bar fully closed by the end of each minute (causal: bar j closes at t[j] + tf)."""
    tf_ms, out, j = b1m.TF_MS[s.tf], [], -1
    for t in t1m:
        while j + 1 < len(s.t) and s.t[j + 1] + tf_ms <= t + b1m.MINUTE_MS:
            j += 1
        out.append(htf_vals[j] if j >= 0 else None)
    return out


def replay_family(job):
    """Re-trade each fold's chosen config on 1m bars; returns (HTF result, 1m result) of the stitched OOS."""
    alt, tf, fam = job
    s, b = load_htf(alt)[tf], load_htf(ANCHOR)[tf]
    ft, fr = b1m.load_funding(alt)
    cfgs = configs(fam, tf, s, b)
    res_htf, folds = walk_forward(tf, s, cfgs, ft, fr, *WINDOWS[tf])
    cols = b1m.load_1m(alt)
    m1 = Series('1m', cols['t'], cols['o'], cols['h'], cols['l'], cols['c'])
    a1m = to_1m(atr(s, 14), s, m1.t)
    by_name = {c.name: c for c in cfgs}
    eq, trades, E = [], [], 1.0
    first_minute = lambda k: bisect_left(m1.t, s.t[k]) if k < len(s) else len(m1)
    for f in folds:
        c = by_name.get(f['chosen'])
        if c is None:  # FLAT fold
            continue
        sig1m = [x or 0 for x in to_1m(c.sig, s, m1.t)]
        r = simulate(m1, sig1m, c.risk, max(1, first_minute(f['start'])), first_minute(f['end']),
                     A=a1m, fund_t=ft, fund_r=fr)
        eq.extend(E * v for v in r.eq[::1440])
        E *= r.eq[-1]
        trades.extend(r.trades)
    return alt, tf, fam, res_htf, Result(eq=eq or [1.0], pos=[], trades=trades)


def replay(tf, fams):
    jobs = [(a, tf, fam) for fam in fams for a in ALTS]
    with Pool(3) as pool:
        done = pool.map(replay_family, jobs)
    lines = ['v13 replay: chosen configs re-traded on 1m bars (true intrabar order for stops/trails)']
    for alt, tf, fam, htf, one in done:
        mh = metrics(htf, tf)
        lines.append(f"\n--- {alt} {tf} {fam}\n  [HTF] tot {mh['total'] * 100:+.1f}%  n {mh['n']}  exp {mh['exp'] * 100:+.3f}%\n"
                     f"{trade_table(htf.trades)}\n"
                     f"  [1m ] tot {(one.eq[-1] - 1) * 100:+.1f}%  n {len(one.trades)}\n{trade_table(one.trades)}")
    (RESULTS / f'v13-replay-{tf}.txt').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    cmd, args = sys.argv[1:2], sys.argv[2:]
    if cmd == ['screen']:
        screen(args or list(WINDOWS))
    elif cmd == ['replay'] and len(args) >= 2:
        replay(args[0], args[1:])
    else:
        sys.exit(__doc__)
