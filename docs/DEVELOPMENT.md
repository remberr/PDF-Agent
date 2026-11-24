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

<a id="input-limits"></a>
## 输入与资源限制（T01，2026-11-24）

保护阈值由 [`.env.example`](../.env.example) 的 `PDF_AGENT_MAX_*` 配置，均须为正整数，API 重启后生效。默认：问题去首尾空白后最多 8000 字符；每批最多 5 个 PDF、累计 40 MiB，每文件最多 20 MiB、200 页、100 万提取字符和 2000 Chunk；文件名最多 255 字符。上传/索引每进程最多 1 个请求，普通问答和 SSE 共用每进程 2 个请求额度。超额立即返回 429（含 `Retry-After`），不在应用层排队。容器须显式传入这些环境变量，例如使用本地 Compose override 的 `environment`；仅编辑宿主 `.env` 不保证未声明的变量被 Compose 转发。

请求体在 JSON 缓冲或 multipart 暂存前计量：上传为累计字节限额加 64 KiB multipart 余量；问答为字符限额 × 12 加 4096 字节 JSON 余量，兼容非 BMP 字符的 JSON 代理对转义。即使省略或伪报 Content-Length，实际接收字节仍受限。读取请求体默认连续空闲最多 15 秒、累计最多 120 秒，超时返回 408 并释放准入额度；这不是解析/生成总超时。问题校验失败返回 422，字节/文件数/页/文本/Chunk 超限返回 413；空白文本 PDF、损坏/加密/空文件返回安全的 400。

所有文件的名称及字节数先预检，失败不写入文档或向量（会话读取仍可能刷新活动时间）。之后仍逐文件解析、编码和原子提交；第二份 PDF 解析失败时，第一份成功文件保留，可读取会话确认后重传。重复文件名仍跳过。这些限制不改变响应字段或 SSE 事件。

阈值是可调整的保护默认值，多进程或副本的额度相加。尚无会话累计存储配额或身份级速率限制。解析器单页解压和原生编码仍缺少硬内存/CPU 沙箱。取消会等待当前运行线程结束，并在阶段边界停止后续工作。已开始的数据库提交沿用原子事务语义。问答终态与断线处理见[执行契约](EXECUTION.md)。可信本地评估绕过 HTTP 上传限额，只使用受控数据。

<a id="llm-budgets"></a>
## LLM 预算、重试与离线门禁（T03，2026-11-24）

配置入口为 [`.env.example`](../.env.example) 的 `LLM_*` 项，按请求加载。默认每请求最多12次SDK尝试（包括应用重试）、12万预留/已结算输入Token、2.4万输出Token；单调用输出最多4096。默认USD费用预估额度0.50，使用已有定价模块按调用开始时间、Cache Hit/Miss较高的输入单价预留，USD/CNY展示仍独立计算。未知模型/价格或日历时，启用的费用额度会在派发前拒绝调用；仅将费用额度设为空字符串可显式关闭该项，其他上限仍有效。无效配置不会静默禁用保护。

Planner、Memory摘要、所有Specialist、Collaboration、最多一次补充步骤及Reviewer共用绑定到UsageTracker的线程安全预算。调用前按UTF-8字节启发式和输出上限预留，并行竞争也不能绕过预留；输入估算不是供应商Tokenizer。返回后根据有效Token/价格结算，缺缓存分项时可结算已知Token而费用仍未知；缺准确用量的部分继续保留预留。原usage/by_model/by_operation仅累计实际SDK尝试返回的用量，不加入预留数、不重复记费。日志和评估报告的budget字段是控制数据，不能当作实际账单；供应商计数超出预留时保留真实计数并停止后续调用，不裁剪成“通过”。

请求LLM截止默认180秒，单次SDK超时最多60秒并裁剪到剩余时间。截止覆盖新调用、重试、Memory锁等待及节点推进；SDK超时是传输I/O超时，不是整个进程/Graph的硬墙钟保证。原生检索、SDK在途I/O和数据库保存可能超过截止，无法安全强杀线程或撤销已经发送的供应商请求；迟到响应仍记录用量，但不作为正常成功继续。它不是账户级账单或跨请求配额。

SDK自动重试固定为0。应用默认也不重试，可配置0–2次，仅连接/超时、HTTP408/409/429/5xx可重试；认证/参数错误、畸形回答不重试。每次重试重新竞争共享额度，等待计入截止，指数退避并受最大等待限制；过长的数字Retry-After不重试。失败且无用量仍为未知费用，不能当作免费。HTTP断连和生成器关闭会取消同一预算，阻止后续新调用/重试；在途请求不保证立即终止，断线后的完整保存/恢复仍属T06/T07。

`llm_budget_reserved/settled/exhausted/cancelled/finished`、`llm_call_failed` 与重试事件只记录受控诊断和用量。预算耗尽进入安全的失败或降级结果，由 JSON 和 SSE 共同使用的 `execution` 字段说明生成与保存状态。事件和状态定义见[执行契约](EXECUTION.md)。

`PDF_AGENT_DISABLE_LLM_API=1`在真实客户端工厂阻止网络访问（即使已有客户端/Key），CI固定开启。仅`0`或`false`允许客户端访问，空值或无效值同样关闭。标准unittest包入口默认也开启，只有显式的付费测试opt-in才不强制该值；不在CI清除此保护。CLI的routing完全不用模型，歧义用例记失败；live/real-pdf生成及Judge统一要求`--allow-paid-api`，免费Source也在禁止LLM的上下文执行。缓存探针保留64输出Token/次、2–5次、零重试的原限制，同时使用统一预算与用量网关。运行命令见[测试文档](TESTING.md)，代码中的付费开关不是替代任务授权。

<a id="model-output-validation"></a>
## 模型控制输出校验（T09a，2026-11-24）

运行时Schema位于[agent/output_schemas.py](../agent/output_schemas.py)，复用现有Pydantic；合法步骤名来自[agent/state.py](../agent/state.py)的SpecialistStep。没有新增依赖或改变API、SSE字段及Graph拓扑。

| 调用路径 | 模型响应契约 | 本轮边界 |
| --- | --- | --- |
| Planner模型分支 | JSON步骤名数组 | qa/source/summary/keyword/compare；原始数组1–5项，禁止任务对象、执行参数及未知值；规则快路径不调用模型/解码器 |
| Collaboration | 七字段JSON对象 | answer、issues、missing_information、recommendations、needs_revision、next_steps全部必填；额外字段拒绝，不默认伪造模型判断 |
| QA/Summary/Keyword/Compare、Reviewer、Memory | 自然语言 | 保留原字符串契约，不强制JSON；各Agent外层字典由代码构造，非模型控制JSON；Source无LLM |
| Evaluation Judge | 独立评分JSON | 保留其现有整数评分/列表检查，不在T09a重构 |

控制JSON在解析前限制原始响应字符数：Planner 2048、Collaboration 32768。协作answer去首尾空白后为1–16000字符；三类诊断列表各至多20条，每条去首尾空白后为1–2048字符。needs_revision必须是真正布尔值，next_steps必须是最多五项的合法步骤数组；请求修订须有新步骤，不修订则数组必须为空，任何已执行步骤或混入非法步骤都使整份响应失败。全局最多一次补充仍由既有Graph控制器限制。

安全本地修复仅包括首尾空白、开头单个BOM、完整且独占响应的json/无标签代码围栏、字符串首尾空白及步骤稳定去重。原始数组超限不会先去重来绕过限制；大小写/近形字不映射成合法Agent。重复对象键、NaN/Infinity常量、非法JSON/类型/枚举、缺字段、额外参数、空答案、异常长度或修订矛盾直接拒绝，不从说明文字中抽取子JSON，不修复尾逗号/单引号，不截短或部分保留非法计划。

失败回退沿用既有契约：Planner返回QA规则回退并明确记录来源，不声称其是校验成功的模型计划；Collaboration使用原专业结果、status=failed、needs_revision=false、next_steps=[]，不把原始非法文本注入答案。没有新增LLM修复调用；原调用和已有网络重试仍由T03预算统计，预算拒绝/取消不会触发付费修复。

model_output_repaired记录固定修复代码；model_output_validation_failed记录节点、固定原因和Pydantic错误代码，planner_fallback/collaboration_fallback记录确定性回退。日志不包含响应、问题、文档、原始ValidationError、错误位置键或输入值，避免恶意字段名也泄露内容。

这些 Schema 用于类型和执行控制。事实、引用支持度、自然语言质量及提示注入鲁棒性仍需独立评估。严格七字段和长度上限尚未做付费模型遵循率验证。节点失败、降级、断流和保存失败按[执行契约](EXECUTION.md)汇总与展示。上下文容量、摘要缓存及并发行为见 [Memory](MEMORY.md)。

## 运行和调试

终端一（已激活 Python 环境）：

```text
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --env-file .env
```

显式 `--env-file` 在导入应用前加载设置。请在仓库根目录启动，并使用已显式升级到当前 revision 的本地 PostgreSQL/pgvector。调试迁移使用独立测试数据库。

终端二（使用浏览器信任、含本地访问主机名或 IP 的开发证书）：

```powershell
cd frontend
npm ci
$env:PDF_AGENT_DEV_TLS_CERT_PEM = Get-Content -Raw -LiteralPath 'C:/local-certs/localhost.pem'
$env:PDF_AGENT_DEV_TLS_KEY_PEM = Get-Content -Raw -LiteralPath 'C:/local-certs/localhost-key.pem'
npm run dev
```

访问证书覆盖的 `https://127.0.0.1:5173` 或 `https://localhost:5173`。Vite 把 `/health` 和 `/sessions` 转发给回环后端。可通过 `PDF_AGENT_DEV_BACKEND` 更换代理上游。开发私钥置于仓库外。直接用 FastAPI 提供构建站点时，可在回环监听并提供 Uvicorn 的 `--ssl-certfile` 和 `--ssl-keyfile`。应用的 Cookie 安全属性在开发与生产一致。

- `SESSION_BROWSER_ORIGINS` 是浏览器会话允许的精确 HTTPS Origin 列表，默认为回环的 5173 和 8000。部署时配置实际公开 HTTPS 来源，保持前端和 API 同源，HTTPS 可由可信入口终止。`CORS_ORIGINS` 单独控制跨域响应，前端使用同源 Cookie 调用。
- 浏览器会话请求发送 `X-PDF-Agent-Client: browser`。创建和写操作要求允许的 Origin。脚本通过 `POST /sessions` 和 `X-Session-Mode: bearer` 创建，不带 Origin。安全保存响应中的 `session_token`，对会话 API 发送 `Authorization: Bearer <token>`。创建响应同时提供 `expires_at`，凭据绝对有效期 24 小时。
- 健康、OpenAPI 和文档可访问后端 `/health`、`/openapi.json` 和 `/docs`。历史记录及到期凭据不能仅凭 ID 恢复。数据库 TTL 仍由原保留配置控制。执行问答可能触发付费 API，须遵守 [AGENTS.md](../AGENTS.md) 的授权边界。
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

默认映射 8000；不要用 `down -v` 排障，否则会删除命名卷。端口冲突优先改本地宿主机映射；容器健康检查读取 `PORT`。默认 Compose 仍用外接数据库，由部署环境显式升级 Schema。

<a id="render-embedded-postgres"></a>
### Render 单服务与同容器 PostgreSQL

现有 `pdf-agent` Web 服务使用 1 CPU、2 GiB 与 1 GB `/data` 盘。镜像在 Render（`RENDER=true`）默认启用内置 PostgreSQL，也可用 `PDF_AGENT_DATABASE_MODE=embedded` 显式启用。由启动器在 `/data/pdf-agent-postgres/pg17` 创建并维护新库，旧目录保持原样。本次生产切换使用空数据库，旧会话、SQLite、FAISS、PDF 和向量不导入。用户需创建新会话并重新上传。Render 的同源浏览器 Origin 默认取 `RENDER_EXTERNAL_URL`，额外自定义域名使用 `SESSION_BROWSER_ORIGINS` 配置完整 HTTPS Origin。

启动时必须检测到 `/data` 挂载且至少余 192 MiB，运行中低于 96 MiB 安全余量时停止进程，释放写入压力并保留数据。上线前盘点盘内占用，持续监测实际增长；阈值是安全余量，WAL 和库文件无固定写入上限。数据库只监听 `127.0.0.1:5432`，运维通过私有 Unix socket 的系统用户身份认证。应用和 Alembic 使用不同的数据库角色与启动时生成的 SCRAM 密码；迁移结束停用迁移角色登录。环境无需额外存储数据库连接串。

启动器等待 PostgreSQL 就绪，准备 pgvector，再通过 `alembic upgrade head` 确认 Schema 后启动 Web 应用。迁移或子进程失败会关闭容器；接收停止信号时先停止 HTTP 应用，再干净关闭 PostgreSQL。单 Web worker、最多 3 个活跃池连接、PostgreSQL `shared_buffers=32MB`、`work_mem=1MB`、`max_connections=12`。单线程 BGE-M3、编码批次 1、同时最多一个问答及一个上传；模型内的编码锁继续串行处理。该部署默认值同时限制问题 2,000 字符、单批最多 2 份 PDF、单文件 10 MiB、单批 20 MiB、每份 PDF 40 页、48,000 字符和 48 个 Chunk。本地外接数据库模式沿用现有输入默认值。

切换以正常推送并通过 CI 的提交为准，保持 Auto Deploy、Blueprint Auto Sync 关闭，手动部署同一服务。不改盘挂载、大小或套餐。带盘部署会短暂中断。旧部署制品与旧数据目录保留；若首发失败，先确认平台当前 live 版本，再按需回退到预先核实的旧制品。新库若已有写入，先保全新库原生备份，再决定切换；旧构建不读取新目录。保留数据的回滚不执行降级、不覆盖或恢复整个 `/data` 快照。

原生备份由服务 Shell 中的 `postgres` 系统用户完成。将 `pg_dump -Fc` 产物存入临时受限文件，再通过安全 SSH/SCP 转移至既有受限位置，并记录恢复测试、校验值与保护周期。不要把备份、凭据或业务正文放入 Git 或日志。

```bash
# Render Shell，使用 root 运行。随后安全转出打印的临时文件。
archive=$(mktemp /tmp/pdf-agent-XXXXXX.dump)
runuser -u postgres -- pg_dump -h /run/pdf-agent-postgres -Fc pdf_agent > "$archive"
runuser -u postgres -- pg_dump --version
sha256sum "$archive"
printf '%s\n' "$archive"
```

只向隔离 PostgreSQL 17 实例的专用空库执行 `pg_restore --exit-on-error --single-transaction`，确保 pgvector 可用，核对 Alembic、会话、消息、文档、凭据和向量后再评估恢复切换。需保留对象所有权时预建同名角色。对新库保留原生备份；Render 磁盘快照不作为自管 PostgreSQL 的恢复方式。没有可核实备份或盘容量时，暂停实际数据操作。相关平台约束见 [Render 持久盘](https://render.com/docs/disks) 与 [部署与回退](https://render.com/docs/deploys)。

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

`DB_POOL_SIZE=5`、`DB_MAX_OVERFLOW=0`、`DB_POOL_TIMEOUT_SECONDS=5`、`DB_CONNECT_TIMEOUT_SECONDS=5` 是初始默认值。前三项控制每进程 QueuePool，overflow 可为零。connect timeout 是整数，libpq 对过小值可能采用自身最小等待时间。连接使用 UTC，开启 pre_ping、关闭 echo 并隐藏 SQL 参数。应用在生命周期内核验 Schema 并释放 Engine。存储操作使用短连接或短事务，模型调用和 SSE 全程无需持有数据库连接。断连的事务由调用方处理，且应用不会自动重放。

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


<a id="memory-limits"></a>
## Memory 容量（T09b）

Memory使用原LLM网关/UsageTracker；不新建客户端或模型修复路径。实现与会话/版本缓存、锁外摘要、历史窗口及保留边界见[MEMORY.md](MEMORY.md)。.env.example包含以下可选配置；值无效时明确失败且不回显原始配置内容。

| 环境变量 | 默认值 | 合法范围 |
| --- | --- | --- |
| MEMORY_HISTORY_MAX_MESSAGES | 100 | 整数1–1000 |
| MEMORY_HISTORY_MAX_BYTES | 24000 | 整数1–1000000，UTF-8字节 |
| MEMORY_RECENT_MAX_BYTES | 8000 | 整数1–100000，不大于history字节限额 |
| MEMORY_SUMMARY_MAX_BYTES | 4000 | 整数1–16000 |
| MEMORY_SESSION_MAX_BYTES | 4000 | 整数1–16000 |
| MEMORY_CACHE_MAX_ENTRIES | 128 | 整数1–1024；同时约束在途摘要数 |
| MEMORY_CACHE_TTL_SECONDS | 900 | 有限正数，不大于86400 |

默认history字节额度划出recent部分后，余下16000字节用于较早历史摘要输入。上述限额不改变数据库历史保留或会话TTL，不代表语义质量保证；T03独立控制调用/Token/费用和截止。缓存按进程持有，不需要新基础设施。
