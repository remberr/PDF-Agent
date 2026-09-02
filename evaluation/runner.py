import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from langchain_core.documents import Document

from agent.graph_agent import build_pdf_agent_graph
from agent.llm_planner import plan_steps_with_llm
from agent.state import create_initial_agent_state
from app.services.agent_service import serialize_sources
from evaluation.metrics import evaluate_output, summarize_results
from utils.llm_client import LLMClientError, chat_with_deepseek
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


def _run_live_case(case, graph):
    documents = _build_documents(case)
    vectorstore = StaticVectorStore(documents)
    loaded_pdfs = list(
        dict.fromkeys(document.metadata["source"] for document in documents)
    )
    state = create_initial_agent_state(
        case["question"],
        vectorstore,
        [],
        loaded_pdfs,
    )
    usage_tracker = new_usage_tracker()

    started_at = perf_counter()
    with observability_context(
        session_id=f"evaluation:{case['id']}",
        usage_tracker=usage_tracker,
    ):
        final_state = graph.invoke(state)
    latency_ms = round((perf_counter() - started_at) * 1000, 2)

    return {
        "answer": final_state.get("answer", ""),
        "steps": final_state.get("steps", []),
        "sources": serialize_sources(final_state.get("results", [])),
        "revision_count": final_state.get("revision_count", 0),
        "latency_ms": latency_ms,
        "usage": usage_tracker.summary(),
    }


def _judge_output(case, output):
    documents = "\n\n".join(
        (
            f"[{document['source']}, page {document['page'] + 1}]\n"
            f"{document['content']}"
        )
        for document in case.get("documents", [])
    )
    prompt = f"""
You are evaluating a PDF question-answering agent.

Question:
{case['question']}

Reference evidence:
{documents}

Candidate answer:
{output['answer']}

Return ONLY JSON with integer scores from 1 to 5:
{{
  "correctness": 1,
  "groundedness": 1,
  "relevance": 1,
  "reason": "One concise explanation."
}}

Scoring rules:
- correctness: factual agreement with the reference evidence
- groundedness: claims are supported by the reference evidence
- relevance: directly answers the question without unnecessary content
"""

    content = chat_with_deepseek(
        prompt,
        operation="evaluation_judge",
    ).strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].lstrip()

    parsed = json.loads(content)
    result = {
        dimension: max(1, min(5, int(parsed[dimension])))
        for dimension in ("correctness", "groundedness", "relevance")
    }
    result["reason"] = str(parsed.get("reason", ""))
    return result


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
    if args.llm_judge:
        values.update(
            {
                "llm_judge_success_rate": 1.0,
                "llm_judge_average": args.min_llm_judge_score,
            }
        )
    return values


def run(args):
    cases = _select_cases(load_cases(args.dataset), args)
    requires_llm = args.llm_judge or any(
        case.get("expected_steps") != ["source"] for case in cases
    )

    if args.mode == "live" and requires_llm and not os.getenv("DEEPSEEK_API_KEY"):
        raise ValueError(
            "DEEPSEEK_API_KEY is required for the selected live cases."
        )

    graph = build_pdf_agent_graph() if args.mode == "live" else None
    results = []

    for case in cases:
        output = (
            _run_live_case(case, graph)
            if args.mode == "live"
            else _run_routing_case(case)
        )
        result = {
            "id": case["id"],
            "question": case["question"],
            "expected_steps": case.get("expected_steps", []),
            "actual_steps": output["steps"],
        }

        if args.mode == "live":
            result["metrics"] = evaluate_output(case, output)
            result["answer"] = output["answer"]
            result["sources"] = output["sources"]
            result["usage"] = output["usage"]
        else:
            result["metrics"] = {
                "route_exact_match": float(
                    output["steps"] == case.get("expected_steps", [])
                )
            }

        if args.llm_judge:
            try:
                result["llm_judge"] = _judge_output(case, output)
            except (LLMClientError, json.JSONDecodeError, KeyError, ValueError) as exc:
                result["llm_judge_error"] = str(exc)

        results.append(result)

    summary = summarize_results(results, args.mode)
    if args.llm_judge:
        successful_judges = sum(
            bool(result.get("llm_judge")) for result in results
        )
        summary["llm_judge_success_rate"] = round(
            successful_judges / len(results),
            4,
        )
        summary.setdefault("llm_judge_average", 0.0)

    thresholds = _thresholds(args)
    passed = all(
        summary[metric] >= minimum
        for metric, minimum in thresholds.items()
    )
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "dataset": str(args.dataset),
        "passed": passed,
        "thresholds": thresholds,
        "summary": summary,
        "cases": results,
    }

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")

    return 0 if passed else 1


def build_parser():
    parser = argparse.ArgumentParser(
        description="Evaluate PDF Agent routing, answers, and citations."
    )
    parser.add_argument(
        "--mode",
        choices=("routing", "live"),
        default="routing",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
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
