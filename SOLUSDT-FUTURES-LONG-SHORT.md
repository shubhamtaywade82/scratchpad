# SOLUSDT USD-M Perpetual Futures — LONG & SHORT Analysis (v3)

Data: Binance **USDM-M SOLUSDT perp** via `@nemesis-oss/binance-sdk` (`createUSDMClient`, public endpoints):
1,500 daily + 1,800 4h candles (2022-09 → 2026-10-13), **4,575 funding settlements**, OI history, top-trader & taker ratios.
Scripts: `fetch-futures.mjs`, `analyze-futures.py`, `analyze-futures2.py` → outputs in `analysis-futures*-output.txt`.
Backtest rules: signal at close t → held t→t+1; 0.07%/side fee+slippage on turnover; **funding credited/debited per settlement day**; 1x gross (leverage discussed separately).

## 1. Live futures state (snapshot at fetch)
- Mark 106.60 / Index 106.66 — perp trading slightly **below** index
- **Next/last funding −0.0064%** (shorts currently *pay* ~0.02%/day ≈ −7% APR to hold)
- Open Interest **$910M** (−5.2% over 30d, range $882–1,078M) — leverage being flushed, not rebuilt
- Top-traders position L/S **2.24**, global account L/S **2.36**, taker buy/sell **0.94** → retail/majority net long, smart money also long, but passive sellers dominant. Crowd is one-sided long into a −4.7% 24h tape.

## 2. Funding economics — the first thing spot analysis misses
| stat | value |
|---|---|
| median 8h rate | +0.0046% (**≈ +5% APR** longs pay) |
| positive-rate share | 67% of all settlements |
| extreme low | **−2.00%/8h** (liquidation cascade; shorts paid ≈ +270% APR annualized that day) |
| cumulative cost of holding 1x long | **−23.4%** over 4y (B&H total fell from +416% spot-style to **+313%** after funding) |
| avg daily funding above SMA200 | **+0.026%** (longs pay when crowded-bullish) |
| avg daily funding below SMA200 | **−0.001%** (shorts pay ≈ nothing in bear regime) |

Funding is regime-correlated: the bull leg taxes longs ~9.4%/yr; the bear leg is nearly free to short.

## 3. Is shorting SOLUSDT profitable? Backtests say "symmetric LS destroys value"
All numbers include fees **and** funding:

| strategy (daily bars, ~4y) | Total | MDD | Sharpe |
|---|---|---|---|
| Buy & hold 1x long | **+313%** | −76.0% | 0.83 |
| Static 1x short | **−100%** (wiped) | −99.8% | −0.83 |
| Long >SMA200 / **short <SMA200** (symmetric) | −8% | −86.8% | 0.35 |
| EMA20/200 cross LS | −95% | −98.4% | −0.24 |
| MACD-sign LS | −44% | −85.1% | 0.38 |
| RSI(30/70) mean-revert LS | −61% | −81.5% | −0.22 |
| Vol-target 40% LS | +26% | −58.1% | 0.34 |
| **Long gate + 0.25x crisis-short (<SMA200 & mom30<−20%)** | **+189%** | −61.5% | 0.72 |
| **Long-only gate (best overall)** | **+203%** | −60.3% | **0.75** |

**P&L decomposition of symmetric LS:** long days earned **+201%** on price, short days earned **−72%** (i.e. lost it), and funding cost both sides another ~−20%. The short side of every always-on trend system was a net loser.

Why: yearly table for static short — 2022 (spot −69%!) a leveraged perp short still made only modestly after the Jan-Feb melt-up phase and funding whipsaws; 2023 (+1003% B&H) a static short loses **−96.7%**; 2024 −67%; even in down years 2025/2026 the short earns only −27%/−14% because SOL's bear legs are violent V-rebounds. Shorting has **negative skew**: bounded gains, −100% tail.

## 4. Where shorts DO work (asymmetric, conditional)
1. **Deep-negative-funding episodes** (funding ≤ −0.05%/8h avg, n=33): forward returns **+5.3% @7d, +22.8% @14d**. This is the classic liquidation-capitulation signal → *long*, funded by the shorts who piled in. A pure funding-contrarian book (deep-neg→long, hot→small short) returned **+31% with −46% MDD** — the best drawdown profile among directional systems.
2. **Crisis shorts** only pay when gated hard: below SMA200 **and** 30d momentum < −20%, at **¼ size**. Adds hedge value without wrecking the book (+189% vs +203%, but cushions choppy 2024/2026 exits). Looser short gates (mom<−10%, any size ≥0.5) all degraded results.
3. **Shorting hot funding (p80+) is NOT a sell signal** on SOL — fwd 30d after crowded-long funding averaged **+10%**. Trend beats crowd here.

## 5. Leverage reality check (perp-specific)
At 3x, a −33% adverse move liquidates. SOL's worst single week since 2025 peak was −76% cumulative; a 5-day −25% drawdown occurs ~15× in sample. **Recommendation: ≤2x for the long-gate book, ≤1x effective on any short sleeve**, vol-targeted (40%/realized-vol weight cap 1.5x). Cross-margin short + long legs must be sized against combined exposure, not notional.

## 6. Verdict — how to trade both directions on the perp
- **Core (≈70% of risk):** long-only SMA200 regime gate, vol-sized. Funding drag (~−19% cumulative) is the price of using perps instead of spot for the long leg — if you can hold spot, do that and use the perp only for hedging.
- **Hedge sleeve (≤25% of core size):** short only when price < SMA200 **and** 30d momentum < −20%, half-life measured in weeks, exit on first deep-negative-funding print (that's your cover-to-long flip).
- **Flip trigger:** funding ≤ −0.05%/8h sustained + OI falling (like now-ish conditions in Jun-2026) = historically the strongest long entry in this dataset.
- **Never:** static short, symmetric always-in LS, or RSI/MACD-sign LS on this symbol — every variant tested lost 44–100%.

*Caveats: ~4y sample, few independent bear regimes; funding/OI history limited to Binance USDM; backtests are in-sample parameterizations — treat the family ranking (asymmetric ≫ symmetric) as the robust finding, not the exact thresholds. Not financial advice.*
