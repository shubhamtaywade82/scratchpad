"""Strategies sourced from web research (see SOLUSDT-WEBSTRATS-v9.md for links and what each source claimed).

  adxst    Supertrend with an ADX trend-strength gate on new entries (Quantzee / Forextester suggest a trend-quality
           filter against whipsaws). A flip into a direction opens a position only when ADX(14) > threshold; an
           existing position is held until Supertrend flips.
  squeeze  Bollinger/Keltner squeeze release (Mudrex / pyquantlab). Squeeze = Bollinger Bands inside Keltner Channels.
           On the bar the squeeze releases, enter in the direction of close vs the 20-bar SMA. Exit when close
           crosses back through the SMA.
  tsmom    Short-lookback time-series momentum (a crypto TSMOM paper reports daily short-lookback signals holding up
           out of sample). Sign of the L-bar return, always in market after warm-up.

All signals use bars <= k. Pre-declared grids are small; breadth across cells is the screen, not the best cell.

Usage:  python3 -m research.webstrats
"""
import math
import statistics as st
import sys
from typing import List

from research.adaptive_st import vol_adaptive_st_sig
from research.engine import (Risk, Series, atr, ema, load_funding, load_klines, supertrend_sig, tsmom_sig)
from research.ideas import walk
from research.engine import metrics, BARS_PER_YEAR
from research.search import WINDOWS

STOP_ATR = 3.0
RISK_PCT = 0.01
LEV_BY_TF = {'1h': 5.0, '4h': 5.0, '1d': 1.0}    # 1d: a 3-ATR stop exceeds the 5x buffer (see leverage.txt)


def adx(s: Series, n: int = 14) -> List[float]:
    """Wilder ADX. Undefined (0.0) until 2n bars are available."""
    N = len(s)
    out = [0.0] * N
    tr_list, pdm, mdm = [], [], []
    for k in range(1, N):
        up = s.h[k] - s.h[k - 1]
        dn = s.l[k - 1] - s.l[k]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        mdm.append(dn if (dn > up and dn > 0) else 0.0)
        tr_list.append(max(s.h[k] - s.l[k], abs(s.h[k] - s.c[k - 1]), abs(s.l[k] - s.c[k - 1])))
    if len(tr_list) < 2 * n:
        return out
    tr_s = sum(tr_list[:n])
    p_s = sum(pdm[:n])
    m_s = sum(mdm[:n])
    dx = []
    for i in range(n, len(tr_list)):
        if i > n:
            tr_s = tr_s - tr_s / n + tr_list[i]
            p_s = p_s - p_s / n + pdm[i]
            m_s = m_s - m_s / n + mdm[i]
        pdi = 100 * p_s / tr_s if tr_s else 0.0
        mdi = 100 * m_s / tr_s if tr_s else 0.0
        d = pdi + mdi
        dx.append(100 * abs(pdi - mdi) / d if d else 0.0)
        if len(dx) == n:
            adx_v = sum(dx) / n
        elif len(dx) > n:
            adx_v = (adx_v * (n - 1) + dx[-1]) / n
        else:
            continue
        out[i + 1] = adx_v
    return out


def supertrend_dirs(s: Series, period: int, mult: float) -> List[int]:
    return supertrend_sig(s, period, mult)


def adx_gated(dirs: List[int], adx_v: List[float], thr: float) -> List[int]:
    """Enter only on a Supertrend flip with ADX above thr; hold until Supertrend flips again."""
    out = [0] * len(dirs)
    pos = 0
    for k in range(len(dirs)):
        d = dirs[k]
        if d == 0:
            continue
        if d != pos:                       # Supertrend flipped (or first defined bar)
            pos = d if adx_v[k] > thr else 0
        out[k] = pos
    return out


def squeeze_sig(s: Series, n: int = 20, m_bb: float = 2.0, m_kc: float = 1.5) -> List[int]:
    N = len(s)
    A = atr(s, n)
    ema_mid = ema(s.c, n)
    sma = [None] * N
    sd = [None] * N
    for k in range(n - 1, N):
        w = s.c[k - n + 1:k + 1]
        sma[k] = st.fmean(w)
        sd[k] = st.pstdev(w)
    sq = [False] * N
    for k in range(N):
        if sma[k] is None or A[k] is None:
            continue
        bb_u, bb_l = sma[k] + m_bb * sd[k], sma[k] - m_bb * sd[k]
        kc_u, kc_l = ema_mid[k] + m_kc * A[k], ema_mid[k] - m_kc * A[k]
        sq[k] = bb_u < kc_u and bb_l > kc_l
    out = [0] * N
    pos = 0
    for k in range(1, N):
        if sma[k] is None:
            continue
        released = sq[k - 1] and not sq[k]
        if pos == 0 and released:
            pos = 1 if s.c[k] > sma[k] else (-1 if s.c[k] < sma[k] else 0)
        elif pos == 1 and s.c[k] < sma[k]:
            pos = 0
        elif pos == -1 and s.c[k] > sma[k]:
            pos = 0
        out[k] = pos
    return out


def cells(tf: str, s: Series):
    out = []
    # 1. Supertrend + ADX gate, on the fixed factor and on the volatility-adaptive band
    adx_v = adx(s, 14)
    bases = [('ST p10 x3', supertrend_dirs(s, 10, 3.0)),
             ('vol-adaptive p20 L100 1.5-4', vol_adaptive_st_sig(s, 20, 100, 1.5, 4.0))]
    for bname, dirs in bases:
        out.append((f"{bname} ungated", 'base', dirs))
        for thr in (20.0, 25.0):
            out.append((f"{bname} + ADX>{thr:g}", 'adx', adx_gated(dirs, adx_v, thr)))
    # 2. squeeze release, two Bollinger / Keltner width pairs
    for m_bb, m_kc in [(2.0, 1.5), (2.0, 2.0)]:
        out.append((f"squeeze BB{m_bb:g} KC{m_kc:g}", 'squeeze', squeeze_sig(s, 20, m_bb, m_kc)))
    # 3. short-lookback time-series momentum
    lookbacks = {'1h': [6, 12, 24], '4h': [6, 12, 24], '1d': [3, 5, 10]}[tf]
    for L in lookbacks:
        out.append((f"TSMOM short L{L}", 'tsmom', tsmom_sig(s, L)))
    return out


def screen(tf: str, ft, fr):
    s = load_klines(tf)
    lev = LEV_BY_TF[tf]
    print(f"\n==================== {tf}: {len(s)} bars, web strategies, {lev:g}x, risk {RISK_PCT * 100:.0f}%, stop {STOP_ATR:.0f} ATR ====================")
    rows = []
    for name, fam, sig in cells(tf, s):
        risk = Risk(sizing='risk', risk_pct=RISK_PCT, lev=lev, sl_mult=STOP_ATR)
        res, folds = walk(tf, s, sig, risk, None, ft, fr)
        m = metrics(res, tf)
        flip_res, _ = walk(tf, s, [-x for x in sig], risk, None, ft, fr)
        fm = metrics(flip_res, tf)
        rows.append((name, fam, m, folds, fm))
        print(f"{name:<30} WF tot {m['total'] * 100:+7.1f}%  Sh {m['sharpe']:+5.2f}  MDD {m['mdd'] * 100:6.1f}%  "
              f"n {m['n']:3d}  L/S {m['nl']}/{m['ns']}  stops {m['stops']:2d} liq {m['liqs']} skip {m['skipped']:3d}  "
              f"folds+ {sum(f > 0 for f in folds)}/{len(folds)}  flipped {fm['total'] * 100:+6.1f}%")
    pos = sum(1 for _, _, m, _, _ in rows if m['total'] > 0)
    print(f"-- breadth: {pos}/{len(rows)} cells positive WF OOS; median Sh {st.median(m['sharpe'] for _, _, m, _, _ in rows):+.2f}")
    for fam in ('base', 'adx', 'squeeze', 'tsmom'):
        sub = [(m, fm) for _, f, m, _, fm in rows if f == fam]
        if sub:
            print(f"   {fam:<8} positive {sum(m['total'] > 0 for m, _ in sub)}/{len(sub)}  "
                  f"median Sh {st.median(m['sharpe'] for m, _ in sub):+.2f}  "
                  f"median tot {st.median(m['total'] for m, _ in sub) * 100:+.1f}%  "
                  f"flipped positive {sum(fm['total'] > 0 for _, fm in sub)}/{len(sub)}")
    return rows


def null_check(tf: str, ft, fr, lookbacks):
    """Original, flipped and causal-delay variants for the TSMOM cells that survived the screen."""
    from research.engine import delay_sig
    s = load_klines(tf)
    lev = LEV_BY_TF[tf]
    print(f"\n==================== null checks, {tf} TSMOM short, {lev:g}x ====================")
    for L in lookbacks:
        base = tsmom_sig(s, L)
        variants = [('original', base), ('flipped', [-x for x in base])]
        variants += [(f'delay {d}', delay_sig(base, d)) for d in (1, 3)]
        for label, sig in variants:
            risk = Risk(sizing='risk', risk_pct=RISK_PCT, lev=lev, sl_mult=STOP_ATR)
            res, folds = walk(tf, s, sig, risk, None, ft, fr)
            m = metrics(res, tf)
            print(f"TSMOM L{L:<3} {label:<10} WF tot {m['total'] * 100:+7.1f}%  Sh {m['sharpe']:+5.2f}  "
                  f"MDD {m['mdd'] * 100:6.1f}%  n {m['n']:3d}  folds+ {sum(f > 0 for f in folds)}/{len(folds)}")


if __name__ == '__main__':
    ft, fr = load_funding()
    if sys.argv[1:2] == ['null']:
        null_check(sys.argv[2], ft, fr, [int(x) for x in sys.argv[3].split(',')])
    else:
        for tf in (sys.argv[1:] or ['1h', '4h', '1d']):
            screen(tf, ft, fr)

