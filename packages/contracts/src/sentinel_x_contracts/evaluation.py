"""Versioned, browser-safe evaluation archive contracts."""

from datetime import datetime, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EVALUATION_REPORT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationMetadata(StrictBaseModel):
    commit_sha: Optional[str] = None
    profile: str
    environment_ref: str
    hardware_ref: Optional[str] = None
    dataset_ref: str
    model_ref: str
    policy_ref: Optional[str] = None
    prompt_ref: Optional[str] = None
    slo_policy_ref: Optional[str] = None
    report_kind: Literal["light-fixture", "formal-benchmark"] = "light-fixture"
    dataset_split: Literal["dev", "calibration", "holdout"] = "dev"
    random_seed: int
    runs_per_scenario: int = Field(ge=1)
    timeout_seconds: int = Field(gt=0)


class EvaluationComparability(StrictBaseModel):
    comparable: bool = False
    baseline_ref: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)


class EvaluationRecoverySummary(StrictBaseModel):
    attempted: int = Field(default=0, ge=0)
    succeeded: int = Field(default=0, ge=0)
    escalated: int = Field(default=0, ge=0)
    unknown: int = Field(default=0, ge=0)


class EvaluationSLOSummary(StrictBaseModel):
    available: bool = False
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    reason: Optional[str] = None


class EvaluationSecuritySummary(StrictBaseModel):
    runs_with_violations: int = Field(default=0, ge=0)
    total_violations: int = Field(default=0, ge=0)


class EvaluationMetricResult(StrictBaseModel):
    name: str
    category: str
    value: float
    unit: str
    target: Optional[float] = None
    direction: Literal["higher_is_better", "lower_is_better"]
    passed: Optional[bool] = None


class EvaluationMetricAggregate(EvaluationMetricResult):
    sample_count: int = Field(ge=1)


class EvaluationRunArchive(StrictBaseModel):
    run_id: str
    scenario_ref: str
    run_index: int = Field(ge=0)
    incident_id: str
    model_ref: str
    config: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    metrics: list[EvaluationMetricResult] = Field(default_factory=list)


class EvaluationFailureArchive(StrictBaseModel):
    scenario_ref: str
    run_index: int = Field(ge=0)
    category: str
    code: str
    message: str


class EvaluationAggregate(StrictBaseModel):
    attempted_runs: int = Field(ge=0)
    completed_runs: int = Field(ge=0)
    failed_runs: int = Field(ge=0)
    metrics: list[EvaluationMetricAggregate] = Field(default_factory=list)


class EvaluationArchive(StrictBaseModel):
    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=EVALUATION_REPORT_ID_PATTERN)
    created_at: datetime
    report_kind: str = "evaluation"
    source_mode: Literal["fixture", "observed", "replay"] = "observed"
    publishable: bool = False
    limitations: list[str] = Field(default_factory=list)
    metadata: EvaluationMetadata
    comparability: EvaluationComparability
    recovery_summary: EvaluationRecoverySummary = Field(default_factory=EvaluationRecoverySummary)
    slo_summary: EvaluationSLOSummary = Field(default_factory=EvaluationSLOSummary)
    security_summary: EvaluationSecuritySummary = Field(default_factory=EvaluationSecuritySummary)
    aggregate: EvaluationAggregate
    runs: list[EvaluationRunArchive] = Field(default_factory=list)
    failures: list[EvaluationFailureArchive] = Field(default_factory=list)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("created_at 必须是 UTC 时间")
        return value

    @model_validator(mode="after")
    def validate_totals(self):
        aggregate = self.aggregate
        if aggregate.attempted_runs != aggregate.completed_runs + aggregate.failed_runs:
            raise ValueError("attempted_runs 必须等于 completed_runs + failed_runs")
        if aggregate.completed_runs != len(self.runs):
            raise ValueError("completed_runs 必须等于 runs 数量")
        if aggregate.failed_runs != len(self.failures):
            raise ValueError("failed_runs 必须等于 failures 数量")
        if self.metadata.report_kind == "formal-benchmark" and self.metadata.profile == "light-fixture":
            raise ValueError("light-fixture 不能标记为 formal-benchmark")
        return self
