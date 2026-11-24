import asyncio
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

from app.api.session_access import (
    SessionRoute, clear_owner_cookie, creation_mode, not_found, set_owner_cookie,
)
from app.schemas.requests import AskRequest
from app.schemas.responses import (
    AskResponse,
    HealthResponse,
    SessionDetailResponse,
    SessionResponse,
    UploadResponse,
)
from app.services.agent_service import ask_pdf_agent, stream_pdf_agent
from app.services.pdf_service import load_pdf_into_session, validate_uploads
from app.input_limits import get_upload_admission
from app.services.postgres_store import create_owned_session
from app.services.session_credentials import issue_credential
from app.services.session_store import delete_session, get_session


router = APIRouter()
session_router = APIRouter(route_class=SessionRoute)


@router.get("/health", response_model=HealthResponse)
def health_check():
    return {
        "status": "ok",
        "service": "PDF Agent API"
    }


@session_router.post("/sessions", response_model=SessionResponse, response_model_exclude_none=True)
def create_pdf_session(request: Request, response: Response):
    mode = creation_mode(request)
    token, owner = issue_credential(mode)
    session_id, expires_at = create_owned_session(owner)
    if mode == 'bearer':
        return {'session_id': session_id, 'session_token': token, 'expires_at': expires_at}
    set_owner_cookie(response, session_id, token)
    return {'session_id': session_id}


@session_router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def get_pdf_session(session_id: str, request: Request):
    session = get_session(session_id, owner=request.state.session_owner)

    if session is None:
        raise not_found()

    return {
        "session_id": session_id,
        "loaded_pdfs": session["loaded_pdfs"],
        "message_count": session.get("message_count", len(session["messages"])),
        "has_vectorstore": session["vectorstore"] is not None,
        "total_documents": session.get("document_count", 0)
    }


@session_router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pdf_session(session_id: str, request: Request):
    owner = request.state.session_owner
    if not delete_session(session_id, owner=owner):
        raise not_found()

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if owner.mode == 'cookie':
        clear_owner_cookie(response, session_id)
    return response


@session_router.post("/sessions/{session_id}/pdfs", response_model=UploadResponse)
async def upload_pdfs(
    session_id: str,
    request: Request,
    files: List[UploadFile] = File(...)
):
    with get_upload_admission().slot():
        session = await asyncio.to_thread(get_session, session_id, owner=request.state.session_owner)
        if session is None:
            raise not_found()

        # Check every filename and exact byte count before the first commit.
        await validate_uploads(files)
        uploaded_files = []
        for uploaded_file in files:
            loaded = await load_pdf_into_session(session, uploaded_file)
            if loaded:
                uploaded_files.append(uploaded_file.filename)

    return {
        "session_id": session_id,
        "uploaded_files": uploaded_files,
        "loaded_pdfs": session["loaded_pdfs"],
        "total_documents": session.get("document_count", 0)
    }


@session_router.post("/sessions/{session_id}/ask", response_model=AskResponse)
def ask_question(
    session_id: str,
    request: AskRequest,
    http_request: Request,
):
    session = get_session(session_id, owner=http_request.state.session_owner)

    if session is None:
        raise not_found()

    if session["vectorstore"] is None:
        raise HTTPException(
            status_code=400,
            detail="Please upload at least one PDF before asking questions."
        )

    return ask_pdf_agent(
        session,
        request.question,
        http_request.state.request_id,
        getattr(http_request.state, 'llm_budget', None),
    )


@session_router.post("/sessions/{session_id}/ask/stream")
def stream_question(
    session_id: str,
    request: AskRequest,
    http_request: Request,
):
    session = get_session(session_id, owner=http_request.state.session_owner)

    if session is None:
        raise not_found()

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
            getattr(http_request.state, 'llm_budget', None),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


router.include_router(session_router)
