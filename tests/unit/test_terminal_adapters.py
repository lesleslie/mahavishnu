"""Unit tests for terminal adapters."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from mahavishnu.terminal.adapters.iterm2 import ITerm2Adapter
from mahavishnu.terminal.adapters.mcpretentious import (
    McpretentiousAdapter,
    SessionNotFoundError,
    TerminalError,
)
from mahavishnu.terminal.adapters.mock import MockTerminalAdapter


class MockMCPClient:
    """Mock MCP client for testing mcpretentious adapter."""

    def __init__(self):
        self.calls = []
        self.session_counter = 0

    async def call_tool(self, tool, params):
        """Mock call_tool method."""
        self.calls.append((tool, params))
        if tool == "mcpretentious-open":
            self.session_counter += 1
            return {"terminal_id": f"term_{self.session_counter}"}
        elif tool == "mcpretentious-read":
            return {"output": "mock output"}
        elif tool == "mcpretentious-list":
            return {"terminals": [{"id": "term_1"}, {"id": "term_2"}]}
        return {}


# ============================================================================
# Mcpretentious Adapter Tests
# ============================================================================


class TestMcpretentiousAdapter:
    """Tests for McpretentiousAdapter."""

    @pytest.fixture
    def mock_mcp(self):
        """Create a mock MCP client."""
        return MockMCPClient()

    @pytest.fixture
    def adapter(self, mock_mcp):
        """Create a mcpretentious adapter with mock MCP client."""
        return McpretentiousAdapter(mock_mcp)

    @pytest.mark.asyncio
    async def test_launch_session(self, adapter, mock_mcp):
        """Test launching a session via mcpretentious adapter."""
        session_id = await adapter.launch_session("echo test", 80, 24)

        assert session_id.startswith("term_")
        assert len(mock_mcp.calls) == 2  # open + send command
        assert mock_mcp.calls[0][0] == "mcpretentious-open"
        assert mock_mcp.calls[1][0] == "mcpretentious-type"
        assert mock_mcp.calls[1][1]["input"] == ["echo test", "enter"]

        # Check session metadata
        assert session_id in adapter._sessions
        assert adapter._sessions[session_id]["command"] == "echo test"

    @pytest.mark.asyncio
    async def test_send_command(self, adapter, mock_mcp):
        """Test sending command to session."""
        # Launch a session first
        session_id = await adapter.launch_session("cat", 80, 24)
        mock_mcp.calls.clear()

        # Send command
        await adapter.send_command(session_id, "test input")

        assert len(mock_mcp.calls) == 1
        assert mock_mcp.calls[0][0] == "mcpretentious-type"
        assert mock_mcp.calls[0][1]["terminal_id"] == session_id
        assert mock_mcp.calls[0][1]["input"] == ["test input", "enter"]

    @pytest.mark.asyncio
    async def test_send_command_session_not_found(self, adapter):
        """Test sending command to non-existent session raises SessionNotFoundError."""
        with pytest.raises(SessionNotFoundError) as exc_info:
            await adapter.send_command("nonexistent", "test")

        assert "nonexistent" in str(exc_info.value.details.get("session_id", ""))

    @pytest.mark.asyncio
    async def test_capture_output(self, adapter, mock_mcp):
        """Test capturing output with line limit."""
        # Launch a session first
        session_id = await adapter.launch_session("echo test", 80, 24)
        mock_mcp.calls.clear()

        # Capture output
        output = await adapter.capture_output(session_id, lines=50)

        assert output == "mock output"
        assert len(mock_mcp.calls) == 1
        assert mock_mcp.calls[0][0] == "mcpretentious-read"
        assert mock_mcp.calls[0][1]["terminal_id"] == session_id
        assert mock_mcp.calls[0][1]["limit_lines"] == 50

    @pytest.mark.asyncio
    async def test_capture_output_no_limit(self, adapter, mock_mcp):
        """Test capturing output without line limit."""
        # Launch a session first
        session_id = await adapter.launch_session("echo test", 80, 24)
        mock_mcp.calls.clear()

        # Capture output without limit
        output = await adapter.capture_output(session_id)

        assert output == "mock output"
        assert mock_mcp.calls[0][0] == "mcpretentious-read"
        assert "limit_lines" not in mock_mcp.calls[0][1]

    @pytest.mark.asyncio
    async def test_capture_output_session_not_found(self, adapter):
        """Test capturing output from non-existent session raises SessionNotFoundError."""
        with pytest.raises(SessionNotFoundError):
            await adapter.capture_output("nonexistent")

    @pytest.mark.asyncio
    async def test_close_session(self, adapter, mock_mcp):
        """Test closing a session."""
        # Launch a session first
        session_id = await adapter.launch_session("echo test", 80, 24)
        assert session_id in adapter._sessions

        # Close session
        await adapter.close_session(session_id)

        assert session_id not in adapter._sessions
        assert any(call[0] == "mcpretentious-close" for call in mock_mcp.calls)

    @pytest.mark.asyncio
    async def test_list_sessions(self, mock_mcp):
        """Test listing sessions."""
        adapter = McpretentiousAdapter(mock_mcp)
        sessions = await adapter.list_sessions()

        assert len(sessions) == 2
        assert sessions[0]["id"] == "term_1"

    @pytest.mark.asyncio
    async def test_adapter_name(self, adapter):
        """Test adapter name property."""
        assert adapter.adapter_name == "mcpretentious"


# ============================================================================
# Mock Terminal Adapter Tests
# ============================================================================


class TestMockTerminalAdapter:
    """Tests for MockTerminalAdapter."""

    @pytest.fixture
    def adapter(self):
        """Create a mock terminal adapter."""
        return MockTerminalAdapter(auto_respond=True, response_delay=0.01)

    @pytest.mark.asyncio
    async def test_launch_session(self, adapter):
        """Test launching a mock session."""
        session_id = await adapter.launch_session("qwen", 120, 40)

        assert session_id is not None
        assert len(session_id) == 8  # UUID[:8]
        assert session_id in adapter._sessions
        assert adapter._sessions[session_id]["command"] == "qwen"
        assert adapter._sessions[session_id]["columns"] == 120
        assert adapter._sessions[session_id]["rows"] == 40

    @pytest.mark.asyncio
    async def test_send_command(self, adapter):
        """Test sending command to mock session."""
        session_id = await adapter.launch_session("qwen")

        await adapter.send_command(session_id, "hello")

        # Check command was recorded
        history = adapter.get_command_history(session_id)
        assert "hello" in history

        # Check output buffer
        output = await adapter.capture_output(session_id)
        assert "hello" in output

    @pytest.mark.asyncio
    async def test_send_command_auto_respond(self, adapter):
        """Test auto-respond generates mock output."""
        session_id = await adapter.launch_session("qwen")

        await adapter.send_command(session_id, "status")

        output = await adapter.capture_output(session_id)
        assert "[Mock]" in output
        assert "Status: OK" in output

    @pytest.mark.asyncio
    async def test_send_command_session_not_found(self, adapter):
        """Test sending command to non-existent session."""
        with pytest.raises(ValueError, match="Session .* not found"):
            await adapter.send_command("nonexistent", "test")

    @pytest.mark.asyncio
    async def test_capture_output(self, adapter):
        """Test capturing output from mock session."""
        session_id = await adapter.launch_session("qwen")
        await adapter.send_command(session_id, "echo hello")

        output = await adapter.capture_output(session_id)

        assert "[Mock Terminal Started" in output
        assert "echo hello" in output

    @pytest.mark.asyncio
    async def test_capture_output_with_line_limit(self, adapter):
        """Test capturing output with line limit."""
        session_id = await adapter.launch_session("qwen")
        await adapter.send_command(session_id, "cmd1")
        await adapter.send_command(session_id, "cmd2")
        await adapter.send_command(session_id, "cmd3")

        # Capture only last 2 buffer entries
        # Note: The mock adapter limits buffer entries, not output lines
        output = await adapter.capture_output(session_id, lines=2)

        # Should contain cmd3 output (last 2 buffer entries)
        assert "cmd3" in output

    @pytest.mark.asyncio
    async def test_capture_output_session_not_found(self, adapter):
        """Test capturing from non-existent session."""
        with pytest.raises(ValueError, match="Session .* not found"):
            await adapter.capture_output("nonexistent")

    @pytest.mark.asyncio
    async def test_close_session(self, adapter):
        """Test closing a mock session."""
        session_id = await adapter.launch_session("qwen")
        assert session_id in adapter._sessions

        await adapter.close_session(session_id)

        assert session_id not in adapter._sessions
        assert session_id not in adapter._command_history

    @pytest.mark.asyncio
    async def test_list_sessions(self, adapter):
        """Test listing mock sessions."""
        await adapter.launch_session("cmd1")
        await adapter.launch_session("cmd2")

        sessions = await adapter.list_sessions()

        assert len(sessions) == 2
        assert all("session_id" in s for s in sessions)
        assert all("command" in s for s in sessions)

    @pytest.mark.asyncio
    async def test_adapter_name(self, adapter):
        """Test adapter name property."""
        assert adapter.adapter_name == "mock"

    @pytest.mark.asyncio
    async def test_mock_response_patterns(self, adapter):
        """Test mock response generation patterns."""
        session_id = await adapter.launch_session("qwen")

        # Test help command
        await adapter.send_command(session_id, "help")
        output = await adapter.capture_output(session_id)
        assert "Available commands" in output

        # Test status command
        await adapter.send_command(session_id, "status")
        output = await adapter.capture_output(session_id)
        assert "Status: OK" in output

        # Test echo command
        await adapter.send_command(session_id, "echo test message")
        output = await adapter.capture_output(session_id)
        assert "test message" in output

    @pytest.mark.asyncio
    async def test_no_auto_respond(self):
        """Test adapter with auto_respond disabled."""
        adapter = MockTerminalAdapter(auto_respond=False, response_delay=0.01)
        session_id = await adapter.launch_session("qwen")

        await adapter.send_command(session_id, "test")

        output = await adapter.capture_output(session_id)
        # Should only have the command, no response
        assert "$ test" in output
        # No mock response since auto_respond is False
        lines = output.split("\n")
        # Should not contain [Mock] response for this specific command
        mock_responses = [l for l in lines if "[Mock] Executed: test" in l]
        assert len(mock_responses) == 0

    @pytest.mark.asyncio
    async def test_get_command_history(self, adapter):
        """Test getting command history."""
        session_id = await adapter.launch_session("initial")

        await adapter.send_command(session_id, "cmd1")
        await adapter.send_command(session_id, "cmd2")

        history = adapter.get_command_history(session_id)

        assert "initial" in history  # Launch command
        assert "cmd1" in history
        assert "cmd2" in history

    @pytest.mark.asyncio
    async def test_get_command_history_nonexistent_session(self, adapter):
        """Test getting history for non-existent session."""
        history = adapter.get_command_history("nonexistent")
        assert history == []


# ============================================================================
# Adapter Selection Tests
# ============================================================================


class TestAdapterSelection:
    """Tests for selecting appropriate adapter."""

    def test_mock_adapter_for_testing(self):
        """Mock adapter should be used for testing."""
        adapter = MockTerminalAdapter()
        assert adapter.adapter_name == "mock"

    def test_mcpretentious_adapter_requires_mcp(self):
        """Mcpretentious adapter requires MCP client."""
        mock_mcp = MockMCPClient()
        adapter = McpretentiousAdapter(mock_mcp)
        assert adapter.adapter_name == "mcpretentious"
