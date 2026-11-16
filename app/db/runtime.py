"""Shared process engine, created explicitly and disposed on application shutdown."""
from threading import Lock
from sqlalchemy import text
from app.db.config import load_database_settings
from app.db.engine import create_database_engine

_engine = None
_lock = Lock()
SCHEMA_REVISION = '0002_vectors'


def get_engine():
    global _engine
    with _lock:
        if _engine is None:
            _engine = create_database_engine(load_database_settings())
        return _engine


def verify_schema(engine=None):
    with (engine if engine is not None else get_engine()).connect() as connection:
        if connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all() != [SCHEMA_REVISION]:
            raise RuntimeError('Database schema mismatch; run the explicit migration command.')
        if not connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'")):
            raise RuntimeError('Required vector extension is missing.')


def dispose_engine():
    global _engine
    with _lock:
        if _engine is not None:
            _engine.dispose()
            _engine = None
