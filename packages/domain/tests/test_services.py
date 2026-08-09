"""领域服务测试。"""

from uuid import uuid4

from sentinel_x_domain.services import compute_plan_hash


def test_compute_plan_hash_accepts_uuid_and_serialized_incident_id():
    incident_id = uuid4()
    parameters = {"reason": "持续 5xx", "timeout_seconds": 120}

    from_uuid = compute_plan_hash(
        "restart_deployment@1",
        "inventory-api",
        parameters,
        incident_id,
    )
    from_string = compute_plan_hash(
        "restart_deployment@1",
        "inventory-api",
        {"timeout_seconds": 120, "reason": "持续 5xx"},
        str(incident_id),
    )

    assert from_uuid == from_string
    assert len(from_uuid) == 64
