import io
import json
import logging
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from agent.collaboration_agent import collaboration_agent
from app.api.routes import router
from tests.session_access_fixtures import AUTH_HEADERS, HTTP_SESSION_ID, accept_test_owner
from utils.llm_client import LLMClientError, chat_with_deepseek
from utils.observability import (
    JsonFormatter,
    RequestContextMiddleware,
    new_usage_tracker,
    observability_context,
)


# Synthetic values occur only in exceptions, never in the requested PDF answer.
PRIVATE_VALUES = (
    "test-only-secret-key-DO-NOT-USE",
    "private-document-body-marker",
    "C:\\private-workspace\\confidential.pdf",
    "/private-storage/sessions.db",
)
PRIVATE_ERROR = " | ".join(PRIVATE_VALUES)
PROVIDER_USAGE = {
    "prompt_tokens": 40,
    "completion_tokens": 10,
    "total_tokens": 50,
    "prompt_cache_hit_tokens": 8,
    "prompt_cache_miss_tokens": 32,
}


@contextmanager
def capture_json_logs():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
        handler.close()


def make_session(vectorstore):
    return {
        "session_id": "privacy-test-session",
        "vectorstore": vectorstore,
        "loaded_pdfs": ["paper.pdf"],
        "messages": [],
        "vectorstore_path": "unused",
        "document_count": 1,
    }


def make_app():
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(RequestContextMiddleware)
    return app


def decode_result(response, streaming):
    if not streaming:
        return response.json()
    events = []
    for block in response.text.strip().split("\n\n"):
        event_line, data_line = block.split("\n", 1)
        events.append((event_line.removeprefix("event: "),
                       json.loads(data_line.removeprefix("data: "))))
    assert events[0][0] == "progress"
    assert events[-1][0] == "result"
    assert {kind for kind, _ in events} <= {"progress", "result"}
    return events[-1][1]


class ErrorPrivacyTests(unittest.TestCase):
    def assert_private_values_absent(self, value):
        # Compare decoded objects as well as wire text to catch JSON escapes.
        rendered = str(value)
        for marker in PRIVATE_VALUES:
            self.assertNotIn(marker, rendered)
        self.assertNotIn("confidential.pdf", rendered)
        self.assertNotIn("private-storage", rendered)

    def test_llm_failure_keeps_usage_and_cause_without_public_provider_body(self):
        error = TimeoutError(PRIVATE_ERROR)
        error.usage = dict(PROVIDER_USAGE)
        client = Mock()
        client.chat.completions.create.side_effect = error
        tracker = new_usage_tracker()
        with patch("utils.llm_client.get_deepseek_client", return_value=client), \
                observability_context("privacy-request", usage_tracker=tracker):
            with self.assertRaises(LLMClientError) as caught:
                chat_with_deepseek("Safe question", model="deepseek-flash", operation="qa")
        self.assert_private_values_absent(str(caught.exception))
        self.assertIs(caught.exception.__cause__, error)
        usage = tracker.summary()
        self.assertEqual(usage["llm_calls"], 1)
        self.assertEqual(usage["total_tokens"], 50)
        self.assertEqual(usage["cache_hit_tokens"], 8)
        self.assertEqual(usage["cache_miss_tokens"], 32)

    def test_exception_logs_keep_cause_and_location_without_messages_or_source(self):
        try:
            try:
                raise ValueError(PRIVATE_ERROR)
            except ValueError as error:
                raise RuntimeError("outer-private-message") from error
        except RuntimeError:
            record = logging.LogRecord("app.test", logging.ERROR, __file__, 1,
                                       "operation_failed", (), sys.exc_info())
        with observability_context("privacy-request"):
            payload = json.loads(JsonFormatter().format(record))
        self.assert_private_values_absent(payload)
        self.assertNotIn("outer-private-message", str(payload))
        self.assertNotIn(__file__, str(payload))
        self.assertNotIn("raise RuntimeError", str(payload))
        self.assertEqual(payload["request_id"], "privacy-request")
        self.assertEqual(payload["event"], "operation_failed")
        self.assertEqual(payload["exception"]["type"], "RuntimeError")
        trace = payload["exception"]["stacktrace"]
        self.assertIn("ValueError", trace)
        self.assertIn("RuntimeError", trace)
        self.assertIn("test_exception_logs_keep_cause_and_location", trace)
        self.assertRegex(trace, r":\d+")

    def test_specialist_errors_are_safe_in_json_sse_history_and_logs(self):
        for failure in ("retrieval", "provider"):
            for streaming in (False, True):
                with self.subTest(failure=failure, streaming=streaming):
                    vectorstore = Mock()
                    vectorstore.similarity_search.return_value = [
                        Document(page_content="Safe evidence.",
                                 metadata={"source": "paper.pdf", "page": 0})
                    ]
                    error = TimeoutError(PRIVATE_ERROR)
                    error.usage = dict(PROVIDER_USAGE)
                    client = Mock()
                    client.chat.completions.create.side_effect = error
                    if failure == "retrieval":
                        vectorstore.similarity_search.side_effect = OSError(PRIVATE_ERROR)
                    session = make_session(vectorstore)
                    with patch("app.api.routes.get_session", return_value=session), \
                            patch("app.services.agent_service.save_session"), \
                            patch("utils.llm_client.get_deepseek_client", return_value=client), \
                            capture_json_logs() as logs, accept_test_owner(), TestClient(make_app(), headers=AUTH_HEADERS) as http:
                        response = http.post(
                            f"/sessions/{HTTP_SESSION_ID}/ask" + ("/stream" if streaming else ""),
                            headers={"X-Request-ID": "privacy-request"},
                            json={"question": "What is the conclusion?"},
                        )
                    self.assertEqual(response.status_code, 200)
                    result = decode_result(response, streaming)
                    self.assert_private_values_absent(result)
                    self.assert_private_values_absent(response.text)
                    self.assert_private_values_absent(session["messages"])
                    self.assert_private_values_absent(logs.getvalue())
                    self.assertEqual(response.headers["X-Request-ID"], "privacy-request")
                    self.assertEqual(result["steps"], ["qa"])
                    self.assertIn("unavailable" if failure == "provider" else "failed",
                                  result["answer"].lower())
                    self.assertEqual(session["messages"][-1]["content"], result["answer"])
                    self.assertEqual(result["usage"]["llm_calls"], int(failure == "provider"))
                    self.assertEqual(result["usage"]["total_tokens"], 50 if failure == "provider" else 0)
                    diagnostics = [json.loads(line) for line in logs.getvalue().splitlines()]
                    event = "llm_call_failed" if failure == "provider" else "specialist_failed"
                    failed = [entry for entry in diagnostics if entry["event"] == event]
                    self.assertEqual(len(failed), 1)
                    self.assertEqual(failed[0]["request_id"], "privacy-request")
                    self.assertEqual(failed[0]["operation" if failure == "provider" else "step"], "qa")

    def test_collaboration_failure_does_not_copy_exception_into_recommendations(self):
        with patch("agent.collaboration_agent.chat_with_deepseek",
                   side_effect=LLMClientError(PRIVATE_ERROR)):
            result = collaboration_agent("Compare.", ["qa", "source"],
                                         ["Useful answer.", "Useful citation."])
        self.assert_private_values_absent(result)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["needs_revision"])
        self.assertEqual(result["answer"], "Useful answer.\n\nUseful citation.")
        self.assertTrue(result["recommendations"])

    def test_workflow_failure_keeps_protocol_without_exception_in_result_or_history(self):
        graph = Mock()
        graph.stream.side_effect = ValueError(PRIVATE_ERROR)
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                session = make_session(object())
                with patch("app.api.routes.get_session", return_value=session), \
                        patch("app.services.agent_service.get_pdf_agent_graph", return_value=graph), \
                        patch("app.services.agent_service.save_session"), \
                        capture_json_logs() as logs, accept_test_owner(), TestClient(make_app(), headers=AUTH_HEADERS) as http:
                    response = http.post(
                        f"/sessions/{HTTP_SESSION_ID}/ask" + ("/stream" if streaming else ""),
                        headers={"X-Request-ID": "privacy-request"},
                        json={"question": "What is the conclusion?"},
                    )
                self.assertEqual(response.status_code, 200)
                result = decode_result(response, streaming)
                self.assert_private_values_absent(result)
                self.assert_private_values_absent(response.text)
                self.assert_private_values_absent(session["messages"])
                self.assert_private_values_absent(logs.getvalue())
                self.assertTrue(result["answer"])
                self.assertEqual(result["usage"]["llm_calls"], 0)
                diagnostics = [json.loads(line) for line in logs.getvalue().splitlines()]
                failed = next(entry for entry in diagnostics if entry["event"] == "agent_workflow_failed")
                self.assertEqual(failed["error_type"], "ValueError")
                self.assertEqual(failed["request_id"], "privacy-request")

    def test_upload_parser_and_storage_failures_do_not_leak_exception_details(self):
        for failure in ("parser", "storage"):
            with self.subTest(failure=failure):
                session = make_session(None)
                with patch("app.api.routes.get_session", return_value=session) as get_session, \
                        patch("app.services.pdf_service.parse_pdf_documents",
                              side_effect=ValueError(PRIVATE_ERROR)), \
                        capture_json_logs() as logs, \
                        accept_test_owner(), TestClient(make_app(), headers=AUTH_HEADERS, raise_server_exceptions=False) as http:
                    if failure == "storage":
                        get_session.side_effect = OSError(PRIVATE_ERROR)
                    response = http.post(
                        f"/sessions/{HTTP_SESSION_ID}/pdfs",
                        files={"files": ("sample.pdf", b"test parser input", "application/pdf")},
                        headers={"X-Request-ID": "privacy-request"},
                    )
                self.assertEqual(response.status_code, 500)
                self.assert_private_values_absent(response.text)
                self.assert_private_values_absent(logs.getvalue())
                diagnostics = [json.loads(line) for line in logs.getvalue().splitlines()]
                failed = next(entry for entry in diagnostics if entry["event"] == "http_request_failed")
                self.assertEqual(failed["request_id"], "privacy-request")
                self.assertEqual(failed["exception"]["type"], "ValueError" if failure == "parser" else "OSError")


if __name__ == "__main__":
    unittest.main()
