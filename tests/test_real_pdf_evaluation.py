import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from agent.llm_planner import plan_steps_fast
from evaluation.judge import judge_output
from evaluation.real_pdf import DEFAULT_MANIFEST, DEFAULT_REAL_DATASET, RealPDFCorpus, validate_real_cases
from evaluation.runner import build_parser, load_cases, run


class LocalTestEmbeddings(Embeddings):
    """Unit-test vectors only; the Real PDF CLI always uses production embeddings."""
    def embed_query(self, text):
        text = text.lower()
        return [float('jupiter' in text), float('venus' in text), .1]

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]


class RealPDFEvaluationTests(unittest.TestCase):
    def test_dataset_is_annotated_and_keeps_controlled_cases_separate(self):
        cases = load_cases(DEFAULT_REAL_DATASET)
        filenames = [f['filename'] for f in json.loads(DEFAULT_MANIFEST.read_text())['files']]
        validate_real_cases(cases, filenames)
        self.assertEqual(len(cases), 30)
        self.assertEqual({step for c in cases for step in c['expected_steps']}, {'qa', 'summary', 'compare', 'source', 'keyword'})
        for c in cases:
            self.assertNotIn('documents', c)
            self.assertTrue(c['forbidden_claims'])
            self.assertFalse(c['annotation']['human_verified'])
            with self.subTest(case=c['id']):
                self.assertEqual(plan_steps_fast(c['question']), c['expected_steps'])

    def fixture(self, directory):
        folder = Path(directory)
        file = folder / 'unit.pdf'
        file.write_bytes(b'unit test parser input')
        manifest = folder / 'manifest.json'
        manifest.write_text(json.dumps({'files': [{'filename':file.name, 'sha256':hashlib.sha256(file.read_bytes()).hexdigest(), 'pages':2}]}))
        docs = [Document(page_content='Jupiter is the largest planet.', metadata={'source':file.name,'page':0}),
                Document(page_content='Venus has a dense atmosphere.', metadata={'source':file.name,'page':1})]
        case = {'id':'unit', 'question':'What does the PDF say about Jupiter?', 'pdf_files':[file.name], 'expected_steps':['qa'],
                'required_facts':[{'id':'F1','statement':'REFERENCE_ONLY_SENTINEL','citations':['unit.pdf, page 1']}],
                'expected_citations':[{'source':file.name,'page':1,'evidence':['Jupiter is the largest planet.']}],
                'forbidden_claims':['UNSUPPORTED_SENTINEL'], 'answerability':'answerable', 'expected_behavior':'Answer with evidence.',
                'annotation':{'status':'pending_human_review'}}
        return manifest, docs, case

    def test_real_faiss_retrieval_has_no_reference_leakage_and_usage_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, docs, case = self.fixture(directory)
            dataset = Path(directory) / 'cases.json'
            dataset.write_text(json.dumps([case]))
            report = Path(directory) / 'report.json'
            args = build_parser().parse_args(['--mode','real-pdf','--manifest',str(manifest),'--dataset',str(dataset),
                                             '--pdf-dir',directory,'--allow-paid-api','--llm-judge','--output',str(report)])
            client = Mock()
            def completion(**kwargs):
                prompt = kwargs['messages'][0]['content']
                is_judge = 'independent PDF answer evaluator' in prompt
                if is_judge:
                    self.assertIn('REFERENCE_ONLY_SENTINEL', prompt)
                    content = json.dumps(dict(correctness=5, completeness=5, groundedness=5, relevance=5))
                else:
                    self.assertIn('Jupiter is the largest planet.', prompt)
                    self.assertNotIn('REFERENCE_ONLY_SENTINEL', prompt)
                    self.assertNotIn('UNSUPPORTED_SENTINEL', prompt)
                    content = 'Jupiter is the largest planet [unit.pdf, page 1].'
                return SimpleNamespace(model='deepseek-flash', choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                                       usage={'prompt_tokens':100,'completion_tokens':10})
            client.chat.completions.create.side_effect = completion
            with patch('evaluation.real_pdf.parse_pdf_documents', return_value=docs) as parser, \
                 patch('utils.vectorstore.get_embeddings', return_value=LocalTestEmbeddings()), \
                 patch('utils.llm_client.get_deepseek_client', return_value=client), \
                 patch.dict(os.environ, {'DEEPSEEK_API_KEY':'unit-only'}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(args), 0)
            parser.assert_called_once_with(Path(directory)/'unit.pdf', 'unit.pdf')
            data = json.loads(report.read_text())
            self.assertEqual(data['mode'], 'real-pdf')
            self.assertEqual(data['summary']['agent_usage']['llm_calls'], 1)
            self.assertEqual(data['summary']['judge_usage']['llm_calls'], 1)
            self.assertEqual(data['summary']['total_usage']['total_tokens'], 220)
            self.assertEqual(data['summary']['total_usage']['by_operation']['qa']['total_tokens'], 110)
            self.assertFalse(data['corpus']['reference_evidence_in_agent_context'])

    def test_evidence_wrong_page_and_hash_fail_before_index_or_api(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, docs, case = self.fixture(directory)
            with patch('evaluation.real_pdf.parse_pdf_documents', return_value=docs), patch('evaluation.real_pdf.create_vectorstore') as index:
                corpus = RealPDFCorpus(directory, manifest)
                self.assertEqual(corpus.validate_evidence([case])['evidence_quotes_checked'], 1)
                altered = deepcopy(case)
                altered['expected_citations'][0]['evidence'] = ['Fabricated quote']
                with self.assertRaisesRegex(ValueError, 'quote missing'):
                    corpus.validate_evidence([altered])
                altered['expected_citations'][0]['page'] = 20
                altered['required_facts'][0]['citations'] = ['unit.pdf, page 20']
                with self.assertRaisesRegex(ValueError, 'out of range'):
                    corpus.validate_evidence([altered])
                index.assert_not_called()
                (Path(directory)/'unit.pdf').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    RealPDFCorpus(directory, manifest)

    def test_no_paid_requests_without_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, docs, case = self.fixture(directory)
            dataset = Path(directory)/'cases.json'
            dataset.write_text(json.dumps([case]))
            args = build_parser().parse_args(['--mode','real-pdf','--pdf-dir',directory,'--manifest',str(manifest),'--dataset',str(dataset)])
            with patch('evaluation.real_pdf.parse_pdf_documents', return_value=docs), patch('evaluation.real_pdf.create_vectorstore') as index, patch('utils.llm_client.get_deepseek_client') as client:
                with self.assertRaisesRegex(ValueError, 'allow-paid-api'):
                    run(args)
            index.assert_not_called()
            client.assert_not_called()
            # Incorrect reference routing must not bypass the paid-request guard.
            case['expected_steps'] = ['source']
            dataset.write_text(json.dumps([case]))
            with patch('evaluation.real_pdf.parse_pdf_documents', return_value=docs):
                with self.assertRaisesRegex(ValueError, 'allow-paid-api'):
                    run(args)

    def test_judge_checks_semantic_facts_omissions_and_abstention(self):
        case = load_cases(DEFAULT_REAL_DATASET)[-2]
        answer = {'answer':'Insufficient evidence for an exact bill.', 'sources':[]}
        scores = json.dumps(dict(correctness=5, completeness=5, groundedness=5, relevance=5))
        with patch('evaluation.judge.chat_with_deepseek', return_value=scores) as chat:
            judge_output(case, answer)
        prompt = chat.call_args.args[0]
        for token in ('semantic entailment', 'omissions', 'forbidden_claims', 'pending_human_review', 'insufficient_evidence'):
            self.assertIn(token, prompt)
        with patch('evaluation.judge.chat_with_deepseek', return_value=scores.replace('"correctness": 5', '"correctness": 7')):
            with self.assertRaisesRegex(ValueError, 'Invalid Judge score'):
                judge_output(case, answer)


@unittest.skipUnless(os.getenv('PDF_AGENT_RUN_LOCAL_PDF_TESTS') == '1', 'Requires local PDFs and cached production embeddings; opt in explicitly.')
class LocalPDFIntegrationTests(unittest.TestCase):
    def test_production_parser_embeddings_faiss(self):
        corpus = RealPDFCorpus(os.environ['PDF_AGENT_EVAL_PDF_DIR'])
        cases = load_cases(DEFAULT_REAL_DATASET)
        self.assertEqual(corpus.validate_evidence(cases)['case_count'], 30)
        index = corpus.vectorstore_for([f['filename'] for f in corpus.manifest])
        docs = index.similarity_search('BERT masked language model next sentence prediction', k=4)
        self.assertTrue(any(doc.metadata['source'] == 'N19-1423.pdf' for doc in docs))


@unittest.skipUnless(os.getenv('PDF_AGENT_RUN_PAID_TESTS') == '1', 'PAID DeepSeek API integration: never enabled by ordinary CI or API key alone.')
class PaidPDFIntegrationTests(unittest.TestCase):
    def test_real_rag_and_judge_report(self):
        # This invokes real production embeddings, FAISS, LangGraph and DeepSeek.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'paid.json'
            args = build_parser().parse_args(['--mode','real-pdf','--pdf-dir',os.environ['PDF_AGENT_EVAL_PDF_DIR'],
                                             '--case','real-qa-attention-scaling','--allow-paid-api','--llm-judge','--output',str(output)])
            with contextlib.redirect_stdout(io.StringIO()):
                code = run(args)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(code, 0)
            self.assertEqual(report['cases'][0]['judge_status'], 'succeeded')
            self.assertGreater(report['summary']['agent_usage']['llm_calls'], 0)
            self.assertGreater(report['summary']['judge_usage']['llm_calls'], 0)


if __name__ == '__main__':
    unittest.main()
