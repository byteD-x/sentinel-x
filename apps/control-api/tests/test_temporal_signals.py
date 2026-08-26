from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from sentinel_x_control_api.postgres_dispatcher import OutboxRecord
from sentinel_x_control_api.temporal_signals import (
    TemporalApprovalSignalPublisher,
    TemporalSignalDeliveryError,
    build_temporal_outbox_sink,
)
from sentinel_x_incident_worker import temporal_runtime
from sentinel_x_incident_worker.temporal_runtime import (
    IncidentWorkflowInput,
    TemporalIncidentWorkflow,
)


class _Handle:
    def __init__(self):
        self.calls = []

    async def signal(self, name, payload):
        self.calls.append((name, payload))


class _Client:
    def __init__(self):
        self.handle = _Handle()

    def get_workflow_handle(self, _workflow_id):
        return self.handle


def _approval_event(**payload_overrides):
    payload = {
        "approval_id": "approval-1",
        "plan_hash": "plan-1",
        "approved": True,
        "decided_by": "operator-1",
        "reason": "approved",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    payload.update(payload_overrides)
    return OutboxRecord(
        id=uuid4(),
        aggregate_type="incident",
        aggregate_id=uuid4(),
        sequence=2,
        event_type="approval.decided",
        actor_type="APPROVER",
        payload=payload,
        occurred_at=datetime.now(timezone.utc),
        attempt_count=0,
    )


@pytest.mark.asyncio
async def test_publisher_rejects_incomplete_approval_outbox_payload():
    publisher = TemporalApprovalSignalPublisher(_Client())

    with pytest.raises(TemporalSignalDeliveryError, match="缺少必填"):
        await publisher.publish(_approval_event(plan_hash=""))


@pytest.mark.asyncio
async def test_outbox_sink_publishes_locally_only_after_temporal_signal():
    client = _Client()
    delivered = []
    sink = build_temporal_outbox_sink(
        TemporalApprovalSignalPublisher(client),
        delivered.append,
        asyncio.get_running_loop(),
        timeout_seconds=1,
    )

    event = _approval_event()
    await asyncio.to_thread(sink, event)

    assert delivered == [event]
    assert client.handle.calls == [("approval_decision", event.payload)]


@pytest.mark.asyncio
async def test_outbox_sink_leaves_event_unpublished_when_signal_is_invalid():
    delivered = []
    sink = build_temporal_outbox_sink(
        TemporalApprovalSignalPublisher(_Client()),
        delivered.append,
        asyncio.get_running_loop(),
        timeout_seconds=1,
    )

    with pytest.raises(TemporalSignalDeliveryError):
        await asyncio.to_thread(sink, _approval_event(approval_id=""))

    assert delivered == []


@pytest.mark.asyncio
async def test_publisher_delivers_approval_outbox_to_temporal_workflow():
    incident_id = uuid4()
    approval_id = "approval-signal-e2e"
    plan_hash = "plan-signal-e2e"
    async with await WorkflowEnvironment.start_time_skipping() as environment, Worker(
        environment.client,
        task_queue="control-api-signal-queue",
        workflows=[TemporalIncidentWorkflow],
        activities=temporal_runtime.TEMPORAL_ACTIVITIES,
    ):
        handle = await environment.client.start_workflow(
            TemporalIncidentWorkflow.run,
            IncidentWorkflowInput(
                incident_id=str(incident_id),
                approval_id=approval_id,
                plan_hash=plan_hash,
            ),
            id=f"incident/{incident_id}",
            task_queue="control-api-signal-queue",
        )
        publisher = TemporalApprovalSignalPublisher(environment.client)
        event = replace(
            _approval_event(
                approval_id=approval_id,
                plan_hash=plan_hash,
                decided_by="signal-test-operator",
                expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            ),
            aggregate_id=incident_id,
        )
        await publisher.publish(event)
        result = await handle.result()

    assert result.status == "RESOLVED"
    assert result.approval_id == approval_id
