# PostgreSQL 迁移方案（已批准分项本地实施）

后续目标变更（2026-11-16）：用户决定最终以pgvector替代FAISS。本文保留原审计和T15关系库方案；“保留FAISS”“文件代次发布”等未来设计不再作为最终目标，以[pgvector衔接方案](PGVECTOR_MIGRATION.md)及TASKS最新依赖为准。当前仅T15a完成，关系业务迁移未完成；不重复T15a，也不凭新规划将旧任务标为完成。

方案基线：2026-11-16 19:12（Asia/Shanghai），`4d4e55b` 加本地 T02a 修复。下文的“当前实现”和“拟新增”保留当时审计/目标设计；用户随后批准分项本地实施，T15a 已落实连接基础设施和开发数据库，其余目标未因此完成。当前架构以 [ARCHITECTURE.md](ARCHITECTURE.md) 为准，唯一执行状态和验证记录维护在 [T15](../plans/TASKS.md#t15)。不授予生产连接、迁移或部署权限。

## 1. 当前实现与证据

### 代码、SQL 和调用边界

| 位置（当前行号 / 函数） | 实际行为及迁移影响 |
| --- | --- |
| `app/services/session_store.py:15–30`，`_connect` | 根目录来自 PDF_AGENT_DATA_DIR，SQLite 文件为 sessions.db；每次建立 sqlite3 连接，timeout/busy_timeout 为 5 秒 |
| 同文件 `:43–97`，`init_session_store` | WAL；CREATE TABLE IF NOT EXISTS；PRAGMA table_info；缺少 created_at/updated_at 时 ALTER TABLE；COALESCE 回填；创建 updated_at 索引 |
| 同文件 `:121–165`，`create_session` | uuid4().hex；INSERT 七字段；预先记录索引路径，即使索引目录尚不存在 |
| 同文件 `:168–232`，`get_session` | SELECT 单行；过期 DELETE，否则 UPDATE updated_at；提交后加载 FAISS、解析两列 JSON；GET 也是写操作 |
| 同文件 `:235–267`，`save_session` | 单次 UPDATE 全量覆盖文件名、消息、索引路径、页数和 updated_at；无版本校验，未检查未匹配行 |
| 同文件 `:270–348`，删除相关函数 | SQL DELETE 后删除磁盘目录；删除按 session_id 推导路径，有格式/根目录校验，失败留给后续清理 |
| 同文件 `:351–408`，`cleanup_expired_sessions` | SELECT 过期 ID、按 cutoff DELETE、SELECT 全部存活 ID，再扫描磁盘孤儿目录；DB 快照与扫描间可发生竞争 |
| `app/main.py:44–73` | lifespan 初始化并立即清理；周期清理用 asyncio.to_thread；关闭时取消任务 |
| `app/api/routes.py:38–153` | 会话 CRUD、上传、JSON/SSE 问答都依赖 session_store；上传为 async，其他业务路由为同步函数 |
| `app/services/pdf_service.py:29–101` | 同名跳过；原 PDF 临时保存后删除；FAISS 保存先于 save_session；多文件逐个处理 |
| `app/services/agent_service.py:158–203,339` | 内存先追加 user，完成后追加 assistant 并 save_session；消息含 sources、steps、collaboration_notes、timings、usage 等，不能仅迁移 role/content |
| `utils/vectorstore.py:55–72` | 保存 index.faiss/index.pkl；加载允许 pickle 反序列化，必须保留可信磁盘边界 |
| `tests/test_session_lifecycle.py:1–123` | 直接使用 sqlite3、临时 DB_PATH、旧 schema、PRAGMA 和 mock 时间；需要改为 PG 集成回归，旧 schema 样本保留给导入测试 |

上述 session_store 是业务 SQLite SQL 的唯一集中实现；`?` 占位符用于所有参数，sqlite3.Row 用于行映射。COALESCE、普通 INSERT/UPDATE/DELETE 等并非 SQLite 独有，不能靠全局字符串替换迁移；应改为参数化 SQLAlchemy Core 表达式。PRAGMA、sqlite3.Row、文件 DB_PATH、sqlite3 的连接上下文均需替换。

当前 `with sqlite3.Connection` 管理提交/回滚但不负责 close；测试已有 GC 清理连接的注释。没有跨线程共享数据库连接的显式设计，也没有跨请求事务、会话锁或冲突控制。Specialist 线程主要做检索/生成，不应让它们持有数据库 Connection。

关联文件：compose.yaml、render.yaml 只有 API 与 `/data` 持久卷；无 DATABASE_URL、PostgreSQL 服务、SQLAlchemy/Alembic 显式依赖或迁移目录。requirements 两份需同时检查；CI 当前无 PG 服务。README 双语仍描述 SQLite。`.gitignore`/`.dockerignore` 排除 app/data，但新的备份目录必须单独确认排除。`main.py` 是 Streamlit 内存原型，不读 SQLite；evaluation 使用独立向量库并复用部分服务工具，不应因此强制连接数据库。

### 当前表结构

只有 `sessions` 一表，无聊天/文档子表，无外键。源码声明如下，实际生产历史 schema 和数据尚未读取：

| 字段 | SQLite 声明 | 语义 |
| --- | --- | --- |
| session_id | TEXT PRIMARY KEY | 通常是 32 位小写十六进制 ID；源码未额外声明 NOT NULL |
| loaded_pdfs | TEXT NOT NULL | JSON 字符串数组，按上传顺序，业务按文件名去重 |
| messages | TEXT NOT NULL | JSON 消息对象数组；可带历史扩展字段 |
| vectorstore_path | TEXT，可空 | 相对或绝对本地路径；创建空会话也可能非空 |
| document_count | INTEGER NOT NULL DEFAULT 0 | PDF 页级 Document 总数，不是 PDF 文件数或 chunk 数 |
| created_at / updated_at | INTEGER NOT NULL | Unix 秒；旧库经 ALTER 添加时列可能允许 NULL，再由初始化回填 |

除主键外只有 `idx_sessions_updated_at(updated_at)`。没有 JSON 有效性、非负计数或消息角色约束。未知字段、无效 JSON、非法 ID、异常路径不能在导入时静默忽略。

### TTL 与索引关系

默认 TTL 86400 秒、清理间隔 3600 秒；`updated_at <= now - TTL` 即过期，get/save 刷新时间。启动就会删过期行，导入期间若沿用自动清理，可能马上删除刚迁入的旧会话或把尚未导入的索引判成孤儿。

FAISS 目录默认 `app/data/vectorstores/{session_id}`，Docker/Render 在 `/data/vectorstores/`。读取信任 DB 中路径，删除却按 ID 推导；两者不一致是迁移检查项。原 PDF 不长期保存，丢失 index.pkl 中的文本不能假定可从原 PDF 重建。

## 2. 推荐技术选择

采用 **PostgreSQL 17 + 同步 SQLAlchemy 2.x Core + psycopg 3 + Alembic**。Compose、CI、Render 使用同一 PG 主版本；实现时锁定经测试的依赖版本及镜像补丁/digest，不宣称当前已验证版本组合。Render 文档列有 PG 17 支持；选定主版本后不能在 Blueprint 中直接改版本完成升级。[Render 版本与配置](https://render.com/docs/blueprint-spec)

驱动显式使用 `postgresql+psycopg` dialect，避免依赖默认驱动选择；具体 SQLAlchemy 2.x 小版本在实施前与 Python 3.11、Alembic、LangChain 依赖一起解析验证。[SQLAlchemy psycopg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg)

| 方案 | 判断 |
| --- | --- |
| psycopg 原生 SQL + 自写 migration runner | 依赖少，但需自己维护池、版本与迁移机制；不作为本次首选 |
| SQLAlchemy Core + Alembic | 推荐。贴合现有函数/字典服务，统一连接、参数化 SQL、事务和 schema 版本，无需 ORM 对象图 |
| 完整 ORM / async ORM / asyncpg 全面改造 | 当前收益不足；会扩大到同步 Graph、线程池和 SSE 生命周期，暂不采用 |

一个进程一个 Engine，Connection 只在单次短操作内使用 `engine.begin()`，成功提交、失败回滚、退出归还池；不跨线程或 SSE yield 共享 Connection，更不在 LLM/Embedding 等待期间占用事务。异步入口调用数据库操作时在线程工作单元内取得并释放连接。Engine 在应用停止时 dispose。[SQLAlchemy 连接与事务](https://docs.sqlalchemy.org/en/20/core/connections.html)

Alembic 管理 schema，应用启动仅检查连接与目标 revision，不在 CRUD 中建表，也不自动运行 schema 迁移。不以 `create_all()` 或 `stamp head` 替代执行迁移；autogenerate 产物必须人工复核。SQLite 数据搬运是独立工具，不塞入 Alembic revision。[Alembic 生成迁移](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)

不引入 pgvector、Redis、任务队列、双写或 CDC；SQLite 仅保留在迁移/回滚工具中，目标运行时没有“PG 失败就退回 SQLite”的隐式分支。FAISS 仍要求单实例、共享同一可信磁盘；PG 本身不使应用获得多副本能力。

## 3. 目标 schema 草案

采用三张业务表，加 Alembic 自己的版本表。以关系键和顺序拆分对象，保留异构消息 payload，避免这次同时重构 Agent 数据模型。

| 表 | 字段、约束与索引 |
| --- | --- |
| sessions | `session_id VARCHAR(32)` 主键、非空、十六进制格式 CHECK；`document_count INTEGER NOT NULL DEFAULT 0 CHECK >=0`；`created_at/updated_at TIMESTAMPTZ NOT NULL`；`index_key TEXT NULL`（受控相对目录，不保存主机绝对路径）；`index_version BIGINT NOT NULL DEFAULT 0 CHECK >=0`；updated_at B-tree 索引 |
| session_messages | `session_id` 外键 → sessions，ON DELETE CASCADE；`ordinal BIGINT CHECK >=0`；复合主键 `(session_id, ordinal)`；`payload JSONB NOT NULL`，CHECK 为 object；`batch_id UUID NOT NULL`、`batch_ordinal INTEGER NOT NULL CHECK >=0`，UNIQUE `(session_id,batch_id,batch_ordinal)`，用于一次内部保存的幂等，不作为公开 API 字段 |
| session_documents | `session_id` 外键 → sessions，ON DELETE CASCADE；`ordinal INTEGER CHECK >=0`；主键 `(session_id,ordinal)`；`filename TEXT NOT NULL`，UNIQUE `(session_id,filename)`；`page_count/chunk_count INTEGER NULL CHECK >=0`、`size_bytes BIGINT NULL CHECK >=0`、`sha256 TEXT NULL`、`uploaded_at TIMESTAMPTZ NULL` |

消息 payload 原样保留所有逻辑字段、空值与数组顺序，不重复拆出 role/content 或给历史消息编造创建时间。ordinal 定义历史顺序；batch_id 对同一次保存重试保持稳定，重新提交的用户请求属于新 batch。若相同 batch 的内容不同，报冲突而非覆盖。首次导入按源快照身份和 session_id 生成确定性的内部 batch 标识。

旧 loaded_pdfs 只提供文件名；单文档页数、字节数、哈希、上传时间未知时为 NULL，保留 session.document_count 原值，不按可见 chunk 猜页数。新上传才填真实元数据。文件名不改变大小写、不做 Unicode 归一化、不截断，继续作为引用 source；重名异常先报告，不擅自去重。

JSONB 不保持 JSON 字符串的空白/对象键排序，且对 Unicode、数值限制更严格。导入要检测 NUL、非法代理字符、NaN/Infinity、超范围数值、重复对象键及字段类型问题；有问题则阻止切换并保留原库，不用替换字符或删字段“修复”。精确原始文本由只读备份保留，目标验证按完整解析内容、数组顺序和数值语义比较。[PostgreSQL JSON 类型约束](https://www.postgresql.org/docs/current/datatype-json.html)

时间戳以 UTC 秒精度转换为 TIMESTAMPTZ，连接时区设为 UTC；服务统一使用可注入的 UTC 秒级时钟，一次操作捕获一次 now，保留原过期比较边界。内部兼容字典按旧约定输出 Unix 秒，公开 ID 仍是原 32 位字符串。旧库缺失时间字段时，导入工具不调用旧 init：须由审核后的统一迁移基准时间补齐并列入报告；现有时间不重置为导入时刻。

## 4. 服务契约、事务与 FAISS 一致性

保留 `create_session/get_session/save_session/delete_session/cleanup_expired_sessions` 的服务入口及会话字典形状；`loaded_pdfs` 从文档表按 ordinal 重建，`messages` 从消息表按 ordinal 重建，`vectorstore_path` 由受控根目录与 index_key 解析。Graph/Memory 使用字典的方式不变。允许内部保存函数细化为“追加消息批次”和“提交文档/index 元数据”，仅调整 PDF 服务与 `_save_result` 的持久化调用，不改推理、Prompt、检索或公开响应 schema。

- **聊天**：短事务先锁 session 行，分配新 ordinal，追加本次 user/assistant 消息批次并刷新 updated_at；保留旧历史，不用陈旧快照覆盖全部 messages 或文档元数据。不存在/已删除的父行不能被 save 隐式重建。进程崩溃前尚未保存的在途回答不宣称可恢复，切换必须排空活跃请求。
- **上传**：在事务外解析和构建完整新索引代次；文件完整保存并校验后，在短事务校验 index_version，提交文档元数据、页数、索引指针及版本。并发版本冲突不能覆盖另一个上传，也不能重复调用模型；受控失败及回归属于 T05。
- **索引**：新代次放在同磁盘的受控临时目录，再发布为不可变目录 `<session_id>/generations/<generation_id>`。DB 仅在完整文件可读后引用新代次。旧布局 `<session_id>` 作为初始 index_key 保留，不重新 Embedding，也不改文档 source/page。提交失败留下的目录按规则清理，不能误删仍被引用的旧代次。
- **锁与生命周期**：单实例下仅在索引加载/发布/删除边界使用文件访问协调；不跨 SSE yield 持有线程所有者锁，不在 LLM 调用期间持 DB 行锁。跨进程/多副本写 FAISS 不在本次支持范围内。数据库 READ COMMITTED 配合父行锁和版本比较，不泛化为全局 SERIALIZABLE。
- **过期/删除**：在同一短事务重新核对过期条件，用 DELETE RETURNING 获得真正删除的 ID，提交后再删对应文件；失败安全重试。孤儿扫描在删除前重新检查 DB，跳过构建中的目录；DB 断开/查询失败时禁止把空集合视为“全部孤儿”。
- **保留开关**：拟增 `SESSION_RETENTION_ENABLED`，同时控制启动/周期清理和 get_session 的过期删除。迁移及验收期间为 false，全部原有行先导入；恢复 TTL 删除须作为切换确认项。仅停周期任务不够。

这些是 [T05](../plans/TASKS.md#t05) 的一致性工作，不重复创建另一份实现；**PG 事务不覆盖文件系统，不能承诺两者天然原子**。旧代次保留/GC 的安全条件和磁盘余量必须在故障测试后确定，未验证时不自动删除旧代次。

## 5. 配置、连接池与初始化

拟新增 `app/db/config.py`、`engine.py`、`schema.py`，仅承担配置/连接和 Core metadata；持久化逻辑继续集中在 session_store，避免再叠多层通用 repository 框架。

| 配置 | 建议及边界 |
| --- | --- |
| DATABASE_URL | 必填，应用只接受 PostgreSQL；支持 Render 的 postgres:// / postgresql://，结构化解析后规范为 postgresql+psycopg，不打印密码或整条 URL；缺失/错误时明确失败，不退回 SQLite |
| DB_POOL_SIZE / DB_MAX_OVERFLOW | 初始建议 5 / 0，可配置；不是容量验证结果。总连接预算按进程数×池上限，加迁移/管理连接计算 |
| DB_POOL_TIMEOUT_SECONDS / DB_CONNECT_TIMEOUT_SECONDS | 初始建议各 5 秒；正数校验；连接耗尽明确失败，不无限等候 |
| SQLAlchemy 选项 | pool_pre_ping=True，echo=False，hide_parameters=True；pre_ping 不补救已中断事务，更不能自动重放付费工作流 |
| PDF_AGENT_DATA_DIR | 仍管理 FAISS 和本地迁移工件，不再是关系数据库位置 |
| SESSION_TTL_SECONDS / SESSION_CLEANUP_INTERVAL_SECONDS | 保留现有意义和默认值；与保留开关一起测试时间边界 |
| 维护模式 | 拟增 PDF_AGENT_MAINTENANCE_MODE：可在保留挂载磁盘的进程内停止业务请求和清理，供受控备份/切换；不得自动触发导入 |

应用池用默认 QueuePool，Alembic/一次性工具采用独立短连接或 NullPool；暂不增加 PgBouncer。TLS 参数从部署配置进入驱动，不在日志中暴露连接参数。[SQLAlchemy 连接池与断连边界](https://docs.sqlalchemy.org/en/20/core/pooling.html)

开发/CI 显式执行 `python -m alembic upgrade head`（**拟新增后的命令，当前不可用**）；启动校验数据库 revision 后才允许业务。迁移文件单向增加，不修改已发布 revision；数据库降级脚本不等于业务数据回滚。运行用户尽量仅 DML/所需权限，DDL 使用受控迁移凭据；具体 Render 角色授权在实施时验证，不假设已有独立角色。

## 6. 备份、导入、验证与回滚

### 维护窗口的全量切换

1. **盘点但不修改源**：未来工具对明确指定的 SQLite 快照只读打开，核对 schema、全部会话/消息/文档条目、数据大小与 index manifest。盘点不能调用会触发 DDL/TTL 的现有 get/init。当前未盘点真实数据，行数、大小、停机时长未知。
2. **冻结**：批准维护窗口，停止新请求，排空上传/问答和 SSE，停用所有过期/孤儿清理；仅禁止 POST 不够，因为 GET 会更新时间。保留能访问 `/data` 的维护进程，并确认没有其他写入者。
3. **成套备份**：用 SQLite backup API 得到一致数据库快照，配合同一冻结窗口复制全部 FAISS 目录；生成 session→目录→文件哈希清单。不可只复制运行中的 sessions.db 而忽略 WAL。将备份放在独立、受限且排除于 Git/Docker 的位置，验证可读后才迁移。[Python SQLite backup](https://docs.python.org/3.11/library/sqlite3.html#sqlite3.Connection.backup)
4. **准备目标**：全新隔离目标库运行 Alembic，确认 revision；恢复/映射索引根，关闭保留清理；目标不可接收用户业务写入。DATABASE_URL 不放命令行参数或报告，使用受限进程环境。
5. **预检查与导入**：先 dry-run 全量检查；默认要求目标业务表为空。正常数据在一个明确事务中写三表，全部成功才提交。若实际体量不适合单事务，先调整经审核的分批方案，不边迁移边临时改策略。重跑时识别相同快照并完整对账后 no-op；不相同的现有数据必须报冲突，禁止覆盖、截断或静默 ON CONFLICT DO NOTHING。
6. **路径验证**：只从可信源根和合法 ID 映射相对 index_key；不使用来源 DB 的任意绝对路径去读取外部文件。空会话可无索引；已有文档却缺 index.faiss/index.pkl、越界/符号链接路径或哈希不符均阻止切换。只验证可信本地索引，不能反序列化陌生 pickle。
7. **逐项验证**：总数及逐 session 的 ID、document_count、原有时间、文件名顺序、完整消息 payload/顺序、引用和 usage 数值、全部索引哈希对应；FK/唯一性/无孤儿引用检查。报告只记录计数、摘要和异常定位，不输出聊天正文、文件内容或凭据。先用只读工具对账，再做会刷新 TTL 的 API 冒烟。
8. **隔离演练和切换**：测试新进程恢复、非付费 Source、JSON/SSE（mock 模型）、上传/删除的测试会话。用户确认验收及回滚准备后才切换入口；确认原有过期数据的保留安排后单独恢复 TTL，保留备份至约定期限，不由导入工具删除源。

### 回滚分界

- **尚未放开新写入**：可回到冻结时的 SQLite+FAISS 成套快照和确切旧应用制品；先验证路径与清理策略，不先销毁 PostgreSQL。
- **已经产生 PG 新写入**：禁止仅换回旧 Docker 镜像/旧 SQLite。再次冻结并备份 PG+当前索引，使用拟建的反向导出工具重建七字段 SQLite，按 ordinal 重组两列 JSON，保留新增会话/消息和当前文档元数据语义；将活动代次物化到旧布局 `<session_id>/index.faiss,index.pkl` 的独立恢复目录，再逐项对账。旧应用不支持的新扩展元数据保留在受限 PG 备份/迁移清单中，不伪装成旧字段。
- 反向导出、旧版读取和恢复后 TTL 行为必须在隔离环境演练；旧版本没有关闭清理开关，启动前须批准不会提前清理迁入数据的兼容配置或维护版本。验证不通过就保持维护并修复 PG，不能承诺一键无损回滚。
- Alembic downgrade 可能删表，不能代替以上过程。PG 的 pg_dump/备份不含 FAISS，磁盘快照也不含 PG；持续备份由 T12 承接。

## 7. Docker Compose 与 Render 规划

### Compose

- 新增 PostgreSQL 17 `db` 服务及独立 `postgres-data` 卷，保留原 `pdf-agent-data:/data`；默认不向所有宿主机地址暴露数据库端口，需要宿主调试时仅绑定 127.0.0.1。
- 密码从本地忽略的环境文件/秘密注入，无源码默认密码；应用容器使用服务名 db，宿主测试使用 localhost；特殊字符通过 URL 编码或结构化配置处理。
- db 有 pg_isready 检查；单独的一次性 migrate 服务执行 Alembic，应用依赖 DB healthy 和 migrate 成功。迁移服务不运行 SQLite 导入，也不删除数据卷；不在每个请求/worker 启动时争抢 DDL。[Compose 就绪与一次性依赖](https://docs.docker.com/compose/how-tos/startup-order/)
- 当前 Compose 文件和 `/data` 命名卷属于升级资产，不改卷名导致“看似空库”；清理命令不得默认带 `down -v`。新增备份目录的 ignore 规则与镜像上下文同步检查。

### Render

- 拟增加同工作区、同 Singapore 区域的 Managed Postgres，主版本显式为 17。数据库计划、存储大小、连接上限与费用待真实数据盘点后确认；本轮不创建资源、不预选会自动消费的套餐。
- `render.yaml` 拟用 `fromDatabase: {name: ..., property: connectionString}` 注入 DATABASE_URL，不写密码。优先内网连接，同时检查项目环境隔离；外部管理连接受限来源并要求 TLS。按平台支持配置 sslmode，不能为修复连接问题全局关闭 TLS。[Render 连接](https://render.com/docs/postgresql-creating-connecting)、[私网边界](https://render.com/docs/private-network)、[Blueprint 引用](https://render.com/docs/blueprint-spec)
- 保留现有 `/data` 磁盘、单实例及手动部署策略；数据库迁出磁盘不代表 FAISS 可移除磁盘或水平扩展。带磁盘服务也不具备平台的零停机部署保证。[Render 持久磁盘](https://render.com/docs/disks)
- preDeployCommand 可以仅执行 DB schema 的 Alembic upgrade；**pre-deploy 和 one-off job 无法挂载当前服务磁盘**。SQLite 盘点/备份/索引导入必须在明确批准的、能访问原挂载盘的维护环境中执行，不能放到 pre-deploy 或把私有库打进镜像。[Render 部署步骤](https://render.com/docs/deploys)、[磁盘限制](https://render.com/docs/disks)
- Schema 先行必须向前兼容；旧进程可能仍在处理请求，DDL 不等于数据切换。上线审批需包含冻结、在途 SSE 排空、导入对账、运行制品、故障回滚；备份保留和恢复目标另行确认。

## 8. 测试与回归计划

| 层次 | 拟验证内容 | 执行边界 |
| --- | --- | --- |
| 无数据库单元 | 配置校验/URL 脱敏、字典和消息映射、严格 JSON 校验、时间转换、路径边界 | 无网络、无真实 LLM；导入应用/运行 evaluation 不建立连接 |
| PG 集成 | Alembic 空库升级/重复 upgrade；CRUD、FK/排序、消息追加幂等、事务回滚、连接归还/耗尽/断连、TTL 精确边界 | 专用可丢弃 PG17 + TEST_DATABASE_URL，绝不回退到生产 DATABASE_URL |
| SQLite 导入/反向导出 | 当前及旧五字段 schema、全消息字段/空值/Unicode/数值、缺失时间、非法 JSON/ID、重名/异常目录、重跑与冲突、写入中失败全回滚 | 自建合成库及索引；原库只读；逐行对账与反向恢复证明 |
| FAISS 一致性 | 两个上传竞争、问答与上传/删除/TTL 竞争、文件各写阶段/SQL 提交故障、孤儿扫描 DB 失败、进程重启 | 临时磁盘+测试 Embedding；真实缓存模型加载另做本地 opt-in，无付费 |
| API/Agent/前端 | 会话创建/读取/删除、同名上传、多 PDF、完整历史供 Memory、引用文件名/页码、JSON/SSE progress/result 字段与失败用量 | 真实数据库+mock LLM，沿用既有 API 契约；不改 Graph 核心 |
| CI/构建 | 新增独立 PG 集成 job/service container，显式开启测试；保留默认单元、routing、前端 test/build、Docker build | 集成 job 缺 DB 就失败，不以 skip 通过；普通开发默认不启动 DB/付费测试 |

`PDF_AGENT_RUN_POSTGRES_TESTS=1` 及独立 TEST_DATABASE_URL 开关已在 T15a 的连接测试实现，现有命令见 [TESTING.md](TESTING.md#postgresql-连接集成测试t15a)；不代表上表其余测试已实现。测试只能清理其显式创建的隔离数据库/schema/索引目录，不能任意 DROP 用户数据库。连接池和真实 PostgreSQL 行为不能用 SQLite 替代验证。

现有 `test_session_lifecycle.py` 的 SQLite 生命周期断言迁为 PG 集成；旧 SQLite 建表样本转入迁移工具测试。Graph、缓存、费用、Judge、错误隐私等无数据库测试继续默认运行。发布门槛包括完整既有回归、PG/导入/回滚/故障测试、前端构建、容器本地冒烟，不以“服务启动成功”代替迁移验收。

## 9. 拟修改文件与不变范围

| 拟修改/新增 | 原因 |
| --- | --- |
| `app/db/{config,engine,schema}.py`、`__init__.py`（新增） | 连接池、配置、三表 Core metadata；避免业务模块导入时连接 DB |
| `alembic.ini`、`migrations/env.py`、`migrations/versions/*`（新增） | 显式 schema revision 与受控升级，配置文件不含密码 |
| `app/services/session_store.py` | PG 持久化、事务、兼容字典、TTL；替换 PRAGMA 与每次 CRUD 的 DDL |
| `app/services/pdf_service.py`、`agent_service.py`、必要的 `app/api/routes.py` 内部调用 | 分离文档/index 提交与消息批次追加；不改变路径、请求/响应字段、SSE 事件 |
| `app/main.py`、`utils/vectorstore.py` | Engine 生命周期、保留/维护开关、版本校验；T05 可信索引代次和文件协调 |
| `scripts/migrate_sqlite.py`、`scripts/export_legacy_sqlite.py`（拟新增） | 只读预检查、备份/导入、对账与反向恢复；脚本实际命令在实现后写入开发文档 |
| `requirements.api.txt`、`requirements.txt`、`.env.example` | 显式依赖与配置示例、验证版本，无密码默认值 |
| `compose.yaml`、`render.yaml`、必要的 `Dockerfile`、ignore 文件 | PG 服务、独立 schema 步骤、驱动构建及备份排除；不自动执行部署 |
| 生命周期/迁移/PG/并发/API 测试，`.github/workflows/ci.yml` | 分离离线与真实数据库测试并建立必需 CI 门槛 |
| docs 开发/测试/架构、双语 README、AGENTS 技术栈 | 实现并验证后才更新实际能力；本轮不把 SQLite 描述提前改成已迁移 |

不修改 `agent/` 的 Planner/Reviewer/Graph 决策、RAG 检索/Embedding/引用策略、Memory 摘要逻辑、前端交互、公开 schema 与 SSE 协议。遇到必须改变这些契约的设计阻碍应单独提交审核，不能夹带在迁移中。

## 10. 批准边界与剩余限制

用户已批准依照本方案和 TASKS 的依赖分项本地实施，每轮一个任务后停止。若 Core+psycopg+Alembic、三表结构与完整 JSONB 消息、单实例 FAISS/T05 协同、维护窗口全量迁移及双阶段回滚出现重大设计偏差，先解释并审核。生产数据库创建、套餐、窗口、迁移和部署仍需具体批准。

尚待核实：实际库大小/旧 schema/非法数据、索引数量和备份余量、可接受停机时间、Render 目标资源与连接限额、TLS/角色权限、完整回滚耗时。T15a 仅验证新建隔离 PostgreSQL 的连接基础设施，没有读取真实会话库、运行 Alembic revision 或数据迁移。迁移能否达到无丢失要求，必须由未来全量对账和恢复演练证明。
