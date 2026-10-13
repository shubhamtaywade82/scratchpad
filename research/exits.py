"""Exit study: initial stop, breakeven, chandelier trail (with activation) and take-profit, on fixed entries.

Every variant uses the same entries and the same 3-ATR initial stop, so differences come only from the exit logic.
Exit parameters are R-multiples of the initial stop distance (1R = 3 x ATR14 at entry).

Per cell: walk-forward OOS (same windows as v5/v6), 5x margin ceiling, risk 1% per trade.
Also reported: exit mix and average realised R per trade, so a result can be attributed to the exit that produced it.

Usage:  python3 -m research.exits
"""
import statistics as st
import sys
from collections import Counter

from research.adaptive_st import vol_adaptive_st_sig
from research.engine import Risk, donchian_sig, ema_gate, load_funding, load_klines, metrics
from research.ideas import taker_absorb, walk

LEV = 5.0
RISK_PCT = 0.01
STOP_ATR = 3.0

# name, trail_mult, trail_act_r, be_r, tp_r, tp_frac (fraction closed at the target; 1.0 = full exit)
EXITS = [
    ('E0 stop only',                 None, 0.0, None, None, 1.0),
    ('E1 trail 3 ATR',               3.0,  0.0, None, None, 1.0),
    ('E2 trail 3 ATR after 1R',      3.0,  1.0, None, None, 1.0),
    ('E3 breakeven 1R',              None, 0.0, 1.0,  None, 1.0),
    ('E4 TP 1.5R',                   None, 0.0, None, 1.5,  1.0),
    ('E5 TP 2R',                     None, 0.0, None, 2.0,  1.0),
    ('E6 TP 3R',                     None, 0.0, None, 3.0,  1.0),
    ('E7 BE 1R + TP 2R',             None, 0.0, 1.0,  2.0,  1.0),
    ('E8 BE 1R + TP 3R',             None, 0.0, 1.0,  3.0,  1.0),
    ('E9 BE 1R + trail 2 after 1R',  2.0,  1.0, 1.0,  None, 1.0),
    ('E10 scale 50% at 1R',          None, 0.0, None, 1.0,  0.5),
    ('E11 scale 50% at 1R, BE, trail 3 after 1R', 3.0, 1.0, 1.0, 1.0, 0.5),
    ('E12 scale 50% at 2R, BE 1R',   None, 0.0, 1.0,  2.0,  0.5),
]


def signals(tf: str):
    s = load_klines(tf)
    if tf == '1h':
        return [
            ('A 1h adaptive Supertrend p20 L100 1.5-4', tf, vol_adaptive_st_sig(s, 20, 100, 1.5, 4.0)),
            ('C 1h taker-absorb m6 z2 T4', tf, taker_absorb(s, 6, 2.0, 4)),
        ]
    if tf == '4h':
        ema = ema_gate(s, 200)
        return [
            ('B 4h Donchian40 + EMA200', tf, donchian_sig(s, 40, gate=ema)),
            ('D 4h taker-absorb m18 z2 T4', tf, taker_absorb(s, 18, 2.0, 4)),
        ]
    raise ValueError(tf)


def positions(trades):
    """Group closes (partial + remainder) into positions. Returns (win rate, qty-weighted R per position)."""
    groups = {}
    for t in trades:
        key = (t['side'], t['k_in'], round(t['ep'], 10))
        g = groups.setdefault(key, dict(pnl=0.0, qty=0.0, rw=0.0))
        g['pnl'] += t['pnl']
        g['qty'] += t['qty']
        if t['r'] is not None:
            g['rw'] += t['r'] * t['qty']
    if not groups:
        return 0.0, 0.0
    wins = sum(1 for g in groups.values() if g['pnl'] > 0)
    rs = [g['rw'] / g['qty'] for g in groups.values() if g['qty'] > 0 and g['rw'] != 0]
    return wins / len(groups), (st.fmean(rs) if rs else 0.0)


def run_cell(tf, sig, name, trail, act, be, tp, frac, ft, fr):
    s = load_klines(tf)
    risk = Risk(sizing='risk', risk_pct=RISK_PCT, lev=LEV, sl_mult=STOP_ATR,
                trail_mult=trail, trail_act_r=act, be_r=be, tp_r=tp, tp_frac=frac)
    res, folds = walk(tf, s, sig, risk, None, ft, fr)
    m = metrics(res, tf)
    pos_wr, pos_r = positions(res.trades)
    mix = Counter(t['kind'] for t in res.trades)
    cal = m['total'] / abs(m['mdd']) if m['mdd'] < 0 else 0.0
    return dict(m=m, folds=folds, pos_wr=pos_wr, pos_r=pos_r, cal=cal, mix=mix, trades=res.trades,
                ruined=res.ruined or res.eq[-1] <= 0)


def fmt_mix(mix, n):
    order = ['init', 'be', 'trail', 'tp', 'tp_gap', 'tp_partial', 'signal', 'eod', 'liq']
    total = sum(mix.values())
    parts = [f"{k} {mix[k] / total * 100:.0f}%" for k in order if mix.get(k) and total]
    return ' '.join(parts)


def main():
    ft, fr = load_funding()
    for tf in ('1h', '4h'):
        for sname, _, sig in signals(tf):
            print(f"\n==================== {sname} | {tf} | {LEV:g}x, risk {RISK_PCT * 100:.0f}%, initial stop {STOP_ATR:.0f} ATR ====================")
            print(f"{'exit':<44} {'WF tot':>8} {'Sh':>6} {'MDD':>7} {'Calmar':>7} {'pos':>4} {'win%':>5} {'meanR':>6}  exit mix (of closes)")
            rows = []
            for name, trail, act, be, tp, frac in EXITS:
                r = run_cell(tf, sig, name, trail, act, be, tp, frac, ft, fr)
                m = r['m']
                rows.append((name, r))
                print(f"{name:<44} {m['total'] * 100:>+7.1f}% {m['sharpe']:>+6.2f} {m['mdd'] * 100:>6.1f}% {r['cal']:>+7.2f} "
                      f"{m['positions']:>4} {r['pos_wr'] * 100:>4.0f}% {r['pos_r']:>+6.2f}  {fmt_mix(r['mix'], m['n'])}"
                      + ("  RUIN" if r['ruined'] else ""))
            base = rows[0][1]['m']
            better = [n for n, r in rows[1:] if r['m']['sharpe'] > base['sharpe']]
            better_cal = [n for n, r in rows[1:] if r['cal'] > rows[0][1]['cal']]
            print(f"-- {len(better)}/{len(rows) - 1} exit variants beat the stop-only baseline on Sharpe "
                  f"(baseline Sh {base['sharpe']:+.2f}, median variant Sh {st.median(r['m']['sharpe'] for _, r in rows[1:]):+.2f})")
            print(f"-- {len(better_cal)}/{len(rows) - 1} beat the baseline on Calmar (return / |MDD|, baseline {rows[0][1]['cal']:+.2f})")


if __name__ == '__main__':
    main()
