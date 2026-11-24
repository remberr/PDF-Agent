"""Lazy engine factory; lifecycle ownership will be wired in T15c."""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from app.db.config import DatabaseSettings


def create_database_engine(settings: DatabaseSettings, *, migration: bool = False) -> Engine:
    """Create one Engine per owning process, without connecting or creating DDL.

    The owner must dispose it on shutdown. Acquire/release a Connection in the
    same thread with ``engine.begin()`` for each short transaction; never retain
    one across model calls, embedding work or SSE yields. pre_ping repairs stale
    pooled connections, but does not retry an interrupted transaction.
    """
    pool_options = ({'poolclass': NullPool} if migration else {
        'pool_size': settings.pool_size, 'max_overflow': settings.max_overflow,
        'pool_timeout': settings.pool_timeout_seconds, 'pool_pre_ping': True,
    })
    engine = create_engine(
        settings.url,
        **pool_options,
        connect_args={
            "connect_timeout": settings.connect_timeout_seconds,
            "options": f"-c timezone=UTC -c lock_timeout={settings.lock_timeout_ms} -c statement_timeout={settings.statement_timeout_ms}",
        },
        echo=False,
        hide_parameters=True,
    )
    @event.listens_for(engine, 'before_cursor_execute')
    def request_deadline(connection, cursor, statement, parameters, context, many):
        # Default server timeouts also cover pre-ping/queries outside workflows.
        # SET LOCAL expires at transaction end, so pooled clients cannot inherit
        # another request's remaining deadline. Cleanup has its own bounded SQL.
        if context.execution_options.get('skip_request_budget'):
            return
        from utils.observability import get_active_usage_tracker
        tracker = get_active_usage_tracker()
        if tracker is None:
            return
        tracker.budget.check_admitted()
        remaining = max(1, int(tracker.budget.remaining_seconds() * 1000))
        cursor.execute("SELECT set_config('statement_timeout', %s, true), set_config('lock_timeout', %s, true)",
                       (str(min(settings.statement_timeout_ms, remaining)),
                        str(min(settings.lock_timeout_ms, remaining))))
    return engine
