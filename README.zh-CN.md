# 多智能体 PDF 分析系统

[English](README.md) | **简体中文**

一个面向生产部署的 PDF 分析应用，基于 **LangGraph、FastAPI、React 和 DeepSeek** 构建。项目将检索增强生成、专业 Agent、对话记忆、多 Agent 协作以及有界 Reflection/Retry 整合进一套可观测工作流。

[**在线体验**](https://pdf-agent-bxjp.onrender.com) | [**API 文档**](https://pdf-agent-bxjp.onrender.com/docs)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/remberr/PDF-Agent)

## 项目亮点

- 通过基于 Session 的 Web 应用分析一个或多个 PDF
- 将请求路由给问答、总结、关键词、对比和来源 Agent
- 并发执行相互独立的专业 Agent，同时保持 Planner 的步骤顺序
- 在最终合成前协调多个 Agent 的输出
- 当证据或专业能力覆盖不足时执行有界 Reflection/Retry
- 基于 FAISS 检索片段生成答案，并提供文件名与页码引用
- 结合近期对话、历史摘要和当前 PDF Session 上下文
- 通过 SSE 在 React 界面实时展示工作流事件和节点耗时
- 使用 SQLite 保存 Session 元数据，并将 FAISS 索引持久化到磁盘
- 通过确定性的 Planner、Source 和 Reviewer 快路径降低延迟与 Token 消耗
- 将前端和后端打包为一个生产 Docker 服务

## 系统架构

```text
浏览器
  |
  v
React + TypeScript
  |
  | REST + Server-Sent Events
  v
FastAPI
  |
  +-- Session Service --------> SQLite
  +-- PDF Service ------------> PyPDFLoader -> 文本分块 -> FAISS
  |
  v
LangGraph Workflow
  |
  v
Hybrid Planner
  |
  v
并发 Specialist Agent(s)
  |
  +-- Retriever -------------> 相关 PDF 片段
  +-- Memory Manager --------> 对话与 Session 上下文
  |
  v
Workflow Controller
  |
  +-- 单个结果 -------------> Reviewer 快路径
  |
  +-- 多个结果 -------------> Collaboration Agent
                                 |
                                 v
                             Revision Controller
                                 |
                                 +-- 必要时最多重试一次
                                 |
                                 v
                             Reviewer Agent
                                 |
                                 v
                             带引用的最终答案
```

生产容器由同一个 FastAPI 服务提供编译后的 React 应用、API 和 SSE 流。这样既简化了部署，也避免了生产环境中的跨域配置。

## Agent 工作流

### Hybrid Planner

Planner 返回有序的专业 Agent 步骤列表：

```text
qa | source | summary | keyword | compare
```

明确的中英文意图使用确定性路由，模糊请求才回退到 DeepSeek。这样既保留了动态规划能力，也避免了每个问题都调用一次 Planner LLM。

### Specialist Agents

| Agent | 职责 |
| --- | --- |
| QA Agent | 根据检索到的 PDF 证据回答问题 |
| Summary Agent | 总结文档内容 |
| Keyword Agent | 提取重要概念和术语 |
| Compare Agent | 从方法、发现和结论等方面对比多个 PDF |
| Source Agent | 确定性地生成文件名、页码、引用和摘录元数据 |

相互独立的 Specialist 在有界线程池中并发运行，输出仍按 Planner 顺序收集，因此并发执行不会让最终结果的顺序变得不确定。

### Collaboration 与 Reflection

只有在存在多个 Specialist 输出时，Collaboration Agent 才会运行。它负责合并重复结论、检测矛盾、识别缺失信息，并返回结构化的重试决策：

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

Revision Controller 可以补充缺失的 Specialist 步骤，并最多重试一次：

```python
MAX_REVISION_COUNT = 1
```

这种设计既保留了 Reflection 的适应能力，也防止无限循环和不可控的模型成本。

### Reviewer

Reviewer 将多 Agent 输出和协作备注合成为一个带引用的答案。对于只有一个 Specialist 的请求，工作流使用透传快路径，因为额外改写只会增加延迟，通常不会增加有效信息。

### 工作流示例

```text
直接提问
  -> Planner [qa]
  -> QA Agent
  -> Reviewer 快路径
  -> 最终答案

对比并提供引用
  -> Planner [compare, source]
  -> Compare Agent + Source Agent 并发执行
  -> Collaboration Agent
  -> Revision Controller
  -> Reviewer Agent
  -> 最终答案

协作阶段发现缺少总结
  -> Collaboration 请求 [summary]
  -> Summary Agent
  -> Collaboration Agent
  -> Reviewer Agent
  -> 最终答案
```

## 检索与记忆

上传的 PDF 会经过以下 RAG 流程：

```text
PDF -> PyPDFLoader -> 文本分块 -> 多语言 Embedding -> FAISS
                                                   |
问题 -> Retriever --------------------------------+
                                                   |
                                                   v
                                           Specialist Prompt
```

检索片段携带稳定的引用元数据：

```text
Citation: [example.pdf, page 3]
PDF: example.pdf
Page: 3
Content: ...
```

Memory Manager 是 Prompt 上下文组件，而不是独立的 LangGraph 节点。它提供：

- 最近的对话消息
- 较早对话历史的缓存摘要
- 当前 PDF Session 中可用的文件名

检索到的 PDF 片段与对话记忆保持分离。这种区分让文档证据更加明确，也让来源引用更容易检查。

## FastAPI 后端

后端通过 HTTP 提供基于 Session 的 PDF 分析接口：

| 方法 | 接口 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 服务健康检查 |
| `POST` | `/sessions` | 创建 PDF 分析 Session |
| `GET` | `/sessions/{session_id}` | 查看 Session 元数据 |
| `DELETE` | `/sessions/{session_id}` | 删除 Session 及其 FAISS 索引 |
| `POST` | `/sessions/{session_id}/pdfs` | 上传一个或多个 PDF |
| `POST` | `/sessions/{session_id}/ask` | 执行工作流并返回完整响应 |
| `POST` | `/sessions/{session_id}/ask/stream` | 流式返回工作流进度和最终结果 |

交互式 OpenAPI 文档位于 `/docs`。

### 流式工作流

SSE 接口会为正在运行和已经完成的节点发送 `progress` 事件，最后发送一个 `result` 事件。每次请求都会返回 Planner 步骤、重试次数、节点耗时、总耗时、协作备注和来源摘录。

```text
event: progress
data: {"node":"specialists","status":"completed",...}

event: result
data: {"answer":"...","sources":[...],"timings":{...}}
```

### 数据持久化

- SQLite 保存 Session ID、已上传文件名、对话历史、文档数量和 Vectorstore 路径。
- 每个 Session 都拥有独立的持久化 FAISS 索引。
- `PDF_AGENT_DATA_DIR` 控制数据根目录，默认值为 `app/data`。
- Session 默认在 24 小时无活动后过期，每次读取或写入都会刷新 TTL。
- 定时清理任务默认每小时删除过期的 SQLite 记录和孤立 FAISS 目录。
- `SESSION_TTL_SECONDS` 和 `SESSION_CLEANUP_INTERVAL_SECONDS` 用于配置这两个时间。
- Docker 和 Render 将 `/data` 挂载为持久化卷。
- 当前架构面向单应用实例；横向扩展时应将元数据和向量迁移到共享托管服务。

## Web 应用

React 工作区提供：

- 中英文切换
- 多 PDF 上传和浏览器端 Session 恢复
- Markdown 答案与可展开的来源摘录
- 实时展示 Planner、Specialist、Collaboration、Revision 和 Reviewer 状态
- 节点执行耗时与工作流总耗时
- API 健康状态和可读的错误提示
- 响应式桌面端与移动端布局

## 性能与可靠性

当确定性行为更加可靠时，工作流会避免冗余的模型调用：

- 明确的中英文意图跳过 LLM Planner
- 普通问题直接路由到 QA
- 来源引用直接根据检索元数据生成，不调用 LLM
- 单 Specialist 响应跳过 Reviewer 改写
- 相互独立的 Specialist 并发执行
- 只有模糊规划、多 Agent 协作和多 Agent 审查保留 LLM 能力

普通 QA 请求只需要一次 LLM 调用。带来源的 QA 请求只有在多个输出需要协调时才使用 Collaboration 和 Reviewer。

工作流包含可降级的错误处理：

- Planner 失败时回退到 `qa`
- 单个 Specialist 失败不会丢弃其他成功输出
- Collaboration 失败时保留已有结果并跳过重试
- Reviewer 失败时返回 Specialist 输出
- Memory 摘要失败时忽略摘要记忆
- API 校验和 Session 错误返回结构化 HTTP 响应
- PDF 解析完成后清理临时上传文件

## 快速开始

### Docker

根据 `.env.example` 创建 `.env`，并添加 DeepSeek API Key：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-v4-flash
SESSION_TTL_SECONDS=86400
SESSION_CLEANUP_INTERVAL_SECONDS=3600
```

构建并启动生产应用：

```bash
docker compose up --build -d
```

访问：

```text
应用:     http://127.0.0.1:8000
API 文档: http://127.0.0.1:8000/docs
```

容器重建后，SQLite 和 FAISS 数据仍会保留在 `pdf-agent-data` Docker Volume 中。

### 本地开发

安装 Python 依赖并启动 FastAPI：

```bash
pip install -r requirements.api.txt
uvicorn app.main:app --reload
```

在第二个终端中启动 React 开发服务器：

```bash
cd frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。Vite 应用默认连接 `http://127.0.0.1:8000`。

## 部署

仓库包含 Render Blueprint 和多阶段 Docker 构建：

- Node 负责构建 React 前端。
- Python 安装 API 依赖和 CPU-only PyTorch。
- 多语言 Embedding 模型被预先缓存到镜像中。
- FastAPI 在 Render 分配的端口上提供完整应用。
- `/data` 挂载持久化磁盘，用于保存 SQLite 和 FAISS。
- 生命周期清理任务会删除长时间无活动的 Session 和孤立索引。
- 容器和部署平台通过 `/health` 执行健康检查。

点击本文档顶部的按钮即可部署。Blueprint 默认使用新加坡区域的 2 GB 计算实例和 1 GB 持久化磁盘。创建服务时需要将 `DEEPSEEK_API_KEY` 填写为 Render Secret。

## 项目结构

```text
PDF-Agent/
|-- agent/
|   |-- graph_agent.py             # LangGraph 节点、路由与并发执行
|   |-- state.py                   # 类型化工作流状态
|   |-- llm_planner.py             # Hybrid Planner
|   |-- collaboration_agent.py     # 多 Agent 协作与重试决策
|   |-- reviewer_agent.py          # 最终合成与快路径
|   `-- *_agent.py                 # Specialist Agents
|
|-- app/
|   |-- main.py                    # FastAPI 应用与 React 静态资源托管
|   |-- api/routes.py              # Session、上传、问答和 SSE 接口
|   |-- schemas/                   # 类型化 API 请求与响应模型
|   `-- services/                  # Agent、PDF 和持久化服务
|
|-- frontend/
|   `-- src/                       # React UI、API Client 与工作流组件
|
|-- tools/                         # 检索、总结、关键词和对比工具
|-- utils/                         # LLM Client、Memory、引用、分块与 FAISS
|-- tests/                         # Planner、并发、Reviewer、Source 与 SSE 测试
|-- Dockerfile
|-- compose.yaml
|-- render.yaml
|-- requirements.api.txt
`-- requirements.txt
```

## 测试

运行 Agent 快路径和流式接口测试：

```bash
python -m unittest discover -s tests -v
```

测试覆盖确定性规划、中文意图路由、关键词误匹配防护、Specialist 并发执行、Reviewer 快路径、来源格式化、SSE 工作流事件、数据库迁移、Session TTL、主动删除和孤立索引清理。

## 技术栈

| 领域 | 技术 |
| --- | --- |
| Agent 编排 | LangGraph |
| LLM | DeepSeek，通过 OpenAI 兼容 Client 调用 |
| 后端 | FastAPI、Uvicorn、Server-Sent Events |
| 前端 | React、TypeScript、Vite |
| 检索 | LangChain、FAISS、HuggingFace Embeddings |
| PDF 解析 | PyPDFLoader / pypdf |
| 持久化 | SQLite 与持久化 FAISS 索引 |
| 部署 | Docker Compose 与 Render Blueprint |

## 可选 Streamlit 原型

仓库在 `main.py` 中保留了最初的 Streamlit 原型，用于历史对比和直接调试工作流。它不属于生产架构，也不会进入 Docker 部署。

```bash
pip install -r requirements.txt
streamlit run main.py
```

## 简历项目重点

这个项目展示的不只是一个基础聊天界面，还包括：

- 类型化 LangGraph State 与条件路由
- 确定性规则和 LLM 相结合的 Hybrid Planning
- Specialist 并发执行
- 结构化 Collaboration 与有界 Reflection/Retry
- 带可检查页码引用的 RAG
- 对话记忆与 Session 文档上下文分离
- 统一的 LLM 配置与降级处理
- 基于 Session 的 FastAPI API 设计
- SSE 实时可观测性
- 使用 Docker 的单实例持久化部署

## 后续优化

- 增加自动化答案质量和引用质量评估
- 增加结构化应用日志和工作流日志
- 使用 PostgreSQL 和共享向量数据库支持横向扩展
- 增加身份认证、Session 所有权和上传配额
- 增加图表与表格的多模态提取能力

## License

本项目用于学习和作品集展示。
