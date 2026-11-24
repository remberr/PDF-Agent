import os
import logging
import tempfile
import asyncio
import hashlib
import threading
from pathlib import Path
from time import perf_counter

from fastapi import HTTPException, UploadFile
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.input_limits import InputLimits, get_input_limits, get_upload_admission
from app.services.postgres_store import commit_document, get_session
from utils.text_splitter import split_documents
from utils.embeddings import get_bge_embeddings
from utils.observability import log_event


logger = logging.getLogger(__name__)


def parse_pdf_documents(
    pdf_path: str | Path, source_name: str, *, limits: InputLimits | None = None,
) -> list[Document]:
    """Production parser shared by uploads and local PDF evaluation.

    Preserve loader page metadata (zero-based) and stable public filenames.
    """
    # Trusted local evaluation keeps its existing parser behavior. HTTP uploads
    # supply limits and check page count before any text extraction.
    if limits is not None:
        with open(pdf_path, 'rb') as source:
            reader = PdfReader(source)
            if reader.is_encrypted:
                raise HTTPException(400, 'Encrypted PDFs are not supported.')
            if len(reader.pages) > limits.max_pages:
                raise HTTPException(413, 'PDF exceeds the configured page limit.')
    docs = []
    text_chars = 0
    for doc in PyPDFLoader(str(pdf_path)).lazy_load():
        text_chars += len(doc.page_content)
        if limits is not None:
            if len(docs) >= limits.max_pages:
                raise HTTPException(413, 'PDF exceeds the configured page limit.')
            if text_chars > limits.max_text_chars:
                raise HTTPException(413, 'PDF exceeds the configured text limit.')
        doc.metadata['source'] = source_name
        docs.append(doc)
    return docs


async def validate_uploads(files: list[UploadFile], limits: InputLimits | None = None) -> None:
    """Preflight the complete batch without trusting Content-Length or file.size."""
    limits = limits or get_input_limits()
    if len(files) > limits.max_files:
        raise HTTPException(413, 'Too many PDF files in one upload.')
    total = 0
    for file in files:
        name = file.filename
        if not name or len(name) > 255 or not name.lower().endswith('.pdf'):
            raise HTTPException(400, 'A PDF filename of at most 255 characters is required.')
        size = 0
        try:
            await file.seek(0)
            while block := await file.read(64 * 1024):
                size += len(block)
                total += len(block)
                if size > limits.max_file_bytes or total > limits.max_batch_bytes:
                    raise HTTPException(413, 'PDF upload exceeds the configured byte limit.')
            if not size:
                raise HTTPException(400, 'Empty PDF files are not supported.')
        finally:
            await file.seek(0)


async def load_pdf_into_session(session: dict, uploaded_file: UploadFile) -> bool:
    """Bound one PDF's processing and atomically append it to the session."""
    with get_upload_admission().slot():
        return await _load_pdf_into_session(session, uploaded_file)


async def _load_pdf_into_session(session: dict, uploaded_file: UploadFile) -> bool:

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
    limits = get_input_limits()
    size = 0
    digest = hashlib.sha256()
    cancelled = threading.Event()

    try:
        def index_document():
            nonlocal pdf_path, size
            # One worker owns copy/parse/encode/commit. The awaiting coroutine
            # drains it even on cancellation before releasing file or permit.
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                pdf_path = tmp_file.name
                while block := uploaded_file.file.read(64 * 1024):
                    if cancelled.is_set():
                        return None
                    size += len(block)
                    if size > limits.max_file_bytes:
                        raise HTTPException(413, 'PDF exceeds the configured byte limit.')
                    digest.update(block)
                    tmp_file.write(block)
            if cancelled.is_set():
                return None
            if not size:
                raise HTTPException(400, 'Empty PDF files are not supported.')
            docs = parse_pdf_documents(pdf_path, uploaded_file.filename, limits=limits)
            if cancelled.is_set():
                return None
            # Retain guards at the service boundary even for alternate parsers.
            if len(docs) > limits.max_pages or sum(len(doc.page_content) for doc in docs) > limits.max_text_chars:
                raise HTTPException(413, 'PDF exceeds the configured page or text limit.')
            chunks = []
            for doc in docs:
                chunks.extend(split_documents([doc]))
                if len(chunks) > limits.max_chunks:
                    raise HTTPException(413, 'PDF exceeds the configured chunk limit.')
            if not chunks or not any(item.page_content.strip() for item in chunks):
                raise HTTPException(400, 'PDF contains no searchable text.')
            if cancelled.is_set():
                return None
            vectors = get_bge_embeddings().embed_documents([item.page_content for item in chunks])
            if cancelled.is_set():
                return None
            committed = commit_document(session['session_id'], uploaded_file.filename,
                len(docs), chunks, vectors, size_bytes=size, sha256=digest.hexdigest())
            return docs, chunks, committed, get_session(session['session_id'])

        indexing = asyncio.create_task(asyncio.to_thread(index_document))
        was_cancelled = False
        while True:
            try:
                result = await asyncio.shield(indexing)
                break
            except asyncio.CancelledError:
                # Repeated cancellation must not release the slot/file while
                # native parsing or encoding still uses it. Stop before the
                # next stage, but cannot undo an already running DB commit.
                was_cancelled = True
                cancelled.set()
            except Exception:
                if was_cancelled:
                    raise asyncio.CancelledError from None
                raise
        if was_cancelled:
            raise asyncio.CancelledError
        docs, chunks, committed, refreshed = result
        if refreshed is None:
            raise LookupError('Session no longer exists.')
        session.update(refreshed)

        log_event(
            logger,
            logging.INFO,
            "pdf_indexed",
            session_id=session.get("session_id"),
            file_size_bytes=size,
            page_count=len(docs),
            chunk_count=len(chunks),
            loaded_pdf_count=len(session["loaded_pdfs"]),
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )

        return committed

    except HTTPException:
        raise
    except PdfReadError:
        raise HTTPException(400, 'PDF could not be parsed. Check that it is valid and unencrypted.') from None
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
