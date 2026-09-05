"""Coverage-push test for the 1 missed line in mahavishnu/core/envelopes.py"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.capabilities import EnvelopeAddress, EnvelopeId, TraceId
from mahavishnu.core.envelopes import read_envelope
from mahavishnu.core.errors import ErrorCode, MahavishnuError


@pytest.mark.asyncio
async def test_read_envelope_raises_when_dhara_returns_none() -> None:
    """Line 55: read_envelope raises MahavishnuError when call_tool('get') returns None."""
    dhara = AsyncMock()
    dhara.call_tool.return_value = None
    addr = EnvelopeAddress(
        trace_id=TraceId("0" * 32),
        envelope_id=EnvelopeId("12345678-1234-4234-8234-123456789012"),
    )
    with pytest.raises(MahavishnuError) as exc_info:
        await read_envelope(addr, dhara=dhara)
    assert exc_info.value.error_code is ErrorCode.RESOURCE_NOT_FOUND
    assert addr.to_key() in str(exc_info.value)