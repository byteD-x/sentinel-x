import pytest

from sentinel_x_incident_worker.activities import (
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
    with pytest.raises(RuntimeError, match="SLO observation adapter"):
        await verify_slo_recovery("inventory-api", observed_p99_samples=[100.0])
