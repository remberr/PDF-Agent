"""Explicit migration entry point. No credentials stored in alembic.ini."""
from alembic import context
from app.db.config import load_database_settings
from app.db.engine import create_database_engine
from app.db.schema import metadata

if context.is_offline_mode():
    raise RuntimeError('Offline SQL generation is not supported; use an isolated PostgreSQL database.')

provided = context.config.attributes.get('connection')
if provided is not None:
    context.configure(connection=provided, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_database_engine(load_database_settings(), migration=True)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
