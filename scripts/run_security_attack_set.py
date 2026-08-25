"""运行固定安全攻击集并输出脱敏 JSON 报告。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source_path in (ROOT / "packages" / "policy" / "src", ROOT / "packages" / "diagnostics" / "src", ROOT / "packages" / "contracts" / "src"):
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))

from sentinel_x_policy.attack_set import evaluate_attack_set  # noqa: E402


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "evidence/security-attack-set.json")
    report = evaluate_attack_set()
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
