"""Unit tests for ``mahavishnu.mcp.server_core``.

Covers the public surface:

* ``McpretentiousMCPClient.call_tool`` routing for each known tool name and
  the unknown-tool ``ValueError`` path, plus the lazy ``_ensure_started``
  behaviour and the inner-start ``RuntimeError`` propagation.
* ``FastMCPServer`` pure-logic helpers: ``_classify_tool_result`` and
  ``_update_registered_tool_metrics``.
* ``FastMCPServer`` delegating wrappers: ``start``, ``stop``,
  ``register_worktree_tools``.
* The ``run_server`` module-level entry point.

``FastMCPServer.__init__`` is not exercised here because it instantiates a
full ``MahavishnuApp`` and registers ~27 MCP tools — that is covered by the
existing integration suites. We construct bare instances via ``__new__`` and
inject only the attributes each test needs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.server_core import (
    FastMCPServer,
    McpretentiousMCPClient,
    run_server,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bare_server() -> FastMCPServer:
    """Build a ``FastMCPServer`` skipping ``__init__`` (no App wiring)."""
    return FastMCPServer.__new__(FastMCPServer)


@pytest.fixture
def mock_inner_client() -> AsyncMock:
    """Mock the underlying ``McpretentiousClient`` used by the wrapper."""
    client = AsyncMock()
    client.open_terminal = AsyncMock(return_value="term-xyz")
    client.type_text = AsyncMock(return_value=None)
    client.read_text = AsyncMock(return_value="hello world")
    client.close_terminal = AsyncMock(return_value=None)
    client.list_terminals = AsyncMock(return_value=[{"id": "t1"}])
    return client


@pytest.fixture
def mcp_client(mock_inner_client: AsyncMock) -> McpretentiousMCPClient:
    """Build a wrapper whose ``_client`` is a mock."""
    wrapper = McpretentiousMCPClient.__new__(McpretentiousMCPClient)
    wrapper._client = mock_inner_client
    wrapper._started = False
    return wrapper


# ---------------------------------------------------------------------------
# McpretentiousMCPClient
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.mcp
async def test_call_tool_open_returns_terminal_id(
    mcp_client: McpretentiousMCPClient,
    mock_inner_client: AsyncMock,
) -> None:
    """`mcpretentious-open` returns ``{"terminal_id": ...}`` from inner client."""
    result = await mcp_client.call_tool(
        "mcpretentious-open", {"columns": 120, "rows": 40}
    )

    assert result == {"terminal_id": "term-xyz"}
    mock_inner_client.open_terminal.assert_awaited_once_with(columns=120, rows=40)
    assert mcp_client._started is True


@pytest.mark.unit
@pytest.mark.mcp
async def test_call_tool_open_uses_defaults_when_missing(
    mcp_client: McpretentiousMCPClient,
    mock_inner_client: AsyncMock,
) -> None:
    """`mcpretentious-open` falls back to 80x24 when no size supplied."""
    await mcp_client.call_tool("mcpretentious-open", {})

    mock_inner_client.open_terminal.assert_awaited_once_with(columns=80, rows=24)


@pytest.mark.unit
@pytest.mark.mcp
async def test_call_tool_type_passes_text_segments(
    mcp_client: McpretentiousMCPClient,
    mock_inner_client: AsyncMock,
) -> None:
    """`mcpretentious-type` splats the ``input`` list as positional args."""
    result = await mcp_client.call_tool(
        "mcpretentious-type", {"terminal_id": "t1", "input": ["hello ", "world"]}
    )

    assert result == {}
    mock_inner_client.type_text.assert_awaited_once_with("t1", "hello ", "world")


@pytest.mark.unit
@pytest.mark.mcp
async def test_call_tool_read_returns_output_dict(
    mcp_client: McpretentiousMCPClient,
    mock_inner_client: AsyncMock,
) -> None:
    """`mcpretentious-read` returns ``{"output": <text>}``."""
    result = await mcp_client.call_tool(
        "mcpretentious-read", {"terminal_id": "t1", "limit_lines": 100}
    )

    assert result == {"output": "hello world"}
    mock_inner_client.read_text.assert_awaited_once_with("t1", lines=100)


@pytest.mark.unit
@pytest.mark.mcp
async def test_call_tool_read_omits_lines_when_unset(
    mcp_client: McpretentiousMCPClient,
    mock_inner_client: AsyncMock,
) -> None:
    """`mcpretentious-read` without ``limit_lines`` passes ``None``."""
    await mcp_client.call_tool("mcpretentious-read", {"terminal_id": "t1"})

    mock_inner_client.read_text.assert_awaited_once_with("t1", lines=None)


@pytest.mark.unit
@pytest.mark.mcp
async def test_call_tool_close_returns_empty_dict(
    mcp_client: McpretentiousMCPClient,
    mock_inner_client: AsyncMock,
) -> None:
    """`mcpretentious-close` returns ``{}`` after delegating close."""
    result = await mcp_client.call_tool("mcpretentious-close", {"terminal_id": "t1"})

    assert result == {}
    mock_inner_client.close_terminal.assert_awaited_once_with("t1")


@pytest.mark.unit
@pytest.mark.mcp
async def test_call_tool_list_returns_terminals_dict(
    mcp_client: McpretentiousMCPClient,
    mock_inner_client: AsyncMock,
) -> None:
    """`mcpretentious-list` returns ``{"terminals": [...]}``."""
    result = await mcp_client.call_tool("mcpretentious-list", {})

    assert result == {"terminals": [{"id": "t1"}]}
    mock_inner_client.list_terminals.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.mcp
async def test_call_tool_unknown_name_raises_value_error(
    mcp_client: McpretentiousMCPClient,
) -> None:
    """An unrecognised tool name raises ``ValueError`` naming the tool."""
    with pytest.raises(ValueError, match="Unknown tool: not-a-real-tool"):
        await mcp_client.call_tool("not-a-real-tool", {})


@pytest.mark.unit
@pytest.mark.mcp
async def test_ensure_started_only_starts_once(
    mcp_client: McpretentiousMCPClient,
    mock_inner_client: AsyncMock,
) -> None:
    """The inner ``start()`` is called at most once across multiple tool calls."""
    mock_inner_client.start = AsyncMock(return_value=None)

    await mcp_client.call_tool("mcpretentious-list", {})
    await mcp_client.call_tool("mcpretentious-close", {"terminal_id": "t1"})

    mock_inner_client.start.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.mcp
async def test_ensure_started_wraps_inner_failures(
    mock_inner_client: AsyncMock,
) -> None:
    """``_ensure_started`` raises ``RuntimeError`` when the inner start fails."""
    mock_inner_client.start = AsyncMock(side_effect=OSError("uvx not found"))
    wrapper = McpretentiousMCPClient.__new__(McpretentiousMCPClient)
    wrapper._client = mock_inner_client
    wrapper._started = False

    with pytest.raises(RuntimeError, match="Could not start mcpretentious"):
        await wrapper._ensure_started()

    assert wrapper._started is False


@pytest.mark.unit
@pytest.mark.mcp
async def test_call_tool_propagates_inner_errors(
    mcp_client: McpretentiousMCPClient,
    mock_inner_client: AsyncMock,
) -> None:
    """Errors from the inner client surface to the caller unchanged."""
    mock_inner_client.list_terminals = AsyncMock(
        side_effect=RuntimeError("server died")
    )

    with pytest.raises(RuntimeError, match="server died"):
        await mcp_client.call_tool("mcpretentious-list", {})


@pytest.mark.unit
@pytest.mark.mcp
async def test_wrapper_init_starts_unstarted() -> None:
    """A freshly constructed wrapper has ``_started`` False and the default client."""
    wrapper = McpretentiousMCPClient()
    assert wrapper._started is False
    assert wrapper._client is not None


# ---------------------------------------------------------------------------
# FastMCPServer — pure logic helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.mcp
def test_classify_tool_result_non_dict_is_success(bare_server: FastMCPServer) -> None:
    """Non-dict results are always classified as ``success``."""
    assert bare_server._classify_tool_result("ok") == "success"
    assert bare_server._classify_tool_result(42) == "success"
    assert bare_server._classify_tool_result(None) == "success"


@pytest.mark.unit
@pytest.mark.mcp
def test_classify_tool_result_dict_with_error_key(bare_server: FastMCPServer) -> None:
    """A dict carrying an ``error`` key maps to status ``error``."""
    assert bare_server._classify_tool_result({"error": "boom"}) == "error"
    assert bare_server._classify_tool_result({"error": None, "data": [1]}) == "success"
    # Falsy values (``None``, ``""``) for `error` do not flip status
    assert bare_server._classify_tool_result({"error": ""}) == "success"


@pytest.mark.unit
@pytest.mark.mcp
def test_classify_tool_result_dict_with_status_key(bare_server: FastMCPServer) -> None:
    """A known unhealthy ``status`` string maps to ``error``."""
    assert bare_server._classify_tool_result({"status": "error"}) == "error"
    assert bare_server._classify_tool_result({"status": "failed"}) == "error"
    assert bare_server._classify_tool_result({"status": "unhealthy"}) == "error"


@pytest.mark.unit
@pytest.mark.mcp
def test_classify_tool_result_case_insensitive_status(bare_server: FastMCPServer) -> None:
    """Status matching is case-insensitive."""
    assert bare_server._classify_tool_result({"status": "ERROR"}) == "error"
    assert bare_server._classify_tool_result({"status": "Failed"}) == "error"


@pytest.mark.unit
@pytest.mark.mcp
def test_classify_tool_result_dict_success(bare_server: FastMCPServer) -> None:
    """Plain result dicts are ``success``."""
    assert bare_server._classify_tool_result({"data": [1, 2]}) == "success"
    assert bare_server._classify_tool_result({"status": "ok"}) == "success"
    assert bare_server._classify_tool_result({}) == "success"


@pytest.mark.unit
@pytest.mark.mcp
def test_update_registered_tool_metrics_uses_configured_server_name(
    bare_server: FastMCPServer,
) -> None:
    """The gauge label comes from ``app.config.server_name`` when set."""
    bare_server.app = MagicMock()
    bare_server.app.config = MagicMock(server_name="custom-orchestrator")
    bare_server._registered_tool_count = 12

    with patch("mahavishnu.mcp.server_core.mcp_tools_registered") as mock_gauge:
        bare_server._update_registered_tool_metrics()

    mock_gauge.labels.assert_called_once_with(server="custom-orchestrator")
    mock_gauge.labels.return_value.set.assert_called_once_with(12)


@pytest.mark.unit
@pytest.mark.mcp
def test_update_registered_tool_metrics_falls_back_to_default(
    bare_server: FastMCPServer,
) -> None:
    """Missing or non-string ``server_name`` falls back to ``"mahavishnu"``."""
    bare_server.app = MagicMock()
    bare_server.app.config = MagicMock(spec=[])  # no server_name attribute
    bare_server._registered_tool_count = 0

    with patch("mahavishnu.mcp.server_core.mcp_tools_registered") as mock_gauge:
        bare_server._update_registered_tool_metrics()

    mock_gauge.labels.assert_called_once_with(server="mahavishnu")
    mock_gauge.labels.return_value.set.assert_called_once_with(0)


@pytest.mark.unit
@pytest.mark.mcp
def test_update_registered_tool_metrics_empty_string_name_falls_back(
    bare_server: FastMCPServer,
) -> None:
    """An empty ``server_name`` is replaced with the default ``"mahavishnu"``."""
    bare_server.app = MagicMock()
    bare_server.app.config = MagicMock(server_name="")
    bare_server._registered_tool_count = 3

    with patch("mahavishnu.mcp.server_core.mcp_tools_registered") as mock_gauge:
        bare_server._update_registered_tool_metrics()

    mock_gauge.labels.assert_called_once_with(server="mahavishnu")


# ---------------------------------------------------------------------------
# FastMCPServer — delegating wrappers
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.mcp
async def test_start_delegates_to_helper_with_defaults(
    bare_server: FastMCPServer,
) -> None:
    """``start()`` forwards to the lifecycle helper with default host/port."""
    fake_helper = AsyncMock()
    bare_server.app = MagicMock()

    with patch(
        "mahavishnu.mcp.server_core._start_server_helper", fake_helper
    ) as helper:
        await bare_server.start()

    helper.assert_awaited_once_with(bare_server, host="127.0.0.1", port=3000)


@pytest.mark.unit
@pytest.mark.mcp
async def test_start_passes_custom_host_and_port(bare_server: FastMCPServer) -> None:
    """``start()`` forwards custom host/port to the lifecycle helper."""
    fake_helper = AsyncMock()
    bare_server.app = MagicMock()

    with patch(
        "mahavishnu.mcp.server_core._start_server_helper", fake_helper
    ) as helper:
        await bare_server.start(host="0.0.0.0", port=9001)

    helper.assert_awaited_once_with(bare_server, host="0.0.0.0", port=9001)


@pytest.mark.unit
@pytest.mark.mcp
async def test_stop_delegates_to_helper(bare_server: FastMCPServer) -> None:
    """``stop()`` awaits the lifecycle stop helper with ``self`` only."""
    fake_helper = AsyncMock()
    bare_server.app = MagicMock()

    with patch(
        "mahavishnu.mcp.server_core._stop_server_helper", fake_helper
    ) as helper:
        await bare_server.stop()

    helper.assert_awaited_once_with(bare_server)


@pytest.mark.unit
@pytest.mark.mcp
async def test_register_worktree_tools_delegates_to_helper(
    bare_server: FastMCPServer,
) -> None:
    """``register_worktree_tools()`` awaits the worktree helper with ``self`` only."""
    fake_helper = AsyncMock()
    bare_server.app = MagicMock()

    with patch(
        "mahavishnu.mcp.server_core._register_worktree_tools_helper", fake_helper
    ) as helper:
        await bare_server.register_worktree_tools()

    helper.assert_awaited_once_with(bare_server)


# ---------------------------------------------------------------------------
# Module-level entry point
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.mcp
async def test_run_server_builds_server_then_starts() -> None:
    """``run_server`` instantiates ``FastMCPServer`` and calls ``start()``."""
    fake_server = MagicMock()
    fake_server.start = AsyncMock()
    fake_init = MagicMock(return_value=fake_server)

    with patch("mahavishnu.mcp.server_core.FastMCPServer", fake_init):
        await run_server(config="some-config")

    fake_init.assert_called_once_with("some-config")
    fake_server.start.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.mcp
async def test_run_server_passes_none_config_by_default() -> None:
    """``run_server`` with no argument forwards ``None`` as the config."""
    fake_server = MagicMock()
    fake_server.start = AsyncMock()
    fake_init = MagicMock(return_value=fake_server)

    with patch("mahavishnu.mcp.server_core.FastMCPServer", fake_init):
        await run_server()

    fake_init.assert_called_once_with(None)
    fake_server.start.assert_awaited_once_with()
