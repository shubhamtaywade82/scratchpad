"""Scale-out grid on the 4h Donchian(40) + EMA200 entry (the v5 primary swing system).

Grid (all with a 3-ATR initial stop, 5x margin ceiling, risk 1% per trade, walk-forward OOS):
  target  1R, 1.5R, 2R, 3R           fraction closed at target  25%, 50%, 75%
  breakeven after 1R   off / on      trail for the remainder   off / 3-ATR chandelier after 1R

Baseline: stop plus signal flip, no scale-out.
Reported with breadth (how many variants beat the baseline) so a single winning cell is not read as a finding.

Usage:  python3 -m research.scaleout
"""
import statistics as st

from research.engine import donchian_sig, ema_gate, load_funding, load_klines
from research.exits import run_cell

TP_R = [1.0, 1.5, 2.0, 3.0]
FRACS = [0.25, 0.5, 0.75]
BE = [None, 1.0]
TRAIL = [None, 3.0]


def main():
    ft, fr = load_funding()
    s = load_klines('4h')
    sig = donchian_sig(s, 40, gate=ema_gate(s, 200))

    base = run_cell('4h', sig, 'baseline', None, 0.0, None, None, 1.0, ft, fr)
    bm = base['m']
    base_folds_pos = sum(f > 0 for f in base['folds'])
    print("==================== 4h Donchian(40) + EMA200 scale-out grid | 5x, risk 1%, initial stop 3 ATR ====================")
    print(f"{'variant':<46} {'WF tot':>8} {'Sh':>6} {'MDD':>7} {'Calmar':>7} {'pos':>4} {'win%':>5} {'meanR':>6} {'folds+':>6}")
    print(f"{'BASELINE stop + signal flip':<46} {bm['total'] * 100:>+7.1f}% {bm['sharpe']:>+6.2f} {bm['mdd'] * 100:>6.1f}% "
          f"{base['cal']:>+7.2f} {bm['positions']:>4} {base['pos_wr'] * 100:>4.0f}% {base['pos_r']:>+6.2f} "
          f"{base_folds_pos:>3}/{len(base['folds'])}")

    rows = []
    for tp in TP_R:
        for frac in FRACS:
            for be in BE:
                for trail in TRAIL:
                    act = 1.0 if trail else 0.0
                    name = (f"scale {int(frac * 100)}% at {tp:g}R"
                            f"{', BE 1R' if be else ''}{', trail 3 after 1R' if trail else ''}")
                    r = run_cell('4h', sig, name, trail, act, be, tp, frac, ft, fr)
                    m = r['m']
                    rows.append((name, r))
                    fp = sum(f > 0 for f in r['folds'])
                    print(f"{name:<46} {m['total'] * 100:>+7.1f}% {m['sharpe']:>+6.2f} {m['mdd'] * 100:>6.1f}% "
                          f"{r['cal']:>+7.2f} {m['positions']:>4} {r['pos_wr'] * 100:>4.0f}% {r['pos_r']:>+6.2f} "
                          f"{fp:>3}/{len(r['folds'])}")

    n = len(rows)
    beat_sh = sum(1 for _, r in rows if r['m']['sharpe'] > bm['sharpe'])
    beat_cal = sum(1 for _, r in rows if r['cal'] > base['cal'])
    beat_mdd = sum(1 for _, r in rows if r['m']['mdd'] > bm['mdd'])    # less negative = smaller drawdown
    beat_tot = sum(1 for _, r in rows if r['m']['total'] > bm['total'])
    print(f"\n-- breadth over {n} variants vs baseline:")
    print(f"   beat baseline Sharpe   {beat_sh}/{n}  (baseline {bm['sharpe']:+.2f}; median variant {st.median(r['m']['sharpe'] for _, r in rows):+.2f})")
    print(f"   beat baseline Calmar   {beat_cal}/{n}  (baseline {base['cal']:+.2f}; median variant {st.median(r['cal'] for _, r in rows):+.2f})")
    print(f"   beat baseline WF total {beat_tot}/{n}  (baseline {bm['total'] * 100:+.1f}%)")
    print(f"   smaller MDD            {beat_mdd}/{n}  (baseline {bm['mdd'] * 100:.1f}%)")
    best_cal = max(rows, key=lambda x: x[1]['cal'])
    print(f"-- best Calmar: {best_cal[0]}  Calmar {best_cal[1]['cal']:+.2f}, Sh {best_cal[1]['m']['sharpe']:+.2f}, "
          f"WF {best_cal[1]['m']['total'] * 100:+.1f}%, MDD {best_cal[1]['m']['mdd'] * 100:.1f}%  "
          f"(selected in-sample from {n}; not a finding on its own)")


if __name__ == '__main__':
    main()
