"""本地 outbox projector/dispatcher。

这是 PostgreSQL projector 的同契约 local slice：它不改变 Workflow 权威状态，
只按 incident 序号构建可重放读模型，并在 gap/冲突时 fail-closed。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sqlite3
import threading
from pathlib import Path
from typing import Callable


class ProjectionError(RuntimeError):
    """投影无法安全推进。"""


@dataclass
class IncidentProjection:
    aggregate_id: str
    last_sequence: int = 0
    event_ids: set[str] = field(default_factory=set)
    events: list[dict] = field(default_factory=list)


class OutboxProjector:
    """对 outbox 事件执行严格序列投影和至少一次 dispatch。"""

    def __init__(self, sink: Callable[[dict], None] | None = None):
        self._projections: dict[str, IncidentProjection] = {}
        self._sink = sink or (lambda _event: None)

    def apply(self, event: dict) -> bool:
        event_id = event.get("id")
        aggregate_id = event.get("aggregate_id")
        sequence = event.get("sequence")
        if not isinstance(event_id, str) or not isinstance(aggregate_id, str) or not isinstance(sequence, int):
            raise ProjectionError("outbox 事件字段无效")
        projection = self._projections.setdefault(aggregate_id, IncidentProjection(aggregate_id))
        if event_id in projection.event_ids:
            return False
        if sequence <= projection.last_sequence:
            raise ProjectionError("同一事故出现未登记的旧序号或冲突事件")
        if sequence != projection.last_sequence + 1:
            raise ProjectionError("outbox 事件存在序号缺口")
        self._sink(dict(event))
        projection.events.append(dict(event))
        projection.event_ids.add(event_id)
        projection.last_sequence = sequence
        return True

    def dispatch(self, events: list[dict], mark_published: Callable[[str], bool]) -> int:
        dispatched = 0
        for event in sorted(events, key=lambda item: (str(item.get("aggregate_id")), item.get("sequence", 0))):
            applied = self.apply(event)
            if applied or event.get("id") in self._event_ids():
                if not mark_published(event["id"]):
                    raise ProjectionError("outbox 事件发布确认失败")
                dispatched += int(applied)
        return dispatched

    def projection(self, aggregate_id: str) -> IncidentProjection | None:
        return self._projections.get(aggregate_id)

    def _event_ids(self) -> set[str]:
        return {event_id for projection in self._projections.values() for event_id in projection.event_ids}


class SQLiteOutboxProjector:
    """可跨进程恢复的本地 outbox projector。

    事件先以 ``published=0`` 持久化，再调用 sink，成功后标记已发布。sink
    失败会保留 pending 事件，重启后可再次 dispatch；因此消费者必须具备
    幂等性。该实现仅服务 local profile，不替代 PostgreSQL ``SKIP LOCKED``。
    """

    def __init__(self, path: str | Path, sink: Callable[[dict], None] | None = None):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.RLock()
        self._sink = sink or (lambda _event: None)
        with self._connection:
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projection_state (
                    aggregate_id TEXT PRIMARY KEY,
                    last_sequence INTEGER NOT NULL CHECK (last_sequence >= 0)
                );
                CREATE TABLE IF NOT EXISTS projection_events (
                    aggregate_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK (sequence > 0),
                    payload TEXT NOT NULL,
                    published INTEGER NOT NULL DEFAULT 0 CHECK (published IN (0, 1)),
                    PRIMARY KEY (aggregate_id, event_id),
                    UNIQUE (aggregate_id, sequence)
                );
                """
            )

    @staticmethod
    def _validate(event: dict) -> tuple[str, str, int]:
        event_id = event.get("id")
        aggregate_id = event.get("aggregate_id")
        sequence = event.get("sequence")
        if not isinstance(event_id, str) or not isinstance(aggregate_id, str) or not isinstance(sequence, int):
            raise ProjectionError("outbox 事件字段无效")
        return event_id, aggregate_id, sequence

    def _persist(self, event: dict) -> tuple[bool, bool]:
        event_id, aggregate_id, sequence = self._validate(event)
        serialized = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT published, payload FROM projection_events WHERE aggregate_id = ? AND event_id = ?",
                (aggregate_id, event_id),
            ).fetchone()
            if existing is not None:
                return False, bool(existing[0])
            row = self._connection.execute(
                "SELECT last_sequence FROM projection_state WHERE aggregate_id = ?",
                (aggregate_id,),
            ).fetchone()
            last_sequence = int(row[0]) if row else 0
            if sequence <= last_sequence:
                raise ProjectionError("同一事故出现未登记的旧序号或冲突事件")
            if sequence != last_sequence + 1:
                raise ProjectionError("outbox 事件存在序号缺口")
            self._connection.execute(
                "INSERT INTO projection_events(aggregate_id, event_id, sequence, payload) VALUES (?, ?, ?, ?)",
                (aggregate_id, event_id, sequence, serialized),
            )
            self._connection.execute(
                """
                INSERT INTO projection_state(aggregate_id, last_sequence) VALUES (?, ?)
                ON CONFLICT(aggregate_id) DO UPDATE SET last_sequence = excluded.last_sequence
                """,
                (aggregate_id, sequence),
            )
        return True, False

    def _mark_published(self, aggregate_id: str, event_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE projection_events SET published = 1 WHERE aggregate_id = ? AND event_id = ?",
                (aggregate_id, event_id),
            )

    def dispatch(self, events: list[dict] | None = None, mark_published: Callable[[str], bool] | None = None) -> int:
        """投递新事件和历史 pending 事件，返回本次首次成功发布数。"""
        candidates = events if events is not None else self.pending_events()
        dispatched = 0
        for event in sorted(candidates, key=lambda item: (str(item.get("aggregate_id")), item.get("sequence", 0))):
            inserted, published = self._persist(event)
            if published:
                continue
            event_id, aggregate_id, _ = self._validate(event)
            if not inserted:
                row = self._connection.execute(
                    "SELECT payload, published FROM projection_events WHERE aggregate_id = ? AND event_id = ?",
                    (aggregate_id, event_id),
                ).fetchone()
                if row is None or row[1]:
                    continue
                event = json.loads(row[0])
            self._sink(dict(event))
            if mark_published is not None and not mark_published(event_id):
                raise ProjectionError("outbox 事件发布确认失败")
            self._mark_published(aggregate_id, event_id)
            dispatched += 1
        return dispatched

    def pending_events(self) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM projection_events WHERE published = 0 ORDER BY aggregate_id, sequence"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def projection(self, aggregate_id: str) -> IncidentProjection | None:
        with self._lock:
            state = self._connection.execute(
                "SELECT last_sequence FROM projection_state WHERE aggregate_id = ?",
                (aggregate_id,),
            ).fetchone()
            rows = self._connection.execute(
                "SELECT event_id, payload FROM projection_events WHERE aggregate_id = ? ORDER BY sequence",
                (aggregate_id,),
            ).fetchall()
        if state is None:
            return None
        events = [json.loads(row[1]) for row in rows]
        return IncidentProjection(
            aggregate_id=aggregate_id,
            last_sequence=int(state[0]),
            event_ids={str(row[0]) for row in rows},
            events=events,
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
