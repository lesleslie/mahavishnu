"""Unit tests for mahavishnu/websocket/server.py.

Covers the MahavishnuWebSocketServer: construction, on_connect, on_disconnect,
on_message (including rate-limit handling), subscribe/unsubscribe flows,
pool/workflow status lookups, channel permission checks, the
handle_event_envelope bridge, leave_all_rooms, and all broadcast helpers.

The base class is mocked at the module boundary so no real sockets are
opened and the tests are fully deterministic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from mcp_common.websocket import MessageType, WebSocketMessage, WebSocketProtocol
from mcp_common.websocket.protocol import EventTypes
import pytest

# =============================================================================
# Module-level Patches & Helpers
# =============================================================================


@pytest.fixture(autouse=True)
def _patch_metrics():
    """Replace get_metrics() so the constructor does not touch Prometheus.

    The metrics collector is replaced with a MagicMock that supports
    adjust_connections / inc_error / etc.
    """
    fake_metrics = MagicMock(name="metrics")
    fake_metrics.adjust_connections = MagicMock()
    fake_metrics.inc_error = MagicMock()
    with patch("mahavishnu.websocket.server.get_metrics", return_value=fake_metrics):
        yield fake_metrics


@pytest.fixture(autouse=True)
def _patch_authenticator():
    """Replace the authenticator factory with a no-op."""
    with patch("mahavishnu.websocket.server.get_authenticator", return_value=None):
        yield


@pytest.fixture
def mock_pool_manager():
    """MagicMock standing in for a PoolManager."""
    pool = MagicMock()
    pool.status = "running"
    pool.workers = ["w1", "w2"]
    mgr = MagicMock()
    mgr.pools = {"pool-1": pool}
    return mgr


def _make_websocket(user=None):
    """Build a MagicMock websocket with optional user dict on it."""
    ws = MagicMock(name="websocket")
    ws.send = AsyncMock()
    if user is not None:
        ws.user = user  # type: ignore[attr-defined]
    return ws


# =============================================================================
# Import & Construction Tests
# =============================================================================


class TestMahavishnuWebSocketServerImport:
    """Smoke import test for the module."""

    def test_module_imports(self):
        """The server module imports without side effects."""
        import mahavishnu.websocket.server as srv  # noqa: F401

        assert hasattr(srv, "MahavishnuWebSocketServer")
        assert hasattr(srv, "_get_explicit_attribute")


class TestMahavishnuWebSocketServerConstruction:
    """Tests for the constructor."""

    def test_default_construction(self, mock_pool_manager):
        """Defaults populate all expected attributes."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        assert server.pool_manager is mock_pool_manager
        assert server.host == "127.0.0.1"
        assert server.port == 8690
        assert server.max_connections == 1000
        # The rate limiter should be a TokenBucketRateLimiter at message_rate_limit
        from mahavishnu.websocket.rate_limiter import TokenBucketRateLimiter

        assert isinstance(server.rate_limiter, TokenBucketRateLimiter)
        assert server.rate_limiter.rate == 100.0
        # burst is 1.5x rate
        assert server.rate_limiter.burst_size == 150.0
        # Internal connection tracking
        assert server._connection_ids == {}
        assert server._event_bridge is not None

    def test_custom_message_rate_limit_sets_burst_size(self, mock_pool_manager):
        """A custom message_rate_limit is reflected in the rate limiter."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager, message_rate_limit=50)

        assert server.rate_limiter.rate == 50.0
        assert server.rate_limiter.burst_size == 75.0

    def test_tls_enabled_warns_on_non_localhost(self, mock_pool_manager, caplog):
        """Binding a non-loopback host without TLS logs a security warning."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        with caplog.at_level("WARNING"):
            MahavishnuWebSocketServer(
                pool_manager=mock_pool_manager,
                host="0.0.0.0",
                tls_enabled=False,
            )

        assert any("SECURITY WARNING" in m for m in caplog.messages)

    def test_tls_disabled_on_localhost_does_not_warn(self, mock_pool_manager, caplog):
        """Binding 127.0.0.1 without TLS does NOT log a security warning."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        with caplog.at_level("WARNING"):
            MahavishnuWebSocketServer(
                pool_manager=mock_pool_manager,
                host="127.0.0.1",
                tls_enabled=False,
            )

        assert not any("SECURITY WARNING" in m for m in caplog.messages)


# =============================================================================
# on_connect() Tests
# =============================================================================


class TestOnConnect:
    """Tests for the on_connect lifecycle hook."""

    @pytest.mark.asyncio
    async def test_on_connect_registers_connection_id(self, mock_pool_manager):
        """on_connect stores the connection_id in _connection_ids."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()

        await server.on_connect(ws, "conn-1")

        assert server._connection_ids[ws] == "conn-1"

    @pytest.mark.asyncio
    async def test_on_connect_sends_welcome_message(self, mock_pool_manager):
        """on_connect sends a SESSION_CREATED welcome to the client."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()

        await server.on_connect(ws, "conn-1")

        ws.send.assert_awaited_once()
        sent = ws.send.await_args.args[0]
        # Decode the welcome
        msg = WebSocketProtocol.decode(sent)
        assert msg.event == EventTypes.SESSION_CREATED
        assert msg.data["connection_id"] == "conn-1"
        assert msg.data["server"] == "mahavishnu"
        assert msg.data["authenticated"] is False
        assert msg.data["secure"] is False
        assert msg.data["rate_limit"] == server.message_rate_limit

    @pytest.mark.asyncio
    async def test_on_connect_marks_user_authenticated(self, mock_pool_manager):
        """If a user dict is attached, the welcome marks authenticated=True."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket(user={"user_id": "alice"})

        await server.on_connect(ws, "conn-1")

        sent = ws.send.await_args.args[0]
        msg = WebSocketProtocol.decode(sent)
        assert msg.data["authenticated"] is True

    @pytest.mark.asyncio
    async def test_on_connect_handles_sync_send(self, mock_pool_manager):
        """If send() returns a non-awaitable, no exception is raised."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = MagicMock()
        ws.send = MagicMock(return_value=None)  # sync, not awaitable
        ws.user = None  # type: ignore[attr-defined]

        # Should not raise
        await server.on_connect(ws, "conn-1")
        ws.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_connect_increments_metric(self, mock_pool_manager, _patch_metrics):
        """on_connect calls metrics.adjust_connections(1)."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()

        await server.on_connect(ws, "conn-1")

        _patch_metrics.adjust_connections.assert_called_with(1)


# =============================================================================
# on_disconnect() Tests
# =============================================================================


class TestOnDisconnect:
    """Tests for the on_disconnect lifecycle hook."""

    @pytest.mark.asyncio
    async def test_on_disconnect_removes_connection(self, mock_pool_manager):
        """on_disconnect cleans up _connection_ids, connections, and rate bucket."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        # Seed an entry in self.connections
        server.connections["conn-1"] = ws

        await server.on_disconnect(ws, "conn-1")

        assert ws not in server._connection_ids
        assert "conn-1" not in server.connections

    @pytest.mark.asyncio
    async def test_on_disconnect_calls_leave_all_rooms(self, mock_pool_manager):
        """on_disconnect removes the connection from all subscribed rooms."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        with patch.object(server, "leave_all_rooms", new=AsyncMock()) as leave:
            await server.on_disconnect(ws, "conn-1")

        leave.assert_awaited_once_with("conn-1")

    @pytest.mark.asyncio
    async def test_on_disconnect_decrements_metric(self, mock_pool_manager, _patch_metrics):
        """on_disconnect calls metrics.adjust_connections(-1)."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        await server.on_disconnect(ws, "conn-1")

        _patch_metrics.adjust_connections.assert_called_with(-1)

    @pytest.mark.asyncio
    async def test_on_disconnect_handles_unknown_websocket(self, mock_pool_manager):
        """on_disconnect for an unknown websocket does not raise."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()

        # Should not raise
        await server.on_disconnect(ws, "ghost")


# =============================================================================
# _can_subscribe_to_channel() Tests
# =============================================================================


class TestChannelPermissions:
    """Tests for the per-channel permission check."""

    @pytest.fixture
    def server(self, mock_pool_manager):
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        return MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

    def test_admin_can_subscribe_to_any_channel(self, server):
        """A user with 'admin' permission passes every check."""
        user = {"user_id": "root", "permissions": ["admin"]}

        assert server._can_subscribe_to_channel(user, "workflow:abc") is True
        assert server._can_subscribe_to_channel(user, "pool:p1") is True
        assert server._can_subscribe_to_channel(user, "worker:w1") is True
        assert server._can_subscribe_to_channel(user, "goal-teams") is True

    def test_workflow_channel_requires_workflow_read(self, server):
        """workflow:* channels need 'workflow:read' permission."""
        user = {"permissions": ["workflow:read"]}
        assert server._can_subscribe_to_channel(user, "workflow:abc") is True

        user = {"permissions": []}
        assert server._can_subscribe_to_channel(user, "workflow:abc") is False

    def test_pool_channel_requires_pool_read(self, server):
        """pool:* channels need 'pool:read' permission."""
        user = {"permissions": ["pool:read"]}
        assert server._can_subscribe_to_channel(user, "pool:p1") is True

        user = {"permissions": []}
        assert server._can_subscribe_to_channel(user, "pool:p1") is False

    def test_worker_channel_requires_worker_read(self, server):
        """worker:* channels need 'worker:read' permission."""
        user = {"permissions": ["worker:read"]}
        assert server._can_subscribe_to_channel(user, "worker:w1") is True

        user = {"permissions": []}
        assert server._can_subscribe_to_channel(user, "worker:w1") is False

    def test_goal_teams_channel_requires_team_read(self, server):
        """goal-teams channels need 'team:read' permission."""
        user = {"permissions": ["team:read"]}
        assert server._can_subscribe_to_channel(user, "goal-teams") is True
        assert server._can_subscribe_to_channel(user, "goal-teams:u1") is True

        user = {"permissions": []}
        assert server._can_subscribe_to_channel(user, "goal-teams") is False

    def test_unknown_channel_defaults_to_deny(self, server):
        """Channels with no matching rule are denied by default."""
        user = {"permissions": []}
        assert server._can_subscribe_to_channel(user, "random:thing") is False

    def test_no_permissions_defaults_to_deny(self, server):
        """A user with no permissions is denied everything (except admin)."""
        user = {"permissions": []}
        assert server._can_subscribe_to_channel(user, "workflow:abc") is False
        assert server._can_subscribe_to_channel(user, "pool:p") is False


# =============================================================================
# on_message() Tests
# =============================================================================


class TestOnMessage:
    """Tests for the on_message dispatcher."""

    @pytest.mark.asyncio
    async def test_request_message_dispatched_to_request_handler(self, mock_pool_manager):
        """A REQUEST message invokes _handle_request, not _handle_event."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        with (
            patch.object(server, "_handle_request", new=AsyncMock()) as handle_req,
            patch.object(server, "_handle_event", new=AsyncMock()) as handle_evt,
        ):
            msg = WebSocketMessage(
                type=MessageType.REQUEST,
                event="ping",
                data={},
            )
            await server.on_message(ws, msg)

        handle_req.assert_awaited_once_with(ws, msg)
        handle_evt.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_event_message_dispatched_to_event_handler(self, mock_pool_manager):
        """An EVENT message invokes _handle_event."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        with (
            patch.object(server, "_handle_request", new=AsyncMock()) as handle_req,
            patch.object(server, "_handle_event", new=AsyncMock()) as handle_evt,
        ):
            msg = WebSocketMessage(
                type=MessageType.EVENT,
                event="client.telemetry",
                data={},
            )
            await server.on_message(ws, msg)

        handle_evt.assert_awaited_once_with(ws, msg)
        handle_req.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rate_limited_message_sends_error(self, mock_pool_manager):
        """A rate-limited message returns without invoking the handler."""
        from mahavishnu.websocket.rate_limiter import RateLimitResult
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        with (
            patch.object(
                server.rate_limiter,
                "check",
                return_value=RateLimitResult(
                    allowed=False,
                    retry_after=0.5,
                    tokens_remaining=0.0,
                    limited=True,
                ),
            ),
            patch.object(server, "_handle_request", new=AsyncMock()) as handle_req,
        ):
            msg = WebSocketMessage(
                type=MessageType.REQUEST,
                event="ping",
                data={},
            )
            await server.on_message(ws, msg)

        # Handler NOT called
        handle_req.assert_not_awaited()
        # Error sent to client
        ws.send.assert_awaited()
        sent = ws.send.await_args.args[0]
        err = WebSocketProtocol.decode(sent)
        assert err.error_code == "RATE_LIMIT_EXCEEDED"
        assert "0.500" in err.error_message

    @pytest.mark.asyncio
    async def test_rate_limit_error_increments_error_metric(
        self, mock_pool_manager, _patch_metrics
    ):
        """Rate-limit errors bump the 'rate_limit' error counter."""
        from mahavishnu.websocket.rate_limiter import RateLimitResult
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        with patch.object(
            server.rate_limiter,
            "check",
            return_value=RateLimitResult(
                allowed=False,
                retry_after=0.1,
                limited=True,
            ),
        ):
            msg = WebSocketMessage(
                type=MessageType.REQUEST,
                event="ping",
                data={},
            )
            await server.on_message(ws, msg)

        _patch_metrics.inc_error.assert_called_with("rate_limit")

    @pytest.mark.asyncio
    async def test_rate_limit_error_send_failure_is_swallowed(self, mock_pool_manager):
        """If the rate-limit error send fails, the exception is swallowed."""
        from mahavishnu.websocket.rate_limiter import RateLimitResult
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws
        ws.send.side_effect = RuntimeError("send failed")

        with patch.object(
            server.rate_limiter,
            "check",
            return_value=RateLimitResult(
                allowed=False,
                retry_after=0.1,
                limited=True,
            ),
        ):
            msg = WebSocketMessage(
                type=MessageType.REQUEST,
                event="ping",
                data={},
            )
            # Should not raise
            await server.on_message(ws, msg)


# =============================================================================
# _handle_request() Tests
# =============================================================================


class TestHandleRequest:
    """Tests for the _handle_request dispatcher."""

    @pytest.mark.asyncio
    async def test_subscribe_joins_room(self, mock_pool_manager):
        """subscribe event joins the requested channel."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        msg = WebSocketMessage(
            type=MessageType.REQUEST,
            event="subscribe",
            data={"channel": "workflow:w1"},
        )
        await server._handle_request(ws, msg)

        assert "conn-1" in server.connection_rooms["workflow:w1"]
        # Confirmation sent
        sent = ws.send.await_args.args[0]
        response = WebSocketProtocol.decode(sent)
        assert response.data["status"] == "subscribed"
        assert response.data["channel"] == "workflow:w1"

    @pytest.mark.asyncio
    async def test_subscribe_forbidden_for_unauthorized_user(self, mock_pool_manager):
        """subscribe with insufficient permission returns FORBIDDEN."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket(user={"user_id": "alice", "permissions": []})
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        msg = WebSocketMessage(
            type=MessageType.REQUEST,
            event="subscribe",
            data={"channel": "workflow:w1"},
        )
        await server._handle_request(ws, msg)

        sent = ws.send.await_args.args[0]
        err = WebSocketProtocol.decode(sent)
        assert err.error_code == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_subscribe_with_admin_always_succeeds(self, mock_pool_manager):
        """An admin user can subscribe to any channel."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket(user={"user_id": "root", "permissions": ["admin"]})
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        msg = WebSocketMessage(
            type=MessageType.REQUEST,
            event="subscribe",
            data={"channel": "workflow:w1"},
        )
        await server._handle_request(ws, msg)

        assert "conn-1" in server.connection_rooms["workflow:w1"]

    @pytest.mark.asyncio
    async def test_unsubscribe_leaves_room(self, mock_pool_manager):
        """unsubscribe event removes the connection from the channel."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws
        # Seed the room
        server.connection_rooms["workflow:w1"] = {"conn-1"}

        msg = WebSocketMessage(
            type=MessageType.REQUEST,
            event="unsubscribe",
            data={"channel": "workflow:w1"},
        )
        await server._handle_request(ws, msg)

        assert "conn-1" not in server.connection_rooms.get("workflow:w1", set())
        sent = ws.send.await_args.args[0]
        response = WebSocketProtocol.decode(sent)
        assert response.data["status"] == "unsubscribed"

    @pytest.mark.asyncio
    async def test_get_pool_status_returns_dict(self, mock_pool_manager):
        """get_pool_status returns a response with the pool's status."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        msg = WebSocketMessage(
            type=MessageType.REQUEST,
            event="get_pool_status",
            data={"pool_id": "pool-1"},
        )
        await server._handle_request(ws, msg)

        sent = ws.send.await_args.args[0]
        response = WebSocketProtocol.decode(sent)
        assert response.data["pool_id"] == "pool-1"
        assert response.data["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_pool_status_unknown_pool(self, mock_pool_manager):
        """An unknown pool_id returns status='not_found'."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        msg = WebSocketMessage(
            type=MessageType.REQUEST,
            event="get_pool_status",
            data={"pool_id": "pool-missing"},
        )
        await server._handle_request(ws, msg)

        sent = ws.send.await_args.args[0]
        response = WebSocketProtocol.decode(sent)
        assert response.data["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_get_workflow_status_returns_dict(self, mock_pool_manager):
        """get_workflow_status returns a placeholder status payload."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        msg = WebSocketMessage(
            type=MessageType.REQUEST,
            event="get_workflow_status",
            data={"workflow_id": "wf-42"},
        )
        await server._handle_request(ws, msg)

        sent = ws.send.await_args.args[0]
        response = WebSocketProtocol.decode(sent)
        assert response.data["workflow_id"] == "wf-42"
        assert response.data["status"] == "running"

    @pytest.mark.asyncio
    async def test_unknown_request_returns_error(self, mock_pool_manager):
        """An unrecognised request event returns UNKNOWN_REQUEST."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        msg = WebSocketMessage(
            type=MessageType.REQUEST,
            event="do_something_weird",
            data={},
        )
        await server._handle_request(ws, msg)

        sent = ws.send.await_args.args[0]
        err = WebSocketProtocol.decode(sent)
        assert err.error_code == "UNKNOWN_REQUEST"
        assert "do_something_weird" in err.error_message

    @pytest.mark.asyncio
    async def test_get_pool_status_without_pool_manager(self, mock_pool_manager):
        """get_pool_status with pool_manager=None silently no-ops."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        server.pool_manager = None
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.connections["conn-1"] = ws

        msg = WebSocketMessage(
            type=MessageType.REQUEST,
            event="get_pool_status",
            data={"pool_id": "pool-1"},
        )
        # Should not raise, should not send
        await server._handle_request(ws, msg)
        # Only the welcome message was sent during on_connect
        ws.send.assert_awaited_once()


# =============================================================================
# _handle_event() Tests
# =============================================================================


class TestHandleEvent:
    """Tests for the _handle_event no-response handler."""

    @pytest.mark.asyncio
    async def test_event_handler_does_not_send_response(self, mock_pool_manager):
        """An EVENT message is acknowledged silently - no reply sent."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        ws.send.reset_mock()  # ignore the welcome message

        msg = WebSocketMessage(
            type=MessageType.EVENT,
            event="client.telemetry",
            data={"foo": "bar"},
        )
        await server._handle_event(ws, msg)

        ws.send.assert_not_awaited()


# =============================================================================
# leave_all_rooms() Tests
# =============================================================================


class TestLeaveAllRooms:
    """Tests for the overridden leave_all_rooms method."""

    @pytest.mark.asyncio
    async def test_leave_all_rooms_clears_all_subscriptions(self, mock_pool_manager):
        """leave_all_rooms removes the connection from every room."""
        from mcp_common.websocket.server import WebSocketServer

        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        server.connection_rooms = {
            "workflow:w1": {"conn-1", "conn-2"},
            "pool:p1": {"conn-1"},
            "global": {"conn-1", "conn-3"},
        }
        server.room_connections = {"conn-1": "global"}

        with patch.object(WebSocketServer, "leave_all_rooms", new=AsyncMock()):
            await server.leave_all_rooms("conn-1")

        # conn-1 should be gone everywhere; empty rooms should be cleaned up
        assert "conn-1" not in server.connection_rooms.get("workflow:w1", set())
        assert "conn-1" not in server.connection_rooms.get("pool:p1", set())
        assert "conn-1" not in server.connection_rooms.get("global", set())
        # Other connections remain
        assert "conn-2" in server.connection_rooms.get("workflow:w1", set())
        assert "conn-3" in server.connection_rooms.get("global", set())

    @pytest.mark.asyncio
    async def test_leave_all_rooms_removes_empty_rooms(self, mock_pool_manager):
        """Empty rooms are removed from connection_rooms entirely."""
        from mcp_common.websocket.server import WebSocketServer

        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        server.connection_rooms = {
            "workflow:w1": {"conn-1"},  # only conn-1
            "pool:p1": {"conn-1"},  # only conn-1
        }

        with patch.object(WebSocketServer, "leave_all_rooms", new=AsyncMock()):
            await server.leave_all_rooms("conn-1")

        # Both rooms are now empty and should be removed
        assert "workflow:w1" not in server.connection_rooms
        assert "pool:p1" not in server.connection_rooms


# =============================================================================
# get_rate_limit_stats() Tests
# =============================================================================


class TestGetRateLimitStats:
    """Tests for the rate-limit stats passthrough."""

    def test_delegates_to_rate_limiter(self, mock_pool_manager):
        """get_rate_limit_stats returns whatever the rate limiter reports."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        sentinel = {"total_connections": 0, "rate": 100.0}

        with patch.object(server.rate_limiter, "get_stats", return_value=sentinel) as stats:
            result = server.get_rate_limit_stats()

        stats.assert_called_once_with(None)
        assert result is sentinel

    def test_passes_specific_connection_id(self, mock_pool_manager):
        """A connection_id is forwarded to the rate limiter."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        with patch.object(server.rate_limiter, "get_stats", return_value={}) as stats:
            server.get_rate_limit_stats("conn-42")

        stats.assert_called_once_with("conn-42")


# =============================================================================
# handle_event_envelope() / handle() Tests
# =============================================================================


class TestEventEnvelopeBridge:
    """Tests for the event-envelope bridge into rooms."""

    @pytest.mark.asyncio
    async def test_handle_event_envelope_delegates_to_event_bridge(self, mock_pool_manager):
        """handle_event_envelope calls self._event_bridge.handle()."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        sentinel = {"status": "broadcast"}

        with patch.object(
            server._event_bridge, "handle", new=AsyncMock(return_value=sentinel)
        ) as handle:
            envelope = MagicMock(name="envelope")
            result = await server.handle_event_envelope(envelope)

        handle.assert_awaited_once_with(envelope)
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_handle_is_compat_alias(self, mock_pool_manager):
        """handle() is a compatibility alias for handle_event_envelope()."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        sentinel = {"status": "broadcast"}

        with patch.object(server._event_bridge, "handle", new=AsyncMock(return_value=sentinel)):
            envelope = MagicMock(name="envelope")
            result = await server.handle(envelope)

        assert result is sentinel


# =============================================================================
# Broadcast Helpers
# =============================================================================


class TestBroadcastHelpers:
    """Tests for the broadcast_* helper methods."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, room, event_type, extra_data",
        [
            (
                "broadcast_workflow_started",
                "workflow:w1",
                EventTypes.WORKFLOW_STARTED,
                {"workflow_id": "w1"},
            ),
            (
                "broadcast_workflow_stage_completed",
                "workflow:w1",
                EventTypes.WORKFLOW_STAGE_COMPLETED,
                {"workflow_id": "w1"},
            ),
            (
                "broadcast_workflow_completed",
                "workflow:w1",
                EventTypes.WORKFLOW_COMPLETED,
                {"workflow_id": "w1"},
            ),
            (
                "broadcast_workflow_failed",
                "workflow:w1",
                EventTypes.WORKFLOW_FAILED,
                {"workflow_id": "w1", "error": "boom"},
            ),
            (
                "broadcast_pool_status_changed",
                "pool:p1",
                EventTypes.POOL_STATUS_CHANGED,
                {"pool_id": "p1"},
            ),
        ],
    )
    async def test_broadcast_methods_target_correct_room(
        self,
        mock_pool_manager,
        method_name,
        room,
        event_type,
        extra_data,
    ):
        """Each broadcast helper routes to the right room with the right event."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        with patch.object(server, "broadcast_to_room", new=AsyncMock()) as broadcast:
            method = getattr(server, method_name)
            if method_name == "broadcast_workflow_stage_completed":
                await method("w1", "stage-1", {"ok": True})
            elif method_name == "broadcast_workflow_completed":
                await method("w1", {"ok": True})
            elif method_name == "broadcast_workflow_failed":
                await method("w1", "boom")
            elif method_name == "broadcast_pool_status_changed":
                await method("p1", {"workers": 3})
            else:
                await method("w1", {"metadata": "x"})

        broadcast.assert_awaited_once()
        call_args = broadcast.await_args
        assert call_args.args[0] == room
        # The event payload should match the event_type
        sent_event = call_args.args[1]
        assert sent_event.event == event_type

    @pytest.mark.asyncio
    async def test_broadcast_worker_status_changed_strips_pool_prefix(self, mock_pool_manager):
        """A 'pool:p1' id is normalized to 'p1' for both room and data."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        with patch.object(server, "broadcast_to_room", new=AsyncMock()) as broadcast:
            await server.broadcast_worker_status_changed("w1", "busy", "pool:p1")

        call_args = broadcast.await_args
        assert call_args.args[0] == "pool:p1"  # room uses full id (with prefix)
        event_payload = call_args.args[1]
        assert event_payload.data["pool_id"] == "p1"  # data has prefix stripped

    @pytest.mark.asyncio
    async def test_broadcast_pool_status_changed_strips_pool_prefix(self, mock_pool_manager):
        """broadcast_pool_status_changed normalizes 'pool:' prefix in data."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        with patch.object(server, "broadcast_to_room", new=AsyncMock()) as broadcast:
            await server.broadcast_pool_status_changed("pool:p1", {"workers": 3})

        event_payload = broadcast.await_args.args[1]
        assert event_payload.data["pool_id"] == "p1"

    @pytest.mark.asyncio
    async def test_broadcast_pool_status_changed_without_prefix(self, mock_pool_manager):
        """If 'pool:' prefix is missing, no error is raised."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        with patch.object(server, "broadcast_to_room", new=AsyncMock()) as broadcast:
            await server.broadcast_pool_status_changed("p1", {"workers": 3})

        call_args = broadcast.await_args
        assert call_args.args[0] == "pool:p1"
        event_payload = call_args.args[1]
        assert event_payload.data["pool_id"] == "p1"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, room, user_room",
        [
            ("broadcast_team_created", "goal-teams", "goal-teams:u1"),
            ("broadcast_team_parsed", "goal-teams", "goal-teams:u1"),
            ("broadcast_team_execution_started", "goal-teams", "goal-teams:u1"),
            ("broadcast_team_execution_completed", "goal-teams", "goal-teams:u1"),
            ("broadcast_team_error", "goal-teams", "goal-teams:u1"),
        ],
    )
    async def test_team_broadcasts_emit_global_and_user_rooms(
        self, mock_pool_manager, method_name, room, user_room
    ):
        """Each team broadcast emits to goal-teams and (if user_id) to user room."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        with patch.object(server, "broadcast_to_room", new=AsyncMock()) as broadcast:
            method = getattr(server, method_name)
            if method_name == "broadcast_team_created":
                await method("t1", "name", "goal", "coordinate", user_id="u1")
            elif method_name == "broadcast_team_parsed":
                await method("goal", "review", ["cap"], 0.9, user_id="u1")
            elif method_name == "broadcast_team_execution_started":
                await method("t1", "task", user_id="u1")
            elif method_name == "broadcast_team_execution_completed":
                await method("t1", True, 100.0, user_id="u1")
            elif method_name == "broadcast_team_error":
                await method("t1", "ERR_X", "boom", user_id="u1")

        # Two broadcasts: global + user-specific
        rooms_called = [call.args[0] for call in broadcast.await_args_list]
        assert room in rooms_called
        assert user_room in rooms_called

    @pytest.mark.asyncio
    async def test_team_broadcast_without_user_id_only_uses_global(self, mock_pool_manager):
        """Without a user_id, the user-specific room is NOT broadcast to."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        with patch.object(server, "broadcast_to_room", new=AsyncMock()) as broadcast:
            await server.broadcast_team_error("t1", "ERR", "boom")

        # Only the global room is hit
        rooms_called = [call.args[0] for call in broadcast.await_args_list]
        assert rooms_called == ["goal-teams"]

    @pytest.mark.asyncio
    async def test_team_execution_started_truncates_long_tasks(self, mock_pool_manager):
        """Tasks over 200 characters are truncated."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        long_task = "x" * 500

        with patch.object(server, "broadcast_to_room", new=AsyncMock()) as broadcast:
            await server.broadcast_team_execution_started("t1", long_task)

        event_payload = broadcast.await_args_list[0].args[1]
        assert len(event_payload.data["task"]) == 200

    @pytest.mark.asyncio
    async def test_adapter_registered_broadcast(self, mock_pool_manager):
        """adapter.registered is broadcast to the 'adapters' room."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        with patch.object(server, "broadcast_to_room", new=AsyncMock()) as broadcast:
            await server.broadcast_adapter_registered(
                "a1", "Adapter 1", ["cap1"], "prefect", "entry_point"
            )

        call = broadcast.await_args
        assert call.args[0] == "adapters"
        assert call.args[1].event == "adapter.registered"
        assert call.args[1].data["adapter_id"] == "a1"

    @pytest.mark.asyncio
    async def test_adapter_enabled_uses_correct_event_name(self, mock_pool_manager):
        """adapter.enabled event when enabled=True, adapter.disabled otherwise."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        with patch.object(server, "broadcast_to_room", new=AsyncMock()) as broadcast:
            await server.broadcast_adapter_enabled("a1", "Adapter 1", True)
            await server.broadcast_adapter_enabled("a1", "Adapter 1", False)

        enabled_event = broadcast.await_args_list[0].args[1]
        disabled_event = broadcast.await_args_list[1].args[1]
        assert enabled_event.event == "adapter.enabled"
        assert disabled_event.event == "adapter.disabled"

    @pytest.mark.asyncio
    async def test_routing_decision_broadcast(self, mock_pool_manager):
        """broadcast_routing_decision sends to the 'adapters' room."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        with patch.object(server, "broadcast_to_room", new=AsyncMock()) as broadcast:
            await server.broadcast_routing_decision("ai_task", "prefect", ["cap1"], 12.345, False)

        call = broadcast.await_args
        assert call.args[0] == "adapters"
        assert call.args[1].event == "adapter.routing_decision"
        # Latency is rounded to 2dp
        assert call.args[1].data["latency_ms"] == 12.35

    @pytest.mark.asyncio
    async def test_adapter_health_changed_includes_details(self, mock_pool_manager):
        """broadcast_adapter_health_changed includes the details dict."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        with patch.object(server, "broadcast_to_room", new=AsyncMock()) as broadcast:
            await server.broadcast_adapter_health_changed(
                "a1", "Adapter 1", "healthy", "degraded", {"latency": 99}
            )

        payload = broadcast.await_args.args[1]
        assert payload.event == "adapter.health_changed"
        assert payload.data["details"] == {"latency": 99}

    @pytest.mark.asyncio
    async def test_adapter_health_changed_defaults_details_to_empty(self, mock_pool_manager):
        """If details is None, an empty dict is used."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        with patch.object(server, "broadcast_to_room", new=AsyncMock()) as broadcast:
            await server.broadcast_adapter_health_changed(
                "a1", "Adapter 1", "healthy", "unhealthy", None
            )

        payload = broadcast.await_args.args[1]
        assert payload.data["details"] == {}


# =============================================================================
# _get_pool_status() Internal Helper
# =============================================================================


class TestGetPoolStatusInternal:
    """Tests for the internal _get_pool_status helper."""

    @pytest.mark.asyncio
    async def test_known_pool(self, mock_pool_manager):
        """A known pool returns its status and worker list."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        status = await server._get_pool_status("pool-1")

        assert status["pool_id"] == "pool-1"
        assert status["status"] == "running"
        assert status["workers"] == ["w1", "w2"]

    @pytest.mark.asyncio
    async def test_unknown_pool(self, mock_pool_manager):
        """An unknown pool returns status='not_found'."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        status = await server._get_pool_status("pool-missing")

        assert status == {"pool_id": "pool-missing", "status": "not_found"}

    @pytest.mark.asyncio
    async def test_exception_is_swallowed(self, mock_pool_manager):
        """An exception in the pool lookup is caught and reported as 'error'."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)

        # Wrap the .pools attribute in a property that raises on access.
        class _BoomPools:
            def __contains__(self, _item):
                raise RuntimeError("boom")

        mock_pool_manager.pools = _BoomPools()
        # hasattr still succeeds (it's an object), but the `in` check raises.

        status = await server._get_pool_status("pool-1")

        assert status["status"] == "error"
        assert "boom" in status["error"]


# =============================================================================
# _get_workflow_status() Internal Helper
# =============================================================================


class TestGetWorkflowStatusInternal:
    """Tests for the internal _get_workflow_status helper."""

    @pytest.mark.asyncio
    async def test_returns_placeholder(self, mock_pool_manager):
        """_get_workflow_status returns a placeholder status."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        status = await server._get_workflow_status("wf-42")

        assert status["workflow_id"] == "wf-42"
        assert status["status"] == "running"
        assert status["stages_completed"] == 0
        assert status["total_stages"] == 10


# =============================================================================
# _get_timestamp() Internal Helper
# =============================================================================


class TestGetTimestamp:
    """Tests for the internal _get_timestamp helper."""

    def test_returns_iso_string(self, mock_pool_manager):
        """_get_timestamp returns an ISO 8601 string."""
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer(pool_manager=mock_pool_manager)
        ts = server._get_timestamp()

        # ISO 8601 has a 'T' separator and ends with +00:00 or Z
        assert isinstance(ts, str)
        assert "T" in ts
