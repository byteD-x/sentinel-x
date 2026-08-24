"""Action Gateway 的本地审批权威记录。

该存储是 light profile 的进程内实现；full profile 应替换为数据库只读投影。
请求体中的审批字段只能作为声明，执行前必须与这里的不可变记录一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from types import MappingProxyType
from typing import Any, Mapping

from sentinel_x_contracts import RiskLevel


@dataclass(frozen=True)
class TargetIdentity:
    namespace: str
    kind: str
    name: str
    uid: str
    generation: int


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    incident_id: str
    runbook_ref: str
    target: str
    parameters: Mapping[str, Any]
    plan_hash: str
    risk_level: RiskLevel
    audience: str
    expires_at: datetime
    target_identity: TargetIdentity
    status: str = "approved"
    max_executions: int = 1

    def __post_init__(self) -> None:
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("审批过期时间必须包含时区")
        if self.max_executions < 1:
            raise ValueError("审批最大消费次数必须为正数")
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )


class ApprovalStore:
    """保存不可变审批记录及其消费次数。"""

    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}
        self._consumed: dict[str, int] = {}
        self._lock = RLock()

    def register(self, record: ApprovalRecord) -> None:
        with self._lock:
            existing = self._records.get(record.approval_id)
            if existing is not None and existing != record:
                raise ValueError(f"审批记录 {record.approval_id} 不可变")
            self._records[record.approval_id] = record

    def get(self, approval_id: str) -> ApprovalRecord | None:
        with self._lock:
            return self._records.get(approval_id)

    def consumed_count(self, approval_id: str) -> int:
        with self._lock:
            return self._consumed.get(approval_id, 0)

    def is_consumable(self, record: ApprovalRecord) -> bool:
        with self._lock:
            return (
                record.status == "approved"
                and self._consumed.get(record.approval_id, 0) < record.max_executions
            )

    def consume(self, record: ApprovalRecord) -> bool:
        with self._lock:
            if record.status != "approved":
                return False
            count = self._consumed.get(record.approval_id, 0)
            if count >= record.max_executions:
                return False
            self._consumed[record.approval_id] = count + 1
            return True

    def revoke(self, approval_id: str) -> None:
        with self._lock:
            record = self._records.get(approval_id)
            if record is None:
                raise KeyError(approval_id)
            revoked = ApprovalRecord(
                **{
                    **record.__dict__,
                    "status": "revoked",
                }
            )
            self._records[approval_id] = revoked

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._consumed.clear()
