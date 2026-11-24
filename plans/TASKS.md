# 改造任务清单

更新时间：2026-11-25（Asia/Shanghai，GitHub 与 Render 分阶段发布）。项目任务状态的唯一事实来源；长期方向与里程碑见 [ROADMAP.md](ROADMAP.md)，当前实现见 [ARCHITECTURE.md](../docs/ARCHITECTURE.md)。需求分级、自动维护门禁及确认边界统一见 [AGENTS.md](../AGENTS.md#连续任务执行模式)。

## 当前入口（2026-11-24）

[工程审计](AUDIT_2026-11-24.md)包含P0–P3、代码行号、风险、方案、依赖与验收。本文件保留各轮历史过程与验收记录；“仍是SQLite”等及过往待办结论只代表对应轮次快照，不覆盖当前条目与下方执行队列。

- T05、T15a–f 本地范围、T16a–f 已实现；审计轮独立PG库曾验证123项120通过/3跳过，不重复迁移；最近完整验收见下方阶段记录。
- T15e本地完成与Render残项分开，残项为T15e2；T15g生产切换未实施。
- T01、T03 与 T09a 已完成本地验收。此前授权的 T06 → T07 → T05a → T09b 已完成本地验收及逐项本地提交。本轮 T04 → T02b 按批准顺序完成本地验收。
- 审计轮只交付规划；随后各项验收见末尾独立实施记录。T09a与T09b均已独立验收，本次据其证据同步T09父项；先前风险及未执行验证保留，不将工程边界验收当作语义质量或生产验证。

<a id="current-execution"></a>
## 当前执行队列与阶段验收（2026-11-25）

- 本轮授权覆盖 GitHub `main` 常规推送、T15e2 非破坏性线上盘点与隔离验证，以及经确认后的 T15g 手动部署。维持 Render Auto Deploy 与 Blueprint Auto Sync 关闭。仅停用已识别的旧 Streamlit push Webhook。生产配置、实例资源、迁移与备份/恢复方案及费用须先确认。新收费资源、套餐升级、真实生产数据迁移及破坏性操作须明确批准；保留全部历史数据，不调用未经授权的付费 LLM。本轮不启动 T08、T10 或无关优化。

| 顺序 | 状态 | 验收及继续条件 |
| --- | --- | --- |
| 1. GitHub 发布 | 阻塞（BLOCKED） | 只读查询确认旧 Streamlit `push` Hook 仍为 Active。GitHub 编辑页要求用户完成 Confirm access，Streamlit 应用管理另需登录。先仅停用并读回该 Hook，再核对旧应用与 `main` 的绑定及其他自动更新入口。若仍有更新渠道，记录证据并暂停。门禁通过后复核发布差异、工作区和远端快进关系，正常推送并验证远端 HEAD 与 CI。 |
| 2. T15e2 Render 部署准备 | 未启动，等待阶段 1 | 盘点服务、Blueprint、环境变量配置（仅记录必要的非秘密信息）、磁盘、实例、数据库及扩展/Schema，确认实际线上版本和历史数据。基于隔离实测记录 BGE-M3 冷启动、峰值内存、CPU、镜像/磁盘及数据库容量余量。复核 T11、T12、T15d1 等既有验收门槛，交付有证据的候选配置、备份恢复与回滚方案、维护窗口和增量月费。 |
| 3. T15g 生产部署 | 未启动，等待阶段 1、2 及生产方案确认 | 仅在前置验收满足且生产配置、资源、迁移及费用获确认后实施。备份并保护生产数据，按实际来源迁移至 PostgreSQL/pgvector，显式执行并验证 Alembic `0004_session_credentials`，核对会话、文档、消息和向量。手动部署已验收的 GitHub 提交，验证健康、会话认证、上传、BGE-M3 检索、JSON/SSE、重启持久化及日志/资源，失败按已批准方案回滚。 |

- 阶段 1 证据：本轮起点 `ef8eef009288697686c090447cfc2f72a14c0310`，工作区与暂存区干净。本地领先 10 个提交。Git 传输的只读探测遭连接重置，随后经认证的 GitHub API 确认远端 `main` 为 `370bb47856f7e4518f789e4cc95274133db9bd53`，本地验证其为祖先。该远端提交最近一轮 CI 已成功，本地候选尚无发布 CI。Hook 已确认仍启用且配置了签名。Render 服务 Auto Deploy 读回为关闭，关联 Blueprint Auto Sync 为 `false`、状态为 `paused`。本轮尚未修改远端设置、推送或部署。
- 沿用前轮完整本地验收，运行代码基线为 `cad5d6c`。该基线后的改动仅为文档，未重跑全量测试或 Docker 构建。生产容量、数据及 Schema 现况、生产迁移、费用和运行验收待对应阶段完成。

### 上轮发布门禁复核（2026-11-25，历史记录）

- 发布复核启动：本地 `main` 为 `cb90f51242dc35ff1788b0b09c33269a90cdb843`，工作区和暂存区干净，基于此前已验收的运行代码。用户接受本地验收，允许仅停用已识别的 Streamlit push Webhook，以及在存在关联且开启自动同步时仅关闭 Render Blueprint Auto Sync。授权包含必要的 TASKS 独立提交和所有门禁通过后的正常推送。其他仓库集成保持原设置，部署、资源创建或删除、生产数据库与后续开发均在范围外。
- 执行顺序：先处理唯一匹配的旧 Webhook，复核 Streamlit 更新渠道、GitHub Actions 与 Render 发布设置，再执行远端和提交复核。GitHub 要求手动重新认证，期间完成不依赖该认证的 Render 门禁。前轮本地验收继续有效，仅进行发布与文档核对。

| 门禁 | 当前状态 | 证据及恢复条件 |
| --- | --- | --- |
| Render | 已完成（DONE） | 已确认服务 Auto Deploy 为 Off，关联 Blueprint 的 Auto Sync 已关闭并读回确认。 |
| Streamlit 更新渠道与 GitHub 发布 | 阻塞（BLOCKED） | 目标 Webhook 仍开启，编辑前须由用户完成 GitHub Confirm access。Streamlit 管理页要求登录，GitHub CLI 也无法枚举 GitHub App 安装。推送暂停，等待停用后读回并确认其他更新入口。 |

- Webhook 证据：GitHub REST 确认唯一启用的仓库 Webhook 为指向旧 Streamlit 的 `push` 订阅，签名密钥已配置并遮蔽。REST 更新契约对签名保留有警告。Chrome 已打开 GitHub 官方编辑路径，但停在 Confirm access，未提交任何 Webhook 更新。需在仓库 Settings → Webhooks 编辑该 Hook，仅取消 Active 并保存，保留签名、订阅和其他集成。登录 Streamlit Community Cloud 的对应工作区，核对旧应用来源及其他自动更新入口，必要时从仓库 Settings → GitHub Apps 核对绑定。禁用仓库 Hook 前后都须确认未有其他未经授权的自动更新渠道。
- Render 变更与验收：确认 `pdf-agent` 服务 Auto Deploy Off，无 pre-deploy 命令。关联 Blueprint 指向本仓库 `main` 的 `render.yaml`，Auto Sync 原为开启。仅修改 `autoSync: false`，响应无同步计划或同步，独立读回为 Off、`paused`，仓库、分支和路径一致。服务 Auto Deploy 仍为 Off。最新部署记录为此前 2026-10-19 的 `live`，未触发部署。
- Git 与 CI 核查：远端 `main` 仍为 `370bb47856f7e4518f789e4cc95274133db9bd53`，是本地的祖先。活动 Actions 只有 CI，最近已完成的远端 CI 为该旧提交的 `success`。未推送，故未触发当前提交的 CI。确认收尾基线后的差异仅为 TASKS，保留既有业务验收，无需重跑全量测试或镜像构建。门禁恢复后再确认目标 Hook、剩余自动更新渠道、远端及待推送范围，随后正常推送并读回两边 HEAD 与 CI。

### 前轮最终收尾与验收（2026-11-24，历史记录）

- 收尾基线：`cad5d6c`，启动时 main 和暂存区干净。GitHub `origin/main` 只读查询为 `370bb47856f7e4518f789e4cc95274133db9bd53`，本地领先 8 项提交。
- 已授权范围：核对并同步文档、清理已确认无用的本轮临时文件、本地回归和 Docker 镜像验收、隔离 PG 迁移及独立收尾提交。通过全部验收、待推送历史检查及远程触发核查后才可正常推送。未授权生产部署、历史库升级、生产迁移或付费模型。T08、T10 和其他待办不启动。

| 执行项 | 当前状态 | 验收和依赖 |
| --- | --- | --- |
| 阶段收尾与验收（沿用原条目，不新增开发编号） | 已完成（DONE） | 实现、提交与历史证据复核，双语 README 和维护文档同步，主机与重建镜像均通过本地验收。收尾独立本地提交包含本记录。 |
| GitHub 发布 | 阻塞（BLOCKED） | 已确认仓库存在启用的 `push` Webhook，目标为 Streamlit 社区云。Render 服务自动部署已关闭，Blueprint 级同步未核实。暂停推送。 |

- 发布核查：用 Git 已保存的认证完成 GitHub 只读查询。默认分支为 `main`，活跃工作流只有 CI。Webhook 列表中有一个启用的 `push` 订阅，目标主机为 `share.streamlit.io`，故自动更新风险未解除。未调用 Hook 或修改设置。经用户确认工作区后，Render 实际 `pdf-agent` 服务的 `main` 自动部署为 `off`，无 pre-deploy 命令。服务读取结果缺少 Blueprint 标识，Dashboard 连接超时，Blueprint 级同步仍未核实。已核对推送范围无 `render.yaml` 变更。解除条件为核实或经单独授权处理触发设置，再复核远程及发布验收。
- 镜像重建：用 `cad5d6c` 的 Git 归档构建。直接 Docker Hub 和内置解析器重试都遇到鉴权连接超时。临时构建参数使用 Google 公共缓存，Dockerfile 前端、Node、Python 的 linux/amd64 摘要逐一与 Docker Hub 核对一致。原 Dockerfile 完成依赖安装、前端构建和固定 BGE-M3 缓存，镜像 `pdf-agent:final-cad5d6c`，ID `sha256:f3ac0f70d37a6b838cab509566ec4aa24719f4b1b7e28a8b5f8d4c00f2ec6b30`。仓库 Dockerfile 和全局设置未改。缓存运行层的备用冒烟另行通过，最终验收以重新构建的镜像为准。收尾提交只有文档差异，运行源码与该镜像相同。
- 本阶段提交归属：本地存储迁移及恢复基线（T05、T15a–f、T16a–f）见 `cf75fa3` 和既有验收记录，异常最少披露 T02a 见 `39ea80c`。待发布的 8 个提交依次为 `f348fa4`（T01/T03/T09a）、`6cf2e0c`（T06）、`8f1155f`（T07）、`c70912a`（T05a）、`64d8acc`（T09b）、`bce5b4e`（协作规范）、`d9a7a53`（T04）和 `cad5d6c`（T02b）。已核对代码入口、公开契约、历史证据及未完成的任务边界。
- 本轮主机验收：Python 3.11 的默认离线全量 `python -B -m unittest discover -s tests -t . -v` 共 245 项，200 通过、45 跳过。开启隔离 PostgreSQL/pgvector 和旧存储恢复 opt-in 后共 245 项，242 通过、3 跳过（真实 PDF 及两个付费 opt-in）。初次用内部网络发布端口导致连接超时，改用新的仅回环临时库后通过。前端 `npm test` 20/20，`npm run build` 通过。Routing 9/9、受控 Source 1/1，均零 LLM。
- 本轮镜像验收：在无外网的内部 Docker 网络和新 PG17/pgvector 数据库中显式 `python -m alembic upgrade head`，数据库 revision 确认为 `0004_session_credentials`。应用以 UID 10001 启动，Docker 健康检查和首页通过。实测 Cookie 属性和 Origin、Bearer、跨会话拒绝、合成 PDF 上传和真实 BGE-M3 编码、Source JSON/SSE 引用和保存。重启后凭据、PDF、已保存的四条消息和向量检索可用。全程零 LLM。HTTP 日志扫描未见合成文件名、正文或原始访问记录。镜像中未见 `.env`、私有 PDF、数据库或测试产物。
- Git 与清理：逐提交检查待发布历史中的变更路径、Git blob、提交说明及收尾差异。一个命中经核实是回环测试库的编码密码夹具。未发现真实凭据、私有 PDF、数据库或测试产物。CI 引用的 Action 标签可解析，远端旧 `370bb47` 的 CI 为成功，本轮因未推送而无新运行。停止并清理本轮测试容器、网络和备用镜像，删除本轮临时构建上下文，保留最终镜像及已忽略的本地验收日志。历史数据、有效测试和恢复制品未清理。
- 收尾与风险：本轮仅改动双语 README、开发和架构说明、TASKS 与 ROADMAP。真实 PDF 语义验收、付费生成/Judge、公开 HTTPS 网关日志、生产备份与迁移仍未执行。新解析依赖产生 BGE 方法弃用提示，镜像通过本地验收，依赖锁定留给 T11。发布继续阻塞，须先处理或排除 Streamlit Webhook 影响并核实 Blueprint 同步，再核对远程分支与 CI。T10/T08、T11/T12、T15e2/T15g 等任务保留原状态，阶段到此停止。

## T04 → T02b 执行队列与阶段验收（2026-11-24，历史记录）

- 设计基线：`bce5b4e28ec3be5b5bd5ac5a6627171ff2737d65`，`main` 相对 `origin/main` 领先 6 个本地提交，开始时工作区与暂存区干净。恢复 AGENTS、TASKS、ROADMAP 与架构、开发、测试上下文，核对 HTTP/POST SSE、前端存储、PostgreSQL 生命周期和日志封装。
- 实施基线：HEAD 同上，main 领先 6 提交，现有工作区仅包含上轮未提交的 TASKS 设计，暂存区干净。用户批准方案 A，按 T04 → T02b 连续实施和验收，各自独立本地提交。
- 已批范围：Cookie / Bearer、32 字节随机值、SHA-256 摘要、24 小时绝对有效期、统一 404、严格 Origin、本地和生产均使用安全 Cookie、兼容切换、隔离 PG 增量迁移、旧浏览器问答及会话键清理、日志脱敏。保持现有数据保留和服务端历史。在线共享不实施，复用已有复制功能即可。授权覆盖已设计的 HTTP/Cookie/前端调整。生产访问、历史数据库升级、推送、部署和真实付费验证均在范围外。

| 执行项 | 当前状态 | 顺序与解除条件 |
| --- | --- | --- |
| [T04](#t04) 会话访问与凭据边界 | 已完成（DONE） | 凭据边界、增量 Schema、浏览器 HTTPS 接入及本地验收通过，本地提交 `d9a7a53d69a311dcadc53c83c2a760466261fe85`。 |
| [T02b](#t02b) 日志与浏览器隐私 | 已完成（DONE） | 浏览器最少持久化、日志和评估错误脱敏通过本地验收。T02b 独立本地提交包含本记录。 |

- 实施分解与验收：[联合方案](#t04-t02b-design)；T04 先用合成请求覆盖签发、五路拒绝、Origin、并发和协议，再完成凭据存储和同源 HTTPS 前端；T02b 补上旧浏览器键清理、最少存储和安全日志，使用合成标记验收。前轮文档验收已核对变更链接、状态与基线，本轮重新执行与代码相关的验证。
- 阶段收尾：隔离 PG/恢复全量 245 项，242 通过、3 跳过；默认离线全量 245 项，200 通过、45 跳过。前端 20/20，完整构建通过。routing 9/9、受控 Source 1/1，零 LLM。实际 Chrome、Uvicorn 和本地 Vite 代理验收通过。无授权范围内剩余项，本轮停于 T02b 独立本地提交。公开网关、生产、历史库升级、付费接口和 Docker 应用镜像构建未执行。

## 上一轮执行队列与阶段验收（2026-11-24，历史记录）

- 开发基线：已完成开发阶段从 `f348fa4da4469a560326364b57915624827fbfa0` 开始；本次规范维护基于 `64d8acc1a09e5ac8be35ecefa82c89309bb178e2`，开始时工作区与暂存区干净。
- 原授权顺序与依赖：T06 → T07 → T05a → T09b，各项验收后独立本地提交。T06依赖T09a和已有T05持久化契约；T07依赖T06；T05a协调T03截止；T09b依赖T03/T06且按用户指定顺序最后执行。
- 已批准方案：T06方案A增量JSON/SSE execution及必要节点快照、T07对应前端适配；原字段、事件名和progress状态枚举保留。该批准无需重复索取，也不扩展为其他协议或业务变更授权。

| 执行项 | 当前状态 | 已核实本地提交/范围 |
| --- | --- | --- |
| T06 | 已完成（DONE） | `6cf2e0cd278f2f92afa467246481521259b9123d` |
| T07 | 已完成（DONE） | `8f1155f415a6b8dc5fa557bcd8b67567d77817fb` |
| T05a | 已完成（DONE） | `c70912af3ac56bfce48b3415ee7d4cf5a19daa53` |
| T09b | 已完成（DONE） | `64d8acc1a09e5ac8be35ecefa82c89309bb178e2` |
| 本次规范维护（简单文档增量，不新增任务编号） | 已完成（DONE） | 仅AGENTS门禁、当前TASKS记录及必要ROADMAP进度澄清；不启动T13a其余范围 |

- 开发阶段验收：已核对Git提交及原日志，最终隔离PG/恢复回归236项233通过/3跳过，默认离线236项194通过/42跳过；前端19/19与完整tsc/Vite构建、routing9/9、受控Source1/1零LLM。详细命令、环境及风险保留在各项实施记录；本次纯文档维护不把这些结果写成新跑测试。
- 未验证/剩余风险：真实付费模型/长对话语义、浏览器挂载E2E、生产负载、远程CI、镜像部署未执行；上游即时取消、独立SQL池等待及有限Memory窗口的限制不变。`0003_request_leases`只在隔离测试库升级，历史本地/生产库未操作，新代码使用旧库前须显式迁移。
- 本次授权与确认边界：只完善规范并同步现状；原开发队列已经结束，没有未完成的已授权业务项可继续。T04/T02b及其他待办保持未授权，不因ROADMAP建议自动启动；付费调用、生产访问、破坏性数据库操作、未批准协议/架构变更、push与部署仍按AGENTS确认边界办理。
- Git授权：规范维护验收时未将原开发队列的commit授权扩展到文档提交；用户随后接受本轮结果，明确批准仅将AGENTS.md、TASKS.md、ROADMAP.md本地提交，说明为 `docs: enforce persistent task lifecycle and development workflow`。本次据此收尾，不启动新任务、不push或部署。
- 本次规范维护验收：重复/冲突审阅、全部相对链接及锚点、四项提交顺序/归属、父子任务状态和`git diff --check`均通过；原“需要确认的变更”条文保持不变。只修改AGENTS.md、TASKS.md、ROADMAP.md三份已有文档，未新增文件或修改业务代码；验收时尚未暂存/提交，随后按上述明确授权一并本地提交，最终哈希与工作区状态以Git及交付记录为准。既有测试仅核对原日志，没有重跑或冒充本轮实测。当前已授权队列无剩余项，阶段结束；未授权待办保持原状态。

## 任务记录约定

- 自动维护时机、代码修改前置门禁、批准恢复、验收提交与连续推进统一见 [AGENTS.md](../AGENTS.md#连续任务执行模式)；本节仅维护记录字段与状态含义，不另设执行流程。
- 任务条目字段：沿用编号/标题、优先级、状态、需求或代码依据、实施范围、依赖（没有则写“无”）、本轮验收标准与验证方式；有待决方案、批准内容或兼容风险时记录适用范围及保留边界。
- 阶段记录字段：基线与既有改动、执行队列/顺序、授权与批准、当前依赖、验收证据、未验证/剩余风险、提交或未提交情况及停止/恢复条件。简单增量可不新建任务卡，仍更新本轮记录并关联已有条目。
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
### T01 · P1 · 已完成（DONE）：输入与资源限制

- 范围：`app/schemas/requests.py`、`app/api/routes.py`、`app/services/pdf_service.py`；配置化问题长度、文件数/字节/页/chunk 限额，文件有效性校验；让耗时同步解析/索引不直接阻塞 async 路由，并约束并发。明确多文件部分成功语义。
- 验收：无效/超限输入不进入后续高成本阶段；正常多 PDF 兼容；失败清理临时资源，返回稳定安全的错误。阈值以实际样本确定，不编造容量。
- 回归：边界值、伪后缀/损坏/空 PDF、重复名、后续文件失败、并发负载下健康接口响应；现有会话/路由测试。
- 实施与验收：2026-11-24，见本文末尾 T01 记录；配置与限制只维护在 [.env.example](../.env.example) 和 [开发文档](../docs/DEVELOPMENT.md#input-limits)。

<a id="t02"></a>
### T02 · P1 · 已完成（DONE）：错误与日志最少披露

- 范围：`utils/observability.py`、`utils/llm_client.py`、API/Agent 错误出口；处理原始异常、文件路径、会话标识在日志与响应中的披露，评估访问日志和浏览器持久化内容。
- 验收：用合成敏感字符串验证客户端/常规日志不泄露 Key、PDF 正文或内部路径；会话标识采用明确策略；仍能用 request_id 关联错误类型和耗时。
- 回归：上游错误、解析错误、存储错误、日志关联与现有 usage；不得把屏蔽所有错误当作脱敏。
- 父项收尾：T02a、T02b 均完成各自的本地验收。网关、生产错误收集和历史日志保留另待验证。

<a id="t02a"></a>
#### T02a · P1 · 已完成：异常正文披露

- 范围：上述四个 Agent/LLM 异常出口、JsonFormatter 异常字段，以及 `tests/test_error_privacy.py`。采用固定失败提示；格式化异常保留类型、模块/函数/行号和原因链，不输出异常正文、绝对路径、源码行或 locals；新增失败事件只写类型/步骤等元数据，避免未配置 JSON formatter 的 CLI 输出原始堆栈。保留 request_id 关联及失败用量。
- 验收：合成敏感异常不进入 JSON/SSE、保存的回答/协作建议和结构化异常日志；保留协议字段、成功行为、失败的已知/未知用量和诊断关联。
- 修改前验证：最初 11 个子场景失败中，有 2 个是测试误把既有 QA“模型不可用”回退当作 Specialist 失败；修正该断言，保留原业务回退。将最终测试在内存中加载的原始 HEAD 五个模块上重放，确认 9 个真实披露失败场景，未回写源码。仅使用合成标记和 mock，记录在已忽略的 `.evaluation-local/engineering-t02a-baseline-replay.log`。
- 修改后验证（2026-11-16）：完整 `python -B -m unittest discover -s tests -v` 共 75 项，72 通过、3 个原有 opt-in 跳过；新增 6 项回归全部通过。基线为 69 项/66 通过/3 跳过，无新增失败。日志 `.evaluation-local/engineering-t02a-tests.log`。
- 评估/构建：routing 9/9 与基线一致；controlled live 的 source-citations 1/1，通过 route/source/citation 阈值，两者均零 LLM 调用；报告为 `.evaluation-local/engineering-t02a-routing.json`、`engineering-t02a-source.json`。本轮前端 npm test 6/6、完整 build/tsc 已通过，前端未修改故复用该结果；Git diff 空白检查通过。无已配置的 Python lint/type-check 命令，不虚构此类结果。
- 边界：未运行付费、真实 PDF 集成或真实部署；Docker 引擎不可用，镜像构建未执行。异常正文被省略后诊断信息减少，但保留类型/代码位置/请求关联；API/SSE 字段及正常回答不变。T06 的失败终态、其他日志内容及 T02b 隐私策略未修复；本轮未提交/推送，整个 T02 不标完成。

<a id="t02b"></a>
#### T02b · P1 · 已完成（DONE）：会话标识与其他日志/浏览器隐私

- 范围：原始 session_id/请求路径、Uvicorn 访问日志、其他日志 message/structured_fields、本地评估报告异常文本、浏览器 localStorage 与保留策略。T02a 不提供任意字符串 DLP，也不更改业务证据/用户正文；普通第三方日志消息或未使用 JsonFormatter 的既有日志处理器需另行审查。
- 验收：明确会话凭据与日志标识策略，合成数据验证日志和前端存储边界，同时保留 request_id 排障和当前 API 兼容性。与 T04 的访问方案协调。
- 回归：访问日志、请求路径、跨会话、浏览器恢复/清理、异常与 usage。
- 2026-11-24 开始：T04 验收已完成并本地提交。浏览器仅保留活动定位和语言，移除旧应用键；不另做分享 UI。HTTP/应用日志仅保留允许的诊断字段，关闭原始 Uvicorn 记录并安全处理开发代理错误。评估报告异常字段仅保留类型。合成标记、浏览器及离线全量回归为本轮验收。
- 2026-11-24 验收：前端清理旧应用会话/问答键，凭证由 HttpOnly Cookie 承担，Web Storage 只写活动定位与语言。浏览器刷新仍可恢复文档和服务端上下文，可见回合只留页面内存。日志保留服务端请求 ID、路由模板、耗时、受控原因、异常类型及用量，关闭 Uvicorn 原始访问日志，Vite 代理仅写固定错误，评估 Agent/Judge 异常字段仅记类型。
- 验证：默认离线与隔离 PG/恢复分别运行 `python -B -m unittest discover -s tests -t . -q`，结果见当前队列。隔离套件的 3 个跳过来自未启用的真实 PDF、真实付费 API 和供应商缓存探针，默认套件另跳过隔离存储 opt-in。 `npm test` 20/20，`npm run build` 通过。Chrome 在本地同源 HTTPS 验证旧键清理、保留其他键、合成问答/引用只留内存和刷新后清空。默认 Uvicorn 启动及断开上游的 Vite 实际输出经合成凭据、摘要、路径、请求头、正文扫描通过。报告和错误注入走本地合成数据与假客户端。
- 剩余边界：Cookie/凭据丢失或到期时匿名会话不可找回，数据仍遵循原保留策略。已生成评估报告中的显式分析材料与历史访问日志仍需按敏感数据管理。上游网关、生产日志、真实模型和容器应用镜像未验证；没有自动清理服务端历史或扩大共享功能。

<a id="t03"></a>
### T03 · P1 · 已完成（DONE）：工作流预算与付费防护

- 范围：`utils/llm_client.py`、Memory、Graph/服务层及 `evaluation/runner.py`；明确 SDK 重试与整体调用/Token/耗时预算，统一 live/real-pdf/Judge 的付费选择语义。
- 验收：预算耗尽不再发起新调用，保留已发生用量/未知成本；重试有界；默认测试与未授权 CLI 不调用供应商。保留 Source/Planner/Reviewer 快路径和报告兼容性，说明新 CLI 约束。
- 回归：超时、重试、预算边界、Judge 失败、模型别名、usage 隔离；使用 mock 验证调用次数，不依赖付费测失败。
- 实施与验收：2026-11-24，见末尾T03记录；配置与预留/实际用量、I/O截止限制见[开发文档](../docs/DEVELOPMENT.md#llm-budgets)。不将其视为硬墙钟、真实账单或跨请求费用上限。

<a id="t04"></a>
### T04 · P1 · 已完成（DONE）：会话访问与凭据边界（旧索引仅离线工具）

- 范围：会话 API、必要前端凭据传递；先明确公开匿名 demo 的访问方案与旧会话兼容策略，再实施最小保护。旧索引路径仅属于离线迁移工具边界，不再作为活动 RAG 路径；工具校验另见 T15d1。
- 验收：访问和删除遵循确认后的凭据契约，拒绝不匹配的访问；持久化路径在可信根内；不反序列化外来索引。不默认建立完整账号系统，不把 CORS 或 UUID 难猜当所有权验证。
- 回归：合法旧/新客户端、无效凭据、路径边界、删除和恢复；使用隔离测试数据。
- 2026-11-24 批准并启动：依赖已有 PostgreSQL / pgvector、T01、T05a、T06、T07。按[联合方案](#t04-t02b-design)签发、验证和迁移，旧 ID 无法换领。验收使用 HTTP/离线测试、非空隔离 PG 和本地 HTTPS 浏览器。
- 2026-11-24 验收：新增 `0004_session_credentials`，Cookie/Bearer 共用正文前鉴权，存储事务复核时效和会话存活。Vite 使用同源 HTTPS 代理，本地采用专用证书，保留生产 Cookie 标志。前端明确显示恢复 404 和旧会话删除未确认。匿名凭据存续与既有数据保留独立。
- 验证：独立回环 PG17/pgvector，开启 PostgreSQL 与 Legacy Recovery 两个 opt-in，`python -B -m unittest discover -s tests -t . -q` 243 项 240 通过、3 项跳过（真实 PDF 与供应商探针等 opt-in）。覆盖非空 0003 升级、旧会话拒绝、Cookie 路径与 Origin、Bearer 摘要/到期、跨会话、正文前拒绝、在途删除复核及 Source JSON/SSE。前端 `npm test` 19/19、`npm run build` 通过。routing 9/9、controlled Source 1/1，均零 LLM。Chrome 通过本地 Vite HTTPS 验证两标签、刷新、切换、旧 Cookie 清除、浏览器重开以及凭据丢失提示。使用测试进程专用证书和 Chrome 隔离配置。
- 本轮已修复验收发现的历史 TTL 取样回归与移动视口提示不可见。迁移仅在专用测试库执行，风险仍包括匿名凭据丢失后无法找回、过期数据沿用原保留策略、匿名新建资源消耗与在途上游不能保证立即停止。生产网关、付费调用、真实历史库和公开部署未验证。
- 阶段补充验收：在隔离库的事务内旧 Schema 比较升级前后的会话、消息、文档、chunk 和租约，数据逐表一致，历史凭据表为空。注入无效摘要确认签发失败回滚。Cookie 对应的服务端凭据到期后读删均返回 404，历史行仍存在。

<a id="t04-t02b-design"></a>
#### T04 / T02b 联合设计（方案 A 已批准）

**现状依据。** [会话路由](../app/api/routes.py) 用路径 ID 读取、删除、上传、JSON 问答和 POST SSE；创建只返回 ID。[PG 存储](../app/services/postgres_store.py) 的普通读取会刷新活动时间并取消息、文件名和向量状态，可信内部调用也复用存储原语。当前 [Schema 检查](../app/db/runtime.py) 要求 `0003_request_leases`。生产由 FastAPI 同源托管前端，Vite 开发默认独立端口，[前端 API](../frontend/src/api.ts) 用 fetch 支持 POST SSE。[页面](../frontend/src/App.tsx) 持久化活动 ID 和完整回合、复制 ID，并在恢复 404 时留下旧会话正文。[日志](../utils/observability.py) 记录原始路径、上下文 ID 与自由文本，Uvicorn 访问日志也进入格式化链路。[评估 runner](../evaluation/runner.py) 还将部分异常原文写入本地报告。

**推荐方案与备选。**

| 方案 | 体验与代价 |
| --- | --- |
| A · 每会话随机令牌，浏览器 HttpOnly Cookie，脚本按需 Bearer（推荐） | 同源 Demo 可刷新和重开恢复，JS 无需持有所有者凭据。会话间权限隔离，服务端可删除失效。需管 Cookie、CSRF、前后端切换与一张增量表。 |
| B · 所有客户端用 Bearer，浏览器凭据仅存内存 | header 接入简单，保留跨域前端部署弹性，刷新和关闭后即失去所有者访问。长期保存在 Web Storage 会扩大同源脚本泄露范围。 |
| C · 浏览器 Cookie 加签名自包含令牌 | 省去凭据表，仍须查会话数据，增加签名密钥轮换和逐会话撤销的复杂度。保留当前只凭 ID 的访问方式也无法建立归属校验。 |

**签发、传输与验证。**

- `POST /sessions` 由服务端生成独立于现有 `session_id` 的 32 字节安全随机值，做 Base64url 编码。单事务写会话和凭据后再响应。浏览器继续收到 `session_id`，凭据仅由 `Set-Cookie` 设置，建议采用 host-only 的 `__Secure-pdf-agent-owner`，`HttpOnly; Secure; SameSite=Strict; Path=/sessions/{session_id}`。按路径区分新旧会话 Cookie，删除时以匹配名称和 Path 清除。Path 缩小发送范围，归属仍由库中摘要验证。建议绝对有效期 24 小时，Cookie Max-Age 与服务端截止对齐，普通请求无续签。Cookie 生命周期和 PG 数据 TTL 独立。
- 脚本显式发送 `X-Session-Mode: bearer` 创建会话。该模式一次性在创建响应返回 `session_token` 和 `expires_at`，客户端安全保存并在后续发送 `Authorization: Bearer …`。一次会话只签发一种传输方式，重复、歧义、双渠道及不符合格式的凭据拒绝。普通详情、上传和 JSON/SSE 输出沿用现有字段，SSE 事件名、终态与 usage 保留。创建、会话数据和错误响应使用 `Cache-Control: no-store`，保留 SSE 禁代理缓冲设置。URL、查询参数、文件表单、请求正文和分享剪贴板没有凭据入口。
- 浏览器走同源 fetch。Cookie 路由要求应用自定义请求头，浏览器写操作包括创建和 POST SSE 校验受信配置中的精确 Origin，拒绝外站、`null` 与缺失 Origin 的 Cookie 写请求。无 Origin 的脚本走显式 Bearer。开发建议使用 Vite 同源代理并验证 Cookie 和流式转发。可在本地 HTTPS 保持生产标志，明文回环调试若需要，须使用显式仅回环配置及独立 Cookie 名。现有跨站前端部署地址和无凭据脚本须修改接入。公网使用 TLS，CORS 保留精确来源控制。
- 五个受保护操作共用同一鉴权入口。先用现有 T01 头部/准入限额处理请求，凭据校验在框架解析 JSON、暂存 multipart、读取会话正文、刷新 TTL、获取租约/Embedding/LLM 前完成。通过会话主键查询有界摘要，校验模式和时效并定时安全比较。读取或删除在短事务内确认会话与授权仍有效，保留 T05a 锁、租约与防复活行为。缺失、错误、过期、无凭据的历史会话及不存在的 ID 在身份关卡统一返回固定 404。跨站 Cookie 请求可先统一拒绝 403，准入错误沿用现有状态，DB 故障用安全的临时错误。SSE 在建立流前鉴权，删除或过期阻止后续请求，已开始的上游调用仍受现有取消与预算机制约束。内部可信评估/向量工具继续使用隔离存储入口，HTTP 不暴露绕过路径。

**浏览器、兼容和共享。**

- 首版 `localStorage` 仅保留语言和版本化活动会话定位值，定位值无授权能力。凭据交给浏览器 Cookie 管理，问答/引用/文件名在页面内存。刷新或同浏览器重开可用 ID + Cookie 恢复服务端文档和会话上下文，历史回合 UI 清空，因为现有详情 API 只返回统计与文件列表。前端应说明此体验差异。确需恢复完整可见历史时可后续设计受保护、分页、无缓存的历史接口。
- 使用已有 RequestScope 阻止旧请求提交到新会话，处理同浏览器多标签、持久化异常、Cookie 被阻止/清除和过期。404 清除活动定位值并提示开始新会话。网络、超时、5xx 保留定位值供重试。新建与删除分别报告结果，确认收到 204 才显示服务端已删除。创建后验证 Cookie 可用，再持久化新定位值。
- 旧库记录保留。无凭据旧会话公网拒绝访问，旧 ID 无法换领令牌，旧版本前端或脚本须重新创建会话。用户另行证明归属时可单独批准离线受控恢复。旧 `pdf-agent-session` 与 `pdf-agent-conversation-*` 在升级后停止读取/写回。建议在用户批准的清理范围内首次加载移除旧 keys，保留语言和其他站点存储，失败提示。清理会移除现有浏览器中的问答副本，需要纳入批准。
- 首版沿用现有会话 ID 复制和浏览器文本选择能力。会话 ID 只供识别。需要在线共享时，另批独立、短期、可撤销的随机只读凭据和只读快照，生成前预览明确范围，前端可从 URL fragment 读一次并立即清除，再由 header 兑换读取。该凭据只能读取所选快照，无法恢复、上传、问答或删除源会话。接收方仍可转发链接或保存内容。首版没有跨设备找回或在线共享表/接口。

**数据库迁移与回退。** 在 `0003_request_leases` 后加独立 Alembic revision，新增一对一所有者凭据表。`session_id` 为 PK/FK，随会话级联删除。存固定长度 32 字节 SHA-256 摘要、签发/到期时间和传输方式，增加长度、时间顺序、模式约束。随机令牌具备 256 位熵，服务端不存明文，摘要不参与日志和响应。现有数据及索引无需回填、重建或改写，既有会话无凭据行。同步运行时 revision 检查和迁移回归。升级只在合成数据的隔离 PG 验收，发布若另获授权则先验证备份，停止旧进程流量，显式 migrate，再部署匹配前后端。优先向前修复；回退时先关闭会话入口，旧构建禁止对公网恢复 ID-only 访问。撤销迁移或恢复备份可能使凭据失效、丢失发布后的写入，须单独批准和对账。

**日志与报告。** 用服务端生成并经 `X-Request-ID` 返回的 request_id 关联排障，取消客户端自定义 ID 的原样回显。HTTP 只记固定路由模板、方法、状态和耗时，未匹配路径采用固定标签。应用事件按允许字段输出，保留阶段、受控原因、异常类型/代码位置及 usage；完整 session_id、头/查询/请求正文、凭据与摘要、文件名、PDF 内容和原始异常不落日志。默认使用 request_id，无跨请求会话标识。将来确需跨请求关联时，用独立日志密钥对已验证会话 ID 做截断 HMAC。避免自由字符串、嵌套或第三方日志绕过，关闭 Uvicorn 原始 access log 并由安全事件替代，评估报告的异常字段写受控类型/原因，保留显式评估输出的分析字段和本地保护。网关、代理、错误采集和 SQL 参数独立核验；托管入口若强制记录原始 URI，需解决该入口的日志策略或重新批准 URL 契约后再公开。

**剩余风险。** Cookie 限制 JS 读取凭据，同源 XSS 仍可代发请求及读取页面数据。Bearer 若从脚本环境或客户端诊断泄露可在期限内重放，删除能阻止未来请求。Cookie 与浏览器定位值一旦清除，匿名所有者无法找回。未证明归属的旧记录将失去公网访问，服务端保留策略另行确定。当前数据 TTL 默认关闭，24 小时凭据期限与文件片段、消息和备份删除无关。匿名用户仍可新建会话消耗资源，复用现有准入和预算，公开运行前另定创建速率、累计配额与数据保留。只持有有效会话凭据的一方获得会话访问，服务端数据备份与管理员访问仍在基础设施信任边界内。

**批准后的实施验收标准。**

1. HTTP 矩阵覆盖 A/B 两套会话凭据、无凭据、错配、重复、篡改、过期、删除、旧 ID 与未知会话，五路一致拒绝，拒绝时不进入正文解析/暂存或昂贵处理，不读会话业务内容、不更新时间/写库。合法 Cookie 和脚本会话的上传、查询、删除、JSON/SSE 与现有协议回归正常；跨站来源、Cookie 属性、缓存头和 SSE 流建立前拒绝有测试。
2. 专用本地 PostgreSQL 从非空 `0003` 升级后核对会话、消息、文件、chunk、租约的数据和外键，旧行无凭据，签发事务失败无半写，重启可验证，删除级联失效，在途删除无复活，数据库错误不开放访问。保留可信离线评估与旧迁移工具的隔离回归。
3. 前端单元、类型/构建与实际本地浏览器冒烟验证同源和开发代理、刷新、重开、多标签/陈旧回调、临时错误保留入口、删除结果、过期或清 Cookie、存储失败。检查 Web Storage 仅含计划字段，批准的旧缓存按范围清理，问答正文和凭据无持久化。共享导出只能包含明确选择的数据。
4. 用合成标记扫描响应错误、应用日志、启动方式的 Uvicorn/代理日志和评估异常字段，核对无原始 ID、路径、凭据/摘要、文件名及内容泄露，正常 request_id、错误类型、状态、耗时、usage 可追踪。运行默认离线 Python 与 routing、受控 Source、前端测试和完整构建。网关/生产验收单独记录，未执行不能当作达标。

## 阶段 2：一致性与生命周期

历史规划快照（2026-11-16，实施前）：当时仍是SQLite/MiniLM，T15a以外的数据库任务未完成；用户目标改为BGE-M3 + pgvector，依赖按[T16](#t16)衔接。当前存储迁移已经完成，见顶部入口和后续验收记录；本段不作为当前待办状态。

<a id="t05"></a>
### T05 · P1 · 已完成：关系数据库/向量数据并发与恢复

- 依赖：T15c、T16c；按[新方案](../docs/PGVECTOR_MIGRATION.md)落实，不先实施即将淘汰的FAISS文件代次发布。
- 范围：关系元数据/Chunk原子提交的竞争和故障处理，唯一约束、提交不确定、TTL/删除及活跃请求。基本写入由T16c负责，消息追加由T15c负责，不重复实现。
- 验收：并发上传/问答不覆盖或重复计数，不复活删除会话；无半写/跨会话Chunk；断连不盲目重放。旧FAISS归档受保护，DB故障不触发“孤儿”批量删除。
- 回归：并发屏障、每个写入阶段及commit不确定故障、进程重启、TTL/删除竞争；恢复由T16d/T15f联合验收，持续备份与T12衔接。

<a id="t06"></a>
### T06 · P1 · 已完成（DONE）：Agent / SSE 失败终态

- 范围：Graph 输出、`agent_service.py`、响应 schema；保留 Specialist 失败信息，统一 JSON/SSE 结果与保存失败语义，减少节点映射漂移，明确断线后的服务器行为。
- 验收：失败/降级不伪装成功，流有明确终态或可识别中断；记录已发生用量；不因自动重试重复生成。兼容既有事件或提供增量扩展说明；不承诺无法证实的上游即时取消。
- 回归：成功、单 Specialist 失败、Reviewer 降级、Graph 异常、保存失败、断线、空/截断流；依赖 T05 的持久化契约。
- 2026-11-24 启动复核：用户确认 `f348fa4da4469a560326364b57915624827fbfa0` 为基线，授权依次执行 T06 → T07 → T05a → T09b，各项验收后独立本地提交；初始工作区和暂存区干净。T01/T03/T09a 及历史风险保留。
- 启动时阻塞（已解除）：`AskResponse` 和 `_build_result` 无整体执行/持久化状态；Specialist 状态在 Graph 汇总时丢失，Reviewer 的模型失败可降级为文本后仍返回 success；服务层把节点更新统一计为 completed，Graph 异常后仍保存并记录 completed，保存异常则没有最终 result。仅修复内部日志不能让 JSON 客户端可靠区分这些情况。新增终态元数据会触及本轮明确要求先确认的公开 API/SSE 契约边界，尚未修改业务代码或提交。
- 当时待批准方案（后获批准）：保留现有响应字段、HTTP 成功传输方式及 `progress`/`result` 事件名和原 status 枚举，增量增加执行元数据；最终结果明确 succeeded/degraded/failed/cancelled、受控原因、节点结果及 saved/failed/not_attempted 保存状态，progress 可携带节点结果快照。断线无法投递时仅记录取消/中断及实际用量，不承诺上游即时取消，不自动重发。旧客户端可忽略新增字段，但须完成 T07 才能正确展示新增失败语义。
- 备选：完全不扩展外部字段，只修正内部状态/日志并沿用 failed progress；这无法满足 JSON 的降级/保存失败可识别验收，不建议以此标记完成。解除条件：用户批准具体增量契约后，先补契约/失败回归测试，再实施 T06；后续三项按指定顺序等待，不绕过当前确认边界。无需破坏性数据库迁移、改变 TTL 保留策略、新框架或付费 API。
- 批准前字段草案（最终实现见EXECUTION.md）：最终 result/AskResponse 增加 `execution` 对象，包含 `status`（succeeded/degraded/failed/cancelled）、受控 `reason`（可为空）、`node_statuses` 映射和 `persistence`（saved/failed/not_attempted）；progress 仅增量携带 `node_statuses`，不扩大其原 status 枚举。旧字段保留，旧服务器缺失新字段时由 T07 明确显示状态未确认，不推定成功；T07 同步适配，旧客户端忽略新字段仍不能获得新增终态保障。
- 本轮前置验证：默认离线 `.venv/Scripts/python.exe -B -m unittest discover -s tests -t . -v`，196 项，165 通过/31 个 opt-in 跳过（13.748 秒）；所有真实模型、真实 PDF、PG 和恢复开关关闭。首次沙箱运行在 HTTP 测试附近无后续输出，已中止；同命令在允许本地进程通信的执行环境重跑通过，未改测试，首次挂起根因未单独确证。前端 `npm test` 6/6、`npm run build`（tsc/Vite）通过。日志在已忽略的 `.evaluation-local/t06-preflight-*`。这是基线复核，不是 T06 验收；PG 集成未运行，尚无任务完成提交。
- 恢复实施：用户明确批准方案 A 的增量终态字段及 T07 适配，原确认阻塞已解除；保留上文历史复核记录。最终字段增加 `generation_status` 单独记录生成结果，整体 `status` 还受保存失败影响；无破坏性 Schema 迁移。

<a id="t07"></a>
### T07 · P1 · 已完成（DONE）：前端恢复与流契约

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
### T09 · P1 · 已完成（DONE）：模型结构与 Memory 边界（T09a、T09b均已验收）

- 范围：Planner/Collaboration 输出校验、`AgentState` 边界、`utils/memory.py`；校验步骤和内部字段，规范去重；限制摘要缓存和历史输入，减少锁内模型 I/O。
- 验收：非法 JSON/步骤/类型走确定的有界回退；单次补充上限不变；Memory 不跨会话串用，有明确容量/淘汰策略；保留既有快路径与回答上下文。
- 回归：畸形输出、重复/未知步骤、空内容、长历史、并发摘要、缓存淘汰、用量归属。
- 父项状态同步（2026-11-24，仅文档核对）：T09a的结构边界与T09b的Memory容量/隔离范围覆盖本项验收，已有各自独立测试记录及提交；据实关闭父项，不新增实现或重跑验证。真实模型遵循率、语义连续性与事实/引用质量仍保留为未验证，不能由本项DONE推导T08/T10完成。

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
### T12 · P1 · 待实施：运维与恢复证据（T12a P1、T12b P2）

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

- 依赖：T15f、T16f全部验收，GitHub 发布及 T15e2 准备和必要发布前置验收通过，核实实际生产数据源、目标 PG/扩展、资源费用和维护窗口。生产配置、资源、迁移方案和费用待确认；新增收费资源、套餐升级、真实生产数据迁移及破坏性操作须明确批准。已获满足前置条件后手动部署的授权，见[当前队列](#current-execution)。
- 范围：盘点实际生产数据、冻结并排空请求、成套备份、执行经演练的迁移、全量对账及切换；明确恢复 TTL 与备份保留时间。
- 验收：生产 ID/聊天/文档/索引逐项对账并确认公开契约；保留可用回滚制品和备份，不删除旧库。首次新写入前后分别采用已演练的回滚流程；报告实际执行结果，不因 T15f 通过而代替上线验收。
- 回归：批准范围内非付费冒烟、日志/连接/磁盘关联及重启验证；发生数据差异即停止开放业务并按批准的恢复方案处理，不自动执行破坏性降级。

## pgvector 专项（2026-11-16，本地实施已授权）

<a id="t16"></a>
### T16 · P1 · 已完成（本地范围）：FAISS → PostgreSQL pgvector

- 历史规划依据（实施前）：用户选择BGE-M3 + pgvector，当时仍是SQLite/MiniLM，见[专项设计](../docs/PGVECTOR_MIGRATION.md)。后续本地实施已完成，验收见下文；Render目标保留在T15e2/T15g，不包含在本项完成范围。
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


## 2026-11-24 后续开发队列

逐项文件位置、风险和方案统一见[审计 F01–F17](AUDIT_2026-11-24.md#4-风险清单与任务映射)。沿用既有编号，下表补齐当前任务的依赖与验收；本轮未开始实施。P3 表示低风险维护。

| 原任务 | 优先级/状态 | 当前范围、依赖与验收 |
| --- | --- | --- |
| T01 | P1 / 已完成 | F01；问题trim/max、全批文件/字节预检、页/文本/Chunk上限、请求体计量/读取期限、上传与问答有限准入、异步SQL读取及取消清理已验收。参数见开发文档；保持逐文件提交，原生解析硬沙箱/总费用预算不在本项完成范围 |
| T02b | P1 / 待实施 | F02/F16；依赖T04凭据设计。路径/session_id、Uvicorn/第三方日志、浏览器持久化、PDF外发/保留说明。合成标记不泄露，request_id仍可关联；已完成T02a不重做 |
| T03 | P1 / 已完成 | F03；复用UsageTracker/ContextVar，共享原子调用/Token/费用预留、请求截止、有限应用重试及取消；SDK零重试，routing零LLM、live/real-pdf/Judge统一opt-in，CI/默认测试网络关闭。178项本地回归及CLI/前端通过，原生在途I/O和硬账单限制见验收记录 |
| T04 | P1 / 待实施（设计待确认） | F02；先定匿名凭据/共享/兼容期，不默认账号系统。所有CRUD、上传和JSON/SSE统一校验；独立客户端越权失败且不触发模型 |
| T06 | P1 / 待实施 | F04；T09a结构校验，T03预算失败协同。成功/降级/失败/保存失败明确，保留协议字段；若改公开终态先确认。覆盖部分失败、断流、DB失败和usage |
| T07 | P1 / 待实施 | F05；API错误/终态依赖T06，网络恢复子项可先做。404/500/断网区别处理；响应校验、分片CRLF/EOF、AbortSignal、reader释放；不清空离线历史、不自动重发收费请求 |
| T08 | P1 / 待实施 | F10；依赖T10最小复核集，遵守T01/T03限制。逐文档与问题覆盖、无答案行为、引用；预登记指标并报告逐题退化，不盲目放大k |
| T10 | P2 / 待实施 | F10；无前置。人工复核跨页/跨文档/无答案最小集并留依据，其余仍provisional。引文存在不等于事实正确，Judge未授权不调用 |
| T14 | P2 / 待实施（进入2027年前） | F14；无依赖。本轮没有核实最新官方费率；后续核实官方日历、别名和独立币种价格，测试未知年份降级 |
| T15g | P1 / 待实施（未获生产操作授权） | 本地完成不能代替目标配置、角色、备份和容量验证；需要维护窗口与具体批准，不自动上线 |

### T05a · P2 · 已完成（DONE）：在途请求、时间和 SQL 等待边界

- 对应F08；保留T05历史原子性/并发验收。文件：app/services/postgres_store.py、app/db/engine.py、agent_service.py。
- 风险与方案：锁前时间可能倒退、TTL启用时长请求缺租约、SQL等待无服务器截止；采用锁后/单调时间、受限在途策略和lock/statement timeout，不跨LLM持事务。
- 依赖：T06，与T03总截止协调。验收：屏障控制时间不倒退，跨TTL长请求/主动删除/清理、超时回滚与池归还；默认保留清理仍关闭。

### T09a · P1 · 已完成（DONE）：Planner/Collaboration 结构验证

- 对应F06，从原T09拆出；文件：agent/llm_planner.py、collaboration_agent.py、状态和测试。
- 无前置。风险/方案：非法嵌套/null导致TypeError；校验允许步骤、去重、bool、回答及数组字段，确定有界回退，复用现有Pydantic或小型解析函数。
- 验收：null/对象/数字/重复/未知值/空回答均不逃逸异常；保留快路径、最多一次补充、usage和T06失败语义。
- 本地验收：2026-11-24新增18项回归、完整196项中193通过/3跳过；详见末尾记录与[结构边界说明](../docs/DEVELOPMENT.md#model-output-validation)。T06负责后续整体终态传播，本轮不实施。

### T09b · P2 · 已完成（DONE）：Memory 容量与锁边界

- 对应F09，复用原T09剩余范围；文件：utils/memory.py、历史读取和调用方。
- 依赖T03/T06。全局锁内I/O、全历史输入和无界缓存改为会话/版本范围、容量/有效期约束和锁外计算。
- 验收：长历史、并发摘要、淘汰/失效、跨会话隔离、usage与上下文连续性；不因摘要复用而增加调用。

### T11a · P2 · 待实施：可复现运行依赖

- 对应F12；文件：requirements、Dockerfile、CI；无前置。
- 风险与方案：多数>=及浮动基础镜像导致漂移；固定经验证的依赖/基础镜像更新方式，保留BGE revision和pypdf一致性、迁移依赖分离。
- 验收：新环境版本清单一致、升级兼容独立验证；安全扫描结果按适用性复核，本轮未作漏洞无风险声明。

### T11b · P2 · 待实施：CI 容器实际运行

- 对应F12；文件：CI、容器验收脚本。
- 依赖T11a、T12a。现有CI仅build，增加独立PG和无FAISS容器启动/上传/Source/SSE/重启验证。
- 验收：默认与非默认PORT、缺模型/DB/schema、安全上下文、零付费且不连接生产；不以docker build成功替代运行。

### T12a · P1 · 待实施：依赖就绪与冷启动

- 对应F07；文件：app/main.py、健康路由、Dockerfile；依赖T11a。
- 方案：静态liveness与内部readiness分工，模型/profile/schema启动门控和PORT一致；公开契约变化先确认。
- 验收：DB断开、扩展/模型缺失、冷启动/重启、非默认PORT均能明确判断，零供应商请求；资源基于实测峰值和余量，不假设旧Render配置足够。

### T12b · P2 · 待实施：原生 PG 备份恢复与运维信号

- 对应F13；文件：本地运维脚本、开发/测试文档。
- 依赖已完成T05/T15f/T16d与T11b制品。原生PG备份/恢复全量对账，明确保留、RPO/RTO与连接/资源/失败指标。
- 验收：全部消息、文档元数据、向量及模型profile可恢复；SQLite反向导出不能当PG完整备份；生产演练、保留数据删除和外部通知另批。

### T15d1 · P2 · 待实施：离线迁移工具验证补强

- 对应F11，保留T15d/T16d历史完成。文件：migration_tools/snapshot.py、import_legacy.py、export_legacy.py；无前置。
- 方案：强制完整manifest必需文件、严格JSON和提交前对账；明确受限恢复与完整PG备份区别；不扩张可信pickle输入。
- 验收：空清单/省略库或索引、重复键、非法数字/Unicode、向量错配、重跑和失败原子性；原输入不改。未经演练不处理生产数据。

### T15e2 · P1 · 待实施：新存储部署候选配置

- 对应F07，承接T15e未实施的Render部分；文件：render.yaml、发布/回退说明。
- 依赖T11b、T12a/b；上线还需T01/T03/T04/T06和T15g批准。
- 发布准备等待 GitHub 阶段验收。核查实际数据来源后确认 T15d1 对迁移路径的适用性；走旧库导入路径时，须先满足相应工具验收。当前授权和证据要求见[当前队列](#current-execution)。
- 方案：明确连接、运行/迁移角色、受控Schema升级、模型资源测量、健康/日志及恢复，先交付可审核配置。
- 验收：静态Blueprint校验、隔离模拟与回退；平台能力和费用在上线前核实；本任务不自动创建收费资源或部署。

### T13a / T13b / T13c · P2 / P3 / P3 · 待实施：文档和可选入口收敛

- a对应F15：docs/开发/测试/架构；无依赖。修陈旧状态，历史设计给日期/替代入口。新checkout命令、双语和模块引用一致；审计轮仅改plans。此次仅授权AGENTS强制任务维护及当前状态同步，见[当前队列](#current-execution)；该文档增量不代表T13a其余范围完成或获实施授权。
- b对应F16：devcontainer/main.py；依赖T01/T02b。明确本地Streamlit定位，保留CORS/XSRF保护，统一异常提示及scope回收。本地启动和失败测试；若公开暴露则提升P1。
- c对应F17：旧FAISS/待接线注释及许可证；无依赖。小范围维护，许可证由所有者选择，不引入额外流程。

## 2026-11-24 审计轮验证（T01实施前）

- 默认123项94通过/29跳过；全新回环PG测试库123项120通过/3跳过，测试后容器停止。前端6/6和tsc/Vite通过；routing9/9、受控Source1/1均零LLM；真实PDF仅校验30Case/90条引文通过。
- 本轮未重跑BGE检索/性能、付费API、生产或Render。历史60.7%不当作本轮实测。详见审计第3节，包括首次沙箱中止和后续重跑。
- 本机已有latest容器因DATABASE_URL配置错误重启，保留原状，不将缓存镜像存在视为服务健康。
- 本轮审计规划不是开发任务验收。新增子项全部待实施；文件范围仅plans，未提交或推送。


## T01 本地实施与验收（2026-11-24）

- 本轮范围：当前最高优先级中可独立验收的输入/上传资源任务组。T04 的凭据/共享/旧客户端方案尚未确认，不擅自改公开访问契约；T03/T06 等保持待实施。开始时已有三份审计规划差异，已保留，未覆盖既有代码工作。
- 根因与方案：原 AskRequest 只校验非空，上传无应用层资源上限、全量字节读入且会话 SQL 阻塞异步入口。新增 app/input_limits.py，复用原解析、切分、Embedding、PG 原子提交；采用每进程非排队准入和阶段前限额，没有引入队列服务、框架、Schema 迁移或改变 LangGraph 拓扑。
- 涉及文件：app/input_limits.py、app/main.py、app/api/routes.py、app/schemas/requests.py、app/services/pdf_service.py、.env.example；回归 tests/test_input_limits.py 与 test_input_limits_pg.py；同步 docs/DEVELOPMENT.md、TESTING.md、ARCHITECTURE.md 及本文件/ROADMAP。
- 行为：问题去首尾空白并限制字符数；JSON/实际multipart字节、接收空闲及累计期限受限，不能靠伪报Content-Length绕过；全批文件名/字节预检在首个PDF提交前完成。解析前校验页数、逐页累计文本、编码前校验Chunk与可搜索正文。临时文件以64KiB块复制，哈希增量计算；上传SQL移到工作线程。
- 并发/取消：上传与问答/SSE分别有每进程有限额度，繁忙立即429/Retry-After；请求体超时408、资源超限413、问题无效422、无文本/损坏/加密PDF400。重复取消也等待工作线程退出后删除文件/释放上传额度，并在阶段边界停止后续编码/提交；不能撤销已经开始的commit。CORS/request_id保留，已收完请求体后的SSE监听不受请求体超时影响。
- 兼容性：路径、响应字段和progress/result事件不变；相同文件名仍跳过。全批名称/字节预检失败不写文档/Chunk，但读取会话仍可能刷新活动时间；后续逐文件解析失败时已成功文件保留。正常多PDF、1024维向量、文件名/物理页码及Source零模型路径由真实PG测试验证。
- 先验/失败证据：复用同日审计基线123项（PG120通过/3跳过）。新增原实现回归复现文件数和空白/超长问题的5个失败断言、同步SQL阻塞；实现中发现的复制取消、SSE接收阶段、合法JSON代理对、CORS提前拒绝边界均补测试并修复，未删有效断言。首个普通沙箱异步测试挂起后已终止本轮精确匹配进程；不记为通过，后续在允许权限下运行。
- 最终后端：.venv/Scripts/python.exe -B -m unittest discover -s tests -v。全新独立回环 pdf_agent_t01_test、端口55439，启用POSTGRES/LEGACY_RECOVERY开关：147项144通过/3跳过，16.441秒，日志 .evaluation-local/t01-full-pg-final.log；默认所有opt-in关闭：147项116通过/31跳过，12.447秒，日志 t01-full-default-final.log。比审计基线新增24项（22离线/2真实PG），既有测试无新增失败。测试开关、占位Key与HF离线设置同审计；没有读取生产URL作为fallback。
- 其他验证：前端npm test 6/6及npm run build（tsc/Vite）通过；routing9/9与受控source-citations1/1均LLM=0；真实三PDF --validate-only 的30Case/90条引文校验通过。报告 .evaluation-local/t01-routing.json、t01-source.json、t01-pdf-validation.json；命令入口见TESTING。AST语法、相对链接与git diff --check通过；没有配置的Python lint/type-check不虚构。
- 验证边界：PG上传采用真实解析/数据库及明确合成Embedding；未重跑真实BGE语义检索、付费生成/Judge/缓存探针，三个对应opt-in仍跳过。未重建应用Docker镜像、访问Render/生产、推送Git或执行数据库迁移；测试库只用于本轮合成夹具，停止容器并保留卷。
- 剩余风险：默认阈值不是容量保证；原生PDF解析/编码没有硬CPU/内存隔离，运行线程不能立即强杀；多进程额度相加、无会话存储配额或身份速率限制。完整SSE取消/失败语义、SDK重试与总费用预算、访问权限和全链路日志分别仍属T06/T03/T04/T02b。本项不将这些边界标完成。
- 停止点：T01满足上述本地验收；当前任务组完成即停。建议下一项T03，T04先审阅最小凭据兼容方案，不自动推进。


## T03 本地实施与验收（2026-11-24）

- 授权与停止范围：只实施T03，保留上轮T01和审计文档差异；不做T04、生产、付费模型、数据库业务迁移、部署、提交或推送。T01未执行的BGE/付费/镜像验证与原生解析、会话配额等风险仍保留在其记录，不因T03完成而消除。
- 根因：SDK默认重试隐藏实际尝试数；逻辑调用缺共享调用/Token/费用/截止预算；live/Judge只检查Key，routing歧义会调用模型；缓存探针使用独立直接调用。复用UsageTracker、既有ContextVar/copy_context及定价/用量归一化，未修改Graph拓扑、状态契约、检索或提示词。
- 修改文件（本轮23个，非整个未提交diff）：utils/llm_budget.py、llm_client.py、observability.py、memory.py；app/services/agent_service.py、app/api/routes.py；main.py；evaluation/runner.py、cache_probe.py；tests/__init__.py、test_llm_budget.py、test_cache_probe.py、test_evaluation_usage.py、test_observability.py；.env.example、.github/workflows/ci.yml；README.md、README.zh-CN.md；docs/ARCHITECTURE.md、DEVELOPMENT.md、TESTING.md；plans/ROADMAP.md与本文件。
- 预算：每个请求Tracker持有同一线程安全RequestBudget，API断连信号传入该对象，Streamlit/评估作用域同样覆盖Planner、Memory、并行专业Agent、Collaboration、补充步骤和Reviewer。调用前原子预留调用/输入估算/输出上限/USD费用估算，失败或并行竞争不能突破预留；已获额度的调用不会因其他线程被拒绝而误丢弃。取消与截止仍能阻止未发出尝试，未开始的预留可释放。
- 结算与观测：原usage及by_model/by_operation仅记每次SDK尝试的供应商用量；预算预留不会混入账单统计。有效Token与缓存/价格可用性分开判断，已知部分结算、未知部分保留保守预留；未知费用保持unavailable。供应商超额计数如实保留并停止后续调用。预留、结算、耗尽、取消、重试原因、超时和最终预算有结构化日志，不输出Prompt、Key或原始供应商错误。评估Case增加agent_budget/judge_budget，探针增加budget，Agent/Judge实际usage隔离不变。
- 超时/重试：SDK max_retries固定0，应用默认0、可设0–2；仅连接/超时和408/409/429/5xx可重试，认证/参数与畸形回答不重试。每次重试重新竞争请求预算，SDK超时裁剪到剩余时间，等待和Memory锁获取遵循截止；过长数字Retry-After不重试。HTTP断连/生成器关闭取消同一预算，已发出调用不可撤回，迟到响应仍保留实际用量。预算失败沿用现有failed progress与安全result，字段和事件类型不变；更广泛终态/前端恢复仍属T06/T07。
- 付费门禁：routing只用规则，歧义Case失败且LLM为0；live/real-pdf生成与Judge均需--allow-paid-api。免费Source有禁止LLM的上下文，参考标注不能授权调用。真实客户端工厂PDF_AGENT_DISABLE_LLM_API仅0/false放行，无效值关闭；CI固定1，默认tests包入口强制离线。标准命令增加-t .确保先导入tests包。付费opt-in不替代用户授权，不在CI关闭网络保护。缓存探针原2–5次、64输出Token、零重试和重复Prompt行为保留，统一网关只记一次用量。
- 回归开发证据：初始门禁/SDK测试在旧实现复现5个失败断言；后续回归发现并修复迟到响应、并发预留误取消及网络开关无效值失效开放问题。旧request_id测试保留原三个精确参数断言并新增预算类型/HTTP关闭检查；Judge测试仅增加Fake调用所需的显式付费选项，原用量/错误断言保留。
- 最终完整命令：.venv/Scripts/python.exe -B -m unittest discover -s tests -t . -v。全新回环PG/pgvector数据库pdf_agent_t03_test、端口55440，POSTGRES/LEGACY_RECOVERY=1：178项175通过/3跳过，29.155秒，日志.evaluation-local/t03-full-pg-final.log。默认全部opt-in=0：178项147通过/31跳过，24.852秒，日志t03-full-default-final.log。相对T01基线新增31项（30预算/工作流/门禁、1探针），既有测试无新增失败。
- 测试类型：全部LLM为Fake/Mock或SDK+httpx.MockTransport，无实际供应商网络。覆盖12线程争抢3次额度、Token/费用/未知用量、取消前后、SDK状态分类、实际Graph的Memory与单专业快路径、Collaboration→一次QA补充→Reviewer、Source与SSE失败协议。模型别名/缓存/定价及Judge失败旧回归全部保留。真实PG测试仍用明确合成Embedding，不代表BGE语义质量。
- 其他验证：frontend npm test 6/6、npm run build（tsc/Vite）通过；网络关闭时routing CLI9/9与受控Source1/1通过且LLM=0，报告.evaluation-local/t03-routing.json、t03-source.json。Python AST、Markdown相对链接、CI YAML结构/离线env及git diff --check通过。T01核心和测试哈希保持不变，routes.py只新增两个预算传参；用户T01改动未覆盖。
- 未执行：真实付费API/Judge/缓存探针、真实BGE语义/压力评估、应用Docker镜像重建、actionlint/远程CI、Render/生产验证。T01的30Case/90引文结果仅保留为此前证据，本轮不冒充新实测。专用PG测试库合成会话/文档/向量/消息对账为0后停止容器，卷保留；历史数据库和索引未动。
- 剩余限制：输入估算不是供应商Tokenizer，预留不是账单或账户级/跨请求/整批评估预算；Agent/Judge各有独立额度。依赖已有价格/日历，未知时默认费用保护拒绝派发（T14仍待维护）。SDK超时是I/O超时，截止阻止新派发/重试并拒绝迟到成功，不保证强杀原生检索、在途网络或数据库保存，无法追回外部费用。默认阈值尚未经真实付费负载调优；完整断流恢复、全链路日志最少披露、Memory容量/锁内I/O、访问凭据和SQL等待分别仍属T06/T07、T02b、T09b、T04、T05a。
- 验收结论：T03达到本地验收，停止，不进入其他任务。建议下一项T09a结构校验，再衔接T06；T04仍需单独审阅凭据与兼容方案。


## T09a 本地实施与验收（2026-11-24）

- 范围：仅Planner/Collaboration模型控制JSON校验，不实施T04/T06。保留T01/T03全部代码与验收/未验证风险；开始时工作区已有上两轮和审计差异，记录73个既有源/测试/配置文件哈希后最小增量修改。
- 路径核实：Planner实际生成步骤数组，Collaboration生成七字段控制对象；专业Agent外层字典由代码构造，QA/Summary/Keyword/Compare、Reviewer、Memory实际模型结果均为自然语言，Source无LLM，故不强行JSON化。Evaluation Judge已有独立评分/列表检查，不纳入T09a重构。
- 修改文件（本轮10个）：新增agent/output_schemas.py、tests/test_model_output_validation.py；修改agent/llm_planner.py、collaboration_agent.py、state.py；同步docs/ARCHITECTURE.md、DEVELOPMENT.md、TESTING.md、plans/ROADMAP.md与本文件。没有更改依赖、Graph拓扑、API/SSE/前端或T03网关/预算。
- Schema：复用Pydantic RootModel/BaseModel严格模式和SpecialistStep Literal。Planner只能是1–5项原始合法步骤数组，不接受任务对象、参数、未知枚举；稳定去重。Collaboration七字段全部必填、额外字段禁止，文本/诊断列表有限长、StrictBool，不把字符串false或数字转换为布尔。修订标志与步骤数组必须一致，任何已执行/非法步骤使整份响应拒绝；不部分筛选后伪装有效结果。
- 本地修复：仅首尾空白、单个开头BOM、完整json/无标签围栏、受支持字符串字段首尾空白、步骤稳定去重；原始长度/数量先限额。拒绝重复对象键、非JSON常量、深层/错误类型/空答案/超长及修订矛盾；不截取子JSON、不修单引号/尾逗号、不做名称大小写或近形字映射。具体字符/数组上限见开发文档与Schema单一实现。
- 回退：Planner记录失败原因后沿用QA规则回退，不声称是有效模型计划；Collaboration标记failed，保留专业结果，needs_revision=false/next_steps=[]，不把原始非法文本放入答案。无专业结果仍为skipped且零调用。没有新增模型修复/重试；原调用与已有传输重试仍由T03预算和usage统计，预算耗尽/取消不买额外修复。
- 日志：model_output_repaired、model_output_validation_failed、planner_fallback、collaboration_fallback只写固定原因/修复与Pydantic错误代码及节点，不记录响应、Prompt、文档、错误位置键或ValidationError原始输入。已覆盖敏感字段名和值不会进入日志或回退结果。
- 开发证据：初始4项回归在旧实现复现7个失败与3个TypeError，记录.evaluation-local/t09a-red.log。扩展测试时出现一次本轮测试文件拼接缩进错误，已修复，未改断言或生产行为来规避。最终新增18项（含表驱动恶意/边界子场景）全部通过，日志t09a-targeted.log；不是实际模型输出质量或安全认证。
- 最终完整命令：.venv/Scripts/python.exe -B -m unittest discover -s tests -t . -v。新建回环PG/pgvector pdf_agent_t09a_test、端口55441，POSTGRES/LEGACY_RECOVERY=1：196项193通过/3跳过，18.365秒，日志.evaluation-local/t09a-full-pg.log；默认全部opt-in关闭：196项165通过/31跳过，13.514秒，日志t09a-full-default.log。相对T03的178项新增18项，旧测试无新增失败。
- 功能回归：Fake/Mock验证正常/非法JSON、缺字段、类型/枚举/参数、空结果/上限/深层/重复键/Unicode、预算耗尽与零额外修复；自然语言六路径保持文本，Source零LLM；JSON/SSE字段和事件保持，非法协作nested status为failed；重复QA修订只执行一次，第二次请求补充仍受既有MAX_REVISION_COUNT=1限制。T03全部预算/重试/费用、Judge失败、隔离与T01回归保留。
- 其他验证：前端npm test 6/6、npm run build（tsc/Vite）通过；Routing CLI9/9、受控Source1/1通过且LLM=0，JSON报告.evaluation-local/t09a-routing.json、t09a-source.json。Python语法、相对链接、新文件空白及git diff --check通过。哈希对账只允许既有agent/planner、collaboration、state三处源码变化，T01/T03及已有测试/Graph/API/SSE源文件均未覆盖。
- 未执行：真实付费API/模型Schema遵循率、真实BGE质量/压力评估、应用Docker镜像重建、远程CI与Render/生产；不能将未运行项写成通过。新测试库仅有合成夹具，对账会话/文档/向量/消息为0后停止容器并保留卷，未动历史数据；未提交、推送或部署。
- 剩余风险：结构/执行控制一致性不代表事实正确、引用受支持或完全防提示注入；严格必填/长度限制可能增加模型回退，尚未付费实测。自然语言空文本/回答质量、Memory容量/锁内I/O、跨请求费用、原生在途取消等既有风险分别仍由T06/T09b、T08/T10和T03后续边界承担，T01/T03原记录保留。
- T06依赖与停止点：T09a提供受控步骤、合法协作字段及明确failed/fallback；T06需继续设计整体成功/降级/失败、持久化失败和断流终态，不能仅凭本项通过宣称全局失败传播完成。Planner回退目前通过日志识别，无新增公共状态或SSE事件；若T06需协议变化仍须先确认。T09父项保持进行中、T09b待实施；本轮T09a完成后停止，不自动进入T06。


## T06 实施与验收（2026-11-24）

- 方案A增量契约已获用户明确批准；保留T01/T03/T09a代码、测试、历史验收及剩余风险。实现见docs/EXECUTION.md；节点范围的ContextVar收集确定性回退原因，专业线程独立汇总结果；不增加模型调用、Graph节点或修订次数。
- JSON/SSE返回execution：整体与生成状态分开、节点结果、受控原因、保存状态。仅成功节点计completed；空/截断Graph失败。保存失败交付原回答与usage，候选消息不污染原快照；断线关闭Graph/取消同一预算，不保证已经断开的客户端收到结果或上游立即停止。
- RED：首批7项失败（6 error/1 failure），另有空专业输出原因断言失败；均在实现后通过。新增13项终态回归，无删除旧断言。
- 最终全量：`.venv/Scripts/python.exe -B -m unittest discover -s tests -t . -v`，独立回环pdf_agent_maturity_test（55440），POSTGRES/LEGACY_RECOVERY开启、真实PDF及付费关闭，209项206通过/3跳过，20.124秒，日志.evaluation-local/t06-full-pg-final.log。此前定向71/71通过；相对基线新增13项，无新增失败。
- routing 9/9及controlled source-citations 1/1，CLI exit均0，均零LLM；报告.evaluation-local/t06-routing.json与t06-source.json。前端本项未改，复用本轮前置6/6及完整tsc/Vite通过记录。无Python lint/type-check配置。
- 未执行：真实付费模型/Judge、真实BGE语义质量、远程CI、Docker镜像重建及生产/部署；均不作通过。保存提交遇连接中断可存在提交结果不确定，不自动重试；T05a补跨TTL/SQL等待，T07补客户端生命周期；T04/T02b不在授权范围。


## T07 实施与验收（2026-11-24）

- 前置T06提交6cf2e0c。复用既有React/TypeScript与Node测试器；新增protocol/sse/requestScope边界模块，API不再把unknown响应直接断言为业务类型；保留已有缓存三态和独立币种定价。
- App显式取消、请求同步准入与旧回调隔离；临时恢复失败保留会话/历史，404单独处理、保留旧对话归档；存储异常显示警告；恢复按钮只GET，不重发生成。WorkflowPanel依据节点快照及execution显示失败/降级/保存失败，旧payload显示未确认。保留原新会话按钮经交互确认删除旧会话的业务行为，未自动改变保留策略。
- RED：新增入口测试因尚无模块失败；随后组件/API测试复现旧结果全节点完成、保存失败未显示、跨会话响应未拒绝三个失败。最终`npm test`19/19（原6+新增13），`npm run build`完整tsc/Vite通过；日志.evaluation-local/t07-tests-final.log和t07-build-final.log。未降低断言。
- 测试包括真实WorkflowPanel的React SSR双语组件渲染、逐字节UTF8/CRLF、空/截断/畸形/无终态、AbortSignal释放与完整result无需等待EOF、HTTP分类无自动重试、旧请求/存储失败。后端代码未改，复用T06最终全量209项206通过/3跳过和零LLM评估结果；未重复跑相同后端检查。
- 限制：无真实浏览器挂载/E2E自动化；同步服务端在途工作不保证客户端abort即终止。严格响应校验的外部客户端需适配增量字段。未执行付费API、生产、远程CI、推送/部署。


## T05a 实施与验收（2026-11-24）

- 前置T06/T07已提交（6cf2e0c/8f1155f）。新0003_request_leases是加表/索引/FK的非破坏性Alembic迁移，不搬迁或改写原会话/聊天/向量；只在55440独立pdf_agent_maturity_test升级，未运行历史/生产迁移或降级。
- 读写在行锁后采样并单调更新活动时间；问答快照获取有截止的共享数据库租约，不跨LLM持事务/连接；TTL排除有效租约，显式删除仍胜出且旧快照无法复活；退出/取消释放，进程崩溃由到期兜底。默认TTL保持关闭，过期操作租约仍可清理。
- DB_LOCK_TIMEOUT_MS/DB_STATEMENT_TIMEOUT_MS服务器默认边界；SET LOCAL额外裁剪到T03剩余截止，池中不泄漏，取消拒绝业务SQL。租约释放允许在耗尽预算后执行短清理，但仍受服务器超时约束，无业务写入自动重试。
- RED：首批6场景1断言失败/5缺实现错误；关闭TTL未清理过期操作租约的追加断言失败；实现后全部通过。新增8项PG+1项配置回归，旧driver options及schema revision断言更新为新准确值，保留原校验强度。
- 完整回归`.venv/Scripts/python.exe -B -m unittest discover -s tests -t . -v`：218项215通过/3跳过（19.075秒），PG及legacy恢复开启、真实PDF与付费关闭，.evaluation-local/t05a-full-pg.log。默认离线同命令218项179通过/39跳过，.evaluation-local/t05a-default.log；定向46项45通过/1 opt-in跳过。未降低断言或跳过新增必需PG测试。
- 前端未改，复用T07的19/19及完整构建。静态检查为git diff --check，无已配置Python lint/type-check。未调用真实付费API、重建镜像、远程CI、生产/Render或push。
- 剩余边界：池/建连等待仍单独最多默认5秒，不是硬实时总HTTP截止；墙钟偏移会影响UTC租约/TTL实际时刻，需主机同步；上传解析/Embedding仍无心跳租约，TTL开启且超期时安全失败而非复活会话。旧二进制回退需审核Schema版本并排空请求，未执行破坏性downgrade。详见LOCAL_STORAGE。


## T09b 实施与验收（2026-11-24）

- 前置T03/T06及用户指定顺序均满足；上一提交c70912a。Memory按会话/内容版本/文件上下文隔离，未知会话仅同一请求Tracker范围复用，完全无范围不全局缓存；LRU+单调TTL与在途索引均有容量上限。摘要与命中日志均在索引锁外；相同key并发合并，等待遵循自身截止/取消，失败/取消唤醒等待者。
- 只通过原网关调用一次摘要，缓存读者不复制usage；模型失败保留已发生/未知用量，正文成功时T06标degraded；空/非法摘要及容量耗尽不伪造成功、不增加修复调用。默认历史100条、总输入24000 UTF8字节（近期8000/较早摘要输入16000）、摘要/文件名各4000字节；默认128缓存项、900秒TTL，范围与局限见MEMORY/DEVELOPMENT。
- PostgreSQL只读取受限历史窗口并独立保留总message_count；原数据库全部历史/未知字段保留。批次追加只保存窗口后的新消息，真实PG验证并发/幂等和公开计数；显式删除、过期读取删除及TTL清理在提交后失效缓存，在途摘要不发布已失效结果。不改变Schema/数据保留策略。
- RED：初始Memory9项6失败/2缺实现错误；PG3项2失败/1缺总计数字段错误；另复现命中日志仍占索引锁的失败后移到锁外。最终新增15项离线+3项PG，保留T01/T03/T09a原断言。
- 最终全量`.venv/Scripts/python.exe -B -m unittest discover -s tests -t . -v`：隔离PG+legacy开启236项233通过/3跳过（21.535秒），日志.evaluation-local/t09b-acceptance-pg.log；所有opt-in关闭默认236项194通过/42跳过（14.938秒），日志t09b-acceptance-default.log。相对f348fa4基线新增40后端测试，未增加失败。
- 最终前端npm test19/19，npm run build完整tsc/Vite通过，日志.evaluation-local/maturity-final-frontend.log及maturity-final-build.log。routing9/9、controlled source-citations1/1，均零LLM；报告maturity-final-routing.json/maturity-final-source.json。Memory最后仅索引锁外日志调整后已重跑全部后端；前端/Source均未受该调整影响，复用本轮成功结果。
- 风险/未执行：有限窗口可能遗漏旧对话，真实模型长对话语义质量、付费RAG/Judge、浏览器挂载E2E、生产负载、远程CI及Docker镜像/部署均未验证；未运行不算通过。历史单条完整JSONB元数据仍读取，总count仍可能随规模变慢；缓存不替代授权，原T04/T02b风险保留。旧记录、SQLite/FAISS及历史本地/生产PG库未删除或迁移，新代码运行到旧PG库前仍须显式升级0003（本轮只升级隔离测试库）。
- 本轮停止：T06→T07→T05a→T09b四项验收完成并按项本地提交；不继续未授权任务，不push/部署/生产访问/真实付费API。
