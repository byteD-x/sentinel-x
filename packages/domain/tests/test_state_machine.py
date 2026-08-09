"""
事故状态机测试 — 覆盖所有合法转换、非法转换、终态和边界条件。
"""

import pytest
from uuid import uuid4

from sentinel_x_contracts import IncidentStatus as ContractIncidentStatus
from sentinel_x_domain.state_machine import (
    IncidentStatus,
    IncidentState,
    IncidentStateMachine,
    InvalidTransitionError,
    VALID_TRANSITIONS,
    TERMINAL_STATUSES,
)


@pytest.fixture
def fresh_state():
    return IncidentState(id=uuid4())


@pytest.fixture
def fresh_sm(fresh_state):
    return IncidentStateMachine(fresh_state)


class TestValidTransitions:
    """合法状态转换测试。"""

    def test_full_happy_path(self, fresh_sm):
        """完整正常路径: DETECTED → RESOLVED。"""
        transitions = [
            IncidentStatus.TRIAGING,
            IncidentStatus.DIAGNOSING,
            IncidentStatus.PLAN_PROPOSED,
            IncidentStatus.AWAITING_APPROVAL,
            IncidentStatus.EXECUTING,
            IncidentStatus.VERIFYING,
            IncidentStatus.RESOLVED,
        ]
        for target in transitions:
            fresh_sm.transition(target)
        assert fresh_sm.status == IncidentStatus.RESOLVED
        assert fresh_sm.is_terminal
        assert len(fresh_sm._state.history) == 7

    def test_auto_recovery_path(self, fresh_sm):
        """自动恢复路径: DIAGNOSING → VERIFYING → RESOLVED。"""
        fresh_sm.transition(IncidentStatus.TRIAGING)
        fresh_sm.transition(IncidentStatus.DIAGNOSING)
        fresh_sm.transition(IncidentStatus.VERIFYING, reason="Kubernetes 自动恢复")
        fresh_sm.transition(IncidentStatus.RESOLVED)
        assert fresh_sm.status == IncidentStatus.RESOLVED

    def test_escalation_from_diagnosing(self, fresh_sm):
        """证据不足升级: DIAGNOSING → ESCALATED。"""
        fresh_sm.transition(IncidentStatus.TRIAGING)
        fresh_sm.transition(IncidentStatus.DIAGNOSING)
        fresh_sm.transition(IncidentStatus.ESCALATED, reason="预算耗尽")
        assert fresh_sm.status == IncidentStatus.ESCALATED

    def test_escalation_from_plan_proposed(self, fresh_sm):
        """策略拒绝升级: PLAN_PROPOSED → ESCALATED。"""
        fresh_sm.transition(IncidentStatus.TRIAGING)
        fresh_sm.transition(IncidentStatus.DIAGNOSING)
        fresh_sm.transition(IncidentStatus.PLAN_PROPOSED)
        fresh_sm.transition(IncidentStatus.ESCALATED, reason="R2 计划被策略拒绝")
        assert fresh_sm.status == IncidentStatus.ESCALATED

    def test_escalation_from_awaiting_approval(self, fresh_sm):
        """审批拒绝升级: AWAITING_APPROVAL → ESCALATED。"""
        fresh_sm.transition(IncidentStatus.TRIAGING)
        fresh_sm.transition(IncidentStatus.DIAGNOSING)
        fresh_sm.transition(IncidentStatus.PLAN_PROPOSED)
        fresh_sm.transition(IncidentStatus.AWAITING_APPROVAL)
        fresh_sm.transition(IncidentStatus.ESCALATED, reason="审批被拒绝")
        assert fresh_sm.status == IncidentStatus.ESCALATED

    def test_execution_failure(self, fresh_sm):
        """执行失败: EXECUTING → FAILED。"""
        fresh_sm.transition(IncidentStatus.TRIAGING)
        fresh_sm.transition(IncidentStatus.DIAGNOSING)
        fresh_sm.transition(IncidentStatus.PLAN_PROPOSED)
        fresh_sm.transition(IncidentStatus.AWAITING_APPROVAL)
        fresh_sm.transition(IncidentStatus.EXECUTING)
        fresh_sm.transition(IncidentStatus.FAILED, reason="Action Gateway 返回错误")
        assert fresh_sm.status == IncidentStatus.FAILED

    def test_verification_failure(self, fresh_sm):
        """恢复失败: VERIFYING → FAILED。"""
        fresh_sm.transition(IncidentStatus.TRIAGING)
        fresh_sm.transition(IncidentStatus.DIAGNOSING)
        fresh_sm.transition(IncidentStatus.PLAN_PROPOSED)
        fresh_sm.transition(IncidentStatus.AWAITING_APPROVAL)
        fresh_sm.transition(IncidentStatus.EXECUTING)
        fresh_sm.transition(IncidentStatus.VERIFYING)
        fresh_sm.transition(IncidentStatus.FAILED, reason="SLO 未恢复")
        assert fresh_sm.status == IncidentStatus.FAILED


class TestInvalidTransitions:
    """非法状态转换测试。"""

    def test_detected_to_executing_blocked(self, fresh_sm):
        """DETECTED → EXECUTING 被阻止。"""
        with pytest.raises(InvalidTransitionError):
            fresh_sm.transition(IncidentStatus.EXECUTING)

    def test_detected_to_resolved_blocked(self, fresh_sm):
        """DETECTED → RESOLVED 被阻止。"""
        with pytest.raises(InvalidTransitionError):
            fresh_sm.transition(IncidentStatus.RESOLVED)

    def test_triaging_to_executing_blocked(self, fresh_sm):
        """TRIAGING → EXECUTING 被阻止。"""
        fresh_sm.transition(IncidentStatus.TRIAGING)
        with pytest.raises(InvalidTransitionError):
            fresh_sm.transition(IncidentStatus.EXECUTING)

    def test_terminal_no_further_transitions(self, fresh_sm):
        """终态不允许进一步转换。"""
        fresh_sm.transition(IncidentStatus.TRIAGING)
        fresh_sm.transition(IncidentStatus.DIAGNOSING)
        fresh_sm.transition(IncidentStatus.ESCALATED)
        # 已是终态
        with pytest.raises(InvalidTransitionError):
            fresh_sm.transition(IncidentStatus.RESOLVED)


class TestStateMachineHelpers:
    """辅助方法测试。"""

    def test_can_transition_to(self, fresh_sm):
        assert fresh_sm.can_transition_to(IncidentStatus.TRIAGING) is True
        assert fresh_sm.can_transition_to(IncidentStatus.EXECUTING) is False

    def test_available_transitions(self, fresh_sm):
        transitions = fresh_sm.available_transitions()
        assert transitions == {IncidentStatus.TRIAGING}

        fresh_sm.transition(IncidentStatus.TRIAGING)
        transitions = fresh_sm.available_transitions()
        assert transitions == {IncidentStatus.DIAGNOSING}

    def test_history_complete(self, fresh_sm):
        """状态历史完整记录。"""
        fresh_sm.transition(IncidentStatus.TRIAGING, reason="告警触发")
        fresh_sm.transition(IncidentStatus.DIAGNOSING)
        history = fresh_sm._state.history
        assert "DETECTED -> TRIAGING (告警触发)" in history
        assert "TRIAGING -> DIAGNOSING" in history

    def test_version_increments(self, fresh_sm):
        """每次转换版本号递增。"""
        assert fresh_sm._state.version == 1
        fresh_sm.transition(IncidentStatus.TRIAGING)
        assert fresh_sm._state.version == 2
        fresh_sm.transition(IncidentStatus.DIAGNOSING)
        assert fresh_sm._state.version == 3

    def test_resolved_at_set_on_terminal(self, fresh_sm):
        """进入终态时设置 resolved_at。"""
        assert fresh_sm._state.resolved_at is None
        fresh_sm.transition(IncidentStatus.TRIAGING)
        fresh_sm.transition(IncidentStatus.DIAGNOSING)
        fresh_sm.transition(IncidentStatus.ESCALATED)
        assert fresh_sm._state.resolved_at is not None


class TestAllTransitionsCovered:
    """确保 VALID_TRANSITIONS 覆盖所有状态。"""

    def test_all_statuses_have_definition(self):
        """每个状态都在转换表中。"""
        for status in IncidentStatus:
            assert status in VALID_TRANSITIONS, f"{status} 缺少转换定义"

    def test_terminal_have_no_outgoing(self):
        """终态没有出边。"""
        for status in TERMINAL_STATUSES:
            assert VALID_TRANSITIONS[status] == set(), f"{status} 不应有出边"

    def test_active_have_outgoing(self):
        """非终态至少有一个出边。"""
        for status in IncidentStatus:
            if status not in TERMINAL_STATUSES:
                assert len(VALID_TRANSITIONS[status]) > 0, f"{status} 缺少出边"


class TestContractReuse:
    def test_status_is_the_shared_contract_enum(self):
        assert IncidentStatus is ContractIncidentStatus
