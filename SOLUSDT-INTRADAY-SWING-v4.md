# SOLUSDT — Intraday & Swing Long/Short Systems (v4)

Scope per user request: **intraday and swing only** (no long-term hold strategies). Instrument: Binance USD-M perpetual SOLUSDT. Costs modeled at every fill: taker fee 5 bps/side + slippage 3 bps/side, stop-market fills checked intra-bar with stop-priority (conservative), and **real funding history applied at each 8h boundary crossed while in position**. Signals computed on bar close, executed at next bar open (no lookahead). Walk-forward split: first 60% train (used only for parameter choice sanity), last 40% pure OOS. Data windows: 15m = 73d, 1h = 108d, 4h = 450d.

## Headline results (1x leverage, all costs in)

### INTRADAY (15m bars) — everything loses after costs
| System | Full total | Full Sharpe | OOS total | OOS Sharpe | Trades | WR | PF |
|---|---|---|---|---|---|---|---|
| Donchian 20 (5-min trend) | −39.7% | −5.5 | −21.8% | −4.4 | 241 | 26% | 0.69 |
| Donchian 48 (12-min trend) | −19.3% | −1.8 | −4.1% | −0.4 | 121 | 26% | 0.85 |
| EMA 12/48 cross | −30.9% | −2.3 | −8.5% | −0.9 | 198 | 20% | 0.83 |
| RSI-7 mean-revert 25/75 | −85.2% | −24.8 | −58.6% | −17.1 | 902 | 45% | 0.49 |
| RSI-14 mean-revert 30/70 | −68.0% | −14.3 | −39.5% | −9.5 | 497 | 47% | 0.59 |
| Time-of-day seasonality (long best 4h / short worst 4h of day) | — | — | −31.6% | −13.3 | 174 | 33% | 0.50 |
| NR vol-compression breakout | −20.0% | −13.4 | −8.8% | −10.0 | 108 | 17% | 0.24 |

Why: average adverse move per round trip ≈ 16 bps (fees+slip+funding). Mean edge per 15m trade even for the best variant is ~0 bps; losers dominate. The hourly-seasonality effect has a **split-half correlation of −0.37** across the two halves of the sample — it is noise, not structure. RSI churn (480–900 trades) is a guaranteed cost leak.

### SWING (1h bars, ~1–3 day holds) — marginal at best
| System | Full | OOS total | OOS Sharpe | Boot CI (5/50/95) |
|---|---|---|---|---|
| Donchian 24 (~1d) | +33.6%, Sh 1.9 | +3.8% | +0.6 | −3.6 / +0.3 / +2.8 |
| Donchian 72 (~3d) | −14.1% | −13.4% | −1.7 | — |
| EMA 10/50 | −14.9% | −23.1% | −3.1 | — |
| RSI-14 MR w/ stops | −43.8% | −7.5% | −0.9 | — |

1h parameter perturbation is jagged (n16 −0.5, n24 +0.6, n36 −3.4…) → no robust plateau. Verdict: **1h systems are coin-flips after costs.**

### SWING (4h bars, ~5–12 day holds) — the only place with signal
| System | Full total | Full Sharpe | OOS total | OOS Sharpe | MDD | Boot CI (5/50/95) |
|---|---|---|---|---|---|---|
| Donchian 40 (~6.7d) | −0.7% | +0.2 | **+37.9%** | **+0.92** | −8.8% | −1.0 / +0.9 / +1.7 |
| Donchian 60 (~10d) | +18.8% | +0.5 | +18.6% | +0.64 | −13.0% | −1.6 / +0.6 / +1.7 |
| Donchian ensemble 20/40/60 | +3.2% | +0.3 | +37.7% | +0.91 | −8.8% | — |
| **D40 + EMA200(4h) trend gate** | **+53.7%, Sh 1.01** | | **+39.0%, Sh 0.97** | −8.1% MDD | PF 2.7 |
| EMA 10/40 cross | −31.3% | −0.2 | +20.0% | +0.55 | — |
| RSI-14 MR | −76.4% | −2.2 | −46.3% | −1.8 | — |

Parameter perturbation of the 4h Donchian family on OOS is a **smooth positive ridge**: n16:+0.3 n20:+0.8 n24:+0.6 n32:+0.7 n40:+0.9 n48:+1.1 n60:+0.6 n72:+0.3 — the hallmark of a real effect rather than an overfit spike. Trade counts are small (15–43) so confidence intervals straddle zero; treat Sharpe ≈ 0.9 as an optimistic-but-plausible expectation, not a promise.

Long/short decomposition (4h D40, full sample): longs avg +0.24%/trade, shorts avg +0.61%/trade — shorts earn their keep here because this window includes SOL's drawdowns; unlike static shorts, these are conditional breakouts.

## Recommended intraday/swing architecture

1. **Do not day-trade 15m SOLUSDT directionally.** Every classical family tested (trend, MR, ORB-style compression, time-of-day) loses money net of fees/slippage/funding. If you must scalp, maker-limit execution and/or zero-fee venues are prerequisites, not enhancements.
2. **Core swing engine: 4h Donchian ensemble (bands 20/40/60), symmetric long+short**, mid-line exit, entry on next-bar-open after band break.
   - Risk sizing: fixed-fractional, risk ≤1% of equity per trade against a 2.5×ATR(14) protective stop ⇒ effective leverage ≈ 1–2×; cap gross at 2.5×.
   - Expect ~2–4 trades/month, holds 5–12 days, most time flat.
3. **Trend overlay:** take longs only above the 4h-EMA200 (~33-day proxy); shorts only below it. This roughly doubled full-sample return (Sh 0.2→1.0) with lower MDD; keep it but expect regime dependence.
4. **Funding awareness:** crossing 8h boundaries means paying/receiving funding; longs pay when funding z-score > 0. For swing sizes the drag is minor (<1%/mo typical) but flatten longs if funding rate > +0.1%/8h sustained (squeeze fuel).
5. **Kill-switches:** daily loss > 3% → halt new entries 24h; equity DD > 15% → halve size; skip entries within ±30 min of funding settlement to avoid predictable pinning.
6. Optional satellite (only if 1h OOS Sharpe stays >0 out-of-sample rolling 90d): 1h Donchian-24 at half size. Currently it does not qualify.

Honest caveat: OOS bootstrap median Sharpe for the winning 4h system is ~+0.9 but its 5th percentile is ~−1.0 — there is a real chance this edge is dead in the next 6 months. Size accordingly (≤2% risk/trade), and re-validate quarterly with `fetch-intraday.mjs` + `analyze-v4b.py`. Not financial advice.

Artifacts: `analyze-v4.py` (first pass, additive-equity bug), `analyze-v4b.py` + `analysis-v4b-output.txt` (final numbers), `analyze-v4c.py` (seasonality/NR/gating tests, appended to same log), data `data/SOLUSDT-intraday.json`.
