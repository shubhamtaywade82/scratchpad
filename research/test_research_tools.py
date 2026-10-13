"""Invariants for the cross-asset, expectancy and quarter-hour tools. Run: python3 -m unittest research.test_research_tools -v"""
import unittest

import numpy as np

from research.cross_asset import features
from research.expectancy import mean_ci, positions_net, win_rate_note, wilson
from research.quarter_hour import corr


class CrossAsset(unittest.TestCase):
    def test_target_never_equals_a_feature(self):
        rng = np.random.default_rng(0)
        ls, lb, le = (np.cumsum(rng.normal(0, 0.01, 200)) for _ in range(3))
        X, y = features(ls, lb, le, 'ALL')
        for c in range(X.shape[1]):
            self.assertFalse(np.allclose(X[:, c], y))

    def test_features_use_current_and_lag_intervals_target_is_next(self):
        rng = np.random.default_rng(1)
        ls, lb, le = (np.cumsum(rng.normal(0, 0.01, 50)) for _ in range(3))
        X, y = features(ls, lb, le, 'OWN')
        r = np.diff(ls)
        self.assertTrue(np.allclose(X[:, 0], r[1:-1]))      # current interval
        self.assertTrue(np.allclose(X[:, 1], r[:-2]))       # lag interval
        self.assertTrue(np.allclose(y, r[2:]))              # next interval


class Expectancy(unittest.TestCase):
    def test_wilson_interval_contains_point_estimate(self):
        lo, hi = wilson(30, 100)
        self.assertLess(lo, 0.30)
        self.assertGreater(hi, 0.30)

    def test_expectancy_example_from_the_report(self):
        # 55% win rate, 200 average win, 300 average loss -> -25 (report's worked example)
        self.assertAlmostEqual(0.55 * 200 - 0.45 * 300, -25)

    def test_win_rate_note_reports_interval_below_50(self):
        # Regression: the old check `hi < 0.5 < lo` could never be true, so an interval entirely below 50% printed "includes 50%"
        self.assertIn('below', win_rate_note(*wilson(19, 56)))      # 19 of 56 (33.9%), CI 22.9%..47.0%, as for the 1h cell
        self.assertIn('above', win_rate_note(*wilson(70, 100)))
        self.assertIn('includes', win_rate_note(*wilson(50, 100)))

    def test_mean_ci_brackets_sample_mean(self):
        rets = [0.02, -0.005, 0.03, -0.01, 0.015, -0.005, 0.04, -0.008]
        lo, hi = mean_ci(rets, B=2000)
        self.assertLess(lo, sum(rets) / len(rets))
        self.assertGreater(hi, sum(rets) / len(rets))

    def test_mean_ci_degenerate_for_constant_returns(self):
        lo, hi = mean_ci([0.01] * 10, B=200)
        self.assertAlmostEqual(lo, 0.01)
        self.assertAlmostEqual(hi, 0.01)

    def test_partial_closes_sum_into_one_position(self):
        trades = [dict(side=1, k_in=5, ep=10.0, ret=0.01), dict(side=1, k_in=5, ep=10.0, ret=0.02),
                  dict(side=-1, k_in=5, ep=10.0, ret=-0.01)]
        self.assertEqual(sorted(positions_net(trades)), [-0.01, 0.03])


class Corr(unittest.TestCase):
    def test_perfect_correlation(self):
        self.assertAlmostEqual(corr([1, 2, 3, 4], [2, 4, 6, 8]), 1.0)


if __name__ == '__main__':
    unittest.main()
