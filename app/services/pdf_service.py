import os
import logging
import tempfile
import asyncio
import hashlib
from time import perf_counter

from fastapi import UploadFile
from langchain_community.document_loaders import PyPDFLoader

from app.services.postgres_store import commit_document, get_session
from utils.text_splitter import split_documents
from utils.embeddings import get_bge_embeddings
from utils.observability import log_event


logger = logging.getLogger(__name__)


def parse_pdf_documents(pdf_path, source_name):
    """Production parser shared by uploads and local PDF evaluation.

    Preserve loader page metadata (zero-based) and stable public filenames.
    """
    docs = PyPDFLoader(str(pdf_path)).load()
    for doc in docs:
        doc.metadata["source"] = source_name
    return docs


async def load_pdf_into_session(session, uploaded_file: UploadFile):
    """
    Load one uploaded PDF into a session and rebuild its vectorstore.
    """

    if uploaded_file.filename in session["loaded_pdfs"]:
        log_event(
            logger,
            logging.INFO,
            "pdf_upload_skipped",
            session_id=session.get("session_id"),
            reason="duplicate_filename",
        )
        return False

    pdf_path = None
    started_at = perf_counter()

    try:
        pdf_bytes = await uploaded_file.read()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(pdf_bytes)
            pdf_path = tmp_file.name

        def index_document():
            docs = parse_pdf_documents(pdf_path, uploaded_file.filename)
            chunks = split_documents(docs)
            vectors = get_bge_embeddings().embed_documents([item.page_content for item in chunks])
            committed = commit_document(session['session_id'], uploaded_file.filename,
                len(docs), chunks, vectors, size_bytes=len(pdf_bytes),
                sha256=hashlib.sha256(pdf_bytes).hexdigest())
            return docs, chunks, committed, get_session(session['session_id'])

        indexing = asyncio.create_task(asyncio.to_thread(index_document))
        try:
            docs, chunks, committed, refreshed = await asyncio.shield(indexing)
        except asyncio.CancelledError:
            # A running worker cannot be cancelled; keep its temporary PDF alive.
            try:
                await indexing
            except Exception:
                logger.warning('Cancelled PDF indexing worker failed.')
            raise
        if refreshed is None:
            raise LookupError('Session no longer exists.')
        session.update(refreshed)

        log_event(
            logger,
            logging.INFO,
            "pdf_indexed",
            session_id=session.get("session_id"),
            file_size_bytes=len(pdf_bytes),
            page_count=len(docs),
            chunk_count=len(chunks),
            loaded_pdf_count=len(session["loaded_pdfs"]),
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )

        return committed

    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "pdf_index_failed",
            exc_info=True,
            session_id=session.get("session_id"),
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
            error_type=type(exc).__name__,
        )
        raise

    finally:
        if pdf_path and os.path.exists(pdf_path):
            os.remove(pdf_path)
