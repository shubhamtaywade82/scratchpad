"""Tests for live/dry-run execution adapter.

Run: python3 -m unittest research.test_execution -v
"""
import unittest
from research.engine import Risk
from research.execution import MarketContext, OKXPerpAdapter, OrderPlan, plan_order


class TestExecution(unittest.TestCase):
    def setUp(self):
        self.risk = Risk(sizing='risk', risk_pct=0.01, lev=5.0, sl_mult=3.0, liq_buffer=0.8, mmr=0.005)

    def test_plan_long_order(self):
        ctx = MarketContext(equity=10000.0, entry_px=100.0, atr=1.0, side=1)
        plan = plan_order(ctx, self.risk)
        self.assertEqual(plan.side_str, 'buy')
        self.assertAlmostEqual(plan.stop_px, 97.0)
        self.assertAlmostEqual(plan.stop_dist_pct, 0.03)
        # 1% risk of 10000 is 100 USD. Stop dist is 3%. Notional = 100 / 0.03 = 3333.33 USD
        self.assertAlmostEqual(plan.notional, 10000 * 0.01 / 0.03)
        self.assertAlmostEqual(plan.qty, plan.notional / 100.0)
        self.assertLessEqual(plan.eff_lev, self.risk.lev)

    def test_plan_short_order(self):
        ctx = MarketContext(equity=10000.0, entry_px=100.0, atr=1.0, side=-1)
        plan = plan_order(ctx, self.risk)
        self.assertEqual(plan.side_str, 'sell')
        self.assertAlmostEqual(plan.stop_px, 103.0)
        self.assertAlmostEqual(plan.stop_dist_pct, 0.03)
        self.assertAlmostEqual(plan.notional, 10000 * 0.01 / 0.03)

    def test_leverage_ceiling_cap(self):
        # Very tight ATR (0.1 on 100 px = 0.3% stop). Budget notional would be 33k (3.3x).
        # But if risk.lev = 2.0, max notional is 20k.
        tight_risk = Risk(sizing='risk', risk_pct=0.01, lev=2.0, sl_mult=3.0, liq_buffer=0.8, mmr=0.005)
        ctx = MarketContext(equity=10000.0, entry_px=100.0, atr=0.05, side=1)
        plan = plan_order(ctx, tight_risk)
        self.assertEqual(plan.notional, 20000.0)
        self.assertEqual(plan.eff_lev, 2.0)

    def test_liquidation_buffer_violation_raises(self):
        # ATR 10 on 100 px = 30% stop.
        # For lev 5x, liq_dist = 1/5 - 0.005 = 0.195. 80% buffer = 0.156.
        # 30% stop > 15.6% max stop -> must raise ValueError.
        ctx = MarketContext(equity=10000.0, entry_px=100.0, atr=10.0, side=1)
        with self.assertRaises(ValueError) as err:
            plan_order(ctx, self.risk)
        self.assertIn("exceeds liquidation safety limit", str(err.exception))

    def test_invalid_market_inputs_raise(self):
        ctx_neg_eq = MarketContext(equity=-100.0, entry_px=100.0, atr=1.0, side=1)
        with self.assertRaises(ValueError):
            plan_order(ctx_neg_eq, self.risk)

        ctx_bad_side = MarketContext(equity=1000.0, entry_px=100.0, atr=1.0, side=0)
        with self.assertRaises(ValueError):
            plan_order(ctx_bad_side, self.risk)

    def test_adapter_signature_and_headers(self):
        adapter = OKXPerpAdapter(key="my_key", secret="my_secret", passphrase="my_pass", is_sim=True)
        headers = adapter.sign_headers("GET", "/api/v5/account/balance")
        self.assertEqual(headers["OKX-ACCESS-KEY"], "my_key")
        self.assertEqual(headers["OKX-ACCESS-PASSPHRASE"], "my_pass")
        self.assertTrue(headers["OKX-ACCESS-TIMESTAMP"].endswith("Z"))
        self.assertTrue(len(headers["OKX-ACCESS-SIGN"]) > 10)

    def test_adapter_dry_run_execution(self):
        adapter = OKXPerpAdapter(key="test", secret="test", passphrase="test", is_sim=True)
        ctx = MarketContext(equity=5000.0, entry_px=100.0, atr=1.0, side=1)
        plan = plan_order(ctx, self.risk, inst_id="SOL-USDT-SWAP")
        receipt = adapter.execute(plan)
        self.assertEqual(receipt["status"], "SIMULATED")
        payload = receipt["payload"]
        self.assertEqual(payload["instId"], "SOL-USDT-SWAP")
        self.assertEqual(payload["side"], "buy")
        self.assertEqual(payload["tdMode"], "isolated")
        self.assertEqual(len(payload["attachAlgoOrds"]), 1)
        self.assertEqual(payload["attachAlgoOrds"][0]["slTriggerPx"], "97.00")


if __name__ == '__main__':
    unittest.main()
