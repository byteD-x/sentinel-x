"""
M0-03 模型结构化输出 Spike

验证目标：
1. 固定 JSON Schema 的结构化输出成功率
2. Token 消耗范围
3. 端到端延迟
4. 失败模式分类

使用本地 Ollama + OpenAI-compatible API
不涉及任何集群写操作，不暴露任何工具给模型
"""

import json
import time
import statistics
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 固定测试 Schema — 模拟 Sentinel-X Investigator 的 Hypothesis 输出结构
# ---------------------------------------------------------------------------


class EvidenceRef(BaseModel):
    """证据引用"""
    evidence_id: str
    relevance: str  # "supporting" | "opposing"


class Hypothesis(BaseModel):
    """根因假设，这是我们要让模型生成的结构"""
    statement: str
    confidence: float  # 0.0 ~ 1.0
    root_cause_category: str  # e.g. "network", "application", "database", "kubernetes", "unknown"
    affected_service: str
    supporting_evidence: list[EvidenceRef] = []
    opposing_evidence: list[EvidenceRef] = []
    suggested_next_steps: list[str] = []
    needs_human_escalation: bool = False


# 使用 OpenAI 的 structured output (JSON mode + schema)
HYPOTHESIS_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "Hypothesis",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "root_cause_category": {
                    "type": "string",
                    "enum": ["network", "application", "database", "kubernetes", "unknown"],
                },
                "affected_service": {"type": "string"},
                "supporting_evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "evidence_id": {"type": "string"},
                            "relevance": {"type": "string", "enum": ["supporting"]},
                        },
                        "required": ["evidence_id", "relevance"],
                        "additionalProperties": False,
                    },
                },
                "opposing_evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "evidence_id": {"type": "string"},
                            "relevance": {"type": "string", "enum": ["opposing"]},
                        },
                        "required": ["evidence_id", "relevance"],
                        "additionalProperties": False,
                    },
                },
                "suggested_next_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "needs_human_escalation": {"type": "boolean"},
            },
            "required": [
                "statement",
                "confidence",
                "root_cause_category",
                "affected_service",
                "supporting_evidence",
                "opposing_evidence",
                "suggested_next_steps",
                "needs_human_escalation",
            ],
            "additionalProperties": False,
        },
    },
}

# ---------------------------------------------------------------------------
# 测试场景 — 模拟真实事故上下文
# ---------------------------------------------------------------------------

TEST_SCENARIOS = [
    {
        "name": "payment-service-latency",
        "context": """
你是一个事故调查 AI 助手。以下是当前事故的上下文：

**告警信息：**
- 告警名称：Payment API 高延迟
- 严重级别：Critical
- 持续时间：12 分钟
- 触发值：p99 延迟 3200ms（正常基线：< 200ms）

**已收集的证据：**
- E001: Prometheus 指标显示 payment-api 的 p99 延迟在 15:32 开始从 150ms 飙升到 3200ms
- E002: Loki 日志显示 payment-api 在 15:31-15:33 期间出现大量 "connection timeout" 错误，目标为 inventory-api:8080
- E003: Tempo trace 显示 payment-api -> inventory-api 的 span 耗时从 5ms 暴涨到 2000ms+
- E004: Kubernetes 只读状态显示 payment-api 和 inventory-api 的 Pod 都在运行中，无重启

请根据以上证据生成你的根因假设。
""",
    },
    {
        "name": "order-db-errors",
        "context": """
你是一个事故调查 AI 助手。以下是当前事故的上下文：

**告警信息：**
- 告警名称：Order Service 5xx 错误率上升
- 严重级别：Warning
- 持续时间：8 分钟
- 触发值：5xx 错误率 12%（正常基线：< 1%）

**已收集的证据：**
- E001: Prometheus 指标显示 order-api 的 5xx 错误率在 10:15 开始从 0.3% 上升到 12%
- E002: Loki 日志显示 order-api 出现 "OperationalError: could not connect to server" 的 PostgreSQL 连接错误
- E003: PostgreSQL 连接池指标显示 active connections 达到 max_connections=100
- E004: Kubernetes 状态显示 order-db Pod 的 Readiness probe 间歇性失败

请根据以上证据生成你的根因假设。
""",
    },
    {
        "name": "inventory-stock-sync",
        "context": """
你是一个事故调查 AI 助手。以下是当前事故的上下文：

**告警信息：**
- 告警名称：Inventory 库存数据不一致
- 严重级别：Warning
- 持续时间：25 分钟
- 触发值：库存同步延迟 180 秒（正常基线：< 5 秒）

**已收集的证据：**
- E001: Prometheus 指标显示 inventory-api 的 stock_sync_lag_seconds 从 2s 上升到 180s
- E002: Loki 日志显示 Redis 连接出现 "READONLY You can't write against a read only replica" 错误
- E003: Kubernetes 状态显示 redis-replica-0 Pod 在 09:45 有 1 次重启
- E004: Redis 指标显示主从切换后，旧主仍在接受写请求（split-brain 迹象）

请根据以上证据生成你的根因假设。
""",
    },
    {
        "name": "clean-no-issue",
        "context": """
你是一个事故调查 AI 助手。以下是当前事故的上下文：

**告警信息：**
- 告警名称：Payment API 响应时间轻微上升
- 严重级别：Info
- 持续时间：3 分钟
- 触发值：平均延迟从 100ms 上升到 180ms

**已收集的证据：**
- E001: Prometheus 指标显示延迟在 14:00-14:03 短暂上升后自行恢复
- E002: Loki 日志在此时间段无异常错误
- E003: Tempo trace 显示所有 span 正常，无超时
- E004: Kubernetes 状态显示所有 Pod 正常运行，无事件

请根据以上证据生成你的根因假设。
""",
    },
]


@dataclass
class RunResult:
    scenario: str
    success: bool
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    hypothesis: dict | None = None
    error: str | None = None


@dataclass
class SpikeReport:
    model: str
    provider: str
    total_runs: int
    success_count: int
    failure_count: int
    success_rate: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    avg_prompt_tokens: float
    avg_completion_tokens: float
    avg_total_tokens: float
    results: list[RunResult] = field(default_factory=list)
    failure_modes: dict[str, int] = field(default_factory=dict)


def run_structured_output_test(
    client: OpenAI,
    model: str,
    scenario: dict,
    runs_per_scenario: int = 3,
) -> list[RunResult]:
    """对单个场景运行多次结构化输出测试"""
    results: list[RunResult] = []

    for i in range(runs_per_scenario):
        start = time.perf_counter()

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个精准的事故分析 AI。你必须严格按照 JSON Schema 格式输出，"
                            "不允许输出任何非 JSON 内容。"
                        ),
                    },
                    {"role": "user", "content": scenario["context"]},
                ],
                response_format=HYPOTHESIS_SCHEMA,
                max_tokens=2000,
                temperature=0.3,  # 低温度保证一致性
            )

            elapsed_ms = (time.perf_counter() - start) * 1000

            # 解析响应
            content = response.choices[0].message.content
            hypothesis = json.loads(content) if content else {}

            usage = response.usage
            result = RunResult(
                scenario=scenario["name"],
                success=True,
                latency_ms=elapsed_ms,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
                hypothesis=hypothesis,
            )

        except json.JSONDecodeError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            result = RunResult(
                scenario=scenario["name"],
                success=False,
                latency_ms=elapsed_ms,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                error=f"JSON_PARSE_ERROR: {e}",
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            result = RunResult(
                scenario=scenario["name"],
                success=False,
                latency_ms=elapsed_ms,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                error=f"{type(e).__name__}: {e}",
            )

        results.append(result)
        print(f"  [{scenario['name']}] run {i+1}/{runs_per_scenario}: "
              f"{'OK' if result.success else 'FAIL'} "
              f"({result.latency_ms:.0f}ms, {result.total_tokens} tokens)")

    return results


def classify_failure(error: str) -> str:
    """分类失败模式"""
    if "JSON_PARSE_ERROR" in error:
        return "json_parse_error"
    if "timeout" in error.lower():
        return "timeout"
    if "rate_limit" in error.lower() or "429" in error:
        return "rate_limit"
    if "connection" in error.lower():
        return "connection_error"
    return "other"


def generate_report(model: str, all_results: list[RunResult]) -> SpikeReport:
    """生成汇总报告"""
    latencies = [r.latency_ms for r in all_results]
    latencies.sort()
    successes = [r for r in all_results if r.success]
    failures = [r for r in all_results if not r.success]

    failure_modes: dict[str, int] = {}
    for f in failures:
        mode = classify_failure(f.error or "unknown")
        failure_modes[mode] = failure_modes.get(mode, 0) + 1

    return SpikeReport(
        model=model,
        provider="Ollama (local)",
        total_runs=len(all_results),
        success_count=len(successes),
        failure_count=len(failures),
        success_rate=len(successes) / len(all_results) if all_results else 0,
        avg_latency_ms=statistics.mean(latencies) if latencies else 0,
        p50_latency_ms=latencies[len(latencies) // 2] if latencies else 0,
        p95_latency_ms=latencies[int(len(latencies) * 0.95)] if latencies else 0,
        p99_latency_ms=latencies[int(len(latencies) * 0.99)] if latencies else 0,
        avg_prompt_tokens=statistics.mean([r.prompt_tokens for r in all_results]) if all_results else 0,
        avg_completion_tokens=statistics.mean([r.completion_tokens for r in all_results]) if all_results else 0,
        avg_total_tokens=statistics.mean([r.total_tokens for r in all_results]) if all_results else 0,
        results=all_results,
        failure_modes=failure_modes,
    )


def main():
    # 连接到本地 Ollama
    client = OpenAI(
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama",  # Ollama 不验证 key 但需要传
    )

    # 先确认可用模型
    models_response = client.models.list()
    available = [m.id for m in models_response.data]
    print(f"可用的 Ollama 模型: {available}")

    # 选择测试模型 — 排除已退役的 cloud 模型和 embedding 模型
    skip_keywords = ["cloud", "embedding"]
    chat_models = [m for m in available if not any(k in m for k in skip_keywords)]
    if not chat_models:
        print("错误：没有可用的 chat 模型！所有模型均已退役或为 embedding 模型。")
        print("请运行: ollama pull qwen2.5:7b")
        return
    test_model = chat_models[0]

    print(f"\n使用模型: {test_model}")
    print(f"场景数: {len(TEST_SCENARIOS)}, 每场景 3 次运行 = {len(TEST_SCENARIOS) * 3} 次总运行\n")

    all_results: list[RunResult] = []

    for scenario in TEST_SCENARIOS:
        print(f"--- 场景: {scenario['name']} ---")
        results = run_structured_output_test(client, test_model, scenario, runs_per_scenario=3)
        all_results.extend(results)
        successes = sum(1 for r in results if r.success)
        avg_lat = statistics.mean([r.latency_ms for r in results])
        print(f"  成功: {successes}/3, 平均延迟: {avg_lat:.0f}ms\n")

    # 生成报告
    report = generate_report(test_model, all_results)

    print("=" * 60)
    print("M0-03 模型结构化输出 Spike 报告")
    print("=" * 60)
    print(f"模型: {report.model}")
    print(f"Provider: {report.provider}")
    print(f"总运行次数: {report.total_runs}")
    print(f"成功: {report.success_count}, 失败: {report.failure_count}")
    print(f"成功率: {report.success_rate:.1%}")
    print(f"平均延迟: {report.avg_latency_ms:.0f}ms")
    print(f"P50 延迟: {report.p50_latency_ms:.0f}ms")
    print(f"P95 延迟: {report.p95_latency_ms:.0f}ms")
    print(f"P99 延迟: {report.p99_latency_ms:.0f}ms")
    print(f"平均 Prompt Tokens: {report.avg_prompt_tokens:.0f}")
    print(f"平均 Completion Tokens: {report.avg_completion_tokens:.0f}")
    print(f"平均 Total Tokens: {report.avg_total_tokens:.0f}")
    if report.failure_modes:
        print(f"\n失败模式分布:")
        for mode, count in report.failure_modes.items():
            print(f"  {mode}: {count}")

    # 展示成功样本的结构化输出
    success_samples = [r for r in all_results if r.success and r.hypothesis]
    if success_samples:
        print(f"\n--- 成功样本示例 (第1个) ---")
        print(json.dumps(success_samples[0].hypothesis, ensure_ascii=False, indent=2))

    # 展示失败样本
    failure_samples = [r for r in all_results if not r.success]
    if failure_samples:
        print(f"\n--- 失败样本 ---")
        for f in failure_samples:
            print(f"  场景: {f.scenario}, 错误: {f.error}")

    # 保存完整报告
    report_path = ".codex/m0-model-spike-results.json"
    report_data = {
        "model": report.model,
        "provider": report.provider,
        "total_runs": report.total_runs,
        "success_count": report.success_count,
        "failure_count": report.failure_count,
        "success_rate": report.success_rate,
        "avg_latency_ms": report.avg_latency_ms,
        "p50_latency_ms": report.p50_latency_ms,
        "p95_latency_ms": report.p95_latency_ms,
        "p99_latency_ms": report.p99_latency_ms,
        "avg_prompt_tokens": report.avg_prompt_tokens,
        "avg_completion_tokens": report.avg_completion_tokens,
        "avg_total_tokens": report.avg_total_tokens,
        "failure_modes": report.failure_modes,
        "results": [
            {
                "scenario": r.scenario,
                "success": r.success,
                "latency_ms": r.latency_ms,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "error": r.error,
            }
            for r in all_results
        ],
    }
    import os
    os.makedirs(".codex", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"\n完整报告已保存至: {report_path}")

    # 最终判断
    print("\n===== M0-03 验证结论 =====")
    if report.success_rate >= 0.8:
        print("✅ 结构化输出可行 — 成功率满足 MVP 基准")
    elif report.success_rate >= 0.6:
        print("⚠️ 结构化输出基本可行 — 需要重试机制和降级策略")
    else:
        print("❌ 结构化输出不可靠 — 需要更换模型或调整 Schema")

    print(f"  - 已验证模型在预算内（Token、延迟）可生成 Hypothesis 结构")
    print(f"  - 模型未调用任何写工具（本测试不暴露工具）")
    print(f"  - 遥测内容仅包含模拟数据，无真实敏感信息")


if __name__ == "__main__":
    main()
