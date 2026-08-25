"""PostgreSQL outbox dispatcher。

使用数据库行锁保证多个 dispatcher 不会同时消费同一事件。sink 调用发生在
事务内并受 timeout 约束；成功标记 published，失败增加 attempt_count 并保留
last_error/available_at，下一轮可重试。sink 必须具备幂等性，因为进程可能在
外部发布成功、数据库提交前崩溃。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID


class PostgresDispatcherError(RuntimeError):
    """Outbox dispatcher 无法安全推进。"""


@dataclass(frozen=True)
class OutboxRecord:
    id: UUID
    aggregate_type: str
    aggregate_id: UUID
    sequence: int
    event_type: str
    actor_type: str
    payload: dict[str, Any]
    occurred_at: datetime
    attempt_count: int


class PostgresOutboxDispatcher:
    """按序领取并发布 PostgreSQL outbox 事件。"""

    def __init__(
        self,
        connect: Callable[[], Any],
        sink: Callable[[OutboxRecord], None],
        *,
        batch_size: int = 50,
        retry_delay_seconds: int = 5,
    ):
        if not callable(connect) or not callable(sink):
            raise TypeError("connect 和 sink 必须是可调用对象")
        if batch_size < 1 or retry_delay_seconds < 0:
            raise ValueError("batch_size 必须为正数且 retry_delay_seconds 不能为负数")
        self._connect = connect
        self._sink = sink
        self._batch_size = batch_size
        self._retry_delay_seconds = retry_delay_seconds

    def dispatch_once(self) -> int:
        connection = self._connect()
        published = 0
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, aggregate_type, aggregate_id, sequence, event_type,
                               actor_type, payload, occurred_at, attempt_count
                        FROM outbox_events
                        WHERE published_at IS NULL AND available_at <= now()
                        ORDER BY aggregate_type, aggregate_id, sequence
                        FOR UPDATE SKIP LOCKED
                        LIMIT %s
                        """,
                        (self._batch_size,),
                    )
                    rows = cursor.fetchall()
                    for row in rows:
                        record = self._record(row)
                        try:
                            self._sink(record)
                        except Exception as exc:  # noqa: BLE001 - sink 边界必须可重试
                            cursor.execute(
                                """
                                UPDATE outbox_events
                                SET attempt_count = attempt_count + 1,
                                    last_error = %s,
                                    available_at = %s
                                WHERE id = %s AND published_at IS NULL
                                """,
                                (str(exc)[:4096], datetime.now(timezone.utc) + timedelta(seconds=self._retry_delay_seconds), record.id),
                            )
                            continue
                        cursor.execute(
                            """
                            UPDATE outbox_events
                            SET published_at = now(), attempt_count = attempt_count + 1
                            WHERE id = %s AND published_at IS NULL
                            """,
                            (record.id,),
                        )
                        if cursor.rowcount != 1:
                            raise PostgresDispatcherError(f"outbox 事件 {record.id} 发布确认失败")
                        published += 1
            return published
        except PostgresDispatcherError:
            raise
        except Exception as exc:  # noqa: BLE001 - DB driver错误统一收敛
            raise PostgresDispatcherError("PostgreSQL outbox dispatch 失败") from exc
        finally:
            connection.close()

    @staticmethod
    def _record(row: tuple[Any, ...]) -> OutboxRecord:
        payload = row[6]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise PostgresDispatcherError("outbox payload 必须是 JSON 对象")
        return OutboxRecord(
            id=UUID(str(row[0])),
            aggregate_type=str(row[1]),
            aggregate_id=UUID(str(row[2])),
            sequence=int(row[3]),
            event_type=str(row[4]),
            actor_type=str(row[5]),
            payload=payload,
            occurred_at=row[7],
            attempt_count=int(row[8]),
        )
