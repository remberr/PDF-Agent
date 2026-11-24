import math
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import psycopg
from sqlalchemy.exc import OperationalError

from app.db.config import DatabaseConfigurationError, load_database_settings
from app.db.engine import create_database_engine


URL = "postgresql://developer:p%40ss%2Fword%3A%25@127.0.0.1:55432/pdf_agent_test"


class DatabaseConfigurationTests(unittest.TestCase):
    def test_official_url_aliases_and_encoded_password(self):
        for scheme in ("postgres", "postgresql", "postgresql+psycopg"):
            with self.subTest(scheme=scheme):
                settings = load_database_settings({"DATABASE_URL": URL.replace("postgresql:", scheme + ":")})
                self.assertEqual(settings.url.drivername, "postgresql+psycopg")
                self.assertEqual(settings.url.password, "p@ss/word:%")
                self.assertEqual(settings.url.port, 55432)
                self.assertEqual(settings.pool_size, 5)
                self.assertEqual(settings.max_overflow, 0)
                self.assertEqual(settings.pool_timeout_seconds, 5)
                self.assertEqual(settings.connect_timeout_seconds, 5)
                self.assertNotIn("p@ss", repr(settings))
                self.assertNotIn("p%40ss", repr(settings))

    def test_missing_or_invalid_url_fails_without_disclosing_input(self):
        for value in (None, "", "secret-marker", "sqlite:///secret-marker",
                      "postgresql+psycopg2://u:secret-marker@localhost/db",
                      "postgresql://u:secret-marker@localhost:bad/db",
                      "postgresql://u:secret-marker@localhost:65536/db",
                      "postgresql://u:secret-marker@/db", "postgresql://localhost/db",
                      "postgresql://u:secret-marker@localhost"):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(DatabaseConfigurationError) as caught:
                    load_database_settings({} if value is None else {"DATABASE_URL": value})
                self.assertNotIn("secret-marker", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    def test_pool_settings_validate_and_override_defaults(self):
        settings = load_database_settings({"DATABASE_URL": URL, "DB_POOL_SIZE": "2",
            "DB_MAX_OVERFLOW": "1", "DB_POOL_TIMEOUT_SECONDS": "0.25",
            "DB_CONNECT_TIMEOUT_SECONDS": "3"})
        self.assertEqual((settings.pool_size, settings.max_overflow,
                          settings.pool_timeout_seconds, settings.connect_timeout_seconds), (2, 1, .25, 3))
        for key in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT_SECONDS", "DB_CONNECT_TIMEOUT_SECONDS"):
            for value in ("", "-1", "nan", "inf", "secret-marker"):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(DatabaseConfigurationError) as caught:
                        load_database_settings({"DATABASE_URL": URL, key: value})
                    self.assertNotIn("secret-marker", str(caught.exception))
            if key != "DB_MAX_OVERFLOW":
                with self.assertRaises(DatabaseConfigurationError):
                    load_database_settings({"DATABASE_URL": URL, key: "0"})
        self.assertTrue(math.isfinite(settings.pool_timeout_seconds))

    def test_server_sql_timeouts_are_positive_explicit_and_configurable(self):
        settings=load_database_settings({'DATABASE_URL':URL,'DB_LOCK_TIMEOUT_MS':'150','DB_STATEMENT_TIMEOUT_MS':'750'})
        self.assertEqual((settings.lock_timeout_ms,settings.statement_timeout_ms),(150,750))
        for key in ('DB_LOCK_TIMEOUT_MS','DB_STATEMENT_TIMEOUT_MS'):
            for value in ('0','-1','nan','1.5','secret-marker'):
                with self.subTest(key=key,value=value),self.assertRaises(DatabaseConfigurationError):
                    load_database_settings({'DATABASE_URL':URL,key:value})

    def test_query_cannot_override_host_timeout_or_timezone(self):
        for query in ("host=remote", "password=secret-marker", "connect_timeout=0",
                      "options=-c%20timezone=Asia/Shanghai", "service=production",
                      "sslmode=require&sslmode=disable"):
            with self.subTest(query=query):
                with self.assertRaises(DatabaseConfigurationError):
                    load_database_settings({"DATABASE_URL": URL + "?" + query})
        settings = load_database_settings({"DATABASE_URL": URL + "?sslmode=verify-full&sslrootcert=ca.pem"})
        self.assertEqual(settings.url.query["sslmode"], "verify-full")

    def test_test_url_never_falls_back_to_application_url(self):
        with self.assertRaises(DatabaseConfigurationError):
            load_database_settings({"DATABASE_URL": URL}, url_variable="TEST_DATABASE_URL")
        settings = load_database_settings({"DATABASE_URL": "invalid", "TEST_DATABASE_URL": URL},
                                          url_variable="TEST_DATABASE_URL")
        self.assertEqual(settings.url.database, "pdf_agent_test")

    def test_engine_is_lazy_and_hides_parameters(self):
        settings = load_database_settings({"DATABASE_URL": URL})
        with patch("psycopg.connect", side_effect=AssertionError("unexpected connection")):
            engine = create_database_engine(settings)
            self.addCleanup(engine.dispose)
            self.assertEqual(engine.pool.checkedout(), 0)
            self.assertEqual(engine.pool.size(), 5)
            self.assertFalse(engine.echo)
            self.assertTrue(engine.hide_parameters)
            self.assertNotIn("p@ss", repr(engine))

    def test_driver_receives_bounded_timeout_and_utc(self):
        settings = load_database_settings({"DATABASE_URL": URL, "DB_CONNECT_TIMEOUT_SECONDS": "3"})
        engine = create_database_engine(settings)
        self.addCleanup(engine.dispose)
        with patch("psycopg.connect", side_effect=psycopg.OperationalError("fixture refusal")) as connect:
            with self.assertRaises(OperationalError):
                engine.connect()
        self.assertEqual(connect.call_args.kwargs["connect_timeout"], 3)
        self.assertEqual(connect.call_args.kwargs["options"], "-c timezone=UTC -c lock_timeout=3000 -c statement_timeout=10000")
        self.assertEqual(engine.pool.checkedout(), 0)

    def test_module_import_does_not_read_configuration_or_connect(self):
        # A fresh interpreter avoids passing merely because unittest discovery
        # already imported app.main through another test module.
        script = """
from unittest.mock import patch
with patch('psycopg.connect', side_effect=AssertionError('unexpected PG connection')), \\
     patch('sqlite3.connect', side_effect=AssertionError('unexpected SQLite connection')), \\
     patch('sqlalchemy.create_engine', side_effect=AssertionError('unexpected engine')):
    import app.db.config
    import app.db.engine
    import app.main
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "DATABASE_URL": "invalid", "HF_HUB_OFFLINE": "1",
                 "DEEPSEEK_API_KEY": "offline-test-placeholder"},
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
