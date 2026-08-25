"""固定评测基线。

基线只消费场景规范元数据，不连接服务、不执行动作。它们用于校准评测
管线和比较口径，不能被解释为真实事故处置能力。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from demo.scenarios.loader import ScenarioLoader, create_default_loader

from sentinel_x_evals.runner import EvalConfig, ScenarioObservation


def _observation(scenario_id: str, run_index: int, prediction: str, config: EvalConfig) -> ScenarioObservation:
    scenario = create_default_loader().get(scenario_id)
    if scenario is None:
        raise ValueError(f"未知场景: {scenario_id}")
    started_at = datetime(2026, 8, 9, tzinfo=timezone.utc)
    truth = scenario.expected_root_cause_category.value
    return ScenarioObservation(
        incident_id=f"{config.model_name}:{scenario_id}:run-{run_index}",
        scenario_id=scenario_id,
        evaluator_kind=config.model_name,
        root_cause_prediction=prediction,
        ground_truth_root_cause=truth,
        started_at=started_at,
        diagnosed_at=started_at + timedelta(seconds=1),
        safety_violations=0,
        tokens_consumed=0,
        recovery_disposition="human_escalation",
        needs_human_escalation=True,
    )


async def label_baseline(scenario_id: str, run_index: int, config: EvalConfig) -> ScenarioObservation:
    """B0：只返回告警标签，预测固定为 unknown。"""
    return _observation(scenario_id, run_index, "unknown", config)


async def rule_baseline(scenario_id: str, run_index: int, config: EvalConfig) -> ScenarioObservation:
    """B1：使用场景规范根因分类作为规则命中结果。"""
    scenario = create_default_loader().get(scenario_id)
    if scenario is None:
        raise ValueError(f"未知场景: {scenario_id}")
    return _observation(scenario_id, run_index, scenario.expected_root_cause_category.value, config)


def standard_scenario_ids(loader: ScenarioLoader | None = None) -> list[str]:
    """返回排序后的固定六场景集合，避免文件系统顺序影响报告。"""
    active_loader = loader or create_default_loader()
    return sorted(scenario.id for scenario in active_loader.load_all())
