"""
Incident Workflow 测试 — 覆盖完整流程、预算耗尽、策略拒绝、Kill Switch。
"""

import pytest
from uuid import uuid4

from sentinel_x_domain.services import compute_plan_hash
from sentinel_x_domain.state_machine import IncidentState, IncidentStatus
from sentinel_x_contracts import RiskLevel as ContractRiskLevel
from sentinel_x_incident_worker.workflows import (
    HypothesisResult,
    IncidentWorkflow,
    PlanResult,
    WorkflowContext,
)
from sentinel_x_policy import RiskLevel


@pytest.fixture
def fresh_state():
    return IncidentState(id=uuid4())


@pytest.fixture
def fresh_ctx(fresh_state):
    return WorkflowContext(incident_id=fresh_state.id, state=fresh_state)


@pytest.mark.asyncio
class TestHappyPath:
    """正常流程测试。"""

    async def test_full_resolution(self, fresh_ctx):
        """完整 DETECTED → RESOLVED 流程。"""
        wf = IncidentWorkflow(fresh_ctx)
        result = await wf.execute()
        assert result.status == IncidentStatus.RESOLVED
        assert len(result.history) >= 6

    async def test_workflow_produces_evidence(self, fresh_ctx):
        """Workflow 应收集证据。"""
        wf = IncidentWorkflow(fresh_ctx)
        await wf.execute()
        assert len(fresh_ctx.collected_evidence_ids) > 0

    async def test_workflow_generates_hypothesis(self, fresh_ctx):
        """Workflow 应生成假设。"""
        wf = IncidentWorkflow(fresh_ctx)
        await wf.execute()
        assert len(fresh_ctx.hypothesis_history) > 0
        assert fresh_ctx.hypothesis_history[0].confidence > 0.5


@pytest.mark.asyncio
class TestBudgetExhaustion:
    """预算耗尽测试。"""

    async def test_time_budget_exhausted(self, fresh_ctx):
        """时间预算耗尽 → ESCALATED。"""
        fresh_ctx.budget_seconds = 1  # 极小预算
        fresh_ctx.seconds_consumed = 1  # 已耗尽
        wf = IncidentWorkflow(fresh_ctx)
        result = await wf.execute()
        assert result.status == IncidentStatus.ESCALATED

    async def test_llm_budget_exhausted(self, fresh_ctx):
        """LLM 调用预算耗尽 → ESCALATED。"""
        fresh_ctx.budget_llm_calls = 0
        wf = IncidentWorkflow(fresh_ctx)
        result = await wf.execute()
        assert result.status in (
            IncidentStatus.ESCALATED,
            IncidentStatus.FAILED,
        )

    async def test_tool_budget_exhausted(self, fresh_ctx):
        """工具调用预算耗尽 → ESCALATED。"""
        fresh_ctx.budget_tool_calls = 0
        wf = IncidentWorkflow(fresh_ctx)
        result = await wf.execute()
        assert result.status in (
            IncidentStatus.ESCALATED,
            IncidentStatus.FAILED,
        )


@pytest.mark.asyncio
class TestKillSwitch:
    """Kill Switch 测试。"""

    async def test_kill_switch_blocks_execution(self, fresh_ctx):
        """Kill Switch 激活时阻止执行。"""
        fresh_ctx.kill_switch_active = True
        wf = IncidentWorkflow(fresh_ctx)
        result = await wf.execute()
        # 执行阶段应被 Kill Switch 拦截 → FAILED
        assert result.status in (
            IncidentStatus.FAILED,
            IncidentStatus.ESCALATED,
        )


@pytest.mark.asyncio
class TestPlanGeneration:
    """计划生成测试。"""

    async def test_plan_hash_uses_shared_canonical_contract(self, fresh_ctx):
        """相同计划不能因 plan_id 变化产生不同 hash。"""
        workflow = IncidentWorkflow(fresh_ctx)
        hypothesis = HypothesisResult(
            hypothesis_id="hypothesis-001",
            statement="inventory-api 进程内状态持续返回 5xx",
            confidence=0.9,
            root_cause_category="application",
            affected_service="inventory-api",
            supporting_evidence_ids=["evidence-001"],
            opposing_evidence_ids=[],
            suggested_next_steps=[],
            needs_human_escalation=False,
        )

        first = await workflow._generate_plan_activity(hypothesis)
        second = await workflow._generate_plan_activity(hypothesis)
        expected = compute_plan_hash(
            first.runbook_ref,
            first.target,
            first.parameters,
            fresh_ctx.incident_id,
        )

        assert first.plan_hash == second.plan_hash == expected
        assert len(first.plan_hash) == 64

    async def test_plan_has_hash(self, fresh_ctx):
        """生成的计划应包含 plan_hash。"""
        wf = IncidentWorkflow(fresh_ctx)
        await wf.execute()
        if fresh_ctx.plan:
            assert fresh_ctx.plan.plan_hash
            assert len(fresh_ctx.plan.plan_hash) == 64

    async def test_plan_is_policy_checked(self, fresh_ctx):
        """计划应经过策略校验。"""
        wf = IncidentWorkflow(fresh_ctx)
        await wf.execute()
        if fresh_ctx.plan:
            assert fresh_ctx.plan.policy_reason  # 策略校验理由不能为空

    async def test_policy_rejection_is_proposed_before_escalation(self, fresh_ctx, monkeypatch):
        """策略拒绝的动作计划必须先进入 PLAN_PROPOSED。"""
        wf = IncidentWorkflow(fresh_ctx)
        wf.sm.transition(IncidentStatus.TRIAGING)
        wf.sm.transition(IncidentStatus.DIAGNOSING)
        fresh_ctx.hypothesis_history.append(
            HypothesisResult(
                hypothesis_id="hypothesis-policy-rejected",
                statement="requires a prohibited action",
                confidence=0.9,
                root_cause_category="database",
                affected_service="inventory-api",
                supporting_evidence_ids=["evidence-001"],
                opposing_evidence_ids=[],
                suggested_next_steps=[],
                needs_human_escalation=False,
            )
        )

        async def rejected_plan(_: HypothesisResult) -> PlanResult:
            return PlanResult(
                plan_id="plan-policy-rejected",
                runbook_ref="db_rollback@1",
                target="inventory-api",
                parameters={},
                risk_level=RiskLevel.R2.value,
                plan_hash="test-plan-hash",
                policy_allowed=False,
                policy_reason="R2 disabled in MVP",
            )

        monkeypatch.setattr(wf, "_generate_plan_activity", rejected_plan)

        await wf._phase_plan()

        assert fresh_ctx.state.status == IncidentStatus.ESCALATED
        assert any("DIAGNOSING -> PLAN_PROPOSED" in entry for entry in fresh_ctx.state.history)
        assert any("PLAN_PROPOSED -> ESCALATED" in entry for entry in fresh_ctx.state.history)

    async def test_no_op_moves_directly_from_diagnosing_to_verifying(self, fresh_ctx, monkeypatch):
        """自动恢复没有动作、审批或 ActionExecution。"""
        wf = IncidentWorkflow(fresh_ctx)

        async def kubernetes_auto_recovery() -> HypothesisResult:
            return HypothesisResult(
                hypothesis_id="hypothesis-auto-recovery",
                statement="workload has already recovered",
                confidence=0.9,
                root_cause_category="kubernetes",
                affected_service="payment-api",
                supporting_evidence_ids=["evidence-001"],
                opposing_evidence_ids=[],
                suggested_next_steps=[],
                needs_human_escalation=False,
            )

        monkeypatch.setattr(wf, "_generate_hypothesis_activity", kubernetes_auto_recovery)

        result = await wf.execute()

        assert result.status == IncidentStatus.RESOLVED
        assert fresh_ctx.plan is not None
        assert fresh_ctx.plan.runbook_ref == "no_op"
        assert fresh_ctx.approval is None
        assert fresh_ctx.actions == []
        assert any("DIAGNOSING -> VERIFYING" in entry for entry in result.history)
        assert all("PLAN_PROPOSED" not in entry for entry in result.history)


def test_policy_risk_level_is_the_shared_contract_enum():
    assert RiskLevel is ContractRiskLevel


@pytest.mark.asyncio
class TestEdgeCases:
    """边界条件测试。"""

    async def test_workflow_terminates(self, fresh_ctx):
        """Workflow 必须在合理时间内终止（不死循环）。"""
        import asyncio
        wf = IncidentWorkflow(fresh_ctx)
        result = await asyncio.wait_for(wf.execute(), timeout=30)
        assert result.status in (
            IncidentStatus.RESOLVED,
            IncidentStatus.ESCALATED,
            IncidentStatus.FAILED,
        )

    async def test_multiple_workflows_independent(self):
        """多个 Workflow 实例互不干扰。"""
        results = []
        for _ in range(3):
            state = IncidentState(id=uuid4())
            ctx = WorkflowContext(incident_id=state.id, state=state)
            wf = IncidentWorkflow(ctx)
            result = await wf.execute()
            results.append(result.status)
        assert all(s in (
            IncidentStatus.RESOLVED, IncidentStatus.ESCALATED, IncidentStatus.FAILED
        ) for s in results)

    async def test_error_log_is_list(self, fresh_ctx):
        """Workflow 的 error_log 应始终是列表类型。"""
        wf = IncidentWorkflow(fresh_ctx)
        await wf.execute()
        # error_log 应始终是列表（可能为空）
        assert isinstance(fresh_ctx.error_log, list)
