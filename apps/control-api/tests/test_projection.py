import pytest

from sentinel_x_control_api.projection import OutboxProjector, ProjectionError, SQLiteOutboxProjector


def _event(event_id: str, aggregate_id: str = "incident-1", sequence: int = 1) -> dict:
    return {
        "id": event_id,
        "aggregate_id": aggregate_id,
        "sequence": sequence,
        "event_type": "incident.created",
        "actor": "system",
    }


def test_projector_is_idempotent_and_marks_only_successful_events():
    published: list[str] = []
    projector = OutboxProjector(sink=lambda event: published.append(event["id"]))
    events = [_event("event-1", sequence=1), _event("event-2", sequence=2)]

    assert projector.dispatch(events, lambda event_id: published.append(f"published:{event_id}") or True) == 2
    assert projector.dispatch(events, lambda _event_id: True) == 0
    assert published == ["event-1", "published:event-1", "event-2", "published:event-2"]


def test_projector_rejects_gap_and_does_not_advance_projection():
    projector = OutboxProjector()

    with pytest.raises(ProjectionError, match="缺口"):
        projector.apply(_event("event-2", sequence=2))
    assert projector.projection("incident-1") is not None
    assert projector.projection("incident-1").last_sequence == 0


def test_projector_rejects_old_conflicting_event():
    projector = OutboxProjector()
    projector.apply(_event("event-1", sequence=1))

    with pytest.raises(ProjectionError, match="旧序号"):
        projector.apply(_event("different-event", sequence=1))


def test_sqlite_projector_retries_pending_event_after_sink_failure(tmp_path):
    delivered: list[str] = []
    should_fail = True

    def sink(event):
        if should_fail:
            raise RuntimeError("sink down")
        delivered.append(event["id"])

    projector = SQLiteOutboxProjector(tmp_path / "projection.sqlite3", sink=sink)
    with pytest.raises(RuntimeError, match="sink down"):
        projector.dispatch([_event("event-1")])
    assert [event["id"] for event in projector.pending_events()] == ["event-1"]
    projector.close()

    should_fail = False
    restored = SQLiteOutboxProjector(tmp_path / "projection.sqlite3", sink=sink)
    assert restored.dispatch() == 1
    assert delivered == ["event-1"]
    assert restored.pending_events() == []
    assert restored.projection("incident-1").last_sequence == 1
    restored.close()


def test_sqlite_projector_persists_gap_and_duplicate_guards(tmp_path):
    projector = SQLiteOutboxProjector(tmp_path / "projection.sqlite3")
    with pytest.raises(ProjectionError, match="缺口"):
        projector.dispatch([_event("event-2", sequence=2)])
    assert projector.projection("incident-1") is None
    assert projector.dispatch([_event("event-1")]) == 1
    assert projector.dispatch([_event("event-1")]) == 0
    with pytest.raises(ProjectionError, match="旧序号"):
        projector.dispatch([_event("different-event", sequence=1)])
    projector.close()
