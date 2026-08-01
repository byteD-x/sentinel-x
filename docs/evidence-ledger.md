# 项目声明与简历证据账本

## 1. 目的

本文件防止把设计、代码存在、测试通过和实测效果混为一谈。任何 README、作品集、简历或面试数字必须先在这里找到证据等级和来源。

等级：

- `D` Designed：有评审过的契约。
- `I` Implemented：代码/配置存在并可定位。
- `T` Tested：可重复测试通过，含命令与原始输出。
- `M` Measured：固定数据集/环境报告，含样本、版本和限制。
- `P` Published：脱敏证据包和公开链接可复查。

当前全部只达到 `D`；仓库没有业务代码、Git commit 或实测报告。

## 2. Claim 台账

| ID | 可对外声明主题 | 当前 | 当前可用表述 | 升级所需证据 |
| --- | --- | --- | --- | --- |
| CLM-01 | 持久化事故工作流 | D | “设计了 Temporal 持久工作流与重放/审批语义” | Worker restart/replay 测试、history refs、commit |
| CLM-02 | 跨指标/日志/Trace/K8s 调查 | D | “定义了四类受限诊断工具与 Evidence 引用协议” | full E2E、工具审计、Top-1 report |
| CLM-03 | 根因 Top-1 | D | “建立了 Top-1 与 B0/B1/C1 评测协议” | holdout dataset、样本数、模型/版本、原始报告 |
| CLM-04 | 安全审批与受控动作 | D | “设计了 R0–R3、不可变审批和独立 Gateway 边界” | 合法/非法 R1、篡改/重放/并发测试 |
| CLM-05 | 零重复副作用 | D | 不能声明已达到 | submit timeout/Worker restart/并发报告 effect=0 |
| CLM-06 | 固定攻击集拦截 | D | “定义了提示注入与越权攻击集” | 样本数、拒绝码、合法接受率、安全报告 |
| CLM-07 | 自动/受控恢复 | D | “设计了自动恢复、restart、scale 三种可区分路径” | 因果对照、SLO observed window、recovery_actor |
| CLM-08 | 可审计事故回放 | D | “定义了只追加时间线和 SSE 重连协议” | refresh/reconnect/export E2E、事故包 hash |
| CLM-09 | 本地 Kubernetes 最小权限 | D | “规划了 namespace/RBAC/NetworkPolicy 权限矩阵” | manifests、can-i/API 负向测试、镜像 digest |
| CLM-10 | 成本与资源治理 | D | “定义了 Token、查询和资源预算口径” | 每事故 Token/费用、CPU/内存/启动时间报告 |
| CLM-11 | 本地可复现 | D | “提供了 full/light 生命周期和验收设计” | 第二台干净环境 cold run、实际命令/时长 |
| CLM-12 | UI 指挥与审批体验 | D | “完成了指挥台信息架构和安全审批交互规格” | 4 视口截图、无障碍/并发/权限测试 |

## 3. 禁止的提前表述

在等级不足前禁止：

- “已使用 Kubernetes/Temporal/OpenTelemetry”用于描述当前仓库事实。
- “根因准确率 X%”“降低 MTTR X%”“成本降低 X%”。
- “生产级”“企业级”“高可用 AIOps”。
- “100% 安全”“零风险”“全自动修复”。
- “完整闭环”而没有真实恢复、正确升级、cleanup 和事故包证据。

固定攻击集确有 M 级报告后，只能写“在 N 个版本化攻击样本中拦截率为 X%”，并同时披露合法 R1 误拒。

## 4. 证据索引字段

每项 T/M/P 证据必须记录：

- claim ID、需求/控制/Backlog IDs。
- Git commit/branch、镜像 digest、依赖锁 hash。
- environment/profile/hardware/OS/cluster provider。
- dataset/scenario/model/prompt/policy/Runbook/SLO versions。
- 命令、开始/结束时间、样本数、随机种子。
- 原始 JSON/report/test log 路径与 SHA-256。
- 通过/失败/跳过数量和失败分类。
- 已知限制、是否可与 baseline 比较、脱敏状态。

## 5. 建议的证据包结构

```text
evidence/<release-id>/
├─ manifest.json
├─ verification-report.md
├─ evaluation-summary.md
├─ security-summary.md
├─ incidents/
├─ screenshots/
└─ checksums.txt
```

该目录当前不创建空内容。实际生成后，原始敏感 artifacts 保持忽略，只选取脱敏、可公开、已校验的证据进入版本控制或发布附件。

## 6. 简历条目生成门槛

一条量化简历 bullet 至少需要：

1. M 级结果，绑定 claim 和需求。
2. 样本数、环境和版本完整。
3. 对照 baseline 或明确绝对口径。
4. 失败样本没有从分母静默删除。
5. 安全边界和 local-only 限制不被省略到产生误导。
6. 公开时证据达到 P；不公开时面试可展示脱敏本地产物。

## 7. 更新责任

- 实现者提交 I/T 证据。
- Evaluator/安全评审者确认 M 级口径。
- 发布者确认 P 级脱敏、hash 和链接。
- 任何口径/版本变化把旧证据标 `STALE`，不覆盖历史。
