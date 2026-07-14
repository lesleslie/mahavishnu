"""Unit tests for ``mahavishnu.terminal.adapters.mcpretentious.McpretentiousAdapter``.

The adapter wraps an MCP client. These tests inject an ``AsyncMock`` MCP
client to exercise every public method and error path.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mahavishnu.terminal.adapters.base import TerminalAdapter
from mahavishnu.terminal.adapters.mcpretentious import (
    McpretentiousAdapter,
    SessionNotFoundError,
    TerminalError,
)
from mahavishnu.terminal.backends import BUILTIN_BACKENDS, PtyBackend

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mcp_client() -> AsyncMock:
    """A mock MCP client whose call_tool returns a dict with terminal_id."""
    client = AsyncMock()
    client.call_tool = AsyncMock()
    return client


@pytest.fixture
def adapter(mcp_client: AsyncMock) -> McpretentiousAdapter:
    return McpretentiousAdapter(mcp_client=mcp_client)


# =============================================================================
# Construction & Interface Tests
# =============================================================================


class TestConstruction:
    """Construction and base class integration tests."""

    def test_is_terminal_adapter(self, adapter: McpretentiousAdapter):
        assert isinstance(adapter, TerminalAdapter)

    def test_adapter_name(self, adapter: McpretentiousAdapter):
        assert adapter.adapter_name == "mcpretentious"

    def test_stores_mcp_client(self, mcp_client: AsyncMock):
        a = McpretentiousAdapter(mcp_client=mcp_client)
        assert a.mcp is mcp_client

    def test_initial_sessions_empty(self, adapter: McpretentiousAdapter):
        assert adapter._sessions == {}


# =============================================================================
# Launch Session Tests
# =============================================================================


class TestLaunchSession:
    """Tests for launch_session and the underlying mcpretentious-open call."""

    async def test_launch_returns_terminal_id(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {"terminal_id": "abc"}
        sid = await adapter.launch_session("qwen", columns=80, rows=24)
        assert sid == "abc"
        # Two calls: open and the initial send_command ("qwen" + "enter")
        assert mcp_client.call_tool.await_count == 2
        # First call: open
        first_call = mcp_client.call_tool.await_args_list[0]
        assert first_call.args[0] == "mcpretentious-open"
        assert first_call.args[1] == {"columns": 80, "rows": 24}

    async def test_launch_stores_session_metadata(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {"terminal_id": "xyz"}
        sid = await adapter.launch_session("qwen", columns=120, rows=40)
        info = adapter._sessions[sid]
        assert info["command"] == "qwen"
        assert info["columns"] == 120
        assert info["rows"] == 40
        assert "created_at" in info

    async def test_launch_initial_command_is_sent(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {"terminal_id": "t1"}
        await adapter.launch_session("qwen")
        # Second call: type with the initial command + enter
        second_call = mcp_client.call_tool.await_args_list[1]
        assert second_call.args[0] == "mcpretentious-type"
        assert second_call.args[1] == {
            "terminal_id": "t1",
            "input": ["qwen", "enter"],
        }

    async def test_launch_wraps_mcp_exception(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.side_effect = RuntimeError("boom")
        with pytest.raises(TerminalError, match="Failed to launch session"):
            await adapter.launch_session("qwen")

    async def test_launch_failure_does_not_register_session(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.side_effect = RuntimeError("boom")
        try:
            await adapter.launch_session("qwen")
        except TerminalError:
            pass
        assert adapter._sessions == {}


# =============================================================================
# Send Command Tests
# =============================================================================


class TestSendCommand:
    """Tests for send_command and the underlying mcpretentious-type call."""

    async def test_send_to_known_session(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {"terminal_id": "t1"}
        await adapter.launch_session("qwen")
        # Reset to track the next call cleanly
        mcp_client.call_tool.reset_mock()
        mcp_client.call_tool.return_value = None

        await adapter.send_command("t1", "ls -la")

        mcp_client.call_tool.assert_awaited_once_with(
            "mcpretentious-type",
            {
                "terminal_id": "t1",
                "input": ["ls -la", "enter"],
            },
        )

    async def test_send_to_unknown_session_raises_session_not_found(
        self,
        adapter: McpretentiousAdapter,
    ):
        with pytest.raises(SessionNotFoundError, match="not found"):
            await adapter.send_command("nope", "ls")

    async def test_send_wraps_mcp_exception(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {"terminal_id": "t1"}
        await adapter.launch_session("qwen")
        mcp_client.call_tool.side_effect = RuntimeError("boom")
        with pytest.raises(TerminalError, match="Failed to send command"):
            await adapter.send_command("t1", "ls")


# =============================================================================
# Capture Output Tests
# =============================================================================


class TestCaptureOutput:
    """Tests for capture_output and the underlying mcpretentious-read call."""

    async def test_capture_full_output(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {"terminal_id": "t1"}
        await adapter.launch_session("qwen")

        # Reset to track the next call
        mcp_client.call_tool.reset_mock()
        mcp_client.call_tool.return_value = {"output": "hello world"}

        result = await adapter.capture_output("t1")
        assert result == "hello world"

    async def test_capture_with_lines_limit(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {"terminal_id": "t1"}
        await adapter.launch_session("qwen")

        mcp_client.call_tool.reset_mock()
        mcp_client.call_tool.return_value = {"output": "last lines"}

        await adapter.capture_output("t1", lines=50)
        mcp_client.call_tool.assert_awaited_once_with(
            "mcpretentious-read",
            {"terminal_id": "t1", "limit_lines": 50},
        )

    async def test_capture_without_lines_omits_limit(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {"terminal_id": "t1"}
        await adapter.launch_session("qwen")

        mcp_client.call_tool.reset_mock()
        mcp_client.call_tool.return_value = {"output": "all output"}

        await adapter.capture_output("t1")
        mcp_client.call_tool.assert_awaited_once_with(
            "mcpretentious-read",
            {"terminal_id": "t1"},
        )

    async def test_capture_unknown_session_raises(
        self,
        adapter: McpretentiousAdapter,
    ):
        with pytest.raises(SessionNotFoundError, match="not found"):
            await adapter.capture_output("nope")

    async def test_capture_wraps_mcp_exception(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {"terminal_id": "t1"}
        await adapter.launch_session("qwen")
        mcp_client.call_tool.side_effect = RuntimeError("boom")
        with pytest.raises(TerminalError, match="Failed to capture output"):
            await adapter.capture_output("t1", lines=10)


# =============================================================================
# Close Session Tests
# =============================================================================


class TestCloseSession:
    """Tests for close_session, including the always-remove local metadata path."""

    async def test_close_known_session(
        self,
        adapter: McpretentiousAdapter if False else McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {"terminal_id": "t1"}
        await adapter.launch_session("qwen")
        mcp_client.call_tool.reset_mock()
        mcp_client.call_tool.return_value = None

        await adapter.close_session("t1")

        mcp_client.call_tool.assert_awaited_once_with(
            "mcpretentious-close",
            {"terminal_id": "t1"},
        )
        # Local metadata removed even on success
        assert "t1" not in adapter._sessions

    async def test_close_unknown_session_calls_mcp_anyway(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = None
        # The current implementation calls call_tool even for unknown ids
        await adapter.close_session("ghost")
        mcp_client.call_tool.assert_awaited_once_with(
            "mcpretentious-close",
            {"terminal_id": "ghost"},
        )

    async def test_close_always_removes_metadata_even_on_error(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {"terminal_id": "t1"}
        await adapter.launch_session("qwen")

        mcp_client.call_tool.side_effect = RuntimeError("boom")
        with pytest.raises(TerminalError, match="Failed to close session"):
            await adapter.close_session("t1")

        assert "t1" not in adapter._sessions


# =============================================================================
# List Sessions Tests
# =============================================================================


class TestListSessions:
    """Tests for list_sessions and the underlying mcpretentious-list call."""

    async def test_list_returns_terminals(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {
            "terminals": [{"id": "t1"}, {"id": "t2"}],
        }
        result = await adapter.list_sessions()
        assert result == [{"id": "t1"}, {"id": "t2"}]
        mcp_client.call_tool.assert_awaited_once_with("mcpretentious-list", {})

    async def test_list_handles_missing_key(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.return_value = {}
        result = await adapter.list_sessions()
        assert result == []

    async def test_list_wraps_mcp_exception(
        self,
        adapter: McpretentiousAdapter,
        mcp_client: AsyncMock,
    ):
        mcp_client.call_tool.side_effect = RuntimeError("boom")
        with pytest.raises(TerminalError, match="Failed to list sessions"):
            await adapter.list_sessions()


# =============================================================================
# Exception Class Tests
# =============================================================================


class TestExceptionClasses:
    """Tests for TerminalError and SessionNotFoundError."""

    def test_session_not_found_is_terminal_error(self):
        e = SessionNotFoundError("nope")
        assert isinstance(e, TerminalError)
        assert "nope" in str(e)

    def test_terminal_error_with_details(self):
        e = TerminalError("boom", details={"k": "v"})
        assert "boom" in str(e)
        assert e.details == {"k": "v"}


# =============================================================================
# Tool-name resolution (BUILTIN_BACKENDS.tool_map contract)
# =============================================================================


class TestToolForResolution:
    """Tests for ``_tool_for`` — backend-specific MCP tool name resolution.

    The contract: when a backend has a ``tool_map`` populated in
    ``BUILTIN_BACKENDS``, every generic operation (``open`` / ``type`` /
    ``read`` / ``close`` / ``list``) must resolve to the mapped name.
    Backends without a ``tool_map`` keep the literal ``mcpretentious-{op}``
    name (back-compat for the default surface).
    """

    def test_default_backend_uses_mcpretentious_prefix(self, mcp_client: AsyncMock) -> None:
        """``backend_name='mcpretentious'`` (empty tool_map) keeps the literal names."""
        adapter = McpretentiousAdapter(mcp_client=mcp_client, backend_name="mcpretentious")

        assert adapter._tool_for("open") == "mcpretentious-open"
        assert adapter._tool_for("type") == "mcpretentious-type"
        assert adapter._tool_for("read") == "mcpretentious-read"
        assert adapter._tool_for("close") == "mcpretentious-close"
        assert adapter._tool_for("list") == "mcpretentious-list"

    def test_no_backend_name_uses_mcpretentious_prefix(
        self, mcp_client: AsyncMock
    ) -> None:
        """``backend_name=None`` falls back to the literal ``mcpretentious-{op}`` names."""
        adapter = McpretentiousAdapter(mcp_client=mcp_client, backend_name=None)

        assert adapter._tool_for("open") == "mcpretentious-open"

    def test_unknown_backend_name_uses_mcpretentious_prefix(
        self, mcp_client: AsyncMock
    ) -> None:
        """A backend name not in ``BUILTIN_BACKENDS`` falls back to the literal names."""
        adapter = McpretentiousAdapter(
            mcp_client=mcp_client, backend_name="not_a_registered_backend"
        )

        assert adapter._tool_for("open") == "mcpretentious-open"

    def test_tool_map_overrides_open(
        self, mcp_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``tool_map={"open": "custom_open"}`` redirects the open call."""
        monkeypatch.setitem(
            BUILTIN_BACKENDS,
            "custom_backend",
            PtyBackend(
                name="custom_backend",
                command="custom-launcher",
                args=(),
                tool_map={"open": "custom_open"},
                requires=(),
            ),
        )
        try:
            adapter = McpretentiousAdapter(
                mcp_client=mcp_client, backend_name="custom_backend"
            )
            assert adapter._tool_for("open") == "custom_open"
        finally:
            monkeypatch.delitem(BUILTIN_BACKENDS, "custom_backend")

    async def test_launch_session_uses_mapped_tool_name(
        self, mcp_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: ``launch_session`` must call the mapped ``open`` tool,
        not ``mcpretentious-open``, when the backend's ``tool_map`` aliases it.
        """
        monkeypatch.setitem(
            BUILTIN_BACKENDS,
            "custom_backend",
            PtyBackend(
                name="custom_backend",
                command="custom-launcher",
                args=(),
                tool_map={"open": "custom_open", "type": "custom_type"},
                requires=(),
            ),
        )
        try:
            mcp_client.call_tool.return_value = {"terminal_id": "abc"}
            adapter = McpretentiousAdapter(
                mcp_client=mcp_client, backend_name="custom_backend"
            )
            await adapter.launch_session("qwen", columns=80, rows=24)
            # First call must use the mapped "open" tool name.
            first_call = mcp_client.call_tool.await_args_list[0]
            assert first_call.args[0] == "custom_open"
            # Second call (the initial "qwen" + enter via send_command) uses the mapped "type" tool.
            second_call = mcp_client.call_tool.await_args_list[1]
            assert second_call.args[0] == "custom_type"
        finally:
            monkeypatch.delitem(BUILTIN_BACKENDS, "custom_backend")
