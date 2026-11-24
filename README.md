# PDF Agent

**English** · [简体中文](README.zh-CN.md)

Ask questions about one or more PDFs, compare documents, or trace an answer back to a filename and page. PDF Agent combines a React workspace, a FastAPI service, and a LangGraph workflow. It stores conversation history and document data in PostgreSQL and retrieves relevant passages with pgvector and BGE-M3.

## What you can do

- Upload PDFs into a session and ask for answers, summaries, keywords, comparisons, or sources.
- See the selected agents, workflow progress, timings, and citations as the backend streams events over SSE.
- Continue a conversation with recent messages and summarized history. Independent specialists can run in parallel; the workflow allows one additional revision when needed.
- Inspect token use, prompt-cache availability, and estimated costs. The Chinese interface uses CNY pricing and the English interface uses USD pricing; neither is derived by currency conversion.

## How it works

```text
PDF → PyPDFLoader → text chunks → BGE-M3 → PostgreSQL / pgvector
Question → LangGraph planner → scoped retrieval + specialists → answer + citations
React ↔ FastAPI → session history and SSE progress
```

Retrieved passages are limited to the active session. PostgreSQL stores sessions, messages, document metadata, and vectors; Alembic manages the schema. Runtime retrieval does not require FAISS.

## Run locally with Docker

You need Docker with Compose. Copy [`.env.example`](.env.example) to `.env`, set a local database password, and configure the connection for Compose:

```dotenv
POSTGRES_PASSWORD=<local-password>
DOCKER_DATABASE_URL=postgresql+psycopg://pdf_agent:<url-encoded-password>@db:5432/pdf_agent_local
DEEPSEEK_API_KEY=<optional-for-source-only-use>
```

Use a real DeepSeek key for generated answers. To use only the source workflow, leave the key empty. On a fresh local database volume:

```sh
docker compose -f compose.vector.yaml up -d --wait db
docker compose -f compose.vector.yaml exec db createdb -U pdf_agent pdf_agent_local
docker compose -f compose.vector.yaml --profile app up -d --build --wait
```

Run `createdb` only if `pdf_agent_local` does not exist. The migration service runs before the API. Use the [API docs](http://127.0.0.1:8001/docs) and [health check](http://127.0.0.1:8001/health) on the container's HTTP port. For the browser workspace, use the [local HTTPS frontend](docs/DEVELOPMENT.md#运行和调试) with `PDF_AGENT_DEV_BACKEND=http://127.0.0.1:8001`, or put the container behind a same-origin HTTPS reverse proxy. The first image build downloads the pinned BGE-M3 model for the runtime cache.

For development without the application container, use Python 3.11 and Node.js 22. See [the development guide](docs/DEVELOPMENT.md) and [local PostgreSQL setup](docs/LOCAL_STORAGE.md) for the host-side URL, Alembic, model cache, and frontend commands. The default `compose.yaml` requires a `DATABASE_URL` that the container can reach and whose schema is already migrated.

## API at a glance

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Health check |
| POST | `/sessions` | Create a session |
| GET / DELETE | `/sessions/{session_id}` | Inspect or delete a session |
| POST | `/sessions/{session_id}/pdfs` | Upload PDFs as multipart `files` |
| POST | `/sessions/{session_id}/ask` | Get an answer and citations |
| POST | `/sessions/{session_id}/ask/stream` | Stream workflow events and the final result |

Both question endpoints take JSON such as `{"question":"Show the sources."}`. Upload a PDF first.

## Tests and evaluation

```sh
python -m unittest discover -s tests -t . -v
npm --prefix frontend test
python -m evaluation.runner --mode routing
```

Requests share LLM call, token reservation, estimated USD cost, and deadline budgets; see [configuration and limits](docs/DEVELOPMENT.md#llm-budgets). SDK retries are disabled, and application retries default to zero. CI and default unit tests block provider network access. Live/real-PDF generation and Judge require explicit `--allow-paid-api`; routing never calls an LLM. Reservations are not billed usage, and cancellation cannot undo requests already sent.

[The testing guide](docs/TESTING.md) covers PostgreSQL integration, offline recovery, and real-PDF evaluation. Use a separate test database and keep PDF files and generated reports outside Git. For local retrieval without model API calls, point `DATABASE_URL` at a migrated test database and run:

```sh
python -m evaluation.runner --mode real-pdf --pdf-dir /path/to/pdfs --retrieval-only --output .evaluation-local/retrieval.json
```

Local acceptance covered PDF upload, BGE-M3 vector writes, Source Agent, SSE, restart persistence, TTL cleanup, and offline recovery. The three-PDF retrieval run checked 90 evidence quotations over 30 cases; mean expected-page recall was 60.7%. This measures retrieval coverage, and does not establish answer quality. Paid generation and Judge evaluation were not run during local migration acceptance.

## Data and deployment

- Each anonymous session has a 24-hour access credential. Browsers receive a secure cookie. API scripts can request a Bearer token at creation. Browser storage keeps only the active session locator and language preference, so visible chat history clears on reload.
- Database retention is off by default. Enable `SESSION_RETENTION_ENABLED` only where deletion is intended. Deleting a session also removes its messages, documents, and vectors. Credential expiry leaves the stored data subject to that retention policy.
- See [local storage and recovery](docs/LOCAL_STORAGE.md) before moving any legacy SQLite/FAISS data. The offline migration tools use [separate dependencies](requirements.migration.txt).
- PostgreSQL/pgvector has been verified locally. The Render deployment and production database were outside this rollout; the existing blueprint is not a PostgreSQL deployment guide.

[Architecture](docs/ARCHITECTURE.md) · [Development](docs/DEVELOPMENT.md) · [Testing](docs/TESTING.md) · [Roadmap](plans/ROADMAP.md) · [Task log](plans/TASKS.md)
