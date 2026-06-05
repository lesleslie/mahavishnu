"""Unit tests for the terminal MCP client module.

Covers ``mahavishnu.terminal.mcp_client.StdioMCPClient`` (low-level JSON-RPC
over stdio transport) and the high-level ``McpretentiousClient`` wrapper.

The production code spawns a child process and talks to it via pipes. We
never spawn anything in tests; instead we patch
``asyncio.create_subprocess_exec`` and provide a fake ``Process`` whose
``stdin``/``stdout`` streams expose the async surface area the client uses.
This keeps the test deterministic, fast, and platform-agnostic.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.terminal.mcp_client import McpretentiousClient, StdioMCPClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_process(stdout_lines: list[bytes] | None = None) -> MagicMock:
    """Build a fake ``asyncio.subprocess.Process`` for tests.

    Args:
        stdout_lines: Pre-canned bytes to return from successive
            ``readline()`` calls. An empty list means EOF immediately.

    Returns:
        A ``MagicMock`` configured with the minimum attribute surface the
        client touches.
    """
    if stdout_lines is None:
        stdout_lines = []

    process = MagicMock(
        spec=["stdin", "stdout", "stderr", "terminate", "kill", "wait", "returncode"]
    )
    process.returncode = None
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdin.drain = AsyncMock()

    # readline() pops the next canned line or returns b"" to signal EOF.
    queue = list(stdout_lines)

    async def _readline() -> bytes:
        if queue:
            return queue.pop(0)
        return b""

    process.stdout = MagicMock()
    process.stdout.readline = _readline

    process.stderr = MagicMock()
    process.terminate = MagicMock()
    process.kill = MagicMock()
    process.wait = AsyncMock(return_value=0)
    return process


def _jsonrpc_response(req_id: int, result: Any) -> bytes:
    """Encode a successful JSON-RPC response line."""
    payload = {"jsonrpc": "2.0", "id": req_id, "result": result}
    return (json.dumps(payload) + "\n").encode()


def _jsonrpc_error(req_id: int, message: str) -> bytes:
    """Encode an error JSON-RPC response line."""
    payload = {"jsonrpc": "2.0", "id": req_id, "error": {"message": message}}
    return (json.dumps(payload) + "\n").encode()


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestStdioMCPClientInstantiation:
    """``StdioMCPClient.__init__`` should record inputs and seed state."""

    def test_default_construction_records_command_and_args(self) -> None:
        """Constructor stores command/args verbatim and initialises state."""
        client = StdioMCPClient("uvx", ["--from", "mcpretentious", "mcpretentious"])

        assert client.command == "uvx"
        assert client.args == ["--from", "mcpretentious", "mcpretentious"]
        assert client.process is None
        assert client._request_id == 0
        assert client._pending_requests == {}

    def test_construction_with_empty_args(self) -> None:
        """An empty args list is valid (e.g. for a bare binary)."""
        client = StdioMCPClient("/usr/local/bin/mcp-server", [])

        assert client.args == []
        assert client.command == "/usr/local/bin/mcp-server"
        assert client._pending_requests == {}


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


class TestStdioMCPClientLifecycle:
    """``start`` / ``stop`` drive the connection state machine."""

    @pytest.mark.asyncio
    async def test_start_spawns_subprocess_and_starts_reader(self) -> None:
        """``start`` invokes ``create_subprocess_exec`` and schedules a reader."""
        fake_process = _make_fake_process()
        with patch(
            "mahavishnu.terminal.mcp_client.asyncio.create_subprocess_exec",
            AsyncMock(return_value=fake_process),
        ) as mock_exec:
            client = StdioMCPClient("uvx", ["mcpretentious"])
            await client.start()

        mock_exec.assert_awaited_once()
        # Command + args are forwarded positionally to subprocess_exec.
        positional = mock_exec.await_args.args
        assert positional[0] == "uvx"
        assert positional[1] == "mcpretentious"
        # stdin/stdout/stderr pipes are requested.
        assert mock_exec.await_args.kwargs["stdin"] is not None
        assert mock_exec.await_args.stdout is not None
        assert mock_exec.await_args.stderr is not None

        assert client.process is fake_process

    @pytest.mark.asyncio
    async def test_start_wraps_subprocess_failure_in_runtime_error(self) -> None:
        """Subprocess-exec failures surface as ``RuntimeError``."""
        with patch(
            "mahavishnu.terminal.mcp_client.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=FileNotFoundError("nope")),
        ):
            client = StdioMCPClient("missing", [])
            with pytest.raises(RuntimeError, match="Failed to start MCP server"):
                await client.start()

    @pytest.mark.asyncio
    async def test_stop_terminates_process_and_awaits_wait(self) -> None:
        """``stop`` calls ``terminate``, then ``wait`` with a timeout."""
        fake_process = _make_fake_process()
        client = StdioMCPClient("uvx", [])
        client.process = fake_process

        await client.stop()

        fake_process.terminate.assert_called_once()
        fake_process.wait.assert_awaited_once()
        fake_process.kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_kills_on_wait_timeout(self) -> None:
        """If the process does not exit within 5s, fall back to ``kill``."""
        fake_process = _make_fake_process()
        fake_process.wait = AsyncMock(side_effect=TimeoutError)
        client = StdioMCPClient("uvx", [])
        client.process = fake_process

        await client.stop()

        fake_process.terminate.assert_called_once()
        fake_process.kill.assert_called_once()
        # Two wait() invocations: one for the timeout path, one after kill.
        assert fake_process.wait.await_count == 2

    @pytest.mark.asyncio
    async def test_stop_is_noop_without_process(self) -> None:
        """``stop`` on an un-started client is a safe no-op."""
        client = StdioMCPClient("uvx", [])
        # Should not raise.
        await client.stop()


# ---------------------------------------------------------------------------
# call_tool — happy path
# ---------------------------------------------------------------------------


class TestStdioMCPClientCallToolHappyPath:
    """When the server replies cleanly, ``call_tool`` returns ``result``."""

    @pytest.mark.asyncio
    async def test_call_tool_sends_jsonrpc_request_and_returns_result(self) -> None:
        """Sends a JSON-RPC request, waits for the response, returns ``result``."""
        response = _jsonrpc_response(1, {"terminal_id": "term-abc"})
        fake_process = _make_fake_process([response])

        client = StdioMCPClient("uvx", [])
        client.process = fake_process
        client._request_id = 0

        # Reader task is normally scheduled by start(); we start it manually
        # since we are not invoking start() here.
        reader = asyncio.create_task(client._read_stdout())

        result = await client.call_tool("mcpretentious-open", {"columns": 80, "rows": 24})

        assert result == {"terminal_id": "term-abc"}
        # Outgoing bytes include the JSON-RPC payload.
        written = b"".join(call.args[0] for call in fake_process.stdin.write.call_args_list)
        request = json.loads(written.decode().strip())
        assert request["jsonrpc"] == "2.0"
        assert request["id"] == 1
        assert request["method"] == "tools/call"
        assert request["params"] == {
            "name": "mcpretentious-open",
            "arguments": {"columns": 80, "rows": 24},
        }
        # Pending map is drained after the response.
        assert client._pending_requests == {}
        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_call_tool_increments_request_id_per_call(self) -> None:
        """Each ``call_tool`` invocation uses a fresh, monotonically increasing id."""
        fake_process = _make_fake_process(
            [
                _jsonrpc_response(1, {"ok": 1}),
                _jsonrpc_response(2, {"ok": 2}),
            ]
        )
        client = StdioMCPClient("uvx", [])
        client.process = fake_process
        reader = asyncio.create_task(client._read_stdout())

        first = await client.call_tool("a", {})
        second = await client.call_tool("b", {})

        assert (first, second) == ({"ok": 1}, {"ok": 2})
        assert client._request_id == 2
        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# call_tool — error paths
# ---------------------------------------------------------------------------


class TestStdioMCPClientCallToolErrors:
    """``call_tool`` translates transport and protocol errors into ``RuntimeError``."""

    @pytest.mark.asyncio
    async def test_call_tool_raises_when_not_started(self) -> None:
        """Calling before start() raises ``RuntimeError``."""
        client = StdioMCPClient("uvx", [])
        with pytest.raises(RuntimeError, match="MCP server process is not running"):
            await client.call_tool("x", {})

    @pytest.mark.asyncio
    async def test_call_tool_raises_on_server_error_response(self) -> None:
        """Server-side error field is converted to ``RuntimeError``."""
        fake_process = _make_fake_process([_jsonrpc_error(1, "boom")])
        client = StdioMCPClient("uvx", [])
        client.process = fake_process
        reader = asyncio.create_task(client._read_stdout())

        with pytest.raises(RuntimeError, match="MCP tool error"):
            await client.call_tool("broken", {})

        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_call_tool_raises_on_invalid_response_shape(self) -> None:
        """Response without ``result`` or ``error`` is rejected."""
        bogus = (json.dumps({"jsonrpc": "2.0", "id": 1}) + "\n").encode()
        fake_process = _make_fake_process([bogus])
        client = StdioMCPClient("uvx", [])
        client.process = fake_process
        reader = asyncio.create_task(client._read_stdout())

        with pytest.raises(RuntimeError, match="Invalid MCP response"):
            await client.call_tool("x", {})

        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_call_tool_timeout_removes_pending_request(self) -> None:
        """A timeout cleans up the pending request and surfaces as ``RuntimeError``."""
        # Empty queue → readline returns b"" → reader loop exits → future is
        # never resolved → asyncio.wait_for raises TimeoutError internally.
        fake_process = _make_fake_process([])
        client = StdioMCPClient("uvx", [])
        client.process = fake_process
        reader = asyncio.create_task(client._read_stdout())

        with (
            patch(
                "mahavishnu.terminal.mcp_client.asyncio.wait_for",
                AsyncMock(side_effect=TimeoutError),
            ),
            pytest.raises(RuntimeError, match="Timeout calling MCP tool"),
        ):
            await client.call_tool("slow", {})

        assert client._pending_requests == {}
        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_call_tool_raises_and_cleans_up_on_unexpected_exception(self) -> None:
        """Non-timeout exceptions still surface as ``RuntimeError`` and clean up."""
        fake_process = _make_fake_process([])
        client = StdioMCPClient("uvx", [])
        client.process = fake_process
        reader = asyncio.create_task(client._read_stdout())

        with (
            patch(
                "mahavishnu.terminal.mcp_client.asyncio.wait_for",
                AsyncMock(side_effect=OSError("connection reset")),
            ),
            pytest.raises(RuntimeError, match="Failed to call MCP tool"),
        ):
            await client.call_tool("flaky", {})

        assert client._pending_requests == {}
        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Request correlation & state machine
# ---------------------------------------------------------------------------


class TestStdioMCPClientRequestCorrelation:
    """Concurrent calls must not cross-deliver responses."""

    @pytest.mark.asyncio
    async def test_concurrent_calls_do_not_cross_deliver(self) -> None:
        """Two in-flight calls each receive their own response by id."""
        # Two responses, in order. Both must reach the right pending future.
        response_lines = [
            _jsonrpc_response(1, {"tag": "first"}),
            _jsonrpc_response(2, {"tag": "second"}),
        ]
        fake_process = _make_fake_process(response_lines)
        client = StdioMCPClient("uvx", [])
        client.process = fake_process
        reader = asyncio.create_task(client._read_stdout())

        first, second = await asyncio.gather(
            client.call_tool("a", {"which": 1}),
            client.call_tool("b", {"which": 2}),
        )

        # Verify each tool name was actually called.
        written = b"".join(call.args[0] for call in fake_process.stdin.write.call_args_list)
        requests = [json.loads(line.decode().strip()) for line in written.splitlines() if line]
        assert [r["params"]["name"] for r in requests] == ["a", "b"]
        assert [r["params"]["arguments"] for r in requests] == [{"which": 1}, {"which": 2}]
        # Verify no cross-delivery of results.
        assert first == {"tag": "first"}
        assert second == {"tag": "second"}

        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_unrelated_stdout_lines_do_not_resolve_pending_requests(self) -> None:
        """Lines without an ``id`` key are ignored by the correlation loop."""
        # Garbage + response. The reader skips the garbage and resolves 1.
        response = _jsonrpc_response(1, {"ok": True})
        fake_process = _make_fake_process([b"not-json\n", response])
        client = StdioMCPClient("uvx", [])
        client.process = fake_process
        reader = asyncio.create_task(client._read_stdout())

        result = await client.call_tool("ok", {})

        assert result == {"ok": True}
        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# High-level McpretentiousClient
# ---------------------------------------------------------------------------


class TestMcpretentiousClient:
    """The high-level client delegates and shapes parameters correctly."""

    def test_default_construction_uses_uvx_mcpretentious(self) -> None:
        """The default ctor wires up the documented uvx command."""
        client = McpretentiousClient()
        inner = client._client  # type: ignore[attr-defined]
        assert isinstance(inner, StdioMCPClient)
        assert inner.command == "uvx"
        assert inner.args == ["--from", "mcpretentious", "mcpretentious"]

    @pytest.mark.asyncio
    async def test_start_and_stop_delegate_to_inner_client(self) -> None:
        """``start``/``stop`` proxy to the underlying ``StdioMCPClient``."""
        client = McpretentiousClient()
        client._client.start = AsyncMock()  # type: ignore[attr-defined]
        client._client.stop = AsyncMock()  # type: ignore[attr-defined]

        await client.start()
        await client.stop()

        client._client.start.assert_awaited_once()  # type: ignore[attr-defined]
        client._client.stop.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_open_terminal_passes_columns_rows_and_extracts_id(self) -> None:
        """``open_terminal`` forwards size params and returns the terminal id."""
        client = McpretentiousClient()
        client._client.call_tool = AsyncMock(  # type: ignore[attr-defined]
            return_value={"terminal_id": "term-xyz"}
        )

        result = await client.open_terminal(columns=100, rows=30)

        assert result == "term-xyz"
        client._client.call_tool.assert_awaited_once_with(  # type: ignore[attr-defined]
            "mcpretentious-open", {"columns": 100, "rows": 30}
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "lines, expected_params",
        [
            (10, {"terminal_id": "term-1", "limit_lines": 10}),
            (None, {"terminal_id": "term-1"}),
        ],
    )
    async def test_read_text_shapes_params_and_returns_output(
        self, lines: int | None, expected_params: dict[str, Any]
    ) -> None:
        """``read_text`` only sends ``limit_lines`` when ``lines`` is set."""
        client = McpretentiousClient()
        client._client.call_tool = AsyncMock(  # type: ignore[attr-defined]
            return_value={"output": "data"}
        )

        result = await client.read_text("term-1", lines=lines)

        assert result == "data"
        client._client.call_tool.assert_awaited_once_with(  # type: ignore[attr-defined]
            "mcpretentious-read", expected_params
        )

    @pytest.mark.asyncio
    async def test_type_text_sends_input_list(self) -> None:
        """``type_text`` packages variadic parts as a JSON array."""
        client = McpretentiousClient()
        client._client.call_tool = AsyncMock()  # type: ignore[attr-defined]

        await client.type_text("term-1", "ls", " ", "/tmp", "enter")

        client._client.call_tool.assert_awaited_once_with(  # type: ignore[attr-defined]
            "mcpretentious-type",
            {"terminal_id": "term-1", "input": ["ls", " ", "/tmp", "enter"]},
        )

    @pytest.mark.asyncio
    async def test_close_terminal_forwards_id(self) -> None:
        """``close_terminal`` sends the close command with the terminal id."""
        client = McpretentiousClient()
        client._client.call_tool = AsyncMock()  # type: ignore[attr-defined]

        await client.close_terminal("term-1")

        client._client.call_tool.assert_awaited_once_with(  # type: ignore[attr-defined]
            "mcpretentious-close", {"terminal_id": "term-1"}
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "response, expected",
        [
            ({"terminals": [{"id": "a"}, {"id": "b"}]}, [{"id": "a"}, {"id": "b"}]),
            ({}, []),
        ],
    )
    async def test_list_terminals_returns_terminals_or_empty(
        self, response: dict[str, Any], expected: list[dict[str, Any]]
    ) -> None:
        """``list_terminals`` returns the ``terminals`` field, or ``[]`` if missing."""
        client = McpretentiousClient()
        client._client.call_tool = AsyncMock(return_value=response)  # type: ignore[attr-defined]

        result = await client.list_terminals()

        assert result == expected
        client._client.call_tool.assert_awaited_once_with(  # type: ignore[attr-defined]
            "mcpretentious-list", {}
        )
