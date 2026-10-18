import re
from statistics import mean

from evaluation.usage import merge_usage


CITATION_PATTERN = re.compile(
    r"\[([^\[\]\n]+?,\s*page\s+\d+)\]",
    re.IGNORECASE,
)


def normalize_citation(value):
    if isinstance(value, dict):
        value = f"{value['source']}, page {value['page']}"
    return " ".join(str(value).casefold().split())


def extract_citations(answer):
    """Return normalized, de-duplicated citation IDs from an answer."""

    citations = []
    seen = set()

    for match in CITATION_PATTERN.findall(answer or ""):
        citation = normalize_citation(match)
        if citation not in seen:
            seen.add(citation)
            citations.append(citation)

    return citations


def _recall(expected, actual):
    if not expected:
        return 1.0
    return len(set(expected) & set(actual)) / len(set(expected))


def _answer_term_recall(answer, expected_terms):
    if not expected_terms:
        return 1.0

    normalized_answer = (answer or "").casefold()
    matched = 0

    for term_group in expected_terms:
        alternatives = (
            term_group
            if isinstance(term_group, list)
            else [term_group]
        )
        if any(str(term).casefold() in normalized_answer for term in alternatives):
            matched += 1

    return matched / len(expected_terms)


def evaluate_output(case, output):
    """Score one workflow output with deterministic, zero-cost metrics."""

    answer = output.get("answer", "")
    actual_steps = output.get("steps", [])
    sources = output.get("sources", [])
    expected_steps = case.get("expected_steps", [])

    valid_citations = {
        normalize_citation(source.get("citation_id", ""))
        for source in sources
        if source.get("citation_id")
    }
    cited = set(extract_citations(answer))
    expected_citations = {
        normalize_citation(citation)
        for citation in case.get("expected_citations", [])
    }

    if cited:
        citation_precision = len(cited & valid_citations) / len(cited)
    else:
        citation_precision = 0.0 if expected_citations else 1.0

    metrics = {
        "route_exact_match": float(actual_steps == expected_steps),
        "answer_nonempty": float(bool(answer.strip())),
        "answer_term_recall": round(
            _answer_term_recall(
                answer,
                case.get("expected_answer_terms", []),
            ),
            4,
        ),
        "source_recall": round(
            _recall(expected_citations, valid_citations),
            4,
        ),
        "citation_precision": round(citation_precision, 4),
        "expected_citation_recall": round(_recall(expected_citations, cited), 4),
        "revision_count": output.get("revision_count", 0),
        "latency_ms": output.get("latency_ms", 0),
    }
    # Keyword overlap remains a legacy controlled-fixture diagnostic, never a
    # factual quality score for real PDFs.
    if 'pdf_files' in case:
        metrics.pop('answer_term_recall')
    return metrics


def summarize_results(results, mode):
    """Aggregate case-level scores into a compact evaluation summary."""

    metrics = [result["metrics"] for result in results]
    summary = {
        "case_count": len(results),
        "route_accuracy": round(
            mean(metric["route_exact_match"] for metric in metrics),
            4,
        ),
    }

    if mode in ("live", "real-pdf"):
        summary.update(
            {
                "answer_success_rate": round(
                    mean(metric["answer_nonempty"] for metric in metrics),
                    4,
                ),
                "source_recall": round(
                    mean(metric["source_recall"] for metric in metrics),
                    4,
                ),
                "citation_precision": round(
                    mean(metric["citation_precision"] for metric in metrics),
                    4,
                ),
                "average_latency_ms": round(
                    mean(metric["latency_ms"] for metric in metrics),
                    2,
                ),
                "total_revisions": sum(
                    metric["revision_count"] for metric in metrics
                ),
            }
        )
        if mode == 'live':
            summary['answer_term_recall'] = round(mean(m['answer_term_recall'] for m in metrics), 4)
        if all('expected_citation_recall' in m for m in metrics):
            summary['expected_citation_recall'] = round(mean(m['expected_citation_recall'] for m in metrics), 4)

    for field in ('agent_usage', 'judge_usage'):
        summary[field] = merge_usage([result.get(field, result.get('usage', {}) if field == 'agent_usage' else {}) for result in results])
    summary['total_usage'] = merge_usage([summary['agent_usage'], summary['judge_usage']])
    # Legacy usage and flat fields continue to refer to Agent usage.
    summary['usage'] = summary['agent_usage']
    for field in ('llm_calls', 'total_tokens', 'estimated_cost_usd', 'cost_estimate_available', 'cost_status'):
        summary[field] = summary['agent_usage'][field]

    judge_results = [
        result["llm_judge"]
        for result in results
        if result.get("llm_judge")
    ]
    if judge_results:
        dimensions = [d for d in ('correctness', 'completeness', 'groundedness', 'relevance') if all(d in r for r in judge_results)]
        summary["llm_judge"] = {
            dimension: round(
                mean(result[dimension] for result in judge_results),
                2,
            )
            for dimension in dimensions
        }
        summary["llm_judge_average"] = round(
            mean(
                score
                for result in judge_results
                for score in (result[d] for d in dimensions)
            ),
            2,
        )

    return summary
