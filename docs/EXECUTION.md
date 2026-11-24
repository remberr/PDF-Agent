# 执行终态与传输契约

T06（2026-11-24）经批准增量扩展。JSON `/ask` 与 SSE `/ask/stream` 共用执行器；原响应字段、`progress`/`result` 事件名及 progress 的 `running/completed/failed` 枚举保留。HTTP 200 表示已交付结果，不代表生成和保存都成功。不增加自动重试、恢复重放或模型修复调用。

## 最终结果 execution

| 字段 | 含义 |
| --- | --- |
| `generation_status` | `succeeded`：完整生成且无节点降级；`degraded`：有可用输出，但规划/专业节点/协作/审阅发生回退或部分失败；`failed`：全部专业输出失败、Graph 异常、空回答或未完成工作流；`cancelled`：观察到取消 |
| `status` | 初值等于 generation_status；保存失败覆盖为 failed。只有生成成功且保存成功才是完全成功 |
| `persistence` | saved：保存函数完成提交；failed：保存抛异常，不能承诺写入成功；not_attempted：观察到取消后未开始保存 |
| `reason` | 无问题为 null；否则为受控代码，不含供应商正文。保存失败时优先为 persistence_failed，生成节点的原因仍在 node_statuses |
| `node_statuses` | 节点名到 `{status, reason}` 的映射；节点 status 为 running/succeeded/degraded/failed/cancelled/skipped。缺失表示未观察到该节点，不推断为成功 |

当前原因包括 specialist_failed、empty_answer、model_unavailable、model_timeout、invalid_model_output、collaboration_failed、reviewer_failed、workflow_error、incomplete_workflow、budget_exhausted、deadline_exceeded、paid_api_disabled、cancelled、persistence_failed，以及无更细原因时的 node_failed。原因描述过程状态，不评判回答事实是否正确。

节点完成后记录实际 outcome；仅 succeeded 节点进入 completed_nodes。progress 增加 node_statuses 快照，正在执行的节点标为 running；degraded/failed/cancelled 沿用原 progress failed，由快照区分细节。Planner 快路径、单专业节点审阅快路径、Source 零模型及最多一次补充步骤不变。

正常传输最终产生一个 result。空/截断 Graph 不生成假成功；保存失败仍交付已生成回答、usage 和失败元数据，不重新生成。保存使用候选消息快照，失败不把候选消息留在原会话对象中。提交时连接中断可能导致提交结果不确定，因此 failed 不能等同于数据库肯定没有写入；不自动重放，保留既有批次幂等约束。

## 取消与资源生命周期

关闭事件迭代器或 HTTP 断连取消 T03 同一预算，阻止后续派发并关闭 Graph 迭代器。尚未开始的保存不执行；已开始/已提交的事务无法撤回。在途同步 SDK/线程不保证即时中断，迟到供应商 usage 仍由原 Tracker 结算。断开的客户端不保证收到 result，客户端 EOF 无完整终态必须视为中断，禁止自动重发付费生成请求。T05a已补充[SQL等待及在途租约](LOCAL_STORAGE.md#在途与sql边界t05a)，池等待和在途SDK仍有独立边界。

## 兼容范围

新增字段不删除、改名或改变既有字段类型。旧客户端可以忽略新增字段，但仍可能误把失败结果当成成功；T07 已提供相应 UI 与显式取消/恢复处理。拒绝额外字段的严格客户端应升级响应 Schema。Python AskResponse 接受旧 payload 缺失 execution（默认 null）；这仅为数据兼容，不代表旧 payload 已验证成功。新服务器生成的最终结果总是包含 execution。

验证入口见 [TESTING.md](TESTING.md)，进度和未执行验证见 [TASKS.md](../plans/TASKS.md)。


## 前端消费（T07）

apiRequest从unknown校验结果与会话结构，ApiError保留HTTP状态；404、5xx、网络失败不再混为会话丢失。SSE在拼接字节后归一化CRLF，校验完整帧，EOF无完整result报中断；单帧2,000,000字符上限，result完成即取消/释放reader，不等无限EOF。取消保留AbortError并终止reader；不重发请求。缺execution的旧payload可读，但显示未确认，不把所有节点推定为完成。

App按RequestScope忽略陈旧回调；上传、恢复、问答及新会话切换有AbortSignal。取消仅影响当前问答，不删除已有结果；点击新会话仍沿用原来经用户交互确认后创建/删除旧会话的行为。暂时恢复失败保留本地历史，提供仅GET的连接重试，不重发生成。404仅失效会话入口，恢复时保留旧对话缓存；localStorage异常不阻断当前页面，但刷新恢复可能不可用。浏览器组件挂载和真实网络中断尚未E2E验证。
