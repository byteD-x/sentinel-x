# 贡献指南

## 基本流程

1. 从 [文档地图](docs/README.md) 找到目标事实的唯一归属文档。
2. 在修改前写清输入、输出、边界和验证方式。
3. 做最小范围修改，遵守 [AGENTS.md](AGENTS.md) 的安全红线与同步规则。
4. 先运行与改动最接近的验证，再运行受影响范围的回归。
5. 提交说明包含 What、Why、How to verify 和剩余风险。

详细事实归属和同步矩阵见 [完整文档地图](docs/README.md)。修改状态、场景、Runbook、SLO、API、数据、Workflow、安全或评测时，必须同步 [需求追踪](docs/requirements-traceability.md) 和受影响的 [工程 Backlog](docs/engineering-backlog.md)。

## 当前文档阶段

- 文档使用 UTF-8 和简体中文；代码标识、事件名、状态值保留英文。
- 架构选型未被代码验证前使用 `proposed`，不能写成“已使用”。
- 指标必须同时给出测量口径；没有报告时使用“目标”或“待测”。
- 新术语先加入 [术语表](docs/glossary.md)，新状态/实体/事件再加入 [领域模型](docs/domain-model-and-contracts.md)。
- 难以回退的实现决策按 [ADR 规则](docs/adr/README.md) 创建；没有 spike/评审证据时保持 `proposed`。
- 对外 claim 按 [证据账本](docs/evidence-ledger.md) 升级，不在 README 或简历中手填无来源数字。

## 未来代码阶段

计划采用下列质量门禁，最终命令以代码骨架落地后的项目配置为准：

| 范围 | 预期门禁 |
| --- | --- |
| Python | Ruff、类型检查、pytest、`compileall` |
| Web | lint、TypeScript 类型检查、单元测试、生产构建 |
| Workflow | 重放测试、超时/重试测试、Worker 重启恢复测试 |
| 基础设施 | Compose/Kubernetes/Helm 清单渲染与策略检查 |
| 安全 | 审批绕过、越权、提示注入、重放、敏感信息泄露回归 |
| 评测 | 固定 fixture、固定配置、机器可读报告与 baseline 比较 |

不要在对应配置和测试尚未落地前把这些门禁写成已经通过。

## 变更审查重点

- 是否扩大了模型或执行器权限。
- 是否绕过审批、幂等或目标状态校验。
- 是否破坏领域状态与 Temporal Workflow 的职责边界。
- 是否让不可信遥测影响系统指令或动作参数。
- 是否修改了评测口径但未更新 baseline 版本。
- 是否引入了 MVP 之外的重依赖或非必要抽象。
