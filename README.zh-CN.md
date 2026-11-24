# PDF Agent

[English](README.md) · **简体中文**

PDF Agent 提供 React 和 FastAPI 工作台，可针对 PDF 提问并追溯引用的文件和页码。LangGraph 多 Agent 工作流使用 BGE-M3 编码，在 PostgreSQL 中通过 pgvector 检索。本文介绍的工程成熟化能力已在本地验收，Render 和生产数据库尚未升级至这一版本。

## 可以做什么

- **多 Agent 文档分析。** 在同一会话中上传多份 PDF，进行问答、摘要、关键词、跨文档比较和来源查询。Planner 选择可并行执行的专项 Agent，Collaboration 可在最终复核前触发一轮补充修订。Planner 和 Collaboration 输出经过结构校验，非法输出走确定性回退。
- **执行进度和终态。** POST SSE 提供进度、引用和最终结果。JSON 与 SSE 都区分成功、降级、失败、取消以及结果是否保存。流中断时可识别缺失终态，避免自动重发生成请求。
- **会话 Memory 与请求预算。** 在受限窗口内使用近期消息，必要时摘要较早的对话。摘要缓存按会话和上下文隔离。一次请求共享调用次数、Token 预留、预估美元费用和时间预算。界面展示 Token 用量、缓存统计可用性和独立估算的人民币或美元费用。
- **匿名会话。** 浏览器用安全的 HttpOnly Cookie，脚本可请求 Bearer 令牌。凭据仅用于对应会话。刷新可恢复文档和服务端上下文，页面可见聊天回合保存在内存中。

## 工作流程

```text
PDF → PyPDFLoader → 文本切块 → BGE-M3 → PostgreSQL + pgvector
问题 → Planner → 当前会话检索与专项 Agent → Collaboration / Reviewer
React ← FastAPI JSON 或 POST SSE ← 回答、引用和执行终态
```

Alembic 管理会话、消息、文档元数据、文本片段、向量、凭据和在途请求租约。上传时文档和片段在同一事务中写入。SQLite 和 FAISS 用于离线迁移与恢复工具。

## 用 Docker 本地运行

准备 Docker 和 Compose。将 [`.env.example`](.env.example) 复制为 `.env`，设置本地数据库密码和 Compose 连接地址：

```dotenv
POSTGRES_PASSWORD=<本地密码>
DOCKER_DATABASE_URL=postgresql+psycopg://pdf_agent:<URL编码后的密码>@db:5432/pdf_agent_local
DEEPSEEK_API_KEY=<仅查询来源时可留空>
```

生成回答需要 DeepSeek API Key。只做来源查询时，将 `DEEPSEEK_API_KEY=` 留空。验收流程会在 API 容器显式设置 `PDF_AGENT_DISABLE_LLM_API=1`。在新的本地数据卷上执行：

```sh
docker compose -f compose.vector.yaml up -d --wait db
docker compose -f compose.vector.yaml exec db createdb -U pdf_agent pdf_agent_local
docker compose -f compose.vector.yaml --profile app up -d --build --wait
```

`pdf_agent_local` 已存在时跳过 `createdb`。迁移服务会先于 API 执行。容器的 HTTP 端口提供[接口文档](http://127.0.0.1:8001/docs)和[健康检查](http://127.0.0.1:8001/health)。浏览器工作台可按[本地 HTTPS 前端](docs/DEVELOPMENT.md#运行和调试)设置 `PDF_AGENT_DEV_BACKEND=http://127.0.0.1:8001`，或在容器前配置同源 HTTPS 反向代理。首次构建会下载固定版本的 BGE-M3，容器运行时从缓存加载。

在主机上开发时使用 Python 3.11 和 Node.js 22。主机连接地址、Alembic、模型缓存和前端命令见[开发指南](docs/DEVELOPMENT.md)和[本地 PostgreSQL 配置](docs/LOCAL_STORAGE.md)。使用默认 `compose.yaml` 时，需要显式指定容器可访问且已完成迁移的 `DATABASE_URL`。

## 常用接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| POST | `/sessions` | 创建会话 |
| GET / DELETE | `/sessions/{session_id}` | 查看或删除会话 |
| POST | `/sessions/{session_id}/pdfs` | 通过 multipart 的 `files` 字段上传 PDF |
| POST | `/sessions/{session_id}/ask` | 获取回答和引用 |
| POST | `/sessions/{session_id}/ask/stream` | 流式接收工作流事件与最终结果 |

脚本创建会话时发送 `X-Session-Mode: bearer`，从响应中保存一次性返回的 `session_token`，后续会话请求发送 `Authorization: Bearer <token>`。凭据 24 小时到期。先上传 PDF，再向问答接口提交 JSON，例如 `{"question":"Show the sources."}`。浏览器的 Cookie 流程使用开发指南中的同源 HTTPS 配置。

## 测试与评估

```sh
python -m unittest discover -s tests -t . -v
npm --prefix frontend test
npm --prefix frontend run build
python -m evaluation.runner --mode routing
```

请求限额与重试行为见[预算配置](docs/DEVELOPMENT.md#llm-budgets)。CI 和默认单元测试关闭供应商调用。live 或 real-pdf 生成和 Judge 需要显式 `--allow-paid-api`。Routing 与仅 Source 检查可零 LLM 运行。预留量用于估算，取消无法撤回已发到供应商的请求。

PostgreSQL 集成测试、离线恢复和真实 PDF 评估见[测试指南](docs/TESTING.md)。请使用独立测试库，并将 PDF 和生成的报告留在 Git 忽略目录。只做本地检索时，将 `DATABASE_URL` 指向已迁移的测试库，然后运行：

```sh
python -m evaluation.runner --mode real-pdf --pdf-dir /path/to/pdfs --retrieval-only --output .evaluation-local/retrieval.json
```

本地验收覆盖匿名访问、上传、会话内检索、Source JSON/SSE、重启持久化、TTL 清理及离线恢复。此前迁移评估在三份 PDF 的 30 条用例和 90 条证据引文上测得 60.7% 的平均预期页召回率。该指标衡量检索覆盖。生成和 Judge 质量由独立任务评估。本轮结果及跳过事项见[阶段记录](plans/TASKS.md#current-execution)。

## 数据与部署

- PostgreSQL 保存对话上下文和提取片段。浏览器 Web Storage 只保留活动会话定位值和语言偏好。应用清理旧聊天缓存，对应用日志中的会话 ID、原始路径和异常正文做脱敏。生成回答时，问题和相关片段可能发送给配置的模型供应商。
- 数据库自动清理默认关闭。需要自动删除时可启用 `SESSION_RETENTION_ENABLED`。显式删除会话会一并清理其消息、文档和向量。凭据到期后，已有数据仍按数据库保留策略处理。
- 迁移旧 SQLite/FAISS 数据前，先阅读[本地存储与恢复指南](docs/LOCAL_STORAGE.md)。离线迁移工具使用[独立依赖](requirements.migration.txt)。
- 当前里程碑是本地发布候选。部署前仍需核验 Render 配置、生产备份与迁移、公开 HTTPS 来源及网关日志。

[架构说明](docs/ARCHITECTURE.md) · [开发指南](docs/DEVELOPMENT.md) · [测试指南](docs/TESTING.md) · [路线图](plans/ROADMAP.md) · [任务记录](plans/TASKS.md)
