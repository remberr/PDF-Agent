from typing import List

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from app.schemas.requests import AskRequest
from app.schemas.responses import (
    AskResponse,
    HealthResponse,
    SessionDetailResponse,
    SessionResponse,
    UploadResponse,
)
from app.services.agent_service import ask_pdf_agent, stream_pdf_agent
from app.services.pdf_service import load_pdf_into_session
from app.services.session_store import create_session, delete_session, get_session


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check():
    return {
        "status": "ok",
        "service": "PDF Agent API"
    }


@router.post("/sessions", response_model=SessionResponse)
def create_pdf_session():
    session_id = create_session()

    return {
        "session_id": session_id
    }


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def get_pdf_session(session_id: str):
    session = get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    return {
        "session_id": session_id,
        "loaded_pdfs": session["loaded_pdfs"],
        "message_count": len(session["messages"]),
        "has_vectorstore": session["vectorstore"] is not None,
        "total_documents": session.get("document_count", 0)
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pdf_session(session_id: str):
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/pdfs", response_model=UploadResponse)
async def upload_pdfs(
    session_id: str,
    files: List[UploadFile] = File(...)
):
    session = get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    uploaded_files = []

    for uploaded_file in files:
        if not uploaded_file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail=f"Only PDF files are supported: {uploaded_file.filename}"
            )

        loaded = await load_pdf_into_session(session, uploaded_file)

        if loaded:
            uploaded_files.append(uploaded_file.filename)

    return {
        "session_id": session_id,
        "uploaded_files": uploaded_files,
        "loaded_pdfs": session["loaded_pdfs"],
        "total_documents": session.get("document_count", 0)
    }


@router.post("/sessions/{session_id}/ask", response_model=AskResponse)
def ask_question(
    session_id: str,
    request: AskRequest,
    http_request: Request,
):
    session = get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    if session["vectorstore"] is None:
        raise HTTPException(
            status_code=400,
            detail="Please upload at least one PDF before asking questions."
        )

    return ask_pdf_agent(
        session,
        request.question,
        http_request.state.request_id,
    )


@router.post("/sessions/{session_id}/ask/stream")
def stream_question(
    session_id: str,
    request: AskRequest,
    http_request: Request,
):
    session = get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    if session["vectorstore"] is None:
        raise HTTPException(
            status_code=400,
            detail="Please upload at least one PDF before asking questions."
        )

    return StreamingResponse(
        stream_pdf_agent(
            session,
            request.question,
            http_request.state.request_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )
