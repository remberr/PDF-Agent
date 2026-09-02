import json
from functools import lru_cache
from time import perf_counter

from agent.graph_agent import build_pdf_agent_graph
from agent.state import create_initial_agent_state, empty_collaboration_notes
from app.services.session_store import save_session


NODE_NAMES = {
    "planner_agent": "planner",
    "specialist_agent": "specialists",
    "workflow_controller": "controller",
    "collaboration_agent": "collaboration",
    "revision_controller": "revision",
    "reviewer_agent": "reviewer"
}


@lru_cache(maxsize=1)
def get_pdf_agent_graph():
    """
    Compile the stateless LangGraph workflow once per API process.
    """

    return build_pdf_agent_graph()


def serialize_sources(results):
    """
    Convert LangChain document sources into API response dictionaries.
    """

    sources = []
    seen_sources = set()

    for doc in results:
        source = doc.metadata.get("source", "Unknown Source")
        page = doc.metadata.get("page", 0) + 1
        citation_id = doc.metadata.get(
            "citation_id",
            f"{source}, page {page}"
        )
        source_key = (citation_id, source, page)

        if source_key in seen_sources:
            continue

        seen_sources.add(source_key)

        sources.append(
            {
                "citation_id": citation_id,
                "source": source,
                "page": page,
                "excerpt": doc.page_content[:800]
            }
        )

    return sources


def _merge_state_update(state, update):
    if not isinstance(update, dict):
        return

    update = dict(update)
    updated_timings = update.pop("timings", None)
    state.update(update)

    if updated_timings:
        timings = dict(state.get("timings", {}))
        timings.update(updated_timings)
        state["timings"] = timings


def _next_node(node_name, state):
    if node_name == "planner_agent":
        return "specialists"

    if node_name == "specialist_agent":
        return "controller"

    if node_name == "workflow_controller":
        if state.get("current_step") != "final":
            return "specialists"
        if len(state.get("answers", [])) > 1:
            return "collaboration"
        return "reviewer"

    if node_name == "collaboration_agent":
        return "revision"

    if node_name == "revision_controller":
        if state.get("current_step") != "final":
            return "specialists"
        return "reviewer"

    return None


def _progress_event(
    node,
    status,
    state,
    completed_nodes,
    elapsed_ms=None
):
    data = {
        "node": node,
        "status": status,
        "completed_nodes": list(completed_nodes),
        "steps": list(state.get("steps", [])),
        "revision_count": state.get("revision_count", 0),
        "timings": dict(state.get("timings", {}))
    }

    if elapsed_ms is not None:
        data["elapsed_ms"] = elapsed_ms

    return {
        "type": "progress",
        "data": data
    }


def _build_result(state):
    answer = state.get("answer", "")
    answers = state.get("answers", [])

    if not answer and answers:
        answer = "\n\n".join(answers)

    return {
        "answer": answer,
        "steps": state.get("steps", []),
        "sources": serialize_sources(state.get("results", [])),
        "collaboration_notes": state.get(
            "collaboration_notes",
            empty_collaboration_notes()
        ),
        "revision_count": state.get("revision_count", 0),
        "timings": state.get("timings", {})
    }


def _save_result(session, result):
    session["messages"].append(
        {
            "role": "assistant",
            "content": result["answer"],
            "steps": result["steps"],
            "collaboration_notes": result["collaboration_notes"],
            "revision_count": result["revision_count"],
            "sources": result["sources"],
            "timings": result["timings"]
        }
    )
    save_session(session)


def iter_pdf_agent_events(session, question):
    """
    Run the LangGraph workflow and yield progress plus the final result.
    """

    pdf_agent_graph = get_pdf_agent_graph()
    workflow_started_at = perf_counter()

    session["messages"].append(
        {
            "role": "user",
            "content": question
        }
    )

    state = create_initial_agent_state(
        question,
        session["vectorstore"],
        session["messages"],
        session["loaded_pdfs"]
    )
    completed_nodes = []
    active_node = "planner"

    yield _progress_event(
        active_node,
        "running",
        state,
        completed_nodes
    )
    node_started_at = perf_counter()

    try:
        for chunk in pdf_agent_graph.stream(
            state,
            stream_mode="updates"
        ):
            if not isinstance(chunk, dict):
                continue

            for node_name, update in chunk.items():
                elapsed_ms = round(
                    (perf_counter() - node_started_at) * 1000,
                    2
                )
                _merge_state_update(state, update)

                public_node = NODE_NAMES.get(node_name, node_name)
                timings = dict(state.get("timings", {}))
                timings[public_node] = round(
                    timings.get(public_node, 0) + elapsed_ms,
                    2
                )
                state["timings"] = timings

                if public_node not in completed_nodes:
                    completed_nodes.append(public_node)

                yield _progress_event(
                    public_node,
                    "completed",
                    state,
                    completed_nodes,
                    elapsed_ms
                )

                active_node = _next_node(node_name, state)
                if active_node:
                    yield _progress_event(
                        active_node,
                        "running",
                        state,
                        completed_nodes
                    )
                    node_started_at = perf_counter()

    except Exception as exc:
        state.update(
            {
                "answer": (
                    "Sorry, the PDF Agent could not complete this request. "
                    f"Error: {exc}"
                ),
                "collaboration_notes": state.get(
                    "collaboration_notes",
                    empty_collaboration_notes()
                )
            }
        )
        yield _progress_event(
            active_node or "workflow",
            "failed",
            state,
            completed_nodes
        )

    timings = dict(state.get("timings", {}))
    timings["total"] = round(
        (perf_counter() - workflow_started_at) * 1000,
        2
    )
    state["timings"] = timings

    result = _build_result(state)
    _save_result(session, result)

    yield {
        "type": "result",
        "data": result
    }


def ask_pdf_agent(session, question):
    """
    Run the workflow synchronously for backward-compatible API clients.
    """

    result = None

    for event in iter_pdf_agent_events(session, question):
        if event["type"] == "result":
            result = event["data"]

    return result


def stream_pdf_agent(session, question):
    """
    Serialize workflow events as Server-Sent Events.
    """

    for event in iter_pdf_agent_events(session, question):
        yield (
            f"event: {event['type']}\n"
            f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
        )
