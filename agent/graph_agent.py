from langgraph.graph import StateGraph, END

from agent.state import AgentState
from agent.chain_agent import plan_steps

from tools.pdf_qa_tool import pdf_qa_tool
from tools.source_tool import source_tool
from tools.pdf_summary_tool import pdf_summary_tool
from tools.keyword_tool import keyword_tool
from tools.compare_tool import compare_tool


def router_node(state: AgentState):
    """
    Plan one or more tool steps based on the user's question.
    """

    steps = plan_steps(state["question"])

    return {
        "steps": steps,
        "current_step": steps[0],
        "answers": [],
        "answer": "",
        "results": []
    }


def tool_node(state: AgentState):
    """
    Execute the current tool step.
    """

    step = state["current_step"]
    question = state["question"]
    vectorstore = state["vectorstore"]
    chat_history = state["chat_history"]

    # Do not modify the original state list directly
    answers = list(state.get("answers", []))
    results = list(state.get("results", []))

    if step == "qa":
        answer, docs = pdf_qa_tool(
            question,
            vectorstore,
            chat_history
        )

        answers.append(answer)
        results.extend(docs)

    elif step == "source":
        docs = source_tool(
            question,
            vectorstore
        )

        answers.append(
            "I found the following relevant sources in the PDFs."
        )

        results.extend(docs)

    elif step == "summary":
        answer, docs = pdf_summary_tool(
            vectorstore,
            chat_history
        )

        answers.append(
            "## Summary\n" + answer
        )

        results.extend(docs)

    elif step == "keyword":
        answer, docs = keyword_tool(
            vectorstore,
            chat_history
        )

        answers.append(
            "## Keywords\n" + answer
        )

        results.extend(docs)

    elif step == "compare":
        answer, docs = compare_tool(
            vectorstore,
            chat_history
        )

        answers.append(
            "## Comparison\n" + answer
        )

        results.extend(docs)

    return {
        "answers": answers,
        "results": results
    }


def next_step_node(state: AgentState):
    """
    Move to the next planned step.
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
    Decide whether the graph should continue or finish.
    """

    if state["current_step"] == "final":
        return "end"

    return "continue"


def final_node(state: AgentState):
    """
    Combine all tool outputs into the final answer.
    """

    answers = state.get("answers", [])

    if answers:
        final_answer = "\n\n".join(answers)
    else:
        final_answer = "No answer was generated."

    return {
        "answer": final_answer
    }


def build_pdf_agent_graph():
    """
    Build and compile the LangGraph PDF Agent.
    """

    graph = StateGraph(AgentState)

    graph.add_node("router", router_node)
    graph.add_node("tool", tool_node)
    graph.add_node("next_step", next_step_node)
    graph.add_node("final", final_node)

    graph.set_entry_point("router")

    graph.add_edge("router", "tool")
    graph.add_edge("tool", "next_step")

    graph.add_conditional_edges(
        "next_step",
        should_continue,
        {
            "continue": "tool",
            "end": "final"
        }
    )

    graph.add_edge("final", END)

    return graph.compile()