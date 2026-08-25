"""
Sentinel-X Control API — 主应用入口。

提供以下端点组：
- GET  /health — 健康检查
- GET  /api/incidents — 事故列表
- POST /api/incidents — 创建事故（Alert Ingress）
- GET  /api/incidents/{id} — 事故详情
- GET  /api/incidents/{id}/timeline — 事故时间线
- GET  /api/incidents/{id}/export — 脱敏事故包（light）
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
import re
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from demo.scenarios.loader import ScenarioLoadError, ScenarioLoader
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sentinel_x_contracts import (
    ActiveApprovalSummary,
    EnvironmentBoundary,
    HypothesisSummary,
    ImpactSummary,
    IncidentSeverity,
    IncidentStatus,
    IncidentCapabilities,
    IncidentMilestone,
    IncidentPhase,
    NextDecision,
    SourceMode,
    RiskLevel,
    VerificationSummary,
)
from sentinel_x_contracts.scenario import ScenarioDefinition
from sentinel_x_domain.services import compute_plan_hash
from sentinel_x_policy import check_mvp_policy
from sentinel_x_control_api.eval_archive import (
    EvaluationArchiveError,
    get_evaluation_archive,
    list_evaluation_archives,
)
from sentinel_x_control_api.local_state import LocalStateSnapshot
from sentinel_x_control_api.local_workflow import LocalExerciseWorkflow
from sentinel_x_control_api.postgres import apply_migrations, check_postgres_health
from sentinel_x_control_api.postgres_repository import PostgresIncidentRepository


EVAL_ARCHIVE_DIR = Path(os.getenv("SENTINEL_EVAL_ARCHIVE_DIR", "evals/results"))
EVAL_ARCHIVE_MAX_BYTES = int(os.getenv("SENTINEL_EVAL_ARCHIVE_MAX_BYTES", "2097152"))
INCIDENT_EXPORT_MAX_BYTES = int(os.getenv("SENTINEL_INCIDENT_EXPORT_MAX_BYTES", "1048576"))
SCENARIOS_DIR = Path(__file__).resolve().parents[4] / "demo" / "scenarios"


def _evaluation_archive_error_response(error: EvaluationArchiveError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"detail": error.detail, "code": error.code},
    )


_EXPORT_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|api[_-]?key|token|secret|password)", re.IGNORECASE
)
_EXPORT_TOKEN = re.compile(r"(?:Bearer\s+|sk-|eyJ|ghp_|xox[baprs]-)[A-Za-z0-9._~+/=-]{12,}")
_EXPORT_KEY_VALUE = re.compile(
    r"(api[_-]?key|apikey|token|secret|password)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


def _sanitize_export_value(value):
    """递归脱敏导出字段，保留结构但不携带凭据或原始令牌。"""
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if _EXPORT_SENSITIVE_KEY.search(str(key))
                else _sanitize_export_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_export_value(item) for item in value]
    if isinstance(value, str):
        return _EXPORT_KEY_VALUE.sub(r"\1: [REDACTED]", _EXPORT_TOKEN.sub("[REDACTED]", value))
    return value


def _build_incident_export(incident: "StoredIncident", approvals: list[dict]) -> dict:
    """构建 light 事故包；哈希覆盖 manifest 之外的规范化内容。"""
    payload = {
        "schema_version": "1.0",
        "export_id": f"incident-export-{incident.id}-v{incident.version}",
        "generated_at": datetime.now().isoformat(),
        "profile": "local-isolated-fixture",
        "source_mode": "fixture",
        "incident": _sanitize_export_value({
            "id": incident.id,
            "fingerprint": incident.fingerprint,
            "status": incident.status.value,
            "severity": incident.severity.value,
            "alert_name": incident.alert_name,
            "description": incident.description,
            "created_at": incident.created_at.isoformat(),
            "updated_at": incident.updated_at.isoformat(),
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
            "workflow_id": incident.workflow_id,
            "version": incident.version,
        }),
        "timeline": [
            _sanitize_export_value({
                "id": event.id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "actor": event.actor,
                "payload": event.payload,
                "timestamp": event.timestamp.isoformat(),
            })
            for event in incident.timeline
        ],
        "approvals": [
            _sanitize_export_value(approval)
            for approval in approvals
            if approval.get("incident_id") == incident.id
        ],
    }
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    content_bytes = len(content.encode("utf-8"))
    if content_bytes > INCIDENT_EXPORT_MAX_BYTES:
        raise ValueError("事故包超过导出大小上限")
    payload["manifest"] = {
        "content_sha256": f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
        "content_bytes": content_bytes,
        "timeline_events": len(payload["timeline"]),
        "approvals": len(payload["approvals"]),
    }
    return payload


def _load_scenario_definitions() -> dict[str, ScenarioDefinition]:
    """从本地 YAML 场景目录加载当前可运行的场景定义。"""
    try:
        scenarios = ScenarioLoader(SCENARIOS_DIR).load_all()
    except ScenarioLoadError as exc:
        raise HTTPException(status_code=503, detail="场景目录不可用") from exc
    return {scenario.id: scenario for scenario in scenarios}


def _public_scenario_projection(scenario: ScenarioDefinition) -> dict:
    """投影场景的安全公开字段，排除评测与注入内部信息。"""
    primary_fault = scenario.faults[0]
    return {
        "id": scenario.id,
        "name": scenario.name,
        "version": scenario.version,
        "description": scenario.description,
        "category": scenario.category.value,
        "target_service": primary_fault.target_service,
        "target_namespace": primary_fault.target_namespace,
        "allowlisted_runbooks": list(scenario.allowlisted_runbooks),
    }


# ---------------------------------------------------------------------------
# Control API 本地请求与响应模型；跨服务枚举直接复用 contracts。
# ---------------------------------------------------------------------------


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


class AlertmanagerAlert(BaseModel):
    """Alertmanager webhook 中被 Control API 使用的字段。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime = Field(alias="startsAt")
    ends_at: Optional[datetime] = Field(default=None, alias="endsAt")
    fingerprint: Optional[str] = None


class AlertmanagerWebhook(BaseModel):
    """版本化 webhook 输入；未知顶层字段不进入领域模型。"""

    model_config = ConfigDict(extra="ignore")

    receiver: str = ""
    status: str = "firing"
    alerts: list[AlertmanagerAlert] = Field(default_factory=list, max_length=50)


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


class ScenarioResponse(StrictBaseModel):
    id: str
    name: str
    version: int
    description: str
    category: str
    target_service: str
    target_namespace: str
    allowlisted_runbooks: list[str] = Field(default_factory=list)


class ScenarioListResponse(StrictBaseModel):
    items: list[ScenarioResponse]


class ScenarioRunResponse(StrictBaseModel):
    exercise_id: str
    scenario_id: str
    incident_id: str
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    environment: str = "local-demo"
    actions_enabled: bool = False


# ---------------------------------------------------------------------------
# 本地状态存储。SQLite 快照只服务 local-isolated profile，不能替代 PostgreSQL 投影。
# ---------------------------------------------------------------------------


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


_ALLOWED_STATUS_TRANSITIONS = {
    IncidentStatus.DETECTED: {IncidentStatus.TRIAGING, IncidentStatus.FAILED},
    IncidentStatus.TRIAGING: {IncidentStatus.DIAGNOSING, IncidentStatus.ESCALATED, IncidentStatus.FAILED},
    IncidentStatus.DIAGNOSING: {
        IncidentStatus.PLAN_PROPOSED,
        IncidentStatus.VERIFYING,
        IncidentStatus.ESCALATED,
        IncidentStatus.FAILED,
    },
    IncidentStatus.PLAN_PROPOSED: {IncidentStatus.AWAITING_APPROVAL, IncidentStatus.VERIFYING, IncidentStatus.ESCALATED, IncidentStatus.FAILED},
    IncidentStatus.AWAITING_APPROVAL: {IncidentStatus.EXECUTING, IncidentStatus.ESCALATED, IncidentStatus.FAILED},
    IncidentStatus.EXECUTING: {IncidentStatus.VERIFYING, IncidentStatus.ESCALATED, IncidentStatus.FAILED},
    IncidentStatus.VERIFYING: {IncidentStatus.RESOLVED, IncidentStatus.ESCALATED, IncidentStatus.FAILED},
    IncidentStatus.RESOLVED: set(),
    IncidentStatus.ESCALATED: set(),
    IncidentStatus.FAILED: set(),
}


class InMemoryStore:
    """本地读模型缓存，可选用 SQLite 快照跨进程恢复。"""

    def __init__(self, state_path: str | Path | None = None):
        self._incidents: dict[str, StoredIncident] = {}
        self._fingerprint_index: dict[str, str] = {}
        self._approvals: dict[str, dict] = {}
        self._workflow_checkpoints: dict[str, dict] = {}
        self._outbox: list[dict] = []
        self._state_snapshot = LocalStateSnapshot(state_path) if state_path else None
        if self._state_snapshot:
            self._restore()

    def reset(self) -> None:
        """清空本地状态，供隔离测试和明确的本地重置流程使用。"""
        self._incidents.clear()
        self._fingerprint_index.clear()
        self._approvals.clear()
        self._workflow_checkpoints.clear()
        self._outbox.clear()
        if self._state_snapshot:
            self._state_snapshot.clear()

    def flush(self) -> None:
        """把由 fixture 直接修改的对象同步到本地快照。"""
        if self._state_snapshot:
            self._state_snapshot.save(self._snapshot_payload())

    def _snapshot_payload(self) -> dict:
        return {
            "schema_version": 2,
            "incidents": [
                {
                    "id": incident.id,
                    "fingerprint": incident.fingerprint,
                    "status": incident.status.value,
                    "severity": incident.severity.value,
                    "alert_name": incident.alert_name,
                    "description": incident.description,
                    "created_at": incident.created_at.isoformat(),
                    "updated_at": incident.updated_at.isoformat(),
                    "resolved_at": (
                        incident.resolved_at.isoformat() if incident.resolved_at else None
                    ),
                    "workflow_id": incident.workflow_id,
                    "version": incident.version,
                    "timeline": [
                        event.model_dump(mode="json") for event in incident.timeline
                    ],
                }
                for incident in self._incidents.values()
            ],
            "approvals": list(self._approvals.values()),
            "workflow_checkpoints": list(self._workflow_checkpoints.values()),
            "outbox": list(self._outbox),
        }

    def _restore(self) -> None:
        assert self._state_snapshot is not None
        payload = self._state_snapshot.load()
        if payload is None:
            return
        if payload.get("schema_version") not in {1, 2}:
            raise ValueError("本地状态快照版本不受支持")
        incidents = payload.get("incidents")
        approvals = payload.get("approvals")
        checkpoints = payload.get("workflow_checkpoints", [])
        outbox = payload.get("outbox", [])
        if not all(isinstance(value, list) for value in (incidents, approvals, checkpoints, outbox)):
            raise ValueError("本地状态快照结构无效")
        for raw in incidents:
            if not isinstance(raw, dict):
                raise ValueError("本地状态快照包含无效事故")
            timeline = raw.get("timeline", [])
            if not isinstance(timeline, list):
                raise ValueError("本地状态快照包含无效时间线")
            incident = StoredIncident(
                id=str(raw["id"]),
                fingerprint=str(raw["fingerprint"]),
                status=IncidentStatus(raw["status"]),
                severity=IncidentSeverity(raw["severity"]),
                alert_name=str(raw["alert_name"]),
                description=str(raw["description"]),
                created_at=datetime.fromisoformat(str(raw["created_at"])),
                updated_at=datetime.fromisoformat(str(raw["updated_at"])),
                resolved_at=(
                    datetime.fromisoformat(str(raw["resolved_at"]))
                    if raw.get("resolved_at")
                    else None
                ),
                workflow_id=raw.get("workflow_id"),
                version=int(raw["version"]),
                timeline=[TimelineEvent.model_validate(event) for event in timeline],
                _timeline_seq=max(
                    (int(event.get("sequence", 0)) for event in timeline if isinstance(event, dict)),
                    default=0,
                ),
            )
            self._incidents[incident.id] = incident
            self._fingerprint_index[incident.fingerprint] = incident.id
        for approval in approvals:
            if not isinstance(approval, dict) or not isinstance(approval.get("id"), str):
                raise ValueError("本地状态快照包含无效审批")
            self._approvals[approval["id"]] = approval
        for event in outbox:
            if not isinstance(event, dict) or not isinstance(event.get("id"), str):
                raise ValueError("本地状态快照包含无效 outbox 事件")
            self._outbox.append(dict(event))
        orphan_checkpoint_found = False
        for checkpoint in checkpoints:
            incident_id = checkpoint.get("incident_id") if isinstance(checkpoint, dict) else None
            if not isinstance(incident_id, str) or incident_id not in self._incidents:
                orphan_checkpoint_found = True
                continue
            self._workflow_checkpoints[incident_id] = checkpoint
        if orphan_checkpoint_found:
            # 测试 reset 或旧版本可能留下孤立 checkpoint；它没有可恢复的事故，
            # 启动时安全丢弃并写回干净快照，避免阻塞 local profile 冷启动。
            self.flush()

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
        self.flush()
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
        self._outbox.append({
            "id": str(uuid4()),
            "aggregate_type": "incident",
            "aggregate_id": incident.id,
            "sequence": event.sequence,
            "event_type": event.event_type,
            "actor": event.actor,
            "payload": event.payload,
            "occurred_at": event.timestamp.isoformat(),
            "published_at": None,
        })
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
        event = self._add_timeline_event(incident, event_type, actor, payload)
        self.flush()
        return event

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
        if new_status not in _ALLOWED_STATUS_TRANSITIONS[old_status]:
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
        self.flush()

    def get_timeline(
        self,
        incident_id: str,
        after_sequence: int = 0,
    ) -> list[TimelineEvent]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return []
        return [e for e in incident.timeline if e.sequence > after_sequence]

    def list_outbox(self, *, unpublished_only: bool = False) -> list[dict]:
        """按事故序号返回可重试的投影事件。"""
        events = self._outbox
        if unpublished_only:
            events = [event for event in events if event.get("published_at") is None]
        return [dict(event) for event in events]

    def mark_outbox_published(self, event_id: str) -> bool:
        for event in self._outbox:
            if event.get("id") == event_id:
                if event.get("published_at") is None:
                    event["published_at"] = datetime.now().isoformat()
                    self.flush()
                return True
        return False

    def list_approvals(self, incident_id: Optional[str] = None) -> list[dict]:
        """按创建顺序返回审批，不向调用方暴露内部可变映射。"""
        approvals = list(self._approvals.values())
        if incident_id is not None:
            approvals = [
                approval for approval in approvals if approval["incident_id"] == incident_id
            ]
        return sorted(approvals, key=lambda approval: approval["created_at"])

    def create_workflow_checkpoint(
        self,
        incident_id: str,
        scenario_id: str,
        phase: str,
    ) -> dict:
        """创建或返回本地可恢复工作流的唯一检查点。"""
        incident = self._incidents.get(incident_id)
        if not incident:
            raise ValueError("事故不存在")
        existing = self._workflow_checkpoints.get(incident_id)
        if existing:
            if existing["scenario_id"] != scenario_id:
                raise ValueError("同一事故不能绑定多个场景工作流")
            return dict(existing)
        checkpoint = {
            "workflow_id": f"incident/{incident_id}",
            "incident_id": incident_id,
            "scenario_id": scenario_id,
            "phase": phase,
            "action_execution_id": None,
            "completed": False,
            "updated_at": datetime.now().isoformat(),
        }
        incident.workflow_id = checkpoint["workflow_id"]
        incident.updated_at = datetime.now()
        incident.version += 1
        self._workflow_checkpoints[incident_id] = checkpoint
        self.flush()
        return dict(checkpoint)

    def get_workflow_checkpoint(self, incident_id: str) -> Optional[dict]:
        checkpoint = self._workflow_checkpoints.get(incident_id)
        return dict(checkpoint) if checkpoint else None

    def update_workflow_checkpoint(
        self,
        incident_id: str,
        *,
        phase: Optional[str] = None,
        action_execution_id: Optional[str] = None,
        completed: Optional[bool] = None,
    ) -> dict:
        """持久化本地编排进度；只保存恢复所需的引用。"""
        checkpoint = self._workflow_checkpoints.get(incident_id)
        if not checkpoint:
            raise ValueError("工作流检查点不存在")
        if phase is not None:
            checkpoint["phase"] = phase
        if action_execution_id is not None:
            checkpoint["action_execution_id"] = action_execution_id
        if completed is not None:
            checkpoint["completed"] = completed
        checkpoint["updated_at"] = datetime.now().isoformat()
        self.flush()
        return dict(checkpoint)

    def list_resumable_workflow_checkpoints(self) -> list[dict]:
        return [
            dict(checkpoint)
            for checkpoint in self._workflow_checkpoints.values()
            if not checkpoint["completed"]
        ]

    def create_approval(
        self,
        incident_id: str,
        data: ApprovalRequest,
        allow_terminal_fixture: bool = False,
    ) -> dict:
        incident = self._incidents.get(incident_id)
        if not incident:
            raise ValueError("事故不存在")
        policy = check_mvp_policy(data.runbook_ref, data.target)
        if not policy.allowed:
            raise ValueError(policy.reason)
        if data.risk_level != policy.risk_level:
            raise ValueError("审批风险等级与登记的 Runbook 不一致")
        expected_plan_hash = compute_plan_hash(
            data.runbook_ref,
            data.target,
            data.parameters,
            incident_id,
        )
        if data.plan_hash != expected_plan_hash:
            raise ValueError("审批 plan hash 与规范化计划不一致")
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
        self.flush()
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
            self.flush()
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

        # 审批决定只记录不可变用户意图；动作、验证和终态由编排器推进。
        # 这样 API 不会绕过 LocalExerciseWorkflow/未来 Temporal 的执行边界。
        self.flush()
        return approval

    def expire_approval(self, approval_id: str) -> Optional[dict]:
        """在恢复或后台扫描时将已过期审批标记为不可执行。"""
        approval = self._approvals.get(approval_id)
        if not approval or approval["status"] in {"rejected", "expired"}:
            return approval
        approval["status"] = "expired"
        self.flush()
        return approval


class PostgresStore(InMemoryStore):
    """full profile 的 PostgreSQL 写入适配器。

    读模型暂时保留进程内对象以兼容现有 API 响应；Incident、Timeline 和
    Outbox 的写入由 PostgreSQL repository 作为权威事务完成。启动恢复/持久
    读模型将在下一切片接入，full profile 不会静默回退到 SQLite。
    """

    def __init__(self, repository: PostgresIncidentRepository):
        super().__init__(state_path=None)
        self.repository = repository
        self.rebuild_projection()

    @staticmethod
    def _timestamp(value: datetime) -> datetime:
        return value.replace(tzinfo=None) if value.tzinfo else value

    def _hydrate(self, record) -> StoredIncident:
        timeline = []
        for item in self.repository.list_timeline(record.id):
            actor = {
                "APPROVER": "approver:postgres",
                "INVESTIGATOR": "investigator",
                "WORKFLOW": "workflow",
                "SCENARIO_RUNNER": "scenario_runner",
                "USER": "user",
            }.get(item.actor_type, "system")
            timeline.append(TimelineEvent(
                id=str(item.id), incident_id=str(item.incident_id),
                sequence=item.sequence, event_type=item.event_type, actor=actor,
                payload=dict(item.payload), timestamp=self._timestamp(item.occurred_at),
            ))
        opened_at = self._timestamp(record.opened_at)
        incident = StoredIncident(
            id=str(record.id), fingerprint=record.fingerprint,
            status=IncidentStatus(record.status), severity=IncidentSeverity(record.severity),
            alert_name=record.service, description="",
            created_at=opened_at, updated_at=opened_at,
            workflow_id=record.workflow_id, version=max(1, record.projection_version),
            timeline=timeline, _timeline_seq=max((event.sequence for event in timeline), default=0),
        )
        self._incidents[incident.id] = incident
        self._fingerprint_index[incident.fingerprint] = incident.id
        return incident

    def rebuild_projection(self) -> None:
        self._incidents.clear()
        self._fingerprint_index.clear()
        for record in self.repository.list_incidents():
            self._hydrate(record)

    def find_by_fingerprint(self, fingerprint: str) -> StoredIncident | None:
        incident = super().find_by_fingerprint(fingerprint)
        if incident:
            return incident
        for record in self.repository.list_incidents():
            if record.fingerprint == fingerprint:
                return self._hydrate(record)
        return None

    def get_incident(self, incident_id: str) -> StoredIncident | None:
        incident = super().get_incident(incident_id)
        if incident:
            return incident
        try:
            record = self.repository.get_incident(UUID(incident_id))
        except ValueError:
            return None
        return self._hydrate(record) if record else None

    def create_incident(self, data: IncidentCreate) -> StoredIncident:
        existing = self.find_by_fingerprint(data.alert_source.fingerprint)
        record = self.repository.create_incident(
            fingerprint=data.alert_source.fingerprint,
            severity=data.alert_source.severity.value,
            service=data.alert_source.alert_name,
            workflow_id=f"incident/{uuid4()}",
        )
        if existing and existing.id == str(record.id):
            self._hydrate(record)
            return self._incidents[str(record.id)]
        self._hydrate(record)
        return self._incidents[str(record.id)]

    def set_status(
        self,
        incident: StoredIncident,
        new_status: IncidentStatus,
        reason: str,
        actor: str = "system",
    ) -> None:
        old_status = incident.status
        if new_status == old_status:
            return
        if new_status not in _ALLOWED_STATUS_TRANSITIONS[old_status]:
            raise ValueError(f"非法事故状态迁移: {old_status.value} -> {new_status.value}")
        actor_type = (
            "APPROVER" if actor.startswith("approver:")
            else "WORKFLOW" if actor in {"workflow", "local_action_gateway"}
            else "INVESTIGATOR" if "diagnostic" in actor or "investigator" in actor
            else "SCENARIO_RUNNER" if "scenario" in actor
            else "USER" if actor.startswith("user:")
            else "SYSTEM"
        )
        record, result = self.repository.transition_status(
            incident_id=UUID(incident.id),
            expected_status=old_status.value,
            new_status=new_status.value,
            actor_type=actor_type,
            payload={"from": old_status.value, "to": new_status.value, "reason": reason},
        )
        incident.status = new_status
        incident.updated_at = datetime.now()
        incident.version = max(1, record.projection_version)
        incident.timeline.append(TimelineEvent(
            id=str(result.id), incident_id=incident.id, sequence=result.sequence,
            event_type=result.event_type, actor=actor, payload=dict(result.payload),
            timestamp=self._timestamp(result.occurred_at),
        ))
        incident._timeline_seq = result.sequence

    def _add_timeline_event(
        self,
        incident: StoredIncident,
        event_type: str,
        actor: str,
        payload: dict | None = None,
    ) -> TimelineEvent:
        actor_type = (
            "APPROVER" if actor.startswith("approver:")
            else "WORKFLOW" if actor in {"workflow", "local_action_gateway"}
            else "INVESTIGATOR" if "diagnostic" in actor or "investigator" in actor
            else "SYSTEM"
        )
        result = self.repository.append_event(
            incident_id=UUID(incident.id),
            event_type=event_type,
            actor_type=actor_type,
            payload=payload or {},
        )
        event = TimelineEvent(
            id=str(result.id),
            incident_id=incident.id,
            sequence=result.sequence,
            event_type=result.event_type,
            actor=actor,
            payload=dict(result.payload),
            timestamp=result.occurred_at.replace(tzinfo=None),
        )
        incident._timeline_seq = result.sequence
        incident.timeline.append(event)
        return event

# ---------------------------------------------------------------------------
# 全局存储实例
# ---------------------------------------------------------------------------


LOCAL_STATE_PATH = Path(os.getenv("SENTINEL_LOCAL_STATE_DB", ".local/data/control-api.sqlite3"))
store = InMemoryStore(state_path=LOCAL_STATE_PATH)
local_workflow = LocalExerciseWorkflow(store, scenarios_dir=SCENARIOS_DIR)
ALERT_INGRESS_HMAC_KEY = os.getenv("ALERT_INGRESS_HMAC_KEY")
ALERT_INGRESS_MAX_BODY_BYTES = int(os.getenv("ALERT_INGRESS_MAX_BODY_BYTES", "1048576"))
ALERT_INGRESS_CLOCK_SKEW_SECONDS = 300
ALERT_INGRESS_REPLAY_TTL_SECONDS = int(os.getenv("ALERT_INGRESS_REPLAY_TTL_SECONDS", "300"))
ALERT_INGRESS_REPLAY_MAX_ENTRIES = int(os.getenv("ALERT_INGRESS_REPLAY_MAX_ENTRIES", "10000"))
_ALERT_INGRESS_REPLAY_CACHE: dict[str, float] = {}
_ALERT_INGRESS_REPLAY_LOCK = threading.Lock()
LOCAL_SESSION_SIGNING_KEY = os.getenv("SENTINEL_LOCAL_SESSION_SIGNING_KEY")
API_VERSION = "v1"


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期。"""
    global store
    if os.getenv("SENTINEL_PROFILE", "light") == "full":
        database_url = os.getenv("DATABASE_URL", "")
        if not database_url:
            raise RuntimeError("SENTINEL_PROFILE=full 缺少 DATABASE_URL")
        try:
            check_postgres_health(database_url)
            migrations_dir = Path(__file__).resolve().parents[4] / "migrations"
            apply_migrations(database_url, migrations_dir=migrations_dir)
            psycopg = __import__("psycopg")
            repository = PostgresIncidentRepository(
                lambda: psycopg.connect(database_url)
            )
            store = PostgresStore(repository)
            local_workflow.store = store
        except Exception as exc:  # noqa: BLE001 - full 启动必须 fail closed
            raise RuntimeError("SENTINEL_PROFILE=full PostgreSQL 初始化失败") from exc
    local_workflow.resume_all()
    yield


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


@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    """在 Pydantic 解析前拒绝明显超限的 webhook 请求体。"""
    content_length = request.headers.get("content-length")
    if content_length and request.url.path in {"/api/incidents", "/api/v1/webhooks/alertmanager"}:
        try:
            too_large = int(content_length) > ALERT_INGRESS_MAX_BODY_BYTES
        except ValueError:
            too_large = True
        if too_large:
            return JSONResponse(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                content={"detail": "Alert Ingress 请求体超过上限"},
            )
    return await call_next(request)


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
    """校验签名并拒绝 nonce 重放；演练场景使用内部调用而非该入口。"""
    if not ALERT_INGRESS_HMAC_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alert Ingress 未配置 HMAC 密钥",
        )
    timestamp = request.headers.get("X-Sentinel-Timestamp")
    signature = request.headers.get("X-Sentinel-Signature")
    nonce = request.headers.get("X-Sentinel-Nonce")
    if not timestamp or not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Alert Ingress 签名缺失")
    if not nonce or len(nonce) > 128:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Alert Ingress nonce 缺失或非法")
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Alert Ingress 时间戳非法") from exc
    if abs(datetime.now().timestamp() - timestamp_value) > ALERT_INGRESS_CLOCK_SKEW_SECONDS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Alert Ingress 签名已过期")
    raw_body = await request.body()
    if len(raw_body) > ALERT_INGRESS_MAX_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Alert Ingress 请求体超过上限")
    expected = hmac.new(
        ALERT_INGRESS_HMAC_KEY.encode("utf-8"),
        timestamp.encode("utf-8") + b"\n" + nonce.encode("utf-8") + b"\n" + raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature[7:], expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Alert Ingress 签名无效")

    now = time.time()
    with _ALERT_INGRESS_REPLAY_LOCK:
        expired = [
            cached_nonce
            for cached_nonce, seen_at in _ALERT_INGRESS_REPLAY_CACHE.items()
            if now - seen_at > ALERT_INGRESS_REPLAY_TTL_SECONDS
        ]
        for cached_nonce in expired:
            _ALERT_INGRESS_REPLAY_CACHE.pop(cached_nonce, None)
        if nonce in _ALERT_INGRESS_REPLAY_CACHE:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Alert Ingress 请求已重放")
        _ALERT_INGRESS_REPLAY_CACHE[nonce] = now
        if len(_ALERT_INGRESS_REPLAY_CACHE) > ALERT_INGRESS_REPLAY_MAX_ENTRIES:
            oldest_nonce = min(_ALERT_INGRESS_REPLAY_CACHE, key=_ALERT_INGRESS_REPLAY_CACHE.get)
            _ALERT_INGRESS_REPLAY_CACHE.pop(oldest_nonce, None)


def build_local_session_token(role: str, expires_at: int) -> str:
    """为隔离环境生成短期会话令牌；生产身份认证不在此实现。"""
    if not LOCAL_SESSION_SIGNING_KEY:
        raise RuntimeError("未配置本地会话签名密钥")
    payload = f"{role}:{int(expires_at)}"
    signature = hmac.new(
        LOCAL_SESSION_SIGNING_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"Bearer {payload}:{signature}"


async def _require_v1_session(request: Request) -> None:
    """v1 只接受短期签名会话，密钥缺失时明确 fail-closed。"""
    if not LOCAL_SESSION_SIGNING_KEY:
        raise HTTPException(status_code=503, detail="v1 会话认证未配置")
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="v1 会话令牌缺失或格式非法")
    parts = authorization.removeprefix("Bearer ").split(":")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="v1 会话令牌缺失或格式非法")
    role, expires_raw, supplied = parts
    if role not in {"viewer", "planner", "approver", "scenario_operator", "system"}:
        raise HTTPException(status_code=403, detail="v1 会话角色非法")
    try:
        expires_at = int(expires_raw)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="v1 会话令牌过期时间非法") from exc
    if expires_at <= int(time.time()):
        raise HTTPException(status_code=401, detail="v1 会话令牌已过期")
    expected = hmac.new(
        LOCAL_SESSION_SIGNING_KEY.encode("utf-8"),
        f"{role}:{expires_at}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="v1 会话令牌签名无效")
    request.state.session_role = role


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
        IncidentStatus.AWAITING_APPROVAL: ("review_approval", "核对恢复操作", "恢复操作等待审批流程继续。"),
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


@app.post("/api/v1/webhooks/alertmanager", status_code=status.HTTP_202_ACCEPTED)
async def receive_alertmanager_webhook(data: AlertmanagerWebhook, request: Request):
    """接收受 HMAC 保护的 Alertmanager webhook 并转换为领域告警。"""
    await _verify_alert_ingress(request)
    firing = next((alert for alert in data.alerts if alert.status == "firing"), None)
    if firing is None:
        return {"status": "ignored", "reason": "没有 firing 告警"}
    labels = firing.labels
    try:
        severity = IncidentSeverity(labels.get("severity", "warning"))
    except ValueError:
        raise HTTPException(status_code=422, detail="Alertmanager severity 非法") from None
    fingerprint = firing.fingerprint or hashlib.sha256(
        json.dumps(labels, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    alert_name = labels.get("alertname", "AlertmanagerAlert")
    source = AlertSource(
        alertmanager_id=data.receiver or "alertmanager",
        fingerprint=fingerprint,
        alert_name=alert_name,
        severity=severity,
        description=firing.annotations.get("description") or firing.annotations.get("summary") or alert_name,
        started_at=firing.starts_at,
    )
    incident = store.create_incident(IncidentCreate(alert_source=source))
    return {
        "status": "accepted",
        "id": incident.id,
        "fingerprint": incident.fingerprint,
        "incident_status": incident.status.value,
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
    request: Request,
    response: Response,
    role: Optional[str] = Header(default=None, alias="X-Sentinel-Role"),
):
    """事故详情。"""
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")
    approval = _active_approval(incident_id)
    normalized_role = getattr(request.state, "session_role", None) or role or "viewer"
    response.headers["ETag"] = f'"incident-{incident.id}-v{incident.version}"'
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
            can_view_raw_evidence=normalized_role in {
                "approver",
                "planner",
                "scenario_operator",
                "system",
            },
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


@app.get("/api/incidents/{incident_id}/export")
async def export_incident(incident_id: str):
    """导出 light 事故包；只返回脱敏 JSON，不接受文件路径或下载参数。"""
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")
    try:
        return _build_incident_export(incident, store.list_approvals(incident_id))
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


# ---- 审批 ----

@app.post("/api/incidents/{incident_id}/approvals", status_code=status.HTTP_201_CREATED)
async def request_approval(
    incident_id: str,
    data: ApprovalRequest,
    request: Request,
    role: Optional[str] = Header(default=None, alias="X-Sentinel-Role"),
):
    """创建审批请求。"""
    _require_role(getattr(request.state, "session_role", None) or role, "planner", "scenario_operator", "system")
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
    request: Request,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    role: Optional[str] = Header(default=None, alias="X-Sentinel-Role"),
):
    """审批决定。"""
    decided_by = _require_role(getattr(request.state, "session_role", None) or role, "approver")
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")
    if request.url.path.startswith("/api/v1/"):
        expected_etag = f'"incident-{incident.id}-v{incident.version}"'
        if if_match is None:
            raise HTTPException(status_code=428, detail="v1 审批决定必须提供 If-Match")
        if if_match != expected_etag:
            raise HTTPException(status_code=412, detail="事故版本已变化，请重新读取并重试")
    result = store.decide_approval(approval_id, decision, decided_by=decided_by, incident_id=incident_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"审批 {approval_id} 不存在或已决定")
    local_workflow.resume(incident_id)
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

@app.get("/api/scenarios", response_model=ScenarioListResponse)
async def list_scenarios():
    """返回从本地 YAML 加载的安全场景目录。"""
    scenarios = _load_scenario_definitions()
    return {"items": [_public_scenario_projection(scenario) for scenario in scenarios.values()]}


@app.post(
    "/api/scenarios/{scenario_id}/run",
    response_model=ScenarioRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_scenario(
    scenario_id: str,
    request: Request,
    role: Optional[str] = Header(default=None, alias="X-Sentinel-Role"),
):
    """启动演练场景。"""
    _require_role(getattr(request.state, "session_role", None) or role, "scenario_operator")
    scenario = _load_scenario_definitions().get(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"场景 {scenario_id} 不存在")

    primary_fault = scenario.faults[0]
    target = primary_fault.target_service
    severity = (
        IncidentSeverity.CRITICAL
        if scenario.category.value in {"database", "kubernetes", "resource"}
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
                alert_name=f"{target} / {scenario.name}",
                severity=severity,
                description=scenario.description,
                started_at=datetime.now(),
            )
        )
    )
    local_workflow.start(incident.id, scenario)

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


# 正式版本化入口：复用同一套业务处理器，认证与并发条件由 v1 门禁补齐。
_v1_auth = [Depends(_require_v1_session)]
app.add_api_route("/api/v1/incidents", create_incident, methods=["POST"], status_code=201, dependencies=_v1_auth)
app.add_api_route("/api/v1/incidents", list_incidents, methods=["GET"], response_model=IncidentListResponse, dependencies=_v1_auth)
app.add_api_route("/api/v1/incidents/{incident_id}", get_incident, methods=["GET"], response_model=IncidentOverviewResponse, dependencies=_v1_auth)
app.add_api_route("/api/v1/incidents/{incident_id}/timeline", get_timeline, methods=["GET"], dependencies=_v1_auth)
app.add_api_route("/api/v1/incidents/{incident_id}/stream", stream_incident, methods=["GET"], dependencies=_v1_auth)
app.add_api_route("/api/v1/incidents/{incident_id}/export", export_incident, methods=["GET"], dependencies=_v1_auth)
app.add_api_route("/api/v1/incidents/{incident_id}/approvals", request_approval, methods=["POST"], status_code=201, dependencies=_v1_auth)
app.add_api_route("/api/v1/incidents/{incident_id}/approvals/{approval_id}", decide_approval, methods=["PUT"], dependencies=_v1_auth)
app.add_api_route("/api/v1/incidents/{incident_id}/approvals", list_approvals, methods=["GET"], dependencies=_v1_auth)
app.add_api_route("/api/v1/approvals", list_all_approvals, methods=["GET"], dependencies=_v1_auth)
app.add_api_route("/api/v1/scenarios", list_scenarios, methods=["GET"], response_model=ScenarioListResponse, dependencies=_v1_auth)
app.add_api_route("/api/v1/scenarios/{scenario_id}/run", run_scenario, methods=["POST"], response_model=ScenarioRunResponse, status_code=202, dependencies=_v1_auth)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
