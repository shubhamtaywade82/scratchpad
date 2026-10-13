"""Funding-rate tests for SOLUSDT, using settled funding history from data/SOLUSDT-futures.json.

1. Carry (delta-neutral sketch): short the perpetual, receive funding while it is positive.
   Spot leg, basis and spot fees are NOT in the data. The cost model charges 4 fills of 5 bps per cycle as a placeholder
   and says so in the output. The result is gross-of-basis: a real delta-neutral position also carries basis risk.
2. Funding mean reversion (directional): causal z-score of settled funding over a trailing window of events.
   z > +thr -> short (crowded longs pay, expect a squeeze down), z < -thr -> long. Exit when |z| < exit.
   Traded with the same engine, risk and walk-forward windows as the other tests.

Usage:  python3 -m research.funding
"""
import bisect
import statistics as st
import sys
from datetime import datetime, timezone

from research.engine import Risk, atr, load_funding, load_klines, metrics, returns_from_levels, simulate
from research.ideas import walk
from research.search import WINDOWS, block_bootstrap_sharpe

CYCLE_COST = 4 * 0.0005        # PLACEHOLDER: 4 fills x 5 bps per carry cycle (perp in/out, spot in/out). Spot fee not sourced.
PER_YEAR = 3 * 365             # settlements per year (8h)


def carry(ft, fr, thr: float, exit_thr: float):
    """Short the perp while funding > thr; exit when funding < exit_thr. Returns summary dict."""
    held, total, cycles, in_pos_events = False, 0.0, 0, 0
    per_year = {}
    for t, r in zip(ft, fr):
        y = datetime.fromtimestamp(t / 1000, timezone.utc).year
        if not held and r > thr:
            held = True
            cycles += 1
            total -= CYCLE_COST / 2             # charge entry half of the cycle cost now, exit half on close
            per_year.setdefault(y, 0.0)
            per_year[y] -= CYCLE_COST / 2
        if held:
            total += r                          # short perp RECEIVES positive funding
            per_year[y] = per_year.get(y, 0.0) + r
            in_pos_events += 1
            if r < exit_thr:
                held = False
                total -= CYCLE_COST / 2
                per_year[y] -= CYCLE_COST / 2
    years = (ft[-1] - ft[0]) / (365.25 * 86400e3)
    return dict(total=total, cagr=total / years, cycles=cycles, share_in=in_pos_events / len(fr),
                per_year=per_year)


def unconditional_short(ft, fr):
    total = sum(fr)
    years = (ft[-1] - ft[0]) / (365.25 * 86400e3)
    return total / years


def z_at_bars(s, ft, fr, window_events: int, robust: bool = False):
    """Causal z-score of the latest settled funding rate at each bar open. None until enough events exist.
    robust=False: mean / stdev. robust=True: median / (1.4826 x MAD). One extreme print (2022: -2%/8h) inflates the
    stdev for a long time, which blocks positive extremes from ever reaching the threshold; the robust form avoids that."""
    out = [None] * len(s)
    for k in range(len(s)):
        j = bisect.bisect_right(ft, s.t[k]) - 1          # latest settled event at or before the bar open
        if j < window_events:
            continue
        w = fr[j - window_events + 1:j + 1]
        if robust:
            med = st.median(w)
            mad = st.median(abs(x - med) for x in w) * 1.4826
            if mad == 0:
                continue
            out[k] = (fr[j] - med) / mad
        else:
            sd = st.pstdev(w)
            if sd == 0:
                continue
            out[k] = (fr[j] - st.fmean(w)) / sd
    return out


def mr_signal(z, thr: float, exit_thr: float):
    sig = [0] * len(z)
    pos = 0
    for k, v in enumerate(z):
        if v is None:
            continue
        if pos == 0:
            if v > thr:
                pos = -1
            elif v < -thr:
                pos = 1
        elif abs(v) < exit_thr:
            pos = 0
        elif pos == -1 and v < -thr:       # flip if the opposite extreme arrives
            pos = 1
        elif pos == 1 and v > thr:
            pos = -1
        sig[k] = pos
    return sig


def mr_cells(tf: str, ft, fr):
    s = load_klines(tf)
    out = []
    for robust in (False, True):
        for N in (90, 270):                 # trailing settlements: 30 days and 90 days
            z = z_at_bars(s, ft, fr, N, robust)
            for thr in (2.0, 2.5):
                tag = 'robust' if robust else 'stdev'
                out.append((f"{tag} z N{N} thr{thr:g}", mr_signal(z, thr, 0.5)))
    return out


def run_mr(tf: str, ft, fr, lev=5.0):
    s = load_klines(tf)
    print(f"\n==================== funding mean reversion (directional), {tf}, {lev:g}x, 1% risk, 3-ATR stop ====================")
    print(f"{'cell':<26} {'WF tot':>8} {'Sh':>6} {'MDD':>7} {'n':>4} {'L/S':>7} {'folds+':>6} {'flipped':>8}")
    rows = []
    for name, sig in mr_cells(tf, ft, fr):
        risk = Risk(sizing='risk', risk_pct=0.01, lev=lev, sl_mult=3.0)
        res, folds = walk(tf, s, sig, risk, None, ft, fr)
        m = metrics(res, tf)
        fres, _ = walk(tf, s, [-x for x in sig], risk, None, ft, fr)
        fm = metrics(fres, tf)
        rows.append((name, m, fm, folds))
        print(f"{name:<26} {m['total'] * 100:>+7.1f}% {m['sharpe']:>+6.2f} {m['mdd'] * 100:>6.1f}% {m['n']:>4} "
              f"{m['nl']}/{m['ns']:<5} {sum(f > 0 for f in folds)}/{len(folds):<4} {fm['total'] * 100:>+7.1f}%")
    pos = sum(1 for _, m, _, _ in rows if m['total'] > 0)
    print(f"-- {pos}/{len(rows)} cells positive WF OOS; flipped positive {sum(1 for _, _, fm, _ in rows if fm['total'] > 0)}/{len(rows)}")
    return rows


def main():
    ft, fr = load_funding()
    print("==================== funding carry: short perp while funding > threshold ====================")
    print(f"placeholder cycle cost {CYCLE_COST * 100:.2f}% (4 fills x 5 bps; spot fee unsourced); basis risk NOT modelled")
    print(f"always-short (no filter) annualised funding: {unconditional_short(ft, fr) * 100:+.1f}%/yr")
    for thr, ex in [(0.0001, 0.0), (0.0003, 0.0001), (0.0005, 0.0001)]:
        c = carry(ft, fr, thr, ex)
        yrs = (ft[-1] - ft[0]) / (365.25 * 86400e3)
        print(f"enter > {thr * 100:.3f}%/8h, exit < {ex * 100:.3f}%/8h: net {c['total'] * 100:+6.1f}% total, "
              f"{c['cagr'] * 100:+5.1f}%/yr, {c['cycles']} cycles, in market {c['share_in'] * 100:.0f}% of periods")
        print("   by year (net of placeholder costs):", ", ".join(f"{y}: {v * 100:+.1f}%" for y, v in sorted(c['per_year'].items())))
    print()
    for tf in ('4h', '1h'):
        run_mr(tf, ft, fr)


if __name__ == '__main__':
    main()
