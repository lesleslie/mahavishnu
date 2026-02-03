"""Unit tests for Mahavishnu worker system."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.workers.base import BaseWorker, WorkerResult, WorkerStatus
from mahavishnu.workers.container import ContainerWorker
from mahavishnu.workers.debug_monitor import DebugMonitorWorker
from mahavishnu.workers.manager import WorkerManager
from mahavishnu.workers.terminal import TerminalAIWorker

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
    manager.list_sessions = AsyncMock(
        return_value=[{"id": "debug_session_123", "status": "running"}]
    )
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
    async def test_start_iterm2_monitor(
        self, debug_monitor_worker, mock_terminal_manager_for_debug
    ):
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


# ============================================================================
# Concurrent Execution Tests
# ============================================================================


class TestConcurrentExecution:
    """Test concurrent worker execution patterns."""

    @pytest.mark.asyncio
    async def test_concurrent_worker_execution(self, worker_manager):
        """Test multiple workers executing concurrently."""
        # Track execution order
        execution_order = []

        async def mock_execute(task):
            execution_order.append(task["id"])
            await asyncio.sleep(0.05)
            return WorkerResult(
                worker_id=task["id"],
                status=WorkerStatus.COMPLETED,
                output=f"Result {task['id']}",
                error=None,
                exit_code=0,
                duration_seconds=0.05,
                metadata={},
            )

        # Create mock workers
        for i in range(5):
            mock_worker = MagicMock()
            mock_worker.execute = mock_execute
            worker_manager._workers[f"worker_{i}"] = mock_worker

        # Execute batch
        worker_ids = [f"worker_{i}" for i in range(5)]
        tasks = [{"id": f"task_{i}"} for i in range(5)]
        results = await worker_manager.execute_batch(worker_ids, tasks)

        assert len(results) == 5
        assert len(execution_order) == 5
        assert all(r.status == WorkerStatus.COMPLETED for r in results.values())

    @pytest.mark.asyncio
    async def test_concurrent_execution_with_failures(self, worker_manager):
        """Test batch execution with some failures."""
        # Mock some workers to fail
        call_count = [0]

        async def mock_execute(task):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                raise RuntimeError("Worker failed")

            await asyncio.sleep(0.01)
            return WorkerResult(
                worker_id=task["id"],
                status=WorkerStatus.COMPLETED,
                output="Success",
                error=None,
                exit_code=0,
                duration_seconds=0.01,
                metadata={},
            )

        # Create mock workers
        for i in range(4):
            mock_worker = MagicMock()
            mock_worker.execute = mock_execute
            worker_manager._workers[f"worker_{i}"] = mock_worker

        # Execute batch
        worker_ids = [f"worker_{i}" for i in range(4)]
        tasks = [{"id": f"task_{i}"} for i in range(4)]
        results = await worker_manager.execute_batch(worker_ids, tasks)

        # Some should succeed, some should fail
        assert len(results) == 4
        success_count = sum(1 for r in results.values() if r.status == WorkerStatus.COMPLETED)
        failed_count = sum(1 for r in results.values() if r.status == WorkerStatus.FAILED)
        assert success_count > 0
        assert failed_count > 0

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_execution(self, worker_manager):
        """Test that semaphore limits concurrent execution."""
        # Create manager with max_concurrent=2
        terminal_manager = MagicMock()
        manager = WorkerManager(
            terminal_manager=terminal_manager,
            max_concurrent=2,
            debug_mode=False,
            session_buddy_client=None,
        )

        # Track concurrent executions
        concurrent_count = 0
        max_concurrent_reached = 0
        lock = asyncio.Lock()

        async def mock_execute(task):
            nonlocal concurrent_count, max_concurrent_reached
            async with lock:
                concurrent_count += 1
                max_concurrent_reached = max(max_concurrent_reached, concurrent_count)

            await asyncio.sleep(0.1)

            async with lock:
                concurrent_count -= 1

            return WorkerResult(
                worker_id="worker",
                status=WorkerStatus.COMPLETED,
                output="Done",
                error=None,
                exit_code=0,
                duration_seconds=0.1,
                metadata={},
            )

        # Add mock workers
        for i in range(5):
            mock_worker = MagicMock()
            mock_worker.execute = mock_execute
            manager._workers[f"worker_{i}"] = mock_worker

        # Execute batch
        await manager.execute_batch(
            worker_ids=[f"worker_{i}" for i in range(5)],
            tasks=[{"prompt": f"Task {i}"} for i in range(5)],
        )

        # Verify concurrency was limited
        assert max_concurrent_reached <= 2


# ============================================================================
# Error Handling and Retry Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_worker_crash_during_execution(self, worker_manager):
        """Test handling worker crash during task execution."""

        # Mock worker that crashes
        async def crash_execute(task):
            await asyncio.sleep(0.01)
            raise RuntimeError("Worker crashed!")

        mock_worker = MagicMock()
        mock_worker.execute = crash_execute
        worker_manager._workers["crash_worker"] = mock_worker

        result = await worker_manager.execute_task(
            worker_id="crash_worker",
            task={"prompt": "Test"},
        )

        assert result.status == WorkerStatus.FAILED
        assert "crashed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_worker_timeout_handling(self, terminal_qwen_worker):
        """Test timeout handling for long-running workers."""
        # Mock _monitor_completion to return a timeout result
        timeout_result = WorkerResult(
            worker_id="session_123",
            status=WorkerStatus.TIMEOUT,
            output="Partial output",
            error="Task timed out",
            exit_code=None,
            duration_seconds=300.0,
            metadata={"timeout": 300},
        )

        terminal_qwen_worker._monitor_completion = AsyncMock(return_value=timeout_result)

        result = await terminal_qwen_worker.execute({"prompt": "Long task", "timeout": 300})

        assert result.status == WorkerStatus.TIMEOUT
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_worker_cleanup_on_failure(self, worker_manager):
        """Test workers are cleaned up even after failures."""
        # Mock worker that fails on stop
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(
            return_value=WorkerResult(
                worker_id="test",
                status=WorkerStatus.COMPLETED,
                output="Done",
                error=None,
                exit_code=0,
                duration_seconds=1.0,
                metadata={},
            )
        )
        mock_worker.stop = AsyncMock(side_effect=RuntimeError("Stop failed"))
        worker_manager._workers["test_worker"] = mock_worker

        # Execute task
        await worker_manager.execute_task("test_worker", {"prompt": "Test"})

        # Close should not raise exception
        await worker_manager.close_worker("test_worker")

        # Worker should be removed from registry despite stop failure
        assert "test_worker" not in worker_manager._workers

    @pytest.mark.asyncio
    async def test_status_check_failure_handling(self, worker_manager):
        """Test monitoring handles status check failures gracefully."""
        # Add a worker that fails status checks
        mock_worker_bad = MagicMock()
        mock_worker_bad.status = AsyncMock(side_effect=RuntimeError("Status failed"))
        worker_manager._workers["bad_worker"] = mock_worker_bad

        # Add a good worker
        mock_worker_good = MagicMock()
        mock_worker_good.status = AsyncMock(return_value=WorkerStatus.RUNNING)
        worker_manager._workers["good_worker"] = mock_worker_good

        statuses = await worker_manager.monitor_workers()

        # Bad worker should be marked as FAILED
        assert statuses["bad_worker"] == WorkerStatus.FAILED
        # Good worker should be RUNNING
        assert statuses["good_worker"] == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_container_worker_execute_not_started(self):
        """Test execute before starting container raises error."""
        worker = ContainerWorker(
            runtime="docker",
            image="python:3.13-slim",
            session_buddy_client=None,
        )

        with pytest.raises(RuntimeError, match="Container not started"):
            await worker.execute({"command": "echo test"})

    @pytest.mark.asyncio
    async def test_terminal_worker_invalid_ai_type(self, mock_terminal_manager):
        """Test starting worker with invalid AI type raises error."""
        worker = TerminalAIWorker(
            terminal_manager=mock_terminal_manager,
            ai_type="invalid",
            session_buddy_client=None,
        )

        with pytest.raises(ValueError, match="Unknown AI type"):
            await worker.start()


# ============================================================================
# Worker Lifecycle Tests
# ============================================================================


class TestWorkerLifecycle:
    """Test complete worker lifecycle."""

    @pytest.mark.asyncio
    async def test_full_worker_lifecycle(self, mock_terminal_manager):
        """Test complete worker lifecycle: start -> execute -> stop."""
        worker = TerminalAIWorker(
            terminal_manager=mock_terminal_manager,
            ai_type="qwen",
            session_buddy_client=None,
        )

        # Mock monitor completion
        worker._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="session_123",
                status=WorkerStatus.COMPLETED,
                output="Task completed",
                error=None,
                exit_code=0,
                duration_seconds=1.0,
                metadata={},
            )
        )

        # Start worker
        session_id = await worker.start()
        assert session_id == "session_123"
        assert worker._status == WorkerStatus.RUNNING

        # Execute task
        result = await worker.execute({"prompt": "Test task"})
        assert result.status == WorkerStatus.COMPLETED

        # Check status
        status = await worker.status()
        assert status == WorkerStatus.RUNNING

        # Get progress
        progress = await worker.get_progress()
        assert "status" in progress
        assert "session_id" in progress

        # Stop worker
        await worker.stop()
        assert worker._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_container_worker_lifecycle(self):
        """Test complete container worker lifecycle."""
        worker = ContainerWorker(
            runtime="docker",
            image="python:3.13-slim",
            session_buddy_client=None,
        )

        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            # Mock start
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"container_123\n", b""))
            mock_subprocess.return_value = mock_proc

            # Start
            container_id = await worker.start()
            assert container_id == "container_123"
            assert worker._running is True

            # Execute
            mock_proc.communicate = AsyncMock(return_value=(b"output\n", b""))
            result = await worker.execute({"command": "echo test"})
            assert result.status == WorkerStatus.COMPLETED

            # Status
            mock_proc.communicate = AsyncMock(return_value=(b"running\n", b""))
            status = await worker.status()
            assert status == WorkerStatus.RUNNING

            # Stop
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            await worker.stop()
            assert worker._running is False
            assert worker.container_id is None


# ============================================================================
# Worker Pool Management Tests
# ============================================================================


class TestWorkerPoolManagement:
    """Test worker pool management operations."""

    @pytest.mark.asyncio
    async def test_add_and_remove_workers(self, worker_manager):
        """Test adding and removing workers from pool."""
        # Add workers manually
        for i in range(3):
            mock_worker = MagicMock()
            mock_worker.stop = AsyncMock()
            worker_manager._workers[f"worker_{i}"] = mock_worker

        assert len(worker_manager._workers) == 3

        # Remove one worker
        await worker_manager.close_worker("worker_1")
        assert len(worker_manager._workers) == 2
        assert "worker_1" not in worker_manager._workers

        # Remove all
        await worker_manager.close_all()
        assert len(worker_manager._workers) == 0

    @pytest.mark.asyncio
    async def test_list_workers_with_status(self, worker_manager):
        """Test listing workers with their status."""
        # Add mock workers
        for i in range(3):
            mock_worker = MagicMock()
            mock_worker.worker_type = f"terminal-{i}"
            mock_worker.status = AsyncMock(
                return_value=WorkerStatus.RUNNING if i % 2 == 0 else WorkerStatus.COMPLETED
            )
            worker_manager._workers[f"worker_{i}"] = mock_worker

        workers_list = await worker_manager.list_workers()

        assert len(workers_list) == 3
        for worker_info in workers_list:
            assert "worker_id" in worker_info
            assert "worker_type" in worker_info
            assert "status" in worker_info

    @pytest.mark.asyncio
    async def test_monitor_specific_workers(self, worker_manager):
        """Test monitoring specific subset of workers."""
        # Add mock workers
        for i in range(5):
            mock_worker = MagicMock()
            mock_worker.status = AsyncMock(return_value=WorkerStatus.RUNNING)
            worker_manager._workers[f"worker_{i}"] = mock_worker

        # Monitor only first 2 workers
        statuses = await worker_manager.monitor_workers(worker_ids=["worker_0", "worker_1"])

        assert len(statuses) == 2
        assert "worker_0" in statuses
        assert "worker_1" in statuses
        assert "worker_2" not in statuses

    @pytest.mark.asyncio
    async def test_collect_results_from_specific_workers(self, worker_manager):
        """Test collecting results from specific workers."""
        # Add mock workers
        for i in range(3):
            mock_worker = MagicMock()
            mock_worker.get_progress = AsyncMock(
                return_value={
                    "status": WorkerStatus.COMPLETED.value,
                    "output_preview": f"Output {i}",
                    "duration_seconds": 1.0,
                }
            )
            worker_manager._workers[f"worker_{i}"] = mock_worker

        # Collect from specific workers
        results = await worker_manager.collect_results(worker_ids=["worker_0", "worker_2"])

        assert len(results) == 2
        assert "worker_0" in results
        assert "worker_2" in results
        assert "worker_1" not in results


# ============================================================================
# Health Check Tests
# ============================================================================


class TestHealthChecks:
    """Test health check functionality."""

    @pytest.mark.asyncio
    async def test_worker_manager_health_check(self, worker_manager):
        """Test WorkerManager health check."""
        # Add mock workers
        for i in range(2):
            mock_worker = MagicMock()
            mock_worker.worker_type = "terminal-qwen"
            mock_worker.status = AsyncMock(return_value=WorkerStatus.RUNNING)
            worker_manager._workers[f"worker_{i}"] = mock_worker

        health = await worker_manager.health_check()

        assert health["status"] == "healthy"
        assert health["workers_active"] == 2
        assert health["max_concurrent"] == 5
        assert "workers" in health

    @pytest.mark.asyncio
    async def test_base_worker_health_check_success(self, terminal_qwen_worker):
        """Test health_check returns healthy when worker is running."""
        terminal_qwen_worker._status = WorkerStatus.RUNNING

        health = await terminal_qwen_worker.health_check()

        assert health["healthy"] is True
        assert health["status"] == WorkerStatus.RUNNING.value
        assert health["worker_type"] == "terminal-qwen"

    @pytest.mark.asyncio
    async def test_base_worker_health_check_failure(self):
        """Test health_check returns unhealthy when worker fails."""

        class FailingWorker(BaseWorker):
            async def start(self) -> str:
                raise RuntimeError("Failed to start")

            async def execute(self, task: dict) -> WorkerResult:
                raise NotImplementedError()

            async def stop(self) -> None:
                pass

            async def status(self) -> WorkerStatus:
                raise RuntimeError("Status check failed")

            async def get_progress(self) -> dict:
                raise NotImplementedError()

        worker = FailingWorker(worker_type="failing")
        health = await worker.health_check()

        assert health["healthy"] is False
        assert "error" in health["details"]


# ============================================================================
# Session-Buddy Storage Tests
# ============================================================================


class TestSessionBuddyStorage:
    """Test Session-Buddy result storage."""

    @pytest.mark.asyncio
    async def test_terminal_worker_session_buddy_error_handling(self, mock_terminal_manager):
        """Test that Session-Buddy errors don't fail worker execution."""
        mock_sb_client = MagicMock()
        mock_sb_client.call_tool = AsyncMock(side_effect=RuntimeError("Storage failed"))

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

        # Execute should succeed despite Session-Buddy failure
        result = await worker.execute({"prompt": "Test"})

        assert result.status == WorkerStatus.COMPLETED
        # Session-Buddy was attempted but failed
        mock_sb_client.call_tool.assert_called()

    @pytest.mark.asyncio
    async def test_container_worker_session_buddy_metadata(self):
        """Test that ContainerWorker stores correct metadata in Session-Buddy."""
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

            result = await worker.execute({"command": "echo test"})

            # Verify Session-Buddy metadata
            call_args = mock_sb_client.call_tool.call_args
            metadata = call_args[1]["arguments"]["metadata"]
            assert metadata["worker_type"] == "container-executor"
            assert metadata["runtime"] == "docker"
            assert metadata["image"] == "python:3.13-slim"
            assert metadata["type"] == "worker_result"


# ============================================================================
# Stream-JSON Content Extraction Tests
# ============================================================================


class TestContentExtraction:
    """Test content extraction from stream-json messages."""

    def test_extract_content_multi_modal(self):
        """Test extracting content from multi-modal messages."""
        worker = TerminalAIWorker(
            terminal_manager=MagicMock(),
            ai_type="claude",
            session_buddy_client=None,
        )

        # Multi-modal content
        data = {
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "image", "source": "data:image..."},
            ]
        }
        content = worker._extract_content(data)
        assert content == "Hello"

    def test_extract_content_no_content(self):
        """Test extracting content when none exists."""
        worker = TerminalAIWorker(
            terminal_manager=MagicMock(),
            ai_type="qwen",
            session_buddy_client=None,
        )

        data = {"other": "field"}
        content = worker._extract_content(data)
        assert content is None

    def test_is_complete_multiple_markers(self):
        """Test various completion markers."""
        worker = TerminalAIWorker(
            terminal_manager=MagicMock(),
            ai_type="qwen",
            session_buddy_client=None,
        )

        # All should return True
        assert worker._is_complete({"finish_reason": "stop"}) is True
        assert worker._is_complete({"done": True}) is True
        assert worker._is_complete({"type": "done"}) is True
        assert worker._is_complete({"type": "completion"}) is True
        assert worker._is_complete({"status": "completed"}) is True

        # Should return False
        assert worker._is_complete({"content": "text"}) is False
        assert worker._is_complete({"delta": {"content": "more"}}) is False


# ============================================================================
# Edge Case Tests
# ============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_execute_with_empty_task(self, terminal_qwen_worker):
        """Test executing with empty task dict."""
        terminal_qwen_worker._monitor_completion = AsyncMock(
            return_value=WorkerResult(
                worker_id="session_123",
                status=WorkerStatus.COMPLETED,
                output="Done",
                error=None,
                exit_code=0,
                duration_seconds=1.0,
                metadata={},
            )
        )

        # Should not raise error
        result = await terminal_qwen_worker.execute({})
        assert result.status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_worker_result_with_long_output(self):
        """Test WorkerResult with very long output."""
        long_output = "x" * 10000
        result = WorkerResult(
            worker_id="test",
            status=WorkerStatus.COMPLETED,
            output=long_output,
            error=None,
            exit_code=0,
            duration_seconds=1.0,
            metadata={},
        )

        # get_summary should truncate
        summary = result.get_summary()
        assert "..." in summary
        assert len(summary) < len(long_output)

    @pytest.mark.asyncio
    async def test_monitor_workers_with_empty_list(self, worker_manager):
        """Test monitoring with no workers."""
        statuses = await worker_manager.monitor_workers(worker_ids=[])
        assert statuses == {}

    @pytest.mark.asyncio
    async def test_collect_results_with_empty_list(self, worker_manager):
        """Test collecting results with no workers."""
        results = await worker_manager.collect_results(worker_ids=[])
        assert results == {}

    @pytest.mark.asyncio
    async def test_close_nonexistent_worker(self, worker_manager):
        """Test closing worker that doesn't exist (should not raise)."""
        # Should not raise error
        await worker_manager.close_worker("nonexistent")

    @pytest.mark.asyncio
    async def test_execute_batch_with_empty_lists(self, worker_manager):
        """Test batch execution with empty lists."""
        results = await worker_manager.execute_batch([], [])
        assert results == {}

    def test_worker_status_enum_coverage(self):
        """Test that all WorkerStatus enum values are accessible."""
        statuses = [
            WorkerStatus.PENDING,
            WorkerStatus.STARTING,
            WorkerStatus.RUNNING,
            WorkerStatus.COMPLETED,
            WorkerStatus.FAILED,
            WorkerStatus.TIMEOUT,
            WorkerStatus.CANCELLED,
        ]

        assert len(statuses) == 7
        assert all(isinstance(s, WorkerStatus) for s in statuses)

    def test_worker_result_serialization_roundtrip(self):
        """Test complete serialization/deserialization roundtrip."""
        original = WorkerResult(
            worker_id="test_worker",
            status=WorkerStatus.COMPLETED,
            output="Test output with special chars: \n\t",
            error=None,
            exit_code=0,
            duration_seconds=1.5,
            metadata={"key": "value", "number": 42},
        )

        # Serialize
        data_dict = original.to_dict()

        # Deserialize
        restored = WorkerResult.from_dict(data_dict)

        # Verify all fields
        assert restored.worker_id == original.worker_id
        assert restored.status == original.status
        assert restored.output == original.output
        assert restored.exit_code == original.exit_code
        assert restored.duration_seconds == original.duration_seconds
        assert restored.metadata == original.metadata
