# HTTP、SSE 与内部动作 API 契约

## 1. 状态与事实来源

本文定义目标 API 语义和安全边界。当前仓库已有 light/prototype FastAPI 端点，但实现路径、请求体和安全门禁尚未完全收敛到本文：Control API 仍使用 `/api/...`，Action Gateway 仍使用 prototype `/api/actions`，正式 `/api/v1` 与 `/internal/v1`、浏览器会话/CSRF、TokenReview/DB 绑定审批等门禁仍属于未完成项。light Control API 用 `X-Sentinel-Role` 实现本地演示能力门控，不能作为认证；Alert Ingress 当前要求时间戳、nonce 和 HMAC，并在 local profile 使用有界 replay cache 拒绝同一 nonce 的重复请求；Action Gateway 已要求独立的不可变审批记录、目标 namespace/kind/name/UID/generation 和一次性消费，默认仍是进程内实现，配置 `SENTINEL_APPROVAL_STORE_DB` 后可使用 SQLite 持久记录并跨连接原子消费，但尚未达到 PostgreSQL 数据库绑定和跨服务事务门禁。light 场景启动会创建内存事故、证据和审批记录；批准后的执行/验证事件是 `light-fixture`，不代表真实 Kubernetes 写入。

实现收敛前，本文是目标契约；代码与测试只能证明 prototype 行为。完成 D1/D2 门禁后，版本化 OpenAPI、生成的 JSON Schema 和契约测试才成为执行事实来源；本文继续维护跨端点规则和设计理由。

公共前缀：`/api/v1`；内部 Action Gateway 前缀：`/internal/v1`。所有时间为 UTC RFC 3339，字段为 `snake_case`，未知 JSON 字段默认拒绝。

## 2. 身份与认证

### 2.1 浏览器会话

MVP 使用明确标注 `local-only` 的预置身份：服务端配置 viewer/responder/approver/scenario_operator 身份，开发登录页只能选择 allowlist 身份并创建短时、HttpOnly、Secure（HTTPS 时）、SameSite=Strict 会话 Cookie。

- 客户端不能通过 `X-User` 等 header 自报身份。
- 写请求要求同源检查和 CSRF token。
- 会话过期不自动重放写请求。
- 该机制不能宣传为生产认证；未来 OIDC 替换时保持角色/capability 契约。

### 2.2 Alert Ingress

Alertmanager 请求使用独立 HMAC 密钥和 headers：

- `X-Sentinel-Timestamp`
- `X-Sentinel-Signature: sha256=<hex>`

签名输入为 `timestamp + "\n" + nonce + "\n" + raw_body`。Control API 校验允许时钟偏差、常量时间比较、body 上限和 local profile 的有界 nonce 重放缓存。示例文档不提供真实密钥。

### 2.3 Worker 到 Action Gateway

服务身份与审批授权分离：

- Worker 使用 Kubernetes TokenRequest 签发的短时 projected ServiceAccount token，audience 固定为 `sentinel-action-gateway`。
- Gateway 通过 TokenReview 验证身份与 audience，并只接受 `incident-worker` ServiceAccount。
- 请求只携带 `approval_id`；Gateway 使用独立数据库权限读取并原子消费不可变审批记录，不接受 Worker 自带的“已批准”声明或共享审批 bearer。

该方案为 `proposed`，在 M0 安全 spike 后以 ADR 固定。

## 3. 公共 headers 与媒体类型

| Header | 方向 | 规则 |
| --- | --- | --- |
| `X-Request-ID` | request/response | 客户端可提供符合格式的 UUID；否则服务端生成 |
| `Idempotency-Key` | command request | 16–128 字符；同身份、路由和规范 body 绑定 |
| `If-Match` | conditional command | 使用资源 ETag，避免基于旧状态写入 |
| `X-CSRF-Token` | browser write | 与会话绑定 |
| `traceparent` | both | 按 W3C Trace Context 传播 |
| `Retry-After` | response | 限流、暂不可用或异步轮询建议 |

JSON 使用 `application/json`；SSE 使用 `text/event-stream`；错误仍返回 JSON。

## 4. 响应与错误

成功响应：

```json
{
  "data": {},
  "meta": {
    "request_id": "00000000-0000-0000-0000-000000000000",
    "schema_version": "1.0"
  }
}
```

错误响应：

```json
{
  "error": {
    "code": "PLAN_HASH_MISMATCH",
    "message": "审批绑定的计划与当前请求不一致。",
    "correlation_id": "00000000-0000-0000-0000-000000000000",
    "details": {}
  }
}
```

`details` 只放可安全展示的字段错误或当前资源版本，不返回堆栈、SQL、凭据、签名原文或内部地址。

| HTTP | 语义 |
| --- | --- |
| 400 | JSON/Schema/业务参数非法 |
| 401 | 未认证或服务 token 无效 |
| 403 | 角色/策略拒绝，如 R2/R3 |
| 404 | 资源不存在或调用方不可见 |
| 409 | 状态转换、幂等 body、审批决定或执行冲突 |
| 410 | 审批/游标已过期且不可恢复 |
| 412 | ETag、目标 UID/generation 前置不满足 |
| 422 | 结构正确但领域不变量失败 |
| 429 | 调查/请求预算或速率限制 |
| 503 | 必需依赖不可用 |
| 504 | 下游超时且结果已知未完成；结果未知使用异步协调 |

## 5. 分页、过滤和排序

- 集合使用不透明 cursor，不使用 offset 作为稳定翻页契约。
- 请求：`limit` 默认 50、最大 200；`cursor`；资源特定 filters。
- 响应 meta：`next_cursor`、`has_more`，不默认计算高成本 total。
- 默认排序必须稳定，追加 ID 作为最终 tie-breaker。
- cursor 绑定 filter/sort；修改条件后旧 cursor 返回 400。

## 6. 幂等与并发

- 所有创建/命令 POST 要求 `Idempotency-Key`，只读诊断由 Workflow 生成稳定 step key。
- 首次请求保存身份、路由、规范 body hash 和响应引用。
- 相同 key/body 返回原结果；相同 key/不同 body 返回 `IDEMPOTENCY_CONFLICT`。
- 处理中重复请求返回 202 和原 operation 引用。
- 资源更新使用 ETag/`If-Match`；ApprovalDecision 使用数据库唯一约束保证一次决定。
- 幂等记录的保留期至少覆盖 Workflow 最大重试/恢复窗口，目标值 7 天，待资源评审。

## 7. Alert API

### `POST /api/v1/alerts`

调用者：Alertmanager。请求是经过上限约束的 Alertmanager webhook 子集：

```json
{
  "schema_version": "1.0",
  "status": "firing",
  "alerts": [{
    "status": "firing",
    "labels": {
      "alertname": "DemoShopHighInventoryErrorRate",
      "service": "inventory-api",
      "severity": "critical",
      "environment": "local-demo",
      "scenario_id": "inventory-latched-5xx@1"
    },
    "annotations": {"summary": "inventory error ratio exceeded"},
    "starts_at": "2026-08-01T09:00:00Z",
    "ends_at": null
  }]
}
```

每个 alert fingerprint 为规范 labels `alertname|environment|service|normalized_target|scenario_id` 的 SHA-256。annotations、当前值、Pod 名和时间戳不参与。

行为：

- firing + 同 fingerprint 活跃 Incident：追加 `alert.repeated`，不新建 Workflow。
- firing + 无活跃 Incident：事务创建 Incident/初始 timeline/outbox；异步确保 Workflow 启动。
- resolved：追加关联事件但不直接把 Incident 设为 `RESOLVED`，仍需 VerificationResult。
- 同一 body 中错误 alert 单项拒绝并报告；整包认证/JSON 失败则整包拒绝。

响应 202，返回每项 `accepted|deduplicated|rejected` 和 Incident ID。

## 8. Incident API

### `GET /api/v1/incidents`

filters：`status[]`、`severity[]`、`service[]`、`awaiting_approval`、`exercise_run_id`、`started_after/before`。默认按需人工优先、`updated_at desc, id desc`。

### `GET /api/v1/incidents/{incident_id}`

返回事故读模型、当前 capabilities、top hypothesis、预算、活动 plan/approval/action、最新 VerificationResult 和 source freshness。ETag 为 projection version。

当前 light `GET /api/incidents/{incident_id}` 已在保留原顶层字段的基础上返回 `environment`、`impact`、`top_hypothesis`、`next_decision`、`active_approval`、`latest_verification`、`capabilities` 和按处置阶段折叠的 `milestones`。所有由内存演练事件生成的摘要显式标记 `source_mode=fixture`；light 响应尚无预算、真实 source freshness、ETag 或持久投影，不能视为正式 `/api/v1` 契约完成。

### `POST /api/v1/incidents/{incident_id}/commands`

调用者：responder。显式命令替代含糊的“启动调查”端点：

```json
{
  "command": "CONTINUE_INVESTIGATION",
  "reason": "补充查询最新恢复窗口",
  "expected_status": "DIAGNOSING"
}
```

MVP 命令：`CONTINUE_INVESTIGATION`、`ESCALATE_TO_HUMAN`、`CANCEL_PENDING_PLAN`。Control API 事务保存 command/outbox，dispatcher 使用 `command_id` Signal Workflow；重复 signal 在 Workflow 内去重。非法角色/状态返回 409/403。

## 9. Evidence、Timeline 与报告

- `GET /incidents/{id}/evidence`：按类型/时间分页，默认只返回摘要和 source_ref。
- `GET /incidents/{id}/hypotheses`：返回版本历史和支持/反对 Evidence IDs。
- `GET /incidents/{id}/timeline`：按 `(sequence, id)` 游标稳定分页。
- `GET /incidents/{id}/export`：异步生成脱敏事故包，返回 operation；viewer+ 可下载，包有 hash 和过期。

原始遥测链接必须经过 allowlist proxy 或打开已配置 Grafana/Tempo 来源，不能接受模型生成 URL。

## 10. SSE 契约

### `GET /api/v1/incidents/{id}/stream`

事件格式：

```text
id: 184
event: timeline.event
data: {"schema_version":"1.0","incident_id":"inc_example","sequence":184,"event_type":"hypothesis.updated","payload":{}}
```

规则：

- `id` 是 Incident 内单调递增 sequence；数据库事务分配，不使用时间戳。
- 客户端重连发送 `Last-Event-ID`；服务端从下一 sequence 补发。
- 每 15 秒发送 `event: heartbeat`，不推进业务 sequence。
- 单连接缓冲有上限；慢客户端断开并要求通过 REST 补拉。
- cursor 仍在保留期：补发后进入实时；已过期返回 410 和最早可用 sequence。
- 客户端按 `incident_id + sequence` 去重，发现 gap 立即暂停实时渲染并 REST 补齐。
- payload 不包含原始秘密、审批凭证或完整大 Evidence。

当前 light/prototype `GET /api/incidents/{id}/stream` 会发送 `id: <sequence>` 与 `event: timeline_event`，接受数值 `Last-Event-ID` 从下一序号补发；前端同时以 REST timeline 补读防止连接缺口。它没有数据库保留窗口、心跳或 410 过期语义，不能视为完整 SSE 契约实现。

## 11. Approval API

### `GET /api/v1/approval-requests`

approver 查看 `PENDING` 请求，可按过期时间、risk 和 service 筛选。

当前 light/prototype 实现提供 `GET /api/approvals?status=pending|all|approved|rejected|expired`，返回审批记录及其关联事故摘要，用于 Web Console 审批队列。`PUT /api/incidents/{incident_id}/approvals/{approval_id}` 要求 `X-Sentinel-Role: approver`，并校验审批与事故归属；该 header 仅用于 local-demo。端点尚未实现正式契约要求的认证、ETag、CSRF 和数据库持久化，不能视为 full profile 审批 API。

### `GET /api/v1/approval-requests/{id}`

返回规范 plan、目标、before state、证据摘要、policy/Runbook 版本、过期和 capabilities。响应带 ETag。

### `POST /api/v1/approval-requests/{id}/decisions`

```json
{
  "decision": "APPROVED",
  "reason": "证据支持锁存故障，目标和范围符合 R1。",
  "expected_plan_hash": "sha256:example-only"
}
```

- approver + CSRF + `Idempotency-Key` + `If-Match`。
- 事务锁定 request，重新检查 pending/expiry/revocation/hash/policy 状态，插入唯一 Decision 并追加 outbox。
- 已决定的相同 key 返回原决定；不同决定返回 409。
- Worker 收到 signal 后只使用 `approval_id`，Action Gateway 再独立读取和消费。

## 12. Exercise 与 Evaluation API

- `GET /scenarios`：返回版本、前置、profile、风险和最近自检，不向 Investigator 接口暴露 ground truth。
- `POST /exercise-runs`：scenario_operator 创建固定场景 run；环境 dirty/活跃 run/健康失败时 409。
- `GET /exercise-runs/{id}`：返回生命周期、注入记录、Incident 和 cleanup 状态。
- `POST /exercise-runs/{id}/commands`：仅 `CLEANUP`、`MARK_DIRTY`；与 AI action 通道完全分离。
- `GET /evaluations`、`GET /evaluations/{id}`：返回配置、可比性、聚合和产物 hash。

ground truth 端点仅 Evaluator 的内部身份可读，不由浏览器或 Investigator 访问。

### 当前 light 场景目录实现

当前 `GET /api/scenarios` 和 `POST /api/scenarios/{scenario_id}/run` 每次均从服务端固定的 YAML 目录读取严格场景契约，不再维护内存硬编码场景或从场景 ID 推导目标。列表只返回 ID、描述、故障分类、首个受限目标的 service/namespace 及允许的 Runbook；ground truth、预期证据、清理元数据和物理路径不会进入浏览器响应。

light fixture 根据 YAML 的明确许可分支：`no_op` 从 `DIAGNOSING` 直接进入 `VERIFYING`，空许可列表升级人工，R1 创建审批，R2/R3 经 policy 拒绝并升级。它不注入真实故障、不执行 Kubernetes 动作，也不替代正式 `/api/v1`、持久化审批或 Scenario Runner。

### 当前 light 评测归档只读实现

当前 Control API 提供 `GET /api/evaluations` 与 `GET /api/evaluations/{report_id}`。它们只读取服务端配置的 `SENTINEL_EVAL_ARCHIVE_DIR`，不接受路径、下载、重跑或删除参数。归档使用严格的 `schema_version: "1.0"`，API 对原始 JSON 字节计算 `sha256`；`raw_report`、ground truth、原始遥测、执行异常和物理路径不会进入浏览器响应。

- 冷启动或空目录返回 `available: false` 和明确原因，不伪造评测数据。
- 损坏、未知字段、聚合总数不一致、非规范 `report_id` 与符号链接均作为无效归档处理；列表保留其 ID 和稳定错误码，详情不回传文件内容。
- 单份归档超过 `SENTINEL_EVAL_ARCHIVE_MAX_BYTES` 时详情返回 `413 EVALUATION_ARCHIVE_TOO_LARGE`；归档目录不可读时返回 `503 EVALUATION_ARCHIVE_UNAVAILABLE`。
- 该实现是 light 本地证据读取能力，不代表 holdout benchmark、baseline 对比或 full `/api/v1` 契约已经完成。

## 13. System API

- `GET /health/live`：无依赖的进程存活。
- `GET /health/ready`：组件职责所需依赖。
- `GET /api/v1/system/health`：viewer+ 查看逐依赖 freshness/error。
- `GET /api/v1/system/kill-switch`：viewer+ 查看；只有本地 platform_admin 能修改，普通 approver 无权。
- kill switch 修改必须要求显式原因、幂等键和审计，开启后阻止新的 R1 execution。

## 14. Internal Action API

### `POST /internal/v1/actions`

```json
{
  "schema_version": "1.0",
  "incident_id": "inc_example",
  "plan_id": "plan_example",
  "approval_id": "apr_example",
  "idempotency_key": "opaque-stable-key"
}
```

Gateway 不接受 plan body 作为授权事实。它从数据库读取 plan/approval/decision/policy refs，执行 [Runbook 规范](runbook-specification.md) 的 gates。

- 201：同步完成且有最终结果。
- 202：已登记并运行/协调，返回 `action_execution_id` 和 poll URL。
- 409：幂等 body 冲突或同目标动作冲突。
- 412：审批/目标状态漂移。
- 403：策略、risk 或 kill switch 拒绝。

请求超时后 Worker 必须用同一幂等键查询，不生成新 key。

### `GET /internal/v1/actions/{id}`

返回状态、稳定 error code、before/after refs、attempt/reconciliation 次数和时间；不返回服务 token、数据库凭据或完整 Kubernetes 对象。

## 15. 限流与上限

初始目标（待基准）：

- 浏览器读取：每会话 60 req/min；写命令 10 req/min。
- Alert webhook：body 最大 1 MiB、每包最多 100 alerts。
- SSE：每用户每 Incident 2 连接、总连接按本机资源配置。
- export：每用户并发 1 个。
- 内部 action：每 Incident 同时 1 个、每目标同时 1 个。

限流不能成为安全唯一控制；合法拒绝返回稳定 code 和 `Retry-After`。

## 16. 契约验收

- OpenAPI 与 Pydantic/TypeScript 生成类型一致，未知字段拒绝。
- 角色、CSRF、HMAC、ServiceAccount audience 和 ground-truth 隔离有负向测试。
- 每个 command 的幂等、并发、ETag、非法状态和超时路径可测试。
- Alert 重放、重复 firing、resolved/re-fired 和 fingerprint 稳定性通过 fixture。
- SSE 断线、gap、重复、慢客户端和过期 cursor 恢复通过。
- 审批并发决定只成功一次，修改 plan/policy/target 后旧审批失效。
- Action API 超时后协调不产生重复副作用。
- 错误响应不泄露堆栈、凭据、原始敏感遥测或不可访问资源存在性。
