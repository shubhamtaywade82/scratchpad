"""Invariant tests for research/engine.py. Run: python3 -m unittest research.test_engine -v"""
import math
import unittest

from research.engine import (Risk, Series, atr, donchian_sig, ema_gate, htf_gate, metrics,
                             simulate, to_series, tsmom_sig)

T0 = 1_700_000_000_000 - (1_700_000_000_000 % 3_600_000)  # hour-aligned epoch ms
HOUR = 3_600_000


def bars(ohlc, tf='1h', t0=T0):
    """ohlc: list of (o, h, l, c). Builds a Series with contiguous hourly opens."""
    step = {'1h': HOUR, '4h': 4 * HOUR, '1d': 24 * HOUR}[tf]
    rows = [dict(openTime=t0 + i * step, open=o, high=h, low=l, close=c) for i, (o, h, l, c) in enumerate(ohlc)]
    return to_series(tf, rows)


def flat(n, p=100.0):
    return [(p, p, p, p)] * n


class SignalAtOpen(unittest.TestCase):
    def test_signal_decided_at_close_executes_at_next_open(self):
        # bars 0..6, flat prices with distinct opens so the fill price identifies the bar
        ohlc = [(100 + i, 100 + i + 0.5, 100 + i - 0.5, 100 + i) for i in range(7)]
        s = bars(ohlc)
        sig = [0] * len(s)
        sig[2:5] = [1, 1, 1]  # target long, decided at closes of bars 2..4
        sig[5] = 0            # decided at close of bar 5 -> exit at open of bar 6
        r = simulate(s, sig, Risk(), 1, len(s), A=[1.0] * len(s), fee=0, slip=0)
        t = r.trades[0]
        self.assertEqual(t['k_in'], 3)
        self.assertEqual(t['ep'], s.o[3])
        self.assertEqual(t['k_out'], 6)
        self.assertEqual(t['px'], s.o[6])


class Stops(unittest.TestCase):
    def setUp(self):
        # bar 3 opens at 100 (entry); ATR fixed at 1.0 so a 2x stop sits at 98
        self.A = [1.0] * 10
        self.risk = Risk(sl_mult=2.0)

    def test_gap_through_stop_fills_at_open_not_stop(self):
        ohlc = flat(3) + [(100, 100.5, 99.5, 100), (97, 97.5, 96.5, 97)] + flat(5)
        s = bars(ohlc)
        sig = [0] * len(s); sig[2] = 1
        r = simulate(s, sig, self.risk, 1, len(s), A=self.A, fee=0, slip=0)
        t = r.trades[0]
        self.assertEqual(t['reason'], 'gap_stop')
        self.assertAlmostEqual(t['px'], 97.0)  # not 98
        self.assertAlmostEqual(t['pnl'], (97 - 100) * t['qty'])

    def test_intrabar_stop_fills_at_stop_level(self):
        ohlc = flat(3) + [(100, 100.5, 99.5, 100), (99, 100, 97.5, 98.5)] + flat(5)
        s = bars(ohlc)
        sig = [0] * len(s); sig[2:] = [1] * (len(s) - 2)
        r = simulate(s, sig, self.risk, 1, len(s), A=self.A, fee=0, slip=0)
        t = r.trades[0]
        self.assertEqual(t['reason'], 'stop')
        self.assertAlmostEqual(t['px'], 98.0)

    def test_stop_applies_to_bar_of_entry(self):
        # entry at open 100 and the same bar's low breaches the 98 stop
        ohlc = flat(3) + [(100, 100.5, 97.0, 99)] + flat(5)
        s = bars(ohlc)
        sig = [0] * len(s); sig[2] = 1
        r = simulate(s, sig, self.risk, 1, len(s), A=self.A, fee=0, slip=0)
        self.assertEqual(r.trades[0]['k_in'], r.trades[0]['k_out'])
        self.assertEqual(r.trades[0]['reason'], 'stop')

    def test_reentry_blocked_after_stop_until_signal_leaves_direction(self):
        ohlc = flat(3) + [(100, 100.5, 99.5, 100), (99, 100, 97.5, 98.5)] + flat(8)
        s = bars(ohlc)
        sig = [0] * len(s)
        sig[2:] = [1] * (len(s) - 2)           # signal stays long: must NOT re-enter after the stop
        r = simulate(s, sig, self.risk, 1, len(s), A=self.A, fee=0, slip=0)
        self.assertEqual(len(r.trades), 1)
        self.assertEqual(r.trades[0]['reason'], 'stop')

    def test_reentry_allowed_after_signal_resets(self):
        ohlc = flat(3) + [(100, 100.5, 99.5, 100), (99, 100, 97.5, 98.5)] + flat(8)
        s = bars(ohlc)
        sig = [0] * len(s)
        sig[2] = 1
        sig[6] = 0
        sig[8] = 1                              # fresh signal after reset -> allowed
        r = simulate(s, sig, self.risk, 1, len(s), A=self.A, fee=0, slip=0)
        self.assertEqual([t['k_in'] for t in r.trades], [3, 9])

    def test_trailing_stop_ratchets_and_exits(self):
        # long at 100; bar 3 high 101 -> chandelier 101 - 1*ATR(1) = 100; bar 4 low 99.5 hits it
        ohlc = flat(3) + [(100, 101, 99.8, 100.5), (100.5, 100.6, 99.5, 99.7)] + flat(5)
        s = bars(ohlc)
        sig = [0] * len(s); sig[2:] = [1] * (len(s) - 2)
        r = simulate(s, sig, Risk(trail_mult=1.0), 1, len(s), A=self.A, fee=0, slip=0)
        t = r.trades[0]
        self.assertEqual(t['reason'], 'stop')
        self.assertAlmostEqual(t['px'], 100.0)

    def test_trailing_stop_never_loosens(self):
        ohlc = flat(3) + [(100, 105, 100, 104), (104.5, 104.5, 100.5, 101)] + flat(4)
        s = bars(ohlc)
        sig = [0] * len(s); sig[2:] = [1] * (len(s) - 2)
        r = simulate(s, sig, Risk(sl_mult=2.0, trail_mult=1.0), 1, len(s), A=self.A, fee=0, slip=0)
        # after bar 3 stop = max(98, 105-1)=104; bar 4 low 100.5 breaches 104 -> exit at 104 (not 98)
        self.assertEqual(r.trades[0]['reason'], 'stop')
        self.assertAlmostEqual(r.trades[0]['px'], 104.0)


class Accounting(unittest.TestCase):
    def test_equity_marked_to_market_at_close(self):
        ohlc = flat(3) + [(100, 100, 90, 92)] + flat(4)   # bar 3 closes 8% below entry, no stop
        s = bars(ohlc)
        sig = [0] * len(s); sig[2] = 1
        r = simulate(s, sig, Risk(), 1, len(s), A=[1.0] * len(s), fee=0, slip=0)
        self.assertAlmostEqual(r.eq[3 - 1], 1 + (92 - 100) * (1 / 100))  # open trade loss visible at bar 3

    def test_funding_charged_to_longs_when_rate_positive(self):
        ohlc = flat(8, 100.0)
        s = bars(ohlc)
        sig = [0] * len(s); sig[1:] = [1] * (len(s) - 1)
        fund_t, fund_r = [s.t[4]], [0.001]          # one funding event exactly at bar 4's open
        r = simulate(s, sig, Risk(), 1, len(s), A=[1.0] * len(s), fund_t=fund_t, fund_r=fund_r, fee=0, slip=0)
        # qty = 1/100 = 0.01; payment = qty * close[3] * rate = 0.01*100*0.001 = 0.001
        self.assertAlmostEqual(r.eq[4 - 1], 1 - 0.001)

    def test_funding_received_by_shorts_when_rate_positive(self):
        ohlc = flat(8, 100.0)
        s = bars(ohlc)
        sig = [0] * len(s); sig[1:] = [-1] * (len(s) - 1)
        r = simulate(s, sig, Risk(), 1, len(s), A=[1.0] * len(s), fund_t=[s.t[4]], fund_r=[0.001], fee=0, slip=0)
        self.assertAlmostEqual(r.eq[4 - 1], 1 + 0.001)

    def test_costs_reduce_round_trip_by_fee_and_slip(self):
        ohlc = flat(8, 100.0)
        s = bars(ohlc)
        sig = [0] * len(s); sig[1:4] = [1, 1, 1]; sig[4] = 0
        r = simulate(s, sig, Risk(), 1, len(s), A=[1.0] * len(s), fee=0.0005, slip=0.0003)
        t = r.trades[0]
        self.assertLess(t['pnl'], 0)
        # entry fills at 100*(1+slip)=100.03, exit at 100*(1-slip)=99.97; qty = E / entry_px
        q = t['qty']
        self.assertAlmostEqual(q, 1 / 100.03)
        expected = q * (99.97 - 100.03) - 0.0005 * q * 100.03 - 0.0005 * q * 99.97
        self.assertAlmostEqual(t['pnl'], expected, 12)

    def test_risk_sizing_matches_risk_budget(self):
        ohlc = flat(8, 100.0)
        s = bars(ohlc)
        sig = [0] * len(s); sig[1:5] = [1] * 4; sig[5] = 0
        risk = Risk(sizing='risk', risk_pct=0.01, sl_mult=2.0, lev=10.0)
        r = simulate(s, sig, risk, 1, len(s), A=[1.0] * len(s), fee=0, slip=0)
        # stop distance = 2 * ATR(1) = 2 -> qty = 0.01 * 1 / 2 = 0.005
        self.assertAlmostEqual(r.trades[0]['qty'], 0.005)

    def test_risk_sizing_capped_by_leverage(self):
        ohlc = flat(8, 100.0)
        s = bars(ohlc)
        sig = [0] * len(s); sig[1:5] = [1] * 4; sig[5] = 0
        risk = Risk(sizing='risk', risk_pct=0.01, sl_mult=0.01, lev=1.0)  # tiny stop -> huge uncapped qty
        r = simulate(s, sig, risk, 1, len(s), A=[1.0] * len(s), fee=0, slip=0)
        self.assertAlmostEqual(r.trades[0]['qty'], 1.0 / 100.0)  # notional capped at 1x equity

    def test_window_flattens_at_end(self):
        s = bars(flat(8, 100.0))
        sig = [1] * len(s)
        r = simulate(s, sig, Risk(), 1, 6, A=[1.0] * len(s), fee=0, slip=0)
        self.assertEqual(r.trades[-1]['reason'], 'eod')
        self.assertEqual(r.pos[-1], 0)

    def test_metrics_drawdown_includes_unrealised_loss(self):
        ohlc = flat(3) + [(100, 100, 90, 90)] + [(90, 100, 90, 100)] + flat(3, 100.0)
        s = bars(ohlc)
        sig = [0] * len(s); sig[2] = 1
        r = simulate(s, sig, Risk(), 1, len(s), A=[1.0] * len(s), fee=0, slip=0)
        m = metrics(r, '1h')
        self.assertLess(m['mdd'], -0.09)   # the bar-3 close at 90 must show in MDD even though it recovered


class Signals(unittest.TestCase):
    def test_atr_constant_range(self):
        s = bars([(100, 101, 99, 100)] * 30)
        a = atr(s, 14)
        self.assertIsNone(a[12])
        self.assertAlmostEqual(a[13], 2.0)
        self.assertAlmostEqual(a[29], 2.0)

    def test_donchian_breakout_midline_exit_and_reversal(self):
        closes = [100] * 5 + [110, 111, 112, 110.5, 99]
        ohlc = [(c, c + 0.5, c - 0.5, c) for c in closes]
        s = bars(ohlc)
        sig = donchian_sig(s, 3)
        self.assertEqual(sig[5], 1)            # 110 > prior 3-bar high 100.5: breakout long
        self.assertEqual(sig[7], 1)            # 112 extends the trend
        self.assertEqual(sig[8], 0)            # 110.5 closes below channel mid-line (111): exit flat
        self.assertEqual(sig[9], -1)           # 99 breaks prior 3-bar low (110): breakout short

    def test_gate_blocks_entries_against_trend(self):
        closes = [100] * 5 + [110]
        ohlc = [(c, c + 0.5, c - 0.5, c) for c in closes]
        s = bars(ohlc)
        sig = donchian_sig(s, 3, gate=[-1] * len(s))   # bearish gate: no long breakouts
        self.assertEqual(sig[5], 0)

    def test_htf_gate_flips_only_after_htf_bar_closes(self):
        # 4h bars 0..4 close at 100 (EMA(3)=100, close not above -> gate -1). 4h bar 5 closes at 200 (gate +1).
        # 4h bar 5 opens at T0+20h and CLOSES at T0+24h. The 1h bar opening at T0+23h must still see -1.
        closes = [100] * 5 + [200] * 3
        htf = bars([(c, c + 1, c - 1, c) for c in closes], tf='4h')
        base = bars([(100, 101, 99, 100)] * 30, tf='1h')
        g = htf_gate(base, htf, 3)
        self.assertEqual(g[23], -1)   # 4h bar 5 not closed yet
        self.assertEqual(g[24], 1)    # first base bar opening at the 4h close sees the new state

    def test_series_rejects_gap(self):
        rows = [dict(openTime=T0 + i * HOUR, open=1, high=1, low=1, close=1) for i in range(5)]
        del rows[2]
        with self.assertRaises(ValueError):
            to_series('1h', rows)

    def test_series_rejects_malformed_ohlc(self):
        rows = [dict(openTime=T0, open=10, high=9, low=8, close=9.5)]   # high < open
        with self.assertRaises(ValueError):
            to_series('1h', rows)

    def test_risk_sizing_without_stop_distance_skips_entry(self):
        s = bars(flat(10))
        r = simulate(s, [1] * 10, Risk(sizing='risk'), 1, 10, A=[1.0] * 10)
        self.assertEqual(r.trades, [])
        self.assertEqual(r.skipped, 1)          # one attempt per signal episode, no retry


class Leverage(unittest.TestCase):
    """Isolated-margin liquidation, liquidation-buffer entry rule, structural stops, ruin."""

    def test_intrabar_liquidation_at_liquidation_price(self):
        # lev 10: liquidation distance = 1/10 - 0.005 = 9.5%. Long at 100 -> liq 90.5. Bar 4 low 90 breaches it.
        ohlc = flat(3) + [(100, 100.5, 99.5, 100), (100, 100.2, 90.0, 95)] + flat(5)
        s = bars(ohlc)
        sig = [0] * len(s); sig[2:] = [1] * (len(s) - 2)
        r = simulate(s, sig, Risk(lev=10.0), 1, len(s), A=[1.0] * len(s), fee=0, slip=0)
        t = r.trades[0]
        self.assertEqual(t['reason'], 'liq')
        self.assertAlmostEqual(t['px'], 100 * (1 - (1 / 10 - 0.005)))

    def test_gap_through_liquidation_fills_at_open(self):
        ohlc = flat(3) + [(100, 100.5, 99.5, 100), (85, 86, 84, 85)] + flat(5)   # open 85 is below liq 90.5
        s = bars(ohlc)
        sig = [0] * len(s); sig[2:] = [1] * (len(s) - 2)
        r = simulate(s, sig, Risk(lev=10.0), 1, len(s), A=[1.0] * len(s), fee=0, slip=0)
        self.assertEqual(r.trades[0]['reason'], 'liq')
        self.assertAlmostEqual(r.trades[0]['px'], 85.0)

    def test_entry_skipped_when_stop_beyond_liquidation_buffer(self):
        # lev 15: liq 6.17%, buffer 0.8 -> max stop 4.93%. 3 x ATR(=3) on price 100 is a 9% stop: skip, one attempt.
        s = bars(flat(10))
        sig = [0] * len(s); sig[2:] = [1] * (len(s) - 2)
        r = simulate(s, sig, Risk(sizing='risk', lev=15.0, sl_mult=3.0), 1, len(s), A=[3.0] * len(s), fee=0, slip=0)
        self.assertEqual(r.trades, [])
        self.assertEqual(r.skipped, 1)

    def test_entry_allowed_when_stop_inside_buffer(self):
        s = bars(flat(10))
        sig = [0] * len(s); sig[2:] = [1] * (len(s) - 2)
        r = simulate(s, sig, Risk(sizing='risk', lev=15.0, sl_mult=1.0), 1, len(s), A=[3.0] * len(s), fee=0, slip=0)
        self.assertGreater(len(r.trades), 0)   # 3% stop < 4.93%

    def test_fixed_notional_equals_leverage_times_equity(self):
        s = bars(flat(6))
        sig = [0] * len(s); sig[1:4] = [1, 1, 1]
        r = simulate(s, sig, Risk(lev=5.0), 1, len(s), A=[1.0] * len(s), fee=0, slip=0)
        self.assertAlmostEqual(r.trades[0]['eff_lev'], 5.0)

    def test_structural_stop_sets_size_and_is_used(self):
        s = bars(flat(8))
        sig = [0] * len(s); sig[1:5] = [1, 1, 1, 1]; sig[5] = 0
        sp = [None] * len(s); sp[1] = 98.0           # structural stop for the entry at the open of bar 2
        r = simulate(s, sig, Risk(sizing='risk', risk_pct=0.01, lev=10.0), 1, len(s),
                     A=[1.0] * len(s), stop_px=sp, fee=0, slip=0)
        t = r.trades[0]
        self.assertAlmostEqual(t['qty'], 0.01 / 2.0)   # d = |100 - 98| = 2 -> qty = 1% / 2

    def test_structural_stop_on_wrong_side_is_skipped(self):
        s = bars(flat(8))
        sig = [0] * len(s); sig[1:5] = [1, 1, 1, 1]
        sp = [None] * len(s); sp[1] = 103.0           # long with stop above entry
        r = simulate(s, sig, Risk(sizing='risk', lev=10.0), 1, len(s), A=[1.0] * len(s), stop_px=sp, fee=0, slip=0)
        self.assertEqual(r.trades, [])
        self.assertEqual(r.skipped, 1)

    def test_ruin_floors_equity_at_zero_and_stops_trading(self):
        # lev 1 short at 100 -> liq at 199.5. Gap up to 400 loses 3x the account: equity floors at 0.
        ohlc = flat(3) + [(100, 100, 100, 100), (400, 401, 399, 400)] + flat(8, 400)
        s = bars(ohlc)
        sig = [0] * len(s); sig[1:] = [-1] * (len(s) - 1)
        r = simulate(s, sig, Risk(lev=1.0), 1, len(s), A=[1.0] * len(s), fee=0, slip=0)
        self.assertTrue(r.ruined)
        self.assertEqual(r.eq[-1], 0.0)
        self.assertEqual(len(r.trades), 1)           # no re-entry on a ruined account

    def test_returns_from_levels_handles_zero_equity(self):
        from research.engine import returns_from_levels
        self.assertEqual(returns_from_levels([0.5, 0.0, 0.0]), [-0.5, -1.0, 0.0])

    def test_validate_rejects_leverage_without_liquidation_distance(self):
        with self.assertRaises(ValueError):
            Risk(lev=300.0).validate()                 # 1/300 < mmr 0.5%


class Ideas(unittest.TestCase):
    def test_sweep_fade_sets_structural_stop_beyond_wick(self):
        from research.ideas import sweep_fade
        # 16 warm-up bars range 99..101 (prior 3-bar high 101); bar 15 wicks to 103 and closes at 100.5: bearish sweep
        ohlc = [(100, 101, 99, 100)] * 15 + [(100, 103, 99.5, 100.5)] + [(100, 100.5, 99.5, 100)] * 4
        s = bars(ohlc)
        sig, sp = sweep_fade(s, 3, 2, buf=0.0)
        self.assertEqual(sig[15], -1)
        self.assertAlmostEqual(sp[15], 103.0)
        self.assertEqual(sig[16], -1)
        self.assertEqual(sig[17], 0)                # held for T=2 bars

    def test_taker_imbalance_requires_taker_volume(self):
        from research.ideas import taker_imbalance
        s = bars(flat(5))
        with self.assertRaises(ValueError):
            taker_imbalance(s, 2)

    def test_hmm_filter_probabilities_sum_to_one(self):
        from research.ideas import hmm_filter
        x = [0.1, -0.2, 0.3, -0.1, 0.05, 2.0, 1.8, 2.2]
        probs = hmm_filter(x, [0.5, 0.5], [[0.9, 0.1], [0.1, 0.9]], [0.0, 1.5], [0.5, 0.5])
        for p in probs:
            self.assertAlmostEqual(sum(p), 1.0, 9)


class AdaptiveST(unittest.TestCase):
    @staticmethod
    def _random_bars(n, seed):
        import random
        rnd = random.Random(seed)
        c = 100.0
        ohlc = []
        for _ in range(n):
            o = c
            c = max(1.0, c * (1 + rnd.gauss(0, 0.01)))
            h = max(o, c) * (1 + abs(rnd.gauss(0, 0.004)))
            l = min(o, c) * (1 - abs(rnd.gauss(0, 0.004)))
            ohlc.append((o, h, l, c))
        return bars(ohlc)

    @staticmethod
    def _truncate(s, m):
        return Series(s.tf, s.t[:m], s.o[:m], s.h[:m], s.l[:m], s.c[:m])

    def test_dynamic_supertrend_with_constant_multiplier_matches_engine(self):
        from research.adaptive_st import supertrend_dyn
        from research.engine import atr, supertrend_sig
        s = self._random_bars(300, 1)
        A = atr(s, 10)
        dyn = supertrend_dyn(s, A, [3.0] * len(s))
        self.assertEqual(dyn, supertrend_sig(s, 10, 3.0))

    def test_vol_adaptive_is_causal(self):
        from research.adaptive_st import vol_adaptive_st_sig
        s = self._random_bars(400, 2)
        full = vol_adaptive_st_sig(s, 10, 50, 2.0, 4.0)
        m = 250
        part = vol_adaptive_st_sig(self._truncate(s, m), 10, 50, 2.0, 4.0)
        self.assertEqual(full[:m], part)            # future bars must not change any past signal

    def test_perf_adaptive_is_causal(self):
        from research.adaptive_st import perf_adaptive_st_sig
        s = self._random_bars(400, 3)
        full = perf_adaptive_st_sig(s, 10, 20)
        m = 250
        part = perf_adaptive_st_sig(self._truncate(s, m), 10, 20)
        self.assertEqual(full[:m], part)

    def test_perf_adaptive_follows_the_only_instance_that_is_right(self):
        # strictly rising closes: long direction wins for every multiplier; the chosen signal must be +1 after warm-up
        from research.adaptive_st import perf_adaptive_st_sig
        ohlc = [(100 + i, 100 + i + 0.5, 100 + i - 0.5, 100 + i + 0.2) for i in range(60)]
        sig = perf_adaptive_st_sig(bars(ohlc), 10, 20)
        self.assertTrue(all(v == 1 for v in sig[30:]))


class DelaySig(unittest.TestCase):
    def test_delay_shifts_forward_and_zero_fills(self):
        from research.engine import delay_sig
        self.assertEqual(delay_sig([1, 2, 3, 4], 2), [0, 0, 1, 2])
        self.assertEqual(delay_sig([1, 2, 3], 0), [1, 2, 3])

    def test_negative_delay_is_rejected(self):
        from research.engine import delay_sig
        with self.assertRaises(ValueError):
            delay_sig([1, 2, 3], -1)


class Exits(unittest.TestCase):
    """Take-profit, breakeven and trail activation. Entry at bar 3's open (100), stop 2 x ATR(1) = 98, 1R = 2."""

    def setUp(self):
        self.A = [1.0] * 12

    def _sig(self, s):
        sig = [0] * len(s)
        sig[2:] = [1] * (len(s) - 2)
        return sig

    def test_take_profit_fills_at_level_without_slippage(self):
        ohlc = flat(3) + [(100, 104, 99.5, 103.5)] + flat(6, 103.5)
        s = bars(ohlc)
        r = simulate(s, self._sig(s), Risk(sl_mult=2.0, tp_r=1.5), 1, len(s), A=self.A, fee=0, slip=0.0003)
        t = r.trades[0]
        self.assertEqual(t['reason'], 'tp')
        self.assertAlmostEqual(t['px'], t['ep'] + 1.5 * 2.0)   # limit price, no slippage applied
        self.assertAlmostEqual(t['r'], 1.5)

    def test_stop_wins_a_same_bar_tie_with_take_profit(self):
        ohlc = flat(3) + [(100, 104, 97.0, 103.5)] + flat(6, 103.5)   # both 98 stop and 103 target touched
        s = bars(ohlc)
        r = simulate(s, self._sig(s), Risk(sl_mult=2.0, tp_r=1.5), 1, len(s), A=self.A, fee=0, slip=0)
        self.assertEqual(r.trades[0]['reason'], 'stop')

    def test_take_profit_gap_fills_at_open(self):
        ohlc = flat(3) + [(100, 100.5, 99.5, 100), (105, 106, 104.5, 105.5)] + flat(6, 105.5)
        s = bars(ohlc)
        r = simulate(s, self._sig(s), Risk(sl_mult=2.0, tp_r=1.5), 1, len(s), A=self.A, fee=0, slip=0)
        t = r.trades[0]
        self.assertEqual(t['reason'], 'tp_gap')
        self.assertAlmostEqual(t['px'], 105.0)

    def test_no_take_profit_without_a_stop_distance(self):
        ohlc = flat(3) + [(100, 110, 99.5, 109)] + flat(6, 109)
        s = bars(ohlc)
        r = simulate(s, self._sig(s), Risk(tp_r=1.5), 1, len(s), A=self.A, fee=0, slip=0)
        self.assertEqual(r.trades[0]['reason'], 'eod')

    def test_breakeven_moves_stop_to_entry_after_one_r(self):
        ohlc = flat(3) + [(100, 102.5, 99.5, 102)] + [(101, 101.5, 99.5, 100.5)] + flat(6, 100.5)
        s = bars(ohlc)
        r = simulate(s, self._sig(s), Risk(sl_mult=2.0, be_r=1.0), 1, len(s), A=self.A, fee=0, slip=0)
        t = r.trades[0]
        self.assertEqual(t['reason'], 'stop')
        self.assertEqual(t['kind'], 'be')
        self.assertAlmostEqual(t['px'], 100.0)
        self.assertAlmostEqual(t['r'], 0.0)

    def test_trail_waits_for_activation(self):
        # bar 3 reaches only 1.25R; bar 4 low 99 would breach a chandelier stop of 101.5, but not the 98 initial stop
        ohlc = flat(3) + [(100, 102.5, 99.5, 102)] + [(102, 102, 99, 99.5)] + flat(6, 99.5)
        s = bars(ohlc)
        r = simulate(s, self._sig(s), Risk(sl_mult=2.0, trail_mult=1.0, trail_act_r=2.0), 1, len(s),
                     A=self.A, fee=0, slip=0)
        self.assertEqual(r.trades[0]['reason'], 'eod')           # trail not yet active: no early exit

    def test_trail_active_after_activation_exits_on_chandelier(self):
        ohlc = flat(3) + [(100, 102.5, 99.5, 102)] + [(102, 102, 99, 99.5)] + flat(6, 99.5)
        s = bars(ohlc)
        r = simulate(s, self._sig(s), Risk(sl_mult=2.0, trail_mult=1.0, trail_act_r=1.0), 1, len(s),
                     A=self.A, fee=0, slip=0)
        t = r.trades[0]
        self.assertEqual(t['kind'], 'trail')
        self.assertAlmostEqual(t['px'], 101.5)                  # 102.5 extreme - 1 x ATR

    def test_no_reentry_after_take_profit_while_signal_persists(self):
        ohlc = flat(3) + [(100, 104, 99.5, 103.5)] + flat(6, 103.5)
        s = bars(ohlc)
        r = simulate(s, self._sig(s), Risk(sl_mult=2.0, tp_r=1.5), 1, len(s), A=self.A, fee=0, slip=0)
        self.assertEqual(len(r.trades), 1)

    def test_validate_rejects_bad_exit_parameters(self):
        for bad in (Risk(tp_r=0.0), Risk(be_r=-1.0), Risk(trail_act_r=-0.5)):
            with self.assertRaises(ValueError):
                bad.validate()


class ScaleOut(unittest.TestCase):
    def test_partial_then_signal_exit_pnl_is_exact(self):
        # entry 100 with d = 2 (2 x ATR 1); qty = 1% / 2 = 0.005. Half closes at the 102 target (1R) on bar 3.
        # Remainder exits at bar 6's open (101.5) when the signal drops to flat.
        ohlc = flat(3) + [(100, 103, 99.5, 102.5)] + [(102, 102.5, 101, 101.5)] + flat(6, 101.5)
        s = bars(ohlc)
        sig = [0] * len(s); sig[2:5] = [1, 1, 1]           # desired long at the opens of bars 3, 4, 5
        r = simulate(s, sig, Risk(sizing='risk', sl_mult=2.0, tp_r=1.0, tp_frac=0.5), 1, len(s), A=[1.0] * len(s),
                     fee=0, slip=0)
        self.assertEqual([t['reason'] for t in r.trades], ['tp_partial', 'signal'])
        q = 0.005
        self.assertAlmostEqual(r.trades[0]['qty'], q / 2)
        self.assertAlmostEqual(r.trades[0]['px'], 102.0)
        self.assertAlmostEqual(r.trades[1]['px'], 101.5)
        expected = (q / 2) * (102.0 - 100.0) + (q / 2) * (101.5 - 100.0)
        self.assertAlmostEqual(sum(t['pnl'] for t in r.trades), expected, 12)

    def test_scale_out_keeps_position_open(self):
        ohlc = flat(3) + [(100, 103, 99.5, 102.5)] + flat(6, 102.5)
        s = bars(ohlc)
        sig = [0] * len(s); sig[2:] = [1] * (len(s) - 2)
        r = simulate(s, sig, Risk(sl_mult=2.0, tp_r=1.0, tp_frac=0.5), 1, len(s), A=[1.0] * len(s), fee=0, slip=0)
        reasons = [t['reason'] for t in r.trades]
        self.assertIn('tp_partial', reasons)
        self.assertEqual(reasons[-1], 'eod')                 # the remainder is still held to the window end
        self.assertEqual(r.pos[-1], 0)

    def test_tp_frac_validation(self):
        for bad in (0.0, 1.5, -0.5):
            with self.assertRaises(ValueError):
                Risk(tp_frac=bad).validate()


class LedgerReconciliation(unittest.TestCase):
    def test_trade_ledger_reconciles_with_equity_under_funding_and_fees(self):
        ohlc = flat(2) + [(100, 105, 98, 103)] + [(103, 106, 101, 104)] + [(104, 105, 99, 100)] + flat(3, 100)
        s = bars(ohlc)
        sig = [0] * len(s)
        sig[1:4] = [1, 1, 1]
        fund_t = [s.t[2] + 1000, s.t[3] + 1000]
        fund_r = [0.001, -0.0005]
        r = simulate(s, sig, Risk(sizing='fixed', lev=2.0), 1, len(s), fund_t=fund_t, fund_r=fund_r)
        self.assertGreater(len(r.trades), 0)
        for t in r.trades:
            self.assertIn('funding', t)
            self.assertAlmostEqual(t['pnl'], t['gross'] - t['exit_fee'] - t['entry_fee'] + t['funding'], 12)
        # Final equity must exactly match 1.0 + sum of all trade PnLs
        self.assertAlmostEqual(1.0 + sum(t['pnl'] for t in r.trades), r.eq[-1], 12)


if __name__ == '__main__':
    unittest.main()
