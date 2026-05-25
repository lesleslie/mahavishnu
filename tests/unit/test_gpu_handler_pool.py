"""Unit tests for GpuHandlerPool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.pools.gpu_handler_pool import GpuHandlerPool, GPU_TASK_CATEGORIES
from mahavishnu.pools.base import PoolConfig


class TestGpuTaskCategories:
    """Tests for GPU_TASK_CATEGORIES frozenset."""

    def test_gpu_task_categories_contains_correct_values(self) -> None:
        """Verify GPU_TASK_CATEGORIES has exactly vision, ml_inference, embedding."""
        assert GPU_TASK_CATEGORIES == frozenset({"vision", "ml_inference", "embedding"})

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


class TestBuildEndpoint:
    """Tests for _build_endpoint() method."""

    @pytest.fixture
    def pool_config(self) -> PoolConfig:
        return PoolConfig(
            name="test-gpu-pool",
            pool_type="runpod",
            extra_config={
                "api_key": "test-key",
                "gpu_type": "NVIDIA_GEFORCE_RTX_4090",
                "endpoint_name": "test-endpoint",
                "dependencies": ["torch"],
                "num_workers": 2,
            },
        )

    def test_raises_runtime_error_when_runpod_flash_not_installed(
        self, pool_config: PoolConfig
    ) -> None:
        """_build_endpoint() raises RuntimeError when runpod-flash is not available."""
        pool = GpuHandlerPool(pool_config)

        with patch("mahavishnu.pools.gpu_handler_pool.Endpoint", None):
            with pytest.raises(RuntimeError, match="runpod-flash"):
                pool._build_endpoint()

    def test_raises_value_error_for_unknown_gpu_type(self, pool_config: PoolConfig) -> None:
        """_build_endpoint() raises ValueError for unknown GpuType."""
        pool = GpuHandlerPool(pool_config)

        # Create a mock GpuType where getattr returns None for unknown GPU
        mock_gpu_type = MagicMock()
        # Make iteration return empty so [g.name for g in GpuType] returns []
        mock_gpu_type.__iter__ = lambda self: iter([])
        # Make getattr return None for the specific GPU type we're testing
        type(mock_gpu_type).__getattr__ = lambda cls, name: None if name == "UNKNOWN_GPU" else getattr(super(type(mock_gpu_type), cls), name, None)

        with patch("mahavishnu.pools.gpu_handler_pool.Endpoint", MagicMock):
            with patch("mahavishnu.pools.gpu_handler_pool.GpuType", mock_gpu_type):
                pool._gpu_type = "UNKNOWN_GPU"
                with pytest.raises(ValueError, match="Unknown GpuType"):
                    pool._build_endpoint()

    def test_build_endpoint_returns_callable_for_valid_gpu_type(
        self, pool_config: PoolConfig
    ) -> None:
        """_build_endpoint() returns a handler function for valid GPU type."""
        pool = GpuHandlerPool(pool_config)

        mock_gpu_type = MagicMock()
        # Set up a valid GPU type attribute
        mock_gpu_type.NVIDIA_GEFORCE_RTX_4090 = "RTX_4090_GPU"
        mock_gpu_type.__iter__ = lambda self: iter([mock_gpu_type.NVIDIA_GEFORCE_RTX_4090])

        # The @Endpoint decorator is a function that takes kwargs and returns a decorator
        # that wraps a function. We need to simulate this behavior.
        def mock_endpoint_decorator(*args, **kwargs):
            def inner(func):
                return func
            return inner

        mock_endpoint = MagicMock(side_effect=mock_endpoint_decorator)

        with patch("mahavishnu.pools.gpu_handler_pool.Endpoint", mock_endpoint):
            with patch("mahavishnu.pools.gpu_handler_pool.GpuType", mock_gpu_type):
                handler = pool._build_endpoint()
                assert callable(handler)


class TestExecuteTask:
    """Tests for execute_task() category routing."""

    @pytest.fixture
    def pool_config(self) -> PoolConfig:
        return PoolConfig(
            name="test-gpu-pool",
            pool_type="runpod",
            extra_config={
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

        This tests the early-return path for known valid categories.
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
        """execute_task() with empty string category falls through to parent.

        The check is: if category and category not in GPU_TASK_CATEGORIES
        Empty string is falsy, so it passes the check and falls through to super().
        """
        pool = GpuHandlerPool(pool_config)

        # Empty string category - should fall through to super
        task = {"category": "", "prompt": "test"}

        result = await pool.execute_task(task)

        # Empty string is falsy, so no rejection - falls through to super()
        # Will fail because endpoint not set, but NOT with "rejected" status
        assert result.get("status") != "rejected", (
            f"Empty category should not be rejected but got: {result}"
        )

    async def test_missing_category_key_is_accepted(self, pool_config: PoolConfig) -> None:
        """execute_task() with no 'category' key falls through to parent.

        task.get("category", "") returns "" when key is absent, which is falsy,
        so rejection check is skipped and super().execute_task() is called.
        """
        pool = GpuHandlerPool(pool_config)

        # Task without 'category' key
        task = {"prompt": "test task"}

        result = await pool.execute_task(task)

        # Missing category should not trigger rejection
        assert result.get("status") != "rejected"

    async def test_rejection_includes_sorted_gpu_categories(
        self, pool_config: PoolConfig
    ) -> None:
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
                "api_key": "test-key",
                "gpu_type": "NVIDIA_GEFORCE_RTX_4090",
                "endpoint_name": "test-endpoint",
                "dependencies": ["torch"],
                "num_workers": 2,
            },
        )

    async def test_valid_category_reaches_endpoint(self, pool_config: PoolConfig) -> None:
        """Valid category delegates to parent which calls the endpoint."""
        pool = GpuHandlerPool(pool_config)

        # Mock the endpoint
        mock_endpoint = AsyncMock(return_value={"category": "vision", "result": "ok"})
        pool._endpoint = mock_endpoint
        # Set pool to running state
        pool._status = MagicMock()

        # Call with valid category
        task = {"category": "vision", "prompt": "describe this"}
        result = await pool.execute_task(task)

        # Should complete successfully
        assert result["status"] == "completed"
        assert result["output"] == {"category": "vision", "result": "ok"}
        mock_endpoint.assert_called_once_with(task)

    async def test_ml_inference_category_reaches_endpoint(self, pool_config: PoolConfig) -> None:
        """ml_inference category delegates to parent which calls the endpoint."""
        pool = GpuHandlerPool(pool_config)

        mock_endpoint = AsyncMock(return_value={"category": "ml_inference", "result": "model output"})
        pool._endpoint = mock_endpoint
        pool._status = MagicMock()

        task = {"category": "ml_inference", "prompt": "run inference"}
        result = await pool.execute_task(task)

        assert result["status"] == "completed"
        mock_endpoint.assert_called_once()

    async def test_embedding_category_reaches_endpoint(self, pool_config: PoolConfig) -> None:
        """embedding category delegates to parent which calls the endpoint."""
        pool = GpuHandlerPool(pool_config)

        mock_endpoint = AsyncMock(return_value={"category": "embedding", "result": [0.1, 0.2]})
        pool._endpoint = mock_endpoint
        pool._status = MagicMock()

        task = {"category": "embedding", "text": "hello world"}
        result = await pool.execute_task(task)

        assert result["status"] == "completed"
        mock_endpoint.assert_called_once()
