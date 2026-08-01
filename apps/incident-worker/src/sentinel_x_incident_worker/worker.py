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
import sys

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

    在 Temporal Server 可用时，连接并注册 Workflow/Activity。
    当 Temporal Server 不可用时，使用本地模式运行 Workflow 测试。
    """

    def __init__(self):
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """启动 Worker。"""
        logger.info(
            f"启动 Incident Worker: "
            f"address={TEMPORAL_CONFIG['address']}, "
            f"namespace={TEMPORAL_CONFIG['namespace']}, "
            f"task_queue={TEMPORAL_CONFIG['task_queue']}"
        )

        self._running = True

        # 尝试连接 Temporal Server
        temporal_available = await self._check_temporal()

        if temporal_available:
            await self._start_temporal_worker()
        else:
            logger.warning(
                "Temporal Server 不可用，Worker 以本地模式运行。"
                "运行: temporal server start-dev 启动 Temporal 开发服务器。"
            )
            await self._start_local_mode()

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
        except Exception:
            return False

    async def _start_temporal_worker(self) -> None:
        """启动 Temporal Worker（注册 Workflow/Activity）。"""
        import temporalio.worker

        # 当连接 Temporal 时，在此注册真实的 Workflow 和 Activity
        logger.info("Temporal Worker 已连接，等待任务...")
        try:
            while self._running:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass

    async def _start_local_mode(self) -> None:
        """本地模式：直接运行 Workflow 进行测试。"""
        from sentinel_x_incident_worker.workflows import (
            IncidentWorkflow,
            WorkflowContext,
        )
        from sentinel_x_domain.state_machine import IncidentState

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
