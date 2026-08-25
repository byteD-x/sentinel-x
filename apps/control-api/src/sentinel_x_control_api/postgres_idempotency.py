"""PostgreSQL-backed idempotency records for full-profile HTTP mutations."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator


@dataclass(frozen=True)
class IdempotencyRecord:
    body_hash: str
    status_code: int
    headers: dict[str, str]
    body: bytes | None


class PostgresIdempotencyStore:
    """原子预留请求键，避免并发请求重复执行副作用。"""

    def __init__(self, connect: Any):
        if not callable(connect):
            raise TypeError("connect 必须是可调用的连接工厂")
        self._connect = connect

    @contextmanager
    def _transaction(self) -> Iterator[tuple[Any, Any]]:
        connection = self._connect()
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    yield connection, cursor
        finally:
            connection.close()

    def reserve(
        self,
        *,
        actor_key: str,
        route: str,
        idempotency_key: str,
        body_hash: str,
    ) -> IdempotencyRecord | None:
        """返回既有记录；返回 None 表示本调用成功预留了该键。"""

        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                INSERT INTO idempotency_records(actor_key, route, idempotency_key, body_hash)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (actor_key, route, idempotency_key) DO NOTHING
                """,
                (actor_key, route, idempotency_key, body_hash),
            )
            if cursor.rowcount == 1:
                return None
            cursor.execute(
                """
                SELECT body_hash, status_code, response_headers, response_body
                FROM idempotency_records
                WHERE actor_key = %s AND route = %s AND idempotency_key = %s
                """,
                (actor_key, route, idempotency_key),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("幂等记录预留后无法读取")
            headers = row[2] or {}
            if isinstance(headers, str):
                headers = json.loads(headers)
            return IdempotencyRecord(
                body_hash=str(row[0]),
                status_code=int(row[1]),
                headers={str(key): str(value) for key, value in dict(headers).items()},
                body=bytes(row[3]) if row[3] is not None else None,
            )

    def complete(
        self,
        *,
        actor_key: str,
        route: str,
        idempotency_key: str,
        body_hash: str,
        status_code: int,
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                UPDATE idempotency_records
                SET status_code = %s, response_headers = %s::jsonb,
                    response_body = %s, completed_at = %s
                WHERE actor_key = %s AND route = %s AND idempotency_key = %s
                  AND body_hash = %s AND status_code = 0
                """,
                (
                    status_code, json.dumps(headers), body,
                    datetime.now(timezone.utc), actor_key, route,
                    idempotency_key, body_hash,
                ),
            )

    def release(
        self, *, actor_key: str, route: str, idempotency_key: str, body_hash: str
    ) -> None:
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                """
                DELETE FROM idempotency_records
                WHERE actor_key = %s AND route = %s AND idempotency_key = %s
                  AND body_hash = %s AND status_code = 0
                """,
                (actor_key, route, idempotency_key, body_hash),
            )
