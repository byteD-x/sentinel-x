"""Sentinel-X 共享契约与类型定义。

本包是所有跨包数据模型的唯一来源，其他包应通过本包导入类型，
禁止在各包内部重复定义相同语义的模型或枚举。
"""

from sentinel_x_contracts.incident import (
    IncidentStatus,
    RiskLevel,
    IncidentSeverity,
    IncidentPhase,
    SourceMode,
    EnvironmentBoundary,
    NextDecision,
    IncidentCapabilities,
    ActiveApprovalSummary,
    IncidentMilestone,
    ImpactSummary,
    HypothesisSummary,
    VerificationSummary,
    AlertSource,
    IncidentCreate,
    Incident,
    IncidentListParams,
    IncidentListResponse,
)
from sentinel_x_contracts.evaluation import (
    EvaluationAggregate,
    EvaluationArchive,
    EvaluationComparability,
    EvaluationFailureArchive,
    EvaluationMetadata,
    EvaluationMetricAggregate,
    EvaluationMetricResult,
    EvaluationRunArchive,
)
from sentinel_x_contracts.evidence import (
    EvidenceSource,
    EvidenceItem,
    DiagnosticToolCall,
)
from sentinel_x_contracts.hypothesis import (
    EvidenceRef,
    Hypothesis,
    InvestigationBudget,
)
from sentinel_x_contracts.approval import (
    ApprovalStatus,
    RemediationPlan,
    ApprovalRequest,
    ActionExecution,
)
from sentinel_x_contracts.timeline import (
    TimelineEventType,
    TimelineEvent,
    OutboxEvent,
)
from sentinel_x_contracts.scenario import (
    FaultCategory,
    RootCauseCategory,
    FaultInjection,
    ScenarioDefinition,
    ExerciseRun,
)

__all__ = [
    # Incident
    "IncidentStatus",
    "RiskLevel",
    "IncidentSeverity",
    "IncidentPhase",
    "SourceMode",
    "EnvironmentBoundary",
    "NextDecision",
    "IncidentCapabilities",
    "ActiveApprovalSummary",
    "IncidentMilestone",
    "ImpactSummary",
    "HypothesisSummary",
    "VerificationSummary",
    "AlertSource",
    "IncidentCreate",
    "Incident",
    "IncidentListParams",
    "IncidentListResponse",
    # Evaluation
    "EvaluationAggregate",
    "EvaluationArchive",
    "EvaluationComparability",
    "EvaluationFailureArchive",
    "EvaluationMetadata",
    "EvaluationMetricAggregate",
    "EvaluationMetricResult",
    "EvaluationRunArchive",
    # Evidence
    "EvidenceSource",
    "EvidenceItem",
    "DiagnosticToolCall",
    # Hypothesis
    "EvidenceRef",
    "Hypothesis",
    "InvestigationBudget",
    # Approval
    "ApprovalStatus",
    "RemediationPlan",
    "ApprovalRequest",
    "ActionExecution",
    # Timeline
    "TimelineEventType",
    "TimelineEvent",
    "OutboxEvent",
    # Scenario
    "FaultCategory",
    "RootCauseCategory",
    "FaultInjection",
    "ScenarioDefinition",
    "ExerciseRun",
]
