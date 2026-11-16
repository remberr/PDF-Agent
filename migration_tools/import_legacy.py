"""Explicit local-only import of a verified, trusted legacy snapshot."""
import argparse
import hashlib
import json
import pickle
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL

from sqlalchemy import select, insert
from app.db.config import load_database_settings
from app.db.engine import create_database_engine
from app.db.runtime import verify_schema
from app.db.schema import sessions, messages, documents, chunks
from app.services.postgres_store import timestamp
from migration_tools.snapshot import verify_snapshot
from utils.embeddings import PROFILE_ID, get_bge_embeddings


class RestrictedDocstoreUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        allowed = {
            ('langchain_community.docstore.in_memory', 'InMemoryDocstore'),
            ('langchain_core.documents.base', 'Document'),
        }
        if (module, name) not in allowed:
            raise pickle.UnpicklingError('Unexpected class in legacy docstore.')
        return super().find_class(module, name)


def read_snapshot(directory, *, missing_timestamp=None):
    directory = Path(directory).resolve()
    verify_snapshot(directory)
    with closing(sqlite3.connect((directory / 'sessions.db').as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute('SELECT * FROM sessions ORDER BY session_id')]
    for row in rows:
        sid = row['session_id']
        if not re.fullmatch('[a-f0-9]{32}', sid):
            raise ValueError('Invalid session ID.')
        row['loaded_pdfs'] = json.loads(row['loaded_pdfs'])
        row['messages'] = json.loads(row['messages'])
        names, history = row['loaded_pdfs'], row['messages']
        if not isinstance(names, list) or any(not isinstance(n, str) or not n for n in names) or len(names) != len(set(names)):
            raise ValueError('Invalid document names.')
        if not isinstance(history, list) or any(not isinstance(m, dict) for m in history):
            raise ValueError('Invalid message payload.')
        if type(row['document_count']) is not int or row['document_count'] < 0:
            raise ValueError('Invalid page count.')
        for field in ('created_at', 'updated_at'):
            if field not in row:
                if missing_timestamp is None:
                    raise ValueError('Legacy timestamps missing; supply a reviewed timestamp policy before import.')
                row[field] = missing_timestamp
            if type(row[field]) is not int or row[field] < 0:
                raise ValueError('Invalid timestamp.')
        row['chunks'] = []
        row['legacy_vectors'] = None
        if names:
            import faiss
            folder = directory / 'vectorstores' / sid
            index = faiss.read_index(str(folder / 'index.faiss'))
            if index.d not in (384, 1024):
                raise ValueError('Unsupported legacy vector dimension.')
            with (folder / 'index.pkl').open('rb') as stream:
                docstore, mapping = RestrictedDocstoreUnpickler(stream).load()
            if set(mapping) != set(range(index.ntotal)) or len(set(mapping.values())) != index.ntotal:
                raise ValueError('Incomplete or ambiguous docstore mapping.')
            for i in range(index.ntotal):
                document = docstore.search(mapping[i])
                if not hasattr(document, 'page_content') or document.metadata.get('source') not in names:
                    raise ValueError('Invalid chunk source.')
                page = document.metadata.get('page')
                if type(page) is not int or page < 0:
                    raise ValueError('Missing physical page metadata.')
                json.dumps(document.metadata, allow_nan=False)
                row['chunks'].append(document)
            if set(d.metadata['source'] for d in row['chunks']) != set(names):
                raise ValueError('A document has no recoverable chunks.')
            profile_path = directory / 'embedding-profile.json'
            if profile_path.is_file():
                profile = json.loads(profile_path.read_text(encoding='utf-8'))
                if profile.get('profile_id') != PROFILE_ID or index.d != 1024 or not isinstance(index, faiss.IndexFlat):
                    raise ValueError('Declared recovery profile does not match a lossless dense index.')
                from utils.embeddings import validate_vectors
                row['legacy_vectors'] = validate_vectors(
                    [index.reconstruct(i) for i in range(index.ntotal)], expected_count=index.ntotal)
    return rows


def import_snapshot(directory, engine, *, embeddings=None, missing_timestamp=None):
    rows = read_snapshot(directory, missing_timestamp=missing_timestamp)
    source_id = hashlib.sha256((Path(directory) / 'manifest.json').read_bytes()).hexdigest()
    verify_schema(engine)
    with engine.connect() as connection:
        existing = connection.execute(select(sessions.c.session_id).where(
            sessions.c.session_id.in_([r['session_id'] for r in rows]))).scalars().all()
    if existing:
        if len(existing) != len(rows):
            raise ValueError('Partially populated target conflicts with this snapshot.')
        verify_import(directory, engine, missing_timestamp=missing_timestamp, embeddings=embeddings)
        return {'verified_sessions': len(rows), 'already_imported': True}
    model = embeddings if embeddings is not None else get_bge_embeddings()
    prepared = []
    for row in rows:
        vectors = row['legacy_vectors'] if row['legacy_vectors'] is not None else model.embed_documents([d.page_content for d in row['chunks']])
        from utils.embeddings import validate_vectors
        if row['chunks']:
            vectors = validate_vectors(vectors, expected_count=len(row['chunks']))
        prepared.append((row, vectors))
    # Whole snapshot is atomic. Encoding holds no database connection.
    with engine.begin() as connection:
        connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        for row, vectors in prepared:
            sid = row['session_id']
            existing = connection.execute(select(sessions).where(sessions.c.session_id == sid)).mappings().first()
            if existing:
                raise ValueError('Target session already exists; verify explicitly instead of overwriting.')
            connection.execute(insert(sessions).values(session_id=sid, document_count=row['document_count'],
                created_at=timestamp(row['created_at']), updated_at=timestamp(row['updated_at'])))
            batch = uuid5(NAMESPACE_URL, source_id + ':' + sid)
            if row['messages']:
                connection.execute(insert(messages), [dict(session_id=sid, ordinal=i, payload=p,
                    batch_id=batch, batch_ordinal=i) for i,p in enumerate(row['messages'])])
            for document_id, name in enumerate(row['loaded_pdfs']):
                selected = [(d, v) for d,v in zip(row['chunks'], vectors) if d.metadata['source'] == name]
                connection.execute(insert(documents).values(session_id=sid, document_id=document_id,
                    filename=name, chunk_count=len(selected)))
                connection.execute(insert(chunks), [dict(chunk_id=uuid4(), session_id=sid,
                    document_id=document_id, chunk_ordinal=i, content=d.page_content, metadata=d.metadata,
                    embedding=v, embedding_profile_id=PROFILE_ID, import_source_id=source_id,
                    content_sha256=hashlib.sha256(d.page_content.encode()).hexdigest())
                    for i,(d,v) in enumerate(selected)])
    verify_import(directory, engine, missing_timestamp=missing_timestamp, embeddings=model)
    return {'sessions': len(rows), 'chunks': sum(len(r['chunks']) for r in rows), 'profile': PROFILE_ID}


def verify_import(directory, engine, *, missing_timestamp=None, embeddings=None):
    rows = read_snapshot(directory, missing_timestamp=missing_timestamp)
    import numpy as np
    expected_vectors = {}
    # Re-encode before acquiring a connection: dimensional checks alone cannot
    # detect a valid-looking vector paired with the wrong chunk.
    for row in rows:
        ordered = [d for name in row['loaded_pdfs'] for d in row['chunks'] if d.metadata['source'] == name]
        if ordered:
            model = embeddings if embeddings is not None else get_bge_embeddings()
            expected_vectors[row['session_id']] = model.embed_documents([d.page_content for d in ordered])
    with engine.connect() as connection:
        for row in rows:
            sid = row['session_id']
            actual = connection.execute(select(sessions).where(sessions.c.session_id == sid)).mappings().one()
            for key in ('created_at', 'updated_at'):
                if int(actual[key].timestamp()) != row[key]:
                    raise ValueError('Timestamp mismatch.')
            if actual['document_count'] != row['document_count']:
                raise ValueError('Page count mismatch.')
            history = connection.execute(select(messages.c.payload).where(messages.c.session_id == sid).order_by(messages.c.ordinal)).scalars().all()
            names = connection.execute(select(documents.c.filename).where(documents.c.session_id == sid).order_by(documents.c.document_id)).scalars().all()
            stored = connection.execute(select(chunks.c.content, chunks.c.metadata, chunks.c.embedding, chunks.c.embedding_profile_id, chunks.c.import_source_id).where(chunks.c.session_id == sid).order_by(chunks.c.document_id, chunks.c.chunk_ordinal)).all()
            expected = [d for n in names for d in row['chunks'] if d.metadata['source'] == n]
            if history != row['messages'] or names != row['loaded_pdfs'] or len(stored) != len(expected):
                raise ValueError('Relational or chunk count mismatch.')
            for item, document in zip(stored, expected):
                source_id = hashlib.sha256((Path(directory) / 'manifest.json').read_bytes()).hexdigest()
                if (item.content != document.page_content or item.metadata != document.metadata
                    or len(item.embedding) != 1024 or item.embedding_profile_id != PROFILE_ID
                    or item.import_source_id != source_id):
                    raise ValueError('Chunk mismatch.')
            for item, vector in zip(stored, expected_vectors.get(sid, [])):
                if not np.allclose(item.embedding, vector, rtol=0, atol=1e-5):
                    raise ValueError('Embedding does not match its source chunk/profile.')
    return {'verified_sessions': len(rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('preflight', 'import', 'verify'))
    parser.add_argument('snapshot')
    parser.add_argument('--missing-timestamp', type=int, help='Explicit reviewed UTC epoch for missing legacy timestamps only')
    parser.add_argument('--trusted-local-snapshot', action='store_true', required=True)
    args = parser.parse_args()
    if args.operation == 'preflight':
        rows = read_snapshot(args.snapshot, missing_timestamp=args.missing_timestamp)
        print(json.dumps({'sessions': len(rows), 'chunks': sum(len(r['chunks']) for r in rows)}))
        return
    settings = load_database_settings()
    if settings.url.host not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('This rehearsal tool only permits a loopback PostgreSQL host.')
    engine = create_database_engine(settings)
    try:
        result = import_snapshot(args.snapshot, engine, missing_timestamp=args.missing_timestamp) if args.operation == 'import' else verify_import(args.snapshot, engine, missing_timestamp=args.missing_timestamp)
        print(json.dumps(result))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
