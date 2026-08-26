"""将 PostgreSQL 审批 outbox 投递为 Temporal Signal。"""

from __future__ import annotations

import asyncio
from typing import Any


class TemporalSignalDeliveryError(RuntimeError):
    """审批 outbox 无法安全投递到对应 Workflow。"""


class TemporalApprovalSignalPublisher:
    """只投递不可变的审批决定，不在 Control API 推进 Workflow 状态。"""

    def __init__(self, client: Any):
        self._client = client

    async def publish(self, event: Any) -> None:
        if getattr(event, "event_type", None) != "approval.decided":
            return

        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            raise TemporalSignalDeliveryError("审批 outbox payload 必须是对象")
        decision = self._decision_payload(payload)
        workflow_id = f"incident/{event.aggregate_id}"
        try:
            handle = self._client.get_workflow_handle(workflow_id)
            await handle.signal("approval_decision", decision)
        except TemporalSignalDeliveryError:
            raise
        except Exception as exc:  # noqa: BLE001 - 由 outbox 保留并重试
            raise TemporalSignalDeliveryError(
                f"Temporal 审批 Signal 投递失败: {workflow_id}"
            ) from exc

    @staticmethod
    def _decision_payload(payload: dict[str, Any]) -> dict[str, Any]:
        required_text = ("approval_id", "plan_hash", "decided_by", "expires_at")
        decision = {key: payload.get(key) for key in required_text}
        if any(not isinstance(value, str) or not value for value in decision.values()):
            raise TemporalSignalDeliveryError("审批 outbox 缺少必填 Signal 字段")
        approved = payload.get("approved")
        if not isinstance(approved, bool):
            raise TemporalSignalDeliveryError("审批 outbox 的 approved 必须是布尔值")
        reason = payload.get("reason", "")
        if not isinstance(reason, str):
            raise TemporalSignalDeliveryError("审批 outbox 的 reason 必须是字符串")
        return {**decision, "approved": approved, "reason": reason}


def build_temporal_outbox_sink(
    publisher: TemporalApprovalSignalPublisher,
    publish_local: Any,
    event_loop: asyncio.AbstractEventLoop,
    *,
    timeout_seconds: float,
):
    """把 dispatcher 工作线程中的 outbox 事件安全桥接到主事件循环。"""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须为正数")

    def sink(event: Any) -> None:
        delivery = asyncio.run_coroutine_threadsafe(publisher.publish(event), event_loop)
        delivery.result(timeout=timeout_seconds)
        publish_local(event)

    return sink
