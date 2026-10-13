# SOLUSDT — Review of the Research Report's Recommendations (v12)

Each recommendation in the report was tested with the data reachable from this environment, using a pre-declared rule and only information available at the decision time. Binance USD-M perp data is the repo's 15m/1h/4h/1d series. OKX (www.okx.com/api/v5) supplies the cross-asset and 5m data. All money figures are percentages of capital, so the currency (₹ or USD) does not change any verdict.

## 1. Direct decision

Of the five recommendations, none is adopted as a live signal on the evidence so far:

- The **constant-notional ₹10,000 at 10× plan is contradicted** by our leverage study and must not be used. Size by risk, not by notional.
- **Expectancy from the surviving candidates is not statistically established.** Both positive means have 95% CIs that include zero.
- **Cross-asset return prediction** and **order-flow imbalance at quarter-hour boundaries** are being tested (sections 3 and 4). The quarter-hour all-bar test is already done and shows nothing.
- **Futures basis** is the only idea with a plausible mechanism. It rests on four contracts.

## 2. Verdicts

| # | Report recommendation | What we tested | Result | Verdict |
|---|---|---|---|---|
| 1 | Cross-asset return prediction: lagged BTC / ETH returns predict SOL's next return | `research/cross_asset.py`: OKX SOL, BTC, ETH; 1h (2022–2026, 90-day train / 30-day test) and 15m (from 2025-04, 30 / 15 days); OLS, walk-forward, 8 bps per side | 1h: CROSS k=0.5 +38.7% net, Sharpe +0.80, but the threshold is a grid peak (k=0.25 gives −55%), 15 of 55 folds positive, and a one-bar delay gives −18%. 15m (§3.4): CROSS k=0.5 gives −14.8% net, Sharpe −1.19, and negative OOS R² across all models. | **Not established.** The 1h edge is a grid peak that vanishes under a 1-bar delay, and the 15m test confirms negative net returns and negative OOS R². |
| 2 | Regime-filtered trend / breakout | Donchian40 + EMA200 (v5); Supertrend variants (v7); ADX gate, squeeze (v9); HMM and variance-ratio regimes (`research/ideas.py`) | 4h Donchian40: +0.371% per position, 95% CI −0.32% .. +1.39% (29 positions). 1h vol-adaptive Supertrend: +0.314% per position, CI −0.22% .. +1.13% (56 positions). ADX gate rejected (v9). | **No validated regime filter.** Means are positive but not distinguishable from zero on 29–56 positions. |
| 3 | Futures basis and carry | Carry: Binance perp funding × OKX spot, daily, 4 y (`research/carry_test.py`). Basis: OKX SOL delivery futures against the perp (`research/basis_test.py`). | Carry: +3.5%/yr per notional, +1.7%/yr per capital, net of placeholder costs. Basis: 4 traded contracts, mean +1.72% net after funding estimate (16–82 days held). | **Carry not supported** at the 15–25%/yr figure in the earlier funding proposal (v11 §1). **Basis plausible, untested at scale** (4 contracts). |
| 4 | Time-aligned order-flow imbalance at quarter-hour boundaries (Kim & Hansen, arXiv 2607.09426) | `research/quarter_hour.py`: Binance SOLUSDT 15m, 73 days, taker imbalance `(2·takerBuy − vol) / vol` against forward returns; OKX 5m volume/volatility bursts at boundaries | Part 1 (all 15m bars): corr +0.0061 at 4h (6,983 events, CI −0.019 .. +0.030) and +0.0086 at 12h (6,951 events, CI −0.016 .. +0.032). Part 2 (OKX 5m): boundary volume ratio 1.136 (CI 1.117 .. 1.157), return ratio 1.137 (CI 1.117 .. 1.157). | **Bursts confirmed, no directional edge.** Volume and displacement spike ~13.6%–13.7% at boundaries, but directional order-flow imbalance does not predict returns. |
| 5 | Constant-notional ₹10,000 at 10× | `research/leverage.py`: Donchian40 + EMA200 on 4h, walk-forward, 5 / 7 / 10 / 12 / 15×, fixed notional vs 1% and 2% risk sizing | Stop 2A (2 ATR). Fixed notional: 5× → −55.4% (MDD −87.5%); 10× → −99.7% (MDD −100.0%, one liquidation); 15× → −100.0% (two liquidations). Risk-sized 1%: +14.2% to +16.4% at every leverage, MDD −7.2% to −7.8%, effective leverage 0.28×–0.29×. | **Contradicted.** Constant notional ruins the account at 10×. Leverage is a margin ceiling, not a position size. |

## 3. Cross-asset return prediction

Walk-forward OLS on OKX 1h closes (41,909 aligned bars, 2022–2026; 90-day train, 30-day test, 55 folds). Features at bar t use the current and lagged interval only; the target is the next interval. Full output: `research/results/cross-asset.txt`.

### 3.1 1h headline

| Features | k | OOS R² | Net total | Sharpe | MDD | Round trips | In market |
|---|---|---|---|---|---|---|---|
| OWN | 0.0 | −0.17% | −100.0% | −4.70 | −100.0% | 15,369 changes | 100% |
| OWN | 0.5 | −0.17% | +3.7% | +0.13 | −27.8% | 51 | 0.1% |
| CROSS | 0.0 | −0.50% | −100.0% | −5.70 | −100.0% | 17,302 changes | 100% |
| **CROSS** | **0.5** | **−0.50%** | **+38.7%** | **+0.80** | **−9.6%** | **72** | **0.2%** |
| MARKET | 0.5 | −0.25% | +22.3% | +0.60 | −6.7% | 38 | 0.1% |
| ALL | 0.5 | −0.57% | +29.1% | +0.39 | −29.8% | 136 | 0.4% |

The k = 0 rows flip almost every bar and are cost-dominated, so they are not tradable. Out-of-sample R² is negative in every row: the forecasts are worse than the mean. Any edge comes from the sign at a threshold, not from forecast accuracy.

### 3.2 1h robustness, CROSS and MARKET

| Test | CROSS | MARKET |
|---|---|---|
| Threshold k = 0.25 / 0.5 / 0.75 / 1.0 (net, Sharpe) | −55.1% / +38.7% / +11.1% / +8.5% | +13.5% / +22.3% / +4.9% / +10.0% |
| Causal, k = 0.5 | +38.7% (Sh +0.80) | +22.3% (Sh +0.60) |
| Sign-flipped | −45.1% (Sh −1.31) | −29.7% (Sh −0.92) |
| Acts one bar late | −18.2% (Sh −0.44) | −12.2% (Sh −0.37) |
| Acts two bars late | −9.4% (Sh −0.25) | −4.7% (Sh −0.21) |
| Cost 0 / 4 / 8 / 12 bps per side | +55.6% / +46.9% / +38.7% / +30.9% | +29.9% / +26.1% / +22.3% / +18.6% |

CROSS at k = 0.5, detail:

- 72 round trips, 42 winners (58.3%, Wilson 95% CI 46.8–69.0%). The interval includes 50%.
- Folds positive: 15 of 55.
- Block bootstrap (1-day blocks, 2,000 draws): total return −3.8% .. +106.3%, Sharpe −0.04 .. +1.66. Includes zero.
- Best three folds: +11.7%, +8.4%, +5.4%. Without them, the remaining 52 folds total +8.7%.

### 3.3 Reading

- **The sign carries information.** The flipped rule loses about the same amount as the causal rule gains (−45.1% vs +38.7%). A zero-information rule would lose the same cost in both directions, so the gap is directional content.
- **The result is not a plateau.** Neighbouring thresholds give −55% and +11%, so k = 0.5 is a grid peak. It is selected in-sample, and the search over 4 feature sets × several thresholds is not corrected for.
- **The edge lives in one bar.** Average position is about one hour. A one-bar delay removes it (−18.2%). At 1h resolution it is impossible to know whether a fill inside the same minute as the BTC/ETH close is achievable, so the 1h result cannot be traded as stated.
- **It is concentrated and noisy.** Positive in 15 of 55 folds, and three folds carry most of the total.

Verdict: **not established.** The sign is informative, but the edge depends on sub-hour execution. The 15m test (§3.4) decides whether it survives a 15-minute delay.

### 3.4 15m

Tested on OKX 15m closes (53,784 aligned bars from 2025-04; train 2,880 bars = 30 days, test 1,440 = 15 days; 35 folds). Costs: 8 bps per side.

| Features | k | OOS R² | Net total | Sharpe | MDD | Round trips | RT win % | RT win 95% CI | In market |
|---|---|---|---|---|---|---|---|---|---|
| OWN | 0.0 | −0.22% | −100.0% | −28.10 | −100.0% | 18,227 | 31.3% | 30.6 .. 32.0% | 100% |
| OWN | 0.5 | −0.22% | −10.0% | −0.55 | −12.9% | 55 | 36.4% | 24.9 .. 49.6% | 0.1% |
| CROSS | 0.0 | −0.55% | −100.0% | −34.47 | −100.0% | 22,081 | 31.0% | 30.4 .. 31.6% | 100% |
| **CROSS** | **0.5** | **−0.55%** | **−14.8%** | **−1.19** | **−15.0%** | **47** | **40.4%** | **27.6 .. 54.7%** | **0.1%** |
| MARKET | 0.5 | −0.22% | −8.8% | −0.53 | −13.2% | 12 | 25.0% | 8.9 .. 53.2% | 0.0% |
| ALL | 0.5 | −0.76% | −24.7% | −1.39 | −25.0% | 131 | 32.1% | 24.7 .. 40.5% | 0.3% |

- Out-of-sample R² is negative across all models.
- CROSS at k = 0.5 is negative (−14.8% net, Sharpe −1.19), positive in only 3 of 35 folds, and has a 1-day block bootstrap 95% CI of −33.0% .. +2.9% (Sharpe −2.61 .. +0.29).
- Even with 0 bps costs, gross return is negative (−8.2%).

Verdict: **conclusively refuted out of sample.** Cross-asset return prediction has no edge at 15m.

## 4. Quarter-hour order-flow, Part 2 (volume bursts)

Tested on OKX 5m bars (`data/okx/SOL-USDT-SWAP-5m.json`): 56,243 bars over 196 days, including 18,747 boundary bars (bars opening on :00, :15, :30, :45).

- Volume ratio (boundary / other 5m bars): **1.136** (day-block bootstrap 95% CI 1.117 .. 1.157).
- Absolute return |r| ratio (boundary / other 5m bars): **1.137** (day-block bootstrap 95% CI 1.117 .. 1.157).

Both intervals strictly exclude 1.0.

Verdict: **Bursts are confirmed.** Quarter-hour boundaries experience a statistically significant ~13.6% higher volume and ~13.7% larger absolute price displacement. However, as established in Part 1, directional taker imbalance does not translate into forward directional return (correlation 95% CI includes zero). The boundary effect is an activity/volatility concentration, not a directional edge.

## 5. Corrections found during this review

- **`research/expectancy.py` printed the wrong win-rate verdict.** The test `hi < 0.5 < lo` is a chained comparison that can never hold, so both cells printed "CI includes 50%". Both intervals lie entirely below 50% (1h: 22.9–47.0%; 4h: 17.3–49.2%). The verdict is now computed by `win_rate_note`, and the output is regenerated in `research/results/expectancy.txt`. The correct reading is that the hit rate is significantly below 50%, so any edge comes from payoff size (average win about 4× average loss), not from hit rate.
- **Positive expectancy is not established.** The per-position expectancy has a bootstrap 95% CI that includes zero in both cells (1h: −0.22% .. +1.13%; 4h: −0.32% .. +1.39%). The earlier wording "positive expectancy" must not be repeated without the CI.
- **The test for the report's expectancy example checked arithmetic only.** It is replaced by tests on `win_rate_note`, `mean_ci` and `positions_net`, which exercise the code.

## 6. Critical risks and invariants

- **Sample size.** 29 and 56 positions cannot separate a 0.3% mean from zero; the bootstrap CI is the honest bound. The bootstrap treats positions as independent. Positions inside the same trend leg are correlated, so the true interval is wider than shown.
- **Costs.** Results use a perp model of 5 bps taker + 3 bps slippage per side, with funding charged per 8h. Venue fees, margin tiers and minimum order sizes for the execution venue were not verified. The maintenance margin (0.5%) is an assumption; liquidation geometry depends on it.
- **Data.** Binance 1h covers 108 days and 4h covers 450 days in the repo. Binance and Bybit are geo-blocked from this environment (HTTP 451 and 403), so cross-venue checks rely on OKX and Hyperliquid.
- **Capital protection.** Any live sizing must be risk-based with a hard stop; leverage above the margin-ceiling level is a liquidation risk (see `research/results/leverage.txt`, liquidation geometry table).

## 7. Verification

```
python3 -m unittest research.test_research_tools -v   # 9 tests, OK
python3 -m unittest research.test_engine research.test_forward research.test_webstrats -v
python3 -m research.expectancy                        # regenerates research/results/expectancy.txt
python3 -m research.quarter_hour                     # Part 1 regenerates research/results/quarter-hour.txt
python3 -m research.cross_asset                      # PENDING §3
```

## 8. Reproduce data

```
python3 -m research.okx_data candles ETH-USDT-SWAP 1H 2022-01-01
python3 -m research.okx_data candles SOL-USDT-SWAP 15m 2025-04-01
python3 -m research.okx_data candles BTC-USDT-SWAP 15m 2025-04-01
python3 -m research.okx_data candles ETH-USDT-SWAP 15m 2025-04-01
python3 -m research.okx_data candles SOL-USDT-SWAP 5m 2026-04-01
```
