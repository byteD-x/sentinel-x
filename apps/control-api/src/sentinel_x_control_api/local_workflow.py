"""local-isolated profile 的可恢复演练编排器。

该编排器只服务没有 Temporal Server 的本地隔离演练。它把小型工作流
检查点保存在 Control API 的 SQLite 状态库中，不能替代 Temporal history
或 PostgreSQL 投影。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from demo.scenarios.loader import ScenarioLoader
from sentinel_x_contracts import IncidentStatus, RiskLevel
from sentinel_x_contracts.scenario import ScenarioDefinition
from sentinel_x_domain.services import compute_plan_hash
from sentinel_x_policy import check_mvp_policy


@dataclass(frozen=True)
class LocalApprovalRequest:
    """满足本地存储审批输入所需的受限字段。"""

    plan_id: str
    runbook_ref: str
    target: str
    parameters: dict[str, Any]
    risk_level: RiskLevel
    plan_hash: str
    hypothesis_id: str


class LocalExerciseWorkflow:
    """本地隔离演练的确定性恢复路径。

    所有状态变更和检查点由传入存储同步持久化。动作仍是显式标记的
    local fixture，不会连接 Kubernetes、Shell 或生产端点。
    """

    def __init__(self, store: Any, scenarios_dir: str | Path | None = None):
        self.store = store
        self.scenarios_dir = Path(scenarios_dir) if scenarios_dir else (
            Path(__file__).resolve().parents[4] / "demo" / "scenarios"
        )

    def start(self, incident_id: str, scenario: ScenarioDefinition) -> None:
        """为新场景事故创建唯一检查点并推进到下一个人工决策。"""
        checkpoint = self.store.get_workflow_checkpoint(incident_id)
        if checkpoint is None:
            self.store.create_workflow_checkpoint(
                incident_id=incident_id,
                scenario_id=scenario.id,
                phase="starting",
            )
        self._advance_investigation(incident_id, scenario)

    def resume_all(self) -> None:
        """在 Control API 重启后继续每个未完成的本地工作流。"""
        for checkpoint in self.store.list_resumable_workflow_checkpoints():
            self.resume(checkpoint["incident_id"])

    def resume(self, incident_id: str) -> None:
        """从已持久化的阶段继续，不重新登记已处理的动作。"""
        checkpoint = self.store.get_workflow_checkpoint(incident_id)
        incident = self.store.get_incident(incident_id)
        if checkpoint is None or incident is None:
            return
        if checkpoint["completed"]:
            return
        if incident.status in {
            IncidentStatus.RESOLVED,
            IncidentStatus.ESCALATED,
            IncidentStatus.FAILED,
        }:
            self.store.update_workflow_checkpoint(
                incident_id, phase="terminal", completed=True
            )
            return

        scenario = self._load_scenario(checkpoint["scenario_id"])
        if checkpoint["phase"] in {"starting", "investigating", "planning"}:
            self._advance_investigation(incident_id, scenario)
            return

        if checkpoint["phase"] == "awaiting_approval":
            approval = self._active_approval(incident_id, include_decided=True)
            if approval is None or approval["status"] == "pending":
                return
            if approval["status"] == "approved":
                self._execute_and_verify(incident_id, approval)
            else:
                self._escalate(
                    incident_id,
                    f"审批{self._approval_status_label(approval['status'])}，升级人工处理",
                )
            return

        if checkpoint["phase"] in {"executing", "verifying"}:
            approval = self._active_approval(incident_id, include_decided=True)
            if approval is None or approval["status"] != "approved":
                self._escalate(incident_id, "恢复时未找到有效批准，升级人工处理")
                return
            self._execute_and_verify(incident_id, approval)

    def _advance_investigation(
        self,
        incident_id: str,
        scenario: ScenarioDefinition,
    ) -> None:
        incident = self.store.get_incident(incident_id)
        if incident is None:
            raise ValueError("事故不存在")
        if incident.status in {
            IncidentStatus.RESOLVED,
            IncidentStatus.ESCALATED,
            IncidentStatus.FAILED,
        }:
            self.store.update_workflow_checkpoint(
                incident_id, phase="terminal", completed=True
            )
            return

        checkpoint = self.store.get_workflow_checkpoint(incident_id)
        if not checkpoint or checkpoint["phase"] != "planning":
            self.store.update_workflow_checkpoint(incident_id, phase="investigating")
        primary_fault = scenario.faults[0]
        target = primary_fault.target_service

        if incident.status == IncidentStatus.DETECTED:
            self._add_once(
                incident_id,
                "scenario.started",
                "scenario_runner",
                {
                    "scenario_id": scenario.id,
                    "profile": "local-isolated",
                    "target": target,
                    "target_namespace": primary_fault.target_namespace,
                },
            )
            self.store.set_status(incident, IncidentStatus.TRIAGING, "故障注入已确认")
        if incident.status == IncidentStatus.TRIAGING:
            self.store.set_status(incident, IncidentStatus.DIAGNOSING, "开始关联受限诊断信号")
        if incident.status not in {IncidentStatus.DIAGNOSING, IncidentStatus.PLAN_PROPOSED}:
            self.resume(incident_id)
            return

        self._record_evidence(incident_id, scenario)
        self._record_hypothesis(incident_id, scenario)
        runbooks = list(scenario.allowlisted_runbooks)
        if not runbooks:
            self._escalate(incident_id, "没有允许的自动恢复动作，升级人工")
            return

        runbook_ref = runbooks[0]
        if runbook_ref == "no_op":
            self.store.set_status(incident, IncidentStatus.VERIFYING, "观察自动恢复")
            self.store.update_workflow_checkpoint(incident_id, phase="verifying")
            self._verify(incident_id, action_execution_id=None)
            return

        self.store.set_status(incident, IncidentStatus.PLAN_PROPOSED, "形成受限恢复方案")
        decision = check_mvp_policy(runbook_ref, target)
        if not decision.allowed:
            self._escalate(incident_id, decision.reason)
            return

        parameters = {"reason": f"恢复隔离演练 {scenario.id}"}
        if runbook_ref == "scale_deployment@1":
            parameters["replicas"] = 3
        plan_hash = compute_plan_hash(runbook_ref, target, parameters, incident.id)
        self._add_once(
            incident_id,
            "plan.proposed",
            "policy_gate",
            {
                "runbook_ref": runbook_ref,
                "target": target,
                "risk_level": decision.risk_level.value,
                "plan_hash": plan_hash,
            },
        )
        self.store.update_workflow_checkpoint(incident_id, phase="planning")
        if self._active_approval(incident_id) is None:
            self.store.create_approval(
                incident_id,
                LocalApprovalRequest(
                    plan_id=f"plan-{incident.id[:8]}",
                    runbook_ref=runbook_ref,
                    target=target,
                    parameters=parameters,
                    risk_level=decision.risk_level,
                    plan_hash=plan_hash,
                    hypothesis_id=f"hyp-{incident.id[:8]}",
                ),
            )
        self.store.update_workflow_checkpoint(incident_id, phase="awaiting_approval")

    def _record_evidence(self, incident_id: str, scenario: ScenarioDefinition) -> None:
        if self._has_event(incident_id, "evidence.collected"):
            return
        sources = ("prometheus", "loki", "tempo", "kubernetes")
        primary_fault = scenario.faults[0]
        summaries = scenario.expected_evidence or [
            f"{primary_fault.target_service} 出现与场景一致的异常信号"
        ]
        for index, source in enumerate(sources, start=1):
            summary = summaries[(index - 1) % len(summaries)]
            self.store.add_timeline_event(
                incident_id,
                "evidence.collected",
                "diagnostic_gateway",
                {
                    "source": source,
                    "summary": summary,
                    "evidence_id": f"ev-{incident_id[:8]}-{index}",
                },
            )

    def _record_hypothesis(self, incident_id: str, scenario: ScenarioDefinition) -> None:
        if self._has_event(incident_id, "hypothesis.generated"):
            return
        primary_fault = scenario.faults[0]
        self.store.add_timeline_event(
            incident_id,
            "hypothesis.generated",
            "local_investigator",
            {
                "statement": (
                    f"{primary_fault.target_service} 的 "
                    f"{scenario.expected_root_cause_category.value} 与已收集证据一致"
                ),
                "confidence": 0.88,
                "category": scenario.expected_root_cause_category.value,
                "affected_service": primary_fault.target_service,
                "supporting_evidence": 4,
                "opposing_evidence": "尚未发现直接反证",
            },
        )

    def _execute_and_verify(self, incident_id: str, approval: dict) -> None:
        incident = self.store.get_incident(incident_id)
        if incident is None:
            return
        expires_at = datetime.fromisoformat(approval["expires_at"])
        if datetime.now(tz=expires_at.tzinfo) > expires_at:
            self.store.expire_approval(approval["id"])
            self._escalate(incident_id, "批准已过期，禁止执行并升级人工处理")
            return
        checkpoint = self.store.get_workflow_checkpoint(incident_id)
        if checkpoint is None:
            return
        execution_id = checkpoint["action_execution_id"] or (
            f"local-action-{incident_id[:8]}-{approval['plan_hash'][:12]}"
        )
        if incident.status == IncidentStatus.AWAITING_APPROVAL:
            self.store.set_status(incident, IncidentStatus.EXECUTING, "本地审批已持久化")
        self.store.update_workflow_checkpoint(
            incident_id, phase="executing", action_execution_id=execution_id
        )
        self._add_once(
            incident_id,
            "action.started",
            "local_action_gateway",
            {
                "execution_id": execution_id,
                "runbook_ref": approval["runbook_ref"],
                "target": approval["target"],
                "mode": "local-isolated-fixture",
            },
            key="execution_id",
        )
        if incident.status == IncidentStatus.EXECUTING:
            self._add_once(
                incident_id,
                "action.completed",
                "local_action_gateway",
                {
                    "execution_id": execution_id,
                    "status": "succeeded",
                    "before_state": "fixture-degraded",
                    "after_state": "fixture-healthy",
                },
                key="execution_id",
            )
            self.store.set_status(incident, IncidentStatus.VERIFYING, "受限动作已协调，开始恢复验证")
        self.store.update_workflow_checkpoint(incident_id, phase="verifying")
        self._verify(incident_id, action_execution_id=execution_id)

    def _verify(self, incident_id: str, action_execution_id: str | None) -> None:
        incident = self.store.get_incident(incident_id)
        if incident is None:
            return
        if incident.status != IncidentStatus.VERIFYING:
            return
        payload: dict[str, Any] = {
            "result": "passed",
            "window_seconds": 60,
            "recovery_actor": (
                "local_action_gateway" if action_execution_id else "kubernetes_controller_fixture"
            ),
        }
        if action_execution_id:
            payload["execution_id"] = action_execution_id
        self._add_once(
            incident_id,
            "recovery.verified",
            "verification_fixture",
            payload,
            key="execution_id" if action_execution_id else None,
        )
        self.store.set_status(incident, IncidentStatus.RESOLVED, "恢复窗口验证通过")
        incident.resolved_at = incident.resolved_at or incident.updated_at
        self.store.flush()
        self.store.update_workflow_checkpoint(
            incident_id, phase="terminal", completed=True
        )

    def _escalate(self, incident_id: str, reason: str) -> None:
        incident = self.store.get_incident(incident_id)
        if incident is None:
            return
        if incident.status not in {
            IncidentStatus.RESOLVED,
            IncidentStatus.ESCALATED,
            IncidentStatus.FAILED,
        }:
            self.store.set_status(incident, IncidentStatus.ESCALATED, reason)
        self._add_once(
            incident_id,
            "incident.escalated",
            "policy_gate",
            {"reason": reason},
            key="reason",
        )
        self.store.update_workflow_checkpoint(
            incident_id, phase="terminal", completed=True
        )

    def _active_approval(
        self, incident_id: str, *, include_decided: bool = False
    ) -> dict | None:
        approvals = self.store.list_approvals(incident_id)
        if include_decided:
            return approvals[-1] if approvals else None
        return next(
            (approval for approval in reversed(approvals) if approval["status"] == "pending"),
            None,
        )

    def _load_scenario(self, scenario_id: str) -> ScenarioDefinition:
        scenario = ScenarioLoader(self.scenarios_dir).get(scenario_id)
        if scenario is None:
            raise ValueError(f"工作流引用的场景不存在: {scenario_id}")
        return scenario

    def _has_event(
        self,
        incident_id: str,
        event_type: str,
        key: str | None = None,
        value: str | None = None,
    ) -> bool:
        for event in self.store.get_timeline(incident_id):
            if event.event_type != event_type:
                continue
            if key is None:
                return True
            if value is not None and event.payload.get(key) == value:
                return True
        return False

    def _add_once(
        self,
        incident_id: str,
        event_type: str,
        actor: str,
        payload: dict[str, Any],
        *,
        key: str | None = None,
    ) -> None:
        value = str(payload[key]) if key and key in payload else None
        if self._has_event(incident_id, event_type, key, value):
            return
        self.store.add_timeline_event(incident_id, event_type, actor, payload)

    @staticmethod
    def _approval_status_label(status: str) -> str:
        return {"rejected": "已拒绝", "expired": "已过期"}.get(status, "无效")
