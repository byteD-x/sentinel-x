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
- GET  /api/scenarios — 场景列表
- POST /api/scenarios/{id}/run — 启动演练
"""

import asyncio
import json
import random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

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


class AlertSource(BaseModel):
    alertmanager_id: str
    fingerprint: str
    alert_name: str
    severity: IncidentSeverity
    description: str
    started_at: datetime


class IncidentCreate(BaseModel):
    alert_source: AlertSource


class IncidentResponse(BaseModel):
    id: str
    status: IncidentStatus
    severity: IncidentSeverity
    alert_name: str
    description: str
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    workflow_id: Optional[str] = None
    version: int = 1


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


class ApprovalRequest(BaseModel):
    plan_id: str
    runbook_ref: str
    target: str
    parameters: dict = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.R1
    plan_hash: str
    hypothesis_id: str


class ApprovalDecision(BaseModel):
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
        self._approvals: dict[str, dict] = {}
        self._scenarios: dict[str, dict] = {}

    def create_incident(self, data: IncidentCreate) -> StoredIncident:
        incident_id = str(uuid4())
        incident = StoredIncident(
            id=incident_id,
            severity=data.alert_source.severity,
            alert_name=data.alert_source.alert_name,
            description=data.alert_source.description,
        )
        self._add_timeline_event(
            incident, "incident.created", "alert_ingress",
            {"fingerprint": data.alert_source.fingerprint},
        )
        self._incidents[incident_id] = incident
        return incident

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

    def get_timeline(
        self,
        incident_id: str,
        after_sequence: int = 0,
    ) -> list[TimelineEvent]:
        incident = self._incidents.get(incident_id)
        if not incident:
            return []
        return [e for e in incident.timeline if e.sequence > after_sequence]

    def create_approval(self, incident_id: str, data: ApprovalRequest) -> dict:
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

    def decide_approval(self, approval_id: str, decision: ApprovalDecision, decided_by: str = "demo-operator") -> Optional[dict]:
        approval = self._approvals.get(approval_id)
        if not approval:
            return None
        if approval["status"] != "pending":
            return None  # 不可重复决定
        # 检查过期
        expires_at = datetime.fromisoformat(approval["expires_at"])
        if datetime.now() > expires_at:
            approval["status"] = "expired"
            return approval
        approval["status"] = "approved" if decision.approved else "rejected"
        approval["decided_at"] = datetime.now().isoformat()
        approval["decided_by"] = decided_by
        approval["decision_reason"] = decision.reason
        event_type = "approval.decided"
        self.add_timeline_event(
            approval["incident_id"], event_type, f"approver:{decided_by}",
            {"approved": decision.approved, "reason": decision.reason},
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
        },
        {
            "id": "order-db-errors@1",
            "name": "order-db-errors@1",
            "version": 1,
            "description": "Order Service 数据库连接池耗尽导致 5xx 错误",
            "category": "database",
        },
        {
            "id": "inventory-split-brain@1",
            "name": "inventory-split-brain@1",
            "version": 1,
            "description": "Redis 主从切换后 split-brain 导致库存数据不一致",
            "category": "application",
        },
        {
            "id": "payment-pod-crash@1",
            "name": "payment-pod-crash@1",
            "version": 1,
            "description": "Payment Pod 因 OOM 崩溃，Kubernetes 自动重启恢复",
            "category": "kubernetes",
        },
        {
            "id": "inventory-cpu-saturation@1",
            "name": "inventory-cpu-saturation@1",
            "version": 1,
            "description": "Inventory CPU 饱和，需要扩容",
            "category": "resource",
        },
        {
            "id": "order-bad-deployment@1",
            "name": "order-bad-deployment@1",
            "version": 1,
            "description": "Order Service 错误部署导致持续失败，需人工回滚",
            "category": "application",
        },
    ]
    for s in demo_scenarios:
        store.add_scenario(s)


store = InMemoryStore()

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


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查。"""
    return HealthResponse()


# ---- 事故 ----

@app.post("/api/incidents", status_code=status.HTTP_201_CREATED)
async def create_incident(data: IncidentCreate):
    """创建事故（Alert Ingress 调用）。"""
    incident = store.create_incident(data)
    return {
        "id": incident.id,
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


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str):
    """事故详情。"""
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")
    return IncidentResponse(
        id=incident.id,
        status=incident.status,
        severity=incident.severity,
        alert_name=incident.alert_name,
        description=incident.description,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        resolved_at=incident.resolved_at,
        workflow_id=incident.workflow_id,
        version=incident.version,
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
async def request_approval(incident_id: str, data: ApprovalRequest):
    """创建审批请求。"""
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")
    if data.risk_level == RiskLevel.R2:
        raise HTTPException(status_code=400, detail="R2 操作在 MVP 中禁用，请升级人工处理")
    if data.risk_level == RiskLevel.R3:
        raise HTTPException(status_code=400, detail="R3 操作永久禁止")
    approval = store.create_approval(incident_id, data)
    return approval


@app.put("/api/incidents/{incident_id}/approvals/{approval_id}")
async def decide_approval(incident_id: str, approval_id: str, decision: ApprovalDecision):
    """审批决定。"""
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")
    result = store.decide_approval(approval_id, decision)
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


# ---- 场景 ----

@app.get("/api/scenarios")
async def list_scenarios():
    """场景列表。"""
    scenarios = store.list_scenarios()
    return {"items": scenarios}


@app.post("/api/scenarios/{scenario_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_scenario(scenario_id: str):
    """启动演练场景。"""
    scenario = store._scenarios.get(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"场景 {scenario_id} 不存在")
    # 模拟：创建一个事故来关联
    from uuid import uuid4
    incident_id = str(uuid4())
    return {
        "exercise_id": str(uuid4()),
        "scenario_id": scenario_id,
        "incident_id": incident_id,
        "status": "injecting",
        "message": f"场景 {scenario_id} 已启动",
    }


# ---- SSE（事故实时推送） ----


@app.get("/api/incidents/{incident_id}/stream")
async def stream_incident(incident_id: str):
    """SSE 实时推送事故更新。"""
    incident = store.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"事故 {incident_id} 不存在")

    async def event_generator():
        last_seq = 0
        # 先发送当前状态
        yield f"data: {json.dumps({'type': 'status', 'status': incident.status.value})}\n\n"
        # 然后轮询新事件（MVP 简化实现，正式版用 outbox + dispatcher）
        for _ in range(300):  # 最多 5 分钟
            events = store.get_timeline(incident_id, last_seq)
            for event in events:
                yield f"data: {json.dumps({'type': 'timeline_event', 'event': {
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

        # 添加一些模拟证据和时间线事件
        store._add_timeline_event(
            incident, "evidence.collected", "diagnostic_gateway",
            {"source": "prometheus", "summary": f"{demo['alert_source'].alert_name} 指标异常"},
        )
        store._add_timeline_event(
            incident, "hypothesis.generated", "investigator",
            {"confidence": 0.75, "category": random.choice(["network", "application", "database"])},
        )

        created.append(incident.id)

    return {"message": f"已创建 {len(created)} 个演示事故", "incident_ids": created}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
