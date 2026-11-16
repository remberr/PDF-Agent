"""Offline exact-distance parity check on existing local PG vectors; no model API."""
import argparse
import json
from time import perf_counter
from statistics import median

import numpy as np
from sqlalchemy import select
from app.db.config import load_database_settings
from app.db.engine import create_database_engine
from app.db.schema import chunks
from utils.embeddings import PROFILE_ID


def compare(engine):
    import faiss
    results = []
    with engine.connect() as connection:
        scopes = connection.execute(select(chunks.c.session_id).distinct()).scalars().all()
        for sid in scopes:
            rows = connection.execute(select(chunks.c.chunk_id, chunks.c.embedding).where(
                chunks.c.session_id == sid, chunks.c.embedding_profile_id == PROFILE_ID)
                .order_by(chunks.c.document_id, chunks.c.chunk_ordinal)).all()
            vectors = np.asarray([r.embedding for r in rows], dtype=np.float32)
            if not len(vectors):
                continue
            index = faiss.IndexFlatIP(1024)
            index.add(vectors)
            elapsed = []
            errors = []
            # Every stored unit vector serves as a probe; duplicates/ties compare scores.
            for vector in vectors:
                expected, _ = index.search(vector.reshape(1,-1), min(4,len(vectors)))
                distance = chunks.c.embedding.cosine_distance(vector)
                started = perf_counter()
                actual = connection.execute(select(distance).where(chunks.c.session_id == sid,
                    chunks.c.embedding_profile_id == PROFILE_ID).order_by(distance).limit(4)).scalars().all()
                elapsed.append((perf_counter()-started)*1000)
                errors.append(float(np.max(np.abs(expected[0] - (1-np.asarray(actual))))))
            results.append({'chunks':len(rows), 'probes':len(vectors), 'max_score_error':max(errors),
                            'sql_p50_ms':median(elapsed), 'sql_p95_ms':float(np.percentile(elapsed,95))})
    return {'comparison':'same BGE vectors, FAISS inner product vs pgvector cosine',
            'score_tolerance':1e-5, 'passed':bool(results) and all(r['max_score_error']<=1e-5 for r in results),
            'scopes':results, 'generation_executed':False,
            'limitations':'Stored-vector probes verify exact numerical parity, not semantic relevance or load capacity.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    settings = load_database_settings()
    if settings.url.host not in ('localhost','127.0.0.1','::1'):
        raise ValueError('Only local database comparisons are allowed.')
    engine = create_database_engine(settings)
    try:
        result = compare(engine)
        from pathlib import Path
        Path(args.output).write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
        return 0 if result['passed'] else 1
    finally:
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
