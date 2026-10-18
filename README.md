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
- Token counts come from the provider response. Cost is an estimate based on [DeepSeek's current peak/off-peak and cache-aware pricing](https://api-docs.deepseek.com/quick_start/pricing/); optional `LLM_*_COST_PER_1M_TOKENS` overrides are peak prices and still receive the off-peak multiplier. Unknown models or incomplete/inconsistent usage are displayed as unavailable, not free.

Representative events include `http_request_completed`, `agent_node_completed`, `llm_call_completed`, `agent_workflow_completed`, `pdf_indexed`, and `session_cleanup_completed`.

#### Where To View Logs And Costs

- On Render, open the `pdf-agent` service and select **Logs**. Search by `request_id`, `session_id`, or an event name to trace one request across HTTP, workflow, and LLM calls.
- With Docker Compose, stream the same JSON logs with `docker compose logs -f pdf-agent`.
- In the Web application, submit a question and open the **Workflow** panel to inspect LLM calls, total tokens, cache hit rate, estimated cost, and the per-operation breakdown.
- API clients can read the same request-level data from the `usage` object returned by `/ask` and by SSE `progress` and `result` events. The final usage summary is also stored with the assistant message in the session.

Cost observability is currently scoped to individual requests and sessions. There is no persistent, application-wide historical cost dashboard yet; JSON logs can be forwarded to an external log platform for longer-term aggregation.

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
DEEPSEEK_MODEL=deepseek-flash
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

Three modes share the existing Planner and LangGraph workflow:

| Mode | Input and purpose | Provider calls |
| --- | --- | --- |
| `routing` | Original `evaluation/cases.json`; exact route regression | None for the bundled deterministic cases |
| `live` | Original controlled documents and `StaticVectorStore`; workflow regression | Generative cases and optional Judge |
| `real-pdf` | Local PDFs → production PyPDFLoader → 1200/250 character splitting → production multilingual MiniLM embeddings → FAISS → LangGraph | Generative cases and optional Judge; requires explicit paid opt-in |

```bash
python -m evaluation.runner --mode routing --output evaluation-report.json
python -m evaluation.runner --mode live --case source-citations --output evaluation/reports/live-source.json
python -m evaluation.runner --mode live --llm-judge --output evaluation/reports/live.json
```

`evaluation/real_pdf_cases.json` contains 30 cases (including six Chinese questions), 60 required facts and 90 page-evidence excerpts covering QA, Summary, Compare, Source, Keyword, combinations, cross-page retrieval, cross-document comparisons, missing details, unanswerable questions and insufficient evidence. `pdf_manifest.json` pins the supplied GPT-2, BERT and Transformer PDFs by filename, physical page count and SHA-256. Keep the files locally; PDFs, extracted text, indexes and reports must not be committed. Default real-PDF reports go to ignored `evaluation/reports/`, separately from controlled reports. `--dataset`, `--manifest`, `--case` (repeatable), `--limit` and `--output` customize a run.

Replace the directory below with the location of the three supplied PDFs:

```bash
# No embeddings or LLM: check hashes, page ranges and exact evidence excerpts.
python -m evaluation.runner --mode real-pdf --pdf-dir "C:/path/to/pdfs" --validate-only

# Production embeddings + real FAISS retrieval; no generation or Judge.
python -m evaluation.runner --mode real-pdf --pdf-dir "C:/path/to/pdfs" --retrieval-only

# LangGraph Source specialist over real FAISS, without provider calls.
python -m evaluation.runner --mode real-pdf --pdf-dir "C:/path/to/pdfs" --case real-source-attention --output evaluation/reports/real-source.json

# PAID: set DEEPSEEK_API_KEY, then explicitly enable generation and judging.
python -m evaluation.runner --mode real-pdf --pdf-dir "C:/path/to/pdfs" --allow-paid-api --llm-judge --output evaluation/reports/real-pdf.json
```

The first embedding run may download the production Hugging Face model; subsequent runs reuse the model cache. Set `HF_HUB_OFFLINE=1` to require cached weights. FAISS indexes are built in memory per `pdf_files` scope and reused during the run. A scope is equivalent to the PDFs uploaded into a session; it does not select pages or supply reference facts to the Agent. All scoped pages enter the index, including distractors. Only the question, filenames and retriever enter workflow state. Production specialist retrieval limits and query strategies are unchanged, so a broad summary or comparison may miss required facts; the evaluation should expose those failures.

Each case has `required_facts` (ID, statement, supporting citation IDs), `expected_citations` (filename, **one-based physical PDF page**, exact evidence excerpts), `forbidden_claims`, `reference_answer`, `answerability`, `expected_behavior` and `annotation`. The legacy controlled `documents[].page` stays zero-based. BERT physical page 4 is printed proceedings page 4174, not page 4174 of the PDF.

**References are provisional.** They were authored after inspecting the supplied text and checking numeric tables visually, then checked against exact page text. They are marked `pending_human_review` / `human_verified: false`, not verified Ground Truth. Quote matching proves provenance, not entailment, completeness or absence. Review the original page, scope, qualifications, fact-to-evidence mapping and refusal expectations before recording a human reviewer/date and changing the annotation status. In particular, absence of a search term alone does not prove unanswerability. Evidence and candidate answers are treated as untrusted content by the Judge.

The optional Judge evaluates semantic correctness, completeness/omissions, evidence support and relevance on 1–5 scales; it checks required facts, forbidden claims, citation issues and calibrated refusals. It accepts faithful paraphrases and does not use keyword overlap as a factual quality score. The Judge also flags annotation ambiguity. Controlled live mode retains legacy answer-term recall; real-PDF reports omit that metric. Deterministic citation metrics only measure page overlap and citation membership, not semantic support. `--min-source-recall`, `--min-citation-precision`, `--min-route-accuracy` and `--min-llm-judge-score` control gates. Judge failure fails a judged run even when other calls succeeded.

Reports use `schema_version: 2`. Each case and `summary` include independent `agent_usage`, `judge_usage` and `total_usage`, with calls, input/output/total tokens, cache hit/miss tokens, estimated USD cost and `by_model` / `by_operation`. Legacy `usage` and flat summary cost/token/call fields remain **Agent-only**. `duration_ms` sums LLM call durations (parallel calls can overlap); `elapsed_ms` measures Agent or Judge wall time. Corpus parsing and indexing time are reported separately under `corpus`. A malformed Judge response retains its recorded usage plus `judge_status: failed` and `llm_judge_error`. A transport failure without provider usage retains a counted attempt and unknown cost. Calls count logical SDK invocations; SDK-internal retry attempts and their unreturned usage cannot be reconstructed.

Validation/retrieval reports use separate mode names, `passed: null`, `generation_executed: false` and `quality_status: not_evaluated`. Retrieval diagnostics include expected-page recall; they are not quality passes. A normal run without a Judge has `quality_status: structural_metrics_only`; a real-PDF judged run remains `provisional_llm_judged` until human reference review. `passed` refers only to the reported thresholds, not certified factual correctness. Reports are printed as JSON and saved when `--output` is supplied (real-PDF mode has a default output). A nonzero exit code means a missed gate or execution/configuration failure.

### Cost estimation

Prices are centralized in `utils/pricing.py`, verified against [DeepSeek's official USD pricing](https://api-docs.deepseek.com/quick_start/pricing/) on 2026-10-18. `deepseek-flash` and legacy `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp` share Flash rates; existing chat/reasoner aliases remain supported. New configurations default to `deepseek-flash`; explicit existing model settings are respected.

| Model | USD per 1M tokens | Off-peak | Peak |
| --- | --- | ---: | ---: |
| `deepseek-flash` | Cache hit | 0.003 | 0.006 |
| `deepseek-flash` | Cache miss | 0.15 | 0.30 |
| `deepseek-flash` | Output | 0.60 | 1.20 |
| `deepseek-v4-pro` | Cache hit | 0.022 | 0.044 |
| `deepseek-v4-pro` | Cache miss | 0.66 | 1.32 |
| `deepseek-v4-pro` | Output | 1.98 | 3.96 |

Cost = `(hit_tokens × hit_price + miss_tokens × miss_price + output_tokens × output_price) / 1,000,000`. Input/output counters must be nonnegative integers. When exactly one cache counter is present, derive the other from total input. Missing both cache counters with nonzero input, invalid counters, or contradictory input/output/cache totals make the estimate unavailable. Explicit zero usage remains valid. Rates use the timezone-aware **request start timestamp**, converted to Beijing time. Peak windows are Monday–Friday `[09:00, 12:00)` and `[14:00, 18:00)`, excluding full Chinese public holiday breaks. Weekends, including makeup working weekends, are off-peak.

`utils/china_holidays.json` currently covers **2026**, with the [State Council notice](https://www.gov.cn/zhengce/content/202511/content_7047090.htm) and a [government mirror](https://www.beijing.gov.cn/zhengce/zhengcefagui/202511/t20251104_4258873.html). Add each newly published year with its authoritative source and reviewed date. No runtime holiday network call is made. During a possible peak window, an unknown year, unreadable calendar, invalid price or unknown model yields `cost_status: unavailable`, `cost_estimate_available: false`, explanatory `pricing_warnings` and `estimated_total_cost_usd: null`. A known weekend or outside-window call is still unambiguously off-peak. For backward compatibility, numeric `estimated_cost_usd` / `known_cost_usd` retain only the priced subtotal; **zero with unavailable status does not mean free**.

The `LLM_CACHE_HIT_COST_PER_1M_TOKENS`, `LLM_CACHE_MISS_COST_PER_1M_TOKENS` and `LLM_OUTPUT_COST_PER_1M_TOKENS` variables override **peak** prices for the selected supported model. Set any or all to finite nonnegative values; overrides are merged before the peak/off-peak multiplier, so off-peak remains half price. Overrides never bypass unknown-model/calendar checks. Invalid values are explicitly unavailable. Leave the overrides unset to keep model-specific defaults; copying Flash prices while selecting Pro would override Pro rates too. Estimates exclude local embedding compute and cannot replace the provider invoice.

## Tests

Run the agent fast-path and streaming tests:

```bash
python -m unittest discover -s tests -v
```

The tests cover deterministic planning, Chinese intent routing, false-positive keyword prevention, concurrent specialist execution, reviewer fast paths, source formatting, SSE workflow events, structured logs, peak/off-peak boundaries and timezones, weekends and public holidays, aliases, complete/partial price overrides, cache-aware accounting, unavailable-cost handling, Agent/Judge usage isolation, evaluation metrics, database migration, session TTL, deletion, and orphan cleanup.

The ordinary suite uses test embeddings and mocked provider responses for integration wiring; it never calls DeepSeek. Local production-PDF and paid integration tests are separately skipped unless explicitly enabled. On PowerShell:

```powershell
# Local PDFs + cached production embeddings, no paid request.
$env:HF_HUB_OFFLINE="1"
$env:PDF_AGENT_EVAL_PDF_DIR="C:/path/to/pdfs"
$env:PDF_AGENT_RUN_LOCAL_PDF_TESTS="1"
python -m unittest discover -s tests -p test_real_pdf_evaluation.py -v

# PAID integration: requires DEEPSEEK_API_KEY and the PDF directory above.
$env:PDF_AGENT_RUN_PAID_TESTS="1"
python -m unittest discover -s tests -p test_real_pdf_evaluation.py -v
Remove-Item Env:PDF_AGENT_RUN_PAID_TESTS
```

### Local verification snapshot — 2026-10-18

These are local observations for this revision, not guarantees for a fresh environment or a hosted deployment. The latest pricing correction reused the unchanged PDF/retrieval checks below and reran the complete offline suite and routing benchmark.

| Check | Observed result |
| --- | --- |
| Full offline suite | 50 tests: 48 passed; local-PDF and paid integration tests skipped |
| Focused pricing tests | 13 passed, included in the full suite |
| Routing benchmark | 9/9 passed, no model calls |
| Controlled Source Live | Passed, no model calls |
| Local production PDF/embedding/FAISS integration | Explicitly enabled and passed separately |
| Reference provenance | Three PDFs / 51 pages; all 90 excerpts matched their annotated pages; semantic human review still pending |
| Retrieval-only diagnostics | All 30 cases executed; no answer generation or Judge |
| Three real Source workflow cases | Route accuracy 1.0, source recall 0.6667, citation precision 1.0; quality gate failed because `real-source-nsp` missed BERT physical PDF page 4 |
| Paid DeepSeek generation and Judge | Not run; not reported as passed |

The source-retrieval failure remains visible in the benchmark. Reference annotations are provisional, and the holiday calendar currently covers 2026. Refresh calendar/pricing sources and complete human reference review before interpreting later evaluations as verified Ground Truth.

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
