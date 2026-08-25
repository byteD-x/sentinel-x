"""本地 outbox projector/dispatcher。

这是 PostgreSQL projector 的同契约 local slice：它不改变 Workflow 权威状态，
只按 incident 序号构建可重放读模型，并在 gap/冲突时 fail-closed。
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
