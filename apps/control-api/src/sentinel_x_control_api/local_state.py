"""本地隔离 profile 的 SQLite 状态快照。"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class LocalStateError(RuntimeError):
    """本地状态快照无法读取或写入。"""


class LocalStateSnapshot:
    """用单行 JSON 快照为本地单控制面提供原子持久化。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.RLock()
        with self._connection:
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS local_state_snapshot (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def load(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM local_state_snapshot WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
        except json.JSONDecodeError as error:
            raise LocalStateError("本地状态快照不是有效 JSON") from error
        if not isinstance(payload, dict):
            raise LocalStateError("本地状态快照必须是 JSON 对象")
        return payload

    def save(self, payload: Mapping[str, Any]) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO local_state_snapshot (id, payload, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (serialized, updated_at),
            )

    def clear(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM local_state_snapshot")
