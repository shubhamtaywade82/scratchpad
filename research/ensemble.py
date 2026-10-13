"""Fixed (non-selected) designs with risk controls, evaluated on the same walk-forward folds.

Why: walk-forward selection of one config per fold is itself a source of noise (see search.py
output). A fixed design has no selection step, so its fold-by-fold results are a clean test of
whether the family has an edge at all, and risk-based sizing shows what drawdown it implies.

Designs are declared below BEFORE running; they are not tuned on these results.

Usage:  python3 -m research.ensemble 4h 1d 1h 15m
"""
import json
import math
import statistics as st
import sys

from research.engine import (Risk, Series, atr, donchian_sig, ema_gate, htf_gate, load_funding, returns_from_levels,
                             load_klines, metrics, simulate, to_series)
from research.evalwin import walk_w
from research.ideas import walk
from research.search import BPY, block_bootstrap_sharpe

HTF_FOR = {'15m': '1h', '1h': '4h'}
VOTE_LENGTHS = {'15m': [96, 192, 384], '1h': [24, 48, 72, 120], '4h': [20, 40, 60, 80], '1d': [20, 40, 55, 80]}


def vote(sigs):
    """Majority vote of several -1/0/+1 target states. Ties resolve to flat (no hidden leverage)."""
    out = []
    for vals in zip(*sigs):
        s = sum(vals)
        out.append(1 if s > 0 else (-1 if s < 0 else 0))
    return out


def designs(tf, base, fund_loader):
    """Returns list of (name, sig, risk). Gate = EMA200 on the same timeframe, or MTF for intraday."""
    if tf in HTF_FOR:
        gate = htf_gate(base, load_klines(HTF_FOR[tf]), 200)
        gname = f"MTF {HTF_FOR[tf]} EMA200"
    else:
        gate = ema_gate(base, 200)
        gname = "EMA200"
    sigs = [donchian_sig(base, n, gate=gate) for n in VOTE_LENGTHS[tf]]
    ens = vote(sigs)
    out = []
    for rp in (0.01, 0.02):
        r = Risk(sizing='risk', risk_pct=rp, sl_mult=3.0, trail_mult=3.0, lev=1.5)
        out.append((f"VOTE{VOTE_LENGTHS[tf]} {gname} stop3 trail3 risk{int(rp * 100)}%", ens, r))
    single = donchian_sig(base, VOTE_LENGTHS[tf][len(VOTE_LENGTHS[tf]) // 2], gate=gate)
    out.append((f"single DON{VOTE_LENGTHS[tf][len(VOTE_LENGTHS[tf]) // 2]} {gname} stop3 trail3 risk1%", single,
                Risk(sizing='risk', risk_pct=0.01, sl_mult=3.0, trail_mult=3.0, lev=1.5)))
    return out


def walk_eval(tf, base, sig, risk, fund_t, fund_r):
    return walk(tf, base, sig, risk, None, fund_t, fund_r)


def fmt(m):
    return (f"tot {m['total'] * 100:+7.1f}%  CAGR {m['cagr'] * 100:+6.1f}%  Sh {m['sharpe']:+5.2f}  "
            f"MDD {m['mdd'] * 100:6.1f}%  Calmar {m['calmar']:+5.2f}  n {m['n']:3d}  WR {m['wr'] * 100:4.1f}%  "
            f"PF {m['pf']:4.2f}  expo {m['exposure'] * 100:4.0f}%  stops {m['stops']}")


def run(tf, fund_t, fund_r):
    base = load_klines(tf)
    n = len(base)
    print(f"\n==================== {tf}: {n} bars ({n / BPY[tf] * 365:.0f} d) — FIXED designs, no selection ====================")
    cut = int(n * 0.6)
    for name, sig, risk in designs(tf, base, None):
        A = atr(base, 14)
        full = metrics(simulate(base, sig, risk, 1, n, A=A, fund_t=fund_t, fund_r=fund_r), tf)
        oos = metrics(simulate(base, sig, risk, cut, n, A=A, fund_t=fund_t, fund_r=fund_r), tf)
        res, folds = walk_eval(tf, base, sig, risk, fund_t, fund_r)
        wf = metrics(res, tf)
        rets = returns_from_levels(res.eq)
        lo, md, hi = block_bootstrap_sharpe(rets, BPY[tf], L=10 if tf == '1d' else 20)
        pos_folds = sum(1 for f in folds if f > 0)
        print(f"\n{name}")
        print(f"  FULL     {fmt(full)}")
        print(f"  OOS 40%  {fmt(oos)}")
        print(f"  WF OOS   {fmt(wf)}")
        print(f"           folds positive {pos_folds}/{len(folds)}: " + " ".join(f"{f * 100:+.1f}%" for f in folds))
        print(f"           block-bootstrap Sharpe 5/50/95: {lo:+.2f} / {md:+.2f} / {hi:+.2f}")


def load_resampled_4h(inst: str) -> Series:
    with open(f'data/okx/{inst}-USDT-SWAP-15m.json') as f:
        rows = json.load(f)['rows']
    bars = []
    for i in range(0, len(rows) - 15, 16):
        c = rows[i:i + 16]
        bars.append(dict(
            openTime=c[0]['t'], open=c[0]['o'],
            high=max(x['h'] for x in c),
            low=min(x['l'] for x in c),
            close=c[-1]['c'],
            volume=sum(x.get('vol', 0.0) for x in c)
        ))
    return to_series('4h', bars)


def _calc_portfolio_stats(rets_matrix, all_trades, bpy: int = 2190) -> dict:
    port_rets = [sum(col) / len(col) for col in zip(*rets_matrix)]
    eq, peak, mdd = [1.0], 1.0, 0.0
    for r in port_rets:
        eq.append(eq[-1] * (1.0 + r))
        peak = max(peak, eq[-1])
        mdd = min(mdd, eq[-1] / peak - 1.0)
    mu, sd = st.fmean(port_rets), st.pstdev(port_rets) or 1e-12
    years = len(port_rets) / bpy
    cagr = (eq[-1] ** (1 / years) - 1) if years > 0 and eq[-1] > 0 else -1.0
    wins = [t['ret'] for t in all_trades if t['ret'] > 0]
    losses = [t['ret'] for t in all_trades if t['ret'] <= 0]
    gp, gl = sum(wins), -sum(losses)
    return dict(
        tot=eq[-1] - 1.0, cagr=cagr, sharpe=mu / sd * math.sqrt(bpy), mdd=mdd,
        calmar=(cagr / abs(mdd)) if mdd < 0 else 0.0,
        n=len(all_trades), wr=len(wins) / len(all_trades) if all_trades else 0.0,
        pf=(gp / gl) if gl > 0 else 0.0, rets=port_rets
    )


def run_portfolio(assets=('BTC', 'ETH', 'SOL')) -> dict:
    print(f"\n==================== MULTI-ASSET PORTFOLIO ({', '.join(assets)}) | 4h DON40+EMA200 ====================")
    risk = Risk(sizing='risk', risk_pct=0.01, lev=5.0, sl_mult=3.0)
    rets_matrix, all_trades = [], []
    for coin in assets:
        s = load_resampled_4h(coin)
        sig = donchian_sig(s, 40, gate=ema_gate(s, 200))
        res, folds = walk_w(s, sig, risk, [], [], 360, 180, '4h')
        m = metrics(res, '4h')
        all_trades.extend(res.trades)
        rets_matrix.append(returns_from_levels(res.eq))
        fpos = sum(1 for f in folds if f > 0)
        print(f"  {coin:<5} {fmt(m)}  folds+ {fpos}/{len(folds)}")
    min_len = min(len(r) for r in rets_matrix)
    stats = _calc_portfolio_stats([r[:min_len] for r in rets_matrix], all_trades)
    lo, md, hi = block_bootstrap_sharpe(stats['rets'], 2190, B=2000, L=20)
    print(f"\n  COMBINED 3-ASSET PORTFOLIO (1/3 risk allocation each):")
    print(f"    tot {stats['tot'] * 100:+7.2f}%  CAGR {stats['cagr'] * 100:+6.2f}%/yr  Sh {stats['sharpe']:+5.2f}  "
          f"MDD {stats['mdd'] * 100:6.2f}%  Calmar {stats['calmar']:+5.2f}  n {stats['n']:3d}  WR {stats['wr'] * 100:4.1f}%  PF {stats['pf']:4.2f}")
    print(f"    block-bootstrap Sharpe 5/50/95: {lo:+.2f} / {md:+.2f} / {hi:+.2f}")
    return stats


if __name__ == '__main__':
    args = sys.argv[1:]
    if 'portfolio' in args:
        run_portfolio()
    else:
        ft, fr = load_funding()
        for tf in (args or ['4h', '1d']):
            run(tf, ft, fr)
