"""Structured-output boundaries; all model calls are Fake/Mock, never network."""
import json
import unittest
from unittest.mock import Mock, patch

from agent.collaboration_agent import collaboration_agent
from agent.llm_planner import plan_steps_with_llm
from tests.test_error_privacy import capture_json_logs, decode_result, make_app
from tests.test_llm_budget import response


def collaboration_payload(**updates):
    return dict(answer='Combined evidence.', issues=[], missing_information=[], recommendations=[],
                needs_revision=False, next_steps=[]) | updates


class PlannerValidationTests(unittest.TestCase):
    def test_valid_plan_preserves_all_five_names_and_order(self):
        with patch('agent.llm_planner.chat_with_deepseek',
                   return_value='["keyword","compare","qa","summary","source"]') as model:
            self.assertEqual(plan_steps_with_llm('Analyze this document.'),
                             ['keyword', 'compare', 'qa', 'summary', 'source'])
        self.assertEqual(model.call_count, 1)

    def test_empty_wrong_root_invalid_json_and_excessive_plans_fall_back(self):
        invalid = [None, 4, '', ' ', '[]', '{}', 'null', 'false', '"qa"',
                   '["QA"]', '["qа"]', '["qa",]', "['qa']", 'prefix ["qa"]',
                   '["summary"] trailing', '[NaN]', '[Infinity]',
                   json.dumps(['summary'] * 6), '[' * 1200, ' ' * 2049,
                   '{"steps":["summary"],"parameters":{"top_k":10000}}']
        for raw in invalid:
            with self.subTest(raw_type=type(raw).__name__), \
                    patch('agent.llm_planner.chat_with_deepseek', return_value=raw) as model:
                self.assertEqual(plan_steps_with_llm('Analyze this document.'), ['qa'])
                self.assertEqual(model.call_count, 1)

    def test_rule_fast_path_still_makes_no_model_or_schema_call(self):
        with patch('agent.llm_planner.chat_with_deepseek') as model, \
                patch('agent.llm_planner.parse_planner_output') as schema:
            self.assertEqual(plan_steps_with_llm('请总结文档并给出来源。'), ['summary', 'source'])
        model.assert_not_called()
        schema.assert_not_called()

    def test_nested_and_unknown_steps_never_escape_or_select_partial_plan(self):
        invalid = ('[{}]', '[[]]', '[null]', '[true]', '[1]', '["summary", "shell"]',
                   '[{"agent":"summary","parameters":{"session_id":"other"}}]')
        for raw in invalid:
            with self.subTest(raw=raw), patch('agent.llm_planner.chat_with_deepseek', return_value=raw), \
                    capture_json_logs() as logs:
                self.assertEqual(plan_steps_with_llm('Analyze this document.'), ['qa'])
                events = [json.loads(line)['event'] for line in logs.getvalue().splitlines()]
                self.assertIn('model_output_validation_failed', events)
                self.assertIn('planner_fallback', events)

    def test_safe_wrapping_and_duplicate_repair_preserve_order(self):
        raw = '\ufeff  ```json\n["summary", " source ", "summary"]\n```  '
        with patch('agent.llm_planner.chat_with_deepseek', return_value=raw) as model, \
                capture_json_logs() as logs:
            self.assertEqual(plan_steps_with_llm('Analyze this document.'), ['summary', 'source'])
        self.assertEqual(model.call_count, 1)
        self.assertIn('model_output_repaired', logs.getvalue())


class CollaborationValidationTests(unittest.TestCase):
    def test_valid_output_and_safe_repair_preserve_contract_and_new_step_order(self):
        data = collaboration_payload(answer='  Combined evidence.\n', issues=['  An issue. '],
            needs_revision=True, next_steps=[' summary ', 'qa', 'summary'])
        with patch('agent.collaboration_agent.chat_with_deepseek',
                   return_value='```JSON\n' + json.dumps(data) + '\n```') as model, \
                capture_json_logs() as logs:
            result = collaboration_agent('Compare.', ['compare'], ['Existing evidence.'])
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['answer'], 'Combined evidence.')
        self.assertEqual(result['issues'], ['An issue.'])
        self.assertTrue(result['needs_revision'])
        self.assertEqual(result['next_steps'], ['summary', 'qa'])
        self.assertEqual(set(result), {'agent', 'status', 'answer', 'issues', 'missing_information',
                                       'recommendations', 'needs_revision', 'next_steps'})
        self.assertEqual(model.call_count, 1)
        self.assertIn('model_output_repaired', logs.getvalue())

    def test_every_required_field_and_unknown_execution_parameters_are_rejected(self):
        payloads = []
        for name in collaboration_payload():
            value = collaboration_payload()
            del value[name]
            payloads.append(value)
        payloads += [collaboration_payload(parameters={'session_id': 'another-session'}),
                     collaboration_payload(status='success'), collaboration_payload(agent='Shell Agent')]
        for payload in payloads:
            with self.subTest(keys=list(payload)), patch('agent.collaboration_agent.chat_with_deepseek',
                                                        return_value=json.dumps(payload)):
                result = collaboration_agent('Compare.', ['compare'], ['Existing evidence.'])
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['needs_revision'])
            self.assertEqual(result['next_steps'], [])

    def test_strict_field_types_and_lengths_are_not_coerced_or_truncated(self):
        changes = [
            {'answer': None}, {'answer': 1}, {'answer': []}, {'answer': 'x' * 16001},
            {'answer': '\ud800'}, {'issues': None}, {'issues': [None]}, {'issues': [{}]},
            {'issues': [' ']}, {'issues': ['x' * 2049]}, {'issues': ['a'] * 21},
            {'missing_information': 'text'}, {'recommendations': 2},
            {'needs_revision': 1}, {'needs_revision': 0}, {'needs_revision': None},
            {'next_steps': 'qa'}, {'next_steps': [1]}, {'next_steps': [{}]},
            {'needs_revision': True, 'next_steps': ['qa'] * 6},
        ]
        for change in changes:
            with self.subTest(field=list(change)), patch('agent.collaboration_agent.chat_with_deepseek',
                    return_value=json.dumps(collaboration_payload(**change))):
                result = collaboration_agent('Compare.', ['compare'], ['Existing evidence.'])
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['answer'], 'Existing evidence.')

    def test_duplicate_keys_non_json_constants_deep_input_and_prose_are_rejected(self):
        body = json.dumps(collaboration_payload())
        cases = [body[:-1] + ',"needs_revision":true}',
                 body[:-1] + ',"private-key":NaN}',
                 body[:-1] + ',"private-key":Infinity}',
                 body[:-1] + ',"private-key":1e999}',
                 body[:-1] + ',"private-key":{"x":1,"x":2}}',
                 body[:-1] + ',"\ud800":1}',
                 'prefix ' + body, body + ' explanation', ' ' * 32769,
                 '[' * 1200 + '0' + ']' * 1200]
        for raw in cases:
            with self.subTest(length=len(raw)), patch('agent.collaboration_agent.chat_with_deepseek', return_value=raw), \
                    capture_json_logs() as logs:
                result = collaboration_agent('Compare.', ['compare'], ['Existing evidence.'])
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('private-key', str(result))
            self.assertNotIn('private-key', logs.getvalue())

    def test_validation_error_logs_never_include_untrusted_keys_or_values(self):
        marker = 'PRIVATE-OUTPUT-MARKER'
        for raw in (json.dumps(collaboration_payload(**{marker: marker})),
                    json.dumps(collaboration_payload(needs_revision=marker)),
                    json.dumps(collaboration_payload(needs_revision=True, next_steps=[marker]))):
            with patch('agent.collaboration_agent.chat_with_deepseek', return_value=raw), capture_json_logs() as logs:
                collaboration_agent('Compare.', ['compare'], ['Existing evidence.'])
            self.assertNotIn(marker, logs.getvalue())
            events = [json.loads(line) for line in logs.getvalue().splitlines()]
            failed = next(event for event in events if event['event'] == 'model_output_validation_failed')
            self.assertTrue(failed['error_codes'])
            self.assertIn('collaboration_fallback', {event['event'] for event in events})

    def test_no_answers_preserves_skipped_state_without_calling_model(self):
        with patch('agent.collaboration_agent.chat_with_deepseek') as model:
            result = collaboration_agent('Compare.', [], [])
        self.assertEqual(result['status'], 'skipped')
        self.assertFalse(result['needs_revision'])
        model.assert_not_called()

    def test_invalid_payloads_fail_closed_without_injecting_raw_response(self):
        invalid = [
            'not JSON private-marker', '[]', '{}',
            json.dumps(collaboration_payload(next_steps=None)),
            json.dumps(collaboration_payload(needs_revision='false', next_steps=['qa'])),
            json.dumps(collaboration_payload(answer={'private-marker': 'object'})),
            json.dumps(collaboration_payload(issues='private-marker')),
            json.dumps(collaboration_payload(answer='  ')),
            json.dumps(collaboration_payload(needs_revision=True, next_steps=['shell'])),
        ]
        for raw in invalid:
            with self.subTest(raw=raw), patch('agent.collaboration_agent.chat_with_deepseek', return_value=raw), \
                    capture_json_logs() as logs:
                result = collaboration_agent('Compare.', ['compare'], ['Existing evidence.'])
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['answer'], 'Existing evidence.')
            self.assertFalse(result['needs_revision'])
            self.assertEqual(result['next_steps'], [])
            self.assertNotIn('private-marker', str(result))
            self.assertNotIn('private-marker', logs.getvalue())
            self.assertIn('model_output_validation_failed', logs.getvalue())

    def test_revision_requires_consistent_nonempty_new_steps(self):
        for data in (
            collaboration_payload(needs_revision=False, next_steps=['qa']),
            collaboration_payload(needs_revision=True, next_steps=[]),
            collaboration_payload(needs_revision=True, next_steps=['compare']),
            collaboration_payload(needs_revision=True, next_steps=['qa', 'compare']),
        ):
            with self.subTest(data=data), patch('agent.collaboration_agent.chat_with_deepseek',
                                                return_value=json.dumps(data)):
                result = collaboration_agent('Compare.', ['compare'], ['Existing evidence.'])
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['needs_revision'])
            self.assertEqual(result['next_steps'], [])


class BudgetAndWorkflowTests(unittest.TestCase):
    def test_validation_fallback_never_buys_an_extra_repair_and_budget_remains_shared(self):
        from utils.llm_budget import BudgetSettings, RequestBudget
        from utils.observability import new_usage_tracker, observability_context
        tracker = new_usage_tracker(RequestBudget(BudgetSettings(max_calls=1)))
        client = Mock()
        client.chat.completions.create.return_value = response('[{}]')
        with patch('utils.llm_client.get_deepseek_client', return_value=client), \
                observability_context(usage_tracker=tracker):
            self.assertEqual(plan_steps_with_llm('Analyze this document.'), ['qa'])
            notes = collaboration_agent('Compare.', ['compare'], ['Existing evidence.'])
        self.assertEqual(notes['status'], 'failed')
        self.assertEqual(notes['next_steps'], [])
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(tracker.summary()['llm_calls'], 1)
        self.assertEqual(tracker.summary()['total_tokens'], 12)
        self.assertEqual(tracker.budget.summary()['stop_reason'], 'calls')

    def test_cancelled_budget_fallback_makes_zero_model_calls(self):
        from utils.llm_budget import RequestBudget
        from utils.observability import new_usage_tracker, observability_context
        tracker = new_usage_tracker(RequestBudget())
        tracker.budget.cancel()
        with patch('utils.llm_client.get_deepseek_client') as client, observability_context(usage_tracker=tracker):
            self.assertEqual(plan_steps_with_llm('Analyze this document.'), ['qa'])
            notes = collaboration_agent('Compare.', ['compare'], ['Existing evidence.'])
        self.assertEqual(notes['status'], 'failed')
        client.return_value.chat.completions.create.assert_not_called()
        self.assertEqual(tracker.summary()['llm_calls'], 0)

    def test_natural_language_nodes_remain_text_and_source_stays_zero_llm(self):
        from langchain_core.documents import Document
        from evaluation.runner import StaticVectorStore
        from agent.qa_agent import qa_agent
        from agent.summary_agent import summary_agent
        from agent.keyword_agent import keyword_agent
        from agent.compare_agent import compare_agent
        from agent.reviewer_agent import reviewer_agent
        from agent.source_agent import source_agent
        from utils.memory import build_llm_conversation_summary
        from utils.observability import new_usage_tracker, observability_context
        text = 'A natural paragraph, without JSON.'
        client = Mock()
        client.chat.completions.create.return_value = response(text)
        store = StaticVectorStore([Document(page_content='Evidence.', metadata={'source': 'paper.pdf', 'page': 0})])
        tracker = new_usage_tracker()
        with patch('utils.llm_client.get_deepseek_client', return_value=client), \
                patch('utils.memory._memory_cache', {}), observability_context(usage_tracker=tracker):
            self.assertEqual(qa_agent('What is it?', store, [])['answer'], text)
            for agent in (summary_agent, keyword_agent, compare_agent):
                self.assertEqual(agent(store, [])['answer'], text)
            self.assertEqual(reviewer_agent('Explain.', ['qa'], ['Evidence.'])['answer'], text)
            self.assertEqual(build_llm_conversation_summary([{'role': 'user', 'content': 'Old.'}] * 12), text)
            source = source_agent('List sources.', store, [])
        self.assertIn('[paper.pdf, page 1]', source['answer'])
        self.assertEqual(client.chat.completions.create.call_count, 6)
        self.assertEqual(tracker.summary()['llm_calls'], 6)

    def test_invalid_collaboration_keeps_json_and_sse_contract_without_raw_injection(self):
        from fastapi.testclient import TestClient
        from langchain_core.documents import Document
        from evaluation.runner import StaticVectorStore
        for streaming in (False, True):
            session = dict(session_id='test', messages=[], loaded_pdfs=['paper.pdf'], document_count=1,
                vectorstore=StaticVectorStore([Document(page_content='Evidence.',
                    metadata={'source': 'paper.pdf', 'page': 0})]))
            client = Mock()
            def completion(**kwargs):
                if 'You are the Collaboration Agent' in kwargs['messages'][0]['content']:
                    return response(json.dumps(collaboration_payload(needs_revision='PRIVATE-MARKER', next_steps=['qa'])))
                return response('Supported [paper.pdf, page 1].')
            client.chat.completions.create.side_effect = completion
            with patch('utils.llm_client.get_deepseek_client', return_value=client), \
                    patch('app.api.routes.get_session', return_value=session), \
                    patch('app.services.agent_service.save_session'), TestClient(make_app()) as http:
                answer = http.post('/sessions/test/ask' + ('/stream' if streaming else ''),
                                   json={'question': 'Compare the PDFs and cite sources.'})
            self.assertEqual(answer.status_code, 200)
            result = decode_result(answer, streaming)
            self.assertEqual(result['collaboration_notes']['status'], 'failed')
            self.assertFalse(result['collaboration_notes']['needs_revision'])
            self.assertEqual(result['revision_count'], 0)
            self.assertNotIn('PRIVATE-MARKER', answer.text)
            self.assertEqual(result['usage']['llm_calls'], 3)
            self.assertEqual(client.chat.completions.create.call_count, 3)

    def test_duplicate_revision_step_executes_once_and_global_revision_limit_is_unchanged(self):
        from app.services.agent_service import iter_pdf_agent_events
        from langchain_core.documents import Document
        from evaluation.runner import StaticVectorStore
        session = dict(session_id='test', messages=[], loaded_pdfs=['paper.pdf'], document_count=1,
            vectorstore=StaticVectorStore([Document(page_content='Evidence.', metadata={'source': 'paper.pdf', 'page': 0})]))
        revisions = []
        def completion(**kwargs):
            if 'You are the Collaboration Agent' in kwargs['messages'][0]['content']:
                revisions.append(True)
                return response(json.dumps(collaboration_payload(needs_revision=True,
                    next_steps=['qa', 'qa'] if len(revisions) == 1 else ['summary'])))
            return response('Supported.')
        client = Mock()
        client.chat.completions.create.side_effect = completion
        with patch('utils.llm_client.get_deepseek_client', return_value=client), \
                patch('app.services.agent_service.save_session'):
            result = list(iter_pdf_agent_events(session, 'Compare the PDFs and cite sources.'))[-1]['data']
        self.assertEqual(result['steps'], ['compare', 'source', 'qa'])
        self.assertEqual(result['revision_count'], 1)
        self.assertEqual(result['usage']['by_operation']['qa']['llm_calls'], 1)
        self.assertNotIn('summary', result['usage']['by_operation'])
        self.assertEqual(result['usage']['llm_calls'], 5)


if __name__ == '__main__':
    unittest.main()
