import json
import unittest
from unittest.mock import Mock, patch

from langchain_core.documents import Document
from app.services.agent_service import ask_pdf_agent, iter_pdf_agent_events, stream_pdf_agent
from tests.test_error_privacy import make_app, make_session, decode_result
from fastapi.testclient import TestClient
from tests.session_access_fixtures import AUTH_HEADERS, HTTP_SESSION_ID, accept_test_owner
from utils.llm_client import LLMClientError
from utils.llm_budget import RequestBudget, BudgetSettings


class ExecutionContractTests(unittest.TestCase):
    def session(self):
        store = Mock()
        store.similarity_search.return_value = [Document(page_content='Evidence', metadata={'source': 'a.pdf', 'page': 0})]
        return make_session(store)

    def test_json_and_sse_success_contract_and_saved_history(self):
        for streaming in (False, True):
            session = self.session()
            with self.subTest(streaming=streaming), patch('app.api.routes.get_session', return_value=session), \
                    patch('app.services.agent_service.save_session'), accept_test_owner(), TestClient(make_app(), headers=AUTH_HEADERS) as http:
                response = http.post(f'/sessions/{HTTP_SESSION_ID}/ask' + ('/stream' if streaming else ''), json={'question': 'sources'})
            result = decode_result(response, streaming)
            self.assertEqual(result['execution']['status'], 'succeeded')
            self.assertEqual(result['execution']['persistence'], 'saved')
            self.assertEqual(result['execution']['generation_status'], 'succeeded')
            self.assertEqual(session['messages'][-1]['execution'], result['execution'])
            self.assertEqual(result['usage']['llm_calls'], 0)

    def test_specialist_failure_and_model_fallback_are_not_success(self):
        for failure in ('retrieval', 'model'):
            session = self.session()
            if failure == 'retrieval':
                session['vectorstore'].similarity_search.side_effect = ValueError('private')
            with patch('utils.deepseek_client.chat_with_deepseek', side_effect=LLMClientError('private')), \
                    patch('app.services.agent_service.save_session'):
                result = ask_pdf_agent(session, 'What is the result?')
            self.assertEqual(result['execution']['status'], 'failed')
            self.assertEqual(result['execution']['node_statuses']['qa']['status'], 'failed')

    def test_empty_specialist_answer_is_not_generation_success(self):
        with patch('agent.graph_agent.qa_agent', return_value={
                'agent': 'QA Agent', 'status': 'success', 'answer': '  ', 'results': []}), \
                patch('app.services.agent_service.save_session'):
            result = ask_pdf_agent(self.session(), 'What is the result?')
        self.assertEqual(result['execution']['status'], 'failed')
        self.assertEqual(result['execution']['node_statuses']['qa']['reason'], 'empty_answer')

    def test_partial_specialist_failure_is_degraded_and_not_completed(self):
        session = self.session()
        with patch('agent.graph_agent.qa_agent', side_effect=ValueError('private')), \
                patch('agent.collaboration_agent.chat_with_deepseek', side_effect=LLMClientError('private')), \
                patch('utils.final_synthesizer.chat_with_deepseek', side_effect=LLMClientError('private')), \
                patch('app.services.agent_service.save_session'):
            events = list(iter_pdf_agent_events(session, 'What is the result? Give sources.'))
        result = events[-1]['data']
        self.assertEqual(result['execution']['status'], 'degraded')
        self.assertEqual(result['execution']['node_statuses']['qa']['status'], 'failed')
        self.assertNotIn('specialists', next(e['data']['completed_nodes'] for e in events
            if e['type']=='progress' and e['data']['node']=='specialists' and e['data']['status']!='running'))

    def test_empty_and_truncated_graph_are_failed(self):
        for chunks in ([], [{'planner_agent': {'steps': ['qa']}}]):
            graph = Mock()
            graph.stream.return_value = iter(chunks)
            with patch('app.services.agent_service.get_pdf_agent_graph', return_value=graph), \
                    patch('app.services.agent_service.save_session'):
                result = ask_pdf_agent(self.session(), 'question')
            self.assertEqual(result['execution']['status'], 'failed')
            self.assertEqual(result['execution']['reason'], 'incomplete_workflow')

    def test_save_failure_keeps_generated_answer_without_mutating_history(self):
        session = self.session()
        with patch('app.services.agent_service.save_session', side_effect=OSError('private')) as save:
            result = ask_pdf_agent(session, 'sources')
        self.assertTrue(result['answer'])
        self.assertEqual(result['execution']['generation_status'], 'succeeded')
        self.assertEqual(result['execution']['status'], 'failed')
        self.assertEqual(result['execution']['persistence'], 'failed')
        self.assertEqual(result['execution']['reason'], 'persistence_failed')
        self.assertEqual(session['messages'], [])
        self.assertEqual(save.call_count, 1)

    def test_close_and_pre_cancel_preserve_no_new_dispatch_or_save(self):
        session = self.session()
        budget = RequestBudget(BudgetSettings())
        with patch('app.services.agent_service.save_session') as save:
            stream = stream_pdf_agent(session, 'sources', llm_budget=budget)
            self.assertIn('event: progress', next(stream))
            stream.close()
        self.assertEqual(session['messages'], [])
        save.assert_not_called()
        self.assertEqual(budget.summary()['cancel_reason'], 'workflow_closed')
        budget = RequestBudget(BudgetSettings())
        budget.cancel('client_disconnected')
        with patch('app.services.agent_service.save_session') as save:
            result = ask_pdf_agent(session, 'sources', llm_budget=budget)
        self.assertEqual(result['execution']['status'], 'cancelled')
        self.assertEqual(result['execution']['persistence'], 'not_attempted')
        save.assert_not_called()

    def test_budget_exhaustion_is_explicit_and_keeps_usage(self):
        budget = RequestBudget(BudgetSettings(max_calls=1))
        budget.reserve('deepseek-flash', 1)
        with patch('app.services.agent_service.save_session'):
            with patch('utils.llm_client.get_deepseek_client', return_value=Mock()):
                result = ask_pdf_agent(self.session(), 'Analyze.', llm_budget=budget)
        self.assertEqual(result['execution']['status'], 'failed')
        self.assertEqual(result['execution']['reason'], 'budget_exhausted')
        self.assertIn('usage', result)

    def test_save_failure_json_sse_has_one_terminal_result_and_no_retry(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming), patch('app.api.routes.get_session', return_value=self.session()), \
                    patch('app.services.agent_service.save_session', side_effect=OSError('private')) as save, \
                    accept_test_owner(), TestClient(make_app(), headers=AUTH_HEADERS) as http:
                response = http.post(f'/sessions/{HTTP_SESSION_ID}/ask' + ('/stream' if streaming else ''), json={'question': 'sources'})
            result = decode_result(response, streaming)
            self.assertEqual(result['execution']['persistence'], 'failed')
            self.assertEqual(result['execution']['status'], 'failed')
            self.assertEqual(save.call_count, 1)
            self.assertNotIn('private', response.text)
            if streaming:
                self.assertEqual(response.text.count('event: result'), 1)

    def test_planner_and_reviewer_fallbacks_are_degraded(self):
        from agent.graph_agent import planner_node, review_node
        from agent.state import create_initial_agent_state
        state = create_initial_agent_state('Analyze.', object(), [])
        with patch('agent.llm_planner.chat_with_deepseek', return_value='null'):
            update = planner_node(state)
        self.assertEqual(update['node_statuses']['planner']['status'], 'degraded')
        state.update(steps=['qa', 'source'], answers=['answer', 'source'])
        with patch('utils.final_synthesizer.chat_with_deepseek', side_effect=LLMClientError('private')):
            update = review_node(state)
        self.assertEqual(update['node_statuses']['reviewer']['status'], 'degraded')
        self.assertIn('answer', update['answer'])

    def test_exception_deadline_and_cancel_keep_terminal_contract_and_close_graph(self):
        import asyncio
        from utils.llm_budget import LLMBudgetExceeded
        for exc, status, reason in [(ValueError('private'), 'failed', 'workflow_error'),
                (LLMBudgetExceeded('deadline'), 'failed', 'deadline_exceeded'),
                (asyncio.CancelledError(), 'cancelled', 'cancelled')]:
            graph = Mock()
            iterator = Mock()
            iterator.__iter__ = Mock(return_value=iterator)
            iterator.__next__ = Mock(side_effect=exc)
            graph.stream.return_value = iterator
            with self.subTest(reason=reason), patch('app.services.agent_service.get_pdf_agent_graph', return_value=graph), \
                    patch('app.services.agent_service.save_session'):
                result = ask_pdf_agent(self.session(), 'question')
            self.assertEqual(result['execution']['status'], status)
            self.assertEqual(result['execution']['reason'], reason)
            iterator.close.assert_called_once()

    def test_new_execution_is_optional_for_legacy_payload_validation(self):
        from app.schemas.responses import AskResponse
        with patch('app.services.agent_service.save_session'):
            result = ask_pdf_agent(self.session(), 'sources')
        result.pop('execution')
        self.assertIsNone(AskResponse.model_validate(result).execution)

    def test_parallel_failure_trace_is_isolated_from_successful_request(self):
        from concurrent.futures import ThreadPoolExecutor
        from agent.graph_agent import planner_node
        from agent.state import create_initial_agent_state
        def run(question):
            return planner_node(create_initial_agent_state(question, object(), []))
        with patch('agent.llm_planner.chat_with_deepseek', return_value='null'), ThreadPoolExecutor(2) as pool:
            failed, success = list(pool.map(run, ['Analyze.', 'sources']))
        self.assertEqual(failed['node_statuses']['planner']['status'], 'degraded')
        self.assertEqual(success['node_statuses']['planner']['status'], 'succeeded')
