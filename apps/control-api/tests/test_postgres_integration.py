"""真实 PostgreSQL migration 验证入口。

默认不自动连接开发者数据库；设置 ``SENTINEL_POSTGRES_ADMIN_URL`` 后运行本文件，
测试会调用临时数据库脚本并在 finally 中删除数据库。CI 未提供该变量时明确跳过。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

import sentinel_x_control_api.app as control_app
from sentinel_x_control_api.app import AlertSource, IncidentCreate, InMemoryStore, PostgresStore
from sentinel_x_control_api.postgres import apply_migrations
from sentinel_x_control_api.postgres_dispatcher import PostgresOutboxDispatcher
from sentinel_x_control_api.postgres_idempotency import PostgresIdempotencyStore
from sentinel_x_control_api.postgres_repository import PostgresIncidentRepository
from sentinel_x_control_api.postgres_replay import PostgresReplayStore
from sentinel_x_domain.services import compute_plan_hash


@pytest.mark.integration
def test_real_postgres_migration_round_trip(tmp_path: Path):
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    output = tmp_path / "postgres-migration.json"
    result = subprocess.run(
        [sys.executable, "scripts/verify_postgres_migrations.py", "--admin-url", admin_url, "--output", str(output)],
        text=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[3],
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"passed": true' in output.read_text(encoding="utf-8")


@pytest.mark.integration
def test_real_repository_and_outbox_dispatcher():
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    database = f"sentinel_x_repo_{uuid4().hex[:10]}"
    admin = psycopg.connect(admin_url, autocommit=True)
    try:
        admin.execute(f'CREATE DATABASE "{database}"')
        database_url = admin_url.rsplit("/", 1)[0] + f"/{database}"
        apply_migrations(
            database_url,
            migrations_dir=Path(__file__).resolve().parents[3] / "migrations",
            connect=lambda *args, **kwargs: psycopg.connect(database_url, **kwargs),
        )
        repository = PostgresIncidentRepository(lambda: psycopg.connect(database_url))
        first = repository.create_incident(
            fingerprint="integration-fingerprint",
            severity="warning",
            service="inventory-api",
            workflow_id="incident/integration-1",
        )
        duplicate = repository.create_incident(
            fingerprint="integration-fingerprint",
            severity="warning",
            service="inventory-api",
            workflow_id="incident/integration-duplicate",
        )
        assert duplicate.id == first.id
        event = repository.append_event(
            incident_id=first.id,
            event_type="evidence.collected",
            actor_type="SYSTEM",
            payload={"source": "integration"},
            workflow_event_id="integration-event-2",
        )
        delivered = []
        dispatcher = PostgresOutboxDispatcher(
            lambda: psycopg.connect(database_url), delivered.append
        )
        assert dispatcher.dispatch_once() == 2
        assert {item.event_type for item in delivered} == {
            "incident.created",
            "evidence.collected",
        }
        assert event.sequence == 2
        assert dispatcher.dispatch_once() == 0
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()


@pytest.mark.integration
def test_postgres_active_fingerprint_claim_is_concurrent_safe():
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    database = f"sentinel_x_concurrent_{uuid4().hex[:10]}"
    admin = psycopg.connect(admin_url, autocommit=True)
    try:
        admin.execute(f'CREATE DATABASE "{database}"')
        database_url = admin_url.rsplit("/", 1)[0] + f"/{database}"
        apply_migrations(
            database_url,
            migrations_dir=Path(__file__).resolve().parents[3] / "migrations",
            connect=lambda *args, **kwargs: psycopg.connect(database_url, **kwargs),
        )
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """
                CREATE FUNCTION test_delay_incident_insert() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    PERFORM pg_sleep(0.2);
                    RETURN NEW;
                END;
                $$;
                CREATE TRIGGER test_delay_incident_insert
                BEFORE INSERT ON incidents FOR EACH ROW
                EXECUTE FUNCTION test_delay_incident_insert();
                """
            )

        def create() -> object:
            return PostgresIncidentRepository(
                lambda: psycopg.connect(database_url)
            ).create_incident(
                fingerprint="concurrent-fingerprint",
                severity="warning",
                service="inventory-api",
                workflow_id=f"incident/concurrent-{uuid4()}",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            records = list(executor.map(lambda _index: create(), range(2)))
        assert records[0].id == records[1].id
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()


@pytest.mark.integration
def test_postgres_idempotency_record_survives_reopen():
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    database = f"sentinel_x_idem_{uuid4().hex[:10]}"
    admin = psycopg.connect(admin_url, autocommit=True)
    try:
        admin.execute(f'CREATE DATABASE "{database}"')
        database_url = admin_url.rsplit("/", 1)[0] + f"/{database}"
        apply_migrations(
            database_url,
            migrations_dir=Path(__file__).resolve().parents[3] / "migrations",
            connect=lambda *args, **kwargs: psycopg.connect(database_url, **kwargs),
        )
        kwargs = {
            "actor_key": "Bearer session-1",
            "route": "/api/v1/approval-requests/1/decisions",
            "idempotency_key": "integration-idempotency-001",
            "body_hash": "a" * 64,
        }
        first = PostgresIdempotencyStore(lambda: psycopg.connect(database_url))
        assert first.reserve(**kwargs) is None
        first.complete(
            **kwargs,
            status_code=200,
            headers={"content-type": "application/json"},
            body=b'{"status":"approved"}',
        )
        reopened = PostgresIdempotencyStore(lambda: psycopg.connect(database_url))
        record = reopened.reserve(**kwargs)
        assert record is not None
        assert record.status_code == 200
        assert record.body == b'{"status":"approved"}'
        assert reopened.reserve(**{**kwargs, "body_hash": "b" * 64}).body_hash == "a" * 64
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()


@pytest.mark.integration
def test_postgres_alert_nonce_claim_is_atomic_and_expires():
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    database = f"sentinel_x_nonce_{uuid4().hex[:10]}"
    admin = psycopg.connect(admin_url, autocommit=True)
    try:
        admin.execute(f'CREATE DATABASE "{database}"')
        database_url = admin_url.rsplit("/", 1)[0] + f"/{database}"
        apply_migrations(
            database_url,
            migrations_dir=Path(__file__).resolve().parents[3] / "migrations",
            connect=lambda *args, **kwargs: psycopg.connect(database_url, **kwargs),
        )
        first = PostgresReplayStore(lambda: psycopg.connect(database_url))
        second = PostgresReplayStore(lambda: psycopg.connect(database_url))
        assert first.claim("nonce-integration", 300) is True
        assert second.claim("nonce-integration", 300) is False
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()


@pytest.mark.integration
def test_control_api_full_lifespan_uses_postgres_store(monkeypatch):
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    database = f"sentinel_x_api_{uuid4().hex[:10]}"
    admin = psycopg.connect(admin_url, autocommit=True)
    original_store = control_app.store
    original_workflow_store = control_app.local_workflow.store
    try:
        admin.execute(f'CREATE DATABASE "{database}"')
        database_url = admin_url.rsplit("/", 1)[0] + f"/{database}"
        monkeypatch.setenv("SENTINEL_PROFILE", "full")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_SESSION_SIGNING_KEY", "integration-session")
        monkeypatch.setenv("ACTION_GATEWAY_URL", "http://gateway")
        monkeypatch.setenv("ALERT_INGRESS_HMAC_KEY", "integration-alert")
        monkeypatch.setattr(
            control_app.local_workflow,
            "resume_all",
            lambda: pytest.fail("full profile 不应续跑 local fixture checkpoint"),
        )
        with TestClient(control_app.app) as client:
            assert isinstance(control_app.store, PostgresStore)
            rejected = client.post(
                "/api/scenarios/inventory-latched-5xx@1/run",
                headers={"X-Sentinel-Role": "scenario_operator"},
            )
            assert rejected.status_code == 503
            assert "Temporal" in rejected.json()["detail"]
            incident = control_app.store.create_incident(
                IncidentCreate(
                    alert_source=AlertSource(
                        alertmanager_id="integration",
                        fingerprint="api-full-fingerprint",
                        alert_name="InventoryHighErrorRate",
                        severity="warning",
                        description="integration",
                        started_at=datetime.now(timezone.utc),
                    )
                )
            )
            with psycopg.connect(database_url) as connection:
                count = connection.execute(
                    "SELECT count(*) FROM incidents WHERE id = %s", (incident.id,)
                ).fetchone()[0]
            assert count == 1
            deadline = time.monotonic() + 3
            published = 0
            while time.monotonic() < deadline and published == 0:
                with psycopg.connect(database_url) as connection:
                    published = connection.execute(
                        "SELECT count(*) FROM outbox_events WHERE aggregate_id = %s AND published_at IS NOT NULL",
                        (incident.id,),
                    ).fetchone()[0]
                if published == 0:
                    time.sleep(0.1)
            assert published == 1
    finally:
        control_app.store = original_store
        control_app.local_workflow.store = original_workflow_store
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()


@pytest.mark.integration
def test_postgres_store_rebuilds_incident_and_timeline_after_restart():
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    database = f"sentinel_x_rebuild_{uuid4().hex[:10]}"
    admin = psycopg.connect(admin_url, autocommit=True)
    try:
        admin.execute(f'CREATE DATABASE "{database}"')
        database_url = admin_url.rsplit("/", 1)[0] + f"/{database}"
        apply_migrations(
            database_url,
            migrations_dir=Path(__file__).resolve().parents[3] / "migrations",
            connect=lambda *args, **kwargs: psycopg.connect(database_url, **kwargs),
        )
        repository = PostgresIncidentRepository(lambda: psycopg.connect(database_url))
        record = repository.create_incident(
            fingerprint="restart-fingerprint",
            severity="critical",
            service="payment-api",
            workflow_id="incident/restart-1",
        )
        repository.append_event(
            incident_id=record.id,
            event_type="evidence.collected",
            actor_type="INVESTIGATOR",
            payload={"source": "postgres"},
            workflow_event_id="restart-event-2",
        )
        restored = control_app.PostgresStore(
            PostgresIncidentRepository(lambda: psycopg.connect(database_url))
        )
        incident = restored.get_incident(str(record.id))
        assert incident is not None
        assert incident.status.value == "DETECTED"
        assert incident.severity.value == "critical"
        assert [event.sequence for event in incident.timeline] == [1, 2]
        assert incident.timeline[1].event_type == "evidence.collected"
        assert incident.timeline[1].payload == {"source": "postgres"}
        restored.set_status(incident, control_app.IncidentStatus.TRIAGING, "restart test")
        restarted = control_app.PostgresStore(
            PostgresIncidentRepository(lambda: psycopg.connect(database_url))
        )
        recovered = restarted.get_incident(str(record.id))
        assert recovered is not None
        assert recovered.status == control_app.IncidentStatus.TRIAGING
        assert [event.sequence for event in recovered.timeline] == [1, 2, 3]
        assert recovered.timeline[-1].event_type == "incident.status_changed"

        repository.append_event(
            incident_id=record.id,
            event_type="hypothesis.generated",
            actor_type="INVESTIGATOR",
            payload={"source": "external-connection"},
            workflow_event_id="restart-event-4",
        )
        events = restored.get_timeline(str(record.id), after_sequence=3)
        assert len(events) == 1
        assert events[0].event_type == "hypothesis.generated"
        assert events[0].payload == {"source": "external-connection"}

        repository.append_event(
            incident_id=record.id,
            event_type="recovery.verified",
            actor_type="WORKFLOW",
            payload={
                "result": "passed", "window_seconds": 60,
                "recovery_actor": "ACTION_GATEWAY",
            },
            workflow_event_id="restart-verification-5",
        )
        with psycopg.connect(database_url) as connection:
            verification = connection.execute(
                "SELECT passed, recovery_actor, observed_window FROM verification_results WHERE incident_id = %s",
                (str(record.id),),
            ).fetchone()
        assert verification is not None
        assert verification[0] is True
        assert verification[1] == "ACTION_GATEWAY"
        assert verification[2]["window_seconds"] == 60
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()


@pytest.mark.integration
def test_postgres_workflow_checkpoint_survives_restart():
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    database = f"sentinel_x_checkpoint_{uuid4().hex[:10]}"
    admin = psycopg.connect(admin_url, autocommit=True)
    try:
        admin.execute(f'CREATE DATABASE "{database}"')
        database_url = admin_url.rsplit("/", 1)[0] + f"/{database}"
        apply_migrations(
            database_url,
            migrations_dir=Path(__file__).resolve().parents[3] / "migrations",
            connect=lambda *args, **kwargs: psycopg.connect(database_url, **kwargs),
        )
        repository = PostgresIncidentRepository(lambda: psycopg.connect(database_url))
        incident = repository.create_incident(
            fingerprint="checkpoint-fingerprint",
            severity="warning",
            service="inventory-api",
            workflow_id="incident/checkpoint-1",
        )
        checkpoint = repository.create_workflow_checkpoint(
            incident_id=incident.id, scenario_id="inventory-latched-5xx@1", phase="awaiting_approval"
        )
        assert checkpoint["completed"] is False
        repository.update_workflow_checkpoint(
            incident.id, phase="executing", action_execution_id="exec-checkpoint-1"
        )
        reopened = PostgresIncidentRepository(lambda: psycopg.connect(database_url))
        restored = reopened.get_workflow_checkpoint(incident.id)
        assert restored is not None
        assert restored["phase"] == "executing"
        assert restored["action_execution_id"] == "exec-checkpoint-1"
        assert [item["incident_id"] for item in reopened.list_resumable_workflow_checkpoints()] == [str(incident.id)]
        reopened.update_workflow_checkpoint(incident.id, phase="terminal", completed=True)
        assert reopened.list_resumable_workflow_checkpoints() == []
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()


@pytest.mark.integration
def test_postgres_approval_is_immutable_and_single_decision():
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    database = f"sentinel_x_approval_{uuid4().hex[:10]}"
    admin = psycopg.connect(admin_url, autocommit=True)
    try:
        admin.execute(f'CREATE DATABASE "{database}"')
        database_url = admin_url.rsplit("/", 1)[0] + f"/{database}"
        apply_migrations(
            database_url,
            migrations_dir=Path(__file__).resolve().parents[3] / "migrations",
            connect=lambda *args, **kwargs: psycopg.connect(database_url, **kwargs),
        )
        repository = PostgresIncidentRepository(lambda: psycopg.connect(database_url))
        incident = repository.create_incident(
            fingerprint="approval-fingerprint",
            severity="warning",
            service="payment-api",
            workflow_id="incident/approval-1",
        )
        expires_at = datetime.now(timezone.utc).replace(microsecond=0)
        expires_at = expires_at.replace(year=expires_at.year + 1)
        approval = repository.create_approval(
            incident_id=incident.id,
            plan_hash="approval-plan-hash-1",
            client_plan_id="plan-approval-1",
            runbook_ref="restart_deployment@1",
            target="payment-api",
            parameters={"reason": "integration"},
            risk_level="R1",
            policy_version="mvp@1",
            target_namespace="demo-shop",
            target_kind="Deployment",
            target_name="payment-api",
            target_uid="fake-payment-api",
            target_observed_generation=1,
            target_resource_version="rv-1",
            rationale="integration approval",
            hypothesis_id="hyp-approval-1",
            expires_at=expires_at,
        )
        assert approval["plan_id"] == "plan-approval-1"
        assert approval["runbook_ref"] == "restart_deployment@1"
        assert approval["target"] == "payment-api"
        assert approval["parameters"] == {"reason": "integration"}
        duplicate = repository.create_approval(
            incident_id=incident.id,
            plan_hash="approval-plan-hash-1",
            client_plan_id="plan-approval-1",
            runbook_ref="restart_deployment@1",
            target="payment-api",
            parameters={"reason": "integration"},
            risk_level="R1",
            policy_version="mvp@1",
            target_namespace="demo-shop",
            target_kind="Deployment",
            target_name="payment-api",
            target_uid="fake-payment-api",
            target_observed_generation=1,
            target_resource_version="rv-1",
            rationale="integration approval",
            hypothesis_id="hyp-approval-1",
            expires_at=expires_at,
        )
        assert duplicate["id"] == approval["id"]
        assert repository.decide_approval(
            approval_id=UUID(approval["id"]),
            incident_id=incident.id,
            approved=True,
            approver_id="approver-1",
            reason="approved in integration",
        )["status"] == "approved"
        assert repository.decide_approval(
            approval_id=UUID(approval["id"]),
            incident_id=incident.id,
            approved=False,
            approver_id="approver-2",
            reason="replay",
        ) is None
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM approval_decisions WHERE request_id = %s",
                (approval["id"],),
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT count(*) FROM timeline_events WHERE incident_id = %s AND event_type LIKE %s",
                (str(incident.id), "approval.%"),
            ).fetchone()[0] == 2
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()


@pytest.mark.integration
def test_control_api_full_approval_is_persisted(monkeypatch):
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    database = f"sentinel_x_api_approval_{uuid4().hex[:10]}"
    admin = psycopg.connect(admin_url, autocommit=True)
    original_store = control_app.store
    original_workflow_store = control_app.local_workflow.store
    try:
        admin.execute(f'CREATE DATABASE "{database}"')
        database_url = admin_url.rsplit("/", 1)[0] + f"/{database}"
        monkeypatch.setenv("SENTINEL_PROFILE", "full")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_SESSION_SIGNING_KEY", "integration-session")
        monkeypatch.setenv("ACTION_GATEWAY_URL", "http://gateway")
        monkeypatch.setenv("ALERT_INGRESS_HMAC_KEY", "integration-alert")
        with TestClient(control_app.app) as client:
            incident = control_app.store.create_incident(
                IncidentCreate(
                    alert_source=AlertSource(
                        alertmanager_id="integration",
                        fingerprint="api-approval-fingerprint",
                        alert_name="PaymentHighErrorRate",
                        severity="warning",
                        description="integration",
                        started_at=datetime.now(timezone.utc),
                    )
                )
            )
            parameters = {"reason": "integration approval"}
            plan_hash = compute_plan_hash(
                "restart_deployment@1", "payment-api", parameters, incident.id
            )
            response = client.post(
                f"/api/incidents/{incident.id}/approvals",
                headers={"X-Sentinel-Role": "planner"},
                json={
                    "plan_id": "plan-api-approval",
                    "runbook_ref": "restart_deployment@1",
                    "target": "payment-api",
                    "parameters": parameters,
                    "risk_level": "R1",
                    "plan_hash": plan_hash,
                    "hypothesis_id": "hyp-api-approval",
                },
            )
            assert response.status_code == 201, response.text
            approval_id = response.json()["id"]
            decision_response = client.put(
                f"/api/incidents/{incident.id}/approvals/{approval_id}",
                headers={"X-Sentinel-Role": "approver"},
                json={"approved": True, "reason": "integration decision"},
            )
            assert decision_response.status_code == 200, decision_response.text
            with psycopg.connect(database_url) as connection:
                assert connection.execute(
                    "SELECT count(*) FROM approval_requests WHERE id = %s",
                    (approval_id,),
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT decision FROM approval_decisions WHERE request_id = %s",
                    (approval_id,),
                ).fetchone()[0] == "approved"
            restarted = control_app.PostgresStore(
                PostgresIncidentRepository(lambda: psycopg.connect(database_url))
            )
            restored_approvals = restarted.list_approvals(incident.id)
            assert len(restored_approvals) == 1
            assert restored_approvals[0]["id"] == approval_id
            assert restored_approvals[0]["plan_id"] == "plan-api-approval"
            assert restored_approvals[0]["runbook_ref"] == "restart_deployment@1"
            assert restored_approvals[0]["decided_by"] == "approver"
            assert restored_approvals[0]["decision_reason"] == "integration decision"
    finally:
        control_app.store = original_store
        control_app.local_workflow.store = original_workflow_store
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()
