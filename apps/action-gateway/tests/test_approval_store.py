from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sentinel_x_action_gateway.approval_store import (
    ApprovalRecord,
    ApprovalStore,
    PostgresApprovalStore,
    SQLiteApprovalStore,
    TargetIdentity,
    build_approval_store,
)
from sentinel_x_contracts import RiskLevel
from sentinel_x_domain.services import compute_plan_hash


@pytest.mark.integration
def test_postgres_approval_store_reads_authoritative_request_and_consumes_once():
    admin_url = os.getenv("SENTINEL_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("未设置 SENTINEL_POSTGRES_ADMIN_URL")
    psycopg = pytest.importorskip("psycopg")
    from sentinel_x_control_api.postgres import apply_migrations
    from sentinel_x_control_api.postgres_repository import PostgresIncidentRepository

    database = f"sentinel_x_gateway_{uuid4().hex[:10]}"
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
            fingerprint="gateway-approval-fingerprint",
            severity="warning",
            service="payment-api",
            workflow_id="incident/gateway-approval-1",
        )
        approval = repository.create_approval(
            incident_id=incident.id,
            plan_hash="gateway-plan-hash-1",
            client_plan_id="plan-gateway-1",
            runbook_ref="restart_deployment@1",
            target="payment-api",
            parameters={"reason": "gateway integration"},
            risk_level="R1",
            policy_version="mvp@1",
            target_namespace="demo-shop",
            target_kind="Deployment",
            target_name="payment-api",
            target_uid="fake-payment-api",
            target_observed_generation=1,
            target_resource_version="rv-1",
            rationale="gateway integration",
            hypothesis_id="hyp-gateway-1",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        repository.decide_approval(
            approval_id=UUID(approval["id"]),
            incident_id=incident.id,
            approved=True,
            approver_id="approver-gateway",
            reason="approved",
        )
        store = PostgresApprovalStore(lambda: psycopg.connect(database_url))
        record = store.get(approval["id"])
        assert record is not None
        assert record.target_identity == TargetIdentity(
            namespace="demo-shop", kind="Deployment", name="payment-api",
            uid="fake-payment-api", generation=1,
        )
        assert store.is_consumable(record) is True
        assert store.consume(record) is True
        assert store.consume(record) is False
        restarted = PostgresApprovalStore(lambda: psycopg.connect(database_url))
        assert restarted.is_consumable(record) is False
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()


def test_approval_record_is_immutable_for_same_id():
    store = ApprovalStore()
    target = TargetIdentity(
        namespace="demo-shop",
        kind="Deployment",
        name="payment-api",
        uid="uid-payment-001",
        generation=7,
    )
    record = ApprovalRecord(
        approval_id="approval-001",
        incident_id="incident-001",
        runbook_ref="restart_deployment@1",
        target="payment-api",
        parameters={"reason": "test"},
        plan_hash=compute_plan_hash(
            "restart_deployment@1", "payment-api", {"reason": "test"}, "incident-001"
        ),
        risk_level=RiskLevel.R1,
        audience="sentinel-action-gateway",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        target_identity=target,
    )

    store.register(record)

    with pytest.raises(ValueError, match="不可变"):
        store.register(
            ApprovalRecord(
                **{
                    **record.__dict__,
                    "target": "inventory-api",
                }
            )
        )


def _record(expires_at: datetime | None = None) -> ApprovalRecord:
    target = TargetIdentity(
        namespace="demo-shop",
        kind="Deployment",
        name="payment-api",
        uid="uid-payment-001",
        generation=7,
    )
    parameters = {"reason": "test"}
    return ApprovalRecord(
        approval_id="approval-persisted",
        incident_id="incident-001",
        runbook_ref="restart_deployment@1",
        target="payment-api",
        parameters=parameters,
        plan_hash=compute_plan_hash(
            "restart_deployment@1", "payment-api", parameters, "incident-001"
        ),
        risk_level=RiskLevel.R1,
        audience="sentinel-action-gateway",
        expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=5),
        target_identity=target,
    )


def test_sqlite_store_survives_reopen_and_consumes_once(tmp_path):
    path = tmp_path / "approvals.sqlite3"
    record = _record()

    first = SQLiteApprovalStore(path)
    first.register(record)
    assert first.is_consumable(record)
    first.close()

    second = SQLiteApprovalStore(path)
    assert second.get(record.approval_id) == record
    assert second.consumed_count(record.approval_id) == 0
    assert second.consume(record) is True
    assert second.consume(record) is False
    assert second.consumed_count(record.approval_id) == 1
    second.close()


def test_sqlite_store_rejects_mutation_and_persists_revoke(tmp_path):
    store = SQLiteApprovalStore(tmp_path / "approvals.sqlite3")
    record = _record()
    store.register(record)

    with pytest.raises(ValueError, match="不可变"):
        store.register(ApprovalRecord(**{**record.__dict__, "target": "inventory-api"}))

    store.revoke(record.approval_id)
    assert store.get(record.approval_id).status == "revoked"
    assert store.consume(record) is False
    store.close()


def test_sqlite_store_atomic_consume_has_one_winner(tmp_path):
    path = tmp_path / "approvals.sqlite3"
    record = _record()
    first = SQLiteApprovalStore(path)
    second = SQLiteApprovalStore(path)
    first.register(record)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda current: current.consume(record), (first, second)))

    assert sorted(results) == [False, True]
    assert first.consumed_count(record.approval_id) == 1
    first.close()
    second.close()


def test_build_approval_store_keeps_light_default_and_supports_path(tmp_path):
    assert isinstance(build_approval_store(), ApprovalStore)
    persistent = build_approval_store(tmp_path / "configured.sqlite3")
    assert isinstance(persistent, SQLiteApprovalStore)
    persistent.close()
