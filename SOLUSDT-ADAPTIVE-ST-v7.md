# SOLUSDT — Adaptive Supertrend (v7)

Instrument: Binance USD-M SOLUSDT perpetual, isolated margin. Data: kline OHLCV. Costs: taker 5 bps/side, adverse slippage 3 bps/side, real funding at each 8h event held through, liquidation at the liquidation price. Signals decided at bar close, executed at next open. Screen: 5× margin ceiling, risk 1% of equity per trade, 3×ATR(14) stop, walk-forward OOS (same windows as v5/v6).

## 1. Direct decision

1. **Use the volatility-adaptive Supertrend, not the performance-adaptive one.** The band multiplier is interpolated between m_lo and m_hi by the trailing percentile rank of ATR% over L bars: calm regimes get tighter bands, volatile regimes wider ones.
2. **Strongest on 1h.** 8 of 8 cells positive (walk-forward +12% to +17%, 47–64 trades each, median Sharpe +2.60). Fixed-factor Supertrend on the same bars: 4 of 4 positive, median Sharpe +1.44. Flipping the direction turns all 8 negative. A 6-bar delay holds; a 12-bar delay fails. **Paper-trade it** with the rules below.
3. **Modest on 4h.** 6 of 8 cells positive, median Sharpe +0.42 (fixed: −0.11). The best cells need the 1.5–4.0 range with L=100. The ATR-20 cell's 6-bar delay gives +0.1%, so the timing signature is weaker there.
4. **No gain on 1d** at 1× (fixed median Sharpe +0.74, adaptive +0.72). At 5×, daily results are contaminated by stop infeasibility (section 3d) and are excluded.
5. **Not validated on 15m** (3 of 8 volatility cells positive, median Sharpe +0.21).
6. **Performance-adaptive rejected.** Picking the instance with the best recent return churns direction (60–190 trades) and loses on 1h and 15m. On 1d it is no better than fixed.

## 2. Design (causal)

- **Volatility-adaptive:** `ap[k] = ATR14[k] / close[k]`. `rank[k]` = share of the last L values of `ap` at or below `ap[k]`. `mult[k] = m_lo + (m_hi − m_lo) · rank[k]`. Standard Supertrend bands and flip rules with `mult[k]`.
- **Performance-adaptive:** three Supertrends with multipliers (2, 3, 4). Each keeps an EWMA (span W) of its held-direction return. At each close, the instance with the highest score sets the direction, and ties go to the middle multiplier.
- **Baseline:** `engine.supertrend_sig`, fixed multiplier, same ATR period.

Causality is tested directly: truncating the series at bar 250 must not change any signal before bar 250 (`research/test_engine.py`, class `AdaptiveST`).

## 3. Results (walk-forward OOS, `research/results/adaptive-st-*.txt`)

### 3a. 1h (5×, 3-ATR stop)

| Family | Positive | Median Sharpe | Median total | Trades |
|---|---|---|---|---|
| fixed (×2, ×3, ×4) | 4/4 | +1.44 | +7.4% | 34–77 |
| **volatility-adaptive** | **8/8** | **+2.60** | **+16.2%** | 47–64 |
| performance-adaptive | 2/6 | −0.42 | −2.9% | 124–191 |

Best adaptive cells: vol p20 L100 range 2.0–4.0: +17.2%, Sharpe 2.98, MDD −10.2%, 47 trades. Vol p10 L100 1.5–4.0: +15.9%, Sharpe 2.53, MDD −8.5%, 57 trades. Folds positive 2–4 of 5, so the edge is not consistent fold by fold.

Caveat: fixed ×2 (+11.4%, Sharpe 2.15, 77 trades) is also strong. The adaptive family's advantage over the best fixed cell is modest; its advantage over ×3 and ×4 is larger.

### 3b. 4h (5×, 3-ATR stop)

| Family | Positive | Median Sharpe | Median total |
|---|---|---|---|
| fixed (×2, ×3, ×4) | 2/4 | −0.11 | −1.5% |
| **volatility-adaptive** | **6/8** | **+0.42** | **+3.7%** |
| performance-adaptive | 4/6 | +0.18 | +1.2% |

Best volatility cells: p10 L100 1.5–4.0 +12.8% (Sharpe 1.25, 68 trades); p20 L100 1.5–4.0 +13.3% (Sharpe 1.30, 68 trades). The L=200 cells are weaker, with p10 L200 2.0–4.0 at −10.5%.

### 3c. 15m (5×, 3-ATR stop)

Volatility-adaptive: 3 of 8 positive, median Sharpe +0.21. Fixed: 2 of 4, median −0.44. Performance-adaptive: 0 of 6, median Sharpe −4.9. Not a candidate at this sample size (73 days).

### 3d. 1d

- **At 1× (no stop infeasibility):** fixed 4/4 positive, median Sharpe +0.74; volatility 8/8, +0.72; performance 6/6, +0.66. No advantage for adaptation. The performance family's flipped version is near zero (median −0.4%), which points to drift rather than direction.
- **At 5× (excluded):** a 3-ATR stop on daily bars is about 20% of price, which exceeds the 15.6% buffer at 5× (`leverage.txt`). The engine skips 20–97 entry episodes per cell, leaving 5–21 trades. The "all positive" 5× result is driven by which low-volatility episodes survive the feasibility rule, not by the signal. Excluded.

## 4. Null checks (`research/results/adaptive-st-null-*.txt`)

Flipped = inverted direction. Delay = the same signal lagged by d bars (causal, `engine.delay_sig`).

| Cell | Original | Flipped | Delay 6 | Delay 12 |
|---|---|---|---|---|
| 4h vol p10 L100 1.5–4.0 | +12.8% (Sh +1.25) | −9.9% (Sh −1.66) | +10.3% (Sh +1.08) | −3.7% (Sh −0.34) |
| 4h vol p20 L100 1.5–4.0 | +13.3% (Sh +1.30) | −10.1% (Sh −1.73) | +0.1% (Sh +0.07) | −2.1% (Sh −0.19) |
| 1h vol p10 L100 1.5–4.0 | +15.9% (Sh +2.53) | −12.1% (Sh −4.46) | +17.7% (Sh +2.86) | −3.4% (Sh −0.47) |
| 1h vol p20 L100 1.5–4.0 | +16.7% (Sh +2.88) | −12.2% (Sh −4.64) | +14.8% (Sh +2.59) | −2.3% (Sh −0.32) |

Interpretation: flipping the direction is strongly negative, so the signal carries directional information. A 6-bar delay does not hurt on 1h, which is consistent with a slow trend-following signal rather than precise timing. Twelve-bar delays turn negative on both timeframes.

**Correction carried over from v6:** the earlier null scripts used a shift helper that read future bars for negative shifts. Those runs produced +65% to +143% and were invalid. They are removed. The helper now rejects negative delays, and the nulls above use causal delays only.

## 5. Risks and invariants

1. **One regime window on 1h.** 108 days. The 1h result could reflect the recent trend rather than a durable edge.
2. **Selection.** 18 cells per timeframe. The volatility-adaptive mechanism was specified in advance, but the range (1.5–4.0 or 2.0–4.0), L and ATR period were chosen from a small grid. Treat the cell-level Sharpe as optimistic.
3. **Adaptive does not clearly beat the best fixed cell.** On 1h, fixed ×2 is comparable (Sharpe 2.15 vs 2.53–2.98).
4. **Stop feasibility.** 3-ATR stops fit below 28× on 1h and below 12.3× on 4h, so 5–10× margin is feasible. At 1d they are not feasible above about 4×.
5. **Liquidation** uses the assumed 0.5% maintenance margin (see v6). Confirm before live use.
6. **Fold consistency.** Positive folds per cell are 2–4 of 5 on 1h. Not every window contributes.

## 6. Implementation

- `research/adaptive_st.py`: `supertrend_dyn`, `vol_adaptive_st_sig`, `perf_adaptive_st_sig`, screen, flip/delay null (`python3 -m research.adaptive_st null 1h`).
- `research/engine.py`: `delay_sig` (causal delays only).
- `research/nulltest.py`: taker-lead nulls, now using causal delays.
- `research/test_engine.py`: 42 tests, including causality for both adaptive variants, the dynamic Supertrend matching the engine with constant multiplier, and the delay helper.

## 7. Verification

```
python3 -m unittest research.test_engine -v                 # expect: Ran 42 tests ... OK
python3 -m research.adaptive_st 4h 1d:1                     # 4h at 5x, 1d at 1x (research/results/adaptive-st-swing.txt, -1d-1x.txt)
python3 -m research.adaptive_st 1h:5 15m:5                  # research/results/adaptive-st-intraday.txt
python3 -m research.adaptive_st null 4h                     # research/results/adaptive-st-null-4h.txt
python3 -m research.adaptive_st null 1h                     # research/results/adaptive-st-null-1h.txt
python3 -m research.nulltest                                # research/results/nulltest.txt
```

Expected: the 1h `vol p20 L100 1.5-4.0` cell reads `WF tot +16.7%  Sh +2.88  n 56` at 5×.

## 8. Next steps

1. **Forward paper-trade the 1h volatility-adaptive Supertrend**, p20 L100 1.5–4.0 (or the 2.0–4.0 range) with the 3-ATR stop, risk 1%, 5× margin ceiling. Run fixed ×2 in parallel as the benchmark. Kill criteria, set before the start: rolling 90-day Sharpe below zero, drawdown beyond 10%, or any loss beyond 2× planned risk.
2. **Fetch multi-year 1h data** from a host where Binance is reachable (this sandbox gets HTTP 451) and rerun the 1h screen. This is the test that decides whether the 1h result holds beyond one regime.
3. **Run the leverage study on the adaptive cell** (`research/leverage.py` pattern) to confirm the 5–10× band before any live sizing.
