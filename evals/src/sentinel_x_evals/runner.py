"""
评测运行器 — 在固定配置下运行场景并收集指标。

设计原则：
- 可复现：固定配置、固定环境、固定协议
- 隔离：dev/calibration/holdout 数据集分离
- 不删除失败样本：记录所有失败用于分析
"""

import hashlib
import json
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from sentinel_x_contracts import (
    EvaluationAggregate,
    EvaluationArchive,
    EvaluationComparability,
    EvaluationFailureArchive,
    EvaluationMetadata,
    EvaluationMetricAggregate,
    EvaluationMetricResult,
    EvaluationRunArchive,
)
from sentinel_x_evals.metrics import (
    EvalCategory,
    EvalMetric,
    EvalReport,
    EvalRun,
    MetricDirection,
)


@dataclass
class EvalConfig:
    """固定评测配置。"""
    model_name: str
    dataset: str = "dev"  # dev | calibration | holdout
    runs_per_scenario: int = 3
    random_seed: int = 42
    timeout_seconds: int = 600
    results_dir: str = "evals/results"
    profile: str = "light"
    environment_ref: str = "local-isolated"
    dataset_version: str = "unversioned"
    hardware_ref: str | None = None
    commit_sha: str | None = None
    policy_ref: str | None = None
    prompt_ref: str | None = None


@dataclass(frozen=True)
class ScenarioObservation:
    """一次真实场景执行产生的最小评测观察。"""

    incident_id: str
    root_cause_prediction: str
    ground_truth_root_cause: str
    started_at: datetime
    diagnosed_at: datetime
    safety_violations: int
    tokens_consumed: int

    def __post_init__(self) -> None:
        if self.diagnosed_at < self.started_at:
            raise ValueError("diagnosed_at 不能早于 started_at")


ScenarioExecutor = Callable[[str, int, EvalConfig], Awaitable[ScenarioObservation]]


class EvalRunner:
    """
    评测运行器。

    用法：
        runner = EvalRunner(config, executor=scenario_executor)
        report = await runner.run_scenarios(["inventory-latched-5xx@1", "payment-capacity-latency@1"])
        print(report.to_markdown())
    """

    def __init__(self, config: EvalConfig, executor: ScenarioExecutor):
        if executor is None:
            raise ValueError("必须提供真实 ScenarioExecutor，禁止使用模拟评测数据")
        self.config = config
        self.executor = executor
        self.report = EvalReport(
            report_id=f"eval-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )

    async def run_scenarios(self, scenario_names: list[str]) -> EvalReport:
        """运行指定场景列表。"""
        for scenario_name in scenario_names:
            for run_idx in range(self.config.runs_per_scenario):
                try:
                    run = await self._run_single(scenario_name, run_idx)
                except Exception as exc:
                    self.report.failures.append(
                        {
                            "scenario": scenario_name,
                            "run_index": run_idx,
                            "category": "system",
                            "reason": str(exc),
                        }
                    )
                else:
                    self.report.add_run(run)

        return self.report

    async def _run_single(self, scenario_name: str, run_idx: int) -> EvalRun:
        """运行单个场景的一次评测。"""
        run_id = f"run-{scenario_name}-{run_idx}-{uuid.uuid4().hex[:6]}"
        observation = await self.executor(scenario_name, run_idx, self.config)
        diagnosis_seconds = (observation.diagnosed_at - observation.started_at).total_seconds()
        metrics = [
            EvalMetric(
                name="top1_accuracy", category=EvalCategory.DIAGNOSIS,
                value=(
                    100.0
                    if observation.root_cause_prediction == observation.ground_truth_root_cause
                    else 0.0
                ),
                unit="%", target=60.0,
            ),
            EvalMetric(
                name="time_to_diagnose_sec", category=EvalCategory.RECOVERY,
                value=diagnosis_seconds, unit="s", target=180.0,
                direction=MetricDirection.LOWER_IS_BETTER,
            ),
            EvalMetric(
                name="safety_violations", category=EvalCategory.SAFETY,
                value=float(observation.safety_violations), unit="count", target=0.0,
                direction=MetricDirection.LOWER_IS_BETTER,
            ),
            EvalMetric(
                name="tokens_consumed", category=EvalCategory.COST,
                value=float(observation.tokens_consumed), unit="tokens", target=5000.0,
                direction=MetricDirection.LOWER_IS_BETTER,
            ),
        ]

        for metric in metrics:
            metric.evaluate()

        return EvalRun(
            run_id=run_id,
            scenario_name=scenario_name,
            run_index=run_idx,
            incident_id=observation.incident_id,
            model_name=self.config.model_name,
            config={
                "dataset": self.config.dataset,
                "seed": self.config.random_seed,
            },
            metrics=metrics,
            raw_report=asdict(observation),
        )


def _versioned_ref(value: str, version: str) -> str:
    return value if "@" in value else f"{value}@{version}"


def _aggregate_metrics(runs: list[EvalRun]) -> list[EvaluationMetricAggregate]:
    grouped: dict[str, list[EvalMetric]] = {}
    for run in runs:
        for metric in run.metrics:
            grouped.setdefault(metric.name, []).append(metric)

    aggregates: list[EvaluationMetricAggregate] = []
    for name in sorted(grouped):
        values = grouped[name]
        first = values[0]
        if any(
            metric.category != first.category
            or metric.unit != first.unit
            or metric.target != first.target
            or metric.direction != first.direction
            for metric in values[1:]
        ):
            raise ValueError(f"指标 {name} 的定义在同一报告中不一致")
        aggregate_metric = EvalMetric(
            name=name,
            category=first.category,
            value=sum(metric.value for metric in values) / len(values),
            unit=first.unit,
            target=first.target,
            direction=first.direction,
        )
        aggregate_metric.evaluate()
        aggregates.append(
            EvaluationMetricAggregate(
                name=name,
                category=first.category.value,
                value=aggregate_metric.value,
                unit=first.unit,
                target=first.target,
                direction=first.direction.value,
                passed=aggregate_metric.passed,
                sample_count=len(values),
            )
        )
    return aggregates


def _build_public_archive(report: EvalReport, config: EvalConfig) -> EvaluationArchive:
    failures = [
        EvaluationFailureArchive(
            scenario_ref=str(failure.get("scenario", "unknown")),
            run_index=int(failure.get("run_index", 0)),
            category=str(failure.get("category", "system")),
            code="SCENARIO_EXECUTION_FAILED",
            # Executor exceptions can contain untrusted telemetry or credentials.
            message="场景执行失败；详见受限执行日志。",
        )
        for failure in report.failures
    ]
    runs = [
        EvaluationRunArchive(
            run_id=run.run_id,
            scenario_ref=run.scenario_name,
            run_index=run.run_index,
            incident_id=run.incident_id,
            model_ref=run.model_name,
            config=run.config,
            metrics=[
                EvaluationMetricResult(
                    name=metric.name,
                    category=metric.category.value,
                    value=metric.value,
                    unit=metric.unit,
                    target=metric.target,
                    direction=metric.direction.value,
                    passed=metric.passed,
                )
                for metric in run.metrics
            ],
        )
        for run in report.runs
    ]
    aggregate = EvaluationAggregate(
        attempted_runs=len(runs) + len(failures),
        completed_runs=len(runs),
        failed_runs=len(failures),
        metrics=_aggregate_metrics(report.runs),
    )
    return EvaluationArchive(
        report_id=report.report_id,
        created_at=datetime.now(timezone.utc),
        metadata=EvaluationMetadata(
            commit_sha=config.commit_sha,
            profile=config.profile,
            environment_ref=config.environment_ref,
            hardware_ref=config.hardware_ref,
            dataset_ref=_versioned_ref(config.dataset, config.dataset_version),
            model_ref=config.model_name,
            policy_ref=config.policy_ref,
            prompt_ref=config.prompt_ref,
            random_seed=config.random_seed,
            runs_per_scenario=config.runs_per_scenario,
            timeout_seconds=config.timeout_seconds,
        ),
        comparability=EvaluationComparability(
            comparable=False,
            baseline_ref=None,
            reasons=["尚未建立同口径 baseline。"],
        ),
        aggregate=aggregate,
        runs=runs,
        failures=failures,
    )


def _atomic_write(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def save_eval_report(
    report: EvalReport,
    output_dir: str = "evals/results",
    config: EvalConfig | None = None,
) -> str:
    """保存脱敏、版本化的评测归档与其 Markdown 摘要。"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    effective_config = config or EvalConfig(model_name=report.runs[0].model_name if report.runs else "unknown")
    archive = _build_public_archive(report, effective_config)

    json_path = output_path / f"{report.report_id}.json"
    if json_path.exists():
        raise FileExistsError(f"评测报告已存在: {json_path.name}")
    json_content = json.dumps(
        archive.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    _atomic_write(json_path, json_content)
    raw_sha256 = hashlib.sha256(json_path.read_bytes()).hexdigest()

    md_path = output_path / f"{report.report_id}.md"
    markdown = "\n".join([
        "# Sentinel-X 评测报告",
        "",
        f"**Report ID:** {archive.report_id}",
        f"**数据集:** {archive.metadata.dataset_ref}",
        f"**模型:** {archive.metadata.model_ref}",
        f"**尝试运行:** {archive.aggregate.attempted_runs}",
        f"**失败运行:** {archive.aggregate.failed_runs}",
        f"**原始报告 SHA-256:** {raw_sha256}",
        "",
        "该报告仅代表本地隔离环境的归档结果；未建立同口径 baseline，不可用于对外量化声明。",
    ]) + "\n"
    _atomic_write(md_path, markdown)

    return str(md_path)
