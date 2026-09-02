from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.services.session_store import init_session_store


app = FastAPI(
    title="PDF Agent API",
    description=(
        "FastAPI backend for a LangGraph-based multi-agent PDF "
        "analysis system."
    ),
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def startup():
    init_session_store()
