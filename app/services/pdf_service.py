import os
import logging
import tempfile
from time import perf_counter

from fastapi import UploadFile
from langchain_community.document_loaders import PyPDFLoader

from app.services.session_store import save_session
from utils.text_splitter import split_documents
from utils.vectorstore import create_vectorstore, save_vectorstore
from utils.observability import log_event


logger = logging.getLogger(__name__)


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

        loader = PyPDFLoader(pdf_path)
        docs = loader.load()

        for doc in docs:
            doc.metadata["source"] = uploaded_file.filename

        session["loaded_pdfs"].append(uploaded_file.filename)
        session["document_count"] = session.get("document_count", 0) + len(docs)

        chunks = split_documents(docs)

        if session["vectorstore"] is None:
            session["vectorstore"] = create_vectorstore(chunks)

        else:
            session["vectorstore"].add_documents(chunks)

        save_vectorstore(
            session["vectorstore"],
            session["vectorstore_path"]
        )
        save_session(session)

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

        return True

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
