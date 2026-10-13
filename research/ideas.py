"""Out-of-the-box hypotheses built only from OHLCV plus the taker-buy volume that every kline row carries.

Every builder is causal: the target state (and structural stop, if any) decided at index k uses bars <= k
and is executed at the open of k+1 by the engine.

Families
  sweep   liquidity sweep fade: a bar pierces the prior N-bar extreme and closes back inside it.
          Fade for T bars with a structural stop beyond the sweep wick (not an ATR multiple).
  taker   aggressor-flow: volume-weighted taker imbalance over m bars, z-scored on its trailing 100 bars.
          'cont'   follow the imbalance with hysteresis.
          'absorb' sellers hit the bid (negative imbalance) yet the bar closes up: buy. Mirror for shorts; hold T bars.
  vr      variance-ratio regime switch: VR(q) over a W-bar window. VR > 1+thr -> momentum over q bars;
          VR < 1-thr -> fade the q-bar move; otherwise flat.
  hmm     2-state Gaussian HMM on log returns, refit on each fold's trailing train window, causal forward filter
          over the test window. Long/short the state's mean sign when its filtered probability exceeds thr.

Usage:  python3 -m research.ideas 4h 1d 1h 15m
"""
import math
import statistics as st
import sys
from typing import List, Optional, Tuple

from research.engine import (Result, Risk, Series, atr, load_funding, load_klines, metrics, prior_max,
                             prior_min, returns_from_levels, simulate, BARS_PER_YEAR)
from research.search import WINDOWS, block_bootstrap_sharpe

SCREEN_LEV = 5.0          # screening leverage: 5x keeps 3-ATR stops inside the liquidation buffer
RISK_PCT = 0.01


# ----------------------------------------------------------------------------- sweep

def sweep_fade(s: Series, N: int, T: int, buf: float = 0.1) -> Tuple[List[int], List[Optional[float]]]:
    n = len(s)
    A = atr(s, 14)
    hi, lo = prior_max(s.h, N), prior_min(s.l, N)
    sig = [0] * n
    stop: List[Optional[float]] = [None] * n
    dirn, timer = 0, 0
    for k in range(n):
        ev, sx = 0, None
        if hi[k] is not None and A[k] is not None:
            if s.h[k] > hi[k] and s.c[k] < hi[k]:          # pierced the high, closed back under: bearish sweep
                ev, sx = -1, s.h[k] + buf * A[k]
            elif s.l[k] < lo[k] and s.c[k] > lo[k]:        # pierced the low, closed back over: bullish sweep
                ev, sx = 1, s.l[k] - buf * A[k]
        if ev:
            dirn, timer = ev, T
            stop[k] = sx
        if timer > 0:
            sig[k] = dirn
            timer -= 1
        else:
            dirn = 0
    return sig, stop


# ----------------------------------------------------------------------------- taker flow

def taker_imbalance(s: Series, m: int) -> List[Optional[float]]:
    """Volume-weighted aggressor imbalance over m bars: sum(2*takerBuy - vol) / sum(vol), in [-1, 1]."""
    if s.tb is None or s.v is None:
        raise ValueError("taker imbalance needs takerBuyBaseVolume and volume")
    n = len(s)
    d = [2 * s.tb[k] - s.v[k] for k in range(n)]
    out: List[Optional[float]] = [None] * n
    for k in range(m - 1, n):
        den = sum(s.v[k - m + 1:k + 1])
        out[k] = sum(d[k - m + 1:k + 1]) / den if den > 0 else 0.0
    return out


def taker_z(s: Series, m: int, L: int = 100) -> List[Optional[float]]:
    """Imbalance standardised by its trailing L-bar mean and stdev (causal). Units: sigma.
    Raw imbalance on SOL is tiny on 4h/1d (|imb| rarely > 0.1), so thresholds are set in sigma, not absolute."""
    imb = taker_imbalance(s, m)
    n = len(s)
    out: List[Optional[float]] = [None] * n
    first = m - 1 + L - 1
    for k in range(first, n):
        w = [imb[j] for j in range(k - L + 1, k + 1)]
        mu, sd = st.fmean(w), st.pstdev(w)
        out[k] = (imb[k] - mu) / sd if sd > 0 else 0.0
    return out


def taker_cont(s: Series, m: int, theta: float) -> List[int]:
    z = taker_z(s, m)
    sig = [0] * len(s)
    st_ = 0
    for k in range(len(s)):
        if z[k] is None:
            continue
        if z[k] > theta:
            st_ = 1
        elif z[k] < -theta:
            st_ = -1
        elif st_ == 1 and z[k] < 0:
            st_ = 0
        elif st_ == -1 and z[k] > 0:
            st_ = 0
        sig[k] = st_
    return sig


def taker_absorb(s: Series, m: int, theta: float, T: int) -> List[int]:
    z = taker_z(s, m)
    sig = [0] * len(s)
    dirn, timer = 0, 0
    for k in range(len(s)):
        if z[k] is None:
            continue
        ev = 0
        if z[k] < -theta and s.c[k] > s.o[k]:         # aggressive sellers absorbed, bar closes up
            ev = 1
        elif z[k] > theta and s.c[k] < s.o[k]:        # aggressive buyers absorbed, bar closes down
            ev = -1
        if ev:
            dirn, timer = ev, T
        if timer > 0:
            sig[k] = dirn
            timer -= 1
        else:
            dirn = 0
    return sig


# ----------------------------------------------------------------------------- variance-ratio regime

def vr_regime(s: Series, W: int, q: int, thr: float) -> List[int]:
    n = len(s)
    lc = [math.log(c) for c in s.c]
    sig = [0] * n
    for k in range(W + q - 1, n):
        win1 = [lc[j] - lc[j - 1] for j in range(k - W + 1, k + 1)]
        winq = [lc[j] - lc[j - q] for j in range(k - W + 1, k + 1)]
        m1, mq = st.fmean(win1), st.fmean(winq)
        v1 = sum((x - m1) ** 2 for x in win1) / (W - 1)
        vq = sum((x - mq) ** 2 for x in winq) / (W - 1)
        if v1 <= 0:
            continue
        vr = vq / (q * v1)
        mom = lc[k] - lc[k - q]
        d = 1 if mom > 0 else (-1 if mom < 0 else 0)
        if vr > 1 + thr:
            sig[k] = d
        elif vr < 1 - thr:
            sig[k] = -d
    return sig


# ----------------------------------------------------------------------------- 2-state Gaussian HMM

def _logn(x: float, mu: float, var: float) -> float:
    return -0.5 * (math.log(2 * math.pi * var) + (x - mu) ** 2 / var)


def hmm_fit(x: List[float], iters: int = 40):
    """Baum-Welch for a 2-state univariate Gaussian HMM with scaled forward-backward."""
    T = len(x)
    mu = [sorted(x)[T // 4], sorted(x)[3 * T // 4]]
    var = [st.pvariance(x) + 1e-9] * 2
    pi = [0.5, 0.5]
    A = [[0.95, 0.05], [0.05, 0.95]]
    for _ in range(iters):
        b = [[math.exp(_logn(x[t], mu[j], var[j])) + 1e-300 for j in range(2)] for t in range(T)]
        alpha = [[0.0, 0.0] for _ in range(T)]
        c = [0.0] * T
        a0 = [pi[j] * b[0][j] for j in range(2)]
        c[0] = sum(a0)
        alpha[0] = [v / c[0] for v in a0]
        for t in range(1, T):
            a = [sum(alpha[t - 1][i] * A[i][j] for i in range(2)) * b[t][j] for j in range(2)]
            c[t] = sum(a)
            alpha[t] = [v / c[t] for v in a]
        beta = [[1.0, 1.0] for _ in range(T)]
        for t in range(T - 2, -1, -1):
            beta[t] = [sum(A[i][j] * b[t + 1][j] * beta[t + 1][j] for j in range(2)) / c[t + 1] for i in range(2)]
        gamma = []
        for t in range(T):
            g = [alpha[t][j] * beta[t][j] for j in range(2)]
            z = sum(g)
            gamma.append([v / z for v in g])
        xi_sum = [[0.0, 0.0], [0.0, 0.0]]
        for t in range(T - 1):
            xi = [[alpha[t][i] * A[i][j] * b[t + 1][j] * beta[t + 1][j] for j in range(2)] for i in range(2)]
            z = sum(sum(r) for r in xi)
            for i in range(2):
                for j in range(2):
                    xi_sum[i][j] += xi[i][j] / z
        pi = gamma[0][:]
        for i in range(2):
            rs = sum(xi_sum[i])
            A[i] = [xi_sum[i][j] / rs for j in range(2)]
        for j in range(2):
            w = sum(gamma[t][j] for t in range(T))
            mu[j] = sum(gamma[t][j] * x[t] for t in range(T)) / w
            var[j] = max(sum(gamma[t][j] * (x[t] - mu[j]) ** 2 for t in range(T)) / w, 1e-8)
    return pi, A, mu, var


def hmm_filter(x: List[float], pi, A, mu, var) -> List[List[float]]:
    """Causal forward filter: P(state_t | x_0..t) for each t."""
    out = []
    p = pi[:]
    for t, xt in enumerate(x):
        if t > 0:
            p = [sum(p[i] * A[i][j] for i in range(2)) for j in range(2)]
        e = [math.exp(_logn(xt, mu[j], var[j])) for j in range(2)]
        g = [p[j] * e[j] for j in range(2)]
        z = sum(g) or 1e-300
        p = [v / z for v in g]
        out.append(p[:])
    return out


def hmm_fold_signal(s: Series, train: int, test: int, thr: float, iters: int = 40) -> List[int]:
    n = len(s)
    lr = [0.0] + [100 * math.log(s.c[k] / s.c[k - 1]) for k in range(1, n)]
    sig = [0] * n
    start = train
    while start + test <= n:
        pi, A, mu, var = hmm_fit(lr[start - train:start], iters)
        probs = hmm_filter(lr[start - 1:start + test - 1], pi, A, mu, var)
        for i, p in enumerate(probs):
            j = 0 if p[0] >= p[1] else 1
            if p[j] > thr and mu[j] != 0:
                sig[start - 1 + i] = 1 if mu[j] > 0 else -1
        start += test
    return sig


# ----------------------------------------------------------------------------- evaluation

def walk(tf: str, s: Series, sig: List[int], risk: Risk, stop_px, ft, fr):
    """Fixed signal, fixed windows (same as search.WINDOWS). Fresh capital per fold; ruin is carried forward."""
    train, test = WINDOWS[tf]
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
            r = simulate(s, sig, risk, start, start + test, A=A, fund_t=ft, fund_r=fr, stop_px=stop_px)
            eq.extend(E * v for v in r.eq)
            E *= r.eq[-1]
            pos.extend(r.pos)
            trades.extend(r.trades)
            skipped += r.skipped
            folds.append(r.eq[-1] - 1)
            ruined = r.ruined or E <= 0
        start += test
    return Result(eq=eq, pos=pos, trades=trades, skipped=skipped), folds


def summarize(tf: str, s: Series, sig, stop_px, risk: Risk, ft, fr):
    res, folds = walk(tf, s, sig, risk, stop_px, ft, fr)
    m = metrics(res, tf)
    rets = returns_from_levels(res.eq)
    lo, md, hi = block_bootstrap_sharpe(rets, BARS_PER_YEAR[tf], L=10 if tf == '1d' else 20)
    return dict(m=m, folds=folds, boot=(lo, md, hi), ruined=res.ruined or (res.eq and res.eq[-1] <= 0))


def cells_for(tf: str, s: Series):
    """Pre-declared grids. Kept small so that breadth (share of positive cells) is an honest screen."""
    G = {
        '15m': dict(sweepN=[48, 192], m=[16, 64], W=[240, 480], trainH=1440),
        '1h': dict(sweepN=[24, 72], m=[6, 24], W=[120, 240], trainH=720),
        '4h': dict(sweepN=[20, 50], m=[6, 18], W=[120, 240], trainH=720),
        '1d': dict(sweepN=[10, 20], m=[3, 10], W=[120, 240], trainH=365),
    }[tf]
    out = []
    for N in G['sweepN']:
        for T in (4, 8, 16):
            sig, sp = sweep_fade(s, N, T)
            out.append((f"sweep N{N} T{T}", 'sweep', sig, sp))
    for m in G['m']:
        for th in (1.0, 2.0):
            out.append((f"taker-cont m{m} z{th}", 'taker', taker_cont(s, m, th), None))
            for T in (4, 8):
                out.append((f"taker-absorb m{m} z{th} T{T}", 'taker', taker_absorb(s, m, th, T), None))
    for W in G['W']:
        for q in (4, 8):
            for thr in (0.1, 0.25):
                out.append((f"VR W{W} q{q} thr{thr}", 'vr', vr_regime(s, W, q, thr), None))
    for thr in (0.6, 0.8):
        out.append((f"HMM train{G['trainH']} thr{thr}", 'hmm',
                    hmm_fold_signal(s, G['trainH'], WINDOWS[tf][1], thr), None))
    return out


def screen(tf: str, ft, fr):
    s = load_klines(tf)
    print(f"\n==================== {tf}: {len(s)} bars, screen at {SCREEN_LEV:.0f}x, risk {RISK_PCT * 100:.0f}%/trade ====================")
    rows = []
    for name, fam, sig, sp in cells_for(tf, s):
        sl = None if sp is not None else 3.0
        risk = Risk(sizing='risk', risk_pct=RISK_PCT, lev=SCREEN_LEV, sl_mult=sl)
        r = summarize(tf, s, sig, sp, risk, ft, fr)
        m = r['m']
        rows.append((name, fam, r))
        print(f"{name:<28} WF tot {m['total'] * 100:+7.1f}%  Sh {m['sharpe']:+5.2f}  MDD {m['mdd'] * 100:6.1f}%  "
              f"n {m['n']:3d}  WR {m['wr'] * 100:4.1f}%  PF {m['pf']:4.2f}  L/S {m['nl']}/{m['ns']}  "
              f"stops {m['stops']:2d} liq {m['liqs']} skip {m['skipped']:3d}  "
              f"boot {r['boot'][0]:+.2f}/{r['boot'][1]:+.2f}/{r['boot'][2]:+.2f}  "
              f"folds+ {sum(f > 0 for f in r['folds'])}/{len(r['folds'])}" + ("  RUIN" if r['ruined'] else ""))
    pos = sum(1 for _, _, r in rows if r['m']['total'] > 0)
    print(f"-- breadth: {pos}/{len(rows)} cells positive WF OOS; median WF Sh {st.median(r['m']['sharpe'] for _, _, r in rows):+.2f}")
    for fam in ('sweep', 'taker', 'vr', 'hmm'):
        sub = [r for _, f, r in rows if f == fam]
        if sub:
            print(f"   {fam:<6} positive {sum(r['m']['total'] > 0 for r in sub)}/{len(sub)}  "
                  f"median Sh {st.median(r['m']['sharpe'] for r in sub):+.2f}  median tot {st.median(r['m']['total'] for r in sub) * 100:+.1f}%")
    return rows


if __name__ == '__main__':
    ft, fr = load_funding()
    for tf in (sys.argv[1:] or ['4h', '1d', '1h', '15m']):
        screen(tf, ft, fr)
