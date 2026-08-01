# 受控 Runbook 规范

## 1. 目标

Runbook 把“建议做什么”约束成可审计、参数有界、可验证的动作。MVP 只允许两个 R1 Runbook；模型不能创建、修改或直接执行 Runbook。

场景清理由 Scenario Runner 负责，不是 Runbook，也不使用事故审批凭证。详细责任边界见 [场景目录](scenario-catalog.md)。

## 2. 生命周期与版本

```text
DRAFT -> REVIEWED -> ACTIVE -> DEPRECATED -> RETIRED
```

- 只有 `ACTIVE` 版本能进入新 RemediationPlan。
- 已发布版本不可原地修改；参数、前置、动作或验证变化都提升版本。
- `DEPRECATED` 可完成已批准且未过期的请求，是否允许由 policy 明确决定。
- `RETIRED` 永不执行，历史记录仍可解析。

激活至少需要平台/安全评审、Schema 测试、最小权限测试、幂等测试、失败协调测试和场景 E2E。

## 3. 定义契约

每个 Runbook 必须包含：

```yaml
id: restart_deployment
version: 1
status: ACTIVE
risk_level: R1
target_selector: {}
parameter_schema: {}
preconditions: []
execution: {}
success_conditions: []
failure_conditions: []
rollback: {}
timeouts: {}
idempotency: {}
required_evidence: []
audit_fields: []
```

约束：

- Schema 使用 allowlist 并拒绝额外字段。
- 目标必须包含 namespace、kind、name、UID 和 generation/resourceVersion。
- 参数是机器可验证值，不接受命令、脚本、模板表达式或自由 URL。
- `risk_level` 是 Runbook 固定上限；策略可以提高风险，不能降低。
- `required_evidence` 只决定是否能提出计划，不等同审批通过。

## 4. 计划与审批绑定

RemediationPlan 只能引用 `runbook_id@version`，并生成规范 `plan_hash`。审批至少绑定 incident、Runbook、risk、目标身份、规范参数、policy version、审批者、过期时间、nonce 和最大执行次数。

以下变化使审批失效：

- Runbook/策略版本变化。
- namespace、kind、name、UID、generation/resourceVersion 变化。
- 参数、超时、目标副本数或动作类型变化。
- Incident 进入不允许执行的状态。
- kill switch 启用、审批撤销/过期/已消费。

## 5. Action Gateway 通用执行协议

1. 认证 Incident Worker 服务身份并检查 audience。
2. 严格解析请求，拒绝额外字段。
3. 读取 ACTIVE Runbook 和 policy，不信任请求中的风险结论。
4. 校验审批完整性、`plan_hash`、nonce、过期和使用次数。
5. 使用只读调用重新获取目标身份、当前状态和前置条件。
6. 在事务中以 `idempotency_key` 原子登记执行；冲突返回原执行引用。
7. 保存脱敏 before state。
8. 使用官方 Kubernetes Client 执行唯一允许操作。
9. 通过轮询/Watch 协调最终结果，保存 after state。
10. 追加审计事件并返回稳定状态；业务恢复由 Incident Workflow 另行验证。

Action Gateway 不持有 LLM 密钥，不调用 Shell/`kubectl`，不解释自然语言。

## 6. `restart_deployment@1`

### 语义

对目标 Deployment 写入由执行器生成的、不可由模型控制值的 restart annotation，使 Kubernetes 执行滚动重启。它不删除 Deployment、不修改镜像或业务配置。

### 参数

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `timeout_seconds` | integer | 30–180，默认目标值 120 |
| `max_unavailable` | integer | 固定由 policy 计算，模型不可提供 |

目标只允许 `demo-shop` namespace 中、Runbook allowlist 内的 Deployment。请求不能包含 annotation value、patch body 或 label selector。

### 前置条件

- Incident 为 `AWAITING_APPROVAL`，审批后由 Workflow 转入 `EXECUTING`。
- 目标 UID 与审批一致，generation 未漂移。
- Deployment 未暂停，期望副本在策略范围内。
- 当前没有同目标冲突 ActionExecution。
- 支持证据包含 `K8S_STATE`，且计划理由不是仅来自日志指令。

### 幂等与成功

- 幂等键由 `incident_id + plan_hash + execution_slot` 派生。
- 第一次执行生成固定 restart token 并保存；重试复用同一 token。
- Kubernetes patch 被接受只表示动作已提交。
- Runbook 层成功条件：观察到新 ReplicaSet/Pod 代次并达到目标 Ready 状态。
- 事故恢复条件仍由 [可观测性与 SLO](observability-and-slo.md) 判断。

### 失败与协调

- 目标漂移：`TARGET_STATE_CHANGED`，不执行。
- rollout 超时：ActionExecution `FAILED`，保留当前集群状态并升级人工。
- 网络超时且结果未知：进入 `RECONCILING`，读取 annotation/代次判断是否已提交，不能直接重复 patch。
- 新 Pods 不健康：不回滚镜像；停止并升级人工。

### 回滚

restart annotation 不需要反向 patch，Kubernetes 滚动过程不可“撤销”。失败时的安全补偿是停止重复动作、保存状态、恢复场景故障条件由独立 cleanup 处理并升级人工。

## 7. `scale_deployment@1`

### 语义

把目标 Deployment 从审批时的 before replicas 调整到一个有界目标。仅用于经场景和策略明确允许的单服务容量实验，不能用于依赖故障、数据库锁或坏版本修复。

### 参数

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `replicas` | integer | 1–5，且最多为 before + 2 |
| `timeout_seconds` | integer | 30–180 |
| `restore_after_seconds` | integer/null | 60–900；为空则事故结束后进入人工恢复队列 |

### 前置条件

- before replicas、UID 和 generation 与审批绑定。
- ResourceQuota 容纳目标副本，目标没有 HPA 或其他副本控制器冲突。
- 证据支持容量不足；对 R2 场景和依赖故障策略拒绝。
- 同目标没有未完成 scale/restart。

### 幂等、成功与恢复

- 相同幂等键重复执行返回原 ActionExecution。
- 当前 replicas 已是目标且 generation 符合时视为无副作用成功。
- Runbook 成功要求期望副本与 Ready 副本达到目标。
- 若配置自动恢复，恢复动作由同一已批准计划中的明确 compensation 触发，并验证目标仍未漂移。
- 业务 SLO 未恢复时 Incident 不能进入 `RESOLVED`。

### 失败

- Quota、调度或镜像拉取失败：不扩大目标，记录原因并升级人工。
- HPA/其他控制器出现：`POLICY_DENIED` 或 `TARGET_STATE_CHANGED`。
- 部分副本 Ready：超时后失败，不连续扩大副本。

## 8. ActionExecution 状态

```text
REGISTERED -> VALIDATING -> RUNNING -> RECONCILING
-> SUCCEEDED | REJECTED | FAILED | CANCELLED
```

- `REJECTED`：动作开始前的策略/审批/目标拒绝，无副作用。
- `FAILED`：执行或协调失败，可能需要人工确认集群最终状态。
- `CANCELLED`：仅在尚未提交副作用时可取消；已提交后转协调。
- 终态后相同幂等键只能读取原结果。

该状态机不替代 Incident 状态机；映射和重试协调见 [Workflow 设计](workflow-design.md)。

## 9. 审计字段

每次校验与执行记录：

- request/correlation/incident/plan/approval/action IDs。
- 调用方、策略和 Runbook 版本。
- 目标规范身份与 before/after hash。
- 每个 gate 的结果和稳定错误码。
- 幂等键 hash、开始/结束时间、尝试和协调次数。
- Kubernetes API verb/resource/response metadata，不记录凭据或完整 Secret-like 内容。

审计只追加，应用身份无 update/delete 权限。

## 10. 永久禁止

- 任意 Shell、命令参数、`kubectl`、`pods/exec`。
- 读取或写入 Secrets、ConfigMap 业务内容、数据库或文件系统。
- 自由 JSON Patch、任意 annotation/label、任意 URL callback。
- wildcard namespace/resource、动态 RBAC、`cluster-admin`。
- 根据模型置信度跳过审批或提高参数上限。
- 把 Scenario Runner 的 cleanup 凭据交给 Action Gateway。

## 11. 验收矩阵

- Schema：未知动作、字段、参数边界、目标类型全部拒绝。
- 审批：缺失、拒绝、过期、撤销、计划篡改、策略变化全部拒绝。
- 目标：UID/generation 漂移、跨 namespace、非 allowlist、HPA 冲突全部拒绝。
- 幂等：并发相同请求、网络超时、Worker 重启均只产生一次副作用。
- 权限：执行身份无法读取 Secrets、exec Pod、操作其他 namespace 或非白名单资源。
- 协调：Kubernetes 成功/拒绝/超时/结果未知/部分 Ready 均有确定终态。
- 恢复：Runbook 成功但 SLO 未恢复时事故升级人工。
- 审计：每个 gate、before/after 和拒绝原因都有可关联记录且无秘密。
