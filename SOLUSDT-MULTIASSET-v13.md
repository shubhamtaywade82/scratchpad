# SOL / ETH / XRP with BTC anchor: HTF from 1m, trailing exits, and the MiniCPM fleet (v13)

## 1. Direct decision

- **No strategy passed every robustness test.** Every family's out-of-sample (OOS) block-bootstrap 5th-percentile Sharpe is below zero, and every deflated Sharpe is under 7%. Treat the survivors as leads, not proven edges.
- **Survived on at least 2 of 3 alts:**
  - 1d Donchian ensemble (Zarattini lookbacks): 3/3.
  - 1d TSMOM: 2/3.
  - 4h TSMOM: 2/3.
  - Everything that fails is on XRP.
- **Best single cells:**
  - 4h TSMOM on SOL: +35.0% OOS, Sharpe 0.74.
  - 1h BTC-anchor breakout on ETH: +61.8%, Sharpe 0.70, but it fails on SOL and XRP.
  - 4h BTC-anchor breakout on SOL: +25.0%, Sharpe 0.62, but its flip null is also slightly positive.
- **Exit rule (§5a):** a fixed 2-ATR stop plus the signal's own exit beats every trailing rule in 9 of 12 cells. Under that rule, 4h DONENS made +156.5% on SOL, +56.9% on ETH and +12.7% on XRP over 2021–2026 with no parameter selection. It is now ported to crypto-trading-agent as `TREND-ENS-μ` (§6, paper only).
- **The 1–10% per-trade target is met by the 4h survivors' winners, not by every trade.** Median winners:
  - 4h DONENS on SOL: +6.6% (p25 +3.6%, p75 +10.0%).
  - 4h TSMOM on SOL: +3.0%.
  - 1d systems overshoot: median winner +8–12%, with many winners above 10%.
  - Losers are capped near the stop: median about −2% to −6% unlevered.
- **Taker-absorption and the 1h adaptive Supertrend are dead on this longer 2021–2026 sample** (0/3 and 1/3). The v6/v7 leads came from short SOL-only windows.
- **The MiniCPM fleet (crypto-trading-agent) loses money and has no directional skill.** Across 900 replayed prompts, `minicpm5-2b` returned `ENTER_LONG` every time: 0 shorts, 0 holds. 697 of those answers failed the fleet's own validation, leaving 203 entries.
  - With the fleet's own exits, the mean return on margin per trade is −3.1% on SOL (t −2.6), −4.1% on ETH (t −3.2) and −2.7% on XRP.
  - Taking the opposite side at the same moments loses less: −1.4%, −1.8% and −2.1%.
  - See §5b.

## 2. Critical risks and invariants

1. **Selection bias.** Up to 1,152 configs were tested per family. Exit parameters were chosen inside each training fold, and the chosen exit changes from fold to fold. No single trailing setting is stable.
2. **Small absolute returns.** At 1% risk per trade, the best 1d survivor made +11% over about 4.5 OOS years. Leverage scales this result and its drawdown together; it does not create edge.
3. **Margin-return figures depend on leverage.** At 10×, a 0.16% round-trip cost is already −1.6% on margin. Many cells with positive equity expectancy show negative 5×/10× margin returns for that reason.
4. **The XRP regime differs** (2021–2023 legal shocks). Report XRP separately and do not pool it.
5. **Causality.** Each HTF bar is built only from complete UTC-aligned 1m buckets. In the 1m replay, a signal applies only after its HTF bar has closed, and ATR comes from the last closed HTF bar.

## 3. Data (1m → HTF)

- Binance USD-M public archive, 2021-01 to 2026-10-22, 1m klines plus funding for BTC/ETH/SOL/XRP. Every zip is sha256-checked against Binance's `.CHECKSUM`.
- The 2022-02 and 2022-04 monthly archives for SOL and XRP are truncated. `fill_gaps` patches them from daily archives, and every symbol now has 0 missing minutes.
- **Resampler check against the Binance API bars already in `data/`:**
  - BTC 1h: 2,970 overlapping bars, 0 mismatches.
  - ETH 4h: 2,000 bars, 1 mismatch.
  - SOL 1d: 1,500 bars, 1 mismatch.
  - The two mismatches are each file's last bar, which was still forming when the reference file was fetched.

## 4. Results (walk-forward OOS, `research/results/v13-screen-{1d,4h,1h}.txt`)

Setup: 1% risk per trade; isolated leverage 2× (1d), 3× (4h), 5× (1h); fee 5 bps + slippage 3 bps per side; funding charged. Folds: 1y/6m (1d), 180d/90d (4h), 90d/30d (1h).

| Family | TF | SOL | ETH | XRP | Verdict |
|---|---|---|---|---|---|
| Donchian ensemble | 1d | +11.1% Sh 0.65 | +5.4% Sh 0.29 | +1.9% Sh 0.13 | 3/3 |
| TSMOM 3/5/10/20d | 1d | +6.4% | +6.6% (flip +2.8%) | −10.2% | 2/3 |
| TSMOM | 4h | **+35.0% Sh 0.74** | +9.0% | −13.8% | 2/3 |
| Donchian ensemble | 4h | +6.7% | −0.6% | −11.1% | 1/3 |
| BTC-anchor breakout | 4h | +25.0% Sh 0.62 (flip +0.5%) | −7.0% | −23.6% | 1/3 |
| BTC-anchor breakout | 1h | −18.4% | **+61.8% Sh 0.70** | −11.8% | 1/3 |
| Alt/BTC ratio Donchian | 1d / 4h | +6.0% / +6.8% | fail | fail | 1/3 |
| Adaptive Supertrend | 1h / 4h | +4.2% / −8.8% | −51.6% / +14.0% | fail | 1/3 |
| Taker absorption | 1h / 4h | fail | fail | fail | 0/3 |

- **BTC as anchor:** the `+btc` EMA200 gate was picked in some folds but not consistently.
- **Cross-asset:** BTC breakout as a trigger works on one alt per timeframe, and the alt changes between timeframes. That pattern suggests noise, not structure.

## 5. Trailing rule engine

**Rule order per bar** (engine invariant 10; 1m replay available):
1. Gap check.
2. Liquidation.
3. Stop (initial, breakeven, lock, trail or giveback).
4. Partial TP.
5. Ratchets from this bar's extreme: breakeven → lock ladder → chandelier trail, tightened past `trail_tight_r` → giveback lock.
6. Time stop at the close.

Stops only ratchet in the favourable direction.

**What walk-forward selection preferred** (the exits most often chosen in training):
- trail activation at 1R;
- tightening to 1.5 ATR past 3R;
- a 50% scale-out at 2R.

Fixed take-profits with no trail were rarely chosen. The choice is not stable across folds.

### 5a. Fixed exit rules on the 1m path (`research/results/v13-exits.txt`)

Setup: no parameter selection; 1% risk per trade; 2021–2026 after warm-up. Each cell is the total return on the 1m path. The signal's own exit (midpoint ratchet or TSMOM flip) stays active in every row.

| Exit rule | 4h DONENS SOL / ETH / XRP | 1d DONENS SOL / ETH / XRP | 1d TSMOM SOL / ETH / XRP | 4h TSMOM SOL / ETH / XRP |
|---|---|---|---|---|
| **E0: 2-ATR stop only** | **+156.5 / +56.9 / +12.7** | **+35.0** / +3.5 / **+25.5** | **+46.5** / +12.4 / **+39.5** | **+92.6** / **+8.6** / **+77.4** |
| E1: chandelier 3 ATR after 1R | +14.4 / +43.6 / −30.3 | +18.3 / +5.5 / −7.2 | +25.9 / +17.2 / −11.3 | +15.4 / +3.0 / +14.8 |
| E2: E1 + tighten to 1.5 ATR past 3R | +20.7 / +17.9 / −31.1 | +21.1 / +6.1 / −2.1 | +29.3 / +16.4 / −8.0 | +11.5 / −7.8 / +9.5 |
| E3: E2 + 50% scale-out at 2R | +24.7 / +19.9 / −24.3 | +16.3 / +4.7 / −2.1 | +23.7 / +11.4 / −7.0 | +12.2 / −14.0 / +10.0 |
| E4: agent `TrailingStopManager` tiers | +14.8 / +24.8 / −19.6 | +9.2 / +3.0 / −2.7 | +28.2 / +3.2 / −5.0 | +1.2 / −4.7 / −4.2 |
| E5: giveback 40% after 1R | +24.1 / +27.5 / −22.1 | +16.7 / −4.0 / −3.5 | +25.7 / +17.0 / −2.5 | +13.4 / +3.9 / −10.5 |
| E6: fixed TP at 2R | +42.1 / +25.5 / −7.8 | +8.5 / +3.3 / −4.7 | +13.2 / +4.1 / −1.8 | +23.6 / −25.8 / +11.4 |

**Answer to "how should the trailing rule engine work"**

For these trend systems, the best rule is not to trail the stop at all. Use a fixed 2-ATR initial stop, and let the signal's own structural exit do the trailing: the Donchian midpoint ratchet, or the TSMOM flip.

- E0 wins 9 of 12 cells. ETH 1d TSMOM, ETH 1d DONENS and ETH 4h TSMOM are the exceptions.
- Every ATR trail, profit-lock tier, giveback rule or fixed target cuts the right tail, and the right tail is where the edge is. For 4h DONENS on SOL under E0, the winners' p75 move is +30.5%, and the median winner is +9.9%.
- Trailing does lower drawdown in some cells (1d SOL DONENS: −10.5% for E0 vs −3.9% for E3), at a large cost in return.
- This matches Kaminski & Lo (stops add value only when there is momentum, and tight stops cut it) and our earlier v8 result.
- E0 is one of 7 rules tried, so a small selection allowance applies. The 4h DONENS walk-forward screen, where trailing exits were chosen inside each training fold, made only +6.7% on SOL against +156% for fixed E0. Choosing the exit inside the fold hurt.

### 5b. MiniCPM fleet replay (`research/results/v13-minicpm-openbmb_minicpm5-2b_latest.txt`)

Setup: 900 random 15m closes (300 per alt), 2021–2026. The model gets the fleet's own prompt and its answer goes through the fleet's own validation. Each entry is held at most 48h on the 1m path, at 10× isolated.

Mean return on margin per trade:

| | SOL | ETH | XRP |
|---|---|---|---|
| Entries traded (validation rejects / skipped because the stop was beyond the liquidation buffer) | 106 (177 / 17) | 48 (248 / 4) | 20 (272 / 8) |
| FLEET exits: LLM stop/target, breakeven at +0.25% | **−3.11%** (t −2.57), win 11% | **−4.13%** (t −3.22), win 8% | −2.73%, win 10% |
| TIERS: agent `TrailingStopManager` tiers | −5.60%, win 40% | −4.77%, win 40% | −8.87%, win 35% |
| FLIP: opposite side, same distances | −1.43% | −1.75% | −2.12% |

Reading:
1. The model is a fixed long bias, not a decision-maker.
2. The fleet's breakeven move at +0.25% ends about 70% of trades at breakeven. At 10×, the 0.16% round-trip cost then becomes about −1.3% on margin per trade, so this rule turns noise into a steady loss.
3. The agent's tiers win more often but lose more: the model's stops are wide (median about 2.4%, which is 24% of margin at 10×), and the tiers do not start working until +1R.
4. **`minicpm5-analyst`** (900 prompts, context capped at 4k; `research/results/v13-minicpm-minicpm5-analyst.txt`):
   - Raw actions: 876 LONG, 11 SHORT, 0 HOLD.
   - FLEET exits, mean margin per trade:
     - SOL −2.82% (t −4.57, n 180);
     - ETH −3.01% (t −5.16, n 189);
     - XRP +1.73% (t +0.55, n 71). This is not significant: 7 take-profits out of 71 trades.
   - Same long bias as the base model, so the same conclusion.
5. Recommendation for crypto-trading-agent: keep `entriesEnabled: false`. Do not use MiniCPM as an entry signal. Use it only for read-only digests and routing, as in `research/llm_desk.py`.

## 6. Implementation

- `research/binance_1m.py`: fetch, verify and patch gaps, load columns with `array('d')`, and resample to UTC-aligned buckets, dropping incomplete buckets.
- `research/engine.py`: new timeframe keys, plus the `trail_tight_*`, `giveback`, `max_bars` and `lock_steps` rules.
- `research/multi_asset.py`: 6 families × BTC gate × 144 exit cells, in-fold selection, flip and delay nulls, a per-trade report on three bases, and `replay` for the 1m path.
- `research/minicpm_replay.py`: ports the crypto-trading-agent fleet prompt and its validation.
- `research/exit_study.py`: fixed-rule exit comparison.
- crypto-trading-agent:
  - `src/agents/TrendEnsembleAgent.ts` (`TREND-ENS-μ`, SOL and ETH, 4h Donchian ensemble). Entry has a 2-ATR stop. Exit: when the ensemble leaves the position's side, the stop moves to the mark, and the paper engine fills at the next mark.
  - It is excluded from the `TrailingStopManager` tiers and is paper-only.
  - It needs `MARKET_DATA_KLINE_LIMIT >= 555`; set it to 1000.
  - Parity: TS on a 1000-bar window vs Python on the full history agrees on 400 of 400 recent 4h bars for both SOL and ETH.

## 7. Verification

- `python3 -m unittest research.test_engine research.test_binance_1m research.test_llm_desk`, plus `uv run --with numpy` for the numpy suites: 109 tests pass.
- 1m replay sanity check: SOL 1d TSMOM, fixed sizing: HTF equity 0.4202 vs 1m equity 0.4203, 102 trades in both. With a 2-ATR stop: 1.0549 vs 1.0550.

## 8. Next steps

1. Run `TREND-ENS-μ` in paper mode with `MARKET_DATA_KLINE_LIMIT=1000` and compare it with the backtest after about 30 trades.
2. Forward-paper the 1d Donchian ensemble and 4h TSMOM on SOL and ETH. Drop XRP.
3. In crypto-trading-agent, keep `entriesEnabled: false` for the MiniCPM fleet. The replay shows the model never shorts or holds.
