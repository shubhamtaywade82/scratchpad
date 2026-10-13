"""Walk-forward evaluation with explicit windows, for series longer than the defaults in research/search.py.

Same conventions as research/ideas.walk: fixed signal, fresh capital each fold, flat at each fold boundary, ruin carried
forward. Bootstrap is a block bootstrap on the stitched per-bar returns.
"""
import random
import statistics as st

from research.engine import BARS_PER_YEAR, Result, Risk, metrics, returns_from_levels, simulate, atr


def walk_w(s, sig, risk: Risk, fund_t, fund_r, train: int, test: int, tf: str, stop_px=None):
    n = len(s)
    A = atr(s, 14)
    E = 1.0
    eq, pos, trades, folds = [], [], [], []
    skipped = 0
    ruined = False
    start = train
    while start + test <= n:
        if ruined:
            eq.extend([0.0] * test)
            pos.extend([0] * test)
            folds.append(-1.0)
        else:
            sp = None if stop_px is None else stop_px
            r = simulate(s, sig, risk, start, start + test, A=A, fund_t=fund_t, fund_r=fund_r, stop_px=sp)
            eq.extend(E * v for v in r.eq)
            E *= r.eq[-1]
            pos.extend(r.pos)
            trades.extend(r.trades)
            skipped += r.skipped
            folds.append(r.eq[-1] - 1)
            ruined = r.ruined or E <= 0
        start += test
    res = Result(eq=eq, pos=pos, trades=trades, skipped=skipped, ruined=ruined)
    return res, folds


def boot_sharpe(res: Result, tf: str, B: int = 1000, L: int = 20, seed: int = 7):
    rets = returns_from_levels(res.eq)
    rnd = random.Random(seed)
    m = len(rets)
    bpy = BARS_PER_YEAR[tf]
    out = []
    for _ in range(B):
        s = []
        while len(s) < m:
            i0 = rnd.randrange(m)
            s.extend(rets[i0:i0 + L])
        s = s[:m]
        sd = st.pstdev(s) or 1e-12
        out.append(st.fmean(s) / sd * (bpy ** 0.5))
    out.sort()
    return out[int(.05 * B)], out[int(.5 * B)], out[int(.95 * B)]


def summarize_w(s, sig, risk, fund_t, fund_r, train, test, tf, stop_px=None):
    res, folds = walk_w(s, sig, risk, fund_t, fund_r, train, test, tf, stop_px)
    m = metrics(res, tf)
    lo, md, hi = boot_sharpe(res, tf, L=10 if tf == '1d' else 20)
    return dict(m=m, folds=folds, boot=(lo, md, hi), ruined=res.ruined or res.eq[-1] <= 0, res=res)
