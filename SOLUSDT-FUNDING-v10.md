# SOLUSDT — Funding-Rate Claims Checked Against Our Data (v10)

Data: settled SOLUSDT funding, 4,575 events from 2022-09-04 to 2026-10-13 (`data/SOLUSDT-futures.json`). Price series for backtests: Binance perp klines in the repo. The 4h series starts 2025-07-20 and the 1h series starts 2026-06-26, so only the 1d series covers the full four years. Costs: taker 5 bps per side. Spot prices, basis and quarterly contracts are not in the repo.

## 1. Verdict on the proposal's claims

| Claim | What the data says |
|---|---|
| "10–30% APY on SOLUSDT during bull runs" from funding arbitrage | Only 2024 supports it. Mean annualised funding is +13.6% in 2024, but −5.7% a year over the full sample. Always-short carry loses. |
| "Funding arb: 15–25% APY target" | Conditional carry (short perp only while funding > 0.01%/8h) nets +3.3% a year after placeholder costs. Spot leg, basis and spot fees are not modelled. **Not supported.** |
| "Funding mean reversion: Sharpe 1.0–1.5 on SOL" | On 1d, the best cells reach Sharpe 0.52. Returns run from −0.5% to +2.2% over four years at 1×. **Direction holds; size and Sharpe do not.** |
| Funding z-score in `factor_sentiment` | No such module exists in this repo. |
| OI divergence table with predictive power on 15m–1h | Not testable: open-interest history here is about 20 days. |
| Basis trade, stat-arb SOL/AVAX, liquidation-cascade hunting | Need quarterly contracts, AVAX history and a liquidation feed. None are in the repo. Not tested. |
| Lo, Mamaysky & Wang (2000): most technical patterns don't survive costs | The [Journal of Finance abstract](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00265) says several indicators "do provide incremental information and may have some practical value." It does not say most fail after costs. |
| "Backtests show PF ≈ 1.0 minus fees — exactly what we got" | Our surviving candidates show profit factors of about 1.7–2.3 in walk-forward. Not 1.0. The 1h candidate is unvalidated, not break-even. |

## 2. Funding carry (`research/results/funding.txt`)

- Funding median +0.0046%/8h. Positive in 67% of settlements. Above +0.01%/8h in 7.6% of them.
- Annualised mean by year: 2023 +1.3%, 2024 +13.6%, 2025 +0.4%, 2026 −1.0%. 2022 is dominated by a single −2%/8h print.
- Conditional carry, placeholder costs (4 × 5 bps per cycle), basis excluded:

| Entry threshold | Net per year | Cycles | In market | By year |
|---|---|---|---|---|
| > 0.010%/8h | +3.3% | 11 | 18% | 2023 +3.4%, 2024 +10.3%, 2025 −0.1% |
| > 0.030%/8h | +2.9% | 6 | 12% | 2023 +3.0%, 2024 +8.9% |
| > 0.050%/8h | +2.3% | 4 | 9% | 2023 +2.8%, 2024 +6.6% |

The gain is concentrated in 2024. Spot-leg fees and the spot-perp basis could erase it, and the basis is the main risk of a delta-neutral position.

## 3. Funding mean reversion, directional (`research/results/funding-mr-1d.txt`)

Signal: robust z-score (median and MAD) or standard z-score of the latest settled funding against its trailing 90 or 270 events. Short when z > +thr, long when z < −thr, exit at |z| < 0.5. Daily bars, 1×, 1% risk, 3-ATR stop, walk-forward OOS.

| Cells | Positive WF OOS | Flipped positive | Return range | Best Sharpe |
|---|---|---|---|---|
| 8 (stdev and robust, 90/270 events, thr 2 and 2.5) | **7 of 8** | **0 of 8** | −0.5% to +2.2% | 0.52 |

Directional, since flipping loses in every cell. Mostly long trades (17–45 long against 8–11 short), so the edge is mainly the long leg on negative-funding extremes. Trade counts are 25–55 over four years, and returns are small.

Why the 4h and 1h tests were misleading: those series cover only 450 and 108 days, and that window has low, mostly negative funding (2025 share above zero: 61%; 2026: 53%). Positive funding extremes almost never occur there. On the full 1d sample they occur at 2.7–3.4% of settlements, so the short leg does get exercised.

The standard z-score is distorted by the 2022 −2% print. It blocks positive extremes for a long time. The robust variant avoids that, and both variants are shown.

## 4. Verification

```
python3 -m research.funding                        # research/results/funding.txt
```

## 5. What I would do next

1. **Do not build the funding carry as proposed.** The full-sample result does not support 15–25% APY, and the spot leg is the part we cannot test here.
2. **Funding mean reversion on 1d is directionally real but too small to trade at 1×.** Forward-testing it alongside the 1d momentum lead would tell us more than more backtests would.
3. **Stat-arb SOL/AVAX** is testable if AVAX history is available from a reachable venue. It needs a cointegration test with out-of-sample pairs, not a single in-sample fit.
