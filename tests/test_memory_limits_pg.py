import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from alembic import command
from alembic.config import Config
from sqlalchemy import select, func, update
from fastapi.testclient import TestClient
from app.db.engine import create_database_engine
from app.db.schema import messages, sessions
from app.services import postgres_store as store
from tests.test_postgres_connection import local_test_settings
from tests.test_error_privacy import make_app
from utils import memory
from utils.observability import observability_context


@unittest.skipUnless(os.getenv('PDF_AGENT_RUN_POSTGRES_TESTS')=='1','opt-in local PostgreSQL test')
class MemoryHistoryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=create_database_engine(local_test_settings(os.environ))
        with cls.engine.begin() as c:
            config=Config('alembic.ini'); config.attributes['connection']=c; command.upgrade(config,'head')

    @classmethod
    def tearDownClass(cls): cls.engine.dispose()

    def setUp(self):
        p=patch.object(store,'get_engine',return_value=self.engine); p.start(); self.addCleanup(p.stop)
        p=patch.dict(os.environ,{'MEMORY_HISTORY_MAX_MESSAGES':'5','SESSION_RETENTION_ENABLED':'false'}); p.start(); self.addCleanup(p.stop)
        self.sid=store.create_session(); self.addCleanup(lambda:store.delete_session(self.sid))
        memory._memory_cache.clear()
        snapshot=store.get_session(self.sid)
        snapshot['messages'].extend({'role':'user','content':str(i),'unknown':{'keep':i}} for i in range(30))
        store.save_session(snapshot)

    def test_window_bounds_reads_without_deleting_records_or_changing_api_counts(self):
        snapshot=store.get_session(self.sid)
        self.assertEqual(len(snapshot['messages']),5)
        self.assertEqual(snapshot['message_count'],30)
        self.assertEqual([m['content'] for m in snapshot['messages']],['25','26','27','28','29'])
        self.assertEqual(snapshot['messages'][-1]['unknown'],{'keep':29})
        with TestClient(make_app()) as http:
            self.assertEqual(http.get(f'/sessions/{self.sid}').json()['message_count'],30)
        with self.engine.connect() as c:
            self.assertEqual(c.scalar(select(func.count()).select_from(messages).where(messages.c.session_id==self.sid)),30)

    def test_concurrent_window_snapshots_append_only_new_messages(self):
        snapshots=[store.get_session(self.sid) for _ in range(2)]
        for i,snapshot in enumerate(snapshots): snapshot['messages'].append({'role':'user','content':f'new-{i}'})
        with ThreadPoolExecutor(2) as pool: list(pool.map(store.save_session,snapshots))
        for snapshot in snapshots: store.save_session(snapshot)
        current=store.get_session(self.sid)
        self.assertEqual(current['message_count'],32)
        self.assertEqual(len(current['messages']),5)
        self.assertTrue({'new-0','new-1'} <= {m['content'] for m in current['messages']})

    def test_delete_and_ttl_invalidate_summary_cache(self):
        data=[{'role':'user','content':'memory'}]*12
        for ttl in (False,True):
            with patch.dict(os.environ,{'MEMORY_HISTORY_MAX_MESSAGES':'100'}), \
                    observability_context(session_id=self.sid),patch('utils.memory.chat_with_deepseek',return_value='summary'):
                memory.build_llm_conversation_summary(data)
            self.assertTrue(memory._memory_cache)
            if ttl:
                with self.engine.begin() as c:
                    c.execute(update(sessions).where(sessions.c.session_id==self.sid).values(updated_at=store.timestamp(1)))
                with patch.dict(os.environ,{'SESSION_RETENTION_ENABLED':'true'}): store.cleanup_expired_sessions()
            else: store.delete_session(self.sid)
            self.assertFalse(memory._memory_cache)
            self.sid=store.create_session()
