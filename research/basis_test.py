"""Basis trade on OKX SOL delivery futures against the OKX SOL-USDT perpetual.

Rule (pre-declared, from the proposal): when the future trades at an annualised premium of at least 15% to the perp and
at least 7 days remain, SHORT the future and LONG the perp; hold to settlement. Each contract is one opportunity.

  gross PnL (per notional) = -(F_exit / F_entry - 1) + (P_exit / P_entry - 1)
  costs = 4 fills x 5 bps = 20 bps per cycle (placeholder fee model)
  perp funding is NOT in the gross figure; an estimate is shown separately from Binance funding over the same window.

Assumptions to flag: delivery at 08:00 UTC on the expiry date (OKX convention, not verified here); settlement value taken as
the final candle's close.

Usage: python3 -m research.basis_test
"""
import bisect
import json
import os
from datetime import datetime, timezone

from research.okx_data import fetch_candles, save

HOUR = 3_600_000
DAY = 86_400_000
ENTRY_ANN = 0.15
MIN_DTE = 7.0
COST = 0.0020


def expiry_ms(inst: str) -> int:
    ymd = inst.split('-')[-1]
    d = datetime.strptime('20' + ymd, '%Y%m%d').replace(hour=8, tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def load_or_fetch(inst: str):
    path = f"data/okx/{inst}-1H.json"
    if os.path.exists(path):
        return json.load(open(path))['rows']
    rows = fetch_candles(inst, '1H', '2024-01-01')
    save(f"{inst}-1H.json", dict(instId=inst, bar='1H', since='2024-01-01', rows=rows))
    return rows


def run():
    perp = json.load(open('data/okx/SOL-USDT-SWAP-1H.json'))['rows']
    perp_t = [r['t'] for r in perp]
    perp_c = {r['t']: r['c'] for r in perp}
    fund = json.load(open('data/okx/SOL-USDT-SWAP-funding.json'))['rows']
    # Funding estimate: Binance SOL funding (repo) averaged over each window, applied to a long perp.
    from research.engine import load_funding
    ft, fr = load_funding()
    expiries = json.load(open('data/okx/expiries-SOL-USD.json'))['found']
    results = []
    for inst, status in expiries:
        rows = load_or_fetch(inst)
        if not rows:
            results.append((inst, 'no candles', None))
            continue
        exp = expiry_ms(inst)
        fut = {r['t']: r['c'] for r in rows}
        times = sorted(fut)
        entry = None
        for t in times:
            if t not in perp_c or t >= exp:
                continue
            dte = (exp - t) / DAY
            if dte < MIN_DTE:
                break
            ann = (fut[t] / perp_c[t] - 1) * 365 / dte
            if ann >= ENTRY_ANN:
                entry = (t, fut[t], perp_c[t], ann, dte)
                break
        if entry is None:
            results.append((inst, 'no entry (premium never >= 15% with 7+ days left)', None))
            continue
        t0, f0, p0, ann0, dte0 = entry
        last_t = max(t for t in times if t <= exp)
        f1, p1 = fut[last_t], perp_c.get(last_t)
        if p1 is None:
            results.append((inst, 'missing perp at exit', None))
            continue
        gross = -(f1 / f0 - 1) + (p1 / p0 - 1)
        net = gross - COST
        held_days = (last_t - t0) / DAY
        i0 = bisect.bisect_left(ft, t0)
        i1 = bisect.bisect_right(ft, last_t)
        fund_est = -sum(fr[i0:i1]) if i1 > i0 else 0.0           # long perp PAYS positive funding: a cost
        final_basis = f1 / p1 - 1
        results.append((inst, 'traded', dict(
            entry=datetime.fromtimestamp(t0 / 1000, timezone.utc).strftime('%Y-%m-%d %H:%M'),
            exit=datetime.fromtimestamp(last_t / 1000, timezone.utc).strftime('%Y-%m-%d %H:%M'),
            ann_entry=ann0, dte=dte0, held=held_days, gross=gross, net=net, fund_est=fund_est,
            net_after_funding=net + fund_est,
            final_basis=final_basis, status=status)))
    return results


def main():
    print("==================== basis trade: short OKX SOL delivery future, long OKX SOL-USDT perp ====================")
    print(f"rule: enter when annualised premium >= {ENTRY_ANN * 100:.0f}% with >= {MIN_DTE:.0f} days left; hold to settlement")
    print(f"{'contract':<22} {'result':<10} {'entry (UTC)':<17} {'ann prem':>9} {'dte':>5} {'held':>6} "
          f"{'gross':>8} {'net':>8} {'fund est':>9} {'net+fund':>9} {'basis@exp':>10}")
    traded = []
    for inst, what, d in run():
        if what != 'traded':
            print(f"{inst:<22} {what}")
            continue
        traded.append(d)
        print(f"{inst:<22} {'traded':<10} {d['entry']:<17} {d['ann_entry'] * 100:>+8.1f}% {d['dte']:>5.0f} {d['held']:>5.1f}d "
              f"{d['gross'] * 100:>+7.2f}% {d['net'] * 100:>+7.2f}% {d['fund_est'] * 100:>+8.2f}% "
              f"{d['net_after_funding'] * 100:>+8.2f}% {d['final_basis'] * 100:>+9.2f}%")
    if traded:
        import statistics as st
        print(f"\n{len(traded)} traded contracts: mean net {st.fmean(d['net'] for d in traded) * 100:+.2f}% per contract, "
              f"mean net after funding estimate {st.fmean(d['net_after_funding'] for d in traded) * 100:+.2f}%, "
              f"mean annualised premium at entry {st.fmean(d['ann_entry'] for d in traded) * 100:.1f}%, "
              f"basis at settlement |mean| {st.fmean(abs(d['final_basis']) for d in traded) * 100:.3f}%")
    else:
        print("\nNo contract met the entry rule.")


if __name__ == '__main__':
    main()
