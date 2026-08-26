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
            now = datetime.now(timezone.utc)
            cursor.execute(
                """
                INSERT INTO incidents(
                    id, workflow_id, alert_fingerprint, status, severity, service,
                    projection_version, workflow_event_id, opened_at, updated_at
                ) VALUES (%s, %s, %s, 'DETECTED', %s, %s, 1, %s, %s, %s)
                ON CONFLICT (alert_fingerprint)
                    WHERE status NOT IN ('RESOLVED', 'ESCALATED', 'FAILED')
                DO NOTHING
                RETURNING id, workflow_id, alert_fingerprint, status, severity, service,
                          opened_at, projection_version
                """,
                (incident_id, workflow_id, fingerprint, severity, service, event_id, now, now),
            )
            row = cursor.fetchone()
            if row is None:
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
                row = cursor.fetchone()
            if row is None:
                raise PostgresRepositoryError("active fingerprint 冲突后未找到事故")
            if row[0] != incident_id:
                return self._incident(row)
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

    def get_incident(self, incident_id: UUID) -> IncidentRecord | None:
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                SELECT id, workflow_id, alert_fingerprint, status, severity, service,
                       opened_at, projection_version
                FROM incidents WHERE id = %s
                """,
                (incident_id,),
            )
            row = cursor.fetchone()
            return self._incident(row) if row else None

    def list_incidents(self) -> list[IncidentRecord]:
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                SELECT id, workflow_id, alert_fingerprint, status, severity, service,
                       opened_at, projection_version
                FROM incidents ORDER BY opened_at DESC, id DESC
                """
            )
            return [self._incident(row) for row in cursor.fetchall()]

    def list_timeline(self, incident_id: UUID) -> list[TimelineRecord]:
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                SELECT id, incident_id, sequence, event_type, actor_type,
                       payload_ref, occurred_at
                FROM timeline_events
                WHERE incident_id = %s ORDER BY sequence
                """,
                (incident_id,),
            )
            records = []
            for row in cursor.fetchall():
                payload = row[5]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                records.append(TimelineRecord(
                    id=UUID(str(row[0])), incident_id=UUID(str(row[1])),
                    sequence=int(row[2]), event_type=str(row[3]),
                    actor_type=str(row[4]), payload=dict(payload or {}),
                    occurred_at=row[6],
                ))
            return records

    def get_timeline_bounds(self, incident_id: UUID) -> tuple[int, int] | None:
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                SELECT MIN(sequence), MAX(sequence)
                FROM timeline_events
                WHERE incident_id = %s
                """,
                (incident_id,),
            )
            row = cursor.fetchone()
            if row is None or row[0] is None or row[1] is None:
                return None
            return int(row[0]), int(row[1])

    @staticmethod
    def _checkpoint(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "incident_id": str(row[0]),
            "workflow_id": str(row[1]),
            "scenario_id": str(row[2]),
            "phase": str(row[3]),
            "action_execution_id": row[4],
            "completed": bool(row[5]),
            "updated_at": row[6].isoformat(),
        }

    def create_workflow_checkpoint(
        self, *, incident_id: UUID, scenario_id: str, phase: str
    ) -> dict[str, Any]:
        """在 PostgreSQL 中原子创建或读取事故唯一 workflow checkpoint。"""
        workflow_id = f"incident/{incident_id}"
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                SELECT incident_id, workflow_id, scenario_id, phase,
                       action_execution_id, completed, updated_at
                FROM workflow_checkpoints
                WHERE incident_id = %s
                FOR UPDATE
                """,
                (incident_id,),
            )
            existing = cursor.fetchone()
            if existing:
                if str(existing[2]) != scenario_id:
                    raise PostgresRepositoryError("同一事故不能绑定多个场景工作流")
                return self._checkpoint(existing)
            now = datetime.now(timezone.utc)
            cursor.execute(
                """
                INSERT INTO workflow_checkpoints(
                    incident_id, workflow_id, scenario_id, phase, updated_at
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING incident_id, workflow_id, scenario_id, phase,
                          action_execution_id, completed, updated_at
                """,
                (incident_id, workflow_id, scenario_id, phase, now),
            )
            row = cursor.fetchone()
            if row is None:
                raise PostgresRepositoryError("workflow checkpoint 写入未返回记录")
            cursor.execute(
                """
                UPDATE incidents
                SET workflow_id = %s, projection_version = projection_version + 1,
                    updated_at = %s
                WHERE id = %s
                """,
                (workflow_id, now, incident_id),
            )
            return self._checkpoint(row)

    def get_workflow_checkpoint(self, incident_id: UUID) -> dict[str, Any] | None:
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                SELECT incident_id, workflow_id, scenario_id, phase,
                       action_execution_id, completed, updated_at
                FROM workflow_checkpoints WHERE incident_id = %s
                """,
                (incident_id,),
            )
            row = cursor.fetchone()
            return self._checkpoint(row) if row else None

    def update_workflow_checkpoint(
        self,
        incident_id: UUID,
        *,
        phase: str | None = None,
        action_execution_id: str | None = None,
        completed: bool | None = None,
    ) -> dict[str, Any]:
        with self._transaction() as (_connection, cursor):
            now = datetime.now(timezone.utc)
            cursor.execute(
                """
                UPDATE workflow_checkpoints
                SET phase = COALESCE(%s, phase),
                    action_execution_id = COALESCE(%s, action_execution_id),
                    completed = COALESCE(%s, completed),
                    updated_at = %s
                WHERE incident_id = %s
                RETURNING incident_id, workflow_id, scenario_id, phase,
                          action_execution_id, completed, updated_at
                """,
                (phase, action_execution_id, completed, now, incident_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise PostgresRepositoryError("workflow checkpoint 不存在")
            return self._checkpoint(row)

    def list_resumable_workflow_checkpoints(self) -> list[dict[str, Any]]:
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                SELECT incident_id, workflow_id, scenario_id, phase,
                       action_execution_id, completed, updated_at
                FROM workflow_checkpoints
                WHERE completed = FALSE ORDER BY updated_at, incident_id
                """
            )
            return [self._checkpoint(row) for row in cursor.fetchall()]

    def transition_status(
        self,
        *,
        incident_id: UUID,
        expected_status: str,
        new_status: str,
        actor_type: str,
        payload: Mapping[str, Any],
    ) -> tuple[IncidentRecord, TimelineRecord]:
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                "SELECT status FROM incidents WHERE id = %s FOR UPDATE",
                (incident_id,),
            )
            current = cursor.fetchone()
            if current is None:
                raise PostgresRepositoryError("事故不存在")
            if str(current[0]) != expected_status:
                raise PostgresRepositoryError("事故状态版本冲突")
            now = datetime.now(timezone.utc)
            cursor.execute(
                """
                UPDATE incidents
                SET status = %s, projection_version = projection_version + 1,
                    updated_at = %s,
                    closed_at = CASE WHEN %s IN ('RESOLVED', 'ESCALATED', 'FAILED')
                                     THEN %s ELSE NULL END
                WHERE id = %s
                RETURNING id, workflow_id, alert_fingerprint, status, severity, service,
                          opened_at, projection_version
                """,
                (new_status, now, new_status, now, incident_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise PostgresRepositoryError("事故状态更新未返回记录")
            event = self._append_event_cursor(
                cursor,
                incident_id=incident_id,
                event_type="incident.status_changed",
                actor_type=actor_type,
                payload=payload,
                workflow_event_id=f"status:{incident_id}:{row[7]}",
                occurred_at=now,
                sequence=self._next_sequence(cursor, incident_id),
            )
            return self._incident(row), event

    def create_approval(
        self,
        *,
        incident_id: UUID,
        plan_hash: str,
        client_plan_id: str,
        runbook_ref: str,
        target: str,
        parameters: Mapping[str, Any],
        risk_level: str,
        policy_version: str,
        target_namespace: str,
        target_kind: str,
        target_name: str,
        target_uid: str,
        target_observed_generation: int,
        target_resource_version: str,
        rationale: str,
        hypothesis_id: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        """登记计划与审批请求；同一 pending plan_hash 返回既有请求。"""
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                SELECT id, incident_id, plan_id, plan_hash, risk_level, policy_version,
                       status, expires_at, version
                FROM approval_requests
                WHERE plan_hash = %s AND status = 'pending'
                FOR UPDATE
                """,
                (plan_hash,),
            )
            existing = cursor.fetchone()
            if existing:
                result = self._approval_dict(existing)
                cursor.execute(
                    "SELECT runbook_id, target_name, parameters, canonical_payload FROM remediation_plans WHERE id = %s",
                    (existing[2],),
                )
                plan = cursor.fetchone()
                if plan:
                    canonical = plan[3] if isinstance(plan[3], dict) else json.loads(plan[3])
                    result.update(
                        plan_id=str(canonical.get("client_plan_id", existing[2])),
                        db_plan_id=str(existing[2]),
                        runbook_ref=f"{plan[0]}@1",
                        target=str(plan[1]),
                        parameters=dict(plan[2] or {}),
                    )
                return result
            plan_id = uuid4()
            approval_id = uuid4()
            now = datetime.now(timezone.utc)
            cursor.execute(
                """
                INSERT INTO remediation_plans(
                    id, incident_id, runbook_id, runbook_version, runbook_hash,
                    risk_level, policy_version, target_namespace, target_kind,
                    target_name, target_uid, target_observed_generation,
                    target_resource_version, parameters, rationale, evidence_ids,
                    canonical_payload, plan_hash, status
                ) VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s, 'PROPOSED')
                """,
                (
                    plan_id, incident_id, runbook_ref.split("@", 1)[0],
                    client_plan_id, risk_level, policy_version, target_namespace,
                    target_kind, target_name, target_uid, target_observed_generation,
                    target_resource_version, json.dumps(dict(parameters), ensure_ascii=False),
                    rationale, json.dumps([hypothesis_id], ensure_ascii=False),
                    json.dumps({"client_plan_id": client_plan_id, "target": target}, ensure_ascii=False),
                    plan_hash,
                ),
            )
            cursor.execute(
                """
                INSERT INTO approval_requests(
                    id, incident_id, plan_id, plan_hash, risk_level, policy_version,
                    nonce_hash, status, expires_at, created_at, version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, 1)
                RETURNING id, incident_id, plan_id, plan_hash, risk_level, policy_version,
                          status, expires_at, version
                """,
                (
                    approval_id, incident_id, plan_id, plan_hash, risk_level,
                    policy_version, f"nonce:{approval_id}", expires_at, now,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise PostgresRepositoryError("审批请求写入未返回记录")
            self._append_event_cursor(
                cursor,
                incident_id=incident_id,
                event_type="approval.requested",
                actor_type="SYSTEM",
                payload={"approval_id": str(approval_id), "plan_hash": plan_hash},
                workflow_event_id=f"approval-requested:{approval_id}",
                occurred_at=now,
                sequence=self._next_sequence(cursor, incident_id),
            )
            result = self._approval_dict(row)
            result.update(
                plan_id=client_plan_id,
                db_plan_id=str(plan_id),
                runbook_ref=runbook_ref,
                target=target,
                parameters=dict(parameters),
            )
            return result

    @staticmethod
    def _approval_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": str(row[0]), "incident_id": str(row[1]), "plan_id": str(row[2]),
            "plan_hash": str(row[3]), "risk_level": str(row[4]),
            "policy_version": str(row[5]), "status": str(row[6]),
            "expires_at": row[7].isoformat(), "version": int(row[8]),
        }

    def list_approvals(self, incident_id: UUID | None = None) -> list[dict[str, Any]]:
        with self._transaction() as (_connection, cursor):
            query = """
                SELECT ar.id, ar.incident_id, ar.plan_id, ar.plan_hash,
                       ar.risk_level, ar.policy_version, ar.status, ar.expires_at,
                       ar.version, rp.runbook_id, rp.runbook_version,
                       rp.target_name, rp.parameters, rp.canonical_payload,
                       ar.created_at, ad.decided_at, ad.approver_id, ad.reason
                FROM approval_requests ar
                JOIN remediation_plans rp ON rp.id = ar.plan_id
                LEFT JOIN approval_decisions ad ON ad.request_id = ar.id
            """
            params: tuple[Any, ...] = ()
            if incident_id is not None:
                query += " WHERE ar.incident_id = %s"
                params = (incident_id,)
            query += " ORDER BY ar.created_at"
            cursor.execute(query, params)
            approvals = []
            for row in cursor.fetchall():
                result = self._approval_dict(row[:9])
                result.update(
                    runbook_ref=f"{row[9]}@{row[10]}",
                    target=str(row[11]),
                    parameters=dict(row[12] or {}),
                    created_at=row[14].isoformat() if row[14] else None,
                    decided_at=row[15].isoformat() if row[15] else None,
                    decided_by=row[16],
                    decision_reason=row[17],
                )
                canonical = row[13]
                if isinstance(canonical, str):
                    canonical = json.loads(canonical)
                if isinstance(canonical, dict) and canonical.get("client_plan_id"):
                    result["plan_id"] = str(canonical["client_plan_id"])
                    result["db_plan_id"] = str(row[2])
                approvals.append(result)
            return approvals

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
        if event_type == "recovery.verified":
            passed = payload.get("result") in {True, "passed"}
            recovery_actor = str(payload.get("recovery_actor", "UNKNOWN"))
            if recovery_actor == "local_action_gateway":
                recovery_actor = "ACTION_GATEWAY"
            if recovery_actor not in {"ACTION_GATEWAY", "SCENARIO_RUNNER", "HUMAN", "UNKNOWN"}:
                recovery_actor = "UNKNOWN"
            action_execution_id = None
            execution_ref = payload.get("execution_id")
            if execution_ref:
                try:
                    action_execution_id = UUID(str(execution_ref))
                except ValueError:
                    action_execution_id = None
            observed_window = {
                key: value for key, value in payload.items()
                if key not in {"result", "recovery_actor", "execution_id"}
            }
            cursor.execute(
                """
                INSERT INTO verification_results(
                    id, incident_id, action_execution_id, trigger_type, trigger_ref,
                    recovery_actor, slo_policy_version, metric, threshold,
                    baseline_window, observed_window, sli_results, passed, failure_reason
                ) VALUES (%s, %s, %s, 'WORKFLOW', %s, %s, 'mvp@1',
                          'http_request_p99_ms', %s::jsonb, %s::jsonb, %s::jsonb,
                          %s::jsonb, %s, %s)
                """,
                (
                    uuid4(), incident_id, action_execution_id, workflow_event_id,
                    recovery_actor, json.dumps({"p99_ms": 200}),
                    json.dumps({"minutes": 15}), json.dumps(observed_window),
                    json.dumps({"passed": passed}), passed,
                    None if passed else str(payload.get("failure_reason", "verification failed")),
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
        approval_id: UUID,
        approved: bool,
        approver_id: str,
        reason: str,
        expected_version: int | None = None,
        incident_id: UUID | None = None,
    ) -> dict[str, Any] | None:
        """以行锁 + 唯一 decision 保证审批只能成功一次。"""

        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                SELECT id, incident_id, plan_id, plan_hash, risk_level, policy_version,
                       status, expires_at, version
                FROM approval_requests
                WHERE id = %s
                FOR UPDATE
                """,
                (approval_id,),
            )
            request = cursor.fetchone()
            if request is None or request[6] != "pending":
                return None
            if incident_id is not None and UUID(str(request[1])) != incident_id:
                return None
            if expected_version is not None and int(request[8]) != expected_version:
                return None
            if request[7] <= datetime.now(timezone.utc):
                cursor.execute(
                    "UPDATE approval_requests SET status = 'expired', version = version + 1 WHERE id = %s",
                    (approval_id,),
                )
                return None
            decision = "approved" if approved else "rejected"
            cursor.execute(
                """
                INSERT INTO approval_decisions(request_id, approver_id, decision, reason, request_version)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (approval_id, approver_id, decision, reason, int(request[8])),
            )
            cursor.execute(
                "UPDATE approval_requests SET status = %s, version = version + 1 WHERE id = %s",
                (decision, approval_id),
            )
            self._append_event_cursor(
                cursor,
                incident_id=UUID(str(request[1])),
                event_type="approval.decided",
                actor_type="APPROVER",
                payload={
                    "approval_id": str(approval_id),
                    "plan_hash": str(request[3]),
                    "approved": approved,
                    "decided_by": approver_id,
                    "reason": reason,
                    "expires_at": request[7].isoformat(),
                },
                workflow_event_id=f"approval-decided:{approval_id}:{request[8]}",
                occurred_at=datetime.now(timezone.utc),
                sequence=self._next_sequence(cursor, UUID(str(request[1]))),
            )
            return {
                **self._approval_dict((request[0], request[1], request[2], request[3], request[4], request[5], decision, request[7], int(request[8]) + 1)),
                "decided_by": approver_id,
                "decision_reason": reason,
            }

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
