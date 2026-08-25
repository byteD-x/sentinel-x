"""运行可重复的本地 MVP 验收门禁并写出脱敏汇总报告。

该入口覆盖当前仓库可在无 Docker/Kubernetes/PostgreSQL 的环境中证明的能力：
Python、两个控制台、六场景 cleanup、攻击集和 fixture 评测。报告会明确标注
``light-fixture`` 限制，失败步骤返回非零退出码。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(name: str, command: list[str], *, cwd: Path = ROOT) -> dict[str, object]:
    started = datetime.now(timezone.utc)
    executable = command[0]
    if os.name == "nt" and executable in {"npm", "npx"}:
        executable = f"{executable}.cmd"
    resolved = shutil.which(executable)
    if resolved is None:
        return {
            "name": name,
            "command": command,
            "returncode": 127,
            "started_at": started.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "output_tail": f"找不到可执行文件: {executable}",
        }
    completed = subprocess.run(
        [resolved, *command[1:]],
        cwd=cwd,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    return {
        "name": name,
        "command": command,
        "returncode": completed.returncode,
        "started_at": started.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "output_tail": output[-4000:],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="evidence/local-mvp")
    parser.add_argument("--scenario-cycles", type=int, default=3)
    parser.add_argument("--evaluation-runs", type=int, default=3)
    args = parser.parse_args()
    if args.scenario_cycles < 1 or args.evaluation_runs < 1:
        parser.error("运行次数必须大于 0")

    output = (ROOT / args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    scenario_report = output / "scenario-matrix.json"
    security_report = output / "security-attack-set.json"
    evaluation_dir = output / "evaluation"
    evaluation_dir.mkdir(parents=True, exist_ok=True)

    python = sys.executable
    steps = [
        _run("python-tests", [python, "-m", "pytest", "-q", "--tb=short"]),
        _run(
            "python-light-lint",
            [python, "-m", "ruff", "check", "packages/", "apps/", "demo/", "--select", "E4,E7,E9"],
        ),
        _run(
            "web-tests",
            ["npm", "test", "--", "--run"],
            cwd=ROOT / "apps" / "web-console",
        ),
        _run("web-lint", ["npm", "run", "lint"], cwd=ROOT / "apps" / "web-console"),
        _run("web-build", ["npm", "run", "build"], cwd=ROOT / "apps" / "web-console"),
        _run(
            "web-ui-contract",
            ["npm", "run", "test:ui-contract"],
            cwd=ROOT / "apps" / "web-console",
        ),
        _run(
            "terminal-tests",
            ["npm", "test", "--", "--run"],
            cwd=ROOT / "apps" / "terminal-console",
        ),
        _run(
            "terminal-build",
            ["npm", "run", "build"],
            cwd=ROOT / "apps" / "terminal-console",
        ),
        _run(
            "scenario-matrix",
            [
                python,
                "scripts/run_scenario_matrix.py",
                "--cycles",
                str(args.scenario_cycles),
                "--output",
                str(scenario_report),
            ],
        ),
        _run("security-attack-set", [python, "scripts/run_security_attack_set.py", str(security_report)]),
        _run(
            "fixture-evaluation",
            [
                python,
                "scripts/run_evaluation.py",
                "--dataset",
                "dev",
                "--runs",
                str(args.evaluation_runs),
                "--output",
                str(evaluation_dir),
            ],
        ),
    ]

    artifacts = [path for path in [scenario_report, security_report, evaluation_dir / "manifest.json"] if path.is_file()]
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": "light-fixture",
        "environment": os.environ.get("SENTINEL_ENVIRONMENT", "local"),
        "scenario_cycles": args.scenario_cycles,
        "evaluation_runs": args.evaluation_runs,
        "steps": steps,
        "artifacts": [{"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)} for path in artifacts],
        "passed": all(step["returncode"] == 0 for step in steps),
        "limitations": [
            "未连接真实 Kubernetes、PostgreSQL、Prometheus、Loki、Tempo 或 Temporal Server。",
            "fixture 评测不支持生产效果、根因准确率或恢复时延声明。",
        ],
    }
    report_path = output / "verification-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report_path)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
