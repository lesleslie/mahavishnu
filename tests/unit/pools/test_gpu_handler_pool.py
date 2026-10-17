"""Integration smoke tests for GpuHandlerPool and category-aware routing.

The runpod SDK 2.0 path is fully mocked — no real GPU hardware required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.pools.base import PoolConfig, PoolStatus
from mahavishnu.pools.gpu_handler_pool import GPU_TASK_CATEGORIES, GpuHandlerPool
from mahavishnu.core.model_routing import TaskCategory


def _fake_run_request(status_value: str = "COMPLETED", output_value: object = None):
    req = MagicMock()
    req.id = "job-test"
    req.job_id = "job-test"
    req.status.return_value = status_value
    req.output.return_value = output_value
    return req


@pytest.fixture
def gpu_config():
    return PoolConfig(
        name="test-gpu",
        pool_type="runpod",
        extra_config={
            # ``endpoint_id`` is required post-SDK-2.0 migration.
            "endpoint_id": "ep-gpu-handler-integration-1234",
            "api_key": "test-key",
            "gpu_type": "NVIDIA_GEFORCE_RTX_4090",
            "endpoint_name": "mahavishnu-gpu-test",
            "dependencies": ["torch", "Pillow"],
        },
    )


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
    """start() surfaces a RuntimeError when the runpod SDK isn't installed.

    Pre-migration this test called ``pool._build_endpoint()`` directly,
    which was the worker-registration decorator path. After SDK 2.0 the
    SDK import is exercised by ``start()``.
    """

    @pytest.mark.asyncio
    async def test_start_fails_without_sdk(self, gpu_config):
        pool = GpuHandlerPool(config=gpu_config)
        with patch("mahavishnu.pools.runpod_pool.runpod", None):
            with pytest.raises(RuntimeError, match="runpod"):
                await pool.start()

    @pytest.mark.asyncio
    async def test_start_registers_endpoint(self, gpu_config):
        """start() constructs ``runpod.Endpoint(endpoint_id)``."""
        pool = GpuHandlerPool(config=gpu_config)

        fake_endpoint = MagicMock(name="endpoint-client")
        mock_runpod = MagicMock(Endpoint=MagicMock(return_value=fake_endpoint))

        with patch("mahavishnu.pools.runpod_pool.runpod", mock_runpod):
            pool_id = await pool.start()

        assert pool._status == PoolStatus.RUNNING
        assert pool_id == pool.pool_id
        mock_runpod.Endpoint.assert_called_once_with("ep-gpu-handler-integration-1234")


class TestGpuHandlerPoolExecution:
    @pytest.mark.asyncio
    async def test_vision_task_executes(self, gpu_config):
        pool = GpuHandlerPool(config=gpu_config)
        pool._status = PoolStatus.RUNNING

        req = _fake_run_request(
            status_value="COMPLETED",
            output_value={"category": "vision", "result": "described", "model": "test-model"},
        )
        endpoint_mock = MagicMock(run=MagicMock(return_value=req))
        pool._endpoint = endpoint_mock

        result = await pool.execute_task({"category": "vision", "image_url": "http://x/img.jpg"})

        assert result["status"] == "completed"
        assert result["output"]["category"] == "vision"

    @pytest.mark.asyncio
    async def test_ml_inference_task_executes(self, gpu_config):
        pool = GpuHandlerPool(config=gpu_config)
        pool._status = PoolStatus.RUNNING

        req = _fake_run_request(
            status_value="COMPLETED",
            output_value={"category": "ml_inference", "result": "predicted", "model": "test-model"},
        )
        endpoint_mock = MagicMock(run=MagicMock(return_value=req))
        pool._endpoint = endpoint_mock

        result = await pool.execute_task({"category": "ml_inference", "prompt": "classify this"})

        assert result["status"] == "completed"
        assert result["output"]["category"] == "ml_inference"

    @pytest.mark.asyncio
    async def test_non_gpu_category_is_rejected(self, gpu_config):
        pool = GpuHandlerPool(config=gpu_config)
        pool._status = PoolStatus.RUNNING
        endpoint_mock = MagicMock(run=MagicMock())
        pool._endpoint = endpoint_mock

        result = await pool.execute_task({"category": "code_generation", "prompt": "write code"})

        assert result["status"] == "rejected"
        assert "GpuHandlerPool only handles" in result["error"]
        endpoint_mock.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_without_category_is_passed_through(self, gpu_config):
        """Tasks with no category key bypass the rejection guard."""
        pool = GpuHandlerPool(config=gpu_config)
        pool._status = PoolStatus.RUNNING

        req = _fake_run_request(status_value="COMPLETED", output_value={"result": "ok"})
        endpoint_mock = MagicMock(run=MagicMock(return_value=req))
        pool._endpoint = endpoint_mock

        result = await pool.execute_task({"prompt": "no category set"})
        assert result["status"] == "completed"


class TestCategoryRouting:
    def test_ml_inference_routing_entry_in_llama_server_table(self):
        from mahavishnu.core.model_routing import DEFAULT_LLAMA_SERVER_ROUTING

        assert TaskCategory.ML_INFERENCE in DEFAULT_LLAMA_SERVER_ROUTING

    def test_ml_inference_routing_entry_in_minimax_table(self):
        from mahavishnu.core.model_routing import DEFAULT_MINIMAX_ROUTING

        assert TaskCategory.ML_INFERENCE in DEFAULT_MINIMAX_ROUTING
