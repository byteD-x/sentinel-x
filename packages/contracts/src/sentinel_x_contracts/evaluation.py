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
    random_seed: int
    runs_per_scenario: int = Field(ge=1)
    timeout_seconds: int = Field(gt=0)


class EvaluationComparability(StrictBaseModel):
    comparable: bool = False
    baseline_ref: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)


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
    metadata: EvaluationMetadata
    comparability: EvaluationComparability
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
        return self
