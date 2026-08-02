"""Control API 集成测试。"""

import hashlib
import hmac
import time

import pytest
from httpx import ASGITransport, AsyncClient

import sentinel_x_control_api.app as control_module

app = control_module.app


@pytest.fixture(autouse=True)
def reset_store(monkeypatch):
    control_module.store._incidents.clear()
    control_module.store._fingerprint_index.clear()
    control_module.store._approvals.clear()
    monkeypatch.setattr(control_module, "ALERT_INGRESS_HMAC_KEY", "test-alert-ingress-secret")


@pytest.fixture
async def client():
    async def sign_alert_request(request):
        if request.method != "POST" or request.url.path != "/api/incidents":
            return
        if "X-Sentinel-Signature" in request.headers:
            return
        timestamp = str(int(time.time()))
        signature = hmac.new(
            b"test-alert-ingress-secret",
            timestamp.encode() + b"\n" + request.content,
            hashlib.sha256,
        ).hexdigest()
        request.headers["X-Sentinel-Timestamp"] = timestamp
        request.headers["X-Sentinel-Signature"] = f"sha256={signature}"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        event_hooks={"request": [sign_alert_request]},
    ) as ac:
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

    async def test_alert_ingress_rejects_invalid_signature(self, client):
        response = await client.post(
            "/api/incidents",
            headers={
                "X-Sentinel-Timestamp": str(int(time.time())),
                "X-Sentinel-Signature": "sha256=invalid",
            },
            json={
                "alert_source": {
                    "alertmanager_id": "test-signature",
                    "fingerprint": "fp-signature",
                    "alert_name": "Signature Test",
                    "severity": "warning",
                    "description": "Test incident",
                    "started_at": "2026-08-01T21:00:00Z",
                }
            },
        )
        assert response.status_code == 401
        assert "签名无效" in response.json()["detail"]

    async def test_alert_ingress_fails_closed_without_secret(self, client, monkeypatch):
        monkeypatch.setattr(control_module, "ALERT_INGRESS_HMAC_KEY", None)
        response = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "test-no-secret",
                "fingerprint": "fp-no-secret",
                "alert_name": "No Secret Test",
                "severity": "warning",
                "description": "Test incident",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })
        assert response.status_code == 503

    async def test_active_fingerprint_is_deduplicated(self, client):
        payload = {
            "alert_source": {
                "alertmanager_id": "dedupe-001",
                "fingerprint": "fp-dedupe-active",
                "alert_name": "Duplicate Alert",
                "severity": "warning",
                "description": "same alert",
                "started_at": "2026-08-01T21:00:00Z",
            }
        }
        first = await client.post("/api/incidents", json=payload)
        second = await client.post("/api/incidents", json=payload)
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]

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
    planner_headers = {"X-Sentinel-Role": "planner"}
    approver_headers = {"X-Sentinel-Role": "approver"}
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
        response = await client.post(f"/api/incidents/{incident_id}/approvals", headers=self.planner_headers, json={
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

        approval_resp = await client.post(f"/api/incidents/{incident_id}/approvals", headers=self.planner_headers, json={
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
            headers=self.approver_headers,
            json={"approved": True, "reason": "证据充分"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"

    async def test_approval_requires_approver_role(self, client):
        create_resp = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "test-role",
                "fingerprint": "fp-role",
                "alert_name": "Role Test",
                "severity": "warning",
                "description": "Test",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })
        incident_id = create_resp.json()["id"]
        approval_resp = await client.post(
            f"/api/incidents/{incident_id}/approvals",
            headers=self.planner_headers,
            json={
                "plan_id": "plan-role",
                "runbook_ref": "restart_deployment@1",
                "target": "payment-api",
                "parameters": {},
                "risk_level": "R1",
                "plan_hash": "rolehash",
                "hypothesis_id": "hyp-role",
            },
        )
        approval_id = approval_resp.json()["id"]
        denied = await client.put(
            f"/api/incidents/{incident_id}/approvals/{approval_id}",
            json={"approved": True, "reason": "证据充分"},
        )
        assert denied.status_code == 403

    async def test_approval_incident_mismatch_is_rejected(self, client):
        headers = self.planner_headers
        first = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "test-mismatch-a", "fingerprint": "fp-mismatch-a",
                "alert_name": "A", "severity": "warning", "description": "A",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })
        second = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "test-mismatch-b", "fingerprint": "fp-mismatch-b",
                "alert_name": "B", "severity": "warning", "description": "B",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })
        approval = await client.post(
            f"/api/incidents/{first.json()['id']}/approvals",
            headers=headers,
            json={
                "plan_id": "plan-mismatch", "runbook_ref": "restart_deployment@1",
                "target": "payment-api", "parameters": {}, "risk_level": "R1",
                "plan_hash": "mismatchhash", "hypothesis_id": "hyp-mismatch",
            },
        )
        response = await client.put(
            f"/api/incidents/{second.json()['id']}/approvals/{approval.json()['id']}",
            headers=self.approver_headers,
            json={"approved": True, "reason": "不应跨事故批准"},
        )
        assert response.status_code == 404

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

        response = await client.post(f"/api/incidents/{incident_id}/approvals", headers=self.planner_headers, json={
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

    async def test_global_approval_queue_returns_incident_context(self, client):
        response = await client.post("/api/scenarios/payment-latency@1/run", headers={"X-Sentinel-Role": "scenario_operator"})
        assert response.status_code == 202

        queue_response = await client.get("/api/approvals")
        assert queue_response.status_code == 200
        items = queue_response.json()["items"]
        matching = [item for item in items if item["incident"]["id"] == response.json()["incident_id"]]
        assert len(matching) == 1
        assert matching[0]["status"] == "pending"
        assert matching[0]["incident"]["severity"] == "warning"

    async def test_global_approval_queue_rejects_unknown_status(self, client):
        response = await client.get("/api/approvals?status=unknown")
        assert response.status_code == 400


@pytest.mark.asyncio
class TestScenarios:
    async def test_list_scenarios(self, client):
        response = await client.get("/api/scenarios")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 6  # 6 个预置场景

    async def test_run_scenario_requires_operator_role(self, client):
        response = await client.post("/api/scenarios/payment-pod-crash@1/run")
        assert response.status_code == 403

    async def test_run_scenario_creates_incident_and_approval(self, client):
        response = await client.post("/api/scenarios/order-db-errors@1/run", headers={"X-Sentinel-Role": "scenario_operator"})
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
            headers={"X-Sentinel-Role": "approver"},
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
