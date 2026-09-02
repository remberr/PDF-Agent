from typing import Any, Dict, List

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


class UsageBreakdownResponse(BaseModel):
    llm_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    estimated_cost_usd: float


class LLMUsageResponse(UsageBreakdownResponse):
    cache_hit_rate: float
    currency: str
    cost_estimate_available: bool
    pricing_tiers: List[str]
    by_model: Dict[str, UsageBreakdownResponse]
    by_operation: Dict[str, UsageBreakdownResponse]


class AskResponse(BaseModel):
    answer: str
    steps: List[str]
    sources: List[SourceResponse]
    collaboration_notes: dict[str, Any]
    revision_count: int
    timings: dict[str, float]
    usage: LLMUsageResponse
