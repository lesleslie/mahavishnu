"""Unit tests for terminal management.

Comprehensive test coverage for:
- TerminalManager lifecycle and operations
- TerminalSession wrapper functionality
- TerminalSettings configuration validation
- Command execution and output capture
- Error handling and edge cases
- Concurrent operations
"""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from mahavishnu.terminal.config import TerminalSettings
from mahavishnu.terminal.manager import TerminalManager
from mahavishnu.terminal.session import TerminalSession

# =============================================================================
# Mock Adapter Implementation
# =============================================================================


class MockTerminalAdapter:
    """Mock terminal adapter for testing.

    Provides a simple in-memory implementation of TerminalAdapter
    for testing without requiring actual terminal or MCP connections.
    """

    def __init__(self, fail_on_launch: bool = False):
        """Initialize mock adapter.

        Args:
            fail_on_launch: If True, launch_session will raise an exception
        """
        self.adapter_name = "mock"
        self._sessions: dict[str, dict] = {}
        self._session_counter = 0
        self._fail_on_launch = fail_on_launch
        self._launch_calls = []
        self._send_calls = []
        self._capture_calls = []
        self._close_calls = []

    async def launch_session(
        self, command: str, columns: int = 80, rows: int = 24, **kwargs
    ) -> str:
        """Launch a mock terminal session.

        Args:
            command: Command to run
            columns: Terminal width
            rows: Terminal height
            **kwargs: Additional parameters

        Returns:
            Session ID

        Raises:
            RuntimeError: If fail_on_launch is True
        """
        self._launch_calls.append((command, columns, rows, kwargs))

        if self._fail_on_launch:
            raise RuntimeError("Failed to launch session")

        self._session_counter += 1
        session_id = f"mock_session_{self._session_counter}"

        self._sessions[session_id] = {
            "id": session_id,
            "command": command,
            "columns": columns,
            "rows": rows,
            "created_at": MagicMock(),
        }

        return session_id

    async def send_command(self, session_id: str, command: str) -> None:
        """Send command to a session.

        Args:
            session_id: Session identifier
            command: Command to send

        Raises:
            KeyError: If session_id doesn't exist
        """
        self._send_calls.append((session_id, command))

        if session_id not in self._sessions:
            raise KeyError(f"Session {session_id} not found")

        # Store command in session history
        self._sessions[session_id].setdefault("commands", []).append(command)

    async def capture_output(self, session_id: str, lines: int | None = None) -> str:
        """Capture output from a session.

        Args:
            session_id: Session identifier
            lines: Number of lines to capture

        Returns:
            Mock output string

        Raises:
            KeyError: If session_id doesn't exist
        """
        self._capture_calls.append((session_id, lines))

        if session_id not in self._sessions:
            raise KeyError(f"Session {session_id} not found")

        # Generate mock output
        output_lines = [f"Line {i}" for i in range(10)]
        if lines is not None:
            output_lines = output_lines[:lines]

        return "\n".join(output_lines)

    async def close_session(self, session_id: str) -> None:
        """Close a session.

        Args:
            session_id: Session identifier

        Raises:
            KeyError: If session_id doesn't exist
        """
        self._close_calls.append(session_id)

        if session_id not in self._sessions:
            raise KeyError(f"Session {session_id} not found")

        del self._sessions[session_id]

    async def list_sessions(self) -> list[dict]:
        """List all active sessions.

        Returns:
            List of session dictionaries
        """
        return list(self._sessions.values())

    @property
    def sessions(self) -> dict[str, dict]:
        """Get all sessions (for testing)."""
        return self._sessions.copy()


# =============================================================================
# TerminalSettings Tests
# =============================================================================


class TestTerminalSettings:
    """Test TerminalSettings configuration."""

    def test_default_settings(self):
        """Test default configuration values."""
        settings = TerminalSettings()

        assert settings.enabled is False
        assert settings.default_columns == 120
        assert settings.default_rows == 40
        assert settings.capture_lines == 100
        assert settings.poll_interval == 0.5
        assert settings.max_concurrent_sessions == 20
        assert settings.adapter_preference == "auto"
        assert settings.iterm2_pooling_enabled is True
        assert settings.iterm2_pool_max_size == 3
        assert settings.iterm2_pool_idle_timeout == 300.0
        assert settings.iterm2_default_profile is None

    def test_custom_settings(self):
        """Test custom configuration values."""
        settings = TerminalSettings(
            enabled=True,
            default_columns=200,
            default_rows=50,
            capture_lines=500,
            poll_interval=1.0,
            max_concurrent_sessions=10,
            adapter_preference="mcpretentious",
        )

        assert settings.enabled is True
        assert settings.default_columns == 200
        assert settings.default_rows == 50
        assert settings.capture_lines == 500
        assert settings.poll_interval == 1.0
        assert settings.max_concurrent_sessions == 10
        assert settings.adapter_preference == "mcpretentious"

    def test_columns_validation(self):
        """Test columns field validation."""
        # Valid ranges
        TerminalSettings(default_columns=40)  # Minimum
        TerminalSettings(default_columns=300)  # Maximum
        TerminalSettings(default_columns=120)  # Default

        # Invalid ranges
        with pytest.raises(ValueError):
            TerminalSettings(default_columns=39)  # Too small

        with pytest.raises(ValueError):
            TerminalSettings(default_columns=301)  # Too large

    def test_rows_validation(self):
        """Test rows field validation."""
        # Valid ranges
        TerminalSettings(default_rows=10)  # Minimum
        TerminalSettings(default_rows=200)  # Maximum
        TerminalSettings(default_rows=40)  # Default

        # Invalid ranges
        with pytest.raises(ValueError):
            TerminalSettings(default_rows=9)  # Too small

        with pytest.raises(ValueError):
            TerminalSettings(default_rows=201)  # Too large

    def test_capture_lines_validation(self):
        """Test capture_lines field validation."""
        # Valid ranges
        TerminalSettings(capture_lines=1)  # Minimum
        TerminalSettings(capture_lines=10000)  # Maximum
        TerminalSettings(capture_lines=100)  # Default

        # Invalid ranges
        with pytest.raises(ValueError):
            TerminalSettings(capture_lines=0)  # Too small

        with pytest.raises(ValueError):
            TerminalSettings(capture_lines=10001)  # Too large

    def test_poll_interval_validation(self):
        """Test poll_interval field validation."""
        # Valid ranges
        TerminalSettings(poll_interval=0.1)  # Minimum
        TerminalSettings(poll_interval=10.0)  # Maximum
        TerminalSettings(poll_interval=0.5)  # Default

        # Invalid ranges
        with pytest.raises(ValueError):
            TerminalSettings(poll_interval=0.09)  # Too small

        with pytest.raises(ValueError):
            TerminalSettings(poll_interval=10.1)  # Too large

    def test_max_concurrent_sessions_validation(self):
        """Test max_concurrent_sessions field validation."""
        # Valid ranges
        TerminalSettings(max_concurrent_sessions=1)  # Minimum
        TerminalSettings(max_concurrent_sessions=100)  # Maximum
        TerminalSettings(max_concurrent_sessions=20)  # Default

        # Invalid ranges
        with pytest.raises(ValueError):
            TerminalSettings(max_concurrent_sessions=0)  # Too small

        with pytest.raises(ValueError):
            TerminalSettings(max_concurrent_sessions=101)  # Too large

    def test_iterm2_pool_settings_validation(self):
        """Test iTerm2 pool settings validation."""
        # Valid pool settings
        TerminalSettings(
            iterm2_pool_max_size=1,  # Minimum
            iterm2_pool_idle_timeout=30.0,  # Minimum
        )
        TerminalSettings(
            iterm2_pool_max_size=10,  # Maximum
            iterm2_pool_idle_timeout=3600.0,  # Maximum
        )

        # Invalid pool size
        with pytest.raises(ValueError):
            TerminalSettings(iterm2_pool_max_size=0)

        with pytest.raises(ValueError):
            TerminalSettings(iterm2_pool_max_size=11)

        # Invalid idle timeout
        with pytest.raises(ValueError):
            TerminalSettings(iterm2_pool_idle_timeout=29.9)

        with pytest.raises(ValueError):
            TerminalSettings(iterm2_pool_idle_timeout=3600.1)


# =============================================================================
# TerminalManager Tests
# =============================================================================


class TestTerminalManagerInitialization:
    """Test TerminalManager initialization and setup."""

    @pytest.mark.asyncio
    async def test_initialization_with_default_config(self):
        """Test manager initialization with default config."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        assert manager.adapter is adapter
        assert manager.config == TerminalSettings()
        assert manager.current_adapter() == "mock"

    @pytest.mark.asyncio
    async def test_initialization_with_custom_config(self):
        """Test manager initialization with custom config."""
        adapter = MockTerminalAdapter()
        config = TerminalSettings(max_concurrent_sessions=5)
        manager = TerminalManager(adapter, config)

        assert manager.adapter is adapter
        assert manager.config.max_concurrent_sessions == 5
        assert manager.current_adapter() == "mock"

    @pytest.mark.asyncio
    async def test_adapter_history_initially_empty(self):
        """Test that adapter history is initially empty."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        history = manager.get_adapter_history()
        assert history == []


class TestTerminalManagerSessionLaunch:
    """Test terminal session launching."""

    @pytest.mark.asyncio
    async def test_launch_single_session(self):
        """Test launching a single session."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        session_ids = await manager.launch_sessions("echo test", count=1)

        assert len(session_ids) == 1
        assert session_ids[0].startswith("mock_session_")
        assert len(adapter.sessions) == 1

    @pytest.mark.asyncio
    async def test_launch_multiple_sessions(self):
        """Test launching multiple sessions concurrently."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        session_ids = await manager.launch_sessions("echo test", count=5)

        assert len(session_ids) == 5
        assert len(set(session_ids)) == 5  # All unique
        assert all(sid.startswith("mock_session_") for sid in session_ids)
        assert len(adapter.sessions) == 5

    @pytest.mark.asyncio
    async def test_launch_sessions_with_custom_dimensions(self):
        """Test launching sessions with custom terminal dimensions."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        await manager.launch_sessions("echo test", count=3, columns=200, rows=60)

        # Verify all sessions were launched with correct dimensions
        for call in adapter._launch_calls:
            assert call[1] == 200  # columns
            assert call[2] == 60  # rows

    @pytest.mark.asyncio
    async def test_launch_sessions_respects_concurrency_limit(self):
        """Test that session launch respects semaphore concurrency limit."""
        adapter = MockTerminalAdapter()
        config = TerminalSettings(max_concurrent_sessions=3)
        manager = TerminalManager(adapter, config)

        # Launch more sessions than semaphore limit
        session_ids = await manager.launch_sessions("echo test", count=10)

        assert len(session_ids) == 10
        assert len(adapter.sessions) == 10

    @pytest.mark.asyncio
    async def test_launch_sessions_failure_propagates(self):
        """Test that launch failures are properly propagated."""
        adapter = MockTerminalAdapter(fail_on_launch=True)
        manager = TerminalManager(adapter)

        with pytest.raises(RuntimeError, match="Failed to launch session"):
            await manager.launch_sessions("echo test", count=1)

    @pytest.mark.asyncio
    async def test_launch_sessions_batch(self):
        """Test launching sessions in batches."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        # Launch 12 sessions (should be 3 batches of 5, 5, 2)
        session_ids = await manager.launch_sessions_batch("echo test", count=12)

        assert len(session_ids) == 12
        assert len(set(session_ids)) == 12


class TestTerminalManagerCommands:
    """Test sending commands to terminal sessions."""

    @pytest.mark.asyncio
    async def test_send_command_to_session(self):
        """Test sending a command to a single session."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        # Launch session first
        session_ids = await manager.launch_sessions("cat", count=1)
        session_id = session_ids[0]

        # Send command
        await manager.send_command(session_id, "test input")

        assert len(adapter._send_calls) == 1
        assert adapter._send_calls[0] == (session_id, "test input")

    @pytest.mark.asyncio
    async def test_send_command_to_nonexistent_session(self):
        """Test sending command to non-existent session raises error."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        with pytest.raises(KeyError, match="Session nonexistent not found"):
            await manager.send_command("nonexistent", "test")

    @pytest.mark.asyncio
    async def test_send_multiple_commands(self):
        """Test sending multiple commands to same session."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        session_ids = await manager.launch_sessions("cat", count=1)
        session_id = session_ids[0]

        await manager.send_command(session_id, "command 1")
        await manager.send_command(session_id, "command 2")
        await manager.send_command(session_id, "command 3")

        assert len(adapter._send_calls) == 3
        assert adapter._send_calls[0][1] == "command 1"
        assert adapter._send_calls[1][1] == "command 2"
        assert adapter._send_calls[2][1] == "command 3"


class TestTerminalManagerOutputCapture:
    """Test output capture from terminal sessions."""

    @pytest.mark.asyncio
    async def test_capture_output_from_session(self):
        """Test capturing output from a single session."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        session_ids = await manager.launch_sessions("echo test", count=1)
        session_id = session_ids[0]

        output = await manager.capture_output(session_id, lines=5)

        assert output == "Line 0\nLine 1\nLine 2\nLine 3\nLine 4"
        assert len(adapter._capture_calls) == 1
        assert adapter._capture_calls[0] == (session_id, 5)

    @pytest.mark.asyncio
    async def test_capture_output_without_limit(self):
        """Test capturing output without line limit."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        session_ids = await manager.launch_sessions("echo test", count=1)
        session_id = session_ids[0]

        output = await manager.capture_output(session_id)

        assert (
            output
            == "Line 0\nLine 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\nLine 7\nLine 8\nLine 9"
        )
        assert adapter._capture_calls[0] == (session_id, None)

    @pytest.mark.asyncio
    async def test_capture_output_from_nonexistent_session(self):
        """Test capturing output from non-existent session raises error."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        with pytest.raises(KeyError, match="Session nonexistent not found"):
            await manager.capture_output("nonexistent")

    @pytest.mark.asyncio
    async def test_capture_all_outputs_concurrently(self):
        """Test capturing outputs from multiple sessions concurrently."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        session_ids = await manager.launch_sessions("echo test", count=3)

        outputs = await manager.capture_all_outputs(session_ids, lines=5)

        assert len(outputs) == 3
        assert all(sid in outputs for sid in session_ids)
        assert all(
            output == "Line 0\nLine 1\nLine 2\nLine 3\nLine 4" for output in outputs.values()
        )

    @pytest.mark.asyncio
    async def test_capture_all_outputs_with_empty_list(self):
        """Test capturing outputs with empty session list."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        outputs = await manager.capture_all_outputs([])

        assert outputs == {}


class TestTerminalManagerSessionClosing:
    """Test closing terminal sessions."""

    @pytest.mark.asyncio
    async def test_close_single_session(self):
        """Test closing a single session."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        session_ids = await manager.launch_sessions("echo test", count=1)
        session_id = session_ids[0]
        assert session_id in adapter.sessions

        await manager.close_session(session_id)

        assert session_id not in adapter.sessions
        assert session_id in adapter._close_calls

    @pytest.mark.asyncio
    async def test_close_nonexistent_session(self):
        """Test closing non-existent session raises error."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        with pytest.raises(KeyError, match="Session nonexistent not found"):
            await manager.close_session("nonexistent")

    @pytest.mark.asyncio
    async def test_close_all_sessions(self):
        """Test closing multiple sessions concurrently."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        session_ids = await manager.launch_sessions("echo test", count=5)
        assert all(sid in adapter.sessions for sid in session_ids)

        await manager.close_all(session_ids)

        assert all(sid not in adapter.sessions for sid in session_ids)
        assert len(adapter._close_calls) == 5

    @pytest.mark.asyncio
    async def test_close_all_with_empty_list(self):
        """Test closing with empty session list."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        await manager.close_all([])  # Should not raise

        assert len(adapter._close_calls) == 0


class TestTerminalManagerListing:
    """Test listing active terminal sessions."""

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self):
        """Test listing sessions when none exist."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        sessions = await manager.list_sessions()

        assert sessions == []

    @pytest.mark.asyncio
    async def test_list_sessions_with_active_sessions(self):
        """Test listing active sessions."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        await manager.launch_sessions("echo test", count=3)

        sessions = await manager.list_sessions()

        assert len(sessions) == 3
        assert all("id" in session for session in sessions)
        assert all("command" in session for session in sessions)


class TestTerminalManagerAdapterSwitching:
    """Test hot-swapping terminal adapters."""

    @pytest.mark.asyncio
    async def test_switch_adapter_without_migration(self):
        """Test switching adapters without session migration."""
        adapter1 = MockTerminalAdapter()
        adapter2 = MockTerminalAdapter()
        adapter2.adapter_name = "mock2"
        manager = TerminalManager(adapter1)

        await manager.switch_adapter(adapter2, migrate_sessions=False)

        assert manager.adapter is adapter2
        assert manager.current_adapter() == "mock2"

        history = manager.get_adapter_history()
        assert len(history) == 1
        assert history[0]["from"] == "mock"
        assert history[0]["to"] == "mock2"
        assert history[0]["migrate_sessions"] is False

    @pytest.mark.asyncio
    async def test_switch_adapter_with_migration(self):
        """Test switching adapters with session migration."""
        adapter1 = MockTerminalAdapter()
        adapter2 = MockTerminalAdapter()
        adapter2.adapter_name = "mock2"
        manager = TerminalManager(adapter1)

        # Launch sessions with first adapter
        await manager.launch_sessions("echo test", count=2)
        assert len(adapter1.sessions) == 2

        # Switch with migration
        await manager.switch_adapter(adapter2, migrate_sessions=True)

        assert manager.adapter is adapter2
        # Sessions should be recreated in new adapter
        assert len(adapter2.sessions) == 2

    @pytest.mark.asyncio
    async def test_switch_adapter_migration_callback(self):
        """Test adapter switch with migration callback."""
        adapter1 = MockTerminalAdapter()
        adapter2 = MockTerminalAdapter()
        adapter2.adapter_name = "mock2"
        manager = TerminalManager(adapter1)

        callback_called = []

        async def callback(old_name, new_name):
            callback_called.append((old_name, new_name))

        manager.set_migration_callback(callback)

        await manager.switch_adapter(adapter2, migrate_sessions=False)

        assert len(callback_called) == 1
        assert callback_called[0] == ("mock", "mock2")


class TestTerminalManagerErrorHandling:
    """Test error handling in TerminalManager."""

    @pytest.mark.asyncio
    async def test_launch_sessions_with_exception_in_gather(self):
        """Test that exceptions in concurrent launches are propagated."""
        adapter = MockTerminalAdapter(fail_on_launch=True)
        manager = TerminalManager(adapter)

        with pytest.raises(RuntimeError):
            await manager.launch_sessions("echo test", count=3)


# =============================================================================
# TerminalSession Tests
# =============================================================================


class TestTerminalSessionInitialization:
    """Test TerminalSession initialization."""

    @pytest.mark.asyncio
    async def test_session_initialization(self):
        """Test session initialization with required parameters."""
        adapter = MockTerminalAdapter()
        session = TerminalSession("session_123", "echo test", adapter)

        assert session.session_id == "session_123"
        assert session.command == "echo test"
        assert session.adapter is adapter
        assert session.last_output is None
        assert session._output_buffer == []

    @pytest.mark.asyncio
    async def test_session_age_property(self):
        """Test session age calculation."""
        adapter = MockTerminalAdapter()
        session = TerminalSession("session_123", "echo test", adapter)

        age = session.age
        assert isinstance(age, timedelta)
        assert age.total_seconds() >= 0


class TestTerminalSessionOperations:
    """Test TerminalSession operations."""

    @pytest.mark.asyncio
    async def test_session_send_command(self):
        """Test sending command through session wrapper."""
        adapter = MockTerminalAdapter()
        # Register session with adapter first
        adapter._sessions["session_123"] = {"id": "session_123", "command": "cat"}
        session = TerminalSession("session_123", "cat", adapter)

        await session.send("test input")

        assert len(adapter._send_calls) == 1
        assert adapter._send_calls[0] == ("session_123", "test input")

    @pytest.mark.asyncio
    async def test_session_read_output(self):
        """Test reading output through session wrapper."""
        adapter = MockTerminalAdapter()
        # Register session with adapter first
        adapter._sessions["session_123"] = {"id": "session_123", "command": "echo test"}
        session = TerminalSession("session_123", "echo test", adapter)

        output = await session.read(lines=5)

        assert output == "Line 0\nLine 1\nLine 2\nLine 3\nLine 4"
        assert session.last_output == output
        assert output in session._output_buffer

    @pytest.mark.asyncio
    async def test_session_close(self):
        """Test closing session through wrapper."""
        adapter = MockTerminalAdapter()
        # Add session to adapter
        adapter._sessions["session_123"] = {"id": "session_123", "command": "test"}
        session = TerminalSession("session_123", "test", adapter)

        await session.close()

        assert "session_123" not in adapter.sessions
        assert "session_123" in adapter._close_calls

    @pytest.mark.asyncio
    async def test_session_output_history(self):
        """Test getting output history from session."""
        adapter = MockTerminalAdapter()
        # Register session with adapter first
        adapter._sessions["session_123"] = {"id": "session_123", "command": "echo test"}
        session = TerminalSession("session_123", "echo test", adapter)

        await session.read(lines=3)
        await session.read(lines=5)

        history = session.get_output_history()

        assert len(history) == 2
        assert history[0] == "Line 0\nLine 1\nLine 2"
        assert history[1] == "Line 0\nLine 1\nLine 2\nLine 3\nLine 4"

    @pytest.mark.asyncio
    async def test_session_repr(self):
        """Test session string representation."""
        adapter = MockTerminalAdapter()
        session = TerminalSession("session_123", "echo test", adapter)

        repr_str = repr(session)

        assert "session_123" in repr_str
        assert "echo test" in repr_str
        assert "age=" in repr_str


# =============================================================================
# Integration Tests
# =============================================================================


class TestTerminalManagementIntegration:
    """Integration tests for terminal management workflows."""

    @pytest.mark.asyncio
    async def test_complete_session_lifecycle(self):
        """Test complete lifecycle: launch, command, capture, close."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        # Launch
        session_ids = await manager.launch_sessions("cat", count=1)
        session_id = session_ids[0]

        # Send command
        await manager.send_command(session_id, "hello")

        # Capture output
        output = await manager.capture_output(session_id, lines=5)
        assert output

        # Close
        await manager.close_session(session_id)

        assert session_id not in adapter.sessions

    @pytest.mark.asyncio
    async def test_multi_session_workflow(self):
        """Test workflow with multiple sessions."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        # Launch multiple sessions
        session_ids = await manager.launch_sessions("cat", count=5)

        # Send different commands to each
        for i, session_id in enumerate(session_ids):
            await manager.send_command(session_id, f"command_{i}")

        # Capture all outputs
        outputs = await manager.capture_all_outputs(session_ids)

        assert len(outputs) == 5

        # Close all
        await manager.close_all(session_ids)

        assert len(adapter.sessions) == 0

    @pytest.mark.asyncio
    async def test_concurrent_managers(self):
        """Test multiple managers operating concurrently."""
        adapter1 = MockTerminalAdapter()
        adapter2 = MockTerminalAdapter()
        manager1 = TerminalManager(adapter1)
        manager2 = TerminalManager(adapter2)

        # Launch sessions on both managers concurrently
        import asyncio

        results = await asyncio.gather(
            manager1.launch_sessions("echo test", count=3),
            manager2.launch_sessions("echo test", count=4),
        )

        assert len(results[0]) == 3
        assert len(results[1]) == 4
        assert len(adapter1.sessions) == 3
        assert len(adapter2.sessions) == 4


# =============================================================================
# Performance and Edge Cases
# =============================================================================


class TestTerminalManagementEdgeCases:
    """Test edge cases and performance scenarios."""

    @pytest.mark.asyncio
    async def test_launch_large_number_of_sessions(self):
        """Test launching many sessions (50+)."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        session_ids = await manager.launch_sessions("echo test", count=50)

        assert len(session_ids) == 50
        assert len(set(session_ids)) == 50
        assert len(adapter.sessions) == 50

    @pytest.mark.asyncio
    async def test_launch_with_zero_count(self):
        """Test launching zero sessions."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        session_ids = await manager.launch_sessions("echo test", count=0)

        assert session_ids == []
        assert len(adapter.sessions) == 0

    @pytest.mark.asyncio
    async def test_capture_with_zero_lines(self):
        """Test capturing with zero lines returns empty string."""
        adapter = MockTerminalAdapter()
        manager = TerminalManager(adapter)

        session_ids = await manager.launch_sessions("echo test", count=1)
        output = await manager.capture_output(session_ids[0], lines=0)

        assert output == ""

    @pytest.mark.asyncio
    async def test_manager_with_extreme_config_values(self):
        """Test manager with extreme but valid config values."""
        adapter = MockTerminalAdapter()
        config = TerminalSettings(
            max_concurrent_sessions=100,
            default_columns=300,
            default_rows=200,
            capture_lines=10000,
        )
        manager = TerminalManager(adapter, config)

        assert manager.config.max_concurrent_sessions == 100
        assert manager.config.default_columns == 300

        # Should still work with extreme values
        session_ids = await manager.launch_sessions("echo test", count=50)
        assert len(session_ids) == 50
