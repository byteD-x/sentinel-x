# 需求、实现、测试与证据追踪矩阵

## 1. 目的

本文件回答每项需求“由谁实现、依据哪份契约、如何测试、报告里看什么、演示在哪里证明”。当前实现/测试均为 planned，不表示已通过。

状态：`DESIGNED`、`IMPLEMENTED`、`TESTED`、`MEASURED`。当前所有 FR/NFR 最高为 `DESIGNED`。

## 2. 测试集标识

| ID | 测试集 |
| --- | --- |
| TS-API | HTTP/Schema/角色/幂等/并发契约 |
| TS-WF | Temporal replay/retry/restart/signal |
| TS-DATA | migration/约束/outbox/对账 |
| TS-SCENARIO | 注入/生效/cleanup/dirty gate |
| TS-DIAG | 工具模板/Evidence/预算/provider |
| TS-ACTION | 审批/Gateway/Runbook/协调/幂等 |
| TS-SEC | RBAC/NetworkPolicy/注入/秘密/越权 |
| TS-SLO | 指标/告警/窗口/恢复验证 |
| TS-UI | 权限/状态/SSE/响应式/无障碍 |
| TS-EVAL | dataset/baseline/holdout/report/成本 |

## 3. 功能需求

| ID | 状态 | 组件/Backlog | 详细契约 | 测试 | 报告证据 | 演示 |
| --- | --- | --- | --- | --- | --- | --- |
| FR-01 告警去重建事故 | DESIGNED | M2-03 | [API](api-contracts.md)、[数据](data-model.md) | TS-API/TS-DATA | dedup result、fingerprint、Incident count | 1:15–2:00 |
| FR-02 持久工作流 | DESIGNED | M2-04/09 | [Workflow](workflow-design.md) | TS-WF | history/run IDs、restart checkpoints、duplicate effects | 演示前证据/回放 |
| FR-03 四类只读工具 | DESIGNED | M3-01..03 | [LLM/工具](llm-and-tooling-protocol.md) | TS-DIAG/TS-SEC | tool/template、scope、status、duration | 2:00–3:30 |
| FR-04 可引用根因假设 | DESIGNED | M3-04/06 | [LLM/工具](llm-and-tooling-protocol.md)、[数据](data-model.md) | TS-DIAG/TS-EVAL | Top-1、Evidence refs、contradictions | 3:30–4:15 |
| FR-05 结构化计划与风险 | DESIGNED | M4-01 | [领域](domain-model-and-contracts.md)、[Runbook](runbook-specification.md) | TS-API/TS-ACTION/TS-SEC | plan/policy/runbook/hash、denials | 4:15–5:15 |
| FR-06 R1 人工审批 | DESIGNED | M4-02/04 | [API](api-contracts.md)、[安全](security-model.md) | TS-API/TS-ACTION/TS-SEC | decision actor/time/hash/expiry | 5:15–6:00 |
| FR-07 幂等 Runbook | DESIGNED | M4-03..07 | [Runbook](runbook-specification.md)、[Workflow](workflow-design.md) | TS-ACTION/TS-WF | execution ID、idempotency hash、effect count | 5:15–6:00 |
| FR-08 SLO 恢复验证 | DESIGNED | M4-08 | [观测/SLO](observability-and-slo.md) | TS-SLO/TS-SCENARIO | baseline/observed/threshold/passed/actor | 6:00–7:15 |
| FR-09 实时时间线与回放 | DESIGNED | M5-02/05 | [UX](user-experience-spec.md)、[API SSE](api-contracts.md) | TS-UI/TS-API | sequence/gap/reconnect/export hash | 7:15–8:30 |
| FR-10 固定数据集评测 | DESIGNED | M3-08/M6-01/02 | [测试评测](testing-and-evaluation.md)、[LLM](llm-and-tooling-protocol.md) | TS-EVAL | dataset/config/run/aggregate/failures | 9:30–10:00 |
| FR-11 遥测提示注入防护 | DESIGNED | M3-07/M4-09 | [安全](security-model.md)、[LLM](llm-and-tooling-protocol.md) | TS-SEC/TS-DIAG | attack case、deterministic denial、egress | 8:30–9:30 |

## 4. 非功能与安全需求

| ID | 需求 | 状态 | 契约/控制 | 测试与证据 |
| --- | --- | --- | --- | --- |
| NFR-01 | Worker 重启可恢复 | DESIGNED | Workflow §16 | TS-WF 三点/多点重启，history refs |
| NFR-02 | 重复外部副作用为 0 目标 | DESIGNED | Runbook 幂等 + Gateway 原子登记 | TS-ACTION 并发/超时，effect count |
| NFR-03 | 攻击集危险动作拦截 100% 门槛 | DESIGNED | R0–R3/policy/Gateway | TS-SEC 样本数、拒绝码；同时合法接受率 |
| NFR-04 | 审计可追溯 | DESIGNED | timeline/outbox/不可变 Decision | TS-DATA 行权限、引用完整率、export hash |
| NFR-05 | 本地 full 可复现 | DESIGNED | deployment profiles/version lock | 第二环境 cold run、资源和实际时长 |
| NFR-06 | 遥测查询有界 | DESIGNED | 工具模板、limit、cardinality | TS-DIAG/TS-SLO 超范围和截断 |
| NFR-07 | 敏感值不外泄 | DESIGNED | data classes/三层脱敏/secret storage | TS-SEC scanner、support/export tests |
| NFR-08 | UI 可访问且不误审批 | DESIGNED | UX 审批/AA/响应式 | TS-UI 4 视口、键盘、screen reader 名称 |
| NFR-09 | 报告可比较 | DESIGNED | dataset/model/prompt/policy/commit metadata | TS-EVAL compatibility gate |
| NFR-10 | cleanup 不冒充 remediation | DESIGNED | recovery_actor、Scenario/Action 分权 | TS-SCENARIO/TS-SLO、指标重算 |

## 5. 场景到 Runbook/验证

| 场景 | 期望系统行为 | 动作 | 关键测试 | 成功分类 |
| --- | --- | --- | --- | --- |
| Pod 崩溃 | 诊断并观察自动拉起 | 无 | TS-SCENARIO/TS-WF/TS-SLO | auto recovery，零 Action |
| capacity latency | 识别容量、审批受限扩容 | scale R1 | TS-DIAG/TS-ACTION/TS-SLO | AI-assisted remediation |
| latched 5xx | 识别进程 latch、审批滚动重启 | restart R1 | TS-DIAG/TS-ACTION/TS-SLO | AI-assisted remediation |
| Redis timeout | 正确升级，不清数据 | 无 | TS-DIAG/TS-SEC/TS-SCENARIO | correct escalation |
| DB lock | 正确升级，不操作 DB | 无 | TS-DIAG/TS-SEC/TS-SCENARIO | correct escalation |
| bad deployment | 识别版本相关，拒绝 R2 回滚 | 无 | TS-DIAG/TS-SEC/TS-EVAL | correct escalation |

## 6. 证据升级规则

- 代码存在只能从 DESIGNED 到 IMPLEMENTED。
- 自动测试及原始输出可把对应路径升到 TESTED。
- 固定数据集、环境和报告完整时才能标 MEASURED。
- 某个场景 MEASURED 不会自动提升其他场景或生产范围。
- 契约/数据集/指标口径变化使关联证据过期，必须提升版本并重新测试。

## 7. 变更检查

修改 FR/NFR、状态机、场景、Runbook、policy、SLO、API 或报告字段时：

1. 更新唯一事实来源。
2. 更新本矩阵的组件/契约/测试/证据映射。
3. 更新 Backlog 依赖和发布 gate。
4. 判断已有报告是否仍可比较；不可比则标记过期，不静默重算。
