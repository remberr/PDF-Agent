import unittest
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent.graph_agent import next_step_node, review_node, specialist_agent_node
from agent.llm_planner import plan_steps_with_llm
from agent.source_agent import source_agent
from agent.state import empty_collaboration_notes
from app.services.agent_service import iter_pdf_agent_events


class PlannerFastPathTests(unittest.TestCase):
    @patch("agent.llm_planner.chat_with_deepseek")
    def test_explicit_multi_agent_intent_skips_llm(self, mock_chat):
        steps = plan_steps_with_llm(
            "Compare these PDFs and cite the sources."
        )

        self.assertEqual(steps, ["compare", "source"])
        mock_chat.assert_not_called()

    @patch("agent.llm_planner.chat_with_deepseek")
    def test_direct_question_skips_llm(self, mock_chat):
        steps = plan_steps_with_llm(
            "What conclusion does the paper reach?"
        )

        self.assertEqual(steps, ["qa"])
        mock_chat.assert_not_called()

    @patch("agent.llm_planner.chat_with_deepseek")
    def test_source_keyword_does_not_match_resources(self, mock_chat):
        steps = plan_steps_with_llm(
            "What resources does the paper describe?"
        )

        self.assertEqual(steps, ["qa"])
        mock_chat.assert_not_called()

    @patch("agent.llm_planner.chat_with_deepseek")
    def test_chinese_summary_and_source_intent_skips_llm(self, mock_chat):
        steps = plan_steps_with_llm("请总结文档并给出引用来源。")

        self.assertEqual(steps, ["summary", "source"])
        mock_chat.assert_not_called()

    @patch(
        "agent.llm_planner.chat_with_deepseek",
        return_value='["summary"]'
    )
    def test_ambiguous_request_uses_llm(self, mock_chat):
        steps = plan_steps_with_llm("Analyze this document.")

        self.assertEqual(steps, ["summary"])
        mock_chat.assert_called_once()


class SourceAgentFastPathTests(unittest.TestCase):
    def test_source_agent_formats_retrieved_documents(self):
        document = SimpleNamespace(
            metadata={"source": "paper.pdf", "page": 2},
            page_content="A concise piece of supporting evidence."
        )
        vectorstore = Mock()
        vectorstore.similarity_search.return_value = [document]

        output = source_agent(
            "Show the source.",
            vectorstore,
            [],
            ["paper.pdf"]
        )

        self.assertEqual(output["status"], "success")
        self.assertIn("[paper.pdf, page 3]", output["answer"])
        self.assertEqual(
            document.metadata["citation_id"],
            "paper.pdf, page 3"
        )


class ParallelSpecialistTests(unittest.TestCase):
    @patch("agent.graph_agent._execute_specialist_step")
    def test_pending_specialists_execute_concurrently_in_step_order(
        self,
        mock_execute
    ):
        barrier = Barrier(2)

        def execute(step, *_args):
            barrier.wait(timeout=2)
            return {
                "agent": f"{step.title()} Agent",
                "status": "success",
                "answer": f"{step} answer",
                "results": []
            }

        mock_execute.side_effect = execute
        state = {
            "question": "Summarize and extract keywords.",
            "steps": ["summary", "keyword"],
            "current_step": "summary",
            "completed_steps": [],
            "answers": [],
            "results": [],
            "timings": {},
            "vectorstore": object(),
            "chat_history": [],
            "loaded_pdfs": ["paper.pdf"]
        }

        output = specialist_agent_node(state)

        self.assertEqual(output["completed_steps"], ["summary", "keyword"])
        self.assertTrue(output["answers"][0].endswith("summary answer"))
        self.assertTrue(output["answers"][1].endswith("keyword answer"))
        self.assertIn("summary", output["timings"])
        self.assertIn("keyword", output["timings"])

        controller_output = next_step_node({
            **state,
            **output
        })
        self.assertEqual(controller_output["current_step"], "final")


class ReviewerFastPathTests(unittest.TestCase):
    @patch("agent.graph_agent.reviewer_agent")
    def test_single_specialist_skips_reviewer_llm(self, mock_reviewer):
        state = {
            "question": "What is the conclusion?",
            "steps": ["qa"],
            "answers": ["## QA Agent\nThe conclusion is supported."],
            "collaboration_notes": empty_collaboration_notes()
        }

        output = review_node(state)

        self.assertEqual(output["answer"], "The conclusion is supported.")
        mock_reviewer.assert_not_called()

    @patch("agent.graph_agent.reviewer_agent")
    def test_multi_agent_path_keeps_reviewer_llm(self, mock_reviewer):
        mock_reviewer.return_value = {"answer": "Combined answer."}
        state = {
            "question": "Compare and cite sources.",
            "steps": ["compare", "source"],
            "answers": [
                "## Compare Agent\nComparison.",
                "## Source Agent\nSources."
            ],
            "collaboration_notes": empty_collaboration_notes()
        }

        output = review_node(state)

        self.assertEqual(output["answer"], "Combined answer.")
        mock_reviewer.assert_called_once()


class StreamingWorkflowTests(unittest.TestCase):
    @patch("app.services.agent_service.save_session")
    @patch("app.services.agent_service.get_pdf_agent_graph")
    def test_stream_emits_progress_result_and_timings(
        self,
        mock_get_graph,
        mock_save_session
    ):
        class FakeGraph:
            def stream(self, _state, stream_mode):
                self.stream_mode = stream_mode
                yield {
                    "planner_agent": {
                        "steps": ["qa"],
                        "current_step": "qa"
                    }
                }
                yield {
                    "specialist_agent": {
                        "answers": ["## QA Agent\nGrounded answer."],
                        "results": [],
                        "completed_steps": ["qa"],
                        "current_step": "qa",
                        "timings": {"qa": 4.2}
                    }
                }
                yield {
                    "workflow_controller": {
                        "current_step": "final"
                    }
                }
                yield {
                    "reviewer_agent": {
                        "answer": "Grounded answer."
                    }
                }

        mock_get_graph.return_value = FakeGraph()
        session = {
            "session_id": "test-session",
            "vectorstore": object(),
            "loaded_pdfs": ["paper.pdf"],
            "messages": [],
            "vectorstore_path": "unused",
            "document_count": 1
        }

        events = list(iter_pdf_agent_events(session, "What is the answer?"))

        self.assertEqual(events[0]["type"], "progress")
        self.assertEqual(events[0]["data"]["node"], "planner")
        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["data"]["answer"], "Grounded answer.")
        self.assertIn("planner", events[-1]["data"]["timings"])
        self.assertIn("qa", events[-1]["data"]["timings"])
        self.assertIn("total", events[-1]["data"]["timings"])
        self.assertEqual(len(session["messages"]), 2)
        mock_save_session.assert_called_once_with(session)


if __name__ == "__main__":
    unittest.main()
