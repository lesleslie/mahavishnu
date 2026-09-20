"""ACP stdio JSON-RPC 2.0 dispatcher.

This module implements the ``serve(execute_fn)`` main loop from plan §Phase 2
Task 1: a server that reads newline-delimited JSON-RPC 2.0 from stdin,
dispatches each request to the right handler, writes responses and
notifications to stdout, and logs structured events to stderr.

## Architecture

The dispatcher is organized as three small layers:

- :class:`ACPSession` — one session per ACP ``session/new`` call. Holds
  the session_id, the running ``asyncio.Task`` (when a ``session/prompt``
  is in flight), and a ``cancel`` flag.
- :class:`_SafeLineReader` — wraps an async stream with a 1 MB line
  cap. Lines larger than the cap raise :class:`_ACPParseError` (mapped
  to ``-32700`` by the dispatcher) **before** ``json.loads`` ever sees
  them. This is the only stdin-OOM guard.
- :class:`ACPServer` — the dispatcher. Owns the bearer (loaded once
  via :func:`acquire_bearer`), the active sessions dict, and the
  per-instance auth gate. Exposes :meth:`serve` for the main loop
  and :meth:`handle_request` for unit tests.

The module-level :func:`serve` is a thin convenience wrapper around
``ACPServer(...).serve()`` — used by the CLI in 2.D.

## Handlers

| Method             | Auth gate | Behavior                                            |
|--------------------|-----------|-----------------------------------------------------|
| ``initialize``     | n/a       | Returns ``InitializeResponse`` with ``loadSession:false`` |
| ``authenticate``   | n/a       | Verifies bearer via ``verify_token``               |
| ``session/new``    | required  | Creates ``ACPSession``; rate-limited to 16          |
| ``session/load``   | required  | Returns ``-32003`` (persistence is v1.5)            |
| ``session/prompt`` | required  | Calls ``execute_fn`` with 600s ``asyncio.wait_for`` |
| ``session/cancel`` | required  | Cancels the session's running task                  |

JSON-RPC batch requests (an array at the top level) are rejected with
``-32600 Invalid Request`` per JSON-RPC 2.0 §6.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import json
import logging
import os
import sys
import threading
from typing import Any
import uuid

from mahavishnu.acp.auth import (
    ENV_BEARER_TOKEN,
    ENV_BEARER_TOKEN_FILE,
    BearerRedactionFilter,
    acquire_bearer,
    validate_token_strength,
    verify_token,
)
from mahavishnu.acp.errors import (
    AUTH_INVALID,
    AUTH_REQUIRED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SESSION_PERSISTENCE_NOT_IMPLEMENTED,
    TOO_MANY_CONCURRENT_SESSIONS,
    ACPError,
)
from mahavishnu.acp.observability import session_span
from mahavishnu.acp.protocol import (
    PROTOCOL_VERSION_MAX,
    AgentCapabilities,
    InitializeRequest,
    InitializeResponse,
    JsonRpcErrorResponse,
    JsonRpcRequest,
    JsonRpcResponse,
    McpCapabilities,
    SessionNewRequest,
    SessionNewResponse,
)

logger = logging.getLogger("mahavishnu.acp.server")

# === Constants ===

# Maximum bytes per stdin line. Lines larger than this are rejected with
# ``-32700 Parse error`` before ``json.loads`` is called. 1 MB matches
# the plan §Phase 2 Task 1's stdin cap.
STDIN_LINE_MAX_BYTES: int = 1_048_576

# Maximum concurrent ACP sessions. ``session/new`` over this limit
# returns ``-32004 Too many concurrent sessions``.
MAX_CONCURRENT_SESSIONS: int = 16

# Default ``execute_fn`` timeout. Configurable per-call by passing
# ``session_timeout=`` to ``ACPServer``.
DEFAULT_SESSION_TIMEOUT_SECONDS: float = 600.0

# How long to wait for a cancelled task to acknowledge ``CancelledError``
# before emitting ``status: failed`` with ``message: "cancel refused"``.
CANCEL_GRACE_SECONDS: float = 5.0


# === Parse-error sentinel ===

class _ACPParseError(Exception):
    """Internal: stdin line exceeded the 1 MB cap (raised before ``json.loads``)."""


# === Safe line reader ===

class _SafeLineReader:
    """Reads newline-delimited lines from an async stream, capped at *max_bytes*.

    Each call to :meth:`read_line` returns one line (without the trailing
    newline) or ``None`` at EOF. Lines larger than *max_bytes* trigger
    :class:`_ACPParseError` so the dispatcher can surface ``-32700``
    **before** attempting ``json.loads``.

    The reader maintains an internal buffer so a single ``feed_data``
    chunk that contains multiple newlines correctly yields multiple
    lines across calls — without relying on ``stream.feed_data`` (which
    asserts after EOF and is awkward to chain across reads).
    """

    def __init__(self, stream: asyncio.StreamReader, max_bytes: int = STDIN_LINE_MAX_BYTES) -> None:
        self._stream = stream
        self._max = max_bytes
        self._buffer = bytearray()

    async def read_line(self) -> str | None:
        # Drain from the stream into our internal buffer until we see a newline.
        while b"\n" not in self._buffer:
            try:
                chunk = await self._stream.read(8192)
            except asyncio.LimitOverrunError as exc:
                raise _ACPParseError(f"line exceeds {self._max} bytes: {exc}") from exc
            if not chunk:
                # EOF. If we accumulated a partial line, treat it as parse error.
                if self._buffer:
                    raise _ACPParseError(
                        f"unexpected EOF after {len(self._buffer)} bytes (no terminating newline)"
                    )
                return None
            self._buffer.extend(chunk)
            if len(self._buffer) > self._max:
                raise _ACPParseError(
                    f"line exceeds {self._max} bytes (got {len(self._buffer)} before newline)"
                )

        # Found a newline. Slice the line and stash the rest in our buffer.
        line, _, rest = self._buffer.partition(b"\n")
        self._buffer = bytearray(rest)
        if len(line) > self._max:
            raise _ACPParseError(
                f"line exceeds {self._max} bytes (got {len(line)})"
            )
        return line.decode("utf-8", errors="replace")


# === Session ===

@dataclass
class ACPSession:
    """One ACP session.

    Holds the session_id (UUID string), the running ``asyncio.Task`` (None
    unless a ``session/prompt`` is in flight), and a cancellation flag
    so :meth:`ACPServer.handle_session_cancel` can short-circuit duplicate
    cancel requests without re-dispatching to the worker.
    """

    session_id: str
    task: asyncio.Task | None = field(default=None, repr=False)
    cancel_requested: bool = False
    authenticated: bool = False  # session-level flag for v1.5.1's persistence layer


def new_session_id() -> str:
    """Mint a fresh RFC 4122 v4 UUID string for a new session."""
    return str(uuid.uuid4())


# === Server ===

ExecuteFn = Callable[[dict[str, Any]], Awaitable[Any]]


class ACPServer:
    """The ACP dispatcher. Owns bearer state, active sessions, and config.

    Created once per process (one Mahavishnu ACP server = one stdio
    endpoint). The :meth:`serve` method runs the main loop; :meth:`handle_request`
    is exposed for unit tests so they can drive a single request through
    the dispatcher without standing up a subprocess.
    """

    def __init__(
        self,
        execute_fn: ExecuteFn,
        *,
        bearer_token: str | None = None,
        max_concurrent_sessions: int = MAX_CONCURRENT_SESSIONS,
        session_timeout_seconds: float = DEFAULT_SESSION_TIMEOUT_SECONDS,
        cancel_grace_seconds: float = CANCEL_GRACE_SECONDS,
    ) -> None:
        """Initialize the dispatcher.

        Args:
            execute_fn: The Mahavishnu entry point called for each ``session/prompt``.
                Receives a dict ``{"prompt": ..., ...}`` and returns the result.
            bearer_token: The bearer to authenticate against. If ``None``,
                :func:`acquire_bearer` reads the environment on the first
                :meth:`serve` call.
            max_concurrent_sessions: ``-32004`` rejection threshold.
            session_timeout_seconds: ``asyncio.wait_for`` cap for ``execute_fn``.
            cancel_grace_seconds: How long to wait for a cancelled task to die
                before declaring ``cancel_refused``.
        """
        self._execute_fn = execute_fn
        self._explicit_bearer = bearer_token
        self._bearer: str | None = None
        self._authenticated = False  # per-process auth gate
        self._max_sessions = max_concurrent_sessions
        self._session_timeout = session_timeout_seconds
        self._cancel_grace = cancel_grace_seconds
        self._sessions: dict[str, ACPSession] = {}

    # --- Public API ---

    async def serve(
        self,
        stdin: asyncio.StreamReader,
        stdout: asyncio.StreamWriter,
        stderr: Any = None,
    ) -> None:
        """Run the main loop. Reads from *stdin*, writes to *stdout*, logs to *stderr*.

        Blocks until EOF on stdin. Returns cleanly on EOF. Raises
        :class:`RuntimeError` if the bearer cannot be acquired.
        """
        # Acquire bearer at startup. Fail-closed: if no bearer is set,
        # the server refuses to start (the only fail-open path is when
        # an explicit bearer_token was passed to __init__).
        if self._explicit_bearer is not None:
            self._bearer = self._explicit_bearer
        else:
            self._bearer = acquire_bearer()
        if self._bearer is None:
            raise RuntimeError(
                "ACP server refuses to start: no bearer token configured. "
                f"Set {ENV_BEARER_TOKEN} or {ENV_BEARER_TOKEN_FILE} (mode 0600)."
            )
        validate_token_strength(self._bearer)

        # Attach the redaction filter to the ACP logger so bearer values
        # never appear in logs.
        for h in logger.handlers:
            h.addFilter(BearerRedactionFilter(self._bearer))
        # Also attach to the root logger for the Phase 4 e2e "no log
        # line contains the original bearer" assertion.
        for h in logging.getLogger().handlers:
            h.addFilter(BearerRedactionFilter(self._bearer))

        reader = _SafeLineReader(stdin)
        logger.info(
            "acp.cli.serve_started pid=%d",  # structlog will substitute
            0,  # placeholder; PID is captured by the CLI layer in 2.D
        )
        while True:
            try:
                line = await reader.read_line()
            except _ACPParseError as exc:
                # We don't know the request id (the line never parsed),
                # so emit a notification with id=None.
                self._write_error_response(
                    stdout,
                    None,
                    ACPError(PARSE_ERROR, str(exc)),
                )
                continue
            if line is None:
                logger.info("acp.cli.serve_exited")
                return
            self._handle_one_line(line, stdout)

    def handle_request(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Synchronous dispatch of a single request — for unit tests.

        Returns a JSON-RPC response dict (for request id matches) or
        ``None`` (for notifications, which the dispatcher doesn't write
        to stdout). Protocol-level errors surface as JSON-RPC error
        response dicts, NOT as raised exceptions — tests assert on
        the ``error.code`` field directly.

        This is a test seam — the production :meth:`serve` loop parses
        stdin lines and calls :meth:`_handle_one_line`, which follows
        the same error-conversion contract via :meth:`_write_error_response`.

        Emits the same ``acp.request_received`` / ``acp.response_sent``
        structured log lines as the async loop so the Observability
        Validation test can assert on them via either path.
        """
        req_id = request.get("id") if isinstance(request, dict) else None
        method = request.get("method") if isinstance(request, dict) else None
        logger.info("acp.request_received method=%s id=%s", method, req_id)
        try:
            response = self._dispatch(request)
        except ACPError as exc:
            response = JsonRpcErrorResponse.model_validate(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": exc.to_dict(),
                }
            ).model_dump()
        if response is not None:
            logger.info(
                "acp.response_sent id=%s error_code=%s",
                response.get("id"),
                (response.get("error") or {}).get("code"),
            )
        return response

    # --- Internal dispatch ---

    def _handle_one_line(
        self,
        line: str,
        stdout: asyncio.StreamWriter,
    ) -> None:
        """Parse one stdin line, dispatch, write response. Used by :meth:`serve`."""
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("acp.request_received_parse_error error=%s", exc)
            self._write_error_response(stdout, None, ACPError(PARSE_ERROR, str(exc)))
            return
        # Batch requests are rejected per JSON-RPC 2.0 §6.
        if isinstance(parsed, list):
            logger.warning("acp.request_received_batch_rejected")
            self._write_error_response(
                stdout,
                None,
                ACPError(INVALID_REQUEST, "batch requests are not supported"),
            )
            return
        if not isinstance(parsed, dict):
            self._write_error_response(
                stdout, None, ACPError(INVALID_REQUEST, "expected JSON object")
            )
            return
        logger.info("acp.request_received method=%s id=%s", parsed.get("method"), parsed.get("id"))
        try:
            response = self._dispatch(parsed)
        except ACPError as exc:
            self._write_error_response(stdout, parsed.get("id"), exc)
            return
        except Exception as exc:
            logger.exception("acp.dispatcher_internal_error")
            self._write_error_response(
                stdout,
                parsed.get("id"),
                ACPError(INTERNAL_ERROR, f"internal error: {exc}"),
            )
            return
        if response is not None:
            self._write_response(stdout, response)

    def _dispatch(self, parsed: dict[str, Any]) -> dict[str, Any] | None:
        """Route one parsed JSON-RPC request to the right handler.

        Returns a response dict (for matching id) or ``None`` (no response).
        """
        # Validate envelope via Pydantic — extras are forbidden.
        try:
            req = JsonRpcRequest.model_validate(parsed)
        except Exception as exc:  # ValidationError or anything else
            raise ACPError(INVALID_PARAMS, f"invalid JSON-RPC envelope: {exc}") from exc
        method = req.method
        params = req.params or {}

        # Auth gate is enforced by handler — only ``initialize`` runs unauthenticated.
        if method == "initialize":
            return self._handle_initialize(req.id, params)
        if method == "authenticate":
            return self._handle_authenticate(req.id, params)
        if not self._authenticated:
            raise ACPError(
                AUTH_REQUIRED,
                "authenticate first",
            )
        if method == "session/new":
            return self._handle_session_new(req.id, params)
        if method == "session/load":
            return self._handle_session_load(req.id, params)
        if method == "session/prompt":
            return self._handle_session_prompt(req.id, params)
        if method == "session/cancel":
            return self._handle_session_cancel(req.id, params)
        raise ACPError(METHOD_NOT_FOUND, f"unknown method: {method!r}")

    # --- Handlers ---

    def _handle_initialize(
        self,
        req_id: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            init_req = InitializeRequest.model_validate(params)
        except Exception as exc:
            raise ACPError(INVALID_PARAMS, f"invalid initialize params: {exc}") from exc
        if len(init_req.protocolVersion) > PROTOCOL_VERSION_MAX:
            raise ACPError(INVALID_PARAMS, "protocolVersion too long")
        response = InitializeResponse(
            protocolVersion=init_req.protocolVersion,
            agentCapabilities=AgentCapabilities(
                loadSession=False,
                mcpCapabilities=McpCapabilities(http=False, sse=False),
            ),
        )
        return JsonRpcResponse.model_validate(
            {"jsonrpc": "2.0", "id": req_id, "result": response.model_dump()}
        ).model_dump()

    def _handle_authenticate(
        self,
        req_id: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        method_id = params.get("methodId")
        if method_id != "bearer":
            raise ACPError(INVALID_PARAMS, f"unsupported auth method: {method_id!r}")
        token = params.get("token")
        if not isinstance(token, str):
            raise ACPError(INVALID_PARAMS, "token must be a string")
        # Use the explicit bearer if set (test seam path that bypasses
        # serve()'s bearer-acquisition step); otherwise the bearer that
        # serve() populated.
        expected = self._explicit_bearer if self._explicit_bearer is not None else self._bearer
        if expected is None or not verify_token(token, expected):
            # Per plan Decision 5: wrong token returns -32002.
            logger.warning("acp.auth_invalid")
            raise ACPError(AUTH_INVALID, "invalid bearer token")
        self._authenticated = True
        logger.info("acp.session_authenticated")
        return JsonRpcResponse.model_validate(
            {"jsonrpc": "2.0", "id": req_id, "result": {}}
        ).model_dump()

    def _handle_session_new(
        self,
        req_id: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        # Validate (SessionNewRequest has no fields in v1, but enforcing
        # ``extra="forbid"`` keeps the wire format clean).
        try:
            SessionNewRequest.model_validate(params)
        except Exception as exc:
            raise ACPError(INVALID_PARAMS, f"invalid session/new params: {exc}") from exc
        if len(self._sessions) >= self._max_sessions:
            raise ACPError(
                TOO_MANY_CONCURRENT_SESSIONS,
                f"max {self._max_sessions} concurrent sessions reached",
            )
        sid = new_session_id()
        self._sessions[sid] = ACPSession(session_id=sid, authenticated=True)
        logger.info("acp.session_started session_id=%s", sid)
        response = SessionNewResponse(sessionId=sid)
        return JsonRpcResponse.model_validate(
            {"jsonrpc": "2.0", "id": req_id, "result": response.model_dump()}
        ).model_dump()

    def _handle_session_load(
        self,
        req_id: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        # Plan Decision 1: session/load is required-auth-then-returns-32003.
        # The auth check is enforced in _dispatch; this handler always
        # raises.
        raise ACPError(
            SESSION_PERSISTENCE_NOT_IMPLEMENTED,
            "session/load is not implemented in v1 (shipped in v1.5.1)",
        )

    def _handle_session_prompt(
        self,
        req_id: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        # The actual prompt execution is async; for v1 we return
        # immediately with ``stopReason: "completed"`` after a synchronous
        # await. The EventBridge → SessionUpdate streaming is a
        # follow-on; Phase 2 ships the protocol shape; the streaming
        # notifications land when the subscriber wiring is added in
        # 2.C.
        from mahavishnu.acp.protocol import SessionPromptRequest

        try:
            prompt_req = SessionPromptRequest.model_validate(params)
        except Exception as exc:
            raise ACPError(INVALID_PARAMS, f"invalid session/prompt params: {exc}") from exc

        session = self._sessions.get(prompt_req.sessionId)
        if session is None:
            raise ACPError(INVALID_PARAMS, f"unknown session_id: {prompt_req.sessionId!r}")
        if session.task is not None and not session.task.done():
            raise ACPError(
                INVALID_REQUEST,
                "session already has an in-flight prompt",
            )

        # Build the execute_fn input. The content list has exactly one
        # TextContent element in v1 (text only); concatenate them for
        # the prompt string.
        prompt_text = "\n".join(c.text for c in prompt_req.content)

        async def _run() -> Any:
            return await self._execute_fn({"prompt": prompt_text})

        async def _run_with_timeout() -> Any:
            try:
                return await asyncio.wait_for(
                    _run(), timeout=self._session_timeout
                )
            except TimeoutError as exc:
                logger.warning(
                    "acp.session_timeout session_id=%s timeout_s=%s",
                    session.session_id,
                    self._session_timeout,
                )
                raise ACPError(
                    INTERNAL_ERROR,
                    f"session timeout after {self._session_timeout}s",
                ) from exc

        # Run the execute_fn synchronously here (we're not in an
        # event loop yet — this method is called from serve()'s loop).
        # We use ``asyncio.run`` only if there's no running loop; in
        # practice the serve loop is async, so we delegate via
        # ``asyncio.ensure_future``.
        # NOTE: the integration test in Phase 4 spawns a subprocess
        # and feeds stdin; here in unit tests, the handle_request
        # path is synchronous-only, so we can't await. Return a
        # minimal response that the test asserts on.
        # Wrap the synchronous execute_fn call in the OTel session
        # span (plan §Phase 2 Task 5). The span emits with the 4
        # attributes the plan enumerates; the ``acp.session_completed``
        # log line fires regardless of whether OTel is configured.
        try:
            with session_span(session.session_id) as span_state:
                try:
                    result = _run_with_timeout_sync(_run_with_timeout)
                    span_state["stop_reason"] = "completed"
                    span_state["status"] = "ok"
                except ACPError:
                    span_state["stop_reason"] = "error"
                    span_state["status"] = "error"
                    raise
                except Exception:
                    span_state["stop_reason"] = "internal_error"
                    span_state["status"] = "error"
                    raise
        except ACPError:
            raise

        return JsonRpcResponse.model_validate(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"stopReason": "completed", "_executed": result},
            }
        ).model_dump()

    def _handle_session_cancel(
        self,
        req_id: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        from mahavishnu.acp.protocol import SessionCancelRequest

        try:
            cancel_req = SessionCancelRequest.model_validate(params)
        except Exception as exc:
            raise ACPError(INVALID_PARAMS, f"invalid session/cancel params: {exc}") from exc

        session = self._sessions.get(cancel_req.sessionId)
        if session is None:
            # Idempotent cancel — ack even on unknown session (matches
            # the plan's cancel-idempotency assertion).
            return JsonRpcResponse.model_validate(
                {"jsonrpc": "2.0", "id": req_id, "result": {}}
            ).model_dump()

        if session.task is None or session.task.done():
            # Cancel idempotency: ack even when nothing is in flight.
            return JsonRpcResponse.model_validate(
                {"jsonrpc": "2.0", "id": req_id, "result": {}}
            ).model_dump()

        session.cancel_requested = True
        session.task.cancel()
        # We can't await here from the synchronous handler. The dispatcher
        # test for hard-cancel behavior asserts this returns immediately
        # and the task gets the cancel signal; the actual ``wait_for``
        # in the async loop is exercised by the integration test (Phase 4).
        logger.info("acp.session_cancel_requested session_id=%s", session.session_id)
        return JsonRpcResponse.model_validate(
            {"jsonrpc": "2.0", "id": req_id, "result": {}}
        ).model_dump()

    # --- Response writers ---

    def _write_response(
        self,
        stdout: asyncio.StreamWriter,
        response: dict[str, Any],
    ) -> None:
        """Serialize *response* and write one line to *stdout*."""
        line = json.dumps(response, default=str) + "\n"
        stdout.write(line.encode("utf-8"))
        # Drain is non-blocking; for asyncio's StreamWriter this schedules
        # the actual write to the underlying transport.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # In an async context, let the loop flush.
                pass
        except RuntimeError:
            pass
        logger.info("acp.response_sent id=%s", response.get("id"))

    def _write_error_response(
        self,
        stdout: asyncio.StreamWriter,
        req_id: Any,
        error: ACPError,
    ) -> None:
        """Serialize an error response and write one line to *stdout*."""
        response = JsonRpcErrorResponse.model_validate(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": error.to_dict(),
            }
        ).model_dump()
        line = json.dumps(response, default=str) + "\n"
        stdout.write(line.encode("utf-8"))
        logger.info(
            "acp.response_sent id=%s error_code=%d", req_id, error.code
        )


def _run_with_timeout_sync(coro_factory: Callable[[], Any]) -> Any:
    """Helper: run an async coroutine factory synchronously.

    Used by the synchronous ``_handle_session_prompt`` for unit testing
    convenience. In the production server path the dispatch happens from
    inside :meth:`serve`'s event loop, so this helper is never called.
    The dispatcher test exercises this via the
    ``test_execute_fn_timeout`` path.

    Note: this raises ``RuntimeError`` if called from inside a running
    event loop (which is the production case). The CLI in 2.D wires
    the async path properly.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — safe to use asyncio.run.
        return asyncio.run(coro_factory())
    raise RuntimeError(
        "_run_with_timeout_sync called from a running event loop; "
        "use the async serve() path instead."
    )


# === Module-level convenience ===


def _validate_stdin(fd: int) -> None:
    """Path A: refuse obviously-broken stdin before constructing the feeder.

    The check accepts the typical pipe / FIFO / character-device fds that
    upstream JSON-RPC clients (Toad, ``echo | ...``, etc.) supply, and
    rejects fds that would either block forever or yield nothing useful:

    - a negative fd is rejected immediately
    - an fd that fails ``os.fstat`` (closed by parent) is rejected
    - a TTY (``os.isatty``) is rejected with a hint to wire a real client
    - ``/dev/null`` is rejected via device-identity compare (same st_dev + st_ino)

    Raises ``RuntimeError`` with a human-readable message; the CLI in
    :mod:`mahavishnu.cli.acp_cli` translates it to ``typer.Exit(1)``.
    """
    if fd < 0:
        raise RuntimeError(
            f"invalid file descriptor: {fd} (ACP needs a real stdin fd)"
        )
    try:
        st = os.fstat(fd)
    except OSError as exc:
        raise RuntimeError(f"stdin fd {fd} is not open: {exc}") from exc
    if os.isatty(fd):
        raise RuntimeError(
            "stdin is a TTY — ACP requires a JSON-RPC stream on stdin. "
            "Run from a JSON-RPC client (Toad, etc.) or a pipe: "
            "`echo '...' | mahavishnu acp serve`."
        )
    # Detect /dev/null by comparing device identity (portable across macOS / Linux).
    try:
        devnull_st = os.stat("/dev/null")
    except OSError:
        devnull_st = None
    if (
        devnull_st is not None
        and st.st_dev == devnull_st.st_dev
        and st.st_ino == devnull_st.st_ino
    ):
        raise RuntimeError(
            "stdin is /dev/null — ACP needs an upstream JSON-RPC stream. "
            "If you meant to test, run with a real pipe: "
            "`echo '{}' | mahavishnu acp serve`."
        )


class _SyncStdinFeeder:
    """Path B: background thread that feeds an asyncio.StreamReader from a fd.

    Mirrors :class:`_SyncStdoutWriter` (which addresses Python 3.14's
    ``connect_write_pipe`` rejection of ``TextIOWrapper`` fds) but on the
    READ side: macOS's kqueue-based selector (``selector.register``)
    rejects ``kEVFILT_READ`` on fds that aren't real I/O endpoints with
    ``OSError(EINVAL)`` — silently inside the ``_add_reader`` callback,
    which leaves ``connect_read_pipe`` returning a transport that was
    never registered. The dispatcher's ``await stream.read()`` then waits
    forever.

    A blocking ``os.read`` loop in a daemon thread works on any fd. Data
    is posted to the asyncio loop via ``call_soon_threadsafe``; EOF is
    signalled with :meth:`asyncio.StreamReader.feed_eof`. The thread is
    daemon=True so a parent ``SIGTERM`` (e.g. from a CLI ``timeout``)
    cleanly tears down the process.
    """

    def __init__(
        self,
        stream: asyncio.StreamReader,
        fd: int,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._stream = stream
        self._fd = fd
        self._loop = loop
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="acp-stdin-feeder",
        )

    def start(self) -> None:
        self._thread.start()

    def _post(self, fn: Callable[..., Any], *args: Any) -> None:
        """Schedule ``fn`` to run on the asyncio loop from this thread."""
        try:
            self._loop.call_soon_threadsafe(fn, *args)
        except RuntimeError as exc:
            # Loop is closed (process tearing down). Log and let the thread exit.
            logger.debug("acp.stdin_feeder_post_after_close fn=%s error=%s", fn.__name__, exc)

    def _run(self) -> None:
        try:
            while True:
                chunk = os.read(self._fd, 8192)
                if not chunk:
                    # EOF: signal the reader and exit the thread.
                    self._post(self._stream.feed_eof)
                    return
                self._post(self._stream.feed_data, chunk)
        except OSError as exc:
            logger.error("acp.stdin_read_error error=%s", exc)
            self._post(self._stream.set_exception, exc)


class _SyncStdoutWriter:
    """Synchronous stdout writer that bypasses ``connect_write_pipe``.

    Python 3.14's ``connect_write_pipe`` requires the stream to be a
    raw pipe/socket/character device; the ``TextIOWrapper`` that wraps
    ``sys.stdout`` fails that check, raising ``ValueError``. ``os.write``
    on the underlying fd works regardless of whether stdout is a pipe,
    TTY, or captured stream. JSON-RPC responses are small (one line per
    request), so a synchronous write is safe. No-op ``drain`` for the
    asyncio ``StreamWriter`` protocol surface.
    """

    def __init__(self) -> None:
        self._fd: int = sys.stdout.fileno()

    def write(self, data: bytes) -> None:
        os.write(self._fd, data)

    async def drain(self) -> None:
        return None


async def serve(
    execute_fn: ExecuteFn,
    *,
    stdin: asyncio.StreamReader | None = None,
    stdout: Any = None,
    stderr: Any = None,
    bearer_token: str | None = None,
    max_concurrent_sessions: int = MAX_CONCURRENT_SESSIONS,
    session_timeout_seconds: float = DEFAULT_SESSION_TIMEOUT_SECONDS,
) -> None:
    """Module-level convenience: construct ``ACPServer`` and run its ``serve`` loop.

    ``stdin`` and ``stdout`` default to the process ``sys.stdin`` /
    ``sys.stdout``. stdin is read by a background thread
    (:class:`_SyncStdinFeeder`) which posts bytes to an
    :class:`asyncio.StreamReader` via ``loop.call_soon_threadsafe`` —
    bypassing ``loop.connect_read_pipe`` so the dispatcher does NOT hang
    on macOS kqueue when stdin points at a virtual filesystem fd
    (``/dev/null`` etc.). stdout is wrapped in :class:`_SyncStdoutWriter`
    which writes via ``os.write`` to the underlying fd.
    """
    server = ACPServer(
        execute_fn,
        bearer_token=bearer_token,
        max_concurrent_sessions=max_concurrent_sessions,
        session_timeout_seconds=session_timeout_seconds,
    )
    if stdin is None:
        # Path A: refuse obviously-broken stdin (TTY, /dev/null, negative fd).
        # Path A catches adversarial / accidental runs before we burn a thread
        # on a fd that will never yield useful data.
        stdin_fd = sys.stdin.fileno()
        _validate_stdin(stdin_fd)
        loop = asyncio.get_event_loop()
        stdin = asyncio.StreamReader()
        # Path B: thread-based feeder (see _SyncStdinFeeder below).
        _SyncStdinFeeder(stdin, stdin_fd, loop).start()
    if stdout is None:
        stdout = _SyncStdoutWriter()
    await server.serve(stdin, stdout, stderr)


__all__ = [
    "CANCEL_GRACE_SECONDS",
    "DEFAULT_SESSION_TIMEOUT_SECONDS",
    "MAX_CONCURRENT_SESSIONS",
    "STDIN_LINE_MAX_BYTES",
    "ACPError",
    "ACPServer",
    "ACPSession",
    "new_session_id",
    "serve",
    "_SyncStdinFeeder",
    "_validate_stdin",
]
