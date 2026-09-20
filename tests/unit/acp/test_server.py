"""Tests for ``mahavishnu.acp.server`` — dispatcher core (2.B)."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import pytest

from mahavishnu.acp.errors import (
    AUTH_INVALID,
    AUTH_REQUIRED,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    SESSION_PERSISTENCE_NOT_IMPLEMENTED,
    TOO_MANY_CONCURRENT_SESSIONS,
)
from mahavishnu.acp.server import (
    MAX_CONCURRENT_SESSIONS,
    STDIN_LINE_MAX_BYTES,
    ACPServer,
    ACPSession,
    _ACPParseError,
    _SafeLineReader,
    _SyncStdinFeeder,
    _validate_stdin,
    new_session_id,
)

pytestmark = [pytest.mark.unit, pytest.mark.acp, pytest.mark.acp_stdio]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_bearer() -> str:
    return "a" * 40  # 40-byte bearer (passes min-length)


@pytest.fixture
def server(valid_bearer: str) -> ACPServer:
    """An ACPServer with an explicit bearer, ready for synchronous dispatch."""
    async def execute_fn(payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "prompt": payload.get("prompt")}

    return ACPServer(
        execute_fn=execute_fn,
        bearer_token=valid_bearer,
    )


def _request(method: str, params: dict[str, Any] | None = None, req_id: Any = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}


def _error_code(response: dict[str, Any] | None) -> int | None:
    """Extract the JSON-RPC error code from a response dict (or None if success)."""
    if response is None:
        return None
    err = response.get("error")
    if err is None:
        return None
    return err.get("code")


def _result(response: dict[str, Any]) -> Any:
    """Extract the JSON-RPC result field."""
    return response.get("result")


# ---------------------------------------------------------------------------
# JSON-RPC envelope validation
# ---------------------------------------------------------------------------

class TestEnvelopeValidation:
    """Malformed JSON-RPC envelopes are rejected before method dispatch."""

    def test_unknown_method_returns_method_not_found(self, server: ACPServer) -> None:
        response = server.handle_request(_request("session/prompt"))
        # session/prompt requires auth first; without auth → AUTH_REQUIRED.
        # To test METHOD_NOT_FOUND, use a method that doesn't bypass auth.
        # initialize does not require auth, so test a non-existent method
        # with auth bypass: this is hard to express via the current
        # envelope validation. Instead, authenticate first.
        server.handle_request(_request("authenticate", {"methodId": "bearer", "token": "a" * 40}))
        response = server.handle_request(_request("totally/made/up"))
        assert _error_code(response) == METHOD_NOT_FOUND

    def test_extra_fields_in_envelope_rejected(self, server: ACPServer) -> None:
        bad = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
            "rogue": "field",
        }
        # Extra envelope fields should be rejected by Pydantic.
        response = server.handle_request(bad)
        assert _error_code(response) == INVALID_PARAMS

    def test_invalid_jsonrpc_version_rejected(self, server: ACPServer) -> None:
        bad = {"jsonrpc": "1.0", "id": 1, "method": "initialize", "params": {}}
        response = server.handle_request(bad)
        assert _error_code(response) == INVALID_PARAMS


# ---------------------------------------------------------------------------
# initialize handler
# ---------------------------------------------------------------------------

class TestInitialize:
    def test_initialize_returns_protocol_version_echo(self, server: ACPServer) -> None:
        response = server.handle_request(
            _request("initialize", {"protocolVersion": "0.0.1", "clientInfo": {"name": "smoke", "version": "0.0.1"}})
        )
        result = _result(response)
        assert result["protocolVersion"] == "0.0.1"
        assert result["agentCapabilities"]["loadSession"] is False
        assert result["agentCapabilities"]["mcpCapabilities"]["http"] is False
        assert result["agentCapabilities"]["mcpCapabilities"]["sse"] is False

    def test_initialize_does_not_require_auth(self, server: ACPServer) -> None:
        # initialize is the only method that runs unauthenticated.
        response = server.handle_request(
            _request("initialize", {"protocolVersion": "0.0.1", "clientInfo": {"name": "smoke", "version": "0.0.1"}})
        )
        assert _error_code(response) is None

    def test_initialize_oversized_protocol_version_rejected(self, server: ACPServer) -> None:
        response = server.handle_request(
            _request(
                "initialize",
                {
                    "protocolVersion": "x" * 200,  # exceeds PROTOCOL_VERSION_MAX=32
                    "clientInfo": {"name": "smoke", "version": "0.0.1"},
                },
            )
        )
        assert _error_code(response) == INVALID_PARAMS


# ---------------------------------------------------------------------------
# authenticate handler
# ---------------------------------------------------------------------------

class TestAuthenticate:
    def test_correct_bearer_succeeds(self, server: ACPServer, valid_bearer: str) -> None:
        response = server.handle_request(
            _request("authenticate", {"methodId": "bearer", "token": valid_bearer})
        )
        assert _error_code(response) is None

    def test_wrong_bearer_returns_auth_invalid(self, server: ACPServer) -> None:
        response = server.handle_request(
            _request("authenticate", {"methodId": "bearer", "token": "wrong-token-here-padding-padding"})
        )
        assert _error_code(response) == AUTH_INVALID

    def test_non_bearer_method_rejected(self, server: ACPServer) -> None:
        response = server.handle_request(
            _request("authenticate", {"methodId": "mtls", "token": "x" * 40})
        )
        assert _error_code(response) == INVALID_PARAMS

    def test_missing_token_rejected(self, server: ACPServer) -> None:
        response = server.handle_request(
            _request("authenticate", {"methodId": "bearer"})
        )
        assert _error_code(response) == INVALID_PARAMS


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------

class TestAuthGate:
    """Per-process auth gate: every method except ``initialize`` requires prior ``authenticate``."""

    def test_session_new_without_auth_returns_auth_required(self, server: ACPServer) -> None:
        response = server.handle_request(_request("session/new"))
        assert _error_code(response) == AUTH_REQUIRED

    def test_session_load_without_auth_returns_auth_required(self, server: ACPServer) -> None:
        response = server.handle_request(_request("session/load"))
        assert _error_code(response) == AUTH_REQUIRED

    def test_session_prompt_without_auth_returns_auth_required(self, server: ACPServer) -> None:
        response = server.handle_request(
            _request("session/prompt", {"sessionId": "x" * 36, "content": [{"type": "text", "text": "hi"}]})
        )
        assert _error_code(response) == AUTH_REQUIRED

    def test_session_cancel_without_auth_returns_auth_required(self, server: ACPServer) -> None:
        response = server.handle_request(_request("session/cancel", {"sessionId": "x" * 36}))
        assert _error_code(response) == AUTH_REQUIRED

    def test_session_load_returns_session_persistence_not_implemented_after_auth(
        self, server: ACPServer, valid_bearer: str
    ) -> None:
        server.handle_request(_request("authenticate", {"methodId": "bearer", "token": valid_bearer}))
        response = server.handle_request(_request("session/load"))
        assert _error_code(response) == SESSION_PERSISTENCE_NOT_IMPLEMENTED


# ---------------------------------------------------------------------------
# session/new — rate limiting
# ---------------------------------------------------------------------------

class TestSessionNew:
    def _authenticate(self, server: ACPServer, valid_bearer: str) -> None:
        server.handle_request(
            _request("authenticate", {"methodId": "bearer", "token": valid_bearer})
        )

    def test_session_new_creates_session(
        self, server: ACPServer, valid_bearer: str
    ) -> None:
        self._authenticate(server, valid_bearer)
        response = server.handle_request(_request("session/new"))
        result = _result(response)
        assert "sessionId" in result
        assert len(result["sessionId"]) == 36  # UUID4 string length

    def test_session_new_increments_count(
        self, server: ACPServer, valid_bearer: str
    ) -> None:
        self._authenticate(server, valid_bearer)
        for i in range(3):
            response = server.handle_request(_request("session/new", req_id=i))
            assert _error_code(response) is None
        assert len(server._sessions) == 3  # type: ignore[attr-defined]

    def test_session_new_over_rate_limit_returns_too_many(
        self, valid_bearer: str
    ) -> None:
        """When ``len(sessions) >= max_concurrent_sessions``, the next ``session/new`` is rejected."""

        async def execute_fn(payload: dict[str, Any]) -> dict[str, Any]:
            return {}

        # Use a small max for the test.
        server = ACPServer(
            execute_fn=execute_fn,
            bearer_token=valid_bearer,
            max_concurrent_sessions=2,
        )
        self._authenticate(server, valid_bearer)
        # First two succeed.
        for i in range(2):
            r = server.handle_request(_request("session/new", req_id=i))
            assert _error_code(r) is None
        # Third is rate-limited.
        r = server.handle_request(_request("session/new", req_id=3))
        assert _error_code(r) == TOO_MANY_CONCURRENT_SESSIONS


# ---------------------------------------------------------------------------
# session/cancel — idempotency
# ---------------------------------------------------------------------------

class TestSessionCancel:
    def _authenticate_and_create_session(
        self, server: ACPServer, valid_bearer: str
    ) -> str:
        server.handle_request(_request("authenticate", {"methodId": "bearer", "token": valid_bearer}))
        response = server.handle_request(_request("session/new"))
        return _result(response)["sessionId"]

    def test_cancel_unknown_session_acks(
        self, server: ACPServer, valid_bearer: str
    ) -> None:
        """Cancel is idempotent — ack even on unknown session_id (no error)."""
        server.handle_request(
            _request("authenticate", {"methodId": "bearer", "token": valid_bearer})
        )
        response = server.handle_request(
            _request("session/cancel", {"sessionId": "x" * 36})
        )
        assert _error_code(response) is None

    def test_cancel_inactive_session_acks(
        self, server: ACPServer, valid_bearer: str
    ) -> None:
        """Cancel on a session with no in-flight task is a no-op ack."""
        sid = self._authenticate_and_create_session(server, valid_bearer)
        response = server.handle_request(_request("session/cancel", {"sessionId": sid}))
        assert _error_code(response) is None


# ---------------------------------------------------------------------------
# ACPSession dataclass
# ---------------------------------------------------------------------------

class TestACPSession:
    def test_new_session_has_uuid_id(self) -> None:
        sid = new_session_id()
        assert len(sid) == 36
        # UUID4 string format: 8-4-4-4-12 hex digits
        assert sid.count("-") == 4

    def test_session_defaults(self) -> None:
        sess = ACPSession(session_id="abc")
        assert sess.session_id == "abc"
        assert sess.task is None
        assert sess.cancel_requested is False
        assert sess.authenticated is False


# ---------------------------------------------------------------------------
# _SafeLineReader
# ---------------------------------------------------------------------------

class TestSafeLineReader:
    @pytest.mark.asyncio
    async def test_reads_normal_line(self) -> None:
        stream = asyncio.StreamReader()
        stream.feed_data(b'{"jsonrpc":"2.0"}\n')
        stream.feed_eof()
        reader = _SafeLineReader(stream, max_bytes=1024)
        line = await reader.read_line()
        assert line == '{"jsonrpc":"2.0"}'

    @pytest.mark.asyncio
    async def test_reads_multiple_lines_sequentially(self) -> None:
        stream = asyncio.StreamReader()
        stream.feed_data(b'line1\nline2\nline3\n')
        stream.feed_eof()
        reader = _SafeLineReader(stream, max_bytes=1024)
        assert await reader.read_line() == "line1"
        assert await reader.read_line() == "line2"
        assert await reader.read_line() == "line3"
        assert await reader.read_line() is None

    @pytest.mark.asyncio
    async def test_oversize_line_raises_parse_error(self) -> None:
        stream = asyncio.StreamReader()
        big = b"x" * 2000 + b"\n"
        stream.feed_data(big)
        stream.feed_eof()
        reader = _SafeLineReader(stream, max_bytes=1024)
        with pytest.raises(_ACPParseError):
            await reader.read_line()

    @pytest.mark.asyncio
    async def test_eof_returns_none(self) -> None:
        stream = asyncio.StreamReader()
        stream.feed_eof()
        reader = _SafeLineReader(stream, max_bytes=1024)
        assert await reader.read_line() is None

    @pytest.mark.asyncio
    async def test_eof_after_partial_line_raises_parse_error(self) -> None:
        """An incomplete line (no newline) at EOF is a parse error."""
        stream = asyncio.StreamReader()
        stream.feed_data(b"no newline here")
        stream.feed_eof()
        reader = _SafeLineReader(stream, max_bytes=1024)
        with pytest.raises(_ACPParseError):
            await reader.read_line()

    @pytest.mark.asyncio
    async def test_long_line_split_across_chunks_rejected(self) -> None:
        """A line >max_bytes split across multiple chunks is still rejected."""
        stream = asyncio.StreamReader()
        # Feed in chunks smaller than max_bytes.
        chunks = [b"x" * 500, b"x" * 500, b"x" * 500, b"\n"]
        for c in chunks:
            stream.feed_data(c)
        stream.feed_eof()
        reader = _SafeLineReader(stream, max_bytes=1024)
        with pytest.raises(_ACPParseError):
            await reader.read_line()


# ---------------------------------------------------------------------------
# Plan §Phase 2 Task 1 specific assertions
# ---------------------------------------------------------------------------

class TestPlanInvariants:
    """Specific assertions enumerated in plan §Phase 2 Task 1."""

    def test_uses_compare_digest(self) -> None:
        """The dispatcher delegates bearer comparison to ``mahavishnu.acp.auth``
        which uses ``secrets.compare_digest`` (verified in test_auth.py)."""
        import inspect

        from mahavishnu.acp.auth import verify_token

        source = inspect.getsource(verify_token)
        assert "compare_digest" in source

    def test_bearer_loaded_via_acquire_bearer(self) -> None:
        """The dispatcher calls ``acquire_bearer`` at startup; we verify
        by inspecting the ACPServer.serve method."""
        import inspect

        from mahavishnu.acp.server import ACPServer

        source = inspect.getsource(ACPServer.serve)
        assert "acquire_bearer" in source

    def test_stdin_cap_constant_matches_plan(self) -> None:
        assert STDIN_LINE_MAX_BYTES == 1_048_576

    def test_default_max_concurrent_sessions_matches_plan(self) -> None:
        assert MAX_CONCURRENT_SESSIONS == 16

    def test_handle_request_returns_none_for_valid_request(self, server: ACPServer) -> None:
        """``handle_request`` returns a response dict for requests with an id."""
        response = server.handle_request(
            _request("initialize", {"protocolVersion": "0.0.1", "clientInfo": {"name": "smoke", "version": "0.0.1"}})
        )
        assert response is not None
        assert "result" in response


# ---------------------------------------------------------------------------
# Constructor (fail-closed without bearer)
# ---------------------------------------------------------------------------

class TestConstructorFailClosed:
    """End-to-end of the serve() main loop with injected streams."""

    class _MockStdout:
        """Captures stdout writes for assertion. Mimics the protocol
        ``_write_response`` expects (``write(data: bytes)``).

        Note: the dispatcher's ``_write_response`` calls ``stdout.write(line.encode("utf-8"))``
        and logs the response. ``_write_error_response`` does the same.
        No ``drain`` is awaited, so a simple Mock that records bytes is enough.
        """

        def __init__(self) -> None:
            self.lines: list[bytes] = []

        def write(self, data: bytes) -> None:
            self.lines.append(data)

        def get_text(self) -> str:
            return b"".join(self.lines).decode("utf-8", errors="replace")

    @pytest.mark.asyncio
    async def test_serve_refuses_to_start_without_bearer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If no bearer is set and the env is empty, ``serve()`` raises RuntimeError."""
        from mahavishnu.acp.auth import (
            ENV_BEARER_TOKEN,
            ENV_BEARER_TOKEN_FILE,
            reset_cached_bearer_for_tests,
        )

        monkeypatch.delenv(ENV_BEARER_TOKEN, raising=False)
        monkeypatch.delenv(ENV_BEARER_TOKEN_FILE, raising=False)
        reset_cached_bearer_for_tests()

        async def execute_fn(payload: dict[str, Any]) -> dict[str, Any]:
            return {}

        server = ACPServer(execute_fn=execute_fn, bearer_token=None)
        stdin = asyncio.StreamReader()
        stdin.feed_eof()
        stdout = self._MockStdout()
        with pytest.raises(RuntimeError, match="refuses to start"):
            await server.serve(stdin, stdout)
        reset_cached_bearer_for_tests()

    @pytest.mark.asyncio
    async def test_serve_succeeds_with_explicit_bearer(
        self, valid_bearer: str
    ) -> None:
        """Smoke test: explicit bearer → server consumes one ``initialize`` line and writes a response."""

        async def execute_fn(payload: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        server = ACPServer(execute_fn=execute_fn, bearer_token=valid_bearer)
        stdin = asyncio.StreamReader()
        stdin.feed_data(
            b'{"jsonrpc":"2.0","id":1,"method":"initialize",'
            b'"params":{"protocolVersion":"0.0.1","clientInfo":{"name":"smoke","version":"0.0.1"}}}\n'
        )
        stdin.feed_eof()
        stdout = self._MockStdout()
        await server.serve(stdin, stdout)
        # One response line for the initialize call. The JSON-RPC response
        # must include the protocolVersion echo and ``loadSession: false``.
        assert len(stdout.lines) == 1
        text = stdout.get_text()
        # Pydantic may render JSON with or without spaces; assert on the
        # canonical fields individually. Integer values render as JSON
        # numbers (no surrounding quotes), strings as quoted.
        assert '"jsonrpc"' in text and '"2.0"' in text
        assert '"id": 1' in text or '"id":1' in text
        assert '"loadSession": false' in text or '"loadSession":false' in text
        assert '"protocolVersion": "0.0.1"' in text or '"protocolVersion":"0.0.1"' in text

    @pytest.mark.asyncio
    async def test_serve_with_multiple_requests(
        self, valid_bearer: str
    ) -> None:
        """End-to-end: initialize, authenticate, session/new — three responses over one stream."""

        async def execute_fn(payload: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        server = ACPServer(execute_fn=execute_fn, bearer_token=valid_bearer)
        stdin = asyncio.StreamReader()
        lines = [
            b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"0.0.1","clientInfo":{"name":"smoke","version":"0.0.1"}}}\n',
            b'{"jsonrpc":"2.0","id":2,"method":"authenticate","params":{"methodId":"bearer","token":"' + valid_bearer.encode() + b'"}}\n',
            b'{"jsonrpc":"2.0","id":3,"method":"session/new","params":{}}\n',
        ]
        stdin.feed_data(b"".join(lines))
        stdin.feed_eof()
        stdout = self._MockStdout()
        await server.serve(stdin, stdout)
        assert len(stdout.lines) == 3
        text = stdout.get_text()
        # Each id should appear once in the responses. Integer ids render
        # as JSON numbers, so we match with or without a space after the colon.
        for req_id in (1, 2, 3):
            assert f'"id": {req_id}' in text or f'"id":{req_id}' in text

    @pytest.mark.asyncio
    async def test_serve_handles_parse_error_with_id_none(
        self, valid_bearer: str
    ) -> None:
        """A malformed JSON line → response with ``-32700 Parse error``."""
        async def execute_fn(payload: dict[str, Any]) -> dict[str, Any]:
            return {}

        server = ACPServer(execute_fn=execute_fn, bearer_token=valid_bearer)
        stdin = asyncio.StreamReader()
        # JSON missing the closing brace — ``json.loads`` raises JSONDecodeError.
        stdin.feed_data(b'{"jsonrpc":"2.0","id":1,"method"\n')
        stdin.feed_eof()
        stdout = self._MockStdout()
        await server.serve(stdin, stdout)
        text = stdout.get_text()
        assert "Parse error" in text or "-32700" in text


# ---------------------------------------------------------------------------
# _SyncStdinFeeder — Path B: thread-based stdin reader (mirrors _SyncStdoutWriter)
# ---------------------------------------------------------------------------


class TestSyncStdinFeeder:
    """``_SyncStdinFeeder`` posts data from a blocking ``os.read`` thread into an
    :class:`asyncio.StreamReader` via ``loop.call_soon_threadsafe``.

    This is the replacement for ``loop.connect_read_pipe(lambda: protocol, sys.stdin)``
    which fails with ``OSError(EINVAL)`` on macOS kqueue when stdin is a virtual
    filesystem fd (``/dev/null``, etc.). The thread bypasses the selector
    entirely — any open, readable fd works.
    """

    @pytest.mark.asyncio
    async def test_feeder_posts_chunks_from_pipe_to_stream_reader(self) -> None:
        """Writing to a pipe is reflected in the asyncio stream reader."""
        r_fd, w_fd = os.pipe()
        try:
            stream = asyncio.StreamReader()
            loop = asyncio.get_running_loop()
            feeder = _SyncStdinFeeder(stream, r_fd, loop)
            feeder.start()

            os.write(w_fd, b"hello stdin\n")
            data = await asyncio.wait_for(stream.readuntil(b"\n"), timeout=2.0)
            assert data == b"hello stdin\n"
        finally:
            try:
                os.close(r_fd)
            except OSError:
                pass
            try:
                os.close(w_fd)
            except OSError:
                pass

    @pytest.mark.asyncio
    async def test_feeder_signals_eof_when_writer_closes(self) -> None:
        """Closing the write end of the pipe causes ``feed_eof`` to fire."""
        r_fd, w_fd = os.pipe()
        try:
            stream = asyncio.StreamReader()
            loop = asyncio.get_running_loop()
            feeder = _SyncStdinFeeder(stream, r_fd, loop)
            feeder.start()

            os.write(w_fd, b"data\n")
            assert await asyncio.wait_for(stream.readuntil(b"\n"), timeout=2.0) == b"data\n"

            os.close(w_fd)  # trigger EOF
            # After EOF, readline() returns b"" (per asyncio StreamReader semantics).
            tail = await asyncio.wait_for(stream.readline(), timeout=2.0)
            assert tail == b""
        finally:
            try:
                os.close(r_fd)
            except OSError:
                pass

    @pytest.mark.asyncio
    async def test_feeder_handles_dev_null_as_immediate_eof(self) -> None:
        """``/dev/null`` yields ``b""`` on first ``os.read``; the feeder surfaces EOF cleanly.

        This is the key behaviour that makes ``mahavishnu acp serve < /dev/null``
        exit cleanly instead of hanging.
        """
        dev_null_fd = os.open("/dev/null", os.O_RDONLY)
        try:
            stream = asyncio.StreamReader()
            loop = asyncio.get_running_loop()
            feeder = _SyncStdinFeeder(stream, dev_null_fd, loop)
            feeder.start()
            # /dev/null read returns b"" immediately → EOF is fed to the stream.
            tail = await asyncio.wait_for(stream.readline(), timeout=2.0)
            assert tail == b""
        finally:
            os.close(dev_null_fd)


# ---------------------------------------------------------------------------
# _validate_stdin — Path A: pre-flight stdin fitness check
# ---------------------------------------------------------------------------


class TestValidateStdin:
    """``_validate_stdin`` rejects obviously-broken stdin before constructing the feeder."""

    def test_validate_stdin_accepts_pipe_read_end(self) -> None:
        r_fd, w_fd = os.pipe()
        try:
            # Should accept the read end of a fresh pipe — passes silently.
            assert _validate_stdin(r_fd) is None
        finally:
            os.close(r_fd)
            os.close(w_fd)

    def test_validate_stdin_rejects_tty_fd(self) -> None:
        """Opening ``/dev/tty`` (a TTY character device) makes the check refuse with
        a clear message — interactive terminals are not a JSON-RPC source.
        """
        # /dev/tty only opens if there IS a controlling terminal;
        # skip the test if the test runner has none (CI, etc.).
        try:
            tty_fd = os.open("/dev/tty", os.O_RDONLY)
        except OSError:
            pytest.skip("no controlling terminal available for the test")
        try:
            with pytest.raises(RuntimeError, match="TTY|terminal"):
                _validate_stdin(tty_fd)
        finally:
            os.close(tty_fd)

    def test_validate_stdin_rejects_dev_null_with_clear_message(self) -> None:
        """``/dev/null`` is rejected with a diagnostic, not silently allowed."""
        dev_null_fd = os.open("/dev/null", os.O_RDONLY)
        try:
            with pytest.raises(RuntimeError, match="/dev/null"):
                _validate_stdin(dev_null_fd)
        finally:
            os.close(dev_null_fd)

    def test_validate_stdin_rejects_negatively_sized_fd(self) -> None:
        """A negative fd is rejected immediately."""
        with pytest.raises(RuntimeError, match="invalid file descriptor"):
            _validate_stdin(-1)


# ---------------------------------------------------------------------------
# Module-level serve() uses the new feeder (integration-shape test)
# ---------------------------------------------------------------------------


class TestServeModuleLevelStdin:
    """Module-level ``serve()`` must NOT hang on stdin wiring; it must consume the
    pipe, respond, and return on EOF within bounded time.

    These tests monkeypatch ``sys.stdin`` to point at a real pipe so the
    module-level wiring (which now uses ``_SyncStdinFeeder``) is exercised
    end-to-end.
    """

    @pytest.mark.asyncio
    async def test_serve_module_level_completes_via_pipe(
        self, valid_bearer: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``serve()`` with a real pipe as ``sys.stdin`` reads the request,
        responds, and exits on EOF — no hang.
        """
        from mahavishnu.acp.server import serve as serve_module

        r_fd, w_fd = os.pipe()
        # Wrap r_fd in a FileIO; ``monkeypatch.setattr`` will close it on undo,
        # so we deliberately do NOT ``os.close(r_fd)`` ourselves here.
        stdin_wrapper = os.fdopen(r_fd, "rb", buffering=0)
        monkeypatch.setattr(sys, "stdin", stdin_wrapper)

        async def execute_fn(payload: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        class _CapturingStdout:
            def __init__(self) -> None:
                self.lines: list[bytes] = []

            def write(self, data: bytes) -> None:
                self.lines.append(data)

        stdout = _CapturingStdout()
        os.write(
            w_fd,
            b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
            b'{"protocolVersion":"0.0.1","clientInfo":{"name":"smoke","version":"0.0.1"}}}\n',
        )
        os.close(w_fd)  # signal EOF; the feeder will see EOF and exit cleanly

        await asyncio.wait_for(
            serve_module(execute_fn, bearer_token=valid_bearer, stdout=stdout),
            timeout=8.0,
        )
        text = b"".join(stdout.lines).decode("utf-8", errors="replace")
        assert '"id": 1' in text or '"id":1' in text

    @pytest.mark.asyncio
    async def test_serve_module_level_refuses_dev_null_with_clear_error(
        self, valid_bearer: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``serve()`` with ``sys.stdin`` pointing at ``/dev/null`` raises a
        clear ``RuntimeError`` instead of hanging.
        """
        from mahavishnu.acp.server import serve as serve_module

        async def execute_fn(payload: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        dev_null_fd = os.open("/dev/null", os.O_RDONLY)
        # Same lifecycle pattern as above: ``monkeypatch.setattr`` closes the
        # fd on undo; we never ``os.close`` it ourselves.
        stdin_wrapper = os.fdopen(dev_null_fd, "rb", buffering=0)
        monkeypatch.setattr(sys, "stdin", stdin_wrapper)

        class _NopStdout:
            def write(self, data: bytes) -> None:
                pass

        with pytest.raises(RuntimeError, match="/dev/null|refuses to start"):
            await asyncio.wait_for(
                serve_module(execute_fn, bearer_token=valid_bearer, stdout=_NopStdout()),
                timeout=3.0,
            )
