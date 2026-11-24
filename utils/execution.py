"""Internal failure signals for nodes that intentionally return a fallback answer.

Scopes are per invocation, copied into specialist threads, never process-global
mutable failure state. They carry codes only, not provider errors or PDF text.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from utils.llm_budget import LLMBudgetExceeded, LLMAccessDenied

_issues = ContextVar('execution_issues', default=None)


def error_reason(exc: BaseException) -> str:
    if isinstance(exc, LLMBudgetExceeded):
        if exc.reason == 'paid_api_not_authorized':
            return 'paid_api_disabled'
        if exc.reason in {'cancelled', 'client_disconnected', 'workflow_closed'}:
            return 'cancelled'
        return 'deadline_exceeded' if exc.reason == 'deadline' else 'budget_exhausted'
    if isinstance(exc, LLMAccessDenied):
        return 'paid_api_disabled'
    if isinstance(exc, TimeoutError) or type(exc).__name__ == 'APITimeoutError' or (
        exc.__cause__ is not None and (
            isinstance(exc.__cause__, TimeoutError) or type(exc.__cause__).__name__ == 'APITimeoutError'
        )
    ):
        return 'model_timeout'
    return 'model_unavailable'


def record_issue(reason: str, *, fatal: bool = True) -> None:
    issues = _issues.get()
    if issues is not None:
        issues.append((reason, fatal))


@contextmanager
def issue_scope():
    issues = []
    token = _issues.set(issues)
    try:
        yield issues
    finally:
        _issues.reset(token)


def outcome(status: str, reason: str | None = None) -> dict:
    return {'status': status, 'reason': reason}


def tracked_node(name: str):
    """Attach explicit outcomes without changing LangGraph routing or reducers."""
    def decorate(function):
        @wraps(function)
        def run(state):
            with issue_scope() as issues:
                update = function(state)
            nodes = {**state.get('node_statuses', {}), **update.get('node_statuses', {})}
            status, reason = 'succeeded', None
            if name == 'specialists':
                children = [nodes[step] for step in state.get('steps', []) if step in nodes]
                if children and any(child['status'] != 'succeeded' for child in children):
                    status = 'degraded' if any(child['status'] in {'succeeded', 'degraded'} for child in children) else 'failed'
                    reason = next(child['reason'] for child in children if child['status'] != 'succeeded')
            if name == 'collaboration' and update.get('collaboration_notes', {}).get('status') == 'failed':
                status, reason = 'degraded', 'collaboration_failed'
            if issues:
                status, reason = 'degraded', issues[0][0]
            nodes[name] = outcome(status, reason)
            update['node_statuses'] = nodes
            return update
        return run
    return decorate
