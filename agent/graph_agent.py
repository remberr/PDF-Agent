from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter

from langgraph.graph import StateGraph, END

from agent.state import AgentState, empty_collaboration_notes
from agent.llm_planner import plan_steps_with_llm

from agent.qa_agent import qa_agent
from agent.source_agent import source_agent
from agent.summary_agent import summary_agent
from agent.keyword_agent import keyword_agent
from agent.compare_agent import compare_agent
from agent.reviewer_agent import reviewer_agent
from agent.collaboration_agent import collaboration_agent


MAX_REVISION_COUNT = 1


def planner_node(state: AgentState):
    """
    Planner Agent node.

    Responsibilities:
    - Analyze the user's question.
    - Decide which specialist agents should be executed.
    """

    # Plan one or more agent steps
    steps = plan_steps_with_llm(state["question"])

    return {
        "steps": steps,
        "current_step": steps[0],
        "completed_steps": [],
        "answers": [],
        "answer": "",
        "results": [],
        "collaboration_notes": empty_collaboration_notes(),
        "revision_count": 0,
        "timings": {}
    }


def collaboration_node(state: AgentState):
    """
    Collaboration Agent node.

    Responsibilities:
    - Coordinate outputs from all completed specialist agents.
    - Identify contradictions, gaps, and overlapping findings.
    - Store collaboration notes and lightweight revision decisions.
    """

    question = state["question"]
    steps = state.get("steps", [])
    answers = state.get("answers", [])

    output = collaboration_agent(
        question,
        steps,
        answers
    )

    return {
        "collaboration_notes": output
    }


def revision_controller_node(state: AgentState):
    """
    Revision Controller node.

    Responsibilities:
    - Read Collaboration Agent revision decisions.
    - Add missing specialist steps when revision is useful.
    - Limit retries to avoid infinite workflow loops.
    """

    steps = list(state.get("steps", []))
    revision_count = state.get("revision_count", 0)
    collaboration_notes = state.get(
        "collaboration_notes",
        empty_collaboration_notes()
    )

    needs_revision = collaboration_notes.get("needs_revision", False)
    next_steps = collaboration_notes.get("next_steps", [])

    next_steps = [
        step for step in next_steps
        if step not in steps
    ]

    if (
        needs_revision
        and next_steps
        and revision_count < MAX_REVISION_COUNT
    ):
        steps.extend(next_steps)

        return {
            "steps": steps,
            "current_step": next_steps[0],
            "revision_count": revision_count + 1
        }

    return {
        "current_step": "final"
    }


def _execute_specialist_step(
    step,
    question,
    vectorstore,
    chat_history,
    loaded_pdfs
):
    """
    Execute one specialist and normalize failures into agent output.
    """

    try:
        if step == "qa":
            return qa_agent(
                question,
                vectorstore,
                chat_history,
                loaded_pdfs
            )

        if step == "source":
            return source_agent(
                question,
                vectorstore,
                chat_history,
                loaded_pdfs
            )

        if step == "summary":
            return summary_agent(
                vectorstore,
                chat_history,
                loaded_pdfs
            )

        if step == "keyword":
            return keyword_agent(
                vectorstore,
                chat_history,
                loaded_pdfs
            )

        if step == "compare":
            return compare_agent(
                vectorstore,
                chat_history,
                loaded_pdfs
            )

        return {
            "agent": "Unknown Agent",
            "status": "failed",
            "answer": f"Unknown step: {step}",
            "results": []
        }

    except Exception as exc:
        return {
            "agent": f"{step.title()} Agent",
            "status": "failed",
            "answer": f"This step failed and was skipped: {exc}",
            "results": []
        }


def _execute_timed_specialist(
    step,
    question,
    vectorstore,
    chat_history,
    loaded_pdfs
):
    started_at = perf_counter()
    output = _execute_specialist_step(
        step,
        question,
        vectorstore,
        chat_history,
        loaded_pdfs
    )
    elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
    return output, elapsed_ms


def specialist_agent_node(state: AgentState):
    """
    Specialist Agent node.

    Responsibilities:
    - Execute all pending independent specialists in parallel.
    - Collect answers and retrieved documents in planned step order.
    - Execute only newly added steps during a revision pass.
    """

    question = state["question"]
    vectorstore = state["vectorstore"]
    chat_history = state["chat_history"]
    loaded_pdfs = state.get("loaded_pdfs", [])
    steps = state.get("steps", [])
    completed_steps = list(state.get("completed_steps", []))
    pending_steps = [
        step for step in steps
        if step not in completed_steps
    ]

    answers = list(state.get("answers", []))
    results = list(state.get("results", []))
    timings = dict(state.get("timings", {}))

    if not pending_steps:
        return {
            "current_step": "final"
        }

    outputs = {}
    max_workers = min(len(pending_steps), 5)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _execute_timed_specialist,
                step,
                question,
                vectorstore,
                chat_history,
                loaded_pdfs
            ): step
            for step in pending_steps
        }

        for future in as_completed(futures):
            step = futures[future]
            output, elapsed_ms = future.result()
            outputs[step] = output
            timings[step] = elapsed_ms

    for step in pending_steps:
        output = outputs[step]
        answers.append(
            f"## {output['agent']}\n{output['answer']}"
        )
        results.extend(output.get("results", []))

    completed_steps.extend(pending_steps)

    return {
        "answers": answers,
        "results": results,
        "completed_steps": completed_steps,
        "timings": timings,
        "current_step": pending_steps[-1]
    }


def next_step_node(state: AgentState):
    """
    Workflow Controller node.

    Responsibilities:
    - Move to the next planned agent step.
    - Mark the workflow as complete when no steps remain.
    """

    steps = state["steps"]
    completed_steps = state.get("completed_steps", [])
    pending_steps = [
        step for step in steps
        if step not in completed_steps
    ]

    if pending_steps:
        return {
            "current_step": pending_steps[0]
        }

    return {
        "current_step": "final"
    }


def should_continue(state: AgentState):
    """
    Determine whether to continue executing specialist agents
    or move to review/collaboration after all specialist agents finish.
    """

    if state["current_step"] != "final":
        return "continue"

    answers = state.get("answers", [])

    if len(answers) > 1:
        return "collaboration"

    return "review"


def should_revise(state: AgentState):
    """
    Determine whether the revision controller added new specialist work.
    """

    if state["current_step"] == "final":
        return "review"

    return "continue"


def review_node(state: AgentState):
    """
    Reviewer Agent node.

    Responsibilities:
    - Review specialist outputs and collaboration notes.
    - Synthesize a final answer.
    """

    question = state["question"]
    steps = state.get("steps", [])
    answers = state.get("answers", [])
    collaboration_notes = state.get(
        "collaboration_notes",
        empty_collaboration_notes()
    )

    if answers:

        collaboration_answer = collaboration_notes.get("answer", "")

        # A single specialist already produced a complete answer. Keep the
        # Reviewer node in the trace, but avoid a redundant LLM rewrite.
        if len(answers) == 1 and not collaboration_answer:
            specialist_answer = answers[0]

            if specialist_answer.startswith("## "):
                _, separator, content = specialist_answer.partition("\n")
                if separator and content:
                    specialist_answer = content

            return {
                "answer": specialist_answer
            }

        reviewer_step = list(steps)
        reviewer_answers = list(answers)

        if collaboration_answer:
            reviewer_step.append("collaboration")
            reviewer_answers.append(
                f"## Collaboration Analysis\n{collaboration_answer}"
            )

        try:
            output = reviewer_agent(
                question,
                reviewer_step,
                reviewer_answers
            )

            final_answer = output["answer"]

        except Exception:
            final_answer = "\n\n".join(reviewer_answers)

    else:

        final_answer = "No answer was generated."

    return {
        "answer": final_answer
    }


def build_pdf_agent_graph():
    """
    Build and compile the LangGraph Multi-Agent PDF system.
    """

    graph = StateGraph(AgentState)

    # Add graph nodes
    graph.add_node("planner_agent", planner_node)
    graph.add_node("specialist_agent", specialist_agent_node)
    graph.add_node("workflow_controller", next_step_node)
    graph.add_node("reviewer_agent", review_node)
    graph.add_node("collaboration_agent", collaboration_node)
    graph.add_node("revision_controller", revision_controller_node)

    # Set graph entry point
    graph.set_entry_point("planner_agent")

    # Define workflow edges
    graph.add_edge("planner_agent", "specialist_agent")
    graph.add_edge("specialist_agent", "workflow_controller")

    # Conditional edge:
    # Continue specialists, collaborate for multi-agent outputs,
    # or review directly for single-agent outputs.
    graph.add_conditional_edges(
        "workflow_controller",
        should_continue,
        {
            "continue": "specialist_agent",
            "collaboration": "collaboration_agent",
            "review": "reviewer_agent"
        }
    )

    # Decide whether collaboration requires a lightweight revision
    graph.add_edge("collaboration_agent", "revision_controller")

    # Conditional edge:
    # Retry a missing specialist step or continue to final review.
    graph.add_conditional_edges(
        "revision_controller",
        should_revise,
        {
            "continue": "specialist_agent",
            "review": "reviewer_agent"
        }
    )

    # End after reviewer agent
    graph.add_edge("reviewer_agent", END)

    return graph.compile()
