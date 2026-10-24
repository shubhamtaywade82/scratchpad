"""Tests for research/binance_1m.py resampling. Run: python3 -m unittest research.test_binance_1m -v"""
import unittest
from array import array

from research.binance_1m import missing_minutes, resample

DAY = 86_400_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % DAY)  # 00:00 UTC
MIN = 60_000


def minutes(n, t0=T0, skip=()):
    cols = {k: array('d') for k in ('t', 'o', 'h', 'l', 'c', 'v', 'tb')}
    for i in range(n):
        if i in skip:
            continue
        p = 100.0 + i
        for k, val in zip(cols, (t0 + i * MIN, p, p + 0.5, p - 0.5, p + 0.25, 1.0, 0.4)):
            cols[k].append(val)
    return cols


class Resample(unittest.TestCase):
    def test_240_minutes_make_one_4h_bar(self):
        s = resample(minutes(240), '4h')
        self.assertEqual(len(s), 1)
        self.assertEqual((s.t[0], s.o[0], s.h[0], s.l[0], s.c[0]), (T0, 100.0, 339.5, 99.5, 339.25))
        self.assertAlmostEqual(s.v[0], 240.0)
        self.assertAlmostEqual(s.tb[0], 96.0)

    def test_bucket_with_missing_minute_is_dropped(self):
        cols = minutes(480, skip={300})
        s = resample(cols, '4h')
        self.assertEqual(s.t, [T0])
        self.assertEqual(missing_minutes(cols), 1)

    def test_buckets_align_to_utc_epoch_not_first_row(self):
        s = resample(minutes(300, t0=T0 + 30 * MIN), '1h')
        self.assertEqual(s.t, [T0 + h * 3_600_000 for h in (1, 2, 3, 4)])


if __name__ == '__main__':
    unittest.main()
