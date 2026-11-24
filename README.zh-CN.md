# PDF Agent

[English](README.md) · **简体中文**

上传一份或多份 PDF，即可针对文档提问、比较内容，或从回答追溯到文件和页码。PDF Agent 由 React 界面、FastAPI 服务和 LangGraph 工作流组成，在 PostgreSQL 中保存对话和文档数据，使用 pgvector 和 BGE-M3 检索相关段落。

## 可以做什么

- 在会话中上传 PDF，进行问答、摘要、关键词提取、跨文档比较和来源查询。
- 通过 SSE 查看选中的 Agent、执行进度、耗时及最终引用。
- 结合最近的消息和历史摘要继续对话。互不依赖的 Agent 可以并行执行；工作流最多增加一轮修订。
- 查看 Token 用量、提示词缓存统计和费用估算。中文界面使用人民币定价，英文界面使用美元定价，两者独立计算。

## 工作流程

```text
PDF → PyPDFLoader → 文本切块 → BGE-M3 → PostgreSQL / pgvector
问题 → LangGraph 规划 → 当前会话检索与专项 Agent → 回答和引用
React ↔ FastAPI → 会话历史与 SSE 进度
```

检索范围限定在当前会话。PostgreSQL 保存会话、消息、文档元数据和向量；Alembic 管理数据库结构。运行时检索不依赖 FAISS。

## 用 Docker 本地运行

准备 Docker 和 Compose。将 [`.env.example`](.env.example) 复制为 `.env`，设置本地数据库密码和 Compose 连接地址：

```dotenv
POSTGRES_PASSWORD=<本地密码>
DOCKER_DATABASE_URL=postgresql+psycopg://pdf_agent:<URL编码后的密码>@db:5432/pdf_agent_local
DEEPSEEK_API_KEY=<仅查询来源时可留空>
```

需要生成回答时填写有效的 DeepSeek API Key；只走来源查询时可留空。在新的本地数据卷上执行：

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

先上传 PDF，再向问答接口提交 JSON，例如 `{"question":"Show the sources."}`。

## 测试与评估

```sh
python -m unittest discover -s tests -t . -v
npm --prefix frontend test
python -m evaluation.runner --mode routing
```

同一请求共享LLM调用、Token预留、USD费用预估和截止预算，配置及限制见[开发文档](docs/DEVELOPMENT.md#llm-budgets)。SDK自动重试关闭，应用重试默认零次。CI和默认单元测试禁止供应商网络访问；live/real-pdf生成及Judge要求显式`--allow-paid-api`，routing始终不调用模型。预留不是实际账单，取消不能撤回已发出的请求。

PostgreSQL 集成测试、离线恢复和真实 PDF 评估见[测试指南](docs/TESTING.md)。请使用独立测试库，并将 PDF 和生成的报告留在 Git 忽略目录。只做本地检索时，将 `DATABASE_URL` 指向已迁移的测试库，然后运行：

```sh
python -m evaluation.runner --mode real-pdf --pdf-dir /path/to/pdfs --retrieval-only --output .evaluation-local/retrieval.json
```

本地验收覆盖真实 PDF 上传、BGE-M3 向量写入、来源 Agent、SSE、重启持久化、TTL 清理及离线恢复。三份 PDF 的 30 条检索用例校验了 90 条证据引文，平均预期页召回率为 60.7%。该指标只衡量检索覆盖，不能代表回答质量。本地迁移验收未运行付费生成或 Judge。

## 数据与部署

- 匿名会话凭据绝对有效期为 24 小时。浏览器使用安全 Cookie，脚本可在创建时请求 Bearer 令牌。浏览器只保存活动会话定位值和语言偏好，刷新后清空页面聊天回合。
- 数据库自动清理默认关闭。需要自动删除时可启用 `SESSION_RETENTION_ENABLED`。显式删除会话会一并清理其消息、文档和向量。凭据到期后，已有数据仍按数据库保留策略处理。
- 迁移旧 SQLite/FAISS 数据前，先阅读[本地存储与恢复指南](docs/LOCAL_STORAGE.md)。离线迁移工具使用[独立依赖](requirements.migration.txt)。
- PostgreSQL/pgvector 已完成本地验证。本轮未切换 Render 或生产数据库，现有 Blueprint 不可当作新存储方案的部署指引。

[架构说明](docs/ARCHITECTURE.md) · [开发指南](docs/DEVELOPMENT.md) · [测试指南](docs/TESTING.md) · [路线图](plans/ROADMAP.md) · [任务记录](plans/TASKS.md)
