"""Stop / trail sensitivity surface for fixed signals. The point is plateau-vs-spike, not picking a cell.

Usage:  python3 -m research.sensitivity
"""
import statistics as st
import math

from research.engine import Risk, atr, donchian_sig, ema_gate, load_funding, load_klines, metrics, simulate
from research.search import BPY, WINDOWS

SL = [2.0, 3.0, 4.0, 5.0]
TR = [None, 2.0, 3.0, 4.0, 5.0]


def surface(tf, n_chan, fund_t, fund_r):
    base = load_klines(tf)
    N = len(base)
    sig = donchian_sig(base, n_chan, gate=ema_gate(base, 200))
    A = atr(base, 14)
    train, test = WINDOWS[tf]
    print(f"\n{tf} DON{n_chan}+EMA200, risk 1%/trade, FULL-sample Sharpe | MDD | trades  (WF-OOS total in brackets)")
    print("sl \\ trail " + "".join(f"{str(t):>26}" for t in TR))
    for sl in SL:
        row = f"sl{sl:<10}"
        for tr in TR:
            risk = Risk(sizing='risk', risk_pct=0.01, sl_mult=sl, trail_mult=tr, max_gross=1.5)
            full = metrics(simulate(base, sig, risk, 1, N, A=A, fund_t=fund_t, fund_r=fund_r), tf)
            # walk-forward OOS, fixed config
            E, start, eq = 1.0, train, []
            while start + test <= N:
                r = simulate(base, sig, risk, start, start + test, A=A, fund_t=fund_t, fund_r=fund_r)
                E *= r.eq[-1]
                start += test
            wf_tot = E - 1
            row += f"  {full['sharpe']:+5.2f}|{full['mdd'] * 100:6.1f}|{full['n']:3d}[{wf_tot * 100:+6.1f}%]"
        print(row)


def long_short_and_bh(tf, n_chan, fund_t, fund_r):
    base = load_klines(tf)
    N = len(base)
    sig = donchian_sig(base, n_chan, gate=ema_gate(base, 200))
    risk = Risk(sizing='risk', risk_pct=0.01, sl_mult=4.0, trail_mult=4.0, max_gross=1.5)
    m = metrics(simulate(base, sig, risk, 1, N, A=atr(base, 14), fund_t=fund_t, fund_r=fund_r), tf)
    r = [math.log(base.c[i] / base.c[i - 1]) for i in range(1, N)]
    bh = st.fmean(r) / st.pstdev(r) * math.sqrt(BPY[tf])
    bh_tot = base.c[-1] / base.c[0] - 1
    print(f"\n{tf} DON{n_chan}+EMA200 sl4/tr4 risk1%: long n={m['nl']} avg {m['el'] * 100:+.2f}%/tr | "
          f"short n={m['ns']} avg {m['es'] * 100:+.2f}%/tr | Sh {m['sharpe']:+.2f} MDD {m['mdd'] * 100:.1f}%")
    print(f"{tf} buy&hold over same bars: total {bh_tot * 100:+.1f}%  Sh {bh:+.2f}")


if __name__ == '__main__':
    ft, fr = load_funding()
    surface('4h', 60, ft, fr)
    surface('4h', 40, ft, fr)
    long_short_and_bh('4h', 60, ft, fr)
    long_short_and_bh('1d', 40, ft, fr)


def candidate_folds(tf, n_chan, sl, tr, fund_t, fund_r):
    """Per-fold OOS for one fixed candidate, plus full-sample and bootstrap for the same config."""
    from research.search import block_bootstrap_sharpe
    base = load_klines(tf)
    N = len(base)
    sig = donchian_sig(base, n_chan, gate=ema_gate(base, 200))
    A = atr(base, 14)
    risk = Risk(sizing='risk', risk_pct=0.01, sl_mult=sl, trail_mult=tr, max_gross=1.5)
    train, test = WINDOWS[tf]
    E, start, all_eq = 1.0, train, [1.0]
    folds = []
    while start + test <= N:
        r = simulate(base, sig, risk, start, start + test, A=A, fund_t=fund_t, fund_r=fund_r)
        folds.append(r.eq[-1] - 1)
        all_eq.extend(E * v for v in r.eq)
        E *= r.eq[-1]
        start += test
    rets = [all_eq[i] / all_eq[i - 1] - 1 for i in range(1, len(all_eq))]
    lo, md, hi = block_bootstrap_sharpe(rets, BPY[tf], L=10 if tf == '1d' else 20)
    full = metrics(simulate(base, sig, risk, 1, N, A=A, fund_t=fund_t, fund_r=fund_r), tf)
    print(f"{tf} DON{n_chan}+EMA200 sl{sl}/tr{tr} risk1%: full Sh {full['sharpe']:+.2f} MDD {full['mdd'] * 100:.1f}% "
          f"n {full['n']} L {full['nl']}({full['el'] * 100:+.2f}%) S {full['ns']}({full['es'] * 100:+.2f}%) | "
          f"WF folds positive {sum(f > 0 for f in folds)}/{len(folds)}: " + " ".join(f"{f * 100:+.1f}%" for f in folds) +
          f" | WF total {(E - 1) * 100:+.1f}% | boot Sh 5/50/95 {lo:+.2f}/{md:+.2f}/{hi:+.2f}")
