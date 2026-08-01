# 工程 Backlog 与交付顺序

## 1. 使用规则

本文件把 [开发路线](development-plan.md) 的 M0–M6 拆成可实现、可验收的工作项。当前所有项状态为 `PLANNED`，不表示已有实现。

状态：`PLANNED -> READY -> IN_PROGRESS -> BLOCKED -> DONE`。只有输入已具备、契约已评审、验证环境可用时才能进入 READY。

优先级：P0 阻断核心闭环，P1 阻断完整 MVP，P2 为增强。任何安全 P0 未完成时不得开启 R1。

## 2. 通用完成定义

每个工作项 DONE 需要：

- 代码/配置/文档与上游契约一致。
- 正常、边界和失败路径有自动测试或可重复验证。
- lint、类型、单元和受影响回归通过。
- 没有真实秘密、生产数据、未处理的高危扫描结果。
- 产物记录 commit、依赖/镜像版本、命令、环境和实际结果。
- 对安全、契约、SLO、场景或报告有影响时更新唯一事实来源。

## 3. M0：验证关键假设

| ID | P | 工作项 | 输入 | 输出/验收 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| M0-01 | P0 | k3d/kind 本机对比 spike | Windows + Docker Desktop | 启停/网络/卷/内存/清理原始报告；连续 3 次目标门槛 | 无 |
| M0-02 | P0 | Temporal durable spike | 最小 Python 环境 | Signal 等待、Activity retry、Worker 三点重启、replay 报告 | 无 |
| M0-03 | P0 | 模型结构化输出 spike | 候选 provider | 固定 Schema 成功/失败/Token/成本原始结果，不调用写工具 | 无 |
| M0-04 | P0 | 审批与服务身份 spike | 本地 K8s/DB | TokenReview audience、不可变审批读取、并发消费和过期测试 | M0-01 |
| M0-05 | P0 | OTel 关联与资源基准 | 三个最小服务 | traceparent、日志/指标/span 关联和 Collector 资源报告 | M0-01 |
| M0-06 | P0 | 固化首批 ADR 与版本 | M0-01..05 证据 | ADR 状态从 proposed 到 accepted/rejected；运行时版本锁定 | M0-01..05 |

M0 退出条件：关键选择有原始证据，完整栈资源可接受或轻量降级边界明确；否则调整架构而非直接进入开发。

## 4. M1：可观测演练底座

| ID | P | 工作项 | 输出/验收 | 依赖 |
| --- | --- | --- | --- | --- |
| M1-01 | P0 | 初始化 monorepo 与统一任务入口 | Python/Web 锁文件、任务命令、最小 CI；干净安装通过 | M0-06 |
| M1-02 | P0 | 实现 order/inventory/payment 最小链路 | 合成订单正常流、稳定错误码和契约测试 | M1-01 |
| M1-03 | P0 | 接入 PostgreSQL/Redis 与合成数据 | 无真实数据；事务/缓存失败可控，migration 可重复 | M1-02 |
| M1-04 | P0 | 全链路 OTel instrumentation | Resource/log/metric/span Schema 与关联测试通过 | M0-05, M1-02 |
| M1-05 | P0 | 部署观测栈和 dashboard 基线 | Prometheus/Loki/Tempo 查询及 freshness smoke | M1-04 |
| M1-06 | P0 | 实现场景 Schema 与 Scenario Runner | strict Schema、目标 allowlist、注入/cleanup 幂等 | M1-03, M1-05 |
| M1-07 | P0 | 实现 6 个固定场景 | 每场景连续注入/清理目标 3 次，无残留；ground truth 隔离 | M1-06 |
| M1-08 | P0 | 建立稳定负载与 SLO 基线 | 实际 RPS/并发/样本/窗口报告，冻结 `slo_policy_version` | M1-02, M1-05 |
| M1-09 | P1 | Alertmanager 规则与 webhook fixture | fingerprint、for 窗口、重复/resolved fixture | M1-05, M1-08 |

M1 退出条件：故障先于 AI 可复现，跨信号 Evidence 与标准答案一致，cleanup 与 remediation 分开记录。

## 5. M2：确定性事故运行时

| ID | P | 工作项 | 输出/验收 | 依赖 |
| --- | --- | --- | --- | --- |
| M2-01 | P0 | 生成 contracts 包 | Pydantic/JSON Schema/OpenAPI/TS 类型一致，未知字段拒绝 | M1-01 |
| M2-02 | P0 | 实现领域表和 migrations | 空库/升级样本、约束、索引、审计权限测试 | M2-01 |
| M2-03 | P0 | Alert Ingress 与去重事务 | HMAC/重放/body 上限/并发 fingerprint 测试 | M1-09, M2-02 |
| M2-04 | P0 | IncidentWorkflow 骨架 | 规范状态、Signal/Query、Activity 边界、replay fixtures | M0-02, M2-01 |
| M2-05 | P0 | projection/outbox/dispatcher | 原子投影、至少一次投递、消费者去重、积压恢复 | M2-02, M2-04 |
| M2-06 | P0 | Control API 事故读模型 | 列表/详情/cursor/ETag/角色契约测试 | M2-02, M2-05 |
| M2-07 | P1 | SSE timeline | sequence、Last-Event-ID、gap、慢客户端、410 测试 | M2-05, M2-06 |
| M2-08 | P0 | Workflow/DB 对账 | DB 落后重建、冲突告警/kill switch，不静默覆盖 | M2-05 |
| M2-09 | P0 | Worker 恢复矩阵 | 分诊/调查/等待审批等点重启不丢状态 | M2-04..08 |

M2 退出条件：不用 LLM 也能用 fixture 跑完所有合法状态/失败路径，历史 replay 与投影对账可重复。

## 6. M3：只读 AI 调查器

| ID | P | 工作项 | 输出/验收 | 依赖 |
| --- | --- | --- | --- | --- |
| M3-01 | P0 | Diagnostic Gateway 通用框架 | template allowlist、范围/limit/timeout、统一错误和审计 | M2-01, M1-05 |
| M3-02 | P0 | Metrics/Logs 工具 | 无原始 PromQL/LogQL，截断/脱敏/source_ref 测试 | M3-01 |
| M3-03 | P0 | Trace/K8s 只读工具 | trace 枚举受限；K8s 无 Secrets/exec/跨 namespace | M3-01 |
| M3-04 | P0 | Evidence 规范化与去重 | hash、freshness、truncated、重复 Activity 测试 | M3-02, M3-03 |
| M3-05 | P0 | Provider adapter 与 prompt bundle | 固定版本、Schema、timeout/429/解析失败和成本记录 | M0-03, M2-01 |
| M3-06 | P0 | 调查 controller/Hypothesis | 竞争假设、支持/反对证据、预算、停止/升级路径 | M3-04, M3-05 |
| M3-07 | P0 | 提示注入与秘密测试集 | tool/policy/egress 不变，固定攻击集确定性阻断 | M3-06 |
| M3-08 | P1 | B0/B1/C1 与抗泄漏数据集 | dev/calibration/holdout 隔离、消融和失败分类 | M1-07, M3-06 |

M3 退出条件：Investigator 只有 R0 工具；模型/provider/工具失败均安全升级，不能产生 ActionExecution。

## 7. M4：审批与受控恢复

| ID | P | 工作项 | 输出/验收 | 依赖 |
| --- | --- | --- | --- | --- |
| M4-01 | P0 | policy 与 plan validator | risk 不可降级、目标解析、canonical hash 和负向测试 | M3-06 |
| M4-02 | P0 | Approval API/不可变决定 | local-only 角色、CSRF、ETag、过期/撤销/并发一次决定 | M2-06, M4-01 |
| M4-03 | P0 | Action Gateway 服务骨架 | projected SA token、TokenReview、独立 DB role、kill switch | M0-04, M2-02 |
| M4-04 | P0 | Gateway gate/原子消费/幂等 | 篡改/重放/目标漂移/并发/同目标冲突全部拒绝 | M4-02, M4-03 |
| M4-05 | P0 | `restart_deployment@1` | 锁存 5xx 场景因果闭环、timeout/unknown 协调 | M1-07, M4-04 |
| M4-06 | P0 | `scale_deployment@1` | 容量场景、quota/HPA/partial ready/compensation 测试 | M1-07, M4-04 |
| M4-07 | P0 | Workflow action 协调 | 201/202/timeout/reconcile/restart 零重复副作用目标 | M2-04, M4-05, M4-06 |
| M4-08 | P0 | SLO VerificationResult | baseline/observed/缺失数据/cleanup actor 判定 | M1-08, M4-07 |
| M4-09 | P0 | 安全控制回归 | R0 合法接受、R1 合法/非法、R2/R3、Secrets/exec/namespace | M4-01..08 |

M4 退出条件：合法 R1 能完成因果恢复；所有危险路径确定性拒绝；动作成功不替代 SLO 恢复。

## 8. M5：Web Console

| ID | P | 工作项 | 输出/验收 | 依赖 |
| --- | --- | --- | --- | --- |
| M5-01 | P0 | 前端基础与类型客户端 | 路由、错误边界、OpenAPI 类型、权限 capabilities | M2-06 |
| M5-02 | P0 | 事故列表/详情/SLO | filter URL、stale/partial/offline、图表查询可追溯 | M2-07, M4-08 |
| M5-03 | P0 | Evidence/Hypothesis/预算 | 支持/反对证据、恶意文本安全渲染 | M3-06 |
| M5-04 | P0 | 审批队列与高风险确认 | 目标/参数/hash/过期完整；不可编辑；并发冲突 | M4-02 |
| M5-05 | P1 | 时间线回放和导出 | SSE gap 补拉、T0–T8 同步、脱敏包 hash | M2-07, M4-08 |
| M5-06 | P1 | 演练/评测/系统页面 | dirty gate、可比性、kill switch 只读/授权操作 | M1-07, M3-08, M4-09 |
| M5-07 | P0 | 响应式与无障碍验收 | 4 视口截图、键盘/焦点/AA、无重叠和误触 | M5-01..06 |

## 9. M6：评测与证据发布

| ID | P | 工作项 | 输出/验收 | 依赖 |
| --- | --- | --- | --- | --- |
| M6-01 | P0 | 评测 runner/report Schema | 原始 JSON -> Markdown，失败样本不删除 | M3-08, M4-09 |
| M6-02 | P0 | 固定 benchmark | 根因/时延/恢复/安全/成本/资源，版本和样本完整 | M6-01 |
| M6-03 | P0 | 脱敏事故包 | Schema、secret scan、hash、过期和可回放 | M5-05 |
| M6-04 | P1 | CI/release gates | replay、migration、安全、E2E、前端、SBOM/扫描 | M5-07, M6-02 |
| M6-05 | P1 | 冷启动复现 | 第二个干净环境按文档运行，记录阻碍和实际时长 | M6-04 |
| M6-06 | P0 | 简历证据核对 | 所有对外 claim 绑定报告/commit/样本/限制 | M6-02, M6-03, M6-05 |

## 10. 关键路径与并行边界

```text
M0 -> M1 -> M2 -> M3 -> M4 -> M5 -> M6
```

- M1 的 Web/Demo Shop 与 M0 的部分 spike 可在契约固定后并行。
- M2 API/DB/Workflow 可以分人实现，但 contracts 先行。
- M3 四类工具可并行，统一 Gateway/Evidence 契约先行。
- M5 可在 mock API 上开始，但不能自行发明状态或审批字段。
- R1 权限在 M3 安全基线和 M4 gates 通过前保持关闭。

## 11. Backlog 变更规则

- 新工作项必须说明用户/风险价值、依赖和验收证据。
- 拆分工作项保留原 ID 的父关联，不把未完成内容悄悄标 DONE。
- 发现架构选择错误先更新 ADR/契约和受影响 backlog，再实现。
- scope 增加 R2、生产接入、多租户或新重依赖必须重新做产品与威胁评审，不作为普通 P2 混入。
