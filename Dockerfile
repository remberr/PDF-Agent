# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/appuser/.cache/huggingface \
    PDF_AGENT_DATA_DIR=/data \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.api.txt ./
RUN pip install --no-cache-dir \
        torch==2.7.0 \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.api.txt

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data "${HF_HOME}" \
    && chown -R appuser:appuser /data /home/appuser

COPY --chown=appuser:appuser . ./
COPY --from=frontend-builder --chown=appuser:appuser \
    /frontend/dist ./frontend/dist

USER appuser

# Bake the embedding model into the image so the first PDF upload is ready to run.
RUN python -c "from utils.vectorstore import get_embeddings; get_embeddings()"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
