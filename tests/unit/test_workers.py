"""Unit tests for Mahavishnu worker system."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import pytest

from mahavishnu.workers.base import BaseWorker, WorkerResult, WorkerStatus
from mahavishnu.workers.terminal import TerminalAIWorker
from mahavishnu.workers.container import ContainerWorker
from mahavishnu.workers.debug_monitor import DebugMonitorWorker
from mahavishnu.workers.manager import WorkerManager


# ============================================================================
# Base Worker Tests
# ============================================================================

class TestWorkerStatus:
    """Test WorkerStatus enum."""

    def test_worker_status_values(self):
        """Test that WorkerStatus has all expected values."""
        assert WorkerStatus.PENDING.value == "pending"
        assert WorkerStatus.STARTING.value == "starting"
        assert WorkerStatus.RUNNING.value == "running"
        assert WorkerStatus.COMPLETED.value == "completed"
        assert WorkerStatus.FAILED.value == "failed"
        assert WorkerStatus.TIMEOUT.value == "timeout"
        assert WorkerStatus.CANCELLED.value == "cancelled"


class TestWorkerResult:
    """Test WorkerResult dataclass."""

    def test_worker_result_creation(self):
        """Test creating a WorkerResult."""
        result = WorkerResult(
            worker_id="test_worker",
            status=WorkerStatus.COMPLETED,
            output="Success!",
            error=None,
            exit_code=0,
            duration_seconds=1.5,
            metadata={"key": "value"},
        )

        assert result.worker_id == "test_worker"
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "Success!"
        assert result.error is None
        assert result.exit_code == 0
        assert result.duration_seconds == 1.5
        assert result.metadata == {"key": "value"}

    def test_worker_result_is_success(self):
        """Test is_success method."""
        success_result = WorkerResult(
            worker_id="test",
            status=WorkerStatus.COMPLETED,
            output="OK",
            error=None,
            exit_code=0,
            duration_seconds=1.0,
            metadata={},
        )

        failure_result = WorkerResult(
            worker_id="test",
            status=WorkerStatus.FAILED,
            output=None,
            error="Error!",
            exit_code=1,
            duration_seconds=1.0,
            metadata={},
        )

        assert success_result.is_success() is True
        assert failure_result.is_success() is False

    def test_worker_result_to_dict(self):
        """Test to_dict method."""
        result = WorkerResult(
            worker_id="test_worker",
            status=WorkerStatus.COMPLETED,
            output="Success!",
            error=None,
            exit_code=0,
            duration_seconds=1.5,
            metadata={"key": "value"},
        )

        result_dict = result.to_dict()

        assert result_dict["worker_id"] == "test_worker"
        assert result_dict["status"] == "completed"
        assert result_dict["output"] == "Success!"
        assert result_dict["error"] is None
        assert result_dict["exit_code"] == 0
        assert result_dict["duration_seconds"] == 1.5
        assert result_dict["metadata"] == {"key": "value"}

    def test_worker_result_from_dict(self):
        """Test from_dict class method."""
        data = {
            "worker_id": "test_worker",
            "status": "completed",
            "output": "Success!",
            "error": None,
            "exit_code": 0,
            "duration_seconds": 1.5,
            "metadata": {"key": "value"},
        }

        result = WorkerResult.from_dict(data)

        assert result.worker_id == "test_worker"
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "Success!"


class TestBaseWorker:
    """Test BaseWorker abstract class."""

    def test_base_worker_cannot_be_instantiated(self):
        """Test that BaseWorker cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseWorker(worker_type="test")


# ============================================================================
# Terminal AI Worker Tests
# ============================================================================

@pytest.fixture
def mock_terminal_manager():
    """Create a mock TerminalManager."""
    manager = MagicMock()
    manager.launch_sessions = AsyncMock(return_value=["session_123"])
    manager.send_input = AsyncMock()
    manager.send_command = AsyncMock()
    manager.close_session = AsyncMock()
    manager.list_sessions = AsyncMock(return_value=[{"id": "session_123", "status": "running"}])
    manager.capture_output = AsyncMock(return_value="")
    return manager


@pytest.fixture
def terminal_qwen_worker(mock_terminal_manager):
    """Create a TerminalAIWorker for Qwen."""
    return TerminalAIWorker(
        terminal_manager=mock_terminal_manager,
        ai_type="qwen",
        session_id="session_123",
        session_buddy_client=None,
    )


@pytest.fixture
def terminal_claude_worker(mock_terminal_manager):
    """Create a TerminalAIWorker for Claude."""
    return TerminalAIWorker(
        terminal_manager=mock_terminal_manager,
        ai_type="claude",
        session_id="session_123",
        session_buddy_client=None,
    )


class TestTerminalAIWorker:
    """Test TerminalAIWorker class."""

    def test_initialization_qwen(self, terminal_qwen_worker):
        """Test Qwen worker initialization."""
        assert terminal_qwen_worker.ai_type == "qwen"
        assert terminal_qwen_worker.session_id == "session_123"
        assert terminal_qwen_worker.worker_type == "terminal-qwen"

    def test_initialization_claude(self, terminal_claude_worker):
        """Test Claude worker initialization."""
        assert terminal_claude_worker.ai_type == "claude"
        assert terminal_claude_worker.session_id == "session_123"
        assert terminal_claude_worker.worker_type == "terminal-claude"

    def test_command_template_qwen(self, terminal_qwen_worker):
        """Test Qwen command template."""
        template = terminal_qwen_worker._get_command_template()
        assert "qwen" in template
        assert "stream-json" in template

    def test_command_template_claude(self, terminal_claude_worker):
        """Test Claude command template."""
        template = terminal_claude_worker._get_command_template()
        assert "claude" in template
        assert "stream-json" in template

    @pytest.mark.asyncio
    async def test_start_qwen(self, terminal_qwen_worker, mock_terminal_manager):
        """Test starting Qwen worker."""
        session_id = await terminal_qwen_worker.start()

        assert session_id == "session_123"
        mock_terminal_manager.launch_sessions.assert_called_once()
        assert terminal_qwen_worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_execute_task(self, terminal_qwen_worker, mock_terminal_manager):
        """Test executing a task."""
        # Mock the output parsing
        terminal_qwen_worker._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="session_123",
                status=WorkerStatus.COMPLETED,
                output="Task completed",
                error=None,
                exit_code=0,
                duration_seconds=2.0,
                metadata={},
            )
        )

        result = await terminal_qwen_worker.execute({"prompt": "Test task"})

        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "Task completed"
        mock_terminal_manager.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_status_running(self, terminal_qwen_worker):
        """Test status when running."""
        terminal_qwen_worker._status = WorkerStatus.RUNNING
        status = await terminal_qwen_worker.status()
        assert status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_stop(self, terminal_qwen_worker, mock_terminal_manager):
        """Test stopping worker."""
        await terminal_qwen_worker.stop()

        mock_terminal_manager.close_session.assert_called_once_with("session_123")
        assert terminal_qwen_worker._status == WorkerStatus.COMPLETED


# ============================================================================
# Container Worker Tests
# ============================================================================

class TestContainerWorker:
    """Test ContainerWorker class."""

    def test_initialization(self):
        """Test container worker initialization."""
        worker = ContainerWorker(
            runtime="docker",
            image="python:3.13-slim",
            session_buddy_client=None,
        )

        assert worker.runtime == "docker"
        assert worker.image == "python:3.13-slim"
        assert worker.worker_type == "container-executor"
        assert worker.container_id is None

    @pytest.mark.asyncio
    async def test_start_container_success(self):
        """Test starting a container successfully."""
        worker = ContainerWorker(runtime="docker", image="python:3.13-slim")

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            # Mock successful container launch
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"container_123\n", b""))

            mock_subprocess.return_value = mock_proc

            container_id = await worker.start()

            assert container_id == "container_123"
            assert worker._status == WorkerStatus.RUNNING
            assert worker._running is True

    @pytest.mark.asyncio
    async def test_start_container_failure(self):
        """Test container start failure."""
        worker = ContainerWorker(runtime="docker", image="python:3.13-slim")

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            # Mock failed container launch
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"Error: image not found"))

            mock_subprocess.return_value = mock_proc

            with pytest.raises(RuntimeError, match="Failed to launch container"):
                await worker.start()

            assert worker._status == WorkerStatus.FAILED

    @pytest.mark.asyncio
    async def test_execute_command_success(self):
        """Test executing command in container."""
        worker = ContainerWorker(runtime="docker", image="python:3.13-slim")
        worker.container_id = "container_123"
        worker._running = True

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            # Mock successful command execution
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"42\n", b""))

            mock_subprocess.return_value = mock_proc

            result = await worker.execute({"command": "echo 42"})

            assert result.status == WorkerStatus.COMPLETED
            assert result.output == "42\n"
            assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_execute_command_failure(self):
        """Test command execution failure."""
        worker = ContainerWorker(runtime="docker", image="python:3.13-slim")
        worker.container_id = "container_123"
        worker._running = True

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            # Mock failed command execution
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"Error: command not found"))

            mock_subprocess.return_value = mock_proc

            result = await worker.execute({"command": "invalid_command"})

            assert result.status == WorkerStatus.FAILED
            assert "Error: command not found" in result.error
            assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_execute_without_command(self):
        """Test executing without command raises error."""
        worker = ContainerWorker(runtime="docker", image="python:3.13-slim")
        worker.container_id = "container_123"

        with pytest.raises(ValueError, match="must specify 'command'"):
            await worker.execute({})

    @pytest.mark.asyncio
    async def test_stop_container(self):
        """Test stopping container."""
        worker = ContainerWorker(runtime="docker", image="python:3.13-slim")
        worker.container_id = "container_123"
        worker._running = True

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_subprocess.return_value = mock_proc

            await worker.stop()

            assert worker._running is False
            assert worker.container_id is None
            assert worker._status == WorkerStatus.COMPLETED


# ============================================================================
# Debug Monitor Worker Tests
# ============================================================================

@pytest.fixture
def mock_terminal_manager_for_debug():
    """Create a mock TerminalManager for debug monitor."""
    manager = MagicMock()
    manager.launch_sessions = AsyncMock(return_value=["debug_session_123"])
    manager.close_session = AsyncMock()
    manager.list_sessions = AsyncMock(return_value=[{"id": "debug_session_123", "status": "running"}])
    manager.current_adapter.return_value = "iterm2"
    return manager


@pytest.fixture
def debug_monitor_worker(mock_terminal_manager_for_debug):
    """Create a DebugMonitorWorker."""
    return DebugMonitorWorker(
        log_path=Path("/tmp/test-debug.log"),
        terminal_manager=mock_terminal_manager_for_debug,
        session_buddy_client=None,
    )


class TestDebugMonitorWorker:
    """Test DebugMonitorWorker class."""

    def test_initialization(self, debug_monitor_worker):
        """Test debug monitor initialization."""
        assert debug_monitor_worker.worker_type == "debug-monitor"
        assert str(debug_monitor_worker.log_path) == "/tmp/test-debug.log"
        assert debug_monitor_worker.session_id is None
        assert debug_monitor_worker._running is False

    @pytest.mark.asyncio
    async def test_start_iterm2_monitor(self, debug_monitor_worker, mock_terminal_manager_for_debug):
        """Test starting iTerm2 debug monitor."""
        session_id = await debug_monitor_worker._start_iterm2_monitor()

        assert session_id == "debug_session_123"
        mock_terminal_manager_for_debug.launch_sessions.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_without_session_buddy(self, debug_monitor_worker):
        """Test starting monitor without Session-Buddy."""
        debug_monitor_worker.session_buddy_client = None

        session_id = await debug_monitor_worker.start()

        assert session_id == "debug_session_123"
        # Streaming task should not be created
        assert debug_monitor_worker._streaming_task is None

    @pytest.mark.asyncio
    async def test_status_running(self, debug_monitor_worker):
        """Test status when running."""
        debug_monitor_worker.session_id = "debug_session_123"
        debug_monitor_worker._running = True
        debug_monitor_worker._streaming_task = AsyncMock()
        debug_monitor_worker._streaming_task.done = MagicMock(return_value=False)

        status = await debug_monitor_worker.status()

        assert status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_stop(self, debug_monitor_worker, mock_terminal_manager_for_debug):
        """Test stopping debug monitor."""
        debug_monitor_worker.session_id = "debug_session_123"
        debug_monitor_worker._running = True
        # Don't set a mock streaming task - the code handles None correctly
        debug_monitor_worker._streaming_task = None

        await debug_monitor_worker.stop()

        assert debug_monitor_worker._running is False
        assert debug_monitor_worker.session_id is None
        mock_terminal_manager_for_debug.close_session.assert_called_once_with("debug_session_123")

    @pytest.mark.asyncio
    async def test_execute_not_implemented(self, debug_monitor_worker):
        """Test that execute raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="does not execute tasks"):
            await debug_monitor_worker.execute({})


# ============================================================================
# Worker Manager Tests
# ============================================================================

@pytest.fixture
def mock_worker_manager_deps():
    """Create mock dependencies for WorkerManager."""
    terminal_manager = MagicMock()
    terminal_manager.create = MagicMock(return_value=terminal_manager)
    session_buddy_client = None
    return terminal_manager, session_buddy_client


@pytest.fixture
def worker_manager(mock_worker_manager_deps):
    """Create a WorkerManager instance."""
    terminal_manager, session_buddy_client = mock_worker_manager_deps
    return WorkerManager(
        terminal_manager=terminal_manager,
        max_concurrent=5,
        debug_mode=False,
        session_buddy_client=session_buddy_client,
    )


class TestWorkerManager:
    """Test WorkerManager class."""

    def test_initialization(self, worker_manager):
        """Test WorkerManager initialization."""
        assert worker_manager.max_concurrent == 5
        assert worker_manager.debug_mode is False
        assert len(worker_manager._workers) == 0

    def test_initialization_max_concurrent_clamping(self, mock_worker_manager_deps):
        """Test that max_concurrent is clamped to valid range."""
        terminal_manager, session_buddy_client = mock_worker_manager_deps

        # Test upper limit
        manager1 = WorkerManager(
            terminal_manager=terminal_manager,
            max_concurrent=200,
            session_buddy_client=session_buddy_client,
        )
        assert manager1.max_concurrent == 100

        # Test lower limit
        manager2 = WorkerManager(
            terminal_manager=terminal_manager,
            max_concurrent=0,
            session_buddy_client=session_buddy_client,
        )
        assert manager2.max_concurrent == 1

    @pytest.mark.asyncio
    async def test_spawn_qwen_workers(self, worker_manager):
        """Test spawning Qwen workers."""
        with patch.object(worker_manager, "_create_worker") as mock_create:
            mock_worker = AsyncMock()
            mock_worker.start = AsyncMock(return_value="worker_123")
            mock_create.return_value = mock_worker

            worker_ids = await worker_manager.spawn_workers(
                worker_type="terminal-qwen",
                count=3,
            )

            assert len(worker_ids) == 3
            assert mock_create.call_count == 3

    @pytest.mark.asyncio
    async def test_spawn_unknown_worker_type(self, worker_manager):
        """Test that unknown worker type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown worker type"):
            await worker_manager.spawn_workers(worker_type="unknown-type", count=1)

    @pytest.mark.asyncio
    async def test_execute_task_success(self, worker_manager):
        """Test executing task on worker."""
        mock_worker = AsyncMock()
        mock_worker.execute = AsyncMock(
            return_value=WorkerResult(
                worker_id="worker_123",
                status=WorkerStatus.COMPLETED,
                output="Done",
                error=None,
                exit_code=0,
                duration_seconds=1.0,
                metadata={},
            )
        )
        worker_manager._workers["worker_123"] = mock_worker

        result = await worker_manager.execute_task(
            worker_id="worker_123",
            task={"prompt": "Test"},
        )

        assert result.status == WorkerStatus.COMPLETED
        mock_worker.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_task_worker_not_found(self, worker_manager):
        """Test executing task on non-existent worker."""
        with pytest.raises(ValueError, match="Worker not found"):
            await worker_manager.execute_task(
                worker_id="nonexistent",
                task={"prompt": "Test"},
            )

    @pytest.mark.asyncio
    async def test_execute_batch(self, worker_manager):
        """Test batch execution."""
        # Create mock workers
        for i in range(3):
            mock_worker = AsyncMock()
            mock_worker.execute = AsyncMock(
                return_value=WorkerResult(
                    worker_id=f"worker_{i}",
                    status=WorkerStatus.COMPLETED,
                    output=f"Result {i}",
                    error=None,
                    exit_code=0,
                    duration_seconds=1.0,
                    metadata={},
                )
            )
            worker_manager._workers[f"worker_{i}"] = mock_worker

        worker_ids = ["worker_0", "worker_1", "worker_2"]
        tasks = [{"prompt": f"Task {i}"} for i in range(3)]

        results = await worker_manager.execute_batch(worker_ids, tasks)

        assert len(results) == 3
        assert all(result.status == WorkerStatus.COMPLETED for result in results.values())

    @pytest.mark.asyncio
    async def test_execute_batch_length_mismatch(self, worker_manager):
        """Test that batch execution raises error on length mismatch."""
        with pytest.raises(ValueError, match="must have same length"):
            await worker_manager.execute_batch(
                worker_ids=["worker_0", "worker_1"],
                tasks=[{"prompt": "Task 0"}],
            )

    @pytest.mark.asyncio
    async def test_close_worker(self, worker_manager):
        """Test closing a specific worker."""
        mock_worker = AsyncMock()
        mock_worker.stop = AsyncMock()
        worker_manager._workers["worker_123"] = mock_worker

        await worker_manager.close_worker("worker_123")

        mock_worker.stop.assert_called_once()
        assert "worker_123" not in worker_manager._workers

    @pytest.mark.asyncio
    async def test_close_all(self, worker_manager):
        """Test closing all workers."""
        # Create mock workers
        for i in range(3):
            mock_worker = AsyncMock()
            mock_worker.stop = AsyncMock()
            worker_manager._workers[f"worker_{i}"] = mock_worker

        await worker_manager.close_all()

        assert len(worker_manager._workers) == 0


# ============================================================================
# Session-Buddy Integration Tests
# ============================================================================

class TestSessionBuddyIntegration:
    """Test Session-Buddy integration across workers."""

    @pytest.mark.asyncio
    async def test_terminal_worker_stores_result(self):
        """Test that TerminalAIWorker stores results in Session-Buddy."""
        mock_sb_client = MagicMock()
        mock_sb_client.call_tool = AsyncMock()

        mock_terminal_manager = MagicMock()
        mock_terminal_manager.launch_sessions = AsyncMock(return_value=["session_123"])
        mock_terminal_manager.send_command = AsyncMock()
        mock_terminal_manager.capture_output = AsyncMock(return_value="")

        worker = TerminalAIWorker(
            terminal_manager=mock_terminal_manager,
            ai_type="qwen",
            session_buddy_client=mock_sb_client,
        )

        # Mock _monitor_completion to return a result
        worker._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="session_123",
                status=WorkerStatus.COMPLETED,
                output="Success",
                error=None,
                exit_code=0,
                duration_seconds=1.0,
                metadata={},
            )
        )

        # Execute should trigger Session-Buddy storage
        with patch("time.time", return_value=1234567890.0):
            await worker.execute({"prompt": "Test"})

        # Verify Session-Buddy was called
        mock_sb_client.call_tool.assert_called()
        call_args = mock_sb_client.call_tool.call_args
        assert call_args[0][0] == "store_memory"
        assert "metadata" in call_args[1]["arguments"]

    @pytest.mark.asyncio
    async def test_container_worker_stores_result(self):
        """Test that ContainerWorker stores results in Session-Buddy."""
        mock_sb_client = MagicMock()
        mock_sb_client.call_tool = AsyncMock()

        worker = ContainerWorker(
            runtime="docker",
            image="python:3.13-slim",
            session_buddy_client=mock_sb_client,
        )
        worker.container_id = "container_123"
        worker._running = True

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"Output\n", b""))
            mock_subprocess.return_value = mock_proc

            with patch("time.time", return_value=1234567890.0):
                result = await worker.execute({"command": "echo test"})

                # Verify Session-Buddy was called
                mock_sb_client.call_tool.assert_called()
                call_args = mock_sb_client.call_tool.call_args
                assert call_args[0][0] == "store_memory"
                metadata = call_args[1]["arguments"]["metadata"]
                assert metadata["worker_type"] == "container-executor"


# ============================================================================
# Stream-JSON Parsing Tests
# ============================================================================

class TestStreamJsonParsing:
    """Test stream-json parsing in TerminalAIWorker."""

    def test_is_complete_with_finish_reason(self):
        """Test detecting completion via finish_reason."""
        worker = TerminalAIWorker(
            terminal_manager=MagicMock(),
            ai_type="qwen",
            session_buddy_client=None,
        )

        # Complete message
        data = {"finish_reason": "stop"}
        assert worker._is_complete(data) is True

        # Incomplete message
        data = {"delta": {"content": "more text"}}
        assert worker._is_complete(data) is False

    def test_is_complete_with_done_marker(self):
        """Test detecting completion via done marker."""
        worker = TerminalAIWorker(
            terminal_manager=MagicMock(),
            ai_type="claude",
            session_buddy_client=None,
        )

        # Complete message
        data = {"type": "done"}
        assert worker._is_complete(data) is True

        # Incomplete message
        data = {"type": "content"}
        assert worker._is_complete(data) is False

    def test_extract_content_from_delta(self):
        """Test extracting content from delta format."""
        worker = TerminalAIWorker(
            terminal_manager=MagicMock(),
            ai_type="qwen",
            session_buddy_client=None,
        )

        data = {"delta": {"content": "Hello, world!"}}
        content = worker._extract_content(data)
        assert content == "Hello, world!"

    def test_extract_content_from_text_field(self):
        """Test extracting content from text field."""
        worker = TerminalAIWorker(
            terminal_manager=MagicMock(),
            ai_type="claude",
            session_buddy_client=None,
        )

        data = {"text": "Hello, world!"}
        content = worker._extract_content(data)
        assert content == "Hello, world!"
