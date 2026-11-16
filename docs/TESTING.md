> 本地存储已接入 PostgreSQL/pgvector；启动、迁移及保护历史数据的当前命令见 [LOCAL_STORAGE.md](LOCAL_STORAGE.md)。下文 SQLite/T15a 记录为历史基线，不能作为当前 API 启动条件。

# 测试与评估

更新时间：2026-11-16 18:45（Asia/Shanghai）。命令来自当前脚本、测试装饰器和 CI；列出命令不代表本次已执行。环境准备见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## 分类与边界

| 类别 | 入口 | 数据/外部调用 | 能证明什么 |
| --- | --- | --- | --- |
| 后端单元与组件回归 | `tests/test_*.py`、unittest | mock LLM、临时 SQLite/文件；部分 FAISS 用测试 Embedding | 状态、生命周期、定价、用量、评估契约；不是完整 HTTP 并发/E2E |
| 前端单元 | `frontend/tests/workflow-cache.test.ts` | Node 内置测试器，无浏览器 | 缓存/费用显示辅助逻辑；不是面板交互或 SSE 浏览器测试 |
| routing 评估 | `evaluation/cases.json` | 规则路由，无 LLM | 预期步骤匹配；不验证 LLM Planner 或回答质量 |
| controlled live | 同上，StaticVectorStore | 预设 Document；部分用例调用模型/Judge | 可控工作流和引用回归；不是真实向量检索 |
| 本地真实 PDF | manifest + `real_pdf_cases.json` | 原 PDF、生产解析/Embedding/FAISS；模型可需首次下载 | 证据出处验证、实际检索或 Source 路径 |
| 付费 RAG / Judge | real-pdf 生成与 Judge | DeepSeek，参考资料会传给 Judge | 实际生成和语义评分；参考标注仍需人工复核 |
| 付费缓存探针 | `evaluation/cache_probe.py` | 同一有用 PDF 页重复 Prompt | 每次缓存字段/命中率；不保证命中、不证明回答质量 |

## 默认本地检查

以下 PowerShell 命令在独立测试终端执行，设置只影响该终端。显式关闭可选集成开关，避免继承历史设置；测试后关闭此终端。占位 Key 不是网络防火墙，新测试仍须 mock 外部调用。

```powershell
$env:PDF_AGENT_RUN_LOCAL_PDF_TESTS = "0"
$env:PDF_AGENT_RUN_PAID_TESTS = "0"
$env:PDF_AGENT_RUN_CACHE_API_TESTS = "0"
$env:PDF_AGENT_RUN_POSTGRES_TESTS = "0"
$env:DEEPSEEK_API_KEY = "offline-test-placeholder"
$env:HF_HUB_OFFLINE = "1"
python -B -m unittest discover -s tests -v
python -B -m evaluation.runner --mode routing --output evaluation-report.json
python -B -m evaluation.runner --mode live --case source-citations --output evaluation/reports/live-source.json
```

POSIX shell 可先 `export PDF_AGENT_RUN_LOCAL_PDF_TESTS=0 PDF_AGENT_RUN_PAID_TESTS=0 PDF_AGENT_RUN_CACHE_API_TESTS=0 PDF_AGENT_RUN_POSTGRES_TESTS=0 DEEPSEEK_API_KEY=offline-test-placeholder HF_HUB_OFFLINE=1`，再执行相同 Python 命令。Source 示例限定当前受控数据集和确定性路径，不可把任意 `live` 命令视为免费。

单文件回归示例：`python -B -m unittest discover -s tests -p test_observability.py -v`。用例按行为选择：

| 改动 | 最少应覆盖 |
| --- | --- |
| Graph/Planner/状态 | `test_agent_fast_paths.py`、`test_evaluation.py`、routing，以及所改分支的失败回归 |
| SQLite/FAISS 生命周期 | `test_session_lifecycle.py`，补充受影响的并发/故障测试；现有测试未完整覆盖这些风险 |
| 提示词/缓存/价格 | `test_prompt_cache.py`、`test_cache_probe.py`、`test_observability.py`、`test_pricing.py`、`test_localized_pricing.py` |
| Evaluation/Judge | `test_evaluation.py`、`test_evaluation_usage.py`、`test_real_pdf_evaluation.py`；保持参考证据隔离 |
| API/SSE/前端契约 | 前后端相关测试及构建；目前需按改动补充 HTTP/SSE/浏览器场景，不能只靠类型检查 |

前端（从根目录进入 `frontend`，依赖已安装）：

```text
cd frontend
npm test
npm run build
```

只检查应用 TypeScript 而不构建产物可用 `node node_modules/typescript/bin/tsc --project tsconfig.app.json --noEmit --incremental false`；这不能替代包含 Vite 配置检查及打包的完整 build。仓库目前没有 lint 命令或覆盖率门槛，不应虚构。

## PostgreSQL 连接集成测试（T15a）

`test_db_config.py` 和 `test_postgres_connection.py` 中的安全入口测试默认离线运行。7 项真实 PostgreSQL 连接测试默认跳过，不计为通过。先按 [开发文档](DEVELOPMENT.md#postgresql-迁移开发环境t15a) 启动独立 PG17 测试库并设置 TEST_DATABASE_URL，再在关闭付费开关的终端执行：

```powershell
$env:PDF_AGENT_RUN_POSTGRES_TESTS = "1"
try {
    python -B -m unittest discover -s tests -p test_postgres_connection.py -v
} finally {
    $env:PDF_AGENT_RUN_POSTGRES_TESTS = "0"
}
```

测试只接受显式 TEST_DATABASE_URL、回环地址（127.0.0.1/::1/localhost）及 `_test` 后缀库名，不读取 DATABASE_URL 作 fallback，不自动读 `.env`。启用但缺 URL、连接失败或版本不是 PG17 时直接失败；需保留这些失败为错误，不能捕获后跳过。不要通过端口转发将回环地址连接到生产库。

覆盖 UTC、commit/rollback、连接归还、池耗尽超时、线程各自持连接、pre_ping 替换失效连接、中断事务不重放和拒绝连接。用临时表，不创建/删除业务表；断连注入仅终止本测试打开的 backend PID，测试用户需能终止自己的连接。它不是 schema/CRUD/TTL/导入验收，后续 T15b–T15f 扩展。当前 CI 仍只跑默认离线部分，PG 集成 job 留给 T15e。

## 真实 PDF：不调用付费模型

准备 [pdf_manifest.json](../evaluation/pdf_manifest.json) 指定文件：`language-models.pdf`、`N19-1423.pdf`、`NIPS-2017-attention-is-all-you-need-Paper.pdf`。文件名、页数与 SHA-256 必须匹配；引文页码是一基物理页，不是论文印刷页码。建议放仓库外或已忽略的 `evaluation/pdfs/`，不要提交原 PDF、提取文本或索引。

```text
python -m evaluation.runner --mode real-pdf --pdf-dir "C:/path/to/pdfs" --validate-only
python -m evaluation.runner --mode real-pdf --pdf-dir "C:/path/to/pdfs" --retrieval-only
python -m evaluation.runner --mode real-pdf --pdf-dir "C:/path/to/pdfs" --case real-source-attention --output evaluation/reports/real-source.json
```

`validate-only` 不建 Embedding；`retrieval-only` 使用 BGE-M3 与 pgvector、统一 `k=4` 做诊断，需要指向隔离测试库的 `DATABASE_URL`。它不等同于各 Specialist 的检索策略，也不执行生成。Source 示例运行真实工作流但无 LLM；不代表生成式 RAG 全部通过。离线运行需先缓存模型，再设 `HF_HUB_OFFLINE=1`。离线恢复测试另安装 `requirements.migration.txt` 并设置 `PDF_AGENT_RUN_LEGACY_RECOVERY_TESTS=1`。

本地集成测试（在默认测试终端、其余付费开关仍为 0）：

```powershell
$env:PDF_AGENT_EVAL_PDF_DIR = "C:/path/to/pdfs"
$env:PDF_AGENT_RUN_LOCAL_PDF_TESTS = "1"
try {
    python -m unittest discover -s tests -p test_real_pdf_evaluation.py -v
} finally {
    $env:PDF_AGENT_RUN_LOCAL_PDF_TESTS = "0"
}
```

## 付费测试：获得具体授权后单独执行

在另一个终端设置有效的后端 Key，并明确测试数据、用例、调用数量/预算和报告路径。不要在 CI 默认启用，也不要把它们接到普通检查脚本。

```text
python -m evaluation.runner --mode real-pdf --pdf-dir "C:/path/to/pdfs" --case real-qa-attention-scaling --allow-paid-api --llm-judge --output evaluation/reports/paid-rag.json
python -m evaluation.cache_probe --pdf-path "C:/path/to/pdfs/N19-1423.pdf" --page 3 --attempts 3 --allow-paid-api --output evaluation/reports/cache-probe.json
```

前一命令含 Agent 与 Judge，调用数随路由/协作而变化，并非一次。缓存探针最多三次（此示例），失败会提前停止；每次输出 hit/miss/input Token 和命中率。模型服务异步缓存不保证正命中率。

若需要执行 unittest 包装的真实 API 测试，分别设置以下开关，执行后立即恢复为 0；开关相互独立：

```powershell
$env:PDF_AGENT_EVAL_PDF_DIR = "C:/path/to/pdfs"
$env:PDF_AGENT_RUN_PAID_TESTS = "1"
try {
    python -m unittest discover -s tests -p test_real_pdf_evaluation.py -v
} finally {
    $env:PDF_AGENT_RUN_PAID_TESTS = "0"
}

$env:PDF_AGENT_CACHE_PDF_PATH = "C:/path/to/pdfs/N19-1423.pdf"
$env:PDF_AGENT_RUN_CACHE_API_TESTS = "1"
try {
    python -m unittest discover -s tests -p test_cache_probe.py -v
} finally {
    $env:PDF_AGENT_RUN_CACHE_API_TESTS = "0"
}
```

真实 RAG unittest 的报告位于临时目录并在结束后清理；需要留存报告时使用上面的 CLI。缓存 unittest 默认保存到 `evaluation/reports/cache-probe.json`。

**既有边界：** real-pdf 生成/Judge 与缓存探针要求 `--allow-paid-api`；controlled `--mode live --llm-judge` 或含生成的 live 用例只检查 Key，没有同样的显式付费开关。因此禁止将“live”误认为免费；统一防误调用仍是 [T03](../plans/TASKS.md#t03) 待办。付费相关环境变量不是 CLI 的统一防护开关。

## 报告解释与 CI

- controlled 与 real-pdf 数据集分离；默认真实报告写入已忽略的 `evaluation/reports/`，可用 `--output` 指定。自定义路径应检查忽略规则与隐私。
- 每 Case 与 summary 有 `agent_usage`、`judge_usage`、`total_usage`，保留兼容 `usage` 及 by_model/by_operation。Judge 失败保留状态和已记录用量；未知成本不等于免费。
- validation/retrieval 报告 `passed: null`、质量未评估；普通无 Judge 的报告只有结构指标。引用 precision/recall 基于集合匹配，不能推导语义正确。
- 真实 PDF 的 30 条参考用例含事实、引文与禁用主张，`human_verified` 当前为 false。程序核对原文不替代人工语义复核；Judge 通过也不自动把参考升级为 Ground Truth。
- CLI 非零退出可能是阈值未达标或配置/执行错误，需查看报告；跳过不能算通过。

[CI](../.github/workflows/ci.yml) 在 main push/PR 和手动触发时运行 Python 3.11 unittest、routing、Node 22 build/test，再构建 Docker 镜像（`push: false`）。默认不运行真实 PDF/付费测试，不运行容器健康检查；当前也未上传评估报告为 CI artifact。

历史验证证据：2026-11-16 上一阶段只读审计在 `4d4e55b` 上记录后端 69 项（66 通过、3 个 opt-in 跳过），前端 6 项通过、应用 TS noEmit 通过、routing 9/9 且零 LLM 调用。这不是本次文档变更的重新执行结果，也不包含前端完整 build、真实 PDF 生成、付费 API、Docker 运行或线上负载验证。本阶段纯文档验收只检查内容、链接、命令与改动范围。
