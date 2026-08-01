# 本地演练平台运维与排障手册

## 1. 适用范围

本文面向 Sentinel-X 本地隔离演练环境的维护者，定义健康检查、安全停止、dirty 环境、动作协调、备份恢复、升级和常见故障处理。当前没有实现，所有命令入口以 [本地开发与部署](local-development-and-deployment.md) 的目标任务为准。

这不是生产值班手册，不授权接入或操作真实系统。

## 2. 运维角色

| 角色 | 职责 | 禁止 |
| --- | --- | --- |
| platform maintainer | 环境部署、配置、备份、升级、kill switch | 代替审批者伪造业务决定 |
| scenario_operator | 场景自检、注入、cleanup、dirty gate | 使用 Action Gateway 或控制面凭据 |
| approver | 审批固定 R1 plan | 修改环境、Runbook 或 policy |
| security reviewer | 权限、攻击集、秘密轮换和事件审查 | 直接修改不可变审计 |

本地可由一人兼任，但每个操作仍记录实际角色和身份，不能声称生产职责分离。

## 3. 每次启动检查

按顺序确认：

1. 当前环境 ID、profile、cluster metadata 与目标目录。
2. kill switch 开启、actions 默认关闭。
3. PostgreSQL migration 与 Temporal Worker version 兼容。
4. outbox 无异常积压，Workflow/projection 对账无漂移。
5. 观测栈采集/查询、数据新鲜度和时钟正常。
6. demo-shop 版本/副本/代理规则/故障开关为基线。
7. 没有活跃 ExerciseRun、ActionExecution 或 pending approval 残留。
8. 权限负向 smoke 仍拒绝 Secrets、exec、跨 namespace 和 R2/R3。

任何一项不确定时保持 kill switch，不启动 benchmark。

## 4. Kill switch

### 启用条件

- Action 状态未知或重复副作用疑似发生。
- Gateway/DB/Temporal 对账失败。
- RBAC、审批、策略或身份验证异常。
- 环境目标、UID、generation 或 namespace 与预期不符。
- 准备停止/升级/恢复控制面。

### 启用步骤

1. 记录操作者、原因、环境和关联 Incident/Action。
2. 通过权威 Control API/管理入口原子启用。
3. 验证新 R1 请求返回 `POLICY_DENIED`/kill-switch 稳定码。
4. 不终止已提交动作；转到动作协调流程。
5. 保留只读调查和 Scenario 必要 cleanup。

### 关闭条件

- 原因已定位并有验证证据。
- 所有 Action 最终状态确定，审批/目标/投影一致。
- 安全回归和健康门禁通过。
- 关闭动作由有权限维护者记录原因；不能由 LLM 或普通 approver 关闭。

## 5. Dirty 环境恢复

1. 立即阻止新 ExerciseRun，保持 kill switch。
2. 导出脱敏 run/incident/action/timeline/cluster state 引用。
3. 从 FaultInjection 记录确认本次 run 的精确目标和 before state。
4. 使用 Scenario Runner 专用 cleanup；不把权限移给 Action Gateway。
5. 检查故障开关、Toxiproxy toxic、镜像 digest、副本、持锁事务和临时资源。
6. 运行 baseline/cooldown window 和跨信号健康检查。
7. 全部通过标记 CLEAN；任何未知保持 DIRTY。

禁止用“删除整个 cluster”掩盖无法解释的动作副作用；如最终选择重建，先保存证据并记录根因和不可恢复项。

## 6. Action 状态未知

症状：Worker submit 超时、Gateway 返回 `RECONCILING`、Kubernetes API 超时或 Workflow 重启。

处理：

1. 启用 kill switch，禁止同目标新动作。
2. 使用原 `action_execution_id`/idempotency key hash 查询 Gateway，不生成新 key。
3. 对照 Gateway DB 登记、审批消费、Kubernetes 目标 annotation/generation/resourceVersion。
4. 如果副作用已提交，继续协调 rollout/scale 最终状态；不能重新 patch。
5. 如果可证明从未提交，Gateway 将原 execution 置为明确失败/拒绝后才允许新计划。
6. 对账 Timeline/Workflow projection，记录人工结论和证据。

无法证明最终状态时 Incident/Action 保持失败或升级人工，不标记恢复。

## 7. Temporal 故障

### Worker 不消费任务

- 检查 namespace、task queue、Worker build ID、readiness 和网络。
- 查看 backlog、poller 与非确定性错误，不直接清空 queue。
- 新 Worker 必须先对 history fixtures replay；不兼容版本回滚。

### Workflow 卡在等待

- Query status/budget/pending wait，核对 DB command/outbox 是否已投递。
- Approval 已决定但未推进：重投同 command ID Signal，不直接改 Workflow state。
- Activity 超时：按错误分类检查 retry；写动作转专门协调。

### 非确定性错误

- 停止发布、保持旧 Worker 和 kill switch。
- 对失败 history 运行 replay 定位代码分支。
- 修复必须使用官方版本兼容机制，禁止删除 history 或新建同一事故绕过。

## 8. PostgreSQL 与 outbox 故障

### 数据库不可用

- Control API 写命令和审批应失败，不缓存后自动重放未知写请求。
- Workflow 的 DB Activity 有限重试；超限升级/失败。
- Action Gateway 无法独立读取审批时默认拒绝执行。

### Outbox 积压

- 检查 dispatcher、锁、attempt/backoff 和 poison event。
- 同 event ID 重投，消费者 inbox 去重。
- 不手工修改 published 标记掩盖失败；必要修正追加审计。

### Workflow/投影漂移

- 比较 Temporal checkpoint 与 Incident projection checkpoint。
- DB 落后：执行幂等 reproject。
- DB 超前/冲突：保持 kill switch，找出非法写入，不自动覆盖。

## 9. 可观测性故障

| 症状 | 检查 | 安全行为 |
| --- | --- | --- |
| Prometheus 无数据 | scrape/Collector/时间范围/resource attrs | 不做恢复判定 |
| Loki 查询失败 | ingestion、tenant/namespace、limit | 保留其他 Evidence，标记缺失 |
| Tempo trace 断裂 | traceparent 传播、sampling、Collector | 不伪造跨服务因果 |
| 数据过期 | source freshness/retention | Evidence 标记 expired |
| 基数过高 | top labels/series budget | 停止新增高基 label，修复 instrumentation |
| 时钟漂移 | node/container/host time | 暂停 benchmark，不能比较 T0–T8 |

观测源不可用时系统可以继续只读查看既有数据，但不能凭不完整信号进入 `RESOLVED`。

## 10. LLM provider 故障

- 429/5xx/timeout 按固定 retry 和预算处理。
- Schema 修复最多一次；持续失败升级 `MODEL_OUTPUT_INVALID`。
- 不临时切换未评测模型、提高 Token 上限或放宽工具。
- fallback alias 若已配置和评测，报告标记 provider/model 变化并判不可直接比较。
- API key 疑似泄露时立即禁用/轮换，检查日志和事故包，不只重启 Pod。

## 11. Action Gateway 故障

- 身份 TokenReview 失败：确认 audience/ServiceAccount/时钟，默认拒绝。
- 审批 DB 读取失败：不信任 Worker payload，默认拒绝。
- RBAC denied：确认目标和 policy，不扩大权限作为临时修复。
- 目标漂移：创建新 plan/approval，禁止修改旧审批。
- rollout/scale 部分成功：进入协调，不连续扩大动作。
- 重复请求：必须返回原 execution；出现第二个副作用立即安全事件处理。

## 12. Scenario Runner 故障

- 注入请求成功但故障未生效：不记录 T0，run 失败并 cleanup。
- cleanup 超时：自动硬超时/专用回退仍失败则 DIRTY。
- 目标 UID/版本漂移：停止，不做宽泛 selector 清理。
- 持锁事务无法确认：只处理本 run 带标签且身份匹配的注入连接。
- 错误版本 cleanup：只恢复 before digest，不使用 `latest`。

Scenario Runner 永远不能操作 `sentinel-system`/`observability` 或真实环境。

## 13. 备份与恢复

### 备份

- 启用 kill switch，等待/协调所有 Action。
- 记录 PostgreSQL migration、Temporal namespace/version、commit 和配置 hash。
- 创建数据库逻辑备份与脱敏 metadata；不打包环境秘密。
- 报告和 Evidence source refs 分开归档，标明遥测保留期。

### 恢复演练

1. 恢复到新项目专属数据库/环境，不覆盖当前实例。
2. 运行兼容 migration 和约束检查。
3. 对照行数、关键 hash、审批/时间线不可变记录。
4. 连接 Temporal 前比较恢复点；不一致保持 kill switch。
5. 运行只读对账和 UI 回放，再考虑启用新写命令。

RPO/RTO 在本地基准后定义；当前不宣称生产恢复目标。

## 14. 凭据轮换

| 凭据 | 轮换策略 |
| --- | --- |
| session signing key | 短双 key 验证窗口，使旧 session 到期 |
| Alert HMAC | Alertmanager/Control API 协调双 key 窗口，测试重放 |
| LLM key | provider 创建新 key、更新 Investigator、验证、撤销旧 key |
| DB roles | 分组件轮换，验证连接池刷新和最小权限 |
| ServiceAccount token | projected 短期自动轮换，不持久化 |

轮换过程不记录值，只记录 key ID/fingerprint、安全时间和结果。

## 15. 升级与回滚

- 升级前：kill switch、备份、migration dry-run、Workflow replay、契约/安全回归、镜像 digest。
- 顺序：兼容 DB expand -> 兼容 Worker/Activities -> API -> Web -> contract 收紧。
- 旧/新 Worker 使用官方 version routing，不能同时消费不兼容 history。
- 回滚只回应用到兼容版本；不可逆 migration/Workflow/Runbook 需 ADR 和前向修复方案。
- 升级后运行只读 smoke、SSE、outbox、场景自检；最后才考虑开启 R1。

## 16. 脱敏支持包

支持包包含：

- 版本、profile、集群 provider、非敏感配置 hash。
- health summary、Workflow/Activity refs、outbox checkpoint。
- Incident/Timeline/Approval/Action/Verification 的脱敏记录。
- 相关日志/Trace/Evidence hash 与有限摘要。
- 资源状态 allowlist 字段和错误码。

不包含：env 文件、Secret、Cookie/token、完整审批 nonce、原始敏感遥测、管理员 kubeconfig。生成后运行 secret scanner，记录包 hash 和过期时间。

## 17. 数据清理

- 清理按明确 run/日期/产物 ID，先 dry-run 列出绝对项目路径和数据库范围。
- 应用审计只追加；保留期删除由专用维护角色执行并追加 tombstone/audit。
- 原始遥测过期后 Evidence 显示 expired，不删除历史结论引用。
- 不使用未解析变量、通配根目录、用户主目录或跨 shell 拼接做递归删除。

## 18. 运维验收

- kill switch 在 Gateway 不可达/DB 不可达/并发请求时仍默认拒绝。
- dirty、Action unknown、outbox drift、Temporal restart 和观测源缺失均有可重复演练。
- 备份恢复在新环境通过只读回放和约束检查。
- key 轮换不泄露值，旧凭据在窗口后失效。
- 升级前 replay 和迁移门禁阻止不兼容部署。
- 支持包通过秘密扫描且可定位关键错误，不需要原始生产数据。
- down/reset/purge 的目标边界和失败行为通过安全测试。
