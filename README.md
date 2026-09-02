# Multi-Agent PDF Analysis System

**English** | [简体中文](README.zh-CN.md)

A production-oriented PDF analysis application built with **LangGraph, FastAPI, React, and DeepSeek**. It combines retrieval-augmented generation, specialized agents, conversation memory, multi-agent collaboration, and bounded reflection/retry in an observable workflow.

[**Live Demo**](https://pdf-agent-bxjp.onrender.com) | [**API Docs**](https://pdf-agent-bxjp.onrender.com/docs)

[![CI](https://github.com/remberr/PDF-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/remberr/PDF-Agent/actions/workflows/ci.yml)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/remberr/PDF-Agent)

## Highlights

- Analyze one or more uploaded PDFs through a session-based web application
- Route requests to focused QA, summary, keyword, comparison, and source agents
- Run independent specialist agents concurrently while preserving planner order
- Coordinate multi-agent results before final synthesis
- Use bounded reflection/retry when evidence or specialist coverage is incomplete
- Ground answers in FAISS-retrieved chunks with filename and page citations
- Combine recent conversation, summarized history, and current PDF session context
- Stream live workflow events and node timings to the React interface with SSE
- Persist session metadata in SQLite and FAISS indexes on disk
- Reduce latency and token usage with deterministic planner, source, and reviewer fast paths
- Package the frontend and backend as one production Docker service

## Architecture

```text
Browser
  |
  v
React + TypeScript
  |
  | REST + Server-Sent Events
  v
FastAPI
  |
  +-- Session Service --------> SQLite
  +-- PDF Service ------------> PyPDFLoader -> text chunks -> FAISS
  |
  v
LangGraph Workflow
  |
  v
Hybrid Planner
  |
  v
Specialist Agent(s) in parallel
  |
  +-- Retriever -------------> relevant PDF chunks
  +-- Memory Manager --------> conversation and session context
  |
  v
Workflow Controller
  |
  +-- single result ---------> Reviewer fast path
  |
  +-- multiple results ------> Collaboration Agent
                                 |
                                 v
                             Revision Controller
                                 |
                                 +-- retry once when needed
                                 |
                                 v
                             Reviewer Agent
                                 |
                                 v
                             Final cited answer
```

The production container serves the compiled React application, API, and SSE stream from the same FastAPI origin. This keeps deployment simple and avoids cross-origin configuration in production.

## Agent Workflow

### Hybrid Planner

The Planner returns an ordered list of specialist steps:

```text
qa | source | summary | keyword | compare
```

Clear English and Chinese intents use deterministic routing. Ambiguous requests fall back to DeepSeek, preserving adaptive planning without paying for a planner model call on every question.

### Specialist Agents

| Agent | Responsibility |
| --- | --- |
| QA Agent | Answer questions from retrieved PDF evidence |
| Summary Agent | Summarize document content |
| Keyword Agent | Extract important concepts and terminology |
| Compare Agent | Compare multiple PDFs across methods, findings, and conclusions |
| Source Agent | Format deterministic filename, page, citation, and excerpt metadata |

Independent specialists run concurrently in a bounded thread pool. Their outputs are collected in planner order so parallel execution does not make the final answer nondeterministic.

### Collaboration And Reflection

The Collaboration Agent runs only when multiple specialist outputs are available. It merges overlapping findings, detects contradictions, identifies missing information, and returns a structured retry decision:

```python
{
    "answer": "...",
    "issues": [],
    "missing_information": [],
    "recommendations": [],
    "needs_revision": False,
    "next_steps": [],
}
```

The Revision Controller can add missing specialist steps and retry once:

```python
MAX_REVISION_COUNT = 1
```

This keeps reflection adaptive while preventing infinite loops and uncontrolled model cost.

### Reviewer

The Reviewer synthesizes multi-agent outputs and collaboration notes into one cited answer. A single-specialist request uses a pass-through fast path because an additional rewrite would add latency without adding useful information.

### Example Paths

```text
Direct question
  -> Planner [qa]
  -> QA Agent
  -> Reviewer fast path
  -> Answer

Compare with citations
  -> Planner [compare, source]
  -> Compare Agent + Source Agent in parallel
  -> Collaboration Agent
  -> Revision Controller
  -> Reviewer Agent
  -> Answer

Missing summary during collaboration
  -> Collaboration requests [summary]
  -> Summary Agent
  -> Collaboration Agent
  -> Reviewer Agent
  -> Answer
```

## Retrieval And Memory

Uploaded PDFs pass through this RAG pipeline:

```text
PDF -> PyPDFLoader -> text splitting -> multilingual embeddings -> FAISS
                                                          |
Question -> retriever ------------------------------------+
                                                          |
                                                          v
                                                  specialist prompt
```

Retrieved chunks carry stable citation metadata:

```text
Citation: [example.pdf, page 3]
PDF: example.pdf
Page: 3
Content: ...
```

The Memory Manager is a prompt-context component, not a standalone LangGraph node. It contributes:

- recent conversation messages
- cached summaries of older conversation history
- the filenames available in the current PDF session

Retrieved PDF chunks remain separate from conversation memory. This distinction keeps document evidence explicit and makes source attribution easier to inspect.

## FastAPI Backend

The backend exposes session-based PDF analysis over HTTP:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health check |
| `POST` | `/sessions` | Create a PDF analysis session |
| `GET` | `/sessions/{session_id}` | Inspect session metadata |
| `DELETE` | `/sessions/{session_id}` | Delete a session and its FAISS index |
| `POST` | `/sessions/{session_id}/pdfs` | Upload one or more PDFs |
| `POST` | `/sessions/{session_id}/ask` | Run the workflow and return one response |
| `POST` | `/sessions/{session_id}/ask/stream` | Stream workflow progress and the final result |

Interactive OpenAPI documentation is available at `/docs`.

### Streaming Workflow

The SSE endpoint emits `progress` events for active and completed nodes, followed by one `result` event. Each request includes planner steps, revision count, per-node timings, total duration, collaboration notes, source excerpts, and cumulative LLM usage.

```text
event: progress
data: {"node":"specialists","status":"completed",...}

event: result
data: {"answer":"...","sources":[...],"timings":{...},"usage":{...}}
```

### Structured Logging And Cost Observability

- Application, HTTP, workflow, PDF lifecycle, and LLM events are emitted as JSON to stdout.
- Every HTTP response includes `X-Request-ID`; the same ID and Session ID correlate request, node, and model-call logs, including the full SSE lifetime.
- LLM logs contain the operation, model, latency, input/output tokens, cache hit/miss tokens, cache hit rate, pricing tier, and estimated USD cost. Prompts, PDF text, API keys, and answers are not logged.
- API and SSE results expose request-level `usage` totals with `by_model` and `by_operation` breakdowns. The Workflow panel displays calls, total tokens, cache hit rate, estimated cost, and per-operation usage.
- Token counts come from the provider response. Cost is an estimate based on [DeepSeek's current peak/off-peak and cache-aware pricing](https://api-docs.deepseek.com/quick_start/pricing/); set all three `LLM_*_COST_PER_1M_TOKENS` variables to override built-in rates after a pricing change.

Representative events include `http_request_completed`, `agent_node_completed`, `llm_call_completed`, `agent_workflow_completed`, `pdf_indexed`, and `session_cleanup_completed`.

### Persistence

- SQLite stores session IDs, uploaded filenames, chat history, document counts, and vectorstore paths.
- Each session has a persisted FAISS index.
- `PDF_AGENT_DATA_DIR` controls the storage root and defaults to `app/data`.
- Sessions expire after 24 hours of inactivity by default; each read or write refreshes the TTL.
- A scheduled cleanup removes expired SQLite rows and orphaned FAISS directories every hour.
- `SESSION_TTL_SECONDS` and `SESSION_CLEANUP_INTERVAL_SECONDS` configure both intervals.
- Docker and Render mount `/data` as a persistent volume.
- This design targets a single application instance. Horizontal scaling should move metadata and vectors to shared managed services.

## Web Application

The React workspace provides:

- English and Chinese language switching
- multi-PDF upload and browser-side session restoration
- Markdown answers with expandable source excerpts
- live Planner, Specialist, Collaboration, Revision, and Reviewer states
- node-level execution timings and total workflow duration
- request-level LLM token, cache, and estimated cost observability
- API health and readable error states
- responsive desktop and mobile layouts

## Performance And Reliability

The workflow avoids redundant model calls where deterministic behavior is more reliable:

- explicit English and Chinese intents skip LLM planning
- ordinary questions route directly to QA
- source citations are formatted from retrieval metadata without an LLM
- single-specialist responses skip reviewer rewriting
- independent specialists execute concurrently
- only ambiguous planning, multi-agent collaboration, and multi-agent review remain model-powered

A normal QA request uses one LLM call. A QA request with sources uses collaboration and review only when multiple outputs require coordination.

Failure paths degrade gracefully:

- planner failure falls back to `qa`
- one specialist failure does not discard other successful outputs
- collaboration failure preserves available results and skips retry
- reviewer failure returns the specialist output
- memory summarization failure omits summary memory
- API validation and session errors return structured HTTP responses
- temporary uploaded PDF files are removed after parsing

## Quick Start

### Docker

Create `.env` from `.env.example` and add your DeepSeek API key:

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-v4-flash
LOG_LEVEL=INFO
SESSION_TTL_SECONDS=86400
SESSION_CLEANUP_INTERVAL_SECONDS=3600
```

Build and start the production application:

```bash
docker compose up --build -d
```

Open:

```text
Application: http://127.0.0.1:8000
API docs:    http://127.0.0.1:8000/docs
```

SQLite and FAISS data remain in the `pdf-agent-data` Docker volume when the container is recreated.

### Local Development

Install Python dependencies and start FastAPI:

```bash
pip install -r requirements.api.txt
uvicorn app.main:app --reload
```

In a second terminal, start the React development server:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite application connects to `http://127.0.0.1:8000` by default.

## Deployment

The repository includes a Render Blueprint and a multi-stage Docker build:

- Node builds the React frontend.
- Python installs API dependencies and CPU-only PyTorch.
- The multilingual embedding model is cached in the image.
- FastAPI serves the complete application on Render's assigned port.
- A persistent disk is mounted at `/data` for SQLite and FAISS.
- Idle sessions and orphaned indexes are removed by the lifecycle cleanup task.
- `/health` is used for container and platform health checks.

Deploy with the button at the top of this README. The provided Blueprint uses a 2 GB compute instance and a 1 GB persistent disk in Singapore. Enter `DEEPSEEK_API_KEY` as a Render secret during creation.

## Project Structure

```text
PDF-Agent/
|-- agent/
|   |-- graph_agent.py             # LangGraph nodes, routing, and concurrency
|   |-- state.py                   # Typed workflow state
|   |-- llm_planner.py             # Hybrid request planning
|   |-- collaboration_agent.py     # Multi-agent coordination and retry decision
|   |-- reviewer_agent.py          # Final synthesis and fast path
|   `-- *_agent.py                 # Specialist agents
|
|-- app/
|   |-- main.py                    # FastAPI app and React static hosting
|   |-- api/routes.py              # Session, upload, ask, and SSE endpoints
|   |-- schemas/                   # Typed API request/response models
|   `-- services/                  # Agent, PDF, and persistence services
|
|-- frontend/
|   `-- src/                       # React UI, API client, and workflow components
|
|-- evaluation/                    # Benchmark cases, metrics, and evaluation CLI
|-- tools/                         # Retrieval, summary, keyword, and comparison tools
|-- utils/                         # LLM, observability, memory, citations, and FAISS
|-- tests/                         # Workflow, lifecycle, and evaluation tests
|-- Dockerfile
|-- compose.yaml
|-- render.yaml
|-- requirements.api.txt
`-- requirements.txt
```

## Agent Evaluation

The repository includes a versioned evaluation dataset and two evaluation modes:

| Mode | What it measures | LLM cost |
| --- | --- | --- |
| `routing` | Exact Planner route accuracy across English, Chinese, multi-agent, and false-positive cases | None |
| `live` | Full LangGraph execution, answer term recall, source recall, citation precision, revisions, and latency | Uses DeepSeek for generative cases |

Run the zero-cost regression benchmark used by CI:

```bash
python -m evaluation.runner --mode routing --output evaluation-report.json
```

Run controlled end-to-end cases with optional LLM-as-a-Judge scoring:

```bash
python -m evaluation.runner --mode live --llm-judge --output evaluation-report.json
```

The judge is opt-in because it adds one LLM request per evaluated case. Use `--case source-citations` for one case or `--limit 2` for a smaller run. A non-zero exit code is returned when configured quality thresholds are missed, so the runner can act as a CI quality gate.

## Tests

Run the agent fast-path and streaming tests:

```bash
python -m unittest discover -s tests -v
```

The tests cover deterministic planning, Chinese intent routing, false-positive keyword prevention, concurrent specialist execution, reviewer fast paths, source formatting, SSE workflow events, structured logs, token/cost accounting, evaluation metrics, database migration, session TTL, deletion, and orphan cleanup.

GitHub Actions runs the backend tests and frontend production build in parallel, then verifies the complete production Docker image. Dependency and BuildKit caches keep repeat runs fast.

## Technology Stack

| Area | Technology |
| --- | --- |
| Agent orchestration | LangGraph |
| LLM | DeepSeek through an OpenAI-compatible client |
| Backend | FastAPI, Uvicorn, Server-Sent Events |
| Frontend | React, TypeScript, Vite |
| Retrieval | LangChain, FAISS, HuggingFace embeddings |
| PDF parsing | PyPDFLoader / pypdf |
| Persistence | SQLite and persisted FAISS indexes |
| Deployment | Docker Compose and Render Blueprint |

## Optional Streamlit Prototype

The repository retains the original Streamlit prototype in `main.py` for historical comparison and quick direct workflow debugging. It is not part of the production architecture or Docker deployment.

```bash
pip install -r requirements.txt
streamlit run main.py
```

## Portfolio Focus

This project demonstrates practical AI engineering beyond a basic chat interface:

- typed LangGraph state and conditional routing
- hybrid deterministic and LLM-based planning
- concurrent specialist execution
- structured collaboration and bounded reflection/retry
- RAG with inspectable page-level citations
- conversation and session memory separation
- centralized LLM configuration and fallback behavior
- reproducible Agent Evaluation with deterministic CI gates and optional LLM judging
- correlated JSON logs and cache-aware LLM cost observability
- session-based FastAPI API design
- real-time SSE observability
- persisted single-instance deployment with Docker

## Future Improvements

- Move persistence to PostgreSQL and a shared vector database for horizontal scaling
- Add authentication, session ownership, and upload quotas
- Add multimodal extraction for figures and tables

## License

This project is intended for educational and portfolio use.
