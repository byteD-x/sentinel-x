"""Hypothesis and investigation contracts."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from uuid import UUID, uuid4


class EvidenceRef(BaseModel):
    """证据引用，标注支持或反对。"""

    evidence_id: UUID
    relevance: str = Field(..., pattern="^(supporting|opposing)$")


class Hypothesis(BaseModel):
    """模型生成的根因假设。"""

    id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    statement: str = Field(..., min_length=10, max_length=2000)
    confidence: float = Field(..., ge=0.0, le=1.0)
    root_cause_category: str = Field(
        ..., pattern="^(network|application|database|kubernetes|unknown)$"
    )
    affected_service: str
    supporting_evidence: list[EvidenceRef] = Field(default_factory=list, max_length=20)
    opposing_evidence: list[EvidenceRef] = Field(default_factory=list, max_length=20)
    suggested_next_steps: list[str] = Field(default_factory=list, max_length=10)
    needs_human_escalation: bool = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now())
    model_provider: str = ""
    model_name: str = ""
    total_tokens_used: int = 0

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, v: object) -> object:
        """将 >1 的值归一化到 0-1 范围（防御模型输出百分比格式）。

        使用 mode="before" 确保在 Field(le=1.0) 约束前先执行归一化。
        """
        if isinstance(v, (int, float)):
            if v > 1.0:
                return v / 100.0
        return v


class InvestigationBudget(BaseModel):
    """调查预算配置。"""

    max_seconds: int = Field(default=480, ge=10)
    max_llm_calls: int = Field(default=8, ge=1)
    max_tool_calls: int = Field(default=20, ge=1)
    max_query_window_minutes: int = Field(default=30, ge=5)
    seconds_consumed: int = 0
    llm_calls_consumed: int = 0
    tool_calls_consumed: int = 0

    @property
    def is_exhausted(self) -> bool:
        return (
            self.seconds_consumed >= self.max_seconds
            or self.llm_calls_consumed >= self.max_llm_calls
            or self.tool_calls_consumed >= self.max_tool_calls
        )
