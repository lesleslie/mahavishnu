"""Unit tests for track_channel_session and get_channel_sessions MCP tools.

Tests cover create / query / close lifecycle, input validation, mcp_client delegation,
and error handling — all without a live Session-Buddy connection.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_server_and_client():
    """Build minimal server+mcp_client mocks and register the SB tools.

    Returns a ``tools`` dict whose callables have ``user_id`` pre-injected so
    tests don't need to carry authentication boilerplate everywhere.
    """
    registered: dict[str, object] = {}

    server = MagicMock()

    def tool_decorator():
        def outer(fn):
            registered[fn.__name__] = fn
            return fn

        return outer

    server.tool = tool_decorator

    mcp_client = MagicMock()
    mcp_client.call_tool = AsyncMock(return_value={"ok": True})

    from mahavishnu.mcp.tools.session_buddy_tools import register_session_buddy_tools

    register_session_buddy_tools(server, session_manager=None, mcp_client=mcp_client)

    # Wrap each registered function so tests don't need to pass user_id every time.
    authed: dict[str, object] = {}
    for name, fn in registered.items():
        async def _authed(fn=fn, **kwargs):
            kwargs.setdefault("user_id", "test-user")
            return await fn(**kwargs)

        authed[name] = _authed

    return authed, mcp_client


@pytest.fixture
def tools_and_client():
    return _make_server_and_client()


class TestTrackChannelSession:
    @pytest.mark.asyncio
    async def test_session_start_delegates_to_session_buddy(self, tools_and_client):
        tools, client = tools_and_client
        fn = tools["track_channel_session"]

        result = await fn(
            event_type="channel_session_start",
            channel_type="slack",
            channel_id="D0AR18B4WUU",
            sender_id="U01234ABCD",
        )

        assert result["status"] == "success"
        assert "event_id" in result
        client.call_tool.assert_awaited_once()
        call_args = client.call_tool.call_args
        assert call_args[0][0] == "mcp__session-buddy__track_channel_session"
        payload = call_args[0][1]
        assert payload["event_type"] == "channel_session_start"
        assert payload["channel_type"] == "slack"
        assert payload["event_version"] == "2.0"

    @pytest.mark.asyncio
    async def test_session_end_passes_channel_fields(self, tools_and_client):
        tools, client = tools_and_client
        fn = tools["track_channel_session"]

        result = await fn(
            event_type="channel_session_end",
            channel_type="signal",
            channel_id="signal-group-123",
            sender_id="user@example.com",
            session_scope="day",
        )

        assert result["status"] == "success"
        payload = client.call_tool.call_args[0][1]
        assert payload["session_scope"] == "day"
        assert payload["event_type"] == "channel_session_end"

    @pytest.mark.asyncio
    async def test_heartbeat_includes_message_preview(self, tools_and_client):
        tools, client = tools_and_client
        fn = tools["track_channel_session"]

        long_message = "x" * 300
        await fn(
            event_type="channel_heartbeat",
            channel_type="slack",
            channel_id="C01234ABCD",
            sender_id="U01234ABCD",
            message_preview=long_message,
        )

        payload = client.call_tool.call_args[0][1]
        assert len(payload["message_preview"]) == 200  # truncated

    @pytest.mark.asyncio
    async def test_invalid_event_type_rejected(self, tools_and_client):
        tools, _ = tools_and_client
        fn = tools["track_channel_session"]

        result = await fn(
            event_type="bad_event",
            channel_type="slack",
            channel_id="C01",
            sender_id="U01",
        )

        assert result["status"] == "error"
        assert "event_type" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_scope_rejected(self, tools_and_client):
        tools, _ = tools_and_client
        fn = tools["track_channel_session"]

        result = await fn(
            event_type="channel_session_start",
            channel_type="slack",
            channel_id="C01",
            sender_id="U01",
            session_scope="unknown_scope",
        )

        assert result["status"] == "error"
        assert "session_scope" in result["error"]

    @pytest.mark.asyncio
    async def test_mcp_client_error_returns_error_status(self, tools_and_client):
        tools, client = tools_and_client
        client.call_tool = AsyncMock(side_effect=RuntimeError("Session-Buddy unreachable"))
        fn = tools["track_channel_session"]

        result = await fn(
            event_type="channel_session_start",
            channel_type="slack",
            channel_id="C01",
            sender_id="U01",
        )

        assert result["status"] == "error"
        assert "Session-Buddy" in result["error"]
        assert "event_id" in result  # preserved even on error

    @pytest.mark.asyncio
    async def test_thread_id_included_when_provided(self, tools_and_client):
        tools, client = tools_and_client
        fn = tools["track_channel_session"]

        await fn(
            event_type="channel_session_start",
            channel_type="slack",
            channel_id="C01",
            sender_id="U01",
            session_scope="thread",
            thread_id="1234567890.123456",
        )

        payload = client.call_tool.call_args[0][1]
        assert payload["thread_id"] == "1234567890.123456"

    @pytest.mark.asyncio
    async def test_optional_fields_omitted_when_none(self, tools_and_client):
        tools, client = tools_and_client
        fn = tools["track_channel_session"]

        await fn(
            event_type="channel_session_start",
            channel_type="slack",
            channel_id="C01",
            sender_id="U01",
        )

        payload = client.call_tool.call_args[0][1]
        assert "thread_id" not in payload
        assert "workspace" not in payload
        assert "platform" not in payload
        assert "message_preview" not in payload


class TestGetChannelSessions:
    @pytest.mark.asyncio
    async def test_query_delegates_to_session_buddy(self, tools_and_client):
        tools, client = tools_and_client
        fn = tools["get_channel_sessions"]

        result = await fn(channel_type="slack", limit=10)

        assert result["status"] == "success"
        client.call_tool.assert_awaited_once()
        call_args = client.call_tool.call_args
        assert call_args[0][0] == "mcp__session-buddy__get_channel_sessions"
        assert call_args[0][1]["channel_type"] == "slack"
        assert call_args[0][1]["limit"] == 10

    @pytest.mark.asyncio
    async def test_query_with_no_filters(self, tools_and_client):
        tools, client = tools_and_client
        fn = tools["get_channel_sessions"]

        result = await fn()

        assert result["status"] == "success"
        payload = client.call_tool.call_args[0][1]
        assert payload == {"limit": 20}

    @pytest.mark.asyncio
    async def test_invalid_limit_rejected(self, tools_and_client):
        tools, _ = tools_and_client
        fn = tools["get_channel_sessions"]

        result = await fn(limit=0)
        assert result["status"] == "error"
        assert "limit" in result["error"]

        result = await fn(limit=500)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_invalid_scope_in_query_rejected(self, tools_and_client):
        tools, _ = tools_and_client
        fn = tools["get_channel_sessions"]

        result = await fn(session_scope="bad_scope")
        assert result["status"] == "error"
        assert "session_scope" in result["error"]

    @pytest.mark.asyncio
    async def test_mcp_client_error_returns_error(self, tools_and_client):
        tools, client = tools_and_client
        client.call_tool = AsyncMock(side_effect=RuntimeError("timeout"))
        fn = tools["get_channel_sessions"]

        result = await fn()
        assert result["status"] == "error"
        assert "timeout" in result["error"]
