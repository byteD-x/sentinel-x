"""
Sentinel-X Control API — 主应用入口。

提供以下端点组：
- GET  /health — 健康检查
- GET  /api/incidents — 事故列表
- POST /api/incidents — 创建事故（Alert Ingress）
- GET  /api/incidents/{id} — 事故详情
- GET  /api/incidents/{id}/timeline — 事故时间线
- GET  /api/incidents/{id}/evidence — 证据列表
- GET  /api/incidents/{id}/hypotheses — 假设列表
- POST /api/incidents/{id}/approvals — 创建审批
- PUT  /api/incidents/{id}/approvals/{approval_id} — 审批决定
- GET  /api/approvals — 全局审批队列
- GET  /api/scenarios — 场景列表
- POST /api/scenarios/{id}/run — 启动演练
"""

import asyncio
import hashlib
import hmac
import json
import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sentinel_x_contracts import (
    ActiveApprovalSummary,
    EnvironmentBoundary,
    HypothesisSummary,
    ImpactSummary,
    IncidentCapabilities,
    IncidentMilestone,
    IncidentPhase,
    NextDecision,
    SourceMode,
    VerificationSummary,
)
from sentinel_x_domain.services import compute_plan_hash
from sentinel_x_control_api.eval_archive import (
    EvaluationArchiveError,
    get_evaluation_archive,
    list_evaluation_archives,
)


EVAL_ARCHIVE_DIR = Path(os.getenv("SENTINEL_EVAL_ARCHIVE_DIR", "evals/results"))
EVAL_ARCHIVE_MAX_BYTES = int(os.getenv("SENTINEL_EVAL_ARCHIVE_MAX_BYTES", "2097152"))


def _evaluation_archive_error_response(error: EvaluationArchiveError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"detail": error.detail, "code": error.code},
    )


# ---------------------------------------------------------------------------
# 精简内联模型 — 避免依赖 contracts 包的导入问题
# 正式开发时替换为 from sentinel_x_contracts import ...
# ---------------------------------------------------------------------------


class IncidentStatus(str, Enum):
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
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class IncidentSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AlertSource(StrictBaseModel):
    alertmanager_id: str
    fingerprint: str
    alert_name: str
    severity: IncidentSeverity
    description: str
    started_at: datetime


class IncidentCreate(StrictBaseModel):
    alert_source: AlertSource


class IncidentResponse(BaseModel):
    id: str
    fingerprint: Optional[str] = None
    status: IncidentStatus
    severity: IncidentSeverity
    alert_name: str
    description: str
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    workflow_id: Optional[str] = None
    version: int = 1


class IncidentOverviewResponse(IncidentResponse):
    environment: EnvironmentBoundary
    impact: Optional[ImpactSummary] = None
    top_hypothesis: Optional[HypothesisSummary] = None
    next_decision: NextDecision
    active_approval: Optional[ActiveApprovalSummary] = None
    latest_verification: Optional[VerificationSummary] = None
    capabilities: IncidentCapabilities
    milestones: list[IncidentMilestone] = Field(default_factory=list)


class IncidentListResponse(BaseModel):
    items: list[IncidentResponse]
    total: int
    next_cursor: Optional[str] = None


class TimelineEvent(BaseModel):
    id: str
    incident_id: str
    sequence: int
    event_type: str
    actor: str
    payload: dict = Field(default_factory=dict)
    timestamp: datetime


class ApprovalRequest(StrictBaseModel):
    plan_id: str
    runbook_ref: str
    target: str
    parameters: dict = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.R1
    plan_hash: str
    hypothesis_id: str


class ApprovalDecision(StrictBaseModel):
    approved: bool
    reason: str


class HypothesisResponse(BaseModel):
    id: str
    statement: str
    confidence: float
    root_cause_category: str
    affected_service: str
    needs_human_escalation: bool
    generated_at: datetime


class ScenarioResponse(BaseModel):
    id: str
    name: str
    version: int
    description: str
    category: str


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    environment: str = "local-demo"
    actions_enabled: bool = False


# ---------------------------------------------------------------------------
# 内存存储 — MVP 阶段替代 PostgreSQL
# 正式开发时替换为 SQLAlchemy + PostgreSQL
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field


@dataclass
class StoredIncident:
    id: str
    fingerprint: str = ""
    status: IncidentStatus = IncidentStatus.DETECTED
    severity: IncidentSeverity = IncidentSeverity.WARNING
    alert_name: str = ""
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None
    workflow_id: Optional[str] = None
    version: int = 1
    timeline: list[TimelineEvent] = field(default_factory=list)
    _timeline_seq: int = 0


class InMemoryStore:
    """线程安全的内存存储。"""

    def __init__(self):
        self._incidents: dict[str, StoredIncident] = {}
        self._fingerprint_index: dict[str, str] = {}
        self._approvals: dict[str, dict] = {}
        self._scenarios: dict[str, dict] = {}

    def create_incident(self, data: IncidentCreate) -> StoredIncident:
        existing_id = self._fingerprint_index.get(data.alert_source.fingerprint)
        if existing_id:
            existing = self._incidents.get(existing_id)
            if existing and existing.status not in {
                IncidentStatus.RESOLVED,
                IncidentStatus.ESCALATED,
                IncidentStatus.FAILED,
            }:
                return existing
        incident_id = str(uuid4())
        incident = StoredIncident(
            id=incident_id,
            fingerprint=data.alert_source.fingerprint,
            severity=data.alert_source.severity,
            alert_name=data.alert_source.alert_name,
            description=data.alert_source.description,
        )
        self._add_timeline_event(
            incident, "incident.created", "alert_ingress",
            {"fingerprint": data.alert_source.fingerprint},
        )
        self._incidents[incident_id] = incident
        self._fingerprint_index[data.alert_source.fingerprint] = incident_id
        return incident

    def find_by_fingerprint(self, fingerprint: str) -> Optional[StoredIncident]:
        incident_id = self._fingerprint_index.get(fingerprint)
        return self._incidents.get(incident_id) if incident_id else None

    def get_incident(self, incident_id: str) -> Optional[StoredIncident]:
        return self._incidents.get(incident_id)

    def list_incidents(
        self,
        status_filter: Optional[IncidentStatus] = None,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> tuple[list[StoredIncident], Optional[str]]:
        incidents = list(self._incidents.values())
        # 按时间倒序
        incidents.sort(key=lambda i: i.created_at, reverse=True)
        if status_filter:
            incidents = [i for i in incidents if i.status == status_filter]
        # 简单分页
        start = 0
        if cursor:
            for idx, inc in enumerate(incidents):
                if inc.id == cursor:
                    start = idx + 1
                    break
        page = incidents[start : start + limit]
        next_cursor = page[-1].id if len(page) == limit and len(incidents) > start + limit else None
        return page, next_cursor

    def _add_timeline_event(
        self,
        incident: StoredIncident,
        event_type: str,
        actor: str,
        payload: dict | None = None,
    ) -> TimelineEvent:
        incident._timeline_seq += 1
        event = TimelineEvent(
            id=str(uuid4()),
            incident_id=incident.id,
            sequence=incident._timeline_seq,
            event_type=event_type,
            actor=actor,
            payload=payload or {},
            timestamp=datetime.now(),
        )
        incident.timeline.append(event)
        return event

    def add_timeline_event(
        self,
        incident_id: str,
        event_type: str,
        actor: str,
        payload: dict | None = None,
    ) -> Optional[TimelineEvent]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return None
        return self._add_timeline_event(incident, event_type, actor, payload)

    def set_status(
        self,
        incident: StoredIncident,
        new_status: IncidentStatus,
        reason: str,
        actor: str = "system",
    ) -> None:
        """更新演示事故状态，并留下可回放的状态事件。"""
        old_status = incident.status
        if new_status == old_status:
            return
        allowed = {
            IncidentStatus.DETECTED: {IncidentStatus.TRIAGING, IncidentStatus.FAILED},
            IncidentStatus.TRIAGING: {IncidentStatus.DIAGNOSING, IncidentStatus.ESCALATED, IncidentStatus.FAILED},
            IncidentStatus.DIAGNOSING: {IncidentStatus.PLAN_PROPOSED, IncidentStatus.ESCALATED, IncidentStatus.FAILED},
            IncidentStatus.PLAN_PROPOSED: {IncidentStatus.AWAITING_APPROVAL, IncidentStatus.VERIFYING, IncidentStatus.ESCALATED, IncidentStatus.FAILED},
            IncidentStatus.AWAITING_APPROVAL: {IncidentStatus.EXECUTING, IncidentStatus.ESCALATED, IncidentStatus.FAILED},
            IncidentStatus.EXECUTING: {IncidentStatus.VERIFYING, IncidentStatus.ESCALATED, IncidentStatus.FAILED},
            IncidentStatus.VERIFYING: {IncidentStatus.RESOLVED, IncidentStatus.ESCALATED, IncidentStatus.FAILED},
            IncidentStatus.RESOLVED: set(),
            IncidentStatus.ESCALATED: set(),
            IncidentStatus.FAILED: set(),
        }
        if new_status not in allowed[old_status]:
            raise ValueError(f"非法事故状态迁移: {old_status.value} -> {new_status.value}")
        incident.status = new_status
        incident.updated_at = datetime.now()
        incident.version += 1
        self._add_timeline_event(
            incident,
            "incident.status_changed",
            actor,
            {"from": old_status.value, "to": new_status.value, "reason": reason},
        )

    def get_timeline(
        self,
        incident_id: str,
        after_sequence: int = 0,
    ) -> list[TimelineEvent]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return []
        return [e for e in incident.timeline if e.sequence > after_sequence]

    def create_approval(
        self,
        incident_id: str,
        data: ApprovalRequest,
        allow_terminal_fixture: bool = False,
    ) -> dict:
        incident = self._incidents.get(incident_id)
        if not incident:
            raise ValueError("事故不存在")
        if incident.status == IncidentStatus.DETECTED:
            self.set_status(incident, IncidentStatus.TRIAGING, "进入审批前检查")
            self.set_status(incident, IncidentStatus.DIAGNOSING, "完成基础诊断")
            self.set_status(incident, IncidentStatus.PLAN_PROPOSED, "形成恢复计划")
        if incident.status == IncidentStatus.PLAN_PROPOSED:
            self.set_status(incident, IncidentStatus.AWAITING_APPROVAL, "等待人工批准 R1 动作")
        if incident.status != IncidentStatus.AWAITING_APPROVAL and not (
            allow_terminal_fixture
            and incident.status in {IncidentStatus.RESOLVED, IncidentStatus.ESCALATED, IncidentStatus.FAILED}
        ):
            raise ValueError(f"当前状态不可创建审批: {incident.status.value}")
        approval_id = str(uuid4())
        approval = {
            "id": approval_id,
            "incident_id": incident_id,
            "plan_id": data.plan_id,
            "runbook_ref": data.runbook_ref,
            "target": data.target,
            "parameters": data.parameters,
            "risk_level": data.risk_level.value,
            "plan_hash": data.plan_hash,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(minutes=30)).isoformat(),
            "decided_at": None,
            "decided_by": None,
            "decision_reason": None,
        }
        self._approvals[approval_id] = approval
        self.add_timeline_event(incident_id, "approval.requested", "system", approval)
        return approval

    def decide_approval(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        decided_by: str,
        incident_id: Optional[str] = None,
    ) -> Optional[dict]:
        approval = self._approvals.get(approval_id)
        if not approval:
            return None
        if incident_id is not None and approval["incident_id"] != incident_id:
            return None
        if approval["status"] != "pending":
            return None  # 不可重复决定
        # 检查过期
        expires_at = datetime.fromisoformat(approval["expires_at"])
        if datetime.now() > expires_at:
            approval["status"] = "expired"
            return approval
        incident = self._incidents.get(approval["incident_id"])
        if not incident or incident.status != IncidentStatus.AWAITING_APPROVAL:
            return None
        approval["status"] = "approved" if decision.approved else "rejected"
        approval["decided_at"] = datetime.now().isoformat()
        approval["decided_by"] = decided_by
        approval["decision_reason"] = decision.reason
        event_type = "approval.decided"
        self.add_timeline_event(
            approval["incident_id"], event_type, f"approver:{decided_by}",
            {"approved": decision.approved, "reason": decision.reason},
        )

        if incident:
            if decision.approved:
                self.set_status(incident, IncidentStatus.EXECUTING, "人工批准 R1 动作")
                self._add_timeline_event(
                    incident,
                    "action.started",
                    "action_gateway_fixture",
                    {
                        "runbook_ref": approval["runbook_ref"],
                        "target": approval["target"],
                        "mode": "light-fixture",
                    },
                )
                self.set_status(incident, IncidentStatus.VERIFYING, "动作完成，开始检查恢复")
                self._add_timeline_event(
                    incident,
                    "action.completed",
                    "action_gateway_fixture",
                    {"status": "succeeded", "before_state": "degraded", "after_state": "healthy"},
                )
                self.set_status(incident, IncidentStatus.RESOLVED, "恢复窗口验证通过")
                incident.resolved_at = incident.resolved_at or datetime.now()
                self._add_timeline_event(
                    incident,
                    "recovery.verified",
                    "verification_fixture",
                    {"result": "passed", "window_seconds": 60},
                )
            else:
                if incident.status not in {IncidentStatus.RESOLVED, IncidentStatus.ESCALATED, IncidentStatus.FAILED}:
                    self.set_status(incident, IncidentStatus.ESCALATED, "人工拒绝恢复动作")
                self._add_timeline_event(
                    incident,
                    "incident.escalated",
                    "system",
                    {"reason": decision.reason},
                )
        return approval

    def add_scenario(self, scenario: dict) -> None:
        self._scenarios[scenario["id"]] = scenario

    def list_scenarios(self) -> list[dict]:
        return list(self._scenarios.values())


# ---------------------------------------------------------------------------
# 全局存储实例
# ---------------------------------------------------------------------------

def _store_demo_scenarios(store: InMemoryStore) -> None:
    demo_scenarios = [
        {
            "id": "payment-latency@1",
            "name": "payment-latency@1",
            "version": 1,
            "description": "Payment API 高延迟：inventory-api 网络超时导致级联延迟",
            "category": "network",
            "allowlisted_runbooks": ["restart_deployment@1"],
        },
        {
            "id": "order-db-errors@1",
            "name": "order-db-errors@1",
            "version": 1,
            "description": "Order Service 数据库连接池耗尽导致 5xx 错误",
            "category": "database",
            "allowlisted_runbooks": ["restart_deployment@1"],
        },
        {
            "id": "inventory-split-brain@1",
            "name": "inventory-split-brain@1",
            "version": 1,
            "description": "Redis 主从切换后 split-brain 导致库存数据不一致",
            "category": "application",
            "allowlisted_runbooks": ["restart_deployment@1"],
        },
        {
            "id": "payment-pod-crash@1",
            "name": "payment-pod-crash@1",
            "version": 1,
            "description": "Payment Pod 因 OOM 崩溃，Kubernetes 自动重启恢复",
            "category": "kubernetes",
            "allowlisted_runbooks": ["no_op"],
        },
        {
            "id": "inventory-cpu-saturation@1",
            "name": "inventory-cpu-saturation@1",
            "version": 1,
            "description": "Inventory CPU 饱和，需要扩容",
            "category": "resource",
            "allowlisted_runbooks": ["scale_deployment@1"],
        },
        {
            "id": "order-bad-deployment@1",
            "name": "order-bad-deployment@1",
            "version": 1,
            "description": "Order Service 错误部署导致持续失败，需人工回滚",
            "category": "application",
            "allowlisted_runbooks": ["db_rollback@1"],
        },
    ]
    for s in demo_scenarios:
        store.add_scenario(s)


store = InMemoryStore()
ALERT_INGRESS_HMAC_KEY = os.getenv("ALERT_INGRESS_HMAC_KEY")
ALERT_INGRESS_CLOCK_SKEW_SECONDS = 300

# 预置演示场景
_store_demo_scenarios(store)


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期。"""
    # 启动时
    yield
    # 关闭时


app = FastAPI(
    title="Sentinel-X Control API",
    version="0.1.0",
    description="AI 事故指挥中心控制面 API",
    lifespan=lifespan,
)

# CORS — 允许本地开发
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_role(role: Optional[str], *allowed_roles: str) -> str:
    """所有会改变控制面状态的端点都显式要求调用方角色。"""
    normalized = role or "viewer"
    if normalized not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"角色 {normalized} 无权执行此操作",
        )
    return normalized


async def _verify_alert_ingress(request: Request) -> None:
    """light 环境也不接受无签名告警；演练场景使用内部调用而非该入口。"""
    if not ALERT_INGRESS_HMAC_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alert Ingress 未配置 HMAC 密钥",
        )
    timestamp = request.headers.get("X-Sentinel-Timestamp")
    signature = request.headers.get("X-Sentinel-Signature")
    if not timestamp or not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Alert Ingress 签名缺失")
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Alert Ingress 时间戳非法") from exc
    if abs(datetime.now().timestamp() - timestamp_value) > ALERT_INGRESS_CLOCK_SKEW_SECONDS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Alert Ingress 签名已过期")
    raw_body = await request.body()
    expected = hmac.new(
        ALERT_INGRESS_HMAC_KEY.encode("utf-8"),
        timestamp.encode("utf-8") + b"\n" + raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature[7:], expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Alert Ingress 签名无效")


_PHASE_ORDER = [
    IncidentPhase.DETECT,
    IncidentPhase.INVESTIGATE,
    IncidentPhase.PLAN,
    IncidentPhase.APPROVE,
    IncidentPhase.EXECUTE,
    IncidentPhase.VERIFY,
]


def _phase_for_status(incident_status: IncidentStatus) -> IncidentPhase:
    if incident_status in {IncidentStatus.DETECTED, IncidentStatus.TRIAGING}:
        return IncidentPhase.DETECT
    if incident_status == IncidentStatus.DIAGNOSING:
        return IncidentPhase.INVESTIGATE
    if incident_status == IncidentStatus.PLAN_PROPOSED:
        return IncidentPhase.PLAN
    if incident_status == IncidentStatus.AWAITING_APPROVAL:
        return IncidentPhase.APPROVE
    if incident_status == IncidentStatus.EXECUTING:
        return IncidentPhase.EXECUTE
    return IncidentPhase.VERIFY


def _phase_for_event(event: TimelineEvent) -> Optional[IncidentPhase]:
    event_phases = {
        "incident.created": IncidentPhase.DETECT,
        "scenario.started": IncidentPhase.DETECT,
        "evidence.collected": IncidentPhase.INVESTIGATE,
        "hypothesis.generated": IncidentPhase.INVESTIGATE,
        "plan.proposed": IncidentPhase.PLAN,
        "approval.requested": IncidentPhase.APPROVE,
        "approval.decided": IncidentPhase.APPROVE,
        "action.started": IncidentPhase.EXECUTE,
        "action.completed": IncidentPhase.EXECUTE,
        "recovery.verified": IncidentPhase.VERIFY,
    }
    if event.event_type != "incident.status_changed":
        return event_phases.get(event.event_type)
    target = event.payload.get("to")
    try:
        target_status = IncidentStatus(target)
        if target_status in {
            IncidentStatus.RESOLVED,
            IncidentStatus.ESCALATED,
            IncidentStatus.FAILED,
        }:
            return _phase_for_status(IncidentStatus(event.payload.get("from")))
        return _phase_for_status(target_status)
    except (TypeError, ValueError):
        return None


def _milestone_summary(event: TimelineEvent) -> str:
    payload = event.payload
    if event.event_type == "incident.created":
        return "故障已创建"
    if event.event_type == "scenario.started":
        return "演练故障已启动"
    if event.event_type == "incident.status_changed":
        return str(payload.get("reason") or "处置阶段已更新")
    if event.event_type == "evidence.collected":
        return str(payload.get("summary") or "调查证据已收集")
    if event.event_type == "hypothesis.generated":
        return str(payload.get("statement") or "形成待验证判断")
    if event.event_type == "approval.requested":
        return f"等待审批 {payload.get('runbook_ref', '恢复操作')}"
    if event.event_type == "approval.decided":
        return "恢复操作已批准" if payload.get("approved") else "恢复操作已拒绝"
    if event.event_type == "action.started":
        return "恢复操作开始执行"
    if event.event_type == "action.completed":
        return "恢复操作执行完成"
    if event.event_type == "recovery.verified":
        return "恢复窗口验证完成"
    return "处置记录已更新"


def _milestone_evidence_refs(event: TimelineEvent) -> list[str]:
    payload = event.payload
    if event.event_type == "evidence.collected" and payload.get("evidence_id"):
        return [str(payload["evidence_id"])]
    refs = payload.get("supporting_evidence")
    if isinstance(refs, list):
        return [str(ref) for ref in refs]
    return []


def _build_milestones(incident: StoredIncident) -> list[IncidentMilestone]:
    phased_events = [
        (event, phase)
        for event in incident.timeline
        if (phase := _phase_for_event(event)) is not None
    ]
    current_phase = (
        phased_events[-1][1]
        if incident.status in {IncidentStatus.ESCALATED, IncidentStatus.FAILED} and phased_events
        else _phase_for_status(incident.status)
    )
    current_index = _PHASE_ORDER.index(current_phase)
    by_phase: dict[IncidentPhase, IncidentMilestone] = {}
    source_kinds = {
        IncidentPhase.DETECT: "alert",
        IncidentPhase.INVESTIGATE: "hypothesis",
        IncidentPhase.PLAN: "plan",
        IncidentPhase.APPROVE: "approval",
        IncidentPhase.EXECUTE: "action",
        IncidentPhase.VERIFY: "verification",
    }
    for event, phase in phased_events:
        phase_index = _PHASE_ORDER.index(phase)
        state = "current" if phase_index == current_index else "complete"
        if (
            incident.status in {IncidentStatus.ESCALATED, IncidentStatus.FAILED}
            and phase == current_phase
        ):
            state = "failed"
        by_phase[phase] = IncidentMilestone(
            id=event.id,
            phase=phase,
            state=state,
            occurred_at=event.timestamp,
            summary=_milestone_summary(event),
            evidence_refs=_milestone_evidence_refs(event),
            source_kind=source_kinds[phase],
            source_mode=SourceMode.FIXTURE,
        )
    return [by_phase[phase] for phase in _PHASE_ORDER if phase in by_phase]


def _active_approval(incident_id: str) -> Optional[dict]:
    pending = [
        approval
        for approval in store._approvals.values()
        if approval["incident_id"] == incident_id and approval["status"] == "pending"
    ]
    return min(pending, key=lambda item: item["expires_at"]) if pending else None


def _latest_event(incident: StoredIncident, event_type: str) -> Optional[TimelineEvent]:
    return next(
        (event for event in reversed(incident.timeline) if event.event_type == event_type),
        None,
    )


def _top_hypothesis(incident: StoredIncident) -> Optional[HypothesisSummary]:
    event = _latest_event(incident, "hypothesis.generated")
    if event is None:
        return None
    refs = event.payload.get("supporting_evidence")
    supporting_count = len(refs) if isinstance(refs, list) else int(refs or 0)
    confidence = event.payload.get("confidence")
    return HypothesisSummary(
        statement=str(event.payload.get("statement") or "证据不足"),
        confidence=float(confidence) if confidence is not None else None,
        supporting_evidence_count=supporting_count,
        opposing_evidence=(
            str(event.payload["opposing_evidence"])
            if event.payload.get("opposing_evidence") is not None
            else None
        ),
        source_mode=SourceMode.FIXTURE,
    )


def _latest_verification(incident: StoredIncident) -> Optional[VerificationSummary]:
    event = _latest_event(incident, "recovery.verified")
    if event is None:
        return None
    result = event.payload.get("result")
    return VerificationSummary(
        passed=result is True or result == "passed",
        window_seconds=(
            int(event.payload["window_seconds"])
            if event.payload.get("window_seconds") is not None
            else None
        ),
        recovery_actor=event.actor,
        source_mode=SourceMode.FIXTURE,
    )


def _next_decision(incident: StoredIncident, approval: Optional[dict]) -> NextDecision:
    if approval:
        return NextDecision(
            kind="review_approval",
            title="核对并决定恢复操作",
            reason="恢复操作在审批通过前不会执行。",
            target_href="#approval-section",
        )
    decisions = {
        IncidentStatus.DETECTED: ("investigate", "开始确认影响", "等待进入调查阶段。"),
        IncidentStatus.TRIAGING: ("investigate", "确认故障范围", "正在收集初始信号。"),
        IncidentStatus.DIAGNOSING: ("investigate", "等待调查结论", "正在关联调查证据。"),
        IncidentStatus.PLAN_PROPOSED: ("investigate", "核对恢复方案", "恢复方案尚未提交审批。"),
        IncidentStatus.EXECUTING: ("wait_execution", "等待操作完成", "恢复操作正在执行。"),
        IncidentStatus.VERIFYING: (
            "review_verification",
            "等待恢复验证",
            "需要完整观察窗口确认恢复。",
        ),
        IncidentStatus.RESOLVED: (
            "review_verification",
            "查看恢复结果",
            "故障已进入终态，仍需核对验证证据。",
        ),
        IncidentStatus.ESCALATED: ("escalated", "交由人工处理", "系统已停止自动推进。"),
        IncidentStatus.FAILED: ("failed", "检查失败原因", "处置流程未完成。"),
    }
    kind, title, reason = decisions[incident.status]
    return NextDecision(kind=kind, title=title, reason=reason)


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查。"""
    return HealthResponse()


@app.get("/api/evaluations")
async def list_evaluations():
    """列出已归档的本地评测报告，冷启动时不伪造数据。"""
    try:
        return list_evaluation_archives(EVAL_ARCHIVE_DIR, EVAL_ARCHIVE_MAX_BYTES)
    except EvaluationArchiveError as exc:
        return _evaluation_archive_error_response(exc)


@app.get("/api/evaluations/{report_id}")
async def get_evaluation(report_id: str):
    """读取单份已校验的本地评测归档。"""
    try:
        return get_evaluation_archive(EVAL_ARCHIVE_DIR, report_id, EVAL_ARCHIVE_MAX_BYTES)
    except EvaluationArchiveError as exc:
        return _evaluation_archive_error_response(exc)


# ---- 事故 ----

@app.post("/api/incidents", status_code=status.HTTP_201_CREATED)
async def create_incident(data: IncidentCreate, request: Request):
    """创建事故（Alert Ingress 调用）。"""
    await _verify_alert_ingress(request)
    incident = store.create_incident(data)
    return {
        "id": incident.id,
        "fingerprint": incident.fingerprint,
        "status": incident.status.value,
        "alert_name": incident.alert_name,
        "created_at": incident.created_at.isoformat(),
    }


@app.get("/api/incidents", response_model=IncidentListResponse)
async def list_incidents(
    status: Optional[IncidentStatus] = None,
    cursor: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
):
    """事故列表。"""
    items, next_cursor = store.list_incidents(status_filter=status, cursor=cursor, limit=limit)
    return IncidentListResponse(
        items=[
            IncidentResponse(
                id=inc.id,
                fingerprint=inc.fingerprint,
                status=inc.status,
                severity=inc.severity,
                alert_name=inc.alert_name,
                description=inc.description,
                created_at=inc.created_at,
                updated_at=inc.updated_at,
                resolved_at=inc.resolved_at,
                workflow_id=inc.workflow_id,
                version=inc.version,
            )
            for inc in items
        ],
        total=len(store._incidents),
        next_cursor=next_cursor,
    )


@app.get("/api/incidents/{incident_id}", response_model=IncidentOverviewResponse)
async def get_incident(
    incident_id: str,
    role: Optional[str] = Header(default=None, alias="X-Sentinel-Role"),
):
    """事故详情。"""
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")
    approval = _active_approval(incident_id)
    normalized_role = role or "viewer"
    return IncidentOverviewResponse(
        id=incident.id,
        fingerprint=incident.fingerprint,
        status=incident.status,
        severity=incident.severity,
        alert_name=incident.alert_name,
        description=incident.description,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        resolved_at=incident.resolved_at,
        workflow_id=incident.workflow_id,
        version=incident.version,
        environment=EnvironmentBoundary(
            profile=os.getenv("SENTINEL_PROFILE", "light"),
            data_scope="exercise",
            source_mode=SourceMode.FIXTURE,
        ),
        impact=ImpactSummary(
            summary=incident.description,
            observed_at=incident.updated_at,
            source_mode=SourceMode.FIXTURE,
        ),
        top_hypothesis=_top_hypothesis(incident),
        next_decision=_next_decision(incident, approval),
        active_approval=(
            ActiveApprovalSummary(
                id=approval["id"],
                runbook_ref=approval["runbook_ref"],
                target=approval["target"],
                risk_level=approval["risk_level"],
                expires_at=approval["expires_at"],
                plan_hash=approval["plan_hash"],
            )
            if approval
            else None
        ),
        latest_verification=_latest_verification(incident),
        capabilities=IncidentCapabilities(
            can_decide_approval=bool(approval and normalized_role == "approver"),
            can_view_raw_evidence=True,
            denial_reason=(
                None
                if normalized_role == "approver"
                else "当前角色不能提交审批决定"
            ),
        ),
        milestones=_build_milestones(incident),
    )


@app.get("/api/incidents/{incident_id}/timeline")
async def get_timeline(
    incident_id: str,
    after_sequence: int = Query(default=0, ge=0),
):
    """事故时间线。"""
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")
    events = store.get_timeline(incident_id, after_sequence)
    return {
        "incident_id": incident_id,
        "events": [
            {
                "id": e.id,
                "sequence": e.sequence,
                "event_type": e.event_type,
                "actor": e.actor,
                "payload": e.payload,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in events
        ],
    }


# ---- 审批 ----

@app.post("/api/incidents/{incident_id}/approvals", status_code=status.HTTP_201_CREATED)
async def request_approval(
    incident_id: str,
    data: ApprovalRequest,
    role: Optional[str] = Header(default=None, alias="X-Sentinel-Role"),
):
    """创建审批请求。"""
    _require_role(role, "planner", "scenario_operator", "system")
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")
    if data.risk_level == RiskLevel.R2:
        raise HTTPException(status_code=400, detail="R2 操作在 MVP 中禁用，请升级人工处理")
    if data.risk_level == RiskLevel.R3:
        raise HTTPException(status_code=400, detail="R3 操作永久禁止")
    try:
        approval = store.create_approval(incident_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return approval


@app.put("/api/incidents/{incident_id}/approvals/{approval_id}")
async def decide_approval(
    incident_id: str,
    approval_id: str,
    decision: ApprovalDecision,
    role: Optional[str] = Header(default=None, alias="X-Sentinel-Role"),
):
    """审批决定。"""
    decided_by = _require_role(role, "approver")
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")
    result = store.decide_approval(approval_id, decision, decided_by=decided_by, incident_id=incident_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"审批 {approval_id} 不存在或已决定")
    return result


@app.get("/api/incidents/{incident_id}/approvals")
async def list_approvals(incident_id: str):
    """审批列表。"""
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")
    approvals = [
        a for a in store._approvals.values()
        if a["incident_id"] == incident_id
    ]
    return {"items": approvals}


@app.get("/api/approvals")
async def list_all_approvals(
    status_filter: Optional[str] = Query(default="pending", alias="status"),
):
    """全局审批队列，默认只返回仍需人工处理的请求。"""
    allowed_statuses = {"pending", "approved", "rejected", "expired", "all"}
    if status_filter not in allowed_statuses:
        raise HTTPException(status_code=400, detail="不支持的审批状态筛选")

    items = []
    for approval in store._approvals.values():
        if status_filter != "all" and approval["status"] != status_filter:
            continue
        incident = store.get_incident(approval["incident_id"])
        if not incident:
            continue
        items.append({
            **approval,
            "incident": {
                "id": incident.id,
                "status": incident.status.value,
                "severity": incident.severity.value,
                "alert_name": incident.alert_name,
                "description": incident.description,
                "updated_at": incident.updated_at.isoformat(),
            },
        })

    items.sort(key=lambda item: (
        item["status"] != "pending",
        item["expires_at"],
        item["created_at"],
    ))
    return {"items": items, "total": len(items)}


# ---- 场景 ----

@app.get("/api/scenarios")
async def list_scenarios():
    """场景列表。"""
    scenarios = store.list_scenarios()
    return {"items": scenarios}


@app.post("/api/scenarios/{scenario_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_scenario(
    scenario_id: str,
    role: Optional[str] = Header(default=None, alias="X-Sentinel-Role"),
):
    """启动演练场景。"""
    _require_role(role, "scenario_operator")
    scenario = store._scenarios.get(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"场景 {scenario_id} 不存在")

    service_target = next(
        (
            service
            for service in ("payment", "inventory", "order")
            if service in scenario_id
        ),
        "order",
    )
    target = f"{service_target}-api"
    severity = (
        IncidentSeverity.CRITICAL
        if scenario["category"] in {"database", "kubernetes", "resource"}
        else IncidentSeverity.WARNING
    )
    fingerprint = f"exercise:{scenario_id}"
    existing = store.find_by_fingerprint(fingerprint)
    if existing and existing.status not in {
        IncidentStatus.RESOLVED,
        IncidentStatus.ESCALATED,
        IncidentStatus.FAILED,
    }:
        raise HTTPException(status_code=409, detail="该场景已有活动演练")
    incident = store.create_incident(
        IncidentCreate(
            alert_source=AlertSource(
                alertmanager_id=f"scenario:{scenario_id}",
                fingerprint=fingerprint,
                alert_name=f"{target} / {scenario['name']}",
                severity=severity,
                description=scenario["description"],
                started_at=datetime.now(),
            )
        )
    )
    store.add_timeline_event(
        incident.id,
        "scenario.started",
        "scenario_runner",
        {"scenario_id": scenario_id, "profile": "light", "target": target},
    )
    store.set_status(incident, IncidentStatus.TRIAGING, "故障注入已确认")
    store.set_status(incident, IncidentStatus.DIAGNOSING, "Agent 开始关联诊断信号")

    evidence = scenario.get("expected_evidence") or [
        f"Prometheus: {target} 指标偏离基线",
        f"Loki: {target} 故障日志已归档",
        f"Tempo: {target} 依赖调用链异常",
    ]
    for index, summary in enumerate(evidence, start=1):
        store.add_timeline_event(
            incident.id,
            "evidence.collected",
            "diagnostic_gateway",
            {
                "source": ["prometheus", "loki", "tempo"][index % 3],
                "summary": summary,
                "evidence_id": f"ev-{incident.id[:8]}-{index}",
            },
        )
    store.add_timeline_event(
        incident.id,
        "hypothesis.generated",
        "investigator_fixture",
        {
            "statement": scenario["name"] + " 与目标服务异常信号一致",
            "confidence": 0.88,
            "category": scenario["category"],
            "affected_service": target,
            "supporting_evidence": len(evidence),
            "opposing_evidence": "payment-api / PostgreSQL 基线正常",
        },
    )

    allowed_runbooks = scenario.get("allowlisted_runbooks", [])
    runbook_ref = allowed_runbooks[0] if allowed_runbooks else "no_op"
    store.set_status(incident, IncidentStatus.PLAN_PROPOSED, "形成受限恢复方案")
    if runbook_ref == "db_rollback@1":
        store.set_status(incident, IncidentStatus.ESCALATED, "R2 回滚在 MVP 中禁用")
        store.add_timeline_event(
            incident.id,
            "incident.escalated",
            "policy_gate",
            {"reason": "R2 操作在 MVP 中禁用", "runbook_ref": runbook_ref},
        )
    elif runbook_ref == "no_op":
        store.set_status(incident, IncidentStatus.VERIFYING, "观察自动恢复")
        store.add_timeline_event(
            incident.id,
            "recovery.verified",
            "verification_fixture",
            {"result": "passed", "action": "none", "window_seconds": 60},
        )
        store.set_status(incident, IncidentStatus.RESOLVED, "自动恢复验证通过")
        incident.resolved_at = datetime.now()
    else:
        parameters = {"reason": f"修复 {scenario_id} 的演练故障"}
        if runbook_ref == "scale_deployment@1":
            parameters["replicas"] = 4
        store.set_status(incident, IncidentStatus.AWAITING_APPROVAL, "等待人工批准 R1 动作")
        store.create_approval(
            incident.id,
            ApprovalRequest(
                plan_id=f"plan-{incident.id[:8]}",
                runbook_ref=runbook_ref,
                target=target,
                parameters=parameters,
                risk_level=RiskLevel.R1,
                plan_hash=compute_plan_hash(runbook_ref, target, parameters, incident.id),
                hypothesis_id=f"hyp-{incident.id[:8]}",
            ),
        )

    return {
        "exercise_id": str(uuid4()),
        "scenario_id": scenario_id,
        "incident_id": incident.id,
        "status": incident.status.value,
        "message": f"场景 {scenario_id} 已启动",
    }


# ---- SSE（事故实时推送） ----


@app.get("/api/incidents/{incident_id}/stream")
async def stream_incident(
    incident_id: str,
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
):
    """SSE 实时推送事故更新。"""
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")
    try:
        initial_sequence = int(last_event_id) if last_event_id else 0
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Last-Event-ID 必须是时间线序号") from exc
    if initial_sequence < 0:
        raise HTTPException(status_code=400, detail="Last-Event-ID 不能为负数")

    async def event_generator():
        last_seq = initial_sequence
        # 先发送当前状态
        yield f"data: {json.dumps({'type': 'status', 'status': incident.status.value})}\n\n"
        # 然后轮询新事件（MVP 简化实现，正式版用 outbox + dispatcher）
        for _ in range(300):  # 最多 5 分钟
            events = store.get_timeline(incident_id, last_seq)
            for event in events:
                yield f"id: {event.sequence}\nevent: timeline_event\ndata: {json.dumps({'type': 'timeline_event', 'event': {
                    'id': event.id,
                    'sequence': event.sequence,
                    'event_type': event.event_type,
                    'actor': event.actor,
                    'payload': event.payload,
                    'timestamp': event.timestamp.isoformat(),
                }})}\n\n"
                last_seq = max(last_seq, event.sequence)
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---- 演示数据 ----

@app.post("/api/demo/seed", status_code=status.HTTP_201_CREATED)
async def seed_demo_data():
    """注入演示数据。"""
    import random

    demo_incidents = [
        {
            "alert_source": AlertSource(
                alertmanager_id="alt-001",
                fingerprint="fp-payment-latency-001",
                alert_name="Payment API High Latency",
                severity=IncidentSeverity.CRITICAL,
                description="payment-api p99 延迟从 150ms 飙升到 3200ms，持续 12 分钟",
                started_at=datetime.now() - timedelta(minutes=15),
            ),
            "status_sequence": [
                IncidentStatus.TRIAGING,
                IncidentStatus.DIAGNOSING,
                IncidentStatus.PLAN_PROPOSED,
                IncidentStatus.AWAITING_APPROVAL,
            ],
        },
        {
            "alert_source": AlertSource(
                alertmanager_id="alt-002",
                fingerprint="fp-order-db-001",
                alert_name="Order Service 5xx Error Rate",
                severity=IncidentSeverity.WARNING,
                description="order-api 5xx 错误率从 0.3% 上升到 12%",
                started_at=datetime.now() - timedelta(minutes=8),
            ),
            "status_sequence": [
                IncidentStatus.TRIAGING,
                IncidentStatus.DIAGNOSING,
            ],
        },
        {
            "alert_source": AlertSource(
                alertmanager_id="alt-003",
                fingerprint="fp-inventory-sync-001",
                alert_name="Inventory Stock Sync Lag",
                severity=IncidentSeverity.WARNING,
                description="inventory-api 库存同步延迟从 2s 上升到 180s",
                started_at=datetime.now() - timedelta(minutes=25),
            ),
            "status_sequence": [
                IncidentStatus.TRIAGING,
                IncidentStatus.DIAGNOSING,
                IncidentStatus.ESCALATED,
            ],
        },
        {
            "alert_source": AlertSource(
                alertmanager_id="alt-004",
                fingerprint="fp-cpu-sat-001",
                alert_name="Inventory CPU Saturation",
                severity=IncidentSeverity.CRITICAL,
                description="inventory-api CPU 使用率持续 >95%",
                started_at=datetime.now() - timedelta(minutes=5),
            ),
            "status_sequence": [
                IncidentStatus.TRIAGING,
                IncidentStatus.DIAGNOSING,
                IncidentStatus.PLAN_PROPOSED,
                IncidentStatus.AWAITING_APPROVAL,
                IncidentStatus.EXECUTING,
                IncidentStatus.VERIFYING,
                IncidentStatus.RESOLVED,
            ],
        },
    ]

    created = []
    for demo in demo_incidents:
        create_data = IncidentCreate(alert_source=demo["alert_source"])
        incident = store.create_incident(create_data)
        # 推进到指定状态序列
        for target_status in demo["status_sequence"]:
            old_status = incident.status
            incident.status = target_status
            incident.updated_at = datetime.now()
            incident.version += 1
            event_type = f"incident.status_changed"
            store._add_timeline_event(
                incident, event_type, "system",
                {"from": old_status.value, "to": target_status.value},
            )
            if target_status == IncidentStatus.RESOLVED:
                incident.resolved_at = datetime.now()

        # 添加可读的证据、假设和演示审批，确保首屏可以完整回放调查链路。
        affected_service = (
            "payment-api"
            if "Payment" in demo["alert_source"].alert_name
            else "inventory-api"
        )
        evidence_payloads = [
            {
                "source": "prometheus",
                "summary": f"{demo['alert_source'].alert_name} 指标异常",
                "evidence_id": f"ev-{incident.id[:8]}-metrics",
            },
            {
                "source": "loki",
                "summary": f"{affected_service} 日志出现连续超时或错误",
                "evidence_id": f"ev-{incident.id[:8]}-logs",
            },
            {
                "source": "tempo",
                "summary": "跨服务 Trace 将慢点收敛到同一依赖调用",
                "evidence_id": f"ev-{incident.id[:8]}-trace",
            },
        ]
        for payload in evidence_payloads:
            store._add_timeline_event(incident, "evidence.collected", "diagnostic_gateway", payload)
        store._add_timeline_event(
            incident,
            "hypothesis.generated",
            "investigator_fixture",
            {
                "statement": f"{affected_service} 的依赖调用异常是当前事故的主要根因",
                "confidence": 0.86,
                "category": random.choice(["network", "application", "database"]),
                "affected_service": affected_service,
                "supporting_evidence": [p["evidence_id"] for p in evidence_payloads],
                "opposing_evidence": "其他业务服务基线正常",
            },
        )

        if incident.status == IncidentStatus.AWAITING_APPROVAL:
            target = "payment-api"
            runbook_ref = "restart_deployment@1"
            parameters = {"reason": "清除演练故障并验证恢复"}
            approval = store.create_approval(
                incident.id,
                ApprovalRequest(
                    plan_id=f"plan-{incident.id[:8]}",
                    runbook_ref=runbook_ref,
                    target=target,
                    parameters=parameters,
                    risk_level=RiskLevel.R1,
                    plan_hash=compute_plan_hash(runbook_ref, target, parameters, incident.id),
                    hypothesis_id=f"hyp-{incident.id[:8]}",
                ),
            )
        elif incident.status == IncidentStatus.RESOLVED:
            target = "inventory-api"
            runbook_ref = "scale_deployment@1"
            parameters = {"replicas": 4, "reason": "验证扩容后的恢复窗口"}
            approval = store.create_approval(
                incident.id,
                ApprovalRequest(
                    plan_id=f"plan-{incident.id[:8]}",
                    runbook_ref=runbook_ref,
                    target=target,
                    parameters=parameters,
                    risk_level=RiskLevel.R1,
                    plan_hash=compute_plan_hash(runbook_ref, target, parameters, incident.id),
                    hypothesis_id=f"hyp-{incident.id[:8]}",
                ),
                allow_terminal_fixture=True,
            )
            # 已解决事故只用于展示历史审批，不再次触发动作；直接写入只读演示记录。
            approval.update(
                {
                    "status": "approved",
                    "decided_at": datetime.now().isoformat(),
                    "decided_by": "demo-operator",
                    "decision_reason": "演示数据中的已验证恢复",
                }
            )
            store.add_timeline_event(
                incident.id,
                "approval.decided",
                "approver:demo-operator",
                {"approved": True, "reason": "演示数据中的已验证恢复", "fixture": True},
            )

        created.append(incident.id)

    return {"message": f"已创建 {len(created)} 个演示事故", "incident_ids": created}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
