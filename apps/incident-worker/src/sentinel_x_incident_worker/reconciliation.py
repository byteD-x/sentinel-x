"""Temporal Workflow 与数据库投影的严格对账契约。"""

from __future__ import annotations

from dataclasses import dataclass


class ReconciliationConflict(RuntimeError):
    """Workflow 与 DB projection 无法安全对齐。"""


@dataclass(frozen=True)
class ProjectionCheckpoint:
    workflow_run_id: str
    workflow_event_id: str
    status: str
    projection_version: int


def reconcile_checkpoint(
    expected: ProjectionCheckpoint,
    observed: ProjectionCheckpoint,
) -> None:
    """校验同一 workflow event 的状态投影，任何漂移都 fail-closed。"""

    if expected.workflow_run_id != observed.workflow_run_id:
        raise ReconciliationConflict("workflow_run_id 与数据库投影不一致")
    if expected.workflow_event_id != observed.workflow_event_id:
        raise ReconciliationConflict("workflow_event_id 与数据库投影不一致")
    if expected.status != observed.status:
        raise ReconciliationConflict("Workflow 状态与数据库投影不一致")
    if observed.projection_version < expected.projection_version:
        raise ReconciliationConflict("数据库投影落后于 Workflow checkpoint")
