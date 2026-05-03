"""Integration smoke test for RunPodPool.

Skipped unless RUNPOD_API_KEY is set in the environment.
Run manually:
    RUNPOD_API_KEY=<key> pytest tests/integration/pools/test_runpod_pool_smoke.py -v -s
"""

import os

import pytest

from mahavishnu.pools.base import PoolConfig, PoolStatus
from mahavishnu.pools.runpod_pool import RunPodPool

pytestmark = pytest.mark.skipif(
    not os.getenv("RUNPOD_API_KEY"),
    reason="RUNPOD_API_KEY not set — skipping RunPod integration test",
)


@pytest.fixture
async def live_pool():
    config = PoolConfig(
        name="smoke-test-pool",
        pool_type="runpod",
        extra_config={
            "api_key": os.environ["RUNPOD_API_KEY"],
            "gpu_type": "NVIDIA_GEFORCE_RTX_4090",
            "endpoint_name": "mahavishnu-smoke",
            "dependencies": [],
            "num_workers": 1,
        },
    )
    pool = RunPodPool(config=config)
    await pool.start()
    yield pool
    await pool.stop()


@pytest.mark.asyncio
async def test_live_execute_task(live_pool):
    result = await live_pool.execute_task(
        {"prompt": "hello from smoke test", "category": "general"}
    )
    assert result["status"] == "completed"
    assert result["output"] is not None
    assert live_pool._status == PoolStatus.RUNNING


@pytest.mark.asyncio
async def test_live_health_check(live_pool):
    health = await live_pool.health_check()
    assert health["status"] == "healthy"
    assert health["pool_type"] == "runpod"
