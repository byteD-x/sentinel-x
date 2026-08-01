# 术语与命名规范

## 1. 使用规则

本文件是 Sentinel-X 业务术语、状态和命名的唯一解释来源。代码、API、事件、界面和报告必须使用这里的规范词；新增同义词前先判断是否确有不同语义。

## 2. 核心业务术语

| 规范名称 | 中文解释 | 不应混用的概念 |
| --- | --- | --- |
| `ScenarioDefinition` | 一个不可变版本的故障演练定义，包含注入、标准答案、允许动作、恢复断言和清理 | 不是一次实际运行 |
| `ExerciseRun` | 某个场景版本在某个环境中的一次执行 | 不等同 Incident；可能在告警前失败 |
| `FaultInjection` | 本次运行实际施加的故障及其撤销状态 | 不等同根因文本 |
| `Incident` | 由告警创建、由 Workflow 推进的事故记录 | 不等同告警本身 |
| `Evidence` | 带来源、查询和时间范围的可验证证据 | 摘要不能替代原始引用 |
| `DiagnosticStep` | 一次类型化只读工具调用及其结果 | 不允许包含写操作 |
| `Hypothesis` | 对根因的结构化假设，带置信度和支持/反对证据 | 不是最终事实或执行授权 |
| `RemediationPlan` | 基于已登记 Runbook 生成的类型化动作提案 | 不是自由文本脚本 |
| `Runbook` | 经评审、版本化、参数有界的动作定义 | 不允许运行时即时生成 |
| `ApprovalRequest` | 对固定 `plan_hash`、目标和参数的审批请求 | 不等同通用操作许可 |
| `ApprovalDecision` | 审批者对一次请求的不可变决定 | 批准后不能修改计划 |
| `ActionExecution` | Action Gateway 对一次已授权动作的执行记录 | API 2xx 不代表恢复成功 |
| `VerificationResult` | 基于明确 SLI、窗口和阈值的恢复判定 | 不使用主观“看起来正常” |
| `TimelineEvent` | 只追加的事故事实事件 | 不作为任意日志存储 |
| `EvalResult` | 在固定数据集和配置下产生的评测结果 | 不能跨版本直接比较 |
| ground truth | 场景预先登记的主要根因、目标和预期证据 | 不由被测模型生成或修改 |
| investigation budget | 一次调查允许的最大步骤、时长、Token、查询窗口和结果大小 | 不是计费配额 |
| dirty environment | 故障或临时变更未被确认清理的演练环境 | 该状态下禁止下一次 benchmark |

## 3. 系统组件名称

| 名称 | 规范职责 |
| --- | --- |
| Web Console | 面向查看、调查、审批和回放的浏览器界面 |
| Control API | 对外 HTTP/SSE、鉴权和领域读写入口 |
| Alert Ingress | 告警校验、指纹去重和 Incident 创建模块 |
| Incident Workflow | Temporal 中事故流程的唯一推进者 |
| Incident Worker | 承载 Workflow 与 Activities 的进程 |
| Investigator | 使用 LLM 和只读工具生成假设与计划的 Activity 集合 |
| Diagnostic Gateway | PromQL、Loki、Tempo、Kubernetes 只读查询适配层 |
| Action Gateway | 独立最小权限动作校验与执行服务 |
| Scenario Runner | 固定故障的注入、自检和清理执行器 |
| Evaluator | 离线计算根因、时延、恢复、安全和成本指标 |

“控制面”包含 Web Console、Control API、Worker 和 Action Gateway；“演练环境”指 `demo-shop` 及其故障注入组件。不要用“数据面”指代遥测存储，以免与业务请求流混淆。

## 4. 规范状态

事故只使用以下状态：

`DETECTED`、`TRIAGING`、`DIAGNOSING`、`PLAN_PROPOSED`、`AWAITING_APPROVAL`、`EXECUTING`、`VERIFYING`、`RESOLVED`、`ESCALATED`、`FAILED`。

详细转换见 [领域模型与接口契约](domain-model-and-contracts.md)。界面可显示中文翻译，但 API、事件、数据库和报告必须保存英文枚举：

| 枚举 | 界面中文 |
| --- | --- |
| `DETECTED` | 已发现 |
| `TRIAGING` | 分诊中 |
| `DIAGNOSING` | 调查中 |
| `PLAN_PROPOSED` | 已提出方案 |
| `AWAITING_APPROVAL` | 等待审批 |
| `EXECUTING` | 执行中 |
| `VERIFYING` | 验证恢复中 |
| `RESOLVED` | 已恢复 |
| `ESCALATED` | 已升级人工 |
| `FAILED` | 系统失败 |

`ESCALATED` 表示系统正确停止并交给人工，不应一律显示为产品错误；`FAILED` 表示平台流程自身无法完成。

## 5. 风险与权限词汇

- `R0`：只读、无副作用的查询，可自动执行但受预算和审计约束。
- `R1`：单服务、可逆、参数有界的动作，必须人工审批。
- `R2`：数据库、发布回滚或跨服务动作，MVP 禁用并升级人工。
- `R3`：任意 Shell、`pods/exec`、Secrets 或集群级动作，永久禁止。
- approval：授权某个固定 plan，不是给 Agent 扩权。
- policy denial：确定性策略拒绝；不能由模型重写措辞后重试绕过。
- kill switch：阻止新的 R1 执行，不影响只读查看和必要场景清理。

## 6. 可观测性词汇

- SLI：从数据源计算的服务质量指标。
- SLO：SLI 在时间窗口内应达到的目标，不等同 SLA。
- alert condition：用于创建告警的条件，通常短于产品 SLO 窗口。
- baseline window：故障前用于比较的稳定窗口。
- observed window：动作后用于验证恢复的窗口。
- trace correlation：通过 `trace_id`、`span_id`、`request_id` 和 `exercise_run_id` 关联信号。
- evidence summary：经过脱敏和长度限制的摘要，不是原始日志全文。

## 7. 命名规范

- API 和 JSON 字段：`snake_case`。
- Python 包/函数：`snake_case`；类与 Pydantic model：`PascalCase`。
- TypeScript 变量/函数：`camelCase`；组件和类型：`PascalCase`。
- 数据库表：复数 `snake_case`；主键 `id`；外键 `<entity>_id`。
- 事件：小写过去时领域事实，如 `approval.decided`。
- 指标：`sentinel_<subsystem>_<measurement>_<unit>`，counter 以 `_total` 结尾。
- Runbook：`<verb>_<resource>@<version>`，例如 `restart_deployment@1`。
- 场景：`<service>-<fault>@<version>`，例如 `payment-pod-crash@1`。

## 8. 禁止性表述

没有可追溯报告前，禁止使用“生产级”“全自动修复”“准确率达到”“显著降低 MTTR”“零风险”等结论。推荐使用：

- “拟议使用”表示尚未通过 M0 决策。
- “目标”表示有明确定义但未实测的门槛。
- “本次运行观测到”表示只适用于指定报告和样本。
- “MVP 禁用”表示契约拒绝，而不是暂时没有按钮。
