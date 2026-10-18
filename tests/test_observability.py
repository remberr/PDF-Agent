import json
import logging
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.services.agent_service import iter_pdf_agent_events
from utils.llm_client import chat_with_deepseek
from utils.observability import (
    JsonFormatter,
    RequestContextMiddleware,
    empty_usage_summary,
    get_model_pricing,
    new_usage_tracker,
    observability_context,
    record_llm_usage,
)


class PricingTests(unittest.TestCase):
    def test_deepseek_pricing_uses_peak_and_off_peak_rates(self):
        peak = datetime(2026, 9, 7, 1, tzinfo=timezone.utc)
        off_peak = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)

        with patch.dict(os.environ, {}, clear=False):
            for env_name in (
                "LLM_CACHE_HIT_COST_PER_1M_TOKENS",
                "LLM_CACHE_MISS_COST_PER_1M_TOKENS",
                "LLM_OUTPUT_COST_PER_1M_TOKENS",
            ):
                os.environ.pop(env_name, None)

            peak_prices = get_model_pricing("deepseek-flash", peak)
            off_peak_prices = get_model_pricing(
                "deepseek-flash",
                off_peak,
            )

        self.assertEqual(peak_prices["tier"], "peak")
        self.assertEqual(peak_prices["cache_miss"], 0.30)
        self.assertEqual(off_peak_prices["tier"], "off_peak")
        self.assertEqual(off_peak_prices["cache_miss"], 0.15)

    def test_usage_tracker_calculates_cache_aware_cost(self):
        tracker = new_usage_tracker()
        usage = {
            "prompt_tokens": 1000,
            "completion_tokens": 100,
            "total_tokens": 1100,
            "prompt_cache_hit_tokens": 100,
            "prompt_cache_miss_tokens": 900,
        }

        with patch(
            "utils.observability.get_model_pricing",
            return_value={
                "cache_hit": 0.006,
                "cache_miss": 0.30,
                "output": 1.20,
                "tier": "peak",
                "available": True,
            },
        ):
            with observability_context(usage_tracker=tracker):
                record_llm_usage(
                    "deepseek-flash",
                    "qa",
                    usage,
                    25.0,
                )

        summary = tracker.summary()

        self.assertEqual(summary["llm_calls"], 1)
        self.assertEqual(summary["total_tokens"], 1100)
        self.assertEqual(summary["cache_hit_rate"], 0.1)
        self.assertAlmostEqual(summary["estimated_cost_usd"], 0.0003906)
        self.assertEqual(summary["by_operation"]["qa"]["llm_calls"], 1)


class StructuredLoggingTests(unittest.TestCase):
    def test_json_formatter_includes_request_context_and_fields(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            "test.logger",
            logging.INFO,
            __file__,
            1,
            "workflow_completed",
            (),
            None,
        )
        record.event = "workflow_completed"
        record.structured_fields = {"duration_ms": 12.5}

        with observability_context("request-1", "session-1"):
            payload = json.loads(formatter.format(record))

        self.assertEqual(payload["event"], "workflow_completed")
        self.assertEqual(payload["request_id"], "request-1")
        self.assertEqual(payload["session_id"], "session-1")
        self.assertEqual(payload["duration_ms"], 12.5)

    @patch("app.api.routes.ask_pdf_agent")
    @patch("app.api.routes.get_session")
    def test_request_id_reaches_agent_and_response_header(
        self,
        mock_get_session,
        mock_ask_pdf_agent,
    ):
        session = {
            "session_id": "session-1",
            "vectorstore": object(),
        }
        mock_get_session.return_value = session
        mock_ask_pdf_agent.return_value = {
            "answer": "Answer",
            "steps": ["qa"],
            "sources": [],
            "collaboration_notes": {},
            "revision_count": 0,
            "timings": {"total": 1.0},
            "usage": empty_usage_summary(),
        }
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.add_middleware(RequestContextMiddleware)

        with TestClient(test_app) as client:
            response = client.post(
                "/sessions/session-1/ask",
                headers={"X-Request-ID": "client-request-1"},
                json={"question": "What is the result?"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "client-request-1")
        mock_ask_pdf_agent.assert_called_once_with(
            session,
            "What is the result?",
            "client-request-1",
        )


class LLMClientUsageTests(unittest.TestCase):
    @patch("utils.llm_client.get_deepseek_client")
    def test_llm_client_records_provider_usage(self, mock_get_client):
        response = SimpleNamespace(
            model="deepseek-flash",
            choices=[SimpleNamespace(message=SimpleNamespace(content="Answer"))],
            usage=SimpleNamespace(
                prompt_tokens=20,
                completion_tokens=5,
                total_tokens=25,
                prompt_cache_hit_tokens=4,
                prompt_cache_miss_tokens=16,
            ),
        )
        client = Mock()
        client.chat.completions.create.return_value = response
        mock_get_client.return_value = client
        tracker = new_usage_tracker()

        with observability_context(usage_tracker=tracker):
            answer = chat_with_deepseek("Prompt", operation="qa")

        self.assertEqual(answer, "Answer")
        self.assertEqual(tracker.summary()["total_tokens"], 25)
        self.assertIn("qa", tracker.summary()["by_operation"])

    @patch("app.services.agent_service.save_session")
    @patch("utils.llm_client.get_deepseek_client")
    def test_workflow_aggregates_usage_from_specialist_thread(
        self,
        mock_get_client,
        _mock_save_session,
    ):
        response = SimpleNamespace(
            model="deepseek-flash",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Grounded [paper.pdf, page 1]."
                    )
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=40,
                completion_tokens=10,
                total_tokens=50,
                prompt_cache_hit_tokens=8,
                prompt_cache_miss_tokens=32,
            ),
        )
        client = Mock()
        client.chat.completions.create.return_value = response
        mock_get_client.return_value = client
        document = SimpleNamespace(
            metadata={"source": "paper.pdf", "page": 0},
            page_content="Grounded evidence.",
        )
        vectorstore = Mock()
        vectorstore.similarity_search.return_value = [document]
        session = {
            "session_id": "usage-session",
            "vectorstore": vectorstore,
            "loaded_pdfs": ["paper.pdf"],
            "messages": [],
            "vectorstore_path": "unused",
            "document_count": 1,
        }

        events = list(
            iter_pdf_agent_events(
                session,
                "What is the result?",
                "request-usage",
            )
        )
        usage = events[-1]["data"]["usage"]

        self.assertEqual(usage["llm_calls"], 1)
        self.assertEqual(usage["total_tokens"], 50)
        self.assertEqual(usage["by_operation"]["qa"]["llm_calls"], 1)


if __name__ == "__main__":
    unittest.main()
