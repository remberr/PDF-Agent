import json
import logging
import os
import re
import sys
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from uuid import uuid4

from utils.pricing import MODEL_ALIASES, MODEL_PRICING, PRICE_ENV_VARS, get_model_pricing, _is_peak_time

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_request_id_var = ContextVar("request_id", default=None)
_session_id_var = ContextVar("session_id", default=None)
_usage_tracker_var = ContextVar("usage_tracker", default=None)
_logging_lock = Lock()
_logging_configured = False


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "message": record.getMessage(),
        }

        request_id = _request_id_var.get()
        session_id = _session_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        if session_id:
            payload["session_id"] = session_id

        fields = getattr(record, "structured_fields", None)
        if fields:
            payload.update(_json_safe(fields))

        if record.exc_info:
            payload["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "stacktrace": self.formatException(record.exc_info),
            }

        return json.dumps(payload, ensure_ascii=False)


def configure_logging():
    """Configure application and Uvicorn logs as one JSON stream."""

    global _logging_configured

    with _logging_lock:
        if _logging_configured:
            return

        level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())

        root_logger = logging.getLogger()
        root_logger.handlers = [handler]
        root_logger.setLevel(level)

        for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            uvicorn_logger = logging.getLogger(logger_name)
            uvicorn_logger.handlers = []
            uvicorn_logger.propagate = True

        _logging_configured = True


def log_event(logger, level, event, exc_info=None, **fields):
    logger.log(
        level,
        event,
        exc_info=exc_info,
        extra={
            "event": event,
            "structured_fields": fields,
        },
    )


def cache_usage_summary(llm_calls, input_tokens, cache_hit_tokens, unavailable_calls):
    """Keep the legacy numeric rate; its availability must be checked first."""
    available = llm_calls > 0 and unavailable_calls == 0 and input_tokens > 0
    return {
        "cache_usage_available": available,
        "cache_status": "no_calls" if llm_calls == 0 else "available" if available else "unavailable",
        "cache_unavailable_calls": unavailable_calls,
        "cache_hit_rate": cache_hit_tokens / input_tokens if available else 0.0,
    }


@dataclass
class UsageBucket:
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    estimated_cost_usd: float = 0.0
    estimated_cost_cny: float = 0.0
    duration_ms: float = 0.0
    unpriced_calls: int = 0
    unpriced_cny_calls: int = 0
    cache_unavailable_calls: int = 0

    def add(self, usage):
        self.llm_calls += 1
        self.input_tokens += usage["input_tokens"]
        self.output_tokens += usage["output_tokens"]
        self.total_tokens += usage["total_tokens"]
        self.cache_hit_tokens += usage["cache_hit_tokens"]
        self.cache_miss_tokens += usage["cache_miss_tokens"]
        self.estimated_cost_usd += usage["estimated_cost_usd"]
        self.estimated_cost_cny += usage.get("estimated_cost_cny") or 0.0
        self.duration_ms += usage.get("duration_ms", 0.0)
        self.unpriced_calls += int(not usage["cost_estimate_available"])
        self.unpriced_cny_calls += int(not usage.get("cost_estimate_cny_available", False))
        self.cache_unavailable_calls += int(not usage.get("cache_usage_available", False))

    def to_dict(self):
        return {
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
            # Numeric subtotal retained for API compatibility. Check availability
            # before displaying this as the complete estimated cost.
            "estimated_cost_usd": round(self.estimated_cost_usd, 10),
            "known_cost_usd": round(self.estimated_cost_usd, 10),
            "estimated_total_cost_usd": round(self.estimated_cost_usd, 10) if self.unpriced_calls == 0 else None,
            "estimated_cost_cny": round(self.estimated_cost_cny, 10) if self.unpriced_cny_calls == 0 else None,
            "known_cost_cny": round(self.estimated_cost_cny, 10),
            "cost_estimate_cny_available": self.unpriced_cny_calls == 0,
            "unpriced_cny_calls": self.unpriced_cny_calls,
            "duration_ms": round(self.duration_ms, 2),
            "unpriced_calls": self.unpriced_calls,
            "cost_estimate_available": self.unpriced_calls == 0,
            "cost_status": "available" if self.unpriced_calls == 0 else "unavailable",
            **cache_usage_summary(self.llm_calls, self.input_tokens, self.cache_hit_tokens,
                                  self.cache_unavailable_calls),
        }


class UsageTracker:
    """Thread-safe request-level LLM usage accumulator."""

    def __init__(self):
        self._lock = Lock()
        self._total = UsageBucket()
        self._by_model = defaultdict(UsageBucket)
        self._by_operation = defaultdict(UsageBucket)
        self._pricing_tiers = set()
        self._unpriced_calls = 0
        self._pricing_warnings = set()

    def record(self, usage):
        with self._lock:
            self._total.add(usage)
            self._by_model[usage["model"]].add(usage)
            self._by_operation[usage["operation"]].add(usage)
            self._pricing_tiers.add(usage["pricing_tier"])
            if not usage["cost_estimate_available"]:
                self._unpriced_calls += 1
                self._pricing_warnings.add(usage.get("pricing_reason") or "Provider usage unavailable; incurred cost is unknown.")

    def summary(self):
        with self._lock:
            total = self._total.to_dict()
            total.update(
                {
                    "currency": "USD",
                    "cost_estimate_available": self._unpriced_calls == 0,
                    "pricing_tiers": sorted(self._pricing_tiers),
                    "pricing_warnings": sorted(self._pricing_warnings),
                    "by_model": {
                        key: bucket.to_dict()
                        for key, bucket in sorted(self._by_model.items())
                    },
                    "by_operation": {
                        key: bucket.to_dict()
                        for key, bucket in sorted(self._by_operation.items())
                    },
                }
            )
            return total


def new_usage_tracker():
    return UsageTracker()


def empty_usage_summary():
    return UsageTracker().summary()


def get_usage_summary(tracker=None):
    tracker = tracker or _usage_tracker_var.get()
    return tracker.summary() if tracker is not None else empty_usage_summary()


@contextmanager
def observability_context(request_id=None, session_id=None, usage_tracker=None):
    tokens = []

    if request_id is not None:
        tokens.append((_request_id_var, _request_id_var.set(request_id)))
    if session_id is not None:
        tokens.append((_session_id_var, _session_id_var.set(session_id)))
    if usage_tracker is not None:
        tokens.append((_usage_tracker_var, _usage_tracker_var.set(usage_tracker)))

    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


def _usage_payload(usage):
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return {
        key: getattr(usage, key)
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
            "prompt_tokens_details",
        )
        if hasattr(usage, key)
    }


def _safe_int(value):
    return value if type(value) is int and value >= 0 else 0


def _cache_usage(payload):
    """Read DeepSeek counters (or the documented OpenAI-compatible fallback).

    A missing split is unknown, not an all-cache-miss request. A single valid
    counter determines the other; conflicting provider fields stay unavailable.
    """
    input_tokens = payload.get("prompt_tokens")
    if type(input_tokens) is not int or input_tokens < 0:
        return 0, 0, "Provider input token count unavailable."
    hit = payload.get("prompt_cache_hit_tokens")
    miss = payload.get("prompt_cache_miss_tokens")
    details = payload.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else getattr(details, "cached_tokens", None)
    for value in (hit, miss, cached):
        if value is not None and (type(value) is not int or not 0 <= value <= input_tokens):
            return 0, 0, "Invalid provider cache token counter."
    if hit is not None and cached is not None and hit != cached:
        return 0, 0, "Provider cache hit counters disagree."
    if hit is None:
        hit = cached
    if hit is None and miss is None:
        return (0, 0, "Provider cache usage unavailable; input cache split is unknown.") if input_tokens else (0, 0, None)
    if hit is None:
        hit = input_tokens - miss
    if miss is None:
        miss = input_tokens - hit
    if hit + miss != input_tokens:
        return 0, 0, "Provider cache hit/miss tokens do not sum to input tokens."
    return hit, miss, None


def _usage_error(payload):
    """Require actual counters and a determinate cache split before pricing."""
    for key in ("prompt_tokens", "completion_tokens"):
        if type(payload.get(key)) is not int or payload[key] < 0:
            return f"Provider usage missing or invalid: {key}."
    for key in ("total_tokens",):
        if key in payload and (type(payload[key]) is not int or payload[key] < 0):
            return f"Invalid provider token counter: {key}."
    input_tokens = payload["prompt_tokens"]
    cache_error = _cache_usage(payload)[2]
    if cache_error:
        return cache_error
    if "total_tokens" in payload and payload["total_tokens"] != input_tokens + payload["completion_tokens"]:
        return "Provider total tokens do not sum to input/output tokens."
    return None


def record_llm_usage(model, operation, usage, duration_ms, at=None):
    """Normalize provider usage, estimate cost, and update the active tracker."""

    payload = _usage_payload(usage)
    if not isinstance(payload, dict):
        payload = {}
    usage_error = _usage_error(payload)
    input_tokens = _safe_int(payload.get("prompt_tokens"))
    output_tokens = _safe_int(payload.get("completion_tokens"))
    total_tokens = _safe_int(
        payload.get("total_tokens") or input_tokens + output_tokens
    )
    cache_hit_tokens, cache_miss_tokens, cache_error = _cache_usage(payload)
    cache_available = cache_error is None and input_tokens > 0
    pricing_at = at or datetime.now(timezone.utc)
    pricing = get_model_pricing(model, at=pricing_at)
    cost_available = pricing["available"] and usage_error is None
    estimated_cost = (
        cache_hit_tokens * pricing["cache_hit"]
        + cache_miss_tokens * pricing["cache_miss"]
        + output_tokens * pricing["output"]
    ) / 1_000_000
    pricing_cny = get_model_pricing(model, at=pricing_at, currency="CNY")
    cost_cny_available = pricing_cny["available"] and usage_error is None
    estimated_cost_cny = (
        cache_hit_tokens * pricing_cny["cache_hit"]
        + cache_miss_tokens * pricing_cny["cache_miss"]
        + output_tokens * pricing_cny["output"]
    ) / 1_000_000
    normalized = {
        "model": model,
        "operation": operation,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_hit_tokens": cache_hit_tokens,
        "cache_miss_tokens": cache_miss_tokens,
        **cache_usage_summary(1, input_tokens, cache_hit_tokens, int(not cache_available)),
        "cache_usage_reason": cache_error or ("No input tokens available for a cache rate." if not input_tokens else None),
        "estimated_cost_usd": round(estimated_cost, 10) if cost_available else 0.0,
        "estimated_total_cost_usd": round(estimated_cost, 10) if cost_available else None,
        "estimated_cost_cny": round(estimated_cost_cny, 10) if cost_cny_available else None,
        "cost_estimate_cny_available": cost_cny_available,
        "pricing_cny_reason": pricing_cny.get("reason") or usage_error,
        "pricing_cny_tier": pricing_cny["tier"],
        "cost_status": "available" if cost_available else "unavailable",
        "pricing_reason": pricing.get("reason") or usage_error,
        "call_started_at": at.isoformat() if at else None,
        "currency": "USD",
        "pricing_tier": pricing["tier"],
        "cost_estimate_available": cost_available,
        "usage_available": usage_error is None,
        "duration_ms": round(duration_ms, 2),
    }

    tracker = _usage_tracker_var.get()
    if tracker is not None:
        tracker.record(normalized)

    return normalized


class RequestContextMiddleware:
    """Attach request IDs and log full HTTP response duration, including SSE."""

    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger("app.http")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        candidate = headers.get("x-request-id", "").strip()
        request_id = (
            candidate if REQUEST_ID_PATTERN.fullmatch(candidate) else uuid4().hex
        )
        scope.setdefault("state", {})["request_id"] = request_id
        started_at = perf_counter()
        status_code = 500
        completed = False

        async def send_with_context(message):
            nonlocal status_code, completed

            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = list(message.get("headers", []))
                if not any(
                    key.lower() == b"x-request-id"
                    for key, _value in response_headers
                ):
                    response_headers.append(
                        (b"x-request-id", request_id.encode("ascii"))
                    )
                message["headers"] = response_headers

            if (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
                and not completed
            ):
                completed = True
                log_event(
                    self.logger,
                    logging.INFO,
                    "http_request_completed",
                    method=scope["method"],
                    path=scope["path"],
                    status_code=status_code,
                    duration_ms=round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                )

            await send(message)

        with observability_context(request_id=request_id):
            log_event(
                self.logger,
                logging.INFO,
                "http_request_started",
                method=scope["method"],
                path=scope["path"],
            )
            try:
                await self.app(scope, receive, send_with_context)
            except Exception:
                log_event(
                    self.logger,
                    logging.ERROR,
                    "http_request_failed",
                    exc_info=True,
                    method=scope["method"],
                    path=scope["path"],
                    duration_ms=round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                )
                raise
