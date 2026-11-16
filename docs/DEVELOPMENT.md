> 本地存储已接入 PostgreSQL/pgvector；启动、迁移及保护历史数据的当前命令见 [LOCAL_STORAGE.md](LOCAL_STORAGE.md)。下文 SQLite/T15a 记录为历史基线，不能作为当前 API 启动条件。

# 本地开发

更新时间：2026-11-16 18:45（Asia/Shanghai）。以下从仓库根目录执行，除非注明进入 `frontend`。架构边界见 [ARCHITECTURE.md](ARCHITECTURE.md)，验证命令集中在 [TESTING.md](TESTING.md)。

## 环境准备

对齐 CI：Python 3.11、Node.js 22（支持 `--experimental-strip-types` 的版本）、npm；Docker 为可选。首次安装依赖和 Embedding 模型需要网络。Python 依赖未完整锁定，因此新环境的解析版本可能与既有环境不同。

```text
python -m venv .venv
```

激活虚拟环境：PowerShell 用 `.\.venv\Scripts\Activate.ps1`，POSIX shell 用 `source .venv/bin/activate`。若本机策略禁止激活，可直接用 `.\.venv\Scripts\python.exe` 替代后续 `python`，无需更改系统执行策略。

```text
python -m pip install torch==2.7.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.api.txt
```

这是当前 CI/Docker 的 CPU 路线，不是跨所有操作系统的安装保证；安装失败先检查 Python、平台及 wheel 支持。可选 Streamlit 原型需改用 `requirements.txt`，不影响主 Web 入口。

在本地从 [.env.example](../.env.example) 创建 `.env`，已有文件时只补缺失项，不覆盖。只有实际模型生成才需要有效 `DEEPSEEK_API_KEY`；普通离线测试见测试文档。不要把密钥放进前端变量或终端共享记录。模型默认值、价格覆盖说明以该示例和 [llm_client.py](../utils/llm_client.py)、[pricing.py](../utils/pricing.py) 为准。

## 运行和调试

终端一（已激活 Python 环境）：

```text
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --env-file .env
```

显式 `--env-file` 在导入应用前加载设置，避免各模块导入时读取环境的时序差异。当前默认数据目录相对工作目录，因此应在仓库根目录启动。会话保存在 `app/data`；需要独立测试数据目录时，在启动前设置 `PDF_AGENT_DATA_DIR`。不要把日常开发连到生产数据目录。

终端二：

```text
cd frontend
npm ci
npm run dev
```

访问 `http://127.0.0.1:5173`；后端健康检查 `http://127.0.0.1:8000/health`，接口调试 `/docs`、契约 `/openapi.json`。调试普通会话和上传可使用 `/docs`；执行问答可能触发付费 API，须遵守 [AGENTS.md](../AGENTS.md) 的授权边界。

- Vite 默认直连 `http://127.0.0.1:8000`，不是代理。更换地址可从 [frontend/.env.example](../frontend/.env.example) 创建本地 `.env` 后设置 `VITE_API_BASE_URL`；修改后重启 Vite。所有 `VITE_*` 都可能进入浏览器构建，不能存秘密。
- 后端 `CORS_ORIGINS` 是逗号分隔的来源列表，默认允许 localhost/127.0.0.1 的 5173。它只控制浏览器跨域，不提供认证。
- 同源构建：在 `frontend` 执行 `npm run build`，然后启动/重启后端访问 `/`。生产默认 API 基址为空；构建时若保留本地 `VITE_API_BASE_URL` 会把该地址写进产物，需先核对。
- 调试 Graph 看 `agent/graph_agent.py` 和 `app/services/agent_service.py`；请求日志可按 request_id 关联。浏览器 Network 中检查 `/ask/stream` 的 progress/result，不要把它当作模型逐 Token 流。
- 修改后端环境变量需重启；改进日志时只记录排障所需元数据，不输出完整提示词、PDF 或密钥。

## 可选入口与 Docker

Streamlit 原型：安装 `requirements.txt` 后运行 `python -m streamlit run main.py`。当前 `.devcontainer` 自动启动的也是这个原型，且关闭其 CORS/XSRF 保护；不是推荐的公开 Web 部署配置，迁移任务见 [T13](../plans/TASKS.md#t13)。

仅当任务授权本地容器运行时，在确认 `.env` 与宿主机端口后执行：

```text
docker compose up --build -d
docker compose ps
docker compose logs --tail 100 pdf-agent
```

默认映射 8000，数据在命名卷 `pdf-agent-data`；不要用 `down -v` 排障，否则会删除持久数据。端口冲突优先改本地宿主机映射；容器内部改 `PORT` 时需处理硬编码健康检查。上述命令不推送镜像、不部署 Render。远程发布需另行授权与当时状态验证。

## PostgreSQL 迁移开发环境（T15a）

目前 API 仍使用 SQLite；新增的 `app/db` 只是惰性配置/Engine 工厂，尚未接入 lifespan 或业务存储。Alembic 已列为依赖，revision 和建表命令将在 T15b 实现，当前不要执行 upgrade 或数据导入。

独立 [compose.postgres.yaml](../compose.postgres.yaml) 只启动 PostgreSQL，避免主 Compose 在迁移中途要求新密码或改变现有应用启动行为。镜像固定 PG17 digest，本次实测为 17.12；后续更新镜像须重跑数据库测试。它使用自己的项目 `pdf-agent-postgres-dev` 和 `postgres-data` 卷，不挂载现有 `/data`，默认只开放 `127.0.0.1:55432`。

在已启动 Docker Desktop 的独立 PowerShell 终端，首次创建测试库：

```powershell
# 首次生成；若该卷已存在，使用之前保存的同一密码，不要重新生成。
$env:POSTGRES_PASSWORD = (python -c "import secrets; print(secrets.token_urlsafe(32))")
docker compose -f compose.postgres.yaml config --quiet
docker compose -f compose.postgres.yaml up -d --wait --wait-timeout 90
$env:TEST_DATABASE_URL = 'postgresql+psycopg://pdf_agent:' + [Uri]::EscapeDataString($env:POSTGRES_PASSWORD) + '@127.0.0.1:55432/pdf_agent_test'
```

密码可保存到已有、被忽略的 `.env`（只添加缺少项，不覆盖原文件）；也可使用受限环境变量或仓库外秘密文件。不要输出完整 Compose config、数据库 URL 或密码。`POSTGRES_PORT` 可修改宿主端口，同时修改 TEST_DATABASE_URL；更换环境变量不会重设既有卷中的数据库密码。此文件创建的是专用 `pdf_agent_test`，不为应用自动创建开发/生产业务库。

集成测试命令见 [TESTING.md](TESTING.md#postgresql-连接集成测试t15a)。用后执行 `docker compose -f compose.postgres.yaml stop`，不带 `down -v`；保留本地卷便于复验。当前应用仍使用原 `compose.yaml`，不要合并两个文件来尝试提前切换数据库。

连接配置由 `load_database_settings()` 显式读取环境，模块导入不读取 `.env` 或连接数据库。`DATABASE_URL` 缺失/错误会报配置异常，无 SQLite fallback；现有 SQLite 服务尚未调用这个入口。允许 postgres/postgresql/postgresql+psycopg 前缀，密码须 URL 编码；TLS 支持 sslmode/sslrootcert/sslcert/sslkey，另支持 application_name，拒绝通过 URL query 覆盖 host、timeout、options 或 service。配置对象 repr 隐藏整个 URL；调用方仍不得主动打印原始 URL 或驱动异常正文。

`DB_POOL_SIZE=5`、`DB_MAX_OVERFLOW=0`、`DB_POOL_TIMEOUT_SECONDS=5`、`DB_CONNECT_TIMEOUT_SECONDS=5` 是初始默认值，不是容量结论。前三项控制每进程 QueuePool，超时均为正数，overflow 可为零；connect timeout 为整数，libpq 对过小值可能采用自身最小等待时间。连接使用 UTC，开启 pre_ping、关闭 echo 并隐藏 SQL 参数。所有者显式创建/关闭 Engine，每个工作线程在短 `engine.begin()` 内取得和归还 Connection；不跨模型调用/SSE 持连接，断连中的事务不会自动重放。应用生命周期接入留给 T15c。

## 常见问题

| 现象 | 排查入口 |
| --- | --- |
| 缺 Key、模型调用失败 | 核对后端进程环境与模型名，不展示 Key；不要用重复付费请求代替配置排查 |
| 首次上传很慢或 Embedding 下载失败 | 检查 Hugging Face 缓存及网络；`HF_HUB_OFFLINE=1` 要求权重已缓存，不能自动创造离线缓存 |
| 前端连不上后端 | 核对健康接口、VITE API 地址、后端 CORS、端口；请求失败不一定是会话失效 |
| 后端 `/` 只返回 JSON | 未构建 `frontend/dist` 时的既有行为；使用 Vite 或构建前端 |
| 会话过期或重启后找不到数据 | 核对数据目录、卷挂载和 TTL；读取会话会刷新 TTL，删除/清理会移除索引 |
| 费用 unavailable 或缓存率不显示 | 核对 usage 完整性、模型映射、币种及节假日年份；不把未知当零费用，详见架构可观测性章节 |
| PDF 文件名重复或文档内容没更新 | 当前按文件名去重，不是按内容版本替换；先在隔离新会话验证，不直接清理生产索引 |

## 日常开发流程

确认任务范围与现有 diff → 阅读相关实现/测试 → 最小修改 → 按 [TESTING.md](TESTING.md) 验证 → 检查敏感文件与兼容性 → 报告结果。无需为每个小修建立新流程或强制新工作树。工程改造任务仅在获授权后进入实施，状态更新 [TASKS.md](../plans/TASKS.md)；涉及事实变化时同步对应专题，README 能力描述按任务授权处理。
