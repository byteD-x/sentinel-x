# Sentinel-X 完整文档地图

## 1. 当前状态

当前是 **D1-light 原型建设中**：已有控制台、Control API、Action Gateway、Incident Worker、共享包、演练服务、场景 fixture、基础设施草案和自动化测试。文档仍是跨模块契约与目标边界的事实来源；代码中已落地的 light/prototype 能力应回链到证据账本，未完成的 full profile、持久存储、Temporal Server replay、数据库绑定审批和固定 benchmark 仍保持 `proposed` 或 `untested`。

阅读本文时请区分：

- `implemented`：代码或配置可定位，但不等于完整验收。
- `tested`：有本地可重复命令通过，但只覆盖命令声明的范围。
- `measured`：固定场景/环境/样本报告完成后才能用于对外指标。
- `proposed`：目标方案或设计约束，不能写成已实现能力。

## 2. 推荐阅读路径

### 先理解产品

1. [项目 README](../README.md)：30 秒理解定位、边界和目标闭环。
2. [产品需求](product-requirements.md)：用户、价值、MVP、非目标和产品验收。
3. [术语表](glossary.md)：状态、风险、组件和命名的唯一解释。
4. [Web Console UX](user-experience-spec.md)：页面、信息层级、审批交互和无障碍。

### 再理解系统如何工作

1. [系统架构](architecture.md)：组件、部署、数据流和信任边界总览。
2. [领域模型](domain-model-and-contracts.md)：规范状态、实体、事件和不变量总表。
3. [API 契约](api-contracts.md)：认证、HTTP、SSE、幂等、并发和内部 Action API。
4. [数据模型](data-model.md)：表、约束、事务、outbox、审计和保留。
5. [Workflow 设计](workflow-design.md)：Temporal、Activity、Signal、重试、协调和对账。
6. [LLM 与工具协议](llm-and-tooling-protocol.md)：调查循环、四类工具、Evidence、预算和注入防护。

### 然后理解演练与安全

1. [场景目录](scenario-catalog.md)：六类故障的因果、ground truth、证据、恢复和 cleanup。
2. [Runbook 规范](runbook-specification.md)：两种 R1 动作、审批绑定、幂等和失败协调。
3. [可观测性与 SLO](observability-and-slo.md)：信号 Schema、SLI、告警和恢复窗口。
4. [安全模型](security-model.md)：威胁、角色、风险和核心控制。
5. [安全控制矩阵](security-control-matrix.md)：Threat -> Control -> 负向测试 -> 残余风险。
6. [测试与评测](testing-and-evaluation.md)：测试分层、基线、数据集、指标和报告协议。

### 最后按计划实施与交付

1. [开发计划](development-plan.md)：M0–M6 里程碑与关键路径。
2. [工程 Backlog](engineering-backlog.md)：可直接领取的工作项、依赖和验收。
3. [配置字典](configuration-reference.md)：变量、默认、秘密和 profile。
4. [本地开发与部署](local-development-and-deployment.md)：资源、端口、启停、清理和 Windows 约束。
5. [运维手册](operations-runbook.md)：kill switch、dirty、对账、备份、升级和排障。
6. [需求追踪](requirements-traceability.md)：FR/NFR 到组件、测试、报告和演示。
7. [风险登记](risk-register.md)：风险评分、触发、缓解和应急。
8. [发布门禁](release-readiness.md)：D0–D3 Go/No-Go 和产物。
9. [证据账本](evidence-ledger.md)：简历/README claim 的证据等级。
10. [10 分钟演示](demo-runbook.md)：实时演示、回放、失败兜底和 cleanup。

辅助资料：[ADR 索引](adr/README.md)、[官方参考](references.md)、[贡献指南](../CONTRIBUTING.md)、[安全报告政策](../SECURITY.md)、[Agent 规则](../AGENTS.md)。

当前实现进度与验证记录见 [.codex/mvp-progress.md](../.codex/mvp-progress.md)。

## 3. 唯一事实来源

| 事实 | 唯一详细来源 | 其他文档如何使用 |
| --- | --- | --- |
| 用户、MVP、非目标、FR | `product-requirements.md` | 只摘要/引用 |
| 术语、规范命名 | `glossary.md` | 不自造同义状态 |
| 组件/部署/信任边界 | `architecture.md` | 细节下沉到专项契约 |
| Incident 状态/实体/事件 | `domain-model-and-contracts.md` | API/DB/Workflow 实现它 |
| HTTP/SSE/认证/幂等 | `api-contracts.md` | 实现后 OpenAPI 执行化 |
| 表/事务/outbox/保留 | `data-model.md` | 实现后 migration 执行化 |
| Temporal 长流程 | `workflow-design.md` | 状态枚举仍引用领域模型 |
| 调查、工具、prompt、预算 | `llm-and-tooling-protocol.md` | 安全/评测引用 |
| 场景因果与 cleanup | `scenario-catalog.md` | fixture 执行化 |
| R1 动作语义 | `runbook-specification.md` | policy/Action 实现 |
| 遥测、SLI、告警、恢复 | `observability-and-slo.md` | 实现后规则/仪表盘执行化 |
| UI 页面与交互 | `user-experience-spec.md` | OpenAPI 提供数据 |
| 威胁与安全原则 | `security-model.md` | 控制矩阵提供验证映射 |
| 测试/评测公式 | `testing-and-evaluation.md` | 报告 Schema 执行化 |
| 配置 | `configuration-reference.md` | `.env.example` 只列模板 |
| 工作顺序 | `engineering-backlog.md` | 开发计划保留里程碑总览 |
| Claim 等级 | `evidence-ledger.md` | README/简历不得越级 |

## 4. 文档同步矩阵

| 变化 | 必须同步 |
| --- | --- |
| FR/MVP/非目标 | 产品需求、追踪矩阵、Backlog、README |
| 状态/实体/事件 | 领域模型、API、数据、Workflow、测试、UX |
| 场景/ground truth/cleanup | 场景目录、SLO、测试、追踪、演示、dataset version |
| Runbook/动作/审批 | Runbook、API、数据、Workflow、安全矩阵、测试 |
| 工具/prompt/provider/预算 | LLM 协议、配置、测试、风险、证据账本 |
| SLI/告警/窗口 | 可观测性、场景、测试、报告/baseline version |
| 身份/RBAC/NetworkPolicy | 安全模型/矩阵、API、部署、运维、ADR |
| profile/端口/命令 | 配置、开发部署、运维、README（命令已实现后） |
| 架构选择 | ADR、架构、风险、Backlog、相关专项契约 |
| 公开 claim/指标 | 证据账本、发布门禁、README/简历、报告 |

## 5. 状态更新规则

- 文档完成只能证明 DESIGNED/D0。
- 代码和配置可定位后标 IMPLEMENTED。
- 可重复测试和原始输出后标 TESTED。
- 固定环境/数据集报告后标 MEASURED。
- 脱敏证据包可复查后标 PUBLISHED。

实现完成后，把相应 `proposed` 转为事实并附证据。不能用文件数量、服务 Ready、`skipped` 或一次演示替代效果和安全验收。
