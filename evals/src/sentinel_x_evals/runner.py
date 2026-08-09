"""
评测运行器 — 在固定配置下运行场景并收集指标。

设计原则：
- 可复现：固定配置、固定环境、固定协议
- 隔离：dev/calibration/holdout 数据集分离
- 不删除失败样本：记录所有失败用于分析
"""

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

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
        report = await runner.run_scenarios(["payment-latency@1", "order-db-errors@1"])
        print(report.to_markdown())
    """

    def __init__(self, config: EvalConfig, executor: ScenarioExecutor):
        if executor is None:
            raise ValueError("必须提供真实 ScenarioExecutor，禁止使用模拟评测数据")
        self.config = config
        self.executor = executor
        self.report = EvalReport(
            report_id=f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
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
            incident_id=observation.incident_id,
            model_name=self.config.model_name,
            config={
                "dataset": self.config.dataset,
                "seed": self.config.random_seed,
            },
            metrics=metrics,
            raw_report=asdict(observation),
        )


def save_eval_report(report: EvalReport, output_dir: str = "evals/results") -> str:
    """保存评测报告。"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # JSON 原始数据
    json_path = output_path / f"{report.report_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "report_id": report.report_id,
            "failures": report.failures,
            "runs": [
                {
                    "run_id": r.run_id,
                    "scenario": r.scenario_name,
                    "model": r.model_name,
                    "metrics": [
                        {"name": m.name, "value": m.value, "unit": m.unit, "passed": m.passed}
                        for m in r.metrics
                    ],
                }
                for r in report.runs
            ],
        }, f, ensure_ascii=False, indent=2)

    # Markdown 摘要
    md_path = output_path / f"{report.report_id}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report.to_markdown())

    return str(md_path)
