"""
事故 Workflow — 事故生命周期的确定性编排。

每个事故实例对应一个 Temporal Workflow。
Workflow 内只保存确定性逻辑（状态机转换、条件判断），
所有外部 I/O 封装在 Activity 中。

规范流程：
  DETECTED → TRIAGING → DIAGNOSING → PLAN_PROPOSED
  → AWAITING_APPROVAL → EXECUTING → VERIFYING → RESOLVED
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sentinel_x_contracts import IncidentStatus, RiskLevel
from sentinel_x_domain.state_machine import (
    IncidentState,
    IncidentStateMachine,
)
from sentinel_x_domain.services import compute_plan_hash
from sentinel_x_policy import (
    check_mvp_policy,
    classify_runbook_risk,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Activity 结果类型
# ---------------------------------------------------------------------------


@dataclass
class EvidenceResult:
    """证据收集 Activity 的返回结果。"""
    evidence_ids: list[str]
    total_collected: int
    errors: list[str] = field(default_factory=list)


@dataclass
class HypothesisResult:
    """假设生成 Activity 的返回结果。"""
    hypothesis_id: str
    statement: str
    confidence: float
    root_cause_category: str
    affected_service: str
    supporting_evidence_ids: list[str]
    opposing_evidence_ids: list[str]
    suggested_next_steps: list[str]
    needs_human_escalation: bool
    model_name: str = ""
    tokens_used: int = 0


@dataclass
class PlanResult:
    """计划生成 Activity 的返回结果。"""
    plan_id: str
    runbook_ref: str
    target: str
    parameters: dict
    risk_level: str
    plan_hash: str
    policy_allowed: bool
    policy_reason: str


@dataclass
class ApprovalResult:
    """审批等待 Activity 的返回结果。"""
    approval_id: str
    approved: bool
    decided_by: str
    reason: str
    decided_at: datetime


@dataclass
class ActionResult:
    """动作执行 Activity 的返回结果。"""
    execution_id: str
    success: bool
    before_state: str
    after_state: str
    output: str
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Workflow 内部状态
# ---------------------------------------------------------------------------


@dataclass
class WorkflowContext:
    """
    Workflow 内部上下文 — 跟踪调查预算和执行状态。

    在真实 Temporal 中，这存储在 Workflow 的成员变量中。
    """
    incident_id: UUID
    state: IncidentState
    budget_seconds: int = 480
    budget_llm_calls: int = 8
    budget_tool_calls: int = 20
    seconds_consumed: int = 0
    llm_calls_consumed: int = 0
    tool_calls_consumed: int = 0
    collected_evidence_ids: list[str] = field(default_factory=list)
    hypothesis_history: list[HypothesisResult] = field(default_factory=list)
    plan: Optional[PlanResult] = None
    approval: Optional[ApprovalResult] = None
    actions: list[ActionResult] = field(default_factory=list)
    error_log: list[str] = field(default_factory=list)
    kill_switch_active: bool = False

    @property
    def budget_exhausted(self) -> bool:
        return (
            self.seconds_consumed >= self.budget_seconds
            or self.llm_calls_consumed >= self.budget_llm_calls
            or self.tool_calls_consumed >= self.budget_tool_calls
        )


# ---------------------------------------------------------------------------
# IncidentWorkflow 编排器
# ---------------------------------------------------------------------------


class IncidentWorkflow:
    """
    事故 Workflow 编排器。

    在真实 Temporal 环境中使用 @workflow.defn 装饰，
    当前实现为可测试的异步编排器。

    用法：
        wf = IncidentWorkflow(ctx)
        await wf.execute()
    """

    def __init__(self, ctx: WorkflowContext):
        self.ctx = ctx
        self.sm = IncidentStateMachine(ctx.state)
        self._started_at = datetime.now()

    async def execute(self) -> IncidentState:
        """执行完整的事故 Workflow。"""
        logger.info(f"Workflow 启动: incident={self.ctx.incident_id}")

        try:
            # Phase 1: Triage — 分诊
            await self._phase_triage()

            # Phase 2: Diagnosis — 诊断调查
            await self._phase_diagnosis()

            # 检查是否需要升级
            if self.sm.status == IncidentStatus.ESCALATED:
                return self.ctx.state

            # Phase 3: Plan — 提出方案
            await self._phase_plan()

            if self.sm.status == IncidentStatus.ESCALATED:
                return self.ctx.state

            # Phase 4: Approval — 等待审批
            await self._phase_approval()

            if self.sm.status == IncidentStatus.ESCALATED:
                return self.ctx.state

            # Phase 5: Execute — 执行恢复
            await self._phase_execute()

            if self.sm.status == IncidentStatus.FAILED:
                return self.ctx.state

            # Phase 6: Verify — 验证恢复
            await self._phase_verify()

        except Exception as e:
            logger.error(f"Workflow 异常: {e}")
            if self.sm.is_active:
                self.sm.transition(IncidentStatus.FAILED, reason=str(e))
            self.ctx.error_log.append(str(e))

        elapsed = (datetime.now() - self._started_at).total_seconds()
        logger.info(
            f"Workflow 完成: incident={self.ctx.incident_id}, "
            f"status={self.sm.status.value}, elapsed={elapsed:.1f}s"
        )
        return self.ctx.state

    async def _phase_triage(self) -> None:
        """分诊阶段：收集初始证据。"""
        self.sm.transition(IncidentStatus.TRIAGING, reason="告警触发")

        # Activity: 收集证据
        evidence = await self._collect_evidence_activity()
        self.ctx.collected_evidence_ids.extend(evidence.evidence_ids)
        self.ctx.tool_calls_consumed += 1
        self.ctx.seconds_consumed += 5  # 模拟耗时

        if evidence.total_collected == 0:
            self.sm.transition(
                IncidentStatus.ESCALATED,
                reason="无法收集任何证据",
            )

    async def _phase_diagnosis(self) -> None:
        """诊断阶段：生成假设并迭代调查。"""
        self.sm.transition(IncidentStatus.DIAGNOSING, reason="开始诊断")

        max_iterations = 3
        for iteration in range(max_iterations):
            if self.ctx.budget_exhausted:
                self.sm.transition(
                    IncidentStatus.ESCALATED,
                    reason="调查预算耗尽",
                )
                return

            # Activity: 生成假设
            hypothesis = await self._generate_hypothesis_activity()
            self.ctx.hypothesis_history.append(hypothesis)
            self.ctx.llm_calls_consumed += 1
            self.ctx.seconds_consumed += 15

            # 判断是否需要更多证据
            if hypothesis.needs_human_escalation:
                self.sm.transition(
                    IncidentStatus.ESCALATED,
                    reason=f"模型建议人工介入: {hypothesis.statement}",
                )
                return

            # 如果置信度足够高，停止诊断
            if hypothesis.confidence >= 0.6:
                logger.info(
                    f"诊断置信度达标: {hypothesis.confidence:.2f}, "
                    f"类别={hypothesis.root_cause_category}"
                )
                break

            # 否则收集更多证据（循环）
            if iteration < max_iterations - 1:
                additional = await self._collect_evidence_activity()
                self.ctx.collected_evidence_ids.extend(additional.evidence_ids)
                self.ctx.tool_calls_consumed += 1

    async def _phase_plan(self) -> None:
        """方案阶段：基于最佳假设生成恢复计划。"""
        if not self.ctx.hypothesis_history:
            self.sm.transition(IncidentStatus.ESCALATED, reason="无可用假设")
            return

        # 选择置信度最高的假设
        best = max(self.ctx.hypothesis_history, key=lambda h: h.confidence)

        # Activity: 生成计划
        plan = await self._generate_plan_activity(best)
        self.ctx.plan = plan
        self.ctx.llm_calls_consumed += 1

        # 无动作的自动恢复不进入 PLAN_PROPOSED，不创建审批或 ActionExecution。
        if plan.runbook_ref == "no_op":
            self.sm.transition(
                IncidentStatus.VERIFYING,
                reason="自动恢复场景，无需动作",
            )
            return

        self.sm.transition(IncidentStatus.PLAN_PROPOSED, reason="生成恢复方案")

        if not plan.policy_allowed:
            logger.warning(f"策略拒绝: {plan.policy_reason}")
            self.sm.transition(
                IncidentStatus.ESCALATED,
                reason=f"策略拒绝: {plan.policy_reason}",
            )
            return

    async def _phase_approval(self) -> None:
        """审批阶段：等待人工审批。"""
        if not self.ctx.plan:
            return

        # 自动恢复或 R0 无需审批
        if self.sm.status == IncidentStatus.VERIFYING:
            return

        risk = classify_runbook_risk(self.ctx.plan.runbook_ref)
        if risk == RiskLevel.R0:
            return  # R0 无需审批

        self.sm.transition(
            IncidentStatus.AWAITING_APPROVAL,
            reason=f"等待审批: {self.ctx.plan.runbook_ref} → {self.ctx.plan.target}",
        )

        # Activity: 等待审批（在 Temporal 中这是 workflow.wait_for_signal）
        approval = await self._await_approval_activity(self.ctx.plan)
        self.ctx.approval = approval

        if not approval.approved:
            self.sm.transition(
                IncidentStatus.ESCALATED,
                reason=f"审批被拒绝: {approval.reason}",
            )

    async def _phase_execute(self) -> None:
        """执行阶段：通过 Action Gateway 执行已审批的动作。"""
        if not self.ctx.plan or not self.ctx.approval:
            return

        # 自动恢复场景无需执行
        if self.ctx.plan.runbook_ref == "no_op":
            return

        # Kill Switch 检查
        decision = check_mvp_policy(
            self.ctx.plan.runbook_ref,
            self.ctx.plan.target,
            kill_switch_active=self.ctx.kill_switch_active,
        )
        if not decision.allowed:
            self.sm.transition(
                IncidentStatus.ESCALATED,
                reason=f"执行前策略拦截: {decision.reason}（当前状态: {self.sm.status.value}）",
            )
            return

        self.sm.transition(
            IncidentStatus.EXECUTING,
            reason=f"执行: {self.ctx.plan.runbook_ref}",
        )

        # Activity: 执行动作
        result = await self._execute_action_activity(
            self.ctx.plan, self.ctx.approval
        )
        self.ctx.actions.append(result)

        if not result.success:
            self.sm.transition(
                IncidentStatus.FAILED,
                reason=f"动作执行失败: {result.error or result.output}",
            )

    async def _phase_verify(self) -> None:
        """验证阶段：检查 SLO 恢复。"""
        if self.sm.status == IncidentStatus.EXECUTING:
            self.sm.transition(IncidentStatus.VERIFYING, reason="验证恢复状态")
        elif self.sm.status != IncidentStatus.VERIFYING:
            raise RuntimeError(f"不能从 {self.sm.status.value} 进入恢复验证")

        # Activity: 验证恢复
        recovered = await self._verify_recovery_activity()
        self.ctx.tool_calls_consumed += 1

        if recovered:
            self.sm.transition(IncidentStatus.RESOLVED, reason="SLO 恢复验证通过")
        else:
            self.sm.transition(
                IncidentStatus.FAILED,
                reason="SLO 恢复验证未通过",
            )

    # -------------------------------------------------------------------
    # Activity 桩 — 在生产环境中这些是真正的 Temporal Activities
    # -------------------------------------------------------------------

    async def _collect_evidence_activity(self) -> EvidenceResult:
        """[Activity] 通过 Diagnostic Gateway 收集证据。"""
        await asyncio.sleep(0.1)  # 模拟网络延迟
        return EvidenceResult(
            evidence_ids=[str(uuid4()) for _ in range(2)],
            total_collected=2,
        )

    async def _generate_hypothesis_activity(self) -> HypothesisResult:
        """[Activity] 调用 LLM 生成根因假设。"""
        await asyncio.sleep(0.3)
        hid = str(uuid4())
        return HypothesisResult(
            hypothesis_id=hid,
            statement="疑似 inventory-api 连接超时导致 payment-api 延迟飙升",
            confidence=0.72,
            root_cause_category="network",
            affected_service="inventory-api",
            supporting_evidence_ids=self.ctx.collected_evidence_ids[:1],
            opposing_evidence_ids=[],
            suggested_next_steps=[
                "检查 inventory-api 网络连通性",
                "查看 inventory-api 最近部署变更",
            ],
            needs_human_escalation=False,
            model_name="qwen2.5:7b",
            tokens_used=520,
        )

    async def _generate_plan_activity(
        self, hypothesis: HypothesisResult
    ) -> PlanResult:
        """[Activity] 基于假设生成恢复计划。"""
        await asyncio.sleep(0.1)

        # 根据根因类别决定 Runbook
        runbook_map = {
            "network": "restart_deployment@1",
            "application": "restart_deployment@1",
            "database": "scale_deployment@1",
            "kubernetes": "no_op",
            "unknown": "scale_deployment@1",
        }
        runbook = runbook_map.get(hypothesis.root_cause_category, "restart_deployment@1")
        target = hypothesis.affected_service

        plan_id = str(uuid4())
        parameters = {"reason": hypothesis.statement}
        plan_hash = compute_plan_hash(
            runbook,
            target,
            parameters,
            self.ctx.incident_id,
        )

        # no_op 是自动恢复场景，无需策略校验
        if runbook == "no_op":
            return PlanResult(
                plan_id=plan_id,
                runbook_ref=runbook,
                target=target,
                parameters=parameters,
                risk_level=RiskLevel.R0.value,
                plan_hash=plan_hash,
                policy_allowed=True,
                policy_reason="自动恢复场景，无需策略校验",
            )

        # 策略校验
        decision = check_mvp_policy(runbook, target)

        return PlanResult(
            plan_id=plan_id,
            runbook_ref=runbook,
            target=target,
            parameters=parameters,
            risk_level=decision.risk_level.value,
            plan_hash=plan_hash,
            policy_allowed=decision.allowed,
            policy_reason=decision.reason,
        )

    async def _await_approval_activity(
        self, plan: PlanResult
    ) -> ApprovalResult:
        """
        [Activity] 等待人工审批。

        在真实 Temporal 中，使用 workflow.wait_for_signal('approval_decision')。
        此处模拟自动批准（仅用于测试）。
        """
        await asyncio.sleep(0.5)  # 模拟等待
        return ApprovalResult(
            approval_id=str(uuid4()),
            approved=True,
            decided_by="demo-operator",
            reason="自动批准（测试模式）",
            decided_at=datetime.now(),
        )

    async def _execute_action_activity(
        self, plan: PlanResult, approval: ApprovalResult
    ) -> ActionResult:
        """
        [Activity] 通过 Action Gateway 执行已批准的动作。

        在真实环境中，此 Activity 调用 Action Gateway 的 gRPC/HTTP 接口。
        """
        await asyncio.sleep(0.5)

        # 模拟幂等键
        idempotency_key = f"{plan.runbook_ref}:{plan.target}:{plan.plan_hash}:{approval.approval_id[:8]}"

        return ActionResult(
            execution_id=str(uuid4()),
            success=True,
            before_state=f"{plan.target}: replicas=3, status=degraded",
            after_state=f"{plan.target}: replicas=3, status=healthy",
            output=f"成功执行 {plan.runbook_ref} on {plan.target}",
        )

    async def _verify_recovery_activity(self) -> bool:
        """[Activity] 验证 SLO 恢复。"""
        await asyncio.sleep(0.3)
        # 确定性测试：始终返回 True，避免随机失败
        return True
