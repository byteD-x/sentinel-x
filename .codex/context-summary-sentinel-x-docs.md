# Sentinel-X 完整开发前基线上下文摘要

## 任务范围

在 `E:\Project\sentinel-x` 初始化完整开发前资料和安全默认工程模板，不创建业务实现、不运行不存在的构建/测试、不虚构指标。所有技术选择标 `proposed`，所有数值标初始目标/待测。

## 本地参考

只读检查以下项目的 README、AGENTS、架构、测试、SLO、部署、路线和演示资料：

- `E:\Project\customer-ai-runtime`
- `E:\Project\rag-qa-system`
- `E:\Project\paper-retrieval-platform`

官方依据覆盖 OpenTelemetry、Temporal、Kubernetes、Prometheus/Loki/Tempo、Google SRE、OpenAPI/JSON Schema、OWASP LLM 和 WCAG；链接集中在 `docs/references.md`。

## 子代理记录

| 子代理 | 范围 | 关键采用结果 | 写入 | 状态 |
| --- | --- | --- | --- | --- |
| `candidate_gap` | 简历/岗位能力缺口与面试穿透审计 | 增加抗泄漏评测、证据账本、合法 R1 接受率；修正模型分数不是统计置信区间 | 无，只读 | completed |
| `doc_patterns` | 现有项目文档模式与完整性审计 | 建立专项事实来源、cleanup/remediation 分离、运行/UX/观测细化 | 无，只读 | completed |
| `sentinel_arch` | 架构、安全、运行时与二次风险审计 | 修正主演示因果链、无动作验证路径、审批授权、Action 超时协调和双状态边界 | 无，只读 | completed |

主代理复核并整合全部结论；子代理未修改文件，均已结束。

## 最终统一定义

- 事故状态：`DETECTED -> TRIAGING -> DIAGNOSING`，之后按动作、自动恢复或升级分支，最终进入 `RESOLVED | ESCALATED | FAILED`。
- 风险：R0 只读无外部副作用；R1 可逆动作需审批；R2 MVP 禁用；R3 永久禁止。
- 场景因果：Pod 崩溃自动恢复；容量过载对应受限扩容；进程内锁存 5xx 对应滚动重启；Redis/DB lock/bad deployment 正确升级。
- cleanup：Scenario Runner 恢复测试夹具，不计 AI remediation。
- 审批：Worker 服务身份与动作授权分离；Gateway 独立读取并原子消费不可变审批。
- 数据：Temporal 权威流程，PostgreSQL 权威外部命令/审批/动作登记并保存幂等投影，通过 outbox 和对账协调。
- 模型：只用登记的 R0 查询模板；遥测为不可信输入；ground truth 与 holdout 隔离。

## 交付类别

- 产品/体验：PRD、术语、UX、场景、Runbook、演示。
- 平台契约：架构、领域、API、数据、Workflow、LLM/工具、观测/SLO。
- 安全/质量：安全模型、控制矩阵、测试评测、需求追踪。
- 工程运行：配置、开发部署、运维、Backlog、风险、发布和证据账本。
- 决策/依据：7 份 proposed ADR 与官方参考。
- 根准备文件：`.env.example`、`.editorconfig`、`.gitattributes`、`.gitignore`、SECURITY、CONTRIBUTING、CHANGELOG、AGENTS。

## 明确未做

- 未初始化 Git、创建 commit/branch 或选择许可证。
- 未创建业务代码、依赖锁、容器、Kubernetes 清单、CI 或可运行脚本。
- 未执行运行时、性能、安全攻击或 E2E 测试。
- 未把任何技术状态更新为“已实现”，未生成简历数字。
