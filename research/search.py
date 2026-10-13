"""Walk-forward search over trend families on SOLUSDT USD-M perpetuals.

Protocol (no parameter ever sees the bars it is scored on):
  * Indicators are causal and computed once on the full series.
  * Each fold: every config is simulated on the TRAIN window only; the best train Sharpe
    (with >= MIN_TRADES trades) is selected, then traded on the following TEST window.
    Each fold starts and ends flat.
  * Stitched OOS equity = fold equity curves chained multiplicatively.
  * Block-bootstrap CI on the stitched per-bar returns.
  * Reported for comparison: the v4 baseline (fixed a priori config) and the full-sample
    in-sample best config (optimistic; shows the size of the selection bias).

Usage:  python3 -m research.search 4h 1d 1h 15m
"""
import math
import random
import statistics as st
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional

from research.engine import (FEE, SLIP, Result, Risk, atr, donchian_sig, ema_gate, htf_gate, returns_from_levels,
                             load_funding, load_klines, metrics, simulate, supertrend_sig,
                             tsmom_sig)

MIN_TRADES = 3
CUT = 0.6                                  # v4 split, used only for the comparison table
WINDOWS = {                                # (train bars, test bars) per timeframe
    '15m': (1440, 720),                    # 15 d / 7.5 d
    '1h': (720, 360),                      # 30 d / 15 d
    '4h': (720, 360),                      # 120 d / 60 d
    '1d': (365, 182),                      # 1 y / 6 m
}
DON_N = {'15m': [48, 96, 192, 384], '1h': [24, 48, 72, 120], '4h': [20, 30, 40, 60, 80], '1d': [20, 40, 55, 80, 120]}
TSMOM_L = {'15m': [96, 288, 672], '1h': [24, 72, 168], '4h': [30, 60, 120, 240], '1d': [20, 60, 120, 200]}
HTF_FOR = {'15m': '1h', '1h': '4h'}        # intraday trend gate source


@dataclass
class Cfg:
    name: str
    sig: List[int]
    risk: Risk
    family: str


def build_configs(tf: str, base, load: Callable[[str], object]) -> List[Cfg]:
    gates = {'none': None}
    for L in (100, 200):
        gates[f'ema{L}'] = ema_gate(base, L)
    if tf in HTF_FOR:
        gates[f'mtf-{HTF_FOR[tf]}-ema200'] = htf_gate(base, load(HTF_FOR[tf]), 200)
    cfgs: List[Cfg] = []
    for n in DON_N[tf]:
        for exit_kind in ('mid', 'half'):
            exit_n = None if exit_kind == 'mid' else max(2, n // 2)
            for gname, g in gates.items():
                sig = donchian_sig(base, n, exit_n=exit_n, gate=g)
                for sl in (None, 2.0, 3.0):
                    for tr in (None, 3.0):
                        nm = f"DON{n}/{exit_kind}/{gname}/sl{sl}/tr{tr}"
                        cfgs.append(Cfg(nm, sig, Risk(sl_mult=sl, trail_mult=tr), 'DON'))
    for p in (10, 20):
        for m in (2.0, 3.0, 4.0):
            sig = supertrend_sig(base, p, m)
            for sl in (None, 3.0):
                cfgs.append(Cfg(f"ST{p}x{m}/sl{sl}", sig, Risk(sl_mult=sl), 'ST'))
    for L in TSMOM_L[tf]:
        sig = tsmom_sig(base, L)
        for sl in (None, 3.0):
            cfgs.append(Cfg(f"TSMOM{L}/sl{sl}", sig, Risk(sl_mult=sl), 'TSMOM'))
    return cfgs


def block_bootstrap_sharpe(rets: List[float], bpy: int, B: int = 1000, L: int = 20, seed: int = 7):
    rnd = random.Random(seed)
    m = len(rets)
    out = []
    for _ in range(B):
        s: List[float] = []
        while len(s) < m:
            i0 = rnd.randrange(m)
            s.extend(rets[i0:i0 + L])
        s = s[:m]
        sd = st.pstdev(s) or 1e-12
        out.append(st.fmean(s) / sd * math.sqrt(bpy))
    out.sort()
    return out[int(.05 * B)], out[int(.5 * B)], out[int(.95 * B)]


def walk_forward(tf: str, base, cfgs: List[Cfg], fund_t, fund_r, train: int, test: int):
    n = len(base)
    A = atr(base, 14)
    E = 1.0
    eq_all: List[float] = []
    pos_all: List[int] = []
    trades_all: List[dict] = []
    folds = []
    start = train
    while start + test <= n:
        best = None
        for c in cfgs:
            r = simulate(base, c.sig, c.risk, max(1, start - train), start, A=A, fund_t=fund_t, fund_r=fund_r)
            m = metrics(r, tf)
            if m['n'] < MIN_TRADES:
                continue
            if best is None or m['sharpe'] > best[1]['sharpe']:
                best = (c, m)
        if best is None:
            r = simulate(base, [0] * n, Risk(), start, start + test, A=A)
            chosen = 'FLAT (no config met MIN_TRADES in train)'
        else:
            chosen = best[0].name
            r = simulate(base, best[0].sig, best[0].risk, start, start + test, A=A, fund_t=fund_t, fund_r=fund_r)
        m_oos = metrics(r, tf)
        eq_all.extend(E * v for v in r.eq)
        E = E * r.eq[-1]
        pos_all.extend(r.pos)
        trades_all.extend(r.trades)
        folds.append(dict(start=start, end=start + test, chosen=chosen,
                          train_sharpe=best[1]['sharpe'] if best else float('nan'),
                          oos_total=m_oos['total'], oos_sharpe=m_oos['sharpe'], oos_n=m_oos['n']))
        start += test
    return Result(eq=eq_all, pos=pos_all, trades=trades_all), folds


def stitched_report(tf: str, res: Result):
    m = metrics(res, tf)
    rets = returns_from_levels(res.eq)
    lo, md, hi = block_bootstrap_sharpe(rets, BPY[tf], L=10 if tf == '1d' else 20)
    return m, (lo, md, hi)


BPY = {'15m': 35040, '1h': 8760, '4h': 2190, '1d': 365}


def fmt(m):
    return (f"tot {m['total'] * 100:+7.1f}%  CAGR {m['cagr'] * 100:+6.1f}%  Sh {m['sharpe']:+5.2f}  "
            f"MDD {m['mdd'] * 100:6.1f}%  Calmar {m['calmar']:+5.2f}  n {m['n']:3d}  WR {m['wr'] * 100:4.1f}%  "
            f"PF {m['pf']:4.2f}  exp {m['exp'] * 100:+.2f}%/tr  expo {m['exposure'] * 100:4.0f}%  "
            f"L {m['nl']}({m['el'] * 100:+.2f}%) S {m['ns']}({m['es'] * 100:+.2f}%)")


def run(tf: str, fund_t, fund_r):
    base = load_klines(tf)
    load = lambda t: load_klines(t)
    cfgs = build_configs(tf, base, load)
    train, test = WINDOWS[tf]
    n = len(base)
    print(f"\n==================== {tf}: {n} bars ({n / BPY[tf] * 365:.0f} d), {len(cfgs)} configs ====================")

    # 1. walk-forward
    res, folds = walk_forward(tf, base, cfgs, fund_t, fund_r, train, test)
    m, (lo, md, hi) = stitched_report(tf, res)
    print(f"[WF OOS] {len(folds)} folds x {test} bars  {fmt(m)}")
    print(f"         block-bootstrap OOS Sharpe 5/50/95: {lo:+.2f} / {md:+.2f} / {hi:+.2f}")
    for f in folds:
        print(f"         fold {f['start']:>5}-{f['end']:<5} train_Sh {f['train_sharpe']:+5.2f}  "
              f"oos {f['oos_total'] * 100:+6.1f}% Sh {f['oos_sharpe']:+5.2f} n {f['oos_n']:2d}  {f['chosen']}")

    # 2. in-sample best over the full sample (optimistic, shows selection bias)
    best_full = None
    for c in cfgs:
        r = simulate(base, c.sig, c.risk, 1, n, A=atr(base, 14), fund_t=fund_t, fund_r=fund_r)
        mm = metrics(r, tf)
        if mm['n'] >= MIN_TRADES and (best_full is None or mm['sharpe'] > best_full[1]['sharpe']):
            best_full = (c, mm)
    if best_full:
        print(f"[IS best, full sample, OPTIMISTIC] {best_full[0].name}: {fmt(best_full[1])}")

    # 3. v4 baseline, a priori (not searched): 4h/1d Donchian40 with EMA200 gate, no stop
    if tf in ('4h', '1d'):
        c = Cfg('v4 DON40+EMA200 nostop', donchian_sig(base, 40, gate=ema_gate(base, 200)), Risk(), 'DON')
        cut = int(n * CUT)
        full = metrics(simulate(base, c.sig, c.risk, 1, n, A=atr(base, 14), fund_t=fund_t, fund_r=fund_r), tf)
        oos = metrics(simulate(base, c.sig, c.risk, cut, n, A=atr(base, 14), fund_t=fund_t, fund_r=fund_r), tf)
        print(f"[v4 baseline full] {fmt(full)}")
        print(f"[v4 baseline OOS ] {fmt(oos)}")

    # 4. gross (no fee/slip/funding) on the in-sample best: is there any pre-cost edge?
    if best_full:
        c = best_full[0]
        g = metrics(simulate(base, c.sig, c.risk, 1, n, A=atr(base, 14), fee=0.0, slip=0.0), tf)
        print(f"[gross, zero cost, IS best] n {g['n']}  exp/tr {g['exp'] * 100:+.3f}%  total {g['total'] * 100:+.1f}%  Sh {g['sharpe']:+.2f}")
    return res, folds, m


if __name__ == '__main__':
    tfs = sys.argv[1:] or ['4h', '1d']
    ft, fr = load_funding()
    for tf in tfs:
        run(tf, ft, fr)
