"""How should the trailing rule engine work? Fixed exit rules (no selection) on the v13 survivors, traded on the
1m path so stops, locks and trails fire in true minute order. Also replays crypto-trading-agent's
TrailingStopManager tiers (lock_steps) against chandelier / giveback / fixed-target alternatives.

Usage: python3 -m research.exit_study   -> research/results/v13-exits.txt
"""
from multiprocessing import Pool

from research import binance_1m as b1m
from research.engine import Risk, Series, atr, metrics, simulate, tsmom_sig
from research.multi_asset import ALTS, DAYS, LEV, RESULTS, load_htf, to_1m, trade_table, zarattini_sig

AGENT_TIERS = ((1.0, 0.0), (1.5, 0.5), (2.0, 1.0), (3.0, 2.0))
EXITS = {
    'E0 stop 2ATR only': dict(sl_mult=2.0),
    'E1 chandelier 3ATR after 1R': dict(sl_mult=2.0, trail_mult=3.0, trail_act_r=1.0),
    'E2 E1 + tighten to 1.5ATR past 3R': dict(sl_mult=2.0, trail_mult=3.0, trail_act_r=1.0,
                                              trail_tight_r=3.0, trail_tight_mult=1.5),
    'E3 E2 + scale 50% at 2R': dict(sl_mult=2.0, trail_mult=3.0, trail_act_r=1.0, trail_tight_r=3.0,
                                    trail_tight_mult=1.5, tp_r=2.0, tp_frac=0.5),
    'E4 agent tiers + 1.5ATR trail past 2R': dict(sl_mult=2.0, lock_steps=AGENT_TIERS, trail_mult=1.5, trail_act_r=2.0),
    'E5 giveback 40% after 1R': dict(sl_mult=2.0, giveback=0.4, trail_act_r=1.0),
    'E6 fixed TP 2R': dict(sl_mult=2.0, tp_r=2.0),
}
STRATEGIES = {('1d', 'DONENS'): lambda s: zarattini_sig(s, [5, 10, 20, 30, 60, 90]),
              ('4h', 'DONENS'): lambda s: zarattini_sig(s, [n * 6 for n in (5, 10, 20, 30, 60, 90)]),
              ('1d', 'TSMOM L10d'): lambda s: tsmom_sig(s, 10),
              ('4h', 'TSMOM L10d'): lambda s: tsmom_sig(s, 60)}


def run_alt(alt: str) -> list:
    cols = b1m.load_1m(alt)
    m1 = Series('1m', cols['t'], cols['o'], cols['h'], cols['l'], cols['c'])
    fund = b1m.load_funding(alt)
    out = []
    for (tf, name), build in STRATEGIES.items():
        s = load_htf(alt)[tf]
        sig, a = build(s), atr(s, 14)
        sig1m, a1m = [x or 0 for x in to_1m(sig, s, m1.t)], to_1m(a, s, m1.t)
        start = s.t[200]  # skip indicator warm-up
        i0 = next(i for i, t in enumerate(m1.t) if t >= start)
        for ex, kw in EXITS.items():
            risk = Risk(sizing='risk', lev=LEV[tf], risk_pct=0.01, **kw)
            htf = simulate(s, sig, risk, 200, len(s), A=a, fund_t=fund[0], fund_r=fund[1])
            one = simulate(m1, sig1m, risk, i0, len(m1), A=a1m, fund_t=fund[0], fund_r=fund[1])
            # keep a summary only: 28 minute-equity curves per process exhausted RAM on the first run
            out.append((alt, tf, name, ex, metrics(htf, tf), dict(ret=one.eq[-1] - 1, mdd=min_dd(one.eq), trades=one.trades)))
    return out


def main():
    with Pool(2) as pool:
        rows = [r for part in pool.map(run_alt, ALTS) for r in part]
    lines = ['v13 exit study: fixed rules, no selection, 1% risk/trade, full sample after warm-up (2021-2026). '
             'HTF = bar-level exits, 1m = minute-path exits (the honest number).']
    for (tf, name) in STRATEGIES:
        lines.append(f'\n==================== {tf} {name} ====================')
        for alt, t, n, ex, mh, one in rows:
            if (t, n) != (tf, name):
                continue
            lines.append(f'{alt} {ex:40s} HTF tot {mh["total"] * 100:+7.1f}%  |  1m tot {one["ret"] * 100:+7.1f}%  '
                         f'MDD {one["mdd"] * 100:6.1f}%  n {len(one["trades"])}')
            lines.append(trade_table(one['trades']))
    text = '\n'.join(lines) + '\n'
    (RESULTS / 'v13-exits.txt').write_text(text)
    print(text)


def min_dd(eq: list) -> float:
    peak, mdd = 1.0, 0.0
    for v in eq[::60]:  # hourly sampling of the minute equity is enough for drawdown
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd


if __name__ == '__main__':
    main()
