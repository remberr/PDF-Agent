"""Lazy engine factory; lifecycle ownership will be wired in T15c."""

from sqlalchemy import create_engine
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
    return create_engine(
        settings.url,
        **pool_options,
        connect_args={
            "connect_timeout": settings.connect_timeout_seconds,
            "options": "-c timezone=UTC",
        },
        echo=False,
        hide_parameters=True,
    )
