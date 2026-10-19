import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.schemas.responses import LLMUsageResponse
from evaluation.usage import merge_usage
from utils.observability import empty_usage_summary, new_usage_tracker, observability_context, record_llm_usage
from utils.pricing import get_model_pricing


PEAK = datetime(2026, 9, 7, 1, tzinfo=timezone.utc)
OFF_PEAK = datetime(2026, 9, 7, 4, tzinfo=timezone.utc)
HOLIDAY = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
USAGE = dict(prompt_tokens=1000, completion_tokens=100, prompt_cache_hit_tokens=100,
             prompt_cache_miss_tokens=900)


class LocalizedPricingTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_official_independent_cny_and_usd_price_tables(self):
        for model, usd, cny in (
            ('deepseek-flash', (.006, .30, 1.20), (.04, 2, 8)),
            ('deepseek-v4-pro', (.044, 1.32, 3.96), (.30, 9, 27)),
        ):
            for currency, expected in (('USD', usd), ('CNY', cny)):
                with self.subTest(model=model, currency=currency):
                    prices = get_model_pricing(model, PEAK, currency=currency)
                    self.assertEqual(tuple(prices[k] for k in ('cache_hit', 'cache_miss', 'output')), expected)
                    for at in (OFF_PEAK, HOLIDAY):
                        prices = get_model_pricing(model, at, currency=currency)
                        self.assertEqual(tuple(prices[k] for k in ('cache_hit', 'cache_miss', 'output')),
                                         tuple(value / 2 for value in expected))
        self.assertEqual(get_model_pricing('deepseek-v4-flash', PEAK, currency='CNY'),
                         get_model_pricing('deepseek-flash', PEAK, currency='CNY'))

    def test_usd_overrides_never_convert_or_override_cny(self):
        os.environ['LLM_OUTPUT_COST_PER_1M_TOKENS'] = '99'
        self.assertEqual(get_model_pricing('deepseek-flash', PEAK)['output'], 99)
        self.assertEqual(get_model_pricing('deepseek-flash', PEAK, currency='CNY')['output'], 8)
        self.assertEqual(get_model_pricing('deepseek-flash', OFF_PEAK, currency='CNY')['output'], 4)
        os.environ['LLM_OUTPUT_COST_PER_1M_TOKENS'] = 'invalid'
        self.assertFalse(get_model_pricing('deepseek-flash', PEAK)['available'])
        self.assertTrue(get_model_pricing('deepseek-flash', PEAK, currency='CNY')['available'])

    def test_usage_api_and_evaluation_preserve_both_currencies_per_call(self):
        tracker = new_usage_tracker()
        with observability_context(usage_tracker=tracker):
            call = record_llm_usage('deepseek-flash', 'qa', USAGE, 1, at=PEAK)
            record_llm_usage('deepseek-flash', 'qa', USAGE, 1, at=OFF_PEAK)
        self.assertAlmostEqual(call['estimated_cost_usd'], .0003906)
        self.assertAlmostEqual(call['estimated_cost_cny'], .002604)
        summary = tracker.summary()
        self.assertAlmostEqual(summary['estimated_cost_cny'], .003906)
        encoded = LLMUsageResponse.model_validate(summary).model_dump()
        self.assertTrue(encoded['cost_estimate_cny_available'])
        self.assertAlmostEqual(encoded['by_operation']['qa']['estimated_cost_cny'], .003906)
        merged = merge_usage([summary, empty_usage_summary(), summary])
        self.assertAlmostEqual(merged['estimated_cost_cny'], .007812)
        self.assertAlmostEqual(merged['by_model']['deepseek-flash']['estimated_cost_cny'], .007812)

    def test_unknown_cost_and_legacy_reports_do_not_become_free_cny(self):
        tracker = new_usage_tracker()
        with observability_context(usage_tracker=tracker):
            record_llm_usage('unknown', 'qa', USAGE, 1, at=PEAK)
        result = tracker.summary()
        self.assertFalse(result['cost_estimate_cny_available'])
        self.assertIsNone(result['estimated_cost_cny'])
        legacy = dict(llm_calls=1, input_tokens=1000, output_tokens=100, estimated_cost_usd=.001)
        self.assertIsNone(merge_usage([legacy])['estimated_cost_cny'])
        self.assertEqual(merge_usage([])['estimated_cost_cny'], 0)

    def test_currency_availability_is_independent_and_invalid_usage_is_unavailable(self):
        with patch.dict(os.environ, {'LLM_OUTPUT_COST_PER_1M_TOKENS': 'invalid'}):
            call = record_llm_usage('deepseek-flash', 'qa', USAGE, 1, at=PEAK)
        self.assertFalse(call['cost_estimate_available'])
        self.assertTrue(call['cost_estimate_cny_available'])
        for payload in (None, {'prompt_tokens': 1000, 'completion_tokens': 100}):
            call = record_llm_usage('deepseek-flash', 'qa', payload, 1, at=PEAK)
            self.assertFalse(call['cost_estimate_cny_available'])
            self.assertIsNone(call['estimated_cost_cny'])


if __name__ == '__main__':
    unittest.main()
