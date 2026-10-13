"""Expectancy and win-rate confidence for the surviving candidates, per POSITION (partial closes summed).

E = p*W - (1-p)*L, with W and L the mean win and absolute mean loss, measured in return on equity at entry, net of costs.
The win-rate interval is Wilson 95%. The report asks that p's interval support p > 0.5 before trusting a win-rate edge.

Usage: python3 -m research.expectancy
"""
import math
import random

from research.engine import donchian_sig, ema_gate, load_funding, load_klines
from research.adaptive_st import vol_adaptive_st_sig
from research.exits import run_cell


def positions_net(trades):
    groups = {}
    for t in trades:
        key = (t['side'], t['k_in'], round(t['ep'], 10))
        groups[key] = groups.get(key, 0.0) + t['ret']
    return list(groups.values())


def wilson(k, n, z=1.96):
    if n == 0:
        return float('nan'), float('nan')
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return centre - half, centre + half


def win_rate_note(lo, hi):
    """Where the Wilson interval sits relative to 50%. A hit-rate below 50% is not an edge problem by itself:
    trend systems with payoff ratio > 1 can carry positive expectancy at p < 0.5."""
    if lo > 0.5:
        return "win-rate CI excludes 50% (above): the hit rate is itself above a coin flip"
    if hi < 0.5:
        return "win-rate CI excludes 50% (below): any edge comes from payoff size, not hit rate"
    return "win-rate CI includes 50%: a win-rate edge is not established"


def mean_ci(rets, B=10000, seed=3):
    """IID Bootstrap 95% CI of the mean per-position return. Positions are resampled with replacement."""
    n = len(rets)
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choice(rets) for _ in range(n)) / n for _ in range(B))
    return means[int(0.025 * B)], means[int(0.975 * B)]


def block_mean_ci(rets, block_size=4, B=10000, seed=3):
    """Block bootstrap 95% CI preserving trade clustering and serial dependence."""
    n = len(rets)
    if n < block_size:
        return mean_ci(rets, B=B, seed=seed)
    rnd = random.Random(seed)
    means = []
    for _ in range(B):
        sample = []
        while len(sample) < n:
            start = rnd.randint(0, n - block_size)
            sample.extend(rets[start:start + block_size])
        means.append(sum(sample[:n]) / n)
    means.sort()
    return means[int(0.025 * B)], means[int(0.975 * B)]


def summarise(name, rets):
    n = len(rets)
    wins = [r for r in rets if r > 0]
    losses = [-r for r in rets if r <= 0]
    p = len(wins) / n if n else float('nan')
    W = sum(wins) / len(wins) if wins else 0.0
    L = sum(losses) / len(losses) if losses else 0.0
    E = p * W - (1 - p) * L
    lo, hi = wilson(len(wins), n)
    print(f"{name:<34} positions {n:>3}  win rate {p * 100:5.1f}% (95% CI {lo * 100:4.1f}-{hi * 100:4.1f}%)  "
          f"avg win {W * 100:+.2f}%  avg loss {L * 100:.2f}%  expectancy {E * 100:+.3f}%/position")
    clo, chi = mean_ci(rets)
    blo, bhi = block_mean_ci(rets, block_size=4)
    print(f"   IID bootstrap 95% CI   {clo * 100:+.3f}% .. {chi * 100:+.3f}%  ({'excludes' if clo > 0 or chi < 0 else 'includes'} 0)")
    print(f"   Block bootstrap 95% CI {blo * 100:+.3f}% .. {bhi * 100:+.3f}%  ({'excludes' if blo > 0 or bhi < 0 else 'includes'} 0)")
    print("   " + win_rate_note(lo, hi))


def main():
    ft, fr = load_funding()
    s1 = load_klines('1h')
    s4 = load_klines('4h')
    cells = [
        ('1h vol-adaptive ST, stop-only', '1h', vol_adaptive_st_sig(s1, 20, 100, 1.5, 4.0)),
        ('4h Donchian40 + EMA200, stop-only', '4h', donchian_sig(s4, 40, gate=ema_gate(s4, 200))),
    ]
    print("==================== expectancy per position, walk-forward, 5x, 1% risk, 3-ATR stop, net of costs ====================")
    for name, tf, sig in cells:
        r = run_cell(tf, sig, name, None, 0.0, None, None, 1.0, ft, fr)
        summarise(name, positions_net(r['trades']))


if __name__ == '__main__':
    main()
