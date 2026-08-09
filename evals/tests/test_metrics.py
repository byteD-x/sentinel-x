"""评测指标契约测试。"""

from sentinel_x_evals.metrics import (
    COST_METRICS,
    RECOVERY_METRICS,
    SAFETY_METRICS,
    EvalCategory,
    EvalMetric,
    MetricDirection,
)


def test_lower_is_better_metric_passes_below_target():
    metric = EvalMetric(
        name="time_to_diagnose_sec",
        category=EvalCategory.RECOVERY,
        value=120.0,
        unit="s",
        target=180.0,
        direction=MetricDirection.LOWER_IS_BETTER,
    )

    assert metric.meets_target() is True


def test_predefined_time_metrics_are_lower_is_better():
    time_metrics = [metric for metric in RECOVERY_METRICS if metric.name.startswith("time_to_")]

    assert time_metrics
    assert all(metric.direction == MetricDirection.LOWER_IS_BETTER for metric in time_metrics)


def test_predefined_bounded_metrics_are_lower_is_better():
    bounded_names = {
        "safety_violations",
        "tokens_consumed",
        "llm_calls_per_incident",
        "total_cost_estimate",
    }
    bounded_metrics = [
        metric for metric in [*SAFETY_METRICS, *COST_METRICS] if metric.name in bounded_names
    ]

    assert {metric.name for metric in bounded_metrics} == bounded_names
    assert all(metric.direction == MetricDirection.LOWER_IS_BETTER for metric in bounded_metrics)


def test_lower_is_better_metric_fails_above_target():
    metric = EvalMetric(
        name="time_to_diagnose_sec",
        category=EvalCategory.RECOVERY,
        value=181.0,
        unit="s",
        target=180.0,
        direction=MetricDirection.LOWER_IS_BETTER,
    )

    assert metric.meets_target() is False


def test_evaluate_records_target_result():
    metric = EvalMetric(
        name="top1_accuracy",
        category=EvalCategory.DIAGNOSIS,
        value=75.0,
        unit="%",
        target=60.0,
    )

    assert metric.passed is None
    assert metric.evaluate() is True
    assert metric.passed is True


def test_metric_at_target_passes_for_both_directions():
    for direction in MetricDirection:
        metric = EvalMetric(
            name="boundary",
            category=EvalCategory.RESOURCE,
            value=10.0,
            unit="count",
            target=10.0,
            direction=direction,
        )
        assert metric.meets_target() is True


def test_metric_without_target_is_not_evaluated():
    metric = EvalMetric(
        name="descriptive_only",
        category=EvalCategory.RESOURCE,
        value=10.0,
        unit="count",
    )

    assert metric.evaluate() is None
    assert metric.passed is None
