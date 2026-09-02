import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.services.session_store import init_session_store


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"


def get_cors_origins() -> list[str]:
    configured_origins = os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    )
    return [
        origin.strip()
        for origin in configured_origins.split(",")
        if origin.strip()
    ]


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
    allow_origins=get_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

if (FRONTEND_DIST / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="frontend-assets",
    )


@app.get("/", include_in_schema=False)
def frontend():
    if FRONTEND_INDEX.is_file():
        return FileResponse(FRONTEND_INDEX)

    return {
        "status": "ok",
        "service": "PDF Agent API",
        "frontend": "Run the Vite development server or build frontend/dist.",
    }


@app.on_event("startup")
def startup():
    init_session_store()
