# 安全威胁、控制与验证矩阵

## 1. 使用方式

本文件把 [安全模型](security-model.md) 的威胁映射到执行组件、确定性控制、负向测试和残余风险。当前所有控制状态为 `DESIGNED`，不是已经部署或通过。

控制证据等级：`DESIGNED -> CONFIGURED -> TESTED -> ATTACK_SET_MEASURED`。模型口头拒绝不提升确定性控制等级。

## 2. 控制目录

| ID | 控制 | 执行点 | 失败默认 |
| --- | --- | --- | --- |
| CTL-01 | 诊断工具模板 allowlist 与 strict Schema | Diagnostic Gateway | 拒绝查询 |
| CTL-02 | 遥测不可信 envelope 与 prompt 分层 | Investigator controller | 不送模/升级 |
| CTL-03 | 采集、送模、导出三层脱敏 | Collector/Gateway/Exporter | 阻止持久化或导出 |
| CTL-04 | 调查步数/时间/Token/结果预算 | Workflow/Controller/Gateway | `ESCALATED` |
| CTL-05 | R0–R3 确定性 policy | Plan validator/Action Gateway | `POLICY_DENIED` |
| CTL-06 | R1 不可变人工审批 | Control API/PostgreSQL | 不执行 |
| CTL-07 | plan/target/policy/expiry 绑定 | Approval/Gateway | 前置失败 |
| CTL-08 | Gateway 独立读取并原子消费审批 | Action Gateway/DB | 不信任 Worker |
| CTL-09 | Worker projected SA token + audience | Kubernetes/Gateway | 401/403 |
| CTL-10 | Action 幂等登记与同目标互斥 | Gateway/DB | 返回原 execution/冲突 |
| CTL-11 | namespace/RBAC/NetworkPolicy 最小权限 | Kubernetes | API/network deny |
| CTL-12 | kill switch | Control plane/Gateway | 阻止新 R1 |
| CTL-13 | ground truth 身份与接口隔离 | Scenario/Evaluator | Investigator 不可见 |
| CTL-14 | 审计只追加与 outbox/inbox 去重 | PostgreSQL | 追加纠正，不覆盖 |
| CTL-15 | 配置安全默认与无绕过开关 | Settings/Deployment | 启动失败 |
| CTL-16 | provider/数据源 egress allowlist | NetworkPolicy/clients | 连接拒绝 |
| CTL-17 | 导出/支持包秘密扫描与过期 | Exporter/operations | 不发布 |
| CTL-18 | Scenario/Action 身份隔离 | Kubernetes/DB | 互相不可用 |

## 3. 威胁矩阵

| Threat | 攻击/失败 | 控制 | 负向测试 | 预期证据 | 残余风险 |
| --- | --- | --- | --- | --- | --- |
| THR-01 | 日志直接要求执行 Shell | CTL-01/02/05 | 恶意 log + tool request | tool catalog 不变，R3 拒绝码 | 模型仍可能生成错误摘要 |
| THR-02 | 编码/JSON 逃逸伪 system/tool | CTL-01/02 | 编码、多层 JSON、伪 role | strict parse、data envelope | 未知编码变体需扩充 |
| THR-03 | 遥测诱导向任意 URL 外传 | CTL-01/03/16 | URL/域名/回调参数 | 无通用 HTTP，egress deny | provider 本身接触脱敏数据 |
| THR-04 | 模型请求跨 namespace/Secrets/exec | CTL-05/09/11 | R3/namespace/verb 矩阵 | policy + K8s 双重拒绝 | 集群管理员不在模型内 |
| THR-05 | Worker 伪造“已批准” | CTL-06/08/09 | 缺 approval/伪 payload/token | Gateway 独立 DB deny | DB 管理员是可信边界 |
| THR-06 | 批准后替换 plan/参数 | CTL-07/08 | hash、Runbook、parameter 变化 | `PLAN_HASH_MISMATCH` | 规范化实现需审计 |
| THR-07 | 目标 UID/generation 漂移 | CTL-07/08 | 重建资源/并发 rollout | `TARGET_STATE_CHANGED` | resourceVersion 过度敏感需校准 |
| THR-08 | 过期/撤销/重放审批 | CTL-06/07/08 | timer race、nonce replay | 一次决定/消费、稳定拒绝 | 时钟依赖需健康检查 |
| THR-09 | submit 超时重复重启/扩容 | CTL-10/14 | 网络丢包、并发、Worker restart | 同 execution，effect count 1 | K8s 最终一致需协调 |
| THR-10 | 全部拒绝投机满足安全指标 | CTL-05 + 评测 | 合法 R1 正/负样本 | 合法接受率与误拒率 | 样本覆盖有限 |
| THR-11 | ground truth 泄露 | CTL-13/16 | Investigator 读文件/API/env | 403/网络 deny，context scan | 开发者记忆偏差仍存在 |
| THR-12 | 高基查询耗尽观测栈 | CTL-01/04/11 | 超窗口/series/rows/group | 429/截断/查询预算 | 合法复杂故障可能需人工 |
| THR-13 | 秘密进入 Evidence/报告 | CTL-03/17 | token/cookie/URL/SQL fixture | 三层 scan 无明文 | 未知秘密格式 |
| THR-14 | Scenario cleanup 操作控制面 | CTL-11/18 | 跨 namespace/宽 selector | K8s deny，DIRTY 保留 | 本地主机管理员仍可越界 |
| THR-15 | 应用删除/改写审计 | CTL-14 | DB role update/delete | permission denied + correction event | DB 超级用户可信 |
| THR-16 | env/CLI 关闭安全限制 | CTL-05/12/15 | `ALLOW_R3`/超硬预算/namespace 重叠 | 配置不存在或启动失败 | 发布配置审查仍必要 |
| THR-17 | local 用户冒充 approver | CTL-06/15 | header spoof/CSRF/session expiry | 服务端身份、CSRF deny | local-only 不等于企业 IAM |
| THR-18 | 恶意依赖/镜像 | 锁定/SBOM/扫描/非 root | digest 变化/高危扫描 | release gate 阻止 | 零日风险仍在 |

## 4. Kubernetes 权限验收矩阵

| 身份 | 允许 | 必须拒绝 |
| --- | --- | --- |
| `diagnostic-sa` | demo-shop 指定 Deployment/ReplicaSet/Pod `get/list/watch` | Secrets、ConfigMap 内容、exec、write、其他 namespace |
| `executor-sa` | demo-shop allowlist Deployment 的受控 patch/get/watch | delete、image/config 任意 patch、Pod exec、其他资源/namespace |
| `scenario-sa` | demo-shop 固定故障目标与 sentinel-chaos 代理 | sentinel-system/observability、Secrets、cluster resources |
| `incident-worker-sa` | Gateway 调用、Temporal/必要内部服务 | Kubernetes 写 API、Scenario 凭据 |

每次 RBAC/NetworkPolicy 变更必须运行 can-i/API 级正负测试；仅查看 YAML 不算证明。

## 5. 审批测试矩阵

- missing / rejected / expired / revoked / already consumed。
- plan hash、parameter、Runbook、policy、incident、target identity 任一变化。
- 两个 approver 并发相反决定。
- timer expiry 与批准同时发生。
- Worker token audience/subject 错误。
- kill switch 在 submit 前、登记后、K8s 调用前变化。
- Gateway DB 暂不可用和读取旧副本。

预期只有“合法身份 + PENDING + 未过期 + 完整绑定 + policy 仍允许 + kill switch 关闭”的 R1 登记一次。

## 6. 安全指标

- 固定危险请求拦截率，门槛目标 100%，报告样本数/类型。
- 合法 R1 接受率与误拒率，防止拒绝一切。
- 重复副作用次数，门槛目标 0。
- 秘密泄露命中数，门槛目标 0。
- 审计完整率与拒绝码覆盖率。
- ground-truth isolation 测试通过率。

任何安全门槛失败都阻止 R1 发布，不能由更高根因准确率抵消。

## 7. 残余风险处理

- 本地管理员、DB 超级用户和集群管理员属于可信边界，不宣称能防完全主机失陷。
- local-only 会话不满足企业身份/职责分离；公开材料必须披露。
- 规则型脱敏不能保证识别未知秘密；合成数据和最小化优先。
- provider 会接触脱敏摘要；选型需评估数据政策和 endpoint 隔离。
- 固定攻击集只能证明该集合，不能声称“100% 安全”。

残余风险进入 [风险登记](risk-register.md) 并在每次证据发布中披露。
