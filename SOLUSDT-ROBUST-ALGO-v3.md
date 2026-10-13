# SOLUSDT Perp — v3: Trading with Robust Algorithms

Data: Binance USD-M perpetuals via `@nemesis-oss/binance-sdk` (1,500 daily bars 2022-09→2026-10-13, actual funding history 4,575 settlements). Scripts: `analyze-v3.py`, `analyze-v3b.py`; logs: `analysis-v3-output.txt`, `analysis-v3b-output.txt`.

## The honest answer up front

After running the standard robust-algorithm toolkit (walk-forward optimization, parameter-ensemble Donchian breakout, TSMOM, volatility targeting, deflated Sharpe, block-bootstrap CIs) **on both sides of the market**, the conclusion is uncomfortable but that's the point of robustness testing:

| System (all costs incl. funding & slippage) | Total | Ann. | Sharpe | Max DD | Calmar |
|---|---|---|---|---|---|
| Buy & Hold perp (pays funding) | **+338%** | +51.9% | 0.92 | −76.0% | 0.68 |
| Donchian ensemble, TV60% (long+short) | +59% | +14.1% | 0.82 | **−20.4%** | 0.69 |
| Same, walk-forward re-tuned | +19% | +5.0% | 0.50 | −9.0% | 0.55 |
| Bear-gated RSI short overlay | +18% | +4.8% | 0.58 | −14.3% | 0.34 |
| Classic TSMOM 90d vol-targeted | −70% | −28.6% | −0.05 | −85.7% | −0.33 |
| Funding-carry short sleeve | −41% | −13.9% | −1.10 | −43.3% | −0.32 |
| SMA200-gated long w/ vol target | +21% | +5.6% | 0.34 | −46.9% | 0.12 |

**No systematic long/short algorithm beat buy-and-hold on total return, and every one has a deflated-Sharpe probability < 0.5** (prob. the edge is real after correcting for multiple testing) — i.e., none survives rigorous statistical scrutiny at conventional thresholds. This matches the earlier finding that daily SOL direction is essentially unpredictable; the ML test (v2) got the same verdict.

## What DID survive robustness checks

1. **Donchian breakout ensemble (the best risk-adjusted system found).** Average of 5 entry/exit bands (20/10, 40/15, 55/20, 80/25, 120/30 days), symmetric long/short, position sized as `min(2.5x, 60% target-vol / 20d realized-vol)`:
   - Sharpe 0.82 ≈ buy & hold's 0.92, but **max drawdown −20% vs −76%**.
   - **Parameter-flat**: dropping/adding any band or shifting exits ±5 days keeps Sharpe 0.79–0.93 → not an overfit spike. Target-vol changes only scale risk, not Sharpe — exactly what a robust design should look like.
   - Walk-forward (train 2y → trade 6m OOS rolling): positive in every fold's aggregate (+19%, MDD −9%).
   - Bootstrap: worst-5%-case yearly DD −9.8% vs −47.6% for holding; P(loss-year) similar (~42%) but bounded tail.
   - Cost: it is **right-tail-trimming** — time-in-market only ~10%, so it structurally cannot capture the 2023 melt-up (+36% vs B&H's +415%). Trend systems miss V-shaped bottoms by design.
2. **Short-side reality check.** Shorts were tested four ways (symmetric breakout, bear-gated mean-reversion, pure static short, funding carry). Only *gated* shorts (breakout ensembles' 3% short-time; RSI-bounce-in-bear) add small drawdown protection. **Ungated shorting of SOL is statistically indefensible** — the asset's positive drift and violent squeezes destroy short sellers (TSMOM shorts lost −56% in 2025 alone; carry-short lost money because funding is negative 33% of the time and even "expensive" funding days were followed by *rising*, not falling, prices).
3. **Funding is a cost line, not an alpha source.** Mean 8h funding = −0.005% (≈ −5.6%/yr *paid to longs*), so holding the perp historically *beat* spot. Useful as a regime thermometer (deep-negative funding marked 2022 bottom area) but too rare-to-trade as a standalone signal.

## Recommended robust framework (if you must trade this instrument)

A three-layer allocation, judged on worst-case rather than best-case:

- **Core (60–80%): passive perp accumulation with a hard vol-cap.** No timing algorithm reliably beats holding SOL over 4 years; if you believe in the asset, B&H with ≤2x effective leverage and never more than ~35% of portfolio in one fat-tailed name.
- **Satellite (20–30%): Donchian-ensemble trend system above** — the only algo whose Sharpe ≈ B&H at ¼ the drawdown. It will feel useless most months (90% flat); its job is to harvest the slow trends (2024, 2026) and to be short during confirmed collapses instead of long.
- **Crisis overlay (≤10%): bear-gated bounce-shorts** (short RSI>65 bounces only when price<SMA200 AND SMA50<SMA200, exit RSI<40). Small positive expectancy, −14% worst DD, strictly rule-based.
- **Kill switch:** cap gross exposure at 2.5x vol-sized units; force flat if margin utilization > 50% or funding-rate z-score > +3 against you (squeeze risk).

## Why this is "better" than v1/v2/futures answers

- Selection by **Calmar/drawdown under walk-forward**, not in-sample total return (v1's momentum-gate "+390%" was survivorship of a tuned parameter; WF version of the same family made −14%).
- **Multiple-testing deflation** applied — we report that nothing clears DSR>0.95 instead of cherry-picking the winner of 30 backtests.
- **Both directions traded honestly with funding**, which killed three previously-plausible ideas (carry-short, TSMOM, crowd-fade).

*Not financial advice. Past performance of these rules on 4 years of data does not guarantee future results; sample contains only one full bull-bear cycle.*
