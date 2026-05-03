"""Unit tests for RunPodPool — Flash SDK is fully mocked."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.pools.base import PoolConfig, PoolStatus
from mahavishnu.pools.runpod_pool import RunPodPool


@pytest.fixture
def config():
    return PoolConfig(
        name="test-runpod",
        pool_type="runpod",
        extra_config={
            "api_key": "test-key",
            "gpu_type": "NVIDIA_GEFORCE_RTX_4090",
            "endpoint_name": "mahavishnu-test",
            "dependencies": ["torch"],
        },
    )


@pytest.fixture
def pool(config):
    return RunPodPool(config=config)


@pytest.mark.asyncio
async def test_start_returns_pool_id(pool):
    with patch("mahavishnu.pools.runpod_pool.Endpoint", return_value=MagicMock()):
        pool_id = await pool.start()
    assert pool_id == pool.pool_id
    assert pool._status == PoolStatus.RUNNING


@pytest.mark.asyncio
async def test_execute_task_success(pool):
    mock_endpoint = AsyncMock(return_value={"output": "result"})
    pool._endpoint = mock_endpoint
    pool._status = PoolStatus.RUNNING

    result = await pool.execute_task({"prompt": "analyze image", "category": "vision"})

    assert result["status"] == "completed"
    assert result["pool_id"] == pool.pool_id
    assert result["output"] == {"output": "result"}
    assert result["duration"] >= 0.0


@pytest.mark.asyncio
async def test_execute_task_failure(pool):
    mock_endpoint = AsyncMock(side_effect=RuntimeError("RunPod error"))
    pool._endpoint = mock_endpoint
    pool._status = PoolStatus.RUNNING

    result = await pool.execute_task({"prompt": "analyze image"})

    assert result["status"] == "failed"
    assert "RunPod error" in result["error"]


@pytest.mark.asyncio
async def test_execute_batch_runs_concurrently(pool):
    call_count = 0

    async def fake_execute(task):
        nonlocal call_count
        call_count += 1
        return {
            "status": "completed",
            "pool_id": pool.pool_id,
            "worker_id": "ep",
            "output": "ok",
            "error": None,
            "duration": 0.0,
        }

    pool.execute_task = fake_execute
    tasks = [{"prompt": f"task {i}"} for i in range(3)]
    results = await pool.execute_batch(tasks)

    assert len(results) == 3
    assert call_count == 3


@pytest.mark.asyncio
async def test_health_check_running(pool):
    pool._status = PoolStatus.RUNNING
    pool._endpoint = MagicMock()
    health = await pool.health_check()

    assert health["pool_id"] == pool.pool_id
    assert health["pool_type"] == "runpod"
    assert health["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_check_no_endpoint(pool):
    pool._status = PoolStatus.PENDING
    pool._endpoint = None
    health = await pool.health_check()

    assert health["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_scale_is_noop(pool):
    """Flash handles scaling; scale() should log and return without error."""
    pool._status = PoolStatus.RUNNING
    await pool.scale(5)  # No exception
    assert pool._status == PoolStatus.RUNNING


@pytest.mark.asyncio
async def test_collect_memory_returns_items(pool):
    import collections

    pool._task_results = collections.deque(
        [
            {
                "worker_id": "ep-1",
                "output": "result A",
                "status": "completed",
                "timestamp": time.time(),
            }
        ],
        maxlen=1000,
    )
    items = await pool.collect_memory()
    assert len(items) == 1
    assert items[0]["metadata"]["pool_type"] == "runpod"


@pytest.mark.asyncio
async def test_stop_clears_endpoint(pool):
    pool._endpoint = MagicMock()
    pool._status = PoolStatus.RUNNING
    await pool.stop()
    assert pool._status == PoolStatus.STOPPED
    assert pool._endpoint is None
