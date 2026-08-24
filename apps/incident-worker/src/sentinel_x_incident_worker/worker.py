"""
Worker 入口 — 连接 Temporal Server 并注册 Workflow 和 Activities。

启动方式：
    python -m sentinel_x_incident_worker.worker

环境变量：
    TEMPORAL_ADDRESS: Temporal Server 地址（默认 127.0.0.1:7233）
    TEMPORAL_NAMESPACE: Temporal 命名空间（默认 sentinel-local）
    TEMPORAL_TASK_QUEUE: Task Queue 名称（默认 sentinel-incidents）
"""

import asyncio
import logging
import os
import signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sentinel_x_incident_worker")


# Temporal Worker 配置（当 Temporal Server 可用时使用）
TEMPORAL_CONFIG = {
    "address": os.getenv("TEMPORAL_ADDRESS", "127.0.0.1:7233"),
    "namespace": os.getenv("TEMPORAL_NAMESPACE", "sentinel-local"),
    "task_queue": os.getenv("TEMPORAL_TASK_QUEUE", "sentinel-incidents"),
}


class WorkerRunner:
    """
    Worker 运行器。

    `light` profile 只运行本地 Workflow fixture。
    `full` profile 连接 Temporal Server 并注册 durable Workflow/Activities。
    """

    def __init__(self):
        self._running = False
        self._shutdown_event = asyncio.Event()
        self.profile = os.getenv("SENTINEL_PROFILE", "light")
        self._worker = None
        self._client = None

    async def start(self) -> None:
        """启动 Worker。"""
        logger.info(
            f"启动 Incident Worker: "
            f"address={TEMPORAL_CONFIG['address']}, "
            f"namespace={TEMPORAL_CONFIG['namespace']}, "
            f"task_queue={TEMPORAL_CONFIG['task_queue']}"
        )

        self._running = True

        if self.profile == "light":
            logger.warning("light profile：运行本地 Workflow fixture，不连接 Temporal Server。")
            await self._start_local_mode()
            return

        if self.profile != "full":
            raise RuntimeError(f"不支持的 SENTINEL_PROFILE: {self.profile}")

        if not await self._check_temporal():
            raise RuntimeError("full profile 需要可用的 Temporal Server；禁止降级为本地 fixture")
        await self._start_temporal_worker()

    async def _check_temporal(self) -> bool:
        """检查 Temporal Server 是否可用。"""
        try:
            import temporalio.service
            client = await temporalio.service.connect(
                temporalio.service.ServiceConfig(
                    target_host=TEMPORAL_CONFIG["address"],
                )
            )
            # 尝试获取 server 信息
            await client.system.get_server_info()
            return True
        except Exception:  # noqa: BLE001 - Temporal SDK 连接错误类型不稳定，必须 fail closed
            return False

    async def _start_temporal_worker(self) -> None:
        """连接 Temporal 并运行真实 Worker。"""
        from temporalio.client import Client

        from sentinel_x_incident_worker.temporal_runtime import build_temporal_worker

        self._client = await Client.connect(
            TEMPORAL_CONFIG["address"],
            namespace=TEMPORAL_CONFIG["namespace"],
        )
        self._worker = build_temporal_worker(
            self._client,
            task_queue=TEMPORAL_CONFIG["task_queue"],
        )
        logger.info(
            "Temporal Worker 已注册: workflow=SentinelIncidentWorkflow, "
            "activities=3, task_queue=%s",
            TEMPORAL_CONFIG["task_queue"],
        )
        await self._worker.run()

    async def _start_local_mode(self) -> None:
        """本地模式：直接运行 Workflow 进行测试。"""
        from sentinel_x_domain.state_machine import IncidentState

        from sentinel_x_incident_worker.workflows import (
            IncidentWorkflow,
            WorkflowContext,
        )

        logger.info("本地模式：运行测试 Workflow...")

        state = IncidentState()
        ctx = WorkflowContext(
            incident_id=state.id,
            state=state,
        )
        wf = IncidentWorkflow(ctx)
        result = await wf.execute()

        logger.info(f"测试 Workflow 完成: status={result.status.value}")
        logger.info(f"状态历史: {' → '.join([e for e in result.history])}")

    async def shutdown(self) -> None:
        """优雅关闭。"""
        logger.info("Worker 正在关闭...")
        self._running = False
        if self._worker is not None:
            await self._worker.shutdown()
        self._shutdown_event.set()


async def main():
    runner = WorkerRunner()

    # 注册信号处理
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(runner.shutdown()))
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            pass

    await runner.start()


if __name__ == "__main__":
    asyncio.run(main())
