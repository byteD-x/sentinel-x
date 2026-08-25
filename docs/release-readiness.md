# 发布、演示与证据就绪门禁

## 1. 发布层级

| 层级 | 含义 | 当前状态 |
| --- | --- | --- |
| D0 Documentation Baseline | 完整设计与开发准备 | SUPERSEDED：已进入 light prototype 代码阶段 |
| D1 Developer Preview | light 可运行，核心 contracts/Workflow fixture | READY（local-only）：统一本地 MVP 门禁已通过（Python/Web/Terminal、六场景 cleanup、攻击集、fixture 评测），并有 SQLite projection durable slice；PostgreSQL、OIDC 和真实观测仍不在此层级 |
| D2 Demo MVP | full 六场景、两 R1、UI、固定 E2E | NOT_READY |
| D3 Evidence Release | holdout benchmark、脱敏事故包、冷启动复现 | NOT_READY |

层级不是语义版本号。项目初始化 Git、选择许可证和发布渠道后再确定版本策略。

## 2. 通用 Go/No-Go

任何以下情况直接 No-Go：

- 真实秘密、生产数据或生产连接存在。
- R2/R3 可达、审批可绕过、权限越 namespace。
- 重复副作用、Action 最终状态未知未协调。
- Workflow replay/数据库 migration 不兼容。
- 环境 DIRTY、cleanup 失败或 ground truth 泄漏。
- 安全门槛失败或失败测试被跳过。
- 报告缺 commit/digest/profile/dataset/model/policy/SLO 版本。
- 对外 claim 高于 [证据账本](evidence-ledger.md) 等级。

## 3. D0 文档门禁

- README、文档地图、AGENTS、CONTRIBUTING、SECURITY 可导航。
- 产品、架构、术语、场景、Runbook、SLO、API、数据、Workflow、LLM/工具、UX、安全、测试、开发部署、运维、Backlog、风险、追踪和 ADR 职责清晰。
- 所有 Markdown 严格 UTF-8、单 H1、围栏平衡、内部链接有效、无冲突标记和明显秘密。
- 技术选择为 `proposed`，指标为目标/待测；没有虚构命令、测试或性能。
- 统一状态机、R0–R3、场景名称和 cleanup/remediation 语义。
- `.env.example` 敏感值为空，忽略/编码属性合理。

## 4. D1 Developer Preview 门禁

- Git、许可证、运行时版本和锁文件已确定。
- 真实 `doctor/bootstrap/test` 命令和干净安装记录。
- OpenAPI/Schema/TS 类型生成一致。
- migration、状态机、Workflow replay/restart、projection/outbox 测试通过。
- light profile 明确禁用真实故障和 R1。
- 最小 UI/接口显示当前 profile 和未实现能力，不伪装 full。

当前阻塞：

- Control API 已提供 `/api/v1`、local-only 短期 HMAC session、ETag/If-Match；light 仍使用 SQLite outbox，full profile 已接入 PostgreSQL Incident/Timeline/Approval 写入、权威时间线读取、审批一次性决定与启动读模型重建，仍缺 OIDC/CSRF、Action 跨服务授权事务。
- Action Gateway 已默认 fail-closed，并校验 HMAC 审批凭证、audience、管理员令牌、独立审批记录、目标身份和一次性消费；light SQLite backend 与 full PostgreSQL 权威审批读取/条件消费均已覆盖重启和单赢家验证，仍缺 TokenReview、服务身份和 ActionExecution 跨服务事务。
- Alert Ingress 已校验时间戳、nonce、HMAC 和有界 body，并提供版本化 Alertmanager webhook 转换；仍未完成 PostgreSQL 去重事务和真实 Alertmanager/观测栈联调。
- Control API 的 `X-Sentinel-Role` 只提供 local-demo 角色门控，不是浏览器会话、OIDC 或服务身份认证。
- light Workflow fixture 的动作执行仍是模拟路径，但恢复结论已改为读取受控观测样本；另有单场景 `SentinelIncidentWorkflow` 已注册真实 Temporal Worker，并通过 SDK 测试服务器执行、Signal、Worker restart 和 history replay。
- full 多场景 Temporal replay、PostgreSQL 观测/Verification 投影和 full observability E2E 未完成；PostgreSQL schema migration、domain repository、Incident/Timeline/Approval/ActionExecution 持久化、outbox dispatcher、Control API lifespan 后台发布、Action Gateway PostgreSQL 审批消费、Temporal reconciliation Activity 及跨连接时间线读取已在本机 PostgreSQL 15 临时数据库验证，业务投影 checkpoint 全链路写入、真实 crash/restart 对账和跨进程 SSE 发布仍未完成。Control API、Action Gateway、Diagnostic Gateway 和 Incident Worker 现在会在缺少真实适配器时 fail-closed，禁止静默回退到本地 SQLite 或 fixture 成功。
- GitHub Actions 已配置独立 PostgreSQL 16 migration integration job，但尚无远端成功 run 证据；本地 PostgreSQL 15 集成通过不替代远端 CI 证据。
- 最近远端 run `32843853898` 因 GitHub 账户 billing lock 未启动，CI 门禁保持未验证。
- 默认质量门禁需持续覆盖全部真实测试目录，并保留原始输出。

## 5. D2 Demo MVP 门禁

当前状态：NOT_READY。已完成隔离执行器接入和固定评测 CLI，但真实 kind/k3d、观测查询、六场景注入/cleanup 与 full E2E 仍未通过。

### 环境与功能

- full profile 冷启动成功，版本/digest/资源记录完整。
- 六场景连续注入/cleanup，环境 CLEAN。
- Pod 自动恢复、capacity scale、latched 5xx restart 三条路径因果可区分。
- Redis/DB lock/bad deployment 正确升级且无越权动作。
- Worker 在规定点重启，SSE 重连和事故回放完整。

### 安全

- 服务身份、审批绑定、过期/撤销/篡改/重放/并发全部通过。
- R2/R3、Secrets、exec、跨 namespace、任意查询/URL 全部拒绝。
- 固定攻击集门槛通过，同时报告合法 R1 接受和误拒。
- secret scan、RBAC/NetworkPolicy 和导出脱敏通过。

### UI 与演示

- 4 视口无重叠；键盘、焦点、对比度和可访问名称通过。
- 审批显示完整目标/参数/risk/hash/expiry，不能编辑计划。
- archived fallback 包 hash/版本验证，明确 live 与 replay。
- 10 分钟演示预演成功，cleanup 单独显示。

## 6. D3 Evidence Release 门禁

- dev/calibration/holdout 隔离和污染检查通过。
- B0/B1/C1、消融、失败分类、样本数和不确定性完整。
- 根因、时延、恢复、安全、合法接受、成本、资源全部有机器可读原始报告。
- 第二个干净环境完成 cold run；实际时长、问题和补偿记录。
- evidence manifest、checksums、secret scan 和保留/过期策略通过。
- 所有公开 claims 与证据账本一致，限制没有被营销措辞删除。

## 7. 发布产物

按层级选择：

- 源码与锁文件、migration、OpenAPI/Schema。
- 镜像 digest 与 SBOM/扫描摘要。
- 部署配置、非秘密 profile metadata。
- 测试/评测 JSON 和 Markdown 摘要。
- 脱敏事故包、截图/录屏与 checksums。
- ADR、风险、已知限制、升级/回滚说明。

不发布 raw `.env`、token、Cookie、kubeconfig、数据库 dump、原始敏感遥测或可消费审批。

## 8. 版本与变更

- API/事件/Scenario/Runbook/policy/prompt/SLO/dataset 分别版本化。
- 破坏性 API/事件变化提升主版本或路径。
- Scenario/Runbook 发布后不可原地改写。
- 报告可比性要求所有相关版本一致；不一致时明确不可比较。
- CHANGELOG 只记录已发生、可验证的变化；不把 roadmap 当 release note。

## 9. 回滚准备

- 应用回滚前 Workflow replay 与 DB compatibility 必须证明。
- migration 无安全 rollback 时提供 forward-fix 和备份恢复。
- Runbook/policy 回滚不能重新激活已知不安全版本。
- 发布后异常先 kill switch，协调 Action，再选择应用回滚。
- 事故/报告/审计不因回滚删除。

## 10. 签署记录

实际发布时在发布工件中记录：release ID、commit、日期、scope、每个 gate 的证据链接、No-Go 例外及接受者角色。当前不创建虚假签署人或“全部通过”勾选。
