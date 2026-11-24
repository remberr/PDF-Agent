"""Thread-safe dispatch budgets. Reservations are estimates, not billed usage."""
import json
import logging
import math
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from threading import Event, Lock
from time import monotonic

from utils.pricing import get_model_pricing


class LLMClientError(Exception):
    """A completion could not be obtained safely."""


class LLMBudgetExceeded(LLMClientError):
    def __init__(self, reason: str):
        super().__init__('LLM request budget is unavailable or exhausted.')
        self.reason = reason


class LLMAccessDenied(LLMClientError):
    """No provider request is permitted in this execution context."""


@dataclass(frozen=True)
class BudgetSettings:
    max_calls: int = 12
    max_input_tokens: int = 120000
    max_output_tokens: int = 24000
    max_output_per_call: int = 4096
    max_estimated_cost_usd: float | None = 0.50
    request_timeout_seconds: float = 180
    call_timeout_seconds: float = 60
    max_retries: int = 0
    retry_base_delay_seconds: float = 0.25
    max_retry_delay_seconds: float = 2


SETTING_ENV_VARS = {
    'max_calls': 'LLM_MAX_CALLS_PER_REQUEST',
    'max_input_tokens': 'LLM_MAX_INPUT_TOKENS_PER_REQUEST',
    'max_output_tokens': 'LLM_MAX_OUTPUT_TOKENS_PER_REQUEST',
    'max_output_per_call': 'LLM_MAX_OUTPUT_TOKENS_PER_CALL',
    'max_estimated_cost_usd': 'LLM_MAX_ESTIMATED_COST_USD_PER_REQUEST',
    'request_timeout_seconds': 'LLM_REQUEST_TIMEOUT_SECONDS',
    'call_timeout_seconds': 'LLM_CALL_TIMEOUT_SECONDS',
    'max_retries': 'LLM_MAX_RETRIES',
    'retry_base_delay_seconds': 'LLM_RETRY_BASE_DELAY_SECONDS',
    'max_retry_delay_seconds': 'LLM_MAX_RETRY_DELAY_SECONDS',
}


def load_budget_settings(environ=None) -> BudgetSettings:
    env = os.environ if environ is None else environ
    defaults = BudgetSettings()
    values = {}
    for field in fields(defaults):
        name = SETTING_ENV_VARS[field.name]
        raw = env.get(name, str(getattr(defaults, field.name)))
        if field.name == 'max_estimated_cost_usd' and raw == '':
            values[field.name] = None  # Explicitly disable only the monetary guard.
            continue
        try:
            integer = field.name in {'max_calls', 'max_input_tokens', 'max_output_tokens',
                                     'max_output_per_call', 'max_retries'}
            value = int(raw) if integer else float(raw)
            if not math.isfinite(value) or value < 0 or (value == 0 and field.name != 'max_retries'):
                raise ValueError
            if field.name == 'max_retries' and value > 2:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f'Invalid finite budget setting: {name}.') from None
        values[field.name] = value
    return BudgetSettings(**values)


def estimate_input_tokens(messages: list[dict]) -> int:
    """Conservative UTF-8 byte heuristic, not a provider tokenizer guarantee."""
    return len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) + 32 * len(messages) + 32


_access_allowed = ContextVar('llm_access_allowed', default=True)


@contextmanager
def llm_access(allowed: bool):
    token = _access_allowed.set(_access_allowed.get() and allowed)
    try:
        yield
    finally:
        _access_allowed.reset(token)


def ensure_llm_access() -> None:
    if not _access_allowed.get():
        raise LLMAccessDenied('LLM calls require explicit authorization in evaluation mode.')


def _log(event: str, **fields) -> None:
    # Local import avoids a cycle with UsageTracker, which owns the budget.
    from utils.observability import log_event
    log_event(logging.getLogger(__name__), logging.INFO, event, **fields)


@dataclass(frozen=True)
class Reservation:
    number: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None


class RequestBudget:
    def __init__(self, settings: BudgetSettings | None = None, *, clock=monotonic):
        self.settings = settings or load_budget_settings()
        self._clock = clock
        self._deadline = clock() + self.settings.request_timeout_seconds
        self._lock = Lock()
        self._cancelled = Event()
        self._reason = None
        self._cancel_reason = None
        self._overrun = False
        self._attempts = 0
        self._input = self._output = 0
        self._cost = 0.0
        self._unknown_pricing = 0
        self._unresolved = 0
        self._active = {}

    def remaining_seconds(self) -> float:
        return max(0.0, self._deadline - self._clock())

    def _stop_locked(self, reason: str) -> None:
        if self._reason is None:
            self._reason = reason
            self._cancelled.set()
            exhausted = reason in {'calls', 'input_tokens', 'output_tokens', 'cost_unavailable',
                                   'estimated_cost_usd', 'deadline', 'provider_usage_over_budget'}
            _log('llm_budget_exhausted' if exhausted else 'llm_budget_cancelled',
                 reason=reason, attempts_admitted=self._attempts)

    def _deny_locked(self, reason: str):
        self._stop_locked(reason)
        raise LLMBudgetExceeded(self._reason)

    def _check_locked(self) -> None:
        if self._cancel_reason:
            raise LLMBudgetExceeded(self._cancel_reason)
        if self._reason:
            raise LLMBudgetExceeded(self._reason)
        if self.remaining_seconds() <= 0:
            self._deny_locked('deadline')

    def check(self) -> None:
        with self._lock:
            self._check_locked()

    def cancel(self, reason='cancelled') -> None:
        with self._lock:
            if self._cancel_reason is None:
                self._cancel_reason = reason
                if self._reason is not None:
                    _log('llm_budget_cancelled', reason=reason, attempts_admitted=self._attempts)
            self._stop_locked(reason)

    def check_admitted(self) -> None:
        """A peer's denied reservation does not invalidate an admitted attempt."""
        with self._lock:
            if self._cancel_reason:
                raise LLMBudgetExceeded(self._cancel_reason)
            if self._overrun:
                raise LLMBudgetExceeded('provider_usage_over_budget')
            if self.remaining_seconds() <= 0:
                self._deny_locked('deadline')
            if self._reason and self._reason not in {
                'calls', 'input_tokens', 'output_tokens', 'estimated_cost_usd', 'cost_unavailable',
            }:
                raise LLMBudgetExceeded(self._reason)

    def wait(self, delay: float) -> None:
        self.check()
        if delay >= self.remaining_seconds():
            self.cancel('deadline')
            self.check()
        self._cancelled.wait(delay)
        self.check()

    def reserve(self, model: str, input_tokens: int, *, output_limit=None, at=None) -> Reservation:
        if type(input_tokens) is not int or input_tokens < 0:
            raise ValueError('Input reservation must be a non-negative integer.')
        pricing = get_model_pricing(model, at=at or datetime.now(timezone.utc))
        with self._lock:
            self._check_locked()
            limits = self.settings
            if self._attempts >= limits.max_calls:
                self._deny_locked('calls')
            if self._input + input_tokens > limits.max_input_tokens:
                self._deny_locked('input_tokens')
            output_tokens = min(limits.max_output_per_call, limits.max_output_tokens - self._output,
                                output_limit if output_limit is not None else limits.max_output_per_call)
            if output_tokens <= 0:
                self._deny_locked('output_tokens')
            cost = ((input_tokens * max(pricing['cache_hit'], pricing['cache_miss'])
                     + output_tokens * pricing['output']) / 1_000_000) if pricing['available'] else None
            if limits.max_estimated_cost_usd is not None:
                if cost is None:
                    self._deny_locked('cost_unavailable')
                if self._cost + cost > limits.max_estimated_cost_usd:
                    self._deny_locked('estimated_cost_usd')
            self._attempts += 1
            reservation = Reservation(self._attempts, input_tokens, output_tokens, cost)
            self._active[reservation.number] = reservation
            self._input += input_tokens
            self._output += output_tokens
            self._cost += cost or 0.0
            self._unknown_pricing += int(cost is None)
            _log('llm_budget_reserved', attempt=reservation.number,
                 estimated_input_tokens=input_tokens, reserved_output_tokens=output_tokens,
                 reserved_estimated_cost_usd=cost)
            return reservation

    def release_unstarted(self, reservation: Reservation) -> None:
        with self._lock:
            if self._active.pop(reservation.number, None) is None:
                raise RuntimeError('Budget reservation was already settled.')
            self._input -= reservation.input_tokens
            self._output -= reservation.output_tokens
            self._cost -= reservation.estimated_cost_usd or 0
            self._unknown_pricing -= int(reservation.estimated_cost_usd is None)

    def settle(self, reservation: Reservation, usage: dict) -> None:
        """Release unused reservations only when provider counters are determinate."""
        with self._lock:
            if self._active.pop(reservation.number, None) is None:
                raise RuntimeError('Budget reservation was already settled.')
            tokens_known = usage.get('token_usage_available', False)
            cost_known = usage.get('cost_estimate_available', False)
            if tokens_known:
                self._input += usage['input_tokens'] - reservation.input_tokens
                self._output += usage['output_tokens'] - reservation.output_tokens
            if cost_known:
                self._cost += usage['estimated_cost_usd'] - (reservation.estimated_cost_usd or 0.0)
                self._unknown_pricing -= int(reservation.estimated_cost_usd is None)
            self._unresolved += int(not tokens_known or not cost_known)
            limits = self.settings
            if (self._input > limits.max_input_tokens or self._output > limits.max_output_tokens
                    or (limits.max_estimated_cost_usd is not None and self._cost > limits.max_estimated_cost_usd)):
                self._overrun = True
                self._stop_locked('provider_usage_over_budget')
            _log('llm_budget_settled', attempt=reservation.number,
                 token_usage_available=tokens_known, cost_estimate_available=cost_known)

    def summary(self) -> dict:
        with self._lock:
            return dict(attempts_admitted=self._attempts, in_flight=len(self._active),
                        input_tokens_committed_or_reserved=self._input,
                        output_tokens_committed_or_reserved=self._output,
                        cost_committed_or_reserved_usd=None if self._unknown_pricing else round(self._cost, 10),
                        unresolved_usage_attempts=self._unresolved,
                        stop_reason=self._reason, cancel_reason=self._cancel_reason,
                        remaining_seconds=round(self.remaining_seconds(), 3),
                        accounting='conservative_reservations_not_billed_usage')
