from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.errors import ErrorCode
from mahavishnu.terminal.adapters.base import SessionNotFoundError, TerminalError


class MockMcpResult:
    def __init__(self, text: str) -> None:
        self.content = [MagicMock(text=text)]


def make_mock_mcp(tool_results: dict[str, Any] | None = None) -> AsyncMock:
    mock = AsyncMock()
    if tool_results:
        mock.call_tool.side_effect = lambda name, params: MockMcpResult(
            tool_results.get(name, "")
        )
    else:
        mock.call_tool.return_value = MockMcpResult("output")
    return mock


@pytest.mark.unit
async def test_adapter_name_is_crow() -> None:
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter

    adapter = CrowTerminalAdapter(make_mock_mcp())
    assert adapter.adapter_name == "crow"


@pytest.mark.unit
async def test_launch_session_returns_session_id() -> None:
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter

    mcp = make_mock_mcp()
    mcp.call_tool.return_value = MockMcpResult("session-abc123")
    adapter = CrowTerminalAdapter(mcp)

    session_id = await adapter.launch_session("bash")
    assert isinstance(session_id, str)
    assert len(session_id) > 0


@pytest.mark.unit
async def test_send_command_unknown_session_raises_session_not_found() -> None:
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter

    adapter = CrowTerminalAdapter(make_mock_mcp())
    with pytest.raises(SessionNotFoundError):
        await adapter.send_command("nonexistent-session", "ls")


@pytest.mark.unit
async def test_send_command_pty_crash_raises_terminal_error_with_mhv307() -> None:
    """A PTY crash in crow-mcp surfaces as TerminalError(MHV-307).

    ``capture_output`` is a local cache read since the crow-mcp terminal
    tool became one-shot (commit b892ab46); ``send_command`` is the method
    that still reaches the server, so that is where the failure surfaces.
    """
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter

    mcp = make_mock_mcp()
    adapter = CrowTerminalAdapter(mcp)
    # Manually register a session to bypass SessionNotFoundError
    adapter._sessions["session-x"] = {"command": "bash"}
    # Make call_tool raise (simulates PTY crash / crow-mcp error)
    mcp.call_tool.side_effect = RuntimeError("PTY crashed")

    with pytest.raises(TerminalError) as exc_info:
        await adapter.send_command("session-x", "ls")

    assert exc_info.value.error_code == ErrorCode.CROW_MCP_UNAVAILABLE


@pytest.mark.unit
async def test_list_sessions_returns_empty_when_none() -> None:
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter

    adapter = CrowTerminalAdapter(make_mock_mcp())
    sessions = await adapter.list_sessions()
    assert sessions == []
