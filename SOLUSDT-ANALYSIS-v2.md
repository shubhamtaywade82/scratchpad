# SOLUSDT — Analysis v2 ("a better way")

**Data:** same 4 years of Binance klines pulled via `@nemesis-oss/binance-sdk` (`data/SOLUSDT-klines.json`, as of 2026-10-13).
**New code:** `analyze-v2.py` → full results in `analysis-v2-output.txt`.

## Why v1 was not good enough

| Flaw in v1 | Fix in v2 |
|---|---|
| "RSI mean-revert: +3.7%" used **RSI(14) on the close you trade at** — partly lookahead | All signals computed at close t, exposure applied only to return t→t+1 |
| Fee charged once, one-sided | 0.12% fee+slippage charged on **every unit of turnover**, both sides |
| Binary 0/1 positions ignored that SOL's vol swings 2x | **Volatility targeting** (scale weight by 20d realized vol) |
| No statistical test of whether anything is predictable | **Walk-forward ML** with purged time-series CV (5×120d folds, gap=5) |
| Point estimates only | **Monte-Carlo bootstrap** of 1-year outcomes (1,000 paths) |
| Descriptive indicators, no structure | **Regime clustering** (k-means on vol/momentum/trend/DD/volume) |

## 1. The honest headline: next-day direction is NOT predictable

Walk-forward LogReg accuracy **46.3%**, RandomForest **49.7%** — at/below coin-flip out-of-sample. Both traded long/short lose −58% to −84%. Conclusion: **there is no daily-timing edge in this data**; any analysis claiming one is overfitting. This kills the "find the perfect indicator" approach and reframes the problem as *risk management*, not prediction.

## 2. Regimes exist and are persistent (k-means, 3 clusters)

| Regime | Share | Avg fwd-30d | Avg ATR% | px vs SMA200 | Interpretation |
|---|---|---|---|---|---|
| R1 "bull trend" | 28% | **+14.6%** | 6.7% | +72% | strong momentum above trend; best expected returns |
| R0 "chop/base" | 51% | +4.6% | 5.6% | −6% | low-vol sideways; mild positive drift |
| R2 "stress" | 21% | +5.5%* | **8.9%** | −6% | high-vol drawdown; noisy bounce stats (*survivorship of rebounds) |

Regime membership changes slowly (bull regime ≈ the 2023 & late-2026 runs), which is exactly why a **trend gate** works while day-to-day ML doesn't.

## 3. Risk-managed backtests beat v1's naive ones (warmup 2023-03 → 2026-10, ~3.6y, costs on turnover)

| Strategy | Total | CAGR | Max DD | Sharpe | Exposure |
|---|---|---|---|---|---|
| Buy & Hold | +416.0% | +58.5% | −76.3% | 0.97 | 100% |
| ~100d momentum gate | +390.0% | +56.2% | **−49.4%** | **1.02** | 58% |
| SMA200 trend filter | +258.8% | +43.1% | −58.6% | 0.87 | 56% |
| Vol-target 40% (no gate) | +215.8% | +38.1% | −56.3% | 0.95 | 100% |
| EMA50/200 cross | +134.0% | +27.0% | −64.6% | 0.69 | 59% |
| **Vol-target 40% + SMA200 gate** | +110.4% | +23.2% | **−34.8%** | 0.80 | 56% |
| Cycle accumulation (buy deep DD) | +26.8% | +6.9% | −38.0% | 0.42 | 72% |

Corrections to v1's story:
- With honest costs and next-bar fills, **~100d momentum actually matches buy & hold (+390% vs +416%) with roughly half the drawdown and slightly higher Sharpe (1.02 vs 0.97)** — v1's "+121%" version was hurt by its cruder fill/fee model and shorter lookback.
- **Volatility targeting is the single biggest drawdown reducer**: −34.8% MDD vs −76.3% for B&H, at the cost of ~35 pts CAGR.
- v1's dip-buying edge disappeared under realistic costs — confirmed dead end.
- Adding a 4h overlay on top destroyed exposure (only 4% time-in-market due to conservative lag) — multi-timeframe confirmation here is redundancy, not signal. Simpler wins.

## 4. Monte-Carlo: what a random year looks like (1,000 bootstrap years)

| | Median 1y return | P(loss) | P(+50%) | P(−50% or worse) | Median max-DD |
|---|---|---|---|---|---|
| Buy & Hold | +31.4% | 34% | 44% | 6% | −45% |
| Vol-target 40% + SMA200 gate | +39.6% | **7%** | 38% | **0%** | **−15%** |

The gated strategy has a *higher median* outcome than B&H despite lower total return, because it truncates the left tail. For an asset whose defining feature is −76% drawdowns, **tail truncation is the whole game**.

## 5. Live signal state (today)

- Price $106.73, **+22.6% above SMA200 → gate ON (long allowed)**
- 20d realized vol 55% → target weight **0.73x** (strategy never went above 0.87x historically — vol is the binding constraint, not conviction)
- Rolling-1y Sharpe: strategy **0.98** vs B&H **0.51** right now
- Weight 90d ago was 0.00x (below-SMA200 during the June bear leg) — the gate already did its job avoiding part of the −76% episode

## Recommended framework (the "better way")

1. **Don't predict.** Accept 50% daily accuracy; spend zero effort on entry timing.
2. **Gate by regime:** long-only when price > SMA200 (~100d momentum as alternative); flat otherwise. Removes the −76% tail.
3. **Size by volatility, not conviction:** weight = 40%/realized-vol, capped 1.5x. Converts SOL's vol clustering from a hazard into the sizing engine.
4. Judge everything on **worst rolling-1y Sharpe and MC left tail**, not total return (v1's mistake). Worst trailing-year Sharpe seen: −1.69 (strategy) vs −2.20 (B&H).

Result: ~⅓ of the drawdown of holding, comparable Sharpe, and a 1-year loss probability of 7% instead of 34% — achieved with two transparent rules, no fitted parameters beyond standard windows.

*Not financial advice; ~3.6 testable years of one asset is a small sample; regime statistics include overlapping-window bias.*
