"""Control API 集成测试。"""

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_x_control_api.app import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
class TestHealthCheck:
    async def test_health_returns_ok(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"
        assert data["actions_enabled"] is False


@pytest.mark.asyncio
class TestIncidents:
    async def test_create_incident(self, client):
        response = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "test-001",
                "fingerprint": "fp-test",
                "alert_name": "Test Alert",
                "severity": "warning",
                "description": "Test incident",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "DETECTED"

    async def test_list_incidents(self, client):
        # 先创建一些事故
        for i in range(3):
            await client.post("/api/incidents", json={
                "alert_source": {
                    "alertmanager_id": f"test-{i}",
                    "fingerprint": f"fp-{i}",
                    "alert_name": f"Alert {i}",
                    "severity": "warning",
                    "description": f"Test {i}",
                    "started_at": "2026-08-01T21:00:00Z",
                }
            })
        response = await client.get("/api/incidents")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 3

    async def test_get_nonexistent_incident(self, client):
        response = await client.get("/api/incidents/nonexistent")
        assert response.status_code == 404

    async def test_create_incident_rejects_unknown_fields(self, client):
        response = await client.post("/api/incidents", json={
            "unexpected_top": True,
            "alert_source": {
                "alertmanager_id": "test-extra",
                "fingerprint": "fp-extra",
                "alert_name": "Extra Field Test",
                "severity": "warning",
                "description": "Test incident",
                "started_at": "2026-08-01T21:00:00Z",
                "unexpected_nested": "ignored-before-fix",
            }
        })
        assert response.status_code == 422

    async def test_timeline(self, client):
        create_resp = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "test-tl",
                "fingerprint": "fp-tl",
                "alert_name": "Timeline Test",
                "severity": "info",
                "description": "Timeline test",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })
        incident_id = create_resp.json()["id"]
        response = await client.get(f"/api/incidents/{incident_id}/timeline")
        assert response.status_code == 200
        data = response.json()
        assert len(data["events"]) >= 1  # incident.created 事件


@pytest.mark.asyncio
class TestApprovals:
    async def test_create_approval(self, client):
        # 创建事故
        create_resp = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "test-approval",
                "fingerprint": "fp-approval",
                "alert_name": "Approval Test",
                "severity": "warning",
                "description": "Test",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })
        incident_id = create_resp.json()["id"]

        # 创建审批
        response = await client.post(f"/api/incidents/{incident_id}/approvals", json={
            "plan_id": "plan-001",
            "runbook_ref": "restart_deployment@1",
            "target": "payment-api",
            "parameters": {},
            "risk_level": "R1",
            "plan_hash": "abc123",
            "hypothesis_id": "hyp-001",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "pending"

    async def test_approve(self, client):
        create_resp = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "test-decide",
                "fingerprint": "fp-decide",
                "alert_name": "Decide Test",
                "severity": "warning",
                "description": "Test",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })
        incident_id = create_resp.json()["id"]

        approval_resp = await client.post(f"/api/incidents/{incident_id}/approvals", json={
            "plan_id": "plan-002",
            "runbook_ref": "scale_deployment@1",
            "target": "inventory-api",
            "parameters": {"replicas": 5},
            "risk_level": "R1",
            "plan_hash": "def456",
            "hypothesis_id": "hyp-002",
        })
        approval_id = approval_resp.json()["id"]

        response = await client.put(
            f"/api/incidents/{incident_id}/approvals/{approval_id}",
            json={"approved": True, "reason": "证据充分"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"

    async def test_r2_rejected(self, client):
        create_resp = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "test-r2",
                "fingerprint": "fp-r2",
                "alert_name": "R2 Test",
                "severity": "warning",
                "description": "Test",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })
        incident_id = create_resp.json()["id"]

        response = await client.post(f"/api/incidents/{incident_id}/approvals", json={
            "plan_id": "plan-r2",
            "runbook_ref": "db_rollback@1",
            "target": "order-db",
            "parameters": {},
            "risk_level": "R2",
            "plan_hash": "r2hash",
            "hypothesis_id": "hyp-r2",
        })
        assert response.status_code == 400  # R2 被拒绝
        assert "R2" in response.json()["detail"]


@pytest.mark.asyncio
class TestScenarios:
    async def test_list_scenarios(self, client):
        response = await client.get("/api/scenarios")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 6  # 6 个预置场景

    async def test_run_scenario_creates_incident_and_approval(self, client):
        response = await client.post("/api/scenarios/order-db-errors@1/run")
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "AWAITING_APPROVAL"

        incident_id = data["incident_id"]
        incident_response = await client.get(f"/api/incidents/{incident_id}")
        assert incident_response.status_code == 200

        timeline_response = await client.get(f"/api/incidents/{incident_id}/timeline")
        event_types = {event["event_type"] for event in timeline_response.json()["events"]}
        assert {"scenario.started", "evidence.collected", "hypothesis.generated"} <= event_types

        approvals_response = await client.get(f"/api/incidents/{incident_id}/approvals")
        approvals = approvals_response.json()["items"]
        assert len(approvals) == 1
        assert approvals[0]["runbook_ref"] == "restart_deployment@1"

        approve_response = await client.put(
            f"/api/incidents/{incident_id}/approvals/{approvals[0]['id']}",
            json={"approved": True, "reason": "演练验证通过"},
        )
        assert approve_response.status_code == 200

        resolved_response = await client.get(f"/api/incidents/{incident_id}")
        assert resolved_response.json()["status"] == "RESOLVED"

        final_timeline = await client.get(f"/api/incidents/{incident_id}/timeline")
        final_event_types = {event["event_type"] for event in final_timeline.json()["events"]}
        assert {"action.started", "action.completed", "recovery.verified"} <= final_event_types


@pytest.mark.asyncio
class TestDemoSeed:
    async def test_seed_demo_data(self, client):
        response = await client.post("/api/demo/seed")
        assert response.status_code == 201
        data = response.json()
        assert "已创建" in data["message"]
