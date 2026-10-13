# SOLUSDT — Web-Sourced Strategies (v9) and Forward Test of the 1h Adaptive Supertrend

Instrument: SOLUSDT. Backtests use the Binance USD-M history already in the repo (perpetual, with funding). The forward test uses Kraken SOL-USD spot hourly bars (see section 4). Costs: taker 5 bps + slippage 3 bps per side. Walk-forward OOS with the same windows as v5–v8. Stop 3×ATR(14), risk 1% per trade. Leverage 5× on 1h and 4h, 1× on 1d (a 3-ATR stop on daily bars exceeds the 5× buffer).

## 1. Direct decision

1. **New candidate from the web research: 1d short-lookback time-series momentum (L3, L5, L10 daily bars), 1×.** All three lookbacks are positive out of sample (+7% to +13%, Sharpe 0.5–0.9, MDD −5% to −6%). Flipping the direction turns all three negative (−6% to −11%), so the signal is directional. The timing is less clear: a 1-day delay raises L5 and lowers L10 by about 10 points. Treat it as the best new lead, not a validated edge. It runs on daily bars with about 2–3 years of out-of-sample data.
2. **Keep the 1h volatility-adaptive Supertrend as the forward-test candidate, ungated.** Adding an ADX trend filter does not improve it: on 1h the Sharpe moves between 2.8 and 3.3 on 37–46 trades (noise), and on 4h it cuts the return from +13% to +3.5%.
3. **Reject the Bollinger/Keltner squeeze breakout for perps.** Its flipped version is also profitable on 4h and 1d, so direction contributes nothing. The edge looks like volatility expansion, and a perpetual can't trade that without a direction.
4. **Reject ADX-gated Supertrend on 1d and 4h.** It is neutral or negative against the ungated version.
5. **Reject short-lookback momentum on 1h and 4h.** It churns (175–395 trades) and loses on the fast lookbacks once costs are paid.

## 2. What the web research said, and what held up

| Source | Claim | Result here |
|---|---|---|
| [Quantzee: Supertrend settings guide](https://quantzee.com/supertrend-indicator-settings-guide/) | Add a trend-quality filter such as ADX, EMA or RSI to reduce sideways whipsaws | ADX gate neutral on 1h, harmful on 4h, negative on 1d. **Not confirmed.** |
| [Forextester: Supertrend guide](https://forextester.com/blog/supertrend-indicator/) | An EMA200 trend filter plus RSI reduces whipsaws | EMA200 gating was already tested in v5 and was not robust. Not repeated. |
| [HackerNoon: 6.7 years of TradingView Supertrend](https://hackernoon.com/the-truth-about-tradingviews-supertrend-strategy-after-67-years-of-backtesting) | The best multiplier depends on the test window | Our 4h fixed-factor Supertrend shows the same instability: its flipped version wins. |
| [usekeel.io: Supertrend settings for crypto](https://usekeel.io/strategies/settings/supertrend-best-settings-crypto) | A 12-setting grid on Hyperliquid, best Sharpe 0.99 net of fees and funding | Vendor claim, not checked. Our own Supertrend grid on 4h was negative. |
| [BoringEdge: Bitcoin Supertrend 2017–2026](https://boringedge.com/bitcoin-supertrend-strategy-backtest/) | ATR 10 with multiplier 3 on BTC daily: CAGR below buy-and-hold, much smaller drawdown | Spot long-or-cash. Not tested here; it matches our general finding that trend stops cut drawdown and return together. |
| [Mudrex: Keltner vs Bollinger for crypto](https://mudrex.com/learn/keltner-channels-vs-bollinger-bands-crypto/) and [pyquantlab: BB–KC squeeze on Bitcoin](https://medium.com/@pyquantlab/optimizing-the-bollinger-band-keltner-channel-squeeze-strategy-volatility-breakout-trading-in-70b49101cb30) | BB inside KC marks a squeeze; Sharpe above 1 across 243 parameter sets | The 243-set claim is in-sample and not verified. Our test: squeeze positive, but flip also positive on 4h and 1d. **Not directional.** |
| [Crypto TSMOM: daily short-lookback signals](https://www.researchgate.net/publication/374536953_Time_Series_Momentum_Trading_Strategy_for_Cryptocurrencies) and [dynamic TSMOM for cryptocurrencies](https://community.portfolio123.com/uploads/short-url/amrMsuqIKzdHcHHyvMud4YNPwZB.pdf) | Short-lookback daily momentum held up out of sample (Jan 2021–Aug 2022) | **Consistent with it on SOL, 1d, 1×: positive at L3, L5, L10 and directional under flip.** The 1-day delay result is inconsistent. |
| [Reading: Bitcoin intraday time-series momentum](https://centaur.reading.ac.uk/100181/3/21Sep2021Bitcoin%20Intraday%20Time-Series%20Momentum.R2.pdf) | First half-hour predicts the last half-hour of Bitcoin trading | Not tested: the local 15m history is 73 days, too short for a session effect. |
| [arXiv 2306.17178: cross-exchange order flow](https://arxiv.org/pdf/2306.17178) and [arXiv 2602.00776: order flow imbalance](https://arxiv.org/html/2602.00776v1) | Order-flow predictive power falls as the horizon lengthens | Consistent with the taker-absorption leads, which work only on 1h and 4h. |
| [arXiv 2607.09426: quarter-hour effect in crypto futures](https://arxiv.org/html/2607.09426v2) | Return predictability around periodic algorithmic trading times | Not tested: 73 days of 15m data is too short. |

## 3. Results (walk-forward OOS, `research/results/webstrats-*.txt`)

### 3a. 1d, 1× (where the candidate momentum lead lives)

| Cell | WF tot | Sh | MDD | Folds + | Flipped |
|---|---|---|---|---|---|
| ST p10 ×3 | +19.9% | +0.77 | −13.7% | 3/6 | −6.9% |
| ST p10 ×3 + ADX>20 | +12.6% | +0.60 | −13.9% | 4/6 | −4.1% |
| ST p10 ×3 + ADX>25 | +11.0% | +0.55 | −15.4% | 3/6 | −2.1% |
| Vol-adaptive p20 L100 1.5–4 | +14.8% | +0.73 | −13.7% | 3/6 | −5.0% |
| Vol-adaptive + ADX>25 | +11.0% | +0.64 | −12.2% | 3/6 | −3.4% |
| Squeeze BB2 KC1.5 | −1.3% | −0.17 | −5.6% | 3/6 | +0.9% |
| Squeeze BB2 KC2 | +3.6% | +0.31 | −7.6% | 3/6 | −1.8% |
| **TSMOM short L3** | **+7.0%** | **+0.51** | **−5.1%** | 4/6 | −5.6% |
| **TSMOM short L5** | **+13.3%** | **+0.91** | **−6.3%** | 4/6 | −10.7% |
| **TSMOM short L10** | **+12.5%** | **+0.80** | **−6.2%** | 3/6 | −9.5% |

Breadth: 10 of 11 cells positive. Momentum is 3 of 3 positive with the lowest drawdowns (about half the Supertrend cells).

Null checks, TSMOM short (`webstrats-null-1d.txt`):

| Lookback | Original | Flipped | Delay 1 day | Delay 3 days |
|---|---|---|---|---|
| L5 | +13.3% (Sh +0.91) | −10.7% (Sh −1.05) | +17.2% (Sh +1.16) | +1.2% (Sh +0.11) |
| L10 | +12.5% (Sh +0.80) | −9.5% (Sh −0.99) | +1.9% (Sh +0.15) | +4.4% (Sh +0.31) |

The flip result says the momentum sign has directional information. The delay results show the timing isn't precise: a one-day lag helps L5 and hurts L10.

Context: buy-and-hold over the full 1d sample returns about +231% with Sharpe +0.31 (from the v5 sensitivity run). The momentum strategy returns less in absolute terms and has a higher Sharpe with much less drawdown. That comparison is over a rising SOL sample, so it doesn't show the strategy beats buy-and-hold in every regime.

### 3b. 1h and 4h

- **1h:** 9 of 11 cells positive, but the positives are mostly the vol-adaptive Supertrend family. Squeeze positive and non-directional (flipped +0.5% and +1.3%). Short TSMOM L6 and L12 lose heavily (−28% and −9%), and L24 is directional but small (+2.8%, flipped −23%).
- **4h:** the fixed Supertrend p10 ×3 is negative (−5.4%) and its flipped version is positive (+7.8%), so on this sample the signal is anti-directional. The squeeze flip is also positive. The vol-adaptive ungated cell (+13.3%, flip −10.1%) remains directional.

Screen totals: 33 cells across three timeframes, each also run flipped. The momentum lead has 8 extra delay runs. Breadth by family is in each results file.

## 4. Forward test of the 1h volatility-adaptive Supertrend

- **Data source:** Kraken public OHLC, SOLUSD 60-minute. Binance returns HTTP 451 from this environment and I did not route around it. Kraken is spot, so there is no funding, and fees and slippage use the perpetual cost model.
- **Deployment:** forward start 2026-10-13 05:00 UTC, flat. The first decision uses only completed bars. Ledger: `forward/ledger.json`. Bars: `forward/bars-kraken-1h.json` (720 bars stored).
- **Mechanics:** `research/forward.py` keeps completed bars only, halts on any gap and does not fill it, and replays the causal engine from the start time. The fixed ×2 Supertrend runs alongside as the benchmark. Equity at the end of each replay includes a notional exit at the last close.
- **Schedule:** a daily routine (`trig_0184R4B7goj2s9z4QQo1qHLN`, 00:10 UTC) runs `forward update` and pushes `forward/` to this branch with fast-forward pushes only. It does not change research code or parameters. Delete it to stop the test.
- **Why daily is enough:** the replay is deterministic and causal, so updating once a day gives the same ledger as hourly updates. Entries and exits are still dated to the bar open.
- **Sample size:** the 1h candidate averages about one position every two days, so 60 positions take roughly four months. Expect no meaningful forward verdict before then.
- **Current status:** `WAITING` (the first complete decision bar is 05:00 UTC).

Kill rules, set before the first trade:
1. Rolling 90-day Sharpe below zero after at least 30 positions.
2. Realised drawdown beyond 10%.
3. Any single position loss beyond 2× the planned 1% risk.
4. A `GAP` status that persists for more than one day.

## 5. Verification

```
python3 -m unittest research.test_engine research.test_forward research.test_webstrats -v
python3 -m research.webstrats 1h        # research/results/webstrats-1h.txt (also 4h, 1d)
python3 -m research.webstrats null 1d 5,10
python3 -m research.forward status      # forward ledger
```

## 6. Next steps

1. Let the forward test run. Do not change the signal or its parameters while it runs.
2. Consider adding the 1d TSMOM L5 as a second forward test. Its evidence is independent of the 1h candidate, but it needs a separate ledger and a decision on whether to trade 1× or a level above.
3. Resolve the 1-day delay inconsistency before any risk is put on the momentum lead. More history on 1d would help, and so would a second venue.
