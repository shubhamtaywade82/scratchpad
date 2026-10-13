"""Delta-neutral funding carry, daily, four years.

Position while held: SHORT the perpetual (receives positive funding) and LONG spot, equal notional N.
  PnL per day (per unit notional) = funding received in the day  +  (spot return - perp return)  - costs at entry/exit

Data (no single venue has both legs over four years, so this is a cross-venue approximation). All prices are day OPENS:
  perp price and funding   Binance USD-M (repo: data/SOLUSDT-futures.json, data/SOLUSDT-intraday.json 1d)
  spot price               OKX SOL-USDT spot, open of each UTC day from the 1H candles
The tracking error between the two venues is measured and reported; a real hedge also faces it.

Costs: 4 fills x 5 bps per cycle = 20 bps of notional (entry: perp + spot; exit: perp + spot). Placeholder for fees.
Capital: 2N (no margin), so returns are shown per unit notional and per unit capital.

Usage: python3 -m research.carry_test
"""
import json
import math
import statistics as st
from datetime import datetime, timezone

from research.engine import load_funding, load_klines

DAY = 86_400_000
CYCLE_COST = 0.0020


def okx_spot_open_daily(path='data/okx/SOL-USDT-1H.json'):
    """Open price of each UTC day from OKX spot 1H candles (first candle of the day)."""
    rows = json.load(open(path))['rows']
    out = {}
    for r in sorted(rows, key=lambda r: r['t']):
        d = (r['t'] // DAY) * DAY
        if d not in out:
            out[d] = r['o']
    return out


def perp_open_daily():
    s = load_klines('1d')
    return {t: o for t, o in zip(s.t, s.o)}


def tracking(perp, spot):
    common = sorted(set(perp) & set(spot))
    pr = [perp[common[i]] / perp[common[i - 1]] - 1 for i in range(1, len(common))]
    sr = [spot[common[i]] / spot[common[i - 1]] - 1 for i in range(1, len(common))]
    diff = [a - b for a, b in zip(sr, pr)]
    corr = st.correlation(pr, sr)
    ann_te = st.pstdev(diff) * math.sqrt(365)
    return len(common), corr, ann_te, common


def carry(days, perp, spot, ft, fr, enter_thr: float, exit_thr: float):
    """Holding interval for day i is (open_i, open_{i+1}]. Funding inside it is received by the short perp.
    Entry and exit decisions use only the latest settlement at or before the day's open."""
    pnl = dict(funding=0.0, basis=0.0, cost=0.0)
    yearly = {}
    cycles = 0
    in_days = 0
    state = 0
    j = 0
    rate_now = None
    for i in range(len(days) - 1):
        d, d1 = days[i], days[i + 1]
        y = datetime.fromtimestamp(d / 1000, timezone.utc).year
        while j < len(ft) and ft[j] <= d:
            rate_now = fr[j]
            j += 1
        if rate_now is not None:
            if state == 0 and rate_now > enter_thr:
                state = 1
                cycles += 1
                pnl['cost'] -= CYCLE_COST / 2
                yearly[y] = yearly.get(y, 0.0) - CYCLE_COST / 2
            elif state == 1 and rate_now < exit_thr:
                state = 0
                pnl['cost'] -= CYCLE_COST / 2
                yearly[y] = yearly.get(y, 0.0) - CYCLE_COST / 2
        if state == 1:
            f = _sum_interval(ft, fr, d, d1)
            b = (spot[d1] / spot[d] - 1) - (perp[d1] / perp[d] - 1)
            pnl['funding'] += f
            pnl['basis'] += b
            yearly[y] = yearly.get(y, 0.0) + f + b
            in_days += 1
    years = (days[-1] - days[0]) / (365.25 * DAY)
    net = pnl['funding'] + pnl['basis'] + pnl['cost']
    return dict(pnl=pnl, net=net, per_year_notional=net / years, per_year_capital=net / years / 2,
                cycles=cycles, in_market=in_days / (len(days) - 1), yearly=yearly)


def _sum_interval(ft, fr, d, d1):
    """Sum of settlement rates with d < t <= d1 (bisect on the sorted settlement times)."""
    import bisect
    lo = bisect.bisect_right(ft, d)
    hi = bisect.bisect_right(ft, d1)
    return sum(fr[lo:hi])


def main():
    ft, fr = load_funding()
    perp = perp_open_daily()
    spot = okx_spot_open_daily()
    n, corr, te, common = tracking(perp, spot)
    print(f"tracking: {n} common days, daily return correlation perp(Binance) vs spot(OKX) = {corr:.4f}, "
          f"annualised tracking error = {te * 100:.2f}%")
    days = sorted(d for d in perp if d in spot)
    print(f"carry window: {datetime.fromtimestamp(days[0] / 1000, timezone.utc).date()} -> "
          f"{datetime.fromtimestamp(days[-1] / 1000, timezone.utc).date()}  ({len(days)} days)")
    print("always-short-perp, long-spot (no filter):")
    c0 = carry(days, perp, spot, ft, fr, enter_thr=-1.0, exit_thr=-1.0)
    print(f"   net {c0['net'] * 100:+.1f}% per notional ({c0['per_year_notional'] * 100:+.1f}%/yr), "
          f"funding {c0['pnl']['funding'] * 100:+.1f}%, basis {c0['pnl']['basis'] * 100:+.1f}%, cost {c0['pnl']['cost'] * 100:+.1f}%")
    print("conditional carry (enter when funding > enter, exit when funding < exit):")
    for enter, ex in [(0.0001, 0.0), (0.0003, 0.0001), (0.0005, 0.0001)]:
        c = carry(days, perp, spot, ft, fr, enter, ex)
        print(f"   enter > {enter * 100:.3f}%/8h, exit < {ex * 100:.3f}%/8h: net {c['net'] * 100:+.1f}% per notional, "
              f"{c['per_year_notional'] * 100:+.1f}%/yr per notional, {c['per_year_capital'] * 100:+.1f}%/yr per capital, "
              f"cycles {c['cycles']}, in market {c['in_market'] * 100:.0f}%")
        print(f"      funding {c['pnl']['funding'] * 100:+.1f}%  basis {c['pnl']['basis'] * 100:+.1f}%  "
              f"costs {c['pnl']['cost'] * 100:+.1f}%   by year (per notional): "
              + ", ".join(f"{y}: {v * 100:+.1f}%" for y, v in sorted(c['yearly'].items())))


if __name__ == '__main__':
    main()
