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
            prices = get_model_pricing('unknown-model')
            self.assertEqual(prices['tier'], 'configured')
            self.assertEqual(prices['output'], 3)
            for value in ['nan', '-1', 'bad', 'inf']:
                os.environ['LLM_OUTPUT_COST_PER_1M_TOKENS'] = value
                self.assertFalse(get_model_pricing('deepseek-flash')['available'])

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
