# ADR-0006：Temporal 与 PostgreSQL 的一致性边界

- 状态：proposed
- 提出日期：2026-08-01
- 决策者角色：runtime、data、architecture

## 背景

Temporal 擅长流程历史和恢复，但 UI/审批/查询需要关系读模型。两者同时存状态容易产生双权威和漂移；跨系统分布式事务又不实际。

## 驱动因素

- Workflow 决策可重放恢复。
- 用户审批先不可变落盘再通知 Workflow。
- UI 时间线可分页/SSE。
- outbox/Signal 至少一次投递可去重和对账。

## 候选方案

1. 只用 Temporal history 做所有查询：业务查询/审批/报告困难。
2. PostgreSQL 状态机为权威，Temporal 仅任务：弱化 durable decision，容易重复推进。
3. Temporal 权威流程 + PostgreSQL 外部命令/投影 + 幂等 Activity/outbox/对账。
4. 两者双写分布式事务：复杂、支持有限，不适合 MVP。

## 拟议决定

Temporal 是 Incident 流程/timer/retry 的权威；PostgreSQL 是用户 command/ApprovalDecision 和 Action 原子登记的权威，并保存 Workflow 的查询投影。Workflow 通过幂等 Activity 原子更新 projection/timeline/outbox。DB command 用 outbox + ID Signal Workflow。checkpoint 对账：DB 落后可重建，DB 超前/冲突不覆盖并启用 kill switch。

## 正面后果

- 每类事实有明确所有者。
- 不依赖分布式事务，重复投递可安全处理。
- UI 和报告可高效查询，Workflow 可恢复。

## 负面后果

- 需要 projector、outbox/inbox、checkpoint 和对账器。
- 短暂最终一致，UI 可能显示 stale 并需标记。
- 恢复点不一致时运维流程更复杂。

## 验证门槛

- 重复 Activity/Signal/outbox 不产生重复状态/动作。
- DB 落后能从显式 Workflow refs 重建。
- DB 超前/非法冲突触发告警/kill switch，不自动覆盖。
- Approval 决定落盘但 Signal 丢失可重投并只处理一次。

## 回退/重审

若投影复杂度超过收益，可减少读模型字段，但不能让两个系统都能独立推进 Incident。任何权威边界变化需要迁移和 superseding ADR。

## 关联

[数据模型](../data-model.md)、[Workflow 设计](../workflow-design.md)、[运维手册](../operations-runbook.md)
