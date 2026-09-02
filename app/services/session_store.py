import json
import logging
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from utils.vectorstore import load_vectorstore
from utils.observability import log_event


DATA_DIR = Path(os.getenv("PDF_AGENT_DATA_DIR", "app/data")).expanduser()
VECTORSTORE_DIR = DATA_DIR / "vectorstores"
DB_PATH = DATA_DIR / "sessions.db"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "86400"))
SESSION_CLEANUP_INTERVAL_SECONDS = int(
    os.getenv("SESSION_CLEANUP_INTERVAL_SECONDS", "3600")
)

logger = logging.getLogger(__name__)
SESSION_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _validate_lifecycle_settings():
    if SESSION_TTL_SECONDS <= 0:
        raise ValueError("SESSION_TTL_SECONDS must be greater than zero.")

    if SESSION_CLEANUP_INTERVAL_SECONDS <= 0:
        raise ValueError(
            "SESSION_CLEANUP_INTERVAL_SECONDS must be greater than zero."
        )


def init_session_store():
    """
    Initialize the SQLite-backed session store.
    """

    _validate_lifecycle_settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)

    now = int(time.time())

    with _connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                loaded_pdfs TEXT NOT NULL,
                messages TEXT NOT NULL,
                vectorstore_path TEXT,
                document_count INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )

        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }

        if "created_at" not in columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN created_at INTEGER")

        if "updated_at" not in columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN updated_at INTEGER")

        conn.execute(
            """
            UPDATE sessions
            SET
                created_at = COALESCE(created_at, ?),
                updated_at = COALESCE(updated_at, ?)
            WHERE created_at IS NULL OR updated_at IS NULL
            """,
            (now, now),
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
            ON sessions(updated_at)
            """
        )
        conn.commit()


def get_vectorstore_path(session_id):
    """
    Return the persisted FAISS path for a session.
    """

    return VECTORSTORE_DIR / session_id


def vectorstore_exists(path):
    """
    Return whether a persisted FAISS vectorstore exists.
    """

    path = Path(path)

    return (
        (path / "index.faiss").exists()
        and (path / "index.pkl").exists()
    )


def create_session():
    """
    Create a SQLite-backed PDF analysis session.
    """

    init_session_store()

    session_id = uuid4().hex
    vectorstore_path = str(get_vectorstore_path(session_id))
    now = int(time.time())

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id,
                loaded_pdfs,
                messages,
                vectorstore_path,
                document_count,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                json.dumps([]),
                json.dumps([]),
                vectorstore_path,
                0,
                now,
                now,
            )
        )
        conn.commit()

    log_event(
        logger,
        logging.INFO,
        "session_created",
        session_id=session_id,
        ttl_seconds=SESSION_TTL_SECONDS,
    )
    return session_id


def get_session(session_id):
    """
    Return a session by ID, or None when it does not exist.
    """

    init_session_store()

    now = int(time.time())
    expired = False

    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT
                session_id,
                loaded_pdfs,
                messages,
                vectorstore_path,
                document_count,
                created_at,
                updated_at
            FROM sessions
            WHERE session_id = ?
            """,
            (session_id,)
        ).fetchone()

        if row is None:
            return None

        if row["updated_at"] <= now - SESSION_TTL_SECONDS:
            conn.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            expired = True
        else:
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            conn.commit()

    if expired:
        remove_session_vectorstore_safely(session_id, "expired")
        return None

    vectorstore_path = row["vectorstore_path"]
    vectorstore = None

    if vectorstore_path and vectorstore_exists(vectorstore_path):
        vectorstore = load_vectorstore(vectorstore_path)

    return {
        "session_id": row["session_id"],
        "loaded_pdfs": json.loads(row["loaded_pdfs"]),
        "messages": json.loads(row["messages"]),
        "vectorstore": vectorstore,
        "vectorstore_path": vectorstore_path,
        "document_count": row["document_count"],
        "created_at": row["created_at"],
        "updated_at": now,
    }


def save_session(session):
    """
    Persist mutable session metadata to SQLite.
    """

    init_session_store()

    now = int(time.time())

    with _connect() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET
                loaded_pdfs = ?,
                messages = ?,
                vectorstore_path = ?,
                document_count = ?,
                updated_at = ?
            WHERE session_id = ?
            """,
            (
                json.dumps(session["loaded_pdfs"]),
                json.dumps(session["messages"]),
                session.get("vectorstore_path"),
                session.get("document_count", 0),
                now,
                session["session_id"]
            )
        )
        conn.commit()

    session["updated_at"] = now


def remove_session_vectorstore(session_id):
    """
    Remove a session's FAISS directory without trusting stored paths.
    """

    if not SESSION_ID_PATTERN.fullmatch(session_id):
        log_event(
            logger,
            logging.WARNING,
            "vectorstore_delete_rejected",
            reason="invalid_session_id",
        )
        return False

    vectorstore_root = VECTORSTORE_DIR.resolve()
    vectorstore_path = get_vectorstore_path(session_id).resolve()

    if vectorstore_path.parent != vectorstore_root:
        log_event(
            logger,
            logging.WARNING,
            "vectorstore_delete_rejected",
            reason="outside_vectorstore_root",
        )
        return False

    if not vectorstore_path.exists():
        return False

    shutil.rmtree(vectorstore_path)
    return True


def remove_session_vectorstore_safely(session_id, reason):
    """
    Remove a FAISS directory without failing the session lifecycle operation.
    """

    try:
        return remove_session_vectorstore(session_id)
    except OSError:
        log_event(
            logger,
            logging.ERROR,
            "vectorstore_delete_failed",
            exc_info=True,
            session_id=session_id,
            reason=reason,
        )
        return False


def delete_session(session_id):
    """
    Delete one session and its persisted FAISS index.
    """

    init_session_store()

    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()

    if cursor.rowcount == 0:
        return False

    remove_session_vectorstore_safely(session_id, "deleted")

    log_event(
        logger,
        logging.INFO,
        "session_deleted",
        session_id=session_id,
    )

    return True


def cleanup_expired_sessions(now=None):
    """
    Delete idle sessions and FAISS directories that no longer have a session.
    """

    init_session_store()

    current_time = int(time.time()) if now is None else int(now)
    expiration_cutoff = current_time - SESSION_TTL_SECONDS

    with _connect() as conn:
        expired_session_ids = [
            row[0]
            for row in conn.execute(
                """
                SELECT session_id
                FROM sessions
                WHERE updated_at <= ?
                """,
                (expiration_cutoff,),
            ).fetchall()
        ]

        conn.execute(
            "DELETE FROM sessions WHERE updated_at <= ?",
            (expiration_cutoff,),
        )
        active_session_ids = {
            row[0]
            for row in conn.execute("SELECT session_id FROM sessions").fetchall()
        }
        conn.commit()

    for session_id in expired_session_ids:
        remove_session_vectorstore_safely(session_id, "expired")

    orphan_count = 0
    for path in VECTORSTORE_DIR.iterdir():
        if not path.is_dir() or path.name in active_session_ids:
            continue

        if remove_session_vectorstore_safely(path.name, "orphaned"):
            orphan_count += 1

    deleted_count = len(expired_session_ids)
    if deleted_count or orphan_count:
        log_event(
            logger,
            logging.INFO,
            "session_cleanup_completed",
            expired_sessions=deleted_count,
            orphaned_vectorstores=orphan_count,
        )

    return {
        "expired_sessions": deleted_count,
        "orphaned_vectorstores": orphan_count,
    }
