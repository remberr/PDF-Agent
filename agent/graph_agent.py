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
        "answers": [],
        "answer": "",
        "results": [],
        "collaboration_notes": empty_collaboration_notes(),
        "revision_count": 0
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


def specialist_agent_node(state: AgentState):
    """
    Specialist Agent node.

    Responsibilities:
    - Execute the current specialist agent.
    - Collect the agent's answer and retrieved documents.
    """

    step = state["current_step"]
    question = state["question"]
    vectorstore = state["vectorstore"]
    chat_history = state["chat_history"]
    loaded_pdfs = state.get("loaded_pdfs", [])

    # Copy state values to avoid modifying
    # the original lists directly
    answers = list(state.get("answers", []))
    results = list(state.get("results", []))

    try:
        if step == "qa":

            output = qa_agent(
                question,
                vectorstore,
                chat_history,
                loaded_pdfs
            )

        elif step == "source":

            output = source_agent(
                question,
                vectorstore,
                chat_history,
                loaded_pdfs
            )

        elif step == "summary":

            output = summary_agent(
                vectorstore,
                chat_history,
                loaded_pdfs
            )

        elif step == "keyword":

            output = keyword_agent(
                vectorstore,
                chat_history,
                loaded_pdfs
            )

        elif step == "compare":

            output = compare_agent(
                vectorstore,
                chat_history,
                loaded_pdfs
            )

        else:

            output = {
                "agent": "Unknown Agent",
                "status": "failed",
                "answer": f"Unknown step: {step}",
                "results": []
            }

    except Exception as exc:
        output = {
            "agent": f"{step.title()} Agent",
            "status": "failed",
            "answer": f"This step failed and was skipped: {exc}",
            "results": []
        }

    # Save specialist agent answer
    answers.append(
        f"## {output['agent']}\n{output['answer']}"
    )

    # Save retrieved documents
    results.extend(output.get("results", []))

    return {
        "answers": answers,
        "results": results
    }


def next_step_node(state: AgentState):
    """
    Workflow Controller node.

    Responsibilities:
    - Move to the next planned agent step.
    - Mark the workflow as complete when no steps remain.
    """

    steps = state["steps"]
    current_step = state["current_step"]

    current_index = steps.index(current_step)
    next_index = current_index + 1

    if next_index < len(steps):

        return {
            "current_step": steps[next_index]
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

        reviewer_step = list(steps)
        reviewer_answers = list(answers)

        collaboration_answer = collaboration_notes.get("answer", "")

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
