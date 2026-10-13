# SOLUSDT — Historical Data Analysis

**Tooling:** [`@nemesis-oss/binance-sdk`](https://www.npmjs.com/package/@nemesis-oss/binance-sdk) v3.0.0 (`SpotClient` → `market.klines()`, public market data, no API key required)
**Data:** Binance Spot klines fetched **2026-10-13 UTC**
- `1d`: 1,500 candles (2022-09-05 → 2026-10-13, ~4 years)
- `4h`: 1,800 candles (2025-12-17 → 2026-10-13)
- `1h`: 1,440 candles (2026-08-14 → 2026-10-13)

Files: `fetch-sol.mjs` (SDK fetch), `analyze-sol.py` (indicators/backtests), `data/SOLUSDT-klines.json` (raw), `analysis-output.txt` (full output).

---

## 1. Snapshot

| Metric | Value |
|---|---|
| Last close | **$106.73** |
| 7d / 30d / 90d return | **-11.6% / +7.5% / +38.1%** |
| 180d / 365d return | +19.9% / **-48.9%** |
| 52w range | $62.20 – $202.44 (now -47% below high, +72% above low) |
| Period ATH / ATL | $261.97 (2025-01-18) / $9.64 (2022-12-29) |
| Annualized vol (365d / 90d) | 64.2% / 56.0% |
| Max drawdown since Jan-2025 peak | **-76.3%** (troughed 2026-06-06) |
| Sharpe (365d) | -0.72 |
| Avg daily quote volume (30d) | ~$272M |

**Yearly returns:** 2022 −69% · 2023 **+918%** · 2024 +72% · 2025 −36% · 2026 YTD −16%.

## 2. Return distribution (daily, 4y)

- Mean +0.19%/day but median −0.07% → right-skewed; up-days only 49%.
- Fat tails: 172 days >+5%, 123 days <−5%; extremes +32.5% / −42.2%.
- Rolling 30d returns: median +1.2%, p10 −25.7%, p90 +43.9% → wide dispersion; timing matters more than average edge.

## 3. Technical picture (multi-timeframe)

| Signal | Daily | 4H | 1H |
|---|---|---|---|
| Trend (EMA50 vs EMA200) | ✅ Bullish (golden state) | ✅ Bullish | — |
| vs SMA20 / SMA200 | −8.3% / +22.6% | −2.9% / −4.9% | — |
| RSI(14) | 40.8 neutral | 34.1 weak | 42.1 |
| MACD hist | −2.16 (bearish cross 2026-10-01) | −0.20 | −0.34 |
| Bollinger %B | 4% (riding lower band) | — | — |
| ATR(14) | $4.96 (4.6%) | — | — |

**Read:** the larger-cycle uptrend that began from the June-2026 low ($62) is intact (price +23% above SMA200, golden-cross state, +38% over 90d), but momentum has rolled over short-term: a sharp −11.6% week has pushed price to the lower Bollinger band, below SMA20, with bearish MACD on all three timeframes. Volume confirms the broader recovery (+11% 30d vs 90d) and taker-buy ratio is balanced (~50.3%), i.e., no capitulation flush yet.

**Key levels (swing-clustered, last 180d):**
- Resistance: **$112**, then **$122** (Sept swing highs)
- Support: **$99.3**, **$84–83** (Apr/May shelf), **$74.8**, major at **$62** (June low)

## 4. Strategy backtests (daily, long-only, next-bar-open fills, 0.1% fee)

| Strategy | Total | CAGR | Max DD | Trades | Win% | Time in mkt |
|---|---|---|---|---|---|---|
| Buy & Hold | **+416.6%** | +58.6% | −76.3% | 1 | — | 100% |
| SMA50/200 trend | +31.1% | +7.9% | −68.3% | 6 | 17% | 55% |
| 20/50 EMA cross | +62.0% | +12.9% | −64.2% | 17 | 18% | 49% |
| 90d momentum | +121.1% | +22.8% | −59.8% | 35 | 34% | 55% |
| RSI mean-revert (<30 buy, >55 exit) | +3.7% | +0.9% | −53.1% | 7 | 43% | 18% |

Takeaways:
- **Every tested systematic strategy badly lagged buy-and-hold** over this window — SOL's moves are violent and gap-heavy, so trend filters mostly cut winners (low win rates = whipsaw) while still eating huge drawdowns during the 2025→2026 −76% grind.
- Trend/momentum systems did their one job partially: they reduced max drawdown by ~8–17 pts and kept capital busy ~half the time — but at a large return cost.
- RSI dip-buying had the best risk profile (−53% MDD, 43% win rate) but only participated in 18% of days; it avoids regime drawdowns rather than profiting from them.
- Honest conclusion from history: **SOLUSDT rewards cycle-bottom accumulation and punishes mid-cycle trading**. The asset's defining historical feature is the tail risk (−76% drawdowns are "normal"), not smooth trend.

## 5. Summary assessment

- **Regime:** recovering from a deep bear phase (ATH $262 → $62); currently mid-term bullish structure, short-term pullback to lower band.
- **Watch:** whether $99–100 support holds against the bearish short-term momentum; reclaim of $112 would realign all timeframes bullishly. Break of $99 opens $84–83.
- **Risk framing:** with ~56–64% annualized vol and 4.6% daily ATR, position sizing should assume ±10–15% weekly swings as routine.

*Not financial advice — historical statistics do not predict future returns.*
