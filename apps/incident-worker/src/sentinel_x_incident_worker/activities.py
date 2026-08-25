"""
独立 Activity 函数 — Worker 注册到 Temporal 的可执行单元。

每个 Activity 有独立的超时、重试策略和错误处理。
所有外部 I/O（数据库、网络、LLM API、K8s API）必须通过 Activity。
"""

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sentinel_x_incident_worker.reconciliation import (
    ProjectionCheckpoint,
    reconcile_checkpoint,
)
from sentinel_x_diagnostics import DiagnosticToolType
from sentinel_x_diagnostics.sources import HttpTelemetrySource, TelemetrySourceError

logger = logging.getLogger(__name__)


def _require_real_full_adapter(capability: str) -> None:
    """full profile 禁止把 fixture 返回值当作真实外部 I/O。"""
    if os.getenv("SENTINEL_PROFILE", "light") == "full":
        raise RuntimeError(
            f"full profile 未配置真实 {capability} adapter；禁止使用 fixture Activity"
        )


def _telemetry_source() -> HttpTelemetrySource:
    urls = {
        "prometheus": os.getenv("PROMETHEUS_BASE_URL", ""),
        "loki": os.getenv("LOKI_BASE_URL", ""),
        "tempo": os.getenv("TEMPO_BASE_URL", ""),
    }
    if not all(urls.values()):
        raise RuntimeError("full profile 未配置 Prometheus adapter（需同时配置 Loki/Tempo）")
    return HttpTelemetrySource(
        prometheus_base_url=urls["prometheus"],
        loki_base_url=urls["loki"],
        tempo_base_url=urls["tempo"],
        timeout_seconds=float(os.getenv("TELEMETRY_TIMEOUT_SECONDS", "3")),
    )


def _observed_evidence(
    source: HttpTelemetrySource,
    tool: DiagnosticToolType,
    params: dict,
    query: str,
    *,
    include_payload: bool = False,
) -> dict:
    try:
        response = source.query(tool, params)
    except TelemetrySourceError:
        raise
    payload = response.payload
    if payload.get("status") not in {None, "success"}:
        raise RuntimeError(f"{tool.value} adapter 返回失败状态")
    payload_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    evidence = {
        "evidence_id": str(uuid4()),
        "source": tool.value,
        "source_ref": response.source_ref,
        "source_mode": "observed",
        "query": query,
        "summary": f"{tool.value} 真实来源查询成功",
        "raw_hash": payload_hash,
        "collected_at": datetime.now().isoformat(),
        "truncated": False,
    }
    if include_payload:
        evidence["_payload"] = payload
    return evidence


async def reconcile_postgres_projection(
    *,
    incident_id: str,
    expected: dict,
    database_url: str | None = None,
) -> dict:
    """Activity：从 PostgreSQL 读取投影 checkpoint 并 fail-closed 对账。

    ``database_url`` 仅供测试注入；生产 Activity 从 Worker 环境读取，避免
    凭据进入 Temporal Workflow history。
    """
    url = database_url or os.getenv("DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgresql+")):
        raise RuntimeError("PostgreSQL reconciliation 需要 DATABASE_URL")

    def read_checkpoint() -> dict:
        try:
            psycopg = __import__("psycopg")
        except ImportError as exc:
            raise RuntimeError("PostgreSQL reconciliation 需要 psycopg") from exc
        connection = psycopg.connect(url)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT workflow_run_id, workflow_event_id, status, projection_version
                    FROM incidents WHERE id = %s
                    """,
                    (incident_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("PostgreSQL projection 中不存在事故")
                return {
                    "workflow_run_id": row[0] or "",
                    "workflow_event_id": row[1] or "",
                    "status": str(row[2]),
                    "projection_version": int(row[3]),
                }
        finally:
            connection.close()

    observed = await asyncio.to_thread(read_checkpoint)
    reconcile_checkpoint(
        ProjectionCheckpoint(**expected),
        ProjectionCheckpoint(**observed),
    )
    return observed


# ---------------------------------------------------------------------------
# 证据收集 Activities
# ---------------------------------------------------------------------------


async def collect_prometheus_evidence(
    query: str,
    time_range_minutes: int = 15,
    incident_id: Optional[UUID] = None,
) -> dict:
    """
    [Activity] 执行 Prometheus 即时查询。

    超时: 30s, 重试: 最多 2 次（瞬态网络错误）
    """
    if os.getenv("SENTINEL_PROFILE", "light") != "full":
        await asyncio.sleep(0.2)
        return {
            "evidence_id": str(uuid4()), "source": "prometheus", "query": query,
            "summary": f"PromQL 查询结果摘要（窗口: {time_range_minutes}min）",
            "raw_hash": hashlib.sha256(query.encode()).hexdigest()[:16],
            "collected_at": datetime.now().isoformat(), "truncated": False,
        }
    return await asyncio.to_thread(
        _observed_evidence, _telemetry_source(), DiagnosticToolType.QUERY_PROMETHEUS,
        {"query": query, "time_range_minutes": time_range_minutes}, query,
    )


async def collect_loki_evidence(
    query: str,
    time_range_minutes: int = 15,
    limit: int = 50,
) -> dict:
    """
    [Activity] 执行 Loki 日志查询。

    超时: 30s, 重试: 最多 2 次
    结果自动脱敏。
    """
    if os.getenv("SENTINEL_PROFILE", "light") != "full":
        await asyncio.sleep(0.2)
        return {
            "evidence_id": str(uuid4()), "source": "loki", "query": query,
            "summary": f"LogQL 查询结果摘要（{limit} 条日志）",
            "raw_hash": hashlib.sha256(query.encode()).hexdigest()[:16],
            "collected_at": datetime.now().isoformat(), "truncated": False,
        }
    return await asyncio.to_thread(
        _observed_evidence, _telemetry_source(), DiagnosticToolType.QUERY_LOKI,
        {"query": query, "limit": limit, "time_range_minutes": time_range_minutes}, query,
    )


async def collect_tempo_evidence(
    trace_id: Optional[str] = None,
    service_name: Optional[str] = None,
    time_range_minutes: int = 15,
) -> dict:
    """
    [Activity] 查询 Tempo Trace。

    超时: 30s, 重试: 最多 1 次
    """
    query = f"trace_id={trace_id or 'auto'} service={service_name or 'auto'}"
    if os.getenv("SENTINEL_PROFILE", "light") != "full":
        await asyncio.sleep(0.2)
        return {
            "evidence_id": str(uuid4()), "source": "tempo", "query": query,
            "summary": "Trace 查询结果摘要",
            "raw_hash": hashlib.sha256(f"{trace_id}{service_name}".encode()).hexdigest()[:16],
            "collected_at": datetime.now().isoformat(), "truncated": False,
        }
    return await asyncio.to_thread(
        _observed_evidence, _telemetry_source(), DiagnosticToolType.QUERY_TEMPO,
        {"trace_id": trace_id, "service_name": service_name or "unknown", "time_range_minutes": time_range_minutes}, query,
    )


async def collect_k8s_pod_status(
    namespace: str = "demo-shop",
    label_selector: Optional[str] = None,
) -> dict:
    """
    [Activity] 查询 Kubernetes Pod 状态（只读）。

    权限: diagnostic-sa，仅 get/list/watch
    禁止: Secrets、exec、写操作
    """
    _require_real_full_adapter("Kubernetes")
    await asyncio.sleep(0.15)
    return {
        "evidence_id": str(uuid4()),
        "source": "kubernetes",
        "query": f"kubectl get pods -n {namespace}" + (f" -l {label_selector}" if label_selector else ""),
        "summary": f"Pod 状态查询结果（namespace={namespace}）",
        "raw_hash": hashlib.sha256(f"{namespace}{label_selector}".encode()).hexdigest()[:16],
        "collected_at": datetime.now().isoformat(),
        "truncated": False,
    }


# ---------------------------------------------------------------------------
# LLM Activities
# ---------------------------------------------------------------------------


async def call_llm_structured(
    system_prompt: str,
    user_prompt: str,
    output_schema: dict,
    model: str = "",
    base_url: str = "",
    api_key: str = "",
    timeout_seconds: int = 60,
    max_output_tokens: int = 2000,
) -> dict:
    """
    [Activity] 调用 LLM 并获取结构化输出。

    超时: 60s, 重试: 最多 2 次（429/5xx）
    温度固定为 0.3，确保一致性。

    安全: API key 仅在此 Activity 中使用，不传递给 Workflow。
    """
    from sentinel_x_incident_worker.llm_client import LLMClient

    client_options = {
        "base_url": base_url or "http://localhost:11434/v1",
        "api_key": api_key or "ollama",
        "model": model or "qwen2.5:7b",
        "timeout_seconds": timeout_seconds,
        "max_output_tokens": max_output_tokens,
    }
    client = LLMClient(**client_options)

    result = await client.structured_output(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        output_schema=output_schema,
    )

    if not result.success:
        logger.error(f"LLM 调用失败: {result.error}")
        # 返回降级结果
        return {
            "id": str(uuid4()),
            "statement": "LLM 调用失败，使用降级假设",
            "confidence": 0.3,
            "root_cause_category": "unknown",
            "affected_service": "unknown",
            "tokens_used": result.tokens_total,
            "model": result.model,
            "error": result.error,
        }

    parsed_output = result.parsed_output or {}
    return {
        "id": str(uuid4()),
        "statement": parsed_output.get("statement", ""),
        "confidence": parsed_output.get("confidence", 0.5),
        "root_cause_category": parsed_output.get("root_cause_category", "unknown"),
        "affected_service": parsed_output.get("affected_service", ""),
        "supporting_evidence_refs": parsed_output.get("supporting_evidence_refs", []),
        "opposing_evidence_refs": parsed_output.get("opposing_evidence_refs", []),
        "suggested_next_steps": parsed_output.get("suggested_next_steps", []),
        "needs_human_escalation": parsed_output.get("needs_human_escalation", False),
        "tokens_used": result.tokens_total,
        "model": result.model,
    }


# ---------------------------------------------------------------------------
# Action Gateway Activities
# ---------------------------------------------------------------------------


async def submit_action_to_gateway(
    action_gateway_url: str,
    runbook_ref: str,
    target: str,
    parameters: dict,
    idempotency_key: str,
    approval_token: str,
    plan_hash: str = "",
    audience: str = "sentinel-action-gateway",
    timeout_seconds: int = 120,
    approval_id: str = "",
    incident_id: str = "",
    approval_expires_at: str = "",
    target_identity: dict | None = None,
    target_resource_version: str = "unknown",
) -> dict:
    """
    [Activity] 向 Action Gateway 提交已审批的动作。

    超时: 120s, 重试: 0 次（非幂等动作不自动重试）
    重试由 Workflow 层协调（检查幂等键状态后决定）。

    安全：
    - 使用短时 ServiceAccount token 认证
    - audience 固定，防止 token 被重放到其他服务
    - approval_token 绑定到本次审批
    """
    if os.getenv("SENTINEL_PROFILE", "light") != "full":
        await asyncio.sleep(0.5)
        return {
            "execution_id": str(uuid4()), "status": "succeeded",
            "before_state": f"{target}: 3 replicas, 2 unhealthy",
            "after_state": f"{target}: 3 replicas, 3 healthy",
            "output": f"Successfully executed {runbook_ref} on {target}",
            "idempotency_key": idempotency_key,
        }
    secret = os.getenv("SENTINEL_SERVICE_IDENTITY_SECRET", "")
    required = {"approval_id": approval_id, "incident_id": incident_id, "approval_expires_at": approval_expires_at, "plan_hash": plan_hash}
    if not secret or any(not value for value in required.values()) or not target_identity:
        raise RuntimeError("full profile Action Gateway adapter 缺少服务身份、审批或目标身份字段")
    timestamp = str(int(datetime.now().timestamp()))
    signature = "sha256=" + hmac.new(
        secret.encode("utf-8"), f"control-api:{timestamp}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    payload = {
        "runbook_ref": runbook_ref, "target": target, "parameters": parameters,
        "idempotency_key": idempotency_key, "plan_hash": plan_hash,
        "approval_id": approval_id, "approval_token": approval_token,
        "approval_expires_at": approval_expires_at, "incident_id": incident_id,
        "audience": audience, "target_identity": target_identity,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        action_gateway_url.rstrip("/") + "/api/actions", data=body,
        headers={
            "Accept": "application/json", "Content-Type": "application/json",
            "X-Sentinel-Service-Name": "control-api",
            "X-Sentinel-Service-Timestamp": timestamp,
            "X-Sentinel-Service-Signature": signature,
        }, method="POST",
    )

    def call() -> dict:
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                result = json.loads(response.read(1024 * 1024))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Action Gateway HTTP 调用失败") from exc
        if not isinstance(result, dict) or not result.get("execution_id"):
            raise RuntimeError("Action Gateway 返回缺少 execution_id")
        return result

    return await asyncio.to_thread(call)


async def check_action_status(
    action_gateway_url: str,
    execution_id: str,
    timeout_seconds: int = 30,
) -> dict:
    """
    [Activity] 查询 Action Gateway 中某个执行的当前状态。

    用于超时后的协调（reconcile）。
    """
    if os.getenv("SENTINEL_PROFILE", "light") != "full":
        await asyncio.sleep(0.1)
        return {"execution_id": execution_id, "status": "succeeded"}
    secret = os.getenv("SENTINEL_SERVICE_IDENTITY_SECRET", "")
    if not secret:
        raise RuntimeError("full profile Action Gateway adapter 缺少服务身份密钥")
    timestamp = str(int(datetime.now().timestamp()))
    signature = "sha256=" + hmac.new(
        secret.encode("utf-8"), f"control-api:{timestamp}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    request = Request(
        action_gateway_url.rstrip("/") + f"/api/actions/{execution_id}",
        headers={
            "Accept": "application/json", "X-Sentinel-Service-Name": "control-api",
            "X-Sentinel-Service-Timestamp": timestamp,
            "X-Sentinel-Service-Signature": signature,
        }, method="GET",
    )

    def call() -> dict:
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                result = json.loads(response.read(1024 * 1024))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Action Gateway 状态查询失败") from exc
        if not isinstance(result, dict) or result.get("execution_id") != execution_id:
            raise RuntimeError("Action Gateway 状态响应不匹配")
        return result

    return await asyncio.to_thread(call)


# ---------------------------------------------------------------------------
# 验证 Activities
# ---------------------------------------------------------------------------


async def verify_slo_recovery(
    service_name: str,
    baseline_window_minutes: int = 15,
    observed_window_minutes: int = 10,
    target_p99_ms: float = 200.0,
    observed_p99_samples: Optional[list[float]] = None,
    minimum_samples: int = 1,
) -> dict:
    """
    [Activity] 验证服务 SLO 恢复。

    通过比较 baseline 和 observed 窗口的指标来判断恢复。
    """
    if os.getenv("SENTINEL_PROFILE", "light") == "full":
        source = _telemetry_source()
        query = (
            f'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{service="{service_name}"}}[5m])) by (le))'
        )
        observed = await asyncio.to_thread(
            _observed_evidence,
            source,
            DiagnosticToolType.QUERY_PROMETHEUS,
            {"query": query, "time_range_minutes": observed_window_minutes},
            query,
            include_payload=True,
        )
        payload = observed.get("_payload")
        samples = _extract_prometheus_samples(payload)
        observed.pop("_payload", None)
    else:
        await asyncio.sleep(0.3)
        samples = observed_p99_samples or []
    failure_reason: str | None = None
    if not samples:
        failure_reason = "观测窗口无数据"
        observed_p99 = None
    elif len(samples) < minimum_samples:
        failure_reason = "观测样本不足"
        observed_p99 = max(samples)
    elif any(not math.isfinite(sample) or sample < 0 for sample in samples):
        failure_reason = "观测样本无效"
        observed_p99 = max(samples)
    else:
        observed_p99 = max(samples)
        if observed_p99 > target_p99_ms:
            failure_reason = "观测窗口超过 SLO 阈值"
    recovered = failure_reason is None

    return {
        "service": service_name,
        "baseline_p99_ms": target_p99_ms,
        "observed_p99_ms": observed_p99,
        "recovered": recovered,
        "verification_window_minutes": observed_window_minutes,
        "baseline_window_minutes": baseline_window_minutes,
        "sample_count": len(samples),
        "failure_reason": failure_reason,
        "verified_at": datetime.now().isoformat(),
    }


def _extract_prometheus_samples(payload: dict | None) -> list[float]:
    """解析 Prometheus vector/matrix 的数值，拒绝非数值输入。"""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    result = data.get("result")
    if not isinstance(result, list):
        return []
    samples: list[float] = []
    for item in result:
        values = item.get("value") if isinstance(item, dict) else None
        if values is None and isinstance(item, dict):
            values = item.get("values")
        if isinstance(values, list) and values and isinstance(values[0], list):
            values = [entry[1] for entry in values if isinstance(entry, list) and len(entry) > 1]
        if isinstance(values, list) and len(values) >= 2 and not isinstance(values[0], list):
            values = [values[1]]
        if isinstance(values, list):
            for value in values:
                try:
                    # http_request_duration_seconds 以秒计，契约阈值统一使用毫秒。
                    samples.append(float(value) * 1000.0)
                except (TypeError, ValueError):
                    continue
    return samples
