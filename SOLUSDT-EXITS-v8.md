# SOLUSDT — Trailing Stop, Breakeven and Take-Profit Study (v8)

Instrument: Binance USD-M SOLUSDT perpetual, isolated margin. Data: kline OHLCV. Costs: taker 5 bps/side, adverse slippage 3 bps/side on stops and signal exits, real funding, liquidation at the liquidation price. Entries are fixed; only the exit logic varies. Initial stop is always 3×ATR(14), so 1R = 3 ATR at entry. Screen: 5× margin ceiling, risk 1% of equity per trade, walk-forward OOS (same windows as v5–v7).

## 1. Direct decision

1. **Keep the signal flip as the primary exit.** On every entry tested, the stop-only baseline (initial stop plus signal flip) is the best or tied for best on Sharpe and on return-to-drawdown. The flip is where the edge comes from. Exits that cut winners lower the mean R per position (for the 1h adaptive entry: +0.36R stop-only, +0.10R to +0.25R with most TP and trail variants).
2. **Take-profit caps hurt.** A full take-profit at 1.5R, 2R or 3R lowers Sharpe on the 4h Donchian and on the 1h adaptive entry. On the taker entries it is about neutral.
3. **Trailing stops trade return for drawdown.** On the 1h adaptive entry, an immediate 3-ATR chandelier cuts MDD by about a third (−9.1% to −5.9%) but cuts return by 10 points and Sharpe from 2.88 to 1.92. Activating the trail after 1R is worse on the 1h adaptive and 4h Donchian entries (1h adaptive Sharpe 0.79) and identical on the taker entries.
4. **Breakeven at 1R is neutral.** It moves the stop to entry once the trade is up 1R. Results are within noise of the baseline on all four entries.
5. **One exit change has a real case: scale out 50% at 1R** on the 1h adaptive entry. Sharpe is unchanged (2.87 against 2.88), MDD falls from −9.1% to −5.7%, and Calmar rises from 1.84 to 1.93. It does not help on the 4h Donchian (Sharpe 0.73 against 1.28) or on the taker entries. Treat it as an option for the 1h adaptive lead, not a general rule.

## 2. Design

- **Breakeven (`be_r`):** once the best favourable excursion since entry reaches `be_r × 1R`, the stop moves to the entry price. No fee buffer is added, so a breakeven stop can still lose the round-trip cost.
- **Trail activation (`trail_act_r`):** the chandelier trail (extreme ∓ `trail_mult × ATR`) only ratchets once the trade has reached `trail_act_r × 1R`.
- **Take-profit (`tp_r`):** limit exit at entry ± `tp_r × 1R`. It fills at the limit price with no slippage. A gap past the level fills at the open. If a stop and a take-profit touch the same bar, the stop fills first (conservative). After a take-profit exit, the same direction is blocked until the signal leaves it, so there is no immediate re-entry.
- **Scale-out (`tp_frac`):** the target closes `tp_frac` of the position and the rest keeps running under the remaining exits.
- **Stop kind:** every stop exit records whether the initial stop, breakeven or trail set the stop (`init`, `be`, `trail`).
- **Position-level metrics:** scale-out splits one position into several closes. Win rate, mean R and Calmar are therefore reported per position, not per close.

## 3. Results (walk-forward OOS, `research/results/exits.txt`)

Columns: WF total, Sharpe, MDD, Calmar (return / |MDD|), positions, win rate per position, mean R per position, exit mix (share of closes).

### 3a. 1h adaptive Supertrend (p20 L100 1.5–4), 108 days

| Exit | WF tot | Sh | MDD | Calmar | Pos | Win% | meanR |
|---|---|---|---|---|---|---|---|
| **E0 stop only (baseline)** | **+16.7%** | **+2.88** | −9.1% | +1.84 | 56 | 34% | +0.36 |
| E1 trail 3 ATR | +6.6% | +1.92 | −5.9% | +1.12 | 56 | 45% | +0.17 |
| E2 trail 3 ATR after 1R | +2.6% | +0.79 | −7.0% | +0.37 | 56 | 41% | +0.10 |
| E3 breakeven 1R | +17.3% | +2.97 | −9.0% | +1.93 | 56 | 27% | +0.37 |
| E4 TP 1.5R | +6.8% | +2.06 | −6.4% | +1.07 | 56 | 36% | +0.17 |
| E5 TP 2R | +2.5% | +0.73 | −7.0% | +0.35 | 56 | 34% | +0.10 |
| E6 TP 3R | +3.7% | +1.01 | −6.5% | +0.57 | 56 | 34% | +0.13 |
| E7 BE 1R + TP 2R | +3.1% | +0.90 | −6.8% | +0.45 | 56 | 29% | +0.11 |
| E8 BE 1R + TP 3R | +4.2% | +1.13 | −6.2% | +0.68 | 56 | 27% | +0.13 |
| E9 BE 1R + trail 2 after 1R | +3.8% | +1.22 | −6.0% | +0.63 | 56 | 46% | +0.12 |
| **E10 scale 50% at 1R** | +11.1% | +2.87 | **−5.7%** | **+1.93** | 56 | 46% | +0.25 |
| E11 scale 50% at 1R, BE, trail 3 after 1R | +3.8% | +1.31 | −6.1% | +0.63 | 56 | 46% | +0.12 |
| E12 scale 50% at 2R, BE 1R | +10.3% | +2.36 | −6.2% | +1.67 | 56 | 29% | +0.24 |

### 3b. 4h Donchian(40) + EMA200, 450 days

| Exit | WF tot | Sh | MDD | Calmar | Pos | Win% | meanR |
|---|---|---|---|---|---|---|---|
| **E0 stop only (baseline)** | **+10.1%** | **+1.28** | −6.1% | +1.67 | 29 | 31% | +0.39 |
| E1 trail 3 ATR | +8.4% | +1.36 | −4.5% | +1.84 | 29 | 28% | +0.32 |
| E2 trail 3 ATR after 1R | +6.5% | +1.01 | −5.0% | +1.28 | 29 | 28% | +0.26 |
| E3 breakeven 1R | +9.6% | +1.23 | −6.1% | +1.59 | 29 | 24% | +0.37 |
| E4 TP 1.5R | −1.6% | −0.32 | −4.8% | −0.34 | 29 | 31% | −0.03 |
| E5 TP 2R | −0.3% | −0.03 | −4.8% | −0.06 | 29 | 31% | +0.02 |
| E6 TP 3R | +2.8% | +0.54 | −4.8% | +0.59 | 29 | 31% | +0.13 |
| E7 BE 1R + TP 2R | −0.8% | −0.11 | −4.9% | −0.15 | 29 | 24% | +0.00 |
| E8 BE 1R + TP 3R | +2.3% | +0.46 | −4.8% | +0.49 | 29 | 24% | +0.11 |
| E9 BE 1R + trail 2 after 1R | −0.9% | −0.15 | −6.2% | −0.14 | 29 | 31% | −0.00 |
| E10 scale 50% at 1R | +3.8% | +0.73 | −5.2% | +0.75 | 29 | 31% | +0.17 |
| E11 scale 50% at 1R, BE, trail 3 after 1R | +2.1% | +0.45 | −4.5% | +0.46 | 29 | 31% | +0.10 |
| E12 scale 50% at 2R, BE 1R | +4.4% | +0.76 | −5.3% | +0.83 | 29 | 24% | +0.19 |

The immediate 3-ATR trail gives a slightly better Calmar (1.84 against 1.67). Its neighbours do not: trail after 1R is 1.28, and the trail-2 variant is negative. This matches the trail-sensitivity surface in v5: the trail distance is fragile, not a plateau.

### 3b-2. 4h Donchian scale-out grid (48 variants, `research/scaleout.py`)

Grid: target 1R / 1.5R / 2R / 3R, fraction closed 25% / 50% / 75%, breakeven at 1R off / on, 3-ATR trail after 1R off / on.

| Breadth vs baseline (stop + signal flip: Sh +1.28, Calmar +1.67, WF +10.1%, MDD −6.1%) | Result |
|---|---|
| Beat baseline on Sharpe | **0 of 48** (median variant +0.75) |
| Beat baseline on Calmar | **0 of 48** (median variant +0.81) |
| Beat baseline on WF total return | **0 of 48** |
| Smaller MDD | 48 of 48, but only to −4.2% … −5.7% |
| Positive folds | 3 of 5 in every variant, same as baseline |

Patterns:
- **Larger fraction closed loses more.** 25% closed costs about 2 points of return. 75% closed costs about 9 points. The return loss scales with the fraction, and the drawdown benefit barely does.
- **Earlier target loses more.** At 75% closed, 1R reaches +0.8% and 3R reaches +4.6%.
- **Breakeven and trail add a little more cost.** Both are neutral to slightly negative on top of scale-out.
- **Best Calmar in the grid is 25% at 3R (1.47)**, which is still below the baseline's 1.67. It was selected in-sample from 48 cells and is not a finding.

Why the 4h Donchian differs from the 1h adaptive entry: its edge is a few large trend winners held for weeks (baseline mean R +0.39, against +0.05 to +0.32 across the grid). Partial exits cap exactly those winners. On the 1h adaptive entry the same cut reduced MDD by about 37% with Sharpe unchanged, so scale-out is entry-specific, not a general exit rule.

### 3c. 1h taker-absorb (m6 z2 T4), 22 positions

Each exit changes at most two of the 22 positions. 95% of closes are signal flips, because the entry holds for four bars and rarely reaches 1R. Take-profit at 2R and 2R with breakeven give Calmar 3.63 against 3.03, but that is one trade's difference in 22 and does not qualify as an improvement.

### 3d. 4h taker-absorb (m18 z2 T4), 25 positions

No exit change moves Sharpe or drawdown beyond noise. Signal flips account for 82–92% of closes.

## 4. Caveats

1. **Fold boundaries force a flat exit.** Each walk-forward fold closes any open position at its last bar, so the signal tail is truncated (the `eod` share, 0–9%). This slightly flatters the trailing and take-profit variants on short folds. It affects all variants alike.
2. **Single-period evidence.** The 1h result covers 108 days. The 4h Donchian covers 450 days. Neither covers a full regime cycle.
3. **Selection.** 13 exit variants on 4 entries, and the 1h scale-out result is the best of them. Treat its advantage as a candidate for a forward test, not a finding.
4. **Fees on breakeven.** A breakeven stop is placed exactly at entry, so it still loses the round-trip fee and slippage. The "BE" variants therefore carry a small hidden cost on each stop-out.
5. **Liquidation is unaffected.** Exits do not change the liquidation price. The stop must still sit inside the buffer at entry.

## 5. Implementation

- `research/engine.py`: `tp_r`, `be_r`, `trail_act_r`, `tp_frac` on `Risk`; take-profit (intrabar and gap), breakeven and activated trail ratchets; scale-out via `_Book.take_partial`; stop-kind tracking; `positions` in `metrics`.
- `research/exits.py`: the 13 exit variants, the four entries, position-level win rate, mean R and Calmar.
- `research/test_engine.py`: 54 tests. New: take-profit fills at the level with no slippage, stop wins a same-bar tie, take-profit gap fills at the open, no take-profit without a stop distance, breakeven moves the stop after 1R, trail waits for activation, trail exits after activation, no re-entry after take-profit, scale-out pnl exact, validation.

Regression: `research/results/sensitivity.txt` (trail surface from v5) is byte-identical after the change.

## 6. Verification

```
python3 -m unittest research.test_engine -v      # expect: Ran 54 tests ... OK
python3 -m research.exits                        # research/results/exits.txt
```

Expected: the 1h adaptive table shows `E0 stop only +16.7% +2.88 -9.1%` and `E10 scale 50% at 1R +11.1% +2.87 -5.7%`.

## 7. Next steps

1. **Forward-test one exit change at a time.** Start with the baseline exit on the 1h adaptive lead. Run the scale-out (E10) in parallel for at least 60 positions, and compare MDD and Sharpe.
2. **If drawdown is the constraint, prefer scale-out over trailing.** On the 1h lead, scale-out cuts MDD by about 37% (−9.1% to −5.7%) with Sharpe unchanged. The trail cuts MDD by about 35% but halves Sharpe (2.88 to 1.92).
3. **Do not add a fixed take-profit or scale-out to the 4h Donchian.** The 48-variant grid (section 3b-2) shows no variant beats the baseline on Sharpe, Calmar or return. The taker entries show no benefit either.
