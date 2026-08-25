"""在指定 PostgreSQL 上执行可重复 migration。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "control-api" / "src"))
from sentinel_x_control_api.postgres import PostgresRuntimeError, apply_migrations  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--migrations-dir", default=str(ROOT / "migrations"))
    args = parser.parse_args()
    try:
        records = apply_migrations(args.database_url, migrations_dir=args.migrations_dir)
    except PostgresRuntimeError as exc:
        parser.error(str(exc))
    print(json.dumps({"migrations": [record.__dict__ for record in records]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
