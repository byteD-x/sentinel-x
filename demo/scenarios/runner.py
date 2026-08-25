"""隔离演练场景 Runner。

Runner 只调用受控 backend，不执行 YAML 中的 ``cleanup_command`` 字符串。
默认的内存 backend 用于 CI 和没有 Docker/Kubernetes 的开发环境；真实 kind/k3d
backend 必须实现同一协议并自行提供目标身份与 cleanup 证据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from sentinel_x_contracts.scenario import ScenarioDefinition


class ScenarioBackend(Protocol):
    """受控故障注入后端。"""

    def inject(self, scenario: ScenarioDefinition) -> str: ...

    def observe(self, scenario: ScenarioDefinition) -> dict[str, object]: ...

    def cleanup(self, scenario: ScenarioDefinition) -> str: ...

    def is_clean(self) -> bool: ...


class ScenarioRunnerError(RuntimeError):
    """演练无法安全完成。"""


@dataclass(frozen=True)
class ScenarioCycleResult:
    scenario_id: str
    cycle: int
    injected: bool
    observed: dict[str, object]
    cleaned: bool
    environment_clean: bool
    started_at: str
    completed_at: str
    error: str | None = None


@dataclass
class InMemoryScenarioBackend:
    """确定性的隔离 backend，不连接外部服务。"""

    active: dict[str, dict[str, object]] = field(default_factory=dict)
    cleanup_calls: dict[str, int] = field(default_factory=dict)

    def inject(self, scenario: ScenarioDefinition) -> str:
        if scenario.id in self.active:
            raise ScenarioRunnerError(f"场景已注入: {scenario.id}")
        targets = {fault.target_namespace for fault in scenario.faults}
        if targets != {"demo-shop"}:
            raise ScenarioRunnerError("场景目标必须全部位于 demo-shop namespace")
        self.active[scenario.id] = {
            "scenario_id": scenario.id,
            "fault_types": [fault.fault_type for fault in scenario.faults],
            "targets": [fault.target_service for fault in scenario.faults],
            "injected": True,
        }
        return f"memory://scenario/{scenario.id}/injected"

    def observe(self, scenario: ScenarioDefinition) -> dict[str, object]:
        state = self.active.get(scenario.id)
        if state is None:
            raise ScenarioRunnerError(f"场景尚未注入: {scenario.id}")
        return {
            "source": "local-memory",
            "scenario_id": scenario.id,
            "active": True,
            "fault_types": list(state["fault_types"]),
            "target_services": list(state["targets"]),
            "ground_truth_category": scenario.expected_root_cause_category.value,
        }

    def cleanup(self, scenario: ScenarioDefinition) -> str:
        self.cleanup_calls[scenario.id] = self.cleanup_calls.get(scenario.id, 0) + 1
        self.active.pop(scenario.id, None)
        return f"memory://scenario/{scenario.id}/cleaned"

    def is_clean(self) -> bool:
        return not self.active


class ScenarioRunner:
    """执行注入、观测、cleanup，并在每轮结束强制检查 dirty gate。"""

    def __init__(self, backend: ScenarioBackend):
        self.backend = backend

    def run_cycle(self, scenario: ScenarioDefinition, cycle: int) -> ScenarioCycleResult:
        if cycle < 1:
            raise ValueError("cycle 必须从 1 开始")
        started = datetime.now(timezone.utc)
        # inject 可能在写入部分状态后失败；只要调用过 inject，就必须进入
        # cleanup，避免异常路径把演练环境留在 DIRTY 状态。
        injection_attempted = False
        injected = False
        observed: dict[str, object] = {}
        error: str | None = None
        cleaned = False
        try:
            injection_attempted = True
            self.backend.inject(scenario)
            injected = True
            observed = self.backend.observe(scenario)
        except Exception as exc:  # noqa: BLE001 - runner 要记录失败并继续 cleanup
            error = str(exc)
        finally:
            if injection_attempted:
                try:
                    self.backend.cleanup(scenario)
                    cleaned = True
                except Exception as exc:  # noqa: BLE001 - 汇总为可审计失败
                    error = error or str(exc)
        environment_clean = self.backend.is_clean()
        if not environment_clean:
            error = error or "演练环境 DIRTY，存在未清理注入"
        completed = datetime.now(timezone.utc)
        return ScenarioCycleResult(
            scenario_id=scenario.id,
            cycle=cycle,
            injected=injected,
            observed=observed,
            cleaned=cleaned,
            environment_clean=environment_clean,
            started_at=started.isoformat(),
            completed_at=completed.isoformat(),
            error=error,
        )

    def run_matrix(self, scenarios: list[ScenarioDefinition], cycles: int = 3) -> list[ScenarioCycleResult]:
        if cycles < 1:
            raise ValueError("cycles 必须大于 0")
        results: list[ScenarioCycleResult] = []
        for cycle in range(1, cycles + 1):
            for scenario in scenarios:
                result = self.run_cycle(scenario, cycle)
                results.append(result)
                if not result.environment_clean:
                    raise ScenarioRunnerError(f"第 {cycle} 轮 {scenario.id} 后环境 DIRTY")
        return results
