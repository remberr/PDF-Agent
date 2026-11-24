# PostgreSQL + pgvector 迁移方案

日期：2026-11-16（Asia/Shanghai）。本轮为架构分析和任务规划，未修改业务代码、安装 pgvector、运行迁移或部署。用户已确认就是当前工作区；“关系库迁移完成”实际对应上一轮 T15a 完成，不能作为全量迁移已完成的证据。状态统一见 [TASKS](../plans/TASKS.md#t16)，现状仍见 [ARCHITECTURE](ARCHITECTURE.md)。以下表结构、命令职责和性能门槛是待审核设计，不是现有能力。

## 1. 实际基线与前置差异

工作区 HEAD 为 `4d4e55b`，保留已有未提交改动；本轮不切分支、不拉取、不覆盖它们。

| 证据 | 结论 |
| --- | --- |
| `app/services/session_store.py:6,17,28,43` | 仍是 sqlite3、sessions.db 和生命周期 DDL；尚无 PG 业务持久化 |
| `app/main.py:59–60` | lifespan 仍调用旧 init_session_store |
| `app/db/config.py`、`engine.py:1–17` | T15a 已提供 SQLAlchemy/psycopg 配置和惰性 Engine，未接入业务；复用，不另建连接框架 |
| `app/db/` 仅三个文件；未找到 alembic.ini、migrations 或 schema.py | Alembic 仅安装依赖，revision 尚未实现；复用 T15b 待办，不将其重复建成新任务 |
| `utils/vectorstore.py:8,15–19,44–72`；`Dockerfile:42` | 实际模型是 multilingual MiniLM；FAISS 建库/保存/危险 pickle 加载；没有显式 normalize_embeddings |
| `pdf_service.py:46–72,99–101` | 解析临时 PDF，切块后写 FAISS 再保存会话，finally 删除原 PDF；不能假设全部原 PDF 可恢复 |
| 五个 `tools/*_tool.py` 的 similarity_search 调用 | QA/Source k=3，Keyword k=10，Summary/Compare k=30；后三类按文件最多保留三块 |
| `evaluation/real_pdf.py:105–120`；`main.py:197` | 真实 PDF 评估及 Streamlit 原型也依赖向量工厂，完全移除 FAISS 时必须一并适配 |
| `render.yaml:5,9,24–27` | 声明 1c-2g Web、/health、1GB /data 磁盘，没有 Managed PG 声明或 DATABASE_URL；不是已核实的线上资源状态 |

本轮仅在默认本地 `app/data/vectorstores` 盘点：2 份 IndexFlatL2（50、1 条向量），均384维，均有配对 index.pkl，索引二进制合计78,426字节。未执行 pickle 反序列化，未打开真实会话数据库，因此 Docstore 完整性、会话关联和线上数量仍待预检。之前提供的三份测试 PDF 在原路径存在，不代表这些索引对应的所有原 PDF 都存在。

合成输入、离线缓存模型探针（没有模型下载或付费 API）：

| 加载对象 | 文档/查询维度 | L2 范数 | 说明 |
| --- | --- | --- | --- |
| 当前生产工厂 MiniLM | 384 | 两个文档4.934115、3.374458；查询5.014658 | 非单位向量，encode_kwargs={} |
| 单独加载缓存 BAAI/bge-m3（CPU） | 1024 | 两文档及查询均1.0 | 模块为 Transformer、Pooling、Normalize；不是当前应用配置 |

BGE-M3 官方 dense 输出1024维，SentenceTransformers 模块含 Normalize，与缓存探针一致。[官方模型卡](https://huggingface.co/BAAI/bge-m3)、[模块配置](https://huggingface.co/BAAI/bge-m3/raw/main/modules.json)。实施时仍须锁定实际 revision、库版本、pooling、dtype、最大长度和编码参数，不能只按模型名称推断旧索引来源。当前384维向量不能填充/截断成1024维，也不能冒充 BGE-M3 数据。

**衔接原则：** 不重做 T15a；沿用 T15b/c/d 的关系库任务。用户目标是 BGE-M3 + pgvector，但对当前代码而言还包含模型接线变化，应在 T16a 固定契约、在评估中单独量化。旧方案中尚未实施的 FAISS 文件代次发布不再作为必经中间架构；T05 改为 PG 元数据/Chunk 同事务和竞争控制。不把这些待办标成已完成。

## 2. 推荐技术与接口

继续用同步 SQLAlchemy Core、psycopg 3、同一进程 Engine 和 Alembic；新增轻量 `pgvector` Python 类型适配依赖。不另引入拥有独立连接池/表体系的 LangChain PGVector 存储，也不添加 ORM、Redis、向量微服务、稀疏检索或 reranker。用 `pgvector.sqlalchemy.VECTOR` 和已有连接工厂；若使用驱动类型注册，在同一 Engine 的连接事件中注册。首次建扩展的迁移连接不能先依赖 vector 类型已经存在。[pgvector Python 官方集成](https://github.com/pgvector/pgvector-python#sqlalchemy)

实现 `SessionVectorStore`，构造时绑定可信 session_id 和经过验证的 Embedding profile，公开 `similarity_search(query, k=4) -> list[Document]`。查询正文先本地 Embedding，再获取短连接执行查询，完成即归还；Graph/Memory 持有轻量适配器，不持有连接。空会话保持 `vectorstore is None` 和 has_vectorstore=false，存在可检索 Chunk 才创建适配器，不能让旧 API 的空库检查失效。

所有 SELECT/INSERT/DELETE 都在存储边界强制绑定 session_id；调用者的 metadata/filter 不能覆盖它，缺失 scope 直接报错。一次查询必须先限制当前会话及模型 profile，再排序和 LIMIT；禁止全库 top-k 后 Python 过滤。返回 Document 保留 content、source 文件名、零基 page 和其余完整 metadata；引用继续转换为一基物理页，不改现有 k、固定主题查询或每文件三块逻辑。

上传由同一事务写文档行、Chunk 和会话计数/时间，不用先调用 adapter.add_documents 再独立 save_session。仅调整服务内部保存边界，不改上传响应、Graph 节点或 SSE progress/result。Streamlit 原型分配独立 PG 会话并沿用同一 adapter，重置只清理自己的会话；评估为每个文档集合建立独立测试 scope，保持 case.pdf_files 隔离。StaticVectorStore 受控测试保留。

## 3. Schema 与隔离

以下是增量表草案。关系表和 Alembic revision 当前尚未存在，先由 T15b 定义；若后续提供已完成版本，则按真实 PK/FK 适配而非重建关系表。

| document_chunks 字段 | 约束 / 用途 |
| --- | --- |
| session_id | 与 sessions.session_id 同类型，非空 |
| document_id | 使用已有文档的稳定主键；若 T15b 沿用 `(session_id, ordinal)`，此列使用该 ordinal 的类型，不另建重复 documents 表 |
| chunk_id UUID | 主键；迁移使用来源身份、session/document/ordinal/content hash 派生稳定 UUID；不能只按文本全局去重 |
| chunk_ordinal INTEGER | 非负，UNIQUE(session_id, document_id, chunk_ordinal)，重复段落也保留各自位置 |
| content TEXT | 原 Chunk 正文，非空；不得用参考答案替代 |
| metadata JSONB | 非空 object，完整保留 source/page 等；严检非法 Unicode/非有限数/重复 JSON 键，失败报告而非静默清洗 |
| embedding VECTOR(1024) | 非空、有限值、非零；写入检查维度及归一化契约 |
| embedding_profile_id TEXT | model revision、dimension、pooling、归一化、dtype/编码策略的固定指纹；写入/查询均校验，不混检不同模型 |
| content_sha256 / import_source_id | 内容完整性及迁移快照归属，支持重跑对账；新上传的 import_source_id 可空 |

建立 `(session_id, document_id)` 复合 FK 指向同一会话的文档键，ON DELETE CASCADE；父文档对 sessions 同样 cascade。若现有文档只有全局 UUID，则增加与 session 的唯一键以供复合 FK，不能仅有两个各自独立的 FK。B-tree 至少覆盖 session/profile 的检索过滤和 document 的删除。新增字段不改既有会话 ID、消息、TTL 时间或 document_count（当前为页数）。

这是服务层查询范围与数据库关联完整性的保证，不等同用户认证；现有匿名 API 的访问控制仍归 T04。首版不靠连接级 session 变量传递 scope，以避免池复用串用；不默认为表所有者添加一个会被绕过的 RLS 并宣称安全。若后续要求数据库独立租户防护，再用非 BYPASSRLS 角色及事务级策略专项验证，不阻塞当前明确的会话检索隔离测试。

Alembic 增量 revision：先验证扩展可用/权限，再 `CREATE EXTENSION IF NOT EXISTS vector`，随后建表/FK/普通索引。应用启动检查 revision、扩展和模型 profile，禁止每次请求 DDL。扩展版本必须记录并与本地/CI 对齐，不随安装命令静默升级；downgrade 不自动 DROP EXTENSION CASCADE 或删除生产 Chunk。当前 stock postgres:17 开发镜像没有据此证明已含扩展，需使用经验证并固定 digest 的 pgvector PG17 镜像/构建，原开发卷保持不动。

## 4. 精确检索优先，HNSW 按测量启用

首版选择按 session/profile 过滤后精确余弦检索（embedding <=> query，升序，确定性 chunk_ordinal/chunk_id 作为等距 tie-breaker）。基于当前51条本地向量，建立近似索引没有证据支持；线上规模未知，不把它当全部用户容量。归一化 BGE 的 cosine、inner product 与 L2 排名可等价比较，当前非归一化 MiniLM 则不能直接换成 cosine 仍宣称排名一致。

精确检索不需 ANN 调参、结果完整，耗时随会话候选量增长。HNSW 增加建索引/内存/写入成本且有召回损失；共享索引的 session 过滤可能返回少于 k。只有基准显示精确检索达不到确认后的延迟目标时，才单独迁移 `vector_cosine_ops` HNSW，并测试 ef_search、支持版本的 iterative_scan、过滤选择率与召回；不足 k 时安全使用同会话精确补查，不取消 session 条件。[pgvector 过滤与索引说明](https://github.com/pgvector/pgvector#filtering)

不默认每会话建独立表/索引或分区，不先引入 halfvec/量化；1024维 float32 是首版基线。未来 HNSW 需独立非事务并发建索引步骤/失败清理方案，不能把 CONCURRENTLY 塞进普通事务 revision。

## 5. 写入、删除与 TTL 一致性

解析、切块、Embedding 全部在 DB 事务外进行。一个 PDF 的最终提交使用短事务：锁定/重新检查会话存在及未过期 → 检查唯一文件名 → 创建文档与批量 Chunk → 更新页数/时间 → commit。异常全部 rollback；内存 loaded_pdfs 只在 commit 后更新。多文件请求保留当前逐文件成功语义，不改为整请求原子性。

并发同名上传可在写入前各自做过 Embedding，但唯一键/父行锁必须避免重复行和页数累加；不为重试再次调用 LLM。写入后断线、提交结果未知时凭稳定批次/内容摘要对账，不盲目全量重插。上传遇已删除会话必须失败，禁止 upsert 复活父行。

会话删除与 TTL DELETE 在同一关系数据库内级联删除文档和 Chunk；保留原 `updated_at <= now - TTL` 和读取续期行为。检查聊天保存与清理的锁/更新时间规则，批量清理有界、失败回滚，不扫描本地目录作为新向量清理依据。文档删除应提供内部事务能力和测试；当前没有单文档 DELETE API，本轮不新增公开端点。TTL/删除也必须使缓存的轻量 adapter 后续查询返回无数据；不缓存跨删除的 Document 结果。

迁移期间关闭所有旧索引删除/孤儿扫描及 TTL，冻结业务 GET/写入并排空 SSE/上传。新系统恢复 TTL 时只删除活动 PG 数据；归档旧索引保持只读，受独立保留安排保护，不能被原定时清理顺手删除。

## 6. 数据搬迁与回滚

### 导入路径

1. 用 T15d 已有/待实现的成套快照和关系数据校验，先核实会话、文档 ID、源目录、消息完整性与目标 revision。当前关系库尚未迁移，因此先复用 T15d，不新增另一套 SQLite importer，也不连接生产执行。
2. 导出工具仅对显式可信本地备份加载 FAISS/Docstore，校验真实路径在批准根内、无越界链接、index/pkl 的配对哈希。pickle 可执行代码，文件存在不代表可安全加载；不在 Web 服务接收或反序列化用户提供的索引包。
3. 逐行检查 index.ntotal、index_to_docstore_id 映射和 Docstore 一致，索引每行恰好对应一个 Document；每个 source 必须关联同会话的唯一文档。页码/字段缺失、孤儿映射、无法说明的多余条目均阻止验收，不丢弃后继续。
4. **同 profile 的 BGE 索引**：若1024维、模型 provenance/归一化/距离策略可证实且能无损 reconstruct，则复用 float32 向量。压缩索引的近似重构不能称为无损迁移；同维度不证明同模型。
5. **当前384维索引或 profile 不明**：若可信 Docstore 正文/metadata 完整，可用冻结 Chunk 重新编码 BGE-M3，不需要原 PDF、不重新切块。记录为模型迁移并单独评估。若 Docstore 缺失，则需原 PDF、版本/hash、相同 parser/splitter 配置才能重建；缺 PDF/证据不全就阻塞对应会话，禁止生成替代正文。三份评估 PDF 不足以证明全部用户历史可恢复。
6. 脚本分 dry-run/export/import/verify；导出制品含源文件 hash、模型指纹、逐 Chunk 内容/metadata/向量摘要和完整数据，私有制品排除于 Git、镜像和日志。用户可审核的报告只含聚合数量、摘要、异常类别，不输出正文/凭据。
7. 目标默认按每会话完整事务提交，整个迁移期间保持业务冻结、目标不对外开放；每会话重跑先逐条对账，相同快照完全相同则 no-op，冲突/未知已有行必须拒绝，不能 ON CONFLICT DO NOTHING 掩盖差异。大到不适合单事务时，先审核 staging + 原子发布方案，不临时改成可见半批提交。
8. 完成所有 scope 后检查 ID/文档/Chunk数量、顺序、完整metadata、模型/维度/范数、无孤儿、非向量关系数据及索引对应；同模型搬迁核对向量数值容差，重新编码核对新产物而非要求与384维旧值相同。对账通过才允许切换。

### 两种回滚时点

- **pgvector 尚无新写入**：保留同一维护窗口的关系库+FAISS快照及已验证旧制品，停止新进程后回切；只做增量 schema，不用破坏性 downgrade。关系库若仍涉及 SQLite，使用 T15 的成套恢复方案，不把 pgvector 故障当成允许丢聊天记录的理由。
- **pgvector 已有上传/聊天/删除/TTL 变化**：旧 FAISS 已过时，不能仅回滚镜像。重新冻结并备份当前 PG，将当前存活 Chunk/完整 metadata 和向量重建到新的 FAISS恢复目录，用兼容 BGE-M3 的旧后端制品验证，再切换；保留所有新增聊天并避免复活已删除数据。当前 MiniLM 旧镜像不能查询1024维重建索引，必须在切换前准备、演练 BGE兼容恢复制品。无法恢复就保持维护修复新系统。
- 移除 FAISS **运行时依赖**与删除**历史索引备份**是两件事：前者在本地验收后完成；离线迁移/回滚制品仍保留固定版本 FAISS，旧索引和磁盘删除须在回滚保留期后单独批准，不在自动部署脚本里清理。

## 7. 本地测试和性能验收

| 层次 | 必须验证 |
| --- | --- |
| 默认离线 | adapter契约、输入/profile维度、空库、metadata保真、费用/Memory/Graph/JSON/SSE原有测试；不连真实 DB，不调用模型供应商 |
| PG + pgvector 集成 | 真扩展/升级幂等、非空旧关系库增量升级、FK/唯一性、上传原子性、重复/中途失败/提交不确定、删除/TTL竞争、连接归还/耗尽/断连 |
| 隔离 | 两会话同名文件/相同内容/最近向量，逐个验证所有查询/删除路径；伪造metadata/session filter不可越界，k大于会话数量也不返回他会话；并行Graph和池复用不串数据 |
| 迁移/回滚 | 可信合成 FAISS、重复文本、多页metadata、缺Docstore/缺PDF、384与1024混合、非有限向量、重跑/冲突/中断；新聊天/上传/删除后回滚全量对账 |
| 功能 | 真实 PG+mock LLM 跑 QA/Summary/Keyword/Compare/Source及多Agent；上传/读取/JSON问答/SSE/Memory、费用和来源字段兼容；Streamlit及空会话路径 |
| 构建 | Linux Docker非root、模型离线加载、端口healthcheck、DB/扩展不可用时不可误ready、重启；前端npm test/build；CI独立PG服务及显式opt-in集成job |

沿用现有 TEST_DATABASE_URL 和本地 opt-in 安全边界，为 pgvector 集成增加独立开关；缺扩展/版本/配置时失败，不以 skip 代替已启用的验收。默认离线测试不需要 PostgreSQL。当前代码尚无 pgvector CLI；实施后才向 TESTING 添加可运行命令，不能用现有 FAISS CLI 报告冒充新后端结果。

评估分两组：

- **后端等价性**：冻结同一批 BGE-M3 Chunk、向量、查询向量，对 FAISS 与 pgvector 精确检索比较排名/距离、top-k和 source/page。非等距 top-k 应一致；浮点候选容差1e-5、归一化范数容差1e-5；等距允许同距离集合的稳定次序差异，不把序号差当质量下降。最终容差按实际dtype在 T16a登记。
- **模型差异**：当前 MiniLM → BGE-M3 单独对比引用召回、跨页/跨文档覆盖和检索遗漏；保留 `real_pdf_cases.json` 的30条用例及参考隔离，未人工复核标注仍为 provisional。QA等生成语义不能靠检索指标宣称通过；付费生成/Judge未授权时明确未运行。Source可本地无付费执行。

性能记录分开：模型冷启动、query Embedding、纯 SQL 检索、结果组装、上传批量写入、全链路（mock LLM），报告p50/p95、峰值RSS、DB连接峰值、表/索引大小及样本数。固定硬件、模型revision、热身，分别测并发1/5/10、每会话1k/10k及总100k等合成规模和三份真实PDF；这些规模是测试矩阵，不是当前生产量。

建议验收候选：10k Chunk/会话、并发5时纯SQL p95≤200ms；同profile精确检索证据召回不低于冻结FAISS；如启用HNSW，相对精确Recall@k≥0.99且无过滤少结果/串会话；目标容器峰值内存≤限额70%、无OOM和连接泄漏。以上是待确认目标，若基线不适合先调整并登记，不能测试后改阈值凑通过。本轮未做这些负载和质量测试。

## 8. Render 架构、成本和上线流程

2026-11-25 发布授权调整为复用现有 Render Web 实例、套餐及磁盘，在同容器运行 PostgreSQL/pgvector 和 Web 应用。仅初始化新库与迁移 Schema，旧版数据原样保留。本节下方保留最初托管 PG 与历史导入方案，以供设计追溯；现行操作见 [同容器部署设计](DEVELOPMENT.md#render-embedded-postgres)。

### 历史规划：独立托管数据库与旧数据导入

继续一个 Docker Web 服务托管 FastAPI + 已构建 React，本地 CPU BGE-M3；Managed PG 同时保存关系数据和 Chunk向量。首版单实例/单worker，避免多进程重复加载模型；无新GPU服务、Redis、pgvector独立服务。数据库与Web保持同工作区/区域（现有声明Singapore），核对环境隔离，优先内网连接。[Render私网](https://render.com/docs/private-network)

Render支持vector扩展，但现有目标实例的PG主版本、扩展版本、权限与费用尚未查询；上线前先核查并复用已有 Managed PG，不能自动再创建收费数据库。若实际不存在，则另批创建。DATABASE_URL通过已有秘密或Blueprint fromDatabase connectionString注入，DeepSeek Key继续sync:false，均不放Docker ARG/源码。外网管理连接使用TLS和访问限制，沿用T15连接池。[Render扩展](https://render.com/docs/postgresql-extensions)

### 资源预算（候选，非线上账单）

本地BGE探针参数567,754,752个，当前FP32权重占2,271,019,008字节（约2.11GiB），**不包括**激活、tokenizer、Python/Torch/FAISS或PDF解析内存。不能用当前1c-2g配置承诺可运行；Windows短文本探针耗时不代表Render延迟。首选在2CPU/8GB容器中测量，batch从1开始、有界并发；4GB仅在真实上传峰值和余量门槛通过后再选。不擅自更换量化/半精度或修改模型语义来满足预算。

2026-11-16核对官方月度标价：

| 候选 | Web | Managed PG | PG磁盘示例 | 月合计示例 |
| --- | --- | --- | --- | --- |
| 较稳妥的起测组合 | 2c-8g：$135 | 1c-2g：$40 | 5GB × $0.30 = $1.50 | $176.50 |
| 仅通过压测后考虑 | 2c-4g：$85 | 0.5c-1g：$19 | 5GB：$1.50 | $105.50 |

以上不是已批准套餐，不是现有资源实际消费；若已有PG应计算增量差额。未含工作区费用（Hobby $0、Pro $25/月）、超额带宽/构建时间、DeepSeek费用及旧盘保留费（1GB $0.25/月）；实际用量/地区可用性/账单上线前复核。5GB只是预算示例，需按数据盘点定容。[官方价格](https://render.com/pricing.md)、[Compute规格](https://render.com/docs/compute-plans)

1024维 vector 单项约4104字节，100k向量仅向量本体约410.4MB；还需正文/JSONB、B-tree/HNSW、行/TOAST/WAL、备份及迁移共存余量，不能据此宣称5GB可容纳所有数据。[pgvector存储定义](https://github.com/pgvector/pgvector#vector-type)

### 发布与持久磁盘

1. 复用Node/Python多阶段Docker、非root、固定BGE revision模型缓存；依赖和镜像不含Key、PDF、Docstore或备份。模型冷启动只读缓存，healthcheck遵守PORT，先验证模型/profile和DB schema，ready不触发LLM。保留公开/health响应；通过启动门控与内部探针实现就绪，不默默改公开API协议。
2. 本地集成、真实检索、Docker及恢复演练完成后，准备可审阅render.yaml、费用、维护窗口和不可逆步骤清单，再取得具体生产授权。保持autoDeployTrigger: off；Git推送、资源创建、配置同步和部署各按实际授权执行，不能因“最终部署”目标自动操作。
3. Alembic schema升级可作为pre-deploy，仅执行已验证的向后兼容增量DDL；runtime角色不做迁移。长时间向量导入不放pre-deploy，任何依赖旧FAISS磁盘的导出必须在可访问原盘的受控维护环境执行。Render pre-deploy和one-off均不能挂载原服务磁盘。[部署步骤](https://render.com/docs/deploys#pre-deploy-command)、[磁盘限制](https://render.com/docs/disks#disk-limitations-and-considerations)
4. 冻结业务/TTL、备份关系库及旧索引、导出/导入/对账，再切换Docker制品；迁移失败保持维护。已有生产PG数据禁止清库/重建关系表；升级前后校验会话/消息与文档快照，区分TTL合法删除和数据丢失。
5. 新制品无付费冒烟：会话恢复、测试PDF上传、Source、mock环境验证过的API/SSE契约、连接与引用；真实QA/模型健康验证如需付费另批。观测错误率、数据库连接、内存和检索延迟。异常按第6节回滚，不以旧镜像启动成功代替数据恢复。
6. 全量切换后，向量与关系数据不再需要应用持久盘，原PDF仍是临时文件，模型烘焙在镜像。迁移及回滚窗口继续保留旧/data磁盘/离线恢复制品；确认没有SQLite/FAISS/备份/模型缓存运行依赖、完成保留安排后才另批卸载/删除。最终Postgres备份可覆盖业务数据，但恢复环境仍需相同模型revision与应用制品；不因删掉FAISS就自动宣称支持多副本。

## 9. 拟修改模块与实施边界

| 模块 | 拟改动 |
| --- | --- |
| `app/db/`、T15 Alembic链 | 复用连接；增量vector类型/表/FK/index，校验扩展与profile；不重建关系库 |
| `utils/vectorstore.py`及小型PG adapter模块 | 会话绑定similarity_search，BGE配置与revision，替代FAISS读写入口 |
| `app/services/pdf_service.py`、`session_store.py` | 文档+Chunk原子提交、空库语义、删除/TTL级联；保留消息和公开字段 |
| `tools/`、Graph、Memory | 以原契约回归为主，不改k、提示词或节点决策；不进行无关重构 |
| `evaluation/real_pdf.py`、`runner.py`、`main.py` | 真PG评估作用域和报告后端字段、Streamlit适配；保留受控测试 |
| `scripts/`迁移工具、可选迁移依赖文件 | 可信FAISS导出、幂等导入/全量对账、反向恢复；FAISS仅离线迁移制品保留 |
| Docker/Compose/requirements/CI/render.yaml | 扩展镜像、固定模型、PG集成、最终移除runtime FAISS、内网配置及手动上线 |
| tests及开发/测试/架构/README | 实施后据实更新，README不提前宣称迁移/性能已完成 |

任务依赖与三阶段唯一状态见 [T16](../plans/TASKS.md#t16)。本轮只有代码审查、默认本地索引结构盘点和合成Embedding探针；没有运行pgvector、迁移/性能/全功能测试、生产查询或部署。建议下一轮先执行T16a固定基线与模型契约，再按既有T15b衔接；不同时实施整条迁移链。
