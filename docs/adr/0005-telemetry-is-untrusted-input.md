# ADR-0005：遥测一律视为不可信输入

- 状态：proposed
- 提出日期：2026-08-01
- 决策者角色：security、AI、observability

## 背景

日志、Trace attributes、告警 annotations 和错误正文可由故障服务或攻击者控制。LLM 会阅读这些内容；若把它们当系统指令，攻击者可诱导越权工具、秘密外发或伪审批。

## 驱动因素

- 提示注入是核心展示和真实风险。
- 安全不能依赖模型“听话”。
- 工具结果仍需保留可解释证据价值。

## 候选方案

1. 依赖 system prompt 告知模型忽略攻击：成本低，但不是确定性边界。
2. 预先删除可疑文本：会漏变体，也可能损坏诊断证据。
3. 不可信 envelope + 模板工具 + 双重脱敏 + 确定性 policy/Gateway。
4. 完全不向模型提供日志：安全简单，但削弱调查价值。

## 拟议决定

所有外部/业务遥测按不可信数据处理：明确 role/data envelope、转义/长度限制、采集和送模脱敏、固定工具模板、无通用 URL/Shell、结构化模型输出。模型生成的任何 plan 仍需确定性验证、风险分级、人工审批和 Gateway 独立校验。

## 正面后果

- 攻击文本仍可作为 Evidence 展示，不会获得控制权。
- 安全边界在模型之外，能做确定性负向测试。
- 数据最小化和外发范围清晰。

## 负面后果

- 摘要/截断可能丢失诊断细节。
- 脱敏存在未知模式漏检残余风险。
- 工具模板减少模型自由探索，需要维护模板覆盖。

## 验证门槛

- 固定攻击集不能改变 tool catalog、query scope、risk、approval 或 egress。
- 模型即使输出 R3，policy/Gateway 仍确定性拒绝。
- secret fixture 在 Evidence、provider request、日志和导出四处无明文。
- 合法诊断/合法 R1 接受率同时报告，避免拒绝一切。

## 回退/重审

该原则是安全不变量，不因模型能力提升取消。若某信号源被提升可信，必须证明其签名、写入权限和内容边界，并创建 superseding ADR。

## 关联

[安全模型](../security-model.md)、[LLM 工具协议](../llm-and-tooling-protocol.md)、[安全矩阵](../security-control-matrix.md)
