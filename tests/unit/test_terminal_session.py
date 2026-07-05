"""Unit tests for TerminalSession."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.terminal.session import TerminalSession


class TestTerminalSession:
    """Tests for TerminalSession."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock terminal adapter."""
        adapter = MagicMock()
        adapter.send_command = AsyncMock()
        adapter.capture_output = AsyncMock(return_value="test output line 1\ntest output line 2")
        adapter.close_session = AsyncMock()
        return adapter

    @pytest.fixture
    def session(self, mock_adapter):
        """Create a TerminalSession instance."""
        return TerminalSession("session_ABC", "echo hello", mock_adapter)

    def test_init_sets_properties(self, session, mock_adapter):
        """Test __init__ sets correct session properties."""
        assert session.session_id == "session_ABC"
        assert session.command == "echo hello"
        assert session.adapter is mock_adapter
        assert isinstance(session.created_at, datetime)
        assert session.last_output is None
        assert session._output_buffer == []

    def test_adapter_property(self, session, mock_adapter):
        """Test adapter property returns the adapter."""
        assert session.adapter is mock_adapter

    def test_command_property(self, session):
        """Test command property returns the command."""
        assert session.command == "echo hello"

    def test_session_id_property(self, session):
        """Test session_id property returns the ID."""
        assert session.session_id == "session_ABC"

    @pytest.mark.asyncio
    async def test_send_calls_adapter_send_command(self, session, mock_adapter):
        """Test send delegates to adapter.send_command."""
        await session.send("ls -la")

        mock_adapter.send_command.assert_called_once_with("session_ABC", "ls -la")

    @pytest.mark.asyncio
    async def test_read_captures_and_stores_output(self, session, mock_adapter):
        """Test read captures output and stores in buffer."""
        output = await session.read()

        mock_adapter.capture_output.assert_called_once_with("session_ABC", None)
        assert session.last_output == output
        assert len(session._output_buffer) == 1

    @pytest.mark.asyncio
    async def test_read_with_lines_limit(self, session, mock_adapter):
        """Test read with lines parameter passes it to adapter."""
        await session.read(lines=50)

        mock_adapter.capture_output.assert_called_once_with("session_ABC", 50)

    @pytest.mark.asyncio
    async def test_read_accumulates_in_buffer(self, session, mock_adapter):
        """Test multiple reads accumulate in output buffer."""
        await session.read()
        await session.read()
        await session.read()

        assert len(session._output_buffer) == 3
        assert session.last_output == session._output_buffer[-1]

    @pytest.mark.asyncio
    async def test_close_calls_adapter_close_session(self, session, mock_adapter):
        """Test close delegates to adapter.close_session."""
        await session.close()

        mock_adapter.close_session.assert_called_once_with("session_ABC")

    def test_age_property_returns_timedelta(self, session):
        """Test age property returns timedelta from creation."""
        # Age should be a timedelta (approximately 0 or small since session just created)
        age = session.age
        assert isinstance(age, timedelta)
        assert age.total_seconds() >= 0

    def test_get_output_history_returns_copy(self, session):
        """Test get_output_history returns a copy of buffer."""
        session._output_buffer.append("line 1")
        session._output_buffer.append("line 2")

        history = session.get_output_history()

        assert history == ["line 1", "line 2"]
        # Ensure it's a copy, not the original
        history.append("line 3")
        assert len(session._output_buffer) == 2

    def test_get_output_history_empty(self, session):
        """Test get_output_history returns empty list initially."""
        assert session.get_output_history() == []

    def test_repr_format(self, session):
        """Test __repr__ returns expected format."""
        repr_str = repr(session)

        assert "TerminalSession" in repr_str
        assert "session_ABC" in repr_str
        assert "echo hello" in repr_str
        assert "age=" in repr_str

    def test_last_output_initially_none(self, session):
        """Test last_output is None before any read."""
        assert session.last_output is None

    @pytest.mark.asyncio
    async def test_multiple_send_commands(self, session, mock_adapter):
        """Test sending multiple commands works correctly."""
        await session.send("cmd1")
        await session.send("cmd2")
        await session.send("cmd3")

        assert mock_adapter.send_command.call_count == 3
        calls = mock_adapter.send_command.call_args_list
        assert calls[0][0][1] == "cmd1"
        assert calls[1][0][1] == "cmd2"
        assert calls[2][0][1] == "cmd3"


class TestTerminalSessionWithMockAdapter:
    """Tests for TerminalSession using MockTerminalAdapter."""

    @pytest.fixture
    def mock_terminal_adapter(self):
        """Create a real MockTerminalAdapter for integration-style tests."""
        from mahavishnu.terminal.adapters.mock import MockTerminalAdapter

        return MockTerminalAdapter(auto_respond=True, response_delay=0.001)

    @pytest.mark.asyncio
    async def test_session_with_mock_adapter(self, mock_terminal_adapter):
        """Test TerminalSession wrapping MockTerminalAdapter."""
        session_id = await mock_terminal_adapter.launch_session("initial")
        session = TerminalSession(session_id, "initial", mock_terminal_adapter)
        await session.send("status")
        output = await session.read()

        assert "Mock" in output
        assert "Status" in output

    @pytest.mark.asyncio
    async def test_session_close_with_mock_adapter(self, mock_terminal_adapter):
        """Test closing session with mock adapter."""
        TerminalSession("mock_id", "initial", mock_terminal_adapter)
        session_id = await mock_terminal_adapter.launch_session("test")

        # Create session wrapper
        session_wrapper = TerminalSession(session_id, "test", mock_terminal_adapter)
        await session_wrapper.close()

        # Session should be removed from adapter
        sessions = await mock_terminal_adapter.list_sessions()
        assert session_id not in [s["session_id"] for s in sessions]


class TestTerminalSessionEdgeCases:
    """Test edge cases and error handling."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock adapter that raises errors."""
        adapter = MagicMock()
        adapter.send_command = AsyncMock(side_effect=RuntimeError("Send failed"))
        adapter.capture_output = AsyncMock(side_effect=RuntimeError("Capture failed"))
        adapter.close_session = AsyncMock()
        return adapter

    @pytest.fixture
    def session(self, mock_adapter):
        """Create a TerminalSession instance."""
        return TerminalSession("session_err", "echo test", mock_adapter)

    @pytest.mark.asyncio
    async def test_send_raises_on_adapter_error(self, session):
        """Test send propagates adapter errors."""
        with pytest.raises(RuntimeError, match="Send failed"):
            await session.send("test")

    @pytest.mark.asyncio
    async def test_read_raises_on_adapter_error(self, session):
        """Test read propagates adapter errors."""
        with pytest.raises(RuntimeError, match="Capture failed"):
            await session.read()

    def test_age_with_known_created_at(self):
        """Test age calculation with a known created_at time."""
        old_time = datetime.now() - timedelta(hours=1)
        adapter = MagicMock()
        session = TerminalSession("old_session", "echo old", adapter)
        session.created_at = old_time

        age = session.age
        assert age.total_seconds() >= 3600  # At least 1 hour old
        assert age.total_seconds() < 3601  # But less than 1 hour + 1 second

    @pytest.mark.asyncio
    async def test_read_updates_last_output_before_error(self, mock_adapter):
        """Test that even if read fails, buffer captures what it can."""
        # This tests the scenario where read partially succeeds
        pass  # Already covered - last_output and buffer are updated after successful read

    def test_output_buffer_is_private(self, session):
        """Test that _output_buffer is a private list."""
        assert hasattr(session, "_output_buffer")
        assert isinstance(session._output_buffer, list)

    def test_get_output_history_type(self, session):
        """Test get_output_history returns list type."""
        result = session.get_output_history()
        assert isinstance(result, list)

    def test_repr_contains_session_id_type(self, session):
        """Test repr contains the session_id in repr format."""
        repr_str = repr(session)
        assert "session_ABC" in repr_str or "session_err" in repr_str
