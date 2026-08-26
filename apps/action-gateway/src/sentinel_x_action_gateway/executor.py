"""受控动作执行器。

默认执行器只生成 light fixture 结果；``FakeKubernetesExecutor`` 用于
隔离测试和 CI，维护受限 Deployment 状态，不连接真实 Kubernetes 集群。
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from sentinel_x_action_gateway.approval_store import TargetIdentity


class ActionExecutionError(RuntimeError):
    """动作执行器无法安全完成请求。"""


class TargetIdentityMismatch(ActionExecutionError):
    """请求中的目标身份与当前 Deployment 身份不一致。"""


@dataclass(frozen=True)
class ActionExecutionResult:
    """执行器返回的受控结果。"""

    status: str
    after_state: str | None = None
    output: str | None = None
    error: str | None = None


class ActionExecutor(Protocol):
    """Gateway 可替换的动作执行边界。"""

    execution_mode: str

    def describe(self, target_identity: TargetIdentity) -> str:
        """读取执行前状态。"""

    def execute(
        self,
        runbook_ref: str,
        target_identity: TargetIdentity,
        parameters: dict,
    ) -> ActionExecutionResult:
        """执行一个已通过 Gateway 门控的动作。"""

    def reconcile(
        self,
        runbook_ref: str,
        target_identity: TargetIdentity,
        parameters: dict,
    ) -> ActionExecutionResult:
        """重新读取受限目标，协调此前结果未知的动作。"""


class FixtureActionExecutor:
    """light profile 的确定性执行器，不产生外部副作用。"""

    execution_mode = "fixture"

    @staticmethod
    def _replicas(parameters: dict) -> int:
        value = parameters.get("replicas", 3)
        return value if isinstance(value, int) and not isinstance(value, bool) else 3

    def describe(self, target_identity: TargetIdentity) -> str:
        return (
            f"{target_identity.name}: replicas=3, status=running, "
            f"uid={target_identity.uid}, generation={target_identity.generation}"
        )

    def execute(
        self,
        runbook_ref: str,
        target_identity: TargetIdentity,
        parameters: dict,
    ) -> ActionExecutionResult:
        replicas = self._replicas(parameters)
        return ActionExecutionResult(
            status="succeeded",
            after_state=(
                f"{target_identity.name}: replicas={replicas}, status=healthy, "
                f"uid={target_identity.uid}, generation={target_identity.generation}"
            ),
            output=f"成功执行 {runbook_ref} on {target_identity.name}",
        )

    def reconcile(
        self,
        runbook_ref: str,
        target_identity: TargetIdentity,
        parameters: dict,
    ) -> ActionExecutionResult:
        return ActionExecutionResult(
            status="unknown",
            error="fixture 执行器不能提供权威 reconcile 结论",
        )


@dataclass
class FakeDeployment:
    """fake Kubernetes API 中的最小 Deployment 状态。"""

    identity: TargetIdentity
    replicas: int = 3
    ready_replicas: int = 3
    healthy: bool = True
    restart_count: int = 0
    resource_version: int = 1


class FakeKubernetesApi:
    """只允许按 namespace/kind/name 管理的内存 Deployment API。"""

    def __init__(self) -> None:
        self._deployments: dict[tuple[str, str, str], FakeDeployment] = {}
        self._lock = RLock()
        self.failure_mode: str | None = None

    def register_deployment(
        self,
        identity: TargetIdentity,
        *,
        replicas: int = 3,
        ready_replicas: int | None = None,
        healthy: bool = True,
    ) -> None:
        if identity.kind != "Deployment":
            raise ValueError("fake API 仅支持 Deployment")
        if replicas < 1:
            raise ValueError("副本数必须为正数")
        ready = replicas if ready_replicas is None else ready_replicas
        if ready < 0 or ready > replicas:
            raise ValueError("ready 副本数必须位于 0..replicas")
        with self._lock:
            self._deployments[self._key(identity)] = FakeDeployment(
                identity=identity,
                replicas=replicas,
                ready_replicas=ready,
                healthy=healthy,
            )

    def set_failure_mode(self, mode: str | None) -> None:
        if mode not in {None, "timeout", "partial_ready", "unknown"}:
            raise ValueError("不支持的 fake API 失败模式")
        self.failure_mode = mode

    def get_deployment(self, identity: TargetIdentity) -> FakeDeployment:
        with self._lock:
            deployment = self._deployments.get(self._key(identity))
            if deployment is None:
                raise ActionExecutionError("目标 Deployment 不存在")
            if deployment.identity != identity:
                raise TargetIdentityMismatch("目标 UID/generation 已漂移")
            return self._copy(deployment)

    def get_current(self, namespace: str, kind: str, name: str) -> FakeDeployment:
        with self._lock:
            deployment = self._deployments.get((namespace, kind, name))
            if deployment is None:
                raise ActionExecutionError("目标 Deployment 不存在")
            return self._copy(deployment)

    def apply(
        self,
        runbook_ref: str,
        identity: TargetIdentity,
        parameters: dict,
    ) -> ActionExecutionResult:
        with self._lock:
            deployment = self._deployments.get(self._key(identity))
            if deployment is None:
                raise ActionExecutionError("目标 Deployment 不存在")
            if deployment.identity != identity:
                raise TargetIdentityMismatch("目标 UID/generation 已漂移")

            before = self._format(deployment)
            mode = self.failure_mode
            if mode == "timeout":
                return ActionExecutionResult(
                    status="failed",
                    after_state=before,
                    error="fake Kubernetes API 请求超时",
                )

            if runbook_ref == "restart_deployment@1":
                desired_replicas = deployment.replicas
                deployment.restart_count += 1
            elif runbook_ref == "scale_deployment@1":
                desired_replicas = parameters.get("replicas")
                if isinstance(desired_replicas, bool) or not isinstance(desired_replicas, int):
                    raise ActionExecutionError("副本数必须为整数")
                if not 1 <= desired_replicas <= 10:
                    raise ActionExecutionError("副本数必须位于 1..10")
                deployment.replicas = desired_replicas
            else:
                raise ActionExecutionError(f"fake API 不支持 Runbook: {runbook_ref}")

            deployment.identity = TargetIdentity(
                namespace=deployment.identity.namespace,
                kind=deployment.identity.kind,
                name=deployment.identity.name,
                uid=deployment.identity.uid,
                generation=deployment.identity.generation + 1,
            )
            deployment.resource_version += 1
            if mode == "partial_ready":
                deployment.ready_replicas = max(0, desired_replicas - 1)
                deployment.healthy = False
            else:
                deployment.ready_replicas = desired_replicas
                deployment.healthy = True

            after = self._format(deployment)
            if mode == "unknown":
                return ActionExecutionResult(
                    status="unknown",
                    after_state=after,
                    error="动作请求已发送但结果未知，需要协调",
                )
            if mode == "partial_ready":
                return ActionExecutionResult(
                    status="failed",
                    after_state=after,
                    error="Deployment 未达到期望 ready 副本数",
                )
            return ActionExecutionResult(
                status="succeeded",
                after_state=after,
                output=f"fake Kubernetes 已执行 {runbook_ref} on {identity.name}",
            )

    @staticmethod
    def _key(identity: TargetIdentity) -> tuple[str, str, str]:
        return identity.namespace, identity.kind, identity.name

    @staticmethod
    def _copy(deployment: FakeDeployment) -> FakeDeployment:
        return FakeDeployment(**deployment.__dict__)

    @staticmethod
    def _format(deployment: FakeDeployment) -> str:
        state = "healthy" if deployment.healthy else "degraded"
        return (
            f"{deployment.identity.name}: replicas={deployment.replicas}, "
            f"ready={deployment.ready_replicas}, status={state}, "
            f"uid={deployment.identity.uid}, generation={deployment.identity.generation}, "
            f"resource_version={deployment.resource_version}"
        )


class FakeKubernetesExecutor:
    """将 fake API 适配到 ActionExecutor。"""

    execution_mode = "fake-k8s"

    def __init__(self, api: FakeKubernetesApi) -> None:
        self.api = api

    def describe(self, target_identity: TargetIdentity) -> str:
        return self.api._format(self.api.get_deployment(target_identity))

    def execute(
        self,
        runbook_ref: str,
        target_identity: TargetIdentity,
        parameters: dict,
    ) -> ActionExecutionResult:
        return self.api.apply(runbook_ref, target_identity, parameters)

    def reconcile(
        self,
        runbook_ref: str,
        target_identity: TargetIdentity,
        parameters: dict,
    ) -> ActionExecutionResult:
        current = self.api.get_current(
            target_identity.namespace, target_identity.kind, target_identity.name
        )
        if current.identity.uid != target_identity.uid:
            return ActionExecutionResult(status="failed", error="目标 UID 已漂移")
        if current.identity.generation <= target_identity.generation:
            return ActionExecutionResult(
                status="unknown", error="尚未观察到预期的目标 generation 变化"
            )
        if runbook_ref == "scale_deployment@1" and current.replicas != parameters.get("replicas"):
            return ActionExecutionResult(status="failed", error="副本数未达到批准的目标")
        if not current.healthy or current.ready_replicas != current.replicas:
            return ActionExecutionResult(status="failed", error="Deployment 未达到健康 ready 状态")
        return ActionExecutionResult(
            status="succeeded",
            after_state=self.api._format(current),
            output=f"fake Kubernetes reconcile 确认 {runbook_ref} 已生效",
        )
