"""
Policy Engine — 风险分级与确定性策略校验。

负责：
1. 动作风险等级判定（R0/R1/R2/R3）
2. MVP 模式下的危险操作拦截
3. 审批 Target 白名单校验
4. 幂等键生成规则
5. Kill Switch 检查

所有函数为纯函数，不依赖外部 I/O。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RiskLevel(str, Enum):
    R0 = "R0"  # 只读，无副作用，可自动执行
    R1 = "R1"  # 单服务可逆动作，需审批
    R2 = "R2"  # 数据库/跨服务动作，MVP 禁用
    R3 = "R3"  # 任意 Shell/exec/Secrets，永久禁止


# ---------------------------------------------------------------------------
# Runbook 风险登记表
# ---------------------------------------------------------------------------

RUNBOOK_RISK_MAP: dict[str, RiskLevel] = {
    "restart_deployment@1": RiskLevel.R1,
    "scale_deployment@1": RiskLevel.R1,
    "db_rollback@1": RiskLevel.R2,
    "db_migration@1": RiskLevel.R2,
    "cross_service_restart@1": RiskLevel.R2,
    "exec_pod_command@1": RiskLevel.R3,
    "read_secrets@1": RiskLevel.R3,
    "cluster_admin@1": RiskLevel.R3,
}

# MVP 允许的 Runbook 白名单
MVP_ALLOWED_RUNBOOKS: set[str] = {
    "restart_deployment@1",
    "scale_deployment@1",
}

# R1 动作的合法目标正则模式
ALLOWED_TARGET_PATTERNS = [
    r"^(order|inventory|payment)-(api|db|worker)$",
    r"^redis-(master|replica)$",
]


@dataclass
class PolicyDecision:
    """策略校验结果。"""
    allowed: bool
    risk_level: RiskLevel
    reason: str
    requires_approval: bool = True


def classify_runbook_risk(runbook_ref: str) -> RiskLevel:
    """根据 Runbook 引用确定风险等级。"""
    return RUNBOOK_RISK_MAP.get(runbook_ref, RiskLevel.R3)


def check_mvp_policy(
    runbook_ref: str,
    target: str,
    kill_switch_active: bool = False,
) -> PolicyDecision:
    """
    MVP 策略校验。

    Args:
        runbook_ref: Runbook 引用，如 "restart_deployment@1"
        target: 目标服务名称
        kill_switch_active: Kill Switch 是否激活

    Returns:
        PolicyDecision
    """
    risk = classify_runbook_risk(runbook_ref)

    # Kill Switch
    if kill_switch_active and risk != RiskLevel.R0:
        return PolicyDecision(
            allowed=False,
            risk_level=risk,
            reason="Kill Switch 已激活，阻止所有 R1+ 动作",
            requires_approval=True,
        )

    # R3 — 永久禁止
    if risk == RiskLevel.R3:
        return PolicyDecision(
            allowed=False,
            risk_level=risk,
            reason=f"R3 动作 {runbook_ref} 永久禁止",
            requires_approval=False,
        )

    # R2 — MVP 禁用
    if risk == RiskLevel.R2:
        return PolicyDecision(
            allowed=False,
            risk_level=risk,
            reason=f"R2 动作 {runbook_ref} 在 MVP 中禁用，请升级人工处理",
            requires_approval=False,
        )

    # R1 — 需审批
    if risk == RiskLevel.R1:
        if runbook_ref not in MVP_ALLOWED_RUNBOOKS:
            return PolicyDecision(
                allowed=False,
                risk_level=risk,
                reason=f"Runbook {runbook_ref} 不在 MVP 白名单中",
                requires_approval=False,
            )

        if not _is_valid_target(target):
            return PolicyDecision(
                allowed=False,
                risk_level=risk,
                reason=f"目标 {target} 不在合法目标范围内",
                requires_approval=False,
            )

        return PolicyDecision(
            allowed=True,
            risk_level=risk,
            reason=f"R1 动作 {runbook_ref} 需要审批",
            requires_approval=True,
        )

    # R0 — 只读，直接允许
    return PolicyDecision(
        allowed=True,
        risk_level=risk,
        reason="R0 只读操作，无需审批",
        requires_approval=False,
    )


def _is_valid_target(target: str) -> bool:
    """检查目标是否匹配合法的服务名称模式。"""
    import re
    for pattern in ALLOWED_TARGET_PATTERNS:
        if re.match(pattern, target):
            return True
    return False


def validate_idempotency_key(key: str, max_age_hours: int = 24) -> bool:
    """
    验证幂等键格式。

    格式: {runbook_ref}:{target}:{plan_hash}:{nonce}
    """
    parts = key.split(":")
    if len(parts) < 4:
        return False
    if not all(parts):
        return False
    return True


def generate_idempotency_key(
    runbook_ref: str,
    target: str,
    plan_hash: str,
    nonce: str,
) -> str:
    """生成唯一幂等键。"""
    return f"{runbook_ref}:{target}:{plan_hash}:{nonce}"
