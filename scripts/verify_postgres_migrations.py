"""在隔离临时数据库中真实验证 PostgreSQL migration 的 up/down/reapply。

连接串通过 ``--admin-url`` 或 ``SENTINEL_POSTGRES_ADMIN_URL`` 提供，脚本不会
把连接串写入报告。默认使用系统 ``psql/createdb/dropdb``，不要求 Python
PostgreSQL 驱动；这只验证 schema migration，不代表应用 repository 已完成。
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations" / "versions"


class VerificationError(RuntimeError):
    """PostgreSQL migration 验证失败。"""


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        raise VerificationError(
            f"命令失败: {command[0]} (exit={result.returncode})\n{result.stderr[-2000:]}"
        )
    return result


def _tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for candidate in Path(r"C:\Program Files\PostgreSQL").glob("*/bin/" + name + ".exe"):
        return str(candidate)
    return None


def _psql(admin_url: str, database: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    executable = _tool("psql")
    assert executable is not None
    parsed = urlsplit(admin_url)
    database_url = urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", parsed.query, parsed.fragment))
    return _run([executable, "--dbname", database_url, *args], check=check)


def _createdb(admin_url: str, database: str) -> None:
    executable = _tool("psql")
    assert executable is not None
    _run([executable, "--dbname", admin_url, "--command", f'CREATE DATABASE "{database}"'])


def _dropdb(admin_url: str, database: str) -> None:
    executable = _tool("psql")
    assert executable is not None
    _run(
        [executable, "--dbname", admin_url, "--command", f'DROP DATABASE IF EXISTS "{database}"'],
        check=False,
    )


def _assert_schema(admin_url: str, database: str) -> dict[str, int]:
    query = """
    SELECT
      (SELECT count(*) FROM information_schema.tables
       WHERE table_schema = 'public' AND table_name IN
       ('incidents','remediation_plans','timeline_events','approval_requests',
        'approval_decisions','action_executions','verification_results','outbox_events')) AS table_count,
      (SELECT count(*) FROM pg_trigger WHERE tgname IN
       ('timeline_events_immutable','approval_decisions_immutable')) AS trigger_count,
      (SELECT count(*) FROM pg_indexes WHERE indexname = 'incidents_active_fingerprint_uidx') AS index_count;
    """
    output = _psql(admin_url, database, "--tuples-only", "--no-align", "--command", query).stdout.strip()
    values = [int(value) for value in output.split("|")]
    expected = {"table_count": 8, "trigger_count": 2, "index_count": 1}
    actual = dict(zip(expected, values, strict=True))
    if actual != expected:
        raise VerificationError(f"schema 断言失败: {actual}，期望 {expected}")
    return actual


def _assert_constraints(admin_url: str, database: str) -> None:
    first = """
    INSERT INTO incidents (
      id, workflow_id, alert_fingerprint, status, severity, service
    ) VALUES (
      '00000000-0000-0000-0000-000000000001', 'workflow/test', 'fingerprint/test',
      'DETECTED', 'warning', 'inventory-api'
    );
    """
    _psql(admin_url, database, "--command", first)
    duplicate = """
    INSERT INTO incidents (
      id, workflow_id, alert_fingerprint, status, severity, service
    ) VALUES (
      '00000000-0000-0000-0000-000000000002', 'workflow/test-2', 'fingerprint/test',
      'DETECTED', 'warning', 'inventory-api'
    );
    """
    duplicate = _psql(admin_url, database, "--set", "ON_ERROR_STOP=1", "--command", duplicate, check=False)
    if duplicate.returncode == 0:
        raise VerificationError("active fingerprint 唯一约束未拒绝重复告警")
    _psql(
        admin_url,
        database,
        "--command",
        "INSERT INTO timeline_events (id, incident_id, sequence, event_type, schema_version, actor_type, occurred_at) VALUES ('00000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000001', 1, 'incident.created', '1.0', 'SYSTEM', now());",
    )
    immutable = _psql(
        admin_url,
        database,
        "--command",
        "UPDATE timeline_events SET event_type = 'tampered' WHERE id = '00000000-0000-0000-0000-000000000011';",
        check=False,
    )
    if immutable.returncode == 0:
        raise VerificationError("timeline append-only trigger 未拒绝 UPDATE")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-url", default=os.getenv("SENTINEL_POSTGRES_ADMIN_URL", ""))
    parser.add_argument("--output", default="evidence/postgres-migration-verification.json")
    args = parser.parse_args()
    if not args.admin_url:
        parser.error("请通过 --admin-url 或 SENTINEL_POSTGRES_ADMIN_URL 提供临时 PostgreSQL 管理连接")
    if _tool("psql") is None:
        parser.error("需要 psql")

    database = f"sentinel_x_verify_{secrets.token_hex(6)}"
    started = datetime.now(timezone.utc)
    report = {
        "schema_version": "1.0",
        "profile": "full-postgresql-schema",
        "database": database,
        "started_at": started.isoformat(),
        "passed": False,
        "checks": [],
        "limitations": ["仅验证 migration/schema/约束；尚未验证应用 repository、Temporal 对账或 Kubernetes/OTel E2E。"],
    }
    try:
        _createdb(args.admin_url, database)
        up = MIGRATIONS / "0001_domain.sql"
        down = MIGRATIONS / "0001_domain.down.sql"
        _psql(args.admin_url, database, "--file", str(up))
        _psql(args.admin_url, database, "--file", str(up))
        report["checks"].append({"name": "up-idempotent", "passed": True})
        report["checks"].append({"name": "schema", "passed": True, "details": _assert_schema(args.admin_url, database)})
        _assert_constraints(args.admin_url, database)
        report["checks"].append({"name": "constraints-and-append-only", "passed": True})
        _psql(args.admin_url, database, "--file", str(down))
        report["checks"].append({"name": "down", "passed": True})
        _psql(args.admin_url, database, "--file", str(up))
        report["checks"].append({"name": "reapply", "passed": True})
        report["passed"] = True
    except VerificationError as exc:
        report["error"] = str(exc)
    finally:
        _dropdb(args.admin_url, database)
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        output = (ROOT / args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
