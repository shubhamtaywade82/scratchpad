"""Cross-asset return prediction for SOL: can lagged BTC / ETH returns predict SOL's next-bar return out of sample?

Target: SOL log return over the next bar (r_{t+1}). Every feature at bar t uses bars <= t only.
Model: OLS with intercept, fitted on a rolling training window, applied to the next test window (walk-forward).
Trading rule (pre-declared): position = sign(prediction), or flat when |prediction| < k * sigma_train (k = 0 or 0.5).
Costs: 8 bps per side (5 bps taker + 3 bps slippage), charged on every change of position. 16 bps per round trip.

Feature sets (the report's list, made concrete):
  OWN      SOL return at t and t-1                    (SOL's own lagged information)
  CROSS    BTC and ETH returns at t and t-1           (the cross-asset idea)
  MARKET   mean of BTC and ETH returns, t and t-1     (broad crypto state)
  ALL      OWN + CROSS

Frequencies: 1h (train 2160 bars = 90 days, test 720 = 30 days) on OKX data 2022-2026, and 15m (train 2880 bars = 30 days,
test 1440 = 15 days) on OKX data from 2025-04. The 10-minute spillover reported by Guo et al. (2024) is only testable at 15m.

Usage: python3 -m research.cross_asset
"""
import json
import math
import statistics as st
import sys

import numpy as np

COST = 0.0008        # per side
CONFIGS = {'1h': dict(train=2160, test=720, bpy=8760), '15m': dict(train=2880, test=1440, bpy=35040)}


def load(tf: str):
    def closes(inst):
        rows = json.load(open(f'data/okx/{inst}-{"1H" if tf == "1h" else "15m"}.json'))['rows']
        return {r['t']: r['c'] for r in rows}
    s = closes('SOL-USDT-SWAP')
    b = closes('BTC-USDT-SWAP')
    e = closes('ETH-USDT-SWAP')
    common = sorted(set(s) & set(b) & set(e))
    if tf == '15m':
        common = [t for t in common if t >= 1743465600000]          # from 2025-04-01
    ls = np.log([s[t] for t in common])
    lb = np.log([b[t] for t in common])
    le = np.log([e[t] for t in common])
    return common, ls, lb, le


def features(ls, lb, le, kind):
    """Row j uses the CURRENT interval j and the LAG interval j-1 as features (known at close of interval j),
    and TARGETS the NEXT interval j+1. Feature and target never share an interval."""
    r_s = np.diff(ls)
    r_b = np.diff(lb)
    r_e = np.diff(le)
    r_m = (r_b + r_e) / 2
    M = len(r_s)
    cur = slice(1, M - 1)
    lag = slice(0, M - 2)
    tgt = slice(2, M)
    cols = []
    if kind in ('OWN', 'ALL'):
        cols += [r_s[cur], r_s[lag]]
    if kind in ('CROSS', 'ALL'):
        cols += [r_b[cur], r_b[lag], r_e[cur], r_e[lag]]
    if kind == 'MARKET':
        cols += [r_m[cur], r_m[lag]]
    X = np.column_stack(cols)
    y = r_s[tgt]
    return X, y


def run(tf: str, kind: str, k: float):
    cfg = CONFIGS[tf]
    t, ls, lb, le = load(tf)
    X, y = features(ls, lb, le, kind)
    n = len(y)
    train, test = cfg['train'], cfg['test']
    preds = np.full(n, np.nan)
    sig_tr = np.full(n, np.nan)
    start = train
    while start + test <= n:
        Xtr = np.column_stack([np.ones(train), X[start - train:start]])
        ytr = y[start - train:start]
        beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
        in_sample = Xtr @ beta
        s_res = float(np.std(ytr - in_sample))
        Xte = np.column_stack([np.ones(test), X[start:start + test]])
        preds[start:start + test] = Xte @ beta
        sig_tr[start:start + test] = s_res
        start += test
    ok = ~np.isnan(preds)
    p = preds[ok]
    actual = y[ok]
    thr = k * sig_tr[ok]
    pos = np.where(p > thr, 1, np.where(p < -thr, -1, 0))
    gross = pos * actual
    turns = np.abs(np.diff(np.concatenate([[0], pos])))
    net = gross - COST * turns
    hit = float(np.mean(np.sign(p[pos != 0]) == np.sign(actual[pos != 0]))) if np.any(pos != 0) else float('nan')
    ss_res = float(np.sum((actual - p) ** 2))
    ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
    oos_r2 = 1 - ss_res / ss_tot
    sd = float(np.std(net)) or 1e-12
    sh = float(np.mean(net) / sd * math.sqrt(cfg['bpy']))
    eq = np.cumprod(1 + net)
    peak = np.maximum.accumulate(eq)
    mdd = float(np.min(eq / peak - 1))
    return dict(oos_r2=oos_r2, hit=hit, gross_tot=float(np.sum(gross)), net_tot=float(np.exp(np.sum(np.log1p(net))) - 1),
                sharpe=sh, mdd=mdd, trades=int(np.sum(turns > 0)), in_mkt=float(np.mean(pos != 0)), n=int(len(actual)))


def main():
    for tf in ('1h', '15m'):
        try:
            load(tf)
        except FileNotFoundError as ex:
            print(f"{tf}: data missing ({ex.filename}); skipped")
            continue
        t, *_ = load(tf)
        print(f"\n==================== cross-asset return prediction, SOL, {tf}: {len(t)} aligned bars ====================")
        print(f"{'features':<8} {'k':>4} {'OOS R2':>9} {'hit':>7} {'gross':>9} {'net':>9} {'Sh net':>7} {'MDD':>8} {'trades':>7} {'in mkt':>7}")
        for kind in ('OWN', 'CROSS', 'MARKET', 'ALL'):
            for k in (0.0, 0.5):
                r = run(tf, kind, k)
                print(f"{kind:<8} {k:>4.1f} {r['oos_r2'] * 100:>+8.3f}% {r['hit'] * 100:>6.1f}% {r['gross_tot'] * 100:>+8.1f}% "
                      f"{r['net_tot'] * 100:>+8.1f}% {r['sharpe']:>+7.2f} {r['mdd'] * 100:>7.1f}% {r['trades']:>7d} {r['in_mkt'] * 100:>6.0f}%")


if __name__ == '__main__':
    main()
