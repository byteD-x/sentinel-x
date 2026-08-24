"""六场景本地 fixture 评测适配器的确定性验收测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from demo.scenarios.loader import ScenarioLoader
from sentinel_x_contracts.scenario import ScenarioDefinition
from sentinel_x_evals.local_fixture import (
    LocalFixtureScenarioEvaluator,
    LocalFixtureUnknownScenarioError,
    RecoveryDisposition,
)
from sentinel_x_evals.runner import EvalConfig


STANDARD_SCENARIO_IDS = {
    "payment-pod-crash@1",
    "payment-capacity-latency@1",
    "inventory-latched-5xx@1",
    "inventory-redis-timeout@1",
    "order-database-lock@1",
    "payment-bad-deployment@1",
}


@pytest.fixture
def evaluator() -> LocalFixtureScenarioEvaluator:
    repository_root = Path(__file__).resolve().parents[2]
    loader = ScenarioLoader(repository_root / "demo" / "scenarios")
    return LocalFixtureScenarioEvaluator(loader)


@pytest.mark.asyncio
async def test_local_fixture_evaluator_covers_the_exact_six_yaml_scenarios(
    evaluator: LocalFixtureScenarioEvaluator,
) -> None:
    observations = [
        await evaluator.execute(scenario_id, run_index=0, config=EvalConfig(model_name="fixture"))
        for scenario_id in sorted(STANDARD_SCENARIO_IDS)
    ]

    assert {observation.scenario_id for observation in observations} == STANDARD_SCENARIO_IDS
    assert {observation.root_cause_prediction for observation in observations} == {
        "WORKLOAD_UNAVAILABLE",
        "CAPACITY_EXHAUSTION",
        "LATCHED_RUNTIME_FAILURE",
        "CACHE_TIMEOUT",
        "DATABASE_LOCK_CONTENTION",
        "BAD_DEPLOYMENT",
    }
    assert {observation.evaluator_kind for observation in observations} == {"local_fixture"}
    assert all(observation.started_at.tzinfo is not None for observation in observations)


@pytest.mark.asyncio
async def test_local_fixture_never_reads_or_exposes_human_ground_truth(
    evaluator: LocalFixtureScenarioEvaluator, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_getattribute = ScenarioDefinition.__getattribute__

    def forbid_ground_truth(self: ScenarioDefinition, name: str):
        if name == "ground_truth":
            raise AssertionError("fixture evaluator must not read YAML answer text")
        return original_getattribute(self, name)

    monkeypatch.setattr(ScenarioDefinition, "__getattribute__", forbid_ground_truth)
    first = await evaluator.execute(
        "inventory-latched-5xx@1", run_index=0, config=EvalConfig(model_name="fixture")
    )
    repeated = await evaluator.execute(
        "inventory-latched-5xx@1", run_index=0, config=EvalConfig(model_name="fixture")
    )

    assert first == repeated
    assert first.root_cause_prediction == "LATCHED_RUNTIME_FAILURE"
    assert first.ground_truth_root_cause == "LATCHED_RUNTIME_FAILURE"
    assert "inventory-api" not in repr(first)


@pytest.mark.asyncio
async def test_r1_allowlisted_scenarios_require_approval(
    evaluator: LocalFixtureScenarioEvaluator,
) -> None:
    observations = {
        scenario_id: await evaluator.execute(scenario_id, run_index=1, config=EvalConfig(model_name="fixture"))
        for scenario_id in ("payment-capacity-latency@1", "inventory-latched-5xx@1")
    }

    assert observations["payment-capacity-latency@1"].selected_runbook == "scale_deployment@1"
    assert observations["inventory-latched-5xx@1"].selected_runbook == "restart_deployment@1"
    assert {
        observation.recovery_disposition for observation in observations.values()
    } == {RecoveryDisposition.AWAITING_R1_APPROVAL}
    assert all(not observation.needs_human_escalation for observation in observations.values())


@pytest.mark.asyncio
async def test_pod_crash_is_observed_as_no_action_automatic_recovery(
    evaluator: LocalFixtureScenarioEvaluator,
) -> None:
    observation = await evaluator.execute(
        "payment-pod-crash@1", run_index=0, config=EvalConfig(model_name="fixture")
    )

    assert observation.selected_runbook == "no_op"
    assert observation.recovery_disposition == RecoveryDisposition.AUTO_RECOVERY
    assert observation.needs_human_escalation is False


@pytest.mark.asyncio
async def test_non_r1_scenarios_escalate_without_authorized_recovery(
    evaluator: LocalFixtureScenarioEvaluator,
) -> None:
    observations = {
        scenario_id: await evaluator.execute(scenario_id, run_index=0, config=EvalConfig(model_name="fixture"))
        for scenario_id in (
            "inventory-redis-timeout@1",
            "order-database-lock@1",
            "payment-bad-deployment@1",
        )
    }

    assert all(
        observation.recovery_disposition == RecoveryDisposition.HUMAN_ESCALATION
        for observation in observations.values()
    )
    assert all(observation.needs_human_escalation for observation in observations.values())
    assert observations["inventory-redis-timeout@1"].selected_runbook is None
    assert observations["order-database-lock@1"].selected_runbook is None
    assert observations["payment-bad-deployment@1"].selected_runbook == "rollback_deployment@1"


@pytest.mark.asyncio
async def test_unknown_scenario_is_rejected(evaluator: LocalFixtureScenarioEvaluator) -> None:
    with pytest.raises(LocalFixtureUnknownScenarioError, match="unknown-scenario@1"):
        await evaluator.execute("unknown-scenario@1", run_index=0, config=EvalConfig(model_name="fixture"))
