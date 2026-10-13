"""Null checks for the taker-absorption leads: does the result depend on direction and timing?

If the flipped-direction or time-delayed versions score as well as the original, the 'edge' is not a
directional property of aggressor flow and should not be traded.

Usage: python3 -m research.nulltest
"""
import statistics as st

from research.engine import Risk, delay_sig, load_funding, load_klines, metrics
from research.ideas import taker_absorb, walk

LEADS = [('1h', 6, 2.0, 4), ('4h', 18, 2.0, 4)]
DELAYS = [6, 12]   # causal delays only; advancing a signal would read future bars


def run(tf, sig, ft, fr):
    s = load_klines(tf)
    risk = Risk(sizing='risk', risk_pct=0.01, lev=10, sl_mult=3.0)
    res, folds = walk(tf, s, sig, risk, None, ft, fr)
    m = metrics(res, tf)
    return m['total'], m['sharpe'], m['n']


def main():
    ft, fr = load_funding()
    for tf, m_, th, T in LEADS:
        s = load_klines(tf)
        base = taker_absorb(s, m_, th, T)
        tot, sh, n = run(tf, base, ft, fr)
        print(f"\n{tf} taker-absorb m{m_} z{th} T{T}: original          WF {tot * 100:+6.1f}%  Sh {sh:+5.2f}  n {n}")
        flipped = [-x for x in base]
        tot, sh, n = run(tf, flipped, ft, fr)
        print(f"{tf} taker-absorb m{m_} z{th} T{T}: direction flipped  WF {tot * 100:+6.1f}%  Sh {sh:+5.2f}  n {n}")
        for d in DELAYS:
            tot, sh, n = run(tf, delay_sig(base, d), ft, fr)
            print(f"{tf} taker-absorb m{m_} z{th} T{T}: delayed {d:2d} bars  WF {tot * 100:+6.1f}%  Sh {sh:+5.2f}  n {n}")


if __name__ == '__main__':
    main()
