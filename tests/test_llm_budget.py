"""Budget/payment regressions. Fake completions only; no provider network."""
import contextlib
import io
import json
import os
import tempfile
import unittest
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
from threading import Barrier
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from evaluation.runner import build_parser, run
from utils import llm_client
from utils.llm_budget import BudgetSettings, LLMBudgetExceeded, RequestBudget, llm_access, load_budget_settings
from utils.observability import new_usage_tracker, observability_context


def response(text='answer', input_tokens=10, output_tokens=2):
    return SimpleNamespace(model='deepseek-flash',
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=dict(prompt_tokens=input_tokens, completion_tokens=output_tokens,
                   total_tokens=input_tokens + output_tokens,
                   prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=input_tokens))


def settings(**overrides):
    return replace(BudgetSettings(max_estimated_cost_usd=None, retry_base_delay_seconds=0.001), **overrides)


class BudgetGatewayTests(unittest.TestCase):
    def call(self, client, tracker, prompt='safe question'):
        with patch('utils.llm_client.get_deepseek_client', return_value=client), \
                observability_context(usage_tracker=tracker):
            return llm_client.chat_with_deepseek(prompt, operation='qa')

    def test_known_usage_releases_reservation_without_counting_it_as_consumption(self):
        tracker = new_usage_tracker(RequestBudget(settings()))
        client = Mock()
        client.chat.completions.create.return_value = response()
        self.assertEqual(self.call(client, tracker), 'answer')
        self.assertEqual(tracker.summary()['llm_calls'], 1)
        self.assertEqual(tracker.summary()['total_tokens'], 12)
        budget = tracker.budget.summary()
        self.assertEqual(budget['input_tokens_committed_or_reserved'], 10)
        self.assertEqual(budget['output_tokens_committed_or_reserved'], 2)
        self.assertEqual(budget['in_flight'], 0)
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs['max_tokens'], 4096)
        self.assertGreater(kwargs['timeout'], 0)
        self.assertLessEqual(kwargs['timeout'], 60)

    def test_parallel_specialists_cannot_exceed_atomic_call_limit(self):
        tracker = new_usage_tracker(RequestBudget(settings(max_calls=3)))
        client = Mock()
        client.chat.completions.create.return_value = response()
        barrier = Barrier(12)
        def work():
            barrier.wait(timeout=3)
            try:
                return llm_client.chat_with_deepseek('safe', operation='qa')
            except LLMBudgetExceeded:
                return 'blocked'
        with patch('utils.llm_client.get_deepseek_client', return_value=client), \
                observability_context(usage_tracker=tracker), ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(copy_context().run, work) for _ in range(12)]
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(results.count('answer'), 3)
        self.assertEqual(results.count('blocked'), 9)
        self.assertEqual(client.chat.completions.create.call_count, 3)
        self.assertEqual(tracker.summary()['total_tokens'], 36)
        self.assertEqual(tracker.summary()['by_operation']['qa']['llm_calls'], 3)

    def test_input_and_cost_exhaustion_never_dispatch_or_record_a_free_call(self):
        for limits in (settings(max_input_tokens=1), settings(max_estimated_cost_usd=1e-10)):
            with self.subTest(limits=limits):
                tracker = new_usage_tracker(RequestBudget(limits))
                client = Mock()
                with self.assertRaises(LLMBudgetExceeded):
                    self.call(client, tracker)
                client.chat.completions.create.assert_not_called()
                self.assertEqual(tracker.summary()['llm_calls'], 0)

    def test_output_limit_is_reserved_across_calls_and_sent_to_provider(self):
        tracker = new_usage_tracker(RequestBudget(settings(max_output_per_call=5, max_output_tokens=8)))
        client = Mock()
        client.chat.completions.create.side_effect = lambda **kwargs: response(output_tokens=kwargs['max_tokens'])
        self.call(client, tracker)
        self.call(client, tracker)
        with self.assertRaises(LLMBudgetExceeded):
            self.call(client, tracker)
        self.assertEqual([call.kwargs['max_tokens'] for call in client.chat.completions.create.call_args_list], [5, 3])
        self.assertEqual(tracker.summary()['output_tokens'], 8)

    def test_unknown_usage_keeps_reservation_and_prevents_an_unfunded_retry(self):
        tracker = new_usage_tracker(RequestBudget(settings(max_retries=1, max_output_per_call=8, max_output_tokens=8)))
        client = Mock()
        client.chat.completions.create.side_effect = TimeoutError('private timeout content')
        with self.assertRaises(LLMBudgetExceeded):
            self.call(client, tracker)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(tracker.summary()['llm_calls'], 1)
        self.assertFalse(tracker.summary()['cost_estimate_available'])
        self.assertEqual(tracker.budget.summary()['unresolved_usage_attempts'], 1)
        self.assertEqual(tracker.budget.summary()['output_tokens_committed_or_reserved'], 8)

    def test_token_counters_settle_even_when_cache_split_and_cost_are_unknown(self):
        tracker = new_usage_tracker(RequestBudget(settings()))
        client = Mock()
        result = response()
        result.usage = dict(prompt_tokens=10, completion_tokens=2)
        client.chat.completions.create.return_value = result
        self.call(client, tracker)
        self.assertEqual(tracker.budget.summary()['input_tokens_committed_or_reserved'], 10)
        self.assertFalse(tracker.summary()['cost_estimate_available'])

    def test_expired_and_cancelled_requests_do_not_dispatch(self):
        for cancelled in (False, True):
            now = [0]
            budget = RequestBudget(settings(request_timeout_seconds=2), clock=lambda: now[0])
            tracker = new_usage_tracker(budget)
            if cancelled:
                budget.cancel()
            else:
                now[0] = 2
            client = Mock()
            with self.assertRaises(LLMBudgetExceeded):
                self.call(client, tracker)
            client.chat.completions.create.assert_not_called()
            self.assertEqual(tracker.summary()['llm_calls'], 0)

    def test_cancellation_after_reservation_releases_unstarted_attempt_without_billing(self):
        tracker = new_usage_tracker(RequestBudget(settings()))
        reserve = tracker.budget.reserve
        def cancel_after_reserving(*args, **kwargs):
            reservation = reserve(*args, **kwargs)
            tracker.budget.cancel('cancelled')
            return reservation
        client = Mock()
        with patch.object(tracker.budget, 'reserve', side_effect=cancel_after_reserving):
            with self.assertRaises(LLMBudgetExceeded):
                self.call(client, tracker)
        client.chat.completions.create.assert_not_called()
        self.assertEqual(tracker.summary()['llm_calls'], 0)
        self.assertEqual(tracker.budget.summary()['in_flight'], 0)
        self.assertEqual(tracker.budget.summary()['input_tokens_committed_or_reserved'], 0)

    def test_transport_timeout_is_clipped_to_remaining_request_time(self):
        now = [0]
        budget = RequestBudget(settings(request_timeout_seconds=3), clock=lambda: now[0])
        tracker = new_usage_tracker(budget)
        now[0] = 1
        client = Mock()
        client.chat.completions.create.return_value = response()
        self.call(client, tracker)
        self.assertEqual(client.chat.completions.create.call_args.kwargs['timeout'], 2)

    def test_late_response_keeps_actual_usage_but_terminates_request(self):
        now = [0]
        budget = RequestBudget(settings(request_timeout_seconds=1), clock=lambda: now[0])
        tracker = new_usage_tracker(budget)
        def late(**kwargs):
            now[0] = 2
            return response()
        client = Mock()
        client.chat.completions.create.side_effect = late
        with self.assertRaises(LLMBudgetExceeded):
            self.call(client, tracker)
        self.assertEqual(tracker.summary()['total_tokens'], 12)
        self.assertTrue(tracker.summary()['cost_estimate_available'])

    def test_cancellation_during_retry_prevents_next_attempt_and_keeps_unknown_usage(self):
        tracker = new_usage_tracker(RequestBudget(settings(max_retries=2)))
        def cancelled(**kwargs):
            tracker.budget.cancel('client_disconnected')
            raise TimeoutError('private timeout content')
        client = Mock()
        client.chat.completions.create.side_effect = cancelled
        with self.assertRaises(LLMBudgetExceeded):
            self.call(client, tracker)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(tracker.summary()['llm_calls'], 1)
        self.assertFalse(tracker.summary()['cost_estimate_available'])

    def test_sdk_cancellation_records_unknown_cost_without_retry(self):
        tracker = new_usage_tracker(RequestBudget(settings(max_retries=2)))
        client = Mock()
        client.chat.completions.create.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            self.call(client, tracker)
        self.assertEqual(tracker.summary()['llm_calls'], 1)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertFalse(tracker.summary()['cost_estimate_available'])

    def test_malformed_response_is_not_retried_or_counted_twice(self):
        tracker = new_usage_tracker(RequestBudget(settings(max_retries=2)))
        client = Mock()
        malformed = response()
        malformed.choices = []
        client.chat.completions.create.return_value = malformed
        with self.assertRaises(llm_client.LLMClientError):
            self.call(client, tracker)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(tracker.summary()['total_tokens'], 12)

    def test_evaluation_policy_is_inherited_and_blocks_before_client_access(self):
        tracker = new_usage_tracker(RequestBudget(settings()))
        with llm_access(False), llm_access(True), observability_context(usage_tracker=tracker), \
                patch('utils.llm_client.get_deepseek_client') as factory:
            with self.assertRaises(llm_client.LLMClientError):
                llm_client.chat_with_deepseek('safe')
            factory.assert_not_called()
        self.assertEqual(tracker.summary()['llm_calls'], 0)

    def test_request_trackers_are_isolated(self):
        first = new_usage_tracker(RequestBudget(settings(max_calls=1)))
        second = new_usage_tracker(RequestBudget(settings(max_calls=1)))
        client = Mock()
        client.chat.completions.create.return_value = response()
        self.call(client, first)
        with self.assertRaises(LLMBudgetExceeded):
            self.call(client, first)
        self.assertEqual(self.call(client, second), 'answer')
        self.assertEqual(second.summary()['llm_calls'], 1)

    def test_provider_overrun_is_recorded_and_stops_subsequent_calls(self):
        tracker = new_usage_tracker(RequestBudget(settings(max_output_tokens=4, max_output_per_call=4)))
        client = Mock()
        client.chat.completions.create.return_value = response(output_tokens=5)
        with self.assertRaises(LLMBudgetExceeded):
            self.call(client, tracker)
        with self.assertRaises(LLMBudgetExceeded):
            self.call(client, tracker)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(tracker.summary()['output_tokens'], 5)  # Never clip actual billing counters.

    def test_long_retry_after_does_not_sleep_or_dispatch_again(self):
        tracker = new_usage_tracker(RequestBudget(settings(max_retries=1)))
        failure = RuntimeError('private provider error')
        failure.status_code = 429
        failure.response = SimpleNamespace(headers={'retry-after': '120'})
        client = Mock()
        client.chat.completions.create.side_effect = failure
        with self.assertRaises(llm_client.LLMClientError):
            self.call(client, tracker)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(tracker.summary()['llm_calls'], 1)

    def test_logs_distinguish_reservations_retry_and_actual_usage_without_private_text(self):
        from tests.test_error_privacy import capture_json_logs
        private = 'test-only-private-prompt-provider-key-marker'
        tracker = new_usage_tracker(RequestBudget(settings(max_retries=1)))
        failure = TimeoutError(private)
        client = Mock()
        client.chat.completions.create.side_effect = [failure, response()]
        with capture_json_logs() as logs:
            self.call(client, tracker, private)
        text = logs.getvalue()
        self.assertNotIn(private, text)
        events = {json.loads(line)['event'] for line in text.splitlines()}
        self.assertTrue({'llm_budget_reserved', 'llm_budget_settled', 'llm_retry_scheduled',
                         'llm_call_failed', 'llm_call_completed'} <= events)
        self.assertEqual(tracker.summary()['llm_calls'], 2)
        self.assertFalse(tracker.summary()['cost_estimate_available'])


class RetryTransportTests(unittest.TestCase):
    def test_http_status_classification_and_no_sdk_retry_multiplication(self):
        import httpx
        from openai import OpenAI
        for status, expected in [(408, 2), (409, 2), (429, 2), (503, 2), (400, 1), (401, 1), (403, 1), (422, 1)]:
            with self.subTest(status=status):
                calls = []
                def transport(request):
                    calls.append(request)
                    if len(calls) == 1:
                        return httpx.Response(status, json={'error': {'message': 'private provider body'}},
                                              headers={'retry-after': '0'})
                    return httpx.Response(200, json=dict(id='fake', created=0, object='chat.completion',
                        model='deepseek-flash', choices=[{'index': 0, 'finish_reason': 'stop',
                            'message': {'role': 'assistant', 'content': 'answer'}}],
                        usage={'prompt_tokens': 10, 'completion_tokens': 2, 'prompt_cache_hit_tokens': 0}))
                tracker = new_usage_tracker(RequestBudget(settings(max_retries=1)))
                with OpenAI(api_key='fake', base_url='http://fake.invalid', max_retries=0,
                            http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
                    with patch('utils.llm_client.get_deepseek_client', return_value=client), \
                            observability_context(usage_tracker=tracker):
                        if expected == 2:
                            self.assertEqual(llm_client.chat_with_deepseek('safe'), 'answer')
                        else:
                            with self.assertRaises(llm_client.LLMClientError):
                                llm_client.chat_with_deepseek('safe')
                self.assertEqual(len(calls), expected)
                self.assertEqual(tracker.summary()['llm_calls'], expected)
                self.assertFalse(tracker.summary()['cost_estimate_available'])


class BudgetConfigurationTests(unittest.TestCase):
    def test_invalid_configuration_and_unknown_pricing_fail_closed(self):
        for name, value in [('LLM_MAX_RETRIES', '3'), ('LLM_MAX_CALLS_PER_REQUEST', '0'),
                            ('LLM_CALL_TIMEOUT_SECONDS', 'nan'), ('LLM_MAX_INPUT_TOKENS_PER_REQUEST', '-1'),
                            ('LLM_MAX_ESTIMATED_COST_USD_PER_REQUEST', 'secret-invalid')]:
            with self.subTest(name=name), self.assertRaises(ValueError) as caught:
                load_budget_settings({name: value})
            self.assertNotIn(value, str(caught.exception))
        budget = RequestBudget(BudgetSettings())
        with self.assertRaises(LLMBudgetExceeded):
            budget.reserve('unknown-model', 10)
        self.assertEqual(budget.summary()['attempts_admitted'], 0)
        self.assertIsNone(load_budget_settings({'LLM_MAX_ESTIMATED_COST_USD_PER_REQUEST': ''}).max_estimated_cost_usd)


class WorkflowBudgetTests(unittest.TestCase):
    def test_collaboration_revision_and_reviewer_use_the_same_request_budget(self):
        from app.services.agent_service import iter_pdf_agent_events
        from evaluation.runner import StaticVectorStore
        from langchain_core.documents import Document
        for limit in (4, 5):
            with self.subTest(limit=limit):
                collaboration_calls = []
                def completion(**kwargs):
                    if 'You are the Collaboration Agent' in kwargs['messages'][0]['content']:
                        collaboration_calls.append(True)
                        return response(json.dumps(dict(answer='combined evidence', issues=[],
                            missing_information=[], recommendations=[], needs_revision=len(collaboration_calls) == 1,
                            next_steps=['qa'] if len(collaboration_calls) == 1 else [])))
                    return response()
                session = dict(session_id='test', loaded_pdfs=['paper.pdf'], messages=[],
                    vectorstore=StaticVectorStore([Document(page_content='evidence',
                        metadata={'source': 'paper.pdf', 'page': 0})]), document_count=1)
                client = Mock()
                client.chat.completions.create.side_effect = completion
                with patch('utils.llm_client.get_deepseek_client', return_value=client), \
                        patch('app.services.agent_service.save_session'):
                    events = list(iter_pdf_agent_events(session, 'Compare the PDFs and cite sources.',
                        llm_budget=RequestBudget(settings(max_calls=limit))))
                result = events[-1]['data']
                self.assertEqual(result['revision_count'], 1)
                self.assertEqual(result['usage']['llm_calls'], limit)
                self.assertEqual(result['usage']['by_operation']['collaboration']['llm_calls'], 2)
                self.assertEqual(result['usage']['by_operation']['qa']['llm_calls'], 1)
                self.assertEqual(result['usage']['by_operation']['compare']['llm_calls'], 1)
                if limit == 5:
                    self.assertEqual(result['usage']['by_operation']['reviewer']['llm_calls'], 1)
                    self.assertEqual(result['answer'], 'answer')
                else:
                    self.assertNotIn('reviewer', result['usage']['by_operation'])
                    self.assertTrue(any(event['type'] == 'progress' and event['data']['status'] == 'failed'
                                        for event in events))

    def test_shared_budget_covers_planner_parallel_agents_and_existing_sse_failure_result(self):
        from app.services.agent_service import iter_pdf_agent_events
        from evaluation.runner import StaticVectorStore
        from langchain_core.documents import Document
        budget = RequestBudget(settings(max_calls=1))
        session = dict(session_id='test-session', loaded_pdfs=['paper.pdf'], messages=[],
                       vectorstore=StaticVectorStore([Document(page_content='evidence',
                           metadata={'source': 'paper.pdf', 'page': 0})]), document_count=1)
        client = Mock()
        client.chat.completions.create.return_value = response('["qa", "summary"]')
        with patch('utils.llm_client.get_deepseek_client', return_value=client), \
                patch('app.services.agent_service.save_session'):
            events = list(iter_pdf_agent_events(session, 'Analyze this document.', llm_budget=budget))
        self.assertEqual(events[-1]['type'], 'result')
        self.assertTrue(any(event['type'] == 'progress' and event['data']['status'] == 'failed' for event in events))
        self.assertEqual(events[-1]['data']['usage']['llm_calls'], 1)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(session['messages'][-1]['usage']['total_tokens'], 12)

    def test_memory_and_answer_share_budget_and_preserve_single_specialist_fast_path(self):
        from app.services.agent_service import iter_pdf_agent_events
        from evaluation.runner import StaticVectorStore
        from langchain_core.documents import Document
        history = [{'role': 'user', 'content': f'old message {number}'} for number in range(12)]
        session = dict(session_id='test-session', loaded_pdfs=['paper.pdf'], messages=history,
                       vectorstore=StaticVectorStore([Document(page_content='evidence',
                           metadata={'source': 'paper.pdf', 'page': 0})]), document_count=1)
        client = Mock()
        client.chat.completions.create.return_value = response()
        with patch('utils.llm_client.get_deepseek_client', return_value=client), \
                patch('utils.memory._memory_cache', {}), patch('app.services.agent_service.save_session'):
            result = list(iter_pdf_agent_events(session, 'What is the result?',
                llm_budget=RequestBudget(settings(max_calls=2))))[-1]['data']
        self.assertEqual(result['usage']['llm_calls'], 2)
        self.assertEqual(set(result['usage']['by_operation']), {'memory_summary', 'qa'})
        self.assertEqual(result['answer'], 'answer')

    def test_memory_lock_wait_respects_request_deadline(self):
        from utils import memory
        budget = RequestBudget(settings(request_timeout_seconds=0.03))
        tracker = new_usage_tracker(budget)
        history = [{'role': 'user', 'content': 'old'}] * 12
        with memory._memory_cache_lock:
            with observability_context(usage_tracker=tracker), patch('utils.memory.chat_with_deepseek') as chat:
                with self.assertRaises(LLMBudgetExceeded):
                    memory.build_llm_conversation_summary(history)
                chat.assert_not_called()
        self.assertEqual(budget.summary()['stop_reason'], 'deadline')

    def test_closing_sse_iterator_cancels_budget_without_changing_event_types(self):
        from app.services.agent_service import stream_pdf_agent
        budget = RequestBudget(settings())
        session = dict(session_id='test', messages=[], loaded_pdfs=[], vectorstore=object())
        events = stream_pdf_agent(session, 'What is the result?', llm_budget=budget)
        self.assertIn('event: progress', next(events))
        events.close()
        with self.assertRaises(LLMBudgetExceeded):
            budget.check()
        self.assertEqual(budget.summary()['attempts_admitted'], 0)


class DisconnectBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_disconnect_cancels_same_budget_used_by_sync_workflow(self):
        from utils.observability import RequestContextMiddleware
        observed = []
        async def app(scope, receive, send):
            budget = scope['state']['llm_budget']
            budget.check()
            await receive()
            with self.assertRaises(LLMBudgetExceeded):
                budget.check()
            observed.append(budget.summary()['stop_reason'])
        async def receive():
            return {'type': 'http.disconnect'}
        async def send(message):
            pass
        await RequestContextMiddleware(app)({'type': 'http', 'method': 'POST',
            'path': '/sessions/test/ask/stream', 'headers': []}, receive, send)
        self.assertEqual(observed, ['client_disconnected'])


class PaymentBoundaryTests(unittest.TestCase):
    def test_live_generation_and_judge_need_explicit_flag_even_with_key(self):
        for case, judge in [('compare-reports', False), ('source-citations', True)]:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                args = build_parser().parse_args(['--mode', 'live', '--case', case,
                    '--output', str(Path(directory) / 'report.json')] + (['--llm-judge'] if judge else []))
                client = Mock()
                client.chat.completions.create.return_value = response()
                with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'not-a-real-key'}), \
                        patch('utils.llm_client.get_deepseek_client', return_value=client), \
                        contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(ValueError, 'allow-paid-api'):
                        run(args)
                client.chat.completions.create.assert_not_called()

    def test_routing_ambiguous_question_never_calls_planner_llm(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / 'cases.json'
            dataset.write_text(json.dumps([{'id': 'ambiguous', 'question': 'Analyze this document.',
                                            'expected_steps': ['qa']}]), encoding='utf-8')
            report_path = Path(directory) / 'report.json'
            args = build_parser().parse_args(['--dataset', str(dataset), '--output', str(report_path)])
            client = Mock()
            client.chat.completions.create.return_value = response('["qa"]')
            with patch('utils.llm_client.get_deepseek_client', return_value=client), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = run(args)
            self.assertEqual(result, 1)
            self.assertEqual(json.loads(report_path.read_text())['summary']['llm_calls'], 0)
            client.chat.completions.create.assert_not_called()

    def test_real_client_factory_disables_sdk_retry(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'not-a-real-key', 'PDF_AGENT_DISABLE_LLM_API': '0'}), \
                patch.object(llm_client, '_deepseek_client', None), patch.object(llm_client, 'OpenAI') as factory:
            llm_client.get_deepseek_client()
        self.assertEqual(factory.call_args.kwargs.get('max_retries'), 0)

    def test_network_kill_switch_blocks_even_cached_client(self):
        for value in ('1', 'true', ' true ', 'invalid-setting'):
            with self.subTest(value=value), patch.dict(os.environ, {'PDF_AGENT_DISABLE_LLM_API': value}), \
                    patch.object(llm_client, '_deepseek_client', Mock()):
                with self.assertRaises(llm_client.LLMClientError):
                    llm_client.get_deepseek_client()
