"""Exact dense retrieval with an immutable session scope."""
import re
from sqlalchemy import select
from langchain_core.documents import Document
from app.db.runtime import get_engine
from app.db.schema import chunks
from utils.embeddings import get_bge_embeddings, PROFILE_ID, validate_vectors


class SessionVectorStore:
    def __init__(self, session_id, *, engine=None, embeddings=None):
        if not isinstance(session_id, str) or not re.fullmatch('[a-f0-9]{32}', session_id):
            raise ValueError('A valid session scope is required.')
        self._session_id = session_id
        self._engine = engine
        self._embeddings = embeddings

    def close(self):
        """Explicitly discard an evaluation/prototype scope created by its owner."""
        from sqlalchemy import delete
        from app.db.schema import sessions
        engine = self._engine if self._engine is not None else get_engine()
        with engine.begin() as connection:
            connection.execute(delete(sessions).where(sessions.c.session_id == self._session_id))

    def similarity_search(self, query, k=4):
        if type(k) is not int or not 1 <= k <= 1000:
            raise ValueError('k must be between 1 and 1000.')
        model = self._embeddings if self._embeddings is not None else get_bge_embeddings()
        vector = validate_vectors([model.embed_query(query)], expected_count=1)[0]
        statement = select(chunks.c.content, chunks.c.metadata).where(
            chunks.c.session_id == self._session_id,
            chunks.c.embedding_profile_id == PROFILE_ID,
        ).order_by(chunks.c.embedding.cosine_distance(vector), chunks.c.document_id,
                   chunks.c.chunk_ordinal, chunks.c.chunk_id).limit(k)
        engine = self._engine if self._engine is not None else get_engine()
        with engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [Document(page_content=row['content'], metadata=row['metadata']) for row in rows]
