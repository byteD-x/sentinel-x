"""本地隔离状态库的持久化恢复测试。"""

from datetime import datetime, timedelta
from pathlib import Path

from demo.scenarios.loader import ScenarioLoader
from sentinel_x_contracts import IncidentSeverity, IncidentStatus, RiskLevel
from sentinel_x_control_api.app import (
    AlertSource,
    ApprovalRequest,
    ApprovalDecision,
    IncidentCreate,
    InMemoryStore,
)
from sentinel_x_control_api.local_workflow import LocalExerciseWorkflow
from sentinel_x_domain.services import compute_plan_hash


def test_store_restores_incident_timeline_and_approval_after_recreation(tmp_path):
    """本地进程重建后必须保留可继续处理的审批事故。"""
    state_path = tmp_path / "control-api.sqlite3"
    store = InMemoryStore(state_path=state_path)
    incident = store.create_incident(
        IncidentCreate(
            alert_source=AlertSource(
                alertmanager_id="local-state-test",
                fingerprint="local-state-test-fingerprint",
                alert_name="Inventory latch",
                severity=IncidentSeverity.WARNING,
                description="inventory-api returns latched 5xx",
                started_at=datetime(2026, 8, 9, 12, 0, 0),
            )
        )
    )
    store.set_status(incident, IncidentStatus.TRIAGING, "已接收隔离演练信号")
    store.set_status(incident, IncidentStatus.DIAGNOSING, "开始收集证据")
    store.set_status(incident, IncidentStatus.PLAN_PROPOSED, "生成受控恢复计划")
    parameters = {"reason": "latched failure", "timeout_seconds": 120}
    approval = store.create_approval(
        incident.id,
        ApprovalRequest(
            plan_id="plan-local-state",
            runbook_ref="restart_deployment@1",
            target="inventory-api",
            parameters=parameters,
            risk_level=RiskLevel.R1,
            plan_hash=compute_plan_hash(
                "restart_deployment@1", "inventory-api", parameters, incident.id
            ),
            hypothesis_id="hyp-local-state",
        ),
    )

    restored = InMemoryStore(state_path=state_path)
    restored_incident = restored.get_incident(incident.id)

    assert restored_incident is not None
    assert restored_incident.status is IncidentStatus.AWAITING_APPROVAL
    assert [event.sequence for event in restored.get_timeline(incident.id)] == [1, 2, 3, 4, 5, 6]
    assert restored.list_approvals(incident.id) == [approval]


def test_store_restores_resumable_workflow_checkpoint_after_recreation(tmp_path):
    """等待审批的工作流在进程重建后必须保留唯一处理位置。"""
    state_path = tmp_path / "workflow.sqlite3"
    store = InMemoryStore(state_path=state_path)
    incident = store.create_incident(
        IncidentCreate(
            alert_source=AlertSource(
                alertmanager_id="workflow-state-test",
                fingerprint="workflow-state-test-fingerprint",
                alert_name="Capacity saturation",
                severity=IncidentSeverity.WARNING,
                description="payment-api capacity is saturated",
                started_at=datetime(2026, 8, 9, 12, 0, 0),
            )
        )
    )

    checkpoint = store.create_workflow_checkpoint(
        incident_id=incident.id,
        scenario_id="payment-capacity-latency@1",
        phase="awaiting_approval",
    )

    restored = InMemoryStore(state_path=state_path)

    assert restored.get_workflow_checkpoint(incident.id) == checkpoint


def test_approved_local_workflow_resumes_without_duplicate_action_after_restart(tmp_path):
    """批准落盘后重启，恢复只能提交一次固定动作并走到验证终态。"""
    scenario_dir = Path(__file__).resolve().parents[3] / "demo" / "scenarios"
    scenario = ScenarioLoader(scenario_dir).get("inventory-latched-5xx@1")
    assert scenario is not None
    state_path = tmp_path / "approved-workflow.sqlite3"
    store = InMemoryStore(state_path=state_path)
    incident = store.create_incident(
        IncidentCreate(
            alert_source=AlertSource(
                alertmanager_id="approved-workflow-test",
                fingerprint="approved-workflow-test-fingerprint",
                alert_name="Inventory latch",
                severity=IncidentSeverity.WARNING,
                description="inventory-api returns latched 5xx",
                started_at=datetime(2026, 8, 9, 12, 0, 0),
            )
        )
    )
    workflow = LocalExerciseWorkflow(store)
    workflow.start(incident.id, scenario)
    approval = store.list_approvals(incident.id)[0]
    store.decide_approval(
        approval["id"],
        ApprovalDecision(approved=True, reason="已核对本地隔离目标"),
        decided_by="approver",
        incident_id=incident.id,
    )

    restarted_store = InMemoryStore(state_path=state_path)
    restarted_workflow = LocalExerciseWorkflow(restarted_store)
    restarted_workflow.resume(incident.id)
    restarted_workflow.resume(incident.id)
    restored = restarted_store.get_incident(incident.id)

    assert restored is not None
    assert restored.status is IncidentStatus.RESOLVED
    assert [
        event.event_type for event in restarted_store.get_timeline(incident.id)
    ].count("action.started") == 1
    assert restarted_store.get_workflow_checkpoint(incident.id)["completed"] is True


def test_planning_checkpoint_recovers_without_recursive_resume(tmp_path):
    """计划检查点落盘后崩溃，重启应补建审批而不是递归推进。"""
    scenario_dir = Path(__file__).resolve().parents[3] / "demo" / "scenarios"
    scenario = ScenarioLoader(scenario_dir).get("inventory-latched-5xx@1")
    assert scenario is not None
    store = InMemoryStore(state_path=tmp_path / "planning-crash.sqlite3")
    incident = store.create_incident(
        IncidentCreate(
            alert_source=AlertSource(
                alertmanager_id="planning-crash",
                fingerprint="planning-crash-fingerprint",
                alert_name="Inventory latch",
                severity=IncidentSeverity.WARNING,
                description="inventory-api returns latched 5xx",
                started_at=datetime(2026, 8, 9, 12, 0, 0),
            )
        )
    )
    store.set_status(incident, IncidentStatus.TRIAGING, "故障已确认")
    store.set_status(incident, IncidentStatus.DIAGNOSING, "证据已收集")
    store.set_status(incident, IncidentStatus.PLAN_PROPOSED, "计划已生成")
    store.create_workflow_checkpoint(
        incident_id=incident.id,
        scenario_id=scenario.id,
        phase="planning",
    )

    workflow = LocalExerciseWorkflow(store)
    workflow.resume(incident.id)

    approvals = store.list_approvals(incident.id)
    assert len(approvals) == 1
    assert store.get_workflow_checkpoint(incident.id)["phase"] == "awaiting_approval"


def test_approved_expired_workflow_escalates_without_action(tmp_path):
    """批准后停机超过有效期，恢复必须拒绝动作并升级人工。"""
    scenario_dir = Path(__file__).resolve().parents[3] / "demo" / "scenarios"
    scenario = ScenarioLoader(scenario_dir).get("inventory-latched-5xx@1")
    assert scenario is not None
    store = InMemoryStore(state_path=tmp_path / "expired-approval.sqlite3")
    incident = store.create_incident(
        IncidentCreate(
            alert_source=AlertSource(
                alertmanager_id="expired-approval",
                fingerprint="expired-approval-fingerprint",
                alert_name="Inventory latch",
                severity=IncidentSeverity.WARNING,
                description="inventory-api returns latched 5xx",
                started_at=datetime(2026, 8, 9, 12, 0, 0),
            )
        )
    )
    workflow = LocalExerciseWorkflow(store)
    workflow.start(incident.id, scenario)
    approval = store.list_approvals(incident.id)[0]
    store.decide_approval(
        approval["id"],
        ApprovalDecision(approved=True, reason="已批准"),
        decided_by="approver",
        incident_id=incident.id,
    )
    approval["expires_at"] = (datetime.now() - timedelta(minutes=1)).isoformat()
    store.flush()

    workflow.resume(incident.id)

    restored = store.get_incident(incident.id)
    assert restored is not None
    assert restored.status is IncidentStatus.ESCALATED
    assert store.list_approvals(incident.id)[0]["status"] == "expired"
    assert not any(
        event.event_type == "action.started"
        for event in store.get_timeline(incident.id)
    )
