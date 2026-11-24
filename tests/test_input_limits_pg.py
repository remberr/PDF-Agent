"""Opt-in real PDF parsing and HTTP upload against a disposable PostgreSQL DB."""
import os
import unittest
from unittest.mock import patch

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import select, func

from app.api.routes import router
from app.db.engine import create_database_engine
from app.db.schema import chunks, documents
from app.input_limits import InputLimits, InputLimitsMiddleware
from app.services import postgres_store as store
from tests.test_input_limits import pdf_bytes
from tests.session_access_fixtures import create_bearer_session
from tests.test_pgvector_storage import SyntheticEmbeddings
from tests.test_postgres_connection import local_test_settings
from utils.observability import RequestContextMiddleware


@unittest.skipUnless(os.getenv('PDF_AGENT_RUN_POSTGRES_TESTS') == '1', 'opt-in local PostgreSQL test')
class LimitedUploadIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_database_engine(local_test_settings(os.environ))
        with cls.engine.begin() as connection:
            config = Config('alembic.ini')
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    async def asyncSetUp(self):
        self.patch = patch.object(store, 'get_engine', return_value=self.engine)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.sid, headers = create_bearer_session(store)
        self.addCleanup(lambda: store.delete_session(self.sid))
        app = FastAPI()
        app.include_router(router)
        app.add_middleware(InputLimitsMiddleware)
        app.add_middleware(RequestContextMiddleware)
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers=headers)
        self.addAsyncCleanup(self.http.aclose)
        self.addCleanup(lambda: self.assertEqual(self.engine.pool.checkedout(), 0))

    async def test_multi_pdf_duplicate_source_json_and_sse_keep_metadata(self):
        model = SyntheticEmbeddings()
        with patch('app.services.pdf_service.get_bge_embeddings', return_value=model), \
                patch('utils.pgvector_store.get_bge_embeddings', return_value=model), \
                patch('utils.pgvector_store.get_engine', return_value=self.engine), \
                patch('utils.llm_client.get_deepseek_client', side_effect=AssertionError('No paid calls')):
            response = await self.http.post(f'/sessions/{self.sid}/pdfs', files=[
                ('files', ('one.pdf', pdf_bytes(text='first evidence'), 'application/pdf')),
                ('files', ('two.pdf', pdf_bytes(text='second evidence'), 'application/pdf'))])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['uploaded_files'], ['one.pdf', 'two.pdf'])
            self.assertEqual(response.json()['total_documents'], 2)
            duplicate = await self.http.post(f'/sessions/{self.sid}/pdfs',
                files={'files': ('one.pdf', pdf_bytes(text='replacement'), 'application/pdf')})
            self.assertEqual(duplicate.json()['uploaded_files'], [])
            with self.engine.connect() as connection:
                self.assertEqual(connection.scalar(select(func.count()).select_from(chunks).where(
                    chunks.c.session_id == self.sid)), 2)
                metadata = connection.execute(select(chunks.c.metadata).where(
                    chunks.c.session_id == self.sid)).scalars().all()
            self.assertEqual({item['source'] for item in metadata}, {'one.pdf', 'two.pdf'})
            self.assertTrue(all(item['page'] == 0 for item in metadata))
            for suffix in ('ask', 'ask/stream'):
                result = await self.http.post(f'/sessions/{self.sid}/{suffix}',
                                              json={'question': '请列出来源和页码'})
                self.assertEqual(result.status_code, 200)
                if suffix == 'ask':
                    self.assertEqual(result.json()['usage']['llm_calls'], 0)
                else:
                    self.assertIn('event: result', result.text)
            self.assertEqual(len(store.get_session(self.sid)['messages']), 4)

    async def test_preflight_is_atomic_but_later_pdf_parse_failure_preserves_prior_success(self):
        model = SyntheticEmbeddings()
        with patch('app.services.pdf_service.get_bge_embeddings', return_value=model):
            with patch('app.services.pdf_service.get_input_limits', return_value=InputLimits(max_batch_bytes=8)):
                rejected = await self.http.post(f'/sessions/{self.sid}/pdfs', files=[
                    ('files', ('one.pdf', b'12345', 'application/pdf')),
                    ('files', ('two.pdf', b'67890', 'application/pdf'))])
            self.assertEqual(rejected.status_code, 413)
            self.assertEqual(store.get_session(self.sid)['loaded_pdfs'], [])
            partial = await self.http.post(f'/sessions/{self.sid}/pdfs', files=[
                ('files', ('one.pdf', pdf_bytes(), 'application/pdf')),
                ('files', ('bad.pdf', b'not a pdf', 'application/pdf'))])
            self.assertEqual(partial.status_code, 400)
            self.assertEqual(store.get_session(self.sid)['loaded_pdfs'], ['one.pdf'])
            with self.engine.connect() as connection:
                self.assertEqual(connection.scalar(select(func.count()).select_from(documents).where(
                    documents.c.session_id == self.sid)), 1)
