"""Tests for mahavishnu.pools.runpod_pool — RunPodPool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.pools.base import PoolConfig, PoolMetrics, PoolStatus
from mahavishnu.pools.runpod_pool import RunPodPool


def _make_pool_config(**overrides) -> PoolConfig:
    defaults: dict[str, object] = {
        "name": "test-runpod",
        "pool_type": "runpod",
        "min_workers": 1,
        "max_workers": 10,
    }
    defaults.update(overrides)
    return PoolConfig(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# RunPodPool.__init__
# ---------------------------------------------------------------------------


class TestRunPodPoolInit:
    def test_defaults(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        assert pool.config.pool_type == "runpod"
        assert pool._endpoint is None
        assert pool._tasks_completed == 0
        assert pool._tasks_failed == 0
        assert pool._task_durations == []
        assert pool._status == PoolStatus.PENDING

    def test_extra_config_parsed(self):
        cfg = PoolConfig(
            name="gpu-pool",
            pool_type="runpod",
            extra_config={
                "api_key": "rp-secret",
                "gpu_type": "NVIDIA_A100",
                "endpoint_name": "my-endpoint",
                "num_workers": 5,
                "dependencies": ["torch", "transformers"],
            },
        )
        pool = RunPodPool(config=cfg)
        assert pool._api_key == "rp-secret"
        assert pool._gpu_type == "NVIDIA_A100"
        assert pool._endpoint_name == "my-endpoint"
        assert pool._num_workers == 5
        assert pool._dependencies == ["torch", "transformers"]

    def test_default_gpu_type(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        assert pool._gpu_type == "NVIDIA_GEFORCE_RTX_4090"

    def test_inherits_from_base(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        assert pool.config is cfg
        assert "runpod" in pool.pool_id


# ---------------------------------------------------------------------------
# _build_endpoint
# ---------------------------------------------------------------------------


class TestBuildEndpoint:
    def test_raises_when_runpod_flash_not_available(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)

        with patch("mahavishnu.pools.runpod_pool.Endpoint", None):
            with pytest.raises(RuntimeError, match="runpod-flash"):
                pool._build_endpoint()

    def test_raises_on_unknown_gpu_type(self):
        cfg = PoolConfig(
            name="test",
            pool_type="runpod",
            extra_config={"gpu_type": "INVALID_GPU"},
        )
        pool = RunPodPool(config=cfg)

        with patch("mahavishnu.pools.runpod_pool.GpuType", MagicMock(INVALID_GPU=None)):
            with pytest.raises(ValueError, match="Unknown GpuType"):
                pool._build_endpoint()

    def test_build_endpoint_invocates_endpoint_decorator(self):
        cfg = _make_pool_config(
            extra_config={"gpu_type": "NVIDIA_GEFORCE_RTX_4090"},
        )
        pool = RunPodPool(config=cfg)

        # Track what arguments Endpoint was called with
        endpoint_calls: list[dict] = []
        captured_fn = None

        def mock_endpoint_decorator(*args, **kwargs):
            endpoint_calls.append({"args": args, "kwargs": kwargs})
            # Return a callable that, when invoked with a function, returns that function
            def decorator(fn):
                nonlocal captured_fn
                captured_fn = fn
                return fn
            return decorator

        mock_gpu = MagicMock()
        mock_gpu.NVIDIA_GEFORCE_RTX_4090 = "NVIDIA_GEFORCE_RTX_4090"

        with patch("mahavishnu.pools.runpod_pool.Endpoint", mock_endpoint_decorator):
            with patch("mahavishnu.pools.runpod_pool.GpuType", mock_gpu):
                pool._build_endpoint()

        assert len(endpoint_calls) == 1
        call_kwargs = endpoint_calls[0]["kwargs"]
        assert call_kwargs["name"] == "mahavishnu-worker"
        assert call_kwargs["gpu"] == "NVIDIA_GEFORCE_RTX_4090"
        assert call_kwargs["workers"] == 3
        assert call_kwargs["dependencies"] == []
        # The internal _run_task was captured
        assert captured_fn is not None


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestStart:
    @pytest.mark.asyncio
    async def test_start_success_sets_running(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)

        # Track Endpoint decorator calls
        endpoint_calls: list[dict] = []
        captured_fn = None

        def mock_endpoint_decorator(*args, **kwargs):
            endpoint_calls.append({"args": args, "kwargs": kwargs})
            def decorator(fn):
                nonlocal captured_fn
                captured_fn = fn
                return fn
            return decorator

        mock_gpu = MagicMock()
        mock_gpu.NVIDIA_GEFORCE_RTX_4090 = "NVIDIA_GEFORCE_RTX_4090"

        with patch("mahavishnu.pools.runpod_pool.Endpoint", mock_endpoint_decorator):
            with patch("mahavishnu.pools.runpod_pool.GpuType", mock_gpu):
                result = await pool.start()
                assert result == pool.pool_id
                assert pool._status == PoolStatus.RUNNING
                # The decorated _run_task is stored as _endpoint
                assert pool._endpoint is captured_fn

    @pytest.mark.asyncio
    async def test_start_sets_failed_on_exception(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)

        mock_gpu = MagicMock()
        mock_gpu.NVIDIA_GEFORCE_RTX_4090 = "NVIDIA_GEFORCE_RTX_4090"

        with patch(
            "mahavishnu.pools.runpod_pool.Endpoint",
            MagicMock(side_effect=RuntimeError("registration failed")),
        ):
            with patch("mahavishnu.pools.runpod_pool.GpuType", mock_gpu):
                with pytest.raises(RuntimeError, match="registration failed"):
                    await pool.start()
                assert pool._status == PoolStatus.FAILED


# ---------------------------------------------------------------------------
# execute_task()
# ---------------------------------------------------------------------------


class TestExecuteTask:
    @pytest.mark.asyncio
    async def test_not_started_returns_failed(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._endpoint = None
        pool._status = PoolStatus.PENDING

        result = await pool.execute_task({"prompt": "hello"})
        assert result["status"] == "failed"
        assert result["error"] == "Pool not started — call start() first"
        assert pool._tasks_failed == 0  # not counted as task failure

    @pytest.mark.asyncio
    async def test_success_tracks_completed(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING

        mock_endpoint = AsyncMock(return_value={"result": "hello world"})
        pool._endpoint = mock_endpoint

        result = await pool.execute_task({"prompt": "say hello"})
        assert result["status"] == "completed"
        assert result["output"] == {"result": "hello world"}
        assert result["pool_id"] == pool.pool_id
        assert "mahavishnu-worker" in result["worker_id"]
        assert pool._tasks_completed == 1
        assert len(pool._task_durations) == 1

    @pytest.mark.asyncio
    async def test_timeout_tracks_failed(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING

        pool._endpoint = AsyncMock(side_effect=TimeoutError("execution timeout"))

        result = await pool.execute_task({"prompt": "slow task"})
        assert result["status"] == "timeout"
        assert "execution timeout" in result["error"]
        assert pool._tasks_failed == 1
        assert pool._tasks_completed == 0

    @pytest.mark.asyncio
    async def test_exception_tracks_failed(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING

        pool._endpoint = AsyncMock(side_effect=RuntimeError("GPU out of memory"))

        result = await pool.execute_task({"prompt": "big model"})
        assert result["status"] == "failed"
        assert "GPU out of memory" in result["error"]
        assert pool._tasks_failed == 1

    @pytest.mark.asyncio
    async def test_result_stored_in_task_results(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING

        mock_endpoint = AsyncMock(return_value="output_data")
        pool._endpoint = mock_endpoint

        await pool.execute_task({"prompt": "test"})
        assert len(pool._task_results) == 1
        assert pool._task_results[0]["output"] == "output_data"
        assert pool._task_results[0]["status"] == "completed"


# ---------------------------------------------------------------------------
# execute_batch()
# ---------------------------------------------------------------------------


class TestExecuteBatch:
    @pytest.mark.asyncio
    async def test_batch_runs_all_tasks(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING

        pool._endpoint = AsyncMock(side_effect=[
            {"result": "r1"},
            {"result": "r2"},
            {"result": "r3"},
        ])

        results = await pool.execute_batch([{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}])
        assert len(results) == 3
        assert results["0"]["output"] == {"result": "r1"}
        assert results["1"]["output"] == {"result": "r2"}
        assert results["2"]["output"] == {"result": "r3"}

    @pytest.mark.asyncio
    async def test_batch_partial_failures(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING

        pool._endpoint = AsyncMock(side_effect=[
            {"result": "ok"},
            TimeoutError("timeout"),
            {"result": "done"},
        ])

        results = await pool.execute_batch([{}, {}, {}])
        assert results["0"]["status"] == "completed"
        assert results["1"]["status"] == "timeout"
        assert results["2"]["status"] == "completed"
        assert pool._tasks_completed == 2
        assert pool._tasks_failed == 1


# ---------------------------------------------------------------------------
# scale()
# ---------------------------------------------------------------------------


class TestScale:
    @pytest.mark.asyncio
    async def test_scale_is_noop(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        # Should not raise — Flash auto-scales
        await pool.scale(target_worker_count=100)


# ---------------------------------------------------------------------------
# health_check()
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_unhealthy_when_not_started(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._endpoint = None
        pool._status = PoolStatus.PENDING

        health = await pool.health_check()
        assert health["status"] == "unhealthy"
        assert health["reason"] == "endpoint not registered"

    @pytest.mark.asyncio
    async def test_unhealthy_when_endpoint_none_but_running(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._endpoint = None
        pool._status = PoolStatus.RUNNING

        health = await pool.health_check()
        assert health["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_healthy_when_running(self):
        cfg = _make_pool_config(
            extra_config={
                "gpu_type": "NVIDIA_A100",
                "num_workers": 5,
            },
        )
        pool = RunPodPool(config=cfg)
        pool._endpoint = MagicMock()
        pool._status = PoolStatus.RUNNING
        pool._tasks_completed = 10
        pool._tasks_failed = 2

        health = await pool.health_check()
        assert health["status"] == "healthy"
        assert health["gpu_type"] == "NVIDIA_A100"
        assert health["workers_configured"] == 5
        assert health["tasks_completed"] == 10
        assert health["tasks_failed"] == 2


# ---------------------------------------------------------------------------
# get_metrics()
# ---------------------------------------------------------------------------


class TestGetMetrics:
    @pytest.mark.asyncio
    async def test_metrics_reflect_task_stats(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING
        pool._tasks_completed = 5
        pool._tasks_failed = 1
        pool._task_durations = [1.0, 2.0, 3.0, 4.0, 5.0]

        metrics = await pool.get_metrics()
        assert isinstance(metrics, PoolMetrics)
        assert metrics.tasks_completed == 5
        assert metrics.tasks_failed == 1
        assert metrics.avg_task_duration == pytest.approx(3.0)
        assert metrics.total_workers == 3

    @pytest.mark.asyncio
    async def test_zero_duration_when_no_tasks(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING

        metrics = await pool.get_metrics()
        assert metrics.avg_task_duration == 0.0
        assert metrics.tasks_completed == 0

    @pytest.mark.asyncio
    async def test_active_workers_zero_when_not_running(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.STOPPED
        pool._num_workers = 5

        metrics = await pool.get_metrics()
        assert metrics.active_workers == 0


# ---------------------------------------------------------------------------
# collect_memory()
# ---------------------------------------------------------------------------


class TestCollectMemory:
    @pytest.mark.asyncio
    async def test_collect_memory_returns_items(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._task_results.append(
            {
                "worker_id": "wp-1",
                "output": "result A",
                "status": "completed",
                "timestamp": 1000.0,
            }
        )
        pool._task_results.append(
            {
                "worker_id": "wp-2",
                "output": "result B",
                "status": "failed",
                "timestamp": 1001.0,
            }
        )

        items = await pool.collect_memory()
        assert len(items) == 2
        assert items[0]["content"] == "result A"
        assert items[0]["metadata"]["pool_type"] == "runpod"
        assert items[0]["metadata"]["worker_id"] == "wp-1"
        assert items[1]["content"] == "result B"

    @pytest.mark.asyncio
    async def test_collect_memory_clears_results(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._task_results.append(
            {
                "worker_id": "wp-1",
                "output": "data",
                "status": "completed",
                "timestamp": 1000.0,
            }
        )

        await pool.collect_memory()
        assert len(pool._task_results) == 0

    @pytest.mark.asyncio
    async def test_collect_memory_empty_when_no_results(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)

        items = await pool.collect_memory()
        assert items == []


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_clears_endpoint_and_status(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._endpoint = MagicMock()
        pool._status = PoolStatus.RUNNING
        pool._task_results.append(
            {
                "worker_id": "wp-1",
                "output": "data",
                "status": "completed",
                "timestamp": 1000.0,
            }
        )

        await pool.stop()
        assert pool._endpoint is None
        assert pool._status == PoolStatus.STOPPED
        assert len(pool._task_results) == 0

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.STOPPED

        # Should not raise
        await pool.stop()
        assert pool._status == PoolStatus.STOPPED