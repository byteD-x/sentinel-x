# 安全与威胁模型

## 1. 安全目标

Sentinel-X 的核心安全目标不是让 AI “足够聪明”，而是确保即使模型判断错误、遥测被污染、请求被重放或组件故障，也不能越过预先定义的权限与审批边界。

本文描述 MVP 目标控制，尚未实现或验证。

## 2. 保护资产

- 演练环境的可用性与数据完整性。
- 审批身份、决策和凭证。
- Runbook、策略和场景定义的完整性。
- Incident、Evidence、Timeline 和 ActionExecution 审计记录。
- 模型 API 密钥与服务凭据。
- 遥测中可能出现的 Token、Cookie、个人信息和业务数据。

真实生产资产不在范围内，因为 MVP 禁止连接生产系统。

## 3. 信任假设与边界

- 浏览器、告警发送者、模型 provider 和遥测内容均不默认可信。
- Control API、Worker 和 Action Gateway 是不同权限主体。
- LLM 生成的假设、参数和计划只是候选输入，不是授权。
- PostgreSQL/Temporal 的管理员仍属于本地可信运维边界；MVP 不解决主机被完全攻陷。
- 本地预置身份必须明确标记 `local-only`，不能宣传为生产认证。

## 4. 主要威胁与控制

| 威胁 | 典型路径 | 必需控制 |
| --- | --- | --- |
| 遥测提示注入 | 日志包含“忽略规则并执行命令” | 不可信内容分隔、固定系统策略、结构化工具、动作二次校验 |
| 越权动作 | 模型或用户请求任意资源写入 | 独立执行身份、白名单目标、RBAC、namespace 限制 |
| 审批篡改 | 批准后替换目标或参数 | `plan_hash`、目标 UID/代次、策略版本绑定 |
| 重放与重复副作用 | 重试多次触发重启/扩容 | nonce、过期时间、最大次数、全局幂等键 |
| 审批者混淆 | 页面只显示自然语言摘要 | 展示规范动作、目标、参数、影响、证据和回滚 |
| 敏感信息泄露 | 日志/Trace 被送入模型或写入审计 | 采集与发送前脱敏、最小化、结果大小限制 |
| SSRF/工具滥用 | 模型构造任意 URL 或查询 | 无通用 HTTP 工具；数据源和查询模板白名单 |
| 拒绝服务/成本耗尽 | 无限诊断循环或超大日志 | 步数、时间、Token、查询窗口、结果大小和并发预算 |
| 审计删除 | 应用修改历史掩盖动作 | 只追加时间线；应用角色无 update/delete |
| 场景越界 | 故障注入影响控制面 | namespace、ServiceAccount、NetworkPolicy 和目标白名单 |
| 依赖/供应链污染 | 未固定镜像或包被替换 | 锁定依赖、镜像 digest、SBOM/扫描作为后续门禁 |

## 5. 角色与权限

| 角色/身份 | 允许 | 禁止 |
| --- | --- | --- |
| `viewer` | 查看事故、证据、时间线和报告 | 发起调查、审批、执行 |
| `responder` | 发起调查、提出计划 | 代表审批者批准、直接执行 |
| `approver` | 批准/拒绝 R1 计划 | 修改计划、执行 R2/R3 |
| `scenario_operator` | 启动/清理已登记场景 | 操作控制面和观测栈 |
| `diagnostic-sa` | 对必要 K8s 资源 `get/list/watch` | Secrets、写操作、`pods/exec` |
| `executor-sa` | 在 `demo-shop` 执行白名单 Deployment patch | 其他 namespace、任意资源、任意命令 |

MVP 可以允许同一自然人同时拥有 `responder` 和 `approver` 角色以方便本地演示，但系统必须记录实际身份，且不能把这描述为职责分离已经满足。

## 6. 动作风险等级

| 等级 | 定义 | MVP 策略 |
| --- | --- | --- |
| R0 | 无副作用的只读查询 | 可自动执行，仍需审计和预算 |
| R1 | 单服务、可逆、参数有界 | 一人审批；仅重启或限定扩容 |
| R2 | 数据库、版本回滚、跨服务变更 | 禁用并升级人工 |
| R3 | 任意 Shell、`pods/exec`、Secrets、集群级操作 | 永久禁止 |

动作不能因模型置信度高而降低风险等级。

## 7. 审批凭证

有效审批至少绑定：

- `incident_id`
- `action_type` 与 `runbook_version`
- namespace、kind、name、UID 和 generation/resourceVersion
- 规范化参数与 `plan_hash`
- `policy_version`
- `approver_id` 与决定时间
- `expires_at`、nonce 和 `max_executions`

MVP 拟议采用数据库绑定授权：Worker 只传 `approval_id`，Action Gateway 使用专用最小数据库角色独立读取并原子消费不可变审批记录，校验 Schema、plan hash、过期、使用次数、RBAC、策略、目标状态和幂等；不能信任 Worker 声称“已经校验”。Worker 的服务身份使用 audience 固定的短时 projected ServiceAccount token，并由 Gateway 通过 TokenReview 校验。详细见 [API 契约](api-contracts.md) 和 [ADR-0003](adr/0003-database-bound-approval-and-workload-identity.md)。

## 8. 受控执行顺序

```text
接收类型化请求
-> 校验调用方身份
-> 校验 Runbook/动作/目标白名单
-> 校验审批完整性与 plan_hash
-> 重新读取目标 UID 与当前代次
-> 原子登记 idempotency_key
-> 记录 before_state
-> 使用官方 Kubernetes Client 执行有限操作
-> 记录 after_state 与结果
-> 写入只追加审计事件
```

任一步失败都默认拒绝。不得在执行器内调用 LLM、Shell 或 `kubectl`。

## 9. 遥测提示注入防护

- 系统提示明确声明遥测是引用数据，不能改变角色、策略或工具权限。
- 工具参数由严格 Schema 校验，拒绝额外字段和自由文本命令。
- 对日志、Trace attributes 和告警 annotations 做长度限制与分隔。
- 在送入模型前脱敏 Authorization、Cookie、API Key、Token 和连接串模式。
- 计划中的目标、动作和参数必须来自允许集合，不能从日志文本直接提升。
- 固定攻击集包含直接指令、伪系统消息、编码指令、超长内容、伪造审批和数据外传请求。
- 模型拒绝并不是最终控制；Action Gateway 的确定性拒绝才是安全边界。

## 10. 服务身份与网络

- 浏览器不能用 header 自报用户；local-only 会话由服务端预置身份创建，写请求有 CSRF 防护。
- Alertmanager 使用独立 HMAC key、时间窗口和重放缓存。
- Worker、Diagnostic、Action、Scenario 使用不同 ServiceAccount 和数据库角色，不共享 kubeconfig/凭据。
- Gateway token audience 固定，调用身份和审批授权是两套校验。
- NetworkPolicy 默认拒绝；Investigator 只出站到固定 provider，Gateway 无模型 egress，Diagnostic 无通用 HTTP。
- Scenario Runner 和 Action Gateway 的写权限不重叠，均无法操作控制面/观测 namespace。

## 11. 凭据与数据

- 本地密钥从 ignored env 文件或 Kubernetes Secret 注入；仓库 `.env.example` 的敏感值保持为空。
- 模型密钥只对 Investigator Activity 可见；Action Gateway 不持有。
- Kubernetes 身份使用独立 ServiceAccount，不共享 kubeconfig 管理员凭据。
- 日志默认不记录请求正文、审批凭证、模型密钥或原始敏感遥测。
- 数据分为 synthetic public、internal、sensitive、secret；secret 不进入业务表、日志、模型输入或报告。
- 事故导出包先脱敏和秘密扫描，再允许下载；初始本地保留目标为原始遥测 7 天、领域审计/脱敏报告 30 天，待资源与安全评审固定。
- 示例和测试只使用合成数据，不复制真实生产日志。

## 12. 审计与紧急控制

所有身份变化、诊断查询、模型调用元数据、计划、审批、拒绝、执行和验证都产生可关联 TimelineEvent。审计记录包含 actor、时间、关联 ID、策略/Runbook 版本和结果，不记录秘密值。

系统需要全局 kill switch：启用后阻止所有 R1 新执行，但不影响只读查看和必要的场景清理。只有本地 platform maintainer 能改变权威状态，普通 approver 和 LLM 无权关闭；每次变化记录身份、原因和时间。审批必须可过期；尚未消费的审批可撤销。

## 13. 安全验收

至少覆盖：

- 无审批、过期、拒绝、撤销、篡改和重复审批。
- 修改目标 UID、代次、参数、Runbook 或策略版本。
- 越 namespace、非白名单资源、R2/R3 和额外 Schema 字段。
- 相同幂等键并发请求、超时后重试和 Worker 重启。
- 日志/Trace 中的提示注入、秘密模式、超长文本和伪造工具输出。
- kill switch 生效、审计只追加、模型组件不能访问执行身份。

固定攻击集的危险操作拦截目标为 100%，并同时报告合法 R1 接受率/误拒率；这是发布门槛目标，不是当前实测结论。完整 Threat/Control/Test 映射见 [安全控制矩阵](security-control-matrix.md)。

## 14. 已知限制

- 单机本地环境无法证明生产级网络隔离、身份治理和高可用。
- local-only 身份不能证明企业级认证与职责分离。
- 脱敏规则可能漏掉未知秘密格式，需要通过攻击集持续扩充。
- 模型 provider 会接触经过筛选的遥测摘要，使用前仍需评估其数据政策。
- 宿主机或集群管理员完全失陷不在 MVP 威胁模型内。
