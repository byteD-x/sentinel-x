from datetime import datetime, timedelta, timezone

import pytest

from sentinel_x_action_gateway.approval_store import (
    ApprovalRecord,
    ApprovalStore,
    TargetIdentity,
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
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
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
