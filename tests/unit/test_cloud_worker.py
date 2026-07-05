"""Tests for mahavishnu.workers.cloud_worker — CloudWorkerConfig and FallbackChain integration."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.cloud_worker import CloudWorker, CloudWorkerConfig, _build_fallback_chain
from mahavishnu.workers.task_router import TaskCategory

if TYPE_CHECKING:
    from mcp_common.llm import LLMSettings


def _make_mock_chain(content: str = "result", provider: str = "minimax") -> MagicMock:
    chain = MagicMock()
    chain._providers = []
    chain.execute = AsyncMock(
        return_value={
            "content": content,
            "provider": provider,
            "model": "MiniMax-M2.7",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }
    )
    return chain


@pytest.fixture
def mock_chain():
    return _make_mock_chain()


@pytest.fixture
def worker(mock_chain):
    """Pre-started worker with chain injected directly (bypasses from_settings patch)."""
    w = CloudWorker(config=CloudWorkerConfig(), worker_id="test-worker")
    w._chain = mock_chain
    w._status = WorkerStatus.RUNNING
    w._start_time = time.time()
    return w


class TestCloudWorkerConfig:
    def test_defaults(self):
        cfg = CloudWorkerConfig()
        assert cfg.model == "MiniMax-M2.7"
        assert cfg.timeout == 300
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 4096
        assert cfg.intelligent_routing is True
        assert cfg.model_routing is None

    def test_custom_values(self):
        cfg = CloudWorkerConfig(
            minimax_url="https://custom.api/v1",
            model="MiniMax-M2.7-highspeed",
            timeout=600,
            temperature=0.3,
            max_tokens=8192,
            intelligent_routing=False,
        )
        assert cfg.model == "MiniMax-M2.7-highspeed"
        assert cfg.temperature == 0.3
        assert cfg.intelligent_routing is False
        assert cfg.minimax_url == "https://custom.api/v1"

    @patch.dict(os.environ, {"MINIMAX_BASE_URL": "https://override.api/v1"}, clear=False)
    def test_minimax_url_from_env(self):
        cfg = CloudWorkerConfig()
        assert cfg.minimax_url == "https://override.api/v1"

    @patch.dict(os.environ, {"LLAMA_SERVER_URL": "http://myserver:9000"}, clear=False)
    def test_llama_server_url_from_env(self):
        cfg = CloudWorkerConfig()
        assert cfg.llama_server_url == "http://myserver:9000"

    @patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://mymac:11434/v1"}, clear=False)
    def test_ollama_url_from_env(self):
        cfg = CloudWorkerConfig()
        assert cfg.ollama_url == "http://mymac:11434/v1"

    def test_get_model_for_category_default(self):
        from mahavishnu.workers.task_router import DEFAULT_MINIMAX_ROUTING

        cfg = CloudWorkerConfig(model="default-model")
        assert (
            cfg.get_model_for_category(TaskCategory.CODE_GENERATION)
            == DEFAULT_MINIMAX_ROUTING[TaskCategory.CODE_GENERATION]
        )

    def test_get_model_for_category_with_routing(self):
        routing = {
            TaskCategory.REASONING: "reasoning-model",
            TaskCategory.CODE_GENERATION: "code-model",
        }
        cfg = CloudWorkerConfig(model="fallback", model_routing=routing)
        assert cfg.get_model_for_category(TaskCategory.REASONING) == "reasoning-model"
        assert cfg.get_model_for_category(TaskCategory.GENERAL) == "fallback"


class TestBuildFallbackChain:
    def test_chain_includes_three_providers(self):

        captured: list[LLMSettings] = []

        def capture(settings: LLMSettings) -> MagicMock:
            captured.append(settings)
            return _make_mock_chain()

        cfg = CloudWorkerConfig()
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", side_effect=capture
        ):
            _build_fallback_chain(cfg)

        assert len(captured) == 1
        settings = captured[0]
        assert "minimax" in settings.providers
        assert "llama_server" in settings.providers
        assert "ollama" in settings.providers
        assert settings.fallback_chain == ["minimax", "llama_server", "ollama"]

    def test_minimax_url_in_settings(self):

        captured: list[LLMSettings] = []

        def capture(s: LLMSettings) -> MagicMock:
            captured.append(s)
            return _make_mock_chain()

        cfg = CloudWorkerConfig(minimax_url="https://custom.minimax/v1")
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", side_effect=capture
        ):
            _build_fallback_chain(cfg)

        assert captured[0].providers["minimax"]["base_url"] == "https://custom.minimax/v1"

    def test_llama_server_url_in_settings(self):

        captured: list[LLMSettings] = []

        def capture(s: LLMSettings) -> MagicMock:
            captured.append(s)
            return _make_mock_chain()

        cfg = CloudWorkerConfig(llama_server_url="http://myserver:9000")
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", side_effect=capture
        ):
            _build_fallback_chain(cfg)

        assert captured[0].providers["llama_server"]["base_url"] == "http://myserver:9000"


class TestCloudWorkerInit:
    def test_default_init(self):
        worker = CloudWorker()
        assert worker.config.model == "MiniMax-M2.7"
        assert worker._chain is None
        assert "cloud-" in worker._worker_id

    def test_custom_config(self):
        cfg = CloudWorkerConfig(model="custom-model")
        worker = CloudWorker(config=cfg)
        assert worker.config.model == "custom-model"

    def test_custom_worker_id(self):
        worker = CloudWorker(worker_id="my-worker")
        assert worker._worker_id == "my-worker"


class TestCloudWorkerStart:
    @pytest.mark.asyncio
    async def test_start_builds_chain(self, mock_chain):
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ) as mock_fs:
            worker = CloudWorker()
            result = await worker.start()
            mock_fs.assert_called_once()
            assert worker._chain is mock_chain
            assert result == worker._worker_id
            assert worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_sets_running(self, mock_chain):
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker()
            await worker.start()
            assert worker._status == WorkerStatus.RUNNING


class TestCloudWorkerExecute:
    @pytest.mark.asyncio
    async def test_execute_no_prompt(self, mock_chain):
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker()
            await worker.start()
            result = await worker.execute({})
            assert result.error == "No prompt provided in task"
            assert result.status == WorkerStatus.FAILED

    @pytest.mark.asyncio
    async def test_execute_returns_worker_result(self, worker, mock_chain):
        result = await worker.execute({"prompt": "hello"})
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "result"

    @pytest.mark.asyncio
    async def test_execute_calls_chain(self, worker, mock_chain):
        await worker.execute({"prompt": "write a function"})
        mock_chain.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_auto_starts(self, mock_chain):
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker()
            # Don't call start() — execute should auto-start
            result = await worker.execute({"prompt": "test"})
            assert result.is_success()

    @pytest.mark.asyncio
    async def test_execute_passes_task_type(self, worker, mock_chain):
        """Intelligent routing passes task_type from classify_task() to chain."""
        await worker.execute({"prompt": "write a python function"})
        call_task = mock_chain.execute.call_args[0][0]
        assert call_task["task_type"] == TaskCategory.CODE_GENERATION.value

    @pytest.mark.asyncio
    async def test_execute_code_task_type(self, worker, mock_chain):
        await worker.execute({"prompt": "write a function to sort a list"})
        call_task = mock_chain.execute.call_args[0][0]
        assert call_task["task_type"] == TaskCategory.CODE_GENERATION.value

    @pytest.mark.asyncio
    async def test_execute_explicit_model_passed_to_chain(self, worker, mock_chain):
        await worker.execute({"prompt": "test", "model": "MiniMax-M2.7-highspeed"})
        call_task = mock_chain.execute.call_args[0][0]
        assert call_task["model"] == "MiniMax-M2.7-highspeed"

    @pytest.mark.asyncio
    async def test_execute_with_system_prompt(self, worker, mock_chain):
        await worker.execute({"prompt": "hello", "system": "You are helpful."})
        call_task = mock_chain.execute.call_args[0][0]
        messages = call_task["messages"]
        assert messages[0] == {"role": "system", "content": "You are helpful."}
        assert messages[1] == {"role": "user", "content": "hello"}

    @pytest.mark.asyncio
    async def test_execute_custom_temperature_and_tokens(self, worker, mock_chain):
        await worker.execute({"prompt": "test", "temperature": 0.1, "max_tokens": 100})
        call_task = mock_chain.execute.call_args[0][0]
        assert call_task["temperature"] == 0.1
        assert call_task["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_execute_chain_failure_returns_failed_result(self, mock_chain):
        mock_chain.execute = AsyncMock(side_effect=RuntimeError("all providers down"))
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker()
            await worker.start()
            result = await worker.execute({"prompt": "test"})
            assert result.status == WorkerStatus.FAILED
            assert "all providers down" in result.error

    @pytest.mark.asyncio
    async def test_execute_no_intelligent_routing(self, mock_chain):
        cfg = CloudWorkerConfig(intelligent_routing=False)
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker(config=cfg)
            await worker.start()
            await worker.execute({"prompt": "debug this error"})
        call_task = mock_chain.execute.call_args[0][0]
        assert call_task["task_type"] == TaskCategory.GENERAL.value

    @pytest.mark.asyncio
    async def test_execute_rate_limit_rejected(self, mock_chain):
        """Rate-limit rejection returns FAILED result without calling chain."""
        from mahavishnu.workers.task_router import RateLimitConfig, configure_rate_limiter

        configure_rate_limiter(RateLimitConfig(limit=0))  # reject all
        try:
            with patch(
                "mahavishnu.workers.cloud_worker.FallbackChain.from_settings",
                return_value=mock_chain,
            ):
                worker = CloudWorker()
                await worker.start()
                result = await worker.execute({"prompt": "test"})
            assert result.status == WorkerStatus.FAILED
            assert "Rate limit exceeded" in result.error
            mock_chain.execute.assert_not_awaited()
        finally:
            configure_rate_limiter(RateLimitConfig(limit=10_000))  # restore permissive limit

    @pytest.mark.asyncio
    async def test_execute_metadata_includes_provider(self, worker, mock_chain):
        mock_chain.execute = AsyncMock(
            return_value={
                "content": "ok",
                "provider": "llama_server",
                "model": "qwen3.5",
                "usage": {},
            }
        )
        result = await worker.execute({"prompt": "test"})
        assert result.metadata["provider"] == "llama_server"
        assert result.metadata["model"] == "qwen3.5"


class TestCloudWorkerStop:
    @pytest.mark.asyncio
    async def test_stop_clears_chain(self, mock_chain):
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker()
            await worker.start()
            await worker.stop()
            assert worker._chain is None
            assert worker._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        worker = CloudWorker()
        await worker.stop()
        assert worker._status == WorkerStatus.COMPLETED


class TestCloudWorkerHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_no_chain(self):
        worker = CloudWorker()
        result = await worker.health_check()
        assert result["healthy"] is False
        assert "chain not initialized" in result["details"]["error"]

    @pytest.mark.asyncio
    async def test_health_check_healthy_provider(self, mock_chain):
        mock_provider = MagicMock()
        mock_provider.name = "minimax"
        mock_provider.health_check = AsyncMock(return_value=True)
        mock_chain._providers = [mock_provider]

        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker()
            await worker.start()
            result = await worker.health_check()

        assert result["healthy"] is True
        assert result["details"]["providers"]["minimax"] is True

    @pytest.mark.asyncio
    async def test_health_check_all_providers_down(self, mock_chain):
        mock_provider = MagicMock()
        mock_provider.name = "minimax"
        mock_provider.health_check = AsyncMock(return_value=False)
        mock_chain._providers = [mock_provider]

        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker()
            await worker.start()
            result = await worker.health_check()

        assert result["healthy"] is False

    @pytest.mark.asyncio
    async def test_health_check_provider_raises(self, mock_chain):
        mock_provider = MagicMock()
        mock_provider.name = "minimax"
        mock_provider.health_check = AsyncMock(side_effect=RuntimeError("timeout"))
        mock_chain._providers = [mock_provider]

        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker()
            await worker.start()
            result = await worker.health_check()

        assert result["details"]["providers"]["minimax"] is False


class TestCloudWorkerSessionBuddy:
    @pytest.mark.asyncio
    async def test_store_result_in_session_buddy(self, mock_chain):
        mock_chain.execute = AsyncMock(
            return_value={
                "content": "stored result",
                "provider": "minimax",
                "model": "MiniMax-M2.7",
                "usage": {},
            }
        )
        sb_client = AsyncMock()
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker(worker_id="sb-test", session_buddy_client=sb_client)
            await worker.start()
            await worker.execute({"prompt": "test"})

        sb_client.call_tool.assert_awaited_once()
        assert sb_client.call_tool.call_args.args[0] == "store_memory"
        args = sb_client.call_tool.call_args.kwargs["arguments"]
        assert args["content"] == "stored result"
        assert args["metadata"]["type"] == "cloud_execution"

    @pytest.mark.asyncio
    async def test_session_buddy_error_does_not_fail_worker(self, mock_chain):
        sb_client = AsyncMock()
        sb_client.call_tool = AsyncMock(side_effect=RuntimeError("SB down"))
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker(worker_id="sb-test", session_buddy_client=sb_client)
            await worker.start()
            result = await worker.execute({"prompt": "test"})

        assert result.is_success()


class TestCloudWorkerStatusAndProgress:
    @pytest.mark.asyncio
    async def test_status_returns_current(self, mock_chain):
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker()
            await worker.start()
            assert await worker.status() == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_get_progress(self, mock_chain):
        with patch(
            "mahavishnu.workers.cloud_worker.FallbackChain.from_settings", return_value=mock_chain
        ):
            worker = CloudWorker(worker_id="progress-test")
            await worker.start()
            progress = await worker.get_progress()

        assert progress["worker_id"] == "progress-test"
        assert progress["worker_type"] == "terminal-cloud"
        assert progress["model"] == "MiniMax-M2.7"
        assert progress["duration_seconds"] >= 0
