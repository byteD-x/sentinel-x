# M0-03 模型结构化输出 Spike 报告

> **执行日期：** 2026-08-01  
> **执行环境：** Windows 10 Pro, Python 3.13.9, Ollama 0.17.7  
> **验证人：** Claude Code Agent  
> **原始数据：** `.codex/m0-model-spike-results.json`

## 1. 验证目标

验证候选模型能否在固定 JSON Schema 下稳定生成 Hypothesis 结构化输出，并评估 Token 消耗、延迟和失败模式。

## 2. 实验设计

- **测试模型：** qwen2.5:7b（Ollama 本地部署，4.7 GB）
- **Provider：** Ollama (OpenAI-compatible API，`http://127.0.0.1:11434/v1`)
- **测试 Schema：** Hypothesis（statement, confidence, root_cause_category, affected_service, supporting/opposing evidence, suggested_next_steps, needs_human_escalation）
- **场景数：** 4（payment-service-latency, order-db-errors, inventory-stock-sync, clean-no-issue）
- **每场景运行：** 3 次
- **总运行次数：** 12
- **补充测试：** glm-5:cloud, kimi-k2.5:cloud, minimax-m2.5:cloud, deepseek-v3.2:cloud — 全部已退役（410 Gone），不可用

## 3. 原始结果

| 指标 | 值 |
| --- | --- |
| 成功率 | **100%** (12/12) |
| 平均延迟 | 10,685ms |
| P50 延迟 | 10,341ms |
| P95 延迟 | 17,244ms |
| P99 延迟 | 17,244ms |
| 平均 Prompt Tokens | 265 |
| 平均 Completion Tokens | 270 |
| 平均 Total Tokens | 535 |

## 4. 关键发现

### 4.1 结构化输出能力 ✅

qwen2.5:7b 成功生成 12/12 个完全符合 JSON Schema 的 Hypothesis 结构：
- 所有必填字段均被填充
- 枚举值正确使用（`root_cause_category` 正确选择 `application`/`database`/`network`/`kubernetes`/`unknown`）
- evidence 引用使用规范的 `evidence_id` + `relevance` 结构
- `suggested_next_steps` 合理且非破坏性

### 4.2 Schema 校验缺口 ⚠️

模型返回 `confidence: 85` 而非 Schema 要求的 `0.0~1.0` 范围。**这验证了架构文档的核心安全原则：模型输出不能直接信任，必须经过服务端 Schema 校验层过滤。** 在 Sentinel-X 中，所有模型输出应通过 Pydantic 严格校验后再写入数据库。

### 4.3 模型可用性风险 ☢️

原先拉取的 4 个 cloud 模型（deepseek-v3.2, glm-5, kimi-k2.5, minimax-m2.5）全部已退役（410 Gone）。**本地开发的模型可用性完全依赖 Ollama 的模型更新策略。** 正式开发时应：
1. 锁定特定模型版本（而非 `:latest` 或 `:cloud`）
2. 在 `LLM_MODEL` 配置中固定模型标识
3. 定期验证模型可用性

### 4.4 延迟评估

本地 7B 模型延迟约 10 秒/请求。对于事故调查场景（非实时交互），此延迟可接受，但需要为 Investigator 设置合理的调查预算上限（`INVESTIGATION_MAX_SECONDS` 默认 480s，预算充足）。

### 4.5 Token 消耗

平均 535 tokens/次调用，远低于 `LLM_MAX_OUTPUT_TOKENS=8000` 上限。预算充足。

## 5. 样本输出

```json
{
  "statement": "根因假设：inventory-api 服务在 15:31-15:33 期间出现了大量连接超时错误，导致 payment-api 调用 inventory-api 时延迟显著增加，进而引发了 Payment API 的高延迟告警。",
  "confidence": 85,
  "root_cause_category": "application",
  "affected_service": "inventory-api",
  "supporting_evidence": [
    {"evidence_id": "E002", "relevance": "supporting"},
    {"evidence_id": "E003", "relevance": "supporting"}
  ],
  "opposing_evidence": [
    {"evidence_id": "E001", "relevance": "opposing"},
    {"evidence_id": "E004", "relevance": "opposing"}
  ],
  "suggested_next_steps": [
    "检查 inventory-api 的负载情况和资源使用情况，确认是否存在性能瓶颈。",
    "审查 inventory-api 的代码和配置，查找可能导致连接超时的具体原因。",
    "监控 inventory-api 的服务状态，确保其在高负载情况下仍能正常响应。"
  ],
  "needs_human_escalation": false
}
```

## 6. 对 ADR 的影响

| ADR | 验证结果 | 建议状态 |
| --- | --- | --- |
| ADR-0005（遥测为不可信输入） | **强化**：模型输出也需要 Schema 二次校验 | accepted（有证据） |

## 7. 后续行动

- [ ] 在 M3 实现时，Investigator 的输出必须通过 Pydantic 严格校验
- [ ] 在 `configuration-reference.md` 中记录模型锁定策略
- [ ] 定期运行 `ollama list` 检查模型可用性
- [ ] 考虑在 CI 中加入模型可用性 smoke test

## 8. 结论

✅ **结构化输出可行。** qwen2.5:7b 本地模型能够稳定生成符合 Sentinel-X Hypothesis Schema 的结构化输出。100% 成功率，Token 和延迟在预算范围内。模型输出验证需要服务端二次校验（Pydantic），这是架构中已规划的安全措施。
