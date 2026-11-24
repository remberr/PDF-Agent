import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text, update, event, func
from sqlalchemy.exc import OperationalError
from app.db.engine import create_database_engine
from app.db.schema import sessions
from app.services import postgres_store as store
from tests.test_postgres_connection import local_test_settings


@unittest.skipUnless(os.getenv('PDF_AGENT_RUN_POSTGRES_TESTS') == '1', 'opt-in local PostgreSQL test')
class SessionConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = local_test_settings(os.environ)
        cls.engine = create_database_engine(cls.settings)
        with cls.engine.begin() as connection:
            config = Config('alembic.ini'); config.attributes['connection'] = connection
            command.upgrade(config, 'head')

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        p = patch.object(store, 'get_engine', return_value=self.engine); p.start(); self.addCleanup(p.stop)
        p = patch.dict(os.environ, {'SESSION_RETENTION_ENABLED':'true'}); p.start(); self.addCleanup(p.stop)
        self.sid = store.create_session()
        self.addCleanup(lambda: store.delete_session(self.sid))

    def test_activity_time_is_read_after_row_lock_and_never_moves_backwards(self):
        waiting, clock_read = threading.Event(), threading.Event()
        def before(conn, cursor, statement, parameters, context, many):
            if 'FOR UPDATE' in statement: waiting.set()
        def clock(value=None):
            clock_read.set(); return original(1000 if value is None else value)
        original = store.timestamp
        with self.engine.begin() as holder:
            holder.execute(update(sessions).where(sessions.c.session_id==self.sid).values(updated_at=original(2000)))
        event.listen(self.engine, 'before_cursor_execute', before)
        try:
            with self.engine.connect() as holder, ThreadPoolExecutor(1) as pool:
                tx = holder.begin()
                holder.execute(select(sessions).where(sessions.c.session_id==self.sid).with_for_update())
                waiting.clear()
                try:
                    with patch.object(store, 'timestamp', side_effect=clock), patch.object(store, 'SESSION_TTL_SECONDS', 100000):
                        future=pool.submit(store.get_session,self.sid)
                        self.assertTrue(waiting.wait(3))
                        self.assertFalse(clock_read.is_set(), 'Wall clock must be sampled after acquiring row lock')
                        tx.commit()
                        snapshot=future.result(timeout=3)
                        self.assertEqual(snapshot['updated_at'],2000)
                finally:
                    if tx.is_active: tx.rollback()
        finally: event.remove(self.engine,'before_cursor_execute',before)

    def test_active_request_crosses_ttl_then_cleanup_after_release(self):
        with patch.object(store, 'SESSION_TTL_SECONDS', 10), patch.object(store.time,'time',return_value=1000):
            with self.engine.begin() as c:
                c.execute(update(sessions).where(sessions.c.session_id==self.sid).values(updated_at=store.timestamp(1000)))
            lease=store.acquire_session_lease(self.sid,60)
            self.assertEqual(self.engine.pool.checkedout(),0)
            with patch.object(store.time,'time',return_value=1030):
                self.assertEqual(store.cleanup_expired_sessions()['expired_sessions'],0)
                snapshot=store.get_session(self.sid)
                snapshot['messages'].append({'role':'user','content':'during request'})
                store.save_session(snapshot)
                store.release_session_lease(self.sid,lease)
            with patch.object(store.time,'time',return_value=1041):
                self.assertEqual(store.cleanup_expired_sessions()['expired_sessions'],1)

    def test_crashed_lease_expires_and_explicit_delete_is_not_blocked(self):
        with patch.object(store, 'SESSION_TTL_SECONDS', 10), patch.object(store.time,'time',return_value=1000):
            with self.engine.begin() as c:
                c.execute(update(sessions).where(sessions.c.session_id==self.sid).values(updated_at=store.timestamp(1000)))
            store.acquire_session_lease(self.sid,20)
            with patch.object(store.time,'time',return_value=1021):
                self.assertEqual(store.cleanup_expired_sessions()['expired_sessions'],1)
        self.sid=store.create_session()
        snapshot=store.get_session(self.sid)
        lease=store.acquire_session_lease(self.sid,20)
        self.assertTrue(store.delete_session(self.sid))
        store.release_session_lease(self.sid,lease)
        snapshot['messages'].append({'role':'user','content':'late'})
        with self.assertRaises(LookupError): store.save_session(snapshot)

    def test_lock_timeout_rolls_back_and_returns_connection(self):
        settings=replace(self.settings,lock_timeout_ms=100,statement_timeout_ms=1000)
        engine=create_database_engine(settings)
        try:
            with self.engine.begin() as holder:
                holder.execute(select(sessions).where(sessions.c.session_id==self.sid).with_for_update())
                with engine.begin() as blocked:
                    with self.assertRaises(OperationalError):
                        blocked.execute(update(sessions).where(sessions.c.session_id==self.sid).values(document_count=99))
            self.assertEqual(engine.pool.checkedout(),0)
            self.assertEqual(store.get_session(self.sid)['document_count'],0)
        finally: engine.dispose()

    def test_statement_timeout_rolls_back_and_pool_is_reusable(self):
        engine=create_database_engine(replace(self.settings,statement_timeout_ms=50))
        try:
            with self.assertRaises(OperationalError):
                with engine.begin() as c:
                    c.execute(update(sessions).where(sessions.c.session_id==self.sid).values(document_count=99))
                    c.execute(text('SELECT pg_sleep(1)'))
            with engine.connect() as c: self.assertEqual(c.scalar(text('SELECT 1')),1)
            self.assertEqual(engine.pool.checkedout(),0)
            self.assertEqual(store.get_session(self.sid)['document_count'],0)
        finally: engine.dispose()

    def test_request_close_releases_lease_without_saving_history(self):
        from app.services.agent_service import iter_pdf_agent_events
        from app.db.schema import request_leases
        session=store.get_session(self.sid)
        events=iter_pdf_agent_events(session,'sources')
        next(events)  # initial progress; no costly work dispatched yet
        next(events)  # planner update after lease acquired
        with self.engine.connect() as c:
            self.assertEqual(c.scalar(select(func.count()).select_from(request_leases).where(request_leases.c.session_id==self.sid)),1)
        events.close()
        with self.engine.connect() as c:
            self.assertEqual(c.scalar(select(func.count()).select_from(request_leases).where(request_leases.c.session_id==self.sid)),0)
        self.assertEqual(store.get_session(self.sid)['messages'],[])
        self.assertEqual(self.engine.pool.checkedout(),0)

    def test_expired_operational_leases_cleaned_with_retention_disabled(self):
        from app.db.schema import request_leases
        lease=store.acquire_session_lease(self.sid,1)
        with self.engine.begin() as c:
            c.execute(update(request_leases).where(request_leases.c.lease_id==lease).values(expires_at=store.timestamp(1)))
        with patch.dict(os.environ,{'SESSION_RETENTION_ENABLED':'false'}):
            self.assertEqual(store.cleanup_expired_sessions()['expired_sessions'],0)
        with self.engine.connect() as c:
            self.assertIsNotNone(c.scalar(select(sessions.c.session_id).where(sessions.c.session_id==self.sid)))
            self.assertEqual(c.scalar(select(func.count()).select_from(request_leases).where(request_leases.c.session_id==self.sid)),0)

    def test_request_remaining_deadline_caps_statement_and_does_not_leak_to_pool(self):
        from utils.llm_budget import RequestBudget, BudgetSettings, LLMBudgetExceeded
        from utils.observability import new_usage_tracker, observability_context
        engine=create_database_engine(replace(self.settings,pool_size=1))
        try:
            budget=RequestBudget(BudgetSettings(request_timeout_seconds=.15))
            with observability_context(usage_tracker=new_usage_tracker(budget)):
                with self.assertRaises(OperationalError):
                    with engine.begin() as c: c.execute(text('SELECT pg_sleep(1)'))
            with engine.connect() as c:
                self.assertEqual(c.scalar(text('SHOW statement_timeout')),'10s')
                self.assertEqual(c.scalar(text('SHOW lock_timeout')),'3s')
            budget.cancel('client_disconnected')
            with observability_context(usage_tracker=new_usage_tracker(budget)):
                with self.assertRaises(LLMBudgetExceeded):
                    with engine.begin() as c: c.execute(text('SELECT 1'))
            self.assertEqual(engine.pool.checkedout(),0)
        finally: engine.dispose()
