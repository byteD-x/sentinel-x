# Changelog

本项目遵循 Keep a Changelog 的结构；语义版本策略将在首次代码发布前确定。

## [Unreleased]

### Added

- light Action Gateway 默认 fail-closed，新增 HMAC 审批凭证、管理员 Kill Switch 令牌和进程内并发幂等测试。
- Control API 新增活动 fingerprint 去重、状态迁移校验、审批归属校验与 local-demo 角色门控。
- Web Console 新增审批队列、系统状态、评测证据页面、角色可见性、SSE 重连/补读、演练预检和理由化拒绝。
- 演练服务测试改为动态端口、健康检查和可靠 teardown；前端补充 ESLint 门禁。

### Notes

- 当前为 D1-light 原型。fixture 执行、内存存储和 local-demo 角色门控不代表生产身份授权、Temporal 持久化、PostgreSQL、真实 Kubernetes 动作或 benchmark 已完成。
- 所有性能/效果数值仍为目标或待测。
