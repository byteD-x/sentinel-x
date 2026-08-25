"""PostgreSQL domain write repository 的最小 durable slice。

所有方法都在一个数据库事务内完成领域写入、只追加时间线和 outbox 登记。
该模块不被 light profile 导入使用；真实连接由调用方注入，便于 worker/API
在 Activity/command 边界使用，也便于没有 PostgreSQL 驱动时保持可测试。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping
from uuid import UUID, uuid4


class PostgresRepositoryError(RuntimeError):
    """领域事务无法安全完成。"""


@dataclass(frozen=True)
class IncidentRecord:
    id: UUID
    workflow_id: str
    fingerprint: str
    status: str
    severity: str
    service: str
    opened_at: datetime
    projection_version: int


@dataclass(frozen=True)
class TimelineRecord:
    id: UUID
    incident_id: UUID
    sequence: int
    event_type: str
    actor_type: str
    payload: Mapping[str, Any]
    occurred_at: datetime


class PostgresIncidentRepository:
    """Incident/Timeline/Outbox 的事务写入边界。

    ``connect`` 必须返回 psycopg 风格连接；不在这里创建全局连接，避免
    Workflow 中发生隐式网络 I/O。连接池和生命周期由应用负责。
    """

    def __init__(self, connect: Any):
        if not callable(connect):
            raise TypeError("connect 必须是可调用的连接工厂")
        self._connect = connect

    @contextmanager
    def _transaction(self) -> Iterator[tuple[Any, Any]]:
        connection = self._connect()
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    yield connection, cursor
        except PostgresRepositoryError:
            raise
        except Exception as exc:  # noqa: BLE001 - DB driver errors统一收敛
            raise PostgresRepositoryError("PostgreSQL 领域事务失败") from exc
        finally:
            connection.close()

    @staticmethod
    def _incident(row: tuple[Any, ...]) -> IncidentRecord:
        return IncidentRecord(
            id=UUID(str(row[0])),
            workflow_id=str(row[1]),
            fingerprint=str(row[2]),
            status=str(row[3]),
            severity=str(row[4]),
            service=str(row[5]),
            opened_at=row[6],
            projection_version=int(row[7]),
        )

    def create_incident(
        self,
        *,
        fingerprint: str,
        severity: str,
        service: str,
        workflow_id: str,
        incident_id: UUID | None = None,
        event_id: str | None = None,
    ) -> IncidentRecord:
        """重复 active fingerprint 返回原事故；新事故与初始事件同事务提交。"""

        incident_id = incident_id or uuid4()
        event_id = event_id or f"incident-created:{incident_id}"
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                SELECT id, workflow_id, alert_fingerprint, status, severity, service,
                       opened_at, projection_version
                FROM incidents
                WHERE alert_fingerprint = %s
                  AND status NOT IN ('RESOLVED', 'ESCALATED', 'FAILED')
                FOR UPDATE
                """,
                (fingerprint,),
            )
            existing = cursor.fetchone()
            if existing:
                return self._incident(existing)
            now = datetime.now(timezone.utc)
            cursor.execute(
                """
                INSERT INTO incidents(
                    id, workflow_id, alert_fingerprint, status, severity, service,
                    projection_version, workflow_event_id, opened_at, updated_at
                ) VALUES (%s, %s, %s, 'DETECTED', %s, %s, 1, %s, %s, %s)
                RETURNING id, workflow_id, alert_fingerprint, status, severity, service,
                          opened_at, projection_version
                """,
                (incident_id, workflow_id, fingerprint, severity, service, event_id, now, now),
            )
            row = cursor.fetchone()
            if row is None:
                raise PostgresRepositoryError("创建事故未返回记录")
            self._append_event_cursor(
                cursor,
                incident_id=incident_id,
                event_type="incident.created",
                actor_type="SYSTEM",
                payload={"fingerprint": fingerprint},
                workflow_event_id=event_id,
                occurred_at=now,
                sequence=1,
            )
            return self._incident(row)

    def append_event(
        self,
        *,
        incident_id: UUID,
        event_type: str,
        actor_type: str,
        payload: Mapping[str, Any] | None = None,
        workflow_event_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> TimelineRecord:
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                SELECT sequence FROM timeline_events
                WHERE incident_id = %s
                ORDER BY sequence DESC
                LIMIT 1
                FOR UPDATE
                """,
                (incident_id,),
            )
            row = cursor.fetchone()
            sequence = int(row[0]) + 1 if row else 1
            return self._append_event_cursor(
                cursor,
                incident_id=incident_id,
                event_type=event_type,
                actor_type=actor_type,
                payload=payload or {},
                workflow_event_id=workflow_event_id,
                occurred_at=occurred_at or datetime.now(timezone.utc),
                sequence=sequence,
            )

    def _append_event_cursor(
        self,
        cursor: Any,
        *,
        incident_id: UUID,
        event_type: str,
        actor_type: str,
        payload: Mapping[str, Any],
        workflow_event_id: str | None,
        occurred_at: datetime,
        sequence: int,
    ) -> TimelineRecord:
        event_id = uuid4()
        cursor.execute(
            """
            INSERT INTO timeline_events(
                id, incident_id, sequence, event_type, schema_version, actor_type,
                payload_ref, occurred_at, workflow_event_id
            ) VALUES (%s, %s, %s, %s, '1.0', %s, %s::jsonb, %s, %s)
            RETURNING id, incident_id, sequence, event_type, actor_type,
                      payload_ref, occurred_at
            """,
            (
                event_id,
                incident_id,
                sequence,
                event_type,
                actor_type,
                json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
                occurred_at,
                workflow_event_id,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise PostgresRepositoryError("时间线写入未返回记录")
        cursor.execute(
            """
            INSERT INTO outbox_events(
                id, aggregate_type, aggregate_id, sequence, event_type, schema_version,
                actor_type, payload, occurred_at
            ) VALUES (%s, 'incident', %s, %s, %s, '1.0', %s, %s::jsonb, %s)
            """,
            (
                event_id,
                incident_id,
                sequence,
                event_type,
                actor_type,
                json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
                occurred_at,
            ),
        )
        return TimelineRecord(
            id=UUID(str(row[0])),
            incident_id=UUID(str(row[1])),
            sequence=int(row[2]),
            event_type=str(row[3]),
            actor_type=str(row[4]),
            payload=dict(row[5]),
            occurred_at=row[6],
        )

    def decide_approval(
        self,
        *,
        request_id: UUID,
        approved: bool,
        approver_id: str,
        reason: str,
        expected_version: int,
    ) -> bool:
        """以行锁 + 唯一 decision 保证审批只能成功一次。"""

        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                SELECT incident_id, status, expires_at, version
                FROM approval_requests
                WHERE id = %s
                FOR UPDATE
                """,
                (request_id,),
            )
            request = cursor.fetchone()
            if request is None or request[1] != "pending" or int(request[3]) != expected_version:
                return False
            if request[2] <= datetime.now(timezone.utc):
                cursor.execute(
                    "UPDATE approval_requests SET status = 'expired', version = version + 1 WHERE id = %s",
                    (request_id,),
                )
                return False
            decision = "approved" if approved else "rejected"
            cursor.execute(
                """
                INSERT INTO approval_decisions(request_id, approver_id, decision, reason, request_version)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (request_id, approver_id, decision, reason, expected_version),
            )
            cursor.execute(
                "UPDATE approval_requests SET status = %s, version = version + 1 WHERE id = %s",
                (decision, request_id),
            )
            self._append_event_cursor(
                cursor,
                incident_id=UUID(str(request[0])),
                event_type="approval.decided",
                actor_type="APPROVER",
                payload={"request_id": str(request_id), "approved": approved, "reason": reason},
                workflow_event_id=f"approval-decided:{request_id}:{expected_version}",
                occurred_at=datetime.now(timezone.utc),
                sequence=self._next_sequence(cursor, UUID(str(request[0]))),
            )
            return True

    @staticmethod
    def _next_sequence(cursor: Any, incident_id: UUID) -> int:
        cursor.execute(
            """
            SELECT sequence FROM timeline_events
            WHERE incident_id = %s
            ORDER BY sequence DESC
            LIMIT 1
            FOR UPDATE
            """,
            (incident_id,),
        )
        row = cursor.fetchone()
        return int(row[0]) + 1 if row else 1
