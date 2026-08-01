# Architecture Decision Records

## 1. 目的

ADR 记录影响多个模块、难以回退或涉及安全/数据/运行时边界的决策。当前 ADR 全部为 `proposed`，需 M0 spike/评审证据后才能变为 `accepted` 或 `rejected`。

## 2. 状态

- `proposed`：方案完整但证据/评审未完成。
- `accepted`：已满足验证要求并成为实现约束。
- `rejected`：评审后不采用，保留理由。
- `superseded`：被新 ADR 取代，链接后继。
- `deprecated`：现有实现仍可能存在，但禁止新使用。

## 3. 编号与文件名

`NNNN-short-kebab-title.md`。编号永久保留，不能因拒绝/删除重排。日期使用提出日期；状态变化追加决策记录，不改写历史理由。

## 4. 必需章节

1. 状态、日期、决策者角色。
2. 背景与问题。
3. 决策驱动因素。
4. 候选方案与比较。
5. 拟议/最终决定。
6. 正面/负面后果。
7. 验证证据与接受门槛。
8. 回退/重审条件。
9. 关联文档。

不得使用“业界常用”替代证据；安全 ADR 必须包含失败路径和残余风险。

## 5. 当前 ADR

| ID | 决策 | 状态 |
| --- | --- | --- |
| [0001](0001-modular-control-plane-and-isolated-action-gateway.md) | 模块化控制面 + 独立 Action Gateway | proposed |
| [0002](0002-temporal-as-sole-durable-orchestrator.md) | Temporal 作为唯一持久编排 | proposed |
| [0003](0003-database-bound-approval-and-workload-identity.md) | 数据库绑定审批 + 工作负载身份 | proposed |
| [0004](0004-opentelemetry-prometheus-loki-tempo-stack.md) | 统一可观测栈 | proposed |
| [0005](0005-telemetry-is-untrusted-input.md) | 遥测视为不可信输入 | proposed |
| [0006](0006-temporal-postgresql-consistency-boundary.md) | Temporal/PostgreSQL 一致性边界 | proposed |
| [0007](0007-single-local-kubernetes-cluster-with-namespace-isolation.md) | 单本地集群 + namespace 隔离 | proposed |

## 6. 待 M0 后创建/决定

- k3d 与 kind 的具体 provider 选择。
- Python/Node/数据库/Temporal 的锁定版本。
- 模型 provider、模型版本和 fallback 策略。
- 本地 ID 类型（UUIDv7 或 ULID）。
- policy 是否需要 OPA（MVP 默认不引入）。
- 公开许可证、版本策略和发布渠道。

这些事项没有足够证据前不创建空 Accepted ADR。

## 7. 评审流程

1. 提交 proposed ADR 与可重复 spike/测试计划。
2. 架构、安全、运维和评测角色按影响评审。
3. 执行门槛并链接原始证据 hash/commit。
4. 更新状态和日期，记录 dissent/限制。
5. 同步架构、Backlog、风险、部署和证据账本。
