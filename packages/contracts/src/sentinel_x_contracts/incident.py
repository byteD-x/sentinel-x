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
