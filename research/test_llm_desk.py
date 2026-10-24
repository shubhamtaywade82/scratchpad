"""Validation-gate tests for research/llm_desk.py (no model calls). Run: python3 -m unittest research.test_llm_desk -v"""
import json
import unittest
from unittest import mock

from research import llm_desk as desk


class Gates(unittest.TestCase):
    def test_intent_outside_enum_is_rejected(self):
        self.assertEqual(desk.parse_intent('{"intent": "MARKET"}'), 'MARKET')
        with self.assertRaises(desk.ValidationError):
            desk.parse_intent('{"intent": "PLACE_ORDER"}')

    def test_tool_call_must_be_allowlisted_with_exact_valid_arguments(self):
        tool, args = desk.parse_tool_call('{"tool": "futures_klines", "arguments": '
                                          '{"symbol": "solusdt", "interval": "4h", "limit": 100}}')
        self.assertEqual((tool, args['symbol']), ('futures_klines', 'SOLUSDT'))
        bad = [
            {'tool': 'futures_new_order', 'arguments': {'symbol': 'SOLUSDT'}},
            {'tool': 'funding_rate', 'arguments': {'symbol': 'DOGEUSDT'}},
            {'tool': 'funding_rate', 'arguments': {'symbol': 'SOLUSDT', 'side': 'BUY'}},
            {'tool': 'futures_klines', 'arguments': {'symbol': 'SOLUSDT', 'interval': '3m', 'limit': 10}},
            {'tool': 'futures_klines', 'arguments': {'symbol': 'SOLUSDT', 'interval': '1h', 'limit': 5000}},
        ]
        for call in bad:
            with self.assertRaises(desk.ValidationError, msg=call):
                desk.parse_tool_call(json.dumps(call))

    def test_answer_must_cite_supplied_evidence_only(self):
        ids = ['exits', 'nulltest']
        self.assertTrue(desk.check_citations('Trail helps [exits].', ids))
        self.assertTrue(desk.check_citations('Insufficient evidence to answer.', ids))
        for answer in ('Trail helps.', 'Trail helps [exits] and [made-up].'):
            with self.assertRaises(desk.ValidationError):
                desk.check_citations(answer, ids)

    def test_summary_needs_all_sections_and_no_invented_numbers(self):
        full = '## Summary\nequity 0.9941\n## Key events\n-\n## Anomalies\nNone observed.\n## Recommended action\nwait'
        self.assertTrue(desk.check_summary(full, 'equity 0.9941'))
        with self.assertRaises(desk.ValidationError):
            desk.check_summary('## Summary\nok', '')
        with self.assertRaises(desk.ValidationError):
            desk.check_summary(full.replace('0.9941', '0.9999'), 'equity 0.9941')


class Escalation(unittest.TestCase):
    def test_retries_locally_then_escalates_then_fails(self):
        replies = iter(['{"intent": "BUY"}', '{"intent": "SELL"}', '{"intent": "MARKET"}'])
        with mock.patch.object(desk, 'chat', side_effect=lambda *a, **k: next(replies)) as chat:
            value, model = desk.gated('local', 'q', desk.parse_intent, as_json=True)
        self.assertEqual((value, model), ('MARKET', desk.ESCALATE_MODEL))
        self.assertIn('rejected', chat.call_args_list[1].args[1])
        with mock.patch.object(desk, 'chat', return_value='{"intent": "BUY"}'):
            with self.assertRaises(desk.DeskError):
                desk.gated('local', 'q', desk.parse_intent, as_json=True)

    def test_order_requests_never_dispatch(self):
        with mock.patch.object(desk, 'chat', return_value='{"intent": "OTHER"}'):
            self.assertTrue(desk.route('buy 10 SOL at market').startswith('OTHER'))


if __name__ == '__main__':
    unittest.main()
