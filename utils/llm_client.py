import os
import logging
import asyncio
from concurrent.futures import CancelledError
from datetime import datetime, timezone
from time import perf_counter

from dotenv import load_dotenv
from openai import OpenAI, APIConnectionError

from utils.llm_budget import (
    LLMClientError, LLMAccessDenied, LLMBudgetExceeded, RequestBudget, ensure_llm_access, estimate_input_tokens,
)
from utils.observability import get_active_usage_tracker, log_event, record_llm_usage


load_dotenv()

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"
DEFAULT_TIMEOUT = 60

_deepseek_client = None
logger = logging.getLogger(__name__)


def get_deepseek_model():
    """
    Return the configured DeepSeek model name.
    """

    return os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)


def get_deepseek_client():
    """
    Return a shared DeepSeek-compatible OpenAI client.
    """

    global _deepseek_client

    if os.getenv('PDF_AGENT_DISABLE_LLM_API', '0').strip().lower() not in {'0', 'false'}:
        raise LLMAccessDenied('LLM network access is disabled.')

    if _deepseek_client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY")

        if not api_key:
            raise LLMClientError(
                "DEEPSEEK_API_KEY is not configured."
            )

        _deepseek_client = OpenAI(
            api_key=api_key,
            base_url=DEEPSEEK_BASE_URL,
            timeout=DEFAULT_TIMEOUT,
            max_retries=0,
        )

    return _deepseek_client


def _retry_reason(exc):
    if isinstance(exc, (APIConnectionError, TimeoutError, ConnectionError)):
        return 'transport_timeout' if 'Timeout' in type(exc).__name__ else 'connection'
    status = getattr(exc, 'status_code', None)
    if type(status) is int and (status in {408, 409, 429} or 500 <= status <= 599):
        return f'http_{status}'
    return None


def request_completion(messages, *, model=None, temperature=0, operation='unspecified',
                       client=None, output_limit=None, timeout_limit=None, max_retries=None):
    """One gateway for Agent and probe attempts; every SDK attempt is recorded once."""
    requested_model = model or get_deepseek_model()
    tracker = get_active_usage_tracker()
    budget = tracker.budget if tracker is not None else RequestBudget()
    try:
        ensure_llm_access()
        client = client if client is not None else get_deepseek_client()
    except LLMAccessDenied:
        budget.cancel('paid_api_not_authorized')
        raise
    estimated_input = estimate_input_tokens(messages)
    retries = budget.settings.max_retries if max_retries is None else min(max_retries, budget.settings.max_retries)
    for attempt in range(retries + 1):
        call_started_at = datetime.now(timezone.utc)
        reservation = budget.reserve(requested_model, estimated_input, output_limit=output_limit, at=call_started_at)
        timeout = min(budget.settings.call_timeout_seconds, budget.remaining_seconds(),
                      timeout_limit if timeout_limit is not None else budget.settings.call_timeout_seconds)
        started_at = perf_counter()
        failure = None
        try:
            budget.check_admitted()
        except LLMBudgetExceeded:
            budget.release_unstarted(reservation)
            raise
        try:
            response = client.chat.completions.create(
                model=requested_model, messages=messages, temperature=temperature,
                timeout=timeout, max_tokens=reservation.output_tokens,
            )
        except (asyncio.CancelledError, CancelledError) as exc:
            usage = record_llm_usage(requested_model, operation, getattr(exc, 'usage', None),
                                     (perf_counter() - started_at) * 1000, at=call_started_at)
            budget.settle(reservation, usage)
            log_event(logger, logging.INFO, 'llm_call_cancelled', operation=operation, attempt=reservation.number)
            budget.cancel('cancelled')
            raise
        except Exception as exc:
            failure = exc
            provider_usage = getattr(exc, 'usage', None)
            response_model = requested_model
        else:
            provider_usage = getattr(response, 'usage', None)
            response_model = getattr(response, 'model', None) or requested_model

        usage = record_llm_usage(
            response_model, operation, provider_usage,
            (perf_counter() - started_at) * 1000, at=call_started_at,
        )
        budget.settle(reservation, usage)
        if failure is None:
            log_event(logger, logging.INFO, 'llm_call_completed', **usage)
            try:
                budget.check_admitted()
            except LLMBudgetExceeded as exc:
                exc.recorded_usage = usage
                raise
            return response, usage
        reason = _retry_reason(failure)
        log_event(logger, logging.ERROR, 'llm_call_failed', model=requested_model,
                  operation=operation, error_type=type(failure).__name__, retry_reason=reason,
                  attempt=reservation.number, duration_ms=usage['duration_ms'])
        error = LLMClientError('DeepSeek request failed. Please try again later.')
        error.recorded_usage = usage
        if reason is None or attempt >= retries:
            raise error from failure
        delay = budget.settings.retry_base_delay_seconds * 2 ** attempt
        headers = getattr(getattr(failure, 'response', None), 'headers', {})
        try:
            retry_after = float(headers.get('retry-after', 0))
            if retry_after >= 0:
                delay = max(delay, retry_after)
        except (TypeError, ValueError):
            pass
        if delay > budget.settings.max_retry_delay_seconds:
            log_event(logger, logging.INFO, 'llm_retry_skipped', reason='server_wait_too_long')
            raise error from failure
        log_event(logger, logging.INFO, 'llm_retry_scheduled', reason=reason,
                  retry_number=attempt + 1, delay_seconds=delay)
        budget.wait(delay)


def chat_with_deepseek(prompt, model=None, temperature=0, operation='unspecified', system_prompt=None):
    messages = []
    if system_prompt is not None:
        messages.append({'role': 'system', 'content': system_prompt})
    messages.append({'role': 'user', 'content': prompt})
    response, _usage = request_completion(messages, model=model, temperature=temperature, operation=operation)

    try:
        content = response.choices[0].message.content
        if not isinstance(content, str):
            raise TypeError
        return content

    except (AttributeError, IndexError, TypeError) as exc:
        log_event(
            logger,
            logging.ERROR,
            "llm_response_invalid",
            model=getattr(response, 'model', None) or model or get_deepseek_model(),
            operation=operation,
            error_type=type(exc).__name__,
        )
        raise LLMClientError(
            "DeepSeek returned an invalid response format."
        ) from exc
