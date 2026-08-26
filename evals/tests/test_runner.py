"""确定性评测运行器测试。"""

import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

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


def test_eval_config_rejects_invalid_dataset_and_small_holdout():
    with pytest.raises(ValueError, match="dataset"):
        EvalConfig(model_name="x", dataset="production")
    with pytest.raises(ValueError, match="10"):
        EvalConfig(model_name="x", dataset="holdout", runs_per_scenario=3)


def test_eval_config_fails_closed_for_dirty_or_full_fixture_environment():
    with pytest.raises(ValueError, match="dirty"):
        EvalConfig(model_name="x", dirty=True)
    with pytest.raises(ValueError, match="full profile"):
        EvalConfig(model_name="x", profile="full", source_mode="fixture")


@pytest.mark.asyncio
async def test_saved_report_preserves_executor_failure_as_a_sanitized_archive_record(tmp_path):
    async def execute_scenario(_scenario_name, _run_index, _config):
        raise RuntimeError("scenario injection failed")

    runner = EvalRunner(
        EvalConfig(model_name="investigator-v1", runs_per_scenario=1),
        executor=execute_scenario,
    )
    report = await runner.run_scenarios(["inventory-latched-5xx@1"])

    save_eval_report(report, str(tmp_path))
    raw_report = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert raw_report["aggregate"]["attempted_runs"] == 1
    assert raw_report["aggregate"]["failed_runs"] == 1
    assert raw_report["failures"] == [{
        "scenario_ref": "inventory-latched-5xx@1",
        "run_index": 0,
        "category": "system",
        "code": "SCENARIO_EXECUTION_FAILED",
        "message": "场景执行失败；详见受限执行日志。",
    }]
    assert "scenario injection failed" not in json.dumps(raw_report, ensure_ascii=False)


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


@pytest.mark.asyncio
async def test_saved_report_writes_versioned_public_archive_with_aggregate_and_hash(tmp_path):
    started_at = datetime(2026, 8, 9, 10, 0, 0)

    async def execute_scenario(_scenario_name, _run_index, _config):
        return ScenarioObservation(
            incident_id="incident-archive-001",
            root_cause_prediction="LATCHED_RUNTIME_FAILURE:inventory-api",
            ground_truth_root_cause="LATCHED_RUNTIME_FAILURE:inventory-api",
            started_at=started_at,
            diagnosed_at=started_at + timedelta(seconds=42),
            safety_violations=0,
            tokens_consumed=512,
        )

    runner = EvalRunner(
        EvalConfig(model_name="investigator-v1", runs_per_scenario=1),
        executor=execute_scenario,
    )
    report = await runner.run_scenarios(["inventory-latched-5xx@1"])

    markdown_path = save_eval_report(report, str(tmp_path))
    json_path = next(tmp_path.glob("*.json"))
    archive = json.loads(json_path.read_text(encoding="utf-8"))

    assert archive["schema_version"] == "1.0"
    assert archive["metadata"]["model_ref"] == "investigator-v1"
    assert archive["aggregate"]["attempted_runs"] == 1
    assert archive["aggregate"]["completed_runs"] == 1
    assert archive["aggregate"]["failed_runs"] == 0
    assert archive["runs"][0]["scenario_ref"] == "inventory-latched-5xx@1"
    assert "raw_report" not in archive["runs"][0]
    assert hashlib.sha256(json_path.read_bytes()).hexdigest() in Path(markdown_path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_fixture_report_is_explicitly_non_publishable_and_non_comparable(tmp_path):
    started_at = datetime(2026, 8, 9, 10, 0, 0)

    async def execute_scenario(_scenario_name, _run_index, _config):
        return ScenarioObservation(
            incident_id="incident-fixture-boundary",
            root_cause_prediction="unknown",
            ground_truth_root_cause="unknown",
            started_at=started_at,
            diagnosed_at=started_at + timedelta(seconds=1),
            safety_violations=0,
            tokens_consumed=0,
        )

    runner = EvalRunner(
        EvalConfig(
            model_name="fixture",
            profile="light-fixture",
            source_mode="fixture",
            runs_per_scenario=1,
        ),
        executor=execute_scenario,
    )
    report = await runner.run_scenarios(["inventory-latched-5xx@1"])

    save_eval_report(report, str(tmp_path), runner.config)
    archive = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))

    assert archive["report_kind"] == "light-fixture"
    assert archive["source_mode"] == "fixture"
    assert archive["publishable"] is False
    assert archive["limitations"]
    assert archive["comparability"]["comparable"] is False
    assert archive["recovery_summary"] == {
        "attempted": 1,
        "succeeded": 0,
        "escalated": 0,
        "unknown": 1,
    }
    assert archive["slo_summary"]["available"] is False
    assert archive["security_summary"] == {
        "runs_with_violations": 0,
        "total_violations": 0,
    }


@pytest.mark.asyncio
async def test_public_report_never_exposes_executor_failure_text(tmp_path):
    secret_like_text = "Authorization: Bearer should-not-be-published"

    async def execute_scenario(_scenario_name, _run_index, _config):
        raise RuntimeError(secret_like_text)

    runner = EvalRunner(
        EvalConfig(model_name="investigator-v1", runs_per_scenario=1),
        executor=execute_scenario,
    )
    report = await runner.run_scenarios(["inventory-latched-5xx@1"])

    markdown_path = save_eval_report(report, str(tmp_path), runner.config)
    archive = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))

    assert archive["aggregate"]["attempted_runs"] == 1
    assert archive["aggregate"]["failed_runs"] == 1
    assert archive["failures"][0]["message"] != secret_like_text
    assert secret_like_text not in Path(markdown_path).read_text(encoding="utf-8")
