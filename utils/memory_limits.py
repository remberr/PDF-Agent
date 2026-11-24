"""Bounded context windows; persistence retains complete historical records."""
import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryLimits:
    history_messages: int = 100
    history_bytes: int = 24000
    recent_bytes: int = 8000
    summary_bytes: int = 4000
    session_bytes: int = 4000
    cache_entries: int = 128
    cache_ttl_seconds: float = 900


def load_memory_limits() -> MemoryLimits:
    names = {
        'history_messages': ('MEMORY_HISTORY_MAX_MESSAGES', 1000),
        'history_bytes': ('MEMORY_HISTORY_MAX_BYTES', 1_000_000),
        'recent_bytes': ('MEMORY_RECENT_MAX_BYTES', 100000),
        'summary_bytes': ('MEMORY_SUMMARY_MAX_BYTES', 16000),
        'session_bytes': ('MEMORY_SESSION_MAX_BYTES', 16000),
        'cache_entries': ('MEMORY_CACHE_MAX_ENTRIES', 1024),
        'cache_ttl_seconds': ('MEMORY_CACHE_TTL_SECONDS', 86400),
    }
    defaults = MemoryLimits()
    values = {}
    for field, (name, maximum) in names.items():
        try:
            value = (float if field == 'cache_ttl_seconds' else int)(os.getenv(name, str(getattr(defaults, field))))
            if not math.isfinite(value) or not 0 < value <= maximum:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f'{name} must be positive and <= {maximum}.') from None
        values[field] = value
    if values['recent_bytes'] > values['history_bytes']:
        raise ValueError('MEMORY_RECENT_MAX_BYTES must not exceed MEMORY_HISTORY_MAX_BYTES.')
    return MemoryLimits(**values)


class HistoryWindow(list):
    def __init__(self, values, total_count: int):
        super().__init__(values)
        self.total_count = total_count
