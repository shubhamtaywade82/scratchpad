# SOLUSDT — The Six Strategies from the Funding/Perp Proposal, Tested (v11)

Each idea was tested with the data that could be reached from this environment. Binance returns HTTP 451 and Bybit returns HTTP 403 (country block); neither was used around. OKX (www.okx.com/api/v5), Hyperliquid (api.hyperliquid.xyz) and Coinbase/Kraken spot answer normally and were used. Every test is pre-declared, uses only data available at the decision time, and reports its own sample size.

## 1. Verdicts

| # | Strategy | Data | Result | Verdict |
|---|---|---|---|---|
| 1 | Funding carry, delta-neutral (short perp + long spot, conditional on funding) | Binance perp funding and prices (4 y), OKX spot (4 y) | Funding captured +15.1% over 4 y gross; net **+3.5%/yr per notional, +1.7%/yr per capital** after placeholder costs. Basis term unreliable (cross-venue tracking error 13% annualised). | **Not supported** at the proposed 15–25%. Funding capture is small. |
| 2 | Funding mean reversion (directional) | Binance 1d (4 y); Hyperliquid 1d and 4h (2–3 y) | Binance 1d: 7/8 cells positive, flip negative, returns −0.5% to +2.2%. Hyperliquid 1d: 5/8 positive, flips inconsistent. Hyperliquid 4h: 2/8 positive, flips positive 5/8. | **Does not replicate across venues.** |
| 3 | Open-interest divergence | OKX OI 1H (30 d) and 1D (180 d) | No category reaches |t| = 2. Largest: |t| = 1.53 (1D, price down and OI down). | **No evidence.** |
| 4 | Basis trade (short delivery future, long perp, when premium > 15%/yr) | OKX SOL delivery futures (11 expired, 4 with candle history) | 4 traded: net after funding estimate +0.56% to +4.47% per contract (16–82 days), about 4–22%/yr. Mean +1.72%. | **Plausible, untested at scale.** Four contracts only. |
| 5 | Stat-arb pair SOL / AVAX (Engle–Granger gated) | OKX SOL and AVAX perps, hourly (4 y) and daily | Hourly: cointegrated in 13 of 55 folds; WF total −20.3%, Sharpe −0.71, MDD −22.8%. Daily: cointegrated in 0 of 15 folds. | **Fails.** Engine validated on synthetic cointegrated data (+114%). |
| 6 | Liquidation-cascade hunting | Needs historical liquidation data | OKX liquidation endpoint returns only the most recent records (one at test time). Hyperliquid and Binance have no reachable history. Heatmaps (Coinglass, Hyblock) need paid access or keys. | **Not testable here.** |

Bottom line: no strategy from the proposal shows an edge that survives its own test. The basis trade is the only one with positive results, and it rests on four contracts.

## 2. Data limits (these shape every verdict)

- **Binance:** 4 years of perp prices and funding in the repo, but 1h prices only cover 108 days and 4h only 450. No reachable spot data.
- **OKX:** candles 4 years (SOL and AVAX, perp and spot). Funding history only about 100 days (the public endpoint stops there). Open interest only 30 days (1H) and 180 days (1D); `begin` is rejected. Delivery contracts: 11 found; 7 of them have no candle history after settlement ("already settled").
- **Hyperliquid:** funding 3.4 years (hourly settlements). Candles 1d from 2023-05, 4h from 2024-07, 1h only the last 208 days. No SOL spot.
- **Cross-venue:** the funding carry combines Binance funding with OKX spot. Daily return correlation between Binance perp and OKX spot is 0.990, but the annualised tracking error is 13.3%. Part of that is cross-venue noise, which this data cannot separate from real hedge risk.

## 3. Results

### 3.1 Funding carry (`research/results/carry-test.txt`)

Daily, four years. Position while held: short perp, long spot, equal notional. Enter when the latest settled funding exceeds the threshold; exit when it falls below the exit level. Costs: 4 fills × 5 bps per cycle (placeholder).

| Enter / exit (per 8h) | Net per notional | Per year, notional | Per year, capital (2N) | Cycles | In market | Funding / basis / costs |
|---|---|---|---|---|---|---|
| always on | −39.0% | −9.5% | −4.8% | — | 100% | −23.4% / −15.5% / −0.1% |
| > 0.010% / < 0.000% | +14.3% | +3.5% | +1.7% | 6 | 18% | +15.1% / +0.4% / −1.2% |
| > 0.030% / < 0.010% | +11.8% | +2.9% | +1.4% | 3 | 11% | +12.1% / +0.3% / −0.6% |
| > 0.050% / < 0.010% | +9.1% | +2.2% | +1.1% | 2 | 8% | +9.4% / +0.2% / −0.4% |

Funding is what the conditional rule captures, and it is small. The basis line is dominated by cross-venue error and should not be read as a result. The proposal's 15–25% is not reached over four years.

### 3.2 Funding mean reversion (`research/results/funding-mr-1d.txt`, `research/results/fundmr-hl.txt`)

Signal: standard or robust (median/MAD) z-score of the latest settlement against 720 or 2160 trailing settlements. Short above +thr, long below −thr, exit at |z| < 0.5. 1% risk, 3-ATR stop, walk-forward.

| Venue / timeframe | Cells | Positive WF | Flipped positive | Range of WF totals |
|---|---|---|---|---|
| Binance 1d (4 y, 1× lev) | 8 | 7 | 0 | −0.5% to +2.2% |
| Hyperliquid 1d (3.4 y, 1×) | 8 | 5 | 4 | −2.0% to +3.6% |
| Hyperliquid 4h (2.2 y, 5×) | 8 | 2 | 5 | −9.4% to +2.0% |

Binance 1d is the only setting where flipping consistently loses. The same design does not hold on Hyperliquid, and on its 4h series the flips win more often than the original. Trade counts are 18–123, and returns are small.

### 3.3 Open-interest divergence (`research/results/oi-test.txt`)

Four categories of the price change (up/down) × open-interest change (up/down) over each OI step. Forward return is the next step's price change.

| Window | Category | N | Mean forward return | t-stat |
|---|---|---|---|---|
| 1H (30 d) | P+ OI+ | 191 | +0.053% | +1.20 |
| 1H | P+ OI− | 158 | −0.036% | −0.86 |
| 1H | P− OI+ | 184 | +0.012% | +0.25 |
| 1H | P− OI− | 185 | +0.006% | +0.13 |
| 1D (180 d) | P+ OI+ | 61 | +0.242% | +0.66 |
| 1D | P+ OI− | 33 | −0.384% | −0.87 |
| 1D | P− OI+ | 28 | −0.662% | −1.30 |
| 1D | P− OI− | 56 | +0.757% | +1.53 |

No category has |t| ≥ 2. The funding column from the proposal could not be included, because OKX funding covers only about 100 days.

### 3.4 Basis trade (`research/results/basis-test.txt`)

Rule (pre-declared): when the future's annualised premium to the perp is at least 15% and at least 7 days remain, short the future and long the perp; hold to settlement. Costs: 20 bps per cycle. Perp funding is estimated from Binance funding and shown separately, with the sign corrected so that a long perp pays positive funding.

| Contract | Entry (UTC) | Premium at entry | Days held | Gross | Net | Funding estimate | Net after funding |
|---|---|---|---|---|---|---|---|
| SOL-USD_UM-260807 | 2026-06-30 | +16.4% | 38 | +1.36% | +1.16% | −0.30% | +0.86% |
| SOL-USD_UM-260814 | 2026-06-23 | +15.9% | 52 | +1.15% | +0.95% | −0.39% | +0.56% |
| SOL-USD_UM-260828 | 2026-08-12 | +38.1% | 16 | +1.40% | +1.20% | −0.23% | +0.97% |
| SOL-USD_UM-260925 | 2026-07-05 | +15.1% | 82 | +5.42% | +5.22% | −0.76% | +4.47% |

Mean net after the funding estimate: +1.72% per contract, about 4–22% a year. Seven of the 11 expired contracts have no candle history, so they could not be tested. Four contracts is not a basis for a return estimate. What it does show is that convergence happened in every case: the basis at settlement fell to within 1.2% in all four.

### 3.5 Stat-arb SOL / AVAX (`research/results/pairs-test.txt`)

Walk-forward. Train 90 days (hourly) or 365 days (daily). Hedge ratio, spread mean and deviation from the train window only. Trade only if Engle–Granger t < −3.34 on the train residual. Entry at |z| > 2, exit at |z| < 0.5, stop at |z| > 4. Costs 10 bps of gross capital per round trip.

| Timeframe | Folds | Cointegrated | WF total | Sharpe | MDD | Trades |
|---|---|---|---|---|---|---|
| 1h (90 d / 30 d) | 55 | 13 | −20.3% | −0.71 | −22.8% | 14 |
| 1d (365 d / 91 d) | 15 | 0 | 0.0% | — | 0.0% | 0 |

Validation: on synthetic series that are cointegrated by construction, the same code returns +114% with Sharpe 11.3 and MDD −2%, so the losses on SOL / AVAX are not a mechanical error. Cointegration appears in roughly a quarter of hourly folds and then does not persist out of sample.

### 3.6 Liquidation-cascade hunting

Not tested. The OKX public liquidation-orders endpoint returned a single record, dated a few minutes before the probe. No reachable source provides history. Liquidation heatmaps are proprietary or need API keys. The claim "Sharpe 0.5–1.0" cannot be checked from here.

## 4. What this means for the proposal

- **The proposal's specific numbers do not hold on our data.** Carry does not reach 15–25%, funding mean reversion does not replicate across venues, and the pair fails out of sample.
- **The basis trade is the one to keep looking at.** It is the only result with a plausible mechanism (convergence) and positive outcomes. It needs (a) more expired contracts with candle history, (b) real fill and margin data for the short future leg, and (c) a live forward ledger on the current OKX contracts.
- **The claim that "backtests show PF ≈ 1.0 minus fees" is not what we see**, and the claim that the current strategy is "break-even" is not what the numbers say either. The 1h adaptive Supertrend is still unvalidated and is being forward-tested.

## 5. Corrections to my earlier notes

- First draft of the carry test paired day closes with funding intervals that start at the open. Replaced with open-to-open returns and exact settlement intervals before the results in §3.1 were produced.
- The first basis run added long-perp funding with the wrong sign. Fixed; the corrected run is in §3.4.

## 6. Reproduce

```
python3 -m research.okx_data candles SOL-USDT-SWAP 1H 2022-01-01   # and AVAX-USDT-SWAP, SOL-USDT, AVAX-USDT
python3 -m research.okx_data expiries SOL-USD 2024-01-01 2026-10-13
python3 -m research.hl_data
python3 -m research.carry_test
python3 -m research.funding                 # Binance funding mean reversion (4h, 1d)
python3 -m research.fundmr_xvenue           # Hyperliquid replication
python3 -m research.oi_test
python3 -m research.basis_test
python3 -m research.pairs_test
```
