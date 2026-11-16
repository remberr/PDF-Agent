"""Opt-in tests against a disposable loopback PostgreSQL 17 database only."""

import os
import socket
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, TimeoutError

from app.db.config import DatabaseConfigurationError, load_database_settings
from app.db.engine import create_database_engine


def local_test_settings(environ):
    settings = load_database_settings(environ, url_variable="TEST_DATABASE_URL")
    if settings.url.host not in {"127.0.0.1", "::1", "localhost"} or not settings.url.database.endswith("_test"):
        raise DatabaseConfigurationError("PostgreSQL tests require a loopback host and a database ending in _test.")
    return settings


class PostgresTestSafetyTests(unittest.TestCase):
    def test_requires_explicit_test_url(self):
        with self.assertRaises(DatabaseConfigurationError):
            local_test_settings({"DATABASE_URL": "postgresql://u:p@127.0.0.1/production"})

    def test_rejects_remote_and_non_test_database(self):
        for target in ("remote.example/pdf_agent_test", "127.0.0.1/production"):
            with self.subTest(target=target), self.assertRaises(DatabaseConfigurationError):
                local_test_settings({"TEST_DATABASE_URL": "postgresql://u:p@" + target})


@unittest.skipUnless(os.environ.get("PDF_AGENT_RUN_POSTGRES_TESTS") == "1", "opt-in local PostgreSQL test")
class PostgresConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Opted-in but missing/unreachable DB is an error, never a skip/fallback.
        cls.settings = local_test_settings(os.environ)
        probe = create_database_engine(cls.settings)
        try:
            with probe.connect() as connection:
                version = int(connection.scalar(text("SHOW server_version_num")))
                if not 170000 <= version < 180000:
                    raise RuntimeError("The integration suite requires PostgreSQL 17.")
        finally:
            probe.dispose()

    def new_engine(self, **overrides):
        engine = create_database_engine(replace(self.settings, **overrides))
        self.addCleanup(engine.dispose)
        return engine

    def test_connect_utc_and_release(self):
        engine = self.new_engine()
        with engine.begin() as connection:
            self.assertEqual(connection.scalar(text("SELECT current_database()")), self.settings.url.database)
            self.assertEqual(connection.scalar(text("SHOW timezone")), "UTC")
        self.assertEqual(engine.pool.checkedout(), 0)

    def test_commit_rollback_and_pool_return(self):
        engine = self.new_engine(pool_size=1, max_overflow=0)
        with engine.begin() as connection:
            connection.execute(text("CREATE TEMP TABLE t15a_transaction (value integer)"))
            connection.execute(text("INSERT INTO t15a_transaction VALUES (1)"))
        with self.assertRaisesRegex(RuntimeError, "rollback fixture"):
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO t15a_transaction VALUES (2)"))
                raise RuntimeError("rollback fixture")
        with engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM t15a_transaction")), 1)
        self.assertEqual(engine.pool.checkedout(), 0)

    def test_pool_exhaustion_is_bounded_then_reusable(self):
        engine = self.new_engine(pool_size=1, max_overflow=0, pool_timeout_seconds=.2)
        with engine.connect():
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                with engine.connect():
                    self.fail("Pool must not exceed the configured limit")
            elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, .15)
            self.assertLess(elapsed, 2)
        with engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT 1")), 1)
        self.assertEqual(engine.pool.checkedout(), 0)

    def test_threads_acquire_distinct_connections(self):
        engine = self.new_engine(pool_size=2, max_overflow=0)
        barrier = threading.Barrier(2, timeout=5)

        def query():
            with engine.begin() as connection:
                pid = connection.scalar(text("SELECT pg_backend_pid()"))
                identity = id(connection)
                barrier.wait()
                return pid, identity

        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = list(executor.map(lambda _: query(), range(2)))
        self.assertNotEqual(first[0], second[0])
        self.assertNotEqual(first[1], second[1])
        self.assertEqual(engine.pool.checkedout(), 0)

    def terminate_own_backend(self, pid):
        # Only terminate the exact PID opened by this test, never other clients.
        control = self.new_engine(pool_size=1, max_overflow=0)
        with control.begin() as connection:
            self.assertTrue(connection.scalar(text("SELECT pg_terminate_backend(:pid, 2000)"), {"pid": pid}))

    def test_pre_ping_replaces_dead_idle_connection(self):
        engine = self.new_engine(pool_size=1, max_overflow=0)
        with engine.connect() as connection:
            old_pid = connection.scalar(text("SELECT pg_backend_pid()"))
        self.terminate_own_backend(old_pid)
        with engine.connect() as connection:
            self.assertNotEqual(connection.scalar(text("SELECT pg_backend_pid()")), old_pid)
        self.assertEqual(engine.pool.checkedout(), 0)

    def test_disconnect_aborts_transaction_without_replay(self):
        engine = self.new_engine(pool_size=1, max_overflow=0)
        with self.assertRaises(DBAPIError) as caught:
            with engine.begin() as connection:
                pid = connection.scalar(text("SELECT pg_backend_pid()"))
                self.terminate_own_backend(pid)
                connection.execute(text("SELECT 1"))
        self.assertTrue(caught.exception.connection_invalidated)
        with engine.begin() as connection:
            self.assertEqual(connection.scalar(text("SELECT 1")), 1)
        self.assertEqual(engine.pool.checkedout(), 0)

    def test_unavailable_server_fails_without_password_disclosure(self):
        # Bind without listening: known-local refused endpoint, not a real DB.
        with socket.socket() as endpoint:
            endpoint.bind(("127.0.0.1", 0))
            url = self.settings.url.set(host="127.0.0.1", port=endpoint.getsockname()[1])
            engine = self.new_engine(url=url, connect_timeout_seconds=2)
            started = time.monotonic()
            with self.assertRaises(OperationalError) as caught:
                engine.connect()
            self.assertLess(time.monotonic() - started, 6)
            if url.password:
                self.assertNotIn(url.password, str(caught.exception))
            self.assertEqual(engine.pool.checkedout(), 0)


if __name__ == "__main__":
    unittest.main()
