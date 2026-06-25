from langgraph.graph import StateGraph, END

from agent.state import AgentState
from agent.llm_planner import plan_steps_with_llm

from agent.qa_agent import qa_agent
from agent.source_agent import source_agent
from agent.summary_agent import summary_agent
from agent.keyword_agent import keyword_agent
from agent.compare_agent import compare_agent
from agent.reviewer_agent import reviewer_agent


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
        "results": []
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

    # Copy state values to avoid modifying
    # the original lists directly
    answers = list(state.get("answers", []))
    results = list(state.get("results", []))

    if step == "qa":

        output = qa_agent(
            question,
            vectorstore,
            chat_history
        )

    elif step == "source":

        output = source_agent(
            vectorstore,
            chat_history
        )

    elif step == "summary":

        output = summary_agent(
            vectorstore,
            chat_history
        )

    elif step == "keyword":

        output = keyword_agent(
            vectorstore,
            chat_history
        )

    elif step == "compare":

        output = compare_agent(
            vectorstore,
            chat_history
        )

    else:

        output = {
            "agent": "Unknown Agent",
            "status": "failed",
            "answer": f"Unknown step: {step}",
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
    Decide whether to continue executing specialist agents
    or move to the Reviewer Agent.
    """

    if state["current_step"] == "final":
        return "review"

    return "continue"


def review_node(state: AgentState):
    """
    Reviewer Agent node.

    Responsibilities:
    - Review all specialist agent outputs.
    - Synthesize a final answer.
    """

    question = state["question"]
    steps = state.get("steps", [])
    answers = state.get("answers", [])

    if answers:

        output = reviewer_agent(
            question,
            steps,
            answers
        )

        final_answer = output["answer"]

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

    # Set graph entry point
    graph.set_entry_point("planner_agent")

    # Define workflow edges
    graph.add_edge("planner_agent", "specialist_agent")
    graph.add_edge("specialist_agent", "workflow_controller")

    # Conditional edge:
    # Continue executing agents or move to reviewer
    graph.add_conditional_edges(
        "workflow_controller",
        should_continue,
        {
            "continue": "specialist_agent",
            "review": "reviewer_agent"
        }
    )

    # End after reviewer agent
    graph.add_edge("reviewer_agent", END)

    return graph.compile()