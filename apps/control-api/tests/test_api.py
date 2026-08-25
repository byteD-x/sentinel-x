"""Control API 集成测试。"""

import hashlib
import hmac
import json
import time

import pytest
from demo.scenarios.loader import ScenarioLoader
from httpx import ASGITransport, AsyncClient
from sentinel_x_contracts import IncidentSeverity, IncidentStatus, RiskLevel
from sentinel_x_domain.services import compute_plan_hash

import sentinel_x_control_api.app as control_module
import sentinel_x_control_api.eval_archive as eval_archive_module

app = control_module.app


def write_evaluation_archive(directory, report_id="eval-20260809-101500-a1b2c3"):
    archive = {
        "schema_version": "1.0",
        "report_id": report_id,
        "created_at": "2026-08-09T10:15:00Z",
        "metadata": {
            "commit_sha": "a" * 40,
            "profile": "light",
            "environment_ref": "local-isolated",
            "hardware_ref": None,
            "dataset_ref": "holdout@1",
            "model_ref": "investigator-v1",
            "policy_ref": "policy@1",
            "prompt_ref": "investigator@1",
            "random_seed": 42,
            "runs_per_scenario": 1,
            "timeout_seconds": 600,
        },
        "comparability": {
            "comparable": False,
            "baseline_ref": None,
            "reasons": ["尚未建立同口径 baseline。"],
        },
        "aggregate": {
            "attempted_runs": 1,
            "completed_runs": 1,
            "failed_runs": 0,
            "metrics": [{
                "name": "top1_accuracy",
                "category": "diagnosis",
                "value": 100.0,
                "unit": "%",
                "target": 60.0,
                "direction": "higher_is_better",
                "passed": True,
                "sample_count": 1,
            }],
        },
        "runs": [{
            "run_id": "run-001",
            "scenario_ref": "inventory-latched-5xx@1",
            "run_index": 0,
            "incident_id": "incident-001",
            "model_ref": "investigator-v1",
            "config": {"dataset": "holdout@1", "seed": 42},
            "metrics": [{
                "name": "top1_accuracy",
                "category": "diagnosis",
                "value": 100.0,
                "unit": "%",
                "target": 60.0,
                "direction": "higher_is_better",
                "passed": True,
            }],
        }],
        "failures": [],
    }
    path = directory / f"{report_id}.json"
    path.write_text(json.dumps(archive, ensure_ascii=False), encoding="utf-8")
    return path, archive


@pytest.fixture(autouse=True)
def reset_store(monkeypatch):
    control_module.store._incidents.clear()
    control_module.store._fingerprint_index.clear()
    control_module.store._approvals.clear()
    control_module.store._workflow_checkpoints.clear()
    control_module.store.flush()
    control_module._ALERT_INGRESS_REPLAY_CACHE.clear()
    control_module.store._outbox.clear()
    control_module.store.flush()
    monkeypatch.setattr(control_module, "ALERT_INGRESS_HMAC_KEY", "test-alert-ingress-secret")


@pytest.fixture
async def client():
    async def sign_alert_request(request):
        if request.method != "POST" or request.url.path != "/api/incidents":
            return
        if "X-Sentinel-Signature" in request.headers:
            return
        timestamp = str(int(time.time()))
        nonce = str(time.time_ns())
        signature = hmac.new(
            b"test-alert-ingress-secret",
            timestamp.encode() + b"\n" + nonce.encode() + b"\n" + request.content,
            hashlib.sha256,
        ).hexdigest()
        request.headers["X-Sentinel-Timestamp"] = timestamp
        request.headers["X-Sentinel-Nonce"] = nonce
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
class TestVersionedApi:
    async def test_v1_fails_closed_without_session_key(self, client, monkeypatch):
        monkeypatch.setattr(control_module, "LOCAL_SESSION_SIGNING_KEY", None)
        response = await client.get("/api/v1/incidents")
        assert response.status_code == 503
        assert "会话认证" in response.json()["detail"]

    async def test_v1_stream_fails_closed_without_session_key(self, client, monkeypatch):
        monkeypatch.setattr(control_module, "LOCAL_SESSION_SIGNING_KEY", None)
        response = await client.get("/api/v1/incidents/missing/stream")
        assert response.status_code == 503
        assert "会话认证" in response.json()["detail"]

    async def test_v1_stream_authenticates_before_loading_incident(self, client, monkeypatch):
        monkeypatch.setattr(control_module, "LOCAL_SESSION_SIGNING_KEY", "test-session-secret")
        viewer = control_module.build_local_session_token("viewer", int(time.time()) + 300)
        response = await client.get(
            "/api/v1/incidents/missing/stream",
            headers={"Authorization": viewer},
        )
        assert response.status_code == 404
        assert "不存在" in response.json()["detail"]

    async def test_v1_export_fails_closed_without_session_key(self, client, monkeypatch):
        monkeypatch.setattr(control_module, "LOCAL_SESSION_SIGNING_KEY", None)
        response = await client.get("/api/v1/incidents/missing/export")
        assert response.status_code == 503
        assert "会话认证" in response.json()["detail"]

    async def test_v1_export_returns_hashed_redacted_incident_package(self, client, monkeypatch):
        monkeypatch.setattr(control_module, "LOCAL_SESSION_SIGNING_KEY", "test-session-secret")
        created = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "export-test",
                "fingerprint": "fp-export-test",
                "alert_name": "Export Test",
                "severity": "warning",
                "description": "exportable incident",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })
        incident_id = created.json()["id"]
        control_module.store.add_timeline_event(
            incident_id,
            "evidence.collected",
            "diagnostic_gateway",
            {
                "token": "Bearer " + "s" * 40,
                "nested": {"password": "secret-value"},
                "summary": "safe evidence",
            },
        )
        viewer = control_module.build_local_session_token("viewer", int(time.time()) + 300)

        response = await client.get(
            f"/api/v1/incidents/{incident_id}/export",
            headers={"Authorization": viewer},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["schema_version"] == "1.0"
        assert data["profile"] == "local-isolated-fixture"
        assert data["manifest"]["timeline_events"] == 2
        serialized = dict(data)
        manifest = serialized.pop("manifest")
        canonical = json.dumps(serialized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        assert manifest["content_sha256"] == "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert "secret-value" not in json.dumps(data, ensure_ascii=False)
        assert "[REDACTED]" in json.dumps(data, ensure_ascii=False)

    async def test_v1_detail_returns_etag_and_requires_if_match_for_decision(self, client, monkeypatch):
        monkeypatch.setattr(control_module, "LOCAL_SESSION_SIGNING_KEY", "test-session-secret")
        started = await client.post(
            "/api/scenarios/inventory-latched-5xx@1/run",
            headers={"X-Sentinel-Role": "scenario_operator"},
        )
        incident_id = started.json()["incident_id"]
        approval_id = (await client.get(f"/api/incidents/{incident_id}/approvals")).json()["items"][0]["id"]
        viewer = control_module.build_local_session_token("viewer", int(time.time()) + 300)
        detail = await client.get(f"/api/v1/incidents/{incident_id}", headers={"Authorization": viewer})
        assert detail.status_code == 200
        etag = detail.headers["etag"]
        assert etag.startswith(f'"incident-{incident_id}-v') and etag.endswith('"')

        approver = control_module.build_local_session_token("approver", int(time.time()) + 300)
        missing = await client.put(
            f"/api/v1/incidents/{incident_id}/approvals/{approval_id}",
            headers={"Authorization": approver},
            json={"approved": True, "reason": "并发测试"},
        )
        assert missing.status_code == 428
        stale = await client.put(
            f"/api/v1/incidents/{incident_id}/approvals/{approval_id}",
            headers={"Authorization": approver, "If-Match": '"incident-%s-v999"' % incident_id},
            json={"approved": True, "reason": "并发测试"},
        )
        assert stale.status_code == 412

    async def test_full_v1_mutation_requires_csrf_token(self, client, monkeypatch):
        monkeypatch.setenv("SENTINEL_PROFILE", "full")
        monkeypatch.setattr(control_module, "LOCAL_SESSION_SIGNING_KEY", "test-session-secret")
        planner = control_module.build_local_session_token("scenario_operator", int(time.time()) + 300)
        response = await client.post(
            "/api/v1/scenarios/inventory-latched-5xx@1/run",
            headers={"Authorization": planner},
        )
        assert response.status_code == 403
        assert "CSRF" in response.json()["detail"]

    async def test_full_v1_mutation_accepts_signed_csrf_token(self, client, monkeypatch):
        monkeypatch.setenv("SENTINEL_PROFILE", "full")
        monkeypatch.setattr(control_module, "LOCAL_SESSION_SIGNING_KEY", "test-session-secret")
        session = control_module.build_local_session_token("scenario_operator", int(time.time()) + 300)
        csrf = hmac.new(
            b"test-session-secret", f"csrf:{session}".encode(), hashlib.sha256
        ).hexdigest()
        response = await client.post(
            "/api/v1/scenarios/inventory-latched-5xx@1/run",
            headers={"Authorization": session, "X-CSRF-Token": csrf},
        )
        assert response.status_code == 202


@pytest.mark.asyncio
class TestEvaluations:
    async def test_empty_evaluation_archive_returns_unavailable_reason(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(control_module, "EVAL_ARCHIVE_DIR", tmp_path, raising=False)

        response = await client.get("/api/evaluations")

        assert response.status_code == 200
        assert response.json() == {
            "available": False,
            "unavailable_reason": "尚无已归档的评测报告",
            "items": [],
        }

    async def test_evaluation_list_exposes_valid_archive_summary_and_raw_hash(self, client, monkeypatch, tmp_path):
        path, _ = write_evaluation_archive(tmp_path)
        monkeypatch.setattr(control_module, "EVAL_ARCHIVE_DIR", tmp_path, raising=False)

        response = await client.get("/api/evaluations")

        assert response.status_code == 200
        data = response.json()
        assert data["available"] is True
        item = data["items"][0]
        assert item["archive_status"] == "valid"
        assert item["report_id"] == "eval-20260809-101500-a1b2c3"
        assert item["metadata"]["dataset_ref"] == "holdout@1"
        assert item["aggregate"]["completed_runs"] == 1
        assert item["artifact"]["sha256"] == f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"

    async def test_evaluation_detail_returns_validated_archive_and_raw_hash(self, client, monkeypatch, tmp_path):
        path, archive = write_evaluation_archive(tmp_path)
        monkeypatch.setattr(control_module, "EVAL_ARCHIVE_DIR", tmp_path, raising=False)

        response = await client.get("/api/evaluations/eval-20260809-101500-a1b2c3")

        assert response.status_code == 200
        data = response.json()
        assert data["report"] == archive
        assert data["artifact"]["sha256"] == f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"

    async def test_invalid_evaluation_archive_is_listed_without_leaking_its_contents(self, client, monkeypatch, tmp_path):
        (tmp_path / "eval-invalid.json").write_text('{"schema_version":', encoding="utf-8")
        monkeypatch.setattr(control_module, "EVAL_ARCHIVE_DIR", tmp_path, raising=False)

        list_response = await client.get("/api/evaluations")
        detail_response = await client.get("/api/evaluations/eval-invalid")

        assert list_response.status_code == 200
        assert list_response.json()["items"] == [{
            "report_id": "eval-invalid",
            "archive_status": "invalid",
            "error": {
                "code": "EVALUATION_ARCHIVE_INVALID",
                "message": "评测归档无效",
            },
        }]
        assert detail_response.status_code == 422
        assert detail_response.json() == {
            "detail": "评测归档无效",
            "code": "EVALUATION_ARCHIVE_INVALID",
        }

    async def test_evaluation_detail_rejects_symbolic_link_archives(self, client, monkeypatch, tmp_path):
        external_path = tmp_path.parent / f"{tmp_path.name}-outside.json"
        external_path.write_text("{}", encoding="utf-8")
        original_resolve = eval_archive_module.Path.resolve
        original_is_symlink = eval_archive_module.Path.is_symlink

        def resolve(path, *args, **kwargs):
            if path.name == "eval-linked.json":
                return external_path
            return original_resolve(path, *args, **kwargs)

        monkeypatch.setattr(eval_archive_module.Path, "resolve", resolve)
        monkeypatch.setattr(
            eval_archive_module.Path,
            "is_symlink",
            lambda path: path.name == "eval-linked.json" or original_is_symlink(path),
        )
        monkeypatch.setattr(control_module, "EVAL_ARCHIVE_DIR", tmp_path, raising=False)

        response = await client.get("/api/evaluations/eval-linked")

        assert response.status_code == 422
        assert response.json() == {
            "detail": "评测归档无效",
            "code": "EVALUATION_ARCHIVE_INVALID",
        }

    async def test_evaluation_detail_rejects_an_invalid_report_identifier(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(control_module, "EVAL_ARCHIVE_DIR", tmp_path, raising=False)

        response = await client.get("/api/evaluations/invalid.report")

        assert response.status_code == 422
        assert response.json() == {
            "detail": "评测报告标识无效",
            "code": "INVALID_EVALUATION_ID",
        }

    async def test_evaluation_detail_refuses_archives_over_the_read_limit(self, client, monkeypatch, tmp_path):
        write_evaluation_archive(tmp_path)
        monkeypatch.setattr(control_module, "EVAL_ARCHIVE_DIR", tmp_path, raising=False)
        monkeypatch.setattr(control_module, "EVAL_ARCHIVE_MAX_BYTES", 1, raising=False)

        response = await client.get("/api/evaluations/eval-20260809-101500-a1b2c3")

        assert response.status_code == 413
        assert response.json() == {
            "detail": "评测归档超过读取上限",
            "code": "EVALUATION_ARCHIVE_TOO_LARGE",
        }

    async def test_evaluation_detail_rejects_inconsistent_run_totals(self, client, monkeypatch, tmp_path):
        path, archive = write_evaluation_archive(tmp_path, "eval-inconsistent")
        archive["aggregate"]["attempted_runs"] = 2
        path.write_text(json.dumps(archive, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(control_module, "EVAL_ARCHIVE_DIR", tmp_path, raising=False)

        response = await client.get("/api/evaluations/eval-inconsistent")

        assert response.status_code == 422
        assert response.json() == {
            "detail": "评测归档无效",
            "code": "EVALUATION_ARCHIVE_INVALID",
        }

    async def test_evaluation_list_marks_non_routable_report_ids_as_invalid(self, client, monkeypatch, tmp_path):
        write_evaluation_archive(tmp_path, "eval.invalid")
        monkeypatch.setattr(control_module, "EVAL_ARCHIVE_DIR", tmp_path, raising=False)

        response = await client.get("/api/evaluations")

        assert response.status_code == 200
        assert response.json()["items"] == [{
            "report_id": "eval.invalid",
            "archive_status": "invalid",
            "error": {
                "code": "EVALUATION_ARCHIVE_INVALID",
                "message": "评测归档无效",
            },
        }]

    async def test_evaluation_list_reports_an_unreadable_archive_directory(self, client, monkeypatch, tmp_path):
        original_iterdir = eval_archive_module.Path.iterdir

        def iterdir(path):
            if path == tmp_path.resolve():
                raise OSError("permission denied")
            return original_iterdir(path)

        monkeypatch.setattr(eval_archive_module.Path, "iterdir", iterdir)
        monkeypatch.setattr(control_module, "EVAL_ARCHIVE_DIR", tmp_path, raising=False)

        response = await client.get("/api/evaluations")

        assert response.status_code == 503
        assert response.json() == {
            "detail": "评测归档目录不可用",
            "code": "EVALUATION_ARCHIVE_UNAVAILABLE",
        }

    async def test_evaluation_detail_rejects_a_report_without_a_utc_timestamp(self, client, monkeypatch, tmp_path):
        path, archive = write_evaluation_archive(tmp_path, "eval-naive-time")
        archive["created_at"] = "2026-08-09T10:15:00"
        path.write_text(json.dumps(archive, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(control_module, "EVAL_ARCHIVE_DIR", tmp_path, raising=False)

        response = await client.get("/api/evaluations/eval-naive-time")

        assert response.status_code == 422
        assert response.json() == {
            "detail": "评测归档无效",
            "code": "EVALUATION_ARCHIVE_INVALID",
        }


@pytest.mark.asyncio
class TestIncidents:
    async def test_alertmanager_webhook_is_converted_to_incident(self, client):
        body = {
            "receiver": "sentinel-webhook",
            "status": "firing",
            "alerts": [{
                "status": "firing",
                "labels": {"alertname": "HighErrorRate", "severity": "critical", "service": "inventory-api"},
                "annotations": {"summary": "inventory error rate high"},
                "startsAt": "2026-08-25T04:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "fingerprint": "alertmanager-fingerprint-001",
                "generatorURL": "https://prometheus.invalid/graph",
            }],
        }
        raw_body = json.dumps(body, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        nonce = "alertmanager-webhook-nonce"
        signature = hmac.new(
            b"test-alert-ingress-secret",
            timestamp.encode() + b"\n" + nonce.encode() + b"\n" + raw_body,
            hashlib.sha256,
        ).hexdigest()
        response = await client.post(
            "/api/v1/webhooks/alertmanager",
            content=raw_body,
            headers={
                "content-type": "application/json",
                "X-Sentinel-Timestamp": timestamp,
                "X-Sentinel-Nonce": nonce,
                "X-Sentinel-Signature": f"sha256={signature}",
            },
        )

        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        incident = control_module.store.get_incident(response.json()["id"])
        assert incident is not None
        assert incident.severity is IncidentSeverity.CRITICAL
        assert incident.fingerprint == "alertmanager-fingerprint-001"

    async def test_alert_ingress_body_limit_is_enforced(self, client, monkeypatch):
        monkeypatch.setattr(control_module, "ALERT_INGRESS_MAX_BODY_BYTES", 32)
        body = json.dumps({
            "alert_source": {
                "alertmanager_id": "body-limit",
                "fingerprint": "body-limit",
                "alert_name": "Body Limit",
                "severity": "warning",
                "description": "x" * 64,
                "started_at": "2026-08-01T21:00:00Z",
            }
        }, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        response = await client.post(
            "/api/incidents",
            content=body,
            headers={
                "X-Sentinel-Timestamp": timestamp,
                "X-Sentinel-Nonce": "body-limit",
                "X-Sentinel-Signature": "sha256=" + hmac.new(
                    b"test-alert-ingress-secret",
                    timestamp.encode() + b"\nbody-limit\n" + body,
                    hashlib.sha256,
                ).hexdigest(),
            },
        )

        assert response.status_code == 413

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
                "X-Sentinel-Nonce": "invalid-signature-nonce",
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

    async def test_alert_ingress_rejects_replayed_nonce(self, client):
        payload = {
            "alert_source": {
                "alertmanager_id": "replay-test",
                "fingerprint": "fp-replay",
                "alert_name": "Replay Test",
                "severity": "warning",
                "description": "replayed alert",
                "started_at": "2026-08-01T21:00:00Z",
            }
        }
        timestamp = str(int(time.time()))
        nonce = "replay-nonce"
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(
            b"test-alert-ingress-secret",
            timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Sentinel-Timestamp": timestamp,
            "X-Sentinel-Nonce": nonce,
            "X-Sentinel-Signature": f"sha256={signature}",
        }
        first = await client.post("/api/incidents", headers=headers, content=body)
        second = await client.post("/api/incidents", headers=headers, content=body)
        assert first.status_code == 201
        assert second.status_code == 401
        assert "重放" in second.json()["detail"]

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

    async def test_overview_does_not_invent_missing_diagnosis_or_verification(self, client):
        created = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "test-overview-empty",
                "fingerprint": "fp-overview-empty",
                "alert_name": "Overview Empty",
                "severity": "warning",
                "description": "Only alert context is available",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })

        response = await client.get(f"/api/incidents/{created.json()['id']}")

        assert response.status_code == 200
        overview = response.json()
        assert overview["top_hypothesis"] is None
        assert overview["latest_verification"] is None
        assert [milestone["phase"] for milestone in overview["milestones"]] == ["detect"]

    async def test_viewer_cannot_decide_pending_approval(self, client):
        started = await client.post(
            "/api/scenarios/inventory-latched-5xx@1/run",
            headers={"X-Sentinel-Role": "scenario_operator"},
        )

        response = await client.get(f"/api/incidents/{started.json()['incident_id']}")

        assert response.status_code == 200
        capabilities = response.json()["capabilities"]
        assert capabilities["can_decide_approval"] is False
        assert capabilities["can_view_raw_evidence"] is False
        assert capabilities["denial_reason"] == "当前角色不能提交审批决定"

        operator_response = await client.get(
            f"/api/incidents/{started.json()['incident_id']}",
            headers={"X-Sentinel-Role": "scenario_operator"},
        )
        assert operator_response.json()["capabilities"]["can_view_raw_evidence"] is True


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
            "plan_hash": compute_plan_hash("restart_deployment@1", "payment-api", {}, incident_id),
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
            "plan_hash": compute_plan_hash("scale_deployment@1", "inventory-api", {"replicas": 5}, incident_id),
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
                "plan_hash": compute_plan_hash("restart_deployment@1", "payment-api", {}, incident_id),
                "hypothesis_id": "hyp-role",
            },
        )
        approval_id = approval_resp.json()["id"]
        denied = await client.put(
            f"/api/incidents/{incident_id}/approvals/{approval_id}",
            json={"approved": True, "reason": "证据充分"},
        )
        assert denied.status_code == 403

    async def test_approval_rejects_plan_hash_tampering(self, client):
        create_resp = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "test-hash-tamper",
                "fingerprint": "fp-hash-tamper",
                "alert_name": "Hash Tamper Test",
                "severity": "warning",
                "description": "Test",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })
        incident_id = create_resp.json()["id"]
        response = await client.post(
            f"/api/incidents/{incident_id}/approvals",
            headers=self.planner_headers,
            json={
                "plan_id": "plan-hash-tamper",
                "runbook_ref": "restart_deployment@1",
                "target": "payment-api",
                "parameters": {},
                "risk_level": "R1",
                "plan_hash": "tampered-plan-hash-0000",
                "hypothesis_id": "hyp-hash-tamper",
            },
        )
        assert response.status_code == 409
        assert "plan hash" in response.json()["detail"]

    async def test_approval_rejects_target_outside_policy(self, client):
        create_resp = await client.post("/api/incidents", json={
            "alert_source": {
                "alertmanager_id": "test-target-policy",
                "fingerprint": "fp-target-policy",
                "alert_name": "Target Policy Test",
                "severity": "warning",
                "description": "Test",
                "started_at": "2026-08-01T21:00:00Z",
            }
        })
        incident_id = create_resp.json()["id"]
        parameters = {}
        response = await client.post(
            f"/api/incidents/{incident_id}/approvals",
            headers=self.planner_headers,
            json={
                "plan_id": "plan-target-policy",
                "runbook_ref": "restart_deployment@1",
                "target": "untrusted-api",
                "parameters": parameters,
                "risk_level": "R1",
                "plan_hash": compute_plan_hash(
                    "restart_deployment@1", "untrusted-api", parameters, incident_id
                ),
                "hypothesis_id": "hyp-target-policy",
            },
        )
        assert response.status_code == 409
        assert "合法目标" in response.json()["detail"]

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
                "plan_hash": compute_plan_hash("restart_deployment@1", "payment-api", {}, first.json()["id"]), "hypothesis_id": "hyp-mismatch",
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
        response = await client.post("/api/scenarios/inventory-latched-5xx@1/run", headers={"X-Sentinel-Role": "scenario_operator"})
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
    async def test_control_api_reuses_shared_incident_enums(self):
        assert control_module.IncidentStatus is IncidentStatus
        assert control_module.RiskLevel is RiskLevel
        assert control_module.IncidentSeverity is IncidentSeverity

    async def test_list_scenarios_projects_yaml_source_without_ground_truth(self, client):
        response = await client.get("/api/scenarios")
        assert response.status_code == 200
        items = response.json()["items"]
        definitions = ScenarioLoader(control_module.SCENARIOS_DIR).load_all()

        assert {item["id"] for item in items} == {definition.id for definition in definitions}
        payment_capacity = next(item for item in items if item["id"] == "payment-capacity-latency@1")
        payment_capacity_definition = next(
            definition for definition in definitions if definition.id == "payment-capacity-latency@1"
        )
        assert payment_capacity["description"] == payment_capacity_definition.description
        assert payment_capacity["target_service"] == "payment-api"
        assert payment_capacity["target_namespace"] == "demo-shop"
        assert "ground_truth" not in payment_capacity
        assert payment_capacity_definition.ground_truth not in response.text

    async def test_run_scenario_requires_operator_role(self, client):
        response = await client.post("/api/scenarios/payment-pod-crash@1/run")
        assert response.status_code == 403

    async def test_run_scenario_uses_yaml_fault_target_without_leaking_ground_truth(self, client):
        definition = ScenarioLoader(control_module.SCENARIOS_DIR).get("payment-capacity-latency@1")
        assert definition is not None

        response = await client.post(
            "/api/scenarios/payment-capacity-latency@1/run",
            headers={"X-Sentinel-Role": "scenario_operator"},
        )

        assert response.status_code == 202
        incident_id = response.json()["incident_id"]
        timeline = (await client.get(f"/api/incidents/{incident_id}/timeline")).json()["events"]
        scenario_started = next(
            event for event in timeline if event["event_type"] == "scenario.started"
        )
        assert scenario_started["payload"]["target"] == "payment-api"
        assert scenario_started["payload"]["target_namespace"] == "demo-shop"

        approvals = (await client.get(f"/api/incidents/{incident_id}/approvals")).json()["items"]
        assert approvals[0]["target"] == "payment-api"
        public_payload = "".join([
            response.text,
            json.dumps(timeline, ensure_ascii=False),
            (await client.get(f"/api/incidents/{incident_id}")).text,
            (await client.get(f"/api/incidents/{incident_id}/approvals")).text,
        ])
        assert definition.ground_truth not in public_payload

    async def test_run_unknown_scenario_returns_not_found(self, client):
        response = await client.post(
            "/api/scenarios/unknown-scenario@1/run",
            headers={"X-Sentinel-Role": "scenario_operator"},
        )

        assert response.status_code == 404
        assert "ground_truth" not in response.text

    async def test_run_scenario_creates_incident_and_approval(self, client):
        response = await client.post("/api/scenarios/inventory-latched-5xx@1/run", headers={"X-Sentinel-Role": "scenario_operator"})
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "AWAITING_APPROVAL"

        incident_id = data["incident_id"]
        checkpoint = control_module.store.get_workflow_checkpoint(incident_id)
        assert checkpoint is not None
        assert checkpoint["phase"] == "awaiting_approval"
        assert checkpoint["completed"] is False
        incident_response = await client.get(f"/api/incidents/{incident_id}")
        assert incident_response.status_code == 200

        timeline_response = await client.get(f"/api/incidents/{incident_id}/timeline")
        event_types = {event["event_type"] for event in timeline_response.json()["events"]}
        assert {"scenario.started", "evidence.collected", "hypothesis.generated"} <= event_types

        approvals_response = await client.get(f"/api/incidents/{incident_id}/approvals")
        approvals = approvals_response.json()["items"]
        assert len(approvals) == 1
        assert approvals[0]["runbook_ref"] == "restart_deployment@1"
        assert approvals[0]["plan_hash"] == compute_plan_hash(
            approvals[0]["runbook_ref"],
            approvals[0]["target"],
            approvals[0]["parameters"],
            incident_id,
        )

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

    async def test_incident_overview_exposes_pending_decision_context(self, client):
        started = await client.post(
            "/api/scenarios/inventory-latched-5xx@1/run",
            headers={"X-Sentinel-Role": "scenario_operator"},
        )
        incident_id = started.json()["incident_id"]

        response = await client.get(
            f"/api/incidents/{incident_id}",
            headers={"X-Sentinel-Role": "approver"},
        )

        assert response.status_code == 200
        overview = response.json()
        assert overview["id"] == incident_id
        assert overview["status"] == "AWAITING_APPROVAL"
        assert overview["environment"] == {
            "profile": "light",
            "data_scope": "exercise",
            "source_mode": "fixture",
        }
        assert overview["next_decision"]["kind"] == "review_approval"
        assert overview["active_approval"]["runbook_ref"] == "restart_deployment@1"
        assert overview["capabilities"]["can_decide_approval"] is True
        assert [milestone["phase"] for milestone in overview["milestones"]] == [
            "detect",
            "investigate",
            "plan",
            "approve",
        ]

    async def test_resolved_overview_exposes_fixture_verification(self, client):
        started = await client.post(
            "/api/scenarios/payment-pod-crash@1/run",
            headers={"X-Sentinel-Role": "scenario_operator"},
        )
        incident_id = started.json()["incident_id"]

        response = await client.get(f"/api/incidents/{incident_id}")

        assert response.status_code == 200
        overview = response.json()
        assert overview["status"] == "RESOLVED"
        assert overview["next_decision"]["kind"] == "review_verification"
        assert overview["impact"]["source_mode"] == "fixture"
        assert overview["top_hypothesis"]["source_mode"] == "fixture"
        assert overview["latest_verification"] == {
            "passed": True,
            "window_seconds": 60,
            "recovery_actor": "verification_fixture",
            "source_mode": "fixture",
        }

        timeline = (await client.get(f"/api/incidents/{incident_id}/timeline")).json()["events"]
        transitions = [
            event["payload"]["to"]
            for event in timeline
            if event["event_type"] == "incident.status_changed"
        ]
        assert transitions == ["TRIAGING", "DIAGNOSING", "VERIFYING", "RESOLVED"]
        assert "PLAN_PROPOSED" not in transitions

    async def test_escalated_overview_marks_last_real_phase_failed(self, client):
        started = await client.post(
            "/api/scenarios/payment-bad-deployment@1/run",
            headers={"X-Sentinel-Role": "scenario_operator"},
        )
        incident_id = started.json()["incident_id"]

        response = await client.get(f"/api/incidents/{incident_id}")

        assert response.status_code == 200
        overview = response.json()
        assert overview["status"] == "ESCALATED"
        assert overview["next_decision"]["kind"] == "escalated"
        assert overview["milestones"][-1]["phase"] == "plan"
        assert overview["milestones"][-1]["state"] == "failed"

    @pytest.mark.parametrize(
        ("scenario_id", "expected_status", "expects_plan", "expected_reason"),
        [
            ("payment-pod-crash@1", "RESOLVED", False, None),
            ("payment-capacity-latency@1", "AWAITING_APPROVAL", True, None),
            ("inventory-latched-5xx@1", "AWAITING_APPROVAL", True, None),
            ("inventory-redis-timeout@1", "ESCALATED", False, "没有允许的自动恢复动作"),
            ("order-database-lock@1", "ESCALATED", False, "没有允许的自动恢复动作"),
            ("payment-bad-deployment@1", "ESCALATED", True, "R2"),
        ],
    )
    async def test_six_catalog_scenarios_follow_explicit_local_policy_branches(
        self,
        client,
        scenario_id,
        expected_status,
        expects_plan,
        expected_reason,
    ):
        started = await client.post(
            f"/api/scenarios/{scenario_id}/run",
            headers={"X-Sentinel-Role": "scenario_operator"},
        )

        assert started.status_code == 202
        assert started.json()["status"] == expected_status
        incident_id = started.json()["incident_id"]
        timeline = (await client.get(f"/api/incidents/{incident_id}/timeline")).json()["events"]
        transitions = [
            event["payload"]["to"]
            for event in timeline
            if event["event_type"] == "incident.status_changed"
        ]

        assert ("PLAN_PROPOSED" in transitions) is expects_plan
        if expected_reason is not None:
            assert expected_reason in str(timeline)


@pytest.mark.asyncio
class TestDemoSeed:
    async def test_seed_demo_data(self, client):
        response = await client.post("/api/demo/seed")
        assert response.status_code == 201
        data = response.json()
        assert "已创建" in data["message"]
