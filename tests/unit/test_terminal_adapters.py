"""Unit tests for terminal adapters.

Tests BaseAdapter ABC, ITerm2Adapter, McpretentiousAdapter, and MockTerminalAdapter.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.terminal.adapters.base import TerminalAdapter
from mahavishnu.terminal.adapters.iterm2 import (
    OSASCRIPT_AVAILABLE,
    ITerm2Adapter,
)
from mahavishnu.terminal.adapters.mcpretentious import (
    McpretentiousAdapter,
    SessionNotFoundError,
)
from mahavishnu.terminal.adapters.mock import MockTerminalAdapter

# ============================================================================
# BaseAdapter ABC Tests
# ============================================================================


class TestBaseAdapterABC:
    """Tests for TerminalAdapter abstract base class enforcement."""

    def test_cannot_instantiate_base_adapter_directly(self):
        """Test that instantiating TerminalAdapter directly raises TypeError."""
        with pytest.raises(TypeError, match="abstract"):
            TerminalAdapter()

    @pytest.mark.asyncio
    async def test_subclass_must_implement_launch_session(self):
        """Test that subclass without launch_session raises TypeError."""

        class IncompleteAdapter(TerminalAdapter):
            @property
            def adapter_name(self) -> str:
                return "incomplete"

            async def send_command(self, session_id: str, command: str) -> None:
                pass

            async def capture_output(self, session_id: str, lines: int | None = None) -> str:
                return ""

            async def close_session(self, session_id: str) -> None:
                pass

            async def list_sessions(self) -> list[dict]:
                return []

        with pytest.raises(TypeError, match="abstract"):
            IncompleteAdapter()

    @pytest.mark.asyncio
    async def test_subclass_must_implement_send_command(self):
        """Test that subclass without send_command raises TypeError."""

        class IncompleteAdapter(TerminalAdapter):
            @property
            def adapter_name(self) -> str:
                return "incomplete"

            async def launch_session(
                self, command: str, columns: int = 80, rows: int = 24, **kwargs
            ) -> str:
                return "session_id"

            async def capture_output(self, session_id: str, lines: int | None = None) -> str:
                return ""

            async def close_session(self, session_id: str) -> None:
                pass

            async def list_sessions(self) -> list[dict]:
                return []

        with pytest.raises(TypeError, match="abstract"):
            IncompleteAdapter()

    @pytest.mark.asyncio
    async def test_subclass_must_implement_capture_output(self):
        """Test that subclass without capture_output raises TypeError."""

        class IncompleteAdapter(TerminalAdapter):
            @property
            def adapter_name(self) -> str:
                return "incomplete"

            async def launch_session_str(
                self, command: str, columns: int = 80, rows: int = 24, **kwargs
            ) -> str:
                return "session_id"

            async def send_command(self, session_id: str, command: str) -> None:
                pass

            async def close_session(self, session_id: str) -> None:
                pass

            async def list_sessions(self) -> list[dict]:
                return []

        with pytest.raises(TypeError, match="abstract"):
            IncompleteAdapter()

    @pytest.mark.asyncio
    async def test_subclass_must_implement_close_session(self):
        """Test that subclass without close_session raises TypeError."""

        class IncompleteAdapter(TerminalAdapter):
            @property
            def adapter_name(self) -> str:
                return "incomplete"

            async def launch_session(
                self, command: str, columns: int = 80, rows: int = 24, **kwargs
            ) -> str:
                return "session_id"

            async def send_command(self, session_id: str, command: str) -> None:
                pass

            async def capture_output(self, session_id: str, lines: int | None = None) -> str:
                return ""

            async def list_sessions(self) -> list[dict]:
                return []

        with pytest.raises(TypeError, match="abstract"):
            IncompleteAdapter()

    @pytest.mark.asyncio
    async def test_subclass_must_implement_list_sessions(self):
        """Test that subclass without list_sessions raises TypeError."""

        class IncompleteAdapter(TerminalAdapter):
            @property
            def adapter_name(self) -> str:
                return "incomplete"

            async def launch_session(
                self, command: str, columns: int = 80, rows: int = 24, **kwargs
            ) -> str:
                return "session_id"

            async def send_command(self, session_id: str, command: str) -> None:
                pass

            async def capture_output(self, session_id: str, lines: int | None = None) -> str:
                return ""

            async def close_session(self, session_id: str) -> None:
                pass

        with pytest.raises(TypeError, match="abstract"):
            IncompleteAdapter()

    @pytest.mark.asyncio
    async def test_subclass_must_implement_adapter_name_property(self):
        """Test that subclass without adapter_name property raises TypeError."""

        class IncompleteAdapter(TerminalAdapter):
            async def launch_session(
                self, command: str, columns: int = 80, rows: int = 24, **kwargs
            ) -> str:
                return "session_id"

            async def send_command(self, session_id: str, command: str) -> None:
                pass

            async def capture_output(self, session_id: str, lines: int | None = None) -> str:
                return ""

            async def close_session(self, session_id: str) -> None:
                pass

            async def list_sessions(self) -> list[dict]:
                return []

        with pytest.raises(TypeError, match="abstract"):
            IncompleteAdapter()


# ============================================================================
# ITerm2Adapter Tests
# ============================================================================


class MockMCPClientForITerm2:
    """Mock MCP client for testing mcpretentious with ITerm2."""

    def __init__(self):
        self.calls = []
        self.session_counter = 0

    async def call_tool(self, tool, params):
        self.calls.append((tool, params))
        if tool == "mcpretentious-open":
            self.session_counter += 1
            return {"terminal_id": f"term_{self.session_counter}"}
        elif tool == "mcpretentious-read":
            return {"output": "mock output"}
        elif tool == "mcpretentious-list":
            return {"terminals": [{"id": "term_1"}, {"id": "term_2"}]}
        return {}


@pytest.mark.skipif(not OSASCRIPT_AVAILABLE, reason="osascript not available (macOS only)")
class TestITerm2Adapter:
    """Tests for ITerm2Adapter."""

    @pytest.fixture
    def adapter(self):
        """Create an iTerm2 adapter instance."""
        return ITerm2Adapter()

    def test_adapter_name_property(self, adapter):
        """Test adapter_name property returns correct value."""
        assert adapter.adapter_name == "iterm2"

    @pytest.mark.asyncio
    async def test_launch_session_generates_uuid(self, adapter):
        """Test launch_session returns valid UUID[:8] format."""
        with (
            patch.object(
                adapter, "_run_applescript", new_callable=AsyncMock, return_value="win_1,tab_1"
            ),
            patch.object(adapter, "_ensure_iterm2_running"),
        ):
            session_id = await adapter.launch_session("echo test")

        assert session_id is not None
        assert len(session_id) == 8

    @pytest.mark.asyncio
    async def test_launch_session_stores_session_metadata(self, adapter):
        """Test launch_session stores correct metadata."""
        with (
            patch.object(
                adapter, "_run_applescript", new_callable=AsyncMock, return_value="win_1,tab_1"
            ),
            patch.object(adapter, "_ensure_iterm2_running"),
        ):
            session_id = await adapter.launch_session("echo test", 120, 40, profile_name="Work")

        assert session_id in adapter._sessions
        metadata = adapter._sessions[session_id]
        assert metadata["command"] == "echo test"
        assert metadata["profile"] == "Work"
        assert metadata["window"] == "win_1"
        assert metadata["tab"] == "tab_1"

    @pytest.mark.asyncio
    async def test_launch_session_new_window_format(self, adapter):
        """Test launch_session with new_window=True builds correct AppleScript."""
        mock_run = AsyncMock(return_value="win_new")
        with patch.object(adapter, "_run_applescript", mock_run):
            with patch.object(adapter, "_ensure_iterm2_running"):
                await adapter.launch_session("echo test", new_window=True)

        calls = mock_run.call_args_list
        # Only one call - launch_session itself, as new_window=True uses create window AppleScript
        assert len(calls) >= 1
        script = calls[-1][0][0]
        assert "create window" in script.lower()
        assert "return windowid" in script.lower()

    @pytest.mark.asyncio
    async def test_launch_session_tab_format(self, adapter):
        """Test launch_session with tab builds correct AppleScript."""
        mock_run = AsyncMock(return_value="win_1,tab_1")
        with patch.object(adapter, "_run_applescript", mock_run):
            with patch.object(adapter, "_ensure_iterm2_running"):
                await adapter.launch_session("echo test", new_window=False)

        calls = mock_run.call_args_list
        script = calls[-1][0][0]
        assert "create tab" in script.lower()
        assert "tabid" in script.lower()

    @pytest.mark.asyncio
    async def test_send_command_uses_window_tab_identity(self, adapter):
        """Test send_command targets specific window/tab by identity."""
        adapter._sessions["test"] = {
            "command": "initial",
            "created_at": datetime.now(),
            "window": "win_ABC",
            "tab": "tab_XYZ",
            "new_window": False,
        }

        mock_run = AsyncMock(return_value="")
        with patch.object(adapter, "_run_applescript", mock_run):
            await adapter.send_command("test", "ls -la")

        script = mock_run.call_args[0][0]
        assert "window id" in script.lower()
        assert "win_ABC" in script
        assert "tab id" in script.lower()
        assert "tab_XYZ" in script

    @pytest.mark.asyncio
    async def test_send_command_session_not_found(self, adapter):
        """Test send_command raises KeyError for nonexistent session."""
        with pytest.raises(KeyError, match="Session nonexistent not found"):
            await adapter.send_command("nonexistent", "test")

    @pytest.mark.asyncio
    async def test_capture_output_returns_placeholder(self, adapter):
        """Test capture_output returns AppleScript limitation message."""
        adapter._sessions["test"] = {
            "command": "echo hello",
            "created_at": datetime.now(),
        }

        output = await adapter.capture_output("test")

        assert "Output capture not available via AppleScript" in output
        assert "test" in output

    @pytest.mark.asyncio
    async def test_capture_output_session_not_found(self, adapter):
        """Test capture_output raises KeyError for nonexistent session."""
        with pytest.raises(KeyError, match="Session nonexistent not found"):
            await adapter.capture_output("nonexistent")

    @pytest.mark.asyncio
    async def test_close_session_targets_by_identity(self, adapter):
        """Test close_session targets specific window/tab by identity."""
        adapter._sessions["test"] = {
            "command": "test",
            "created_at": datetime.now(),
            "window": "win_123",
            "tab": "tab_456",
            "new_window": False,
        }

        mock_run = AsyncMock(return_value="")
        with patch.object(adapter, "_run_applescript", mock_run):
            await adapter.close_session("test")

        script = mock_run.call_args[0][0]
        assert "window id" in script.lower()
        assert "tab id" in script.lower()
        assert "close" in script.lower()

    @pytest.mark.asyncio
    async def test_close_session_new_window_uses_window_close(self, adapter):
        """Test close_session for new_window=True closes window directly."""
        adapter._sessions["test"] = {
            "command": "test",
            "created_at": datetime.now(),
            "window": "win_789",
            "tab": None,
            "new_window": True,
        }

        mock_run = AsyncMock(return_value="")
        with patch.object(adapter, "_run_applescript", mock_run):
            await adapter.close_session("test")

        script = mock_run.call_args[0][0]
        assert "window id" in script.lower()
        assert "win_789" in script

    @pytest.mark.asyncio
    async def test_close_session_removes_from_tracking(self, adapter):
        """Test close_session removes session from internal tracking."""
        adapter._sessions["test"] = {
            "command": "test",
            "created_at": datetime.now(),
            "window": "win_123",
            "tab": "tab_456",
            "new_window": False,
        }

        with patch.object(adapter, "_run_applescript", new_callable=AsyncMock, return_value=""):
            await adapter.close_session("test")

        assert "test" not in adapter._sessions

    @pytest.mark.asyncio
    async def test_close_session_not_found(self, adapter):
        """Test close_session raises KeyError for nonexistent session."""
        with pytest.raises(KeyError, match="Session nonexistent not found"):
            await adapter.close_session("nonexistent")

    @pytest.mark.asyncio
    async def test_list_sessions_returns_session_info(self, adapter):
        """Test list_sessions returns properly formatted session info."""
        adapter._sessions = {
            "s1": {
                "command": "cmd1",
                "created_at": datetime(2026, 1, 1, 12, 0, 0),
                "profile": None,
                "new_window": False,
                "window": "win_1",
                "tab": "tab_1",
            },
            "s2": {
                "command": "cmd2",
                "created_at": datetime(2026, 1, 1, 12, 1, 0),
                "profile": "Work",
                "new_window": True,
                "window": "win_2",
                "tab": None,
            },
        }

        sessions = await adapter.list_sessions()

        assert len(sessions) == 2
        ids = {s["id"] for s in sessions}
        assert ids == {"s1", "s2"}
        for s in sessions:
            assert s["adapter"] == "iterm2"
            assert "command" in s
            assert "window_id" in s

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, adapter):
        """Test list_sessions returns empty list when no sessions."""
        sessions = await adapter.list_sessions()
        assert sessions == []

    @pytest.mark.asyncio
    async def test_cleanup_closes_all_sessions(self, adapter):
        """Test cleanup closes all tracked sessions."""
        adapter._sessions = {
            "s1": {
                "command": "test",
                "created_at": datetime.now(),
                "window": "win_1",
                "tab": "tab_1",
                "new_window": True,
            },
        }

        with patch.object(adapter, "_run_applescript", new_callable=AsyncMock, return_value=""):
            await adapter.cleanup()

        assert len(adapter._sessions) == 0

    @pytest.mark.asyncio
    async def test_ensure_iterm2_running_calls_applescript(self, adapter):
        """Test _ensure_iterm2_running invokes AppleScript."""
        mock_script = AsyncMock(return_value="")
        with patch.object(adapter, "_run_applescript", mock_script):
            await adapter._ensure_iterm2_running()

        mock_script.assert_called_once()
        script = mock_script.call_args[0][0]
        assert "iTerm2" in script
        assert "launch" in script


class TestITerm2AdapterUnavailable:
    """Tests for iTerm2 adapter when osascript is unavailable."""

    def test_init_raises_import_error_without_osascript(self):
        """Test ITerm2Adapter.__init__ raises ImportError when osascript unavailable."""
        with (
            patch("mahavishnu.terminal.adapters.iterm2.OSASCRIPT_AVAILABLE", False),
            pytest.raises(ImportError, match="osascript not available"),
        ):
            ITerm2Adapter()

    def test_iter2_available_flag_is_boolean(self):
        """Test OSASCRIPT_AVAILABLE is a boolean."""
        assert isinstance(OSASCRIPT_AVAILABLE, bool)


# ============================================================================
# McpretentiousAdapter Tests
# ============================================================================


class TestMcpretentiousAdapter:
    """Tests for McpretentiousAdapter."""

    @pytest.fixture
    def mock_mcp(self):
        """Create a mock MCP client."""
        return MockMCPClientForITerm2()

    @pytest.fixture
    def adapter(self, mock_mcp):
        """Create a mcpretentious adapter with mock MCP client."""
        return McpretentiousAdapter(mock_mcp)

    def test_adapter_name_property(self, adapter):
        """Test adapter_name property returns 'mcpretentious'."""
        assert adapter.adapter_name == "mcpretentious"

    @pytest.mark.asyncio
    async def test_launch_session_calls_open_and_send(self, adapter, mock_mcp):
        """Test launch_session calls mcpretentious-open and sends command."""
        session_id = await adapter.launch_session("echo test", 80, 24)

        assert session_id.startswith("term_")
        assert len(mock_mcp.calls) == 2
        assert mock_mcp.calls[0][0] == "mcpretentious-open"
        assert mock_mcp.calls[1][0] == "mcpretentious-type"

    @pytest.mark.asyncio
    async def test_launch_session_stores_metadata(self, adapter, mock_mcp):
        """Test launch_session stores command metadata."""
        session_id = await adapter.launch_session("echo test", columns=120, rows=40)

        assert session_id in adapter._sessions
        metadata = adapter._sessions[session_id]
        assert metadata["command"] == "echo test"
        assert metadata["columns"] == 120
        assert metadata["rows"] == 40

    @pytest.mark.asyncio
    async def test_send_command_types_with_enter(self, adapter, mock_mcp):
        """Test send_command appends enter key to input."""
        session_id = await adapter.launch_session("cat", 80, 24)
        mock_mcp.calls.clear()

        await adapter.send_command(session_id, "test input")

        assert mock_mcp.calls[0][0] == "mcpretentious-type"
        assert mock_mcp.calls[0][1]["input"] == ["test input", "enter"]

    @pytest.mark.asyncio
    async def test_send_command_session_not_found(self, adapter):
        """Test send_command raises SessionNotFoundError for nonexistent session."""
        with pytest.raises(SessionNotFoundError):
            await adapter.send_command("nonexistent", "test")

    @pytest.mark.asyncio
    async def test_capture_output_with_lines_limit(self, adapter, mock_mcp):
        """Test capture_output sends limit_lines parameter when lines is set."""
        session_id = await adapter.launch_session("echo test", 80, 24)
        mock_mcp.calls.clear()

        await adapter.capture_output(session_id, lines=50)

        assert mock_mcp.calls[0][0] == "mcpretentious-read"
        assert mock_mcp.calls[0][1]["limit_lines"] == 50

    @pytest.mark.asyncio
    async def test_capture_output_no_limit(self, adapter, mock_mcp):
        """Test capture_output does not send limit_lines when None."""
        session_id = await adapter.launch_session("echo test", 80, 24)
        mock_mcp.calls.clear()

        await adapter.capture_output(session_id)

        assert mock_mcp.calls[0][0] == "mcpretentious-read"
        assert "limit_lines" not in mock_mcp.calls[0][1]

    @pytest.mark.asyncio
    async def test_capture_output_session_not_found(self, adapter):
        """Test capture_output raises SessionNotFoundError for nonexistent session."""
        with pytest.raises(SessionNotFoundError):
            await adapter.capture_output("nonexistent")

    @pytest.mark.asyncio
    async def test_close_session_calls_close_tool(self, adapter, mock_mcp):
        """Test close_session calls mcpretentious-close and cleans up metadata."""
        session_id = await adapter.launch_session("echo test", 80, 24)
        assert session_id in adapter._sessions
        mock_mcp.calls.clear()

        await adapter.close_session(session_id)

        assert session_id not in adapter._sessions
        assert any(call[0] == "mcpretentious-close" for call in mock_mcp.calls)

    @pytest.mark.asyncio
    async def test_list_sessions_returns_terminals(self, adapter, mock_mcp):
        """Test list_sessions returns result from mcpretentious-list."""
        sessions = await adapter.list_sessions()

        assert len(sessions) == 2
        assert sessions[0]["id"] == "term_1"


# ============================================================================
# MockTerminalAdapter Tests
# ============================================================================


class TestMockTerminalAdapter:
    """Tests for MockTerminalAdapter."""

    @pytest.fixture
    def adapter(self):
        """Create a MockTerminalAdapter with auto_respond enabled."""
        return MockTerminalAdapter(auto_respond=True, response_delay=0.001)

    @pytest.fixture
    def adapter_no_auto(self):
        """Create a MockTerminalAdapter with auto_respond disabled."""
        return MockTerminalAdapter(auto_respond=False, response_delay=0.0)

    def test_adapter_name_property(self, adapter):
        """Test adapter_name property returns 'mock'."""
        assert adapter.adapter_name == "mock"

    @pytest.mark.asyncio
    async def test_launch_session_generates_uuid(self, adapter):
        """Test launch_session returns UUID[:8] format session ID."""
        session_id = await adapter.launch_session("qwen", 120, 40)

        assert session_id is not None
        assert len(session_id) == 8
        assert session_id in adapter._sessions

    @pytest.mark.asyncio
    async def test_launch_session_stores_metadata(self, adapter):
        """Test launch_session stores correct metadata."""
        session_id = await adapter.launch_session("qwen", columns=120, rows=40)

        metadata = adapter._sessions[session_id]
        assert metadata["command"] == "qwen"
        assert metadata["columns"] == 120
        assert metadata["rows"] == 40
        assert "created_at" in metadata
        assert len(metadata["output_buffer"]) > 0  # Initial mock output

    @pytest.mark.asyncio
    async def test_send_command_adds_to_history(self, adapter):
        """Test send_command records command in history."""
        session_id = await adapter.launch_session("initial")
        await adapter.send_command(session_id, "cmd1")
        await adapter.send_command(session_id, "cmd2")

        history = adapter.get_command_history(session_id)
        assert "initial" in history
        assert "cmd1" in history
        assert "cmd2" in history

    @pytest.mark.asyncio
    async def test_send_command_session_not_found(self, adapter):
        """Test send_command raises ValueError for nonexistent session."""
        with pytest.raises(ValueError, match="Session nonexistent not found"):
            await adapter.send_command("nonexistent", "test")

    @pytest.mark.asyncio
    async def test_capture_output_returns_buffer(self, adapter):
        """Test capture_output returns full output buffer."""
        session_id = await adapter.launch_session("qwen")
        await adapter.send_command(session_id, "status")

        output = await adapter.capture_output(session_id)

        assert "[Mock Terminal Started" in output
        assert "status" in output

    @pytest.mark.asyncio
    async def test_capture_output_with_line_limit(self, adapter):
        """Test capture_output with lines limit returns last N buffer entries."""
        session_id = await adapter.launch_session("qwen")
        await adapter.send_command(session_id, "cmd1")
        await adapter.send_command(session_id, "cmd2")
        await adapter.send_command(session_id, "cmd3")

        output = await adapter.capture_output(session_id, lines=2)

        lines = output.split("\n")
        # Should contain last 2 buffer entries
        assert len([l for l in lines if l.strip()]) >= 2

    @pytest.mark.asyncio
    async def test_capture_output_session_not_found(self, adapter):
        """Test capture_output raises ValueError for nonexistent session."""
        with pytest.raises(ValueError, match="Session nonexistent not found"):
            await adapter.capture_output("nonexistent")

    @pytest.mark.asyncio
    async def test_close_session_removes_from_tracking(self, adapter):
        """Test close_session removes session from internal tracking."""
        session_id = await adapter.launch_session("qwen")
        assert session_id in adapter._sessions

        await adapter.close_session(session_id)

        assert session_id not in adapter._sessions
        assert session_id not in adapter._command_history

    @pytest.mark.asyncio
    async def test_list_sessions_returns_session_info(self, adapter):
        """Test list_sessions returns list of session info dicts."""
        await adapter.launch_session("cmd1")
        await adapter.launch_session("cmd2")

        sessions = await adapter.list_sessions()

        assert len(sessions) == 2
        assert all("session_id" in s for s in sessions)
        assert all("command" in s for s in sessions)
        assert all("created_at" in s for s in sessions)

    @pytest.mark.asyncio
    async def test_mock_response_help_command(self, adapter):
        """Test mock response for help command."""
        session_id = await adapter.launch_session("qwen")
        await adapter.send_command(session_id, "help")

        output = await adapter.capture_output(session_id)
        assert "Available commands" in output

    @pytest.mark.asyncio
    async def test_mock_response_status_command(self, adapter):
        """Test mock response for status command."""
        session_id = await adapter.launch_session("qwen")
        await adapter.send_command(session_id, "status")

        output = await adapter.capture_output(session_id)
        assert "Status: OK" in output

    @pytest.mark.asyncio
    async def test_mock_response_echo_command(self, adapter):
        """Test mock response for echo command."""
        session_id = await adapter.launch_session("qwen")
        await adapter.send_command(session_id, "echo hello world")

        output = await adapter.capture_output(session_id)
        assert "hello world" in output

    @pytest.mark.asyncio
    async def test_mock_response_exit_command(self, adapter):
        """Test mock response for exit command."""
        session_id = await adapter.launch_session("qwen")
        await adapter.send_command(session_id, "exit")

        output = await adapter.capture_output(session_id)
        assert "Session ended" in output

    @pytest.mark.asyncio
    async def test_mock_response_unknown_command(self, adapter):
        """Test mock response for unknown command returns exit code 0."""
        session_id = await adapter.launch_session("qwen")
        await adapter.send_command(session_id, "unknown cmd")

        output = await adapter.capture_output(session_id)
        assert "Executed: unknown cmd" in output
        assert "Return code: 0" in output

    @pytest.mark.asyncio
    async def test_auto_respond_disabled(self, adapter_no_auto):
        """Test that auto_respond=False skips mock response generation."""
        session_id = await adapter_no_auto.launch_session("qwen")
        await adapter_no_auto.send_command(session_id, "test")

        output = await adapter_no_auto.capture_output(session_id)
        # Only input line, no mock response
        lines = [l for l in output.split("\n") if l.strip()]
        assert len(lines) == 2  # Initial + command

    @pytest.mark.asyncio
    async def test_get_command_history_empty_for_unknown_session(self, adapter):
        """Test get_command_history returns [] for unknown session."""
        history = adapter.get_command_history("nonexistent")
        assert history == []

    @pytest.mark.asyncio
    async def test_adapter_exports_all_required_methods(self):
        """Test MockTerminalAdapter implements all TerminalAdapter methods."""
        methods = [
            "launch_session",
            "send_command",
            "capture_output",
            "close_session",
            "list_sessions",
        ]
        for method_name in methods:
            assert hasattr(MockTerminalAdapter, method_name)
