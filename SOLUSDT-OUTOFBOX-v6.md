# SOLUSDT — Out-of-Box Intraday & Swing Search, and 5x–15x Leverage (v6)

Instrument: Binance USD-M SOLUSDT perpetual, isolated margin. Data: kline OHLCV plus `takerBuyBaseVolume` (present on every kline row). Open interest, long/short ratios and other non-OHLCV feeds are **not** used. Funding is used only as a cost. Costs: taker 5 bps/side, adverse slippage 3 bps/side, real funding at each 8h event held through, liquidation at the liquidation price with slippage. Signals decided at bar close, executed at next open.

## 1. Direct decision

1. **Intraday lead (1h): aggressor-absorption, paper-trade only.** Long when the volume-weighted taker imbalance over 6 bars is at least 2σ below its trailing 100-bar mean and the bar closes up (sellers hit the bid and got absorbed). Short is the mirror. Hold 4 bars. Initial stop 3×ATR(14). Risk 1% of equity per trade. Margin ceiling 10×. Evidence is real but thin: 22 out-of-sample trades, walk-forward +4.3%, 4/5 folds positive, and it behaves like a directional signal under both null checks (section 3c). Its trades are 16 long and 6 short, so it is long-biased.
2. **Swing lead (4h): aggressor-absorption as a second, paper-only candidate** (m=18, 2σ, hold 4 bars, 3×ATR stop, 1% risk). Walk-forward +3.9% at 10×, Sharpe 1.86, MDD −1.7%, 24 trades. Keep the v5 Donchian(40)+EMA200 candidate as the primary swing system; it is the only design with a stable parameter plateau.
3. **Dropped:** liquidity-sweep fade, variance-ratio regime switching, and the 2-state Gaussian HMM. All three have negative breadth on every timeframe.
4. **No 15m setup qualifies.**
5. **Leverage:** use 5×–10× as an isolated-margin ceiling, never as the sizing rule. Size by risk (1% of equity per trade), which gives an effective leverage of 0.2×–0.8×. Constant-notional leverage at 5×–15× is ruinous on 4h and 1d. 15× is only feasible with stops of about 2.4 ATR or less on 4h, and on 1d 5×–15× is incompatible with ATR stops.

## 2. Critical risks and invariants

1. **Maintenance margin rate is an assumption (0.5%).** Liquidation distance is `1/lev − mmr`. Binance raises the maintenance rate with notional tier, which shrinks the liquidation distance. Fees and funding also pull liquidation closer; neither is modelled. Confirm the tier for your notional from the leverage-bracket endpoint before any live use.
2. **Gap risk.** Gaps through the liquidation level happened (2 liquidations at 15× and 1 at 10× on 4h DON40 at 2 ATR). The engine fills at the open, and equity floors at zero (ruin).
3. **Constant-notional leverage is the dominant risk.** On 4h DON40 at 2 ATR, 5× fixed gives MDD −87.5% and P(MDD worse than −30%) = 100%. Risk-sized trading at the same leverage gives MDD −7.5%. The leverage setting is the same in both; the sizing rule decides the outcome.
4. **Stop feasibility rules out trades.** A stop beyond `0.8 × liquidation distance` skips the entry. At 15× on 4h DON40 with 3 ATR, 21 of 29 episodes are skipped and only 8 trades remain.
5. **Small samples.** The leads have 22–25 trades. Block-bootstrap intervals are wide (1h: 5th percentile −0.95 Sharpe, median +3.68).
6. **Selection.** The screen covered 28 cells per timeframe across 4 families, plus a leverage grid. Leads were chosen by family-level breadth and null tests, not by the top cell. The headline Sharpe figures are still optimistic.
7. **Single-window dependence.** The 1h lead rests on 108 days, and the 4h lead on 450 days with a −40% SOL drawdown inside it.
8. **v5 correction.** The v5 engine let isolated 1× positions survive liquidation. The 1d walk-forward figures in v5 were invalid and are corrected in the v5 document. The 4h, 1h and 15m results are unaffected.

## 3. Results

### 3a. Screen breadth (`research/results/ideas-screen-*.txt`)

Screen at 5×, risk 1% per trade, stop 3×ATR (structural for sweep). Each cell is a walk-forward OOS run with fixed parameters. "Positive" means WF total > 0.

| Family | 1h | 15m | 4h | 1d |
|---|---|---|---|---|
| Liquidity sweep fade | 0/6 (median Sh −3.69) | 0/6 (−8.28) | 1/6 (−0.52) | 2/6 (−0.23) |
| Taker imbalance (continuation + absorption) | **6/12 (+0.16)** | 2/12 (−5.07) | **6/12 (+0.05)** | 5/12 (−0.25) |
| Variance-ratio regime switch | 0/8 (−5.58) | 0/8 (−13.06) | 1/8 (−0.55) | 3/8 (−0.17) |
| 2-state Gaussian HMM | 0/2 (−5.44) | 0/2 (−9.92) | 0/2 (−3.13) | 0/2 (−1.25) |

Taker imbalance is the only family with breadth near 50% on the timeframes with enough data. Its median Sharpe is still about zero, so breadth alone does not establish an edge.

Taker imbalance is z-scored on its trailing 100-bar mean and standard deviation. Raw imbalance on SOL is tiny on 4h and 1d (|imbalance| is rarely above 0.1), so fixed thresholds never fired in the first run. The σ-based version is the one reported.

### 3b. Leads

| Lead | TF | Sizing / stop | WF OOS total | Sharpe | MDD | Trades L/S | Folds + | Bootstrap 5/50/95 (screen) |
|---|---|---|---|---|---|---|---|---|
| taker-absorb m6 z2 T4 | 1h | risk 1%, 3 ATR, 5× | +4.3% | +3.82 | −1.4% | 16/6 | 4/5 | −0.95 / +3.68 / +7.37 |
| same, 2 ATR, 7× | 1h | risk 1%, 2 ATR | +7.0% | +4.29 | −1.6% | 16/6 | — | — |
| taker-absorb m18 z2 T4 | 4h | risk 1%, 3 ATR, 10× | +3.9% | +1.86 | −1.7% | — | 3/5 (at 5×) | −0.79 / +1.33 / +3.41 (at 5×) |
| DON40 + EMA200 (primary swing) | 4h | risk 1%, 2 ATR, 10× | +14.2% | +1.26 | −7.5% | — | — | — |

The 1h figure is the lead's screen configuration. The 2-ATR row is shown for the leverage study. Sharpe values above 3 come from 22 trades and should not be read as expected performance.

### 3c. Null checks (`research/results/nulltest.txt`)

If the result were not directional, flipping the sign or delaying the signal would leave it positive.

| Lead | Original | Direction flipped | Delayed 6 bars | Delayed 12 bars |
|---|---|---|---|---|
| 1h taker-absorb m6 z2 T4 | +4.3% (Sh +3.82) | −6.5% (Sh −6.43) | −3.1% (Sh −2.17) | −1.2% (Sh −1.41) |
| 4h taker-absorb m18 z2 T4 | +3.9% (Sh +1.86) | −4.2% (Sh −2.01) | −2.2% (Sh −0.93) | −2.1% (Sh −0.98) |

Both leads fail the nulls. Flipping direction turns the result negative, and any delay does too. This is evidence that the signal carries directional information. It is not evidence of a profitable edge: the sample is still small.

**Correction:** an earlier version of this table reported "advanced" (negative-shift) runs. Those read future bars, so they were invalid and are removed. The nulls now use causal delays only (`engine.delay_sig` rejects negative delays).

### 3d. Leverage geometry (`research/results/leverage.txt`)

Isolated margin, mmr 0.5% (assumed), entry buffer 0.8. Liquidation distance = `1/lev − mmr`. Max stop = `0.8 × liquidation distance`. Max leverage for a k-ATR stop = `1 / (k × ATR% / 0.8 + mmr)`.

| TF | Median ATR% | Lev | Liquidation distance | Max stop (ATR) | Max lev for 2-ATR stop | Max lev for 3-ATR stop |
|---|---|---|---|---|---|---|
| 1h | 0.80% | 5 / 10 / 15 | 19.5% / 9.5% / 6.2% | 19.4 / 9.5 / 6.1 | 40× | 28.5× |
| 4h | 2.03% | 5 / 10 / 15 | 19.5% / 9.5% / 6.2% | 7.7 / 3.75 / 2.43 | 18× | 12.3× |
| 1d | 6.58% | 5 / 10 / 15 | 19.5% / 9.5% / 6.2% | 2.37 / 1.15 / 0.75 | 5.9× | 4.0× |

Reading the table: 5×–15× is usable with 2–3 ATR stops on 1h. On 4h, 5×–12× works with 3 ATR, and 15× requires stops of about 2.4 ATR or less. On 1d, ATR stops above about 4× are infeasible, so 5×–15× daily swing needs wider structural stops with much smaller size, or no ATR stop at all.

### 3e. What leverage does to the results

**DON40 + EMA200, 4h, 2-ATR stop** (`leverage.txt`):

| Lev | Risk 1% sizing: WF / Sh / MDD / liq / skip / effLev | Fixed notional: WF / MDD / P(MDD < −30%) |
|---|---|---|
| 1× | — | +8.5% / −29.0% / 52% |
| 5× | +14.7% / +1.31 / −7.5% / 0 / 0 / 0.28× | −55.4% / −87.5% / 100% |
| 10× | +14.2% / +1.26 / −7.5% / 1 / 1 / 0.28× | −99.7% / −100% / 100% |
| 15× | +16.4% / +1.44 / −7.8% / 2 / 4 / 0.29× | −100% / −100% / 100% |

Risk-sized returns are flat across 5×–15×. Leverage changes which stops are feasible and how many gap liquidations occur, not the return. Fixed notional is ruinous at every level above 1×.

**Same, 3-ATR stop:** risk-sized gives +10.1% / +10.2% / +10.9% at 5× / 10× / 15×. At 15×, 21 of 29 episodes are skipped and only 8 trades are taken, so 15× is not a meaningful test of this system.

**Taker-absorb 4h lead, 3-ATR:** risk 1% gives +3.0% (5×), +3.9% (10×), +0.8% (15×, 12 skipped). Fixed notional at 5× gives +65.3% but MDD −49.0% and P(MDD < −30%) = 85%.

**Taker-absorb 1h lead, 3-ATR:** risk 1% gives +4.3% at 5×–10× and +4.6% at 15×, with MDD −1.4% and effective leverage 0.53×. Fixed notional at 5× gives +14.8% and MDD −19.3%, P(MDD < −30%) = 16%. This is the one setup where constant 5× is survivable, because the 1h stop is small in percentage terms. Risk sizing still has a far lower drawdown.

**Rule of thumb** (both sizing modes, derived from the engine):
- Constant notional: each stop costs `lev × stop%` of equity.
- Risk sizing: each stop costs `risk%` of equity. Effective leverage is `risk% / stop%`.

For a 1% risk and a 3-ATR stop on 4h (stop ≈ 6%), effective leverage is about 0.17×, which matches the measured 0.2×.

## 4. Implementation

- `research/engine.py`: causal simulator, now with isolated-margin liquidation, leverage-dependent entry buffer, structural stops, ruin floor, and one-attempt-per-episode entries. Invariants 1–9 are documented at the top.
- `research/ideas.py`: sweep fade, taker imbalance (continuation and absorption), variance-ratio regime, 2-state Gaussian HMM with fold-wise fit and causal filter, and the screen.
- `research/leverage.py`: liquidation geometry, leverage × sizing grid with block-bootstrap drawdown distribution.
- `research/nulltest.py`: direction-flip and causal-delay nulls for the taker leads.
- `research/test_engine.py`: 36 tests, including liquidation, gap liquidation, buffer skip, structural stop size and side, ruin, the HMM filter, and the sweep and taker definitions.
- Regression against v5: the 4h, 1h and 15m walk-forward, the fixed-design and the sensitivity outputs are byte-identical to the v5 results. Only the 1d walk-forward changed (correction above).

Core taker-absorption definition (causal, executed at the next open):

```
imb_m[k] = sum_{j in last m bars}(2*takerBuy_j - vol_j) / sum_{j in last m bars} vol_j
z[k]     = (imb_m[k] - mean(imb_m, last 100)) / std(imb_m, last 100)
long  state for T bars if z[k] < -theta and close[k] > open[k]   (sellers absorbed)
short state for T bars if z[k] >  theta and close[k] < open[k]   (buyers absorbed)
stop  = entry -/+ sl_mult * ATR14[k];  risk sizing 1% of equity;  notional cap = lev * equity
```

## 5. Verification

```
python3 -m unittest research.test_engine -v          # expect: Ran 36 tests ... OK
python3 -m research.ideas 4h 1d                      # research/results/ideas-screen-swing.txt
python3 -m research.ideas 1h 15m                     # research/results/ideas-screen-intraday.txt
python3 -m research.leverage                         # research/results/leverage.txt
python3 -m research.nulltest                         # research/results/nulltest.txt
```

Expected: the 1h absorption cell `taker-absorb m6 z2.0 T4` reads `WF tot +4.3%  Sh +3.82  n 22` at 5×/3-ATR. Flipped-direction and delayed runs are negative in `nulltest.txt`.

## 6. Next steps

1. **Forward paper-trade both leads for at least 60 trades each.** Use the exact rules above. Kill criteria, set before the start: rolling 90-day Sharpe below zero, realized drawdown beyond 10%, or any single loss beyond 2× planned risk.
2. **Confirm the maintenance-margin tier** for your expected notional. Replace the 0.5% assumption, then rerun `research/leverage.py`.
3. **Get multi-year 1h and 4h data.** Run `fetch-intraday.mjs` from a host where Binance is reachable (it returns HTTP 451 here). Then rerun the screens. This is the only way to test the 1h lead beyond 108 days.
4. **Test the long/short imbalance.** The 1h lead is 16 long and 6 short. Confirm the short side on fresh data before sizing shorts equally.
5. **Keep the 10× margin ceiling for swing and 5×–10× for intraday.** Do not use 15× on 1d, and do not use 15× on 4h with 3-ATR stops.
