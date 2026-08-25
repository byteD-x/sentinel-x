"""PostgreSQL-backed Alert Ingress nonce replay protection."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator


class PostgresReplayStore:
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

    def claim(self, nonce: str, ttl_seconds: int) -> bool:
        """原子登记 nonce；True 表示本请求首次出现。"""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._transaction() as (_connection, cursor):
            cursor.execute(
                "DELETE FROM alert_replay_nonces WHERE expires_at <= %s",
                (now,),
            )
            cursor.execute(
                """
                INSERT INTO alert_replay_nonces(nonce, expires_at)
                VALUES (%s, %s)
                ON CONFLICT (nonce) DO NOTHING
                """,
                (nonce, expires_at),
            )
            return cursor.rowcount == 1
