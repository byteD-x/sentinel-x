"""Action Gateway 的本地审批权威记录。

该存储是 light profile 的进程内实现；full profile 应替换为数据库只读投影。
请求体中的审批字段只能作为声明，执行前必须与这里的不可变记录一致。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any

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


class SQLiteApprovalStore:
    """SQLite 持久化审批记录，提供本地跨进程可恢复的消费边界。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(path), check_same_thread=False, isolation_level=None
        )
        self._lock = RLock()
        with self._lock:
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_records (
                    approval_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    runbook_ref TEXT NOT NULL,
                    target TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    plan_hash TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    audience TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    target_identity_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    max_executions INTEGER NOT NULL,
                    consumed_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    @staticmethod
    def _serialize(record: ApprovalRecord) -> tuple:
        return (
            record.approval_id,
            record.incident_id,
            record.runbook_ref,
            record.target,
            json.dumps(dict(record.parameters), ensure_ascii=False, sort_keys=True),
            record.plan_hash,
            record.risk_level.value,
            record.audience,
            record.expires_at.isoformat(),
            json.dumps(record.target_identity.__dict__, ensure_ascii=False, sort_keys=True),
            record.status,
            record.max_executions,
        )

    @staticmethod
    def _deserialize(row: tuple) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=row[0],
            incident_id=row[1],
            runbook_ref=row[2],
            target=row[3],
            parameters=json.loads(row[4]),
            plan_hash=row[5],
            risk_level=RiskLevel(row[6]),
            audience=row[7],
            expires_at=datetime.fromisoformat(row[8]),
            target_identity=TargetIdentity(**json.loads(row[9])),
            status=row[10],
            max_executions=row[11],
        )

    def register(self, record: ApprovalRecord) -> None:
        values = self._serialize(record)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM approval_records WHERE approval_id = ?",
                (record.approval_id,),
            ).fetchone()
            if row is not None and self._deserialize(row) != record:
                raise ValueError(f"审批记录 {record.approval_id} 不可变")
            self._connection.execute(
                """
                INSERT OR IGNORE INTO approval_records (
                    approval_id, incident_id, runbook_ref, target, parameters_json,
                    plan_hash, risk_level, audience, expires_at, target_identity_json,
                    status, max_executions
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

    def get(self, approval_id: str) -> ApprovalRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM approval_records WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return self._deserialize(row) if row else None

    def consumed_count(self, approval_id: str) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT consumed_count FROM approval_records WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def is_consumable(self, record: ApprovalRecord) -> bool:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT status, consumed_count, max_executions
                FROM approval_records WHERE approval_id = ?
                """,
                (record.approval_id,),
            ).fetchone()
        return bool(row and row[0] == "approved" and row[1] < row[2])

    def consume(self, record: ApprovalRecord) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE approval_records
                SET consumed_count = consumed_count + 1
                WHERE approval_id = ? AND status = 'approved'
                  AND consumed_count < max_executions
                """,
                (record.approval_id,),
            )
        return cursor.rowcount == 1

    def revoke(self, approval_id: str) -> None:
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE approval_records SET status = 'revoked'
                WHERE approval_id = ?
                """,
                (approval_id,),
            )
        if cursor.rowcount == 0:
            raise KeyError(approval_id)

    def clear(self) -> None:
        with self._lock:
            self._connection.execute("DELETE FROM approval_records")

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def build_approval_store(path: str | Path | None = None) -> ApprovalStore | SQLiteApprovalStore:
    """按 profile 选择存储；未配置路径时保持 light 内存行为。"""

    return SQLiteApprovalStore(path) if path else ApprovalStore()
