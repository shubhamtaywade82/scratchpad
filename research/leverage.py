"""Leverage study for SOLUSDT USD-M, isolated margin, 5x to 15x (1x shown as reference).

Model (see engine.Risk):
  liquidation distance  = 1/lev - mmr                 (adverse move from entry, fees ignored)
  entry allowed only if stop distance <= liq_buffer * liquidation distance
  closed form:  max leverage for a k-ATR stop = 1 / (k * ATR% / liq_buffer + mmr)

Sizing modes:
  fixed  : notional = lev * equity at every entry (constant leverage)
  risk   : notional = min(risk_pct * equity / stop_distance, lev * equity) (leverage is a cap, not a target)

mmr is an ASSUMPTION (0.5%). Confirm the tier for SOLUSDT notional from the exchange leverage-bracket endpoint.

Usage: python3 -m research.leverage
"""
import itertools
import random
import statistics as st

from research.engine import Risk, atr, donchian_sig, ema_gate, load_funding, load_klines, metrics, returns_from_levels
from research.ideas import taker_absorb, walk

LEVS = [1, 5, 7, 10, 12, 15]
MODES = [('fixed', None), ('risk', 0.01), ('risk', 0.02)]
STOPS = [2.0, 3.0]
MMR = 0.005
BUFFER = 0.8


def geometry(tfs=('1h', '4h', '1d')):
    print("LIQUIDATION GEOMETRY (isolated margin, mmr 0.5% assumed, buffer 0.8)")
    print(f"{'tf':<4}{'med ATR%':>9}{'lev':>5}{'liq dist':>10}{'max stop':>10}{'= ATR':>7}{'Lmax 2ATR':>11}{'Lmax 3ATR':>11}")
    for tf in tfs:
        s = load_klines(tf)
        A = atr(s, 14)
        med = st.median(A[k] / s.c[k] for k in range(14, len(s)))
        for lev in LEVS[1:]:
            lf = 1 / lev - MMR
            ms = lf * BUFFER
            print(f"{tf:<4}{med * 100:>8.2f}%{lev:>5}{lf * 100:>9.2f}%{ms * 100:>9.2f}%{ms / med:>7.2f}"
                  f"{1 / (2 * med / BUFFER + MMR):>10.1f}x{1 / (3 * med / BUFFER + MMR):>10.1f}x")


def mdd_distribution(levels, tf, B=1000, L=20, seed=5):
    """Block-bootstrap of stitched per-bar returns: distribution of maximum drawdown."""
    rets = returns_from_levels(levels)
    rnd = random.Random(seed)
    m = len(rets)
    mdds = []
    for _ in range(B):
        s = []
        while len(s) < m:
            i0 = rnd.randrange(m)
            s.extend(rets[i0:i0 + L])
        s = s[:m]
        eq, peak, mdd = 1.0, 1.0, 0.0
        for r in s:
            eq *= (1 + r)
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
        mdds.append(mdd)
    mdds.sort()
    return mdds[B // 2], mdds[int(0.05 * B)], sum(1 for x in mdds if x < -0.30) / B


def _eval_cell(s, tf: str, sig, ft, fr, sl: float, lev: int, mode: str, rp: float):
    risk = Risk(sizing='fixed' if mode == 'fixed' else 'risk', risk_pct=rp or 0.01, lev=lev, sl_mult=sl)
    res, _ = walk(tf, s, sig, risk, None, ft, fr)
    m = metrics(res, tf)
    p50, _, p30 = mdd_distribution(res.eq, tf)
    tag = 'fixed' if mode == 'fixed' else f"risk{int(rp * 100)}%"
    ruin = 'RUIN' if (res.ruined or res.eq[-1] <= 0) else '-'
    print(f"{sl:>4.0f}A {lev:>4} {tag:<7} {m['total'] * 100:>+7.1f}% {m['sharpe']:>+6.2f} {m['mdd'] * 100:>6.1f}% "
          f"{p50 * 100:>7.1f}% {p30 * 100:>11.1f}% {m['n']:>4} {m['eff_lev']:>7.2f} {m['liqs']:>4} "
          f"{m['skipped']:>5} {m['stops']:>5} {ruin:>5}")


def study(label, tf, sig, ft, fr):
    s = load_klines(tf)
    print(f"\n==================== {label} | {tf} ====================")
    print(f"{'stop':>5} {'lev':>4} {'mode':<7} {'WF tot':>8} {'Sh':>6} {'MDD':>7} {'MDD p50':>8} {'P(MDD<-30%)':>12} "
          f"{'n':>4} {'effLev':>7} {'liq':>4} {'skip':>5} {'stops':>5} {'ruin':>5}")
    for sl, lev, (mode, rp) in itertools.product(STOPS, LEVS, MODES):
        if lev != 1 or mode == 'fixed':
            _eval_cell(s, tf, sig, ft, fr, sl, lev, mode, rp)


if __name__ == '__main__':
    ft, fr = load_funding()
    geometry()
    s4 = load_klines('4h')
    study('DON40 + EMA200 (v4 baseline family)', '4h', donchian_sig(s4, 40, gate=ema_gate(s4, 200)), ft, fr)
    study('taker-absorb m18 z2 T4 (swing lead)', '4h', taker_absorb(s4, 18, 2.0, 4), ft, fr)
    s1 = load_klines('1h')
    study('taker-absorb m6 z2 T4 (intraday lead)', '1h', taker_absorb(s1, 6, 2.0, 4), ft, fr)
