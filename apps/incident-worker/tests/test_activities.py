import pytest

from sentinel_x_incident_worker.activities import (
    collect_k8s_pod_status,
    collect_prometheus_evidence,
    submit_action_to_gateway,
    verify_slo_recovery,
)


@pytest.mark.asyncio
async def test_slo_verification_requires_observed_samples():
    result = await verify_slo_recovery("inventory-api")

    assert result["recovered"] is False
    assert result["failure_reason"] == "观测窗口无数据"


@pytest.mark.asyncio
async def test_slo_verification_rejects_insufficient_window():
    result = await verify_slo_recovery(
        "inventory-api",
        observed_window_minutes=10,
        observed_p99_samples=[150.0],
        minimum_samples=2,
    )

    assert result["recovered"] is False
    assert result["failure_reason"] == "观测样本不足"


@pytest.mark.asyncio
async def test_slo_verification_requires_all_samples_within_threshold():
    recovered = await verify_slo_recovery(
        "inventory-api",
        target_p99_ms=200.0,
        observed_p99_samples=[150.0, 180.0],
        minimum_samples=2,
    )
    degraded = await verify_slo_recovery(
        "inventory-api",
        target_p99_ms=200.0,
        observed_p99_samples=[150.0, 240.0],
        minimum_samples=2,
    )

    assert recovered["recovered"] is True
    assert recovered["observed_p99_ms"] == 180.0
    assert degraded["recovered"] is False
    assert degraded["failure_reason"] == "观测窗口超过 SLO 阈值"


@pytest.mark.asyncio
async def test_full_profile_refuses_synthetic_observation_and_action(monkeypatch):
    monkeypatch.setenv("SENTINEL_PROFILE", "full")

    with pytest.raises(RuntimeError, match="Prometheus adapter"):
        await collect_prometheus_evidence("up")
    with pytest.raises(RuntimeError, match="Action Gateway adapter"):
        await submit_action_to_gateway(
            "http://gateway",
            "restart_deployment@1",
            "inventory-api",
            {},
            "idempotency-key-1234",
            "approval-token",
        )
    with pytest.raises(RuntimeError, match="Prometheus adapter"):
        await verify_slo_recovery("inventory-api", observed_p99_samples=[100.0])


@pytest.mark.asyncio
async def test_full_profile_uses_configured_telemetry_source(monkeypatch):
    monkeypatch.setenv("SENTINEL_PROFILE", "full")
    monkeypatch.setenv("PROMETHEUS_BASE_URL", "http://prometheus")
    monkeypatch.setenv("LOKI_BASE_URL", "http://loki")
    monkeypatch.setenv("TEMPO_BASE_URL", "http://tempo")
    from sentinel_x_incident_worker import activities
    from sentinel_x_diagnostics import DiagnosticToolType
    from sentinel_x_diagnostics.sources import TelemetryResponse

    def fake_query(self, tool, params):
        assert tool is DiagnosticToolType.QUERY_PROMETHEUS
        assert params["query"] == "up"
        return TelemetryResponse(
            payload={"status": "success", "data": {"result": []}},
            source_ref="query_prometheus://configured",
        )

    monkeypatch.setattr(activities.HttpTelemetrySource, "query", fake_query)
    result = await collect_prometheus_evidence("up")
    assert result["source_mode"] == "observed"
    assert result["source_ref"] == "query_prometheus://configured"


@pytest.mark.asyncio
async def test_full_profile_slo_uses_prometheus_samples(monkeypatch):
    monkeypatch.setenv("SENTINEL_PROFILE", "full")
    monkeypatch.setenv("PROMETHEUS_BASE_URL", "http://prometheus")
    monkeypatch.setenv("LOKI_BASE_URL", "http://loki")
    monkeypatch.setenv("TEMPO_BASE_URL", "http://tempo")
    from sentinel_x_incident_worker import activities
    from sentinel_x_diagnostics.sources import TelemetryResponse

    def fake_query(self, _tool, _params):
        return TelemetryResponse(
            payload={"status": "success", "data": {"result": [{"value": [1, "0.18"]}]}},
            source_ref="query_prometheus://configured",
        )

    monkeypatch.setattr(activities.HttpTelemetrySource, "query", fake_query)
    result = await verify_slo_recovery("inventory-api", target_p99_ms=200.0)
    assert result["recovered"] is True
    assert result["observed_p99_ms"] == 180.0
    assert result["sample_count"] == 1


@pytest.mark.asyncio
async def test_full_profile_action_activity_calls_gateway(monkeypatch):
    monkeypatch.setenv("SENTINEL_PROFILE", "full")
    monkeypatch.setenv("SENTINEL_SERVICE_IDENTITY_SECRET", "service-secret")
    from sentinel_x_incident_worker import activities

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return b'{"execution_id":"exec-1","status":"succeeded"}'

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://gateway/api/actions"
        assert request.get_header("X-sentinel-service-name") == "control-api"
        assert timeout == 120
        return Response()

    monkeypatch.setattr(activities, "urlopen", fake_urlopen)
    result = await submit_action_to_gateway(
        "http://gateway", "restart_deployment@1", "inventory-api", {},
        "action-idempotency-001", "approval-token", approval_id="approval-1",
        plan_hash="plan-hash-123456", incident_id="incident-1",
        approval_expires_at="2026-08-25T23:30:00+00:00",
        target_identity={"namespace": "demo-shop", "kind": "Deployment", "name": "inventory-api", "uid": "uid-1", "generation": 1},
    )
    assert result["execution_id"] == "exec-1"


@pytest.mark.asyncio
async def test_full_profile_kubernetes_activity_reads_pod_list(monkeypatch):
    monkeypatch.setenv("SENTINEL_PROFILE", "full")
    monkeypatch.setenv("KUBERNETES_API_URL", "https://kubernetes.local")
    monkeypatch.setenv("KUBERNETES_SERVICEACCOUNT_TOKEN", "token")
    from sentinel_x_incident_worker import activities

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return b'{"kind":"PodList","items":[{"status":{"phase":"Running"}},{"status":{"phase":"Pending"}}]}'

    def fake_urlopen(request, timeout):
        assert request.full_url.endswith("/api/v1/namespaces/demo-shop/pods")
        assert request.get_header("Authorization") == "Bearer token"
        assert timeout == 3.0
        return Response()

    monkeypatch.setattr(activities, "urlopen", fake_urlopen)
    result = await collect_k8s_pod_status()
    assert result["source_mode"] == "observed"
    assert result["pod_count"] == 2
    assert result["phase_counts"] == {"Running": 1, "Pending": 1}
