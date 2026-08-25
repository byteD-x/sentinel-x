"""Timeline event contracts."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field
from uuid import UUID, uuid4


class TimelineEventType(str, Enum):
    INCIDENT_CREATED = "incident.created"
    INCIDENT_STATUS_CHANGED = "incident.status_changed"
    EVIDENCE_COLLECTED = "evidence.collected"
    HYPOTHESIS_GENERATED = "hypothesis.generated"
    PLAN_PROPOSED = "plan.proposed"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"
    ACTION_STARTED = "action.started"
    ACTION_COMPLETED = "action.completed"
    RECOVERY_VERIFIED = "recovery.verified"
    INCIDENT_ESCALATED = "incident.escalated"
    ERROR_OCCURRED = "error.occurred"


class TimelineEvent(BaseModel):
    """只追加的时间线事件。"""

    id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    sequence: int  # 单调递增
    event_type: TimelineEventType
    actor: str  # "system" | "investigator" | "approver:{id}" | "scenario_runner"
    payload: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class OutboxEvent(BaseModel):
    """可重试的本地投影事件；发布确认不改变事件内容。"""

    id: UUID = Field(default_factory=uuid4)
    aggregate_type: str = "incident"
    aggregate_id: UUID
    sequence: int
    event_type: str
    actor: str
    payload: dict = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now())
    published_at: datetime | None = None
