from datetime import UTC, datetime, timedelta

import pytest

from sentinel_x_action_gateway.app import (
    ActionGate,
    ActionSubmitRequest,
    ExecutionStore,
    REGISTERED_RUNBOOKS,
)
from sentinel_x_action_gateway.approval_store import (
    ApprovalRecord,
    ApprovalStore,
    TargetIdentity,
)
from sentinel_x_action_gateway.executor import (
    FakeKubernetesApi,
    FakeKubernetesExecutor,
    TargetIdentityMismatch,
)
from sentinel_x_contracts import RiskLevel
from sentinel_x_domain.services import compute_plan_hash


def test_gateway_app_can_select_fake_k8s_executor(monkeypatch):
    """隔离 full profile 通过环境变量启用 fake-k8s，默认路径不受影响。"""
    monkeypatch.setenv("SENTINEL_EXECUTION_MODE", "fake-k8s")
    import sentinel_x_action_gateway.app as gateway_app

    executor = gateway_app._build_executor()
    assert executor.execution_mode == "fake-k8s"
    deployment = executor.api.get_current("demo-shop", "Deployment", "inventory-api")
    assert deployment.replicas == deployment.ready_replicas == 3


def test_full_profile_rejects_fixture_executor(monkeypatch):
    monkeypatch.setenv("SENTINEL_PROFILE", "full")
    monkeypatch.setenv("SENTINEL_EXECUTION_MODE", "fixture")
    import sentinel_x_action_gateway.app as gateway_app

    with pytest.raises(RuntimeError, match="禁止 fixture"):
        gateway_app._build_executor()


def _identity(generation: int = 1) -> TargetIdentity:
    return TargetIdentity(
        namespace="demo-shop",
        kind="Deployment",
        name="inventory-api",
        uid="uid-inventory-001",
        generation=generation,
    )


def test_fake_api_restart_changes_generation_and_health_state():
    api = FakeKubernetesApi()
    identity = _identity()
    api.register_deployment(identity, replicas=3, ready_replicas=1, healthy=False)

    result = FakeKubernetesExecutor(api).execute(
        "restart_deployment@1", identity, {"reason": "test"}
    )

    assert result.status == "succeeded"
    assert "generation=2" in result.after_state
    current = api.get_current("demo-shop", "Deployment", "inventory-api")
    assert current.identity.generation == 2
    assert current.ready_replicas == 3
    assert current.healthy is True
    assert current.restart_count == 1


def test_fake_api_scale_changes_replica_count():
    api = FakeKubernetesApi()
    identity = _identity()
    api.register_deployment(identity)

    result = FakeKubernetesExecutor(api).execute(
        "scale_deployment@1", identity, {"replicas": 5, "reason": "test"}
    )

    assert result.status == "succeeded"
    current = api.get_current("demo-shop", "Deployment", "inventory-api")
    assert current.replicas == 5
    assert current.ready_replicas == 5
    assert current.healthy is True


def test_fake_api_rejects_uid_or_generation_drift():
    api = FakeKubernetesApi()
    api.register_deployment(_identity(generation=2))

    with pytest.raises(TargetIdentityMismatch, match="UID/generation"):
        FakeKubernetesExecutor(api).execute(
            "restart_deployment@1", _identity(generation=1), {"reason": "test"}
        )


@pytest.mark.parametrize(
    ("mode", "expected_status", "expected_healthy"),
    [
        ("timeout", "failed", True),
        ("partial_ready", "failed", False),
        ("unknown", "unknown", True),
    ],
)
def test_fake_api_failure_modes_are_explicit(mode, expected_status, expected_healthy):
    api = FakeKubernetesApi()
    identity = _identity()
    api.register_deployment(identity)
    api.set_failure_mode(mode)

    result = FakeKubernetesExecutor(api).execute(
        "restart_deployment@1", identity, {"reason": "test"}
    )

    assert result.status == expected_status
    assert result.error
    current = api.get_current("demo-shop", "Deployment", "inventory-api")
    assert current.healthy is expected_healthy


@pytest.mark.asyncio
async def test_action_gate_records_fake_kubernetes_before_after_state():
    api = FakeKubernetesApi()
    identity = _identity()
    api.register_deployment(identity)
    approval_store = ApprovalStore()
    gate = ActionGate(
        store=ExecutionStore(),
        approval_store=approval_store,
        kill_switch=False,
        approval_token_secret="test-secret",
        executor=FakeKubernetesExecutor(api),
    )
    parameters = {"reason": "test"}
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    record = ApprovalRecord(
        approval_id="approval-fake-k8s",
        incident_id="incident-fake-k8s",
        runbook_ref="restart_deployment@1",
        target=identity.name,
        parameters=parameters,
        plan_hash=compute_plan_hash(
            "restart_deployment@1", identity.name, parameters, "incident-fake-k8s"
        ),
        risk_level=RiskLevel.R1,
        audience="sentinel-action-gateway",
        expires_at=expires_at,
        target_identity=identity,
    )
    approval_store.register(record)
    request = ActionSubmitRequest(
        runbook_ref=record.runbook_ref,
        target=record.target,
        parameters=parameters,
        plan_hash=record.plan_hash,
        approval_id=record.approval_id,
        approval_token=gate._expected_approval_token(record),
        approval_expires_at=expires_at,
        incident_id=record.incident_id,
        audience=record.audience,
        target_identity=identity,
        idempotency_key="fake-k8s-idempotency-001",
    )
    allowed, reason, runbook, approval = gate.validate(request)
    assert allowed, reason
    assert runbook is REGISTERED_RUNBOOKS[record.runbook_ref]
    assert approval == record

    execution = await gate.execute(runbook, request, approval)
    assert execution is not None
    assert execution.status == "succeeded"
    assert execution.execution_mode == "fake-k8s"
    assert "generation=1" in execution.before_state
    assert "generation=2" in execution.after_state


@pytest.mark.asyncio
async def test_action_gate_reconciles_unknown_fake_kubernetes_action():
    api = FakeKubernetesApi()
    identity = _identity()
    api.register_deployment(identity)
    api.set_failure_mode("unknown")
    approval_store = ApprovalStore()
    gate = ActionGate(
        store=ExecutionStore(), approval_store=approval_store, kill_switch=False,
        approval_token_secret="test-secret", executor=FakeKubernetesExecutor(api),
    )
    parameters = {"reason": "reconcile test"}
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    approval = ApprovalRecord(
        approval_id="approval-reconcile", incident_id="incident-reconcile",
        runbook_ref="restart_deployment@1", target=identity.name, parameters=parameters,
        plan_hash=compute_plan_hash("restart_deployment@1", identity.name, parameters, "incident-reconcile"),
        risk_level=RiskLevel.R1, audience="sentinel-action-gateway", expires_at=expires_at,
        target_identity=identity,
    )
    approval_store.register(approval)
    request = ActionSubmitRequest(
        runbook_ref=approval.runbook_ref, target=approval.target, parameters=parameters,
        plan_hash=approval.plan_hash, approval_id=approval.approval_id,
        approval_token=gate._expected_approval_token(approval), approval_expires_at=expires_at,
        incident_id=approval.incident_id, audience=approval.audience,
        target_identity=identity, idempotency_key="fake-k8s-reconcile-key-001",
    )
    allowed, reason, runbook, record = gate.validate(request)
    assert allowed, reason
    execution = await gate.execute(runbook, request, record)
    assert execution.status == "unknown"

    reconciled = await gate.reconcile(execution.execution_id)

    assert reconciled.status == "succeeded"
    assert reconciled.reconciliation_count == 1
    assert "generation=2" in reconciled.after_state
