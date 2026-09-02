from typing import Any, List

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str


class SessionResponse(BaseModel):
    session_id: str


class SessionDetailResponse(BaseModel):
    session_id: str
    loaded_pdfs: List[str]
    message_count: int
    has_vectorstore: bool
    total_documents: int


class UploadResponse(BaseModel):
    session_id: str
    uploaded_files: List[str]
    loaded_pdfs: List[str]
    total_documents: int


class SourceResponse(BaseModel):
    citation_id: str
    source: str
    page: int
    excerpt: str


class AskResponse(BaseModel):
    answer: str
    steps: List[str]
    sources: List[SourceResponse]
    collaboration_notes: dict[str, Any]
    revision_count: int
    timings: dict[str, float]
