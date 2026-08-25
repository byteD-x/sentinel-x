"""运行本地固定评测并生成可校验的证据包。

示例：
    python scripts/run_evaluation.py --dataset holdout --runs 10 --output evidence/local
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# 允许从仓库根目录直接运行脚本；正式安装时由包解析器提供同样路径。
ROOT = Path(__file__).resolve().parents[1]
for source_path in (ROOT / "evals" / "src", ROOT / "packages" / "contracts" / "src", ROOT):
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))

from sentinel_x_evals.baselines import label_baseline, rule_baseline, standard_scenario_ids  # noqa: E402
from sentinel_x_evals.local_fixture import LocalFixtureScenarioEvaluator  # noqa: E402
from sentinel_x_evals.runner import EvalConfig, EvalRunner, save_eval_report  # noqa: E402


def _commit_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


async def _run(args: argparse.Namespace) -> Path:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    executors = {"b0": label_baseline, "b1": rule_baseline, "c1": LocalFixtureScenarioEvaluator().execute}
    reports: list[Path] = []
    for name, executor in executors.items():
        config = EvalConfig(
            model_name=name,
            dataset=args.dataset,
            runs_per_scenario=args.runs,
            random_seed=args.seed,
            results_dir=str(output),
            profile="light-fixture",
            environment_ref="local-isolated-fixture",
            dataset_version="scenario-catalog-v1",
            commit_sha=_commit_sha(),
            policy_ref="mvp-policy-v1",
            prompt_ref="none",
        )
        report = await EvalRunner(config, executor).run_scenarios(standard_scenario_ids())
        reports.append(Path(save_eval_report(report, str(output), config)))

    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": "light-fixture",
        "dataset": args.dataset,
        "scenario_count": len(standard_scenario_ids()),
        "runs_per_scenario": args.runs,
        "reports": [path.with_suffix(".json").name for path in reports],
        "commit_sha": _commit_sha(),
        "limitations": [
            "B0/B1/C1 均为本地 fixture；未连接真实 Kubernetes、Prometheus、Loki 或 Tempo。",
            "该证据包用于验证评测管线，不支持生产效果或根因准确率声明。",
        ],
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files = sorted(path for path in output.iterdir() if path.is_file() and path.name != "checksums.txt")
    checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in files)
    (output / "checksums.txt").write_text(checksums, encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("dev", "calibration", "holdout"), default="dev")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="evidence/local")
    args = parser.parse_args()
    print(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
