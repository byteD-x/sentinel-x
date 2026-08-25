import pytest

from sentinel_x_incident_worker.reconciliation import (
    ProjectionCheckpoint,
    ReconciliationConflict,
    reconcile_checkpoint,
)


def _checkpoint(**overrides):
    values = {
        "workflow_run_id": "incident/run-1",
        "workflow_event_id": "event-3",
        "status": "VERIFYING",
        "projection_version": 3,
    }
    values.update(overrides)
    return ProjectionCheckpoint(**values)


def test_reconcile_accepts_matching_or_newer_projection():
    reconcile_checkpoint(_checkpoint(), _checkpoint(projection_version=4))


@pytest.mark.parametrize(
    "change",
    [
        {"workflow_run_id": "incident/other"},
        {"workflow_event_id": "event-other"},
        {"status": "RESOLVED"},
        {"projection_version": 2},
    ],
)
def test_reconcile_rejects_identity_status_and_stale_projection(change):
    with pytest.raises(ReconciliationConflict):
        reconcile_checkpoint(_checkpoint(), _checkpoint(**change))
