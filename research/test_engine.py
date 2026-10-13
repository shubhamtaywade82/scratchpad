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
        risk = Risk(sizing='risk', risk_pct=0.01, sl_mult=2.0, max_gross=10.0)
        r = simulate(s, sig, risk, 1, len(s), A=[1.0] * len(s), fee=0, slip=0)
        # stop distance = 2 * ATR(1) = 2 -> qty = 0.01 * 1 / 2 = 0.005
        self.assertAlmostEqual(r.trades[0]['qty'], 0.005)

    def test_risk_sizing_capped_by_max_gross(self):
        ohlc = flat(8, 100.0)
        s = bars(ohlc)
        sig = [0] * len(s); sig[1:5] = [1] * 4; sig[5] = 0
        risk = Risk(sizing='risk', risk_pct=0.01, sl_mult=0.01, max_gross=1.0)  # tiny stop -> huge uncapped qty
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

    def test_risk_rejects_risk_sizing_without_stop(self):
        s = bars(flat(10))
        with self.assertRaises(ValueError):
            simulate(s, [1] * 10, Risk(sizing='risk'), 1, 10, A=[1.0] * 10)


if __name__ == '__main__':
    unittest.main()
