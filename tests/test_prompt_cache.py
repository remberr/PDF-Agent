import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langchain_core.documents import Document
from openai.types.chat import ChatCompletion

from app.schemas.responses import LLMUsageResponse
from evaluation.usage import merge_usage
from utils.deepseek_client import ask_deepseek
from utils.llm_client import LLMClientError, chat_with_deepseek
from utils.observability import empty_usage_summary, new_usage_tracker, observability_context, record_llm_usage


def counters(hit=0, miss=100, **extra):
    return dict(prompt_tokens=100, completion_tokens=5, total_tokens=105,
                prompt_cache_hit_tokens=hit, prompt_cache_miss_tokens=miss, **extra)


def tracked(payload, model='deepseek-flash', operation='qa'):
    tracker = new_usage_tracker()
    with observability_context(usage_tracker=tracker):
        call = record_llm_usage(model, operation, payload, 1)
    return call, tracker.summary()


class CacheUsageTests(unittest.TestCase):
    def test_zero_missing_and_no_calls_have_distinct_states(self):
        _, zero = tracked(counters())
        self.assertEqual(zero['cache_status'], 'available')
        self.assertTrue(zero['cache_usage_available'])
        self.assertEqual(zero['cache_hit_rate'], 0)
        for payload in (None, {'prompt_tokens': 100, 'completion_tokens': 5}):
            _, missing = tracked(payload)
            self.assertEqual(missing['cache_status'], 'unavailable')
            self.assertFalse(missing['cache_usage_available'])
            self.assertEqual(missing['cache_miss_tokens'], 0)
        empty = empty_usage_summary()
        self.assertEqual(empty['cache_status'], 'no_calls')
        self.assertFalse(empty['cache_usage_available'])

    def test_sdk_keeps_deepseek_extra_counters_and_accumulates_weighted_rate(self):
        tracker = new_usage_tracker()
        client = Mock()
        client.chat.completions.create.side_effect = [ChatCompletion.model_validate({
            'id': 'test', 'created': 0, 'object': 'chat.completion', 'model': 'deepseek-flash',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'ok'}}],
            'usage': payload,
        }) for payload in (counters(60, 40), dict(prompt_tokens=300, completion_tokens=5, total_tokens=305,
                                                prompt_cache_hit_tokens=40, prompt_cache_miss_tokens=260))]
        with patch('utils.llm_client.get_deepseek_client', return_value=client), observability_context(usage_tracker=tracker):
            chat_with_deepseek('one', operation='qa')
            chat_with_deepseek('two', operation='summary')
        summary = tracker.summary()
        self.assertEqual(summary['cache_hit_tokens'], 100)
        self.assertEqual(summary['cache_miss_tokens'], 300)
        self.assertEqual(summary['cache_hit_rate'], .25)
        self.assertEqual(summary['by_operation']['qa']['cache_hit_rate'], .6)
        self.assertEqual(summary['by_model']['deepseek-flash']['cache_status'], 'available')

    def test_nested_sdk_counters_and_single_counter_fallbacks(self):
        for payload in (
            {'prompt_tokens': 100, 'completion_tokens': 5, 'prompt_tokens_details': {'cached_tokens': 30}},
            SimpleNamespace(prompt_tokens=100, completion_tokens=5,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=30)),
            {'prompt_tokens': 100, 'completion_tokens': 5, 'prompt_cache_hit_tokens': 30},
            {'prompt_tokens': 100, 'completion_tokens': 5, 'prompt_cache_miss_tokens': 70},
        ):
            with self.subTest(payload=payload):
                call, summary = tracked(payload)
                self.assertTrue(call['cache_usage_available'])
                self.assertTrue(call['cost_estimate_available'])
                self.assertEqual((summary['cache_hit_tokens'], summary['cache_miss_tokens']), (30, 70))

    def test_invalid_or_conflicting_cache_counters_are_unavailable(self):
        for payload in (counters(-1, 101), counters(30, 80), counters(101, 0), counters(True, 99),
                        counters(30, 70, prompt_tokens_details={'cached_tokens': 40}),
                        dict(prompt_tokens=100, completion_tokens=5, prompt_tokens_details={'cached_tokens': '30'})):
            with self.subTest(payload=payload):
                call, summary = tracked(payload)
                self.assertFalse(call['cache_usage_available'])
                self.assertFalse(call['cost_estimate_available'])
                self.assertEqual(summary['cache_status'], 'unavailable')

    def test_missing_call_poisoning_does_not_look_like_zero_or_complete_rate(self):
        _, known = tracked(counters(60, 40))
        _, unknown = tracked({'prompt_tokens': 100, 'completion_tokens': 5})
        result = merge_usage([empty_usage_summary(), known, unknown])
        self.assertEqual(result['cache_hit_tokens'], 60)
        self.assertEqual(result['cache_unavailable_calls'], 1)
        self.assertEqual(result['cache_status'], 'unavailable')
        self.assertEqual(result['by_operation']['qa']['cache_status'], 'unavailable')
        self.assertEqual(merge_usage([empty_usage_summary(), known])['cache_hit_rate'], .6)
        self.assertEqual(merge_usage([])['cache_status'], 'no_calls')

    def test_cache_availability_is_independent_of_model_pricing(self):
        _, result = tracked(counters(60, 40), model='unknown')
        self.assertFalse(result['cost_estimate_available'])
        self.assertTrue(result['cache_usage_available'])
        self.assertEqual(result['cache_hit_rate'], .6)

    def test_response_schema_retains_cache_state_and_breakdowns(self):
        _, summary = tracked(counters(30, 70))
        encoded = LLMUsageResponse.model_validate(summary).model_dump()
        self.assertEqual(encoded['cache_status'], 'available')
        self.assertEqual(encoded['by_operation']['qa']['cache_hit_rate'], .3)
        self.assertEqual(encoded['by_model']['deepseek-flash']['cache_unavailable_calls'], 0)

    def test_failed_calls_retain_cache_usage_or_unknown_state(self):
        client = Mock()
        failure = RuntimeError('transport failed')
        failure.usage = counters(30, 70)
        tracker = new_usage_tracker()
        client.chat.completions.create.side_effect = [failure, TimeoutError('no usage')]
        with patch('utils.llm_client.get_deepseek_client', return_value=client), observability_context(usage_tracker=tracker):
            for _ in range(2):
                with self.assertRaises(LLMClientError):
                    chat_with_deepseek('repeat')
        result = tracker.summary()
        self.assertEqual(result['llm_calls'], 2)
        self.assertEqual(result['cache_hit_tokens'], 30)
        self.assertEqual(result['cache_unavailable_calls'], 1)
        self.assertEqual(result['cache_status'], 'unavailable')


class PDFPromptTests(unittest.TestCase):
    @patch('utils.deepseek_client.chat_with_deepseek', return_value='Grounded [paper.pdf, page 3].')
    @patch('utils.deepseek_client.build_memory')
    def test_reusable_context_precedes_memory_without_changing_evidence(self, memory, chat):
        docs = [Document(page_content='Second retrieved chunk', metadata={'source': 'paper.pdf', 'page': 2}),
                Document(page_content='First retrieved chunk', metadata={'source': 'paper.pdf', 'page': 0})]
        memory.side_effect = ['older conversation', 'newer conversation']
        for question in ('First question?', 'Follow-up question?'):
            self.assertEqual(ask_deepseek(question, docs, operation='qa'), 'Grounded [paper.pdf, page 3].')
        first, second = chat.call_args_list
        self.assertEqual(first.kwargs['system_prompt'], second.kwargs['system_prompt'])
        self.assertIn('Answer only using the provided PDF context.', first.kwargs['system_prompt'])
        prompt = first.args[0]
        self.assertLess(prompt.index('Second retrieved chunk'), prompt.index('First retrieved chunk'))
        self.assertLess(prompt.index('First retrieved chunk'), prompt.index('older conversation'))
        self.assertLess(prompt.index('older conversation'), prompt.index('First question?'))
        self.assertIn('[paper.pdf, page 3]', prompt)
        self.assertEqual(prompt.split('older conversation')[0], second.args[0].split('newer conversation')[0])

    @patch('utils.llm_client.get_deepseek_client')
    def test_optional_system_message_preserves_existing_single_prompt_callers(self, get_client):
        get_client.return_value.chat.completions.create.return_value = SimpleNamespace(
            model='deepseek-flash', usage=counters(), choices=[SimpleNamespace(message=SimpleNamespace(content='ok'))])
        chat_with_deepseek('legacy')
        self.assertEqual(get_client.return_value.chat.completions.create.call_args.kwargs['messages'],
                         [{'role': 'user', 'content': 'legacy'}])
        chat_with_deepseek('context and question', system_prompt='stable instructions')
        self.assertEqual(get_client.return_value.chat.completions.create.call_args.kwargs['messages'],
                         [{'role': 'system', 'content': 'stable instructions'},
                          {'role': 'user', 'content': 'context and question'}])


if __name__ == '__main__':
    unittest.main()
