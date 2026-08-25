from __future__ import annotations

from pathlib import Path

import pytest

from sentinel_x_control_api.postgres import (
    PostgresRuntimeError,
    apply_migrations,
    check_postgres_health,
)


class FakeCursor:
    def __init__(self, applied: dict[str, str]):
        self.applied = applied
        self.commands: list[tuple[str, tuple | None]] = []
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql: str, params=None):
        self.commands.append((sql, params))
        normalized = sql.strip()
        if normalized.startswith("SELECT checksum"):
            self._row = (self.applied.get(params[0]),) if params[0] in self.applied else None
        elif normalized.startswith("INSERT INTO sentinel_schema_migrations"):
            self.applied[params[0]] = params[1]
        elif normalized == "SELECT 1":
            self._row = (1,)

    def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self, applied=None):
        self.applied = applied if applied is not None else {}
        self.cursor_instance = FakeCursor(self.applied)
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def test_migration_runner_is_idempotent_and_records_checksum(tmp_path: Path):
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "0001_domain.sql").write_text("CREATE TABLE demo (id int);", encoding="utf-8")
    connection = FakeConnection()

    first = apply_migrations(
        "postgresql://control@localhost/sentinel",
        migrations_dir=tmp_path,
        connect=lambda *_args, **_kwargs: connection,
    )
    second = apply_migrations(
        "postgresql://control@localhost/sentinel",
        migrations_dir=tmp_path,
        connect=lambda *_args, **_kwargs: connection,
    )

    assert first == second
    assert len(connection.cursor_instance.commands) == 6
    assert connection.closed


def test_migration_runner_rejects_checksum_drift(tmp_path: Path):
    versions = tmp_path / "versions"
    versions.mkdir()
    migration = versions / "0001_domain.sql"
    migration.write_text("CREATE TABLE demo (id int);", encoding="utf-8")
    connection = FakeConnection({"0001_domain": "stale"})

    with pytest.raises(PostgresRuntimeError, match="checksum"):
        apply_migrations(
            "postgresql://control@localhost/sentinel",
            migrations_dir=tmp_path,
            connect=lambda *_args, **_kwargs: connection,
        )


def test_health_check_rejects_non_postgres_and_accepts_select_one():
    with pytest.raises(PostgresRuntimeError, match="只接受 PostgreSQL"):
        check_postgres_health("sqlite:///local.db")

    connection = FakeConnection()
    check_postgres_health(
        "postgresql://control@localhost/sentinel",
        connect=lambda *_args, **_kwargs: connection,
    )
    assert connection.closed


def test_missing_driver_is_fail_closed(monkeypatch):
    monkeypatch.setattr("sentinel_x_control_api.postgres.importlib.import_module", lambda _name: (_ for _ in ()).throw(ImportError()))

    with pytest.raises(PostgresRuntimeError, match="需要 psycopg"):
        check_postgres_health("postgresql://control@localhost/sentinel")
