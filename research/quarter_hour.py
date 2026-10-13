"""Quarter-hour order-flow hypothesis (Kim & Hansen, arXiv 2607.09426) on Binance SOLUSDT 15m bars in the repo.

Feature (known at the close of the bar): normalised signed taker imbalance  imb = (2 * takerBuy - volume) / volume.
Event A: bars that OPEN on a quarter-hour boundary (:00, :15, :30, :45 UTC).   Control B: all other 15m bars.
Target: the sum of log returns over the NEXT 4 hours (16 bars) and the next 12 hours (48 bars).
Test: correlation between imb and the forward return; 95% intervals from a day-block bootstrap (events in the same day
are correlated, so resampling individual events would overstate precision).

The sample is 73 days (~70 boundary days). A placebo test: if non-boundary bars show the same relation, the "boundary"
explanation is not supported. Taker imbalance is the report's proposed feature; it is not the paper's exact measure.

Usage: python3 -m research.quarter_hour
"""
import math
import random
import statistics as st
from datetime import datetime, timezone

from research.engine import load_klines


def corr(x, y):
    mx, my = st.fmean(x), st.fmean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else float('nan')


def events(s, horizon, boundary: bool):
    """Rows (day, imb, forward_return) for bars whose open time is on a quarter-hour boundary (or not)."""
    rows = []
    N = len(s)
    for k in range(N - horizon - 1):
        t = s.t[k]
        minute = (t // 60_000) % 60
        on = minute % 15 == 0
        if on != boundary:
            continue
        v = s.v[k]
        if v <= 0:
            continue
        imb = (2 * s.tb[k] - v) / v
        fwd = math.log(s.c[k + horizon] / s.c[k])          # close of bar k -> close of bar k+horizon
        day = datetime.fromtimestamp(t / 1000, timezone.utc).date()
        rows.append((day, imb, fwd))
    return rows


def block_ci(rows, B=2000, seed=1):
    days = sorted({d for d, _, _ in rows})
    by = {d: [] for d in days}
    for d, x, y in rows:
        by[d].append((x, y))
    rnd = random.Random(seed)
    out = []
    for _ in range(B):
        sample = [rnd.choice(days) for _ in days]
        xs, ys = [], []
        for d in sample:
            for x, y in by[d]:
                xs.append(x)
                ys.append(y)
        out.append(corr(xs, ys))
    out = [v for v in out if not math.isnan(v)]
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out))]


def volume_bursts(path='data/okx/SOL-USDT-SWAP-5m.json', B=2000, seed=2):
    """OKX SOL-USDT-SWAP 5m candles. Boundary bars = the 5m bars that open on :00, :15, :30, :45.
    Compares mean volume and mean absolute log return of boundary bars against all other 5m bars, with a day-block
    bootstrap on the ratio. OKX candles carry no buy/sell split, so the imbalance part of the paper cannot be tested here."""
    import json
    rows = json.load(open(path))['rows']
    rows.sort(key=lambda r: r['t'])
    days = {}
    for i in range(1, len(rows)):
        t = rows[i]['t']
        minute = (t // 60_000) % 60
        d = datetime.fromtimestamp(t / 1000, timezone.utc).date()
        v = rows[i]['volCcy']
        ar = abs(math.log(rows[i]['c'] / rows[i - 1]['c']))
        on = minute % 15 == 0
        days.setdefault(d, []).append((on, v, ar))
    all_days = sorted(days)
    def ratio(sample_days):
        bv = [v for d in sample_days for on, v, _ in days[d] if on]
        ov = [v for d in sample_days for on, v, _ in days[d] if not on]
        br = [a for d in sample_days for on, _, a in days[d] if on]
        orr = [a for d in sample_days for on, _, a in days[d] if not on]
        return st.fmean(bv) / st.fmean(ov), st.fmean(br) / st.fmean(orr)
    vr, rr = ratio(all_days)
    rnd = random.Random(seed)
    boots_v, boots_r = [], []
    for _ in range(B):
        samp = [rnd.choice(all_days) for _ in all_days]
        a, b = ratio(samp)
        boots_v.append(a)
        boots_r.append(b)
    boots_v.sort()
    boots_r.sort()
    n_on = sum(1 for d in all_days for on, _, _ in days[d] if on)
    print(f"OKX SOL 5m: {len(rows)} bars, {len(all_days)} days, {n_on} boundary bars")
    print(f"   volume ratio (boundary / other): {vr:.3f}   day-block 95% CI {boots_v[int(0.025 * B)]:.3f} .. {boots_v[int(0.975 * B)]:.3f}")
    print(f"   |return| ratio (boundary / other): {rr:.3f}   day-block 95% CI {boots_r[int(0.025 * B)]:.3f} .. {boots_r[int(0.975 * B)]:.3f}")


def main():
    s = load_klines('15m')
    print(f"Binance SOLUSDT 15m: {len(s)} bars, taker volume present: {s.tb is not None}")
    print("Part 1: taker imbalance vs forward returns, all 15m bars.")
    print("        (every 15m bar opens on a quarter-hour mark, so a boundary/placebo split is not possible at this frequency)")
    print(f"{'set':<22} {'horizon':>8} {'events':>7} {'corr(imb, fwd)':>15} {'day-block 95% CI':>20}")
    for hname, h in [('4h', 16), ('12h', 48)]:
        rows = events(s, h, True) + events(s, h, False)
        xs = [x for _, x, _ in rows]
        ys = [y for _, _, y in rows]
        r = corr(xs, ys)
        lo, hi = block_ci(rows)
        sig = 'excludes 0' if lo > 0 or hi < 0 else 'includes 0'
        print(f"{'all 15m bars':<22} {hname:>8} {len(rows):>7} {r:>+15.4f} {lo:>+9.4f} .. {hi:>+7.4f}  ({sig})")
    print("\nPart 2: volume and volatility bursts at quarter-hour boundaries (5m bars, OKX; no buy/sell split).")
    try:
        volume_bursts()
    except FileNotFoundError:
        print("   5m data not available")


if __name__ == '__main__':
    main()
