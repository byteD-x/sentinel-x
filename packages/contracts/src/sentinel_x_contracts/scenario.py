"""Scenario definition contracts."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from uuid import UUID, uuid4


class FaultCategory(str, Enum):
    NETWORK = "network"
    APPLICATION = "application"
    DATABASE = "database"
    KUBERNETES = "kubernetes"
    RESOURCE = "resource"


class FaultInjection(BaseModel):
    """单个故障注入定义。"""

    fault_type: str  # e.g. "latency", "pod-crash", "connection-error"
    target_service: str  # 目标服务名称
    target_namespace: str = "demo-shop"
    parameters: dict = Field(default_factory=dict)
    duration_seconds: int = Field(default=300, ge=10)
    cleanup_command: str = ""


class ScenarioDefinition(BaseModel):
    """不可变的故障演练场景定义。"""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., pattern=r"^[a-z0-9-]+@\d+$")  # e.g. "payment-latency@1"
    version: int = 1
    description: str
    category: FaultCategory
    faults: list[FaultInjection] = Field(..., min_length=1, max_length=5)
    ground_truth: str  # 已知根因
    expected_evidence: list[str] = Field(default_factory=list)  # 预期证据 ID
    expected_root_cause_category: str
    recovery_assertions: list[str] = Field(default_factory=list)
    allowlisted_runbooks: list[str] = Field(default_factory=list)


class ExerciseRun(BaseModel):
    """一次场景演练运行。"""

    id: UUID = Field(default_factory=uuid4)
    scenario_id: UUID
    scenario_version: int
    status: str = "pending"  # pending | injecting | running | cleaning | done | failed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    incident_id: Optional[UUID] = None  # 关联的事故 ID
    environment_dirty: bool = False
