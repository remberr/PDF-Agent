import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main import app
from app.services import session_store


class SessionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)

        self.settings = patch.multiple(
            session_store,
            DATA_DIR=data_dir,
            VECTORSTORE_DIR=data_dir / "vectorstores",
            DB_PATH=data_dir / "sessions.db",
            SESSION_TTL_SECONDS=100,
            SESSION_CLEANUP_INTERVAL_SECONDS=10,
        )
        self.settings.start()
        session_store.init_session_store()

    def tearDown(self):
        self.settings.stop()
        self.temp_dir.cleanup()

    def test_existing_database_is_migrated_with_lifecycle_columns(self):
        session_store.DB_PATH.unlink()

        with sqlite3.connect(session_store.DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE sessions (
                    session_id TEXT PRIMARY KEY,
                    loaded_pdfs TEXT NOT NULL,
                    messages TEXT NOT NULL,
                    vectorstore_path TEXT,
                    document_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                INSERT INTO sessions VALUES (?, ?, ?, ?, ?)
                """,
                ("a" * 32, "[]", "[]", None, 0),
            )

        session_store.init_session_store()

        with sqlite3.connect(session_store.DB_PATH) as conn:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(sessions)")
            }
            timestamps = conn.execute(
                "SELECT created_at, updated_at FROM sessions"
            ).fetchone()

        self.assertIn("created_at", columns)
        self.assertIn("updated_at", columns)
        self.assertTrue(all(timestamp > 0 for timestamp in timestamps))

    def test_session_access_refreshes_ttl_and_cleanup_removes_expired_data(self):
        with patch.object(session_store.time, "time", return_value=1000):
            session_id = session_store.create_session()

        vectorstore_path = session_store.get_vectorstore_path(session_id)
        vectorstore_path.mkdir(parents=True)
        (vectorstore_path / "marker").write_text("test", encoding="utf-8")

        with patch.object(session_store.time, "time", return_value=1050):
            session = session_store.get_session(session_id)

        self.assertIsNotNone(session)
        self.assertEqual(session["updated_at"], 1050)

        active_result = session_store.cleanup_expired_sessions(now=1149)
        self.assertEqual(active_result["expired_sessions"], 0)
        self.assertTrue(vectorstore_path.exists())

        expired_result = session_store.cleanup_expired_sessions(now=1150)
        self.assertEqual(expired_result["expired_sessions"], 1)
        self.assertFalse(vectorstore_path.exists())
        self.assertIsNone(session_store.get_session(session_id))

    def test_delete_session_removes_database_row_and_vectorstore(self):
        session_id = session_store.create_session()
        vectorstore_path = session_store.get_vectorstore_path(session_id)
        vectorstore_path.mkdir(parents=True)
        (vectorstore_path / "marker").write_text("test", encoding="utf-8")

        self.assertTrue(session_store.delete_session(session_id))
        self.assertFalse(vectorstore_path.exists())
        self.assertIsNone(session_store.get_session(session_id))
        self.assertFalse(session_store.delete_session(session_id))

    def test_cleanup_removes_orphaned_vectorstore(self):
        orphan_path = session_store.get_vectorstore_path("b" * 32)
        orphan_path.mkdir(parents=True)
        (orphan_path / "marker").write_text("test", encoding="utf-8")

        result = session_store.cleanup_expired_sessions()

        self.assertEqual(result["orphaned_vectorstores"], 1)
        self.assertFalse(orphan_path.exists())

    def test_openapi_exposes_delete_session_endpoint(self):
        operation = app.openapi()["paths"]["/sessions/{session_id}"]
        self.assertIn("delete", operation)
        self.assertEqual(operation["delete"]["responses"].get("204"), {
            "description": "Successful Response"
        })


if __name__ == "__main__":
    unittest.main()
