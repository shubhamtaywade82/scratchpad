"""Causality and sanity tests for research/webstrats.py. Run: python3 -m unittest research.test_webstrats -v"""
import random
import unittest

from research.engine import Series, tsmom_sig
from research.webstrats import adx, adx_gated, squeeze_sig, supertrend_dirs

T0 = 1_700_000_000_000 - (1_700_000_000_000 % 3_600_000)


def synth(n, seed):
    rnd = random.Random(seed)
    t, o, h, l, c = [], [], [], [], []
    price = 100.0
    for i in range(n):
        op = price
        price = max(1.0, price * (1 + rnd.gauss(0, 0.01)))
        t.append(T0 + i * 3_600_000)
        o.append(op)
        c.append(price)
        h.append(max(op, price) * (1 + abs(rnd.gauss(0, 0.004))))
        l.append(min(op, price) * (1 - abs(rnd.gauss(0, 0.004))))
    return Series('1h', t, o, h, l, c)


def trunc(s, m):
    return Series(s.tf, s.t[:m], s.o[:m], s.h[:m], s.l[:m], s.c[:m])


class WebStrats(unittest.TestCase):
    def test_adx_is_causal(self):
        s = synth(300, 1)
        full, part = adx(s, 14), adx(trunc(s, 200), 14)
        self.assertEqual(full[:200], part)

    def test_squeeze_is_causal(self):
        s = synth(300, 2)
        full, part = squeeze_sig(s), squeeze_sig(trunc(s, 200))
        self.assertEqual(full[:200], part)

    def test_adx_gate_is_causal(self):
        s = synth(300, 3)
        dirs_full = supertrend_dirs(s, 10, 3.0)
        dirs_part = supertrend_dirs(trunc(s, 200), 10, 3.0)
        a_full, a_part = adx(s, 14), adx(trunc(s, 200), 14)
        self.assertEqual(adx_gated(dirs_full, a_full, 20.0)[:200], adx_gated(dirs_part, a_part, 20.0))

    def test_tsmom_short_is_causal(self):
        s = synth(300, 4)
        self.assertEqual(tsmom_sig(s, 5)[:200], tsmom_sig(trunc(s, 200), 5))

    def test_adx_separates_trend_from_chop(self):
        up = Series('1h', [T0 + i * 3_600_000 for i in range(80)],
                    [100 + i for i in range(80)], [100.5 + i for i in range(80)],
                    [99.5 + i for i in range(80)], [100.3 + i for i in range(80)])
        chop_c = [100 + (0.5 if i % 2 else -0.5) for i in range(80)]
        chop = Series('1h', up.t, [100] * 80, [101] * 80, [99] * 80, chop_c)
        self.assertGreater(adx(up, 14)[-1], 50)
        self.assertLess(adx(chop, 14)[-1], 10)


if __name__ == '__main__':
    unittest.main()
