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
| 1 | Cross-asset return prediction: lagged BTC / ETH returns predict SOL's next return | `research/cross_asset.py`: OKX SOL, BTC, ETH; 1h (2022–2026, 90-day train / 30-day test) and 15m (from 2025-04, 30 / 15 days); OLS, walk-forward, 8 bps per side | See §3 | Pending §3 |
| 2 | Regime-filtered trend / breakout | Donchian40 + EMA200 (v5); Supertrend variants (v7); ADX gate, squeeze (v9); HMM and variance-ratio regimes (`research/ideas.py`) | 4h Donchian40: +0.371% per position, 95% CI −0.32% .. +1.39% (29 positions). 1h vol-adaptive Supertrend: +0.314% per position, CI −0.22% .. +1.13% (56 positions). ADX gate rejected (v9). | **No validated regime filter.** Means are positive but not distinguishable from zero on 29–56 positions. |
| 3 | Futures basis and carry | Carry: Binance perp funding × OKX spot, daily, 4 y (`research/carry_test.py`). Basis: OKX SOL delivery futures against the perp (`research/basis_test.py`). | Carry: +3.5%/yr per notional, +1.7%/yr per capital, net of placeholder costs. Basis: 4 traded contracts, mean +1.72% net after funding estimate (16–82 days held). | **Carry not supported** at the 15–25%/yr figure in the earlier funding proposal (v11 §1). **Basis plausible, untested at scale** (4 contracts). |
| 4 | Time-aligned order-flow imbalance at quarter-hour boundaries (Kim & Hansen, arXiv 2607.09426) | `research/quarter_hour.py`: Binance SOLUSDT 15m, 73 days, taker imbalance `(2·takerBuy − vol) / vol` against forward returns; day-block bootstrap | Part 1 (all 15m bars): corr +0.0061 at 4h (6,983 events, CI −0.019 .. +0.030) and +0.0086 at 12h (6,951 events, CI −0.016 .. +0.032). Both intervals include zero. | **Not supported** on this data. Part 2 (OKX 5m volume bursts at boundaries) is pending §4. |
| 5 | Constant-notional ₹10,000 at 10× | `research/leverage.py`: Donchian40 + EMA200 on 4h, walk-forward, 5 / 7 / 10 / 12 / 15×, fixed notional vs 1% and 2% risk sizing | Stop 2A (2 ATR). Fixed notional: 5× → −55.4% (MDD −87.5%); 10× → −99.7% (MDD −100.0%, one liquidation); 15× → −100.0% (two liquidations). Risk-sized 1%: +14.2% to +16.4% at every leverage, MDD −7.2% to −7.8%, effective leverage 0.28×–0.29×. | **Contradicted.** Constant notional ruins the account at 10×. Leverage is a margin ceiling, not a position size. |

## 3. Cross-asset return prediction

PENDING: the ETH 1H file is still downloading. Results will be written to `research/results/cross-asset.txt`.

## 4. Quarter-hour order-flow, Part 2 (volume bursts)

PENDING: needs `data/okx/SOL-USDT-SWAP-5m.json`. OKX candles carry no buy/sell split, so only the volume and |return| parts of the paper's claim can be tested here. The taker-imbalance part cannot be reproduced on OKX.

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
