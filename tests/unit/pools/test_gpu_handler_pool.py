"""Integration smoke tests for GpuHandlerPool and category-aware routing.

The runpod-flash SDK is fully mocked — no real GPU hardware required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.pools.base import PoolConfig, PoolStatus
from mahavishnu.pools.gpu_handler_pool import GPU_TASK_CATEGORIES, GpuHandlerPool
from mahavishnu.workers.task_router import TaskCategory


@pytest.fixture
def gpu_config():
    return PoolConfig(
        name="test-gpu",
        pool_type="runpod",
        extra_config={
            "api_key": "test-key",
            "gpu_type": "NVIDIA_GEFORCE_RTX_4090",
            "endpoint_name": "mahavishnu-gpu-test",
            "dependencies": ["torch", "Pillow"],
        },
    )


@pytest.fixture
def mock_endpoint_factory():
    """Return a factory that produces a mock Flash @Endpoint callable."""

    def _factory(handler_fn):
        async def _async_endpoint(payload):
            return handler_fn(payload)

        return _async_endpoint

    return _factory


class TestGpuHandlerPoolCategories:
    def test_gpu_task_categories_contains_vision_and_ml_inference(self):
        assert "vision" in GPU_TASK_CATEGORIES
        assert "ml_inference" in GPU_TASK_CATEGORIES
        assert "embedding" in GPU_TASK_CATEGORIES

    def test_ml_inference_in_task_category_enum(self):
        assert TaskCategory.ML_INFERENCE == "ml_inference"

    def test_vision_in_task_category_enum(self):
        assert TaskCategory.VISION == "vision"


class TestGpuHandlerPoolStart:
    def test_start_fails_without_sdk(self, gpu_config):
        """GpuHandlerPool raises RuntimeError when runpod-flash is not installed."""
        pool = GpuHandlerPool(config=gpu_config)
        with patch("mahavishnu.pools.gpu_handler_pool.Endpoint", None):
            with pytest.raises(RuntimeError, match="runpod-flash"):
                pool._build_endpoint()

    @pytest.mark.asyncio
    async def test_start_registers_endpoint(self, gpu_config, mock_endpoint_factory):
        pool = GpuHandlerPool(config=gpu_config)

        mock_gpu_type = MagicMock()
        mock_gpu_type.NVIDIA_GEFORCE_RTX_4090 = "RTX_4090"

        captured_handler = {}

        def mock_endpoint_decorator(**kwargs):
            def decorator(fn):
                endpoint = mock_endpoint_factory(fn)
                captured_handler["fn"] = fn
                return endpoint

            return decorator

        with (
            patch("mahavishnu.pools.gpu_handler_pool.Endpoint", mock_endpoint_decorator),
            patch("mahavishnu.pools.gpu_handler_pool.GpuType", mock_gpu_type),
        ):
            pool_id = await pool.start()

        assert pool._status == PoolStatus.RUNNING
        assert pool_id == pool.pool_id
        assert "fn" in captured_handler


class TestGpuHandlerPoolExecution:
    @pytest.mark.asyncio
    async def test_vision_task_executes(self, gpu_config, mock_endpoint_factory):
        pool = GpuHandlerPool(config=gpu_config)
        pool._status = PoolStatus.RUNNING

        async def fake_endpoint(payload):
            return {"category": "vision", "result": "described", "model": "test-model"}

        pool._endpoint = fake_endpoint

        result = await pool.execute_task({"category": "vision", "image_url": "http://x/img.jpg"})

        assert result["status"] == "completed"
        assert result["output"]["category"] == "vision"

    @pytest.mark.asyncio
    async def test_ml_inference_task_executes(self, gpu_config):
        pool = GpuHandlerPool(config=gpu_config)
        pool._status = PoolStatus.RUNNING

        async def fake_endpoint(payload):
            return {"category": "ml_inference", "result": "predicted", "model": "test-model"}

        pool._endpoint = fake_endpoint

        result = await pool.execute_task({"category": "ml_inference", "prompt": "classify this"})

        assert result["status"] == "completed"
        assert result["output"]["category"] == "ml_inference"

    @pytest.mark.asyncio
    async def test_non_gpu_category_is_rejected(self, gpu_config):
        pool = GpuHandlerPool(config=gpu_config)
        pool._status = PoolStatus.RUNNING
        pool._endpoint = AsyncMock()

        result = await pool.execute_task({"category": "code_generation", "prompt": "write code"})

        assert result["status"] == "rejected"
        assert "GpuHandlerPool only handles" in result["error"]
        pool._endpoint.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_without_category_is_passed_through(self, gpu_config):
        """Tasks with no category key bypass the rejection guard."""
        pool = GpuHandlerPool(config=gpu_config)
        pool._status = PoolStatus.RUNNING

        async def fake_endpoint(payload):
            return {"result": "ok"}

        pool._endpoint = fake_endpoint

        result = await pool.execute_task({"prompt": "no category set"})
        assert result["status"] == "completed"


class TestCategoryRouting:
    def test_ml_inference_routing_entry_in_ollama_table(self):
        from mahavishnu.workers.task_router import DEFAULT_OLLAMA_ROUTING

        assert TaskCategory.ML_INFERENCE in DEFAULT_OLLAMA_ROUTING

    def test_ml_inference_routing_entry_in_zai_table(self):
        from mahavishnu.workers.task_router import DEFAULT_ZAI_ROUTING

        assert TaskCategory.ML_INFERENCE in DEFAULT_ZAI_ROUTING
