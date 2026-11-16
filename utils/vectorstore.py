"""PostgreSQL vector factory for isolated evaluation and prototype scopes."""
from collections import defaultdict
from utils.embeddings import BGE_PROFILE, get_bge_embeddings
from utils.pgvector_store import SessionVectorStore

EMBEDDING_MODEL = BGE_PROFILE['model']
get_embeddings = get_bge_embeddings


def create_vectorstore(chunks, *, embeddings=None):
    from app.services.postgres_store import create_session, commit_document, delete_session
    model = embeddings if embeddings is not None else get_embeddings()
    vectors = model.embed_documents([item.page_content for item in chunks])
    groups = defaultdict(list)
    for item, vector in zip(chunks, vectors):
        groups[item.metadata['source']].append((item, vector))
    sid = create_session()
    try:
        for filename, group in groups.items():
            commit_document(sid, filename, len({d.metadata.get('page') for d,v in group}),
                            [d for d,v in group], [v for d,v in group])
    except BaseException:
        delete_session(sid)
        raise
    return SessionVectorStore(sid, embeddings=model)
