# 风险登记与处置

## 1. 评分与状态

- 可能性 L：1 极低，5 很高。
- 影响 I：1 可忽略，5 会破坏安全/核心交付。
- 分数：`L × I`；15–25 极高，8–14 高，4–7 中，1–3 低。
- 状态：`OPEN`、`MITIGATING`、`ACCEPTED`、`CLOSED`。

当前全部为开发前判断，不代表风险已经验证或关闭。Owner 使用角色而非虚构个人姓名。

## 2. 风险总表

| ID | 风险 | L | I | 分数 | Owner | 状态 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| RSK-001 | 主场景故障与 Runbook 无真实因果关系 | 2 | 5 | 10 | product/architecture | MITIGATING |
| RSK-002 | Action 超时导致重复副作用 | 3 | 5 | action/runtime | OPEN |
| RSK-003 | 审批可篡改、重放或被错误身份消费 | 3 | 5 | security | OPEN |
| RSK-004 | 遥测提示注入改变调查或外发边界 | 4 | 5 | AI/security | OPEN |
| RSK-005 | Temporal 与 PostgreSQL 投影漂移 | 3 | 4 | runtime/data | OPEN |
| RSK-006 | 六场景/prompt 泄漏导致评测虚高 | 4 | 4 | evaluation | OPEN |
| RSK-007 | 完整观测栈超出 Windows 主机资源 | 4 | 3 | platform | OPEN |
| RSK-008 | 数据库锁或网络故障 cleanup 不可靠 | 3 | 4 | scenario | OPEN |
| RSK-009 | 高基数/大查询拖垮观测栈或泄露数据 | 3 | 4 | observability | OPEN |
| RSK-010 | local-only 身份被误述为生产级鉴权 | 3 | 4 | product/security | OPEN |
| RSK-011 | ground truth 泄露给 Investigator | 3 | 4 | scenario/evaluation | OPEN |
| RSK-012 | light profile 被误报为完整 E2E | 4 | 3 | release | OPEN |
| RSK-013 | 模型波动、限流或价格变化破坏复现 | 4 | 3 | AI/evaluation | OPEN |
| RSK-014 | 项目范围过重，停留在基础设施搭建 | 4 | 4 | project | OPEN |
| RSK-015 | 恶意/敏感遥测进入日志、模型或事故包 | 3 | 5 | security/data | OPEN |
| RSK-016 | Workflow 升级产生非确定性错误 | 3 | 5 | runtime/release | OPEN |
| RSK-017 | Scenario Runner 或 Gateway 权限越界 | 2 | 5 | platform/security | OPEN |
| RSK-018 | 自动恢复被误当作 AI 修复成果 | 4 | 3 | evaluation/product | MITIGATING |
| RSK-019 | 安全指标通过“拒绝一切”被投机满足 | 3 | 4 | evaluation/security | OPEN |
| RSK-020 | 缺少 Git/版本锁定导致报告无法追溯 | 5 | 3 | release | OPEN |

## 3. 处置明细

### RSK-001：故障与动作因果

- 触发：Runbook 后 SLI 恢复，但相同故障无需动作也会恢复；或 cleanup 先发生。
- 缓解：Pod 崩溃改为自动恢复；容量过载对应 scale；进程内 latch 对应 restart；验证期间保持 fault/负载。
- 应急：冻结对外“自动恢复”表述，重新设计场景并提升版本。
- 关闭证据：对照组、动作组与 cleanup 时间线证明因果。

### RSK-002：重复副作用

- 触发：Gateway submit 超时、第二个 ActionExecution/patch、目标 generation 异常。
- 缓解：DB 原子登记、全局幂等键、固定 restart token、`RECONCILING`、同目标 partial unique。
- 应急：kill switch、禁止新动作、人工协调 K8s 最终状态。
- 关闭证据：并发/超时/Worker 重启攻击矩阵重复副作用为 0。

### RSK-003：审批完整性

- 触发：plan/target/policy 变化后旧 approval 可用；并发批准两次。
- 缓解：不可变 Decision、plan hash、UID/observedGeneration/resourceVersion、过期/nonce/消费次数；Gateway 独立 DB 读取。
- 应急：撤销 pending approvals、轮换服务凭据、保持 kill switch。

### RSK-004：提示注入

- 触发：遥测影响 tool catalog/risk/egress，或模型生成 R3 被接受。
- 缓解：untrusted envelope、模板工具、双重脱敏、无通用 HTTP/Shell、Gateway 确定性拒绝。
- 应急：禁用 provider/调查器，保留只读人工模式，分析攻击 fixture。

### RSK-005：双状态漂移

- 触发：Workflow checkpoint 与 projection 不一致、outbox 长期积压。
- 缓解：Workflow 唯一推进、幂等投影、outbox/inbox、对账与 reproject。
- 应急：kill switch；DB 落后重建，DB 超前不自动覆盖。

### RSK-006：评测污染

- 触发：prompt 包含场景名/答案，固定文本高命中但变体失败。
- 缓解：dev/calibration/holdout 隔离、参数/服务/噪声变体、消融和版本 hash。
- 应急：废弃受污染报告，创建新 dataset 版本，不能只删失败样本。

### RSK-007：主机资源

- 触发：OOM、频繁 swap、Collector 丢数据、启动不可稳定重复。
- 缓解：M0 k3d/kind/stack 基准；light profile；资源配额和保留/采样。
- 应急：缩小非核心观测组件，但报告标记 profile，不冒充 full。

### RSK-008：cleanup 残留

- 触发：代理规则、latch、镜像、副本、持锁连接任一无法确认。
- 缓解：精确 run/target、硬超时、逆序 cleanup、CLEAN/DIRTY gate。
- 应急：阻止新 run、导出证据、专用恢复或重建环境。

### RSK-009：查询与基数

- 触发：series/label 预算超限、查询延迟/内存异常、跨服务数据返回。
- 缓解：模板查询、固定 labels/group-by、time/series/rows 上限、截断。
- 应急：禁用问题模板，保留其他信号，重新做 cardinality 基准。

### RSK-010：身份表述

- 触发：README/简历使用企业 IAM/生产鉴权描述。
- 缓解：所有界面/报告标 `local-only`；发布 gate 检查 claims；未来 OIDC 单独 ADR。
- 应急：撤回材料并更正，不用功能可用性替代安全证明。

### RSK-011：ground truth 泄漏

- 触发：Investigator 网络/配置/日志可读取 expected root cause。
- 缓解：单独身份、配置包、接口和测试；ground truth 仅 Scenario Runner/Evaluator。
- 应急：废弃相关评测，修复隔离后新 dataset/version 重跑。

### RSK-012：profile 混淆

- 触发：fixture 路径报告显示 full 结果或缺 profile metadata。
- 缓解：报告强制 profile、full capability precheck、UI 环境标识。
- 应急：结果标不可比较/无效，补 full E2E。

### RSK-013：模型不稳定

- 触发：输出 Schema 失败率、429、成本或模型版本变化。
- 缓解：固定 alias/version、有限重试、重复运行、失败分类、成本预算。
- 应急：安全升级人工；不切未评测 fallback，不隐藏失败。

### RSK-014：范围失控

- 触发：M1 前加入 Kafka/Service Mesh/eBPF/多租户等，或里程碑长期无可演示产物。
- 缓解：严格非目标、每 M 可独立验收、P0 路径优先。
- 应急：删除未产生实际价值的 planned scope，不重构已有稳定内容。

### RSK-015：敏感数据泄露

- 触发：secret scanner 命中、导出包含凭据、provider 收到不必要原文。
- 缓解：合成数据、采集/送模/导出三层脱敏、最小保留、allowlist 字段。
- 应急：轮换秘密、阻止导出、审查历史与影响，不能只删除当前文件。

### RSK-016：Workflow 非确定性

- 触发：新 Worker replay 失败、运行中 Workflow 卡死。
- 缓解：history fixtures、Worker versioning、确定性代码规则、版本兼容。
- 应急：保留旧 Worker、kill switch、前向兼容修复。

### RSK-017：权限越界

- 触发：角色能读 Secrets、exec、写其他 namespace 或控制面。
- 缓解：独立 SA/RBAC/NetworkPolicy、目标 allowlist、TokenReview audience、负向测试。
- 应急：撤销 SA/RoleBinding、kill switch、轮换 token/DB role、审查动作。

### RSK-018：恢复归因错误

- 触发：`recovery_actor=SCENARIO_RUNNER` 或 Kubernetes 自动拉起仍计 AI success。
- 缓解：分离 remediation/cleanup，自动恢复无 ActionExecution，报告按 actor 分类。
- 应急：重新计算指标和撤回错误 claim。

### RSK-019：拒绝一切

- 触发：危险拦截 100% 同时合法 R1 全被拒绝。
- 缓解：同时报告合法 R1 接受/误拒、正确升级和完成率。
- 应急：安全 gate 仍不降低，修复 policy 精度后重测。

### RSK-020：追溯缺失

- 触发：报告没有 commit/digest/lock hash，当前目录未初始化 Git。
- 缓解：进入代码阶段前初始化版本控制；报告 Schema 强制 metadata。
- 应急：标记报告不可发布，不根据其填写简历数字。

## 4. 评审节奏

- 每个里程碑开始/结束评审一次极高/高风险。
- 安全 gate、场景、Runbook、SLO、provider、架构或 profile 变化时即时评审。
- 分数下降必须有验证证据；不能因“已有文档”直接关闭。
- 已接受风险说明接受者角色、期限和外部表述限制，到期重新评估。
