import json
import logging
import asyncio
from concurrent.futures import CancelledError
from functools import lru_cache
from time import perf_counter

from agent.graph_agent import build_pdf_agent_graph
from agent.state import create_initial_agent_state, empty_collaboration_notes
from utils.execution import error_reason, outcome
from utils.llm_budget import LLMClientError
from utils.memory_limits import HistoryWindow
from app.services.session_store import save_session
from app.services.postgres_store import acquire_session_lease, release_session_lease
from utils.observability import (
    get_usage_summary,
    log_event,
    new_usage_tracker,
    observability_context,
)


NODE_NAMES = {
    "planner_agent": "planner",
    "specialist_agent": "specialists",
    "workflow_controller": "controller",
    "collaboration_agent": "collaboration",
    "revision_controller": "revision",
    "reviewer_agent": "reviewer"
}
logger = logging.getLogger(__name__)


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
    elapsed_ms=None,
    usage_tracker=None,
):
    node_statuses = dict(state.get('node_statuses', {}))
    if status == 'running':
        node_statuses[node] = outcome('running')
    data = {
        "node": node,
        "status": status,
        "completed_nodes": list(completed_nodes),
        "steps": list(state.get("steps", [])),
        "revision_count": state.get("revision_count", 0),
        "timings": dict(state.get("timings", {})),
        "usage": get_usage_summary(usage_tracker),
        "node_statuses": node_statuses,
    }

    if elapsed_ms is not None:
        data["elapsed_ms"] = elapsed_ms

    return {
        "type": "progress",
        "data": data
    }


def _build_result(state, usage_tracker=None):
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
        "timings": state.get("timings", {}),
        "usage": get_usage_summary(usage_tracker),
    }


def _save_result(session, result):
    # Commit a candidate snapshot; a rollback must not leave unsaved messages
    # or success metadata in the caller's session snapshot.
    candidate = dict(session, messages=[*session['messages'], {
        'role': 'assistant', 'content': result['answer'],
        **{key: result[key] for key in ('steps', 'collaboration_notes',
            'revision_count', 'sources', 'timings', 'usage', 'execution')},
    }])
    save_session(candidate)
    session.update(candidate)


def _execution(state, *, reason=None, cancelled=False):
    nodes = dict(state.get('node_statuses', {}))
    steps = [nodes[step] for step in state.get('steps', []) if step in nodes]
    if cancelled:
        generation = 'cancelled'
    elif reason:
        generation = 'failed'
    elif 'reviewer' not in nodes or not state.get('answer', '').strip():
        generation, reason = 'failed', 'incomplete_workflow'
    elif steps and all(node['status'] in {'failed', 'cancelled'} for node in steps):
        generation, reason = 'failed', next((node['reason'] for node in steps if node['reason']), 'specialist_failed')
    elif any(node['status'] in {'degraded', 'failed', 'cancelled'} for node in nodes.values()):
        generation, reason = 'degraded', next((node['reason'] for node in nodes.values() if node['reason']), 'node_failed')
    else:
        generation = 'succeeded'
    return dict(status=generation, generation_status=generation, reason=reason,
                node_statuses=nodes, persistence='not_attempted')


def iter_pdf_agent_events(session, question, request_id=None, llm_budget=None):
    tracker = new_usage_tracker(llm_budget)
    lease = {}
    try:
        yield from _iter_pdf_agent_events(session, question, request_id, tracker, lease)
    except GeneratorExit:
        tracker.budget.cancel('workflow_closed')
        with observability_context(request_id, session.get('session_id'), tracker):
            log_event(logger, logging.INFO, 'agent_workflow_interrupted', reason='cancelled',
                      usage=get_usage_summary(tracker), persistence='not_attempted_or_already_saved')
        raise
    finally:
        if lease:
            try:
                release_session_lease(session['session_id'], lease['id'])
            except Exception as exc:
                with observability_context(request_id, session.get('session_id'), tracker):
                    log_event(logger, logging.ERROR, 'agent_lease_release_failed', error_type=type(exc).__name__)
        with observability_context(request_id, session.get('session_id'), tracker):
            log_event(logger, logging.INFO, 'llm_budget_finished', **tracker.budget.summary())
            tracker.budget.cancel('workflow_closed')


def _iter_pdf_agent_events(session, question, request_id, usage_tracker, lease):
    """
    Run the LangGraph workflow and yield progress plus the final result.
    """

    working_session = dict(session, messages=HistoryWindow(session["messages"],
        session.get("message_count", len(session["messages"]))))
    failure_reason = None
    pdf_agent_graph = None
    workflow_started_at = perf_counter()
    session_id = session.get("session_id")

    with observability_context(request_id, session_id, usage_tracker):
        log_event(
            logger,
            logging.INFO,
            "agent_workflow_started",
            question_length=len(question),
            loaded_pdf_count=len(session.get("loaded_pdfs", [])),
            document_count=session.get("document_count", 0),
        )

    working_session["messages"].append(
        {
            "role": "user",
            "content": question
        }
    )

    working_session["messages"].total_count += 1
    state = create_initial_agent_state(
        question,
        session["vectorstore"],
        working_session["messages"],
        session["loaded_pdfs"]
    )
    completed_nodes = []
    active_node = "planner"

    yield _progress_event(
        active_node,
        "running",
        state,
        completed_nodes,
        usage_tracker=usage_tracker,
    )
    node_started_at = perf_counter()
    graph_events = None

    try:
        with observability_context(request_id, session_id, usage_tracker):
            usage_tracker.budget.check()
            # Only persisted snapshots own DB leases. Synthetic/evaluation
            # sessions without persistence markers keep their existing behavior.
            if '_persisted_message_count' in session:
                lease['id'] = acquire_session_lease(session_id, usage_tracker.budget.remaining_seconds())
        pdf_agent_graph = get_pdf_agent_graph()
        graph_events = iter(
            pdf_agent_graph.stream(
                state,
                stream_mode="updates",
            )
        )

        while True:
            try:
                with observability_context(
                    request_id,
                    session_id,
                    usage_tracker,
                ):
                    usage_tracker.budget.check()
                    chunk = next(graph_events)
                    usage_tracker.budget.check()
            except StopIteration:
                break

            if not isinstance(chunk, dict):
                continue

            emitted_events = []
            for node_name, update in chunk.items():
                with observability_context(
                    request_id,
                    session_id,
                    usage_tracker,
                ):
                    elapsed_ms = round(
                        (perf_counter() - node_started_at) * 1000,
                        2,
                    )
                    _merge_state_update(state, update)

                    public_node = NODE_NAMES.get(node_name, node_name)
                    timings = dict(state.get("timings", {}))
                    timings[public_node] = round(
                        timings.get(public_node, 0) + elapsed_ms,
                        2,
                    )
                    state["timings"] = timings

                    nodes = dict(state.get('node_statuses', {}))
                    nodes.setdefault(public_node, outcome('succeeded'))
                    state['node_statuses'] = nodes
                    node_status = nodes[public_node]['status']
                    if node_status == 'succeeded' and public_node not in completed_nodes:
                        completed_nodes.append(public_node)
                    elif node_status != 'succeeded' and public_node in completed_nodes:
                        completed_nodes.remove(public_node)

                    log_event(
                        logger,
                        logging.INFO,
                        "agent_node_finished",
                        outcome=node_status,
                        node=public_node,
                        elapsed_ms=elapsed_ms,
                        planned_steps=list(state.get("steps", [])),
                        revision_count=state.get("revision_count", 0),
                    )
                    emitted_events.append(
                        _progress_event(
                            public_node,
                            "completed" if node_status == "succeeded" else "failed",
                            state,
                            completed_nodes,
                            elapsed_ms,
                            usage_tracker,
                        )
                    )

                    active_node = _next_node(node_name, state)
                    if active_node:
                        emitted_events.append(
                            _progress_event(
                                active_node,
                                "running",
                                state,
                                completed_nodes,
                                usage_tracker=usage_tracker,
                            )
                        )
                        node_started_at = perf_counter()

            yield from emitted_events

    except (Exception, asyncio.CancelledError) as exc:
        failure_reason = ('cancelled' if isinstance(exc, (asyncio.CancelledError, CancelledError)) else
                          error_reason(exc) if isinstance(exc, LLMClientError) else 'workflow_error')
        state['node_statuses'][active_node or 'workflow'] = outcome(
            'cancelled' if failure_reason == 'cancelled' else 'failed', failure_reason)
        with observability_context(request_id, session_id, usage_tracker):
            log_event(
                logger,
                logging.ERROR,
                "agent_workflow_failed",
                exc_info=True,
                active_node=active_node or "workflow",
                error_type=type(exc).__name__,
            )
            state.update(
                {
                    "answer": (
                        "Sorry, the PDF Agent could not complete this request. "
                        "Please try again later."
                    ),
                    "collaboration_notes": state.get(
                        "collaboration_notes",
                        empty_collaboration_notes(),
                    ),
                }
            )
        yield _progress_event(
            active_node or "workflow",
            "failed",
            state,
            completed_nodes,
            usage_tracker=usage_tracker,
        )
    except GeneratorExit:
        usage_tracker.budget.cancel('workflow_closed')
        raise
    finally:
        if graph_events is not None and hasattr(graph_events, 'close'):
            try:
                graph_events.close()
            except Exception as exc:
                failure_reason = 'workflow_error'
                with observability_context(request_id, session_id, usage_tracker):
                    log_event(logger, logging.ERROR, 'agent_graph_close_failed', error_type=type(exc).__name__)

    timings = dict(state.get("timings", {}))
    timings["total"] = round(
        (perf_counter() - workflow_started_at) * 1000,
        2
    )
    state["timings"] = timings

    with observability_context(request_id, session_id, usage_tracker):
        result = _build_result(state, usage_tracker)
        result['execution'] = _execution(state, reason=failure_reason,
                                         cancelled=failure_reason == 'cancelled')
        # Cancellation can arrive after the final graph yield. No new save is
        # started after observed cancellation; an already committed save cannot
        # be recalled. A broken transport is never promised a terminal event.
        summary = usage_tracker.budget.summary()
        if summary['cancel_reason'] in {'cancelled', 'client_disconnected', 'workflow_closed'}:
            result['execution'] = _execution(state, reason='cancelled', cancelled=True)
        if result['execution']['status'] != 'cancelled':
            result['execution']['persistence'] = 'saved'
            try:
                _save_result(working_session, result)
            except Exception as exc:
                result['execution'].update(status='failed', reason='persistence_failed', persistence='failed')
                log_event(logger, logging.ERROR, 'agent_result_save_failed', error_type=type(exc).__name__)
            else:
                session.update(working_session)
        log_event(logger, logging.INFO, 'agent_workflow_finished',
                  execution=result['execution'], duration_ms=timings['total'], usage=result['usage'])
    yield {'type': 'result', 'data': result}


def ask_pdf_agent(session, question, request_id=None, llm_budget=None):
    """
    Run the workflow synchronously for backward-compatible API clients.
    """

    result = None

    for event in iter_pdf_agent_events(session, question, request_id, llm_budget):
        if event["type"] == "result":
            result = event["data"]

    return result


def stream_pdf_agent(session, question, request_id=None, llm_budget=None):
    """
    Serialize workflow events as Server-Sent Events.
    """

    events = iter_pdf_agent_events(session, question, request_id, llm_budget)
    try:
        for event in events:
            yield (
                f"event: {event['type']}\n"
                f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            )
    finally:
        events.close()
