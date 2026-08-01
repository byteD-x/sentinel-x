# ADR-0003：数据库绑定审批与工作负载身份

- 状态：proposed
- 提出日期：2026-08-01
- 决策者角色：security、runtime、data

## 背景

Worker 调用 Action Gateway 同时需要证明“谁在调用”和“某个动作已获授权”。共享静态 bearer 或让 Worker 发送完整已批准 plan 会把服务身份、审批授权和数据完整性混在一起。

## 驱动因素

- Gateway 必须独立验证，而非信任模型/Worker。
- 审批要绑定 plan/target/policy/expiry/nonce/次数。
- 并发/重放只能消费一次。
- MVP 避免自定义 JWS/PKI 的额外密钥生命周期。

## 候选方案

1. Worker/Gateway 共享静态 token：简单但身份粗、轮换和泄漏风险高。
2. Control API 签发 JWS 审批 token：跨服务好，但需要私钥、验证和吊销设计。
3. Gateway 直接读取/原子消费不可变 DB 审批 + K8s projected SA token 认证 Worker。
4. mTLS + 外部 IAM：边界强，但 MVP 依赖过重。

## 拟议决定

Worker 使用 audience=`sentinel-action-gateway` 的短时 projected ServiceAccount token；Gateway 通过 TokenReview 验证 subject/audience。Worker 请求只传 plan/approval refs 与幂等键。Gateway 使用专用最小 DB role 独立读取 plan/ApprovalDecision/policy view，并在同事务登记 ActionExecution、消费审批次数。

## 正面后果

- 服务身份和动作授权明确分离。
- 审批撤销/过期/并发由数据库约束和锁处理。
- 不引入自定义签名 token 和私钥分发。

## 负面后果

- Gateway 依赖 PostgreSQL；DB 不可用时默认拒绝动作。
- TokenReview 需要有限集群级 API 权限和可用性。
- DB 超级用户仍在可信边界内。

## 验证门槛

- 错 audience/subject/过期 token 被拒绝。
- Worker 伪造 approved payload 不生效。
- approval 篡改/过期/撤销/并发/重放只允许合法一次消费。
- Gateway DB role 无权读取模型密钥、原始遥测或修改 ApprovalDecision。

## 回退/重审

若未来跨集群、跨数据库或离线授权需要可携带凭证，再评估短时 JWS/外部授权服务并建立 superseding ADR。

## 关联

[API 契约](../api-contracts.md)、[数据模型](../data-model.md)、[安全控制矩阵](../security-control-matrix.md)
