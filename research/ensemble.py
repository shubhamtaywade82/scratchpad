"""Fixed (non-selected) designs with risk controls, evaluated on the same walk-forward folds.

Why: walk-forward selection of one config per fold is itself a source of noise (see search.py
output). A fixed design has no selection step, so its fold-by-fold results are a clean test of
whether the family has an edge at all, and risk-based sizing shows what drawdown it implies.

Designs are declared below BEFORE running; they are not tuned on these results.

Usage:  python3 -m research.ensemble 4h 1d 1h 15m
"""
import math
import statistics as st
import sys

from research.engine import (Result, Risk, atr, donchian_sig, ema_gate, htf_gate, load_funding,
                             load_klines, metrics, simulate)
from research.search import BPY, WINDOWS, block_bootstrap_sharpe

HTF_FOR = {'15m': '1h', '1h': '4h'}
VOTE_LENGTHS = {'15m': [96, 192, 384], '1h': [24, 48, 72, 120], '4h': [20, 40, 60, 80], '1d': [20, 40, 55, 80]}


def vote(sigs):
    """Majority vote of several -1/0/+1 target states. Ties resolve to flat (no hidden leverage)."""
    out = []
    for vals in zip(*sigs):
        s = sum(vals)
        out.append(1 if s > 0 else (-1 if s < 0 else 0))
    return out


def designs(tf, base, fund_loader):
    """Returns list of (name, sig, risk). Gate = EMA200 on the same timeframe, or MTF for intraday."""
    if tf in HTF_FOR:
        gate = htf_gate(base, load_klines(HTF_FOR[tf]), 200)
        gname = f"MTF {HTF_FOR[tf]} EMA200"
    else:
        gate = ema_gate(base, 200)
        gname = "EMA200"
    sigs = [donchian_sig(base, n, gate=gate) for n in VOTE_LENGTHS[tf]]
    ens = vote(sigs)
    out = []
    for rp in (0.01, 0.02):
        r = Risk(sizing='risk', risk_pct=rp, sl_mult=3.0, trail_mult=3.0, max_gross=1.5)
        out.append((f"VOTE{VOTE_LENGTHS[tf]} {gname} stop3 trail3 risk{int(rp * 100)}%", ens, r))
    single = donchian_sig(base, VOTE_LENGTHS[tf][len(VOTE_LENGTHS[tf]) // 2], gate=gate)
    out.append((f"single DON{VOTE_LENGTHS[tf][len(VOTE_LENGTHS[tf]) // 2]} {gname} stop3 trail3 risk1%", single,
                Risk(sizing='risk', risk_pct=0.01, sl_mult=3.0, trail_mult=3.0, max_gross=1.5)))
    return out


def walk_eval(tf, base, sig, risk, fund_t, fund_r):
    train, test = WINDOWS[tf]
    n = len(base)
    A = atr(base, 14)
    E = 1.0
    eq_all, pos_all, trades_all, folds = [], [], [], []
    start = train
    while start + test <= n:
        r = simulate(base, sig, risk, start, start + test, A=A, fund_t=fund_t, fund_r=fund_r)
        eq_all.extend(E * v for v in r.eq)
        E *= r.eq[-1]
        pos_all.extend(r.pos)
        trades_all.extend(r.trades)
        folds.append(r.eq[-1] - 1)
        start += test
    return Result(eq=eq_all, pos=pos_all, trades=trades_all), folds


def fmt(m):
    return (f"tot {m['total'] * 100:+7.1f}%  CAGR {m['cagr'] * 100:+6.1f}%  Sh {m['sharpe']:+5.2f}  "
            f"MDD {m['mdd'] * 100:6.1f}%  Calmar {m['calmar']:+5.2f}  n {m['n']:3d}  WR {m['wr'] * 100:4.1f}%  "
            f"PF {m['pf']:4.2f}  expo {m['exposure'] * 100:4.0f}%  stops {m['stops']}")


def run(tf, fund_t, fund_r):
    base = load_klines(tf)
    n = len(base)
    print(f"\n==================== {tf}: {n} bars ({n / BPY[tf] * 365:.0f} d) — FIXED designs, no selection ====================")
    cut = int(n * 0.6)
    for name, sig, risk in designs(tf, base, None):
        A = atr(base, 14)
        full = metrics(simulate(base, sig, risk, 1, n, A=A, fund_t=fund_t, fund_r=fund_r), tf)
        oos = metrics(simulate(base, sig, risk, cut, n, A=A, fund_t=fund_t, fund_r=fund_r), tf)
        res, folds = walk_eval(tf, base, sig, risk, fund_t, fund_r)
        wf = metrics(res, tf)
        rets = [res.eq[0] - 1.0] + [res.eq[i] / res.eq[i - 1] - 1 for i in range(1, len(res.eq))]
        lo, md, hi = block_bootstrap_sharpe(rets, BPY[tf], L=10 if tf == '1d' else 20)
        pos_folds = sum(1 for f in folds if f > 0)
        print(f"\n{name}")
        print(f"  FULL     {fmt(full)}")
        print(f"  OOS 40%  {fmt(oos)}")
        print(f"  WF OOS   {fmt(wf)}")
        print(f"           folds positive {pos_folds}/{len(folds)}: " + " ".join(f"{f * 100:+.1f}%" for f in folds))
        print(f"           block-bootstrap Sharpe 5/50/95: {lo:+.2f} / {md:+.2f} / {hi:+.2f}")


if __name__ == '__main__':
    ft, fr = load_funding()
    for tf in (sys.argv[1:] or ['4h', '1d']):
        run(tf, ft, fr)
