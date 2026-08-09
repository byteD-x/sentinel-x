"""场景定义契约。"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


_SCENARIO_REF_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*@([1-9][0-9]*)$"


class FaultCategory(str, Enum):
    NETWORK = "network"
    APPLICATION = "application"
    DATABASE = "database"
    KUBERNETES = "kubernetes"
    RESOURCE = "resource"


class RootCauseCategory(str, Enum):
    """场景评测允许使用的根因分类。"""

    WORKLOAD_UNAVAILABLE = "WORKLOAD_UNAVAILABLE"
    CAPACITY_EXHAUSTION = "CAPACITY_EXHAUSTION"
    LATCHED_RUNTIME_FAILURE = "LATCHED_RUNTIME_FAILURE"
    CACHE_TIMEOUT = "CACHE_TIMEOUT"
    DATABASE_LOCK_CONTENTION = "DATABASE_LOCK_CONTENTION"
    BAD_DEPLOYMENT = "BAD_DEPLOYMENT"


class FaultInjection(BaseModel):
    """单个故障注入定义。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fault_type: str = Field(..., min_length=1, max_length=100)
    target_service: str = Field(..., min_length=1, max_length=100)
    target_namespace: str = Field(default="demo-shop", min_length=1, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: int = Field(default=300, ge=10)
    cleanup_command: str = Field(
        default="",
        max_length=512,
        description="仅供演练清理器识别的非可信元数据；场景加载器绝不执行该值。",
    )


class ScenarioDefinition(BaseModel):
    """不可变、版本化的故障演练场景定义。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., pattern=_SCENARIO_REF_PATTERN)
    name: str = Field(..., pattern=_SCENARIO_REF_PATTERN)
    version: int = Field(..., ge=1)
    description: str = Field(..., min_length=1)
    category: FaultCategory
    faults: list[FaultInjection] = Field(..., min_length=1, max_length=5)
    ground_truth: str = Field(..., min_length=1)
    expected_evidence: list[str] = Field(default_factory=list)
    expected_root_cause_category: RootCauseCategory
    recovery_assertions: list[str] = Field(..., min_length=1)
    allowlisted_runbooks: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def derive_id_from_name(cls, value: Any) -> Any:
        """让未显式写入 ``id`` 的 YAML 仍以 ``name@version`` 作为稳定 ID。"""
        if not isinstance(value, dict) or "id" in value:
            return value
        name = value.get("name")
        if not isinstance(name, str):
            return value
        return {**value, "id": name}

    @model_validator(mode="after")
    def validate_name_version(self) -> "ScenarioDefinition":
        name_version = int(self.name.rsplit("@", maxsplit=1)[1])
        if name_version != self.version:
            raise ValueError("name 中的版本必须与 version 一致")
        if self.id != self.name:
            raise ValueError("id 必须与 name 一致")
        return self


class ExerciseRun(BaseModel):
    """一次场景演练运行。"""

    id: UUID = Field(default_factory=uuid4)
    scenario_id: str = Field(..., pattern=_SCENARIO_REF_PATTERN)
    scenario_version: int = Field(..., ge=1)
    status: str = "pending"  # pending | injecting | running | cleaning | done | failed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    incident_id: Optional[UUID] = None
    environment_dirty: bool = False

    @model_validator(mode="after")
    def validate_scenario_reference(self) -> "ExerciseRun":
        scenario_ref_version = int(self.scenario_id.rsplit("@", maxsplit=1)[1])
        if scenario_ref_version != self.scenario_version:
            raise ValueError("scenario_id 中的版本必须与 scenario_version 一致")
        return self
