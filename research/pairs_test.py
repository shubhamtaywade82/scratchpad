"""Stat-arb pair SOL / AVAX on OKX perpetuals (SOL-USDT-SWAP, AVAX-USDT-SWAP), walk-forward.

Each fold (pre-declared):
  1. TRAIN window: OLS of log SOL on log AVAX (with intercept) gives alpha and beta. Engle-Granger test on the residual:
     regress d(e_t) on e_{t-1} with intercept; trade the fold only if t(gamma) < -3.34 (EG 5% critical value, 2 variables).
     Spread mean mu and stdev sigma are taken from the train residuals.
  2. TEST window, same alpha and beta. z_t = (e_t - mu) / sigma.
       z < -2  -> long spread  (long SOL, short beta x AVAX)
       z > +2  -> short spread
       |z| < 0.5 -> exit.   |z| > 4 -> stop, no re-entry until |z| < 0.5.
  PnL per bar per unit gross capital = position x (dlogSOL - beta x dlogAVAX) / (1 + beta).
  Costs: each round trip = 2 fills per leg x 5 bps on each leg's notional = 10 bps of gross capital (placeholder fee model).

Frequencies: 1h (train 2160 bars = 90 days, test 720 = 30 days) and 1d (train 365, test 91), 1d built from the 1H closes.

Usage: python3 -m research.pairs_test
"""
import json
import math
import statistics as st
from datetime import datetime, timezone

EG_CRIT = -3.34
ENTRY, EXIT, STOP = 2.0, 0.5, 4.0
COST_RT = 0.0010   # 10 bps of gross capital per round trip


def load_closes():
    s = {r['t']: r['c'] for r in json.load(open('data/okx/SOL-USDT-SWAP-1H.json'))['rows']}
    a = {r['t']: r['c'] for r in json.load(open('data/okx/AVAX-USDT-SWAP-1H.json'))['rows']}
    common = sorted(set(s) & set(a))
    return common, [s[t] for t in common], [a[t] for t in common]


def daily(times, sc, ac):
    out_t, out_s, out_a = [], [], []
    cur = None
    for t, x, y in zip(times, sc, ac):
        day = t // 86_400_000
        if cur is None or day != cur:
            out_t.append(t)
            out_s.append(x)
            out_a.append(y)
            cur = day
        else:
            out_s[-1], out_a[-1] = x, y        # last hourly close of the day
    return out_t, out_s, out_a


def ols(x, y):
    mx, my = st.fmean(x), st.fmean(y)
    sxx = sum((v - mx) ** 2 for v in x)
    beta = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx
    return my - beta * mx, beta


def eg_t(e):
    """t-statistic of gamma in d(e_t) = c + gamma * e_{t-1} + u."""
    dy = [e[i] - e[i - 1] for i in range(1, len(e))]
    x = e[:-1]
    c, g = ols(x, dy)
    resid = [dy[i] - (c + g * x[i]) for i in range(len(dy))]
    s2 = sum(r * r for r in resid) / (len(dy) - 2)
    mx = st.fmean(x)
    sxx = sum((v - mx) ** 2 for v in x)
    se = math.sqrt(s2 / sxx)
    return g / se


def run(times, sc, ac, train, test, bpy, label):
    ls, la = [math.log(v) for v in sc], [math.log(v) for v in ac]
    n = len(times)
    E = 1.0
    eq_all, folds_out, trades = [], [], 0
    fold_pos = 0
    start = train
    while start + test <= n:
        y, x = ls[start - train:start], la[start - train:start]
        alpha, beta = ols(x, y)
        e_tr = [yy - alpha - beta * xx for yy, xx in zip(y, x)]
        t_eg = eg_t(e_tr)
        coint = t_eg < EG_CRIT
        mu, sigma = st.fmean(e_tr), st.pstdev(e_tr)
        pos = 0
        blocked = False
        fold_eq = 1.0
        fold_trades = 0
        for k in range(start, start + test):
            dlog_s = ls[k] - ls[k - 1]
            dlog_a = la[k] - la[k - 1]
            if coint and pos != 0:
                fold_eq *= 1 + pos * (dlog_s - beta * dlog_a) / (1 + beta)
            e = ls[k] - alpha - beta * la[k]
            z = (e - mu) / sigma if sigma > 0 else 0.0
            if not coint:
                eq_all.append(E * fold_eq)
                continue
            new = pos
            if pos == 0 and not blocked:
                if z < -ENTRY:
                    new = 1
                elif z > ENTRY:
                    new = -1
            elif pos != 0 and abs(z) < EXIT:
                new = 0
            elif pos != 0 and abs(z) > STOP:
                new = 0
                blocked = True
            if abs(z) < EXIT:
                blocked = False
            if new != pos:
                fold_eq *= 1 - COST_RT / 2              # half a round trip per entry or exit
                if new != 0:
                    fold_trades += 1
                pos = new
            eq_all.append(E * fold_eq)
        if coint:
            trades += fold_trades
        folds_out.append(dict(start=datetime.fromtimestamp(times[start] / 1000, timezone.utc).strftime('%Y-%m-%d'),
                              coint=coint, t_eg=t_eg, beta=beta, fold_ret=fold_eq - 1, trades=fold_trades))
        E = E * fold_eq
        start += test
    rets = [eq_all[0] - 1.0] + [eq_all[i] / eq_all[i - 1] - 1 for i in range(1, len(eq_all))] if eq_all else []
    peak, mdd = 1.0, 0.0
    lvl = 1.0
    for r in rets:
        lvl *= 1 + r
        peak = max(peak, lvl)
        mdd = min(mdd, lvl / peak - 1)
    sh = st.fmean(rets) / st.pstdev(rets) * math.sqrt(bpy) if rets and st.pstdev(rets) > 0 else float('nan')
    n_coint = sum(1 for f in folds_out if f['coint'])
    print(f"\n{label}: train {train} / test {test} bars, {len(folds_out)} folds, cointegrated in {n_coint}")
    print(f"   WF total {(E - 1) * 100:+.2f}%   Sharpe {sh:+.2f}   MDD {mdd * 100:.2f}%   trades {trades}")
    print(f"   folds with trades: {sum(1 for f in folds_out if f['trades'] > 0)}; per-fold returns: "
          + " ".join(f"{f['fold_ret'] * 100:+.2f}%" for f in folds_out if f['coint']))
    return folds_out


def main():
    times, sc, ac = load_closes()
    print(f"aligned hourly bars: {len(times)} from {datetime.fromtimestamp(times[0] / 1000, timezone.utc).date()} "
          f"to {datetime.fromtimestamp(times[-1] / 1000, timezone.utc).date()}")
    print("==================== SOL/AVAX pair, walk-forward, Engle-Granger gated ====================")
    run(times, sc, ac, train=2160, test=720, bpy=8760, label='1h')
    dt, ds, da = daily(times, sc, ac)
    run(dt, ds, da, train=365, test=91, bpy=365, label='1d')


if __name__ == '__main__':
    main()
