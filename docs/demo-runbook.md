# 10 分钟演示手册

## 1. 演示目标

在 10 分钟内证明三件事：Sentinel-X 能依据跨信号证据定位故障；有影响的动作不能绕过审批与策略；恢复结果由 SLO 验证并可完整回放。

本文是目标演示流程。仓库当前没有可执行命令或 UI，只有实现和预检全部通过后才能按此演示。

## 2. 演示场景

主场景使用 `inventory-latched-5xx@1`：

- 稳定订单流量正在运行。
- `inventory-api` 当前进程进入只存在于内存的持续 5xx 锁存状态，新进程不会继承。
- ground truth 为 `LATCHED_RUNTIME_FAILURE + inventory-api`。
- 允许的 R1 动作为 `restart_deployment@1`。
- 恢复以订单成功率、库存错误率和稳定窗口共同判定，验证期间不调用 Scenario cleanup。

安全插曲使用带提示注入的日志样本，以及一次被修改参数的过期审批请求。它们只用于证明拒绝路径，不执行危险操作。

## 3. 演示前预检

至少提前完成：

- 固定 commit、镜像 digest、scenario、policy、prompt 和模型版本。
- 从干净环境运行未来的 `make doctor` 与 `make demo-up`，所有服务健康。
- 订单负载稳定，未注入故障时 SLO 在基线内。
- 6 个场景完成注入/清理自检，主场景至少预演一次。
- 当前没有活跃 Incident、未清理 ExerciseRun 或已消费审批。
- kill switch 关闭，演示账户角色明确，屏幕中没有秘密值。
- 完整演示报告目录可写；fallback 事故包已脱敏，manifest 中的 commit/digest/schema 与 checksums 已校验。

预检失败就停止现场注入，使用已归档事故包做只读回放，并明确说明不是实时 E2E。

## 4. 时间轴

| 时间 | 操作 | 预期画面/证据 |
| --- | --- | --- |
| 0:00–0:45 | 打开指挥台，展示健康拓扑和当前 SLO | 订单、库存、支付均正常；没有事故 |
| 0:45–1:15 | 启动 `inventory-latched-5xx@1` | ExerciseRun ID、场景版本、目标和计时开始 |
| 1:15–2:00 | 等待告警并打开 Incident | 库存错误率上升；告警指纹被去重；状态进入 `TRIAGING` |
| 2:00–3:30 | 观察自动调查 | 指标、日志、Trace、K8s Evidence 按时间线出现，显示查询来源和预算 |
| 3:30–4:15 | 查看根因假设 | Top-1 指向 inventory-api 的锁存运行时故障，不只给结论，还列支持/反对证据 |
| 4:15–5:15 | 打开修复提案 | 展示 Runbook 版本、R1、目标 UID/代次、参数、影响和 plan hash |
| 5:15–6:00 | 审批并执行 | Action Gateway 二次校验；只产生一次 ActionExecution 和 before/after |
| 6:00–7:15 | 等待验证窗口 | 新进程未继承 latch，订单成功率和库存错误率恢复；状态进入 `RESOLVED` |
| 7:15–8:30 | 回放事故 | 从故障注入、证据、模型决策、人工审批到 SLO 验证完整可追溯 |
| 8:30–9:30 | 展示安全拒绝 | 恶意日志不改变工具边界；篡改/过期审批被确定性拒绝 |
| 9:30–10:00 | 打开评测摘要 | 展示本次逐项结果、baseline、样本范围和限制；随后单独触发 Scenario cleanup，不把它计入恢复 |

## 5. 每段需要证明什么

### 调查阶段

- Trace 指出错误由 inventory 向 order 传播，指标说明影响范围，进程/K8s 状态说明 latch 只存在于旧实例，日志只是其中一类证据。
- 每个 Hypothesis 引用 Evidence ID，并可看到反对证据。
- 调查有最大步数、Token、时间范围和查询结果大小，不会无限循环。

### 审批阶段

- 审批者看到的是规范化动作和真实目标，不是“建议重启一下”的模糊句子。
- UI 明确展示风险、影响、回滚、过期时间和计划 hash。
- 修改任何绑定参数都会使原审批失效。

### 执行与验证阶段

- 模型不接触 Kubernetes 写权限；Action Gateway 使用独立身份。
- 同一幂等键重复提交返回原结果，不再次重启。
- HTTP 成功不是结束，只有 SLO 在稳定窗口内恢复才进入 `RESOLVED`。

### 安全阶段

- 显示恶意日志作为被引用的数据，而不是隐藏它；系统仍保持固定工具边界。
- 显示 Action Gateway 的稳定拒绝码，例如 `APPROVAL_EXPIRED` 或 `PLAN_HASH_MISMATCH`。
- 不尝试真实 R3 命令，不在演示中暴露 Secret 或管理员 kubeconfig。

## 6. 演示产物

结束时应能导出一个脱敏事故包：

- Incident 摘要与状态变化。
- Scenario/Runbook/policy/prompt/model 版本。
- Evidence 元数据、查询与来源引用。
- Hypothesis、RemediationPlan 和 ApprovalDecision。
- ActionExecution before/after 与幂等键 hash。
- VerificationResult 与修复前后窗口。
- EvalResult JSON、Markdown 摘要和原始报告 hash。
- 事故包 manifest、来源 commit/镜像 digest、schema 版本和 checksums 校验结果。

原始大日志、秘密值和可复用审批凭证不进入导出包。

## 7. 失败兜底

| 故障 | 现场处理 | 不得声称 |
| --- | --- | --- |
| 模型 provider 不可用 | 展示失败升级和已归档回放 | “实时 AI 诊断成功” |
| 观测栈查询失败 | 展示该 Activity 的错误与重试/升级 | “完整遥测链路通过” |
| 场景注入失败 | 停止实时演示，使用固定事故包 | “本次 E2E 通过” |
| 动作未恢复 SLO | 保持 `ESCALATED/FAILED` 并解释验证判定 | “已经自动恢复” |
| UI/SSE 中断 | 通过只读 API/报告展示持久状态 | “实时界面正常” |

失败是事故系统的重要路径。正确记录并升级比隐藏失败更能说明工程能力。

## 8. 清理

演示的恢复判定和评测结果冻结后，再执行未来的 `make demo-down` 或等价幂等清理，并在画面/时间线上明确标记 `SCENARIO_CLEANUP`，确认：

- 故障开关、Toxiproxy 规则和临时 patch 已撤销。
- `demo-shop` 回到基线副本与版本。
- 没有活跃 Incident、待审批请求或未完成 ActionExecution。
- 报告已归档，临时凭证和含敏感信息的本地数据按策略处理。

清理未通过时将环境标记为 dirty，不运行下一次 benchmark。
