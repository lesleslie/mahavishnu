"""Tests for mahavishnu.workers.cloud_worker — CloudWorkerConfig and cloud worker logic."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.cloud_worker import CloudWorker, CloudWorkerConfig
from mahavishnu.workers.task_router import TaskCategory


class TestCloudWorkerConfig:
    """Test CloudWorkerConfig dataclass."""

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
            base_url="https://custom.api/v1",
            api_key="test-key",
            model="MiniMax-M2.7-highspeed",
            timeout=600,
            temperature=0.3,
            max_tokens=8192,
            intelligent_routing=False,
        )
        assert cfg.model == "MiniMax-M2.7-highspeed"
        assert cfg.temperature == 0.3
        assert cfg.intelligent_routing is False
        assert cfg.api_key == "test-key"

    @patch.dict(os.environ, {"MINIMAX_BASE_URL": "https://override.api/v1"}, clear=False)
    def test_base_url_from_env(self):
        cfg = CloudWorkerConfig()
        assert cfg.base_url == "https://override.api/v1"

    @patch.dict(os.environ, {"MINIMAX_API_KEY": "env-key-123"}, clear=False)
    def test_api_key_from_env(self):
        cfg = CloudWorkerConfig()
        assert cfg.api_key == "env-key-123"

    def test_get_model_for_category_default(self):
        from mahavishnu.workers.task_router import DEFAULT_MINIMAX_ROUTING

        cfg = CloudWorkerConfig(model="default-model")
        # When model_routing is None, falls back to DEFAULT_MINIMAX_ROUTING
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
        # GENERAL not in routing dict, falls back to config model
        assert cfg.get_model_for_category(TaskCategory.GENERAL) == "fallback"

    def test_get_model_for_category_unknown(self):
        from mahavishnu.workers.task_router import DEFAULT_MINIMAX_ROUTING

        cfg = CloudWorkerConfig(model="fallback")
        # GENERAL is in DEFAULT_MINIMAX_ROUTING → returns "MiniMax-M2.7", not config model
        assert (
            cfg.get_model_for_category(TaskCategory.GENERAL)
            == DEFAULT_MINIMAX_ROUTING[TaskCategory.GENERAL]
        )


class TestCloudWorkerInit:
    """Test CloudWorker initialization."""

    def test_default_init(self):
        from mahavishnu.workers.cloud_worker import CloudWorker

        worker = CloudWorker()
        assert worker.config.model == "MiniMax-M2.7"
        assert worker._client is None
        assert "cloud-" in worker._worker_id

    def test_custom_config(self):
        from mahavishnu.workers.cloud_worker import CloudWorker

        cfg = CloudWorkerConfig(model="custom-model")
        worker = CloudWorker(config=cfg)
        assert worker.config.model == "custom-model"

    def test_custom_worker_id(self):
        from mahavishnu.workers.cloud_worker import CloudWorker

        worker = CloudWorker(worker_id="my-worker")
        assert worker._worker_id == "my-worker"


class TestCloudWorkerStart:
    """Test CloudWorker.start method."""

    @pytest.mark.asyncio
    async def test_start_without_api_key(self):
        from mahavishnu.workers.cloud_worker import CloudWorker

        cfg = CloudWorkerConfig(api_key="")
        worker = CloudWorker(config=cfg)
        with pytest.raises(RuntimeError, match="API key"):
            await worker.start()

    @pytest.mark.asyncio
    async def test_start_success(self):
        from mahavishnu.workers.cloud_worker import CloudWorker

        cfg = CloudWorkerConfig(api_key="test-key")
        worker = CloudWorker(config=cfg)

        mock_client = AsyncMock()
        mock_openai_module = MagicMock()
        mock_openai_module.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai_module}):
            result = await worker.start()
            assert result == worker._worker_id
            mock_openai_module.AsyncOpenAI.assert_called_once()
            call_kwargs = mock_openai_module.AsyncOpenAI.call_args
            assert call_kwargs.kwargs["api_key"] == "test-key"

    @pytest.mark.asyncio
    async def test_start_without_openai_package(self):
        from mahavishnu.workers.cloud_worker import CloudWorker

        cfg = CloudWorkerConfig(api_key="test-key")
        worker = CloudWorker(config=cfg)

        with patch.dict("sys.modules", {"openai": None}), pytest.raises(
            RuntimeError, match="openai package required"
        ):
            await worker.start()


class TestCloudWorkerExecute:
    """Test CloudWorker.execute method."""

    @pytest.mark.asyncio
    async def test_execute_no_prompt(self):
        from mahavishnu.workers.cloud_worker import CloudWorker

        cfg = CloudWorkerConfig(api_key="test-key")
        worker = CloudWorker(config=cfg)

        mock_client = AsyncMock()
        mock_openai_module = MagicMock()
        mock_openai_module.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai_module}):
            await worker.start()
            result = await worker.execute({})
            assert result.error == "No prompt provided in task"
            assert result.status.value == "failed"

    @pytest.mark.asyncio
    async def test_execute_with_explicit_model(self):
        from mahavishnu.workers.cloud_worker import CloudWorker

        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg)

        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "result text"
        mock_message.role = "assistant"
        mock_completion.choices = [MagicMock(message=mock_message)]
        mock_completion.model = "MiniMax-M2.7"
        mock_completion.usage = MagicMock()
        mock_completion.usage.model_dump.return_value = {
            "prompt_tokens": 10,
            "completion_tokens": 20,
        }

        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        mock_openai_module = MagicMock()
        mock_openai_module.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai_module}):
            await worker.start()

            result = await worker.execute({"prompt": "test prompt", "model": "MiniMax-M2.7"})
            assert result.output == "result text"
            assert result.status.value == "completed"

    @pytest.mark.asyncio
    async def test_execute_auto_starts(self):
        from mahavishnu.workers.cloud_worker import CloudWorker

        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg)

        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "auto result"
        mock_message.role = "assistant"
        mock_completion.choices = [MagicMock(message=mock_message)]
        mock_completion.model = "MiniMax-M2.7"
        mock_completion.usage = MagicMock()
        mock_completion.usage.model_dump.return_value = {
            "prompt_tokens": 5,
            "completion_tokens": 10,
        }

        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        mock_openai_module = MagicMock()
        mock_openai_module.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai_module}):
            # Don't call start() — execute should auto-start
            result = await worker.execute({"prompt": "test"})
            assert result.output == "auto result"
            assert result.is_success()


def _make_openai_mock(content="result", usage=None):
    mock_client = MagicMock()
    mock_client.models.list = AsyncMock()
    mock_client.close = MagicMock()
    mock_completion = MagicMock()
    mock_message = MagicMock()
    mock_message.content = content
    mock_message.role = "assistant"
    mock_completion.choices = [MagicMock(message=mock_message)]
    mock_completion.model = "MiniMax-M2.7"
    mock_usage = MagicMock()
    mock_usage.model_dump.return_value = usage or {"prompt_tokens": 10, "completion_tokens": 20}
    mock_completion.usage = mock_usage
    mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
    mock_openai = MagicMock()
    mock_openai.AsyncOpenAI.return_value = mock_client
    return mock_client, mock_openai


class TestCloudWorkerStop:
    @pytest.mark.asyncio
    async def test_stop_closes_client(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="stop-test")
        mock_client, mock_openai = _make_openai_mock()

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            await worker.stop()

            mock_client.close.assert_called_once()
            assert worker._client is None
            assert worker._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stop_without_client(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="stop-test")
        await worker.stop()
        assert worker._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stop_client_error(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="stop-test")
        mock_client, mock_openai = _make_openai_mock()
        mock_client.close = MagicMock(side_effect=RuntimeError("connection lost"))

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            await worker.stop()

            assert worker._client is None
            assert worker._status == WorkerStatus.COMPLETED


class TestCloudWorkerStatusAndProgress:
    @pytest.mark.asyncio
    async def test_status_returns_current(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="status-test")
        mock_client, mock_openai = _make_openai_mock()

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            status = await worker.status()
            assert status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_get_progress(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="progress-test")
        mock_client, mock_openai = _make_openai_mock()

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            progress = await worker.get_progress()

            assert progress["status"] == "running"
            assert progress["worker_id"] == "progress-test"
            assert progress["worker_type"] == "terminal-cloud"
            assert progress["model"] == "MiniMax-M2.7"
            assert progress["duration_seconds"] >= 0
            assert progress["base_url"] == cfg.base_url


class TestCloudWorkerHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="health-test")
        mock_client, mock_openai = _make_openai_mock()

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            result = await worker.health_check()

            assert result["healthy"] is True
            assert result["status"] == "running"
            assert result["worker_type"] == "terminal-cloud"
            assert result["details"]["provider"] == "cloud"
            assert result["details"]["api_key_set"] is True

    @pytest.mark.asyncio
    async def test_health_check_no_client(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="health-test")
        result = await worker.health_check()
        assert result["healthy"] is False

    @pytest.mark.asyncio
    async def test_health_check_client_error(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="health-test")
        mock_client, mock_openai = _make_openai_mock()
        mock_client.models.list = AsyncMock(side_effect=RuntimeError("timeout"))

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            result = await worker.health_check()

            assert result["healthy"] is False
            assert "error" in result["details"]


class TestCloudWorkerExecuteAdvanced:
    @pytest.mark.asyncio
    async def test_execute_with_system_prompt(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="sys-test")
        mock_client, mock_openai = _make_openai_mock("system result")

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            result = await worker.execute(
                {
                    "prompt": "hello",
                    "system": "You are helpful.",
                }
            )

            assert result.output == "system result"
            call_args = mock_client.chat.completions.create.call_args
            messages = call_args.kwargs["messages"]
            assert messages[0]["role"] == "system"
            assert messages[0]["content"] == "You are helpful."
            assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_execute_with_custom_temperature_and_tokens(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="temp-test")
        mock_client, mock_openai = _make_openai_mock()

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            result = await worker.execute(
                {
                    "prompt": "test",
                    "temperature": 0.1,
                    "max_tokens": 100,
                }
            )

            assert result.is_success()
            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["temperature"] == 0.1
            assert call_kwargs["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="timeout-test")
        mock_client, mock_openai = _make_openai_mock()
        mock_client.chat.completions.create = AsyncMock(side_effect=TimeoutError())

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            result = await worker.execute({"prompt": "test", "timeout": 5})

            assert result.status == WorkerStatus.TIMEOUT
            assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_api_error(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="err-test")
        mock_client, mock_openai = _make_openai_mock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            result = await worker.execute({"prompt": "test"})

            assert result.status == WorkerStatus.FAILED
            assert "API down" in result.error

    @pytest.mark.asyncio
    async def test_execute_intelligent_routing(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=True)
        worker = CloudWorker(config=cfg, worker_id="route-test")
        mock_client, mock_openai = _make_openai_mock("routed result")

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            result = await worker.execute(
                {"prompt": "explain and reason about this architecture decision"}
            )

            assert result.output == "routed result"
            assert result.is_success()
            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["model"] == "MiniMax-M2.7"

    @pytest.mark.asyncio
    async def test_execute_empty_content(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="empty-test")
        mock_client, mock_openai = _make_openai_mock(content=None)

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            result = await worker.execute({"prompt": "test"})

            assert result.output == ""
            assert result.is_success()

    @pytest.mark.asyncio
    async def test_execute_no_usage(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        worker = CloudWorker(config=cfg, worker_id="nouse-test")
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "no usage"
        mock_message.role = "assistant"
        mock_completion.choices = [MagicMock(message=mock_message)]
        mock_completion.usage = None
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
        mock_openai = MagicMock()
        mock_openai.AsyncOpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            result = await worker.execute({"prompt": "test"})

            assert result.output == "no usage"
            assert result.metadata["usage"] == {}


class TestCloudWorkerSessionBuddy:
    @pytest.mark.asyncio
    async def test_store_result_in_session_buddy(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        sb_client = AsyncMock()
        worker = CloudWorker(config=cfg, worker_id="sb-test", session_buddy_client=sb_client)
        mock_client, mock_openai = _make_openai_mock("stored result")

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            await worker.execute({"prompt": "test"})

            sb_client.call_tool.assert_awaited_once()
            call_args = sb_client.call_tool.call_args
            assert call_args.kwargs["arguments"]["content"] == "stored result"
            assert call_args.kwargs["arguments"]["metadata"]["type"] == "cloud_execution"

    @pytest.mark.asyncio
    async def test_store_result_session_buddy_error(self):
        cfg = CloudWorkerConfig(api_key="test-key", intelligent_routing=False)
        sb_client = AsyncMock()
        sb_client.call_tool = AsyncMock(side_effect=RuntimeError("SB down"))
        worker = CloudWorker(config=cfg, worker_id="sb-test", session_buddy_client=sb_client)
        mock_client, mock_openai = _make_openai_mock("ok")

        with patch.dict("sys.modules", {"openai": mock_openai}):
            await worker.start()
            result = await worker.execute({"prompt": "test"})

            assert result.output == "ok"
            assert result.is_success()
