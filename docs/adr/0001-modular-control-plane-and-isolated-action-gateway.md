# ADR-0001：模块化控制面与独立 Action Gateway

- 状态：proposed
- 提出日期：2026-08-01
- 决策者角色：architecture、security、platform

## 背景

Sentinel-X 同时包含低风险的事故读写/调查和高风险的 Kubernetes 恢复动作。首版如果拆成大量微服务会放大部署、网络和一致性成本；如果所有能力都在单进程，又无法形成可信的动作权限边界。

## 驱动因素

- 模型/调查代码不能拥有演练环境写身份。
- 空仓库 MVP 需要控制复杂度和本地资源。
- 状态、审批、时间线应在单一领域边界内演进。
- 动作执行要能独立最小权限、审计和 kill switch。

## 候选方案

1. 单体包含执行器：最简单，但写权限与模型同进程，边界过弱。
2. 全微服务：隔离强，但本地运维、协议和一致性过重。
3. 模块化单体控制面 + 独立 Action Gateway：平衡复杂度和安全。

## 拟议决定

Control API 按 incidents/scenarios/approvals/timeline 模块组织，Incident Worker 独立进程承载 Temporal，Web Console 独立前端；这些共享 contracts/domain。Action Gateway 是独立部署、独立 ServiceAccount、独立数据库权限的服务，不链接 LLM provider 或通用诊断工具。

## 正面后果

- 绝大多数业务保持进程内模块边界，减少早期网络接口。
- 写权限和模型密钥物理/身份分离。
- 可单独安全测试、停用和部署 Gateway。

## 负面后果

- 仍需内部 Action API、服务身份和跨进程协调。
- 模块化纪律依赖代码审查，未来可能出现共享包耦合。
- Control API/Worker 不等于高可用，MVP 不解决生产 HA。

## 验证门槛

- Gateway 镜像/进程无法读取 LLM key。
- Worker/Diagnostic 身份无法写 Kubernetes；Gateway 无 Secrets/exec/跨 namespace。
- Gateway 不接受 plan body 授权，能在 Worker 伪造时独立拒绝。
- full 栈资源满足 M0 主机目标，微服务数量没有阻断本地复现。

## 回退/重审

- Gateway 独立服务的资源/复杂度明显超过安全收益时，可评估同 Pod 独立容器，但身份和进程仍隔离。
- 业务边界发展到独立扩缩/团队所有权时再拆其他模块，不为未来猜测提前拆。

## 关联

[架构](../architecture.md)、[安全模型](../security-model.md)、[API 契约](../api-contracts.md)、[Runbook](../runbook-specification.md)
