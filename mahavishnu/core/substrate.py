"""The substrate facade — how the server's producers reach its own store.

Every producer in the server (the ecosystem service/event registry, the
workflow outcome log, the approval decision log, the webhook ingress log)
persists through this module. It replaced a dynamic module lookup that
resolved ``mcp.<name>`` — a name that belonged to the decommissioned
storage service's client package and now resolves to the MCP Python SDK,
which has none of those functions. Every lookup therefore returned
``None`` and every producer silently discarded its data.

The contract the call sites use, and why it is shaped this way:

* :func:`put` is **synchronous**. The producers are sync functions
  (``record_workflow_outcome``, ``record_approval_decision``, the
  ``/webhook`` route), and a sync write cannot be an HTTP round-trip
  without blocking the event loop.
* :func:`get` is **awaitable**. Reads were MCP tool calls, so they were
  coroutines; the store read underneath is synchronous.
* :func:`list_prefix` is **synchronous**, mirroring the retired
  ``list(prefix, ...)``.

Values are JSON-encoded on write and decoded on read, so the store keeps
its string-shape contract and a sibling component reading the same key
through ``mahavishnu_kv_get`` sees the same payload.
"""

from __future__ import annotations

import json
from typing import Any

import msgspec
from oneiric.core.logging import get_logger

from mahavishnu.core.kv_store import kv_store

logger = get_logger(__name__)


def _encode(value: Any) -> str:
    """Serialize a payload to the string the store holds.

    Accepts a ``msgspec`` struct (converted to its builtin form) or any
    JSON-encodable object. A string is JSON-encoded like any other
    value, so every payload round-trips exactly: a bare string would
    otherwise be indistinguishable from a record that failed to decode.
    """
    if isinstance(value, msgspec.Struct):
        value = msgspec.to_builtins(value)
    return json.dumps(value, separators=(",", ":"), default=str)


def _decode(raw: str | None) -> Any | None:
    """Decode a stored string back into its payload.

    Returns ``None`` for a miss or an undecodable value — a corrupt
    record reads as absent rather than crashing the reader.
    """
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError, TypeError:
        return None


def put(key: str, value: Any) -> bool:
    """Persist ``value`` under ``key``.

    Synchronous by contract — the producers that call it are sync
    functions. Failures are logged and swallowed: the substrate is
    non-authoritative, so a write failure degrades the producer rather
    than crashing the request that triggered it.

    Returns:
        ``True`` when the record landed, ``False`` when it did not. The
        return value is what makes a failed write *detectable*: a
        producer that counts successes must not report one when the
        write was swallowed. Swallowing the exception is what keeps the
        producer alive; returning ``False`` is what keeps the failure
        visible.
    """
    try:
        kv_store.put(key, _encode(value))
    except Exception as exc:  # noqa: BLE001 — substrate writes are non-authoritative
        logger.warning(
            "substrate_put_failed",
            extra={"key": key, "reason": type(exc).__name__},
        )
        return False
    return True


async def get(key: str) -> Any | None:
    """Read the payload stored under ``key``, or ``None`` on a miss.

    Awaitable by contract — reads were MCP tool calls. The underlying
    store read is synchronous.
    """
    return _decode(kv_store.get(key))


def list_prefix(prefix: str) -> list[Any]:
    """Return every payload whose key starts with ``prefix``.

    Synchronous by contract. Filters (``since`` / ``status``) are the
    reader's business — the retired API applied them server-side, but
    the only caller applies them to the returned payloads itself, which
    keeps this facade generic over any key prefix.
    """
    return [_decode(value) for _key, value in kv_store.list_prefix(prefix)]


def delete(key: str) -> None:
    """Remove ``key`` from the store, if present."""
    kv_store.delete(key)


__all__ = ["delete", "get", "list_prefix", "put"]
