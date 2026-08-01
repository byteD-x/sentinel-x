# Sentinel-X

> AI 事故指挥中心：在隔离的演练环境中，让 AI 像值班工程师一样收集证据、提出根因假设和恢复方案，但任何有影响的动作都必须经过策略校验与人工审批。

## 当前状态

**阶段：D0 完整开发前设计基线。** 当前仓库包含产品、架构、场景、Runbook、API、数据、Workflow、LLM/工具、UX、安全、测试、部署、运维、Backlog、风险、ADR 和发布资料，但没有可运行业务代码、构建产物、Git commit 或实测指标。文中技术栈均为拟议方案，指标均为目标值或待测项。

## 它要解决什么问题

线上故障发生后，工程师通常需要在告警、指标、日志、Trace 和 Kubernetes 状态之间来回切换。Sentinel-X 把这段过程组织成一条可回放的事故工作流：

```text
发现异常 -> 收集证据 -> 推断根因 -> 提出方案 -> 人工审批 -> 受控执行 -> 验证恢复 -> 复盘评测
```

重点不是“让模型随意操作服务器”，而是展示一套可解释、可恢复、可审计的 AI 工程系统。

## MVP 预期

- 在订单、库存、支付组成的微型商城中注入 6 类固定故障。
- 关联 Prometheus 指标、Loki 日志、Tempo Trace 和 Kubernetes 只读状态。
- 输出带证据引用的根因假设，而不是只给一段自然语言答案。
- 使用持久工作流处理重试、超时、暂停审批和进程重启恢复。
- 只执行预先登记、参数受限、可幂等的 Runbook。
- 对根因命中、诊断和恢复耗时、安全拦截及模型成本做可复现评测。
- 在时间线中回放每个参与者、证据、决策和动作。

## 安全边界

- 仅连接本地隔离演练环境，不连接真实生产系统。
- 诊断默认只读；遥测和工具返回值一律视为不可信输入。
- 模型不能使用任意 Shell、`kubectl`、`pods/exec`、Secrets 或集群管理员权限。
- MVP 只开放两种 R1 可逆动作：限定目标的 Deployment 重启和限定范围扩容，且必须人工审批。
- 数据库变更、跨服务变更和任意代码执行在 MVP 中禁用。

## 拟议技术方案

| 领域 | 方案 | 当前状态 |
| --- | --- | --- |
| 控制台 | React + TypeScript | proposed |
| 控制 API | FastAPI + Pydantic | proposed |
| 持久工作流 | Temporal | proposed |
| 领域存储 | PostgreSQL + SQLAlchemy + Alembic | proposed |
| 可观测性 | OpenTelemetry + Prometheus + Loki + Tempo + Grafana | proposed |
| 演练环境 | Kubernetes（k3d 或 kind） | proposed，待基准验证 |
| 故障注入 | 应用故障开关 + Toxiproxy + 受控 Kubernetes 操作 | proposed |
| 模型接入 | OpenAI-compatible provider | proposed |

## 文档入口

- [完整文档地图与阅读顺序](docs/README.md)
- [产品需求与验收](docs/product-requirements.md)
- [拟议系统架构](docs/architecture.md)
- [领域模型与接口契约](docs/domain-model-and-contracts.md)
- [安全与威胁模型](docs/security-model.md)
- [测试与评测设计](docs/testing-and-evaluation.md)
- [开发路线与环境准备](docs/development-plan.md)
- [10 分钟演示手册](docs/demo-runbook.md)
- [工程 Backlog](docs/engineering-backlog.md)
- [需求追踪矩阵](docs/requirements-traceability.md)
- [风险与发布门禁](docs/risk-register.md)
- [简历证据账本](docs/evidence-ledger.md)
- [贡献指南](CONTRIBUTING.md)
- [Agent 协作规范](AGENTS.md)

## 开始实现前

先完成 [开发路线](docs/development-plan.md) 中的 M0 决策和本机资源基准，再进入代码骨架阶段。任何与本文边界冲突的能力，必须先修改产品、安全和架构文档并完成评审。
