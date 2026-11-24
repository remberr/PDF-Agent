"""Explicit loopback integration suite; only deletes sessions created by each test."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from langchain_core.documents import Document
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError

from app.db.engine import create_database_engine
from app.db.runtime import verify_schema
from app.db.schema import chunks, documents, sessions, owner_credentials
from app.services import postgres_store as store
from tests.test_postgres_connection import local_test_settings
from tests.session_access_fixtures import BROWSER_HEADERS, create_bearer_session
from utils.pgvector_store import SessionVectorStore


from langchain_core.embeddings import Embeddings


class SyntheticEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, query):
        return [1.0] + [0.0] * 1023


@unittest.skipUnless(os.getenv('PDF_AGENT_RUN_POSTGRES_TESTS') == '1', 'opt-in local PostgreSQL test')
class PgvectorStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_database_engine(local_test_settings(os.environ))
        with cls.engine.begin() as connection:
            config = Config('alembic.ini')
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
            command.upgrade(config, 'head')
        verify_schema(cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        retention = patch.dict(os.environ, {'SESSION_RETENTION_ENABLED': 'true'})
        retention.start()
        self.addCleanup(retention.stop)
        self.patch = patch.object(store, 'get_engine', return_value=self.engine)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.ids = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for sid in self.ids:
            store.delete_session(sid)
        self.assertEqual(self.engine.pool.checkedout(), 0)

    def session(self):
        sid = store.create_session()
        self.ids.append(sid)
        return sid

    def document(self, sid, content='test', page_count=1):
        return store.commit_document(sid, 'same.pdf', page_count,
            [Document(page_content=content, metadata={'source': 'same.pdf', 'page': 3})],
            [SyntheticEmbeddings().embed_query('')])

    def test_isolation_metadata_duplicate_and_cascade(self):
        first, second = self.session(), self.session()
        self.assertTrue(self.document(first, 'first'))
        self.assertTrue(self.document(second, 'second'))
        self.assertFalse(self.document(first, 'replacement'))
        for sid, expected in ((first, 'first'), (second, 'second')):
            adapter = SessionVectorStore(sid, engine=self.engine, embeddings=SyntheticEmbeddings())
            result = adapter.similarity_search('same', k=3)
            self.assertEqual([r.page_content for r in result], [expected])
            self.assertEqual(result[0].metadata, {'source': 'same.pdf', 'page': 3})
            self.assertEqual(store.get_session(sid)['document_count'], 1)
        store.delete_session(first)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(chunks).where(chunks.c.session_id == first)), 0)
            self.assertEqual(connection.scalar(select(func.count()).select_from(documents).where(documents.c.session_id == first)), 0)

    def test_invalid_document_rolls_back_all_rows(self):
        sid = self.session()
        with self.assertRaises(IntegrityError):
            self.document(sid, page_count=-1)
        session = store.get_session(sid)
        self.assertEqual(session['loaded_pdfs'], [])
        self.assertEqual(session['document_count'], 0)
        self.assertIsNone(session['vectorstore'])

    def test_concurrent_snapshots_append_unknown_fields_without_overwrite(self):
        sid = self.session()
        snapshots = [store.get_session(sid) for _ in range(2)]
        for i, snapshot in enumerate(snapshots):
            snapshot['messages'].append({'role': 'assistant', 'content': str(i), 'unknown': {'x': [1]}})
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(store.save_session, snapshots))
        for snapshot in snapshots:
            store.save_session(snapshot)
        history = store.get_session(sid)['messages']
        self.assertEqual(len(history), 2)
        self.assertEqual({message['content'] for message in history}, {'0', '1'})
        self.assertTrue(all(message['unknown'] == {'x': [1]} for message in history))

    def test_expiration_retention_switch_and_deleted_snapshot(self):
        sid = self.session()
        self.document(sid)
        snapshot = store.get_session(sid)
        with self.engine.begin() as connection:
            connection.execute(update(sessions).where(sessions.c.session_id == sid).values(updated_at=store.timestamp(1)))
        with patch.dict(os.environ, {'SESSION_RETENTION_ENABLED': 'false'}):
            self.assertEqual(store.cleanup_expired_sessions()['expired_sessions'], 0)
            self.assertIsNotNone(store.get_session(sid))
        store.delete_session(sid)
        snapshot['messages'].append({'role': 'user', 'content': 'late'})
        with self.assertRaises(LookupError):
            store.save_session(snapshot)
        self.assertIsNone(store.get_session(sid))

    def test_invalid_vector_never_writes(self):
        sid = self.session()
        with self.assertRaises(ValueError):
            store.commit_document(sid, 'same.pdf', 1, [Document(page_content='x', metadata={'source': 'same.pdf'})], [[1.0]*384])
        self.assertEqual(store.get_session(sid)['loaded_pdfs'], [])

    def test_internal_document_delete_cascades_and_updates_pages(self):
        sid = self.session()
        self.document(sid)
        self.assertTrue(store.delete_document(sid, 'same.pdf'))
        self.assertFalse(store.delete_document(sid, 'same.pdf'))
        state = store.get_session(sid)
        self.assertEqual(state['document_count'], 0)
        self.assertIsNone(state['vectorstore'])

    def test_ttl_exact_boundary_cascades_vectors(self):
        with patch.object(store, 'SESSION_TTL_SECONDS', 100):
            with patch.object(store.time, 'time', return_value=1000):
                sid = self.session()
                self.document(sid)
            with patch.object(store.time, 'time', return_value=1050):
                self.assertEqual(store.get_session(sid)['updated_at'], 1050)
            with patch.object(store.time, 'time', return_value=1149):
                store.cleanup_expired_sessions()
                with self.engine.connect() as connection:
                    self.assertEqual(connection.scalar(select(func.count()).select_from(chunks).where(chunks.c.session_id == sid)), 1)
            with patch.object(store.time, 'time', return_value=1150):
                store.cleanup_expired_sessions()
                self.assertIsNone(store.get_session(sid))

    def test_concurrent_duplicate_upload_is_single_commit(self):
        sid = self.session()
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = list(executor.map(lambda _: self.document(sid), range(2)))
        self.assertEqual(sorted(result), [False, True])
        self.assertEqual(store.get_session(sid)['document_count'], 1)

    def test_batch_retry_and_conflict(self):
        import copy
        sid = self.session()
        snapshot = store.get_session(sid)
        snapshot['messages'].append({'role': 'user', 'content': 'original'})
        retry = copy.deepcopy(snapshot)
        conflict = copy.deepcopy(snapshot)
        store.save_session(snapshot)
        store.save_session(retry)
        conflict['messages'][0]['content'] = 'changed'
        with self.assertRaises(ValueError):
            store.save_session(conflict)
        self.assertEqual(len(store.get_session(sid)['messages']), 1)

    def test_legacy_snapshot_import_verify_retry_and_conflict(self):
        import tempfile
        import sqlite3
        import json
        from pathlib import Path
        from uuid import uuid4
        from migration_tools.snapshot import snapshot
        from migration_tools.import_legacy import import_snapshot, verify_import
        sid = uuid4().hex
        self.ids.append(sid)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source'
            source.mkdir()
            connection = sqlite3.connect(source / 'sessions.db')
            try:
                connection.execute('CREATE TABLE sessions(session_id TEXT, loaded_pdfs TEXT, messages TEXT, vectorstore_path TEXT, document_count INTEGER)')
                connection.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', (sid, '[]', json.dumps([{'role':'user','custom':[None, 1]}]), None, 0))
                connection.commit()
            finally:
                connection.close()
            backup = Path(folder) / 'backup'
            snapshot(source, backup)
            model = SyntheticEmbeddings()
            model.embed_documents = lambda texts: [model.embed_query(t) for t in texts]
            with self.assertRaises(ValueError):
                import_snapshot(backup, self.engine, embeddings=model)
            self.assertEqual(import_snapshot(backup, self.engine, embeddings=model, missing_timestamp=1000)['sessions'], 1)
            self.assertTrue(import_snapshot(backup, self.engine, embeddings=model, missing_timestamp=1000)['already_imported'])
            with self.assertRaises(ValueError):
                verify_import(backup, self.engine, missing_timestamp=1001)

    def test_api_session_contract_and_empty_question_guard(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with patch('app.db.runtime.get_engine', return_value=self.engine), patch.dict(os.environ, {'SESSION_RETENTION_ENABLED': 'false'}):
            with TestClient(app, base_url='https://localhost:5173', headers=BROWSER_HEADERS) as client:
                response = client.post('/sessions')
                self.assertEqual(response.status_code, 200)
                sid = response.json()['session_id']
                self.assertEqual(response.json(), {'session_id': sid})
                cookie = response.headers['set-cookie']
                self.assertIn(f'Path=/sessions/{sid}', cookie)
                for attribute in ('Max-Age=86400', 'Secure', 'HttpOnly', 'SameSite=strict'):
                    self.assertIn(attribute, cookie)
                self.assertNotIn('Domain=', cookie)
                self.ids.append(sid)
                details = client.get('/sessions/' + sid)
                self.assertEqual(details.json(), {'session_id': sid, 'loaded_pdfs': [],
                    'message_count': 0, 'has_vectorstore': False, 'total_documents': 0})
                self.assertEqual(client.post('/sessions/' + sid + '/ask', json={'question':'What is this?'}).status_code, 400)
                response = client.delete('/sessions/' + sid)
                self.assertEqual(response.status_code, 204)
                self.assertIn('Max-Age=0', response.headers['set-cookie'])
                self.assertEqual(client.get('/sessions/' + sid).status_code, 404)

    def test_bearer_access_is_isolated_and_does_not_touch_denied_rows(self):
        import base64
        import hashlib
        from datetime import timedelta
        from fastapi.testclient import TestClient
        from tests.test_error_privacy import make_app

        legacy = self.session()
        with TestClient(make_app()) as client:
            created = client.post('/sessions', headers={'X-Session-Mode': 'bearer'})
            self.assertEqual(created.status_code, 200)
            self.assertNotIn('set-cookie', created.headers)
            session = created.json()
            sid, token = session['session_id'], session['session_token']
            self.ids.append(sid)
            other, wrong = create_bearer_session(store)
            self.ids.append(other)
            headers = {'Authorization': f'Bearer {token}'}
            with self.engine.connect() as connection:
                row = connection.execute(select(owner_credentials).where(
                    owner_credentials.c.session_id == sid)).one()
                self.assertEqual(row.digest, hashlib.sha256(base64.urlsafe_b64decode(token + '=')).digest())
                self.assertEqual(row.expires_at - row.issued_at, timedelta(hours=24))
                updated = connection.scalar(select(sessions.c.updated_at).where(sessions.c.session_id == sid))
            for method, suffix in (
                ('GET', ''), ('DELETE', ''), ('POST', '/pdfs'),
                ('POST', '/ask'), ('POST', '/ask/stream'),
            ):
                result = client.request(method, f'/sessions/{sid}{suffix}', headers=wrong,
                                        content=b'private body')
                self.assertEqual((result.status_code, result.json()), (404, {'detail': 'Session not found.'}))
            for blocked in (legacy, 'f' * 32, other):
                self.assertEqual(client.get(f'/sessions/{blocked}', headers=headers).status_code, 404)
            with self.engine.connect() as connection:
                self.assertEqual(connection.scalar(select(sessions.c.updated_at).where(
                    sessions.c.session_id == sid)), updated)
            self.assertEqual(client.get(f'/sessions/{sid}', headers=headers).status_code, 200)
            with self.engine.begin() as connection:
                connection.execute(update(owner_credentials).where(owner_credentials.c.session_id == sid)
                                   .values(issued_at=row.issued_at - timedelta(hours=25),
                                           expires_at=row.expires_at - timedelta(hours=25)))
            self.assertEqual(client.get(f'/sessions/{sid}', headers=headers).status_code, 404)
            self.assertEqual(client.delete(f'/sessions/{sid}', headers=headers).status_code, 404)
        self.assertIsNotNone(store.get_session(sid))

    def test_cookie_paths_isolate_sessions_and_origin_applies_to_every_mutation(self):
        from fastapi.testclient import TestClient
        from tests.test_error_privacy import make_app

        with TestClient(make_app(), base_url='https://localhost:5173') as client:
            first, second = [client.post('/sessions', headers=BROWSER_HEADERS).json()['session_id']
                             for _ in range(2)]
            self.ids.extend((first, second))
            for sid in (first, second):
                self.assertEqual(client.get(f'/sessions/{sid}', headers=BROWSER_HEADERS).status_code, 200)
            for method, suffix in (('DELETE', ''), ('POST', '/pdfs'), ('POST', '/ask'), ('POST', '/ask/stream')):
                for origin in ('https://evil.invalid', 'null', ''):
                    headers = {**BROWSER_HEADERS, 'Origin': origin} if origin else {'X-PDF-Agent-Client': 'browser'}
                    self.assertEqual(client.request(method, f'/sessions/{first}{suffix}',
                                                    headers=headers, content=b'{').status_code, 403)
            self.assertEqual(client.delete(f'/sessions/{first}', headers=BROWSER_HEADERS).status_code, 204)
            self.assertEqual(client.get(f'/sessions/{first}', headers=BROWSER_HEADERS).status_code, 404)
            self.assertEqual(client.get(f'/sessions/{second}', headers=BROWSER_HEADERS).status_code, 200)
            with self.engine.connect() as connection:
                self.assertIsNone(connection.scalar(select(owner_credentials.c.session_id).where(
                    owner_credentials.c.session_id == first)))

    def test_owner_access_rechecks_under_transaction_after_concurrent_delete(self):
        from fastapi.testclient import TestClient
        from tests.test_error_privacy import make_app

        sid, headers = create_bearer_session(store)
        self.ids.append(sid)

        def delete_after_check(session_id, owner):
            self.assertTrue(store.check_session_owner(session_id, owner))
            self.assertTrue(store.delete_session(session_id))
            return True

        with TestClient(make_app()) as client, patch(
            'app.api.session_access.check_session_owner', side_effect=delete_after_check
        ), patch('app.api.routes.stream_pdf_agent') as generate:
            response = client.post(f'/sessions/{sid}/ask/stream', headers=headers, json={'question': 'source'})
            self.assertEqual(response.status_code, 404)
            generate.assert_not_called()
        self.assertIsNone(store.get_session(sid))

    def test_source_agent_json_and_sse_use_pg_citations_without_llm(self):
        from fastapi.testclient import TestClient
        from app.main import app
        sid, headers = create_bearer_session(store)
        self.ids.append(sid)
        self.document(sid)
        with patch('app.db.runtime.get_engine', return_value=self.engine), \
             patch('utils.pgvector_store.get_engine', return_value=self.engine), \
             patch('utils.pgvector_store.get_bge_embeddings', return_value=SyntheticEmbeddings()), \
             patch('utils.llm_client.get_deepseek_client') as llm, \
             patch.dict(os.environ, {'SESSION_RETENTION_ENABLED': 'false'}):
            with TestClient(app, headers=headers) as client:
                response = client.post('/sessions/' + sid + '/ask', json={'question': 'Show the sources.'})
                self.assertEqual(response.status_code, 200)
                self.assertIn('same.pdf', response.text)
                stream = client.post('/sessions/' + sid + '/ask/stream', json={'question': 'Show the sources.'})
                self.assertEqual(stream.status_code, 200)
                self.assertIn('event: result', stream.text)
                self.assertIn('same.pdf', stream.text)
                llm.assert_not_called()
        self.assertEqual(len(store.get_session(sid)['messages']), 4)

    @unittest.skipUnless(os.getenv('PDF_AGENT_RUN_LEGACY_RECOVERY_TESTS') == '1', 'opt-in offline FAISS recovery tests')
    def test_recovery_preserves_new_chat_vectors_and_excludes_deleted_session(self):
        import json
        import tempfile
        from pathlib import Path
        from migration_tools.export_legacy import export_legacy
        from migration_tools.snapshot import snapshot
        from migration_tools.import_legacy import read_snapshot
        sid, deleted = self.session(), self.session()
        self.document(sid)
        current = store.get_session(sid)
        current['messages'].append({'role': 'assistant', 'content': 'new write', 'usage': {'tokens': 10}})
        store.save_session(current)
        store.delete_session(deleted)
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'recovery'
            result = export_legacy(destination, self.engine, session_ids=[sid, deleted])
            self.assertEqual(result['sessions'], 1)
            backup = Path(folder) / 'snapshot'
            snapshot(destination, backup)
            rows = read_snapshot(backup)
            self.assertEqual(rows[0]['messages'], current['messages'])
            self.assertEqual(rows[0]['chunks'][0].metadata, {'source':'same.pdf', 'page':3})
            import faiss
            index = faiss.read_index(str(destination / 'vectorstores' / sid / 'index.faiss'))
            self.assertEqual(index.d, 1024)
            self.assertEqual(index.reconstruct(0).tolist(), SyntheticEmbeddings().embed_query(''))
            self.assertTrue((destination / 'embedding-profile.json').is_file())
            from migration_tools.recovery_store import load_recovery_store
            recovered = load_recovery_store(destination, sid, trusted=True, embeddings=SyntheticEmbeddings())
            self.assertEqual(recovered.similarity_search('test', k=1)[0].metadata,
                             {'source':'same.pdf','page':3})

    def test_incremental_upgrade_preserves_nonempty_relational_schema(self):
        from uuid import uuid4
        from sqlalchemy import text
        schema = 'migration_test_' + uuid4().hex
        # Transactional test schema is rolled back, never a historical database.
        with self.engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql('CREATE SCHEMA ' + schema)
                connection.exec_driver_sql('SET LOCAL search_path TO ' + schema + ', public')
                config = Config('alembic.ini')
                config.attributes['connection'] = connection
                # Public alembic_version must not be mistaken for this test's revision.
                connection.exec_driver_sql('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)')
                command.upgrade(config, '0003_request_leases')
                sid = uuid4().hex
                connection.execute(sessions.insert().values(session_id=sid, document_count=2,
                    created_at=store.timestamp(1000), updated_at=store.timestamp(1001)))
                command.upgrade(config, 'head')
                command.upgrade(config, 'head')
                row = connection.execute(select(sessions).where(sessions.c.session_id == sid)).mappings().one()
                self.assertEqual(row['document_count'], 2)
                self.assertEqual(int(row['created_at'].timestamp()), 1000)
                self.assertIsNone(connection.scalar(select(owner_credentials.c.session_id)))
                self.assertEqual(connection.scalar(text('SELECT version_num FROM alembic_version')), '0004_session_credentials')
            finally:
                transaction.rollback()

    def test_database_rejects_cross_session_or_invalid_chunk_metadata(self):
        from uuid import uuid4
        from utils.embeddings import PROFILE_ID
        sid, empty = self.session(), self.session()
        self.document(sid)
        valid = dict(chunk_id=uuid4(), session_id=sid, document_id=0, chunk_ordinal=1,
            content='test', metadata={'source':'same.pdf','page':3},
            embedding=SyntheticEmbeddings().embed_query(''), embedding_profile_id=PROFILE_ID,
            content_sha256='0'*64)
        for changes in ({'session_id':empty}, {'metadata':[]}, {'chunk_ordinal':-1},
                        {'embedding':[0.0]*1024}):
            with self.subTest(changes=list(changes)), self.assertRaises(IntegrityError):
                with self.engine.begin() as connection:
                    connection.execute(chunks.insert().values(**{**valid, **changes}))

    def test_all_specialists_and_combination_use_pg_with_mocked_provider(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from app.services.agent_service import ask_pdf_agent
        sid = self.session()
        self.document(sid)
        store.commit_document(sid, 'second.pdf', 1,
            [Document(page_content='Second evidence', metadata={'source':'second.pdf','page':0})],
            [SyntheticEmbeddings().embed_query('')])
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(model='deepseek-flash',
            choices=[SimpleNamespace(message=SimpleNamespace(content='Supported fixture answer.'))],
            usage={'prompt_tokens':100,'completion_tokens':10})
        cases = [('What is the main contribution?', ['qa']), ('Summarize the documents.', ['summary']),
                 ('Extract keywords.', ['keyword']), ('Compare the documents.', ['compare']),
                 ('Summarize and cite sources.', ['summary','source'])]
        with patch('utils.pgvector_store.get_engine', return_value=self.engine), \
             patch('utils.pgvector_store.get_bge_embeddings', return_value=SyntheticEmbeddings()), \
             patch('utils.llm_client.get_deepseek_client', return_value=client):
            for question, expected in cases:
                with self.subTest(question=question):
                    output = ask_pdf_agent(store.get_session(sid), question)
                    self.assertEqual(output['steps'], expected)
                    self.assertGreater(output['usage']['llm_calls'], 0)
                    self.assertTrue(output['sources'])
        self.assertEqual(len(store.get_session(sid)['messages']), 10)

    def test_delete_wins_against_upload_waiting_for_session_lock(self):
        from threading import Event
        sid = self.session()
        waiting = Event()
        original = store._locked_session
        def locked(*args):
            waiting.set()
            return original(*args)
        with self.engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(select(sessions).where(sessions.c.session_id == sid).with_for_update())
            with patch.object(store, '_locked_session', side_effect=locked), ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.document, sid)
                try:
                    self.assertTrue(waiting.wait(5))
                    connection.execute(sessions.delete().where(sessions.c.session_id == sid))
                    transaction.commit()
                    with self.assertRaises(LookupError):
                        future.result(timeout=5)
                finally:
                    if transaction.is_active:
                        transaction.rollback()
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(chunks).where(chunks.c.session_id == sid)), 0)

    def test_failure_after_chunk_insert_rolls_back_document_and_vectors(self):
        from sqlalchemy import event
        sid = self.session()
        def fail_update(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith('UPDATE sessions'):
                raise RuntimeError('injected final-update failure')
        event.listen(self.engine, 'before_cursor_execute', fail_update)
        try:
            with self.assertRaises(RuntimeError):
                self.document(sid)
        finally:
            event.remove(self.engine, 'before_cursor_execute', fail_update)
        self.assertEqual(store.get_session(sid)['loaded_pdfs'], [])
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(chunks).where(chunks.c.session_id == sid)), 0)

    def test_lost_commit_ack_can_be_reconciled_without_duplicate_messages_or_pages(self):
        from contextlib import contextmanager
        engine = self.engine
        class LostAcknowledgement:
            @contextmanager
            def begin(self):
                with engine.begin() as connection:
                    yield connection
                raise ConnectionError('injected lost commit acknowledgement')
        sid = self.session()
        state = store.get_session(sid)
        state['messages'].append({'role':'user','content':'once'})
        with patch.object(store, 'get_engine', return_value=LostAcknowledgement()):
            with self.assertRaises(ConnectionError):
                store.save_session(state)
            with self.assertRaises(ConnectionError):
                self.document(sid)
        store.save_session(state)
        self.assertFalse(self.document(sid))
        current = store.get_session(sid)
        self.assertEqual(len(current['messages']), 1)
        self.assertEqual(current['document_count'], 1)
