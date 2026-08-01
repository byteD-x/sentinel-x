# ADR-0004：OpenTelemetry + Prometheus/Loki/Tempo 可观测栈

- 状态：proposed
- 提出日期：2026-08-01
- 决策者角色：observability、architecture、evaluation

## 背景

项目要展示跨指标、日志、Trace 和 Kubernetes 状态的根因调查，并通过稳定查询复现 Evidence。自建遥测协议或只使用单一日志源无法支持目标。

## 驱动因素

- 三类信号统一 context/resource。
- 成熟查询和可视化生态。
- 原始遥测与领域状态分离。
- 本地可运行、可导出、可限定查询。

## 候选方案

1. 仅 Prometheus + 应用日志文件：资源轻，但 Trace/关联和查询不足。
2. OTel + Prometheus/Loki/Tempo/Grafana：组件较多，覆盖完整。
3. OpenSearch/Elastic 统一存储：能力强但本地资源和运维更重。
4. 商业 SaaS：快速，但数据外发、成本和离线复现受限。

## 拟议决定

应用使用 OpenTelemetry SDK/Collector；Prometheus 存指标，Loki 存日志，Tempo 存 Trace，Grafana 展示。PostgreSQL 只保存查询、脱敏摘要、hash 和 source_ref。light profile 可用 fixture，但正式 benchmark 只认 full。

## 正面后果

- 使用标准语义和 Trace Context。
- 每类信号有成熟专用后端，Evidence 可追溯。
- 可展示真实的可观测性工程和查询边界。

## 负面后果

- full 栈内存/磁盘和启动复杂度高。
- 三后端保留/健康/查询失败需分别处理。
- 需要严格 label/cardinality/sampling 设计。

## 验证门槛

- 三服务 traceparent 贯穿，错误 Trace 与日志/指标按 run 关联。
- 固定 6 场景所需 Evidence 在窗口内可查询。
- full 资源满足 M0/M1 目标，保留/采样不丢关键错误。
- Diagnostic 模板限制 series/rows/spans 并拒绝任意查询。

## 回退/重审

若 full 栈资源阻断目标主机，先减少非核心 UI/保留和使用裁剪部署；替换后端必须保持 OTel 与 Evidence 契约，不在 light 结果上宣称 full。

## 关联

[可观测性与 SLO](../observability-and-slo.md)、[LLM 工具协议](../llm-and-tooling-protocol.md)、[部署](../local-development-and-deployment.md)
