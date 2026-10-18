import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from types import SimpleNamespace

from utils.observability import get_model_pricing, new_usage_tracker, observability_context, record_llm_usage


BEIJING = timezone(timedelta(hours=8))


class FlashPricingTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_time_boundaries_and_timezones(self):
        for hour, minute, tier in [(8, 59, 'off_peak'), (9, 0, 'peak'),
                                   (11, 59, 'peak'), (12, 0, 'off_peak'),
                                   (13, 59, 'off_peak'), (14, 0, 'peak'),
                                   (17, 59, 'peak'), (18, 0, 'off_peak')]:
            at = datetime(2026, 9, 7, hour, minute, tzinfo=BEIJING)
            with self.subTest(at=at):
                local = get_model_pricing('deepseek-flash', at)
                utc = get_model_pricing('deepseek-flash', at.astimezone(timezone.utc))
                self.assertEqual(local['tier'], tier)
                self.assertEqual(local, utc)

    def test_weekends_holidays_and_makeup_weekend(self):
        for month, day in [(9, 6), (10, 1), (2, 23), (9, 25), (10, 10)]:
            with self.subTest(month=month, day=day):
                p = get_model_pricing('deepseek-flash', datetime(2026, month, day, 10, tzinfo=BEIJING))
                self.assertEqual(p['tier'], 'off_peak')
                self.assertEqual((p['cache_hit'], p['cache_miss'], p['output']), (.003, .15, .60))

    def test_aliases(self):
        at = datetime(2026, 9, 7, 10, tzinfo=BEIJING)
        expected = get_model_pricing('deepseek-flash', at)
        for alias in ['deepseek-v4-flash', 'deepseek-chat', 'deepseek-reasoner', 'deepseek-v4-flash-vision-exp']:
            self.assertEqual(get_model_pricing(alias, at), expected)
        self.assertEqual((expected['cache_hit'], expected['cache_miss'], expected['output']), (.006, .30, 1.20))

    def test_unknown_calendar_and_model_are_explicitly_unavailable(self):
        at = datetime(2035, 1, 8, 10, tzinfo=BEIJING)
        for model in ['deepseek-flash', 'unknown-model']:
            result = get_model_pricing(model, at)
            self.assertFalse(result['available'])
            self.assertEqual(result['tier'], 'unavailable')
            self.assertTrue(result['reason'])

    def test_overrides_and_invalid_prices(self):
        values = {'LLM_CACHE_HIT_COST_PER_1M_TOKENS': '1',
                  'LLM_CACHE_MISS_COST_PER_1M_TOKENS': '2',
                  'LLM_OUTPUT_COST_PER_1M_TOKENS': '3'}
        with patch.dict(os.environ, values):
            prices = get_model_pricing('deepseek-flash', datetime(2026, 9, 7, 10, tzinfo=BEIJING))
            self.assertEqual(prices['tier'], 'peak_configured')
            self.assertEqual(prices['output'], 3)
            prices = get_model_pricing('deepseek-flash', datetime(2026, 9, 7, 12, tzinfo=BEIJING))
            self.assertEqual(prices['tier'], 'off_peak_configured')
            self.assertEqual((prices['cache_hit'], prices['cache_miss'], prices['output']), (.5, 1, 1.5))
            self.assertFalse(get_model_pricing('unknown-model')['available'])
            self.assertFalse(get_model_pricing('deepseek-flash', datetime(2035, 1, 8, 10, tzinfo=BEIJING))['available'])
            for value in ['nan', '-1', 'bad', 'inf']:
                os.environ['LLM_OUTPUT_COST_PER_1M_TOKENS'] = value
                self.assertFalse(get_model_pricing('deepseek-flash')['available'])

    def test_partial_overrides_and_holidays_still_use_off_peak_multiplier(self):
        with patch.dict(os.environ, {'LLM_OUTPUT_COST_PER_1M_TOKENS': '2'}):
            for at in [datetime(2026, 9, 7, 12, tzinfo=BEIJING),
                       datetime(2026, 10, 1, 10, tzinfo=BEIJING),
                       datetime(2026, 10, 10, 10, tzinfo=BEIJING)]:
                with self.subTest(at=at):
                    prices = get_model_pricing('deepseek-flash', at)
                    self.assertEqual(prices['output'], 1)
                    self.assertEqual(prices['cache_miss'], .15)

    def test_pro_rates_are_preserved(self):
        peak = get_model_pricing('deepseek-v4-pro', datetime(2026, 9, 7, 10, tzinfo=BEIJING))
        off = get_model_pricing('deepseek-v4-pro', datetime(2026, 9, 7, 12, tzinfo=BEIJING))
        self.assertEqual((peak['cache_hit'], peak['cache_miss'], peak['output']), (.044, 1.32, 3.96))
        self.assertEqual((off['cache_hit'], off['cache_miss'], off['output']), (.022, .66, 1.98))

    def test_incomplete_or_invalid_usage_is_not_a_zero_cost_estimate(self):
        payloads = [None, {}, {'total_tokens': 10}, {'prompt_tokens': 10},
                    {'prompt_tokens': 10, 'completion_tokens': None},
                    {'prompt_tokens': 10, 'completion_tokens': 2},
                    {'prompt_tokens': 10, 'completion_tokens': 2, 'prompt_cache_hit_tokens': -1},
                    {'prompt_tokens': 10, 'completion_tokens': 2, 'prompt_cache_hit_tokens': 11},
                    {'prompt_tokens': 10, 'completion_tokens': 2, 'prompt_cache_hit_tokens': 2, 'prompt_cache_miss_tokens': 9},
                    {'prompt_tokens': 10, 'completion_tokens': 2.5, 'prompt_cache_hit_tokens': 2},
                    {'prompt_tokens': True, 'completion_tokens': 2, 'prompt_cache_hit_tokens': 0},
                    {'prompt_tokens': 10, 'completion_tokens': 2, 'prompt_cache_hit_tokens': 2, 'total_tokens': 99}]
        for payload in payloads:
            with self.subTest(payload=payload):
                tracker = new_usage_tracker()
                with observability_context(usage_tracker=tracker):
                    result = record_llm_usage('deepseek-flash', 'qa', payload, 1,
                                              at=datetime(2026, 9, 7, 10, tzinfo=BEIJING))
                self.assertFalse(result['cost_estimate_available'])
                self.assertEqual(tracker.summary()['cost_status'], 'unavailable')
                self.assertIsNone(tracker.summary()['estimated_total_cost_usd'])
                self.assertTrue(tracker.summary()['pricing_warnings'])

    def test_cache_miss_can_supply_hit_count_and_zero_usage_is_valid(self):
        at = datetime(2026, 9, 7, 10, tzinfo=BEIJING)
        result = record_llm_usage('deepseek-flash', 'qa',
                                  {'prompt_tokens': 1000, 'completion_tokens': 100,
                                   'prompt_cache_miss_tokens': 600}, 1, at=at)
        self.assertTrue(result['cost_estimate_available'])
        self.assertEqual(result['cache_hit_tokens'], 400)
        self.assertAlmostEqual(result['estimated_cost_usd'], .0003024)
        zero = record_llm_usage('deepseek-flash', 'qa', {'prompt_tokens': 0, 'completion_tokens': 0}, 1, at=at)
        self.assertTrue(zero['cost_estimate_available'])
        unknown = record_llm_usage('unknown-model', 'qa', {'prompt_tokens': 0, 'completion_tokens': 0}, 1, at=at)
        self.assertFalse(unknown['cost_estimate_available'])

    def test_default_model_is_canonical_and_explicit_setting_is_respected(self):
        from utils.llm_client import get_deepseek_model
        os.environ.pop('DEEPSEEK_MODEL', None)
        self.assertEqual(get_deepseek_model(), 'deepseek-flash')
        with patch.dict(os.environ, {'DEEPSEEK_MODEL': 'deepseek-v4-pro'}):
            self.assertEqual(get_deepseek_model(), 'deepseek-v4-pro')

    def test_cost_cache_fallback_duration_and_unavailable_bucket(self):
        at = datetime(2026, 9, 7, 10, tzinfo=BEIJING)
        tracker = new_usage_tracker()
        with observability_context(usage_tracker=tracker):
            priced = record_llm_usage('deepseek-flash', 'qa',
                                     {'prompt_tokens': 1000, 'prompt_cache_hit_tokens': 400,
                                      'completion_tokens': 100}, 25, at=at)
            record_llm_usage('unknown', 'judge', None, 10, at=at)
        self.assertAlmostEqual(priced['estimated_cost_usd'], .0003024)
        result = tracker.summary()
        self.assertEqual(result['duration_ms'], 35)
        self.assertEqual(result['llm_calls'], 2)
        self.assertEqual(result['cost_status'], 'unavailable')
        self.assertIsNone(result['estimated_total_cost_usd'])
        self.assertFalse(result['by_model']['unknown']['cost_estimate_available'])
        self.assertEqual(result['by_operation']['qa']['cache_miss_tokens'], 600)

    def test_llm_call_crossing_boundary_uses_start_time(self):
        from utils.llm_client import chat_with_deepseek
        started = datetime(2026, 9, 7, 11, 59, 59, tzinfo=BEIJING)
        finished = datetime(2026, 9, 7, 12, 0, 1, tzinfo=BEIJING)
        reply = SimpleNamespace(model='deepseek-flash', choices=[SimpleNamespace(message=SimpleNamespace(content='ok'))],
                                usage={'prompt_tokens':1000, 'completion_tokens':100, 'prompt_cache_hit_tokens':400})
        tracker = new_usage_tracker()
        with patch('utils.llm_client.datetime') as clock, patch('utils.llm_client.get_deepseek_client') as client:
            clock.now.return_value = started
            def complete(**kwargs):
                clock.now.return_value = finished
                return reply
            client.return_value.chat.completions.create.side_effect = complete
            with observability_context(usage_tracker=tracker):
                chat_with_deepseek('test')
        self.assertEqual(tracker.summary()['pricing_tiers'], ['peak'])
        self.assertAlmostEqual(tracker.summary()['estimated_cost_usd'], .0003024)

    def test_missing_calendar_is_not_silently_weekday_priced(self):
        at = datetime(2026, 9, 7, 10, tzinfo=BEIJING)
        with patch('utils.pricing._holiday_calendar', side_effect=OSError('calendar unreadable')):
            prices = get_model_pricing('deepseek-flash', at)
        self.assertEqual(prices['tier'], 'unavailable')
        self.assertIn('unreadable', prices['reason'])
        self.assertFalse(get_model_pricing('deepseek-flash', datetime(2026, 9, 7, 10))['available'])


if __name__ == '__main__':
    unittest.main()
