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

Robustness (for the one cell that looks profitable, and its neighbours):
  - k sweep, to see whether the result is a threshold artefact
  - block bootstrap (1-day blocks) of total return and Sharpe
  - sign-flip null: trade the opposite of the prediction. A real signal loses under the flip.
  - delay nulls: act one or two bars late. An edge that survives a 1-bar delay is slow-moving, not a lead.
  - cost sensitivity: 0, 4, 8, 12 bps per side.
Multiple testing: the headline grid is 4 feature sets x 2 thresholds, and the robustness grid adds more cells. The reported
p-values and intervals do not correct for that search.

Usage: python3 -m research.cross_asset
"""
import json
import math

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


def walk_forward(tf: str, kind: str):
    """Out-of-sample predictions for every test row, with the training-window residual sigma and the fold index."""
    cfg = CONFIGS[tf]
    t, ls, lb, le = load(tf)
    X, y = features(ls, lb, le, kind)
    n = len(y)
    train, test = cfg['train'], cfg['test']
    preds = np.full(n, np.nan)
    sig_tr = np.full(n, np.nan)
    fold = np.full(n, -1)
    start, f = train, 0
    while start + test <= n:
        Xtr = np.column_stack([np.ones(train), X[start - train:start]])
        ytr = y[start - train:start]
        beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
        s_res = float(np.std(ytr - Xtr @ beta))
        Xte = np.column_stack([np.ones(test), X[start:start + test]])
        preds[start:start + test] = Xte @ beta
        sig_tr[start:start + test] = s_res
        fold[start:start + test] = f
        start += test
        f += 1
    ok = ~np.isnan(preds)
    p, actual = preds[ok], y[ok]
    ss_res = float(np.sum((actual - p) ** 2))
    ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
    return dict(p=p, actual=actual, sig=sig_tr[ok], fold=fold[ok], bpy=cfg['bpy'], oos_r2=1 - ss_res / ss_tot)


def trade(wf, k=0.0, delay=0, flip=False, cost=COST):
    """Position decided on row i (from the prediction at close of interval i) is held over target row i + delay.
    delay=0 is the causal baseline. flip negates the position (sign-flip null). Costs are charged on every change."""
    p, actual, sig = wf['p'], wf['actual'], wf['sig']
    thr = k * sig
    pos = np.where(p > thr, 1, np.where(p < -thr, -1, 0))
    if flip:
        pos = -pos
    n = len(actual)
    held = np.zeros(n, dtype=int)
    if delay == 0:
        held[:] = pos
    elif delay < n:
        held[delay:] = pos[:n - delay]
    gross = held * actual
    turns = np.abs(np.diff(np.concatenate([[0], held])))
    net = gross - cost * turns
    return dict(held=held, gross=gross, net=net, turns=turns)


def round_trips(held, gross, cost=COST):
    """Runs of constant nonzero position. A run is a win when its gross P&L exceeds the two fills it costs."""
    runs = []
    i, n = 0, len(held)
    while i < n:
        if held[i] == 0:
            i += 1
            continue
        j = i
        while j < n and held[j] == held[i]:
            j += 1
        runs.append(float(np.sum(gross[i:j])) - 2 * cost)
        i = j
    return runs


def wilson(k, n, z=1.96):
    if n == 0:
        return float('nan'), float('nan')
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return centre - half, centre + half


def metrics(wf, tr):
    net, held, fold, bpy = tr['net'], tr['held'], wf['fold'], wf['bpy']
    eq = np.cumprod(1 + net)
    peak = np.maximum.accumulate(eq)
    sd = float(np.std(net)) or 1e-12
    runs = round_trips(held, tr['gross'])
    fold_ids = np.unique(fold)
    fold_rets = [float(np.prod(1 + net[fold == f]) - 1) for f in fold_ids]
    wins = sum(1 for r in runs if r > 0)
    return dict(oos_r2=wf['oos_r2'], net_tot=float(eq[-1] - 1), gross_tot=float(np.sum(tr['gross'])),
                sharpe=float(np.mean(net) / sd * math.sqrt(bpy)), mdd=float(np.min(eq / peak - 1)),
                round_trips=len(runs), wins=wins, rt_win_ci=wilson(wins, len(runs)),
                in_mkt=float(np.mean(held != 0)), folds_pos=sum(1 for r in fold_rets if r > 0),
                folds=len(fold_rets), fold_rets=fold_rets)


def block_bootstrap(net, bpy, block=24, B=2000, seed=4):
    """95% intervals for total return and annualised Sharpe, resampling contiguous blocks of `block` bars."""
    n = len(net)
    rnd = np.random.default_rng(seed)
    starts = np.arange(n - block + 1)
    nb = -(-n // block)
    tots, shs = [], []
    for _ in range(B):
        idx = np.concatenate([np.arange(s, s + block) for s in rnd.choice(starts, size=nb)])[:n]
        r = net[idx]
        tots.append(float(np.prod(1 + r) - 1))
        sd = float(np.std(r)) or 1e-12
        shs.append(float(np.mean(r) / sd * math.sqrt(bpy)))
    tots.sort()
    shs.sort()
    return (tots[int(0.025 * B)], tots[int(0.975 * B)]), (shs[int(0.025 * B)], shs[int(0.975 * B)])


def run(tf: str, kind: str, k: float):
    wf = walk_forward(tf, kind)
    return metrics(wf, trade(wf, k=k))


def headline(tf: str):
    print(f"\n==================== cross-asset return prediction, SOL, {tf} ====================")
    print(f"{'features':<8} {'k':>4} {'OOS R2':>9} {'net':>9} {'Sh net':>7} {'MDD':>8} {'RT':>5} {'RT win':>8} {'RT win 95% CI':>16} {'in mkt':>7}")
    for kind in ('OWN', 'CROSS', 'MARKET', 'ALL'):
        for k in (0.0, 0.5):
            m = run(tf, kind, k)
            lo, hi = m['rt_win_ci']
            win = (m['wins'] / m['round_trips'] * 100) if m['round_trips'] else float('nan')
            print(f"{kind:<8} {k:>4.1f} {m['oos_r2'] * 100:>+8.3f}% {m['net_tot'] * 100:>+8.1f}% {m['sharpe']:>+7.2f} "
                  f"{m['mdd'] * 100:>7.1f}% {m['round_trips']:>5d} {win:>7.1f}% {lo * 100:>6.1f} .. {hi * 100:>5.1f}% {m['in_mkt'] * 100:>6.1f}%")


def _report_thresholds(tf: str, kinds):
    print(f"\n--- {tf}: threshold sweep (k), total net return and Sharpe")
    print(f"{'features':<8} " + "  ".join(f"k={k:<4}" for k in (0.25, 0.5, 0.75, 1.0)))
    for kind in kinds:
        wf = walk_forward(tf, kind)
        cells = []
        for k in (0.25, 0.5, 0.75, 1.0):
            m = metrics(wf, trade(wf, k=k))
            cells.append(f"{m['net_tot'] * 100:+6.1f}% {m['sharpe']:+5.2f}")
        print(f"{kind:<8} " + "  ".join(cells))


def _report_nulls_and_costs(tf: str, kinds):
    print(f"\n--- {tf}: nulls and costs at k=0.5 (net total return / Sharpe)")
    print(f"{'features':<8} {'causal':>16} {'flip sign':>16} {'delay 1':>16} {'delay 2':>16}")
    for kind in kinds:
        wf = walk_forward(tf, kind)
        row = []
        for kw in (dict(), dict(flip=True), dict(delay=1), dict(delay=2)):
            m = metrics(wf, trade(wf, k=0.5, **kw))
            row.append(f"{m['net_tot'] * 100:+6.1f}% {m['sharpe']:+5.2f}")
        print(f"{kind:<8} " + "".join(f"{c:>17}" for c in row))

    print(f"\n--- {tf}: cost sensitivity at k=0.5, causal (net total return / Sharpe)")
    for kind in kinds:
        wf = walk_forward(tf, kind)
        row = []
        for c in (0.0, 0.0004, 0.0008, 0.0012):
            m = metrics(wf, trade(wf, k=0.5, cost=c))
            row.append(f"{c * 1e4:>2.0f} bps: {m['net_tot'] * 100:+6.1f}% {m['sharpe']:+5.2f}")
        print(f"{kind:<8} " + "   ".join(row))


def _report_detail(tf: str, kind: str):
    wf = walk_forward(tf, kind)
    m = metrics(wf, trade(wf, k=0.5))
    (tlo, thi), (slo, shi) = block_bootstrap(trade(wf, k=0.5)['net'], wf['bpy'])
    print(f"\n--- {tf}: {kind} k=0.5 causal, detail")
    print(f"   round trips {m['round_trips']}, winners {m['wins']}, "
          f"folds positive {m['folds_pos']} of {m['folds']}")
    print(f"   block bootstrap (1-day blocks, 2000 draws): total {tlo * 100:+.1f}% .. {thi * 100:+.1f}%,  "
          f"Sharpe {slo:+.2f} .. {shi:+.2f}")
    ranked = sorted(m['fold_rets'], reverse=True)
    ex_top3 = float(np.prod(1 + np.array(ranked[3:])) - 1)
    print(f"   best 3 folds: {' '.join(f'{r * 100:+.1f}%' for r in ranked[:3])}; total without them: {ex_top3 * 100:+.1f}%")


def robustness(tf: str, kinds=('CROSS', 'MARKET')):
    _report_thresholds(tf, kinds)
    _report_nulls_and_costs(tf, kinds)
    _report_detail(tf, kinds[0])


def main():
    for tf in ('1h', '15m'):
        try:
            t, *_ = load(tf)
        except FileNotFoundError as ex:
            print(f"{tf}: data missing ({ex.filename}); skipped")
            continue
        print(f"\n{tf}: {len(t)} aligned bars")
        headline(tf)
        robustness(tf)


if __name__ == '__main__':
    main()
