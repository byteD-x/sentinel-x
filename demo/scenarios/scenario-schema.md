# 场景 Schema

每个场景文件是 YAML，遵循 ScenarioDefinition 契约。

字段：
- name: 场景名称，格式 <service>-<fault>@<version>
- version: 场景版本
- description: 场景描述
- category: fault category (network|application|database|kubernetes|resource)
- faults: 故障注入列表
  - fault_type: 故障类型
  - target_service: 目标服务
  - parameters: 故障参数
  - duration_seconds: 持续时间
  - cleanup_command: 清理命令
- ground_truth: 已知根因描述
- expected_root_cause_category: 预期根因类别
- recovery_assertions: 恢复验证条件
- allowlisted_runbooks: 允许的恢复 Runbook
