"""Approval and action contracts."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from uuid import UUID, uuid4


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class RemediationPlan(BaseModel):
    """恢复计划，绑定到已登记的 Runbook。"""

    id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    hypothesis_id: UUID
    runbook_ref: str = Field(..., pattern=r"^[a-z_]+@\d+$")  # e.g. "restart_deployment@1"
    target: str = Field(..., min_length=1)
    parameters: dict = Field(default_factory=dict)
    risk_level: str = Field(..., pattern="^(R0|R1)$")  # MVP 只允许 R0/R1
    plan_hash: str = Field(..., description="计划的规范哈希，审批绑定此值")
    proposed_at: datetime = Field(default_factory=lambda: datetime.now())


class ApprovalRequest(BaseModel):
    """审批请求。"""

    id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    plan: RemediationPlan
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    expires_at: datetime  # 审批 TTL
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    decision_reason: Optional[str] = None


class ActionExecution(BaseModel):
    """动作执行记录。"""

    id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    approval_id: UUID
    runbook_ref: str
    idempotency_key: str = Field(..., description="全局唯一幂等键")
    target: str
    parameters: dict
    risk_level: str
    status: str = "pending"  # pending | running | succeeded | failed | unknown
    before_state: Optional[str] = None
    after_state: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
