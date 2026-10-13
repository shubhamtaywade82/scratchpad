"""Open-interest divergence, tested as conditional forward returns with t-statistics.

Each OI observation k gives a 2x2 category: price change sign over the OI step (up / down) and open-interest change sign
(up / down). The forward return is the next OI step's price change. The four categories are the message's table without
the funding column: funding history from OKX covers only about 100 days, so it cannot be conditioned on here.

Sample limits (OKX rubik window): 1H ~ 720 points (~30 days), 1D ~ 180 points. Both are reported as they are.

Usage: python3 -m research.oi_test
"""
import bisect
import json
import math
import statistics as st


def load_price_hourly():
    rows = json.load(open('data/okx/SOL-USDT-SWAP-1H.json'))['rows']
    return [r['t'] for r in rows], [r['c'] for r in rows]


def price_at(ts, price_t, price_c):
    """Close of the last hourly candle at or before ts (causal)."""
    j = bisect.bisect_right(price_t, ts) - 1
    return price_c[j] if j >= 0 else None


def categories(oi_rows, price_t, price_c):
    ts = [r['t'] for r in oi_rows]
    oi = [r['oi'] for r in oi_rows]
    px = [price_at(t, price_t, price_c) for t in ts]
    out = []
    for k in range(1, len(ts) - 1):
        if None in (px[k - 1], px[k], px[k + 1]):
            continue
        dp = px[k] / px[k - 1] - 1
        do = oi[k] / oi[k - 1] - 1
        fwd = px[k + 1] / px[k] - 1
        cat = ('P+' if dp > 0 else 'P-') + ('OI+' if do > 0 else 'OI-')
        out.append((cat, fwd))
    return out


def report(name, rows):
    base = [f for _, f in rows]
    mu0 = st.fmean(base)
    print(f"\n{name}: {len(rows)} steps, unconditional mean next-step return {mu0 * 100:+.3f}%")
    print(f"{'category':<10} {'N':>5} {'mean fwd':>10} {'t-stat':>8} {'vs uncond':>10}")
    for cat in ('P+OI+', 'P+OI-', 'P-OI+', 'P-OI-'):
        sub = [f for c, f in rows if c == cat]
        if len(sub) < 3:
            print(f"{cat:<10} {len(sub):>5}   too few observations")
            continue
        mu = st.fmean(sub)
        sd = st.stdev(sub)
        t = mu / (sd / math.sqrt(len(sub))) if sd > 0 else float('nan')
        print(f"{cat:<10} {len(sub):>5} {mu * 100:>+9.3f}% {t:>+8.2f} {(mu - mu0) * 100:>+9.3f}%")


def main():
    price_t, price_c = load_price_hourly()
    for period in ('1H', '1D'):
        oi = json.load(open(f'data/okx/oi-SOL-{period}.json'))['rows']
        report(f"OKX SOL OI {period}", categories(oi, price_t, price_c))
    print("\nA |t| below ~2 is not evidence of a directional pattern. Cells above have 40-180 observations.")


if __name__ == '__main__':
    main()
