"""Forward-runner invariants. Run: python3 -m unittest research.test_forward -v"""
import random
import unittest

from research.forward import HOUR_MS, contiguous_prefix, replay

T0 = 1_700_000_000_000 - (1_700_000_000_000 % HOUR_MS)


def synth(n, seed):
    rnd = random.Random(seed)
    bars, c = [], 100.0
    for i in range(n):
        o = c
        c = max(1.0, c * (1 + rnd.gauss(0, 0.012)))
        h = max(o, c) * (1 + abs(rnd.gauss(0, 0.005)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, 0.005)))
        bars.append(dict(openTime=T0 + i * HOUR_MS, open=o, high=h, low=l, close=c, volume=1000.0))
    return bars


class ForwardReplay(unittest.TestCase):
    def test_appending_bars_never_changes_earlier_closed_trades(self):
        bars = synth(700, 11)
        start_t = bars[400]['openTime']                 # forward start, after warm-up
        short = replay(bars[:600], start_t)
        long_ = replay(bars[:700], start_t)
        cut = bars[599]['openTime']                    # every trade that closed at or before this bar is final
        for key in ('signal_closed', 'benchmark_closed'):
            early_short = [t for t in short[key] if t['exit_utc'] <= _iso(cut)]
            early_long = [t for t in long_[key] if t['exit_utc'] <= _iso(cut)]
            self.assertEqual(early_short, early_long, key)

    def test_waiting_when_no_bar_past_start(self):
        bars = synth(400, 3)
        out = replay(bars, bars[-1]['openTime'] + HOUR_MS)
        self.assertEqual(out['status'], 'WAITING')
        self.assertEqual(out['signal_equity'], 1.0)

    def test_contiguous_prefix_reports_first_gap(self):
        bars = synth(10, 5)
        del bars[4]
        run, gap = contiguous_prefix(bars)
        self.assertEqual(len(run), 4)
        self.assertEqual(gap, bars[3]['openTime'] + HOUR_MS)

    def test_open_position_is_not_reported_as_closed(self):
        bars = synth(500, 21)
        out = replay(bars, bars[300]['openTime'])
        for key in ('signal_closed', 'benchmark_closed'):
            self.assertTrue(all(t['reason'] != 'eod' for t in out[key]))


def _iso(ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


if __name__ == '__main__':
    unittest.main()
