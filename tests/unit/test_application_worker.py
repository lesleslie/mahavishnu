"""Unit tests for ApplicationWorker - MCP-based application control worker."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.application import ApplicationWorker
from mahavishnu.workers.base import WorkerResult
from mahavishnu.workers.registry import WorkerCategory, WorkerConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    worker_type: str = "application-mdinject",
    mcp_server: str = "mdinject",
    default_timeout: int = 300,
) -> WorkerConfig:
    """Create a WorkerConfig for application workers."""
    return WorkerConfig(
        name=worker_type,
        worker_type=worker_type,
        command="",
        category=WorkerCategory.APPLICATION,
        description=f"{worker_type} via MCP",
        mcp_server=mcp_server,
        supports_interactive=False,
        default_timeout=default_timeout,
    )


def _make_worker(
    worker_type: str = "application-mdinject",
    mcp_client: Any = None,
    config: WorkerConfig | None = None,
    session_buddy_client: Any = None,
) -> ApplicationWorker:
    """Create an ApplicationWorker with sensible defaults."""
    cfg = config or _make_config(worker_type)
    client = mcp_client if mcp_client is not None else AsyncMock()
    return ApplicationWorker(
        worker_type=worker_type,
        mcp_client=client,
        config=cfg,
        session_buddy_client=session_buddy_client,
    )


# ---------------------------------------------------------------------------
# TestApplicationWorkerInit
# ---------------------------------------------------------------------------


class TestApplicationWorkerInit:
    def test_basic_init(self) -> None:
        worker = _make_worker()
        assert worker.worker_type == "application-mdinject"
        assert worker.config is not None
        assert worker.config.mcp_server == "mdinject"
        assert worker.mcp_client is not None
        assert worker._start_time is None
        assert worker._mcp_server_name == "mdinject"

    def test_worker_id_format(self) -> None:
        worker = _make_worker()
        assert worker.worker_id.startswith("app_")
        assert len(worker.worker_id) == len("app_") + 12

    def test_worker_id_is_unique(self) -> None:
        w1 = _make_worker()
        w2 = _make_worker()
        assert w1.worker_id != w2.worker_id

    def test_worker_id_is_consistent(self) -> None:
        worker = _make_worker()
        id1 = worker.worker_id
        id2 = worker.worker_id
        assert id1 == id2

    def test_init_sets_initial_status_pending(self) -> None:
        worker = _make_worker()
        assert worker._status == WorkerStatus.PENDING

    def test_init_stores_session_buddy_client(self) -> None:
        sb = MagicMock()
        worker = _make_worker(session_buddy_client=sb)
        assert worker.session_buddy_client is sb

    def test_init_with_no_mcp_server_raises(self) -> None:
        cfg = WorkerConfig(
            name="terminal-shell",
            worker_type="terminal-shell",
            command="bash",
            category=WorkerCategory.SHELL,
            mcp_server=None,
        )
        with pytest.raises(ValueError, match="not an MCP application worker"):
            ApplicationWorker(worker_type="terminal-shell", config=cfg)

    def test_init_with_unknown_worker_type_raises(self) -> None:
        with (
            patch("mahavishnu.workers.application.get_worker_config", return_value=None),
            pytest.raises(ValueError, match="Unknown worker type"),
        ):
            ApplicationWorker(worker_type="nonexistent")

    def test_init_loads_config_from_registry_when_not_provided(self) -> None:
        """When config=None, get_worker_config is called."""
        cfg = _make_config()
        with patch("mahavishnu.workers.application.get_worker_config", return_value=cfg):
            worker = ApplicationWorker(worker_type="application-mdinject")
        assert worker.config is cfg
        assert worker._mcp_server_name == "mdinject"

    def test_init_mcp_client_defaults_to_none(self) -> None:
        cfg = _make_config()
        worker = ApplicationWorker(worker_type="application-mdinject", config=cfg)
        assert worker.mcp_client is None

    def test_init_various_application_types(self) -> None:
        for wtype, server in [
            ("application-gimp", "gimp-mcp"),
            ("application-blender", "blender-mcp"),
            ("application-vscode", "vscode-mcp"),
        ]:
            worker = _make_worker(worker_type=wtype, config=_make_config(wtype, server))
            assert worker._mcp_server_name == server

    def test_init_default_timeout_from_config(self) -> None:
        cfg = _make_config(default_timeout=120)
        worker = _make_worker(config=cfg)
        assert worker.config.default_timeout == 120


# ---------------------------------------------------------------------------
# TestApplicationWorkerStart
# ---------------------------------------------------------------------------


class TestApplicationWorkerStart:
    @pytest.mark.asyncio
    async def test_start_returns_worker_id(self) -> None:
        worker = _make_worker()
        result = await worker.start()
        assert result == worker.worker_id

    @pytest.mark.asyncio
    async def test_start_sets_status_to_running(self) -> None:
        worker = _make_worker()
        await worker.start()
        assert worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_records_start_time(self) -> None:
        worker = _make_worker()
        assert worker._start_time is None
        await worker.start()
        assert worker._start_time is not None
        assert isinstance(worker._start_time, float)

    @pytest.mark.asyncio
    async def test_start_raises_without_mcp_client(self) -> None:
        cfg = _make_config()
        worker = ApplicationWorker(worker_type="application-mdinject", mcp_client=None, config=cfg)
        with pytest.raises(RuntimeError, match="MCP client not provided"):
            await worker.start()

    @pytest.mark.asyncio
    async def test_start_error_message_includes_server_name(self) -> None:
        cfg = _make_config(mcp_server="blender-mcp")
        worker = ApplicationWorker(worker_type="application-blender", mcp_client=None, config=cfg)
        with pytest.raises(RuntimeError, match="blender-mcp"):
            await worker.start()

    @pytest.mark.asyncio
    async def test_start_logs_info(self) -> None:
        worker = _make_worker()
        with patch("mahavishnu.workers.application.logger") as mock_logger:
            await worker.start()
            mock_logger.info.assert_called_once()
            log_msg = mock_logger.info.call_args[0][0]
            assert "application-mdinject" in log_msg
            assert "mdinject" in log_msg


# ---------------------------------------------------------------------------
# TestApplicationWorkerStop
# ---------------------------------------------------------------------------


class TestApplicationWorkerStop:
    @pytest.mark.asyncio
    async def test_stop_sets_completed_status(self) -> None:
        worker = _make_worker()
        await worker.start()
        await worker.stop()
        assert worker._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stop_is_noop_without_start(self) -> None:
        """Stop can be called even if worker was never started."""
        worker = _make_worker()
        await worker.stop()
        assert worker._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stop_logs_info(self) -> None:
        worker = _make_worker()
        with patch("mahavishnu.workers.application.logger") as mock_logger:
            await worker.stop()
            mock_logger.info.assert_called_once()
            assert "application-mdinject" in mock_logger.info.call_args[0][0]


# ---------------------------------------------------------------------------
# TestApplicationWorkerStatus
# ---------------------------------------------------------------------------


class TestApplicationWorkerStatus:
    @pytest.mark.asyncio
    async def test_status_returns_pending_initially(self) -> None:
        worker = _make_worker()
        result = await worker.status()
        assert result == WorkerStatus.PENDING

    @pytest.mark.asyncio
    async def test_status_returns_running_after_start(self) -> None:
        worker = _make_worker()
        await worker.start()
        result = await worker.status()
        assert result == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_status_returns_completed_after_stop(self) -> None:
        worker = _make_worker()
        await worker.start()
        await worker.stop()
        result = await worker.status()
        assert result == WorkerStatus.COMPLETED


# ---------------------------------------------------------------------------
# TestApplicationWorkerGetProgress
# ---------------------------------------------------------------------------


class TestApplicationWorkerGetProgress:
    @pytest.mark.asyncio
    async def test_progress_before_start(self) -> None:
        worker = _make_worker()
        progress = await worker.get_progress()
        assert progress["status"] == WorkerStatus.PENDING.value
        assert progress["worker_id"] == worker.worker_id
        assert progress["worker_type"] == "application-mdinject"
        assert progress["mcp_server"] == "mdinject"
        assert progress["duration_seconds"] == 0

    @pytest.mark.asyncio
    async def test_progress_after_start(self) -> None:
        worker = _make_worker()
        await worker.start()
        progress = await worker.get_progress()
        assert progress["status"] == WorkerStatus.RUNNING.value
        assert progress["duration_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_progress_duration_increases(self) -> None:
        worker = _make_worker()
        await worker.start()
        p1 = await worker.get_progress()
        await asyncio.sleep(0.05)
        p2 = await worker.get_progress()
        assert p2["duration_seconds"] >= p1["duration_seconds"]

    @pytest.mark.asyncio
    async def test_progress_includes_mcp_server(self) -> None:
        worker = _make_worker(config=_make_config(mcp_server="gimp-mcp"))
        progress = await worker.get_progress()
        assert progress["mcp_server"] == "gimp-mcp"


# ---------------------------------------------------------------------------
# TestApplicationWorkerExecute
# ---------------------------------------------------------------------------


class TestApplicationWorkerExecute:
    @pytest.mark.asyncio
    async def test_execute_auto_starts_if_not_running(self) -> None:
        worker = _make_worker()
        assert worker._status == WorkerStatus.PENDING
        worker.mcp_client.call_tool = AsyncMock(return_value="done")
        await worker.execute({"tool": "create_prompt", "arguments": {}})
        assert worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_execute_returns_failed_without_tool(self) -> None:
        worker = _make_worker()
        await worker.start()
        result = await worker.execute({})
        assert result.status == WorkerStatus.FAILED
        assert "No tool name" in result.error
        assert result.worker_id == worker.worker_id

    @pytest.mark.asyncio
    async def test_execute_returns_failed_with_none_tool(self) -> None:
        worker = _make_worker()
        await worker.start()
        result = await worker.execute({"tool": None})
        assert result.status == WorkerStatus.FAILED
        assert "No tool name" in result.error

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value="success output")
        result = await worker.execute({"tool": "create_prompt", "arguments": {"title": "Test"}})
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "success output"
        assert result.duration_seconds >= 0
        assert result.metadata["tool"] == "create_prompt"
        assert result.metadata["worker_type"] == "application-mdinject"
        assert result.metadata["mcp_server"] == "mdinject"

    @pytest.mark.asyncio
    async def test_execute_uses_task_timeout_over_config(self) -> None:
        worker = _make_worker()
        await worker.start()

        async def slow_call(*args: Any, **kwargs: Any) -> str:
            await asyncio.sleep(10)
            return "never"

        worker.mcp_client.call_tool = AsyncMock(side_effect=slow_call)
        result = await worker.execute({"tool": "test_tool", "timeout": 0.1})
        assert result.status == WorkerStatus.TIMEOUT
        assert "timed out" in result.error.lower()
        assert result.metadata["timeout"] == 0.1

    @pytest.mark.asyncio
    async def test_execute_timeout(self) -> None:
        worker = _make_worker()
        await worker.start()

        async def slow_call(*args: Any, **kwargs: Any) -> str:
            await asyncio.sleep(10)
            return "never"

        worker.mcp_client.call_tool = AsyncMock(side_effect=slow_call)
        result = await worker.execute({"tool": "test_tool", "timeout": 0.05})
        assert result.status == WorkerStatus.TIMEOUT
        assert result.duration_seconds is not None

    @pytest.mark.asyncio
    async def test_execute_timeout_logs_error(self) -> None:
        worker = _make_worker()
        await worker.start()

        async def slow_call(*args: Any, **kwargs: Any) -> str:
            await asyncio.sleep(10)
            return "never"

        worker.mcp_client.call_tool = AsyncMock(side_effect=slow_call)
        with patch("mahavishnu.workers.application.logger") as mock_logger:
            await worker.execute({"tool": "test_tool", "timeout": 0.05})
            mock_logger.error.assert_called_once()
            assert "timed out" in mock_logger.error.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_execute_catches_generic_exception(self) -> None:
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(side_effect=ValueError("bad argument"))
        result = await worker.execute({"tool": "test_tool"})
        assert result.status == WorkerStatus.FAILED
        assert "bad argument" in result.error
        assert result.metadata["exception"] == "ValueError"

    @pytest.mark.asyncio
    async def test_execute_catches_runtime_error(self) -> None:
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(side_effect=RuntimeError("connection refused"))
        result = await worker.execute({"tool": "test_tool"})
        assert result.status == WorkerStatus.FAILED
        assert "connection refused" in result.error

    @pytest.mark.asyncio
    async def test_execute_records_duration_on_success(self) -> None:
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value="ok")
        result = await worker.execute({"tool": "test_tool"})
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_execute_records_failure_metadata(self) -> None:
        """Error path returns FAILED result with correct metadata."""
        worker = _make_worker()
        await worker.start()

        async def failing_call(*args: Any, **kwargs: Any) -> str:
            await asyncio.sleep(0.05)
            raise RuntimeError("boom")

        worker.mcp_client.call_tool = AsyncMock(side_effect=failing_call)
        result = await worker.execute({"tool": "test_tool"})
        assert result.status == WorkerStatus.FAILED
        assert result.error == "boom"
        assert result.metadata["exception"] == "RuntimeError"
        assert result.metadata["tool"] == "test_tool"

    @pytest.mark.asyncio
    async def test_execute_error_logs_error(self) -> None:
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(side_effect=RuntimeError("server error"))
        with patch("mahavishnu.workers.application.logger") as mock_logger:
            await worker.execute({"tool": "test_tool"})
            mock_logger.error.assert_called_once()
            assert "server error" in mock_logger.error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_execute_default_arguments(self) -> None:
        """When no arguments provided, defaults to empty dict."""
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value="done")
        result = await worker.execute({"tool": "test_tool"})
        assert result.status == WorkerStatus.COMPLETED
        assert result.metadata["arguments"] == {}


# ---------------------------------------------------------------------------
# TestApplicationWorkerCallMcpTool
# ---------------------------------------------------------------------------


class TestApplicationWorkerCallMcpTool:
    @pytest.mark.asyncio
    async def test_call_uses_prefixed_name_first(self) -> None:
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value="prefixed result")
        result = await worker._call_mcp_tool("create_prompt", {"title": "T"})
        assert result == "prefixed result"
        worker.mcp_client.call_tool.assert_called_once_with(
            "mdinject__create_prompt", {"title": "T"}
        )

    @pytest.mark.asyncio
    async def test_call_falls_back_to_unprefixed_name(self) -> None:
        worker = _make_worker()
        await worker.start()

        call_count = 0

        async def side_effect(name: str, args: dict[str, Any]) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("prefixed not found")
            return "fallback result"

        worker.mcp_client.call_tool = AsyncMock(side_effect=side_effect)
        result = await worker._call_mcp_tool("create_prompt", {"title": "T"})
        assert result == "fallback result"
        assert call_count == 2
        # Second call should be with unprefixed name
        assert worker.mcp_client.call_tool.call_args[0][0] == "create_prompt"

    @pytest.mark.asyncio
    async def test_call_propagates_error_when_both_fail(self) -> None:
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(side_effect=RuntimeError("tool not found"))
        with pytest.raises(RuntimeError, match="tool not found"):
            await worker._call_mcp_tool("nonexistent", {})


# ---------------------------------------------------------------------------
# TestApplicationWorkerExtractOutput
# ---------------------------------------------------------------------------


class TestApplicationWorkerExtractOutput:
    def test_none_returns_empty_string(self) -> None:
        worker = _make_worker()
        assert worker._extract_output(None) == ""

    def test_string_returns_itself(self) -> None:
        worker = _make_worker()
        assert worker._extract_output("hello") == "hello"

    def test_dict_with_content_string(self) -> None:
        worker = _make_worker()
        result = {"content": "direct content"}
        assert worker._extract_output(result) == "direct content"

    def test_dict_with_content_list_of_dicts(self) -> None:
        worker = _make_worker()
        result = {"content": [{"text": "line1"}, {"text": "line2"}]}
        assert worker._extract_output(result) == "line1\nline2"

    def test_dict_with_content_list_of_strings(self) -> None:
        worker = _make_worker()
        result = {"content": ["line1", "line2"]}
        assert worker._extract_output(result) == "line1\nline2"

    def test_dict_with_content_mixed_list(self) -> None:
        worker = _make_worker()
        result = {"content": [{"text": "line1"}, "line2", {"text": "line3"}]}
        assert worker._extract_output(result) == "line1\nline2\nline3"

    def test_dict_with_result_key(self) -> None:
        worker = _make_worker()
        result = {"result": 42}
        assert worker._extract_output(result) == "42"

    def test_dict_with_output_key(self) -> None:
        worker = _make_worker()
        result = {"output": "stdout data"}
        assert worker._extract_output(result) == "stdout data"

    def test_dict_falls_back_to_json(self) -> None:
        worker = _make_worker()
        result = {"key1": "val1", "key2": 123}
        output = worker._extract_output(result)
        parsed = json.loads(output)
        assert parsed["key1"] == "val1"
        assert parsed["key2"] == 123

    def test_list_returns_joined_strings(self) -> None:
        worker = _make_worker()
        result = ["item1", "item2", "item3"]
        assert worker._extract_output(result) == "item1\nitem2\nitem3"

    def test_int_returns_str(self) -> None:
        worker = _make_worker()
        assert worker._extract_output(42) == "42"

    def test_bool_returns_str(self) -> None:
        worker = _make_worker()
        assert worker._extract_output(True) == "True"

    def test_empty_dict_returns_json(self) -> None:
        worker = _make_worker()
        output = worker._extract_output({})
        assert json.loads(output) == {}

    def test_dict_content_priority_over_result(self) -> None:
        """Content key has priority over result key."""
        worker = _make_worker()
        result = {"content": "from_content", "result": "from_result"}
        assert worker._extract_output(result) == "from_content"

    def test_dict_content_empty_list(self) -> None:
        worker = _make_worker()
        result = {"content": []}
        assert worker._extract_output(result) == ""

    def test_dict_content_list_with_non_text_items(self) -> None:
        """Items without 'text' key and not strings are ignored."""
        worker = _make_worker()
        result = {"content": [{"other": "val"}, {"text": "kept"}]}
        assert worker._extract_output(result) == "kept"


# ---------------------------------------------------------------------------
# TestApplicationWorkerStoreResultInSessionBuddy
# ---------------------------------------------------------------------------


class TestApplicationWorkerStoreResultInSessionBuddy:
    @pytest.mark.asyncio
    async def test_store_called_on_success_with_client(self) -> None:
        sb = AsyncMock()
        worker = _make_worker(session_buddy_client=sb)
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value="output")
        result = await worker.execute({"tool": "create_prompt", "arguments": {"title": "T"}})

        assert result.status == WorkerStatus.COMPLETED
        sb.call_tool.assert_called_once()
        call_args = sb.call_tool.call_args
        assert call_args[0][0] == "store_memory"
        arguments = call_args[1]["arguments"]
        assert arguments["content"] == "output"
        assert arguments["metadata"]["type"] == "application_worker_execution"
        assert arguments["metadata"]["worker_id"] == worker.worker_id
        assert arguments["metadata"]["worker_type"] == "application-mdinject"
        assert arguments["metadata"]["mcp_server"] == "mdinject"
        assert arguments["metadata"]["tool"] == "create_prompt"
        assert arguments["metadata"]["status"] == WorkerStatus.COMPLETED.value
        assert "duration_seconds" in arguments["metadata"]
        assert "timestamp" in arguments["metadata"]

    @pytest.mark.asyncio
    async def test_store_not_called_without_client(self) -> None:
        worker = _make_worker(session_buddy_client=None)
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value="output")
        with patch.object(worker, "_store_result_in_session_buddy", new_callable=AsyncMock) as mock:
            await worker.execute({"tool": "create_prompt"})
        mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_failure_is_caught(self) -> None:
        sb = AsyncMock()
        sb.call_tool = AsyncMock(side_effect=ConnectionError("sb down"))
        worker = _make_worker(session_buddy_client=sb)
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value="output")

        with patch("mahavishnu.workers.application.logger") as mock_logger:
            result = await worker.execute({"tool": "create_prompt"})

        assert result.status == WorkerStatus.COMPLETED
        mock_logger.warning.assert_called_once()
        assert "Session-Buddy" in mock_logger.warning.call_args[0][0]

    @pytest.mark.asyncio
    async def test_store_stores_empty_output(self) -> None:
        sb = AsyncMock()
        worker = _make_worker(session_buddy_client=sb)
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value="")
        await worker.execute({"tool": "create_prompt"})
        arguments = sb.call_tool.call_args[1]["arguments"]
        assert arguments["content"] == ""

    @pytest.mark.asyncio
    async def test_store_early_return_when_no_client(self) -> None:
        """Direct call to _store_result_in_session_buddy with no client returns early."""
        worker = _make_worker(session_buddy_client=None)
        worker_result = WorkerResult(
            worker_id="test",
            status=WorkerStatus.COMPLETED,
            output="output",
        )
        # Should not raise
        await worker._store_result_in_session_buddy(worker_result, {"tool": "t"})

    @pytest.mark.asyncio
    async def test_store_logs_on_success(self) -> None:
        sb = AsyncMock()
        worker = _make_worker(session_buddy_client=sb)
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value="output")

        with patch("mahavishnu.workers.application.logger") as mock_logger:
            await worker.execute({"tool": "create_prompt"})

        mock_logger.info.assert_any_call(f"Stored result for {worker.worker_id} in Session-Buddy")

    @pytest.mark.asyncio
    async def test_store_not_called_on_timeout(self) -> None:
        """Session-Buddy store is not attempted on timeout."""
        sb = AsyncMock()
        worker = _make_worker(session_buddy_client=sb)
        await worker.start()

        async def slow_call(*args: Any, **kwargs: Any) -> str:
            await asyncio.sleep(10)
            return "never"

        worker.mcp_client.call_tool = AsyncMock(side_effect=slow_call)
        result = await worker.execute({"tool": "test_tool", "timeout": 0.05})
        assert result.status == WorkerStatus.TIMEOUT
        # store_memory should not have been called (execute catches timeout before store)
        sb.call_tool.assert_not_called()


# ---------------------------------------------------------------------------
# TestApplicationWorkerHealthCheck
# ---------------------------------------------------------------------------


class TestApplicationWorkerHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_running(self) -> None:
        worker = _make_worker()
        await worker.start()
        health = await worker.health_check()
        assert health["healthy"] is True
        assert health["status"] == WorkerStatus.RUNNING.value
        assert health["worker_type"] == "application-mdinject"

    @pytest.mark.asyncio
    async def test_health_check_pending(self) -> None:
        worker = _make_worker()
        health = await worker.health_check()
        assert health["healthy"] is True
        assert health["status"] == WorkerStatus.PENDING.value

    @pytest.mark.asyncio
    async def test_health_check_failed(self) -> None:
        worker = _make_worker()
        worker._status = WorkerStatus.FAILED
        health = await worker.health_check()
        assert health["healthy"] is False

    @pytest.mark.asyncio
    async def test_health_check_completed(self) -> None:
        worker = _make_worker()
        await worker.start()
        await worker.stop()
        health = await worker.health_check()
        # COMPLETED is not in (RUNNING, PENDING) so not healthy
        assert health["healthy"] is False
        assert health["status"] == WorkerStatus.COMPLETED.value


# ---------------------------------------------------------------------------
# TestApplicationWorkerExecuteIntegration
# ---------------------------------------------------------------------------


class TestApplicationWorkerExecuteIntegration:
    @pytest.mark.asyncio
    async def test_full_lifecycle(self) -> None:
        """Test start -> execute -> stop lifecycle."""
        worker = _make_worker()
        wid = await worker.start()
        assert wid == worker.worker_id
        assert worker._status == WorkerStatus.RUNNING

        worker.mcp_client.call_tool = AsyncMock(return_value="result data")
        result = await worker.execute({"tool": "get_info", "arguments": {"id": 1}})
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "result data"

        await worker.stop()
        assert worker._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_multiple_executions(self) -> None:
        """Worker can execute multiple tasks sequentially."""
        worker = _make_worker()
        await worker.start()

        worker.mcp_client.call_tool = AsyncMock(side_effect=["first", "second", "third"])

        r1 = await worker.execute({"tool": "a"})
        r2 = await worker.execute({"tool": "b"})
        r3 = await worker.execute({"tool": "c"})

        assert r1.output == "first"
        assert r2.output == "second"
        assert r3.output == "third"
        assert worker.mcp_client.call_tool.call_count == 3

    @pytest.mark.asyncio
    async def test_execute_with_dict_result_content(self) -> None:
        """MCP tool returns dict with content list (common MCP response format)."""
        worker = _make_worker()
        await worker.start()

        mcp_result = {
            "content": [
                {"type": "text", "text": "Line 1"},
                {"type": "text", "text": "Line 2"},
            ]
        }
        worker.mcp_client.call_tool = AsyncMock(return_value=mcp_result)
        result = await worker.execute({"tool": "read_file"})
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "Line 1\nLine 2"

    @pytest.mark.asyncio
    async def test_execute_with_dict_result_string(self) -> None:
        """MCP tool returns dict with content as plain string."""
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value={"content": "plain text"})
        result = await worker.execute({"tool": "read_file"})
        assert result.output == "plain text"

    @pytest.mark.asyncio
    async def test_execute_with_dict_result_key(self) -> None:
        """MCP tool returns dict with 'result' key."""
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value={"result": "value123"})
        result = await worker.execute({"tool": "compute"})
        assert result.output == "value123"

    @pytest.mark.asyncio
    async def test_execute_with_list_result(self) -> None:
        """MCP tool returns a list."""
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value=["a", "b", "c"])
        result = await worker.execute({"tool": "list_items"})
        assert result.output == "a\nb\nc"

    @pytest.mark.asyncio
    async def test_execute_with_none_result(self) -> None:
        """MCP tool returns None."""
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value=None)
        result = await worker.execute({"tool": "void_tool"})
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == ""

    @pytest.mark.asyncio
    async def test_metadata_includes_tool_and_arguments(self) -> None:
        worker = _make_worker()
        await worker.start()
        worker.mcp_client.call_tool = AsyncMock(return_value="ok")
        args = {"key": "value", "nested": {"a": 1}}
        result = await worker.execute({"tool": "complex_tool", "arguments": args})
        assert result.metadata["tool"] == "complex_tool"
        assert result.metadata["arguments"] == args
