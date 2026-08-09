# 领域模型与接口契约

## 1. 契约约定

本文是开发前契约草案。实现后应由 OpenAPI、JSON Schema 和数据库迁移成为可执行事实来源。

- ID 使用带类型前缀的不透明字符串，如 `inc_...`、`evd_...`、`plan_...`。
- 时间使用 UTC RFC 3339，如 `2026-08-01T08:30:00Z`。
- 枚举值使用大写英文，API 字段使用 `snake_case`。
- 所有可变契约携带 `schema_version`；场景、Runbook 和策略使用不可变版本。
- 自然语言结论不能替代结构化字段。

## 2. 事故状态机

规范状态：

```text
DETECTED
-> TRIAGING
-> DIAGNOSING
-> PLAN_PROPOSED
-> AWAITING_APPROVAL
-> EXECUTING
-> VERIFYING
-> RESOLVED | ESCALATED | FAILED
```

| 当前状态 | 允许进入 | 触发条件 |
| --- | --- | --- |
| `DETECTED` | `TRIAGING` | 告警通过校验并完成去重 |
| `TRIAGING` | `DIAGNOSING`, `ESCALATED`, `FAILED` | 初始上下文完整；或无法确定范围；或系统错误 |
| `DIAGNOSING` | `DIAGNOSING`, `PLAN_PROPOSED`, `VERIFYING`, `ESCALATED`, `FAILED` | 继续调查；证据足够且需动作；自动恢复/无需动作；预算耗尽/证据不足；系统错误 |
| `PLAN_PROPOSED` | `AWAITING_APPROVAL`, `ESCALATED`, `FAILED` | 计划通过 Schema/策略；无需/不允许动作；校验失败 |
| `AWAITING_APPROVAL` | `EXECUTING`, `ESCALATED`, `FAILED` | 批准；拒绝/过期；系统错误 |
| `EXECUTING` | `VERIFYING`, `FAILED` | 动作返回可验证结果；执行失败且不能安全重试 |
| `VERIFYING` | `RESOLVED`, `ESCALATED`, `FAILED` | SLO 恢复；未恢复需人工；验证系统失败 |

终态不可重新打开。新的相关告警创建新 Incident，并通过 `related_incident_ids` 关联。

## 3. 核心实体

| 实体 | 必需字段摘要 |
| --- | --- |
| `ScenarioDefinition` | `id`, `version`, `fault_type`, `target`, `expected_root_cause`, `expected_evidence`, `allowed_actions`, `recovery_assertions`, `cleanup` |
| `ExerciseRun` | `id`, `scenario_ref`, `environment_id`, `status`, `started_at`, `finished_at` |
| `Incident` | `id`, `status`, `severity`, `service`, `alert_fingerprint`, `workflow_id`, `opened_at`, `closed_at` |
| `IncidentOverview` | `environment`, `impact`, `top_hypothesis`, `next_decision`, `active_approval`, `latest_verification`, `capabilities`, `milestones` |
| `Evidence` | `id`, `incident_id`, `type`, `source`, `query`, `time_range`, `summary`, `content_hash`, `source_ref` |
| `Hypothesis` | `id`, `statement`, `confidence`, `supporting_evidence_ids`, `contradicting_evidence_ids`, `status` |
| `DiagnosticStep` | `id`, `tool`, `typed_parameters`, `result_ref`, `duration_ms`, `status`, `error_code` |
| `Runbook` | `id`, `version`, `action_type`, `parameter_schema`, `risk_level`, `rollback` |
| `RemediationPlan` | `id`, `incident_id`, `runbook_ref`, `risk_level`, `policy_version`, `target`, `parameters`, `rationale`, `evidence_ids`, `plan_hash` |
| `ApprovalRequest` | `id`, `plan_hash`, `risk_level`, `expires_at`, `status`, `nonce`, `max_executions` |
| `ApprovalDecision` | `request_id`, `approver_id`, `decision`, `reason`, `decided_at` |
| `ActionExecution` | `id`, `idempotency_key`, `approval_id`, `before_state`, `after_state`, `status` |
| `VerificationResult` | `id`, `metric`, `baseline_window`, `observed_window`, `threshold`, `passed` |
| `TimelineEvent` | `id`, `incident_id`, `actor_type`, `event_type`, `payload_ref`, `occurred_at` |
| `EvalResult` | `run_id`, `dataset_version`, `root_cause_match`, `timings`, `recovery`, `safety`, `cost` |

### 当前 light 场景契约

`ScenarioDefinition` 与嵌套 `FaultInjection` 在当前实现中为冻结、拒绝未知字段的 Pydantic 模型。场景引用固定为 `name@version`，`id` 必须与名称一致，版本不一致会拒绝加载；`RootCauseCategory` 只接受场景目录列出的六类规范值。`cleanup_command` 只是由隔离 Scenario Runner 消费的非可信元数据，Control API、Worker 与模型均不会执行它。

该契约不替代 full profile 的 ExerciseRun 持久化、目标 UID 校验或真实注入/cleanup 生命周期。

### Evidence 类型

- `METRIC`: PromQL 查询、范围和结果引用。
- `LOG`: Loki 查询、范围、脱敏摘要和内容 hash。
- `TRACE`: trace/span ID、关键路径与异常摘要。
- `K8S_STATE`: 资源类型、namespace、name、UID、generation/resourceVersion 和只读状态。
- `DEPLOYMENT_CHANGE`: 已知发布事件或版本差异。

Evidence 保存可验证来源，不把全部原始遥测复制进领域数据库。

## 4. 修复计划示例

```json
{
  "schema_version": "1.0",
  "id": "plan_example",
  "incident_id": "inc_example",
  "runbook_ref": "restart_deployment@1",
  "risk_level": "R1",
  "target": {
    "namespace": "demo-shop",
    "kind": "Deployment",
    "name": "inventory-api",
    "uid": "example-uid",
    "observed_generation": 7,
    "resource_version": "example-resource-version"
  },
  "parameters": {
    "timeout_seconds": 120
  },
  "rationale": "inventory-api 持续 5xx 与旧进程锁存状态在同一时间窗口出现，新进程不会继承。",
  "evidence_ids": ["evd_metric_example", "evd_trace_example"],
  "policy_version": "policy@1",
  "plan_hash": "sha256:example-only"
}
```

`plan_hash` 基于规范化后的 `incident_id + runbook_ref + risk_level + policy_version + target(namespace/kind/name/uid/observed_generation/resource_version) + parameters` 计算。任何受绑定字段变化都必须重新申请审批；Gateway patch 使用审批时的 resourceVersion 做乐观前置校验。

## 5. API 草案

统一前缀拟议为 `/api/v1`。

| 方法与路径 | 角色 | 行为 |
| --- | --- | --- |
| `POST /alerts` | alert source | 校验、去重并创建/关联 Incident |
| `GET /incidents` | viewer+ | 按状态、服务、时间筛选事故 |
| `GET /incidents/{id}` | viewer+ | 返回事故读模型 |
| `GET /incidents/{id}/timeline` | viewer+ | 返回游标分页时间线 |
| `GET /incidents/{id}/stream` | viewer+ | 通过 SSE 推送新时间线事件 |
| `POST /incidents/{id}/commands` | responder+ | 提交明确、幂等、按状态校验的调查/升级命令 |
| `POST /approval-requests/{id}/decisions` | approver | 原子地批准或拒绝一次请求 |
| `POST /exercise-runs` | scenario_operator | 启动固定版本场景 |
| `POST /exercise-runs/{id}/cleanup` | scenario_operator | 幂等清理故障 |
| `GET /exercise-runs/{id}/report` | viewer+ | 获取本次演练评测与产物引用 |

Action Gateway 使用独立内部 API，不从浏览器暴露：

| 方法与路径 | 调用者 | 行为 |
| --- | --- | --- |
| `POST /internal/v1/actions:execute` | Incident Worker | 校验审批和策略并幂等执行 |
| `GET /internal/v1/actions/{id}` | Incident Worker | 查询执行状态与 before/after 引用 |

## 6. 领域事件

事件至少包含 `event_id`、`event_type`、`schema_version`、`incident_id`、`occurred_at`、`actor`、`correlation_id` 和类型化 `payload`。

初始事件集合：

- `incident.detected`
- `incident.status_changed`
- `diagnostic.started`
- `diagnostic.completed`
- `hypothesis.updated`
- `remediation.proposed`
- `approval.requested`
- `approval.decided`
- `action.rejected`
- `action.started`
- `action.completed`
- `verification.completed`
- `incident.closed`
- `evaluation.completed`

MVP 使用数据库 outbox + SSE 投影，不因事件名称存在就提前引入消息队列。HTTP、SSE、幂等、分页和事件投递语义见 [API 契约](api-contracts.md)，事务与去重见 [数据模型](data-model.md)。

## 7. 跨实体不变量

- 每个 Incident 只有一个有效 Workflow ID。
- 一个 `plan_hash` 同时最多存在一个有效 ApprovalRequest。
- ApprovalDecision 只允许从 `PENDING` 原子转换一次。
- 执行时计划、目标 UID、observedGeneration、resourceVersion 和策略必须仍与审批绑定值一致。
- `idempotency_key` 全局唯一；重复请求返回原结果，不再次执行。
- R0 不对演练环境产生外部副作用，但仍写 Evidence/Timeline 审计；R1 必须审批；R2 在 MVP 禁用；R3 永久拒绝。
- 时间线只追加，不允许应用角色更新或删除既有事件。
- `RESOLVED` 必须有通过的 VerificationResult；API 成功不等于恢复成功。

## 8. 错误契约

错误返回稳定 `code`、人类可读 `message`、`correlation_id` 和可选 `details`，不返回堆栈或敏感内容。关键错误码：

- `INVALID_TRANSITION`
- `SCHEMA_VALIDATION_FAILED`
- `POLICY_DENIED`
- `APPROVAL_REQUIRED`
- `APPROVAL_EXPIRED`
- `PLAN_HASH_MISMATCH`
- `TARGET_STATE_CHANGED`
- `IDEMPOTENCY_CONFLICT`
- `INVESTIGATION_BUDGET_EXCEEDED`
- `SCENARIO_NOT_CLEAN`

## 9. 版本兼容

- API 破坏性变更通过路径版本升级。
- 事件消费者至少兼容当前和前一 `schema_version`。
- Scenario/Runbook 发布后不可原地修改，只能创建新版本。
- 评测报告必须固定 dataset、scenario、policy、prompt 和模型版本，缺一项则不能与 baseline 比较。

## 10. 详细契约导航

- [API 契约](api-contracts.md)：认证、端点、幂等、并发、SSE 和内部 Action API。
- [数据模型](data-model.md)：物理表、约束、事务、outbox、审计与保留。
- [Workflow 设计](workflow-design.md)：Temporal 状态推进、Signal、Activity、重试与协调。
- [LLM 与工具协议](llm-and-tooling-protocol.md)：调查循环、工具模板、Evidence 和预算。
- [Runbook 规范](runbook-specification.md)：ActionExecution 状态、审批绑定和两种 R1 动作。
