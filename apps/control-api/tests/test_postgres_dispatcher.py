from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from sentinel_x_control_api.postgres_dispatcher import PostgresOutboxDispatcher


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows


class Tx:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Connection:
    def __init__(self, rows):
        self.cursor_obj = Cursor(rows)
        self.closed = False

    def transaction(self):
        return Tx()

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def _row():
    return (
        uuid4(), "incident", uuid4(), 1, "incident.created", "SYSTEM", {"ok": True},
        datetime.now(timezone.utc), 0,
    )


def test_dispatcher_claims_with_skip_locked_and_marks_success():
    connection = Connection([_row()])
    delivered = []
    dispatcher = PostgresOutboxDispatcher(lambda: connection, delivered.append)

    assert dispatcher.dispatch_once() == 1
    assert len(delivered) == 1
    assert any("FOR UPDATE SKIP LOCKED" in sql for sql, _ in connection.cursor_obj.calls)
    assert any("SET published_at = now()" in sql for sql, _ in connection.cursor_obj.calls)
    assert connection.closed


def test_dispatcher_records_failure_and_retries_later():
    connection = Connection([_row()])

    def sink(_record):
        raise RuntimeError("downstream unavailable")

    assert PostgresOutboxDispatcher(lambda: connection, sink).dispatch_once() == 0
    failure_sql = [sql for sql, _ in connection.cursor_obj.calls if "last_error" in sql]
    assert failure_sql
    assert not any("published_at = now()" in sql for sql, _ in connection.cursor_obj.calls)


def test_dispatcher_validates_configuration():
    with pytest.raises(ValueError):
        PostgresOutboxDispatcher(lambda: Connection([]), lambda _record: None, batch_size=0)
