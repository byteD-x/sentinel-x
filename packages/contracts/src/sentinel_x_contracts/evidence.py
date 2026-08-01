"""Evidence and diagnostic contracts."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from uuid import UUID, uuid4


class EvidenceSource(str, Enum):
    PROMETHEUS = "prometheus"
    LOKI = "loki"
    TEMPO = "tempo"
    KUBERNETES = "kubernetes"


class EvidenceItem(BaseModel):
    """一条可验证的证据记录。"""

    id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    source: EvidenceSource
    query: str  # 原始查询（PromQL/LogQL/TraceQL）
    summary: str  # 脱敏摘要
    raw_hash: str = Field(..., description="原始结果的 SHA256，用于去重")
    truncated: bool = False  # 结果是否被截断
    collected_at: datetime = Field(default_factory=lambda: datetime.now())
    expires_at: datetime  # 证据有效期


class DiagnosticToolCall(BaseModel):
    """一次类型化诊断工具调用。"""

    tool_name: str  # e.g. "query_prometheus", "query_loki", "get_pod_status"
    parameters: dict
    result_evidence_ids: list[UUID] = Field(default_factory=list)
    error: Optional[str] = None
    started_at: datetime
    completed_at: datetime
    budget_consumed: dict = Field(default_factory=dict)  # {step_cost, token_cost, time_cost}
