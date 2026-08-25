"""运行六场景隔离注入/清理矩阵并输出机器可读报告。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source_path in (ROOT, ROOT / "packages" / "contracts" / "src"):
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))

from demo.scenarios.loader import create_default_loader  # noqa: E402
from demo.scenarios.runner import InMemoryScenarioBackend, ScenarioRunner  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--output", default="evidence/scenario-matrix.json")
    args = parser.parse_args()
    scenarios = create_default_loader().load_all()
    results = ScenarioRunner(InMemoryScenarioBackend()).run_matrix(scenarios, cycles=args.cycles)
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": "light-fixture",
        "backend": "in-memory",
        "scenario_count": len(scenarios),
        "cycles": args.cycles,
        "environment_clean": all(result.environment_clean for result in results),
        "results": [result.__dict__ for result in results],
        "limitations": ["未连接 kind/k3d、Kubernetes、PostgreSQL 或真实观测后端。"],
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
