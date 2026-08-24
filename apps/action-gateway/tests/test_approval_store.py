from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sentinel_x_action_gateway.approval_store import (
    ApprovalRecord,
    ApprovalStore,
    SQLiteApprovalStore,
    TargetIdentity,
    build_approval_store,
)
from sentinel_x_contracts import RiskLevel
from sentinel_x_domain.services import compute_plan_hash


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
