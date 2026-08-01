# ADR-0007：单本地 Kubernetes 集群与 namespace 隔离

- 状态：proposed
- 提出日期：2026-08-01
- 决策者角色：platform、security、architecture

## 背景

项目要展示 Kubernetes、最小权限和故障注入，同时在个人 Windows 主机可复现。双集群隔离更强，但资源和启动成本可能阻断 MVP；Docker Compose 又无法完整展示目标权限/资源语义。

## 驱动因素

- full 演练需要 Kubernetes API/RBAC/NetworkPolicy。
- 故障不能影响控制面和观测栈。
- 本地 CPU/内存有限。
- 环境必须可销毁、可重建和明确清理。

## 候选方案

1. Docker Compose：资源轻，但 K8s 权限/状态/Runbook 不真实。
2. 单本地集群 + 四 namespace：资源可控，隔离弱于双集群。
3. 控制/演练双本地集群：隔离强，资源和网络复杂。
4. 远程托管集群：成本/数据/复现边界不符合本地项目。

## 拟议决定

full profile 使用一个本地 Kubernetes 集群，四个 namespace：`sentinel-system`、`observability`、`demo-shop`、`sentinel-chaos`。独立 ServiceAccount、RBAC、NetworkPolicy 和 ResourceQuota；Scenario/Action 目标 allowlist 仅 `demo-shop`。具体 provider k3d/kind 由 M0 另行决定。

## 正面后果

- 一个集群降低本地资源和网络复杂度。
- 能真实验证 K8s API、RBAC、namespace 和 rollout。
- 环境可通过项目 metadata 精确创建/销毁。

## 负面后果

- namespace 不是强安全隔离，集群控制面是共享故障域。
- NetworkPolicy 支持依赖本地 CNI/provider。
- 不能代表生产多集群架构或 HA。

## 验证门槛

- k3d/kind 候选连续启停、网络策略、卷和资源 spike。
- Scenario/Gateway/Diagnostic 正负权限测试通过。
- 故障注入无法选择 sentinel-system/observability。
- full 栈在目标主机资源内，cleanup 后无项目外资源变化。

## 回退/重审

如果单集群故障频繁影响控制面或权限隔离无法实现，评估双集群；若资源不足，light 可用 fixture，但正式 E2E 不降级冒充 full。

## 关联

[架构](../architecture.md)、[本地开发与部署](../local-development-and-deployment.md)、[场景目录](../scenario-catalog.md)
