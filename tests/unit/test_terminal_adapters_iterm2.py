"""Unit tests for iTerm2 adapter."""
import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime

from mahavishnu.terminal.adapters.iterm2 import ITerm2Adapter, ITERM2_AVAILABLE
from mahavishnu.terminal.config import TerminalSettings


@pytest.mark.skipif(not ITERM2_AVAILABLE, reason="iterm2 package not available")
class TestITerm2Adapter:
    """Test suite for iTerm2 adapter."""

    @pytest.fixture
    async def mock_connection(self):
        """Create a mock iTerm2 connection."""
        conn = Mock()
        conn.close = AsyncMock()
        return conn

    @pytest.fixture
    async def mock_app(self):
        """Create a mock iTerm2 app."""
        app = Mock()
        return app

    @pytest.fixture
    async def mock_window(self):
        """Create a mock iTerm2 window."""
        window = Mock()
        return window

    @pytest.fixture
    async def mock_tab(self):
        """Create a mock iTerm2 tab."""
        tab = Mock()
        tab.async_close = AsyncMock()
        return tab

    @pytest.fixture
    async def mock_session(self):
        """Create a mock iTerm2 session."""
        session = Mock()
        session.session_id = "test_session_123"
        session.async_send_text = AsyncMock()
        session.async_set_frame_size = AsyncMock()
        session.async_get_screen_contents = AsyncMock()
        return session

    @pytest.fixture
    def mock_screen_contents(self):
        """Create mock screen contents."""
        screen = Mock()
        screen.contents = "line1\nline2\nline3\n"
        return screen

    @pytest.mark.asyncio
    async def test_iterm2_adapter_init(self):
        """Test iTerm2 adapter initialization."""
        with patch('mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE', True):
            adapter = ITerm2Adapter()
            assert adapter.adapter_name == "iterm2"
            assert adapter._connected is False
            assert len(adapter._sessions) == 0

    @pytest.mark.asyncio
    async def test_iterm2_adapter_not_available(self):
        """Test error when iTerm2 is not available."""
        with patch('mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE', False):
            with pytest.raises(ImportError, match="iterm2 package is not available"):
                ITerm2Adapter()

    @pytest.mark.asyncio
    async def test_ensure_connected(self, mock_connection, mock_app):
        """Test connection establishment to iTerm2."""
        with patch('mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE', True), \
             patch('mahavishnu.terminal.adapters.iterm2.iterm2') as mock_iterm2:
            
            # Setup mocks
            mock_iterm2.Connection.async_connect = AsyncMock(return_value=mock_connection)
            mock_iterm2.AsyncApp.async_get = AsyncMock(return_value=mock_app)
            
            adapter = ITerm2Adapter()
            await adapter._ensure_connected()
            
            assert adapter._connected is True
            assert adapter._connection == mock_connection
            assert adapter._app == mock_app

    @pytest.mark.asyncio
    async def test_launch_session(
        self, mock_connection, mock_app, mock_window, mock_tab, mock_session
    ):
        """Test launching a new iTerm2 session."""
        with patch('mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE', True), \
             patch('mahavishnu.terminal.adapters.iterm2.iterm2') as mock_iterm2:
            
            # Setup mocks
            mock_iterm2.Connection.async_connect = AsyncMock(return_value=mock_connection)
            mock_iterm2.AsyncApp.async_get = AsyncMock(return_value=mock_app)
            mock_app.current_terminal_window = mock_window
            mock_window.async_create_tab = AsyncMock(return_value=mock_tab)
            mock_tab.sessions = [mock_session]
            
            adapter = ITerm2Adapter()
            session_id = await adapter.launch_session("echo test", columns=80, rows=24)
            
            assert session_id == "test_session_123"
            assert session_id in adapter._sessions
            assert adapter._sessions[session_id]["command"] == "echo test"
            mock_session.async_send_text.assert_called_once_with("echo test\n")
            mock_session.async_set_frame_size.assert_called_once_with(80, 24)

    @pytest.mark.asyncio
    async def test_send_command(self, mock_connection, mock_session):
        """Test sending a command to a session."""
        with patch('mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE', True):
            adapter = ITerm2Adapter()
            adapter._connected = True
            adapter._sessions["test_session_123"] = {
                "session": mock_session,
                "tab": Mock(),
                "command": "echo test",
                "created_at": datetime.now(),
            }
            
            await adapter.send_command("test_session_123", "ls -la")
            
            mock_session.async_send_text.assert_called_once_with("ls -la\n")

    @pytest.mark.asyncio
    async def test_send_command_session_not_found(self):
        """Test error when sending to non-existent session."""
        with patch('mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE', True):
            adapter = ITerm2Adapter()
            
            with pytest.raises(KeyError, match="Session nonexistent not found"):
                await adapter.send_command("nonexistent", "test")

    @pytest.mark.asyncio
    async def test_capture_output(
        self, mock_connection, mock_session, mock_screen_contents
    ):
        """Test capturing output from a session."""
        with patch('mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE', True):
            adapter = ITerm2Adapter()
            adapter._connected = True
            adapter._sessions["test_session_123"] = {
                "session": mock_session,
                "tab": Mock(),
                "command": "echo test",
                "created_at": datetime.now(),
            }
            
            # Setup mock return value
            mock_session.async_get_screen_contents = AsyncMock(return_value=mock_screen_contents)
            
            output = await adapter.capture_output("test_session_123")
            
            assert output == "line1\nline2\nline3\n"
            mock_session.async_get_screen_contents.assert_called_once()

    @pytest.mark.asyncio
    async def test_capture_output_with_lines(
        self, mock_connection, mock_session, mock_screen_contents
    ):
        """Test capturing limited lines from a session."""
        with patch('mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE', True):
            adapter = ITerm2Adapter()
            adapter._connected = True
            adapter._sessions["test_session_123"] = {
                "session": mock_session,
                "tab": Mock(),
                "command": "echo test",
                "created_at": datetime.now(),
            }
            
            # Setup mock return value
            mock_session.async_get_screen_contents = AsyncMock(return_value=mock_screen_contents)
            
            output = await adapter.capture_output("test_session_123", lines=2)
            
            assert output == "line2\nline3\n"  # Last 2 lines

    @pytest.mark.asyncio
    async def test_close_session(self, mock_connection, mock_tab):
        """Test closing a session."""
        with patch('mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE', True):
            adapter = ITerm2Adapter()
            adapter._connected = True
            adapter._sessions["test_session_123"] = {
                "session": Mock(),
                "tab": mock_tab,
                "command": "echo test",
                "created_at": datetime.now(),
            }
            
            await adapter.close_session("test_session_123")
            
            assert "test_session_123" not in adapter._sessions
            mock_tab.async_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_sessions(self, mock_connection):
        """Test listing all active sessions."""
        with patch('mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE', True):
            adapter = ITerm2Adapter()
            adapter._connected = True
            adapter._sessions = {
                "session_1": {
                    "session": Mock(),
                    "tab": Mock(),
                    "command": "echo test1",
                    "created_at": datetime(2025, 1, 1, 12, 0, 0),
                },
                "session_2": {
                    "session": Mock(),
                    "tab": Mock(),
                    "command": "echo test2",
                    "created_at": datetime(2025, 1, 1, 12, 1, 0),
                },
            }
            
            sessions = await adapter.list_sessions()
            
            assert len(sessions) == 2
            assert sessions[0]["id"] == "session_1"
            assert sessions[0]["command"] == "echo test1"
            assert sessions[0]["adapter"] == "iterm2"

    @pytest.mark.asyncio
    async def test_cleanup(self, mock_connection, mock_tab):
        """Test cleanup method."""
        with patch('mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE', True):
            adapter = ITerm2Adapter()
            adapter._connected = True
            adapter._connection = mock_connection
            adapter._sessions = {
                "test_session_123": {
                    "session": Mock(),
                    "tab": mock_tab,
                    "command": "echo test",
                    "created_at": datetime.now(),
                }
            }
            
            await adapter.cleanup()
            
            assert len(adapter._sessions) == 0
            mock_tab.async_close.assert_called()
            mock_connection.close.assert_called_once()


# Tests for when iTerm2 is not available
class TestITerm2AdapterNotAvailable:
    """Test suite for when iTerm2 is not available."""

    def test_iterm2_available_flag(self):
        """Test ITERM2_AVAILABLE flag when package is missing."""
        # This test always runs, checking the flag
        if ITERM2_AVAILABLE:
            print("Note: iTerm2 package is installed, skipping unavailable tests")
        else:
            assert ITERM2_AVAILABLE is False
            print("Note: iTerm2 package not installed (expected for CI environments)")
