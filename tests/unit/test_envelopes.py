"""Tests for mahavishnu.core.envelopes — Dhara-backed envelope transport.

Verifies:
- write_envelope uses a typed EnvelopeAddress key and awaits dhara.put()
- write_envelope redacts fields listed in MAHAVISHNU_REDACT_FIELDS before put
- read_envelope round-trips JSON through call_tool('get', ...)
- list_envelopes filters by trace_id prefix even when storage returns extras

Per CLAUDE.md "all orchestration-layer I/O is async", every code path is async.
Per CLAUDE.md "no Any in tool inputs or orchestration state", the trace_id
parameter is a TraceId newtype (not Any).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.capabilities import (
    CapabilityEnvelope,
    EnvelopeAddress,
    EnvelopeId,
    CapabilityId,
    EngineId,
    TraceId,
)
from mahavishnu.core.envelopes import write_envelope, read_envelope, list_envelopes


def _sample_env(trace_id: TraceId = TraceId("0" * 32)) -> CapabilityEnvelope:
    # Valid UUIDv4: third group starts with "4", fourth with 8/9/a/b.
    # The brief's literal "12345678-1234-1234-1234-123456789012" is invalid
    # under the EnvelopeId pattern in capabilities.py — replaced with one
    # that satisfies `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`.
    return CapabilityEnvelope(
        envelope_id=EnvelopeId("12345678-1234-4234-8234-123456789012"),
        capability_id=CapabilityId("worker:bash"),
        engine_id=EngineId("worker-claude-tui"),
        io_out={"output": "hello", "secret_token": "AKIA..."},
        produced_at="2026-08-29T00:00:00Z",
        trace_id=trace_id,
    )


def _dhara_stub() -> AsyncMock:
    """AsyncMock for DharaAdapter; put() is awaited, call_tool() is awaited."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_write_envelope_uses_typed_address() -> None:
    """write_envelope is async; dhara.put() is awaited with the typed key."""
    dhara = _dhara_stub()
    env = _sample_env()
    await write_envelope(env, dhara=dhara)
    expected_key = "envelopes/00000000000000000000000000000000/12345678-1234-4234-8234-123456789012"
    actual_key = dhara.put.call_args[0][0]
    assert actual_key == expected_key
    assert dhara.put.await_count == 1  # was actually awaited, not unawaited coroutine


@pytest.mark.asyncio
async def test_write_envelope_redacts_secret_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """secrets in MAHAVISHNU_REDACT_FIELDS are scrubbed before dhara.put.

    Use monkeypatch.setenv (NOT os.environ direct) so the change doesn't leak
    into later tests.
    """
    monkeypatch.setenv("MAHAVISHNU_REDACT_FIELDS", "secret_token,api_key")
    dhara = _dhara_stub()
    env = _sample_env()
    await write_envelope(env, dhara=dhara)
    payload = dhara.put.call_args[0][1].decode()
    assert "AKIA..." not in payload
    assert "secret_token" in payload  # the key is preserved (the value is redacted)
    assert "<redacted>" in payload


@pytest.mark.asyncio
async def test_read_envelope_roundtrip() -> None:
    """read_envelope uses dhara.call_tool('get', ...) — NOT dhara.get()."""
    dhara = _dhara_stub()
    dhara.call_tool.return_value = (
        '{"envelope_id":"12345678-1234-4234-8234-123456789012",'
        '"capability_id":"worker:bash",'
        '"engine_id":"worker-claude-tui",'
        '"io_out":{"output":"hi"},'
        '"produced_at":"2026-08-29T00:00:00Z",'
        '"trace_id":"00000000000000000000000000000000",'
        '"parent_envelope_ids":[]}'
    )
    addr = EnvelopeAddress(
        trace_id=TraceId("0" * 32),
        envelope_id=EnvelopeId("12345678-1234-4234-8234-123456789012"),
    )
    env = await read_envelope(addr, dhara=dhara)
    assert env.io_out == {"output": "hi"}


@pytest.mark.asyncio
async def test_list_envelopes_filters_by_trace_id() -> None:
    """list_envelopes uses dhara.call_tool('list_keys', {"prefix": ...}) — NOT dhara.list_keys()."""
    dhara = _dhara_stub()
    trace = TraceId("a" * 32)
    other_trace = TraceId("b" * 32)
    dhara.call_tool.return_value = [
        f"envelopes/{trace}/{EnvelopeId('12345678-1234-4234-8234-123456789012')}",
        f"envelopes/{other_trace}/{EnvelopeId('12345678-1234-4234-8234-123456789012')}",
    ]
    addrs = await list_envelopes(trace, dhara=dhara)
    assert len(addrs) == 1
    assert addrs[0].trace_id == trace
