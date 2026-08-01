"""
领域服务 — 不依赖外部 I/O 的纯业务逻辑。

所有函数都是纯函数或仅依赖领域对象的函数。
禁止在此模块中进行数据库、网络或文件系统调用。
"""

import hashlib
import json
from datetime import datetime, timedelta
from uuid import UUID

from sentinel_x_domain.state_machine import IncidentStatus


def compute_evidence_hash(source: str, query: str, raw_result: str) -> str:
    """计算证据的去重哈希。"""
    content = f"{source}:{query}:{raw_result}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_plan_hash(
    runbook_ref: str,
    target: str,
    parameters: dict,
    incident_id: UUID,
) -> str:
    """
    计算恢复计划的规范哈希。

    审批绑定此哈希值，执行前验证哈希未变。
    防止审批后计划被篡改。
    """
    canonical = json.dumps(
        {
            "runbook_ref": runbook_ref,
            "target": target,
            "parameters": parameters,
            "incident_id": str(incident_id),
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def is_risk_allowed(risk_level: str, mvp_mode: bool = True) -> bool:
    """
    判断风险等级是否允许执行。

    MVP 策略：
    - R0：允许（只读操作）
    - R1：允许（需审批的可逆操作）
    - R2：MVP 禁用
    - R3：永久禁止
    """
    if mvp_mode:
        return risk_level in ("R0", "R1")
    return risk_level in ("R0", "R1", "R2")


def validate_approval_not_expired(
    created_at: datetime,
    ttl_minutes: int = 30,
) -> bool:
    """验证审批是否在有效期内。"""
    expires_at = created_at + timedelta(minutes=ttl_minutes)
    return datetime.now() < expires_at


def is_budget_exhausted(
    seconds_consumed: int,
    llm_calls: int,
    tool_calls: int,
    max_seconds: int = 480,
    max_llm_calls: int = 8,
    max_tool_calls: int = 20,
) -> tuple[bool, str]:
    """
    检查调查预算是否耗尽。

    Returns:
        (is_exhausted, reason)
    """
    if seconds_consumed >= max_seconds:
        return True, f"时间预算耗尽 ({seconds_consumed}s >= {max_seconds}s)"
    if llm_calls >= max_llm_calls:
        return True, f"LLM 调用次数耗尽 ({llm_calls} >= {max_llm_calls})"
    if tool_calls >= max_tool_calls:
        return True, f"工具调用次数耗尽 ({tool_calls} >= {max_tool_calls})"
    return False, ""


def normalize_confidence(value: float) -> float:
    """
    归一化置信度到 0.0-1.0 范围。

    防御模型输出百分比格式（如 85 而非 0.85）。
    """
    if value > 1.0:
        return value / 100.0
    return max(0.0, min(1.0, value))


def determine_escalation_reason(
    status: IncidentStatus,
    budget_exhausted: bool,
    evidence_count: int,
) -> str:
    """根据当前状态和上下文确定升级原因。"""
    if budget_exhausted:
        return "调查预算耗尽，需人工介入"
    if evidence_count == 0:
        return "无有效证据收集，需人工调查"
    if status == IncidentStatus.DIAGNOSING:
        return "证据不足以确定根因，升级人工处理"
    if status == IncidentStatus.PLAN_PROPOSED:
        return "恢复计划被策略拒绝，升级人工处理"
    if status == IncidentStatus.AWAITING_APPROVAL:
        return "审批被拒绝，升级人工处理"
    return "系统升级人工处理"
