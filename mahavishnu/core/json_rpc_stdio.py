"""JSON-RPC 2.0 client over asyncio stdio subprocess pipes.

Uses **Content-Length framed** messages (the LSP convention), not NDJSON.
Each frame is::

    Content-Length: <bytes>\r\n
    \r\n
    {"jsonrpc":"2.0", ...}

This is the framing convention used by VS Code's Language Server Protocol
and the Node packages that follow it (including Pi's ``--rpc`` mode, per
design intent in ``docs/plans/2026-09-07-pi-pool-backend.md``).

**Reuse**: ``JSONRPCError`` and ``JSONRPCErrorCode`` are imported from
``mahavishnu.core.json_rpc_ipc``. Do NOT lift those into a shared module —
per the multi-agent review, lifting just the enums is over-engineering.

Security: when ``env`` is provided, the subprocess is spawned with a
**stripped environment** consisting only of the keys in the env_allowlist
plus a small set of required POSIX keys (``PATH``, ``HOME``, ``LANG``,
``NODE_PATH``, ``NODE_ENV``, ``TMPDIR``). The parent environment's
``MAHAVISHNU_*``, ``MINIMAX_*``, ``ZAI_*``, ``DHARA_*``, ``AKOSHA_*``, and
``SESSION_BUDDY_*`` keys are NEVER passed through.

Testability: ``stream_factory`` parameter allows tests to inject a doubled
pipe without spawning a real subprocess. Production code passes ``None``
and gets the default ``asyncio.connect_unix_pipe`` / pipe trio created
by ``asyncio.subprocess.PIPE`` factory.

Traceability: see ``docs/plans/2026-09-07-pi-pool-backend.md`` for the
contract this class implements, including the watchdog behavior on
stdout EOF and heartbeat loss.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import os
import re
import time
from typing import Any, cast

from oneiric.core.logging import get_logger

from .errors import PiProtocolError, PiRPCTimeout
from .json_rpc_ipc import JSONRPCError, JSONRPCErrorCode

logger = get_logger(__name__)


# Default keys always passed through to the subprocess, in addition to the
# caller-provided ``env_allowlist``. These are minimal POSIX keys required
# for ``npx`` to function (``PATH``) and for the Node runtime to honour
# locale expectations (``HOME``, ``LANG``, ``TMPDIR``). ``NODE_PATH`` and
# ``NODE_ENV`` are forward-declared for future Pi features; both default to
# empty in the subprocess.
_REQUIRED_PASSTHROUGH_KEYS: tuple[str, ...] = (
    "PATH",
    "HOME",
    "LANG",
    "NODE_PATH",
    "NODE_ENV",
    "TMPDIR",
)

# Runtime denylist: env-var name prefixes that MUST NOT be forwarded to the
# subprocess, even if the caller's ``env_allowlist`` accidentally or
# maliciously includes them. This is the runtime counterpart to the
# ``MAHAVISHNU_*`` / ``MINIMAX_*`` etc. exclusion documented in
# ``PiPoolSettings.env_allowlist`` — the model-level validator is the first
# line of defense; this denylist is the second.
_FORBIDDEN_ENV_PREFIXES: tuple[str, ...] = (
    "MAHAVISHNU_",
    "MINIMAX_",
    "ZAI_",
    "DHARA_",
    "AKOSHA_",
    "SESSION_BUDDY_",
)


# Type alias for the stream factory seam. ``asyncio.subprocess.PIPE``
# objects satisfy ``StreamReader | StreamWriter`` at runtime, but the
# abstract types are in ``asyncio.streams``. We type as ``Any`` for
# practicality — the runtime contract is "two awaitable read/write ends".
StreamFactory = Callable[..., tuple[Any, Any]]


@dataclass
class _PendingRequest:
    """Tracked in-flight request waiting on a response frame."""

    method: str
    params: Any
    future: asyncio.Future[Any]
    timeout: float


@dataclass
class _WatchdogState:
    """State for the watchdog task. Held on the client."""

    last_frame_at: float = 0.0
    task: asyncio.Task[None] | None = None
    eof_seen: bool = False
    last_seen_method: str = ""
    frames_received: int = 0
    failed: bool = False


class JSONRPCStdioClient:
    """JSON-RPC 2.0 client speaking to a subprocess over Content-Length frames.

    Lifecycle::

        client = JSONRPCStdioClient(command=["npx", "..."], env={"PATH": "..."})
        version = await client.start()
        result = await client.request("ping")
        await client.stop()

    Or via the ``session()`` context manager which calls ``start`` / ``stop``
    for you.

    Watchdog: a background task is spawned in ``start()``. If no inbound
    frame is observed for ``2 * heartbeat_interval`` seconds, the client
    transitions to a failed state and cancels all pending request futures
    with :class:`PiRPCTimeout`. On stdout EOF the watchdog marks EOF and
    cancels pending requests immediately.

    Req: REQ-PI-003
    """  # req: REQ-PI-003

    def __init__(
        self,
        command: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        request_timeout: float = 30.0,
        heartbeat_interval: float = 30.0,
        watchdog_timeout_multiplier: float = 2.0,
        on_protocol_error: Callable[[JSONRPCError], None] | None = None,
        logger: Any | None = None,
        stream_factory: StreamFactory | None = None,
        max_frame_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        """Initialize client. No subprocess is spawned until ``start()``."""
        if not command:
            raise ValueError("command must be a non-empty sequence")
        self._command = tuple(command)
        # Stripped environment — see _build_subprocess_env below.
        self._explicit_env: Mapping[str, str] = env if env is not None else {}
        self._request_timeout = request_timeout
        self._heartbeat_interval = heartbeat_interval
        self._watchdog_timeout_multiplier = watchdog_timeout_multiplier
        self._on_protocol_error = on_protocol_error
        self._logger = logger or get_logger(__name__)
        self._stream_factory = stream_factory
        self._max_frame_bytes = max_frame_bytes

        # Filled by start().
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._next_id = 1
        self._pending: dict[int | str, _PendingRequest] = {}
        self._lock = asyncio.Lock()
        self._started = False
        self._stopped = False
        self._startup_self_test_version: str | None = None
        self._last_ping_ms: float | None = None
        self._last_ping_at: float | None = None
        self._watchdog = _WatchdogState()
        self._on_protocol_error_calls = 0

    # -- Public API ----------------------------------------------------------

    async def start(self) -> str:
        """Spawn the subprocess and run the startup self-test.

        Returns:
            The version string returned by the subprocess's ``--version``
            probe (or ``""`` if no probe output was captured).

        Raises:
            PiProtocolError: If the subprocess cannot be started.
        """
        if self._started:
            raise RuntimeError("JSONRPCStdioClient already started")
        self._stopped = False
        self._watchdog = _WatchdogState(last_frame_at=time.monotonic())

        env = self._build_subprocess_env()
        await self._spawn_process(env)

        # Spawn the reader task. Even with stream_factory (test mode), the
        # reader task is responsible for parsing frames.
        self._reader_task = asyncio.create_task(
            self._read_loop(),
            name="json-rpc-stdio-reader",
        )
        # Spawn the watchdog task.
        self._watchdog.task = asyncio.create_task(
            self._watchdog_loop(),
            name="json-rpc-stdio-watchdog",
        )

        # Run startup self-test: a probe ``--version`` invocation. This is a
        # convention-based probe; the subprocess may not implement it (e.g.
        # in test injection). Failure to probe does not abort start() — the
        # caller decides whether the empty version string is acceptable.
        version = await self._startup_self_test()
        self._startup_self_test_version = version or None
        self._started = True
        return self._startup_self_test_version or ""

    async def _spawn_process(self, env: dict[str, str]) -> None:
        """Spawn the subprocess (or use test stream_factory) and wire pipes.

        Maps FileNotFoundError / PermissionError / OSError to PiProtocolError
        so the public contract of ``start()`` is uniform: any spawn failure
        surfaces as PiProtocolError. Extracted from ``start()`` to keep that
        method under the complexity budget (≤15 branches per CLAUDE.md).

        Req: REQ-PI-003
        """  # req: REQ-PI-003
        try:
            if self._stream_factory is not None:
                # Test seam: factory returns (reader, writer).
                reader, writer = self._stream_factory(env=env)
                self._reader = reader
                self._writer = writer
                self._process = None
                return
            process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            self._process = process
            self._reader = process.stdout
            self._writer = process.stdin
        except FileNotFoundError as e:
            raise PiProtocolError(
                f"subprocess executable not found: {self._command[0]!r}",
                frame_excerpt=str(e),
            ) from e
        except PermissionError as e:
            raise PiProtocolError(
                f"subprocess executable not executable: {self._command[0]!r}",
                frame_excerpt=str(e),
            ) from e
        except OSError as e:
            raise PiProtocolError(
                f"failed to spawn subprocess {self._command!r}: {e}",
                frame_excerpt=str(e),
            ) from e

    async def stop(self) -> None:
        """Tear down the client.

        Cancels pending request futures with :class:`PiRPCTimeout`,
        signals the reader/watchdog tasks to exit, then SIGTERMs the
        subprocess (SIGKILL fallback if it does not exit promptly).
        """
        if self._stopped:
            return
        self._stopped = True
        # Cancel pending requests first so callers see PiRPCTimeout.
        self._fail_pending_requests(PiRPCTimeout("client stopped"))
        # Cancel background tasks.
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
        if self._watchdog.task is not None and not self._watchdog.task.done():
            self._watchdog.task.cancel()
        # Close writer to flush.
        if self._writer is not None and not self._writer.is_closing():
            try:
                self._writer.close()
            except Exception as e:  # noqa: BLE001 - defensive cleanup
                self._logger.debug("error closing writer: %s", e)
        # Subprocess termination.
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._logger.warning("subprocess did not exit after SIGTERM; sending SIGKILL")
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=2.0)
                except TimeoutError:
                    self._logger.warning("subprocess did not exit after SIGKILL")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[JSONRPCStdioClient]:
        """Context manager that calls ``start()`` and ``stop()``."""
        await self.start()
        try:
            yield self
        finally:
            await self.stop()

    async def request(
        self,
        method: str,
        params: Mapping[str, Any] | list[Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        """Send a JSON-RPC request and await the response.

        Args:
            method: Method name to invoke.
            params: Parameters (dict or list, or None).
            timeout: Per-request timeout. Defaults to ``request_timeout``.

        Returns:
            The ``result`` field from the response.

        Raises:
            PiRPCTimeout: If the request exceeds ``timeout`` seconds.
            PiProtocolError: If the response is malformed.
            JSONRPCError: If the peer returns an error response.
        """
        if not self._started:
            raise RuntimeError("client not started")
        if self._stopped:
            raise RuntimeError("client stopped")
        request_id = self._allocate_id()
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        effective_timeout = timeout if timeout is not None else self._request_timeout

        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        async with self._lock:
            self._pending[request_id] = _PendingRequest(
                method=method,
                params=params,
                future=future,
                timeout=effective_timeout,
            )

        await self._send_frame(payload)
        try:
            return await asyncio.wait_for(future, timeout=effective_timeout)
        except TimeoutError as e:
            async with self._lock:
                self._pending.pop(request_id, None)
            raise PiRPCTimeout(
                f"RPC request timed out after {effective_timeout}s",
                method=method,
                timeout_seconds=effective_timeout,
            ) from e

    async def notify(
        self, method: str, params: Mapping[str, Any] | list[Any] | None = None
    ) -> None:
        """Send a JSON-RPC notification (no response expected).

        Args:
            method: Method name.
            params: Parameters (dict or list, or None).
        """
        if not self._started:
            raise RuntimeError("client not started")
        if self._stopped:
            raise RuntimeError("client stopped")
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        await self._send_frame(payload)

    async def ping(self) -> float:
        """Send a ``ping`` notification and measure the round-trip ms.

        Note: this depends on the peer echoing or otherwise acknowledging
        a ping. The implementation here measures the time to write the
        notification; if the peer echoes a ``pong`` notification the future
        would be completed by the reader loop. In the absence of a pong
        contract, this method records a coarse-grained write latency.

        Returns:
            Round-trip latency in milliseconds (>= 0.0).
        """
        start = time.perf_counter()
        await self.notify("ping", {"ts": start})
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._last_ping_ms = elapsed_ms
        self._last_ping_at = time.monotonic()
        return elapsed_ms

    # -- Internal: framing & I/O ---------------------------------------------

    async def _send_frame(self, payload: Mapping[str, Any]) -> None:
        """Encode ``payload`` as a Content-Length framed message and write it."""
        if self._writer is None:
            raise RuntimeError("writer not initialised")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self._writer.write(header)
        self._writer.write(body)
        await self._writer.drain()

    async def _read_loop(self) -> None:
        """Read frames from stdout and dispatch responses / notifications."""
        if self._reader is None:
            return
        try:
            while not self._stopped:
                # Read header lines until blank line.
                header_lines: list[bytes] = []
                content_length: int | None = None
                while True:
                    line = await self._reader.readline()
                    if not line:
                        # EOF.
                        self._watchdog.eof_seen = True
                        self._fail_pending_requests(
                            PiProtocolError("subprocess stdout closed (read EOF)")
                        )
                        return
                    line = line.rstrip(b"\r\n")
                    if not line:
                        # Blank line terminates headers.
                        break
                    header_lines.append(line)
                    m = re.match(rb"(?i)^Content-Length:\s*(\d+)\s*$", line)
                    if m is not None:
                        content_length = int(m.group(1))
                if content_length is None:
                    # Malformed header block — record but continue.
                    self._on_protocol_error_callback(
                        JSONRPCError(
                            JSONRPCErrorCode.PARSE_ERROR,
                            "missing Content-Length header",
                        )
                    )
                    continue
                if content_length < 0 or content_length > self._max_frame_bytes:
                    self._on_protocol_error_callback(
                        JSONRPCError(
                            JSONRPCErrorCode.PARSE_ERROR,
                            f"Content-Length {content_length} out of bounds",
                        )
                    )
                    # Skip this frame by reading and discarding.
                    await self._reader.readexactly(content_length)
                    continue
                body = await self._reader.readexactly(content_length)
                self._watchdog.last_frame_at = time.monotonic()
                self._watchdog.frames_received += 1
                try:
                    decoded = json.loads(body.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    self._on_protocol_error_callback(
                        JSONRPCError(
                            JSONRPCErrorCode.PARSE_ERROR,
                            f"failed to parse JSON body: {e}",
                        )
                    )
                    continue
                if not isinstance(decoded, dict):
                    self._on_protocol_error_callback(
                        JSONRPCError(
                            JSONRPCErrorCode.INVALID_REQUEST,
                            f"top-level JSON must be object, got {type(decoded).__name__}",
                        )
                    )
                    continue
                await self._dispatch_frame(cast("dict[str, Any]", decoded))
        except asyncio.CancelledError:
            # Normal teardown.
            return
        except Exception as e:  # pragma: no cover - defensive
            self._logger.exception("unexpected error in read loop: %s", e)  # noqa: TRY401
            self._fail_pending_requests(
                PiProtocolError(f"read loop crashed: {e}", frame_excerpt=str(e))
            )

    async def _dispatch_frame(self, frame: dict[str, Any]) -> None:
        """Route a single parsed JSON-RPC frame."""
        if "method" in frame and "id" not in frame:
            # Notification — no response expected.
            method = frame.get("method")
            if isinstance(method, str):
                self._watchdog.last_seen_method = method
            return
        if "id" in frame:
            request_id = frame["id"]
            if "error" in frame:
                # Error reply to a pending request.
                err = frame["error"]
                code = err.get("code", JSONRPCErrorCode.INTERNAL_ERROR)
                message = err.get("message", "unknown error")
                data = err.get("data")
                try:
                    code_int = int(code)
                except TypeError, ValueError:
                    code_int = JSONRPCErrorCode.INTERNAL_ERROR
                data_dict: dict[str, Any] | None
                if isinstance(data, dict):
                    data_dict = cast("dict[str, Any]", data)
                else:
                    data_dict = None
                rpc_err = JSONRPCError(code_int, message, data=data_dict)
                async with self._lock:
                    pending = self._pending.pop(request_id, None)
                if pending is not None and not pending.future.done():
                    pending.future.set_exception(rpc_err)
                return
            if "result" in frame:
                async with self._lock:
                    pending = self._pending.pop(request_id, None)
                if pending is not None and not pending.future.done():
                    pending.future.set_result(frame["result"])
                return
        # Unrecognised frame shape.
        self._on_protocol_error_callback(
            JSONRPCError(
                JSONRPCErrorCode.INVALID_REQUEST,
                f"unrecognised JSON-RPC frame: keys={sorted(frame.keys())!r}",
            )
        )

    # -- Internal: startup, watchdog, env -----------------------------------

    async def _startup_self_test(self) -> str:
        """Probe the subprocess with ``--version`` and capture the output.

        Implemented by running the same command with ``--version`` appended.
        If the subprocess does not support ``--version``, returns an empty
        string. Always returns a string (never raises).
        """
        # Cheap, safe probe: append --version to the command and capture
        # stdout. Avoids sharing state with the RPC subprocess.
        cmd = (*self._command, "--version")
        env = self._build_subprocess_env()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return ""
        except (FileNotFoundError, PermissionError, OSError) as e:
            self._logger.debug("--version probe failed: %s", e)
            return ""
        return stdout_b.decode("utf-8", errors="replace").strip()

    async def _watchdog_loop(self) -> None:
        """Watchdog task: emits metrics on heartbeat miss, marks EOF."""
        threshold = self._heartbeat_interval * self._watchdog_timeout_multiplier
        try:
            while not self._stopped:
                await asyncio.sleep(max(0.5, self._heartbeat_interval / 4.0))
                if self._stopped:
                    return
                if self._watchdog.eof_seen:
                    # EOF already handled by read loop; nothing more to do.
                    return
                now = time.monotonic()
                if now - self._watchdog.last_frame_at > threshold:
                    self._logger.warning(
                        "json-rpc-stdio: no inbound frame for %.1fs (threshold %.1fs)",
                        now - self._watchdog.last_frame_at,
                        threshold,
                    )
                    self._watchdog.failed = True
                    self._fail_pending_requests(
                        PiRPCTimeout(
                            f"watchdog: no frame for {now - self._watchdog.last_frame_at:.1f}s",
                        )
                    )
                    return
        except asyncio.CancelledError:
            return

    def _build_subprocess_env(self) -> dict[str, str]:
        """Build the subprocess env from the explicit ``env`` allowlist.

        Starts from a minimal POSIX-required base (PATH, HOME, LANG,
        NODE_PATH, NODE_ENV, TMPDIR) and overlays the explicit
        ``env_allowlist`` keys taken from ``os.environ``. Sensitive
        parent env vars (``MAHAVISHNU_*``, ``MINIMAX_*``, ``ZAI_*``,
        ``DHARA_*``, ``AKOSHA_*``, ``SESSION_BUDDY_*``) are NEVER copied.
        """
        env: dict[str, str] = {}
        # POSIX-required keys.
        for key in _REQUIRED_PASSTHROUGH_KEYS:
            if key in os.environ:
                env[key] = os.environ[key]
        # Caller-specified allowlist keys, filtered against the forbidden-prefix
        # denylist. If the configured allowlist tries to forward a sensitive
        # key (operator error, misconfiguration, or hostile config), drop it
        # with a warning rather than silently leaking the secret.
        for key in self._explicit_env:
            if any(key.startswith(prefix) for prefix in _FORBIDDEN_ENV_PREFIXES):
                self._logger.warning(
                    "json-rpc-stdio refusing to forward sensitive env var: %s",
                    key,
                )
                continue
            if key in os.environ:
                env[key] = os.environ[key]
        return env

    def _fail_pending_requests(self, exc: BaseException) -> None:
        """Cancel all pending request futures with the given exception."""
        pending: dict[int | str, _PendingRequest]
        pending = dict(self._pending)
        self._pending.clear()
        for p in pending.values():
            if not p.future.done():
                p.future.set_exception(exc)

    def _on_protocol_error_callback(self, err: JSONRPCError) -> None:
        """Record a protocol error and notify the caller if registered."""
        self._on_protocol_error_calls += 1
        self._logger.warning(
            "json-rpc-stdio protocol error code=%s message=%s",
            err.code,
            err.message,
        )
        if self._on_protocol_error is not None:
            try:
                self._on_protocol_error(err)
            except Exception:  # pragma: no cover - defensive
                self._logger.exception("on_protocol_error callback raised")

    def _allocate_id(self) -> int:
        """Allocate a fresh JSON-RPC request id."""
        rid = self._next_id
        self._next_id += 1
        return rid

    # -- Introspection (used by health checks) -------------------------------

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def is_stopped(self) -> bool:
        return self._stopped

    @property
    def startup_version(self) -> str | None:
        return self._startup_self_test_version

    @property
    def last_ping_ms(self) -> float | None:
        return self._last_ping_ms

    @property
    def last_ping_at(self) -> float | None:
        return self._last_ping_at

    @property
    def frames_received(self) -> int:
        return self._watchdog.frames_received

    @property
    def watchdog_failed(self) -> bool:
        return self._watchdog.failed

    @property
    def protocol_errors(self) -> int:
        return self._on_protocol_error_calls


__all__ = [
    "JSONRPCStdioClient",
    "StreamFactory",
]
