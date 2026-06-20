from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter
from mahavishnu.terminal.adapters.mcpretentious import TerminalError


@pytest.fixture()
def mock_mcp() -> AsyncMock:
    mcp = AsyncMock()
    result = MagicMock()
    result.content = [MagicMock(text="$ ")]
    mcp.call_tool.return_value = result
    return mcp


@pytest.mark.unit
async def test_capture_output_failure_raises_terminal_error(
    mock_mcp: AsyncMock,
) -> None:
    adapter = CrowTerminalAdapter(mcp_client=mock_mcp)
    session_id = await adapter.launch_session("bash", columns=80, rows=24)

    # Simulate crow-mcp restart: subsequent calls fail
    mock_mcp.call_tool.side_effect = Exception("session not found in crow-mcp")

    with pytest.raises(TerminalError) as exc_info:
        await adapter.capture_output(session_id)

    assert exc_info.value.error_code == "MHV-307"


@pytest.mark.unit
async def test_close_session_failure_does_not_propagate(
    mock_mcp: AsyncMock,
) -> None:
    adapter = CrowTerminalAdapter(mcp_client=mock_mcp)
    session_id = await adapter.launch_session("bash", columns=80, rows=24)

    # Simulate crow-mcp restart: close call fails
    mock_mcp.call_tool.side_effect = Exception("connection refused")

    # Must NOT raise — cleanup should log and continue
    await adapter.close_session(session_id)

    # Session must be removed from local tracking
    sessions = await adapter.list_sessions()
    assert not any(s["id"] == session_id for s in sessions)
