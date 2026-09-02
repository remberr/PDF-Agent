import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

from utils.vectorstore import load_vectorstore


DATA_DIR = Path(os.getenv("PDF_AGENT_DATA_DIR", "app/data")).expanduser()
VECTORSTORE_DIR = DATA_DIR / "vectorstores"
DB_PATH = DATA_DIR / "sessions.db"


def init_session_store():
    """
    Initialize the SQLite-backed session store.
    """

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                loaded_pdfs TEXT NOT NULL,
                messages TEXT NOT NULL,
                vectorstore_path TEXT,
                document_count INTEGER NOT NULL DEFAULT 0
            )
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

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id,
                loaded_pdfs,
                messages,
                vectorstore_path,
                document_count
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                json.dumps([]),
                json.dumps([]),
                vectorstore_path,
                0
            )
        )
        conn.commit()

    return session_id


def get_session(session_id):
    """
    Return a session by ID, or None when it does not exist.
    """

    init_session_store()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT
                session_id,
                loaded_pdfs,
                messages,
                vectorstore_path,
                document_count
            FROM sessions
            WHERE session_id = ?
            """,
            (session_id,)
        ).fetchone()

    if row is None:
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
        "document_count": row["document_count"]
    }


def save_session(session):
    """
    Persist mutable session metadata to SQLite.
    """

    init_session_store()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE sessions
            SET
                loaded_pdfs = ?,
                messages = ?,
                vectorstore_path = ?,
                document_count = ?
            WHERE session_id = ?
            """,
            (
                json.dumps(session["loaded_pdfs"]),
                json.dumps(session["messages"]),
                session.get("vectorstore_path"),
                session.get("document_count", 0),
                session["session_id"]
            )
        )
        conn.commit()
