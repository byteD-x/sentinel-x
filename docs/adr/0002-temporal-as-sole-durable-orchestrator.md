# ADR-0002：Temporal 作为唯一持久编排

- 状态：proposed
- 提出日期：2026-08-01
- 决策者角色：architecture、runtime、AI

## 背景

事故流程需要跨分钟运行、等待审批、处理重试、Worker 重启和动作协调。普通后台任务或只存在内存的 Agent graph 难以可靠恢复；同时叠加多个编排引擎会产生双状态。

## 驱动因素

- 确定性重放和持久 timer。
- Activity retry/timeout/heartbeat 与人工 Signal。
- Worker 重启后不丢状态。
- 避免 Temporal + LangGraph 双编排和重复 checkpoint。

## 候选方案

1. Celery/队列 + 数据库状态机：简单任务成熟，但长等待/重放/协调需大量自建。
2. LangGraph checkpoint：适合 Agent 图，但审批、外部副作用协调和长期运维仍需额外机制。
3. Temporal：复杂度较高，但直接覆盖 durable execution。
4. Temporal 外层 + LangGraph 内层：灵活但 MVP 双状态和调试成本过高。

## 拟议决定

Temporal 是事故与演练长流程的唯一 durable orchestrator。LLM 调用和每个诊断/投影/动作/验证都作为 Activity；MVP 不使用 LangGraph。若未来只读调查分支复杂到 controller 难以维护，可在单个 Activity 内评估 LangGraph，但它不能推进 Incident 或执行写动作。

## 正面后果

- 审批等待、重试和 Worker 恢复有统一语义。
- Workflow history 可用于 replay 测试和事故审计引用。
- 写动作超时可围绕固定幂等键协调。

## 负面后果

- 增加 Temporal 服务、Worker versioning 和 determinism 学习成本。
- history 与 PostgreSQL projection 需要明确对账。
- 本地完整栈资源增加。

## 验证门槛

- M0 spike 通过 Signal 等待、Activity retry、三个重启点和 replay。
- Action submit timeout 用固定 key 不重复副作用。
- 1000 event/目标 history 基准与 continue-as-new 可行。
- Windows full profile 资源可接受。

## 回退/重审

如果 M0 证明 Temporal 资源/部署不可接受且数据库状态机能以更低成本满足全部恢复测试，创建 superseding ADR；不能边实现边保留两套权威流程。

## 关联

[Workflow 设计](../workflow-design.md)、[数据模型](../data-model.md)、[开发计划](../development-plan.md)
