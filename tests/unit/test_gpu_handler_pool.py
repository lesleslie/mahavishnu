"""Unit tests for GpuHandlerPool."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mahavishnu.pools.base import PoolConfig
from mahavishnu.pools.gpu_handler_pool import GPU_TASK_CATEGORIES, GpuHandlerPool


def _fake_run_request(status_value: str = "COMPLETED", output_value: object = None, job_id: str = "job-1"):
    """RunRequest-shaped fake (matches the runpod SDK 2.0 contract)."""
    req = MagicMock()
    req.id = job_id
    req.job_id = job_id
    req.status.return_value = status_value
    req.output.return_value = output_value
    return req


class TestGpuTaskCategories:
    """Tests for GPU_TASK_CATEGORIES frozenset."""

    def test_gpu_task_categories_contains_correct_values(self) -> None:
        """Verify GPU_TASK_CATEGORIES has exactly vision, ml_inference, embedding."""
        assert frozenset({"vision", "ml_inference", "embedding"}) == GPU_TASK_CATEGORIES

    def test_gpu_task_categories_is_frozenset(self) -> None:
        """Verify GPU_TASK_CATEGORIES is immutable."""
        assert isinstance(GPU_TASK_CATEGORIES, frozenset)


class TestGpuHandlerPoolInit:
    """Tests for GpuHandlerPool initialization."""

    @pytest.fixture
    def pool_config(self) -> PoolConfig:
        return PoolConfig(
            name="test-gpu-pool",
            pool_type="runpod",
            extra_config={
                # ``endpoint_id`` is required by the post-migration RunPodPool
                # constructor; the pre-migration test predates that constraint.
                "endpoint_id": "ep-test-gpu-handler",
                "api_key": "test-key",
                "gpu_type": "NVIDIA_GEFORCE_RTX_4090",
                "endpoint_name": "test-endpoint",
                "dependencies": ["torch"],
                "num_workers": 2,
            },
        )

    def test_inherits_from_runpod_pool(self, pool_config: PoolConfig) -> None:
        """Verify GpuHandlerPool is a subclass of RunPodPool."""
        from mahavishnu.pools.runpod_pool import RunPodPool

        pool = GpuHandlerPool(pool_config)
        assert isinstance(pool, RunPodPool)


class TestExecuteTask:
    """Tests for execute_task() category routing."""

    @pytest.fixture
    def pool_config(self) -> PoolConfig:
        return PoolConfig(
            name="test-gpu-pool",
            pool_type="runpod",
            extra_config={
                "endpoint_id": "ep-test-execute",
                "api_key": "test-key",
                "gpu_type": "NVIDIA_GEFORCE_RTX_4090",
                "endpoint_name": "test-endpoint",
                "dependencies": ["torch"],
                "num_workers": 2,
            },
        )

    async def test_rejects_unknown_category_with_rejected_status(
        self, pool_config: PoolConfig
    ) -> None:
        """execute_task() rejects unknown categories with status 'rejected'."""
        pool = GpuHandlerPool(pool_config)

        result = await pool.execute_task({"category": "text", "prompt": "test"})

        assert result["status"] == "rejected"
        assert result["worker_id"] == "none"
        assert result["output"] is None
        assert "text" in result["error"]
        assert "GpuHandlerPool only handles" in result["error"]

    async def test_rejects_reasoning_category(self, pool_config: PoolConfig) -> None:
        """execute_task() rejects 'reasoning' category (not in GPU_TASK_CATEGORIES)."""
        pool = GpuHandlerPool(pool_config)

        result = await pool.execute_task({"category": "reasoning", "prompt": "think"})

        assert result["status"] == "rejected"
        assert result["error"] is not None
        assert "reasoning" in result["error"]

    async def test_rejects_swarm_category(self, pool_config: PoolConfig) -> None:
        """execute_task() rejects 'swarm' category (not in GPU_TASK_CATEGORIES)."""
        pool = GpuHandlerPool(pool_config)

        result = await pool.execute_task({"category": "swarm", "prompt": "test"})

        assert result["status"] == "rejected"
        assert "swarm" in result["error"]

    @pytest.mark.parametrize(
        "category",
        ["vision", "ml_inference", "embedding"],
    )
    async def test_accepts_valid_gpu_categories_no_rejection(
        self, pool_config: PoolConfig, category: str
    ) -> None:
        """execute_task() accepts valid GPU categories without rejection.

        The category check is: if category and category not in GPU_TASK_CATEGORIES
        For valid categories, we should NOT see "rejected" status.
        """
        pool = GpuHandlerPool(pool_config)

        # Task with valid category - should NOT be rejected
        task = {"category": category, "prompt": "test"}

        # Call execute_task and verify it doesn't reject
        result = await pool.execute_task(task)

        # If valid, should NOT be rejected. Since we don't have endpoint started,
        # it will fail in parent, but not with "rejected" status (that happens before super())
        assert result.get("status") != "rejected", (
            f"Category '{category}' should be accepted but was rejected: {result}"
        )

    async def test_empty_category_key_is_accepted(self, pool_config: PoolConfig) -> None:
        """execute_task() with empty string category falls through to parent."""
        pool = GpuHandlerPool(pool_config)

        task = {"category": "", "prompt": "test"}

        result = await pool.execute_task(task)

        # Empty string is falsy, so no rejection - falls through to super()
        assert result.get("status") != "rejected", (
            f"Empty category should not be rejected but got: {result}"
        )

    async def test_missing_category_key_is_accepted(self, pool_config: PoolConfig) -> None:
        """execute_task() with no 'category' key falls through to parent."""
        pool = GpuHandlerPool(pool_config)

        task = {"prompt": "test task"}

        result = await pool.execute_task(task)

        # Missing category should not trigger rejection
        assert result.get("status") != "rejected"

    async def test_rejection_includes_sorted_gpu_categories(self, pool_config: PoolConfig) -> None:
        """Rejected error message includes all valid GPU categories."""
        pool = GpuHandlerPool(pool_config)

        result = await pool.execute_task({"category": "bad_category", "prompt": "test"})

        error_msg = result["error"]
        # Should mention all valid categories
        assert "embedding" in error_msg
        assert "ml_inference" in error_msg
        assert "vision" in error_msg

    async def test_rejection_return_format(self, pool_config: PoolConfig) -> None:
        """Verify rejection response has all required fields."""
        pool = GpuHandlerPool(pool_config)

        result = await pool.execute_task({"category": "bad_category", "prompt": "test"})

        # Check all required keys are present
        assert "pool_id" in result
        assert "worker_id" in result
        assert "status" in result
        assert "output" in result
        assert "error" in result
        assert "duration" in result

        # Check specific values
        assert result["pool_id"] == pool.pool_id
        assert result["worker_id"] == "none"
        assert result["status"] == "rejected"
        assert result["output"] is None
        assert result["duration"] == 0.0

    async def test_valid_category_without_endpoint_set_fails_but_not_rejected(
        self, pool_config: PoolConfig
    ) -> None:
        """Valid category reaches parent but fails because endpoint not started.

        This confirms that valid categories pass through to super().execute_task(),
        even though the call fails because pool was not started.
        """
        pool = GpuHandlerPool(pool_config)

        # Valid category - should pass through to parent
        task = {"category": "vision", "prompt": "test"}
        result = await pool.execute_task(task)

        # Should NOT be "rejected" (which happens in pre-routing before super)
        # Should be "failed" because endpoint is None (pool not started)
        assert result.get("status") == "failed", (
            f"Valid category should reach parent and fail with 'failed', got: {result.get('status')}"
        )
        assert result.get("error") == "Pool not started — call start() first"


class TestExecuteTaskIntegration:
    """Integration-style tests for execute_task with mocked endpoint."""

    @pytest.fixture
    def pool_config(self) -> PoolConfig:
        return PoolConfig(
            name="test-gpu-pool",
            pool_type="runpod",
            extra_config={
                "endpoint_id": "ep-test-integration",
                "api_key": "test-key",
                "gpu_type": "NVIDIA_GEFORCE_RTX_4090",
                "endpoint_name": "test-endpoint",
                "dependencies": ["torch"],
                "num_workers": 2,
            },
        )

    async def test_valid_category_reaches_endpoint(
        self, pool_config: PoolConfig
    ) -> None:
        """Valid category delegates to parent which calls the endpoint.

        Post-migration: ``pool._endpoint`` is the ``runpod.Endpoint``
        client handle, NOT an awaitable. The pool wraps ``endpoint.run``
        in ``asyncio.to_thread``; we mock ``endpoint.run`` to return a
        RunRequest-shaped fake.
        """
        pool = GpuHandlerPool(pool_config)

        req = _fake_run_request(
            status_value="COMPLETED",
            output_value={"category": "vision", "result": "ok"},
            job_id="job-vision-1",
        )
        endpoint_mock = MagicMock()
        endpoint_mock.run = MagicMock(return_value=req)
        pool._endpoint = endpoint_mock
        pool._status = MagicMock()

        task = {"category": "vision", "prompt": "describe this"}
        result = await pool.execute_task(task)

        assert result["status"] == "completed"
        assert result["output"] == {"category": "vision", "result": "ok"}
        endpoint_mock.run.assert_called_once_with(task)

    async def test_ml_inference_category_reaches_endpoint(
        self, pool_config: PoolConfig
    ) -> None:
        """ml_inference category delegates to parent which calls the endpoint."""
        pool = GpuHandlerPool(pool_config)

        req = _fake_run_request(
            status_value="COMPLETED",
            output_value={"category": "ml_inference", "result": "model output"},
        )
        endpoint_mock = MagicMock(run=MagicMock(return_value=req))
        pool._endpoint = endpoint_mock
        pool._status = MagicMock()

        task = {"category": "ml_inference", "prompt": "run inference"}
        result = await pool.execute_task(task)

        assert result["status"] == "completed"
        endpoint_mock.run.assert_called_once()

    async def test_embedding_category_reaches_endpoint(
        self, pool_config: PoolConfig
    ) -> None:
        """embedding category delegates to parent which calls the endpoint."""
        pool = GpuHandlerPool(pool_config)

        req = _fake_run_request(
            status_value="COMPLETED",
            output_value={"category": "embedding", "result": [0.1, 0.2]},
        )
        endpoint_mock = MagicMock(run=MagicMock(return_value=req))
        pool._endpoint = endpoint_mock
        pool._status = MagicMock()

        task = {"category": "embedding", "text": "hello world"}
        result = await pool.execute_task(task)

        assert result["status"] == "completed"
        endpoint_mock.run.assert_called_once()
