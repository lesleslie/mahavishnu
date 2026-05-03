"""Comprehensive tests for the GenericShellWorker class."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.base import WorkerResult
from mahavishnu.workers.generic_shell import GenericShellWorker
from mahavishnu.workers.registry import (
    WorkerCategory,
    WorkerConfig,
    get_worker_config,
    resolve_worker_type,
)


def _mock_terminal_manager() -> MagicMock:
    manager = MagicMock()
    manager.launch_sessions = AsyncMock(return_value=["session_123"])
    manager.send_command = AsyncMock()
    manager.capture_output = AsyncMock(return_value="")
    return manager


def _mock_session_buddy() -> AsyncMock:
    client = AsyncMock()
    client.call_tool = AsyncMock()
    return client


def _make_shell_worker(
    worker_type: str = "terminal-shell",
    terminal_manager: MagicMock | None = None,
    config: WorkerConfig | None = None,
    session_id: str | None = None,
    session_buddy_client: AsyncMock | None = None,
    **kwargs,
) -> GenericShellWorker:
    tm = terminal_manager or _mock_terminal_manager()
    return GenericShellWorker(
        terminal_manager=tm,
        worker_type=worker_type,
        config=config,
        session_id=session_id,
        session_buddy_client=session_buddy_client,
        **kwargs,
    )


class TestGenericShellWorkerInit:
    """Test GenericShellWorker initialization."""

    def test_init_loads_config_from_registry(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        assert worker.config is not None
        assert worker.config.worker_type == "terminal-shell"
        assert worker.worker_type == "terminal-shell"

    def test_init_with_explicit_config(self) -> None:
        cfg = WorkerConfig(
            name="Custom",
            worker_type="custom-worker",
            command="echo hello",
            category=WorkerCategory.SHELL,
        )
        worker = GenericShellWorker(
            terminal_manager=_mock_terminal_manager(),
            worker_type="custom-worker",
            config=cfg,
        )
        assert worker.config is cfg
        assert worker.config.name == "Custom"

    def test_init_raises_on_unknown_worker_type(self) -> None:
        with pytest.raises(ValueError, match="Unknown worker type: nonexistent"):
            GenericShellWorker(
                terminal_manager=_mock_terminal_manager(),
                worker_type="nonexistent",
            )

    def test_init_defaults(self) -> None:
        worker = _make_shell_worker()
        assert worker.session_id is None
        assert worker.session_buddy_client is None
        assert worker._start_time is None
        assert worker._status == WorkerStatus.PENDING
        assert worker._kwargs == {}

    def test_init_with_session_id(self) -> None:
        worker = _make_shell_worker(session_id="existing_session")
        assert worker.session_id == "existing_session"

    def test_init_with_session_buddy_client(self) -> None:
        sb = _mock_session_buddy()
        worker = _make_shell_worker(session_buddy_client=sb)
        assert worker.session_buddy_client is sb

    def test_init_ssh_requires_host(self) -> None:
        with pytest.raises(ValueError, match="SSH worker requires 'host' parameter"):
            GenericShellWorker(
                terminal_manager=_mock_terminal_manager(),
                worker_type="terminal-ssh",
            )

    def test_init_ssh_with_host(self) -> None:
        worker = GenericShellWorker(
            terminal_manager=_mock_terminal_manager(),
            worker_type="terminal-ssh",
            host="example.com",
        )
        assert worker._kwargs["host"] == "example.com"

    def test_init_stores_extra_kwargs(self) -> None:
        worker = GenericShellWorker(
            terminal_manager=_mock_terminal_manager(),
            worker_type="terminal-redis",
            host="localhost",
            port=6379,
        )
        assert worker._kwargs["host"] == "localhost"
        assert worker._kwargs["port"] == 6379


class TestFormatCommand:
    """Test _format_command method."""

    def test_format_command_no_prompt_placeholder(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        command = worker._format_command()
        assert command == "bash --noediting"

    def test_format_command_with_prompt(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-openclaw")
        command = worker._format_command("Do something")
        assert "Do something" in command

    def test_format_command_prompts_are_shell_quoted(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-openclaw")
        command = worker._format_command("arg with spaces")
        assert "'arg with spaces'" in command

    def test_format_command_raises_when_prompt_needed_but_missing(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-openclaw")
        with pytest.raises(ValueError, match="requires prompt but no prompt was provided"):
            worker._format_command()

    def test_format_command_with_kwargs(self) -> None:
        worker = GenericShellWorker(
            terminal_manager=_mock_terminal_manager(),
            worker_type="terminal-ssh",
            host="myserver",
        )
        command = worker._format_command()
        assert "ssh myserver" in command

    def test_format_command_raises_on_missing_kwarg(self) -> None:
        cfg = WorkerConfig(
            name="Bad",
            worker_type="bad",
            command="run --host={host} --port={port}",
            category=WorkerCategory.SHELL,
        )
        worker = GenericShellWorker(
            terminal_manager=_mock_terminal_manager(),
            worker_type="bad",
            config=cfg,
            host="localhost",
        )
        with pytest.raises(ValueError, match="Missing parameter for command"):
            worker._format_command()


class TestStart:
    """Test the start method."""

    @pytest.mark.asyncio
    async def test_start_launches_session(self) -> None:
        tm = _mock_terminal_manager()
        worker = _make_shell_worker(terminal_manager=tm)
        session_id = await worker.start()
        assert session_id == "session_123"
        tm.launch_sessions.assert_awaited_once_with(command="bash --noediting", count=1)
        assert worker.session_id == "session_123"
        assert worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_with_custom_launch_command(self) -> None:
        tm = _mock_terminal_manager()
        worker = _make_shell_worker(terminal_manager=tm)
        await worker.start(launch_command="custom command")
        tm.launch_sessions.assert_awaited_once_with(command="custom command", count=1)

    @pytest.mark.asyncio
    async def test_start_raises_without_terminal_manager(self) -> None:
        worker = GenericShellWorker(
            terminal_manager=None,
            worker_type="terminal-shell",
        )
        with pytest.raises(RuntimeError, match="terminal_manager is not available"):
            await worker.start()


class TestExecute:
    """Test the execute method."""

    @pytest.mark.asyncio
    async def test_execute_auto_starts_when_no_session(self) -> None:
        tm = _mock_terminal_manager()
        worker = _make_shell_worker(terminal_manager=tm, worker_type="terminal-shell")
        tm.capture_output = AsyncMock(return_value="$ ")
        result = await worker.execute({"prompt": "ls"})
        assert result.status == WorkerStatus.COMPLETED
        tm.launch_sessions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_sends_command_for_interactive_worker(self) -> None:
        tm = _mock_terminal_manager()
        tm.capture_output = AsyncMock(return_value=">>> ")
        worker = _make_shell_worker(terminal_manager=tm, worker_type="terminal-python")
        await worker.execute({"prompt": "print(1+1)"})
        tm.send_command.assert_awaited_once_with("session_123", "print(1+1)")

    @pytest.mark.asyncio
    async def test_execute_prompt_bound_auto_start(self) -> None:
        tm = _mock_terminal_manager()
        worker = _make_shell_worker(terminal_manager=tm, worker_type="terminal-openclaw")
        tm.capture_output = AsyncMock(return_value='{"text":"done"}')
        result = await worker.execute({"prompt": "hello"})
        assert result.status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_without_wait_for_completion(self) -> None:
        tm = _mock_terminal_manager()
        worker = _make_shell_worker(terminal_manager=tm, worker_type="terminal-shell")
        tm.capture_output = AsyncMock(return_value="some output")
        result = await worker.execute({"prompt": "ls", "wait_for_completion": False})
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "some output"

    @pytest.mark.asyncio
    async def test_execute_custom_timeout(self) -> None:
        tm = _mock_terminal_manager()
        worker = _make_shell_worker(terminal_manager=tm, worker_type="terminal-shell")
        tm.capture_output = AsyncMock(return_value="$ ")
        result = await worker.execute({"prompt": "sleep 10", "timeout": 5})
        assert result.metadata["timeout"] == 5

    @pytest.mark.asyncio
    async def test_execute_stores_result_in_session_buddy(self) -> None:
        tm = _mock_terminal_manager()
        sb = _mock_session_buddy()
        tm.capture_output = AsyncMock(return_value="$ ")
        worker = _make_shell_worker(
            terminal_manager=tm, worker_type="terminal-shell", session_buddy_client=sb
        )
        await worker.execute({"prompt": "ls"})
        sb.call_tool.assert_awaited_once()
        call_args = sb.call_tool.call_args
        assert call_args[0][0] == "store_memory"

    @pytest.mark.asyncio
    async def test_execute_without_session_buddy(self) -> None:
        tm = _mock_terminal_manager()
        tm.capture_output = AsyncMock(return_value="$ ")
        worker = _make_shell_worker(terminal_manager=tm, worker_type="terminal-shell")
        result = await worker.execute({"prompt": "ls"})
        assert result.status == WorkerStatus.COMPLETED


class TestMonitorCompletion:
    """Test _monitor_completion method."""

    @pytest.mark.asyncio
    async def test_monitor_completion_returns_on_text_marker(self) -> None:
        tm = _mock_terminal_manager()
        tm.capture_output = AsyncMock(return_value="output\n__MAHAVISHNU_DONE__")
        worker = _make_shell_worker(terminal_manager=tm, worker_type="terminal-clai")
        result = await worker._monitor_completion({}, 10)
        assert result.status == WorkerStatus.COMPLETED
        assert "output" in result.output

    @pytest.mark.asyncio
    async def test_monitor_completion_returns_on_json_valid(self) -> None:
        tm = _mock_terminal_manager()
        tm.capture_output = AsyncMock(return_value='{"text":"done"}')
        worker = _make_shell_worker(terminal_manager=tm, worker_type="terminal-openclaw")
        result = await worker._monitor_completion({}, 10)
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "done"

    @pytest.mark.asyncio
    async def test_monitor_completion_timeout(self) -> None:
        tm = _mock_terminal_manager()
        tm.capture_output = AsyncMock(return_value="still running...")

        worker = _make_shell_worker(terminal_manager=tm, worker_type="terminal-shell")

        with patch(
            "mahavishnu.workers.generic_shell.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            mock_sleep.side_effect = [None, asyncio.TimeoutError]
            result = await worker._monitor_completion({}, 0)
        assert result.status == WorkerStatus.TIMEOUT
        assert result.error == "Task timed out"

    @pytest.mark.asyncio
    async def test_monitor_completion_captures_error_on_exception(self) -> None:
        tm = _mock_terminal_manager()
        tm.capture_output = AsyncMock(side_effect=RuntimeError("capture failed"))

        worker = _make_shell_worker(terminal_manager=tm, worker_type="terminal-shell")

        with patch(
            "mahavishnu.workers.generic_shell.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            mock_sleep.side_effect = [None, asyncio.TimeoutError]
            result = await worker._monitor_completion({}, 0)
        assert result.status == WorkerStatus.TIMEOUT


class TestCheckJsonCompletion:
    """Test _check_json_completion method."""

    def test_empty_output(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-qwen")
        completed, content = worker._check_json_completion("")
        assert completed is False
        assert content is None

    def test_valid_json_with_complete_on_flag(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-openclaw")
        completed, content = worker._check_json_completion('{"text":"hello world"}')
        assert completed is True
        assert content == "hello world"

    def test_invalid_json_returns_false(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-qwen")
        completed, content = worker._check_json_completion("not json at all")
        assert completed is False
        assert content is None

    def test_json_line_with_completion_marker(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-qwen")
        completed, content = worker._check_json_completion('{"event":"done","text":"finished"}')
        assert completed is True
        assert content == "finished"

    def test_json_line_with_error_marker(self) -> None:
        cfg = WorkerConfig(
            name="TestErr",
            worker_type="test-err",
            command="test",
            category=WorkerCategory.AI_ASSISTANT,
            stream_format="json",
            completion_markers=["finish_reason"],
            error_markers=["error"],
            complete_on_valid_json=False,
        )
        worker = GenericShellWorker(
            terminal_manager=_mock_terminal_manager(),
            worker_type="test-err",
            config=cfg,
        )
        completed, content = worker._check_json_completion('{"error":"something went wrong"}')
        assert completed is True

    def test_json_line_without_marker_not_completed(self) -> None:
        cfg = WorkerConfig(
            name="Test",
            worker_type="test-json",
            command="test",
            category=WorkerCategory.AI_ASSISTANT,
            stream_format="json",
            completion_markers=["finish_reason"],
            error_markers=["error:"],
            complete_on_valid_json=False,
        )
        worker = GenericShellWorker(
            terminal_manager=_mock_terminal_manager(),
            worker_type="test-json",
            config=cfg,
        )
        completed, content = worker._check_json_completion('{"event":"chunk","text":"partial"}')
        assert completed is False

    def test_multiline_json_finds_marker(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-qwen")
        output = '{"event":"chunk"}\n{"event":"done","text":"final"}'
        completed, content = worker._check_json_completion(output)
        assert completed is True
        assert content == "final"


class TestExtractJsonContent:
    """Test _extract_json_content method."""

    def test_extracts_content_string(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-qwen")
        result = worker._extract_json_content({"content": "hello"})
        assert result == "hello"

    def test_extracts_content_list_of_dicts(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-qwen")
        data = {"content": [{"text": "first"}, {"text": "second"}]}
        result = worker._extract_json_content(data)
        assert result == "first second"

    def test_extracts_content_list_of_strings(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-qwen")
        data = {"content": ["line1", "line2"]}
        result = worker._extract_json_content(data)
        assert result == "line1 line2"

    def test_falls_back_to_text_field(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-qwen")
        result = worker._extract_json_content({"text": "direct text"})
        assert result == "direct text"

    def test_falls_back_to_delta_content(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-qwen")
        result = worker._extract_json_content({"delta": {"content": "streamed"}})
        assert result == "streamed"

    def test_falls_back_to_message_field(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-qwen")
        result = worker._extract_json_content({"message": "a message"})
        assert result == "a message"

    def test_falls_back_to_json_dumps(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-qwen")
        data = {"key": "value", "num": 42}
        result = worker._extract_json_content(data)
        parsed = json.loads(result)
        assert parsed == data


class TestCheckTextCompletion:
    """Test _check_text_completion method."""

    def test_empty_output(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        completed, content = worker._check_text_completion("")
        assert completed is False
        assert content is None

    def test_completion_marker_on_last_line(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        completed, content = worker._check_text_completion("output line\n$ ")
        assert completed is True
        assert content == "output line"

    def test_completion_marker_only_line(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        completed, content = worker._check_text_completion("$ ")
        assert completed is True
        assert content == ""

    def test_no_completion_marker(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        completed, content = worker._check_text_completion("still processing...")
        assert completed is False

    def test_error_marker_detected(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        completed, content = worker._check_text_completion("Error: something broke")
        assert completed is True
        assert content == "Error: something broke"

    def test_error_marker_case_insensitive(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        completed, content = worker._check_text_completion("error: lowercase error")
        assert completed is True

    def test_completion_marker_mid_line_not_detected(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        completed, content = worker._check_text_completion(
            "line with $ sign in middle\nmore output"
        )
        assert completed is False


class TestBuildResult:
    """Test _build_result method."""

    def test_build_result_success(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        worker.session_id = "sess_1"
        worker._start_time = 100.0
        with patch("mahavishnu.workers.generic_shell.asyncio") as mock_aio:
            mock_aio.get_event_loop.return_value.time.return_value = 105.0
            result = worker._build_result("hello world", "world", 60)
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "hello world"
        assert result.exit_code == 0
        assert result.duration_seconds == 5.0
        assert result.metadata["worker_type"] == "terminal-shell"

    def test_build_result_with_error_output(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        worker.session_id = "sess_1"
        worker._start_time = 100.0
        with patch("mahavishnu.workers.generic_shell.asyncio") as mock_aio:
            mock_aio.get_event_loop.return_value.time.return_value = 101.0
            result = worker._build_result("Error: crash", "crash", 60)
        assert result.status == WorkerStatus.FAILED
        assert result.error == "Error detected in output"
        assert result.exit_code == 1

    def test_build_result_no_start_time(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        worker.session_id = "sess_1"
        result = worker._build_result("output", "output", 60)
        assert result.duration_seconds == 0

    def test_build_result_no_session_id(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        worker.session_id = None
        result = worker._build_result("output", "output", 60)
        assert result.worker_id == "unknown"

    def test_build_result_metadata_category(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        worker.session_id = "s1"
        worker._start_time = 0.0
        with patch("mahavishnu.workers.generic_shell.asyncio") as mock_aio:
            mock_aio.get_event_loop.return_value.time.return_value = 1.0
            result = worker._build_result("out", "out", 30)
        assert result.metadata["category"] == "shell"
        assert result.metadata["timeout"] == 30

    def test_build_result_truncates_last_output(self) -> None:
        worker = _make_shell_worker(worker_type="terminal-shell")
        worker.session_id = "s1"
        worker._start_time = 0.0
        long_output = "x" * 300
        with patch("mahavishnu.workers.generic_shell.asyncio") as mock_aio:
            mock_aio.get_event_loop.return_value.time.return_value = 1.0
            result = worker._build_result("full output", long_output, 60)
        assert len(result.metadata["last_output"]) == 200


class TestStoreResultInSessionBuddy:
    """Test _store_result_in_session_buddy method."""

    @pytest.mark.asyncio
    async def test_stores_result_successfully(self) -> None:
        sb = _mock_session_buddy()
        worker = _make_shell_worker(session_buddy_client=sb)
        worker.session_id = "sess_1"
        result = WorkerResult(
            worker_id="sess_1",
            status=WorkerStatus.COMPLETED,
            output="done",
        )
        task = {"prompt": "test"}
        await worker._store_result_in_session_buddy(result, task)
        sb.call_tool.assert_awaited_once()
        args = sb.call_tool.call_args
        assert args[0][0] == "store_memory"
        meta = args[1]["arguments"]["metadata"]
        assert meta["worker_id"] == "sess_1"
        assert meta["status"] == "completed"

    @pytest.mark.asyncio
    async def test_noop_when_no_client(self) -> None:
        worker = _make_shell_worker()
        result = WorkerResult(worker_id="x", status=WorkerStatus.COMPLETED)
        await worker._store_result_in_session_buddy(result, {})
        assert True

    @pytest.mark.asyncio
    async def test_handles_client_error_gracefully(self) -> None:
        sb = _mock_session_buddy()
        sb.call_tool = AsyncMock(side_effect=RuntimeError("connection lost"))
        worker = _make_shell_worker(session_buddy_client=sb)
        worker.session_id = "s1"
        result = WorkerResult(worker_id="s1", status=WorkerStatus.COMPLETED, output="out")
        await worker._store_result_in_session_buddy(result, {"prompt": "test"})
        assert True


class TestStop:
    """Test the stop method."""

    @pytest.mark.asyncio
    async def test_stop_closes_session(self) -> None:
        tm = _mock_terminal_manager()
        tm.close_session = AsyncMock()
        worker = _make_shell_worker(terminal_manager=tm, session_id="sess_1")
        await worker.stop()
        tm.close_session.assert_awaited_once_with("sess_1")
        assert worker._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stop_no_session(self) -> None:
        tm = _mock_terminal_manager()
        tm.close_session = AsyncMock()
        worker = _make_shell_worker(terminal_manager=tm)
        worker.session_id = None
        await worker.stop()
        tm.close_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stop_handles_close_error(self) -> None:
        tm = _mock_terminal_manager()
        tm.close_session = AsyncMock(side_effect=RuntimeError("already closed"))
        worker = _make_shell_worker(terminal_manager=tm, session_id="sess_1")
        await worker.stop()
        assert worker._status == WorkerStatus.COMPLETED


class TestStatus:
    """Test the status method."""

    @pytest.mark.asyncio
    async def test_status_running_when_session_found(self) -> None:
        tm = _mock_terminal_manager()
        tm.list_sessions = AsyncMock(return_value=[{"id": "sess_1"}])
        worker = _make_shell_worker(terminal_manager=tm, session_id="sess_1")
        status = await worker.status()
        assert status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_status_completed_when_session_not_found(self) -> None:
        tm = _mock_terminal_manager()
        tm.list_sessions = AsyncMock(return_value=[{"id": "other_session"}])
        worker = _make_shell_worker(terminal_manager=tm, session_id="sess_1")
        worker._status = WorkerStatus.RUNNING
        status = await worker.status()
        assert status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_status_no_session(self) -> None:
        tm = _mock_terminal_manager()
        worker = _make_shell_worker(terminal_manager=tm)
        worker.session_id = None
        status = await worker.status()
        assert status == WorkerStatus.PENDING

    @pytest.mark.asyncio
    async def test_status_handles_list_error(self) -> None:
        tm = _mock_terminal_manager()
        tm.list_sessions = AsyncMock(side_effect=RuntimeError("boom"))
        worker = _make_shell_worker(terminal_manager=tm, session_id="sess_1")
        worker._status = WorkerStatus.RUNNING
        status = await worker.status()
        assert status == WorkerStatus.COMPLETED


class TestGetProgress:
    """Test the get_progress method."""

    @pytest.mark.asyncio
    async def test_progress_with_session(self) -> None:
        tm = _mock_terminal_manager()
        tm.capture_output = AsyncMock(return_value="processing 50%")
        worker = _make_shell_worker(terminal_manager=tm, session_id="sess_1")
        worker._start_time = 100.0
        with patch("mahavishnu.workers.generic_shell.asyncio") as mock_aio:
            mock_aio.get_event_loop.return_value.time.return_value = 110.0
            progress = await worker.get_progress()
        assert progress["session_id"] == "sess_1"
        assert progress["output_preview"] == "processing 50%"
        assert progress["duration_seconds"] == 10.0
        assert progress["worker_type"] == "terminal-shell"

    @pytest.mark.asyncio
    async def test_progress_without_session(self) -> None:
        tm = _mock_terminal_manager()
        worker = _make_shell_worker(terminal_manager=tm)
        worker.session_id = None
        progress = await worker.get_progress()
        assert progress["session_id"] is None
        assert progress["output_preview"] == ""

    @pytest.mark.asyncio
    async def test_progress_handles_capture_error(self) -> None:
        tm = _mock_terminal_manager()
        tm.capture_output = AsyncMock(side_effect=RuntimeError("capture failed"))
        worker = _make_shell_worker(terminal_manager=tm, session_id="sess_1")
        worker._start_time = 0.0
        with patch("mahavishnu.workers.generic_shell.asyncio") as mock_aio:
            mock_aio.get_event_loop.return_value.time.return_value = 1.0
            progress = await worker.get_progress()
        assert progress["output_preview"] == ""

    @pytest.mark.asyncio
    async def test_progress_truncates_long_output(self) -> None:
        tm = _mock_terminal_manager()
        long_output = "x" * 300
        tm.capture_output = AsyncMock(return_value=long_output)
        worker = _make_shell_worker(terminal_manager=tm, session_id="sess_1")
        worker._start_time = 0.0
        with patch("mahavishnu.workers.generic_shell.asyncio") as mock_aio:
            mock_aio.get_event_loop.return_value.time.return_value = 1.0
            progress = await worker.get_progress()
        assert len(progress["output_preview"]) == 200

    @pytest.mark.asyncio
    async def test_progress_includes_category(self) -> None:
        tm = _mock_terminal_manager()
        worker = _make_shell_worker(terminal_manager=tm, session_id="sess_1")
        worker._start_time = 0.0
        with patch("mahavishnu.workers.generic_shell.asyncio") as mock_aio:
            mock_aio.get_event_loop.return_value.time.return_value = 1.0
            progress = await worker.get_progress()
        assert progress["category"] == "shell"


class TestRegistryIntegration:
    """Test integration with the worker registry."""

    def test_terminal_opencode_not_registered(self) -> None:
        assert get_worker_config("terminal-opencode") is None

    def test_terminal_aider_not_registered(self) -> None:
        assert get_worker_config("terminal-aider") is None

    def test_openclaw_json_agent_mode(self) -> None:
        config = get_worker_config("terminal-openclaw")
        assert config is not None
        assert config.stream_format == "json"
        assert config.complete_on_valid_json is True
        assert "openclaw agent" in config.command

    def test_deepagents_marker_mode(self) -> None:
        config = get_worker_config("terminal-deepagents")
        assert config is not None
        assert config.completion_markers == ["__MAHAVISHNU_DONE__"]
        assert "--non-interactive" in config.command

    def test_clai_marker_mode(self) -> None:
        config = get_worker_config("terminal-clai")
        assert config is not None
        assert config.completion_markers == ["__MAHAVISHNU_DONE__"]

    def test_codex_marker_mode(self) -> None:
        config = get_worker_config("terminal-codex")
        assert config is not None
        assert config.completion_markers == ["__MAHAVISHNU_DONE__"]

    def test_qwen_cli_config(self) -> None:
        config = get_worker_config("terminal-qwen")
        assert config is not None
        assert config.command == "sh -lc 'qwen -o stream-json --approval-mode yolo'"

    def test_claude_cli_config(self) -> None:
        config = get_worker_config("terminal-claude")
        assert config is not None
        assert "claude --output-format stream-json" in config.command

    def test_resolve_worker_type_routes_communication(self) -> None:
        resolved = resolve_worker_type(
            "terminal-qwen",
            task_type="notification",
            prompt="Notify Slack with status update",
        )
        assert resolved == "terminal-openclaw"

    def test_resolve_worker_type_gateway_when_configured(self, monkeypatch) -> None:
        monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "http://localhost:8787")
        resolved = resolve_worker_type(
            "terminal-claude",
            task_type="notification",
            prompt="Send Slack handoff",
        )
        assert resolved == "gateway-openclaw"

    def test_resolve_worker_type_keeps_coding(self) -> None:
        resolved = resolve_worker_type(
            "terminal-qwen",
            task_type="code_generation",
            prompt="Implement FastAPI endpoint",
        )
        assert resolved == "terminal-qwen"

    def test_resolve_worker_type_codex_communication(self) -> None:
        resolved = resolve_worker_type(
            "terminal-codex",
            task_type="notification",
            prompt="Notify Slack",
        )
        assert resolved == "terminal-openclaw"
