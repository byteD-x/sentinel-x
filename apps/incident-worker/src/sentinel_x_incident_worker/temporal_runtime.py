"""Temporal durable thin slice。

该模块只包含可注册到 Temporal 的 Workflow/Activity 边界。现有
``workflows.IncidentWorkflow`` 继续服务 light profile；这里的 Workflow
不访问网络、时钟或随机数，所有外部 I/O 都经由 Activity 完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from sentinel_x_incident_worker.activities import (
        collect_prometheus_evidence,
        reconcile_postgres_projection,
        submit_action_to_gateway,
        verify_slo_recovery,
    )


TEMPORAL_WORKFLOW_NAME = "SentinelIncidentWorkflow"
TEMPORAL_TASK_QUEUE = "sentinel-incidents"

OBSERVATION_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=10),
    maximum_attempts=3,
)


@dataclass
class IncidentWorkflowInput:
    """单场景 durable thin slice 的输入契约。"""

    incident_id: str
    service_name: str = "inventory-api"
    runbook_ref: str = "restart_deployment@1"
    target: str = "inventory-api"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"reason": "inventory-latched-5xx@1"}
    )
    approval_id: str = "approval-inventory-latched-5xx"
    plan_hash: str = ""
    approval_timeout_seconds: int = 900
    approval_required: bool = True
    target_p99_ms: float = 200.0
    observed_p99_samples: list[float] = field(default_factory=lambda: [150.0, 180.0])
    minimum_samples: int = 2
    action_gateway_url: str = "http://127.0.0.1:8090"
    approval_token: str = "local-demo-token"
    approval_expires_at: str = ""
    target_identity: dict[str, Any] = field(default_factory=dict)
    target_resource_version: str = "unknown"


@dataclass
class ApprovalDecision:
    """由 Control API 通过 Signal 发送的不可变审批决定。"""

    approval_id: str
    plan_hash: str
    approved: bool
    decided_by: str
    reason: str = ""
    expires_at: str = ""


@dataclass
class ActionRequest:
    action_gateway_url: str
    runbook_ref: str
    target: str
    parameters: dict[str, Any]
    idempotency_key: str
    approval_token: str
    plan_hash: str = ""
    approval_id: str = ""
    incident_id: str = ""
    approval_expires_at: str = ""
    target_identity: dict[str, Any] = field(default_factory=dict)
    target_resource_version: str = "unknown"


@dataclass
class VerificationRequest:
    service_name: str
    target_p99_ms: float
    observed_p99_samples: list[float]
    minimum_samples: int


@dataclass
class ProjectionReconciliationRequest:
    incident_id: str
    expected: dict[str, Any]


@dataclass
class IncidentWorkflowResult:
    status: str
    history: list[str]
    approval_id: str | None = None
    execution_id: str | None = None
    verification: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None
    workflow_event_refs: list[dict[str, str]] = field(default_factory=list)


@activity.defn(name="collect_incident_evidence")
async def collect_incident_evidence(input: IncidentWorkflowInput) -> dict[str, Any]:
    """收集事故证据；瞬态观测错误由 Workflow 的重试策略处理。"""

    return await collect_prometheus_evidence(
        query=f'http_requests_total{{service="{input.service_name}"}}',
        time_range_minutes=15,
    )


@activity.defn(name="execute_approved_action")
async def execute_approved_action(request: ActionRequest) -> dict[str, Any]:
    """执行已由 Workflow 校验过的 R1 动作。"""

    return await submit_action_to_gateway(
        action_gateway_url=request.action_gateway_url,
        runbook_ref=request.runbook_ref,
        target=request.target,
        parameters=request.parameters,
        idempotency_key=request.idempotency_key,
        approval_token=request.approval_token,
        plan_hash=request.plan_hash,
        approval_id=request.approval_id,
        incident_id=request.incident_id,
        approval_expires_at=request.approval_expires_at,
        target_identity=request.target_identity,
        target_resource_version=request.target_resource_version,
    )


@activity.defn(name="verify_incident_recovery")
async def verify_incident_recovery(request: VerificationRequest) -> dict[str, Any]:
    """读取观测窗口并判断 SLO 是否恢复。"""

    return await verify_slo_recovery(
        service_name=request.service_name,
        target_p99_ms=request.target_p99_ms,
        observed_p99_samples=request.observed_p99_samples,
        minimum_samples=request.minimum_samples,
    )


@activity.defn(name="reconcile_postgres_projection")
async def reconcile_projection(
    request: ProjectionReconciliationRequest,
) -> dict[str, Any]:
    """读取 PostgreSQL projection；数据库凭据只存在 Worker 环境。"""
    return await reconcile_postgres_projection(
        incident_id=request.incident_id,
        expected=request.expected,
    )


@workflow.defn(name=TEMPORAL_WORKFLOW_NAME)
class TemporalIncidentWorkflow:
    """可 replay 的事故流程：证据 -> 计划 -> Signal 审批 -> 动作 -> SLO。"""

    def __init__(self) -> None:
        self._status = "DETECTED"
        self._history = ["DETECTED"]
        self._approval: ApprovalDecision | None = None
        self._verification: dict[str, Any] = {}
        self._execution_id: str | None = None
        self._failure_reason: str | None = None
        self._workflow_event_refs: list[dict[str, str]] = []

    @workflow.signal(name="approval_decision")
    async def approval_decision(self, decision: ApprovalDecision) -> None:
        """只接受第一条决定，后续重复 Signal 不覆盖审计结果。"""

        if self._approval is None:
            self._approval = decision

    @workflow.query(name="workflow_status")
    def workflow_status(self) -> IncidentWorkflowResult:
        """提供 UI/运维查询所需的最小只读状态。"""

        return self._result()

    @workflow.run
    async def run(self, input: IncidentWorkflowInput) -> IncidentWorkflowResult:
        try:
            self._transition("TRIAGING")
            evidence = await workflow.execute_activity(
                collect_incident_evidence,
                input,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=OBSERVATION_RETRY_POLICY,
            )
            self._record_workflow_event_ref("evidence.collected", evidence.get("evidence_id"))

            self._transition("DIAGNOSING")
            self._transition("PLAN_PROPOSED")

            if input.approval_required:
                self._transition("AWAITING_APPROVAL")
                await workflow.wait_condition(
                    lambda: self._approval is not None,
                    timeout=timedelta(seconds=input.approval_timeout_seconds),
                    timeout_summary="等待人工审批超时",
                )
                failure = self._validate_approval(input)
                if failure:
                    return self._fail(failure)

            self._transition("EXECUTING")
            idempotency_key = (
                f"{input.incident_id}:{input.approval_id}:{input.plan_hash}:"
                f"{input.runbook_ref}:{input.target}"
            )
            action = await workflow.execute_activity(
                execute_approved_action,
                ActionRequest(
                    action_gateway_url=input.action_gateway_url,
                    runbook_ref=input.runbook_ref,
                    target=input.target,
                    parameters=input.parameters,
                    idempotency_key=idempotency_key,
                    approval_token=input.approval_token,
                    plan_hash=input.plan_hash,
                    approval_id=input.approval_id,
                    incident_id=input.incident_id,
                    approval_expires_at=(self._approval.expires_at or input.approval_expires_at),
                    target_identity=input.target_identity or {
                        "namespace": "demo-shop", "kind": "Deployment",
                        "name": input.target, "uid": f"fake-{input.target}", "generation": 1,
                    },
                    target_resource_version=input.target_resource_version,
                ),
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            self._execution_id = action.get("execution_id")
            self._record_workflow_event_ref("action.completed", self._execution_id)
            if action.get("status") != "succeeded":
                return self._fail(action.get("error") or "动作执行失败")

            self._transition("VERIFYING")
            self._verification = await workflow.execute_activity(
                verify_incident_recovery,
                VerificationRequest(
                    service_name=input.service_name,
                    target_p99_ms=input.target_p99_ms,
                    observed_p99_samples=input.observed_p99_samples,
                    minimum_samples=input.minimum_samples,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=OBSERVATION_RETRY_POLICY,
            )
            self._record_workflow_event_ref(
                "recovery.verified", self._verification.get("verified_at")
            )
            if not self._verification.get("recovered", False):
                return self._fail(
                    self._verification.get("failure_reason") or "SLO 恢复验证未通过"
                )

            self._transition("RESOLVED")
            return self._result()
        except Exception:  # noqa: BLE001 - 将 ActivityError/序列化错误收敛为可查询终态
            # Activity 重试耗尽或 Workflow 输入非法时，保留可查询的失败终态。
            return self._fail("Temporal Workflow 执行失败")

    def _validate_approval(self, input: IncidentWorkflowInput) -> str | None:
        decision = self._approval
        if decision is None:
            return "缺少审批决定"
        if decision.approval_id != input.approval_id:
            return "审批记录与事故计划不匹配"
        if input.plan_hash and decision.plan_hash != input.plan_hash:
            return "审批计划哈希不匹配"
        if not decision.approved:
            return decision.reason or "审批被拒绝"
        if decision.expires_at:
            try:
                expires_at = datetime.fromisoformat(decision.expires_at)
            except ValueError:
                return "审批过期时间格式无效"
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= workflow.now():
                return "审批已过期"
        return None

    def _transition(self, status: str) -> None:
        self._status = status
        self._history.append(status)

    def _fail(self, reason: str) -> IncidentWorkflowResult:
        if self._status != "FAILED":
            self._transition("FAILED")
        self._failure_reason = reason
        return self._result()

    def _record_workflow_event_ref(self, event_type: str, reference: Any) -> None:
        if reference is None:
            return
        self._workflow_event_refs.append(
            {"event_type": event_type, "reference": str(reference)}
        )

    def _result(self) -> IncidentWorkflowResult:
        return IncidentWorkflowResult(
            status=self._status,
            history=list(self._history),
            approval_id=self._approval.approval_id if self._approval else None,
            execution_id=self._execution_id,
            verification=dict(self._verification),
            failure_reason=self._failure_reason,
            workflow_event_refs=list(self._workflow_event_refs),
        )


TEMPORAL_ACTIVITIES = [
    collect_incident_evidence,
    execute_approved_action,
    verify_incident_recovery,
    reconcile_projection,
]


def build_temporal_worker(client: Any, *, task_queue: str = TEMPORAL_TASK_QUEUE) -> Any:
    """构造真实 Temporal Worker，集中维护注册清单供启动与测试复用。"""

    from temporalio.worker import Worker

    return Worker(
        client,
        task_queue=task_queue,
        workflows=[TemporalIncidentWorkflow],
        activities=TEMPORAL_ACTIVITIES,
    )
