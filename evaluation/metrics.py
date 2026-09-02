import re
from statistics import mean


CITATION_PATTERN = re.compile(
    r"\[([^\[\]\n]+?,\s*page\s+\d+)\]",
    re.IGNORECASE,
)


def normalize_citation(value):
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

    return {
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
        "revision_count": output.get("revision_count", 0),
        "latency_ms": output.get("latency_ms", 0),
    }


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

    if mode == "live":
        usage_summaries = [
            result.get("usage", {}) for result in results
        ]
        summary.update(
            {
                "answer_success_rate": round(
                    mean(metric["answer_nonempty"] for metric in metrics),
                    4,
                ),
                "answer_term_recall": round(
                    mean(metric["answer_term_recall"] for metric in metrics),
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
                "llm_calls": sum(
                    usage.get("llm_calls", 0) for usage in usage_summaries
                ),
                "total_tokens": sum(
                    usage.get("total_tokens", 0) for usage in usage_summaries
                ),
                "estimated_cost_usd": round(
                    sum(
                        usage.get("estimated_cost_usd", 0.0)
                        for usage in usage_summaries
                    ),
                    8,
                ),
            }
        )

    judge_results = [
        result["llm_judge"]
        for result in results
        if result.get("llm_judge")
    ]
    if judge_results:
        summary["llm_judge"] = {
            dimension: round(
                mean(result[dimension] for result in judge_results),
                2,
            )
            for dimension in ("correctness", "groundedness", "relevance")
        }
        summary["llm_judge_average"] = round(
            mean(
                score
                for result in judge_results
                for score in (
                    result["correctness"],
                    result["groundedness"],
                    result["relevance"],
                )
            ),
            2,
        )

    return summary
