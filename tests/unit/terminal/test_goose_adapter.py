"""Unit tests for the Goose terminal adapter.

Verifies adapter contract, HTTP wire format, and error handling against
``httpx2.MockTransport`` (no network, deterministic). Req: REQ-GOO-001,
REQ-GOO-002, REQ-GOO-005.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx2 as httpx
import pytest
from pydantic import SecretStr

from mahavishnu.core.errors import (
    GooseAuthError,
    GooseTimeoutError,
    GooseUnavailable,
)
from mahavishnu.terminal.adapters.goose import GooseTerminalAdapter
from mahavishnu.terminal.goose_client import (
    DEFAULT_GOOSE_HOST,
    DEFAULT_GOOSE_PORT,
    GooseHTTPClient,
    create_goose_http_client,
)


def _mock_handler(
    *responses: httpx.Response,
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a MockTransport handler that returns ``responses`` in order.

    Mirrors tests/unit/_httpx_test_helpers.make_response_handler but
    duplicated here to keep this test file self-contained.
    """
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if not queue:
            raise AssertionError(
                f"unexpected request: {request.method} {request.url}"
            )
        return queue.pop(0)

    return handler


def _build_client(handler: Callable[[httpx.Request], httpx.Response]) -> GooseHTTPClient:
    """Build a GooseHTTPClient whose httpx transport is a MockTransport."""
    transport = httpx.MockTransport(handler)
    return GooseHTTPClient(
        base_url=f"http://{DEFAULT_GOOSE_HOST}:{DEFAULT_GOOSE_PORT}",
        secret_key=SecretStr("test-bearer-token"),
        transport=transport,
    )


@pytest.mark.unit
def test_adapter_name_is_goose() -> None:
    client = _build_client(_mock_handler(httpx.Response(200, json={"ok": True})))
    adapter = GooseTerminalAdapter(client)
    assert adapter.adapter_name == "goose"


@pytest.mark.unit
async def test_run_applescript_raises_not_implemented() -> None:
    client = _build_client(_mock_handler(httpx.Response(200, json={"ok": True})))
    adapter = GooseTerminalAdapter(client)
    with pytest.raises(NotImplementedError):
        await adapter.run_applescript("tell application \"Finder\" to activate")


@pytest.mark.unit
async def test_list_sessions_returns_expected_shape() -> None:
    client = _build_client(_mock_handler())
    adapter = GooseTerminalAdapter(client)
    sessions = await adapter.list_sessions()
    assert sessions == []

    # Add an entry directly and re-list.
    adapter._sessions["abc"] = {
        "command": "bash",
        "columns": 80,
        "rows": 24,
        "server_handle": "s-remote-1",
    }
    sessions = await adapter.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "abc"
    assert sessions[0]["command"] == "bash"
    assert sessions[0]["server_handle"] == "s-remote-1"


@pytest.mark.unit
async def test_launch_session_calls_post_sessions() -> None:
    captured: list[httpx.Request] = []
    queue: list[httpx.Response] = [
        httpx.Response(201, json={"session_id": "srv-001", "id": "srv-001"})
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return queue.pop(0)

    client = _build_client(handler)
    adapter = GooseTerminalAdapter(client)
    session_id = await adapter.launch_session("echo hi", columns=80, rows=24)

    assert isinstance(session_id, str)
    assert len(session_id) >= 8  # UUID4 short form is 8 chars; full UUID is 36
    # POST /sessions
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert req.url.path == "/sessions"
    body = json.loads(req.content)
    assert body["command"] == "echo hi"
    assert body["columns"] == 80
    assert body["rows"] == 24


@pytest.mark.unit
async def test_authorization_header_set_on_every_request() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    client = _build_client(handler)
    # Three requests in a row — every one must carry the bearer.
    await client.request("GET", "/health")
    await client.request("GET", "/sessions")
    await client.request("DELETE", "/sessions/abc")
    assert len(captured) == 3
    for req in captured:
        assert req.headers["Authorization"] == "Bearer test-bearer-token"


@pytest.mark.unit
async def test_close_session_calls_delete() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"session_id": "srv-002"})
        return httpx.Response(204)

    client = _build_client(handler)
    adapter = GooseTerminalAdapter(client)
    local_id = await adapter.launch_session("bash")
    assert len(captured) == 1
    captured.clear()

    await adapter.close_session(local_id)
    assert len(captured) == 1
    assert captured[0].method == "DELETE"
    assert captured[0].url.path == "/sessions/srv-002"


@pytest.mark.unit
async def test_send_command_unknown_session_raises_session_not_found() -> None:
    from mahavishnu.terminal.adapters.base import SessionNotFoundError

    client = _build_client(_mock_handler())
    adapter = GooseTerminalAdapter(client)
    with pytest.raises(SessionNotFoundError):
        await adapter.send_command("ghost-session", "ls")


@pytest.mark.unit
async def test_capture_output_uses_get_endpoint() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"session_id": "srv-003"})
        return httpx.Response(200, json={"output": "hello world"})

    client = _build_client(handler)
    adapter = GooseTerminalAdapter(client)
    local_id = await adapter.launch_session("bash")
    captured.clear()

    text = await adapter.capture_output(local_id, lines=10)
    assert text == "hello world"
    assert len(captured) == 1
    assert captured[0].method == "GET"
    assert captured[0].url.path == "/sessions/srv-003/output"
    # The lines limit is encoded as a query param.
    assert "limit_lines=10" in str(captured[0].url)


@pytest.mark.unit
async def test_auth_error_mapped_to_typed_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = _build_client(handler)
    with pytest.raises(GooseAuthError) as exc_info:
        await client.request("GET", "/health")
    assert exc_info.value.details.get("status_code") == 401


@pytest.mark.unit
async def test_5xx_mapped_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="goose down")

    client = _build_client(handler)
    with pytest.raises(GooseUnavailable) as exc_info:
        await client.request("GET", "/health")
    assert exc_info.value.details.get("status_code") == 503


@pytest.mark.unit
def test_create_goose_http_client_resolves_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAHAVISHNU_TERMINAL__GOOSE_HTTP_HOST", "192.0.2.10")
    monkeypatch.setenv("MAHAVISHNU_TERMINAL__GOOSE_HTTP_PORT", "9090")
    monkeypatch.setenv("MAHAVISHNU_TERMINAL__GOOSE_SECRET_KEY", "env-token")
    built = create_goose_http_client()
    assert built.base_url == "http://192.0.2.10:9090"
    assert built.has_secret is True


@pytest.mark.unit
async def test_timeout_mapped_to_typed_exception() -> None:
    """httpx.TimeoutException raised from transport surfaces as GooseTimeoutError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("read timed out", request=request)

    client = _build_client(handler)
    with pytest.raises(GooseTimeoutError) as exc_info:
        await client.request("GET", "/slow")
    assert exc_info.value.details.get("timeout_seconds") == 30.0


@pytest.mark.unit
def test_invalid_session_id_format_raises() -> None:
    client = _build_client(_mock_handler(httpx.Response(200, json={"ok": True})))
    with pytest.raises(ValueError):
        GooseTerminalAdapter(client, session_id_format="bogus")


@pytest.mark.unit
async def test_startup_probe_reports_auth_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    client = _build_client(handler)
    adapter = GooseTerminalAdapter(client)
    result = await adapter.startup_probe()
    assert result["ok"] is False
    assert result["reason"] == "auth_failed"


@pytest.mark.unit
async def test_startup_probe_reports_ok_on_health() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "healthy"})

    client = _build_client(handler)
    adapter = GooseTerminalAdapter(client)
    result = await adapter.startup_probe()
    assert result == {"ok": True, "adapter": "goose"}


@pytest.mark.unit
async def test_startup_probe_reports_unreachable() -> None:
    """When goose is offline, the probe returns ``reason: unreachable``."""
    from mahavishnu.terminal.goose_client import GooseHTTPClient

    def handler(request: httpx.Request) -> httpx.Response:
        import httpx2 as httpx
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    client = GooseHTTPClient(
        base_url="http://127.0.0.1:8694",
        secret_key=SecretStr("test"),
        transport=transport,
    )
    adapter = GooseTerminalAdapter(client)
    result = await adapter.startup_probe()
    assert result["ok"] is False
    assert result["reason"] == "unreachable"
    assert "install_hint" in result


@pytest.mark.unit
async def test_startup_probe_reports_timeout() -> None:
    """When goose times out, the probe returns ``reason: timeout``."""
    from mahavishnu.terminal.goose_client import GooseHTTPClient

    def handler(request: httpx.Request) -> httpx.Response:
        import httpx2 as httpx
        raise httpx.TimeoutException("read timed out", request=request)

    transport = httpx.MockTransport(handler)
    client = GooseHTTPClient(
        base_url="http://127.0.0.1:8694",
        secret_key=SecretStr("test"),
        transport=transport,
    )
    adapter = GooseTerminalAdapter(client)
    result = await adapter.startup_probe()
    assert result["ok"] is False
    assert result["reason"] == "timeout"


@pytest.mark.unit
async def test_send_command_calls_input_endpoint() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.method == "POST" and request.url.path == "/sessions":
            return httpx.Response(201, json={"session_id": "srv-input"})
        if request.method == "POST" and "/input" in request.url.path:
            return httpx.Response(204)
        return httpx.Response(200)

    client = _build_client(handler)
    adapter = GooseTerminalAdapter(client)
    local_id = await adapter.launch_session("bash")
    captured.clear()
    await adapter.send_command(local_id, "ls -la")
    assert len(captured) == 1
    assert captured[0].method == "POST"
    assert captured[0].url.path == "/sessions/srv-input/input"
    body = json.loads(captured[0].content)
    assert body["command"] == "ls -la"


@pytest.mark.unit
async def test_send_command_translates_5xx_to_terminal_error() -> None:
    """A 5xx on the input endpoint surfaces as TerminalError."""
    from mahavishnu.terminal.adapters.base import TerminalError

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/sessions":
            return httpx.Response(201, json={"session_id": "srv-x"})
        return httpx.Response(500, text="server error")

    client = _build_client(handler)
    adapter = GooseTerminalAdapter(client)
    local_id = await adapter.launch_session("bash")
    with pytest.raises(TerminalError):
        await adapter.send_command(local_id, "ls")


@pytest.mark.unit
async def test_capture_output_returns_string_body() -> None:
    """Some server implementations return a JSON string body, not an object."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"session_id": "srv-str"})
        # Wrap the string in JSON quotes — the parsed value is a Python ``str``
        # and exercises the ``isinstance(result, str)`` branch.
        return httpx.Response(200, json="raw output line 1\nraw output line 2")

    client = _build_client(handler)
    adapter = GooseTerminalAdapter(client)
    local_id = await adapter.launch_session("bash")
    text = await adapter.capture_output(local_id)
    assert "raw output line 1" in text


@pytest.mark.unit
async def test_capture_output_falls_back_to_str_for_non_dict_non_string() -> None:
    """Fallback when the body is neither a string nor a dict (defensive)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"session_id": "srv-fb"})
        # Return a list — neither str nor dict; ``str(result)`` is the path.
        return httpx.Response(200, json=["line1", "line2"])

    client = _build_client(handler)
    adapter = GooseTerminalAdapter(client)
    local_id = await adapter.launch_session("bash")
    text = await adapter.capture_output(local_id)
    # Fallback path: ``str(result)`` of the JSON-parsed list.
    assert "line1" in text or "line2" in text


@pytest.mark.unit
async def test_close_session_unknown_session_is_silent() -> None:
    """Closing an unknown session is a no-op (popped from a missing dict)."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    client = _build_client(handler)
    adapter = GooseTerminalAdapter(client)
    await adapter.close_session("never-existed")
    assert captured == []  # No DELETE was issued.
