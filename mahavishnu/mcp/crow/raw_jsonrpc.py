"""Raw JSON-RPC client for an upstream ``crow-mcp`` subprocess.

Why this exists: the previous design used ``mcp.client.stdio.stdio_client``
plus ``mcp.ClientSession`` for the per-tool call_tool round-trip. Inside
FastMCP's HTTP handler (which opens an anyio task group), MCP SDK's
``ClientSession._handle_message`` opens its own anyio task group, and
the two task groups' cancel-scope tracking collides:

    RuntimeError: Attempted to exit a cancel scope that isn't the
    current tasks's current cancel scope

Surfaced to the MCP caller as a generic ``"Session not found"`` error on
the second tool call after a successful open.

This module replaces ``ClientSession`` with a hand-rolled raw JSON-RPC
loop driven entirely by ``asyncio.Task`` (no anyio task group, no
cancel-scope nesting). The subprocess is spawned via
``asyncio.create_subprocess_exec``; the reader coroutine parses
JSON-RPC frames off the stdout pipe; the writer is an async generator
that pushes onto a per-call ``asyncio.Queue``. Per-call serialization is
a single global ``asyncio.Lock`` since upstream's ``terminal`` tool
multiplexes every caller onto a single PTY.

Layered on top: ``mahavishnu/mcp/crow/terminal_proxy.py`` keeps its
per-handle bookkeeping (``_sessions`` / ``_locks`` / ``_creation_locks``)
so the rest of the system can keep calling ``acquire_session(handle)``
without churn. Each handle's session is just a thin wrapper around the
shared subprocess + per-handle output buffer.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
import sys
from typing import Any

from mahavishnu.mcp.crow.settings import CrowSettings

logger = logging.getLogger(__name__)


@dataclass
class _RawJsonRpcError(Exception):
    """JSON-RPC error frame returned by upstream."""

    code: int
    message: str
    data: Any = None

    def __str__(self) -> str:  # pragma: no cover - debug only
        return f"JSON-RPC error {self.code}: {self.message} (data={self.data!r})"


class _RawJsonRpcClient:
    """Persistent JSON-RPC client wrapping one upstream ``crow-mcp`` subprocess.

    Lifecycle:

    - ``start()`` spawns the subprocess, sends ``initialize``, awaits the
      response, then spawns a reader task that loops over stdout lines.
    - ``call_tool(name, arguments, timeout)`` writes a ``tools/call``
      request and awaits the matching response by request id.
    - ``aclose()`` cancels the reader, closes stdin, SIGKILLs the
      subprocess, and reaps it.

    Thread-safety: a single ``asyncio.Lock`` guards every write to the
    subprocess stdin pipe so that JSON-RPC frames from concurrent
    callers never interleave. The reader task is the only consumer of
    the stdout pipe.
    """

    def __init__(self, settings: CrowSettings) -> None:
        self._settings = settings
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._write_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    async def start(self) -> None:
        """Spawn the subprocess and complete the JSON-RPC initialize handshake."""
        if self._process is not None:
            raise RuntimeError("raw_jsonrpc client already started")
        proc = await asyncio.create_subprocess_exec(
            self._settings.crow_mcp_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=sys.stderr,
            start_new_session=True,
        )
        self._process = proc
        self._reader_task = asyncio.create_task(
            self._read_loop(),
            name=f"crow-raw-jsonrpc-reader-{proc.pid}",
        )

        # JSON-RPC initialize. Wait for the matching response before
        # accepting real tool calls.
        init_request = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mahavishnu-crow-raw-jsonrpc", "version": "0.0.0"},
            },
        }
        self._next_id += 1
        response = await self._round_trip(init_request, timeout=10.0)
        logger.info(
            "Upstream crow-mcp initialized (pid=%s, server=%s)",
            proc.pid,
            response.get("result", {}).get("serverInfo", {}).get("name", "unknown"),
        )

        # Send ``initialized`` notification (no response expected).
        await self._send_notification(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
        )

    async def _read_loop(self) -> None:
        """Read stdout line-by-line, route responses to pending futures."""
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    # EOF: subprocess exited. Resolve all pending futures
                    # so callers don't hang forever.
                    for fut in self._pending.values():
                        if not fut.done():
                            fut.set_exception(
                                RuntimeError("crow-mcp subprocess exited unexpectedly")
                            )
                    self._pending.clear()
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError as exc:
                    logger.warning("crow-mcp: malformed JSON-RPC frame: %s (%s)", text, exc)
                    continue
                msg_id = msg.get("id")
                if msg_id is None:
                    # Notification — log and ignore.
                    logger.debug("crow-mcp notification: %s", msg)
                    continue
                fut = self._pending.pop(msg_id, None)
                if fut is None or fut.done():
                    # Unsolicited response or duplicate. Log and move on.
                    logger.debug("crow-mcp: response for unknown id=%s", msg_id)
                    continue
                if "error" in msg:
                    err = msg["error"]
                    fut.set_exception(
                        _RawJsonRpcError(
                            code=err.get("code", -1),
                            message=err.get("message", "unknown"),
                            data=err.get("data"),
                        )
                    )
                else:
                    fut.set_result(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - background task boundary
            logger.warning("crow-mcp reader loop crashed: %s", exc)

    async def _round_trip(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        """Send ``request``, await the matching response, return it."""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("raw_jsonrpc client not started")
        if self._closed:
            raise RuntimeError("raw_jsonrpc client closed")
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request["id"]] = fut
        payload = (json.dumps(request) + "\n").encode("utf-8")
        async with self._write_lock:
            try:
                self._process.stdin.write(payload)
                await self._process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                self._pending.pop(request["id"], None)
                raise RuntimeError(f"crow-mcp stdin closed: {exc}") from exc
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except TimeoutError as exc:
            self._pending.pop(request["id"], None)
            raise RuntimeError(f"crow-mcp call_tool timed out after {timeout}s") from exc

    async def _send_notification(self, notification: dict[str, Any]) -> None:
        """Send a notification (no response expected)."""
        if self._process is None or self._process.stdin is None:
            return
        payload = (json.dumps(notification) + "\n").encode("utf-8")
        async with self._write_lock:
            try:
                self._process.stdin.write(payload)
                await self._process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                logger.warning("crow-mcp: notification write failed: %s", exc)

    async def call_tool(
        self, name: str, arguments: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        """Call a tool on the upstream crow-mcp and return the raw result."""
        if self._process is None:
            raise RuntimeError("raw_jsonrpc client not started")
        request_id = self._next_id
        self._next_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = await self._round_trip(request, timeout=timeout)
        result = response.get("result", {})
        # MCP SDK wraps tool results in ``{"content": [...], "isError": bool}``.
        # Coerce to a plain dict so callers don't need to know about
        # ``mcp.types`` types.
        if isinstance(result, dict):
            return result
        return {"raw": result}

    async def aclose(self) -> None:
        """Cancel reader, close stdin, SIGKILL + reap the subprocess."""
        self._closed = True
        proc = self._process
        if proc is None:
            return
        # Cancel the reader first so the asyncio.Task exits its readline loop.
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._reader_task), timeout=2.0)
            except BaseException as exc:  # noqa: BLE001 - cleanup boundary
                logger.debug("crow-mcp reader shutdown skipped: %s", exc)
        # Fail any still-pending futures.
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("raw_jsonrpc client closed"))
        self._pending.clear()
        # Close stdin so the subprocess sees EOF.
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001 - cleanup boundary
                pass
        # SIGKILL + reap.
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        try:
            await proc.wait()
        except ProcessLookupError:
            pass


@asynccontextmanager
async def open_raw_jsonrpc_client(settings: CrowSettings):
    """Spawn and start a ``_RawJsonRpcClient``; close on context exit."""
    client = _RawJsonRpcClient(settings)
    await client.start()
    try:
        yield client
    finally:
        await client.aclose()
