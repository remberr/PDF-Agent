# Multi-Agent PDF Analysis System

A React, FastAPI, and LangGraph based PDF analysis application powered by DeepSeek. The system combines Retrieval-Augmented Generation (RAG), dynamic agent planning, conversation memory, multi-agent collaboration, and lightweight reflection/retry to answer questions over one or more uploaded PDFs.

This project is designed as a practical AI engineering portfolio project. It focuses on clear agent responsibilities, observable workflow traces, graceful error handling, and maintainable LLM client abstraction.

The project includes a React web workspace, a FastAPI backend API, and the original Streamlit interface.

## Features

- Upload and analyze one or more PDF files
- Ask questions grounded in retrieved PDF content
- Summarize documents
- Extract keywords and key concepts
- Compare multiple PDFs
- Retrieve supporting sources and page references
- Add stable citation IDs such as `[paper.pdf, page 3]` for retrieved PDF evidence
- Maintain recent conversation and summarized long-term chat context
- Dynamically select specialist agents with a hybrid fast-path/LLM planner
- Coordinate multi-agent outputs with a Collaboration Agent
- Use lightweight reflection/retry when important information is missing
- Run independent specialist agents concurrently
- Synthesize final answers with a Reviewer Agent
- Stream live workflow progress and per-node timings to the React UI
- Display workflow traces in the Streamlit UI
- Use a responsive React workspace for PDF upload, chat, citations, and workflow traces
- Expose session-based PDF upload and question answering through FastAPI
- Centralize DeepSeek client configuration and error handling

## Architecture

```text
User Question
    |
    v
React Web UI
    |
    v
FastAPI Session API
    |
    +-- SQLite session metadata
    +-- persisted FAISS indexes
    |
    v
LangGraph Workflow
    |
    v
Planner Agent
    |
    v
Specialist Agent(s) in parallel
    |
    +-- Retriever -> FAISS PDF chunks
    |
    +-- Memory Manager -> conversation/session context
    |
    v
LLM Prompt Context
    |
    v
Workflow Controller
    |
    +-- single-agent output -------> Reviewer Agent ---> Final Answer
    |
    +-- multi-agent output --------> Collaboration Agent
                                      |
                                      v
                                  Revision Controller
                                      |
                                      +-- retry needed ---> Specialist Agent(s)
                                      |
                                      +-- no retry -------> Reviewer Agent
                                                              |
                                                              v
                                                         Final Answer
```

The original Streamlit UI remains available as a separate direct interface to the LangGraph workflow.

## React Web Frontend

The `frontend/` application is a responsive TypeScript workspace connected to the FastAPI session endpoints. It includes English/Chinese language switching, document upload, browser-side session restoration, Markdown answers, expandable source excerpts, API health status, and an observable agent workflow panel.

Install and run the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open the web application:

```text
http://127.0.0.1:5173
```

The default backend URL is `http://127.0.0.1:8000`. For a deployed API, copy `frontend/.env.example` to `frontend/.env` and set:

```env
VITE_API_BASE_URL=https://your-api.example.com
```

## FastAPI Backend

The FastAPI version exposes the same PDF Agent workflow through HTTP endpoints.

FastAPI sessions are persisted with SQLite, while each session's FAISS vectorstore is saved to disk under `app/data/`. This keeps uploaded PDF sessions recoverable across API process restarts in a single-instance deployment.

Run the API server:

```bash
uvicorn app.main:app --reload
```

Open the interactive API docs:

```text
http://127.0.0.1:8000/docs
```

### API Endpoints

Create a session:

```http
POST /sessions
```

Upload PDFs into a session:

```http
POST /sessions/{session_id}/pdfs
Content-Type: multipart/form-data
```

Ask a question:

```http
POST /sessions/{session_id}/ask
Content-Type: application/json
```

Stream workflow progress and the final answer with Server-Sent Events:

```http
POST /sessions/{session_id}/ask/stream
Content-Type: application/json
Accept: text/event-stream
```

The stream emits `progress` events for Planner, Specialists, Collaboration, Revision, and Reviewer, followed by one `result` event.

Request body:

```json
{
  "question": "Compare the uploaded papers and cite sources."
}
```

Example response:

```json
{
  "answer": "...",
  "steps": ["compare", "source"],
  "sources": [
    {
      "citation_id": "example.pdf, page 3",
      "source": "example.pdf",
      "page": 3,
      "excerpt": "..."
    }
  ],
  "collaboration_notes": {
    "status": "success",
    "issues": [],
    "missing_information": [],
    "recommendations": [],
    "needs_revision": false,
    "next_steps": []
  },
  "revision_count": 0,
  "timings": {
    "planner": 1.2,
    "compare": 2140.5,
    "source": 4.8,
    "specialists": 2142.1,
    "collaboration": 1200.4,
    "reviewer": 1350.7,
    "total": 4701.6
  }
}
```

The Memory Manager is not a standalone LangGraph node. It is one of the context sources used when specialist agents call the LLM. Retrieved PDF chunks and conversation/session memory are combined into the final prompt context.

## Agent Design

### Planner Agent

The Planner Agent analyzes the user request and returns an ordered list of specialist steps. Clear English and Chinese intents use deterministic fast paths, while ambiguous requests fall back to the LLM planner. This preserves adaptive planning without paying for an LLM request on every question.

Example:

```text
User: Compare these papers and provide sources.
Planner: ["compare", "source"]
```

Supported specialist steps:

- `qa`
- `source`
- `summary`
- `keyword`
- `compare`

### Specialist Agents

Each specialist agent owns one focused capability:

- `QA Agent`: answers user questions using retrieved PDF context
- `Source Agent`: deterministically formats retrieved filenames, page numbers, citations, and excerpts without an extra LLM request
- `Summary Agent`: generates document summaries
- `Keyword Agent`: extracts important concepts and terminology
- `Compare Agent`: compares multiple PDFs across topics, methods, findings, and conclusions

Independent specialists selected for the same planning pass run concurrently in a bounded thread pool. Their outputs are collected in the original planner order, and a revision pass executes only newly requested steps.

### Collaboration Agent

The Collaboration Agent runs only when multiple specialist outputs are available. It coordinates agent outputs before final review.

It returns structured collaboration notes:

```python
{
    "answer": "...",
    "issues": [...],
    "missing_information": [...],
    "recommendations": [...],
    "needs_revision": false,
    "next_steps": []
}
```

The collaboration layer helps the system:

- merge overlapping findings
- detect contradictions
- identify missing evidence
- decide whether another specialist step is worth running
- avoid unnecessary retry for simple single-agent requests

### Revision Controller

The Revision Controller reads the Collaboration Agent decision and controls retry behavior.

Current retry policy:

```python
MAX_REVISION_COUNT = 1
```

This keeps the workflow adaptive without allowing infinite loops.

### Reviewer Agent

The Reviewer Agent synthesizes specialist outputs and collaboration notes into one final answer for the user. Single-specialist answers use a pass-through fast path, while multi-agent results still use LLM synthesis for final answer quality.

## Performance Fast Paths

The workflow avoids redundant model requests where the result can be produced reliably without them:

- Explicit planner intents are routed deterministically in English and Chinese
- Normal direct questions route to the QA Agent without an LLM planning call
- Source citations are formatted directly from retrieved document metadata
- Single-specialist answers skip the redundant Reviewer LLM rewrite
- Multiple independent specialists run in parallel instead of waiting serially
- Ambiguous planning, multi-agent collaboration, and multi-agent review remain LLM-powered

This reduces a normal QA request from three LLM calls to one. A QA request with source citations drops from five LLM calls to three while retaining Collaboration and Reviewer behavior.

## Workflow Examples

### Single-Agent Question

```text
User asks a direct question
    |
Planner -> ["qa"]
    |
QA Agent
    |
Reviewer Agent
    |
Final Answer
```

The system skips collaboration and retry for simple requests to reduce latency and token cost.

### Multi-Agent Question With Collaboration

```text
User asks for comparison and sources
    |
Planner -> ["compare", "source"]
    |
Compare Agent
    |
Source Agent
    |
Collaboration Agent
    |
Revision Controller
    |
Reviewer Agent
    |
Final Answer
```

### Multi-Agent Question With Lightweight Retry

```text
Planner -> ["compare", "source"]
    |
Compare Agent + Source Agent
    |
Collaboration Agent detects missing summary
    |
Revision Controller adds "summary"
    |
Summary Agent
    |
Collaboration Agent
    |
Reviewer Agent
    |
Final Answer
```

## RAG Pipeline

```text
Uploaded PDFs
    |
PyPDFLoader
    |
Text splitting
    |
Embeddings
    |
FAISS vector store
    |
Retriever tools
    |
Specialist agents
```

The system retrieves relevant PDF chunks before calling the LLM, so answers are grounded in uploaded document content.

## Memory

The memory manager provides context for follow-up questions:

- Recent conversation memory
- LLM-generated summary of older conversation history
- Current PDF session memory based on all uploaded PDF filenames
- Cached conversation summaries

If memory summarization fails, the system falls back gracefully instead of stopping the workflow.

Retrieved PDF chunks are handled separately as `Relevant PDF Context`, so session memory describes which documents are available while retrieval context describes which chunks were selected for the current question.

## UI Workflow Trace

The Streamlit UI shows a workflow trace for each assistant answer, including:

- planned specialist steps
- whether collaboration was skipped or used
- Collaboration Agent status
- detected issues
- missing information
- recommendations
- revision attempts
- requested retry steps

The React UI consumes the SSE endpoint and updates the workflow while it runs. It shows active and completed nodes, specialist steps, revision status, per-node execution time, and total request time.

This makes the agent behavior observable during demos and debugging.

## Error Handling

The project includes graceful fallback paths:

- Planner failure falls back to `["qa"]`
- Collaboration failure skips retry and preserves available agent outputs
- Memory summary failure skips summary memory
- Reviewer failure returns raw specialist outputs
- Specialist agent failures are recorded without stopping the entire workflow
- Streamlit catches graph-level failures and returns a readable error message

## Source Citations

Retrieved PDF chunks are formatted with stable citation IDs before they are sent to the LLM:

```text
Citation: [example.pdf, page 3]
PDF: example.pdf
Page: 3
Content:
...
```

The assistant can then cite evidence using IDs such as `[example.pdf, page 3]`, and the Streamlit UI displays each source with its filename, page number, and excerpt.

## Temporary File Handling

Uploaded PDFs are written to temporary files only long enough for `PyPDFLoader` to read them. After loading, the app removes the temporary PDF path and also performs cleanup when the user clears all PDFs and chat history.

## Technology Stack

| Area | Technology |
| --- | --- |
| Language | Python |
| Web UI | React, TypeScript, Vite |
| Legacy UI | Streamlit |
| API | FastAPI |
| ASGI server | Uvicorn |
| Agent workflow | LangGraph |
| LLM provider | DeepSeek via OpenAI-compatible API |
| PDF loading | LangChain PyPDFLoader |
| Vector database | FAISS |
| Session persistence | SQLite |
| Retrieval | RAG |
| Embeddings | HuggingFace sentence-transformers |
| Environment config | python-dotenv |

## Project Structure

```text
PDF-Agent/
|-- frontend/
|   |-- src/
|   |   |-- components/
|   |   |-- api.ts
|   |   |-- App.tsx
|   |   |-- styles.css
|   |-- package.json
|   |-- vite.config.ts
|
|-- app/
|   |-- main.py
|   |-- api/
|   |   |-- routes.py
|   |-- schemas/
|   |   |-- requests.py
|   |   |-- responses.py
|   |-- services/
|   |   |-- agent_service.py
|   |   |-- pdf_service.py
|   |   |-- session_store.py
|
|-- agent/
|   |-- graph_agent.py
|   |-- state.py
|   |-- llm_planner.py
|   |-- collaboration_agent.py
|   |-- reviewer_agent.py
|   |-- qa_agent.py
|   |-- source_agent.py
|   |-- summary_agent.py
|   |-- keyword_agent.py
|   |-- compare_agent.py
|
|-- tools/
|   |-- pdf_qa_tool.py
|   |-- source_tool.py
|   |-- pdf_summary_tool.py
|   |-- keyword_tool.py
|   |-- compare_tool.py
|
|-- utils/
|   |-- llm_client.py
|   |-- deepseek_client.py
|   |-- final_synthesizer.py
|   |-- memory.py
|   |-- text_splitter.py
|   |-- vectorstore.py
|
|-- main.py
|-- requirements.txt
|-- README.md
```

## Installation

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-v4-flash
```

Run the application:

```bash
streamlit run main.py
```

Or run the FastAPI and React applications in separate terminals:

```bash
uvicorn app.main:app --reload
```

```bash
cd frontend
npm run dev
```

Run the agent fast-path tests:

```bash
python -m unittest discover -s tests -v
```

## Portfolio Highlights

This project demonstrates:

- LangGraph stateful workflow design
- Dynamic LLM-based agent planning
- Hybrid deterministic/LLM routing for lower latency
- RAG over uploaded PDF documents
- Multi-agent specialization
- Collaboration-based output coordination
- Lightweight reflection/retry with bounded revision count
- Centralized LLM client abstraction
- Graceful error handling and fallback design
- Observable workflow tracing in the UI
- SSE-based real-time workflow progress and timing telemetry
- Typed React integration with a session-based FastAPI backend
- Tested fast paths that avoid redundant LLM calls

## Future Improvements

- Add automated evaluation examples
- Add unit tests for planner parsing and collaboration retry decisions
- Add structured logging for agent workflow events
- Improve source citation formatting
- Add multimodal PDF support for figures and tables

## License

This project is intended for educational and portfolio use.
