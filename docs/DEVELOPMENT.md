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

阈值是可调整的保护默认值，不是压测容量结论。多进程/副本额度相加；尚无会话累计存储配额或身份级速率限制。解析器单页解压、原生编码并没有硬内存/CPU沙箱；取消时等待运行线程结束，在阶段边界停止后续工作，不能回滚已开始的数据库提交。LLM预算见下一节；长时间解析、完整SSE断线恢复和持久化终态仍需T06等补强。可信本地评估不经过HTTP上传限额，禁止对不可信PDF无界运行。

<a id="llm-budgets"></a>
## LLM 预算、重试与离线门禁（T03，2026-11-24）

配置入口为 [`.env.example`](../.env.example) 的 `LLM_*` 项，按请求加载。默认每请求最多12次SDK尝试（包括应用重试）、12万预留/已结算输入Token、2.4万输出Token；单调用输出最多4096。默认USD费用预估额度0.50，使用已有定价模块按调用开始时间、Cache Hit/Miss较高的输入单价预留，USD/CNY展示仍独立计算。未知模型/价格或日历时，启用的费用额度会在派发前拒绝调用；仅将费用额度设为空字符串可显式关闭该项，其他上限仍有效。无效配置不会静默禁用保护。

Planner、Memory摘要、所有Specialist、Collaboration、最多一次补充步骤及Reviewer共用绑定到UsageTracker的线程安全预算。调用前按UTF-8字节启发式和输出上限预留，并行竞争也不能绕过预留；输入估算不是供应商Tokenizer。返回后根据有效Token/价格结算，缺缓存分项时可结算已知Token而费用仍未知；缺准确用量的部分继续保留预留。原usage/by_model/by_operation仅累计实际SDK尝试返回的用量，不加入预留数、不重复记费。日志和评估报告的budget字段是控制数据，不能当作实际账单；供应商计数超出预留时保留真实计数并停止后续调用，不裁剪成“通过”。

请求LLM截止默认180秒，单次SDK超时最多60秒并裁剪到剩余时间。截止覆盖新调用、重试、Memory锁等待及节点推进；SDK超时是传输I/O超时，不是整个进程/Graph的硬墙钟保证。原生检索、SDK在途I/O和数据库保存可能超过截止，无法安全强杀线程或撤销已经发送的供应商请求；迟到响应仍记录用量，但不作为正常成功继续。它不是账户级账单或跨请求配额。

SDK自动重试固定为0。应用默认也不重试，可配置0–2次，仅连接/超时、HTTP408/409/429/5xx可重试；认证/参数错误、畸形回答不重试。每次重试重新竞争共享额度，等待计入截止，指数退避并受最大等待限制；过长的数字Retry-After不重试。失败且无用量仍为未知费用，不能当作免费。HTTP断连和生成器关闭会取消同一预算，阻止后续新调用/重试；在途请求不保证立即终止，断线后的完整保存/恢复仍属T06/T07。

`llm_budget_reserved/settled/exhausted/cancelled/finished`、`llm_call_failed`与重试事件只记录额度、计数、固定原因、操作和错误类型，不记录Prompt、PDF正文、Key或原始供应商异常。API响应字段与SSE的progress/result类型保持不变，预算耗尽复用既有失败进度和安全结果。更细的失败/降级展示仍由T06处理。

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

这些Schema校验类型和执行控制，不证明事实正确、引用受支持或完全防提示注入；自然语言空文本/质量与Memory容量仍由其他任务处理。严格七字段和长度上限尚未做付费模型遵循率验证。节点failed/fallback如何汇总为全局终态、断流恢复及保存失败仍是T06/T07；T09a不新增这些协议，也不自动开始T06。

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
