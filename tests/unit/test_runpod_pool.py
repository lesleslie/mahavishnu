"""Tests for mahavishnu.pools.runpod_pool — RunPodPool (runpod SDK 2.0)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.pools.base import PoolConfig, PoolMetrics, PoolStatus
from mahavishnu.pools.runpod_pool import RunPodPool


def _make_pool_config(**overrides) -> PoolConfig:
    """Build a PoolConfig with a valid ``endpoint_id`` (required by the pool)."""
    defaults: dict[str, object] = {
        "name": "test-runpod",
        "pool_type": "runpod",
        "min_workers": 1,
        "max_workers": 10,
        "extra_config": {"endpoint_id": "ep-test-1234"},
    }
    defaults.update(overrides)
    return PoolConfig(**defaults)  # type: ignore[arg-type]


def _fake_run_request(status_value: str = "COMPLETED", output_value: object = None, job_id: str = "job-1"):
    """Return a MagicMock shaped like the runpod SDK 2.0 RunRequest handle.

    The handle exposes ``.id`` / ``.job_id`` (job uuid), ``.status()`` (returns
    "IN_QUEUE" / "IN_PROGRESS" / "COMPLETED" / "FAILED"), and ``.output()``
    (returns the result dict; blocks until completion). The pool only
    touches these three.
    """
    req = MagicMock()
    req.id = job_id
    req.job_id = job_id
    req.status.return_value = status_value
    req.output.return_value = output_value
    return req


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
        assert pool._endpoint_id == "ep-test-1234"

    def test_extra_config_parsed(self):
        cfg = PoolConfig(
            name="gpu-pool",
            pool_type="runpod",
            extra_config={
                "endpoint_id": "ep-real",
                "api_key": "rp-secret",
                "gpu_type": "NVIDIA_A100",
                "endpoint_name": "my-endpoint",
                "num_workers": 5,
                "dependencies": ["torch", "transformers"],
            },
        )
        pool = RunPodPool(config=cfg)
        assert pool._endpoint_id == "ep-real"
        assert pool._api_key == "rp-secret"
        assert pool._gpu_type == "NVIDIA_A100"
        assert pool._endpoint_name == "my-endpoint"
        assert pool._num_workers == 5
        assert pool._dependencies == ["torch", "transformers"]

    def test_inherits_from_base(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        assert pool.config is cfg
        assert "runpod" in pool.pool_id


# ---------------------------------------------------------------------------
# endpoint_id requirement + SDK presence
# ---------------------------------------------------------------------------


class TestRequiresEndpointId:
    def test_raises_when_endpoint_id_missing(self):
        cfg = PoolConfig(
            name="no-id",
            pool_type="runpod",
            extra_config={"gpu_type": "NVIDIA_A100"},  # endpoint_id absent
        )
        with pytest.raises(ValueError, match="endpoint_id"):
            RunPodPool(config=cfg)


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestStart:
    @pytest.mark.asyncio
    async def test_start_constructs_runpod_endpoint_client(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)

        with patch("mahavishnu.pools.runpod_pool.runpod") as mock_runpod_mod:
            fake_endpoint = MagicMock(name="endpoint-client")
            mock_runpod_mod.Endpoint.return_value = fake_endpoint

            result = await pool.start()

        assert result == pool.pool_id
        assert pool._status == PoolStatus.RUNNING
        assert pool._endpoint is fake_endpoint
        # The id was passed through to the SDK's Endpoint constructor.
        mock_runpod_mod.Endpoint.assert_called_once_with("ep-test-1234")

    @pytest.mark.asyncio
    async def test_start_sets_failed_on_exception(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)

        with patch(
            "mahavishnu.pools.runpod_pool.runpod",
            MagicMock(Endpoint=MagicMock(side_effect=RuntimeError("auth failed"))),
        ):
            with pytest.raises(RuntimeError, match="auth failed"):
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

        req = _fake_run_request(
            status_value="COMPLETED",
            output_value={"result": "hello world"},
            job_id="job-uuid-1",
        )
        # The pool uses ``asyncio.to_thread`` to run the dispatch, but
        # internally it calls ``endpoint.run(payload)`` synchronously.
        endpoint_mock = MagicMock()
        endpoint_mock.run = MagicMock(return_value=req)
        pool._endpoint = endpoint_mock

        result = await pool.execute_task({"prompt": "say hello"})
        assert result["status"] == "completed"
        assert result["output"] == {"result": "hello world"}
        assert result["pool_id"] == pool.pool_id
        # worker_id is "endpoint_id-timestamp" — the runpod job id is
        # only accessible from the run_request envelope, not surfaced
        # on the worker_id surface.
        assert "ep-test-1234" in result["worker_id"]
        assert pool._tasks_completed == 1
        assert len(pool._task_durations) == 1
        endpoint_mock.run.assert_called_once_with({"prompt": "say hello"})

    @pytest.mark.asyncio
    async def test_endpoint_in_progress_maps_to_pool_status(self):
        # ``IN_PROGRESS`` shouldn't appear in practice (output() blocks
        # until completion), but the pool's mapping logic handles it
        # gracefully rather than crashing.
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING
        req = _fake_run_request(status_value="IN_PROGRESS", output_value=None)
        endpoint_mock = MagicMock(run=MagicMock(return_value=req))
        pool._endpoint = endpoint_mock

        result = await pool.execute_task({"prompt": "x"})
        assert result["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_endpoint_failed_maps_to_pool_failed(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING
        req = _fake_run_request(
            status_value="FAILED",
            output_value={"error": "out of memory"},
        )
        endpoint_mock = MagicMock(run=MagicMock(return_value=req))
        pool._endpoint = endpoint_mock

        result = await pool.execute_task({"prompt": "big"})
        assert result["status"] == "failed"
        assert result["output"] == {"error": "out of memory"}

    @pytest.mark.asyncio
    async def test_timeout_tracks_failed(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING

        endpoint_mock = MagicMock(run=MagicMock(side_effect=TimeoutError("execution timeout")))
        pool._endpoint = endpoint_mock

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

        endpoint_mock = MagicMock(run=MagicMock(side_effect=RuntimeError("GPU out of memory")))
        pool._endpoint = endpoint_mock

        result = await pool.execute_task({"prompt": "big model"})
        assert result["status"] == "failed"
        assert "GPU out of memory" in result["error"]
        assert pool._tasks_failed == 1

    @pytest.mark.asyncio
    async def test_result_stored_in_task_results(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING

        req = _fake_run_request(status_value="COMPLETED", output_value="output_data")
        endpoint_mock = MagicMock(run=MagicMock(return_value=req))
        pool._endpoint = endpoint_mock

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

        # ``asyncio.to_thread`` schedules each task on the default
        # executor; completion order is not guaranteed to match
        # submission order. Use a callable side_effect that resolves by
        # the *task payload*, which is preserved per dispatch.
        def by_prompt(payload: dict[str, object]) -> object:
            prompt = payload.get("prompt", "")
            return _fake_run_request(
                status_value="COMPLETED",
                output_value={"result": {"a": "r1", "b": "r2", "c": "r3"}.get(prompt, "")},
            )

        endpoint_mock = MagicMock(run=MagicMock(side_effect=by_prompt))
        pool._endpoint = endpoint_mock

        results = await pool.execute_batch(
            [{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}]
        )
        assert len(results) == 3
        # asyncio.gather preserves input order in the returned list,
        # so index → submission order.
        assert results["0"]["output"] == {"result": "r1"}
        assert results["1"]["output"] == {"result": "r2"}
        assert results["2"]["output"] == {"result": "r3"}

    @pytest.mark.asyncio
    async def test_batch_partial_failures(self):
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._status = PoolStatus.RUNNING

        # Second-payload trips a timeout; the other two complete.
        call_index = {"n": 0}

        def by_index(payload: dict[str, object]) -> object:
            call_index["n"] += 1
            if call_index["n"] == 2:
                raise TimeoutError("timeout")
            return _fake_run_request(status_value="COMPLETED", output_value={"result": "ok"})

        endpoint_mock = MagicMock(run=MagicMock(side_effect=by_index))
        pool._endpoint = endpoint_mock

        results = await pool.execute_batch([{}, {}, {}])
        statuses = sorted(r["status"] for r in results.values())
        assert statuses == ["completed", "completed", "timeout"]
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
        # Should not raise — the serverless endpoint scales itself.
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
        assert health["endpoint_id"] == "ep-test-1234"
        assert health["reason"] == "endpoint client not constructed"

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
        cfg = _make_pool_config()
        pool = RunPodPool(config=cfg)
        pool._endpoint = MagicMock()
        pool._status = PoolStatus.RUNNING
        pool._tasks_completed = 10
        pool._tasks_failed = 2

        health = await pool.health_check()
        assert health["status"] == "healthy"
        assert health["endpoint_id"] == "ep-test-1234"
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
        assert metrics.total_workers == 3  # default _num_workers

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
