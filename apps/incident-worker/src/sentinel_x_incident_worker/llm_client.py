"""
LLM 客户端 — OpenAI-compatible API 封装。

支持:
- OpenAI API、Ollama 及任何 OpenAI-compatible provider
- 结构化输出（JSON Schema）
- 自动重试（429/5xx）
- Token 消耗追踪
- 超时控制

用法：
    client = LLMClient(base_url="http://localhost:11434/v1", model="qwen2.5:7b")
    hypothesis = await client.structured_output(
        system_prompt="你是 SRE 专家...",
        user_prompt="分析以下证据...",
        output_schema=HYPOTHESIS_SCHEMA,
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class LLMCallResult:
    """LLM 调用结果。"""
    success: bool
    parsed_output: dict | None = None
    raw_response: str = ""
    model: str = ""
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_total: int = 0
    latency_seconds: float = 0.0
    retry_count: int = 0
    error: str = ""


@dataclass
class LLMUsage:
    """累计 Token 使用统计。"""
    total_calls: int = 0
    total_success: int = 0
    total_failures: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_total: int = 0
    total_latency_seconds: float = 0.0
    total_retries: int = 0

    @property
    def avg_latency(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_latency_seconds / self.total_calls

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_success / self.total_calls


# ---------------------------------------------------------------------------
# LLM 客户端
# ---------------------------------------------------------------------------


class LLMClientError(Exception):
    """LLM 客户端错误。"""


class LLMTimeoutError(LLMClientError):
    """LLM 调用超时。"""


class LLMStructuredOutputError(LLMClientError):
    """结构化输出解析失败。"""


class LLMClient:
    """
    OpenAI-compatible LLM 客户端。

    封装了重试、超时、结构化输出和 Token 追踪。

    用法：
        client = LLMClient(
            base_url="http://localhost:11434/v1",
            model="qwen2.5:7b",
        )
        result = await client.structured_output(
            system_prompt="你是 SRE 专家",
            user_prompt="分析告警...",
            output_schema={"type": "object", "properties": {...}},
        )
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        api_key = "",
        model: str = "qwen2.5:7b",
        temperature: float = 0.3,
        max_output_tokens: int = 2000,
        timeout_seconds: int = 120,
        max_retries: int = 3,
        retry_delay_seconds: float = 2.0,
        retry_backoff: float = 2.0,
    ):
        if not base_url:
            raise LLMClientError("base_url 不能为空")

        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.retry_backoff = retry_backoff

        client_options = {
            "base_url": base_url.rstrip("/"),
            "api_key": api_key or "not-set",
            "timeout": timeout_seconds,
            "max_retries": 0,  # 我们自己管理重试
        }
        self._client = AsyncOpenAI(**client_options)

        self._usage = LLMUsage()

    @property
    def usage(self) -> LLMUsage:
        return self._usage

    # ------------------------------------------------------------------
    # 结构化输出
    # ------------------------------------------------------------------

    async def structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: dict,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> LLMCallResult:
        """
        调用 LLM 并返回符合 JSON Schema 的结构化输出。

        Args:
            system_prompt: 系统提示
            user_prompt: 用户输入
            output_schema: JSON Schema 定义
            model: 覆盖默认模型
            temperature: 覆盖默认温度
            max_output_tokens: 覆盖最大输出 Token

        Returns:
            LLMCallResult
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # 在 user_prompt 末尾追加 Schema 指令
        schema_instruction = self._build_schema_instruction(output_schema)
        messages.append({"role": "user", "content": schema_instruction})

        return await self._call_with_retry(
            messages=messages,
            model=model or self.model,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_output_tokens or self.max_output_tokens,
            output_schema=output_schema,
        )

    # ------------------------------------------------------------------
    # 简单文本补全
    # ------------------------------------------------------------------

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: Optional[str] = None,
    ) -> LLMCallResult:
        """
        简单文本补全（非结构化）。

        Args:
            system_prompt: 系统提示
            user_prompt: 用户输入

        Returns:
            LLMCallResult (parsed_output 为 None)
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return await self._call_with_retry(
            messages=messages,
            model=model or self.model,
            temperature=self.temperature,
            max_tokens=self.max_output_tokens,
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        output_schema: Optional[dict] = None,
    ) -> LLMCallResult:
        """带重试的 LLM 调用。"""
        last_error = ""
        delay = self.retry_delay_seconds

        for attempt in range(self.max_retries + 1):
            try:
                start = time.perf_counter()
                completion = await self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"} if output_schema else None,
                )
                elapsed = time.perf_counter() - start

                result = self._process_response(
                    completion, elapsed, attempt, output_schema
                )
                self._record_result(result)
                return result

            except asyncio.TimeoutError:
                last_error = f"请求超时 ({self.timeout_seconds}s)"
                logger.warning(f"LLM 调用超时 (attempt {attempt + 1}/{self.max_retries + 1})")

            except Exception as e:
                last_error = str(e)
                error_str = str(e).lower()

                # 判断是否可重试
                if any(kw in error_str for kw in ("429", "rate limit", "503", "502", "timeout", "connection")):
                    logger.warning(
                        f"LLM 调用失败 (attempt {attempt + 1}/{self.max_retries + 1}): {e}"
                    )
                else:
                    # 不可重试的错误
                    logger.error(f"LLM 调用不可重试错误: {e}")
                    result = LLMCallResult(
                        success=False,
                        error=str(e),
                        model=model,
                        retry_count=attempt,
                    )
                    self._record_result(result)
                    return result

            # 重试前等待
            if attempt < self.max_retries:
                await asyncio.sleep(delay)
                delay *= self.retry_backoff

        # 所有重试耗尽
        result = LLMCallResult(
            success=False,
            error=f"重试 {self.max_retries} 次后仍失败: {last_error}",
            model=model,
            retry_count=self.max_retries,
        )
        self._record_result(result)
        return result

    def _process_response(
        self,
        completion: ChatCompletion,
        elapsed: float,
        retry_count: int,
        output_schema: Optional[dict] = None,
    ) -> LLMCallResult:
        """处理 API 响应。"""
        choice = completion.choices[0]
        content = choice.message.content or ""

        # 提取 Token 用量
        usage = completion.usage
        tokens_prompt = usage.prompt_tokens if usage else 0
        tokens_completion = usage.completion_tokens if usage else 0
        tokens_total = usage.total_tokens if usage else 0

        if output_schema:
            # 结构化输出 — 从 JSON 中提取
            parsed = self._extract_json(content, output_schema)
            if parsed is None:
                return LLMCallResult(
                    success=False,
                    raw_response=content[:500],
                    model=completion.model,
                    tokens_prompt=tokens_prompt,
                    tokens_completion=tokens_completion,
                    tokens_total=tokens_total,
                    latency_seconds=elapsed,
                    retry_count=retry_count,
                    error=f"无法从响应中提取有效 JSON: {content[:200]}...",
                )
        else:
            parsed = None

        return LLMCallResult(
            success=True,
            parsed_output=parsed,
            raw_response=content,
            model=completion.model,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            tokens_total=tokens_total,
            latency_seconds=elapsed,
            retry_count=retry_count,
        )

    def _extract_json(self, content: str, schema: dict) -> Optional[dict]:
        """从 LLM 文本响应中提取 JSON。"""
        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 尝试从 JSON 代码块中提取
        import re
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试找到第一个 { ... } 对
        brace_match = re.search(r'\{.*\}', content, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _build_schema_instruction(schema: dict) -> str:
        """构建 Schema 指令追加到 user prompt。"""
        schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
        return (
            "请严格按照以下 JSON Schema 格式输出结果，只输出 JSON 对象，不要包含其他文本：\n"
            f"```json\n{schema_str}\n```\n"
            "请确保：\n"
            "1. 输出是合法的 JSON\n"
            "2. 所有必填字段都已填充\n"
            "3. 数值在 Schema 允许的范围内\n"
            "4. 字符串使用 Schema 中定义的枚举值"
        )

    def _record_result(self, result: LLMCallResult) -> None:
        """更新使用统计。"""
        self._usage.total_calls += 1
        if result.success:
            self._usage.total_success += 1
        else:
            self._usage.total_failures += 1
        self._usage.tokens_prompt += result.tokens_prompt
        self._usage.tokens_completion += result.tokens_completion
        self._usage.tokens_total += result.tokens_total
        self._usage.total_latency_seconds += result.latency_seconds
        self._usage.total_retries += result.retry_count

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    async def health_check(self) -> dict:
        """检查 LLM 服务是否可达。"""
        start = time.perf_counter()
        try:
            # 获取模型列表来验证连接
            models = await asyncio.wait_for(
                self._client.models.list(),
                timeout=10.0,
            )
            elapsed = time.perf_counter() - start
            model_ids = [m.id for m in models.data[:5]]
            return {
                "status": "ok",
                "latency_ms": round(elapsed * 1000, 1),
                "available_models": model_ids,
                "configured_model": self.model,
            }
        except Exception as e:
            elapsed = time.perf_counter() - start
            return {
                "status": "unavailable",
                "latency_ms": round(elapsed * 1000, 1),
                "error": str(e)[:200],
            }


# ---------------------------------------------------------------------------
# 预设的 Schema 定义 — Hypothesis
# ---------------------------------------------------------------------------

HYPOTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "statement": {
            "type": "string",
            "description": "根因假设陈述，包含具体服务和故障机制",
            "minLength": 10,
            "maxLength": 2000,
        },
        "confidence": {
            "type": "number",
            "description": "置信度 0.0-1.0（不是百分比）",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "root_cause_category": {
            "type": "string",
            "enum": ["network", "application", "database", "kubernetes", "unknown"],
            "description": "根因类别",
        },
        "affected_service": {
            "type": "string",
            "description": "受影响的服务名称",
        },
        "supporting_evidence_refs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "支持此假设的证据 ID 列表",
        },
        "opposing_evidence_refs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "不支持此假设的证据 ID 列表",
        },
        "suggested_next_steps": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 10,
            "description": "建议的下一步调查步骤",
        },
        "needs_human_escalation": {
            "type": "boolean",
            "description": "是否需要升级人工处理",
        },
    },
    "required": [
        "statement",
        "confidence",
        "root_cause_category",
        "affected_service",
        "needs_human_escalation",
    ],
    "additionalProperties": False,
}


# 预设的 Schema 定义 — Evidence Analysis
EVIDENCE_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "key_findings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "从证据中提取的关键发现",
        },
        "anomalies_detected": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string"},
                    "observed": {"type": "string"},
                    "expected": {"type": "string"},
                    "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
                },
                "required": ["metric", "observed", "severity"],
            },
        },
        "requires_more_evidence": {"type": "boolean"},
        "suggested_queries": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["key_findings", "requires_more_evidence"],
    "additionalProperties": False,
}
