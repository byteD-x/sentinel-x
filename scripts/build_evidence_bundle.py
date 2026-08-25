"""将指定脱敏产物打包为可校验的证据目录。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals" / "src"))
from sentinel_x_evals.evidence_bundle import build_evidence_bundle  # noqa: E402


def _commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="evidence/bundle")
    parser.add_argument("--artifact", action="append", required=True, help="源文件路径，可重复")
    args = parser.parse_args()
    artifacts = {Path(path).name: Path(path) for path in args.artifact}
    manifest = build_evidence_bundle(
        Path(args.output),
        artifacts,
        commit_sha=_commit(),
        profile="light-fixture",
        limitations=[
            "未连接真实 Kubernetes、PostgreSQL、Prometheus、Loki 或 Tempo。",
            "该证据包用于本地可重复性和安全边界验证，不支持生产效果声明。",
        ],
    )
    print(manifest)


if __name__ == "__main__":
    main()
