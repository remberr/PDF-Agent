import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from evaluation.runner import build_parser, run
from evaluation.usage import merge_usage
from utils.observability import new_usage_tracker, observability_context, record_llm_usage


def response(text):
    return SimpleNamespace(model='deepseek-flash',
                           choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
                           usage={'prompt_tokens': 100, 'completion_tokens': 10, 'prompt_cache_hit_tokens': 40})


class EvaluationUsageTests(unittest.TestCase):
    def run_case(self, directory, text, judge=True):
        path = Path(directory) / 'report.json'
        args = build_parser().parse_args(['--mode', 'live', '--case', 'source-citations', '--output', str(path)] + (['--llm-judge'] if judge else []))
        client = Mock()
        client.chat.completions.create.return_value = response(text)
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'test-only'}), patch('utils.llm_client.get_deepseek_client', return_value=client), contextlib.redirect_stdout(io.StringIO()):
            run(args)
        return json.loads(path.read_text(encoding='utf-8'))

    def test_judge_json_failure_retains_usage_and_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self.run_case(directory, 'not JSON')
        case = report['cases'][0]
        self.assertEqual(case['agent_usage']['llm_calls'], 0)
        self.assertEqual(case['judge_usage']['llm_calls'], 1)
        self.assertEqual(case['judge_usage']['total_tokens'], 110)
        self.assertGreater(case['judge_usage']['estimated_cost_usd'], 0)
        self.assertEqual(case['judge_status'], 'failed')
        self.assertIn('llm_judge_error', case)
        self.assertEqual(report['summary']['total_usage']['total_tokens'], 110)
        self.assertEqual(report['summary']['judge_usage']['total_tokens'], case['judge_usage']['total_tokens'])
        self.assertEqual(report['summary']['judge_usage']['estimated_cost_usd'], case['judge_usage']['estimated_cost_usd'])
        self.assertFalse(report['passed'])

    def test_success_and_no_judge(self):
        scores = json.dumps(dict(correctness=5, completeness=4, groundedness=5, relevance=4, reason='ok'))
        with tempfile.TemporaryDirectory() as directory:
            report = self.run_case(directory, scores)
            no_judge = self.run_case(directory, '', judge=False)
        case = report['cases'][0]
        self.assertEqual(case['judge_status'], 'succeeded')
        self.assertEqual(case['total_usage']['by_operation']['evaluation_judge']['llm_calls'], 1)
        self.assertEqual(case['usage'], case['agent_usage'])
        self.assertGreaterEqual(case['judge_usage']['elapsed_ms'], 0)
        self.assertEqual(no_judge['cases'][0]['judge_status'], 'not_requested')
        self.assertEqual(no_judge['summary']['judge_usage']['llm_calls'], 0)

    def test_merge_counts_models_operations_and_unknown_costs(self):
        tracker = new_usage_tracker()
        with observability_context(usage_tracker=tracker):
            record_llm_usage('unknown', 'failed_judge', None, 20)
        total = merge_usage([tracker.summary(), tracker.summary()])
        self.assertEqual(total['llm_calls'], 2)
        self.assertEqual(total['duration_ms'], 40)
        self.assertEqual(total['unpriced_calls'], 2)
        self.assertEqual(total['cost_status'], 'unavailable')
        self.assertFalse(total['by_operation']['failed_judge']['cost_estimate_available'])

    def test_transport_failure_is_an_unknown_cost_call(self):
        client = Mock()
        client.chat.completions.create.side_effect = TimeoutError('test timeout')
        from utils.llm_client import LLMClientError, chat_with_deepseek
        tracker = new_usage_tracker()
        with patch('utils.llm_client.get_deepseek_client', return_value=client), observability_context(usage_tracker=tracker):
            with self.assertRaises(LLMClientError):
                chat_with_deepseek('test', model='deepseek-flash', operation='evaluation_judge')
        self.assertEqual(tracker.summary()['llm_calls'], 1)
        self.assertEqual(tracker.summary()['cost_status'], 'unavailable')

    def test_parallel_specialists_and_judge_remain_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'report.json'
            args = build_parser().parse_args(['--mode','live','--case','compare-reports','--llm-judge','--output',str(output)])
            client = Mock()
            def complete(**kwargs):
                text = kwargs['messages'][0]['content']
                if 'independent PDF answer evaluator' in text:
                    return response(json.dumps(dict(correctness=5,completeness=5,groundedness=5,relevance=5)))
                return response('Blue rule-based; Green LLM planner [blue-report.pdf, page 1] [green-report.pdf, page 2].')
            client.chat.completions.create.side_effect = complete
            with patch.dict('os.environ', {'DEEPSEEK_API_KEY':'test-only'}), \
                 patch('utils.llm_client.get_deepseek_client', return_value=client), contextlib.redirect_stdout(io.StringIO()):
                run(args)
            report = json.loads(output.read_text(encoding='utf-8'))
        case = report['cases'][0]
        self.assertGreater(case['agent_usage']['llm_calls'], 1)
        self.assertNotIn('evaluation_judge', case['agent_usage']['by_operation'])
        self.assertEqual(set(case['judge_usage']['by_operation']), {'evaluation_judge'})
        self.assertEqual(case['total_usage']['llm_calls'], case['agent_usage']['llm_calls'] + 1)
        self.assertEqual(report['summary']['total_usage']['input_tokens'], case['total_usage']['input_tokens'])


if __name__ == '__main__':
    unittest.main()
