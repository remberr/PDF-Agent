import unittest
from unittest.mock import patch

from agent.llm_planner import plan_steps_with_llm
from evaluation.metrics import (
    evaluate_output,
    extract_citations,
    summarize_results,
)
from evaluation.runner import DEFAULT_DATASET, load_cases


class EvaluationMetricTests(unittest.TestCase):
    def test_extract_citations_normalizes_and_deduplicates(self):
        answer = (
            "Claim [Paper.pdf, page 2]. "
            "Repeated [paper.pdf,   page 2]."
        )

        self.assertEqual(
            extract_citations(answer),
            ["paper.pdf, page 2"],
        )

    def test_evaluate_output_scores_answer_sources_and_route(self):
        case = {
            "expected_steps": ["qa"],
            "expected_answer_terms": [["35%", "35 percent"], "latency"],
            "expected_citations": ["performance.pdf, page 1"],
        }
        output = {
            "answer": (
                "Latency fell by 35% [performance.pdf, page 1]. "
                "Unsupported [unknown.pdf, page 9]."
            ),
            "steps": ["qa"],
            "sources": [
                {
                    "citation_id": "performance.pdf, page 1",
                    "source": "performance.pdf",
                    "page": 1,
                    "excerpt": "Evidence",
                }
            ],
            "revision_count": 0,
            "latency_ms": 125.5,
        }

        metrics = evaluate_output(case, output)

        self.assertEqual(metrics["route_exact_match"], 1.0)
        self.assertEqual(metrics["answer_term_recall"], 1.0)
        self.assertEqual(metrics["source_recall"], 1.0)
        self.assertEqual(metrics["citation_precision"], 0.5)

    def test_summary_aggregates_live_metrics(self):
        result = {
            "metrics": {
                "route_exact_match": 1.0,
                "answer_nonempty": 1.0,
                "answer_term_recall": 0.5,
                "source_recall": 1.0,
                "citation_precision": 1.0,
                "revision_count": 1,
                "latency_ms": 200.0,
            },
            "llm_judge": {
                "correctness": 5,
                "groundedness": 4,
                "relevance": 3,
                "reason": "Grounded and relevant.",
            },
        }

        summary = summarize_results([result], "live")

        self.assertEqual(summary["route_accuracy"], 1.0)
        self.assertEqual(summary["answer_term_recall"], 0.5)
        self.assertEqual(summary["total_revisions"], 1)
        self.assertEqual(summary["average_latency_ms"], 200.0)
        self.assertEqual(summary["llm_judge_average"], 4.0)


class RoutingBenchmarkTests(unittest.TestCase):
    @patch("agent.llm_planner.chat_with_deepseek")
    def test_dataset_routes_without_llm_calls(self, mock_chat):
        cases = load_cases(DEFAULT_DATASET)

        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(
                    plan_steps_with_llm(case["question"]),
                    case["expected_steps"],
                )

        mock_chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
