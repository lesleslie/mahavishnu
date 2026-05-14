"""Comprehensive unit tests for mahavishnu/websocket/server.py."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_common.websocket import MessageType, WebSocketMessage
from mcp_common.websocket.protocol import WebSocketProtocol
import pytest

from mahavishnu.core.events.contract import create_event_envelope
from mahavishnu.websocket.rate_limiter import RateLimitResult
from mahavishnu.websocket.server import (
    MahavishnuWebSocketServer,
    _get_explicit_attribute,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pool_manager() -> MagicMock:
    """Create a mock pool manager."""
    mgr = MagicMock()
    mgr.pools = {}
    return mgr


def _make_server(**overrides) -> MahavishnuWebSocketServer:
    """Create a MahavishnuWebSocketServer with all external deps patched.

    Patches: get_authenticator, get_metrics, load_ssl_context, get_websocket_tls_config.
    """
    with (
        patch("mahavishnu.websocket.server.get_authenticator", return_value=None),
        patch("mahavishnu.websocket.server.get_metrics") as mock_get_metrics,
        patch("mahavishnu.websocket.server.load_ssl_context", return_value={"ssl_context": None}),
        patch(
            "mahavishnu.websocket.server.get_websocket_tls_config",
            return_value={"tls_enabled": False, "cert_file": None},
        ),
    ):
        mock_metrics = MagicMock()
        mock_get_metrics.return_value = mock_metrics

        defaults = {
            "pool_manager": _make_pool_manager(),
            "host": "127.0.0.1",
            "port": 8690,
        }
        defaults.update(overrides)
        server = MahavishnuWebSocketServer(**defaults)
        return server


def _make_websocket(
    *,
    user: dict | None = None,
    has_id: bool = False,
    ws_id: str | None = None,
) -> MagicMock:
    """Create a mock websocket object with AsyncMock send."""
    ws = MagicMock()
    if user is not None:
        ws.__dict__["user"] = user
    if ws_id is not None:
        ws.__dict__["id"] = ws_id
    elif has_id:
        ws.__dict__["id"] = "ws-from-attribute"

    # The real code does ``await websocket.send(...)`` in _handle_request and
    # _send_rate_limit_error, so the mock must be awaitable.
    ws.send = AsyncMock()
    return ws


def _make_message(
    *,
    msg_type: MessageType = MessageType.REQUEST,
    event: str = "subscribe",
    data: dict | None = None,
    correlation_id: str | None = None,
) -> WebSocketMessage:
    """Create a WebSocketMessage for testing."""
    if data is None:
        data = {}
    return WebSocketMessage(
        type=msg_type,
        event=event,
        data=data,
        correlation_id=correlation_id,
    )


# ===========================================================================
# _get_explicit_attribute
# ===========================================================================


class TestGetExplicitAttribute:
    """Tests for the _get_explicit_attribute helper."""

    def test_returns_attribute_when_in_dict(self):
        obj = MagicMock()
        obj.__dict__["custom_attr"] = "value"
        assert _get_explicit_attribute(obj, "custom_attr") == "value"

    def test_returns_default_when_attribute_not_in_dict(self):
        obj = MagicMock()
        assert _get_explicit_attribute(obj, "missing") is None

    def test_returns_custom_default_when_attribute_not_in_dict(self):
        obj = MagicMock()
        assert _get_explicit_attribute(obj, "missing", 42) == 42

    def test_returns_default_for_object_without_dict(self):
        obj = object()
        assert _get_explicit_attribute(obj, "anything") is None


# ===========================================================================
# Initialization
# ===========================================================================


class TestMahavishnuWebSocketServerInit:
    """Tests for MahavishnuWebSocketServer.__init__."""

    def test_sets_default_host_and_port(self):
        server = _make_server()
        assert server.host == "127.0.0.1"
        assert server.port == 8690

    def test_accepts_custom_host_and_port(self):
        server = _make_server(host="0.0.0.0", port=9999)
        assert server.host == "0.0.0.0"
        assert server.port == 9999

    def test_stores_pool_manager(self):
        pm = _make_pool_manager()
        server = _make_server(pool_manager=pm)
        assert server.pool_manager is pm

    def test_initializes_connection_ids_empty(self):
        server = _make_server()
        assert server._connection_ids == {}

    def test_initializes_rate_limiter_with_configured_rate(self):
        server = _make_server(message_rate_limit=50)
        assert server.rate_limiter.rate == 50.0
        assert server.rate_limiter.burst_size == 75.0  # 1.5x

    @pytest.mark.asyncio
    async def test_handle_event_envelope_broadcasts_to_room(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()
        envelope = create_event_envelope(
            "workflow.started",
            "test_service",
            payload={"workflow_id": "wf-123"},
        )

        result = await server.handle_event_envelope(envelope)

        assert result["event_type"] == "workflow.started"
        assert server.broadcast_to_room.await_count == 2
        server.broadcast_to_room.assert_any_await("workflow:wf-123", result)
        server.broadcast_to_room.assert_any_await("global", result)

    def test_initializes_metrics(self):
        server = _make_server()
        assert server.metrics is not None

    def test_default_ssl_context_is_none_on_localhost(self):
        server = _make_server()
        assert server.ssl_context is None

    def test_calls_load_ssl_context_when_tls_enabled(self):
        with (
            patch("mahavishnu.websocket.server.get_authenticator", return_value=None),
            patch("mahavishnu.websocket.server.get_metrics") as mock_get_metrics,
            patch("mahavishnu.websocket.server.load_ssl_context") as mock_load_ssl,
            patch("mahavishnu.websocket.server.get_websocket_tls_config"),
        ):
            mock_get_metrics.return_value = MagicMock()
            fake_ssl = MagicMock()
            mock_load_ssl.return_value = {"ssl_context": fake_ssl}

            server = MahavishnuWebSocketServer(
                pool_manager=_make_pool_manager(),
                tls_enabled=True,
            )
            assert server.ssl_context is fake_ssl

    def test_calls_load_ssl_context_when_cert_file_provided(self):
        with (
            patch("mahavishnu.websocket.server.get_authenticator", return_value=None),
            patch("mahavishnu.websocket.server.get_metrics") as mock_get_metrics,
            patch("mahavishnu.websocket.server.load_ssl_context") as mock_load_ssl,
            patch("mahavishnu.websocket.server.get_websocket_tls_config"),
        ):
            mock_get_metrics.return_value = MagicMock()
            fake_ssl = MagicMock()
            mock_load_ssl.return_value = {"ssl_context": fake_ssl}

            server = MahavishnuWebSocketServer(
                pool_manager=_make_pool_manager(),
                cert_file="/tmp/cert.pem",
                key_file="/tmp/key.pem",
            )
            mock_load_ssl.assert_called_once()
            assert server.ssl_context is fake_ssl

    def test_falls_back_to_env_tls_config_when_ssl_context_still_none(self):
        with (
            patch("mahavishnu.websocket.server.get_authenticator", return_value=None),
            patch("mahavishnu.websocket.server.get_metrics") as mock_get_metrics,
            patch(
                "mahavishnu.websocket.server.load_ssl_context",
                return_value={"ssl_context": None},
            ),
            patch("mahavishnu.websocket.server.get_websocket_tls_config") as mock_env_config,
        ):
            mock_get_metrics.return_value = MagicMock()
            fake_ssl = MagicMock()
            mock_env_config.return_value = {"tls_enabled": True, "cert_file": "/env/cert.pem"}
            mock_load_ssl = MagicMock(
                side_effect=[
                    {"ssl_context": None},
                    {"ssl_context": fake_ssl},
                ]
            )
            with patch("mahavishnu.websocket.server.load_ssl_context", mock_load_ssl):
                server = MahavishnuWebSocketServer(
                    pool_manager=_make_pool_manager(),
                    tls_enabled=True,
                )
            assert server.ssl_context is fake_ssl

    def test_no_env_fallback_when_tls_disabled(self):
        server = _make_server()
        assert server.ssl_context is None

    def test_security_warning_for_non_localhost_without_tls(self, caplog):
        with caplog.at_level(logging.WARNING):
            _make_server(host="0.0.0.0", tls_enabled=False)
        assert any("SECURITY WARNING" in r.message for r in caplog.records)

    def test_no_security_warning_for_localhost(self, caplog):
        with caplog.at_level(logging.WARNING):
            _make_server(host="127.0.0.1", tls_enabled=False)
        assert not any("SECURITY WARNING" in r.message for r in caplog.records)

    def test_no_security_warning_for_localhost_string(self, caplog):
        with caplog.at_level(logging.WARNING):
            _make_server(host="localhost", tls_enabled=False)
        assert not any("SECURITY WARNING" in r.message for r in caplog.records)

    def test_no_security_warning_for_ipv6_localhost(self, caplog):
        with caplog.at_level(logging.WARNING):
            _make_server(host="::1", tls_enabled=False)
        assert not any("SECURITY WARNING" in r.message for r in caplog.records)

    def test_max_connections_forwarded_to_parent(self):
        server = _make_server(max_connections=500)
        assert server.max_connections == 500

    def test_message_rate_limit_forwarded_to_parent(self):
        server = _make_server(message_rate_limit=200)
        assert server.message_rate_limit == 200


# ===========================================================================
# on_connect
# ===========================================================================


class TestOnConnect:
    """Tests for MahavishnuWebSocketServer.on_connect."""

    @pytest.mark.asyncio
    async def test_stores_connection_id_mapping(self):
        server = _make_server()
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        assert server._connection_ids[ws] == "conn-1"

    @pytest.mark.asyncio
    async def test_tracks_connection_metrics(self):
        server = _make_server()
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        server.metrics.adjust_connections.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_sends_welcome_message(self):
        server = _make_server()
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        ws.send.assert_called_once()
        # Verify the sent payload contains expected fields
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.event == "session.created"
        assert decoded.data["connection_id"] == "conn-1"
        assert decoded.data["server"] == "mahavishnu"

    @pytest.mark.asyncio
    async def test_welcome_message_authenticated_flag_true_for_user(self):
        server = _make_server()
        ws = _make_websocket(user={"user_id": "u1"})
        await server.on_connect(ws, "conn-1")
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["authenticated"] is True

    @pytest.mark.asyncio
    async def test_welcome_message_authenticated_flag_false_for_anonymous(self):
        server = _make_server()
        ws = _make_websocket(user=None)
        await server.on_connect(ws, "conn-1")
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["authenticated"] is False

    @pytest.mark.asyncio
    async def test_welcome_message_contains_rate_limit(self):
        server = _make_server(message_rate_limit=50)
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["rate_limit"] == 50

    @pytest.mark.asyncio
    async def test_welcome_message_secure_flag_when_ssl_context_set(self):
        server = _make_server()
        server.ssl_context = MagicMock()
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["secure"] is True

    @pytest.mark.asyncio
    async def test_welcome_message_secure_flag_false_without_ssl(self):
        server = _make_server()
        ws = _make_websocket()
        await server.on_connect(ws, "conn-1")
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["secure"] is False


# ===========================================================================
# on_disconnect
# ===========================================================================


class TestOnDisconnect:
    """Tests for MahavishnuWebSocketServer.on_disconnect."""

    @pytest.mark.asyncio
    async def test_adjusts_connection_metrics_down(self):
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids[ws] = "conn-1"
        await server.on_disconnect(ws, "conn-1")
        server.metrics.adjust_connections.assert_called_once_with(-1)

    @pytest.mark.asyncio
    async def test_removes_rate_limiter_bucket(self):
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids[ws] = "conn-1"
        server.rate_limiter.remove_connection = MagicMock()
        await server.on_disconnect(ws, "conn-1")
        server.rate_limiter.remove_connection.assert_called_once_with("conn-1")

    @pytest.mark.asyncio
    async def test_cleans_up_connection_id_mapping(self):
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids[ws] = "conn-1"
        await server.on_disconnect(ws, "conn-1")
        assert ws not in server._connection_ids

    @pytest.mark.asyncio
    async def test_cleans_up_connections_dict(self):
        server = _make_server()
        ws = _make_websocket()
        server.connections["conn-1"] = ws
        await server.on_disconnect(ws, "conn-1")
        assert "conn-1" not in server.connections

    @pytest.mark.asyncio
    async def test_calls_leave_all_rooms(self):
        server = _make_server()
        ws = _make_websocket()
        server.leave_all_rooms = AsyncMock()
        await server.on_disconnect(ws, "conn-1")
        server.leave_all_rooms.assert_called_once_with("conn-1")

    @pytest.mark.asyncio
    async def test_no_error_when_websocket_not_in_connection_ids(self):
        server = _make_server()
        ws = _make_websocket()
        # Should not raise
        await server.on_disconnect(ws, "conn-unknown")


# ===========================================================================
# on_message
# ===========================================================================


class TestOnMessage:
    """Tests for MahavishnuWebSocketServer.on_message."""

    @pytest.mark.asyncio
    async def test_delegates_request_to_handle_request(self):
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids[ws] = "conn-1"
        server._handle_request = AsyncMock()

        msg = _make_message(
            msg_type=MessageType.REQUEST, event="subscribe", data={"channel": "pool:abc"}
        )
        await server.on_message(ws, msg)
        server._handle_request.assert_called_once_with(ws, msg)

    @pytest.mark.asyncio
    async def test_delegates_event_to_handle_event(self):
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids[ws] = "conn-1"
        server._handle_event = AsyncMock()

        msg = _make_message(msg_type=MessageType.EVENT, event="client.heartbeat")
        await server.on_message(ws, msg)
        server._handle_event.assert_called_once_with(ws, msg)

    @pytest.mark.asyncio
    async def test_rate_limited_message_does_not_process(self):
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids[ws] = "conn-1"
        server._handle_request = AsyncMock()
        server._send_rate_limit_error = AsyncMock()
        server.rate_limiter.check = MagicMock(
            return_value=RateLimitResult(allowed=False, limited=True, retry_after=0.5)
        )

        msg = _make_message()
        await server.on_message(ws, msg)
        server._handle_request.assert_not_called()
        server._send_rate_limit_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_unhandled_message_type_logs_warning(self, caplog):
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids[ws] = "conn-1"

        # ACK is not REQUEST or EVENT
        msg = _make_message(msg_type=MessageType.ACK)
        with caplog.at_level(logging.WARNING):
            await server.on_message(ws, msg)
        assert any("Unhandled message type" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_connection_id_lookup_from_websocket_attribute(self):
        """When _connection_ids has no mapping, falls back to websocket.id."""
        server = _make_server()
        ws = _make_websocket(has_id=True)
        server._connection_ids = {}  # empty

        server._handle_request = AsyncMock()
        msg = _make_message()
        await server.on_message(ws, msg)
        # After lookup, the mapping should be stored
        assert ws in server._connection_ids
        assert server._connection_ids[ws] == "ws-from-attribute"

    @pytest.mark.asyncio
    async def test_connection_id_lookup_from_connections_dict(self):
        """When websocket has no id attribute, looks up in connections dict."""
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids = {}
        server.connections["known-conn"] = ws

        server._handle_request = AsyncMock()
        msg = _make_message()
        await server.on_message(ws, msg)
        assert server._connection_ids[ws] == "known-conn"

    @pytest.mark.asyncio
    async def test_connection_id_generates_uuid_when_not_found(self):
        """When connection cannot be found anywhere, generates a UUID."""
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids = {}
        server.connections = {}

        server._handle_request = AsyncMock()
        msg = _make_message()
        await server.on_message(ws, msg)
        assert ws in server._connection_ids
        assert server._connection_ids[ws] is not None


# ===========================================================================
# _send_rate_limit_error
# ===========================================================================


class TestSendRateLimitError:
    """Tests for MahavishnuWebSocketServer._send_rate_limit_error."""

    @pytest.mark.asyncio
    async def test_increments_error_metric(self):
        server = _make_server()
        ws = _make_websocket()
        msg = _make_message(correlation_id="corr-1")
        rate_result = RateLimitResult(allowed=False, limited=True, retry_after=0.25)

        await server._send_rate_limit_error(ws, msg, rate_result)
        server.metrics.inc_error.assert_called_once_with("rate_limit")

    @pytest.mark.asyncio
    async def test_sends_error_response_to_client(self):
        server = _make_server()
        ws = _make_websocket()
        msg = _make_message(correlation_id="corr-1")
        rate_result = RateLimitResult(allowed=False, limited=True, retry_after=0.25)

        await server._send_rate_limit_error(ws, msg, rate_result)
        ws.send.assert_called_once()
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.type == MessageType.ERROR
        assert decoded.error_code == "RATE_LIMIT_EXCEEDED"
        assert "0.250" in decoded.error_message
        assert decoded.correlation_id == "corr-1"

    @pytest.mark.asyncio
    async def test_handles_send_failure_gracefully(self, caplog):
        server = _make_server()
        ws = _make_websocket()
        ws.send.side_effect = RuntimeError("connection closed")
        msg = _make_message()
        rate_result = RateLimitResult(allowed=False, limited=True, retry_after=0.1)

        with caplog.at_level(logging.DEBUG):
            await server._send_rate_limit_error(ws, msg, rate_result)
        assert any("Failed to send rate limit error" in r.message for r in caplog.records)


# ===========================================================================
# _handle_request - subscribe
# ===========================================================================


class TestHandleRequestSubscribe:
    """Tests for subscribe handling in _handle_request."""

    @pytest.mark.asyncio
    async def test_subscribe_to_channel(self):
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids[ws] = "conn-1"
        server.join_room = AsyncMock()

        msg = _make_message(event="subscribe", data={"channel": "workflow:wf-1"})
        await server._handle_request(ws, msg)

        server.join_room.assert_called_once_with("workflow:wf-1", "conn-1")
        ws.send.assert_called_once()
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["status"] == "subscribed"
        assert decoded.data["channel"] == "workflow:wf-1"

    @pytest.mark.asyncio
    async def test_subscribe_with_no_channel_does_nothing(self):
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids[ws] = "conn-1"
        server.join_room = AsyncMock()

        msg = _make_message(event="subscribe", data={})
        await server._handle_request(ws, msg)

        server.join_room.assert_not_called()
        ws.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_subscribe_forbidden_when_user_lacks_permission(self):
        server = _make_server()
        ws = _make_websocket(user={"user_id": "u1", "permissions": ["read"]})
        server._connection_ids[ws] = "conn-1"

        msg = _make_message(event="subscribe", data={"channel": "workflow:wf-1"})
        await server._handle_request(ws, msg)

        ws.send.assert_called_once()
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.error_code == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_subscribe_allowed_for_admin_user(self):
        server = _make_server()
        ws = _make_websocket(user={"user_id": "admin", "permissions": ["admin"]})
        server._connection_ids[ws] = "conn-1"
        server.join_room = AsyncMock()

        msg = _make_message(event="subscribe", data={"channel": "workflow:wf-1"})
        await server._handle_request(ws, msg)

        server.join_room.assert_called_once()
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["status"] == "subscribed"

    @pytest.mark.asyncio
    async def test_subscribe_generates_connection_id_when_missing(self):
        server = _make_server()
        ws = _make_websocket()
        # Do not pre-populate _connection_ids
        server.join_room = AsyncMock()

        msg = _make_message(event="subscribe", data={"channel": "pool:p1"})
        await server._handle_request(ws, msg)

        server.join_room.assert_called_once()
        call_args = server.join_room.call_args
        # connection_id should be a generated UUID string
        assert call_args[0][1] is not None


# ===========================================================================
# _handle_request - unsubscribe
# ===========================================================================


class TestHandleRequestUnsubscribe:
    """Tests for unsubscribe handling in _handle_request."""

    @pytest.mark.asyncio
    async def test_unsubscribe_from_channel(self):
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids[ws] = "conn-1"
        server.leave_room = AsyncMock()

        msg = _make_message(event="unsubscribe", data={"channel": "workflow:wf-1"})
        await server._handle_request(ws, msg)

        server.leave_room.assert_called_once_with("workflow:wf-1", "conn-1")
        ws.send.assert_called_once()
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["status"] == "unsubscribed"
        assert decoded.data["channel"] == "workflow:wf-1"

    @pytest.mark.asyncio
    async def test_unsubscribe_with_no_channel_does_nothing(self):
        server = _make_server()
        ws = _make_websocket()
        server._connection_ids[ws] = "conn-1"
        server.leave_room = AsyncMock()

        msg = _make_message(event="unsubscribe", data={})
        await server._handle_request(ws, msg)

        server.leave_room.assert_not_called()
        ws.send.assert_not_called()


# ===========================================================================
# _handle_request - get_pool_status
# ===========================================================================


class TestHandleRequestGetPoolStatus:
    """Tests for get_pool_status handling in _handle_request."""

    @pytest.mark.asyncio
    async def test_returns_pool_status_when_found(self):
        server = _make_server()
        ws = _make_websocket()
        mock_pool = MagicMock()
        mock_pool.status = "active"
        mock_pool.workers = ["w1", "w2"]
        server.pool_manager.pools = {"pool-1": mock_pool}

        msg = _make_message(event="get_pool_status", data={"pool_id": "pool-1"})
        await server._handle_request(ws, msg)

        ws.send.assert_called_once()
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["pool_id"] == "pool-1"
        assert decoded.data["status"] == "active"
        assert decoded.data["workers"] == ["w1", "w2"]

    @pytest.mark.asyncio
    async def test_returns_not_found_when_pool_missing(self):
        server = _make_server()
        ws = _make_websocket()

        msg = _make_message(event="get_pool_status", data={"pool_id": "missing"})
        await server._handle_request(ws, msg)

        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_returns_not_found_when_pool_manager_has_no_pools_attr(self):
        server = _make_server()
        server.pool_manager = MagicMock(spec=[])  # no 'pools' attribute
        ws = _make_websocket()

        msg = _make_message(event="get_pool_status", data={"pool_id": "pool-1"})
        await server._handle_request(ws, msg)

        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_no_action_when_no_pool_id(self):
        server = _make_server()
        ws = _make_websocket()

        msg = _make_message(event="get_pool_status", data={})
        await server._handle_request(ws, msg)
        ws.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_action_when_pool_manager_is_none(self):
        server = _make_server(pool_manager=None)
        ws = _make_websocket()

        msg = _make_message(event="get_pool_status", data={"pool_id": "pool-1"})
        await server._handle_request(ws, msg)
        ws.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self, caplog):
        server = _make_server()
        ws = _make_websocket()
        server.pool_manager.pools = MagicMock()
        server.pool_manager.pools.__contains__ = MagicMock(side_effect=RuntimeError("boom"))

        msg = _make_message(event="get_pool_status", data={"pool_id": "pool-1"})
        with caplog.at_level(logging.ERROR):
            await server._handle_request(ws, msg)

        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["status"] == "error"
        assert "boom" in decoded.data["error"]


# ===========================================================================
# _handle_request - get_workflow_status
# ===========================================================================


class TestHandleRequestGetWorkflowStatus:
    """Tests for get_workflow_status handling in _handle_request."""

    @pytest.mark.asyncio
    async def test_returns_workflow_status(self):
        server = _make_server()
        ws = _make_websocket()

        msg = _make_message(event="get_workflow_status", data={"workflow_id": "wf-1"})
        await server._handle_request(ws, msg)

        ws.send.assert_called_once()
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.data["workflow_id"] == "wf-1"
        assert decoded.data["status"] == "running"
        assert "stages_completed" in decoded.data

    @pytest.mark.asyncio
    async def test_no_action_when_no_workflow_id(self):
        server = _make_server()
        ws = _make_websocket()

        msg = _make_message(event="get_workflow_status", data={})
        await server._handle_request(ws, msg)
        ws.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_action_when_pool_manager_is_none(self):
        server = _make_server(pool_manager=None)
        ws = _make_websocket()

        msg = _make_message(event="get_workflow_status", data={"workflow_id": "wf-1"})
        await server._handle_request(ws, msg)
        ws.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_workflow_status_response_includes_stages(self):
        server = _make_server()
        ws = _make_websocket()

        msg = _make_message(event="get_workflow_status", data={"workflow_id": "wf-stages"})
        await server._handle_request(ws, msg)

        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert "stages_completed" in decoded.data
        assert "total_stages" in decoded.data
        assert decoded.data["total_stages"] == 10


# ===========================================================================
# _handle_request - unknown event
# ===========================================================================


class TestHandleRequestUnknownEvent:
    """Tests for unknown request event handling."""

    @pytest.mark.asyncio
    async def test_returns_unknown_request_error(self):
        server = _make_server()
        ws = _make_websocket()

        msg = _make_message(event="do_something_crazy")
        await server._handle_request(ws, msg)

        ws.send.assert_called_once()
        sent_json = ws.send.call_args[0][0]
        decoded = WebSocketProtocol.decode(sent_json)
        assert decoded.error_code == "UNKNOWN_REQUEST"
        assert "do_something_crazy" in decoded.error_message


# ===========================================================================
# _handle_event
# ===========================================================================


class TestHandleEvent:
    """Tests for _handle_event."""

    @pytest.mark.asyncio
    async def test_logs_client_event(self, caplog):
        server = _make_server()
        ws = _make_websocket()

        msg = _make_message(msg_type=MessageType.EVENT, event="client.telemetry")
        with caplog.at_level(logging.DEBUG):
            await server._handle_event(ws, msg)
        assert any("client.telemetry" in r.message for r in caplog.records)


# ===========================================================================
# _can_subscribe_to_channel
# ===========================================================================


class TestCanSubscribeToChannel:
    """Tests for _can_subscribe_to_channel authorization logic."""

    def test_admin_can_subscribe_anywhere(self):
        server = _make_server()
        user = {"user_id": "admin", "permissions": ["admin"]}
        assert server._can_subscribe_to_channel(user, "workflow:x") is True
        assert server._can_subscribe_to_channel(user, "pool:y") is True
        assert server._can_subscribe_to_channel(user, "anything") is True

    def test_workflow_read_allows_workflow_channel(self):
        server = _make_server()
        user = {"user_id": "dev", "permissions": ["workflow:read"]}
        assert server._can_subscribe_to_channel(user, "workflow:wf-1") is True

    def test_workflow_read_denies_pool_channel(self):
        server = _make_server()
        user = {"user_id": "dev", "permissions": ["workflow:read"]}
        assert server._can_subscribe_to_channel(user, "pool:p1") is False

    def test_pool_read_allows_pool_channel(self):
        server = _make_server()
        user = {"user_id": "ops", "permissions": ["pool:read"]}
        assert server._can_subscribe_to_channel(user, "pool:p1") is True

    def test_pool_read_denies_workflow_channel(self):
        server = _make_server()
        user = {"user_id": "ops", "permissions": ["pool:read"]}
        assert server._can_subscribe_to_channel(user, "workflow:wf-1") is False

    def test_worker_read_allows_worker_channel(self):
        server = _make_server()
        user = {"user_id": "ops", "permissions": ["worker:read"]}
        assert server._can_subscribe_to_channel(user, "worker:w1") is True

    def test_team_read_allows_goal_teams_channel(self):
        server = _make_server()
        user = {"user_id": "lead", "permissions": ["team:read"]}
        assert server._can_subscribe_to_channel(user, "goal-teams") is True
        assert server._can_subscribe_to_channel(user, "goal-teams:user-1") is True

    def test_team_read_denies_workflow_channel(self):
        server = _make_server()
        user = {"user_id": "lead", "permissions": ["team:read"]}
        assert server._can_subscribe_to_channel(user, "workflow:wf-1") is False

    def test_no_permissions_denies_all_channels(self):
        server = _make_server()
        user = {"user_id": "anon", "permissions": []}
        assert server._can_subscribe_to_channel(user, "workflow:x") is False
        assert server._can_subscribe_to_channel(user, "pool:y") is False
        assert server._can_subscribe_to_channel(user, "worker:z") is False
        assert server._can_subscribe_to_channel(user, "other") is False

    def test_user_without_permissions_key_denies_all(self):
        server = _make_server()
        user = {"user_id": "minimal"}
        assert server._can_subscribe_to_channel(user, "workflow:x") is False

    def test_multiple_permissions_allow_multiple_channels(self):
        server = _make_server()
        user = {"user_id": "super", "permissions": ["workflow:read", "pool:read"]}
        assert server._can_subscribe_to_channel(user, "workflow:wf-1") is True
        assert server._can_subscribe_to_channel(user, "pool:p1") is True


# ===========================================================================
# _get_pool_status
# ===========================================================================


class TestGetPoolStatus:
    """Tests for _get_pool_status."""

    @pytest.mark.asyncio
    async def test_returns_pool_info_when_available(self):
        server = _make_server()
        mock_pool = MagicMock()
        mock_pool.status = "healthy"
        mock_pool.workers = ["w1", "w2", "w3"]
        server.pool_manager.pools = {"p1": mock_pool}

        result = await server._get_pool_status("p1")
        assert result == {"pool_id": "p1", "status": "healthy", "workers": ["w1", "w2", "w3"]}

    @pytest.mark.asyncio
    async def test_returns_unknown_status_when_pool_lacks_attrs(self):
        server = _make_server()
        bare_pool = MagicMock(spec=[])
        server.pool_manager.pools = {"p1": bare_pool}

        result = await server._get_pool_status("p1")
        assert result["pool_id"] == "p1"
        assert result["status"] == "unknown"
        assert result["workers"] == []

    @pytest.mark.asyncio
    async def test_returns_not_found(self):
        server = _make_server()
        result = await server._get_pool_status("nonexistent")
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_handles_exception(self, caplog):
        server = _make_server()
        server.pool_manager.pools = MagicMock()
        server.pool_manager.pools.__contains__ = MagicMock(side_effect=RuntimeError("db error"))

        with caplog.at_level(logging.ERROR):
            result = await server._get_pool_status("p1")

        assert result["status"] == "error"
        assert "db error" in result["error"]


# ===========================================================================
# _get_workflow_status
# ===========================================================================


class TestGetWorkflowStatus:
    """Tests for _get_workflow_status."""

    @pytest.mark.asyncio
    async def test_returns_placeholder_status(self):
        server = _make_server()
        result = await server._get_workflow_status("wf-1")
        assert result["workflow_id"] == "wf-1"
        assert result["status"] == "running"
        assert result["stages_completed"] == 0
        assert result["total_stages"] == 10

    @pytest.mark.asyncio
    async def test_returns_all_expected_keys(self):
        server = _make_server()
        result = await server._get_workflow_status("wf-2")
        assert set(result.keys()) == {"workflow_id", "status", "stages_completed", "total_stages"}

    @pytest.mark.asyncio
    async def test_preserves_workflow_id_in_result(self):
        server = _make_server()
        result = await server._get_workflow_status("my-custom-wf-id")
        assert result["workflow_id"] == "my-custom-wf-id"


# ===========================================================================
# get_rate_limit_stats
# ===========================================================================


class TestGetRateLimitStats:
    """Tests for get_rate_limit_stats."""

    def test_delegates_to_rate_limiter_global_stats(self):
        server = _make_server()
        server.rate_limiter.get_stats = MagicMock(return_value={"total_connections": 0})
        result = server.get_rate_limit_stats()
        assert result == {"total_connections": 0}
        server.rate_limiter.get_stats.assert_called_once_with(None)

    def test_delegates_to_rate_limiter_with_connection_id(self):
        server = _make_server()
        server.rate_limiter.get_stats = MagicMock(return_value={"connection_id": "c1"})
        result = server.get_rate_limit_stats("c1")
        assert result == {"connection_id": "c1"}
        server.rate_limiter.get_stats.assert_called_once_with("c1")


# ===========================================================================
# leave_all_rooms
# ===========================================================================


class TestLeaveAllRooms:
    """Tests for leave_all_rooms override."""

    @pytest.mark.asyncio
    async def test_calls_parent_leave_all_rooms(self):
        server = _make_server()
        server.connection_rooms = {}
        server.room_connections = {}

        with patch.object(
            type(server).__mro__[1], "leave_all_rooms", new_callable=AsyncMock
        ) as mock_parent:
            await server.leave_all_rooms("conn-1")
            mock_parent.assert_called_once_with("conn-1")

    @pytest.mark.asyncio
    async def test_cleans_up_connection_from_all_rooms(self):
        server = _make_server()
        server.connection_rooms = {
            "room-1": {"conn-1", "conn-2"},
            "room-2": {"conn-1"},
        }
        server.room_connections = {}

        with patch.object(type(server).__mro__[1], "leave_all_rooms", new_callable=AsyncMock):
            await server.leave_all_rooms("conn-1")

        assert "conn-1" not in server.connection_rooms["room-1"]
        assert "room-2" not in server.connection_rooms  # emptied, should be removed

    @pytest.mark.asyncio
    async def test_does_not_remove_non_empty_rooms(self):
        server = _make_server()
        server.connection_rooms = {
            "room-1": {"conn-1", "conn-2"},
        }
        server.room_connections = {}

        with patch.object(type(server).__mro__[1], "leave_all_rooms", new_callable=AsyncMock):
            await server.leave_all_rooms("conn-1")

        assert "room-1" in server.connection_rooms
        assert server.connection_rooms["room-1"] == {"conn-2"}


# ===========================================================================
# _get_timestamp
# ===========================================================================


class TestGetTimestamp:
    """Tests for _get_timestamp."""

    def test_returns_iso_format_string(self):
        server = _make_server()
        ts = server._get_timestamp()
        assert isinstance(ts, str)
        assert "T" in ts  # ISO format contains T separator

    def test_timestamp_contains_timezone(self):
        server = _make_server()
        ts = server._get_timestamp()
        # UTC timestamps end with +00:00
        assert "+00:00" in ts


# ===========================================================================
# broadcast_workflow_started
# ===========================================================================


class TestBroadcastWorkflowStarted:
    """Tests for broadcast_workflow_started."""

    @pytest.mark.asyncio
    async def test_broadcasts_to_workflow_room(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_workflow_started("wf-1", {"prompt": "test"})
        server.broadcast_to_room.assert_called_once()
        call_args = server.broadcast_to_room.call_args
        assert call_args[0][0] == "workflow:wf-1"
        event = call_args[0][1]
        assert event.data["workflow_id"] == "wf-1"
        assert event.data["prompt"] == "test"
        assert "timestamp" in event.data

    @pytest.mark.asyncio
    async def test_event_has_workflow_started_type(self):
        from mcp_common.websocket.protocol import EventTypes

        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_workflow_started("wf-1", {})
        event = server.broadcast_to_room.call_args[0][1]
        assert event.event == EventTypes.WORKFLOW_STARTED


# ===========================================================================
# broadcast_workflow_stage_completed
# ===========================================================================


class TestBroadcastWorkflowStageCompleted:
    """Tests for broadcast_workflow_stage_completed."""

    @pytest.mark.asyncio
    async def test_broadcasts_stage_result(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_workflow_stage_completed("wf-1", "build", {"status": "ok"})
        server.broadcast_to_room.assert_called_once()
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["workflow_id"] == "wf-1"
        assert event.data["stage_name"] == "build"
        assert event.data["result"] == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_event_type_is_stage_completed(self):
        from mcp_common.websocket.protocol import EventTypes

        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_workflow_stage_completed("wf-1", "test", {})
        event = server.broadcast_to_room.call_args[0][1]
        assert event.event == EventTypes.WORKFLOW_STAGE_COMPLETED


# ===========================================================================
# broadcast_workflow_completed
# ===========================================================================


class TestBroadcastWorkflowCompleted:
    """Tests for broadcast_workflow_completed."""

    @pytest.mark.asyncio
    async def test_broadcasts_final_result(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_workflow_completed("wf-1", {"output": "done"})
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["workflow_id"] == "wf-1"
        assert event.data["result"] == {"output": "done"}
        assert "timestamp" in event.data

    @pytest.mark.asyncio
    async def test_event_type_is_workflow_completed(self):
        from mcp_common.websocket.protocol import EventTypes

        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_workflow_completed("wf-1", {})
        event = server.broadcast_to_room.call_args[0][1]
        assert event.event == EventTypes.WORKFLOW_COMPLETED


# ===========================================================================
# broadcast_workflow_failed
# ===========================================================================


class TestBroadcastWorkflowFailed:
    """Tests for broadcast_workflow_failed."""

    @pytest.mark.asyncio
    async def test_broadcasts_error_message(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_workflow_failed("wf-1", "OOM killed")
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["workflow_id"] == "wf-1"
        assert event.data["error"] == "OOM killed"

    @pytest.mark.asyncio
    async def test_event_type_is_workflow_failed(self):
        from mcp_common.websocket.protocol import EventTypes

        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_workflow_failed("wf-1", "err")
        event = server.broadcast_to_room.call_args[0][1]
        assert event.event == EventTypes.WORKFLOW_FAILED


# ===========================================================================
# broadcast_worker_status_changed
# ===========================================================================


class TestBroadcastWorkerStatusChanged:
    """Tests for broadcast_worker_status_changed."""

    @pytest.mark.asyncio
    async def test_broadcasts_to_pool_room(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_worker_status_changed("w1", "busy", "pool:p1")
        server.broadcast_to_room.assert_called_once()
        call_args = server.broadcast_to_room.call_args
        assert call_args[0][0] == "pool:p1"  # normalized (prefix removed)

    @pytest.mark.asyncio
    async def test_normalizes_pool_id_prefix(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_worker_status_changed("w1", "idle", "pool:my-pool")
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["pool_id"] == "my-pool"

    @pytest.mark.asyncio
    async def test_handles_pool_id_without_prefix(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_worker_status_changed("w1", "error", "my-pool")
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["pool_id"] == "my-pool"

    @pytest.mark.asyncio
    async def test_event_contains_timestamp(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_worker_status_changed("w1", "busy", "p1")
        event = server.broadcast_to_room.call_args[0][1]
        assert "timestamp" in event.data


# ===========================================================================
# broadcast_pool_status_changed
# ===========================================================================


class TestBroadcastPoolStatusChanged:
    """Tests for broadcast_pool_status_changed."""

    @pytest.mark.asyncio
    async def test_broadcasts_pool_status(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_pool_status_changed("pool:p1", {"workers": 5, "queue": 2})
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["pool_id"] == "p1"
        assert event.data["status"] == {"workers": 5, "queue": 2}

    @pytest.mark.asyncio
    async def test_normalizes_pool_id(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_pool_status_changed("pool:abc", {})
        call_args = server.broadcast_to_room.call_args
        assert call_args[0][0] == "pool:abc"


# ===========================================================================
# broadcast_team_created
# ===========================================================================


class TestBroadcastTeamCreated:
    """Tests for broadcast_team_created."""

    @pytest.mark.asyncio
    async def test_broadcasts_to_global_goal_teams_channel(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_created(
            team_id="t1",
            team_name="Alpha",
            goal="Build API",
            mode="coordinate",
        )
        # Called once for global channel
        assert server.broadcast_to_room.call_count == 1
        call_args = server.broadcast_to_room.call_args
        assert call_args[0][0] == "goal-teams"
        event = call_args[0][1]
        assert event.event == "team.created"
        assert event.data["team_id"] == "t1"
        assert event.data["team_name"] == "Alpha"
        assert event.data["goal"] == "Build API"
        assert event.data["mode"] == "coordinate"

    @pytest.mark.asyncio
    async def test_also_broadcasts_to_user_channel_when_user_id(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_created(
            team_id="t1",
            team_name="Alpha",
            goal="Build API",
            mode="coordinate",
            user_id="user-1",
        )
        assert server.broadcast_to_room.call_count == 2
        # Second call should be to user-specific channel
        second_call = server.broadcast_to_room.call_args_list[1]
        assert second_call[0][0] == "goal-teams:user-1"

    @pytest.mark.asyncio
    async def test_event_contains_timestamp(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_created("t1", "Team", "Goal", "route")
        event = server.broadcast_to_room.call_args[0][1]
        assert "timestamp" in event.data


# ===========================================================================
# broadcast_team_parsed
# ===========================================================================


class TestBroadcastTeamParsed:
    """Tests for broadcast_team_parsed."""

    @pytest.mark.asyncio
    async def test_broadcasts_parsed_goal(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_parsed(
            goal="Review code",
            intent="review",
            skills=["python", "testing"],
            confidence=0.95,
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.event == "team.parsed"
        assert event.data["goal"] == "Review code"
        assert event.data["intent"] == "review"
        assert event.data["skills"] == ["python", "testing"]
        assert event.data["confidence"] == 0.95

    @pytest.mark.asyncio
    async def test_rounds_confidence_to_three_decimals(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_parsed(
            goal="Build", intent="build", skills=[], confidence=0.123456
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["confidence"] == 0.123

    @pytest.mark.asyncio
    async def test_broadcasts_to_user_channel(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_parsed(
            goal="Test", intent="test", skills=[], confidence=0.8, user_id="u1"
        )
        assert server.broadcast_to_room.call_count == 2
        assert server.broadcast_to_room.call_args_list[1][0][0] == "goal-teams:u1"


# ===========================================================================
# broadcast_team_execution_started
# ===========================================================================


class TestBroadcastTeamExecutionStarted:
    """Tests for broadcast_team_execution_started."""

    @pytest.mark.asyncio
    async def test_broadcasts_execution_started(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_execution_started(
            team_id="t1",
            task="Run full test suite",
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.event == "team.execution_started"
        assert event.data["team_id"] == "t1"
        assert event.data["task"] == "Run full test suite"

    @pytest.mark.asyncio
    async def test_truncates_long_tasks(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        long_task = "x" * 300
        await server.broadcast_team_execution_started(team_id="t1", task=long_task)
        event = server.broadcast_to_room.call_args[0][1]
        assert len(event.data["task"]) == 200

    @pytest.mark.asyncio
    async def test_does_not_truncate_short_tasks(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        short_task = "short"
        await server.broadcast_team_execution_started(team_id="t1", task=short_task)
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["task"] == "short"

    @pytest.mark.asyncio
    async def test_broadcasts_to_user_channel(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_execution_started(team_id="t1", task="build", user_id="u1")
        assert server.broadcast_to_room.call_count == 2


# ===========================================================================
# broadcast_team_execution_completed
# ===========================================================================


class TestBroadcastTeamExecutionCompleted:
    """Tests for broadcast_team_execution_completed."""

    @pytest.mark.asyncio
    async def test_broadcasts_completion(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_execution_completed(
            team_id="t1", success=True, duration_ms=1500.0
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.event == "team.execution_completed"
        assert event.data["team_id"] == "t1"
        assert event.data["success"] is True
        assert event.data["duration_ms"] == 1500.0

    @pytest.mark.asyncio
    async def test_rounds_duration_ms(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_execution_completed(
            team_id="t1", success=False, duration_ms=1234.567
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["duration_ms"] == 1234.57

    @pytest.mark.asyncio
    async def test_broadcasts_to_user_channel(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_execution_completed(
            team_id="t1", success=True, duration_ms=100.0, user_id="u1"
        )
        assert server.broadcast_to_room.call_count == 2


# ===========================================================================
# broadcast_team_error
# ===========================================================================


class TestBroadcastTeamError:
    """Tests for broadcast_team_error."""

    @pytest.mark.asyncio
    async def test_broadcasts_error(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_error(
            team_id="t1",
            error_code="CREATION_FAILED",
            message="No skills matched",
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.event == "team.error"
        assert event.data["team_id"] == "t1"
        assert event.data["error_code"] == "CREATION_FAILED"
        assert event.data["message"] == "No skills matched"

    @pytest.mark.asyncio
    async def test_broadcasts_to_user_channel(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_error(
            team_id="t1",
            error_code="ERR",
            message="fail",
            user_id="u1",
        )
        assert server.broadcast_to_room.call_count == 2

    @pytest.mark.asyncio
    async def test_works_with_empty_team_id(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_team_error(
            team_id="",
            error_code="CREATION_FAILED",
            message="Cannot create team",
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["team_id"] == ""


# ===========================================================================
# broadcast_adapter_registered
# ===========================================================================


class TestBroadcastAdapterRegistered:
    """Tests for broadcast_adapter_registered."""

    @pytest.mark.asyncio
    async def test_broadcasts_to_adapters_channel(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_adapter_registered(
            adapter_id="a1",
            adapter_name="Prefect",
            capabilities=["orchestration", "scheduling"],
            provider="prefect",
            source="entry_point",
        )
        server.broadcast_to_room.assert_called_once()
        call_args = server.broadcast_to_room.call_args
        assert call_args[0][0] == "adapters"
        event = call_args[0][1]
        assert event.event == "adapter.registered"
        assert event.data["adapter_id"] == "a1"
        assert event.data["adapter_name"] == "Prefect"
        assert event.data["capabilities"] == ["orchestration", "scheduling"]
        assert event.data["provider"] == "prefect"
        assert event.data["source"] == "entry_point"


# ===========================================================================
# broadcast_adapter_health_changed
# ===========================================================================


class TestBroadcastAdapterHealthChanged:
    """Tests for broadcast_adapter_health_changed."""

    @pytest.mark.asyncio
    async def test_broadcasts_health_change(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_adapter_health_changed(
            adapter_id="a1",
            adapter_name="Prefect",
            old_status="healthy",
            new_status="degraded",
            details={"latency_ms": 5000},
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.event == "adapter.health_changed"
        assert event.data["adapter_id"] == "a1"
        assert event.data["old_status"] == "healthy"
        assert event.data["new_status"] == "degraded"
        assert event.data["details"] == {"latency_ms": 5000}

    @pytest.mark.asyncio
    async def test_defaults_details_to_empty_dict(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_adapter_health_changed(
            adapter_id="a1",
            adapter_name="Agno",
            old_status="healthy",
            new_status="unhealthy",
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["details"] == {}


# ===========================================================================
# broadcast_adapter_enabled
# ===========================================================================


class TestBroadcastAdapterEnabled:
    """Tests for broadcast_adapter_enabled."""

    @pytest.mark.asyncio
    async def test_broadcasts_adapter_enabled_event(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_adapter_enabled(
            adapter_id="a1",
            adapter_name="LlamaIndex",
            enabled=True,
            reason="Health restored",
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.event == "adapter.enabled"
        assert event.data["enabled"] is True
        assert event.data["reason"] == "Health restored"

    @pytest.mark.asyncio
    async def test_broadcasts_adapter_disabled_event(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_adapter_enabled(
            adapter_id="a1",
            adapter_name="LlamaIndex",
            enabled=False,
            reason="Too many errors",
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.event == "adapter.disabled"
        assert event.data["enabled"] is False

    @pytest.mark.asyncio
    async def test_reason_defaults_to_none(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_adapter_enabled(
            adapter_id="a1",
            adapter_name="Agno",
            enabled=True,
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["reason"] is None


# ===========================================================================
# broadcast_routing_decision
# ===========================================================================


class TestBroadcastRoutingDecision:
    """Tests for broadcast_routing_decision."""

    @pytest.mark.asyncio
    async def test_broadcasts_routing_decision(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_routing_decision(
            task_type="AI_TASK",
            selected_adapter="agno",
            capabilities_matched=["ai", "multi-agent"],
            latency_ms=12.5,
            fallback_used=False,
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.event == "adapter.routing_decision"
        assert event.data["task_type"] == "AI_TASK"
        assert event.data["selected_adapter"] == "agno"
        assert event.data["capabilities_matched"] == ["ai", "multi-agent"]
        assert event.data["latency_ms"] == 12.5
        assert event.data["fallback_used"] is False

    @pytest.mark.asyncio
    async def test_rounds_latency_ms(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_routing_decision(
            task_type="WORKFLOW",
            selected_adapter="prefect",
            capabilities_matched=[],
            latency_ms=3.456,
            fallback_used=True,
        )
        event = server.broadcast_to_room.call_args[0][1]
        assert event.data["latency_ms"] == 3.46

    @pytest.mark.asyncio
    async def test_broadcasts_to_adapters_channel(self):
        server = _make_server()
        server.broadcast_to_room = AsyncMock()

        await server.broadcast_routing_decision(
            task_type="TASK",
            selected_adapter="agno",
            capabilities_matched=[],
            latency_ms=1.0,
            fallback_used=False,
        )
        call_args = server.broadcast_to_room.call_args
        assert call_args[0][0] == "adapters"
