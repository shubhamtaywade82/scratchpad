# SOLUSDT Intraday & Swing Long/Short — Strategy Search (v5)

Instrument: Binance USD-M perpetual SOLUSDT. Costs: taker 5 bps/side, adverse slippage 3 bps/side, real funding applied at every 8h event held through. Signals decided on bar close, executed at next bar open.

## 1. Direct decision

- **Swing (4h): adopt as the candidate to paper-trade, not to deploy.** Donchian(40) breakout, symmetric long/short, EMA200 trend gate, 3×ATR(14) initial stop, 3×ATR chandelier trail, 1% equity risk per trade, gross cap 1.5×, no same-direction re-entry after a stop-out until the signal resets.
  It is the only design tested that is positive on the full sample, positive on walk-forward OOS, and inside a parameter plateau. It is **not validated**: 37 trades in 450 days, and the bootstrap 5th percentile is negative.
- **Intraday (15m / 1h): no setup qualifies. Do not trade one.** Every intraday family tested has OOS fold results that flip sign. The local history (73 and 108 days) cannot separate edge from noise.
- **v4 headline is withdrawn.** It came from an engine that understated drawdown, had no protective stop, and chose its gate on the full sample. Section 3 lists the corrections.

## 2. Critical risks / invariants

1. **Sample size.** 4h OOS is 300 days and about 37 trades in total. Intraday has 73–108 days and 20–70 trades. Any Sharpe here has a wide confidence band. Block-bootstrap 5/50/95 for the candidate: −0.86 / +1.38 / +3.26 (tr3).
2. **Regime dependence.** Over the 450-day 4h window SOL buy-and-hold is **−40%**. Over the 4-year 1d window it is **+231%**. The 1d version of the same candidate is flat over four years (Sh −0.03 full sample). The 4h edge may belong to the last ~15 months of tape and not to a durable mechanism.
3. **Parameter fragility.** Trail distance matters more than stop distance. For DON60 at stop 3, Sh is +0.59 / +0.15 / +0.61 for trail 3 / 4 / 5, with no monotone trend (section 4c). For DON40 the plateau holds except trail = 2.0, which fails everywhere.
4. **Selection bias.** The search tested 200–210 configs per timeframe. The full-sample "best" config looks far better than its walk-forward result (4h: IS Sh +1.28 vs WF −0.38; 15m: IS Sh +4.52 vs WF +0.59). Treat every in-sample number as an upper bound.
5. **Shorts.** The v4 claim that shorts "earn their keep" does not hold for DON60 with stops (short avg −0.02%/trade). For DON40 at tr3 shorts are small positive (+0.21%/trade, n = 21). The edge is mostly long-side here.
6. **Gross edge vs costs.** On the in-sample best, gross expectancy is 1.70%/trade (4h) and 1.22%/trade (15m) against about 0.16% round-trip cost. Costs are not the binding constraint on swing. Instability across folds is.
7. **Fill assumptions not modelled.** Stop fills use stop-market with fixed 3 bps slippage. Real slippage in fast markets, partial fills, and order rejection are not simulated. Funding uses the historical rate at each event.
8. **Liquidation.** At a 1.5× gross cap and 3×ATR stops, stops sit far inside the liquidation distance, but this must be verified against the actual margin mode and maintenance rate before live use.

## 3. What v4 got wrong (corrected here)

| Issue in v4 | Effect | Fixed in v5 |
|---|---|---|
| Equity marked only on trade events | Drawdown understated (realized-only) | Mark-to-market every bar (`engine.simulate`, invariant 7) |
| Swing systems had no protective stop | Violates the mandatory stop-loss standard; 4h D40 unstopped MDD −42.6% | ATR stop at entry, chandelier trail, gap-through fills (invariants 2–5) |
| EMA200 gate chosen on full sample | +53.7% full-sample result is in-sample | Gate is one of the walk-forward options; not selected on OOS |
| Shorts described as profitable | Not supported on the stopped version | Long/short split reported for every design |

## 4. Results

All figures net of costs and funding. Sh is annualized per-bar Sharpe. MDD on mark-to-market equity.

### 4a. Walk-forward with per-fold selection (`research/search.py`)

Train window picks one config by train Sharpe; the next test window is traded with it. Stitched OOS.

| TF | Bars | Folds × test | OOS total | OOS Sh | MDD | Boot 5/50/95 |
|---|---|---|---|---|---|---|
| 4h | 2700 | 5 × 60 d | −13.9% | −0.38 | −35.0% | −2.72 / −0.40 / +1.80 |
| 1d | 1500 | 6 × 6 m | +104.2% | +0.69 | −82.4% | −0.28 / +0.67 / +1.66 |
| 1h | 2600 | 5 × 15 d | +13.7% | +1.84 | −15.8% | −1.48 / +1.68 / +5.33 |
| 15m | 7000 | 7 × 7.5 d | +2.6% | +0.59 | −24.7% | −3.86 / +0.62 / +4.71 |

Selected configs change fold to fold (for example TSMOM120, TSMOM20, DON120, ST10x3, DON24). The chosen family changes almost every fold, so no single selected rule is being validated. The 1d result runs at 1× notional with no stop, so its −82% drawdown makes it unusable as it stands.

### 4b. Fixed designs, risk-sized (`research/ensemble.py`), no selection

| Design | TF | Full Sh | Full MDD | WF OOS | Positive folds |
|---|---|---|---|---|---|
| VOTE(20,40,60,80) EMA200, stop3 trail3, 1% | 4h | +0.33 | −9.5% | −2.1% | 1/5 |
| DON60 EMA200, stop3 trail3, 1% | 4h | +0.59 | −4.7% | +1.7% | 2/5 |
| VOTE(20,40,55,80) EMA200, stop3 trail3, 1% | 1d | +0.04 | −3.9% | −0.7% | 3/6 |
| VOTE(24,48,72,120) MTF-4h EMA200, stop3 trail3, 1% | 1h | −0.35 | −5.0% | −1.1% | 2/5 |
| DON72 MTF-4h EMA200, stop3 trail3, 1% | 1h | +1.14 | −4.7% | +3.6% | 2/5 |
| VOTE(96,192,384) MTF-1h EMA200, stop3 trail3, 1% | 15m | −2.11 | −6.7% | −2.4% | 2/7 |

In the 4h vote design, 28 of 51 trades (55%) ended at a stop. That is why the stop and trail choice dominates the outcome.

### 4c. Stop / trail sensitivity (`research/sensitivity.py`), full-sample Sh

DON40 + EMA200, 4h, risk 1%:

| sl \ trail | None | 2.0 | 3.0 | 4.0 | 5.0 |
|---|---|---|---|---|---|
| 2.0 | +1.39 | −0.51 | +1.47 | +0.97 | +1.41 |
| 3.0 | +1.34 | −0.50 | **+1.56** | +0.96 | +1.35 |
| 4.0 | +1.34 | −0.50 | +1.55 | +0.94 | +1.38 |
| 5.0 | +1.35 | −0.50 | +1.55 | +0.93 | +1.37 |

Plateau: positive everywhere except trail = 2.0.

DON60 + EMA200, 4h, risk 1%: trail None +1.11, trail 2.0 −1.45, trail 3.0 +0.59, trail 4.0 +0.15, trail 5.0 +0.61 (sl3). This is a spike. Not a candidate.

### 4d. Candidate fold detail (`research/results/candidates.txt`)

| Config (4h, DON40 + EMA200, sl3) | Full Sh | Full MDD | Trades L / S | WF total | Folds + | Boot 5/50/95 |
|---|---|---|---|---|---|---|
| trail 3.0 (**candidate**) | +1.56 | −4.2% | 16 (+0.55%) / 21 (+0.21%) | +8.4% | 3/5 | −0.86 / +1.38 / +3.26 |
| trail 5.0 | +1.35 | −5.9% | 16 (+0.74%) / 21 (+0.15%) | +9.8% | 3/5 | −0.95 / +1.18 / +3.08 |
| trail None | +1.34 | −6.1% | 16 (+0.77%) / 21 (+0.12%) | +10.1% | 3/5 | −0.92 / +1.23 / +3.08 |
| trail 4.0 | +0.96 | −6.0% | 16 (+0.40%) / 21 (+0.15%) | +4.2% | 3/5 | −1.44 / +0.60 / +2.55 |

Same design on 1d (4 years): full Sh −0.03, MDD −3.7%, WF −0.7%, 3/6 folds positive. On the last 450 days of 1d only: Sh +0.43, but 6 trades, so that is not independent support.

### 4e. Intraday gross vs net (in-sample best, not selected out of sample)

- 1h: gross +0.75%/trade, net +0.60%/trade (66 trades), but WF folds flip sign.
- 15m: gross +1.22%/trade, net +1.06%/trade (38 trades), WF net +0.09%/trade.

The in-sample figures are selection-inflated. The out-of-sample sign instability is the core finding, not cost.

## 5. Implementation

Code is in `research/`:

- `engine.py`: causal simulator. Invariants 1–8 are documented at the top of the file. Mark-to-market, funding, gap-through and intrabar stops, trailing ratchet, stop-out re-entry block, risk-based sizing with cap.
- `search.py`: walk-forward search over Donchian, Supertrend and TSMOM families (about 200 configs per TF).
- `ensemble.py`: fixed designs with risk sizing and majority-vote ensembles, no selection.
- `sensitivity.py`: stop / trail surface, per-fold candidate report, long/short split and buy-and-hold.
- `test_engine.py`: 23 invariant tests (no-lookahead, gap and intrabar stops, re-entry block, trailing ratchet, funding sign, cost accounting, risk sizing cap, window flatten, MTM drawdown, indicator and gate timing, data validation).

Operating rules for the candidate (proposed; not backtested as a live process):

- Entry: 4h close breaks the prior 40-bar high (long) or low (short) with EMA200 agreeing. Order executes at next open.
- Initial stop: entry ∓ 3×ATR(14) at signal bar. Size: qty = 1% × equity / (3×ATR). Gross ≤ 1.5× equity.
- Trail: chandelier 3×ATR from the bar's extreme, ratchet only.
- After a stop-out, no same-direction entry until the Donchian state leaves that direction.
- Daily loss > 3% of equity: no new entries for 24h. Equity drawdown > 10%: halve risk per trade. These are proposed and must be backtested before live use.

## 6. Verification

Run from the repo root:

```
python3 -m unittest research.test_engine -v        # expect: Ran 23 tests ... OK
python3 -m research.search 4h 1d 1h 15m            # saved to research/results/search-wf.txt
python3 -m research.ensemble 4h 1d 1h 15m          # research/results/fixed-designs.txt
python3 -m research.sensitivity                    # research/results/sensitivity.txt
```

Expected: tests pass; the 4h candidate line in `candidates.txt` reads `full Sh +1.56 MDD -4.2% ... WF total +8.4%`. Any change to these numbers means the data file or engine changed, and the results must be regenerated.

Data-fetch fix: `fetch-intraday.mjs` requested 7,000 15m bars (73 days) and 2,600 1h bars (108 days) despite its comments saying ~2 and ~3 years. Limits set to 70,000 and 26,000 bars. **This was not run here**: Binance returns HTTP 451 (geo-restricted) from this environment. Run it from a host with Binance access, then rerun the commands above. Multi-year intraday data is the only thing that can settle the intraday question.

## 7. Next steps

1. **Forward paper-trade the 4h candidate** (DON40 + EMA200, sl3, tr3, risk 1%) on live data for at least 6 months and 30 trades. Pre-register kill rules before starting: stop if rolling 90-day Sharpe < 0, or realized MDD > 10%, or any single trade loses more than 2× its planned risk.
2. **Run the fetch on a host with Binance access**, then rerun `research/` on 2–3 years of 1h and 15m data. Only then reconsider an intraday system.
3. **Model slippage on stops** from the paper-trade fills, and replace the fixed 3 bps assumption with the measured distribution.
4. **Check the 1d-vs-4h disagreement** with longer 4h history once step 2 provides it.
