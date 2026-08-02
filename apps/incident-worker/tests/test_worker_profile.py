"""Worker profile 的 fail-closed 行为。"""

from unittest.mock import AsyncMock

import pytest

from sentinel_x_incident_worker.worker import WorkerRunner


@pytest.mark.asyncio
async def test_light_profile_runs_only_local_fixture():
    runner = WorkerRunner()
    runner.profile = "light"
    runner._start_local_mode = AsyncMock()

    await runner.start()

    runner._start_local_mode.assert_awaited_once()


@pytest.mark.asyncio
async def test_full_profile_refuses_temporal_fallback():
    runner = WorkerRunner()
    runner.profile = "full"
    runner._check_temporal = AsyncMock(return_value=False)

    with pytest.raises(RuntimeError, match="禁止降级"):
        await runner.start()

