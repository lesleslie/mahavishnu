"""Comprehensive unit tests for the TerminalAIWorker in mahavishnu.workers.terminal."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.base import WorkerResult
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
            command="qwen -o stream-json --approval-mode yolo",
            count=1,
        )
        assert qwen_worker.session_id == "session_abc"
        assert qwen_worker._status == WorkerStatus.RUNNING
        assert qwen_worker._start_time is not None

    @pytest.mark.asyncio
    async def test_start_claude_launches_correct_command(self, claude_worker, mock_terminal_manager):
        await claude_worker.start()
        mock_terminal_manager.launch_sessions.assert_called_once_with(
            command="claude --output-format stream-json --permission-mode acceptEdits",
            count=1,
        )
        assert claude_worker.session_id == "session_abc"
        assert claude_worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_returns_session_id(self, qwen_worker):
        session_id = await qwen_worker.start()
        assert session_id == "session_abc"

    @pytest.mark.asyncio
    async def test_start_unknown_ai_type_raises(self):
        mgr = AsyncMock()
        worker = TerminalAIWorker(mgr, "unknown_type")
        with pytest.raises(ValueError, match="Unknown AI type: unknown_type"):
            await worker.start()

    @pytest.mark.asyncio
    async def test_start_overwrites_existing_session_id(self, qwen_worker):
        qwen_worker.session_id = "old_session"
        await qwen_worker.start()
        assert qwen_worker.session_id == "session_abc"


class TestExecute:

    @pytest.mark.asyncio
    async def test_execute_auto_starts_when_no_session(self, qwen_worker, mock_terminal_manager):
        qwen_worker._monitor_completion = AsyncMock(return_value=WorkerResult(
            worker_id="session_abc",
            status=WorkerStatus.COMPLETED,
            output="done",
        ))
        await qwen_worker.execute({"prompt": "hello"})
        mock_terminal_manager.launch_sessions.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_skips_start_with_existing_session(self, worker_with_session, mock_terminal_manager):
        worker_with_session._monitor_completion = AsyncMock(return_value=WorkerResult(
            worker_id="existing_session",
            status=WorkerStatus.COMPLETED,
            output="done",
        ))
        await worker_with_session.execute({"prompt": "hello"})
        mock_terminal_manager.launch_sessions.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_sends_prompt(self, worker_with_session, mock_terminal_manager):
        worker_with_session._monitor_completion = AsyncMock(return_value=WorkerResult(
            worker_id="existing_session",
            status=WorkerStatus.COMPLETED,
            output="done",
        ))
        await worker_with_session.execute({"prompt": "write tests"})
        mock_terminal_manager.send_command.assert_called_once_with("existing_session", "write tests")

    @pytest.mark.asyncio
    async def test_execute_prepends_repo_path(self, worker_with_session, mock_terminal_manager):
        worker_with_session._monitor_completion = AsyncMock(return_value=WorkerResult(
            worker_id="existing_session",
            status=WorkerStatus.COMPLETED,
            output="done",
        ))
        await worker_with_session.execute({"prompt": "fix bug", "repo": "/path/to/repo"})
        mock_terminal_manager.send_command.assert_called_once_with(
            "existing_session",
            "Working in /path/to/repo. fix bug",
        )

    @pytest.mark.asyncio
    async def test_execute_with_empty_prompt(self, worker_with_session, mock_terminal_manager):
        worker_with_session._monitor_completion = AsyncMock(return_value=WorkerResult(
            worker_id="existing_session",
            status=WorkerStatus.COMPLETED,
            output="done",
        ))
        await worker_with_session.execute({})
        mock_terminal_manager.send_command.assert_called_once_with("existing_session", "")

    @pytest.mark.asyncio
    async def test_execute_stores_in_session_buddy(self, worker_with_session):
        mock_client = AsyncMock()
        worker_with_session.session_buddy_client = mock_client
        worker_with_session._monitor_completion = AsyncMock(return_value=WorkerResult(
            worker_id="existing_session",
            status=WorkerStatus.COMPLETED,
            output="result text",
            duration_seconds=5.0,
            exit_code=0,
        ))
        result = await worker_with_session.execute({"prompt": "do work"})
        mock_client.call_tool.assert_called_once_with(
            "store_memory",
            arguments={
                "content": "result text",
                "metadata": {
                    "type": "worker_execution",
                    "worker_id": "existing_session",
                    "worker_type": "qwen",
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
        worker_with_session._monitor_completion = AsyncMock(return_value=WorkerResult(
            worker_id="existing_session",
            status=WorkerStatus.COMPLETED,
            output="done",
        ))
        await worker_with_session.execute({"prompt": "do work"})

    @pytest.mark.asyncio
    async def test_execute_session_buddy_failure_does_not_propagate(self, worker_with_session):
        mock_client = AsyncMock()
        mock_client.call_tool.side_effect = RuntimeError("SB down")
        worker_with_session.session_buddy_client = mock_client
        worker_with_session._monitor_completion = AsyncMock(return_value=WorkerResult(
            worker_id="existing_session",
            status=WorkerStatus.COMPLETED,
            output="done",
        ))
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

    @pytest.mark.asyncio
    async def test_exception_is_caught_and_logged(self, worker_with_session):
        mock_client = AsyncMock()
        mock_client.call_tool.side_effect = ConnectionError("network error")
        worker_with_session.session_buddy_client = mock_client
        result = WorkerResult(worker_id="x", status=WorkerStatus.COMPLETED, output="o")
        await worker_with_session._store_result_in_session_buddy(result, {})


class TestMonitorCompletion:

    @pytest.mark.asyncio
    async def test_returns_on_finish_reason(self, worker_with_session, mock_terminal_manager):
        completion_line = json.dumps({"finish_reason": "stop"})
        mock_terminal_manager.capture_output.return_value = completion_line
        worker_with_session._is_complete = lambda d: "finish_reason" in d
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await worker_with_session._monitor_completion({"timeout": 5})
        assert result.status == WorkerStatus.COMPLETED
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_returns_on_done_key(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.capture_output.return_value = json.dumps({"done": True})
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await worker_with_session._monitor_completion({"timeout": 5})
        assert result.status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_returns_on_type_done(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.capture_output.return_value = json.dumps({"type": "done"})
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await worker_with_session._monitor_completion({"timeout": 5})
        assert result.status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_returns_on_type_completion(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.capture_output.return_value = json.dumps({"type": "completion"})
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await worker_with_session._monitor_completion({"timeout": 5})
        assert result.status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_returns_on_status_completed(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.capture_output.return_value = json.dumps({"status": "completed"})
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await worker_with_session._monitor_completion({"timeout": 5})
        assert result.status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_extracts_string_content_before_completion(self, worker_with_session, mock_terminal_manager):
        content_line = json.dumps({"content": "hello world"})
        done_line = json.dumps({"type": "done"})
        mock_terminal_manager.capture_output.return_value = f"{content_line}\n{done_line}"
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await worker_with_session._monitor_completion({"timeout": 5})
        assert "hello world" in result.output

    @pytest.mark.asyncio
    async def test_extracts_multimodal_content_before_completion(self, worker_with_session, mock_terminal_manager):
        content_line = json.dumps({"content": [{"type": "text", "text": "multi-modal output"}]})
        done_line = json.dumps({"type": "done"})
        mock_terminal_manager.capture_output.return_value = f"{content_line}\n{done_line}"
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await worker_with_session._monitor_completion({"timeout": 5})
        assert "multi-modal output" in result.output

    @pytest.mark.asyncio
    async def test_content_on_completion_line_is_not_captured(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.capture_output.return_value = json.dumps({
            "content": "lost content",
            "type": "done",
        })
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await worker_with_session._monitor_completion({"timeout": 5})
        assert "lost content" not in result.output

    @pytest.mark.asyncio
    async def test_handles_non_json_lines(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.capture_output.return_value = "plain text line\n" + json.dumps({"type": "done"})
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await worker_with_session._monitor_completion({"timeout": 5})
        assert "plain text line" in result.output

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_result(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.capture_output.return_value = ""
        call_count = 0
        original_time = asyncio.get_event_loop().time()

        def fake_time():
            nonlocal call_count
            call_count += 1
            return original_time + (call_count * 1000)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.time = fake_time
                result = await worker_with_session._monitor_completion({"timeout": 5})
        assert result.status == WorkerStatus.TIMEOUT
        assert result.error == "Task timed out"
        assert result.metadata["timeout"] == 5

    @pytest.mark.asyncio
    async def test_capture_output_exception_handled(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.capture_output.side_effect = RuntimeError("capture failed")
        call_count = 0
        original_time = asyncio.get_event_loop().time()

        def fake_time():
            nonlocal call_count
            call_count += 1
            return original_time + (call_count * 1000)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.time = fake_time
                result = await worker_with_session._monitor_completion({"timeout": 5})
        assert result.status == WorkerStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_multiple_content_chunks_accumulated(self, worker_with_session, mock_terminal_manager):
        chunk1 = json.dumps({"content": "chunk1"})
        chunk2 = json.dumps({"content": "chunk2"})
        chunk3 = json.dumps({"type": "done"})
        mock_terminal_manager.capture_output.return_value = f"{chunk1}\n{chunk2}\n{chunk3}"
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await worker_with_session._monitor_completion({"timeout": 5})
        assert "chunk1" in result.output
        assert "chunk2" in result.output

    @pytest.mark.asyncio
    async def test_multimodal_list_without_text_key_ignored(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.capture_output.return_value = json.dumps({
            "content": [{"type": "image", "url": "http://example.com/img.png"}],
            "type": "done",
        })
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await worker_with_session._monitor_completion({"timeout": 5})
        assert result.output == ""

    @pytest.mark.asyncio
    async def test_default_timeout_is_300(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.capture_output.return_value = ""
        call_count = 0
        original_time = asyncio.get_event_loop().time()

        def fake_time():
            nonlocal call_count
            call_count += 1
            return original_time + (call_count * 1000)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.time = fake_time
                result = await worker_with_session._monitor_completion({})
        assert result.metadata["timeout"] == 300


class TestIsComplete:

    def test_finish_reason_key(self, qwen_worker):
        assert qwen_worker._is_complete({"finish_reason": "stop"}) is True

    def test_done_key(self, qwen_worker):
        assert qwen_worker._is_complete({"done": True}) is True

    def test_type_done(self, qwen_worker):
        assert qwen_worker._is_complete({"type": "done"}) is True

    def test_type_completion(self, qwen_worker):
        assert qwen_worker._is_complete({"type": "completion"}) is True

    def test_status_completed(self, qwen_worker):
        assert qwen_worker._is_complete({"status": "completed"}) is True

    def test_not_complete(self, qwen_worker):
        assert qwen_worker._is_complete({"content": "still going"}) is False

    def test_empty_dict_not_complete(self, qwen_worker):
        assert qwen_worker._is_complete({}) is False

    def test_type_other_not_complete(self, qwen_worker):
        assert qwen_worker._is_complete({"type": "content"}) is False


class TestExtractContent:

    def test_delta_content_format(self, qwen_worker):
        result = qwen_worker._extract_content({"delta": {"content": "delta text"}})
        assert result == "delta text"

    def test_delta_without_content_key(self, qwen_worker):
        result = qwen_worker._extract_content({"delta": {"role": "assistant"}})
        assert result is None

    def test_delta_not_dict(self, qwen_worker):
        result = qwen_worker._extract_content({"delta": "string_delta"})
        assert result is None

    def test_text_field(self, qwen_worker):
        result = qwen_worker._extract_content({"text": "direct text"})
        assert result == "direct text"

    def test_content_string(self, qwen_worker):
        result = qwen_worker._extract_content({"content": "string content"})
        assert result == "string content"

    def test_content_list_with_text_item(self, qwen_worker):
        result = qwen_worker._extract_content({"content": [{"type": "text", "text": "list text"}]})
        assert result == "list text"

    def test_content_list_without_text_key(self, qwen_worker):
        result = qwen_worker._extract_content({"content": [{"type": "image"}]})
        assert result is None

    def test_content_empty_list(self, qwen_worker):
        result = qwen_worker._extract_content({"content": []})
        assert result is None

    def test_content_list_non_dict_item(self, qwen_worker):
        result = qwen_worker._extract_content({"content": ["plain_string"]})
        assert result is None

    def test_no_matching_keys(self, qwen_worker):
        result = qwen_worker._extract_content({"role": "assistant", "model": "qwen"})
        assert result is None

    def test_priority_delta_over_content(self, qwen_worker):
        result = qwen_worker._extract_content({
            "delta": {"content": "delta"},
            "content": "content",
        })
        assert result == "delta"

    def test_priority_text_over_content(self, qwen_worker):
        result = qwen_worker._extract_content({
            "text": "text_val",
            "content": "content_val",
        })
        assert result == "text_val"


class TestBuildResult:

    def test_build_result_with_start_time(self, worker_with_session):
        result = worker_with_session._build_result(["line1", "line2"], "last")
        assert result.status == WorkerStatus.COMPLETED
        assert result.worker_id == "existing_session"
        assert result.output == "line1\nline2"
        assert result.exit_code == 0
        assert result.error is None
        assert result.metadata["last_output"] == "last"
        assert result.metadata["output_lines"] == 2
        assert result.metadata["ai_type"] == "qwen"
        assert isinstance(result.duration_seconds, float)

    def test_build_result_without_start_time(self, qwen_worker):
        qwen_worker.session_id = "sid"
        result = qwen_worker._build_result(["out"], "last_out")
        assert result.duration_seconds == 0

    def test_build_result_empty_lines(self, worker_with_session):
        result = worker_with_session._build_result([], "")
        assert result.output == ""
        assert result.metadata["output_lines"] == 0


class TestGetCommandTemplate:

    def test_qwen_template(self, qwen_worker):
        template = qwen_worker._get_command_template()
        assert template == "qwen -o stream-json --approval-mode yolo"

    def test_claude_template(self, claude_worker):
        template = claude_worker._get_command_template()
        assert template == "claude --output-format stream-json --permission-mode acceptEdits"

    def test_unknown_type_raises(self):
        mgr = AsyncMock()
        worker = TerminalAIWorker(mgr, "invalid")
        with pytest.raises(ValueError, match="Unknown AI type: invalid"):
            worker._get_command_template()


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
    async def test_status_running_when_session_found(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.list_sessions.return_value = [
            {"id": "existing_session", "state": "active"},
        ]
        status = await worker_with_session.status()
        assert status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_status_transitions_to_completed_when_session_missing(self, worker_with_session, mock_terminal_manager):
        mock_terminal_manager.list_sessions.return_value = []
        worker_with_session._status = WorkerStatus.RUNNING
        status = await worker_with_session.status()
        assert status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_status_keeps_completed_when_not_running(self, worker_with_session, mock_terminal_manager):
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
        assert progress["ai_type"] == "qwen"

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
    async def test_progress_handles_capture_exception(self, worker_with_session, mock_terminal_manager):
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
