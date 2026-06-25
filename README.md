# 📄 Multi-Agent PDF Analysis System

A LangGraph-based Multi-Agent PDF Analysis System powered by DeepSeek, featuring dynamic LLM planning, Retrieval-Augmented Generation (RAG), conversation memory, and specialized AI agents for intelligent PDF understanding.

---

## ✨ Features

- 🤖 Multi-Agent Architecture
- 🧠 LLM Planner for Dynamic Agent Selection
- 📚 Retrieval-Augmented Generation (RAG)
- 💬 Conversation Memory Manager
- 📄 Multi-PDF Analysis
- 🔍 Source Citation
- 📝 PDF Summarization
- 🔑 Keyword Extraction
- 📊 Cross-PDF Comparison
- ❓ PDF Question Answering
- 🔄 Reviewer Agent for Final Answer Synthesis
- 🌐 Streamlit Web Interface

---

## 🏗️ System Architecture

```text
                     User
                      │
                      ▼
               Memory Manager
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
Conversation   Session Memory   Recent Memory
Summary Memory
                      │
                      ▼
               Planner Agent
                      │
                      ▼
        ───────────────────────────────
             Specialist Agents
        ───────────────────────────────

        • QA Agent
        • Summary Agent
        • Keyword Agent
        • Compare Agent
        • Source Agent

                      │
                      ▼
               Reviewer Agent
                      │
                      ▼
                 Final Answer
```

---

## 🚀 Technologies

| Category | Technology |
|-----------|------------|
| Language | Python |
| Framework | LangGraph |
| UI | Streamlit |
| LLM | DeepSeek-V4-Flash |
| Embedding | OpenAI Embeddings |
| Vector Database | FAISS |
| Retrieval | RAG |
| Workflow | LangGraph StateGraph |
| Memory | Conversation Memory Manager |
| Agents | Multi-Agent Architecture |
| Planning | LLM Planner |
| PDF Processing | LangChain PDF Loader |
| Prompting | Prompt Engineering |

---

# 🤖 Multi-Agent Design

## Planner Agent

Responsible for understanding the user's request and dynamically selecting specialist agents.

Example:

```text
User

↓

Compare these papers and summarize them

↓

Planner Agent

↓

["compare", "summary"]
```

---

## Specialist Agents

### QA Agent

- Answer user questions using uploaded PDFs.

### Summary Agent

- Generate structured summaries for each uploaded PDF.

### Keyword Agent

- Extract important keywords and concepts.

### Compare Agent

- Compare multiple PDFs by topic, methodology, findings, and conclusions.

### Source Agent

- Retrieve evidence, filenames, page numbers, and supporting sources.

---

## Reviewer Agent

Collect outputs from specialist agents and synthesize a coherent final response.

---

# 🧠 Memory Manager

The system includes a conversation memory manager for maintaining contextual understanding.

### Conversation Summary Memory

- Uses DeepSeek to summarize older conversations.

### Recent Conversation Memory

- Maintains recent dialogue for follow-up questions.

### Session Memory

- Tracks currently uploaded PDFs.

### Cached Memory

- Caches conversation summaries to reduce unnecessary LLM calls.

---

## 🔄 Workflow

```text
User Question
        │
        ▼
Planner Agent
        │
        ▼
Specialist Agent(s)
        │
        ▼
Reviewer Agent
        │
        ▼
Final Answer
```

---

## 📚 Supported Tasks

- Ask questions about uploaded PDFs
- Summarize one or multiple PDFs
- Extract keywords
- Compare multiple documents
- Retrieve supporting evidence
- Handle follow-up questions
- Analyze multiple PDF files simultaneously

---

## 📂 Project Structure

```text
PDF-Agent/
│
├── agent/
│   ├── graph_agent.py
│   ├── llm_planner.py
│   ├── reviewer_agent.py
│   ├── qa_agent.py
│   ├── summary_agent.py
│   ├── keyword_agent.py
│   ├── compare_agent.py
│   ├── source_agent.py
│   └── state.py
│
├── tools/
│   ├── pdf_qa_tool.py
│   ├── pdf_summary_tool.py
│   ├── keyword_tool.py
│   ├── compare_tool.py
│   └── source_tool.py
│
├── utils/
│   ├── deepseek_client.py
│   ├── final_synthesizer.py
│   └── memory.py
│
├── main.py
├── requirements.txt
└── README.md
```

---

## ⚙️ Installation

### Clone the repository

```bash
git clone https://github.com/your-username/PDF-Agent.git
cd PDF-Agent
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure environment variables

Create a `.env` file:

```env
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_MODEL=deepseek-v4-flash
OPENAI_API_KEY=your_embedding_key
```

### Run

```bash
streamlit run main.py
```

---

## 🐳 Docker

Build the Docker image:

```bash
docker build -t pdf-agent .
```

Run the container:

```bash
docker run -p 8501:8501 pdf-agent
```

---

## 🔮 Future Improvements

- Agent Collaboration
- Parallel Agent Execution
- Reflection Agent
- Long-Term Memory
- Multi-Modal PDF Analysis
- Agent Evaluation Pipeline

---

## ⭐ Highlights

- LangGraph Multi-Agent Workflow
- Dynamic LLM Planning
- Retrieval-Augmented Generation (RAG)
- Conversation Memory Manager
- Conversation Summary Memory
- Tool Chaining
- Multi-Step Reasoning
- Modular Agent Design
- Production-Oriented Architecture

---

## 📄 License

This project is intended for educational and research purposes.