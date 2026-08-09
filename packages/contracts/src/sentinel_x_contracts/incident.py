"""Incident domain contracts."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from uuid import UUID, uuid4


class IncidentStatus(str, Enum):
    """规范事故状态 — 唯一来源。"""

    DETECTED = "DETECTED"
    TRIAGING = "TRIAGING"
    DIAGNOSING = "DIAGNOSING"
    PLAN_PROPOSED = "PLAN_PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class RiskLevel(str, Enum):
    R0 = "R0"  # 只读，无副作用
    R1 = "R1"  # 可逆动作，需审批
    R2 = "R2"  # 高风险动作，MVP 禁用
    R3 = "R3"  # 永久禁止


class IncidentSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class IncidentPhase(str, Enum):
    """面向指挥台的规范处置阶段。"""

    DETECT = "detect"
    INVESTIGATE = "investigate"
    PLAN = "plan"
    APPROVE = "approve"
    EXECUTE = "execute"
    VERIFY = "verify"


class SourceMode(str, Enum):
    """读模型数据的真实性来源。"""

    FIXTURE = "fixture"
    OBSERVED = "observed"


class EnvironmentBoundary(BaseModel):
    profile: str
    data_scope: str
    source_mode: SourceMode


class NextDecision(BaseModel):
    kind: str
    title: str
    reason: str
    target_href: Optional[str] = None


class IncidentCapabilities(BaseModel):
    can_decide_approval: bool = False
    can_view_raw_evidence: bool = True
    denial_reason: Optional[str] = None


class ActiveApprovalSummary(BaseModel):
    id: str
    runbook_ref: str
    target: str
    risk_level: RiskLevel
    expires_at: datetime
    plan_hash: str


class IncidentMilestone(BaseModel):
    id: str
    phase: IncidentPhase
    state: str
    occurred_at: datetime
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    source_kind: str
    source_mode: SourceMode


class ImpactSummary(BaseModel):
    summary: str
    observed_at: datetime
    source_mode: SourceMode


class HypothesisSummary(BaseModel):
    statement: str
    confidence: Optional[float] = None
    supporting_evidence_count: int = 0
    opposing_evidence: Optional[str] = None
    source_mode: SourceMode


class VerificationSummary(BaseModel):
    passed: bool
    window_seconds: Optional[int] = None
    recovery_actor: Optional[str] = None
    source_mode: SourceMode


class AlertSource(BaseModel):
    """告警来源信息。"""

    alertmanager_id: str = Field(..., description="Alertmanager 告警 ID")
    fingerprint: str = Field(..., description="去重指纹")
    alert_name: str
    severity: IncidentSeverity
    description: str
    started_at: datetime


class IncidentCreate(BaseModel):
    """创建事故的输入。"""

    alert_source: AlertSource
    initial_evidence_ids: list[str] = Field(default_factory=list)


class Incident(BaseModel):
    """事故读模型。"""

    id: UUID = Field(default_factory=uuid4)
    status: IncidentStatus = IncidentStatus.DETECTED
    severity: IncidentSeverity
    alert_source: AlertSource
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    updated_at: datetime = Field(default_factory=lambda: datetime.now())
    resolved_at: Optional[datetime] = None
    workflow_id: Optional[str] = None  # Temporal Workflow ID
    version: int = 1  # 乐观锁版本号


class IncidentListParams(BaseModel):
    """事故列表查询参数。"""

    status: Optional[IncidentStatus] = None
    severity: Optional[IncidentSeverity] = None
    cursor: Optional[str] = None  # 分页游标
    limit: int = Field(default=20, ge=1, le=100)


class IncidentListResponse(BaseModel):
    """事故列表响应。"""

    items: list[Incident]
    total: int
    next_cursor: Optional[str] = None
