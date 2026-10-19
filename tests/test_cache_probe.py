import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langchain_core.documents import Document

from evaluation.cache_probe import run_probe


class CacheProbeTests(unittest.TestCase):
    def test_paid_guard_runs_before_pdf_or_client_access(self):
        with patch('evaluation.cache_probe.parse_pdf_documents') as pdf, patch('evaluation.cache_probe.get_deepseek_client') as api:
            with self.assertRaisesRegex(ValueError, 'allow-paid-api'):
                run_probe('absent.pdf')
            pdf.assert_not_called()
            api.assert_not_called()

    def test_repeated_requests_record_actual_usage_without_prompt_or_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / 'unit.pdf'
            pdf.write_bytes(b'fixture')
            output = Path(directory) / 'report.json'
            client = Mock()
            client.with_options.return_value = client
            client.chat.completions.create.side_effect = [SimpleNamespace(model='deepseek-flash', usage={
                'prompt_tokens': 100, 'completion_tokens': 5, 'prompt_cache_hit_tokens': hit,
                'prompt_cache_miss_tokens': 100 - hit}) for hit in (0, 64, 64)]
            docs = [Document(page_content='PRIVATE FIXTURE DO NOT LOG', metadata={'source': 'unit.pdf', 'page': 0})]
            with patch('evaluation.cache_probe.parse_pdf_documents', return_value=docs), patch('evaluation.cache_probe.get_deepseek_client', return_value=client), contextlib.redirect_stdout(io.StringIO()):
                report = run_probe(pdf, page=1, delay_seconds=0, output=output, allow_paid_api=True)
            self.assertEqual([call['cache_hit_tokens'] for call in report['calls']], [0, 64, 64])
            self.assertEqual(report['summary']['cache_hit_rate'], 128 / 300)
            self.assertNotIn('PRIVATE FIXTURE', output.read_text())
            self.assertEqual(len({json.dumps(c.kwargs['messages']) for c in client.chat.completions.create.call_args_list}), 1)
            client.with_options.assert_called_once_with(max_retries=0, timeout=45)
            self.assertTrue(report['observed_cache_hit'])

    def test_failed_probe_preserves_incurred_usage_and_stops_paid_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / 'unit.pdf'
            pdf.write_bytes(b'fixture')
            output = Path(directory) / 'report.json'
            error = TimeoutError('failure')
            error.usage = {'prompt_tokens': 100, 'completion_tokens': 5, 'prompt_cache_hit_tokens': 50}
            client = Mock()
            client.with_options.return_value = client
            client.chat.completions.create.side_effect = error
            docs = [Document(page_content='text', metadata={'source': 'unit.pdf', 'page': 0})]
            with patch('evaluation.cache_probe.parse_pdf_documents', return_value=docs), patch('evaluation.cache_probe.get_deepseek_client', return_value=client), contextlib.redirect_stdout(io.StringIO()):
                run_probe(pdf, page=1, delay_seconds=0, output=output, allow_paid_api=True)
            report = json.loads(output.read_text())
            self.assertEqual(report['summary']['llm_calls'], 1)
            self.assertEqual(report['summary']['cache_hit_tokens'], 50)
            self.assertGreater(report['summary']['estimated_cost_usd'], 0)
            self.assertEqual(report['calls'][0]['status'], 'failed')


@unittest.skipUnless(os.getenv('PDF_AGENT_RUN_CACHE_API_TESTS') == '1',
                     'PAID DeepSeek repeated-Prompt probe; never enabled by API key or ordinary CI.')
class PaidCacheIntegrationTests(unittest.TestCase):
    def test_real_repeated_pdf_prompt_records_each_call(self):
        output = os.getenv('PDF_AGENT_CACHE_REPORT', 'evaluation/reports/cache-probe.json')
        report = run_probe(os.environ['PDF_AGENT_CACHE_PDF_PATH'],
                           page=int(os.getenv('PDF_AGENT_CACHE_PDF_PAGE', '3')),
                           output=output, allow_paid_api=True)
        self.assertEqual(len(report['calls']), 3)
        for call in report['calls']:
            self.assertEqual(call['status'], 'succeeded')
            self.assertTrue(call['cache_usage_available'])
            self.assertEqual(call['cache_hit_tokens'] + call['cache_miss_tokens'], call['input_tokens'])
        # Provider caching is asynchronous/best effort: do not assert a positive
        # rate or turn zero hits into a fabricated successful cache optimization.


if __name__ == '__main__':
    unittest.main()
