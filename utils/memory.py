"""Session/version-scoped bounded memory; never hold the index lock over I/O."""
import hashlib
import logging
from collections import OrderedDict
from threading import Lock, Event
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import monotonic

from utils.llm_client import LLMClientError, chat_with_deepseek
from utils.observability import get_active_usage_tracker, get_active_session_id, log_event
from utils.execution import error_reason, record_issue
from utils.memory_limits import load_memory_limits

logger = logging.getLogger(__name__)
_memory_cache = {}
_memory_cache_lock = Lock()
_inflight = {}
_UNAVAILABLE = 'Conversation summary is temporarily unavailable.'


@dataclass
class Flight:
    event: Event = field(default_factory=Event)
    result: str = _UNAVAILABLE
    reason: str | None = None
    invalidated: bool = False
    max_bytes: int = 4000


@contextmanager
def _bounded_memory_lock():
    tracker = get_active_usage_tracker()
    if tracker is None:
        with _memory_cache_lock:
            yield
        return
    budget = tracker.budget
    while True:
        budget.check()
        if _memory_cache_lock.acquire(timeout=min(0.1, budget.remaining_seconds())):
            break
    try:
        budget.check()
        yield
    finally:
        _memory_cache_lock.release()


def _clip(text: str, limit: int, *, tail=False) -> str:
    if limit <= 0:
        return ''
    # Slice characters before encoding, so one huge historical message cannot
    # require an unbounded temporary UTF-8 allocation.
    candidate = text[-limit:] if tail else text[:limit]
    data = candidate.encode('utf-8')
    return (data[-limit:] if tail else data[:limit]).decode('utf-8', errors='ignore')


def _history_text(messages, max_messages, max_bytes):
    lines = []
    remaining = max_bytes
    for message in reversed(messages[-max_messages:]):
        if not isinstance(message, dict):
            continue
        execution = message.get('execution') or {}
        if message.get('role') == 'assistant' and isinstance(execution, dict) and execution.get('generation_status') in {'failed', 'cancelled'}:
            continue
        content = message.get('content')
        if not isinstance(content, str) or not content:
            continue
        role = message.get('role', 'user')
        role = role if role in {'user', 'assistant', 'system'} else 'user'
        prefix = role.capitalize() + ': '
        allowance = remaining - len(prefix.encode()) - (1 if lines else 0)
        if allowance <= 0:
            break
        line = prefix + _clip(content, allowance, tail=True)
        lines.append(line)
        remaining -= len(line.encode()) + (1 if len(lines) > 1 else 0)
        if remaining <= 0:
            break
    return '\n'.join(reversed(lines))


def build_recent_memory(chat_history, max_messages=10):
    limits = load_memory_limits()
    return _history_text(chat_history or [], min(max_messages, limits.history_messages), limits.recent_bytes) or _clip('No recent conversation.', limits.recent_bytes)


def _scope():
    sid = get_active_session_id()
    if sid is not None:
        return ('session', sid)
    tracker = get_active_usage_tracker()
    return ('request', tracker.memory_scope) if tracker is not None else None


def _prune(now, limits):
    for key, (_, expires) in list(_memory_cache.items()):
        if expires <= now:
            del _memory_cache[key]
    while len(_memory_cache) > limits.cache_entries:
        _memory_cache.pop(next(iter(_memory_cache)))


def invalidate_memory(session_id: str) -> None:
    # Short index mutation only, usable after cancellation. No network/DB I/O.
    with _memory_cache_lock:
        for key in list(_memory_cache):
            if key[0] == ('session', session_id):
                del _memory_cache[key]
        for key, flight in _inflight.items():
            if key[0] == ('session', session_id):
                flight.invalidated = True
    log_event(logger, logging.INFO, 'memory_invalidated')


def _reuse(flight):
    tracker = get_active_usage_tracker()
    deadline = monotonic() + 5
    while not flight.event.is_set():
        if tracker is not None:
            tracker.budget.check()
            delay = min(.05, tracker.budget.remaining_seconds())
        else:
            delay = min(.05, max(0, deadline - monotonic()))
            if delay <= 0:
                record_issue('memory_wait_timeout', fatal=False)
                return _clip(_UNAVAILABLE, flight.max_bytes)
        flight.event.wait(delay)
    if tracker is not None:
        tracker.budget.check()
    if flight.reason or flight.invalidated:
        record_issue(flight.reason or 'memory_invalidated', fatal=False)
    return _clip(_UNAVAILABLE, flight.max_bytes) if flight.invalidated else flight.result


def build_llm_conversation_summary(chat_history, recent_window=10, *, loaded_pdfs=None):
    limits = load_memory_limits()
    if not chat_history:
        return _clip('No conversation summary.', limits.summary_bytes)
    window = chat_history[-limits.history_messages:]
    older = window[:-recent_window] if recent_window > 0 else window
    text = _history_text(older, limits.history_messages, limits.history_bytes - limits.recent_bytes)
    if not text:
        return _clip('No older conversation to summarize.', limits.summary_bytes)
    # Cache identity covers the exact bounded input, document context and
    # output limit. Old-version computations cannot overwrite a new version.
    identity = text + '\n' + build_session_memory(loaded_pdfs) + f'\nsummary-limit:{limits.summary_bytes}'
    scope = _scope()
    key = (scope, hashlib.sha256(identity.encode()).hexdigest()) if scope is not None else None
    flight = Flight(result=_clip(_UNAVAILABLE, limits.summary_bytes), max_bytes=limits.summary_bytes)
    owner = True
    cached_summary = None
    capacity_reached = False
    if key is not None:
        with _bounded_memory_lock():
            _prune(monotonic(), limits)
            if key in _memory_cache:
                cached = _memory_cache.pop(key)
                _memory_cache[key] = cached
                cached_summary = cached[0]
            elif key in _inflight:
                flight = _inflight[key]
                owner = False
            elif len(_inflight) >= limits.cache_entries:
                capacity_reached = True
            else:
                _inflight[key] = flight
    if cached_summary is not None:
        log_event(logger, logging.INFO, 'memory_cache_hit')
        return cached_summary
    if capacity_reached:
        record_issue('memory_capacity', fatal=False)
        log_event(logger, logging.WARNING, 'memory_capacity_reached')
        return _clip(_UNAVAILABLE, limits.summary_bytes)
    if not owner:
        return _reuse(flight)

    prompt = f"""Summarize the following previous conversation for an AI PDF Agent.
Focus on user goals, preferences, previously discussed PDFs, important conclusions,
follow-up references and unresolved tasks. Keep it concise and factual.
Do NOT mention that this is a memory summary.
Previous Conversation:
{text}
"""
    cacheable = False
    try:
        # This gateway call owns the cost; cache readers record no synthetic usage.
        summary = chat_with_deepseek(prompt, operation='memory_summary')
        if not isinstance(summary, str) or not summary.strip():
            flight.reason = 'invalid_model_output'
        else:
            flight.result = _clip(summary, limits.summary_bytes)
            cacheable = True
    except LLMClientError as exc:
        flight.reason = error_reason(exc)
    except BaseException:
        flight.reason = 'memory_summary_failed'
        raise
    finally:
        # Even cancelled/failed leaders wake all waiters. Publication/index work
        # is bounded CPU only and never waits on a cancelled request's budget.
        with _memory_cache_lock:
            if key is not None:
                if cacheable and not flight.invalidated:
                    _memory_cache[key] = (flight.result, monotonic() + limits.cache_ttl_seconds)
                    _prune(monotonic(), limits)
                if _inflight.get(key) is flight:
                    del _inflight[key]
            flight.event.set()
    if flight.reason or flight.invalidated:
        record_issue(flight.reason or 'memory_invalidated', fatal=False)
        log_event(logger, logging.WARNING, 'memory_summary_fallback', reason=flight.reason or 'memory_invalidated')
    return _clip(_UNAVAILABLE, limits.summary_bytes) if flight.invalidated else flight.result


def build_session_memory(loaded_pdfs):
    limit = load_memory_limits().session_bytes
    if not loaded_pdfs:
        return _clip('No PDF context available.', limit)
    names = OrderedDict.fromkeys(name for name in loaded_pdfs[-100:] if isinstance(name, str))
    lines = ['Current uploaded PDFs:']
    remaining = max(0, limit - len(lines[0].encode()))
    for name in names:
        if remaining <= 3:
            break
        line = '- ' + _clip(name, remaining - 3)
        lines.append(line)
        remaining -= len(line.encode()) + 1
    return _clip('\n'.join(lines), limit)


def build_memory(chat_history, loaded_pdfs=None):
    limits = load_memory_limits()
    history = chat_history or []
    summary = build_llm_conversation_summary(history, loaded_pdfs=loaded_pdfs)
    recent = build_recent_memory(history)
    session = build_session_memory(loaded_pdfs)
    total = getattr(history, 'total_count', len(history))
    notice = 'Only a bounded conversation window is available.\n' if total > limits.history_messages or any(
        isinstance(m, dict) and isinstance(m.get('content'), str) and len(m['content']) > limits.recent_bytes
        for m in history[-limits.history_messages:]) else ''
    return f"""{notice}Conversation Summary Memory:
{summary}

Recent Conversation Memory:
{recent}

Session Memory:
{session}
"""
