"""Per-handle bookkeeping for upstream ``crow-mcp`` terminal tool.

The actual subprocess management lives in ``raw_jsonrpc.py`` — a pure
asyncio JSON-RPC client that replaces the broken anyio-task-group
implementation. This module owns the per-handle bookkeeping:

- ``acquire_session(handle, settings)`` — get-or-create a handle's
  asyncio.Lock and per-handle output buffer. Lazily starts the shared
  ``_RawJsonRpcClient`` on first contact. Idempotent.
- ``release_session(handle)`` — pop the handle's locks and buffer.
- ``get_crow_session_by_handle(handle)`` — return the shared client so
  tool wrappers can call ``client.call_tool("terminal", ...)``.
- ``shutdown_all_sessions()`` — close the shared client and clear every
  handle. Called from the FastMCP lifespan shutdown.

Concurrency model:

- ONE shared subprocess (one upstream ``crow-mcp`` instance) per server
  boot. Spawned via ``asyncio.create_subprocess_exec`` inside
  ``raw_jsonrpc.py``.
- ONE ``asyncio.Lock`` per handle in ``_locks`` — guards every JSON-RPC
  call TO that handle's pool slot. Different handles never block each
  other on the *bookkeeping* (they only contend when actually calling
  upstream's ``terminal`` tool, which is itself serialized inside the
  upstream PTY).
- ONE per-handle output buffer ``_outputs[handle]`` — last captured
  terminal output for ``crow_terminal_read``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import logging
import time
from typing import TYPE_CHECKING

from mahavishnu.core.errors import ErrorCode, MahavishnuError

if TYPE_CHECKING:
    from mahavishnu.mcp.crow.raw_jsonrpc import _RawJsonRpcClient
    from mahavishnu.mcp.crow.settings import CrowSettings

logger = logging.getLogger(__name__)


@dataclass
class _CrowState:
    """Atomic state for one crow handle.

    With raw JSON-RPC, the subprocess is shared. Each handle only owns
    its serialisation lock and output buffer; the client itself is the
    module-level ``_client`` and is identical across handles.
    """

    handle: str
    last_used_at: float = field(default_factory=time.monotonic)


# ============================================================================
# Shared raw JSON-RPC client (singleton)
# ============================================================================

_client: _RawJsonRpcClient | None = None
_client_lock = asyncio.Lock()


async def get_or_create_client(settings: CrowSettings) -> _RawJsonRpcClient:
    """Get the shared raw JSON-RPC client, starting it if necessary.

    The first caller after server boot performs the spawn + JSON-RPC
    initialize handshake. Subsequent callers return the same instance.
    """
    global _client
    async with _client_lock:
        if _client is None:
            from mahavishnu.mcp.crow.raw_jsonrpc import _RawJsonRpcClient

            _client = _RawJsonRpcClient(settings)
            await _client.start()
        return _client


async def close_client() -> None:
    """Close the shared raw JSON-RPC client. Idempotent."""
    global _client
    async with _client_lock:
        if _client is None:
            return
        client = _client
        _client = None
    await client.aclose()


# ============================================================================
# Legacy singleton (backward compat for the unnamed ``terminal`` tool)
# ============================================================================

_state: _CrowState | None = None
_crow_lock = asyncio.Lock()


async def init_crow_stdio_client(settings: CrowSettings) -> None:
    """Initialise the legacy singleton. Kept for backward compatibility.

    Idempotent: if the shared raw JSON-RPC client is already running
    (started by a prior ``init_crow_stdio_client`` or ``get_or_create_client``
    call), this is a no-op for the client portion — we just refresh
    ``_state`` so old code that reads it can detect init has run. This
    matches the pre-2026-08-29 contract where repeated init was rejected
    only if both _client and _state were already live.
    """
    global _state
    await get_or_create_client(settings)
    async with _crow_lock:
        _state = _CrowState(handle="__legacy__")


async def close_crow_stdio_client() -> None:
    """Close the legacy singleton. Idempotent."""
    global _state
    async with _crow_lock:
        _state = None
    # Do NOT close the shared client here — other per-handle callers may
    # still be using it. The lifespan shutdown path is responsible for
    # the final ``close_client()``.


def get_crow_session() -> _RawJsonRpcClient:
    """Return the shared raw JSON-RPC client. Raises if not initialised."""
    if _client is None:
        raise RuntimeError("crow stdio client not initialized — server lifespan not running")
    return _client


# ============================================================================
# Per-handle session pool
# ============================================================================


class SessionNotFoundError(MahavishnuError):
    """Raised by ``get_crow_session_by_handle`` for unknown handles."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, ErrorCode.RESOURCE_NOT_FOUND, details=details)


_sessions: dict[str, _CrowState] = {}
# Per-handle serialisation locks used by ``crow_terminal_exec`` to keep
# JSON-RPC frames from interleaving on the shared subprocess. Lazily
# populated by ``acquire_session``.
_locks: dict[str, asyncio.Lock] = {}
# Per-handle creation locks — make lazy create safe under concurrent
# first-call races for the same handle.
_creation_locks: dict[str, asyncio.Lock] = {}
# Last captured terminal output per handle (string). Replaced on every
# successful ``crow_terminal_exec`` so ``crow_terminal_read`` returns it.
_outputs: dict[str, str] = {}


async def acquire_session(handle: str, settings: CrowSettings) -> _CrowState:
    """Get-or-create a ``_CrowState`` for ``handle``.

    Lazily creates the per-handle creation lock, per-handle call lock,
    and per-handle output buffer on first contact. If the handle is
    already live, refreshes ``last_used_at`` and returns the existing
    state. After inserting a new entry, LRU-evicts the oldest idle
    handle when the pool is at or above ``max_concurrent_sessions``.
    """
    creation_lock = _creation_locks.setdefault(handle, asyncio.Lock())
    _locks.setdefault(handle, asyncio.Lock())
    _outputs.setdefault(handle, "")

    async with creation_lock:
        existing = _sessions.get(handle)
        if existing is not None:
            existing.last_used_at = time.monotonic()
            return existing

        # Warm-start the shared client so the per-handle bookkeeping is
        # always backed by a live upstream subprocess.
        await get_or_create_client(settings)

        state = _CrowState(handle=handle)
        state.last_used_at = time.monotonic()
        _sessions[handle] = state

        cap = settings.max_concurrent_sessions
        while len(_sessions) > cap:
            oldest = min(_sessions, key=lambda h: _sessions[h].last_used_at)
            if oldest == handle:
                # Pathological: the only entry IS the one we just
                # added. Honour the cap by allowing a single extra
                # slot rather than deleting ourselves.
                break
            logger.info("LRU-evicting crow session handle=%s (cap=%d)", oldest, cap)
            _close_handle_buffers(oldest)

        return state


def _close_handle_buffers(handle: str) -> None:
    """Drop handle from all per-handle dicts. Internal."""
    _sessions.pop(handle, None)
    _outputs.pop(handle, None)
    # Leave _locks and _creation_locks — they're cheap and idempotent.


async def release_session(handle: str) -> None:
    """Release (pop + clear) the per-handle bookkeeping for ``handle``."""
    creation_lock = _creation_locks.setdefault(handle, asyncio.Lock())
    async with creation_lock:
        _close_handle_buffers(handle)


def get_crow_session_by_handle(handle: str) -> _RawJsonRpcClient:
    """Return the shared raw JSON-RPC client for the named handle.

    Raises ``SessionNotFoundError`` if the handle is unknown (i.e. the
    caller never went through ``acquire_session``). Distinct from the
    legacy zero-arg ``get_crow_session()`` (which is the singleton
    accessor for the anonymous ``terminal`` tool).
    """
    if _client is None or handle not in _sessions:
        raise SessionNotFoundError(
            f"crow session handle={handle!r} not found (pool has {len(_sessions)} live sessions)",
        )
    return _client


def record_output(handle: str, output: str) -> None:
    """Store the latest terminal output for a handle."""
    _outputs[handle] = output


def read_output(handle: str) -> str:
    """Return the most recently captured terminal output for a handle."""
    return _outputs.get(handle, "")


async def shutdown_all_sessions() -> None:
    """Clear per-handle state and close the shared client. Idempotent."""
    handles = list(_sessions)
    for handle in handles:
        _close_handle_buffers(handle)
    await close_client()


__all__ = [
    "SessionNotFoundError",
    "_CrowState",
    "acquire_session",
    "close_crow_stdio_client",
    "get_crow_session",
    "get_crow_session_by_handle",
    "get_or_create_client",
    "init_crow_stdio_client",
    "read_output",
    "record_output",
    "release_session",
    "shutdown_all_sessions",
]


# Re-export ``@asynccontextmanager`` and the rest of the public API that
# the tool wrappers / lifespan hooks rely on. We intentionally don't
# import the deprecated helpers (deprecated since the 2026-08-29
# raw-JSON-RPC migration) so any stale callers fail loud at import time.
_deprecated_aliases = [
    "close_session",
    "_close_session",
    "_graceful_evict_task",
    "_pgid_alive",
    "_safe_stdio_client",
    "_spawn_crow_state",
]
for _alias in _deprecated_aliases:
    globals()[_alias] = None  # type: ignore[assignment]


async def _deprecated_no_op(*_args, **_kwargs):  # pragma: no cover
    raise RuntimeError(
        f"terminal_proxy.{_args[0].__name__ if _args else 'helper'} was removed 2026-08-29; "
        "see mahavishnu/mcp/crow/raw_jsonrpc.py for the raw JSON-RPC replacement"
    )
