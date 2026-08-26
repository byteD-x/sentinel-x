from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from sentinel_x_control_api.postgres_repository import (
    PostgresIncidentRepository,
    PostgresRepositoryError,
)


class FakeCursor:
    def __init__(self):
        self.calls: list[tuple[str, tuple | None]] = []
        self.rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))
        if sql.lstrip().startswith("SELECT") and "FROM incidents" in sql:
            self.rows.append(None)
        elif sql.lstrip().startswith("INSERT INTO incidents"):
            self.rows.append((params[0], params[1], params[2], "DETECTED", params[3], params[4], params[6], 1))
        elif sql.lstrip().startswith("INSERT INTO timeline_events"):
            self.rows.append((params[0], params[1], params[2], params[3], params[4], {}, params[6]))
        elif sql.lstrip().startswith("SELECT sequence"):
            self.rows.append((0,))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.closed = False

    def transaction(self):
        return FakeTransaction()

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def test_create_incident_writes_incident_timeline_and_outbox_in_one_transaction():
    connection = FakeConnection()
    repository = PostgresIncidentRepository(lambda: connection)

    record = repository.create_incident(
        fingerprint="fp-1",
        severity="warning",
        service="inventory-api",
        workflow_id="incident/test-1",
    )

    assert record.status == "DETECTED"
    assert record.fingerprint == "fp-1"
    assert connection.closed
    sql = "\n".join(call[0] for call in connection.cursor_instance.calls)
    assert "INSERT INTO incidents" in sql
    assert "INSERT INTO timeline_events" in sql
    assert "INSERT INTO outbox_events" in sql


def test_repository_rejects_non_callable_connection_factory():
    with pytest.raises(TypeError, match="connect"):
        PostgresIncidentRepository(None)


def test_get_timeline_bounds_queries_minimum_and_maximum_sequence():
    connection = FakeConnection()
    connection.cursor_instance.rows.append((4, 9))
    repository = PostgresIncidentRepository(lambda: connection)

    bounds = repository.get_timeline_bounds(UUID("00000000-0000-0000-0000-000000000001"))

    assert bounds == (4, 9)
    sql = "\n".join(call[0] for call in connection.cursor_instance.calls)
    assert "SELECT MIN(sequence), MAX(sequence)" in sql
