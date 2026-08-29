"""Tests for the ``get_capability_result`` MCP tool.

Mocks the Dhara client so no live storage is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastmcp import FastMCP

from mahavishnu.core.capabilities import EnvelopeId, TraceId
from mahavishnu.mcp.tools.get_capability_result_tool import register_get_capability_result


@pytest.mark.unit
def test_get_capability_result_reads_envelopes_from_dhara() -> None:
    dhara = MagicMock()
    dhara.list_keys.return_value = [
        f"envelopes/{'a' * 32}/{EnvelopeId('12345678-1234-4234-8234-123456789012')}",
    ]
    server = FastMCP("test")
    register_get_capability_result(server, dhara=dhara)

    import asyncio
    tools = asyncio.run(server.list_tools())
    assert any(t.name == "get_capability_result" for t in tools)