"""
Action Gateway 测试 — 覆盖完整校验链和安全边界。
"""

import hashlib
import hmac
import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_x_contracts import RiskLevel as ContractRiskLevel
from sentinel_x_action_gateway.app import (
    REGISTERED_RUNBOOKS,
    RiskLevel,
    RunbookDefinition,
    app,
    gate,
    store,
)
from sentinel_x_domain.services import compute_plan_hash


@pytest.fixture(autouse=True)
def reset_state():
    """每个测试前重置状态。"""
    store._executions.clear()
    store._idempotency_keys.clear()
    store._consumed_approval_ids.clear()
    gate.kill_switch = False
    gate.approval_token_secret = "test-approval-secret"
    gate.admin_token = "test-admin-token"


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


def _make_plan_hash(runbook_ref: str, target: str, parameters: dict, incident_id: str) -> str:
    return compute_plan_hash(runbook_ref, target, parameters, incident_id)


def _sign_approval_token(data: dict) -> str:
    canonical = "|".join((
        data["approval_id"],
        data["incident_id"],
        data["plan_hash"],
        data["audience"],
        datetime.fromisoformat(data["approval_expires_at"]).astimezone(timezone.utc).isoformat(),
    ))
    return hmac.new(
        gate.approval_token_secret.encode(), canonical.encode(), hashlib.sha256
    ).hexdigest()


def _make_request(
    runbook_ref: str = "restart_deployment@1",
    target: str = "payment-api",
    parameters: dict | None = None,
    incident_id: str = "incident-test-001",
) -> dict:
    if parameters is None:
        parameters = {"reason": "测试"}
    plan_hash = _make_plan_hash(runbook_ref, target, parameters, incident_id)
    data = {
        "runbook_ref": runbook_ref,
        "target": target,
        "parameters": parameters,
        "idempotency_key": f"test-key-{hashlib.sha256(str(hash(str(parameters))).encode()).hexdigest()[:12]}",
        "plan_hash": plan_hash,
        "approval_id": "approval-test-001",
        "approval_token": "placeholder-token-001",
        "approval_expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=30)
        ).isoformat(),
        "incident_id": incident_id,
        "audience": "sentinel-action-gateway",
    }
    data["approval_token"] = _sign_approval_token(data)
    return data


@pytest.mark.asyncio
class TestHappyPath:
    """正常流程。"""

    async def test_restart_deployment_succeeds(self, client):
        resp = await client.post("/api/actions", json=_make_request())
        assert resp.status_code == 202

    async def test_scale_deployment_succeeds(self, client):
        resp = await client.post("/api/actions", json=_make_request(
            runbook_ref="scale_deployment@1",
            target="inventory-api",
            parameters={"replicas": 5, "reason": "扩容测试"},
        ))
        assert resp.status_code == 202

    async def test_get_status_after_submit(self, client):
        resp = await client.post("/api/actions", json=_make_request())
        execution_id = resp.json()["execution_id"]
        resp2 = await client.get(f"/api/actions/{execution_id}")
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "succeeded"


@pytest.mark.asyncio
class TestRejections:
    """拒绝场景。"""

    async def test_unknown_runbook_rejected(self, client):
        resp = await client.post("/api/actions", json=_make_request(
            runbook_ref="unknown_action@1"
        ))
        assert resp.status_code == 400
        assert "未知 Runbook" in resp.json()["detail"]

    async def test_r2_runbook_rejected(self, client, monkeypatch):
        """已登记的 R2 操作也必须在 MVP 中被拒绝。"""
        monkeypatch.setitem(REGISTERED_RUNBOOKS, "db_rollback@1", RunbookDefinition(
            ref="db_rollback@1",
            description="test-only R2 runbook",
            risk_level=RiskLevel.R2,
            target_selector=r"^inventory-api$",
        ))
        resp = await client.post("/api/actions", json=_make_request(
            runbook_ref="db_rollback@1"
        ))
        assert resp.status_code == 400
        assert "R2" in resp.json()["detail"]

    async def test_r3_runbook_is_permanently_rejected(self, client, monkeypatch):
        """已登记的 R3 操作必须永久拒绝。"""
        monkeypatch.setitem(REGISTERED_RUNBOOKS, "exec_pod_command@1", RunbookDefinition(
            ref="exec_pod_command@1",
            description="test-only R3 runbook",
            risk_level=RiskLevel.R3,
            target_selector=r"^inventory-api$",
        ))
        resp = await client.post("/api/actions", json=_make_request(
            runbook_ref="exec_pod_command@1"
        ))
        assert resp.status_code == 400
        assert "R3" in resp.json()["detail"]

    async def test_invalid_target_rejected(self, client):
        resp = await client.post("/api/actions", json=_make_request(
            target="unauthorized-service"
        ))
        assert resp.status_code == 400
        assert "白名单" in resp.json()["detail"]

    async def test_wrong_plan_hash_rejected(self, client):
        data = _make_request()
        data["plan_hash"] = "0000000000000000"  # 错误的 hash
        data["approval_token"] = _sign_approval_token(data)
        resp = await client.post("/api/actions", json=data)
        assert resp.status_code == 400
        assert "hash" in resp.json()["detail"].lower()

    async def test_invalid_approval_token_rejected(self, client):
        data = _make_request()
        data["approval_token"] = "invalid-token-000000"
        resp = await client.post("/api/actions", json=data)
        assert resp.status_code == 400
        assert "审批凭证" in resp.json()["detail"]

    async def test_invalid_audience_rejected(self, client):
        data = _make_request()
        data["audience"] = "other-service"
        data["approval_token"] = _sign_approval_token(data)
        resp = await client.post("/api/actions", json=data)
        assert resp.status_code == 400
        assert "audience" in resp.json()["detail"]

    async def test_unknown_field_rejected(self, client):
        data = _make_request()
        data["unexpected"] = "not-allowed"
        resp = await client.post("/api/actions", json=data)
        assert resp.status_code == 422

    async def test_duplicate_idempotency_key_rejected(self, client):
        data = _make_request()
        # 第一次
        resp1 = await client.post("/api/actions", json=data)
        assert resp1.status_code == 202
        # 第二次相同 key
        resp2 = await client.post("/api/actions", json=data)
        assert resp2.status_code == 400
        assert "幂等键" in resp2.json()["detail"]

    async def test_approval_id_is_consumed_once_across_idempotency_keys(self, client):
        first = _make_request()
        second = _make_request()
        second["idempotency_key"] = "test-key-for-approval-replay"

        first_response = await client.post("/api/actions", json=first)
        second_response = await client.post("/api/actions", json=second)

        assert first_response.status_code == 202
        assert second_response.status_code == 400
        assert "审批" in second_response.json()["detail"]
        assert "消费" in second_response.json()["detail"]

    async def test_invalid_scale_params_rejected(self, client):
        resp = await client.post("/api/actions", json=_make_request(
            runbook_ref="scale_deployment@1",
            target="order-api",
            parameters={"replicas": 100},  # 超出最大值 10
        ))
        assert resp.status_code == 400

    async def test_boolean_is_not_accepted_as_integer_replicas(self, client):
        resp = await client.post("/api/actions", json=_make_request(
            runbook_ref="scale_deployment@1",
            target="order-api",
            parameters={"replicas": True},
        ))
        assert resp.status_code == 400
        assert "应为整数" in resp.json()["detail"]

    async def test_string_schema_enforces_type_and_max_length(self, client):
        wrong_type = await client.post("/api/actions", json=_make_request(
            target="order-api",
            parameters={"reason": 123},
        ))
        assert wrong_type.status_code == 400
        assert "应为字符串" in wrong_type.json()["detail"]

        too_long = await client.post("/api/actions", json=_make_request(
            target="inventory-api",
            parameters={"reason": "x" * 501},
        ))
        assert too_long.status_code == 400
        assert "最大长度" in too_long.json()["detail"]

    async def test_expired_approval_rejected(self, client):
        data = _make_request()
        data["approval_expires_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()
        data["approval_token"] = _sign_approval_token(data)
        resp = await client.post("/api/actions", json=data)
        assert resp.status_code == 400
        assert "过期" in resp.json()["detail"]

    async def test_approval_token_binds_expiration(self, client):
        data = _make_request()
        data["approval_expires_at"] = (
            datetime.now(timezone.utc) + timedelta(days=1)
        ).isoformat()

        resp = await client.post("/api/actions", json=data)

        assert resp.status_code == 400
        assert "审批凭证" in resp.json()["detail"]


@pytest.mark.asyncio
class TestKillSwitch:
    """Kill Switch 测试。"""

    async def test_kill_switch_blocks_actions(self, client):
        # 激活 Kill Switch
        await client.post(
            "/api/admin/kill-switch?activate=true",
            headers={"X-Sentinel-Admin-Token": gate.admin_token},
        )
        resp = await client.post("/api/actions", json=_make_request())
        assert resp.status_code == 400
        assert "Kill Switch" in resp.json()["detail"]

    async def test_kill_switch_deactivate_restores(self, client):
        # 激活再关闭
        await client.post(
            "/api/admin/kill-switch?activate=true",
            headers={"X-Sentinel-Admin-Token": gate.admin_token},
        )
        await client.post(
            "/api/admin/kill-switch?activate=false",
            headers={"X-Sentinel-Admin-Token": gate.admin_token},
        )
        resp = await client.post("/api/actions", json=_make_request())
        assert resp.status_code == 202

    async def test_kill_switch_requires_admin_token(self, client):
        resp = await client.post("/api/admin/kill-switch?activate=true")
        assert resp.status_code == 403

    async def test_concurrent_same_idempotency_key_has_one_winner(self, client):
        data = _make_request()
        responses = await asyncio.gather(
            client.post("/api/actions", json=data),
            client.post("/api/actions", json=data),
        )
        assert sorted(response.status_code for response in responses) == [202, 400]


@pytest.mark.asyncio
class TestRunbooks:
    """Runbook 列表。"""

    async def test_list_runbooks(self, client):
        resp = await client.get("/api/runbooks")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2  # restart + scale


@pytest.mark.asyncio
class TestHealth:
    """健康检查。"""

    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["actions_enabled"] is True

    async def test_health_defaults_fail_closed(self, client):
        gate.kill_switch = True
        gate.approval_token_secret = None
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["actions_enabled"] is False


def test_gateway_risk_level_is_the_shared_contract_enum():
    assert RiskLevel is ContractRiskLevel
