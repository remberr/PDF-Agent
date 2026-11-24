# 本地 PostgreSQL + pgvector 迁移记录

本文件记录已完成本地验收的 PostgreSQL/pgvector 迁移及恢复步骤。Render 和生产切换不在本轮范围。

## 当前应用入口

API 的 `app/services/session_store.py` 转接 PostgreSQL，上传用 BGE-M3 编码后在同一事务写文档、Chunk 和页数。`utils/pgvector_store.py` 按 session/profile 过滤后精确 cosine top-k，保留 source/page。存储迁移保留Graph及API/SSE原字段；T06增量终态另见[执行契约](EXECUTION.md)。

SQLAlchemy 同步连接池由 `app/db/runtime.py` 管理，Alembic 显式执行，启动只检查 schema。不得通过 `create_all` 或 stamp 跳过迁移。模型编码不持有数据库连接。消息保存按批次追加，不覆盖其他请求的消息。

本地容器由 `compose.vector.yaml` 管理，PG17 + pgvector 固定 digest，端口仅绑定 `127.0.0.1:55433`。`pdf_agent_test` 供测试使用，`pdf_agent_local` 保留历史导入，测试不得改用后者。原 `app/data`、旧 Compose 卷均保留。

## 运行

本轮生成的随机密码只在 Git 忽略的 `.evaluation-local/vector-local.env`。不复制到源码或报告。

```powershell
docker compose --env-file .evaluation-local/vector-local.env -f compose.vector.yaml up -d --wait
powershell -File scripts/run_local_postgres.ps1
```

运行脚本只设置当前子进程的本地 DATABASE_URL、离线模型和 `SESSION_RETENTION_ENABLED=false`；不会修改用户 `.env`。问答仍需要自行配置有效 DeepSeek Key，以上存储验证没有付费模型调用。首次部署到一个新库时需先设置对应 DATABASE_URL 并运行：

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
```

## 历史数据及恢复

`migration_tools/snapshot.py` 使用 SQLite backup API 和索引哈希生成新快照。冻结旧写入后操作；不覆盖已有目标。`import_legacy.py` 只接受显式可信本地快照，限制 pickle 类，校验映射/元数据并重新生成 BGE 向量，全快照事务提交。相同快照重跑先完整对账，变化或冲突拒绝覆盖。

本次旧库有 7 个会话、51 个 Chunk，缺少时间列。用户已批准采用快照创建时间补齐缺失列；现有时间不重置。TTL 清理保持关闭，恢复 TTL 须再次确认。旧单文档页数未知时为 NULL，不用 Chunk 页码猜总页数。

未设置保留开关时也默认关闭清理；只有显式 `SESSION_RETENTION_ENABLED=true` 才启用 TTL。测试在独立测试库显式启用以验证边界，启动本地应用不会继承测试进程的开关。

```powershell
.venv/Scripts/python.exe -m migration_tools.import_legacy preflight <snapshot> --trusted-local-snapshot --missing-timestamp <approved-epoch>
.venv/Scripts/python.exe -m migration_tools.import_legacy import <snapshot> --trusted-local-snapshot --missing-timestamp <approved-epoch>
.venv/Scripts/python.exe -m migration_tools.import_legacy verify <snapshot> --trusted-local-snapshot --missing-timestamp <approved-epoch>
.venv/Scripts/python.exe -m migration_tools.export_legacy <new-recovery-directory>
```

恢复导出包含 PG 当前消息与向量；不会复活已删除会话。恢复向量是 BGE 1024 维单位向量，不能用旧 MiniLM 镜像检索。仅离线迁移/恢复及 FAISS 对照环境安装 `python -m pip install -r requirements.migration.txt`，不向运行镜像安装 FAISS。运行真实 PG 回滚测试还需设置 `PDF_AGENT_RUN_LEGACY_RECOVERY_TESTS=1`。

测试开关、当前证据和未完成验收见 [TASKS](../plans/TASKS.md)。Docker Hub 连接问题不能视为构建成功；纯检索结果不代表付费生成/Judge 质量已验证。

## 验证命令

先显式设置 `TEST_DATABASE_URL` 为独立 loopback `pdf_agent_test` 库，不能指向历史库：

```powershell
$env:PDF_AGENT_RUN_POSTGRES_TESTS='1'
$env:PDF_AGENT_RUN_PAID_TESTS='0'
$env:PDF_AGENT_RUN_CACHE_API_TESTS='0'
$env:PDF_AGENT_RUN_LOCAL_PDF_TESTS='0'
.venv/Scripts/python.exe -B -m unittest discover -s tests -v
```

以下评估使用显式 `DATABASE_URL`；真实检索在测试库创建独立 scope，并在退出时清理自己创建的 scope。数据库操作不要使用历史库作为测试夹具。

```powershell
.venv/Scripts/python.exe -m evaluation.runner --mode routing --output .evaluation-local/routing.json
.venv/Scripts/python.exe -m evaluation.runner --mode real-pdf --pdf-dir C:/path/to/pdfs --retrieval-only --output .evaluation-local/pgvector-real-pdf.json
.venv/Scripts/python.exe -m evaluation.compare_vector_backends --output .evaluation-local/vector-parity.json
```

后端对照命令只读当前 DATABASE_URL 中已有向量，需要迁移工具用的 FAISS；它使用同向量数值探针，不把结果描述为语义评价。报告可能含 PDF 摘录，必须保留在忽略目录中。

运行与开发依赖固定为同一 pypdf 版本，避免页内文本提取差异导致证据引文校验和分块结果漂移。升级解析器时应重新运行三份 PDF 的证据引文和检索回归。

如果 Docker Desktop 的离线检索评估线程过多，可仅对评估进程设置 `OMP_NUM_THREADS=2` 和 `MKL_NUM_THREADS=2`，并在比较耗时时注明线程数。

应用镜像构建成功后，可配置内部 `DOCKER_DATABASE_URL`（`db:5432/pdf_agent_local`，密码需 URL 编码），运行 `docker compose --env-file .evaluation-local/vector-local.env -f compose.vector.yaml --profile app up --build`。迁移服务先于 API 执行。使用旧的默认 `compose.yaml` 时，必须显式提供指向已迁移 PostgreSQL 的 `DATABASE_URL`；该文件不再支持仅使用旧本地 SQLite 卷启动。独立验收使用另一个 Compose 项目和 `pdf_agent_test`，不使用历史卷。

历史 7 会话/51 Chunk 导入、重复对账、数据库重启后逐向量对账通过；原库和索引保留。3PDF/30问题的页召回均值由旧 MiniLM 基线 51.8% 变为 BGE 60.7%，但 4 题下降，需要后续质量复核。容器验收和剩余限制见 [TASKS](../plans/TASKS.md)。


## 在途与SQL边界（T05a）

当前 Schema 为 `0004_session_credentials`。从 `0003_request_leases` 执行 `alembic upgrade head` 新增一对一所有者凭据表及级联外键，保留会话、聊天、PDF、向量和租约。应用启动前须显式迁移。历史会话没有凭据行，公网不可仅凭 ID 访问，可信离线存储入口仍可用于既定流程。当前轮迁移仅在隔离测试库验证。回退前先停用会话入口，再评估从已验证备份恢复，旧构建无法提供凭据保护。

工作流的已持久化会话快照在派发前获取租约，期限由T03剩余请求时间决定，获取锁等待会扣除剩余租期；结束/取消后短事务释放并刷新活动时间，失败清理记录日志，由租约到期兜底。TTL删除/过期读取排除有效租约，主动删除仍级联且不会被旧快照复活。默认SESSION_RETENTION_ENABLED=false保持不变；关闭时只清理过期操作租约，不清理会话。没有跨LLM/SSE持有数据库事务或连接。PDF上传仍由原短事务处理，未给解析/Embedding添加后台心跳或无限租期；若其超出TTL且清理已开启，提交可安全失败，不复活过期会话。

DB_LOCK_TIMEOUT_MS默认3000，DB_STATEMENT_TIMEOUT_MS默认10000，均为正整数；所有连接含pre_ping有服务器侧默认边界。工作流语句额外用SET LOCAL裁剪到T03剩余时间，事务结束清除，避免池中泄漏设置。取消/截止后拒绝新业务SQL；租约释放可绕过已耗尽的请求预算，但仍受默认SQL边界约束，不重试业务写入。池等待和建连分别由既有5秒默认值限制，不被动态语句截止替代，故不承诺硬实时HTTP取消。多工作进程应保持主机时钟同步；单调活动时间不会倒退，但墙钟调整可能影响TTL/租约的实际到期时刻。

回退旧二进制前必须排空在途请求并审核数据库版本。旧二进制检查0002版本，不能直接带新Schema启动；downgrade会删除操作租约表，需另行明确批准后才能执行。本轮没有执行downgrade或删除历史数据。


T09b补充：get_session内部messages仅返回受限最近窗口，message_count仍为数据库总条数；批次保存只追加窗口后新增消息，不把窗口当成完整归档覆盖。所有原始历史仍在session_messages，导出/恢复保留完整记录。容量与失效语义见[MEMORY.md](MEMORY.md)。
