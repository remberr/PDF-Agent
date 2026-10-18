import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from langchain_core.documents import Document

from agent.graph_agent import build_pdf_agent_graph
from agent.llm_planner import plan_steps_fast, plan_steps_with_llm
from agent.state import create_initial_agent_state
from app.services.agent_service import serialize_sources
from evaluation.metrics import evaluate_output, summarize_results
from evaluation.judge import judge_output as _judge_output
from evaluation.real_pdf import DEFAULT_REAL_DATASET, DEFAULT_MANIFEST, RealPDFCorpus
from evaluation.usage import merge_usage
from utils.llm_client import get_deepseek_model
from utils.observability import new_usage_tracker, observability_context


DEFAULT_DATASET = Path(__file__).with_name("cases.json")


class StaticVectorStore:
    """Minimal deterministic retriever for controlled live evaluations."""

    def __init__(self, documents):
        self.documents = documents

    def similarity_search(self, _query, k=4):
        return self.documents[:k]


def load_cases(path):
    with Path(path).open(encoding="utf-8") as dataset_file:
        cases = json.load(dataset_file)

    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation dataset must be a non-empty JSON array.")

    return cases


def _build_documents(case):
    return [
        Document(
            page_content=document["content"],
            metadata={
                "source": document["source"],
                "page": document["page"],
            },
        )
        for document in case.get("documents", [])
    ]


def _run_routing_case(case):
    steps = plan_steps_with_llm(case["question"])
    output = {
        "answer": "",
        "steps": steps,
        "sources": [],
        "revision_count": 0,
        "latency_ms": 0,
    }
    return output


def _run_live_case(case, graph, vectorstore=None, loaded_pdfs=None):
    if vectorstore is None:
        documents = _build_documents(case)
        vectorstore = StaticVectorStore(documents)
        loaded_pdfs = list(dict.fromkeys(doc.metadata['source'] for doc in documents))
    state = create_initial_agent_state(case['question'], vectorstore, [], loaded_pdfs)
    final_state = graph.invoke(state)
    return {
        'answer': final_state.get('answer', ''),
        'steps': final_state.get('steps', []),
        'sources': serialize_sources(final_state.get('results', [])),
        'revision_count': final_state.get('revision_count', 0),
    }


def _select_cases(cases, args):
    selected = cases

    if args.mode == "live":
        selected = [case for case in selected if case.get("live", False)]

    if args.case:
        requested = set(args.case)
        selected = [case for case in selected if case["id"] in requested]
        missing = requested - {case["id"] for case in selected}
        if missing:
            raise ValueError(
                "Unknown or unavailable case IDs: " + ", ".join(sorted(missing))
            )

    if args.limit is not None:
        selected = selected[:args.limit]

    if not selected:
        raise ValueError("No evaluation cases were selected.")

    return selected


def _thresholds(args):
    values = {"route_accuracy": args.min_route_accuracy}
    if args.mode == "live":
        values.update(
            {
                "answer_term_recall": args.min_answer_term_recall,
                "source_recall": args.min_source_recall,
                "citation_precision": args.min_citation_precision,
            }
        )
    if args.mode == 'real-pdf':
        values.update(answer_success_rate=1.0, source_recall=args.min_source_recall,
                      citation_precision=args.min_citation_precision)
    if args.llm_judge:
        values.update(
            {
                "llm_judge_success_rate": 1.0,
                "llm_judge_average": args.min_llm_judge_score,
            }
        )
    return values


def _write_report(report, args):
    rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    print(rendered)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(rendered + '\n', encoding='utf-8')


def _corpus_check_report(cases, corpus, validation, args):
    retrieval_results = []
    if args.retrieval_only:
        for case in cases:
            index = corpus.vectorstore_for(case['pdf_files'])
            started = perf_counter()
            docs = index.similarity_search(case['question'], k=4)
            sources = serialize_sources(docs)
            recall = evaluate_output(case, {'sources': sources})['source_recall']
            retrieval_results.append({'id': case['id'], 'pdf_files': case['pdf_files'],
                                      'sources': sources, 'expected_page_retrieval_recall': recall,
                                      'retrieval_ms': round((perf_counter() - started) * 1000, 2)})
    return {
        'schema_version': 2, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'mode': 'real-pdf-retrieval' if args.retrieval_only else 'real-pdf-validation',
        'dataset': str(args.dataset), 'passed': None, 'validation_passed': True,
        'rag_executed': False, 'generation_executed': False,
        'quality_status': 'not_evaluated', 'reference_validation': validation,
        'corpus': corpus.metadata(), 'cases': retrieval_results,
    }


def run(args):
    if args.limit is not None and args.limit < 1:
        raise ValueError('--limit must be positive.')
    if args.mode != 'real-pdf' and (args.validate_only or args.retrieval_only):
        raise ValueError('--validate-only/--retrieval-only require --mode real-pdf.')
    if args.llm_judge and (args.mode == 'routing' or args.validate_only or args.retrieval_only):
        raise ValueError('--llm-judge requires live or real-pdf generation mode.')
    if args.dataset is None:
        args.dataset = DEFAULT_REAL_DATASET if args.mode == 'real-pdf' else DEFAULT_DATASET
    if args.mode == 'real-pdf' and args.output is None:
        suffix = '-validation' if args.validate_only else '-retrieval' if args.retrieval_only else ''
        args.output = Path(f'evaluation/reports/real-pdf{suffix}.json')
    cases = _select_cases(load_cases(args.dataset), args)
    corpus = None
    validation = None
    if args.mode == 'real-pdf':
        if not args.pdf_dir:
            raise ValueError('--pdf-dir is required for real-pdf mode; PDFs remain local.')
        corpus = RealPDFCorpus(args.pdf_dir, args.manifest)
        validation = corpus.validate_evidence(cases)
        if args.validate_only or args.retrieval_only:
            _write_report(_corpus_check_report(cases, corpus, validation, args), args)
            return 0

    # Payment guards follow the actual deterministic planner, not editable
    # expected routes in reference annotations.
    requires_llm = args.llm_judge or any(plan_steps_fast(case['question']) != ['source'] for case in cases)
    if args.mode in ('live', 'real-pdf') and requires_llm:
        if args.mode == 'real-pdf' and not args.allow_paid_api:
            raise ValueError('Real PDF generation/Judge requires --allow-paid-api. Use --validate-only or --retrieval-only for offline checks.')
        if not os.getenv('DEEPSEEK_API_KEY'):
            raise ValueError('DEEPSEEK_API_KEY is required for the selected generation/Judge cases.')
    graph = build_pdf_agent_graph() if args.mode != 'routing' else None
    results = []
    for case in cases:
        # Build the index outside timed Agent/Judge work. Never use annotations
        # as documents or state inputs, including for unanswerable cases.
        vectorstore = corpus.vectorstore_for(case['pdf_files']) if corpus else None
        agent_tracker = new_usage_tracker()
        output = {'answer': '', 'steps': [], 'sources': [], 'revision_count': 0}
        agent_error = None
        started = perf_counter()
        with observability_context(session_id=f"evaluation:{case['id']}:agent", usage_tracker=agent_tracker):
            try:
                if args.mode == 'routing':
                    output = _run_routing_case(case)
                else:
                    output = _run_live_case(case, graph, vectorstore, case.get('pdf_files'))
            except Exception as exc:
                agent_error = f'{type(exc).__name__}: {exc}'
        elapsed = round((perf_counter() - started) * 1000, 2)
        output['latency_ms'] = elapsed
        agent_usage = agent_tracker.summary() | {'elapsed_ms': elapsed}
        result = {
            'id': case['id'], 'question': case['question'],
            'expected_steps': case.get('expected_steps', []), 'actual_steps': output['steps'],
            'agent_status': 'failed' if agent_error else 'completed',
            'agent_usage': agent_usage, 'usage': agent_usage,
        }
        if agent_error:
            result['agent_error'] = agent_error
        if args.mode != 'routing':
            result.update(metrics=evaluate_output(case, output), answer=output['answer'], sources=output['sources'])
        else:
            result['metrics'] = {'route_exact_match': float(output['steps'] == case.get('expected_steps', []))}
        if corpus:
            result['pdf_files'] = case['pdf_files']
            result['annotation'] = case['annotation']
            result['answerability'] = case['answerability']
        judge_tracker = new_usage_tracker()
        judge_elapsed = 0.0
        result['judge_status'] = 'not_requested'
        if args.llm_judge and not agent_error:
            started = perf_counter()
            with observability_context(session_id=f"evaluation:{case['id']}:judge", usage_tracker=judge_tracker):
                try:
                    result['llm_judge'] = _judge_output(case, output)
                    result['judge_status'] = 'succeeded'
                except Exception as exc:
                    # Usage was recorded before parsing/validation; preserve it
                    # even on transport errors, bad JSON or invalid scores.
                    result['judge_status'] = 'failed'
                    result['llm_judge_error'] = f'{type(exc).__name__}: {exc}'
            judge_elapsed = round((perf_counter() - started) * 1000, 2)
        elif args.llm_judge:
            result['judge_status'] = 'skipped_agent_error'
        result['judge_usage'] = judge_tracker.summary() | {'elapsed_ms': judge_elapsed}
        result['total_usage'] = merge_usage([agent_usage, result['judge_usage']])
        results.append(result)

    summary = summarize_results(results, args.mode)
    if args.llm_judge:
        summary['llm_judge_success_rate'] = round(sum(r['judge_status'] == 'succeeded' for r in results) / len(results), 4)
        summary.setdefault('llm_judge_average', 0.0)
    thresholds = _thresholds(args)
    passed = all(summary[metric] >= minimum for metric, minimum in thresholds.items()) and not any('agent_error' in r for r in results)
    report = {
        'schema_version': 2, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'mode': args.mode, 'dataset': str(args.dataset),
        'dataset_sha256': hashlib.sha256(Path(args.dataset).read_bytes()).hexdigest(),
        'agent_model': get_deepseek_model(),
        'passed': passed, 'thresholds': thresholds, 'summary': summary, 'cases': results,
        'workflow_executed': args.mode != 'routing',
        'generation_executed': args.mode != 'routing' and summary['agent_usage']['llm_calls'] > 0,
        'rag_executed': args.mode == 'real-pdf' and summary['agent_usage']['llm_calls'] > 0,
        'quality_status': 'provisional_llm_judged' if args.llm_judge and corpus else 'llm_judged' if args.llm_judge else 'structural_metrics_only',
    }
    if corpus:
        report.update(corpus=corpus.metadata(), reference_validation=validation)
    _write_report(report, args)
    return 0 if passed else 1


def build_parser():
    parser = argparse.ArgumentParser(
        description="Evaluate PDF Agent routing, answers, and citations."
    )
    parser.add_argument(
        "--mode",
        choices=("routing", "live", "real-pdf"),
        default="routing",
    )
    parser.add_argument("--dataset", type=Path, help="Defaults to cases.json; real-pdf uses real_pdf_cases.json.")
    parser.add_argument("--pdf-dir", type=Path, help="Local directory containing the three manifest PDFs.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument("--validate-only", action="store_true", help="Validate PDF hashes/pages/evidence, no embeddings or LLM.")
    checks.add_argument("--retrieval-only", action="store_true", help="Real embeddings/FAISS retrieval, no generation or Judge.")
    parser.add_argument("--allow-paid-api", action="store_true", help="Explicitly enable real PDF paid generation/Judge.")
    parser.add_argument("--case", action="append", help="Run one case ID.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--llm-judge", action="store_true")
    parser.add_argument("--min-route-accuracy", type=float, default=1.0)
    parser.add_argument("--min-answer-term-recall", type=float, default=0.7)
    parser.add_argument("--min-source-recall", type=float, default=1.0)
    parser.add_argument("--min-citation-precision", type=float, default=0.8)
    parser.add_argument("--min-llm-judge-score", type=float, default=3.0)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        return run(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
