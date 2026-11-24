# PDF Agent

**English** · [简体中文](README.zh-CN.md)

PDF Agent is a React and FastAPI workspace for asking questions about PDFs and tracing answers to a filename and page. A LangGraph multi-agent workflow retrieves BGE-M3 vectors from PostgreSQL with pgvector. The engineering milestone described here has been verified locally. The Render deployment and production database have not been upgraded to it.

## What you can do

- **Multi-agent document analysis.** Upload multiple PDFs for Q&A, summaries, keyword extraction, cross-document comparisons, and source lookup. A planner selects specialists that can run in parallel. Collaboration can request one additional revision before final review. Planner and Collaboration results are schema-validated, with deterministic fallbacks for invalid output.
- **Progress and outcomes.** POST SSE delivers workflow progress and a final result with citations and usage. Both JSON and SSE distinguish success, degradation, failure, cancellation, and whether the result was saved. Interrupted streams can be identified without automatically replaying generation.
- **Memory and budgets.** Requests use a bounded window of recent messages and an optional summary of earlier conversation. Summary caching is scoped to the session and its context. A shared request budget bounds calls, token reservations, estimated USD costs, and time. The UI reports token usage, cache-statistics availability, and independently calculated USD or CNY estimates.
- **Anonymous sessions.** The browser uses a secure HttpOnly cookie, and scripts can request a Bearer token. Access is scoped to a single session. The page can recover documents and server-side context after reload. Visible chat history stays in page memory.

## How it works

```text
PDF → PyPDFLoader → text chunks → BGE-M3 → PostgreSQL + pgvector
Question → Planner → session-scoped specialists → Collaboration / Reviewer
React ← FastAPI JSON or POST SSE ← result, citations, and execution outcome
```

Alembic manages sessions, messages, document metadata, text chunks, vectors, credentials, and in-flight request leases. Uploads commit the document and its chunks together. SQLite and FAISS are reserved for the offline migration and recovery tools.

## Run locally with Docker

You need Docker with Compose. Copy [`.env.example`](.env.example) to `.env`, set a local database password, and configure the connection for Compose:

```dotenv
POSTGRES_PASSWORD=<local-password>
DOCKER_DATABASE_URL=postgresql+psycopg://pdf_agent:<url-encoded-password>@db:5432/pdf_agent_local
DEEPSEEK_API_KEY=<optional-for-source-only-use>
```

Generated answers require a DeepSeek key. For Source lookups, leave `DEEPSEEK_API_KEY=` empty. The acceptance process explicitly sets `PDF_AGENT_DISABLE_LLM_API=1` on the API container. On a fresh local database volume:

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

Scripts create a session with `X-Session-Mode: bearer`, save the one-time `session_token` from the response, and send `Authorization: Bearer <token>` with each session request. Credentials expire after 24 hours. Upload a PDF before asking a question such as `{"question":"Show the sources."}`. Cookie-backed browser requests use the same-origin HTTPS setup described in the development guide.

## Tests and evaluation

```sh
python -m unittest discover -s tests -t . -v
npm --prefix frontend test
npm --prefix frontend run build
python -m evaluation.runner --mode routing
```

See the [request budget settings](docs/DEVELOPMENT.md#llm-budgets) for limits and retry behavior. CI and default unit tests block model-provider calls. Live or real-PDF generation and Judge require explicit `--allow-paid-api`. Routing and Source-only checks run with zero model calls. Reservations are estimates. Cancellation does not retract requests that have already reached the provider.

[The testing guide](docs/TESTING.md) covers PostgreSQL integration, offline recovery, and real-PDF evaluation. Use a separate test database and keep PDF files and generated reports outside Git. For local retrieval without model API calls, point `DATABASE_URL` at a migrated test database and run:

```sh
python -m evaluation.runner --mode real-pdf --pdf-dir /path/to/pdfs --retrieval-only --output .evaluation-local/retrieval.json
```

Local acceptance covers anonymous access, upload, scoped retrieval, Source JSON/SSE, restart persistence, TTL cleanup, and offline recovery. The earlier migration evaluation measured 60.7% mean expected-page recall across 30 retrieval cases and 90 evidence quotations from three PDFs. The metric describes retrieval coverage. Generation and Judge quality have separate evaluation tasks. See the [milestone record](plans/TASKS.md#current-execution) for the latest results and any skipped checks.

## Data and deployment

- PostgreSQL stores chat context and extracted passages. Browser Web Storage retains the active session locator and language preference. The app clears its legacy local chat cache and redacts session IDs, raw request paths, and exception messages from application logs. Generated answers can send the question and relevant passages to the configured provider.
- Database retention is off by default. Enable `SESSION_RETENTION_ENABLED` only where deletion is intended. Deleting a session also removes its messages, documents, and vectors. Credential expiry leaves the stored data subject to that retention policy.
- See [local storage and recovery](docs/LOCAL_STORAGE.md) before moving any legacy SQLite/FAISS data. The offline migration tools use [separate dependencies](requirements.migration.txt).
- The current milestone is a local release candidate. Render configuration, production backups and migration, public HTTPS origins, and gateway logging require separate verification before deployment.

[Architecture](docs/ARCHITECTURE.md) · [Development](docs/DEVELOPMENT.md) · [Testing](docs/TESTING.md) · [Roadmap](plans/ROADMAP.md) · [Task log](plans/TASKS.md)
