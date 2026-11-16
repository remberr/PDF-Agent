# 改造任务清单

更新时间：2026-11-16（Asia/Shanghai，pgvector规划修订）。任务状态的唯一文档来源；长期方向与里程碑见 [ROADMAP.md](ROADMAP.md)，当前实现见 [ARCHITECTURE.md](../docs/ARCHITECTURE.md)。需求分级、自动执行及确认边界统一见 [AGENTS.md](../AGENTS.md)。

## 任务记录约定

- 先检索已有任务；相关需求更新原条目，必要时沿用父编号拆子项。简单低风险修改可不建任务，不为满足格式增加空任务。
- 新建或启动已有任务时补齐：编号/标题、优先级、状态、需求或代码依据、范围、依赖（没有则写“无”）、验收标准及回归方式。涉及确认事项时注明待决方案与批准范围；无需重写未启动任务的历史记录。
- 默认按本文任务顺序选择当前需求范围内、依赖已满足且可执行的未完成项；需要调整顺序时，在相关任务注明原因及前置条件，用户指定顺序优先。优先级用于排序判断，不代表绕过依赖或确认边界。
- 状态沿用中文记录：“待实施（TODO）→ 进行中（IN PROGRESS）→ 已完成（DONE）”；外部条件、必需测试环境或必要批准未满足，以及当前无法解决时记“阻塞（BLOCKED）”。这些是同一套状态的对应名称，不批量改写历史条目；解除阻塞后回到进行中。部分交付不标完成，子项完成不代表父项完成。
- 完成记录包括验证日期、实际命令与结果、跳过/未运行项及原因、剩余限制；验收尚未验证不得标为已完成。既有失败与新增失败分开记录，不复制整段日志。具体流程以 AGENTS 为准。
- 阻塞记录写明原因/证据、已尝试办法、未验证改动的影响、受阻依赖及具体解除条件；不能只写“测试未通过”。连续执行、独立任务选择和暂停条件统一遵循 [AGENTS.md](../AGENTS.md#连续任务执行模式)，本文件不重复维护执行规则。

## 2026-11-16 T02a 实施前复核（历史记录）

基线 HEAD：`4d4e55b`。已有差异为上一轮六份未跟踪工程文档，无跟踪代码修改；本轮保留这些文件。第一阶段审计以当时对话报告及 ARCHITECTURE 中的代码依据复核，仓库没有独立审计报告文件。未确认 P0 事故，不将风险等同于已发生泄露。

| P1 项 | 本轮确认的代码依据（函数或入口） |
| --- | --- |
| T01 | `AskRequest` 仅 min_length；`upload_pdfs` 仅后缀检查；`load_pdf_into_session` 全量 read 后同步解析/Embedding，无字节/页/chunk 上限 |
| T02 | `chat_with_deepseek`、`_execute_specialist_step`、`collaboration_agent`、`iter_pdf_agent_events` 拼接异常；`JsonFormatter` 原样输出异常消息/堆栈 |
| T03 | LLM 客户端仅单调用 timeout，未设置整体预算；`evaluation.runner.run` 的显式付费 guard 仅限制 real-pdf |
| T04 | `routes.py` 仅按 session_id 查会话，无所有权检查；`get_session` 读取 DB 索引路径，`load_vectorstore` 开启危险反序列化；未确认可从公网写入恶意索引 |
| T05 | `save_session` 全量 UPDATE 无版本冲突检查；上传先保存 FAISS 后 SQLite；清理/删除与活跃请求无共享协调 |
| T06 | `iter_pdf_agent_events` 捕获异常后仍 `_save_result` 并记录 completed；保存异常在该捕获范围外 |
| T07 | `App.tsx` 恢复会话的 catch 对任意错误 removeItem；`api.ts` 主要类型断言，流无完整终态/取消契约 |
| T08 | Summary/Compare 固定全库 k=30 后每文件最多三块，QA/Source k=3；无逐文档覆盖保证或语义引用验证 |

本轮选择 T02a：直接错误披露风险有明确证据，范围小，无认证/存储迁移依赖。建议后续顺序 T01 → T03/T04 → T05 → T06/T07 → T08；T02b 保留为独立隐私治理项。T05 的潜在数据丢失风险较高，但需先明确并发和恢复契约，不能混入本轮。

基线实跑：后端 unittest 69 项（66 通过、3 跳过），routing 9/9、零 LLM，前端 npm test 6/6、npm run build（含 tsc -b）通过。Vite 首次因沙箱父目录权限失败，同命令在允许权限下通过，未改配置。Docker 引擎不可用，未构建镜像；不阻断此局部后端任务。未调用付费 API、未部署。

## 阶段 1：边界

<a id="t01"></a>
### T01 · P1 · 待实施：输入与资源限制

- 范围：`app/schemas/requests.py`、`app/api/routes.py`、`app/services/pdf_service.py`；配置化问题长度、文件数/字节/页/chunk 限额，文件有效性校验；让耗时同步解析/索引不直接阻塞 async 路由，并约束并发。明确多文件部分成功语义。
- 验收：无效/超限输入不进入后续高成本阶段；正常多 PDF 兼容；失败清理临时资源，返回稳定安全的错误。阈值以实际样本确定，不编造容量。
- 回归：边界值、伪后缀/损坏/空 PDF、重复名、后续文件失败、并发负载下健康接口响应；现有会话/路由测试。

<a id="t02"></a>
### T02 · P1 · 进行中：错误与日志最少披露

- 范围：`utils/observability.py`、`utils/llm_client.py`、API/Agent 错误出口；处理原始异常、文件路径、会话标识在日志与响应中的披露，评估访问日志和浏览器持久化内容。
- 验收：用合成敏感字符串验证客户端/常规日志不泄露 Key、PDF 正文或内部路径；会话标识采用明确策略；仍能用 request_id 关联错误类型和耗时。
- 回归：上游错误、解析错误、存储错误、日志关联与现有 usage；不得把屏蔽所有错误当作脱敏。

<a id="t02a"></a>
#### T02a · P1 · 已完成：异常正文披露

- 范围：上述四个 Agent/LLM 异常出口、JsonFormatter 异常字段，以及 `tests/test_error_privacy.py`。采用固定失败提示；格式化异常保留类型、模块/函数/行号和原因链，不输出异常正文、绝对路径、源码行或 locals；新增失败事件只写类型/步骤等元数据，避免未配置 JSON formatter 的 CLI 输出原始堆栈。保留 request_id 关联及失败用量。
- 验收：合成敏感异常不进入 JSON/SSE、保存的回答/协作建议和结构化异常日志；保留协议字段、成功行为、失败的已知/未知用量和诊断关联。
- 修改前验证：最初 11 个子场景失败中，有 2 个是测试误把既有 QA“模型不可用”回退当作 Specialist 失败；修正该断言，保留原业务回退。将最终测试在内存中加载的原始 HEAD 五个模块上重放，确认 9 个真实披露失败场景，未回写源码。仅使用合成标记和 mock，记录在已忽略的 `.evaluation-local/engineering-t02a-baseline-replay.log`。
- 修改后验证（2026-11-16）：完整 `python -B -m unittest discover -s tests -v` 共 75 项，72 通过、3 个原有 opt-in 跳过；新增 6 项回归全部通过。基线为 69 项/66 通过/3 跳过，无新增失败。日志 `.evaluation-local/engineering-t02a-tests.log`。
- 评估/构建：routing 9/9 与基线一致；controlled live 的 source-citations 1/1，通过 route/source/citation 阈值，两者均零 LLM 调用；报告为 `.evaluation-local/engineering-t02a-routing.json`、`engineering-t02a-source.json`。本轮前端 npm test 6/6、完整 build/tsc 已通过，前端未修改故复用该结果；Git diff 空白检查通过。无已配置的 Python lint/type-check 命令，不虚构此类结果。
- 边界：未运行付费、真实 PDF 集成或真实部署；Docker 引擎不可用，镜像构建未执行。异常正文被省略后诊断信息减少，但保留类型/代码位置/请求关联；API/SSE 字段及正常回答不变。T06 的失败终态、其他日志内容及 T02b 隐私策略未修复；本轮未提交/推送，整个 T02 不标完成。

<a id="t02b"></a>
#### T02b · P1 · 待实施：会话标识与其他日志/浏览器隐私

- 范围：原始 session_id/请求路径、Uvicorn 访问日志、其他日志 message/structured_fields、本地评估报告异常文本、浏览器 localStorage 与保留策略。T02a 不提供任意字符串 DLP，也不更改业务证据/用户正文；普通第三方日志消息或未使用 JsonFormatter 的既有日志处理器需另行审查。
- 验收：明确会话凭据与日志标识策略，合成数据验证日志和前端存储边界，同时保留 request_id 排障和当前 API 兼容性。与 T04 的访问方案协调。
- 回归：访问日志、请求路径、跨会话、浏览器恢复/清理、异常与 usage；未实施，未宣称全链路脱敏完成。

<a id="t03"></a>
### T03 · P1 · 待实施：工作流预算与付费防护

- 范围：`utils/llm_client.py`、Memory、Graph/服务层及 `evaluation/runner.py`；明确 SDK 重试与整体调用/Token/耗时预算，统一 live/real-pdf/Judge 的付费选择语义。
- 验收：预算耗尽不再发起新调用，保留已发生用量/未知成本；重试有界；默认测试与未授权 CLI 不调用供应商。保留 Source/Planner/Reviewer 快路径和报告兼容性，说明新 CLI 约束。
- 回归：超时、重试、预算边界、Judge 失败、模型别名、usage 隔离；使用 mock 验证调用次数，不依赖付费测失败。

<a id="t04"></a>
### T04 · P1 · 待实施：会话访问与可信索引边界

- 范围：会话 API、存储路径、必要前端凭据传递；先明确公开匿名 demo 的访问方案与旧会话兼容策略，再实施最小保护。验证读取索引路径的可信边界。
- 验收：访问和删除遵循确认后的凭据契约，拒绝不匹配的访问；持久化路径在可信根内；不反序列化外来索引。不默认建立完整账号系统，不把 CORS 或 UUID 难猜当所有权验证。
- 回归：合法旧/新客户端、无效凭据、路径边界、删除和恢复；使用隔离测试数据。

## 阶段 2：一致性与生命周期

2026-11-16 pgvector规划修订：当前仍是SQLite/MiniLM，T15a以外的数据库任务未完成。用户目标已改为BGE-M3 + pgvector；依赖按[T16](#t16)衔接。以下调整只更新待办范围，不表示实施或生产授权。

<a id="t05"></a>
### T05 · P1 · 已完成：关系数据库/向量数据并发与恢复

- 依赖：T15c、T16c；按[新方案](../docs/PGVECTOR_MIGRATION.md)落实，不先实施即将淘汰的FAISS文件代次发布。
- 范围：关系元数据/Chunk原子提交的竞争和故障处理，唯一约束、提交不确定、TTL/删除及活跃请求。基本写入由T16c负责，消息追加由T15c负责，不重复实现。
- 验收：并发上传/问答不覆盖或重复计数，不复活删除会话；无半写/跨会话Chunk；断连不盲目重放。旧FAISS归档受保护，DB故障不触发“孤儿”批量删除。
- 回归：并发屏障、每个写入阶段及commit不确定故障、进程重启、TTL/删除竞争；恢复由T16d/T15f联合验收，持续备份与T12衔接。

<a id="t06"></a>
### T06 · P1 · 待实施：Agent / SSE 失败终态

- 范围：Graph 输出、`agent_service.py`、响应 schema；保留 Specialist 失败信息，统一 JSON/SSE 结果与保存失败语义，减少节点映射漂移，明确断线后的服务器行为。
- 验收：失败/降级不伪装成功，流有明确终态或可识别中断；记录已发生用量；不因自动重试重复生成。兼容既有事件或提供增量扩展说明；不承诺无法证实的上游即时取消。
- 回归：成功、单 Specialist 失败、Reviewer 降级、Graph 异常、保存失败、断线、空/截断流；依赖 T05 的持久化契约。

<a id="t07"></a>
### T07 · P1 · 待实施：前端恢复与流契约

- 范围：`frontend/src/api.ts`、`App.tsx`、工作流面板和 types；区分 404 与临时网络故障，验证外部结果形状、处理存储失败、陈旧请求/会话切换与取消。
- 验收：临时网络故障不删除可恢复的历史；失败不显示完成；跨会话结果不串写；按 T06 正确处理终态并保留双语费用/缓存三种状态。
- 回归：分段 SSE、无 result、错误终态、切换/重复请求、localStorage 异常，补浏览器/组件级必要用例；TS 与前端 build。

## 阶段 3：质量

<a id="t08"></a>
### T08 · P1 · 待实施：检索覆盖与引用质量

- 范围：`tools/`、引用输出及真实 PDF 评估；优先按问题/文档改善 Summary、Compare 和跨页检索，明确无答案/证据不足行为，保持会话隔离。
- 验收：在预先选定且复核的样本上对比基线，报告遗漏和退化；跨文档任务覆盖所需文档，引用可定位原页；不把参考答案注入 Agent，也不无限增大上下文。阈值在执行前约定。
- 回归：本地真实 PDF 检索、跨页/跨文档/无答案/证据不足用例、受控引用测试；付费生成与 Judge 需另行授权，未运行明确标记。

<a id="t09"></a>
### T09 · P2 · 待实施：模型结构与 Memory 边界

- 范围：Planner/Collaboration 输出校验、`AgentState` 边界、`utils/memory.py`；校验步骤和内部字段，规范去重；限制摘要缓存和历史输入，减少锁内模型 I/O。
- 验收：非法 JSON/步骤/类型走确定的有界回退；单次补充上限不变；Memory 不跨会话串用，有明确容量/淘汰策略；保留既有快路径与回答上下文。
- 回归：畸形输出、重复/未知步骤、空内容、长历史、并发摘要、缓存淘汰、用量归属。

<a id="t10"></a>
### T10 · P2 · 待实施：参考标注复核与评估契约

- 范围：`evaluation/real_pdf_cases.json` 的人工事实/引文/拒答复核记录；补充 HTTP/SSE/持久化风险对应评估与测试映射，保持结构指标与语义指标区分。
- 验收：仅经人工确认的条目可更新验证标记，保留复核依据、日期和歧义；无 Key CI 保持零供应商请求；引用匹配不包装为事实正确率。
- 回归：manifest/原文证据验证、Agent/Judge 隔离、Judge 失败、报告模式/阈值兼容。人工复核未完成的条目继续标为待复核。

## 阶段 4：交付与维护

<a id="t11"></a>
### T11 · P2 · 待实施：依赖可复现与容器冒烟

- 范围：Python 依赖锁定策略、Docker 基础镜像/Embedding revision、CI；核查依赖告警适用性，增加容器实际启动和健康验证。保留前端 `npm ci`。
- 验收：干净环境可重建且记录依赖/模型版本；容器以非 root 启动并检查默认及配置端口；没有 Key/PDF 混入镜像；安全升级单独验证兼容性，不根据旧告警直接断言可利用。
- 回归：完整离线后端、routing、前端 test/build、Docker 构建与运行冒烟；CI 不开启付费请求。

<a id="t12"></a>
### T12 · P2 · 待实施：运维与恢复证据

- 依赖：T05、T15d、T16d、T15f。T15/T16负责一次性迁移/回滚，本项负责持续运维，不重复实现迁移工具。
- 范围：最终PostgreSQL关系数据+pgvector统一备份，模型revision/制品单独保留；迁移期SQLite/FAISS快照仍成套保留。明确liveness/readiness、指标和保留策略。
- 验收：在隔离目录完成备份恢复并验证同一会话文档/历史；健康检查不会触发付费 API；失败指标可定位请求。线上演练、部署和告警通知需另行授权。
- 回归：缺失/损坏索引、不可写存储、重启、备份一致性；不以静态 `/health` 成功代替依赖和恢复验证。

<a id="t13"></a>
### T13 · P2 · 待实施：开发入口与文档收敛

- 范围：`.devcontainer` 默认入口及安全设置；检查两份 README 与新工程文档的重复信息，明确可选 Streamlit 定位；许可证选择须由项目所有者确认。
- 验收：开发入口与主 Web 栈一致或清晰标为原型；命令维护单一来源，旧链接可达；不擅自改变 README 能力描述或添加许可证。
- 回归：按选定开发路径启动验证、文档链接/命令一致性；只改文档时无需跑付费或业务测试。

<a id="t14"></a>
### T14 · P2 · 待实施：定价与节假日日历维护

- 范围：`utils/pricing.py`、`china_holidays.json`、相关单元测试；核实新年份官方日历及供应商独立币种价格/别名，不复制多处价格表。
- 验收：新增数据带可追溯官方来源与核实日期；时区、峰谷、周末/节假日和环境覆盖保持一致；信息未知明确 unavailable；不以汇率替代 CNY 官方价。
- 回归：时间边界、未知年份、法定假期/调休周末、别名、缓存计费、CNY/USD 和不完整用量。仅查证价格不需要付费调用；2027 年数据未在本阶段核实。

## PostgreSQL 专项（T15a完成，后续衔接pgvector规划）

<a id="t15"></a>
### T15 · P1 · 进行中：SQLite → PostgreSQL 迁移

- 依据：保留[原审计与方案](../docs/POSTGRESQL_MIGRATION.md)和T15a历史验收。用户确认仍是同一工作区，当前业务仍在SQLite；上轮只完成T15a，不将整个T15标为完成。
- 范围：最新目标调整为BGE-M3 + pgvector，Graph/RAG/Memory及公开API/SSE兼容；本轮仅规划，原实施授权不等于本轮执行指令。生产资源、费用、迁移/部署仍另批。
- 顺序：T15a不重做，T15b/c/d沿用编号，与[T16](#t16)依赖衔接；T05负责向量同事务与竞争，T15e/f/g复用配置、演练和上线职责，不重复创建部署任务。
- 总体验收：完整历史/文件名/页数/ID/索引关联经全量对账；公开契约和既有回归通过；PG 集成、导入、故障恢复与双阶段回滚演练通过；生产切换有独立证据。仅安装驱动、空库建表或规划完成均不满足。
- 规划阶段记录（19:12）：静态阅读全部存储 SQL、调用方/生命周期测试、配置和部署文件；查询官方技术文档，未打开真实数据库或执行备份/迁移。T15a 当前验证见下；schema、数据迁移和生产验收仍未执行。

<a id="t15a"></a>
#### T15a · P1 · 已完成：连接配置与可丢弃开发数据库

- 依赖：T15 本地实施方案已获本轮用户批准；无代码前置任务。
- 范围：显式 SQLAlchemy/psycopg/Alembic 依赖，`app/db/config.py`/`engine.py`、DATABASE_URL 与池参数、Compose PG17/独立卷/healthcheck、专用测试 URL；不修改生产配置。
- 验收：应用导入不连接数据库；缺失/错误 URL 明确失败、不回退 SQLite；特殊字符密码能解析且不写日志；池连接正确归还，超时有界；不共享 Connection 跨线程。Compose 新数据库不覆盖旧 `/data`。
- 回归：配置单元、连接/断连/池耗尽集成、密码脱敏；不得使用生产 DATABASE_URL 作为测试 fallback。
- 实施（2026-11-16）：新增 `app/db/{__init__,config,engine}.py`、`compose.postgres.yaml`、两份数据库测试；同步两份 requirements、`.env.example`、开发/测试文档及架构边界。固定 SQLAlchemy 2.0.52（保留既有版本）、psycopg[binary] 3.3.9、Alembic 1.20.1；官方 PG17 镜像固定 digest，实际服务器 17.12。配置惰性加载，严格 URL/池参数与安全错误、隐藏 URL repr/SQL 参数，UTC、pre_ping、有限连接数和等待。
- 小范围落地调整：采用独立 `compose.postgres.yaml`，而非立即改主 Compose；避免 T15c 前改变现有 SQLite 应用启动或要求新密码。新文件只启动测试 DB，无迁移服务，完整 Compose 接线仍归 T15e。未修改生产配置、业务存储或 Agent/API/SSE。
- 验证：修改前离线 75 项（72 通过、3 opt-in 跳过）；修改后 `python -B -m unittest discover -s tests -v` 92 项（82 通过、10 opt-in 跳过，其中 7 项 PG、3 项既有 PDF/付费测试）。`test_db_config.py` 的 8 项包括独立进程导入 app 不建 Engine/不连 SQLite 或 PG。启用本地 PG 后 `python -B -m unittest discover -s tests -p test_postgres_connection.py -v` 9/9 通过（7 项真实集成 + 2 项入口防护）。缺失 TEST_DATABASE_URL 时启用测试如期非零失败，不跳过、不回退。
- 验证续：真实随机特殊字符密码连接成功；commit/rollback、池归还/耗尽、线程隔离、终止本测试 backend 后 pre_ping 恢复、中断事务失败及连接拒绝通过。`pip check` 无依赖冲突；Compose `config --quiet`/`up --wait` 成功且 healthy；routing 9/9、受控 Source 1/1，均零 LLM 调用；`git diff --check` 通过。命令详见 TESTING，日志/报告位于被忽略的 `.evaluation-local/t15a-*`。
- 环境与保护：本轮 Compose 项目 `pdf-agent-t15a`，仅回环端口 55432，独立卷 `pdf-agent-t15a_postgres-data`。验收后容器已停止（退出 0），卷及本地忽略的随机开发凭据文件保留，未读/改原 SQLite 数据。既有五个业务文件及 error_privacy 测试哈希未变，未提交/推送/部署。
- 剩余边界：未建业务 schema、未接入应用生命周期/存储、未迁移数据；未验证 TLS/Render/高负载容量或 Linux 应用镜像依赖安装。前端和完整应用镜像本轮未重建（无相关代码改动，容器集成归 T15e）。T15b 是下一项，本轮停止。

<a id="t15b"></a>
#### T15b · P1 · 已完成：三表 schema 与 Alembic

- 依赖：T15a、T16a（基线/模型与文档键契约，不重做连接）。
- 范围：Core metadata、sessions/session_messages/session_documents、索引/FK/CHECK、Alembic revision；连接配置复用，不复制密码。将数据库初始化与应用业务启动分开。
- pgvector衔接：文档稳定键供T16b的Chunk复合FK引用，不为旧FAISS新建文件代次机制；已有字段在回滚窗口保留，不擅自删除数据。
- 验收：空 PG 库显式 upgrade 成功，重复 upgrade 无副作用；schema/revision 不匹配时业务不能误启动；全部约束及 UTC 秒精度往返正确；未运行数据导入或任意清表。
- 回归：PG17 真实建表、约束违规回滚、排序/FK、迁移失败、历史 revision 升级；autogenerate 必须复核，不能用 create_all/stamp 冒充迁移。

<a id="t15c"></a>
#### T15c · P1 · 已完成：持久化兼容层与短事务消息追加

- 依赖：T15b。
- 范围：session_store 改为 PG，保留服务入口和字典；消息 batch 幂等追加与文档元数据持久化分离；仅调整 agent_service/PDF 服务的内部保存调用；Engine lifespan、schema 检查及维护/保留开关。
- pgvector衔接：向量adapter接线由T16c负责，未完成接线前不宣称整应用迁移；保留空会话和历史上下文行为。
- 验收：ID/loaded_pdfs/messages/页数/公开响应不变；未知消息字段不丢；并发保存不覆盖历史或复活已删除会话；不在模型/Embedding/SSE 等待期间持数据库连接；停用保留同时阻止 startup/周期/get_session 的过期删除。未完成 T05 前不可作为生产切换候选。
- 回归：PG CRUD、消息顺序/批次重复/内容冲突、事务回滚、TTL 边界、mock LLM 的 JSON/SSE/Memory/usage 与既有离线套件；无数据库的 evaluation/单元测试仍可运行。

<a id="t15d"></a>
#### T15d · P1 · 已完成：只读预检、成套备份、导入与反向导出

- 依赖：T15b、T15c、T05。
- 范围：拟新增 SQLite 导入及 legacy 导出脚本；严格 JSON/schema 校验、路径 manifest、快照身份/重跑检查、目标事务与对账报告；保护原库及原索引。
- pgvector衔接：本项负责关系数据与快照，向量转换/反向FAISS重建由T16d负责，不复制importer；完整恢复由T15f联合验收。
- 验收：合成旧五字段和当前七字段关系库完整迁入，所有行/消息字段及顺序/时间/页数对账；原索引快照哈希保留。异常数据阻止切换，非空冲突拒绝覆盖，中断不产生半批关系数据。反向SQLite导出包含PG新增聊天并保持经核验的索引关联，原文件不改；新向量的旧布局物化由T16d独立验收，整应用可读性归T15f，避免验收依赖成环。
- 回归：SQLite WAL 备份、空会话、缺索引、异常路径/JSON/时间/重复文件、全量和失败重跑、PG 断连、反向恢复对账；先合成数据演练，真实数据操作另获授权。

<a id="t15e"></a>
#### T15e · P1 · 已完成（本地范围）：Compose/CI 集成与 Render 配置准备

- 依赖：T15a–T15d、T05、T16e。
- 范围：Compose一次性Alembic/就绪、固定pgvector镜像、CI独立集成job、BGE多阶段Docker；Render Managed PG引用/fromDatabase、schema pre-deploy及候选预算。只准备配置，不创建资源或部署。
- 验收：本地/CI/目标Render的PG与扩展兼容；缺DB/扩展明确失败，默认零付费；模型离线加载、内存余量/PORT健康检查通过；无秘密入配置。旧FAISS盘在回滚窗口保留、手动部署；pre-deploy不读/data，导入在可访问旧盘的受控环境执行。
- 回归：Compose 启动顺序/重启持久化、前端 test/build、Docker 本地构建/健康检查、Blueprint 静态校验；平台能力与套餐上线前复核，当前不承诺可直接部署。

<a id="t15f"></a>
#### T15f · P1 · 已完成：隔离环境迁移与回滚演练

- 依赖：T15d、T15e、T05、T16d、T16e。
- 范围：按新pgvector方案联合演练冻结/备份/升级/关系与向量导入/对账/新写入/反向恢复；恢复制品必须兼容BGE，不能仅换回MiniLM旧镜像。同步开发/测试/架构、AGENTS及README已验证事实。
- 验收：新旧快照完整对账，新增消息回滚不丢；并发上传/删除/TTL 故障注入不破坏索引；所有既有回归、PG 集成与本地容器冒烟通过；记录真实耗时/容量及未验证项，明确上线与回滚阻断条件。
- 回归：完整离线套件、routing/受控 Source、PG/迁移/并发测试及前端构建；真实 PDF/缓存模型验证单独标记，本任务不调用付费 LLM。没有实际演练不能标完成。

<a id="t15g"></a>
#### T15g · P1 · 待实施：经批准的生产切换

- 依赖：T15f、T16f全部验收，现有Managed PG、扩展/资源费用和维护窗口核实，生产迁移/配置/部署明确批准；若需新收费资源则单独批准。本轮仅有最终上线目标，无实际生产操作授权。
- 范围：盘点实际生产数据、冻结并排空请求、成套备份、执行经演练的迁移、全量对账及切换；明确恢复 TTL 与备份保留时间。
- 验收：生产 ID/聊天/文档/索引逐项对账并确认公开契约；保留可用回滚制品和备份，不删除旧库。首次新写入前后分别采用已演练的回滚流程；报告实际执行结果，不因 T15f 通过而代替上线验收。
- 回归：批准范围内非付费冒烟、日志/连接/磁盘关联及重启验证；发生数据差异即停止开放业务并按批准的恢复方案处理，不自动执行破坏性降级。

## pgvector 专项（2026-11-16，本地实施已授权）

<a id="t16"></a>
### T16 · P1 · 进行中：FAISS → PostgreSQL pgvector

- 依据：用户选择BGE-M3 + pgvector并以Render上线为最终目标；实际仍是SQLite/MiniLM，证据、技术方案和风险见[专项设计](../docs/PGVECTOR_MIGRATION.md)。本轮只做规划，不运行迁移或部署。
- 三阶段：①pgvector迁移：T16a–d，复用未完成的T15b/c/d和T05；②本地验证：T16e、T15e配置/CI准备、T15f联合演练、T16f移除runtime FAISS；③Render部署：复用T15e配置与T15g另行批准的上线，不重复建任务。
- 顺序：T16a → T15b；T16b依赖T16a/T15b，T15c依赖T15b；两者完成后T16c → T05 → T15d → T16d → T16e → T15e → T15f → T16f → 经批准T15g。T15a不重做。
- 总体验收：关系数据不丢、Chunk/向量/metadata/会话对应全量对账；五Agent、RAG/Memory/API/SSE兼容；本地检索/容量/构建和新写入后回滚有证据；runtime及真实评估不再依赖FAISS，离线迁移制品与旧索引保留。上线独立验收。
- 本轮验证：默认本地两份FlatL2共51向量均384维，Docstore仅核对配对文件存在；当前工厂输出384维非单位向量；单独缓存BGE合成探针1024维单位向量、FP32参数约2.27GB。未反序列化Docstore、未连接数据库，未运行pgvector、迁移/性能/生成质量测试；T15a旧结果不是pgvector验收。

<a id="t16a"></a>
#### T16a · P1 · 已完成：固定基线与 Embedding 契约

- 当前授权：用户已明确批准连续执行T16a–f、T15b–f和T05的完整本地迁移与验收；不含T06/T07、生产数据库、Render部署或历史数据删除，付费/破坏性操作另行确认。
- 增量验证（2026-11-16）：保留现有`utils/embeddings.py`和Dockerfile的进行中改动；新增缓存缺失不下载、模型维度不匹配拒绝加载测试。固定revision的BGE真实离线文档/查询探针均1024维并通过单位范数校验。完整离线unittest共99项，89通过、10个opt-in跳过，日志`.evaluation-local/continuous-baseline.log`；git diff空白检查通过，Docker引擎29.8.2可用。
- 未完成：应用向量入口仍是旧MiniLM/FAISS；文档键/profile契约、同模型检索基线及完整容器验证尚未收尾。T16a不标完成，下游数据库Schema/向量迁移、集成评估、Docker构建和恢复演练仍未执行。本记录不将未执行项当作通过，也不将可用的Docker环境误记为阻塞。

- 依赖：T15a；本轮方案获批，明确当前MiniLM到BGE-M3接线属于实施范围。
- 范围：复用HuggingFaceEmbeddings，固定BGE revision/dtype/归一化/长度/批次和profile指纹，明确关系文档稳定键；登记同模型FAISS比较基线及性能门槛。不重复数据库连接任务。
- 验收：query/document均1024维、有限、非零，范数满足登记容差；配置/镜像来源一致，缺模型明确失败、不静默换模型；保留模型变化评估基线。
- 回归：离线合成Embedding、profile/维度错配、模型缺失；无付费。本轮探针没有实现配置契约，不能标完成。

<a id="t16b"></a>
#### T16b · P1 · 已完成：pgvector 增量 Schema

- 依赖：T16a、T15b。
- 范围：复用Engine和Alembic链，新增vector扩展、document_chunks、复合FK/唯一键/B-tree过滤索引；固定本地PG17+扩展镜像，首版不建HNSW。
- 验收：非空关系库升级后ID/消息/文档不变；错误维度/跨会话FK拒绝；重复upgrade安全；扩展缺失/权限不足失败；首次迁移不依赖尚不存在的vector类型注册。
- 回归：真实PG建表/增量升级、约束及失败回滚、非法向量/metadata；不新建第二套连接池或文档表，不执行生产DDL。

<a id="t16c"></a>
#### T16c · P1 · 已完成：会话检索适配与原子上传

- 依赖：T16b、T15c。
- 范围：SessionVectorStore的similarity_search，PDF编码后同事务写文档/Chunk/页数；空库语义、会话/内部文档删除和TTL；评估scope及Streamlit接线。
- 验收：session/profile先过滤再top-k，metadata不能覆盖scope；原k/source/page/API/SSE不变；失败无半提交；空会话has_vectorstore正确；模型等待时不占连接。不新增公开单文档DELETE端点。
- 回归：真实库基本CRUD/两个会话同名同内容、五Agent/组合mock LLM、Memory/usage/JSON/SSE、TTL/重复名；深入竞争/故障复用T05。

<a id="t16d"></a>
#### T16d · P1 · 已完成：FAISS 导入、对账与反向恢复

- 依赖：T16c、T05、T15d。
- 范围：可信快照dry-run/export/import/verify及PG到BGE兼容FAISS恢复；复用关系快照工具，记录来源/profile/逐Chunk对应；不改原库原索引。
- 验收：可证实同profile时复用可无损重构向量；384维/未知profile从完整Chunk重编码并单列模型变化；源缺失/损坏阻塞切换；相同快照重跑完整对账后no-op，冲突拒绝；新写入/删除后反向重建不丢新增历史、不复活已删除数据。
- 回归：合成索引/重复正文/缺字段/映射错误/维度混杂/非有限向量/路径边界、重跑/中断/反向恢复；不加载陌生pickle，不用MiniLM旧制品检索1024维数据。

<a id="t16e"></a>
#### T16e · P1 · 已完成：本地集成与 RAG 性能验收

- 依赖：T16d。
- 范围：真PG及本地PDF评估，同BGE向量FAISS/pgvector精确对照，MiniLM→BGE差异单列；生命周期/隔离/五Agent/API/SSE/Memory及分段延迟、内存/并发矩阵。
- 验收：数据和引用全量核对、非付费回归无新增失败；按事先登记门槛报告top-k/证据召回、SQL与Embedding p50/p95和峰值RSS；精确性能不足才提出HNSW方案。未授权Judge/生成明确未运行，不将结构指标当语义质量。
- 回归：完整离线/PG、routing/Source、真实PDF跨页/跨文档/无答案/证据不足；保留StaticVectorStore。无本地数据/缓存则报告阻碍，不以生产DB替代。

<a id="t16f"></a>
#### T16f · P1 · 已完成：移除运行时 FAISS 并复验制品

- 依赖：T16e、T15f（包含T15e本地Docker/CI与配置准备）。
- 范围：从API/原型/真实评估活动路径及普通requirements移除FAISS和本地索引读写；离线迁移/恢复制品保留独立固定依赖；据实更新架构及开发文档，不删除旧索引/Render盘。
- 验收：未安装FAISS的干净Linux镜像构建/运行/重启、上传/检索/删除/TTL及五Agent回归通过，无隐式FAISS降级；StaticVectorStore可用，离线回滚仍能恢复新写入。
- 回归：无FAISS环境完整后端/PG/评估、前端test/build、Docker健康和模型离线加载、runtime import审查。通过后仍等待T15g具体授权，不自动推送、创建资源或部署。

## 当前本地实施记录（2026-11-16）

- 用户最新范围：只完成本地 PostgreSQL + pgvector；Render 配置和部署均不执行。历史规划中的部署目标不作为本轮验收。
- T15b/T16b：独立 compose.vector.yaml 容器健康；显式 Alembic upgrade head 成功，两次重复 upgrade 通过。没有修改旧 SQLite/FAISS。
- T15c/T16c：已增加 PG 会话短事务、消息批次追加、隔离检索和原子上传接线；真实数据库新增 5 项测试通过。完整回归、迁移脚本、故障与回滚验收仍在继续，以上任务不标完成。

### 本地进展补充（2026-11-16，用户已确认时间补齐策略）

- T15d/T16d：原 SQLite 五字段结构缺时间；用户批准只为缺失时间填入本次快照创建时刻，并保持 TTL 清理关闭。独立快照 7 会话/两套索引已保留；51 Chunk 从可信 Docstore 重编码为固定 BGE 1024 维。导入 pdf_agent_local 后完整消息/文件名/页数/时间/Chunk 元数据对账通过；重复导入返回 already_imported，不覆盖数据。测试仅使用 pdf_agent_test。
- 恢复：已导出 7 会话/51 向量的 BGE 兼容 SQLite/FAISS 副本；新增聊天、用量字段及已删除测试会话不复活的合成恢复测试通过。完整旧应用恢复/无 FAISS 镜像尚未验收，不标 T15f/T16f 完成。
- T16a/T16e：同 BGE 向量 51 个 probe 的 FAISS IP 与 pgvector cosine 分数最大误差 2.384e-7，小于预先设定 1e-5；此为数值一致性，不是语义质量或负载容量。真实 PDF 评估第一次因 Windows GBK 输出失败未产出 JSON，已修复并重跑，不能将第一次记作通过。
- API：PG 后端 Source JSON/SSE 实测通过，0 次 LLM 调用；非空关系 schema 0001→0002、重复 upgrade 和消息批次冲突/TTL/隔离/事务回滚已测试。
- 前端：npm test 6/6；普通沙箱 npm run build 被父目录访问限制阻断，提权本地重跑 tsc/Vite 成功。
- T15e 当前阻碍：Docker 构建在获取 docker/dockerfile:1 frontend 时，auth.docker.io:443 连接超时。未生成镜像，不能宣称 Docker 健康/重启/无 FAISS 验收通过。已有本地镜像均为旧制品，不替代新制品验收。Render 不在本轮范围。

- T16e 并发探针验收门槛（运行前登记）：本地现有最大 50 Chunk 范围，1/2/4 并发各 3 次查询，结果数量/来源范围正确，无异常或连接泄漏；单次查询上限 10 秒。同模型数值差容差 1e-5。该小规模实验不作生产容量承诺；记录进程峰值工作集、Embedding 与端到端 p50/p95。

### 当前状态与完成证据（以上“未完成”段落是早期执行快照）

- T16a、T15b/c、T16b/c、T05：本地实现与对应集成验收已完成。固定 BGE 契约、Alembic 空库/非空增量/重复升级、缺扩展失败保持原 schema/数据、错误 schema 拒绝启动、PG API/五 Agent/组合/Source SSE、并发追加/重复文件/删除竞争/TTL/提交确认丢失/写入中途回滚均有实际验证。连接池耗尽/断连与原有回归保留。
- T15d、T16d：本地数据工具与迁移验收完成。7 会话/51 Chunk 原数据只读快照、导入、重新编码逐向量对账、重复导入、反向完整导出通过；合成新增聊天/用量/删除及 BGE 恢复检索测试通过。只允许可信本地快照，旧数据保留。同 profile 且可无损 reconstruct 的 BGE 恢复制品可复用向量；未知 profile 从正文重编码。T15f 的整应用容器恢复仍单独阻塞，不以工具测试替代。
- 本地应用 Uvicorn HTTP health/create/read/delete 冒烟通过，操作仅新建测试会话。启动脚本 `scripts/run_local_postgres.ps1` 指向独立 pdf_agent_local 并强制关闭 TTL；用户 .env 未改。
- 当前完整 unittest：122 项，119 通过、3 个本地 PDF/付费 opt-in 跳过；此后增加的提交确认丢失测试及恢复/快照相关 3 项复验通过。完整日志 `.evaluation-local/pgvector-acceptance-tests.log`。routing passed=true；前端 6/6 与 tsc/Vite build 通过；Compose config/actionlint/git diff --check 通过。未运行远程 CI。
- T16e：真实3PDF、30条检索评估已保存JSON；90条引文来源校验通过，预期页召回均值0.60666，7个scope。51向量后端数值对照误差<=2.384e-7。1/2/4并发探针通过，最长628ms，峰值工作集2068865024字节（Windows小规模实验，不承诺生产容量）。MiniLM对照正在补齐；无付费生成/Judge，不能宣称语义质量通过。
- T15e 阻塞：Docker Hub auth.docker.io:443 超时，完整应用镜像未构建；本地缓存缺所需基础镜像，旧PDF-Agent镜像不能替代验证。新PG Compose及独立CI job已写入，actionlint通过，远程CI未执行。解除条件是Docker能够访问镜像仓库后重新build并完成容器冒烟/重启。
- T15f 阻塞：依赖T15e新应用镜像。数据级恢复已通过，但Linux整应用恢复尚未执行。
- T16f 阻塞：依赖T15f。API/原型/真实评估活动路径已使用pgvector；普通依赖暂留FAISS，未完成独立迁移依赖拆分和无FAISS镜像验证，不能标完成。
- 本轮不做Render配置/上线，不做T06/T07，不提交或推送Git；已保留原SQLite逻辑行与两套FAISS索引哈希。

### 本地验收收尾（2026-11-16）

- T16e 非付费本地验收完成：MiniLM/FAISS 与 BGE/pgvector 使用同三份PDF/30问题，预期页召回均值分别0.51777/0.60666；7提高、4下降、19不变。四项下降保留为质量风险，不改top-k/Agent策略、不宣称语义质量通过；标注仍provisional。报告分别是 `.evaluation-local/legacy-minilm-retrieval.json`、`pgvector-real-pdf.json` 和 `model-retrieval-comparison.json`。
- 本地数据库容器重启后，7会话重新编码逐向量/关系对账通过；原始SQLite行和FAISS文件哈希不变。Source真实PG零LLM，其他Agent/组合使用明确模拟供应商，不能当付费模型实测。
- 剩余授权任务全部依赖完整新Docker镜像：T15e网络阻塞、T15f整应用恢复阻塞、T16f依赖移除/无FAISS镜像阻塞。普通依赖保留FAISS，尚未完成完整本地交付，不推进Render或Git发布。解除Docker Hub可达性后继续现有任务，不重复迁移历史数据。

- 最终完整回归：123 项，120 通过、3 个明确 opt-in 跳过，日志 `.evaluation-local/pgvector-acceptance-tests-final.log`。按照用户确认，TTL 未设置时也默认关闭（显式 true 才启用），防止绕过启动脚本意外启用历史清理；该改动后的 PG 存储套件单独复验。原工作区既有 Graph/隐私/观测改动保留，没有自动提交/推送。

- TTL 默认关闭后的最终 PG 存储回归：19/19 通过，日志 `.evaluation-local/pgvector-retention-final.log`。历史库原逻辑行与索引哈希已核验，私有密码/快照/报告路径均被 Git 忽略。

- Docker 重启后复验（2026-11-16）：再次执行 `docker --host npipe:////./pipe/docker_engine build -t pdf-agent:pgvector-local .`，引擎正常接收构建，但在解析 `docker/dockerfile:1` 时获取 Docker Hub 匿名 token 再次连接超时（auth.docker.io:443），退出码 1。尚未进入应用构建，无新镜像/容器验收结果。T15e/T15f/T16f 继续阻塞；日志 `.evaluation-local/docker-pgvector-retry.log`。本轮仅补充验证记录，未修改业务代码、数据库或发布配置。

- 再次按用户要求重建（2026-11-16）：`docker build -t pdf-agent:pgvector-local .` 退出码1，仍在docker/dockerfile:1阶段连接auth.docker.io:443超时；没有生成新镜像。日志 `.evaluation-local/docker-pgvector-rebuild.log`，T15e阻塞状态不变。

- 新镜像复验（2026-11-16，Docker Engine 29.9.3）：原 Dockerfile 构建退出 1，在 `docker/dockerfile:1` 获取匿名 token 时连接 `auth.docker.io:443` 超时。使用忽略目录中的临时副本调用 BuildKit 内置语法后，可进入 `node:22-bookworm-slim` / `python:3.11-slim` 元数据解析，但两个基础镜像也因同一鉴权端点超时而阻塞，退出 1。未生成镜像，无法执行容器健康检查。T15e/T15f/T16f 状态不变。日志 `.evaluation-local/docker-pgvector-latest-retry.log`、`.evaluation-local/docker-pgvector-builtin-retry.log`；仓库 Dockerfile 未改。

- 用户已构建 pdf-agent:latest，恢复 T15e 本地验收；使用独立验收项目和新卷，保留历史环境。

- Docker 恢复验证：新镜像与 pgvector 源码哈希一致；独立 Compose 的 PostgreSQL 17.12 / pgvector 0.8.7 / Alembic 0002_vectors 已健康启动。真实 11 页 PDF 写入 39 条向量，Source JSON/SSE 与回滚读回 4 条消息通过。镜像的 pypdf 7.1.0 在证据引文校验中失败，固定已验证的 6.16.2，继续复验无 FAISS 制品。

- 2026-11-16 本地验收：PostgreSQL 17.12、pgvector 0.8.7、Alembic 0002_vectors，升级重跑退出 0；DB/API 重启后保持健康且已写入文档、向量和 4 条聊天消息保留。Linux 容器内对实际上传生成的 39 条 1024 维向量导出 BGE 兼容快照，恢复读回 4 条消息、3 条同会话引用。TTL 关闭时过期夹具保留，显式开启后仅清理该夹具及其文档、向量和消息，接口返回 404。没有使用历史库或旧卷。
- 隔离 Docker DB 完整后端 123 项：120 通过、3 个 opt-in 跳过（docker-accept-host-stable.log）；前端 6/6，两个 Compose 静态校验与 CI YAML 结构检查通过。主机端真实 PDF 检索 30 条、证据引文 90 条、页召回均值 60.7%（docker-accept-host-rag.json），未执行付费生成/Judge。T15e 仅完成本地范围，Render 配置核验/远程 CI 未执行。T16f 无 FAISS 镜像与容器 RAG 仍在复验。

- 正式无 FAISS 镜像已构建：pdf-agent:pgvector-local（配置摘要前缀 b0c68a4bc3b1），以非 root 运行，pypdf 6.16.2，镜像无法导入 FAISS；实际 BGE-M3 离线加载、PDF 11 页/39 向量、Source JSON/SSE、会话隔离、重启持久化、TTL 级联及 Routing 9 条通过。Linux 无 FAISS 全量后端 123 项，119 通过、4 个 opt-in 跳过。容器批量 RAG 首次因默认线程数下耗时过长主动中止，复验仅为评估进程设 OMP/MKL=2；尚待最终检索报告。

- T16f 最终验收通过：无 FAISS Linux 镜像内 3 份 PDF / 30 条检索 / 90 条证据引文，校验通过，平均预期页召回 0.606663，逐题召回与宿主机完全一致。容器评估使用 2 个推理线程，向量范围构建约 236 秒；仅检索，没有生成/Judge。报告 .evaluation-local/container-rag/real-pdf.json。三文档 PDF/pgvector 专项用例单独通过；前端 6/6，Docker 前端构建阶段成功（缓存）。报告、日志和凭据均在 Git 忽略目录。
- 最终隔离环境：API 和 PostgreSQL healthy；一次性 Alembic 容器退出 0；验收库会话、文档、向量、消息计数均为 0（只清理本轮夹具）。默认 Compose 已要求显式提供已迁移的 DATABASE_URL，避免缺配置时进入重启循环；隔离 Compose 的端口可独立配置。历史库/快照和 Render 未操作。
