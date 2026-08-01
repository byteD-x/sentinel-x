"""
事故状态机 — 确定性状态转换引擎。

这是 Sentinel-X 的核心不变量。所有状态转换必须通过此引擎，
不允许在各模块自造同义状态。

规范状态流转：
  DETECTED → TRIAGING → DIAGNOSING → PLAN_PROPOSED
  → AWAITING_APPROVAL → EXECUTING → VERIFYING
  → RESOLVED | ESCALATED | FAILED

特殊路径：
  - DIAGNOSING → VERIFYING：自动恢复场景（Kubernetes auto-recovery）
  - DIAGNOSING → ESCALATED：证据不足或预算耗尽
  - PLAN_PROPOSED → ESCALATED：计划被策略拒绝
  - AWAITING_APPROVAL → ESCALATED：审批被拒绝
  - EXECUTING → FAILED：动作执行失败
  - VERIFYING → FAILED：恢复验证未通过
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class IncidentStatus(str, Enum):
    DETECTED = "DETECTED"
    TRIAGING = "TRIAGING"
    DIAGNOSING = "DIAGNOSING"
    PLAN_PROPOSED = "PLAN_PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


# 合法状态转换表 — 唯一事实来源
VALID_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.DETECTED: {IncidentStatus.TRIAGING},
    IncidentStatus.TRIAGING: {IncidentStatus.DIAGNOSING},
    IncidentStatus.DIAGNOSING: {
        IncidentStatus.PLAN_PROPOSED,
        IncidentStatus.VERIFYING,    # 自动恢复
        IncidentStatus.ESCALATED,    # 证据不足/预算耗尽
    },
    IncidentStatus.PLAN_PROPOSED: {
        IncidentStatus.AWAITING_APPROVAL,
        IncidentStatus.ESCALATED,    # 策略拒绝
    },
    IncidentStatus.AWAITING_APPROVAL: {
        IncidentStatus.EXECUTING,
        IncidentStatus.ESCALATED,    # 审批拒绝
    },
    IncidentStatus.EXECUTING: {
        IncidentStatus.VERIFYING,
        IncidentStatus.FAILED,       # 执行失败
    },
    IncidentStatus.VERIFYING: {
        IncidentStatus.RESOLVED,
        IncidentStatus.FAILED,       # 恢复失败
    },
    IncidentStatus.RESOLVED: set(),   # 终态
    IncidentStatus.ESCALATED: set(),  # 终态
    IncidentStatus.FAILED: set(),     # 终态
}

# 终态集合
TERMINAL_STATUSES: set[IncidentStatus] = {
    IncidentStatus.RESOLVED,
    IncidentStatus.ESCALATED,
    IncidentStatus.FAILED,
}


class InvalidTransitionError(ValueError):
    """非法状态转换异常。"""
    def __init__(
        self,
        current: IncidentStatus,
        target: IncidentStatus,
        message: str = "",
    ):
        if not message:
            valid = [s.value for s in VALID_TRANSITIONS.get(current, set())]
            message = (
                f"非法状态转换: {current.value} -> {target.value}。"
                f"当前状态允许的转换: {valid}"
            )
        super().__init__(message)


@dataclass
class IncidentState:
    """
    事故状态聚合 — 包含事故运行时的全部可变状态。

    在 Temporal 中，此对象由 Workflow 维护。
    PostgreSQL 保存其投影用于查询。
    """
    id: UUID = field(default_factory=uuid4)
    status: IncidentStatus = IncidentStatus.DETECTED
    alert_fingerprint: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None
    version: int = 1
    history: list[str] = field(default_factory=list)  # 状态变更日志


class IncidentStateMachine:
    """
    事故状态机 — 保证所有状态转换符合契约。

    用法：
        sm = IncidentStateMachine(state)
        sm.transition(IncidentStatus.TRIAGING)  # 合法 -> 成功
        sm.transition(IncidentStatus.EXECUTING)  # 非法 -> InvalidTransitionError
    """

    def __init__(self, state: IncidentState):
        self._state = state

    @property
    def status(self) -> IncidentStatus:
        return self._state.status

    @property
    def is_terminal(self) -> bool:
        return self._state.status in TERMINAL_STATUSES

    @property
    def is_active(self) -> bool:
        return not self.is_terminal

    def transition(self, to: IncidentStatus, reason: str = "") -> None:
        """
        执行状态转换。

        Args:
            to: 目标状态
            reason: 转换原因（记录在历史日志中）

        Raises:
            InvalidTransitionError: 如果转换不合法
        """
        if self.is_terminal:
            raise InvalidTransitionError(
                self._state.status,
                to,
                message=f"事故已处于终态 {self._state.status.value}，不可再转换",
            )

        valid_targets = VALID_TRANSITIONS.get(self._state.status, set())
        if to not in valid_targets:
            raise InvalidTransitionError(self._state.status, to)

        old_status = self._state.status
        self._state.status = to
        self._state.updated_at = datetime.now()
        self._state.version += 1

        log_entry = f"{old_status.value} -> {to.value}"
        if reason:
            log_entry += f" ({reason})"
        self._state.history.append(log_entry)

        if to in TERMINAL_STATUSES:
            self._state.resolved_at = datetime.now()

    def can_transition_to(self, target: IncidentStatus) -> bool:
        """检查是否可以转换到目标状态。"""
        if self.is_terminal:
            return False
        return target in VALID_TRANSITIONS.get(self._state.status, set())

    def available_transitions(self) -> set[IncidentStatus]:
        """返回当前状态允许的目标状态集合。"""
        if self.is_terminal:
            return set()
        return VALID_TRANSITIONS.get(self._state.status, set())

    def to_dict(self) -> dict:
        """导出为可序列化的字典。"""
        return {
            "id": str(self._state.id),
            "status": self._state.status.value,
            "alert_fingerprint": self._state.alert_fingerprint,
            "created_at": self._state.created_at.isoformat(),
            "updated_at": self._state.updated_at.isoformat(),
            "resolved_at": self._state.resolved_at.isoformat() if self._state.resolved_at else None,
            "version": self._state.version,
            "history": self._state.history,
        }
