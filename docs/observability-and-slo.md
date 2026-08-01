# 可观测性、告警与 SLO 规范

## 1. 文档状态

本文是可观测资源属性、信号 Schema、SLI/SLO、告警和恢复验证的唯一设计来源。数值均为 **初始目标**，必须在 M1 基线测试后调整并记录版本，当前没有实测结论。

## 2. 信号边界

- demo-shop 业务信号用于事故调查和恢复验证。
- Sentinel-X 自身信号用于判断控制面是否可信。
- Kubernetes 平台信号用于工作负载状态证据。
- Exercise/Scenario 事件用于标记 `T0`、注入和 cleanup，不作为业务 SLI。
- ground truth 不进入模型可访问的日志、指标、Trace 或 Resource attributes。

观测栈拟议为 OpenTelemetry Collector、Prometheus、Loki、Tempo 和 Grafana。实现前保持 `proposed`。

## 3. 统一关联字段

### OTel Resource attributes

所有服务至少提供：

- `service.name`
- `service.namespace`
- `service.version`
- `deployment.environment.name=local-demo`
- `k8s.namespace.name`
- `k8s.deployment.name`（适用时）
- `k8s.pod.uid`（Collector enrichment）

### 请求与演练关联

- W3C `traceparent`/`tracestate` 跨 HTTP 调用传播。
- `request_id` 用于用户可见错误和日志检索，但不替代 `trace_id`。
- `exercise_run_id` 在合成负载请求、日志和 span 中传播。
- `scenario_id` 只标识场景定义版本，不泄露 ground truth。
- `incident_id` 在告警创建后用于控制面信号，不反向写入历史业务 spans。

`exercise_run_id`、`incident_id`、`trace_id` 是高基数字段：允许出现在日志/span 和 exemplars，不作为 Prometheus 常规 label。

## 4. 日志规范

结构化 JSON 日志必需字段：

| 字段 | 说明 |
| --- | --- |
| `timestamp` | UTC RFC 3339 纳秒或运行时最高精度 |
| `severity_text` / `severity_number` | OTel 语义 |
| `service_name`, `service_version` | 服务和版本 |
| `event_name` | 稳定事件名，不用整段 message 聚合 |
| `message` | 面向人的短摘要，视为不可信数据 |
| `trace_id`, `span_id` | 存在活动 span 时必填 |
| `request_id`, `exercise_run_id` | 关联字段 |
| `error_type`, `error_code` | 稳定错误分类；没有错误时省略 |
| `duration_ms` | 适用事件的耗时 |

禁止记录 Authorization、Cookie、API Key、数据库凭据、审批凭证、完整请求正文和原始模型 prompt。换行、控制字符和富 HTML 在展示前转义。

日志 `message` 和任意 attributes 是不可信输入；恶意指令仍可作为攻击 fixture 保存，但必须使用合成秘密，并在进入模型前分隔、脱敏和截断。

## 5. Trace 规范

服务端 span 名称使用低基数路由模板，如 `POST /orders`，不放真实 ID。关键 spans：

- `order.create`
- `inventory.reserve`
- `payment.charge`
- `redis.command`（隐藏 key 内容）
- `db.query`（只保留归一化 operation/table，不记录完整 SQL 参数）
- `sentinel.diagnostic.query`
- `sentinel.llm.generate`
- `sentinel.action.execute`
- `sentinel.verification.evaluate`

错误 span 设置规范 status，并记录稳定 `error.type`；业务拒绝不一律标记系统 ERROR。跨服务关联完整率成为 M1 验收项。

拟议采样：演练业务基线按比例采样，带错误和当前 ExerciseRun 的 Trace 100% tail sampling；正式比例在资源基准后确定。采样决策和 Collector 版本写入评测 metadata。

## 6. 指标命名与基数

优先使用 OpenTelemetry HTTP、RPC、数据库和运行时语义约定；自定义指标采用下列草案：

| 指标 | 类型/单位 | 允许 labels |
| --- | --- | --- |
| `demo_shop_orders_total` | counter / `{order}` | `result`, `failure_category` |
| `demo_shop_payment_requests_total` | counter / `{request}` | `result`, `error_type` |
| `demo_shop_inventory_requests_total` | counter / `{request}` | `result`, `error_type` |
| `demo_shop_dependency_request_duration_seconds` | histogram / seconds | `service`, `dependency`, `operation`, `result` |
| `demo_shop_cache_operations_total` | counter / `{operation}` | `operation`, `result` |
| `demo_shop_db_lock_wait_seconds` | histogram / seconds | `database`, `relation_class` |
| `sentinel_incidents_total` | counter / `{incident}` | `status`, `service`, `severity` |
| `sentinel_diagnostic_steps_total` | counter / `{step}` | `tool`, `status`, `error_code` |
| `sentinel_action_executions_total` | counter / `{action}` | `runbook`, `status`, `error_code` |
| `sentinel_workflow_activity_duration_seconds` | histogram / seconds | `activity`, `status` |
| `sentinel_llm_tokens_total` | counter / `{token}` | `model_alias`, `direction` |

禁止将 user、request、trace、incident、exercise run、pod UID、错误 message 或自由模型名作为 label。每个自定义指标的最大 series 预算在 M0/M1 实测后固定；超过预算触发控制面告警。

## 7. Demo Shop SLI 与初始目标

### 7.1 统一负载契约

正式场景负载拟议为稳定 10 RPS、最多 20 并发，请求分布固定为创建订单主链路；具体值必须由本机基准确认。负载 generator 记录实际发送、客户端取消和超时。由基础设施主动取消的请求不静默排除，单独分类。

### 7.2 SLI

| SLI | 公式 | 初始目标/阈值 |
| --- | --- | --- |
| 订单成功率 | successful orders / accepted order attempts | baseline 5 分钟 ≥ 99% |
| 支付错误率 | failed payment requests / payment requests | baseline 5 分钟 < 1% |
| 订单 P95 | `order-api` server duration histogram | baseline 5 分钟 < 500 ms |
| 依赖 P95 | service -> dependency span/metric histogram | 场景特定，基于 baseline 倍数 |
| Ready 比例 | ready replicas / desired replicas | baseline = 100% |
| DB lock wait | lock wait seconds / blocked count | baseline 无持续阻塞 |

这里的数值只用于开始采集和调试，不是生产 SLO。M1 报告必须给出硬件、负载、样本和实际分布，再冻结 `slo_policy_version`。

### 7.3 窗口

- baseline window：故障前连续 5 分钟，全部健康门槛满足。
- detection window：告警表达式连续满足 30–60 秒，具体按场景定义。
- fault window：从 `T0` 到有效 remediation 或场景 cleanup 前。
- observed window：候选恢复后连续 3 分钟；任何关键 SLI 再次越界则重置。
- cooldown window：run 关闭后 2 分钟用于确认无残留，仅用于环境 gate。

窗口时间均为初始目标，M1 用实际稳定性校准。

## 8. 场景信号与恢复策略

| 场景 | 主要告警条件 | 关键 Evidence | 恢复验证 |
| --- | --- | --- | --- |
| Pod 崩溃 | Ready 比例下降或 payment 错误率越界 | K8s state + error Trace + 业务指标 | 自动拉起后直接进入验证，不要求 AI 动作 |
| 容量/下游延迟 | order/payment P95 越界 | dependency duration + resource/queue + Trace | 合法 scale 后 P95/成功率稳定 |
| 持续 5xx | inventory 5xx 越界 | origin 5xx + error propagation Trace | 合法 restart 清除内存 latch 后稳定 |
| Redis timeout | cache timeout 与 inventory SLI 越界 | client metric + dependency span + log code | 正确升级；cleanup 只验证环境恢复 |
| 数据库锁 | lock wait 与 order P95 越界 | DB metric + db span + blocker ref | 正确升级；cleanup 不计 AI 恢复 |
| 错误发布 | 版本变更后错误率越界 | deployment event + version-sliced signal | 正确升级；R2 回滚禁用 |

场景最终名称和因果定义以 [场景目录](scenario-catalog.md) 为准；若其变化，本表同步更新。

## 9. 告警与指纹

Alertmanager 告警必需 labels：`alertname`、`service`、`severity`、`environment`、`scenario_id`（仅演练）；annotations 仅放摘要和 runbook 文档引用，不放命令。

Alert fingerprint 拟议为以下规范字符串的 SHA-256：

```text
alertname | environment | service | normalized_target | scenario_id
```

不包含当前值、时间戳、Pod 名或自然语言 annotation。Control API 以 fingerprint + 活跃时间桶/Incident 状态做去重。resolved/re-fired 语义和抑制规则在 API 契约中定义。

## 10. Evidence 查询约束

Diagnostic Gateway 只接受登记模板和类型化参数：

- 默认时间范围 `[T2-5m, now]`，单次最大 30 分钟。
- PromQL 最大 series/points；禁止任意高基数 group-by。
- Loki 限定 namespace/service/时间，默认 200 行、最大 1000 行。
- Tempo 必须按已知 trace/service/time 查询，最大返回 spans 数。
- K8s 仅 `demo-shop` 的 get/list/watch，禁止 Secrets 和事件正文中的敏感字段。
- 响应包含 query template ID、规范参数、执行时间、截断标记、source_ref 和 content hash。

准确工具模板见 [LLM 与工具协议](llm-and-tooling-protocol.md)。

## 11. 恢复判定

`VerificationResult` 至少记录：

- `slo_policy_version`
- baseline/observed 起止时间
- 每个 SLI 的查询、单位、阈值、样本和结果
- 数据缺失/过期/截断状态
- 触发验证的 remediation 或无动作原因
- `passed` 与失败原因

规则：

- 动作 API 成功、Pod Ready 或单个指标恢复均不足以标记 `RESOLVED`。
- 所有场景必需 SLI 在完整 observed window 内通过才可 `RESOLVED`。
- 数据源不可用时不能假定恢复，进入 `ESCALATED` 或 `FAILED`。
- 自动恢复场景允许从调查直接进入 `VERIFYING`；仍需 VerificationResult。
- Scenario cleanup 导致的恢复单独标记 `recovery_actor=SCENARIO_RUNNER`，不计 AI remediation 成功。

## 12. Sentinel-X 自观测

必须覆盖：

- Alert Ingress 接收/拒绝/去重。
- Workflow/Activity backlog、时长、重试、heartbeat 和失败。
- Diagnostic 工具查询量、截断、失败与延迟。
- 模型调用次数、Token、延迟、解析失败和预算耗尽。
- Approval 等待、过期、拒绝和并发冲突。
- Action Gateway gate 结果、幂等命中、执行/协调时长和最终状态。
- SSE 连接、断连、游标 gap 和补拉。
- outbox 积压、投影延迟和对账漂移。

初始工程目标：固定 E2E 中 Workflow 丢失为 0、重复外部副作用为 0、攻击集危险动作拦截为 100%。这些是测试门槛，不是当前测量值。

## 13. 健康语义

- liveness：进程事件循环/主线程可运行，不检查所有依赖。
- readiness：处理本组件职责所必需依赖可用；模型不可用可使 Investigator not-ready，但 Control API 只读能力仍可 ready。
- startup：迁移/缓存/Worker 注册完成前阻止 readiness。
- system health：聚合但不掩盖部分失败，输出每个依赖的 last success、latency 和 error code。

Kubernetes Ready 不代表业务 SLO 或完整遥测正常。

## 14. Dashboard 清单

1. Demo Shop golden signals：流量、错误、延迟、饱和度，按服务/版本分组。
2. Incident command：`T0–T8`、关键 SLI、告警、动作和验证窗口。
3. Dependency map：order -> inventory/payment -> Redis/PostgreSQL。
4. Sentinel runtime：Workflow/Activity、outbox、SSE、模型预算。
5. Action safety：gate 拒绝、幂等、目标漂移、kill switch。
6. Evaluation：逐场景时延、命中、恢复、安全和成本。

Dashboard 不是 Evidence 的唯一来源，所有图表必须能给出查询和时间范围。

## 15. 保留、脱敏和隔离

初始本地目标：原始演练遥测保留 7 天，领域审计/脱敏评测产物保留 30 天；实现前由资源基准和安全评审确认。支持按 ExerciseRun 安全清理，但只追加审计记录不由应用直接删除。

demo-shop、Sentinel 控制面和攻击 fixture 使用独立 tenant/label/namespace 查询边界。模型只接收必要摘要；导出包不包含原始秘密、审批 bearer、Cookie 或服务凭据。

## 16. 验收

- 三服务 trace context 贯穿率在固定 E2E 报告中给出，错误 Trace 可关联到同一 run。
- 日志 Schema、脱敏和控制字符处理有契约测试。
- 指标单位和 labels 通过静态规则，禁止高基数字段。
- 六类场景的 `T0`、告警、Evidence 和恢复/升级判定可复现。
- 告警重复投递产生同一活跃 Incident，resolved/re-fired 行为可测试。
- 遥测源失败、数据过期和缺失不会误判 `RESOLVED`。
- cleanup 与 AI remediation 在报告和时间线上明确分离。
- 指标、阈值和窗口修改提升 `slo_policy_version`，旧报告仍可解释。
