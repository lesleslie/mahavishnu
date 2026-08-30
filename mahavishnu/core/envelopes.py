"""Dhara-backed envelope transport for inter-engine state handoff.

Each envelope is a CapabilityEnvelope JSON blob keyed by
``envelopes/<trace_id>/<envelope_id>``. Secrets are redacted from io_out
before persistence — see MAHAVISHNU_REDACT_FIELDS env var (comma-separated
field names whose values are scrubbed before dhara.put).

All envelope operations are async (CLAUDE.md "all orchestration-layer I/O
is async"). DharaClient is at mahavishnu/core/dhara_adapter.py:18; its
public API is ``async def put(self, key, value, ttl=None)`` plus the
``async def call_tool(self, name, arguments: dict[str, Any])`` shim used
for get/list_keys.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from mahavishnu.core.capabilities import (
    CapabilityEnvelope,
    EnvelopeAddress,
    TraceId,
)
from mahavishnu.core.errors import ErrorCode, MahavishnuError

if TYPE_CHECKING:
    from mahavishnu.core.dhara_adapter import DharaClient


_REDACTED = "<redacted>"


def _redact(env: CapabilityEnvelope) -> CapabilityEnvelope:
    """Return a copy of env with fields in MAHAVISHNU_REDACT_FIELDS scrubbed."""
    raw = os.environ.get("MAHAVISHNU_REDACT_FIELDS", "")
    redact = {f.strip() for f in raw.split(",") if f.strip()}
    if not redact:
        return env
    scrubbed_io = {k: (_REDACTED if k in redact else v) for k, v in env.io_out.items()}
    return env.model_copy(update={"io_out": scrubbed_io})


async def write_envelope(env: CapabilityEnvelope, *, dhara: DharaClient) -> None:
    """Persist a (redacted) envelope to Dhara. Awaits dhara.put()."""
    addr = EnvelopeAddress(trace_id=env.trace_id, envelope_id=env.envelope_id)
    scrubbed = _redact(env)
    await dhara.put(addr.to_key(), scrubbed.model_dump_json().encode())


async def read_envelope(addr: EnvelopeAddress, *, dhara: DharaClient) -> CapabilityEnvelope:
    """Load an envelope from Dhara via call_tool('get', ...). Raises if missing."""
    raw = await dhara.call_tool("get", {"key": addr.to_key()})
    if raw is None:
        raise MahavishnuError(
            f"envelope not found at {addr.to_key()}",
            ErrorCode.RESOURCE_NOT_FOUND,
        )
    return CapabilityEnvelope.model_validate_json(raw)


async def list_envelopes(trace_id: TraceId, *, dhara: DharaClient) -> list[EnvelopeAddress]:
    """Return every envelope address under ``envelopes/<trace_id>/``.

    The prefix filter is applied both at the storage call AND defensively in
    Python so callers don't see cross-trace keys if the storage layer returns
    extras (e.g. a stub that ignores the prefix arg).
    """
    prefix = f"envelopes/{trace_id}/"
    keys = await dhara.call_tool("list_keys", {"prefix": prefix})
    return [EnvelopeAddress.from_key(k) for k in keys if k.startswith(prefix)]


__all__ = ["list_envelopes", "read_envelope", "write_envelope"]
