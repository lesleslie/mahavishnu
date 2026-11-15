"""Coverage-push test for the 1 missed line in mahavishnu/core/envelopes.py"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.capabilities import EnvelopeAddress, EnvelopeId, TraceId
from mahavishnu.core.envelopes import read_envelope
from mahavishnu.core.errors import ErrorCode, MahavishnuError


@pytest.mark.asyncio
async def test_read_envelope_raises_when_mcp_returns_none() -> None:
    """read_envelope raises MahavishnuError when the KV read returns None.

    The read goes through ``MCPClient.kv_get`` — the live KV tool, not the
    retired service's bare ``get`` name. Mocking the raw ``call_tool`` here
    leaves ``kv_get`` returning a mock, and the test fails with a Pydantic
    ``ValidationError`` that looks like a model bug rather than a stale stub.
    """
    mcp = AsyncMock()
    mcp.kv_get.return_value = None
    addr = EnvelopeAddress(
        trace_id=TraceId("0" * 32),
        envelope_id=EnvelopeId("12345678-1234-4234-8234-123456789012"),
    )
    with pytest.raises(MahavishnuError) as exc_info:
        await read_envelope(addr, mcp=mcp)
    assert exc_info.value.error_code is ErrorCode.RESOURCE_NOT_FOUND
    assert addr.to_key() in str(exc_info.value)
