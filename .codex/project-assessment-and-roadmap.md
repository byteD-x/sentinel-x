# Sentinel-X 项目开发度、缺陷与下一步开发方案

## 1. 结论先行

Sentinel-X 当前不是“完成的 AI 运维产品”，而是一个 **D1-light 本地原型**：已经具备可运行的事故指挥台、固定故障目录、状态机、审批界面、Action Gateway 门控、SSE 时间线和本地评测归档，但尚未完成 full MVP 所需的真实持久工作流、数据库投影、观测栈、Kubernetes 动作和固定 benchmark。

综合判断：

| 维度 | 当前判断 | 说明 |
| --- | --- | --- |
| 产品/架构设计 | 较成熟 | 产品需求、状态机、安全边界、Runbook、评测口径和发布门禁文档较完整 |
| Light 原型可演示度 | 中高 | 本地 API、Web Console、Terminal Console 和六个场景 fixture 可运行 |
| Full MVP 完成度 | 低到中 | 关键链路仍是 fixture/proposed，不能按生产或完整 E2E 宣称 |
| 生产可用度 | 不具备 | 无正式身份认证、无 PostgreSQL 权威投影、无 Temporal replay 证据、无真实执行器闭环 |
| 面试展示价值 | 高 | 能展示 Agent 边界、状态机、审批、幂等、失败升级和证据账本；必须主动披露限制 |

这里的“完成度”是基于代码、文档和本地命令的工程判断，不是正式 KPI。若按产品 MVP 的 11 项功能需求粗略折算，当前大约处于 **35%–45% 的可验收完成度**：大部分有设计和 fixture，真正达到 full E2E 验收的部分仍很少。

## 2. 证据与验证基线

### 本轮已落地

- 修复 `pytest -q` 的仓库根路径问题，并将 `make test-e2e` 统一为 `python -m pytest`。
- 新增 `.github/workflows/quality.yml`，覆盖 Python 测试/轻量 Ruff、Web Console、Terminal Console。
- Alert Ingress 增加时间戳 + nonce + HMAC，有界 replay cache 和重复 nonce 拒绝。
- Control API 创建审批时重新执行 MVP policy、风险等级和 canonical plan hash 校验。
- 场景启动统一进入 `LocalExerciseWorkflow`；审批决定只记录用户意图，执行/验证由编排器推进；API 启动时恢复未完成 checkpoint。
- 对本地快照中的 orphan checkpoint 做安全清理，避免旧测试状态阻塞启动。

### 已验证

- Python 测试：`python -m pytest -q`，本次运行 **167 passed**。
- Web Console：`npm run test -- --run` 为 **24 passed**，`npm run build`、`npm run lint` 通过。
- Terminal Console：`npm test` 为 **7 passed**，`npm run build` 通过。
- Web UI 合约脚本：`node scripts/ui-contract.test.mjs` 通过。
- Action Gateway、状态机、Alert Ingress HMAC、角色门控、审批过期/篡改/幂等和本地 SQLite 快照均有测试覆盖。

### 未验证或当前明确不具备

- Python Ruff 轻量门禁 `python -m ruff check packages/ apps/ demo/ --select E4,E7,E9` 通过；完整 Ruff 仍有 236 个既存风格/类型/时区提示，不能把完整 lint 记为通过。
- 当前 `python -m pytest -q` 可在本地环境完成 **167 passed**；干净环境安装与完整依赖锁定仍需单独记录，不能据此宣称 full profile 门禁通过。
- Temporal Server replay、Worker 真正注册、Signal/Activity 重启恢复未完成。
- PostgreSQL migration、projection/outbox、DB 绑定审批和跨进程原子消费未完成。
- Prometheus/Loki/Tempo/OTel full profile 查询未完成；诊断与动作仍存在模拟路径。
- Action Gateway 当前为 fixture 执行，不写真实 Kubernetes；恢复验证已改为受控观测样本输入，但仍未连接真实观测源。
- 正式 `/api/v1`、会话认证、CSRF、ETag、正式幂等契约尚未收敛。
- 六场景固定 benchmark、holdout 数据集、第二个干净环境 cold run 和可发布证据包未完成。
- 仓库已有 `.github/workflows/quality.yml`，但尚未有远端 CI run 证据；产品事件埋点/漏斗数据实现仍未完成。

### 关键证据索引

- 当前定位与限制： [README.md](../README.md:7)、[README.md](../README.md:162)。
- 发布状态与阻塞： [docs/release-readiness.md](../docs/release-readiness.md:8)、[docs/release-readiness.md](../docs/release-readiness.md:45)。
- Claim 等级与证据缺口： [docs/evidence-ledger.md](../docs/evidence-ledger.md:20)、[docs/evidence-ledger.md](../docs/evidence-ledger.md:28)。
- 真实 Worker 尚未注册： [apps/incident-worker/src/sentinel_x_incident_worker/worker.py](../apps/incident-worker/src/sentinel_x_incident_worker/worker.py:39)。
- 动作仍为 fixture： [apps/action-gateway/src/sentinel_x_action_gateway/app.py](../apps/action-gateway/src/sentinel_x_action_gateway/app.py:362)。
- 验证路径已要求显式观测样本并覆盖空窗口/样本不足/超阈值失败： [apps/incident-worker/src/sentinel_x_incident_worker/activities.py](../apps/incident-worker/src/sentinel_x_incident_worker/activities.py:254)；真实观测源仍未接入。
- 本地内存状态 + SQLite 快照： [apps/control-api/src/sentinel_x_control_api/app.py](../apps/control-api/src/sentinel_x_control_api/app.py:240)。
- 目标路线和验收项： [docs/engineering-backlog.md](../docs/engineering-backlog.md:50)。

## 3. 角色一：项目经理视角

### 当前开发程度

项目已经完成“概念证明 + 可演示原型”阶段，尚未达到“可验收 MVP”。优势是范围控制得比较好：明确 local-only、R0–R3、人工审批、六个固定场景和不能宣称的指标；问题是文档路线已经很完整，实际 full profile 仍停留在关键路径早期。当前发布级别应保持 **D1 Developer Preview / PARTIAL**，D2 Demo MVP 和 D3 Evidence Release 不能提前承诺。

### 项目管理缺陷

| 优先级 | 缺陷 | 项目影响 | 处理原则 |
| --- | --- | --- | --- |
| P0 | light、full、fixture、真实能力的验收边界分散在多份文档 | 容易出现“代码存在=功能完成”的误判 | 建立单一 Release Readiness 看板，每项只允许 `DESIGNED/IMPLEMENTED/TESTED/MEASURED` 一种状态 |
| P0 | Temporal、PostgreSQL、Kubernetes、观测栈都在关键路径上，但缺少可独立验收的垂直切片 | 开发周期长，晚期才发现架构不可行 | 先做一条“单场景、单 R1、单报告”的 full thin slice，再扩展六场景 |
| P0 | Alert Ingress 只有时间窗 HMAC，没有 nonce/replay cache；审批入口也未在 Control API 端重新计算 policy/plan hash | 重放告警、错误 R1 或伪造审批可能进入本地流程 | 先补 ingress 幂等/重放拒绝，再做服务器端审批绑定和原子消费 |
| P1 | 没有 CI 自动门禁 | 本地通过无法转化为团队持续质量 | 先接入 Python test、Web test/build/lint、Terminal test/build，后接安全和 E2E |
| P1 | 没有实时交付指标 | 无法判断是否在收敛 | 每周只跟踪 5 个指标：D2 门禁关闭数、阻断缺陷数、full E2E 通过数、脏环境次数、证据包完整率 |
| P1 | 尚无版本化演示/benchmark 产物 | 面试或评审结果不可复查 | 固定 commit、scenario、policy、prompt、model、dataset、profile 和报告 hash |
| P1 | Control API、领域状态机和场景启动各自推进状态；LocalExerciseWorkflow 的 `resume_all` 未接入 API lifespan | 进程重启恢复与状态合法性无法作为统一承诺 | 只保留一个编排入口，所有状态转换调用共享状态机，启动时显式恢复未完成 checkpoint |

### 项目经理验收口径

每个里程碑必须同时给出：完成代码、正常路径、失败路径、验证命令、原始报告、未完成项。不能用“服务启动”“页面可见”“测试 skipped”替代闭环验收。

## 4. 角色二：实际用户视角

这里的用户分为值班工程师、事故指挥者、审批者和平台安全工程师。当前用户只能把系统当作隔离演练和学习工具，不能当作生产事故处置工具。

### 当前可用价值

- 值班工程师可以在一个控制台看到事故、场景、证据摘要、假设、审批和时间线。
- 审批者可以看到 Runbook、目标、参数、风险等级、过期时间和 plan hash，并进行批准/拒绝。
- 平台/安全工程师可以演示 fail-closed、R2/R3 拒绝、目标白名单、HMAC 审批凭证和进程内幂等。
- 面试或培训用户可以复现六个版本化故障分支，并观察自动恢复、待审批和升级人工的不同结果。

### 用户缺陷与风险

| 优先级 | 用户问题 | 后果 | 下一步 |
| --- | --- | --- | --- |
| P0 | 页面展示的证据、恢复和执行结果部分来自 fixture/模拟数据 | 用户可能把演示结果误认为真实观测结论 | 所有页面统一显示 `fixture/live/replay`、profile 和数据新鲜度；真实数据未接入时禁用“已恢复”强语义 |
| P0 | 角色由 `X-Sentinel-Role` 本地 header 门控 | 任何能调用本地 API 的人都可能伪造角色 | light 保持 local-only 明示；full 实现服务端会话/OIDC、CSRF、职责分离和审计身份 |
| P0 | Action Gateway 不连接真实目标，SLO 验证仅接受受控样本 | 用户无法证明动作真的改变业务状态 | 先接 fake K8s API 做真实状态变更和失败注入，再接隔离 kind/k3d；验证必须读取真实 observed window |
| P0 | Gateway 只检查请求体带来的 approval_id/expiry/hash，未从独立数据库读取不可变批准记录，也未校验 namespace、UID/generation | 持有共享凭证的调用者可能伪造批准或面对目标漂移执行 | Gateway 使用独立 DB 角色、TokenReview/mTLS、目标身份绑定和一次性原子消费 |
| P1 | 事故回放目前主要是内存/SQLite 快照，导出包和持久 SSE 仍未完成 | 刷新、重启、复盘和跨人协作可信度不足 | PostgreSQL timeline/outbox + SSE gap/reconnect + 脱敏事故包 hash |
| P1 | 真实审批完成后，Control API 当前可直接写入 action/recovery 事件并标记 RESOLVED | UI 看到的“执行成功”不等于 Gateway 或业务真实成功 | 终态只能由执行结果协调和真实 SLO VerificationResult 推进，动作成功与恢复成功分离 |
| P1 | 缺少用户级过滤、搜索、证据新鲜度和“为什么升级人工”的统一解释 | 故障多时认知负担高 | 先补状态/严重度/服务/时间过滤、稳定拒绝码和统一升级原因，不扩展无关图表 |
| P2 | 无产品行为埋点 | 无法知道用户是否完成查看、审批、回放和演练 | 只采集合成环境事件：scenario_started、incident_opened、evidence_viewed、approval_decided、replay_completed |

### 用户验收标准

用户完成一次演练时必须能回答：发生了什么、证据来自哪里、系统为何给出该假设、动作是否被批准、动作是否真正生效、SLO 是否在稳定窗口恢复、若失败应由谁接手。任一答案只能来自 fixture 时，界面必须明确标注。

## 5. 角色三：技术面试官视角

### 当前可展示的技术亮点

1. **边界意识**：模型不持有执行器写权限，Action Gateway 独立 fail-closed，R2/R3 禁止，遥测被视为不可信输入。
2. **状态建模**：共享 contracts/domain 状态机覆盖正常、升级、失败和自动恢复分支，避免各模块自造状态。
3. **安全动作设计**：Runbook allowlist、目标/参数/schema、plan hash、过期、audience、HMAC 和幂等检查有对应测试。
4. **可恢复思路**：已有本地 SQLite checkpoint 和不重复动作测试，且明确它不能替代 Temporal/PostgreSQL。
5. **证据纪律**：evidence ledger 区分 Designed、Implemented、Tested、Measured、Published，避免把 demo 指标写成生产结论。
6. **前端工程**：React/Vite 页面、SSE 断线重连、序号去重、REST 补读、审批焦点处理和组件测试较完整。

### 面试官会追问的短板

| 追问 | 当前真实答案 | 补强方式 |
| --- | --- | --- |
| Temporal 是否真的 durable？ | 否，当前是可测试 Python fixture；full profile 会拒绝启动 | 实现真实 Workflow/Activity/Signal，并提交 replay、三点重启和 history 证据 |
| Action 是否真的改了 Kubernetes？ | 否，`execution_mode=fixture`，只模拟 before/after | fake K8s API 验证状态变化，再做隔离集群 E2E；加入 timeout/reconcile |
| 如何保证审批不能被篡改或重放？ | light 进程内有 hash/HMAC/幂等；数据库绑定、跨进程原子消费尚未完成 | PostgreSQL 不可变 ApprovalDecision、唯一约束、目标 UID/generation、TokenReview 和并发测试 |
| 根因准确率是多少？ | 没有可对外发布的 Top-1；当前 fixture evaluator 不是 benchmark | 先跑 B0/B1 基线，再跑 C1 holdout，披露样本数、失败分类和区间 |
| 为什么不用 LangGraph/Kafka？ | 当前设计刻意避免双编排和无必要基础设施 | 说明 Temporal/PostgreSQL 的职责边界和 ADR，展示被拒绝方案及成本 |
| 测试是否足够？ | light 单元/接口测试较好，full 集成和安全发布门禁不足 | 增加 CI、契约测试、fake K8s、migration、replay、E2E 和攻击集报告 |

### 面试展示建议

用 10 分钟只展示一条主线：`inventory-latched-5xx@1 -> 证据 -> R1 restart 计划 -> 审批 -> Gateway 二次校验 -> SLO 验证 -> 回放`；然后展示一个恶意日志/篡改审批被拒绝的失败样本。不要展示尚未完成的 full profile，不要报准确率、MTTR 或“生产级”结论。

## 6. P0/P1/P2 开发计划

### P0：先关闭“不能可信交付”的阻断项

#### P0-1：固定 D1 基线与自动门禁（首版已完成）

- 新增 CI：Python test、Python 轻量 lint、Web test/build/lint、Terminal test/build。
- 安装并锁定 `ruff`，在 CI 和本地 `make lint` 中给出明确失败码。
- 已修复 `pytest -q` 与 `python -m pytest` 入口不一致；当前通过 pytest 配置显式加入仓库根路径。后续仍应将 `demo.scenarios` 整理为正式可安装包，减少路径耦合。
- 建立 `docs/release-readiness.md` 的 machine-readable checklist；每项绑定命令和报告路径。
- 交付物：CI run、测试汇总、依赖版本、当前已知限制清单。

验证：干净环境执行 `make test`、`make lint`；所有失败不得以 skipped 计通过。完整 Ruff 规则清零后，才升级为完整 Python lint 门禁。

#### P0-2：完成 Temporal + PostgreSQL 最小 durable slice（2–3 周）

- 先只实现 `inventory-latched-5xx@1`，不扩展场景。
- Temporal 注册真实 Workflow、Activity、Signal/审批等待和 retry；去掉 full profile 空实现。
- PostgreSQL 完成 Incident、Timeline、Approval、ActionExecution、VerificationResult 的 migration。
- 将 Alert Ingress 的 fingerprint/nonce 去重、ApprovalDecision 一次决定和 ActionExecution 幂等键放入数据库唯一约束/事务；不要让 API 继续复制一套独立状态转换表。
- 用 outbox/唯一约束保证 command、审批决定、动作登记和投影可重试；加入 Workflow/DB 对账。
- API 先收敛 `/api/v1`，同时保留兼容层的明确弃用策略。

验证：Temporal history replay；调查、等待审批、执行返回后三个重启点；重复告警只产生一个 Incident；审批并发只产生一个决定；数据库恢复后 UI 可重建时间线。

#### P0-3：建立真实但安全的执行验证链（2 周）

- Action Gateway 先接 fake K8s API，模拟 Deployment UID/generation、patch、timeout、partial ready 和状态未知。
- 审批绑定数据库记录、目标身份、参数 hash、policy/runbook version、expiry 和一次性消费。
- Gateway 重新读取批准记录并校验 namespace/kind/name/UID/generation；Control API 的审批创建端也必须服务器端重算 policy 与 canonical plan hash。
- 保持 kill switch 默认开启；在所有负向测试通过前不开放 full R1。

验证：合法 restart/scale 各至少一条成功路径；过期、撤销、重放、目标漂移、参数改写、跨 namespace、Secrets、exec 和 R2/R3 全部拒绝；超时协调后 effect count 为 1。

### P1：补齐可用的 full Demo MVP

#### P1-1：真实演练底座（3–4 周）

- 在 kind/k3d 中完成 order/inventory/payment、PostgreSQL、Redis、OTel Collector、Prometheus、Loki、Tempo 的可重复启动/清理。
- 实现六个场景真实注入、ground truth 隔离、cleanup 幂等和 dirty gate。
- 四类诊断工具接真实来源，保留模板 allowlist、范围、limit、超时、脱敏和审计。

验证：六场景连续注入/清理至少 3 次；每次环境 CLEAN；跨指标/日志/Trace/K8s 引用可追溯；任何观测源缺失都升级，不伪造证据。

#### P1-2：用户体验与回放（1–2 周）

- 实现正式 session/capability、审批冲突处理、ETag/If-Match、SSE 持久 gap 补拉。
- 事故详情显示 `T0–T8`、source freshness、证据缺失和稳定升级原因。
- 完成四视口、键盘、焦点、对比度、错误/离线/脏环境验收。

验证：浏览器刷新、断线重连、并发审批和后端重启后仍能重建同一时间线；无障碍和响应式报告归档。

#### P1-3：固定评测基线（2 周，可与 P1-1 后半并行）

- 实现 B0（告警标签）、B1（规则）和 C1（Sentinel-X 调查器）统一 runner。
- 分离 development/calibration/holdout；保留失败样本、基础设施失败、模型失败和升级结果。
- 记录 dataset/model/prompt/policy/SLO/profile/commit、Token、时延、安全拦截和恢复 actor。

验证：每场景至少 10 次的正式规划（成本试跑后冻结）；输出原始 JSON、Markdown、hash 和失败分类。样本不足时只报计数，不报误导性 p95/置信区间。

### P2：规模化和企业化准备

- OIDC/SSO、RBAC、职责分离、审计保留和密钥轮换。
- 多环境 CI/CD、镜像 digest、SBOM、依赖/镜像扫描、备份恢复和升级回滚。
- Jira/PagerDuty/Slack/Grafana 等只读或受限集成；不扩大到任意生产写入。
- 产品埋点和演练漏斗：启动率、完成率、审批耗时、正确升级率、回放完成率、失败原因分布。
- 只有 D3 Evidence Release 后，才生成带样本、环境和限制的面试/作品集量化结论。

## 7. 30/60/90 天路线图

### 0–30 天：可控交付

- 关闭 P0-1：CI、ruff、统一 test/lint/build、敏感信息扫描。
- 完成 Temporal/PostgreSQL spike 和 ADR 结论，不再维护两套“可能的权威流程”。
- 交付单场景 durable thin slice，R1 仍默认关闭。
- 产出第一版 evidence manifest 和 D1 基线报告。

### 31–60 天：完整 Demo MVP

- 完成 fake K8s 执行器、审批数据库绑定、重放/对账/超时协调。
- kind/k3d full profile 跑通至少三个场景，再扩展到六场景。
- 接入真实只读观测源和最小 OTel 关联；完成 UI 回放、SSE、响应式和无障碍门禁。
- 目标发布层级：D2 预发布；任何安全门禁失败都 No-Go。

### 61–90 天：证据发布与面试版本

- 六场景固定 benchmark、B0/B1/C1 对照、攻击集和恢复报告。
- 第二个干净环境 cold run，记录实际资源、时长、失败和补偿。
- 生成脱敏事故包、checksums、README/简历 claim 对账。
- 目标发布层级：D3 Evidence Release；若未达到，明确交付 D2 限制，不包装成生产能力。

## 8. 最终 Definition of Done

项目可以称为“full Demo MVP”前，必须全部满足：

1. 六个场景可从干净环境注入、观测、清理并重复运行。
2. 至少一个自动/无动作场景和一个合法 R1 场景完成真实验证；至少一个高风险场景正确升级且无动作。
3. Temporal replay、Worker 重启、PostgreSQL migration/projection/outbox 和对账通过。
4. 审批缺失、过期、撤销、重放、篡改、并发、目标漂移和 kill switch 有负向测试。
5. Action 成功不直接等于恢复；必须以真实 SLO observed window 判定。
6. 事故时间线、Evidence、Hypothesis、Approval、Action、Verification 和评测报告可导出并校验 hash。
7. CI、四视口 UI、无障碍、敏感信息扫描和依赖/镜像门禁通过。
8. README、简历和演示材料只使用证据账本允许的 claim。

## 9. 近期不建议做的事情

- 暂不引入 Kafka、向量库、LangGraph、服务网格、eBPF、图数据库或多租户。
- 暂不扩展 R2 数据库修复、R3 任意命令、生产集群接入和“自动化率”营销指标。
- 暂不为 UI 增加大量图表，先补真实数据来源、时间线可信度和失败状态。
- 暂不把 local SQLite 继续演化成第二套生产存储；它只保留为 light profile 的演示/测试实现。

## 10. 给三类对象的一句话结论

- **项目经理**：项目已过概念验证，下一目标不是继续堆页面，而是用一条 full thin slice 关闭 D2 的关键门禁。
- **实际用户**：现在适合隔离演练、培训和架构评审，不适合生产事故处置；任何 fixture 结果都应在界面上明确标注。
- **技术面试官**：项目最有价值的是安全边界、状态机、审批和证据纪律；最需要补强的是 Temporal/PostgreSQL/真实观测执行闭环和可复查 benchmark。
