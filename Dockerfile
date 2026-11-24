# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim-trixie AS runtime

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

USER appuser

# Cache the production model independently of changes to the rest of the source.
COPY --chown=appuser:appuser utils/embeddings.py ./utils/embeddings.py
RUN python -c "from utils.embeddings import create_bge_embeddings; create_bge_embeddings(local_files_only=False)"
USER root

# Give the persistent cluster a stable owner and keep package installation from
# creating an unused cluster in the image.
RUN groupadd --gid 10002 postgres \
    && useradd --uid 10002 --gid postgres --home-dir /var/lib/postgresql --no-create-home postgres \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 update \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y --no-install-recommends postgresql-common \
    && printf 'create_main_cluster = false\n' > /etc/postgresql-common/createcluster.conf \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        postgresql-17 postgresql-17-pgvector tini \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=appuser:appuser . ./
COPY --from=frontend-builder --chown=appuser:appuser \
    /frontend/dist ./frontend/dist
COPY scripts/container_start.py scripts/postgres_hba.conf /opt/pdf-agent/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['PORT'] + '/health', timeout=3)"

ENTRYPOINT ["/usr/bin/tini", "--", "python", "/opt/pdf-agent/container_start.py"]
