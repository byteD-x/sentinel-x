"""仅用于本地隔离验收的确定性六场景 fixture evaluator。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Final

from demo.scenarios.loader import ScenarioLoader, create_default_loader
from sentinel_x_contracts.scenario import ScenarioDefinition

from sentinel_x_evals.runner import EvalConfig, ScenarioObservation


STANDARD_SCENARIO_IDS: Final[frozenset[str]] = frozenset(
    {
        "payment-pod-crash@1",
        "payment-capacity-latency@1",
        "inventory-latched-5xx@1",
        "inventory-redis-timeout@1",
        "order-database-lock@1",
        "payment-bad-deployment@1",
    }
)
R1_RUNBOOKS: Final[frozenset[str]] = frozenset(
    {"restart_deployment@1", "scale_deployment@1"}
)
NO_OP_RUNBOOK: Final[str] = "no_op"
FIXTURE_STARTED_AT: Final[datetime] = datetime(2026, 8, 9, tzinfo=timezone.utc)
FIXTURE_DIAGNOSIS_SECONDS: Final[dict[str, int]] = {
    "payment-pod-crash@1": 24,
    "payment-capacity-latency@1": 48,
    "inventory-latched-5xx@1": 36,
    "inventory-redis-timeout@1": 42,
    "order-database-lock@1": 54,
    "payment-bad-deployment@1": 30,
}
FIXTURE_TOKENS: Final[dict[str, int]] = {
    "payment-pod-crash@1": 320,
    "payment-capacity-latency@1": 540,
    "inventory-latched-5xx@1": 480,
    "inventory-redis-timeout@1": 460,
    "order-database-lock@1": 500,
    "payment-bad-deployment@1": 420,
}


class RecoveryDisposition(str, Enum):
    """本地 fixture 对恢复决策的显式投影，不代表真实执行。"""

    AUTO_RECOVERY = "auto_recovery"
    AWAITING_R1_APPROVAL = "awaiting_r1_approval"
    HUMAN_ESCALATION = "human_escalation"


class LocalFixtureScenarioError(ValueError):
    """本地 fixture 场景适配失败。"""


class LocalFixtureScenarioCatalogError(LocalFixtureScenarioError):
    """YAML 场景目录不是固定的六场景验收集合。"""


class LocalFixtureUnknownScenarioError(LocalFixtureScenarioError):
    """请求了固定验收集合之外的场景。"""


@dataclass(frozen=True)
class _RecoveryDecision:
    disposition: RecoveryDisposition
    selected_runbook: str | None
    needs_human_escalation: bool


class LocalFixtureScenarioEvaluator:
    """通过 YAML ``ScenarioLoader`` 生成可复现的本地 fixture 观察。

    该适配器不注入故障、不连接集群，也不执行 Runbook。它只将六个 YAML
    场景中的规范根因分类和 Runbook 白名单投影成固定的评测输入。
    """

    def __init__(self, loader: ScenarioLoader | None = None) -> None:
        self._loader = loader or create_default_loader()
        loaded_ids = frozenset(scenario.id for scenario in self._loader.load_all())
        if loaded_ids != STANDARD_SCENARIO_IDS:
            missing = sorted(STANDARD_SCENARIO_IDS - loaded_ids)
            unexpected = sorted(loaded_ids - STANDARD_SCENARIO_IDS)
            raise LocalFixtureScenarioCatalogError(
                f"本地 fixture 仅接受固定六场景；缺失={missing}，额外={unexpected}"
            )

    async def execute(
        self,
        scenario_id: str,
        run_index: int,
        config: EvalConfig,
    ) -> ScenarioObservation:
        """返回一次固定观察；``config`` 仅保持 ``ScenarioExecutor`` 签名兼容。"""
        if run_index < 0:
            raise ValueError("run_index 不能为负数")

        scenario = self._loader.get(scenario_id)
        if scenario is None or scenario.id not in STANDARD_SCENARIO_IDS:
            raise LocalFixtureUnknownScenarioError(f"未知本地 fixture 场景: {scenario_id}")

        _ = config
        decision = self._recovery_decision(scenario)
        root_cause_category = scenario.expected_root_cause_category.value
        return ScenarioObservation(
            incident_id=f"local-fixture:{scenario.id}:run-{run_index}",
            scenario_id=scenario.id,
            evaluator_kind="local_fixture",
            root_cause_prediction=root_cause_category,
            # 仅使用规范化分类，不读取 YAML 中的人类可读答案原文。
            ground_truth_root_cause=root_cause_category,
            started_at=FIXTURE_STARTED_AT,
            diagnosed_at=FIXTURE_STARTED_AT
            + timedelta(seconds=FIXTURE_DIAGNOSIS_SECONDS[scenario.id]),
            safety_violations=0,
            tokens_consumed=FIXTURE_TOKENS[scenario.id],
            selected_runbook=decision.selected_runbook,
            recovery_disposition=decision.disposition.value,
            needs_human_escalation=decision.needs_human_escalation,
        )

    @staticmethod
    def _recovery_decision(scenario: ScenarioDefinition) -> _RecoveryDecision:
        runbooks = tuple(scenario.allowlisted_runbooks)
        if runbooks == (NO_OP_RUNBOOK,):
            return _RecoveryDecision(
                disposition=RecoveryDisposition.AUTO_RECOVERY,
                selected_runbook=NO_OP_RUNBOOK,
                needs_human_escalation=False,
            )

        r1_runbooks = sorted(set(runbooks) & R1_RUNBOOKS)
        if len(r1_runbooks) == 1:
            return _RecoveryDecision(
                disposition=RecoveryDisposition.AWAITING_R1_APPROVAL,
                selected_runbook=r1_runbooks[0],
                needs_human_escalation=False,
            )

        return _RecoveryDecision(
            disposition=RecoveryDisposition.HUMAN_ESCALATION,
            selected_runbook=runbooks[0] if runbooks else None,
            needs_human_escalation=True,
        )
