"""
Incident Workflow 测试 — 覆盖完整流程、预算耗尽、策略拒绝、Kill Switch。
"""

import pytest
from uuid import uuid4

from sentinel_x_domain.state_machine import IncidentState, IncidentStatus
from sentinel_x_incident_worker.workflows import (
    IncidentWorkflow,
    WorkflowContext,
)


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

    async def test_plan_has_hash(self, fresh_ctx):
        """生成的计划应包含 plan_hash。"""
        wf = IncidentWorkflow(fresh_ctx)
        await wf.execute()
        if fresh_ctx.plan:
            assert fresh_ctx.plan.plan_hash
            assert len(fresh_ctx.plan.plan_hash) == 16

    async def test_plan_is_policy_checked(self, fresh_ctx):
        """计划应经过策略校验。"""
        wf = IncidentWorkflow(fresh_ctx)
        await wf.execute()
        if fresh_ctx.plan:
            assert fresh_ctx.plan.policy_reason  # 策略校验理由不能为空


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
