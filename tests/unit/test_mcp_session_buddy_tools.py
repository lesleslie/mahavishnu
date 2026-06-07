"""Unit tests for mahavishnu.mcp.tools.session_buddy_tools.

The module decorates async functions with ``@server.tool()`` (where ``server``
is the first arg to ``register_session_buddy_tools``) at call time. Tests use
a ``_StubMCP`` with an ``app`` attribute to satisfy ``getattr(server, "app", None)``
and a mocked ``mcp_client`` for the delegated Session-Buddy calls.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.mcp.tools import session_buddy_tools as sbt
from mahavishnu.mcp.tools.session_buddy_tools import register_session_buddy_tools

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers
# =============================================================================


class _StubMCP:
    """Minimal FastMCP stand-in that also exposes an ``app`` attribute.

    The production tools do ``getattr(server, "app", None)`` to get the
    main MahavishnuApp, so we need both ``.tool()`` and ``.app``.
    """

    def __init__(self, app=None) -> None:
        self.tools: dict[str, object] = {}
        self.app = app

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _run(coro):
    return asyncio.run(coro)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fake_app() -> MagicMock:
    return MagicMock(name="app")


@pytest.fixture
def stub_mcp(fake_app) -> _StubMCP:
    return _StubMCP(app=fake_app)


@pytest.fixture
def fake_mcp_client() -> MagicMock:
    """MagicMock for the Session-Buddy MCP client used by the delegated tools."""
    client = MagicMock(name="mcp_client")
    client.call_tool = AsyncMock(return_value={"status": "ok"})
    return client


@pytest.fixture
def registered(stub_mcp, fake_mcp_client) -> _StubMCP:
    register_session_buddy_tools(
        stub_mcp,
        session_manager=MagicMock(),
        mcp_client=fake_mcp_client,
        rbac_manager=None,
    )
    return stub_mcp


# =============================================================================
# Module-level helpers
# =============================================================================


class TestCoercePriority:
    """_coerce_priority should lower-case and validate against MessagePriority.

    Valid MessagePriority values: low, normal, high, critical.
    """

    def test_lowercases_value(self):
        """Uppercase is normalised to lowercase before lookup."""
        result = sbt._coerce_priority("HIGH")
        assert result.value == "high"

    def test_already_lowercase(self):
        """Lowercase values pass through unchanged."""
        result = sbt._coerce_priority("low")
        assert result.value == "low"

    def test_critical_value(self):
        """CRITICAL is a valid priority."""
        result = sbt._coerce_priority("CRITICAL")
        assert result.value == "critical"

    def test_invalid_raises_value_error(self):
        """Unknown priorities raise ValueError from the enum constructor."""
        with pytest.raises(ValueError):
            sbt._coerce_priority("nonsense")

    def test_unknown_word_raises(self):
        """Even valid-looking words that aren't in the enum raise ValueError."""
        with pytest.raises(ValueError):
            sbt._coerce_priority("urgent")


# =============================================================================
# Index / find code / docs / functions tools (use server.app)
# =============================================================================


class TestCodeIntelTools:
    """The 5 code-intel tools (index_code_graph, get_function_context, etc.) all use server.app."""

    def test_index_code_graph_without_app(self):
        """Without an app on the server, the tool returns a known error.

        Note: the source does ``from ..session_buddy.integration import SessionBuddyManager``
        before checking ``getattr(server, 'app', None)``. In environments where that
        import fails (e.g. test env), the tool returns the catch-all
        ``{"status": "error", "error": "Failed to ...: <import error>"}`` shape. We
        only assert the documented contract: status='error'.
        """
        stub = _StubMCP(app=None)
        register_session_buddy_tools(stub, session_manager=MagicMock(), mcp_client=MagicMock())
        tool = stub.tools["index_code_graph"]
        result = _run(tool(user_id="test-user", project_path="/tmp/repo"))
        assert result["status"] == "error"

    def test_get_function_context_without_app(self):
        stub = _StubMCP(app=None)
        register_session_buddy_tools(stub, session_manager=MagicMock(), mcp_client=MagicMock())
        tool = stub.tools["get_function_context"]
        result = _run(tool(user_id="test-user", project_path="/tmp/repo", function_name="foo"))
        assert result["status"] == "error"

    def test_find_related_code_without_app(self):
        stub = _StubMCP(app=None)
        register_session_buddy_tools(stub, session_manager=MagicMock(), mcp_client=MagicMock())
        tool = stub.tools["find_related_code"]
        result = _run(tool(user_id="test-user", project_path="/tmp/repo", file_path="foo.py"))
        assert result["status"] == "error"

    def test_index_documentation_without_app(self):
        stub = _StubMCP(app=None)
        register_session_buddy_tools(stub, session_manager=MagicMock(), mcp_client=MagicMock())
        tool = stub.tools["index_documentation"]
        result = _run(tool(user_id="test-user", project_path="/tmp/repo"))
        assert result["status"] == "error"

    def test_search_documentation_without_app(self):
        stub = _StubMCP(app=None)
        register_session_buddy_tools(stub, session_manager=MagicMock(), mcp_client=MagicMock())
        tool = stub.tools["search_documentation"]
        result = _run(tool(user_id="test-user", query="find me docs"))
        assert result["status"] == "error"


# =============================================================================
# track_channel_session
# =============================================================================


class TestTrackChannelSession:
    """Tests for the track_channel_session tool (delegated to Session-Buddy)."""

    def test_sends_event_to_session_buddy(self, registered, fake_mcp_client):
        """Successful delegation returns success with the event_id echoed back."""
        tool = registered.tools["track_channel_session"]
        result = _run(
            tool(
                user_id="test-user",
                event_type="channel_session_start",
                channel_type="slack",
                channel_id="C123",
                sender_id="U1",
            )
        )
        assert result["status"] == "success"
        assert "event_id" in result
        assert result["result"] == {"status": "ok"}
        # mcp_client.call_tool was awaited once with the channel-session tool name
        fake_mcp_client.call_tool.assert_awaited_once()
        call = fake_mcp_client.call_tool.await_args
        assert call.args[0] == "mcp__session-buddy__track_channel_session"
        # Payload sanity
        payload = call.args[1]
        assert payload["event_type"] == "channel_session_start"
        assert payload["channel_id"] == "C123"
        assert payload["event_version"] == "2.0"
        assert "event_id" in payload
        assert "timestamp" in payload

    def test_invalid_event_type_returns_error(self, registered, fake_mcp_client):
        """Unknown event_type returns an error and does NOT call the upstream."""
        tool = registered.tools["track_channel_session"]
        result = _run(
            tool(
                user_id="test-user",
                event_type="bogus_event",
                channel_type="slack",
                channel_id="C123",
                sender_id="U1",
            )
        )
        assert result["status"] == "error"
        assert "Invalid event_type" in result["error"]
        fake_mcp_client.call_tool.assert_not_awaited()

    def test_invalid_session_scope_returns_error(self, registered, fake_mcp_client):
        """Unknown session_scope returns an error and does NOT call the upstream."""
        tool = registered.tools["track_channel_session"]
        result = _run(
            tool(
                user_id="test-user",
                event_type="channel_session_start",
                channel_type="slack",
                channel_id="C123",
                sender_id="U1",
                session_scope="week",
            )
        )
        assert result["status"] == "error"
        assert "Invalid session_scope" in result["error"]
        fake_mcp_client.call_tool.assert_not_awaited()

    def test_optional_fields_appear_only_when_set(self, registered, fake_mcp_client):
        """thread_id, workspace, platform, message_preview are only added when set."""
        tool = registered.tools["track_channel_session"]
        _run(
            tool(
                user_id="test-user",
                event_type="channel_heartbeat",
                channel_type="signal",
                channel_id="X1",
                sender_id="U2",
                thread_id="T-1",
                workspace="ws1",
                platform="macos",
                message_preview="hello",
            )
        )
        payload = fake_mcp_client.call_tool.await_args.args[1]
        assert payload["thread_id"] == "T-1"
        assert payload["workspace"] == "ws1"
        assert payload["platform"] == "macos"
        assert payload["message_preview"] == "hello"

    def test_message_preview_truncated_to_200(self, registered, fake_mcp_client):
        """A long message_preview is truncated before being sent."""
        tool = registered.tools["track_channel_session"]
        long_msg = "x" * 500
        _run(
            tool(
                user_id="test-user",
                event_type="channel_heartbeat",
                channel_type="signal",
                channel_id="X1",
                sender_id="U2",
                message_preview=long_msg,
            )
        )
        payload = fake_mcp_client.call_tool.await_args.args[1]
        assert len(payload["message_preview"]) == 200

    def test_upstream_exception_returns_error_with_event_id(self, registered, fake_mcp_client):
        """If the upstream Session-Buddy call raises, the tool returns an error and still echoes event_id."""
        fake_mcp_client.call_tool = AsyncMock(side_effect=RuntimeError("upstream down"))
        tool = registered.tools["track_channel_session"]
        result = _run(
            tool(
                user_id="test-user",
                event_type="channel_session_start",
                channel_type="slack",
                channel_id="C1",
                sender_id="U1",
            )
        )
        assert result["status"] == "error"
        assert "Session-Buddy call failed" in result["error"]
        assert "event_id" in result


# =============================================================================
# get_channel_sessions
# =============================================================================


class TestGetChannelSessions:
    """Tests for the get_channel_sessions tool (delegated query)."""

    def test_default_limit_20(self, registered, fake_mcp_client):
        """No filter arguments means just the limit=20 query is sent."""
        tool = registered.tools["get_channel_sessions"]
        result = _run(tool(user_id="test-user"))
        assert result["status"] == "success"
        fake_mcp_client.call_tool.assert_awaited_once()
        args = fake_mcp_client.call_tool.await_args
        assert args.args[0] == "mcp__session-buddy__get_channel_sessions"
        assert args.args[1] == {"limit": 20}

    def test_all_filters_forwarded(self, registered, fake_mcp_client):
        """All filter kwargs appear in the query dict when set."""
        tool = registered.tools["get_channel_sessions"]
        _run(
            tool(
                user_id="test-user",
                channel_type="slack",
                channel_id="C1",
                sender_id="U1",
                session_scope="thread",
                limit=50,
            )
        )
        query = fake_mcp_client.call_tool.await_args.args[1]
        assert query == {
            "limit": 50,
            "channel_type": "slack",
            "channel_id": "C1",
            "sender_id": "U1",
            "session_scope": "thread",
        }

    def test_limit_too_low(self, registered, fake_mcp_client):
        """limit=0 returns an error and does NOT call the upstream."""
        tool = registered.tools["get_channel_sessions"]
        result = _run(tool(user_id="test-user", limit=0))
        assert result["status"] == "error"
        assert "limit must be between 1 and 200" in result["error"]
        fake_mcp_client.call_tool.assert_not_awaited()

    def test_limit_too_high(self, registered, fake_mcp_client):
        """limit=201 returns an error."""
        tool = registered.tools["get_channel_sessions"]
        result = _run(tool(user_id="test-user", limit=201))
        assert result["status"] == "error"

    def test_invalid_session_scope(self, registered, fake_mcp_client):
        """session_scope outside the whitelist returns an error and does NOT call upstream."""
        tool = registered.tools["get_channel_sessions"]
        result = _run(tool(user_id="test-user", session_scope="month"))
        assert result["status"] == "error"
        assert "Invalid session_scope" in result["error"]
        fake_mcp_client.call_tool.assert_not_awaited()

    def test_upstream_exception(self, registered, fake_mcp_client):
        """Upstream errors are caught and returned in the standard shape."""
        fake_mcp_client.call_tool = AsyncMock(side_effect=RuntimeError("network"))
        tool = registered.tools["get_channel_sessions"]
        result = _run(tool(user_id="test-user"))
        assert result["status"] == "error"
        assert "Session-Buddy query failed" in result["error"]


# =============================================================================
# send_project_message
# =============================================================================


class TestSendProjectMessage:
    """Tests for the send_project_message tool."""

    def test_returns_error_without_app(self):
        """The tool returns status='error' when no app is on the server.

        See TestCodeIntelTools for the import-ordering caveat: the inner
        ``from ..session_buddy.integration import ...`` may fail before the
        ``if not app`` check, so we only assert the documented contract.
        """
        stub = _StubMCP(app=None)
        register_session_buddy_tools(stub, session_manager=MagicMock(), mcp_client=MagicMock())
        tool = stub.tools["send_project_message"]
        result = _run(
            tool(
                user_id="test-user",
                from_project="a",
                to_project="b",
                subject="hi",
                message="msg",
            )
        )
        assert result["status"] == "error"


# =============================================================================
# list_project_messages
# =============================================================================


class TestListProjectMessages:
    """Tests for the list_project_messages tool."""

    def test_returns_error_without_app(self):
        stub = _StubMCP(app=None)
        register_session_buddy_tools(stub, session_manager=MagicMock(), mcp_client=MagicMock())
        tool = stub.tools["list_project_messages"]
        result = _run(tool(user_id="test-user", project="myproj"))
        assert result["status"] == "error"
