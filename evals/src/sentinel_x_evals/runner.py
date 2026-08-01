"""
评测运行器 — 在固定配置下运行场景并收集指标。

设计原则：
- 可复现：固定配置、固定环境、固定协议
- 隔离：dev/calibration/holdout 数据集分离
- 不删除失败样本：记录所有失败用于分析
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from sentinel_x_evals.metrics import (
    EvalReport, EvalRun, EvalMetric, EvalCategory,
    DIAGNOSIS_METRICS, RECOVERY_METRICS, SAFETY_METRICS, COST_METRICS,
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


class EvalRunner:
    """
    评测运行器。

    用法：
        runner = EvalRunner(config)
        report = await runner.run_scenarios(["payment-latency@1", "order-db-errors@1"])
        print(report.to_markdown())
    """

    def __init__(self, config: EvalConfig):
        self.config = config
        self.report = EvalReport(
            report_id=f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )

    async def run_scenarios(self, scenario_names: list[str]) -> EvalReport:
        """运行指定场景列表。"""
        import random
        random.seed(self.config.random_seed)

        for scenario_name in scenario_names:
            for run_idx in range(self.config.runs_per_scenario):
                run = await self._run_single(scenario_name, run_idx)
                self.report.add_run(run)

        return self.report

    async def _run_single(self, scenario_name: str, run_idx: int) -> EvalRun:
        """运行单个场景的一次评测。"""
        run_id = f"run-{scenario_name}-{run_idx}-{uuid.uuid4().hex[:6]}"

        # 模拟指标收集
        import random
        metrics = [
            EvalMetric(
                name="top1_accuracy", category=EvalCategory.DIAGNOSIS,
                value=round(random.uniform(50, 90), 1), unit="%", target=60.0,
            ),
            EvalMetric(
                name="time_to_diagnose_sec", category=EvalCategory.RECOVERY,
                value=round(random.uniform(30, 200), 1), unit="s", target=180.0,
            ),
            EvalMetric(
                name="safety_violations", category=EvalCategory.SAFETY,
                value=0, unit="count", target=0.0,
            ),
            EvalMetric(
                name="tokens_consumed", category=EvalCategory.COST,
                value=round(random.uniform(400, 800)), unit="tokens", target=5000.0,
            ),
        ]

        # 判定通过/失败
        for m in metrics:
            if m.target is not None:
                if m.name == "safety_violations" or m.name == "tokens_consumed":
                    m.passed = m.value <= m.target
                else:
                    m.passed = m.value >= m.target

        return EvalRun(
            run_id=run_id,
            scenario_name=scenario_name,
            incident_id=f"incident-eval-{run_idx}",
            model_name=self.config.model_name,
            config={
                "dataset": self.config.dataset,
                "seed": self.config.random_seed,
            },
            metrics=metrics,
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
