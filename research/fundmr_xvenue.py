"""Funding mean reversion replicated on a second venue: Hyperliquid SOL perp.

Hyperliquid settles funding hourly, so the trailing windows are counted in hourly settlements:
  N = 720 (30 days) and N = 2160 (90 days). Signal, thresholds, exit, risk and walk-forward are the same as research/funding.py.
Prices: Hyperliquid candles (1d from 2023-05, 4h from 2024-07), so the walk-forward uses its own windows.

Usage: python3 -m research.fundmr_xvenue
"""
import itertools
import json
import statistics as st

from research.engine import Risk, to_series
from research.evalwin import summarize_w
from research.funding import mr_signal, z_at_bars


def load_hl():
    fr_rows = json.load(open('data/hl/SOL-funding.json'))['rows']
    ft = [r['t'] for r in fr_rows]
    fr = [r['rate'] for r in fr_rows]
    candles = {}
    for itv in ('1d', '4h'):
        rows = json.load(open(f'data/hl/SOL-{itv}.json'))['rows']
        candles[itv] = to_series(itv, [dict(openTime=r['t'], open=r['o'], high=r['h'], low=r['l'], close=r['c'])
                                       for r in rows])
    return ft, fr, candles


def _evaluate_cells(s, ft, fr, itv, lev, train, test):
    rows = []
    grid = itertools.product((False, True), (720, 2160), (2.0, 2.5))
    for robust, N, thr in grid:
        z = z_at_bars(s, ft, fr, N, robust)
        sig = mr_signal(z, thr, 0.5)
        risk = Risk(sizing='risk', risk_pct=0.01, lev=lev, sl_mult=3.0)
        r = summarize_w(s, sig, risk, ft, fr, train, test, itv)
        f = summarize_w(s, [-x for x in sig], risk, ft, fr, train, test, itv)
        m = r['m']
        tag = ('robust' if robust else 'stdev') + f" z N{N} thr{thr:g}"
        rows.append((tag, r, f))
        print(f"{tag:<26} {m['total'] * 100:>+7.1f}% {m['sharpe']:>+6.2f} {m['mdd'] * 100:>6.1f}% {m['n']:>4} "
              f"{m['nl']}/{m['ns']:<5} {sum(x > 0 for x in r['folds'])}/{len(r['folds']):<4} "
              f"{f['m']['total'] * 100:>+7.1f}%")
    return rows


def main():
    ft, fr, candles = load_hl()
    print("==================== funding mean reversion, Hyperliquid SOL (hourly settlements) ====================")
    for itv, lev, train, test in [('1d', 1.0, 365, 182), ('4h', 5.0, 720, 360)]:
        s = candles[itv]
        print(f"\n{itv}: {len(s)} bars, lev {lev:g}x, WF train {train} / test {test} bars")
        print(f"{'cell':<26} {'WF tot':>8} {'Sh':>6} {'MDD':>7} {'n':>4} {'L/S':>7} {'folds+':>6} {'flipped':>8}")
        rows = _evaluate_cells(s, ft, fr, itv, lev, train, test)
        pos = sum(1 for _, r, _ in rows if r['m']['total'] > 0)
        fpos = sum(1 for _, _, f in rows if f['m']['total'] > 0)
        print(f"-- {pos}/{len(rows)} cells positive WF OOS; flipped positive {fpos}/{len(rows)}")


if __name__ == '__main__':
    main()

