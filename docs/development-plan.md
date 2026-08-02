# 开发路线与环境准备

## 1. 当前基线

仓库已从开发前文档基线进入 D1-light 原型建设阶段：已有 Python monorepo 包、React 控制台、演练微服务、场景 fixture、infra 草案和测试。以下路线图仍定义 full MVP 的完成顺序；已经存在的 light/prototype 代码需要继续收敛到契约、安全和证据门禁，不能因“文件存在”视为 M1–M6 完成。

当前未完成的关键基线：

- full Kubernetes 演练环境和本机资源基准。
- Temporal Server replay、Worker restart 与 Signal 等待验证。
- PostgreSQL migration、projection/outbox 和数据库绑定审批授权。
- OpenTelemetry/Prometheus/Loki/Tempo full profile E2E。
- 固定 benchmark、holdout 数据集和可发布证据包。

## 2. 关键假设

- 开发主机为 Windows + Docker Desktop，具备可用的 Linux 容器环境。
- 完整演示预计需要约 10–12 GB 可用内存，但该数字待 M0 实测。
- 单集群、namespace 隔离足以支持本地 MVP；生产接入不在范围内。
- 云模型与本地模型都通过 OpenAI-compatible 接口适配。
- Temporal 是唯一持久编排候选，首版不加入 LangGraph。
- PostgreSQL 保存领域读模型，Temporal 保存流程历史，两者职责不重叠。

假设被实测推翻时，先更新架构和计划，再调整代码。

## 3. 目标仓库结构

```text
sentinel-x/
├─ apps/
│  ├─ control-api/          # HTTP API、读模型、SSE
│  ├─ incident-worker/      # Temporal Workflow 与 Activities
│  ├─ action-gateway/       # 独立最小权限执行器
│  └─ web-console/          # 事故指挥与回放界面
├─ packages/
│  ├─ contracts/            # Pydantic/JSON Schema/事件契约
│  ├─ domain/               # 领域状态与不变量
│  ├─ diagnostics/          # PromQL/Loki/Tempo/K8s 只读适配
│  └─ policy/               # 风险分级与确定性策略
├─ demo/
│  ├─ services/             # order/inventory/payment
│  ├─ scenarios/            # 版本化故障 fixture
│  └─ load/                 # 稳定流量脚本
├─ infra/
│  ├─ cluster/              # k3d/kind 配置
│  ├─ kubernetes/           # namespace/RBAC/NetworkPolicy/manifests
│  └─ observability/        # OTel/Prometheus/Loki/Tempo/Grafana
├─ evals/                   # runner、baseline 与报告 Schema
├─ tests/                   # 契约、集成、安全与 E2E
├─ docs/
└─ Makefile 或等价任务入口
```

目录按真实代码增长创建，不预先放空包。共享包只有出现至少两个实际消费者后才提取。

## 4. 开发环境准备

### 4.1 拟议依赖

| 依赖 | 用途 | M0/M1 验证 |
| --- | --- | --- |
| Git | 版本与报告可追溯 | 版本可用 |
| Docker Desktop | Linux 容器运行时 | CPU/内存与磁盘基准 |
| k3d 或 kind | 本地 Kubernetes | 二选一稳定启动/销毁三次 |
| kubectl | 仅供开发者管理环境 | 应用容器内不存在 |
| Python | API、Worker、评测 | 版本由首个锁文件固定 |
| Node.js | Web Console | 版本由首个锁文件固定 |
| Temporal CLI/容器 | 工作流开发 | 重放和 Worker 重启实验 |

具体版本不要在锁文件和兼容性验证前猜定。优先采用官方 SDK 和镜像，镜像发布后固定 digest。

### 4.2 配置与环境

仓库已提供不含秘密的 `.env.example`；变量的完整语义、默认和边界统一由 [配置字典](configuration-reference.md) 维护。以下仅保留组件依赖摘要：

| 名称 | 使用者 | 是否敏感 | 说明 |
| --- | --- | --- | --- |
| `DATABASE_URL` | API/Worker | 是 | 本地领域数据库连接 |
| `TEMPORAL_ADDRESS` | API/Worker | 否 | Temporal endpoint |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 各服务 | 否 | Collector endpoint |
| `LLM_BASE_URL` | Investigator | 视部署而定 | OpenAI-compatible endpoint |
| `LLM_API_KEY` | Investigator | 是 | 只注入模型 Activity |
| `LLM_MODEL` | Investigator/Evaluator | 否 | 固定模型标识 |
| `ACTION_GATEWAY_URL` | Worker | 否 | 内部 endpoint |
| `ACTION_GATEWAY_AUDIENCE` | Worker/Gateway | 否 | projected ServiceAccount token 的固定 audience |
| `SENTINEL_PROFILE` | 启动脚本 | 否 | `light` 或 `full` |

Worker 服务身份与审批授权分离：Gateway 验证短时 ServiceAccount token，并从数据库独立读取/消费审批。真实值不得进入仓库、演示截图、日志或报告。

### 4.3 目标任务入口

实现后应提供少量稳定入口，而不是要求使用者记住长命令：

```text
make doctor       检查本机依赖和资源
make demo-up      启动完整演练环境
make demo-down    清理演练环境
make test         运行快速质量门禁
make test-e2e     运行隔离 E2E
make eval         运行固定评测并产出报告
```

这些命令当前不存在。完整 profile、端口、启停、清理和 Windows 约束见 [本地开发与部署](local-development-and-deployment.md)；日常故障处理见 [运维手册](operations-runbook.md)。若 Windows 兼容性需要，可提供等价 PowerShell wrapper，但必须调用同一底层任务定义。

## 5. 分阶段路线

### M0：决策与本机基准

**目标**：把不可逆选型从“拟议”变为有证据的决定。

交付：

- 对 k3d/kind 做启动、销毁、网络和资源占用基准，确定默认与轻量 profile。
- 用 Temporal 最小 Workflow 验证重放、Activity 重试和人工 Signal 等待。
- 用候选模型验证结构化输出成功率与成本，不包含集群写操作。
- 记录首批 ADR：仓库形态、编排、集群、遥测和执行隔离。

验收：基准命令、环境信息和原始结果可重复；选型文档列出被拒绝方案与代价。

### M1：可观测、可注入的演练业务

**目标**：先有稳定故障和 ground truth，再构建 AI。

交付：

- order/inventory/payment、PostgreSQL、Redis 和稳定负载。
- OTel 上下文贯穿三服务；Prometheus、Loki、Tempo 能按同一关联 ID 查询。
- 6 个场景均有 Schema、注入、清理、证据预期和恢复断言。
- Alertmanager 产生稳定、可去重的告警。

验收：每个场景连续注入/清理至少 3 次无残留；告警、日志、指标和 Trace 与 ground truth 对齐。

### M2：事故控制面与持久工作流

**目标**：建立不依赖 LLM 的确定性事故骨架。

交付：

- Incident 状态机、领域表、时间线和告警去重。
- Temporal Workflow、Activity 边界、超时与重试策略。
- Control API、SSE 和基础读模型。
- Worker 重启恢复、非法状态转换和 outbox 测试。

验收：用 fixture 驱动完整状态流；在三个等待点重启 Worker，事故不丢失且无重复副作用。

### M3：只读调查器

**目标**：让模型在严格预算内生成有出处的根因假设。

交付：

- PromQL、Loki、Tempo、K8s 四类只读类型化工具。
- Evidence/Hypothesis 契约、支持与反对证据引用。
- 模型 provider、结构化输出重试、调查预算和人工升级。
- 遥测脱敏与提示注入攻击集。
- B0/B1 与首个 C1 评测报告。

验收：工具无写权限；解析失败、预算耗尽和恶意遥测不会产生动作；报告可复现且披露失败样本。

### M4：审批与受控恢复

**目标**：用独立安全边界完成两种 R1 动作。

交付：

- 版本化 Runbook：Deployment 重启、限定范围扩容。
- ApprovalRequest/Decision 和可验证审批凭证。
- 独立 Action Gateway、最小 RBAC、策略、before/after 与幂等。
- SLO 恢复窗口、kill switch 和完整安全回归。

验收：审批绕过、篡改、过期、重放、目标漂移、R2/R3 和跨 namespace 全部被拒绝；合法重试不重复执行。

### M5：指挥台与事故回放

**目标**：让事故链路可扫描、可审批、可复盘。

交付：

- 服务拓扑与当前影响、状态清晰的事故列表。
- 实时时间线、Evidence/Hypothesis 对照和调查预算。
- 展示规范参数与影响的审批界面。
- 修复前后 SLO、事故回放和报告入口。
- 键盘导航、窄屏和失败/空/加载状态。

验收：按 [演示手册](demo-runbook.md) 完成桌面和移动视口检查；文本不重叠，审批不能误触或只显示模糊摘要。

### M6：固定 benchmark 与交付证据

**目标**：形成可写进简历、能被复查的证据，而不是只录一段视频。

交付：

- 6 个故障、攻击变体和固定运行协议。
- JSON 原始报告、Markdown 摘要、baseline 比较与失败分析。
- 干净环境启动文档、演示录屏和脱敏事故包。
- CI 质量门禁、依赖/镜像扫描和最终文档同步。

验收：另一台满足前提的环境可重复演练；对外数字能定位到报告、commit、环境和样本数。

## 6. 依赖关系

```text
M0 -> M1 -> M2 -> M3 -> M4 -> M5 -> M6
```

- M1 的可重复场景是所有 AI 评测的前提。
- M2 的状态机和重放测试是接入模型与写操作的前提。
- M3 的只读安全基线通过后才允许 M4。
- M4 的安全回归通过后才在 UI 暴露审批。
- UI 可与部分后端工作并行，但不能发明与契约不一致的状态。

## 7. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 完整观测栈内存过高 | Windows 开发体验差 | M0 实测；轻量 profile 使用 fixture，但单独标记 |
| Chaos Mesh 本地不稳定 | 场景不可复现 | MVP 使用应用开关、Toxiproxy 和受控 K8s 操作 |
| 模型输出波动/限流 | 评测不稳定 | 固定配置、Schema、有限重试、重复运行和失败归类 |
| 数据库锁清理失败 | 污染后续场景 | 独立超时、幂等 cleanup、环境 dirty gate |
| ground truth 粒度模糊 | Top-1 无法判定 | 固定 category + target，分离主要根因与促成因素 |
| Temporal/领域库双状态 | 状态漂移 | Workflow 唯一驱动，领域库只做投影和审计 |
| 安全范围悄然扩大 | 演示变成高风险自动化 | R2 禁用、R3 永拒；任何扩大先更新威胁模型 |
| 项目过重导致无法完成 | 简历项目停留在基础设施 | 每个里程碑可独立演示，严格限制依赖和服务数量 |

## 8. 每个里程碑的完成定义

- 正常、边界和失败路径都有自动化或可重复验证。
- 文档和实现一致，未实现项仍明确标注。
- 没有真实秘密、生产数据或生产连接。
- 验证产物包含命令、环境、期望和实际结果。
- 新增依赖有实际消费者和选择依据。
- 本阶段引入的告警、日志与错误能支持排障。
- 影响安全、契约或评测口径的变更完成对应文档同步。

## 9. 近期行动清单

1. 执行 M0 的 k3d/kind 与 Temporal spike，不创建完整业务代码。
2. 根据实测结果建立首批 ADR 和锁定语言/运行时版本。
3. 先实现 Scenario Schema 与最小 `payment-api` 崩溃场景。
4. 验证注入、可观测证据和清理闭环后，再扩展其余业务服务。

这样可以最早暴露本地资源、网络、遥测和工作流风险，避免先完成 UI 后才发现演练底座不可复现。
