"""确定性评测运行器测试。"""

import json
from datetime import datetime, timedelta

import pytest

from sentinel_x_evals.runner import (
    EvalConfig,
    EvalRunner,
    ScenarioObservation,
    save_eval_report,
)


@pytest.mark.asyncio
async def test_runner_calculates_metrics_from_explicit_observation():
    started_at = datetime(2026, 8, 9, 10, 0, 0)

    async def execute_scenario(_scenario_name, _run_index, _config):
        return ScenarioObservation(
            incident_id="incident-001",
            root_cause_prediction="LATCHED_RUNTIME_FAILURE:inventory-api",
            ground_truth_root_cause="LATCHED_RUNTIME_FAILURE:inventory-api",
            started_at=started_at,
            diagnosed_at=started_at + timedelta(seconds=45),
            safety_violations=0,
            tokens_consumed=640,
        )

    runner = EvalRunner(
        EvalConfig(model_name="investigator-v1", runs_per_scenario=1),
        executor=execute_scenario,
    )
    report = await runner.run_scenarios(["inventory-latched-5xx@1"])

    metrics = {metric.name: metric.value for metric in report.runs[0].metrics}
    assert metrics == {
        "top1_accuracy": 100.0,
        "time_to_diagnose_sec": 45.0,
        "safety_violations": 0.0,
        "tokens_consumed": 640.0,
    }


@pytest.mark.asyncio
async def test_runner_preserves_executor_failure():
    async def execute_scenario(_scenario_name, _run_index, _config):
        raise RuntimeError("diagnostic gateway unavailable")

    runner = EvalRunner(
        EvalConfig(model_name="investigator-v1", runs_per_scenario=1),
        executor=execute_scenario,
    )
    report = await runner.run_scenarios(["inventory-latched-5xx@1"])

    assert report.runs == []
    assert report.failures == [
        {
            "scenario": "inventory-latched-5xx@1",
            "run_index": 0,
            "category": "system",
            "reason": "diagnostic gateway unavailable",
        }
    ]


@pytest.mark.asyncio
async def test_runner_rejects_observation_with_negative_diagnosis_duration():
    started_at = datetime(2026, 8, 9, 10, 0, 0)

    async def execute_scenario(_scenario_name, _run_index, _config):
        return ScenarioObservation(
            incident_id="incident-invalid-time",
            root_cause_prediction="unknown",
            ground_truth_root_cause="LATCHED_RUNTIME_FAILURE:inventory-api",
            started_at=started_at,
            diagnosed_at=started_at - timedelta(seconds=1),
            safety_violations=0,
            tokens_consumed=0,
        )

    runner = EvalRunner(
        EvalConfig(model_name="investigator-v1", runs_per_scenario=1),
        executor=execute_scenario,
    )
    report = await runner.run_scenarios(["inventory-latched-5xx@1"])

    assert report.runs == []
    assert report.failures[0]["reason"] == "diagnosed_at 不能早于 started_at"


def test_runner_requires_explicit_executor():
    with pytest.raises(ValueError, match="ScenarioExecutor"):
        EvalRunner(EvalConfig(model_name="investigator-v1"), executor=None)


@pytest.mark.asyncio
async def test_saved_report_preserves_executor_failure(tmp_path):
    async def execute_scenario(_scenario_name, _run_index, _config):
        raise RuntimeError("scenario injection failed")

    runner = EvalRunner(
        EvalConfig(model_name="investigator-v1", runs_per_scenario=1),
        executor=execute_scenario,
    )
    report = await runner.run_scenarios(["inventory-latched-5xx@1"])

    save_eval_report(report, str(tmp_path))
    raw_report = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert raw_report["failures"] == report.failures


@pytest.mark.asyncio
async def test_same_observation_produces_same_metrics():
    started_at = datetime(2026, 8, 9, 10, 0, 0)
    observation = ScenarioObservation(
        incident_id="incident-repeatable",
        root_cause_prediction="LATCHED_RUNTIME_FAILURE:inventory-api",
        ground_truth_root_cause="LATCHED_RUNTIME_FAILURE:inventory-api",
        started_at=started_at,
        diagnosed_at=started_at + timedelta(seconds=30),
        safety_violations=0,
        tokens_consumed=512,
    )

    async def execute_scenario(_scenario_name, _run_index, _config):
        return observation

    runner = EvalRunner(
        EvalConfig(model_name="investigator-v1", runs_per_scenario=2),
        executor=execute_scenario,
    )
    report = await runner.run_scenarios(["inventory-latched-5xx@1"])

    metric_sets = [
        [(metric.name, metric.value, metric.passed) for metric in run.metrics]
        for run in report.runs
    ]
    assert metric_sets[0] == metric_sets[1]
