"""Adaptive Supertrend signals on SOLUSDT, compared with fixed-factor Supertrend on the same engine and risk.

Two adaptive mechanisms (both causal: the value at bar k uses bars <= k only):

  vol   volatility-scaled band multiplier. The multiplier is interpolated between m_lo and m_hi by the
        percentile rank of the current ATR% within the trailing L bars. High-volatility regimes get wider
        bands (fewer whipsaws), low-volatility regimes get tighter bands.

  perf  performance-selected factor. Three Supertrend instances run with multipliers (2, 3, 4). Each has an
        exponentially weighted average of its signed one-bar returns (EWMA over W bars). The instance with the
        best score so far sets the bar's direction. Ties go to the middle multiplier.

Baseline  fixed Supertrend (engine.supertrend_sig) with the same ATR period and the same 3-ATR stop.

Usage:  python3 -m research.adaptive_st 4h 1d:1 1h 15m     (tf or tf:leverage; default 5x)
"""
import statistics as st
import sys
from typing import List, Optional

from research.engine import (Risk, Series, atr, delay_sig, load_funding, load_klines, supertrend_sig, supertrend_dyn)
from research.ideas import summarize

SCREEN_LEV = 5.0
RISK_PCT = 0.01
STOP_ATR = 3.0
PERF_MULTS = (2.0, 3.0, 4.0)


def vol_adaptive_st_sig(s: Series, period: int, L: int, m_lo: float, m_hi: float) -> List[int]:
    n = len(s)
    A = atr(s, period)
    ap: List[Optional[float]] = [None if A[k] is None else A[k] / s.c[k] for k in range(n)]
    mult: List[Optional[float]] = [None] * n
    for k in range(n):
        if ap[k] is None:
            continue
        window = [ap[j] for j in range(max(0, k - L + 1), k + 1) if ap[j] is not None]
        if len(window) < L:
            continue
        rank = sum(1 for v in window if v <= ap[k]) / L          # percentile rank of today's ATR%, in (0, 1]
        mult[k] = m_lo + (m_hi - m_lo) * rank
    return supertrend_dyn(s, A, mult)


def perf_adaptive_st_sig(s: Series, period: int, W: int, mults=PERF_MULTS) -> List[int]:
    n = len(s)
    A = atr(s, period)
    dirs = [supertrend_dyn(s, A, [m] * n) for m in mults]
    alpha = 2.0 / (W + 1)
    K = len(mults)
    mid = K // 2
    perf = [0.0] * K
    out = [0] * n
    for k in range(1, n):
        r = s.c[k] / s.c[k - 1] - 1
        for j in range(K):
            # direction held through bar k was decided at close k-1, so its realised return is known at close k
            perf[j] = (1 - alpha) * perf[j] + alpha * dirs[j][k - 1] * r
        best = max(range(K), key=lambda j: (perf[j], -abs(j - mid)))
        out[k] = dirs[best][k]
    return out


def cells(tf: str, s: Series):
    """Pre-declared grid. Baseline = fixed factor, same ATR periods as the adaptive cells."""
    out = []
    for p, m in [(10, 3.0), (20, 3.0), (10, 2.0), (10, 4.0)]:
        out.append((f"fixed  p{p} x{m}", 'fixed', supertrend_sig(s, p, m)))
    for p in (10, 20):
        for L in (100, 200):
            for lo, hi in [(2.0, 4.0), (1.5, 4.0)]:
                out.append((f"vol    p{p} L{L} {lo}-{hi}", 'vol', vol_adaptive_st_sig(s, p, L, lo, hi)))
    for p in (10, 20):
        for W in (20, 50, 100):
            out.append((f"perf   p{p} W{W}", 'perf', perf_adaptive_st_sig(s, p, W)))
    return out


def _print_summaries(rows, tf, s, lev, ft, fr):
    print("-- family summary (WF OOS)")
    for fam in ('fixed', 'vol', 'perf'):
        sub = [r for _, f, _, r in rows if f == fam]
        print(f"   {fam:<6} positive {sum(r['m']['total'] > 0 for r in sub)}/{len(sub)}  "
              f"median Sh {st.median(r['m']['sharpe'] for r in sub):+.2f}  "
              f"median tot {st.median(r['m']['total'] for r in sub) * 100:+.1f}%")
    print("-- direction-flip null (adaptive cells)")
    for fam in ('vol', 'perf'):
        flipped = []
        for _, f, sig, _ in rows:
            if f == fam:
                risk = Risk(sizing='risk', risk_pct=RISK_PCT, lev=lev, sl_mult=STOP_ATR)
                rr = summarize(tf, s, [-x for x in sig], None, risk, ft, fr)
                flipped.append(rr['m']['total'])
        print(f"   {fam:<6} flipped positive {sum(t > 0 for t in flipped)}/{len(flipped)}  median tot {st.median(flipped) * 100:+.1f}%")


def screen(tf: str, ft, fr, lev: float = SCREEN_LEV):
    s = load_klines(tf)
    print(f"\n==================== {tf}: {len(s)} bars, adaptive Supertrend vs fixed, {lev:g}x, risk {RISK_PCT * 100:.0f}%, stop {STOP_ATR:.0f} ATR ====================")
    rows = []
    for name, fam, sig in cells(tf, s):
        risk = Risk(sizing='risk', risk_pct=RISK_PCT, lev=lev, sl_mult=STOP_ATR)
        r = summarize(tf, s, sig, None, risk, ft, fr)
        rows.append((name, fam, sig, r))
        m = r['m']
        print(f"{name:<22} WF tot {m['total'] * 100:+7.1f}%  Sh {m['sharpe']:+5.2f}  MDD {m['mdd'] * 100:6.1f}%  "
              f"n {m['n']:3d}  WR {m['wr'] * 100:4.1f}%  PF {m['pf']:4.2f}  L/S {m['nl']}/{m['ns']}  "
              f"stops {m['stops']:2d} liq {m['liqs']} skip {m['skipped']:3d}  "
              f"boot {r['boot'][0]:+.2f}/{r['boot'][1]:+.2f}/{r['boot'][2]:+.2f}  "
              f"folds+ {sum(f > 0 for f in r['folds'])}/{len(r['folds'])}" + ("  RUIN" if r['ruined'] else ""))
    _print_summaries(rows, tf, s, lev, ft, fr)
    return rows


NULL_CELLS = [
    ('vol p10 L100 1.5-4.0', lambda s: vol_adaptive_st_sig(s, 10, 100, 1.5, 4.0)),
    ('vol p20 L100 1.5-4.0', lambda s: vol_adaptive_st_sig(s, 20, 100, 1.5, 4.0)),
]


def null_check(tf: str, ft, fr, lev: float = SCREEN_LEV):
    """Original vs direction-flipped vs delayed (causal) signal, for two fixed adaptive cells."""
    s = load_klines(tf)
    risk = Risk(sizing='risk', risk_pct=RISK_PCT, lev=lev, sl_mult=STOP_ATR)
    print(f"\n==================== null checks, {tf} at {lev:g}x ====================")
    for name, fn in NULL_CELLS:
        base = fn(s)
        variants = [('original', base), ('flipped', [-x for x in base])]
        for d in (6, 12):
            variants.append((f'delay {d}', delay_sig(base, d)))
        for label, sig in variants:
            m = summarize(tf, s, sig, None, risk, ft, fr)['m']
            print(f"{name:<22} {label:<10} WF tot {m['total'] * 100:+7.1f}%  Sh {m['sharpe']:+5.2f}  n {m['n']:3d}")


if __name__ == '__main__':
    ft, fr = load_funding()
    if sys.argv[1:2] == ['null']:
        null_check(sys.argv[2] if len(sys.argv) > 2 else '4h', ft, fr)
        sys.exit(0)
    for arg in (sys.argv[1:] or ['4h', '1d', '1h', '15m']):
        tf, _, lv = arg.partition(':')
        screen(tf, ft, fr, float(lv) if lv else SCREEN_LEV)
