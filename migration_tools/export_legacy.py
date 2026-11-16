"""Export a consistent local PG snapshot to a NEW BGE-compatible recovery directory."""
import argparse
import json
import pickle
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
from sqlalchemy import select
from app.db.config import load_database_settings
from app.db.engine import create_database_engine
from app.db.schema import sessions, messages, documents, chunks
from utils.embeddings import PROFILE_ID, BGE_PROFILE, validate_vectors


def export_legacy(destination, engine, *, session_ids=None):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Recovery destination must be new; existing data is never overwritten.')
    # Read all data from one consistent snapshot before writing files.
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as connection:
        with connection.begin():
            connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            data = []
            selection = select(sessions).order_by(sessions.c.session_id)
            if session_ids is not None:
                selection = selection.where(sessions.c.session_id.in_(session_ids))
            for session in connection.execute(selection).mappings():
                sid = session['session_id']
                history = connection.execute(select(messages.c.payload).where(messages.c.session_id == sid).order_by(messages.c.ordinal)).scalars().all()
                names = connection.execute(select(documents.c.filename).where(documents.c.session_id == sid).order_by(documents.c.document_id)).scalars().all()
                vectors = connection.execute(select(chunks).where(chunks.c.session_id == sid).order_by(chunks.c.document_id, chunks.c.chunk_ordinal)).mappings().all()
                if any(v['embedding_profile_id'] != PROFILE_ID for v in vectors):
                    raise ValueError('Cannot export incompatible embedding profiles.')
                if vectors:
                    validate_vectors([v['embedding'] for v in vectors], expected_count=len(vectors))
                data.append((dict(session), history, names, vectors))
    destination.mkdir(parents=True)
    with closing(sqlite3.connect(destination / 'sessions.db')) as connection:
        connection.execute('CREATE TABLE sessions(session_id TEXT PRIMARY KEY, loaded_pdfs TEXT NOT NULL, messages TEXT NOT NULL, vectorstore_path TEXT, document_count INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)')
        for session, history, names, vectors in data:
            sid = session['session_id']
            folder = destination / 'vectorstores' / sid
            if vectors:
                import faiss
                from langchain_community.docstore.in_memory import InMemoryDocstore
                from langchain_core.documents import Document
                folder.mkdir(parents=True)
                index = faiss.IndexFlatIP(1024)
                index.add(np.asarray([v['embedding'] for v in vectors], dtype=np.float32))
                faiss.write_index(index, str(folder / 'index.faiss'))
                mapping = {i: str(v['chunk_id']) for i,v in enumerate(vectors)}
                docstore = InMemoryDocstore({mapping[i]: Document(page_content=v['content'], metadata=v['metadata']) for i,v in enumerate(vectors)})
                with (folder / 'index.pkl').open('xb') as output:
                    pickle.dump((docstore, mapping), output)
            connection.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?)', (sid, json.dumps(names, ensure_ascii=False),
                json.dumps(history, ensure_ascii=False, allow_nan=False), str(folder) if vectors else None,
                session['document_count'], int(session['created_at'].timestamp()), int(session['updated_at'].timestamp())))
        connection.commit()
    # Explicit profile marker prevents using the old MiniLM recovery image.
    (destination / 'embedding-profile.json').write_text(json.dumps({'profile_id': PROFILE_ID, **dict(BGE_PROFILE)}, indent=2), encoding='utf-8')
    return {'sessions': len(data), 'chunks': sum(len(d[3]) for d in data), 'profile': PROFILE_ID}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination')
    args = parser.parse_args()
    settings = load_database_settings()
    if settings.url.host not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Only local rehearsal databases are permitted.')
    engine = create_database_engine(settings)
    try:
        print(json.dumps(export_legacy(args.destination, engine)))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
