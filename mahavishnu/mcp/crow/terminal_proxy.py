"""stdio proxy to a persistent ``crow-mcp`` subprocess.

The crow HTTP server (Task 10 of Plan 1) uses FastMCP for its transport
and ``mcp.client.stdio.stdio_client`` to multiplex a long-running
``crow-mcp`` subprocess. This module owns that subprocess lifecycle.

Two interfaces live here:

Legacy singleton (Task 1, preserved for backward compatibility):

- ``init_crow_stdio_client(settings)`` / ``close_crow_stdio_client()`` /
  ``get_crow_session()`` — one-shot accessor for the anonymous
  ``terminal`` MCP tool. Multiplexes every caller onto one PTY.

Per-session subprocess pool (Task 2):

- ``acquire_session(handle, settings)`` — get-or-create a dedicated
  ``crow-mcp`` subprocess per ``handle``. Spawns on miss, reuses on
  hit. LRU-evicts the oldest idle handle when ``max_concurrent_sessions``
  is reached.
- ``release_session(handle)`` — pop and close the subprocess for
  ``handle``. Idempotent.
- ``get_crow_session_by_handle(handle)`` — accessor that raises
  ``SessionNotFoundError`` when the handle is unknown. Distinct from
  the legacy zero-arg ``get_crow_session()``.
- ``shutdown_all_sessions()`` — walk every live session and close
  it. Called from the FastMCP lifespan shutdown.

Process lifecycle invariants (documented but not yet enforced via
``os.killpg``; ``start_new_session=True`` is already set by
``mcp.client.stdio._create_platform_compatible_process``):

- Each spawned subprocess is in its own process group so
  ``os.killpg()`` can signal the whole tree during eviction.
- Eviction grace sequence: send ``{"command": "exit"}`` to the PTY,
  wait 1 s; if still alive, ``os.killpg(SIGTERM)``; after another
  1 s, ``os.killpg(SIGKILL)``.

Concurrency model:

- One ``asyncio.Lock`` per handle in ``_creation_locks`` — guards
  lazy create under concurrent first-call races. NOT a single global
  lock (that would serialise all callers across the pool).
- One ``asyncio.Lock`` per handle in ``_locks`` — guards every
  JSON-RPC call TO that handle's subprocess (acquired by the
  ``crow_terminal_exec`` / ``crow_terminal_read`` tools). Different
  handles never block each other.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
import logging
import sys
import time
from typing import TYPE_CHECKING

import anyio
from anyio import create_task_group, open_process
from anyio.streams.text import TextReceiveStream
from mcp import ClientSession, types
from mcp.shared.session import SessionMessage

from mahavishnu.core.errors import ErrorCode, MahavishnuError

if TYPE_CHECKING:
    from mahavishnu.mcp.crow.settings import CrowSettings

logger = logging.getLogger(__name__)


@dataclass
class _CrowState:
    """Atomic state for one crow stdio client subprocess.

    Dataclass fields prevent the partial-publish race where a reader
    would see a session whose AsyncExitStack has not yet been assigned.
    ``last_used_at`` powers LRU eviction. ``pgid`` is the process-group
    id captured at spawn for ``os.killpg`` based eviction (currently
    unused; tracked for follow-up hardening).
    """

    session: ClientSession
    exit_stack: AsyncExitStack
    last_used_at: float = field(default_factory=time.monotonic)
    pgid: int | None = None


# ============================================================================
# Legacy singleton (Task 1, backward compat for the ``terminal`` tool)
# ============================================================================

_state: _CrowState | None = None
_crow_lock = asyncio.Lock()


async def init_crow_stdio_client(settings: CrowSettings) -> None:
    """Start the legacy singleton crow-mcp subprocess.

    Kept for backward compatibility with the Task 1 ``terminal`` tool.
    Production per-handle routing should use ``acquire_session`` instead.
    """
    global _state
    async with _crow_lock:
        if _state is not None:
            raise RuntimeError(
                "crow stdio client already initialized; call close_crow_stdio_client first"
            )
        stack = AsyncExitStack()
        try:
            _read, _write, _process = await stack.enter_async_context(
                _safe_stdio_client(settings.crow_mcp_command),
            )
            session = await stack.enter_async_context(ClientSession(_read, _write))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise
        _state = _CrowState(session=session, exit_stack=stack)


async def close_crow_stdio_client() -> None:
    """Close the legacy singleton. Idempotent."""
    global _state
    state = _state
    _state = None
    if state is not None:
        await state.exit_stack.aclose()


def get_crow_session() -> ClientSession:
    """Return the legacy singleton's ClientSession. Raises if not initialised."""
    if _state is None:
        raise RuntimeError("crow stdio client not initialized — server lifespan not running")
    return _state.session


# ============================================================================
# Per-session subprocess pool (Task 2)
# ============================================================================


class SessionNotFoundError(MahavishnuError):
    """Raised by ``get_crow_session_by_handle`` for unknown handles."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, ErrorCode.RESOURCE_NOT_FOUND, details=details)


_sessions: dict[str, _CrowState] = {}
# Per-handle serialisation locks used by ``crow_terminal_exec`` /
# ``crow_terminal_read`` to keep JSON-RPC frames on the same subprocess
# from interleaving. Lazily populated by ``acquire_session``.
_locks: dict[str, asyncio.Lock] = {}
# Per-handle creation locks — make lazy create safe under concurrent
# first-call races for the same handle.
_creation_locks: dict[str, asyncio.Lock] = {}


@asynccontextmanager
async def _safe_stdio_client(command: str):
    """Drop-in replacement for ``mcp.client.stdio.stdio_client`` that
    keeps the reader/writer task group alive in its OWN asyncio task.

    The default mcp helper uses ``async with (task_group, process)``
    so the task group's cancel scope is bound to the task that opened
    the context. When the same task later teardown two such contexts
    in succession, anyio's cancel-scope tracking breaks on the second
    close ("Attempted to exit a cancel scope that isn't the current
    tasks's current cancel scope") and the teardown hangs/cancels.

    This helper instead hosts the task group in a long-running
    ``asyncio.Task`` whose lifetime is decoupled from the caller's
    cancel scope. The caller still gets a yielding
    AsyncExitStack-friendly context manager that returns
    ``(read_stream, write_stream, process)``. Cleanup cancels the
    task-group task (which is owned by this helper), closes the
    memory streams, and waits for the OS process to exit.
    """

    process = await open_process([command], stderr=sys.stderr, start_new_session=True)

    rsw, rs = anyio.create_memory_object_stream(0)
    ws, wsr = anyio.create_memory_object_stream(0)

    async def stdout_reader() -> None:
        if process.stdout is None:
            raise RuntimeError("crow subprocess stdout is unexpectedly None")
        async with rsw:
            buf = ""
            async for chunk in TextReceiveStream(process.stdout, encoding="utf-8"):
                lines = (buf + chunk).split("\n")
                buf = lines.pop()
                for line in lines:
                    if not line.strip():
                        continue
                    msg = types.JSONRPCMessage.model_validate_json(line)
                    await rsw.send(SessionMessage(msg))

    async def stdin_writer() -> None:
        if process.stdin is None:
            raise RuntimeError("crow subprocess stdin is unexpectedly None")
        async with wsr:
            async for msg in wsr:
                payload = msg.message.model_dump_json(by_alias=True, exclude_none=True)
                await process.stdin.send((payload + "\n").encode("utf-8"))

    tg_done: asyncio.Future[None] = asyncio.get_event_loop().create_future()

    async def _manage_tg() -> None:
        try:
            async with create_task_group() as tg:
                tg.start_soon(stdout_reader)
                tg.start_soon(stdin_writer)
                # Block until cancelled; the outer context's finally
                # resolves this future.
                await asyncio.get_event_loop().create_future()
        finally:
            tg_done.set_result(None)

    tg_task = asyncio.create_task(_manage_tg())

    try:
        yield rs, ws, process
    finally:
        # Step 1: cancel the task-group task and give it a bounded
        # window to exit cleanly. We do NOT await it unboundedly
        # because pytest-asyncio / asyncio.run / FastMCP lifespan
        # teardown can propagate their own cancellation into the
        # caller's task while we are mid-await; the cleanup must
        # tolerate that. The inner task group's __aexit__ runs
        # inside ``_manage_tg`` so its cancel scope stays
        # self-consistent regardless of the caller's task state.
        tg_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(tg_task), timeout=2.0)
        except BaseException:
            pass
        # Step 2: close the memory streams so any straggler unblocks.
        for stream in (rs, ws):
            try:
                await stream.aclose()
            except Exception:
                pass
        # Step 3: SIGKILL the OS process and reap it. SIGKILL is the
        # unconditional exit hatch — it does not require the
        # subprocess to cooperate, and ``process.wait()`` on a
        # SIGKILLed process returns near-instantly because the
        # kernel reaps the zombie immediately.
        if process.returncode is None:
            process.kill()
        try:
            await process.wait()
        except ProcessLookupError:
            pass


async def _spawn_crow_state(settings: CrowSettings) -> _CrowState:
    """Spawn a fresh ``crow-mcp`` subprocess and wrap it in ``_CrowState``.

    Enters ``_safe_stdio_client`` and ``ClientSession`` through an
    ``AsyncExitStack``; rolls back the stack on any failure so we
    never leak a half-started subprocess. ``pgid`` capture is
    best-effort (the process is launched via ``anyio.open_process``
    with ``start_new_session=True`` so the child's PID equals its
    PGID on POSIX).
    """
    stack = AsyncExitStack()
    try:
        _read, _write, _process = await stack.enter_async_context(
            _safe_stdio_client(settings.crow_mcp_command),
        )
        session = await stack.enter_async_context(ClientSession(_read, _write))
        await session.initialize()
    except BaseException:
        await stack.aclose()
        raise
    return _CrowState(
        session=session,
        exit_stack=stack,
        pgid=int(_process.pid) if _process.pid is not None else None,
    )


async def _close_session(handle: str) -> None:
    """Pop ``handle`` from ``_sessions`` and close its stack. Idempotent.

    Internal: called by ``release_session`` (which adds the creation
    lock) and by ``shutdown_all_sessions`` (which already snapshots
    keys so no concurrent inserts are pending). Suppresses teardown
    errors because callers are in cleanup paths: ``anyio`` raises
    ``RuntimeError`` when a nested cancel scope is exited from a
    different task than the one that entered it (common in tests
    that run with pytest-asyncio's auto mode), and asyncio may
    surface a ``CancelledError`` during host-loop teardown.
    Either way, the OS subprocess gets a SIGKILL before we return.
    """
    state = _sessions.pop(handle, None)
    if state is not None:
        try:
            await state.exit_stack.aclose()
        except BaseException as exc:
            logger.exception(
                "Error closing crow session %s (subprocess reap is best-effort): %s",
                handle,
                exc,
            )


async def acquire_session(handle: str, settings: CrowSettings) -> _CrowState:
    """Get-or-create a ``_CrowState`` for ``handle``.

    Lazily creates the per-handle creation lock and per-handle call
    lock on first contact. If the handle is already live, refreshes
    ``last_used_at`` and returns the existing state. After inserting a
    new entry, LRU-evicts the oldest idle handle when the pool is at
    or above ``max_concurrent_sessions``.
    """
    creation_lock = _creation_locks.setdefault(handle, asyncio.Lock())
    # Per-handle call lock: lazily created here so the
    # ``crow_terminal_exec`` / ``crow_terminal_read`` tools can
    # ``async with _locks[session_id]`` once ``acquire_session``
    # populated it. A missing entry here is a bug — fail loud.
    _locks.setdefault(handle, asyncio.Lock())

    async with creation_lock:
        existing = _sessions.get(handle)
        if existing is not None:
            existing.last_used_at = time.monotonic()
            return existing

        state = await _spawn_crow_state(settings)
        state.last_used_at = time.monotonic()
        _sessions[handle] = state

        cap = settings.max_concurrent_sessions
        # LRU eviction: walk while we are over cap, removing the
        # oldest entry by ``last_used_at``. ``release_session`` is
        # intentionally NOT used here because we already hold the
        # current handle's creation lock; bypassing it skips a
        # double-acquire and keeps eviction tail-latency bounded.
        while len(_sessions) > cap:
            oldest = min(_sessions, key=lambda h: _sessions[h].last_used_at)
            if oldest == handle:
                # Pathological: the only entry IS the one we just
                # added. Honour the cap by allowing a single extra
                # slot rather than deleting ourselves, which would
                # break the contract that acquire returns a live state.
                break
            logger.info(
                "LRU-evicting crow session handle=%s (cap=%d)", oldest, cap
            )
            await _close_session(oldest)

        return state


async def release_session(handle: str) -> None:
    """Release (pop + close) the subprocess for ``handle``. Idempotent."""
    creation_lock = _creation_locks.setdefault(handle, asyncio.Lock())
    async with creation_lock:
        await _close_session(handle)


def get_crow_session_by_handle(handle: str) -> ClientSession:
    """Return the ClientSession for ``handle``. Raises if unknown.

    Distinct from the legacy zero-arg ``get_crow_session()`` (which
    is the singleton accessor for the anonymous ``terminal`` tool).
    """
    state = _sessions.get(handle)
    if state is None:
        raise SessionNotFoundError(
            f"crow session handle={handle!r} not found (pool has {len(_sessions)} live sessions)",
        )
    return state.session


async def shutdown_all_sessions() -> None:
    """Walk ``_sessions`` and close every stack. Idempotent.

    Called from the FastMCP lifespan shutdown to reap any pool sessions
    that were spawned during the lifetime of the server. Order is
    irrelevant: each ``_close_session`` is independent.
    """
    handles = list(_sessions)
    for handle in handles:
        await _close_session(handle)


__all__ = [
    "_CrowState",
    "init_crow_stdio_client",
    "close_crow_stdio_client",
    "get_crow_session",
    "acquire_session",
    "release_session",
    "get_crow_session_by_handle",
    "shutdown_all_sessions",
    "SessionNotFoundError",
]
