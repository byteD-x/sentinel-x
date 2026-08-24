"""Temporal durable thin slice 的注册、Signal 和边界测试。"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sentinel_x_incident_worker import temporal_runtime
from sentinel_x_incident_worker.temporal_runtime import (
    ApprovalDecision,
    IncidentWorkflowInput,
    TemporalIncidentWorkflow,
)
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker


def test_temporal_definitions_are_explicit():
    assert TemporalIncidentWorkflow.__temporal_workflow_definition.name == (
        "SentinelIncidentWorkflow"
    )
    assert [
        activity.__temporal_activity_definition.name
        for activity in temporal_runtime.TEMPORAL_ACTIVITIES
    ] == [
        "collect_incident_evidence",
        "execute_approved_action",
        "verify_incident_recovery",
    ]
    assert temporal_runtime.OBSERVATION_RETRY_POLICY.maximum_attempts == 3


def test_worker_registration_keeps_workflow_and_activity_contract(monkeypatch):
    calls = {}

    class FakeWorker:
        def __init__(self, client, **kwargs):
            calls["client"] = client
            calls.update(kwargs)

    monkeypatch.setattr("temporalio.worker.Worker", FakeWorker)
    client = object()

    worker = temporal_runtime.build_temporal_worker(client, task_queue="test-queue")

    assert isinstance(worker, FakeWorker)
    assert calls["client"] is client
    assert calls["task_queue"] == "test-queue"
    assert calls["workflows"] == [TemporalIncidentWorkflow]
    assert calls["activities"] == temporal_runtime.TEMPORAL_ACTIVITIES


@pytest.mark.asyncio
async def test_temporal_workflow_resolves_after_matching_approval(monkeypatch):
    async def fake_execute_activity(activity, arg, **_kwargs):
        if activity is temporal_runtime.collect_incident_evidence:
            return {"evidence_id": "evidence-1"}
        if activity is temporal_runtime.execute_approved_action:
            return {"status": "succeeded", "execution_id": "execution-1"}
        return {"recovered": True, "observed_p99_ms": 180.0}

    async def fake_wait_condition(_condition, **_kwargs):
        return None

    monkeypatch.setattr(temporal_runtime.workflow, "execute_activity", fake_execute_activity)
    monkeypatch.setattr(temporal_runtime.workflow, "wait_condition", fake_wait_condition)
    monkeypatch.setattr(
        temporal_runtime.workflow,
        "now",
        lambda: datetime.now(UTC),
    )

    workflow = TemporalIncidentWorkflow()
    input = IncidentWorkflowInput(
        incident_id="incident-1",
        approval_id="approval-1",
        plan_hash="plan-1",
    )
    workflow._approval = ApprovalDecision(
        approval_id="approval-1",
        plan_hash="plan-1",
        approved=True,
        decided_by="operator-1",
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )

    result = await workflow.run(input)

    assert result.status == "RESOLVED"
    assert result.execution_id == "execution-1"
    assert result.history == [
        "DETECTED",
        "TRIAGING",
        "DIAGNOSING",
        "PLAN_PROPOSED",
        "AWAITING_APPROVAL",
        "EXECUTING",
        "VERIFYING",
        "RESOLVED",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("approval", "expected"),
    [
        (
            ApprovalDecision(
                approval_id="other",
                plan_hash="plan-1",
                approved=True,
                decided_by="operator-1",
            ),
            "审批记录与事故计划不匹配",
        ),
        (
            ApprovalDecision(
                approval_id="approval-1",
                plan_hash="plan-1",
                approved=True,
                decided_by="operator-1",
                expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            ),
            "审批已过期",
        ),
    ],
)
async def test_temporal_workflow_rejects_invalid_approval(
    monkeypatch,
    approval: ApprovalDecision,
    expected: str,
):
    monkeypatch.setattr(
        temporal_runtime.workflow,
        "execute_activity",
        AsyncMock(return_value={"evidence_id": "evidence-1"}),
    )
    monkeypatch.setattr(
        temporal_runtime.workflow,
        "wait_condition",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        temporal_runtime.workflow,
        "now",
        lambda: datetime.now(UTC),
    )

    workflow = TemporalIncidentWorkflow()
    workflow._approval = approval

    result = await workflow.run(
        IncidentWorkflowInput(
            incident_id="incident-1",
            approval_id="approval-1",
            plan_hash="plan-1",
        )
    )

    assert result.status == "FAILED"
    assert result.failure_reason == expected


@pytest.mark.asyncio
async def test_temporal_server_executes_signal_path_and_replays_history():
    """使用 Temporal SDK 测试服务器验证 Signal、Activity 和 history replay。"""

    async with await WorkflowEnvironment.start_time_skipping() as environment, Worker(
        environment.client,
        task_queue="temporal-test-queue",
        workflows=[TemporalIncidentWorkflow],
        activities=temporal_runtime.TEMPORAL_ACTIVITIES,
    ):
        handle = await environment.client.start_workflow(
            TemporalIncidentWorkflow.run,
            IncidentWorkflowInput(
                incident_id="incident-temporal-e2e",
                approval_id="approval-temporal-e2e",
                plan_hash="plan-temporal-e2e",
            ),
            id="incident-temporal-e2e",
            task_queue="temporal-test-queue",
        )
        await handle.signal(
            TemporalIncidentWorkflow.approval_decision,
            ApprovalDecision(
                approval_id="approval-temporal-e2e",
                plan_hash="plan-temporal-e2e",
                approved=True,
                decided_by="test-operator",
                expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            ),
        )

        result = await handle.result()
        replay = await Replayer(workflows=[TemporalIncidentWorkflow]).replay_workflow(
            await handle.fetch_history()
        )

    assert result.status == "RESOLVED"
    assert replay.replay_failure is None


@pytest.mark.asyncio
async def test_temporal_workflow_resumes_after_worker_restart():
    """Worker 在审批等待点重启后，Workflow history 和 Signal 仍能继续。"""

    async with await WorkflowEnvironment.start_local() as environment:
        workflow_input = IncidentWorkflowInput(
            incident_id="incident-worker-restart",
            approval_id="approval-worker-restart",
            plan_hash="plan-worker-restart",
        )

        async with Worker(
            environment.client,
            task_queue="temporal-restart-queue",
            workflows=[TemporalIncidentWorkflow],
            activities=temporal_runtime.TEMPORAL_ACTIVITIES,
        ):
            handle = await environment.client.start_workflow(
                TemporalIncidentWorkflow.run,
                workflow_input,
                id="incident-worker-restart",
                task_queue="temporal-restart-queue",
            )
            for _ in range(100):
                snapshot = await handle.query(TemporalIncidentWorkflow.workflow_status)
                if snapshot.status == "AWAITING_APPROVAL":
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("Workflow 未进入审批等待点")

        await handle.signal(
            TemporalIncidentWorkflow.approval_decision,
            ApprovalDecision(
                approval_id="approval-worker-restart",
                plan_hash="plan-worker-restart",
                approved=True,
                decided_by="restart-test-operator",
                expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            ),
        )

        async with Worker(
            environment.client,
            task_queue="temporal-restart-queue",
            workflows=[TemporalIncidentWorkflow],
            activities=temporal_runtime.TEMPORAL_ACTIVITIES,
        ):
            result = await handle.result()

    assert result.status == "RESOLVED"
    assert result.history[-3:] == ["EXECUTING", "VERIFYING", "RESOLVED"]
