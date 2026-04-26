"""Unit tests for NanobotWorker - in-process nanobot AI task execution worker."""

from __future__ import annotations

import asyncio
import builtins
import sys
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.base import WorkerResult
from mahavishnu.workers.nanobot_worker import NanobotWorker


def _make_provider(complete_result: str = "task done") -> Any:
    provider = MagicMock()
    provider.complete = AsyncMock(return_value=complete_result)
    return provider


def _make_config(default_timeout: int = 300) -> Any:
    config = MagicMock()
    config.default_timeout = default_timeout
    return config


def _install_nanobot_mock(
    runner_cls: Any = None,
    loop_cls: Any = None,
) -> dict[str, Any]:
    runner_ns = SimpleNamespace(AgentRunner=runner_cls or MagicMock())
    loop_ns = SimpleNamespace(AgentLoop=loop_cls or MagicMock())
    agent_ns = SimpleNamespace(runner=runner_ns, loop=loop_ns)
    nanobot_ns = SimpleNamespace(agent=agent_ns)
    return {
        "nanobot": nanobot_ns,
        "nanobot.agent": agent_ns,
        "nanobot.agent.runner": runner_ns,
        "nanobot.agent.loop": loop_ns,
    }


class TestNanobotWorkerInit:

    def test_default_runner_mode(self) -> None:
        worker = NanobotWorker()
        assert worker.worker_type == "in-process-nanobot"
        assert worker._is_loop_mode is False
        assert worker._nanobot_provider is None
        assert worker._config is None
        assert worker._session_buddy_client is None
        assert worker._start_time is None

    def test_loop_mode(self) -> None:
        worker = NanobotWorker(worker_type="in-process-nanobot-loop")
        assert worker.worker_type == "in-process-nanobot-loop"
        assert worker._is_loop_mode is True

    def test_worker_id_format(self) -> None:
        worker = NanobotWorker()
        assert worker.worker_id.startswith("nanobot_")
        assert len(worker.worker_id) == len("nanobot_") + 12

    def test_worker_id_is_unique(self) -> None:
        w1 = NanobotWorker()
        w2 = NanobotWorker()
        assert w1.worker_id != w2.worker_id

    def test_worker_id_consistency(self) -> None:
        worker = NanobotWorker()
        id1 = worker.worker_id
        id2 = worker.worker_id
        assert id1 == id2
        assert id1.startswith("nanobot_")
        assert len(id1) == len("nanobot_") + 12

    def test_init_with_provider(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        assert worker._nanobot_provider is provider

    def test_init_with_config(self) -> None:
        config = _make_config(60)
        worker = NanobotWorker(config=config)
        assert worker._config is config
        assert worker._config.default_timeout == 60

    def test_init_with_session_buddy_client(self) -> None:
        client = MagicMock()
        worker = NanobotWorker(session_buddy_client=client)
        assert worker._session_buddy_client is client

    def test_initial_status_is_pending(self) -> None:
        worker = NanobotWorker()
        assert worker._status == WorkerStatus.PENDING


class TestNanobotWorkerStart:

    @pytest.mark.asyncio
    async def test_start_returns_worker_id(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        result = await worker.start()
        assert result == worker.worker_id

    @pytest.mark.asyncio
    async def test_start_sets_status_to_running(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()
        assert worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_records_start_time(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        assert worker._start_time is None
        await worker.start()
        assert worker._start_time is not None
        assert isinstance(worker._start_time, float)

    @pytest.mark.asyncio
    async def test_start_raises_without_provider(self) -> None:
        worker = NanobotWorker()
        with pytest.raises(RuntimeError, match="requires a nanobot_provider"):
            await worker.start()
        assert worker._status == WorkerStatus.FAILED

    @pytest.mark.asyncio
    async def test_start_warns_when_provider_lacks_complete(self) -> None:
        provider = MagicMock(spec=[])
        worker = NanobotWorker(nanobot_provider=provider)
        with patch("mahavishnu.workers.nanobot_worker.logger") as mock_logger:
            await worker.start()
            mock_logger.warning.assert_called_once()
            assert "complete" in mock_logger.warning.call_args[0][0]

    @pytest.mark.asyncio
    async def test_start_transitions_through_starting(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)

        with patch("mahavishnu.workers.nanobot_worker.time") as mock_time:
            mock_time.time.return_value = 1000.0
            await worker.start()

        assert worker._status == WorkerStatus.RUNNING
        assert worker._start_time == 1000.0


class TestNanobotWorkerStop:

    @pytest.mark.asyncio
    async def test_stop_sets_completed_status(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()
        await worker.stop()
        assert worker._status == WorkerStatus.COMPLETED


class TestNanobotWorkerStatus:

    @pytest.mark.asyncio
    async def test_status_returns_pending_initially(self) -> None:
        worker = NanobotWorker()
        result = await worker.status()
        assert result == WorkerStatus.PENDING

    @pytest.mark.asyncio
    async def test_status_returns_running_after_start(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()
        result = await worker.status()
        assert result == WorkerStatus.RUNNING


class TestNanobotWorkerGetProgress:

    @pytest.mark.asyncio
    async def test_progress_before_start(self) -> None:
        worker = NanobotWorker()
        progress = await worker.get_progress()
        assert progress["status"] == WorkerStatus.PENDING.value
        assert progress["worker_id"] == worker.worker_id
        assert progress["worker_type"] == "in-process-nanobot"
        assert progress["mode"] == "runner"
        assert progress["duration_seconds"] == 0
        assert progress["provider"] is None

    @pytest.mark.asyncio
    async def test_progress_after_start(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()
        progress = await worker.get_progress()
        assert progress["status"] == WorkerStatus.RUNNING.value
        assert progress["mode"] == "runner"
        assert progress["provider"] == "MagicMock"
        assert progress["duration_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_progress_loop_mode(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(worker_type="in-process-nanobot-loop", nanobot_provider=provider)
        progress = await worker.get_progress()
        assert progress["mode"] == "loop"
        assert progress["worker_type"] == "in-process-nanobot-loop"

    @pytest.mark.asyncio
    async def test_progress_with_provider(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        progress = await worker.get_progress()
        assert progress["provider"] == "MagicMock"

    @pytest.mark.asyncio
    async def test_progress_duration_increases(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()
        p1 = await worker.get_progress()
        time.sleep(0.05)
        p2 = await worker.get_progress()
        assert p2["duration_seconds"] >= p1["duration_seconds"]


class TestNanobotWorkerExecute:

    @pytest.mark.asyncio
    async def test_execute_auto_starts_if_not_running(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        assert worker._status == WorkerStatus.PENDING
        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, return_value="ok"):
            result = await worker.execute({"prompt": "hello"})
        assert worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_execute_returns_failed_without_prompt(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()
        result = await worker.execute({})
        assert result.status == WorkerStatus.FAILED
        assert result.error == "No prompt provided in task"
        assert result.worker_id == worker.worker_id

    @pytest.mark.asyncio
    async def test_execute_returns_failed_with_empty_prompt(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()
        result = await worker.execute({"prompt": ""})
        assert result.status == WorkerStatus.FAILED
        assert "No prompt" in result.error

    @pytest.mark.asyncio
    async def test_execute_uses_config_timeout(self) -> None:
        provider = _make_provider()
        config = _make_config(60)
        worker = NanobotWorker(nanobot_provider=provider, config=config)
        await worker.start()
        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, return_value="done") as mock_runner:
            await worker.execute({"prompt": "test"})
        assert mock_runner.called

    @pytest.mark.asyncio
    async def test_execute_uses_task_timeout_over_config(self) -> None:
        provider = _make_provider()
        config = _make_config(300)
        worker = NanobotWorker(nanobot_provider=provider, config=config)
        await worker.start()
        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, return_value="done") as mock_runner:
            result = await worker.execute({"prompt": "test", "timeout": 10})
        assert result.duration_seconds is not None

    @pytest.mark.asyncio
    async def test_execute_default_timeout_without_config(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()
        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, return_value="done") as mock_runner:
            await worker.execute({"prompt": "test"})
        assert mock_runner.called


class TestNanobotWorkerExecuteRunner:

    @pytest.mark.asyncio
    async def test_runner_mode_success(self) -> None:
        provider = _make_provider("runner output")
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()
        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, return_value="runner output"):
            result = await worker.execute({"prompt": "hello"})
        assert result.status == WorkerStatus.COMPLETED
        assert result.exit_code == 0
        assert result.duration_seconds >= 0
        assert result.metadata["mode"] == "runner"
        assert result.metadata["provider_type"] == "MagicMock"

    @pytest.mark.asyncio
    async def test_runner_mode_with_system_prompt(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()
        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, return_value="ok") as mock:
            await worker.execute({"prompt": "hello", "system": "Be concise"})
            mock.assert_called_once_with("hello", system="Be concise", tools=None)

    @pytest.mark.asyncio
    async def test_runner_mode_with_tools(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()
        tools = [{"name": "read", "desc": "Read file"}]
        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, return_value="ok") as mock:
            await worker.execute({"prompt": "hello", "tools": tools})
            mock.assert_called_once_with("hello", system=None, tools=tools)


class TestNanobotWorkerExecuteLoop:

    @pytest.mark.asyncio
    async def test_loop_mode_success(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(worker_type="in-process-nanobot-loop", nanobot_provider=provider)
        await worker.start()
        with patch.object(worker, "_execute_loop", new_callable=AsyncMock, return_value="loop output") as mock_loop:
            result = await worker.execute({"prompt": "hello"})
        assert result.status == WorkerStatus.COMPLETED
        assert result.metadata["mode"] == "loop"
        mock_loop.assert_called_once_with("hello", system=None, tools=None)

    @pytest.mark.asyncio
    async def test_loop_mode_cleanup_called(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(worker_type="in-process-nanobot-loop", nanobot_provider=provider)
        await worker.start()

        mock_loop_instance = MagicMock()
        mock_loop_instance.run = AsyncMock(return_value="clean result")
        mock_loop_instance.close_mcp = AsyncMock()

        modules = _install_nanobot_mock(loop_cls=MagicMock(return_value=mock_loop_instance))
        with patch.dict(sys.modules, modules, clear=False):
            output = await worker._execute_loop("test prompt")
            assert output == "clean result"
            mock_loop_instance.run.assert_called_once_with("test prompt")
            mock_loop_instance.close_mcp.assert_called_once()

    @pytest.mark.asyncio
    async def test_loop_mode_cleanup_error_is_caught(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(worker_type="in-process-nanobot-loop", nanobot_provider=provider)
        await worker.start()

        mock_loop_instance = MagicMock()
        mock_loop_instance.run = AsyncMock(return_value="result")
        mock_loop_instance.close_mcp = AsyncMock(side_effect=RuntimeError("cleanup failed"))

        modules = _install_nanobot_mock(loop_cls=MagicMock(return_value=mock_loop_instance))
        with patch.dict(sys.modules, modules, clear=False):
            with patch("mahavishnu.workers.nanobot_worker.logger") as mock_logger:
                output = await worker._execute_loop("test")
                assert output == "result"
                mock_logger.debug.assert_called_once()
                assert "cleanup warning" in mock_logger.debug.call_args[0][0]

    @pytest.mark.asyncio
    async def test_loop_mode_no_cleanup_method(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(worker_type="in-process-nanobot-loop", nanobot_provider=provider)
        await worker.start()

        mock_loop_instance = MagicMock(spec=["run"])
        mock_loop_instance.run = AsyncMock(return_value="no cleanup")

        modules = _install_nanobot_mock(loop_cls=MagicMock(return_value=mock_loop_instance))
        with patch.dict(sys.modules, modules, clear=False):
            output = await worker._execute_loop("test")
            assert output == "no cleanup"


class TestNanobotWorkerTimeout:

    @pytest.mark.asyncio
    async def test_runner_timeout(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()

        async def slow_runner(*args: Any, **kwargs: Any) -> str:
            await asyncio.sleep(10)
            return "never"

        with patch.object(worker, "_execute_runner", side_effect=slow_runner):
            result = await worker.execute({"prompt": "hello", "timeout": 0.1})

        assert result.status == WorkerStatus.TIMEOUT
        assert "timed out" in result.error.lower()
        assert result.duration_seconds is not None

    @pytest.mark.asyncio
    async def test_loop_timeout(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(worker_type="in-process-nanobot-loop", nanobot_provider=provider)
        await worker.start()

        async def slow_loop(*args: Any, **kwargs: Any) -> str:
            await asyncio.sleep(10)
            return "never"

        with patch.object(worker, "_execute_loop", side_effect=slow_loop):
            result = await worker.execute({"prompt": "hello", "timeout": 0.1})

        assert result.status == WorkerStatus.TIMEOUT
        assert result.metadata["timeout"] == 0.1


class TestNanobotWorkerErrorHandling:

    @pytest.mark.asyncio
    async def test_execute_catches_generic_exception(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()

        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, side_effect=ValueError("bad input")):
            result = await worker.execute({"prompt": "hello"})

        assert result.status == WorkerStatus.FAILED
        assert "bad input" in result.error
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_execute_catches_runtime_error(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()

        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, side_effect=RuntimeError("api down")):
            result = await worker.execute({"prompt": "hello"})

        assert result.status == WorkerStatus.FAILED
        assert "api down" in result.error

    @pytest.mark.asyncio
    async def test_execute_records_duration_on_error(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()

        async def failing_runner(*args: Any, **kwargs: Any) -> str:
            await asyncio.sleep(0.05)
            raise RuntimeError("boom")

        with patch.object(worker, "_execute_runner", side_effect=failing_runner):
            result = await worker.execute({"prompt": "hello"})

        assert result.duration_seconds >= 0.05


class TestNanobotWorkerSessionBuddy:

    @pytest.mark.asyncio
    async def test_store_result_called_on_success(self) -> None:
        provider = _make_provider()
        sb_client = AsyncMock()
        worker = NanobotWorker(nanobot_provider=provider, session_buddy_client=sb_client)
        await worker.start()

        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, return_value="output"):
            result = await worker.execute({"prompt": "hello"})

        assert result.status == WorkerStatus.COMPLETED
        sb_client.call_tool.assert_called_once()
        call_args = sb_client.call_tool.call_args
        assert call_args[0][0] == "store_memory"
        arguments = call_args[1]["arguments"]
        assert arguments["content"] == "output"
        assert arguments["metadata"]["type"] == "nanobot_execution"
        assert arguments["metadata"]["worker_id"] == worker.worker_id
        assert arguments["metadata"]["status"] == WorkerStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_store_result_not_called_without_client(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()

        with patch.object(worker, "_store_result", new_callable=AsyncMock) as mock_store:
            await worker.execute({"prompt": "hello"})

        mock_store.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_result_failure_is_caught(self) -> None:
        provider = _make_provider()
        sb_client = AsyncMock()
        sb_client.call_tool = AsyncMock(side_effect=ConnectionError("sb down"))
        worker = NanobotWorker(nanobot_provider=provider, session_buddy_client=sb_client)
        await worker.start()

        with patch("mahavishnu.workers.nanobot_worker.logger") as mock_logger:
            with patch.object(worker, "_execute_runner", new_callable=AsyncMock, return_value="output"):
                result = await worker.execute({"prompt": "hello"})

        assert result.status == WorkerStatus.COMPLETED
        mock_logger.warning.assert_called_once()
        assert "Session-Buddy" in mock_logger.warning.call_args[0][0]

    @pytest.mark.asyncio
    async def test_store_result_stores_empty_output(self) -> None:
        provider = _make_provider()
        sb_client = AsyncMock()
        worker = NanobotWorker(nanobot_provider=provider, session_buddy_client=sb_client)
        await worker.start()

        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, return_value=""):
            result = await worker.execute({"prompt": "hello"})

        sb_client.call_tool.assert_called_once()
        assert sb_client.call_tool.call_args[1]["arguments"]["content"] == ""

    @pytest.mark.asyncio
    async def test_store_result_includes_duration(self) -> None:
        provider = _make_provider()
        sb_client = AsyncMock()
        worker = NanobotWorker(nanobot_provider=provider, session_buddy_client=sb_client)
        await worker.start()

        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, return_value="output"):
            result = await worker.execute({"prompt": "hello"})

        metadata = sb_client.call_tool.call_args[1]["arguments"]["metadata"]
        assert "duration_seconds" in metadata
        assert metadata["duration_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_store_result_truncates_long_prompt(self) -> None:
        provider = _make_provider()
        sb_client = AsyncMock()
        worker = NanobotWorker(nanobot_provider=provider, session_buddy_client=sb_client)
        await worker.start()

        long_prompt = "x" * 1000
        with patch.object(worker, "_execute_runner", new_callable=AsyncMock, return_value="output"):
            await worker.execute({"prompt": long_prompt})

        metadata = sb_client.call_tool.call_args[1]["arguments"]["metadata"]
        assert len(metadata["task_prompt"]) == 500


class TestNanobotWorkerHealthCheck:

    @pytest.mark.asyncio
    async def test_health_check_running(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()
        health = await worker.health_check()
        assert health["healthy"] is True
        assert health["status"] == WorkerStatus.RUNNING.value

    @pytest.mark.asyncio
    async def test_health_check_pending(self) -> None:
        worker = NanobotWorker()
        health = await worker.health_check()
        assert health["healthy"] is True
        assert health["status"] == WorkerStatus.PENDING.value

    @pytest.mark.asyncio
    async def test_health_check_failed(self) -> None:
        worker = NanobotWorker()
        worker._status = WorkerStatus.FAILED
        health = await worker.health_check()
        assert health["healthy"] is False


class TestNanobotWorkerExecuteRunnerDirect:

    @pytest.mark.asyncio
    async def test_execute_runner_imports_and_calls(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()

        mock_runner_instance = MagicMock()
        mock_runner_instance.run = AsyncMock(return_value="direct runner result")

        modules = _install_nanobot_mock(runner_cls=MagicMock(return_value=mock_runner_instance))
        with patch.dict(sys.modules, modules, clear=False):
            output = await worker._execute_runner("do something", system="Be helpful", tools=[{"name": "tool1"}])

        assert output == "direct runner result"
        mock_runner_instance.run.assert_called_once_with("do something")

    @pytest.mark.asyncio
    async def test_execute_runner_default_system_prompt(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()

        mock_runner_instance = MagicMock()
        mock_runner_instance.run = AsyncMock(return_value="result")
        captured_kwargs: dict[str, Any] = {}

        def capture_agent(*args: Any, **kwargs: Any) -> MagicMock:
            captured_kwargs.update(kwargs)
            return mock_runner_instance

        modules = _install_nanobot_mock(runner_cls=capture_agent)
        with patch.dict(sys.modules, modules, clear=False):
            await worker._execute_runner("prompt", system=None, tools=None)

        assert captured_kwargs["system"] == "You are a helpful coding assistant."
        assert captured_kwargs["tools"] == []

    @pytest.mark.asyncio
    async def test_execute_loop_default_system_prompt(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(worker_type="in-process-nanobot-loop", nanobot_provider=provider)
        await worker.start()

        mock_loop_instance = MagicMock()
        mock_loop_instance.run = AsyncMock(return_value="result")
        captured_kwargs: dict[str, Any] = {}

        def capture_agent(*args: Any, **kwargs: Any) -> MagicMock:
            captured_kwargs.update(kwargs)
            return mock_loop_instance

        modules = _install_nanobot_mock(loop_cls=capture_agent)
        with patch.dict(sys.modules, modules, clear=False):
            await worker._execute_loop("prompt", system=None, tools=None)

        assert captured_kwargs["system"] == "You are a helpful coding assistant."
        assert captured_kwargs["tools"] == []

    @pytest.mark.asyncio
    async def test_execute_runner_exception_propagates(self) -> None:
        provider = _make_provider()
        worker = NanobotWorker(nanobot_provider=provider)
        await worker.start()

        modules = _install_nanobot_mock(
            runner_cls=MagicMock(side_effect=ImportError("no module"))
        )
        with patch.dict(sys.modules, modules, clear=False):
            with pytest.raises(ImportError, match="no module"):
                await worker._execute_runner("prompt")
