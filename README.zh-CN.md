# 多智能体 PDF 分析系统

[English](README.md) | **简体中文**

一个面向生产部署的 PDF 分析应用，基于 **LangGraph、FastAPI、React 和 DeepSeek** 构建。项目将检索增强生成、专业 Agent、对话记忆、多 Agent 协作以及有界 Reflection/Retry 整合进一套可观测工作流。

[**在线体验**](https://pdf-agent-bxjp.onrender.com) | [**API 文档**](https://pdf-agent-bxjp.onrender.com/docs)

[![CI](https://github.com/remberr/PDF-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/remberr/PDF-Agent/actions/workflows/ci.yml)
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

SSE 接口会为正在运行和已经完成的节点发送 `progress` 事件，最后发送一个 `result` 事件。每次请求都会返回 Planner 步骤、重试次数、节点耗时、总耗时、协作备注、来源摘录和累计 LLM 用量。

```text
event: progress
data: {"node":"specialists","status":"completed",...}

event: result
data: {"answer":"...","sources":[...],"timings":{...},"usage":{...}}
```

### 结构化日志与成本观测

- 应用、HTTP、工作流、PDF 生命周期和 LLM 事件均以 JSON 输出到 stdout。
- 每个 HTTP 响应都包含 `X-Request-ID`；请求日志、节点日志和模型调用日志使用同一 Request ID 与 Session ID 关联，并覆盖完整 SSE 生命周期。
- LLM 日志记录操作、模型、延迟、输入/输出 Token、缓存命中/未命中 Token、命中率、计价时段和预估美元费用。Prompt、PDF 正文、API Key 和答案不会进入日志。
- API 与 SSE 结果通过 `usage` 返回请求级汇总，并按 `by_model` 和 `by_operation` 拆分。Workflow 面板展示调用数、总 Token、缓存命中率、预估费用和各操作用量。
- Token 数量采用模型服务返回的实际 Usage；费用根据 [DeepSeek 当前峰谷和缓存计价](https://api-docs.deepseek.com/quick_start/pricing/)估算。官方价格变化后，可同时设置三个 `LLM_*_COST_PER_1M_TOKENS` 环境变量覆盖内置单价。

代表性事件包括 `http_request_completed`、`agent_node_completed`、`llm_call_completed`、`agent_workflow_completed`、`pdf_indexed` 和 `session_cleanup_completed`。

#### 在哪里查看日志与成本

- Render：进入 `pdf-agent` 服务并打开 **Logs**，可按 `request_id`、`session_id` 或事件名搜索，串联一次请求中的 HTTP、工作流和 LLM 调用。
- Docker Compose：运行 `docker compose logs -f pdf-agent`，实时查看相同的 JSON 日志。
- Web 应用：提交问题后打开 **Workflow / 工作流** 面板，查看 LLM 调用数、总 Token、缓存命中率、预估费用和各操作明细。
- API：`/ask` 响应以及 SSE 的 `progress`、`result` 事件都会通过 `usage` 返回请求级数据；最终 Usage 汇总也会随 Assistant 消息保存在 Session 中。

目前成本观测以单次请求和单个 Session 为范围，尚未提供持久化的全局历史成本 Dashboard。如需长期聚合，可将 JSON 日志接入外部日志平台。

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
- 请求级 LLM Token、缓存命中和预估费用观测
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
LOG_LEVEL=INFO
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
|-- evaluation/                    # 基准数据集、指标与评测 CLI
|-- tools/                         # 检索、总结、关键词和对比工具
|-- utils/                         # LLM、观测、Memory、引用与 FAISS
|-- tests/                         # 工作流、生命周期与 Evaluation 测试
|-- Dockerfile
|-- compose.yaml
|-- render.yaml
|-- requirements.api.txt
`-- requirements.txt
```

## Agent Evaluation

三种模式复用现有 Planner 和 LangGraph 工作流：

| 模式 | 输入与用途 | 模型请求 |
| --- | --- | --- |
| `routing` | 原 `evaluation/cases.json`，检查精确路由 | 内置确定性用例不调用模型 |
| `live` | 原受控 Document + `StaticVectorStore`，检查工作流回归 | 生成式用例及可选 Judge 调用 DeepSeek |
| `real-pdf` | 本地 PDF → 生产 PyPDFLoader → 1200/250 字符切分 → 生产多语言 MiniLM Embedding → FAISS → LangGraph | 生成和 Judge 需要显式开启付费请求 |

```bash
python -m evaluation.runner --mode routing --output evaluation-report.json
python -m evaluation.runner --mode live --case source-citations --output evaluation/reports/live-source.json
python -m evaluation.runner --mode live --llm-judge --output evaluation/reports/live.json
```

`evaluation/real_pdf_cases.json` 新增 30 条用例，覆盖 QA、Summary、Compare、Source、Keyword、多 Agent 组合、跨页检索、跨文档比较、信息遗漏、无答案和证据不足。`pdf_manifest.json` 固定所提供 GPT-2、BERT、Transformer 文件的名称、物理页数及 SHA-256。PDF、提取文本、索引和报告仅在本地保存，不提交仓库。真实 PDF 默认报告保存在已忽略的 `evaluation/reports/`，与受控报告区分。可用 `--dataset`、`--manifest`、`--case`（可重复）、`--limit`、`--output` 自定义执行。

将下方目录换成三份 PDF 所在位置：

```bash
# 不加载 Embedding、不调用模型：检查哈希、页码和原文证据。
python -m evaluation.runner --mode real-pdf --pdf-dir "C:/Users/31701/Downloads/pdf" --validate-only

# 使用生产 Embedding 和真实 FAISS 检索，不生成答案、不调用 Judge。
python -m evaluation.runner --mode real-pdf --pdf-dir "C:/Users/31701/Downloads/pdf" --retrieval-only

# LangGraph Source Agent + 真实 FAISS，无 DeepSeek 请求。
python -m evaluation.runner --mode real-pdf --pdf-dir "C:/Users/31701/Downloads/pdf" --case real-source-attention --output evaluation/reports/real-source.json

# 付费：先设置 DEEPSEEK_API_KEY，再显式开启真实生成与 Judge。
python -m evaluation.runner --mode real-pdf --pdf-dir "C:/Users/31701/Downloads/pdf" --allow-paid-api --llm-judge --output evaluation/reports/real-pdf.json
```

Embedding 首次运行可能从 Hugging Face 下载生产模型，之后复用缓存；设置 `HF_HUB_OFFLINE=1` 可强制仅用本地权重。FAISS 按 `pdf_files` 文档集合在内存中构建，每个集合在同一次执行中复用。该集合等价于生产会话上传的 PDF，不筛选参考页；整个集合的全部页面及干扰内容都进入索引。工作流仅收到问题、文件名和检索器，不收到参考答案或标注。生产 Agent 的查询策略和检索数量保持原样，因此摘要或比较可能遗漏事实，评估会如实暴露这些问题。

每条用例包含 `required_facts`（事实 ID、陈述、支撑引用 ID）、`expected_citations`（文件名、**从 1 开始的物理 PDF 页码**、原文摘录）、`forbidden_claims`、`reference_answer`、`answerability`、`expected_behavior` 和 `annotation`。原受控数据的 `documents[].page` 仍从 0 开始。BERT 的物理第 4 页印刷页码为 4174，两者不能混用。

**标注仍待人工审核。** 标注基于本地原文阅读、数字表格目视核对及摘录匹配编写，状态为 `pending_human_review` / `human_verified: false`，不是已经人工验证的 Ground Truth。原文匹配只验证来源，不能证明语义蕴含、事实完整性或信息确实不存在。人工复核应检查原始页面、文档范围、限定条件、事实与证据对应关系及拒答要求，再记录审核人、日期并更新状态；尤其不能仅凭检索词缺失证明无答案。Judge 将证据和候选答案中的内容视为不可信数据，不执行其中的指令。

可选 Judge 按语义评估事实正确性、完整性/遗漏、证据支持和相关性（各 1–5 分），检查每项事实、禁止断言、引用问题及合理拒答，并标记标注歧义。忠实改写可得分，不以关键词出现判断事实正确。受控 Live 保留旧关键词召回指标，真实 PDF 报告不使用该指标。确定性来源/引用指标只检查页码交集及引用是否来自检索结果，不能证明语义支持。`--min-source-recall`、`--min-citation-precision`、`--min-route-accuracy` 和 `--min-llm-judge-score` 控制门禁；任何 Judge 失败都会令开启 Judge 的评估失败。

报告使用 `schema_version: 2`。每条 Case 与 `summary` 都有独立的 `agent_usage`、`judge_usage`、`total_usage`，包含调用次数、输入/输出/总 Token、缓存命中/未命中 Token、美元估价及 `by_model` / `by_operation`。旧 `usage` 和 Summary 顶层费用、调用数、Token 字段继续仅表示 **Agent 用量**。`duration_ms` 累加 LLM 调用耗时（并发请求可能重叠），`elapsed_ms` 为 Agent 或 Judge 的墙钟耗时；PDF 解析及建索引时间单列于 `corpus`。Judge 非法 JSON 等失败仍保留已记录的用量、`judge_status: failed` 和 `llm_judge_error`。请求异常而服务未返回 Usage 时保留调用尝试并标记成本未知。调用次数是逻辑 SDK 调用次数，不能还原 SDK 内部重试及未返回的计费数据。

校验/纯检索报告使用独立模式名，`passed: null`、`generation_executed: false`、`quality_status: not_evaluated`；检索报告提供参考页召回诊断，不将执行成功冒充生成质量通过。不启用 Judge 的普通运行标记 `structural_metrics_only`；真实 PDF 的 Judge 结果在人工审核标注前标记 `provisional_llm_judged`。`passed` 只表示报告中所列阈值通过，不代表事实正确性得到认证。报告打印为 JSON，并按 `--output` 保存（真实模式有默认路径）；门禁失败或执行/配置出错返回非零退出码。

### 用量与成本计算

单价集中在 `utils/pricing.py`，于 2026-10-18 核对 [DeepSeek 官方美元价格](https://api-docs.deepseek.com/quick_start/pricing/)。`deepseek-flash` 与旧名称 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` 使用相同 Flash 费率；保留既有 chat/reasoner 别名，不修改项目配置的模型目标。

| USD / 1M Tokens | 谷时 | 峰时 |
| --- | ---: | ---: |
| Cache Hit | 0.003 | 0.006 |
| Cache Miss | 0.15 | 0.30 |
| Output | 0.60 | 1.20 |

费用为 `(命中 Token × 命中单价 + 未命中 Token × 未命中单价 + 输出 Token × 输出单价) / 1,000,000`。服务未提供未命中数时，使用输入中未归为命中的部分。按带时区的**请求开始时间**转换北京时间，周一至周五 `[09:00,12:00)`、`[14:00,18:00)` 为峰时，排除中国完整公共假期；周末（含调休上班的周末）全天谷时。

`utils/china_holidays.json` 当前覆盖 **2026 年**，记录[国务院通知](https://www.gov.cn/zhengce/content/202511/content_7047090.htm)及[政府镜像](https://www.beijing.gov.cn/zhengce/zhengcefagui/202511/t20251104_4258873.html)。新增年份应引用权威来源并记录核对日期，运行时不联网查询节假日。在可能的峰时窗口，未知年份、日历读取失败、无效价格或未知模型会返回 `cost_status: unavailable`、`cost_estimate_available: false`、解释性的 `pricing_warnings` 及 `estimated_total_cost_usd: null`。已知周末或窗口外仍能确定谷时。为兼容旧接口，数值字段 `estimated_cost_usd` / `known_cost_usd` 保留已知部分的费用小计；**unavailable 状态下的小计 0 不代表免费**。

同时设置 `LLM_CACHE_HIT_COST_PER_1M_TOKENS`、`LLM_CACHE_MISS_COST_PER_1M_TOKENS`、`LLM_OUTPUT_COST_PER_1M_TOKENS` 为非负有限数值，可覆盖所有时段，包括未知模型/年份；只设置部分值时，仅在内置时段可判断的情况下覆盖相应单价，无效值显式不可估价。估算不包含本地 Embedding 算力成本，也不能替代服务商账单。

## 测试

运行 Agent 快路径和流式接口测试：

```bash
python -m unittest discover -s tests -v
```

测试覆盖确定性规划、中文意图路由、关键词误匹配防护、Specialist 并发执行、Reviewer 快路径、来源格式化、SSE 工作流事件、结构化日志、Token/费用核算、Evaluation 指标、数据库迁移、Session TTL、主动删除和孤立索引清理。

普通套件使用测试 Embedding 和模型响应替身验证集成连接，不调用 DeepSeek。本地真实 PDF 与付费集成测试分别标记，默认跳过；有 API Key 本身不会开启付费测试。PowerShell 可显式执行：

```powershell
# 本地 PDF + 已缓存的生产 Embedding，不付费。
$env:HF_HUB_OFFLINE="1"
$env:PDF_AGENT_EVAL_PDF_DIR="C:/Users/31701/Downloads/pdf"
$env:PDF_AGENT_RUN_LOCAL_PDF_TESTS="1"
python -m unittest discover -s tests -p test_real_pdf_evaluation.py -v

# 付费集成：还需配置 DEEPSEEK_API_KEY。
$env:PDF_AGENT_RUN_PAID_TESTS="1"
python -m unittest discover -s tests -p test_real_pdf_evaluation.py -v
Remove-Item Env:PDF_AGENT_RUN_PAID_TESTS
```

GitHub Actions 会并行执行后端测试和前端生产构建，全部通过后再验证完整的生产 Docker 镜像。依赖缓存与 BuildKit 缓存可加快后续运行。

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
- 可复现的 Agent Evaluation、确定性 CI 门禁与可选 LLM Judge
- 关联式 JSON 日志与缓存感知的 LLM 成本观测
- 基于 Session 的 FastAPI API 设计
- SSE 实时可观测性
- 使用 Docker 的单实例持久化部署

## 后续优化

- 使用 PostgreSQL 和共享向量数据库支持横向扩展
- 增加身份认证、Session 所有权和上传配额
- 增加图表与表格的多模态提取能力

## License

本项目用于学习和作品集展示。
