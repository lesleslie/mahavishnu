"""Comprehensive unit tests for the TerminalAIWorker in mahavishnu.workers.terminal."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.base import WorkerResult
from mahavishnu.workers.generic_shell import GenericShellWorker
from mahavishnu.workers.protocol import is_terminal_worker
from mahavishnu.workers.registry import get_worker_config
from mahavishnu.workers.terminal import TerminalAIWorker


@pytest.fixture
def mock_terminal_manager():
    manager = AsyncMock()
    manager.launch_sessions = AsyncMock(return_value=["session_abc"])
    manager.send_command = AsyncMock()
    manager.capture_output = AsyncMock(return_value="")
    manager.close_session = AsyncMock()
    manager.list_sessions = AsyncMock(return_value=[])
    return manager


@pytest.fixture
def qwen_worker(mock_terminal_manager):
    return TerminalAIWorker(
        terminal_manager=mock_terminal_manager,
        ai_type="qwen",
    )


@pytest.fixture
def claude_worker(mock_terminal_manager):
    return TerminalAIWorker(
        terminal_manager=mock_terminal_manager,
        ai_type="claude",
    )


@pytest.fixture
def worker_with_session(mock_terminal_manager):
    worker = TerminalAIWorker(
        terminal_manager=mock_terminal_manager,
        ai_type="qwen",
        session_id="existing_session",
    )
    worker._status = WorkerStatus.RUNNING
    worker._start_time = 1000.0
    return worker


class TestInitialization:
    def test_default_state_is_pending(self, qwen_worker):
        assert qwen_worker._status == WorkerStatus.PENDING
        assert qwen_worker._start_time is None
        assert qwen_worker.session_buddy_client is None

    def test_qwen_worker_type(self, qwen_worker):
        assert qwen_worker.worker_type == "terminal-qwen"

    def test_claude_worker_type(self, claude_worker):
        assert claude_worker.worker_type == "terminal-claude"

    def test_session_id_stored(self):
        mgr = AsyncMock()
        worker = TerminalAIWorker(mgr, "qwen", session_id="pre_set")
        assert worker.session_id == "pre_set"

    def test_session_buddy_client_stored(self):
        client = MagicMock()
        mgr = AsyncMock()
        worker = TerminalAIWorker(mgr, "qwen", session_buddy_client=client)
        assert worker.session_buddy_client is client


class TestStart:
    @pytest.mark.asyncio
    async def test_start_qwen_launches_correct_command(self, qwen_worker, mock_terminal_manager):
        await qwen_worker.start()
        mock_terminal_manager.launch_sessions.assert_called_once_with(
            command=get_worker_config("terminal-qwen").command,
            count=1,
        )
        assert qwen_worker.session_id == "session_abc"
        assert qwen_worker._status == WorkerStatus.RUNNING
        assert qwen_worker._start_time is not None

    @pytest.mark.asyncio
    async def test_start_claude_launches_correct_command(
        self, claude_worker, mock_terminal_manager
    ):
        await claude_worker.start()
        mock_terminal_manager.launch_sessions.assert_called_once_with(
            command=get_worker_config("terminal-claude").command,
            count=1,
        )
        assert claude_worker.session_id == "session_abc"
        assert claude_worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_returns_session_id(self, qwen_worker):
        session_id = await qwen_worker.start()
        assert session_id == "session_abc"

    def test_init_unknown_ai_type_raises(self):
        mgr = AsyncMock()
        with pytest.raises(ValueError, match="Unknown worker type: terminal-unknown_type"):
            TerminalAIWorker(mgr, "unknown_type")

    @pytest.mark.asyncio
    async def test_start_overwrites_existing_session_id(self, qwen_worker):
        qwen_worker.session_id = "old_session"
        await qwen_worker.start()
        assert qwen_worker.session_id == "session_abc"


class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_auto_starts_when_no_session(self, qwen_worker, mock_terminal_manager):
        qwen_worker._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="session_abc",
                status=WorkerStatus.COMPLETED,
                output="done",
            )
        )
        await qwen_worker.execute({"prompt": "hello"})
        mock_terminal_manager.launch_sessions.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_skips_start_with_existing_session(
        self, worker_with_session, mock_terminal_manager
    ):
        worker_with_session._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="existing_session",
                status=WorkerStatus.COMPLETED,
                output="done",
            )
        )
        await worker_with_session.execute({"prompt": "hello"})
        mock_terminal_manager.launch_sessions.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_sends_prompt(self, worker_with_session, mock_terminal_manager):
        worker_with_session._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="existing_session",
                status=WorkerStatus.COMPLETED,
                output="done",
            )
        )
        await worker_with_session.execute({"prompt": "write tests"})
        mock_terminal_manager.send_command.assert_called_once_with(
            "existing_session", "write tests"
        )

    @pytest.mark.asyncio
    async def test_execute_prepends_repo_path(self, worker_with_session, mock_terminal_manager):
        worker_with_session._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="existing_session",
                status=WorkerStatus.COMPLETED,
                output="done",
            )
        )
        await worker_with_session.execute({"prompt": "fix bug", "repo": "/path/to/repo"})
        mock_terminal_manager.send_command.assert_called_once_with(
            "existing_session",
            "Working in /path/to/repo. fix bug",
        )

    @pytest.mark.asyncio
    async def test_execute_with_empty_prompt(self, worker_with_session, mock_terminal_manager):
        worker_with_session._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="existing_session",
                status=WorkerStatus.COMPLETED,
                output="done",
            )
        )
        await worker_with_session.execute({})
        mock_terminal_manager.send_command.assert_called_once_with("existing_session", "")

    @pytest.mark.asyncio
    async def test_execute_with_repo_and_empty_prompt(
        self, worker_with_session, mock_terminal_manager
    ):
        worker_with_session._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="existing_session",
                status=WorkerStatus.COMPLETED,
                output="done",
            )
        )
        await worker_with_session.execute({"prompt": "", "repo": "/some/repo"})
        mock_terminal_manager.send_command.assert_called_once_with(
            "existing_session",
            "Working in /some/repo. ",
        )

    @pytest.mark.asyncio
    async def test_execute_stores_in_session_buddy(self, worker_with_session):
        mock_client = AsyncMock()
        worker_with_session.session_buddy_client = mock_client
        worker_with_session._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="existing_session",
                status=WorkerStatus.COMPLETED,
                output="result text",
                duration_seconds=5.0,
                exit_code=0,
            )
        )
        result = await worker_with_session.execute({"prompt": "do work"})
        mock_client.call_tool.assert_called_once_with(
            "store_memory",
            arguments={
                "content": "result text",
                "metadata": {
                    "type": "worker_execution",
                    "worker_id": "existing_session",
                    "worker_type": "terminal-qwen",
                    "worker_name": "Qwen AI",
                    "category": "ai_assistant",
                    "task_prompt": "do work",
                    "status": "completed",
                    "duration_seconds": 5.0,
                    "exit_code": 0,
                    "error": None,
                    "timestamp": result.timestamp,
                },
            },
        )

    @pytest.mark.asyncio
    async def test_execute_skips_session_buddy_when_no_client(self, worker_with_session):
        worker_with_session.session_buddy_client = None
        worker_with_session._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="existing_session",
                status=WorkerStatus.COMPLETED,
                output="done",
            )
        )
        await worker_with_session.execute({"prompt": "do work"})

    @pytest.mark.asyncio
    async def test_execute_session_buddy_failure_does_not_propagate(self, worker_with_session):
        mock_client = AsyncMock()
        mock_client.call_tool.side_effect = RuntimeError("SB down")
        worker_with_session.session_buddy_client = mock_client
        worker_with_session._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="existing_session",
                status=WorkerStatus.COMPLETED,
                output="done",
            )
        )
        result = await worker_with_session.execute({"prompt": "do work"})
        assert result.status == WorkerStatus.COMPLETED


class TestStoreResultInSessionBuddy:
    @pytest.mark.asyncio
    async def test_noop_when_no_client(self, worker_with_session):
        worker_with_session.session_buddy_client = None
        result = WorkerResult(worker_id="x", status=WorkerStatus.COMPLETED, output="o")
        await worker_with_session._store_result_in_session_buddy(result, {"prompt": "p"})

    @pytest.mark.asyncio
    async def test_calls_store_memory_with_correct_args(self, worker_with_session):
        mock_client = AsyncMock()
        worker_with_session.session_buddy_client = mock_client
        result = WorkerResult(
            worker_id="sid",
            status=WorkerStatus.FAILED,
            output="partial",
            error="boom",
            exit_code=1,
            duration_seconds=3.0,
        )
        await worker_with_session._store_result_in_session_buddy(result, {"prompt": "fail task"})
        mock_client.call_tool.assert_called_once()
        call_args = mock_client.call_tool.call_args
        assert call_args[0][0] == "store_memory"
        meta = call_args[1]["arguments"]["metadata"]
        assert meta["error"] == "boom"
        assert meta["exit_code"] == 1
        assert meta["status"] == "failed"
        assert meta["worker_name"] == "Qwen AI"
        assert meta["category"] == "ai_assistant"

    @pytest.mark.asyncio
    async def test_exception_is_caught_and_logged(self, worker_with_session):
        mock_client = AsyncMock()
        mock_client.call_tool.side_effect = ConnectionError("network error")
        worker_with_session.session_buddy_client = mock_client
        result = WorkerResult(worker_id="x", status=WorkerStatus.COMPLETED, output="o")
        await worker_with_session._store_result_in_session_buddy(result, {})


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_closes_session(self, worker_with_session, mock_terminal_manager):
        await worker_with_session.stop()
        mock_terminal_manager.close_session.assert_called_once_with("existing_session")
        assert worker_with_session._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stop_without_session(self, qwen_worker, mock_terminal_manager):
        qwen_worker.session_id = None
        await qwen_worker.stop()
        mock_terminal_manager.close_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_handles_close_exception(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.close_session.side_effect = RuntimeError("close failed")
        await worker_with_session.stop()
        assert worker_with_session._status == WorkerStatus.COMPLETED


class TestStatus:
    @pytest.mark.asyncio
    async def test_status_running_when_session_found(
        self, worker_with_session, mock_terminal_manager
    ):
        mock_terminal_manager.list_sessions.return_value = [
            {"id": "existing_session", "state": "active"},
        ]
        status = await worker_with_session.status()
        assert status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_status_transitions_to_completed_when_session_missing(
        self, worker_with_session, mock_terminal_manager
    ):
        mock_terminal_manager.list_sessions.return_value = []
        worker_with_session._status = WorkerStatus.RUNNING
        status = await worker_with_session.status()
        assert status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_status_keeps_completed_when_not_running(
        self, worker_with_session, mock_terminal_manager
    ):
        worker_with_session._status = WorkerStatus.COMPLETED
        mock_terminal_manager.list_sessions.return_value = []
        status = await worker_with_session.status()
        assert status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_status_handles_list_exception(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.list_sessions.side_effect = RuntimeError("list failed")
        worker_with_session._status = WorkerStatus.RUNNING
        status = await worker_with_session.status()
        assert status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_status_without_session_id(self, qwen_worker):
        qwen_worker.session_id = None
        qwen_worker._status = WorkerStatus.PENDING
        status = await qwen_worker.status()
        assert status == WorkerStatus.PENDING

    @pytest.mark.asyncio
    async def test_status_scans_multiple_sessions(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.list_sessions.return_value = [
            {"id": "other_session"},
            {"id": "existing_session"},
        ]
        status = await worker_with_session.status()
        assert status == WorkerStatus.RUNNING


class TestGetProgress:
    @pytest.mark.asyncio
    async def test_progress_without_session(self, qwen_worker):
        progress = await qwen_worker.get_progress()
        assert progress["session_id"] is None
        assert progress["output_preview"] == ""
        assert progress["worker_type"] == "terminal-qwen"
        assert progress["worker_name"] == "Qwen AI"

    @pytest.mark.asyncio
    async def test_progress_with_session(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.capture_output.return_value = "some output here"
        progress = await worker_with_session.get_progress()
        assert progress["session_id"] == "existing_session"
        assert progress["output_preview"] == "some output here"
        assert progress["worker_type"] == "terminal-qwen"

    @pytest.mark.asyncio
    async def test_progress_truncates_long_output(self, worker_with_session, mock_terminal_manager):
        long_output = "x" * 300
        mock_terminal_manager.capture_output.return_value = long_output
        progress = await worker_with_session.get_progress()
        assert len(progress["output_preview"]) == 200

    @pytest.mark.asyncio
    async def test_progress_handles_capture_exception(
        self, worker_with_session, mock_terminal_manager
    ):
        mock_terminal_manager.capture_output.side_effect = RuntimeError("fail")
        progress = await worker_with_session.get_progress()
        assert progress["output_preview"] == ""

    @pytest.mark.asyncio
    async def test_progress_includes_duration(self, worker_with_session):
        progress = await worker_with_session.get_progress()
        assert progress["duration_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_progress_includes_status_value(self, worker_with_session):
        worker_with_session._status = WorkerStatus.RUNNING
        progress = await worker_with_session.get_progress()
        assert progress["status"] == "running"


class TestProtocolConformance:
    """Verify that concrete worker classes satisfy TerminalWorkerProtocol."""

    def test_generic_shell_worker_satisfies_protocol(self):
        worker = GenericShellWorker(
            terminal_manager=AsyncMock(),
            worker_type="terminal-shell",
        )
        assert is_terminal_worker(worker)

    def test_terminal_ai_worker_satisfies_protocol(self):
        worker = TerminalAIWorker(terminal_manager=AsyncMock(), ai_type="qwen")
        assert is_terminal_worker(worker)

    def test_non_worker_does_not_satisfy_protocol(self):
        assert not is_terminal_worker(object())

    def test_worker_name_is_raw_ai_type_not_config_name(self, qwen_worker):
        # worker_name is the raw ai_type for backward compatibility
        assert qwen_worker.worker_name == "qwen"
        # config.name is the full registry label used in session-buddy metadata
        assert qwen_worker.config.name == "Qwen AI"
        assert qwen_worker.worker_name != qwen_worker.config.name
