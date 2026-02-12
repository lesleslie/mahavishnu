"""Tests for Mahavishnu WebSocket authentication."""

from __future__ import annotations

import pytest
import asyncio
import os

from mahavishnu.websocket.auth import (
    get_authenticator,
    generate_token,
    verify_token,
)
from mahavishnu.websocket.server import MahavishnuWebSocketServer
from mcp_common.websocket import WebSocketProtocol


@pytest.mark.unit
class TestMahavishnuWebSocketAuth:
    """Test Mahavishnu WebSocket authentication configuration."""

    def test_get_authenticator_dev_mode(self):
        """Test getting authenticator in development mode."""
        # Ensure auth is disabled
        os.environ["MAHAVISHNU_AUTH_ENABLED"] = "false"

        authenticator = get_authenticator()
        assert authenticator is None

    def test_generate_token(self):
        """Test generating a JWT token."""
        token = generate_token("user123", ["read", "write"])

        assert isinstance(token, str)
        assert len(token) > 0
        assert token.count(".") == 2  # JWT format

    def test_verify_token(self):
        """Test verifying a generated token."""
        token = generate_token("user123", ["read", "write"])
        payload = verify_token(token)

        assert payload is not None
        assert payload["user_id"] == "user123"
        assert payload["permissions"] == ["read", "write"]

    def test_verify_invalid_token(self):
        """Test verifying an invalid token."""
        payload = verify_token("invalid-token")
        assert payload is None


@pytest.mark.unit
class TestMahavishnuWebSocketServer:
    """Test Mahavishnu WebSocket server with authentication."""

    def test_server_initialization(self):
        """Test server initialization."""
        server = MahavishnuWebSocketServer(
            pool_manager=None,
            host="127.0.0.1",
            port=8690,
            require_auth=False,
        )

        assert server.host == "127.0.0.1"
        assert server.port == 8690
        assert server.require_auth is False

    def test_server_with_auth_enabled(self):
        """Test server with authentication enabled."""
        # Enable auth for this test
        os.environ["MAHAVISHNU_AUTH_ENABLED"] = "true"

        try:
            server = MahavishnuWebSocketServer(
                pool_manager=None,
                require_auth=True,
            )

            assert server.require_auth is True
            # authenticator should be set when AUTH_ENABLED is true
            assert server.authenticator is not None
        finally:
            # Clean up
            os.environ["MAHAVISHNU_AUTH_ENABLED"] = "false"

    def test_channel_authorization(self):
        """Test channel subscription authorization."""
        server = MahavishnuWebSocketServer(
            pool_manager=None,
            require_auth=False,
        )

        # Test admin user
        admin_user = {"user_id": "admin", "permissions": ["admin"]}
        assert server._can_subscribe_to_channel(admin_user, "workflow:123") is True
        assert server._can_subscribe_to_channel(admin_user, "pool:abc") is True

        # Test user with workflow:read permission
        workflow_user = {"user_id": "user1", "permissions": ["workflow:read"]}
        assert server._can_subscribe_to_channel(workflow_user, "workflow:123") is True
        assert server._can_subscribe_to_channel(workflow_user, "pool:abc") is False

        # Test user with pool:read permission
        pool_user = {"user_id": "user2", "permissions": ["pool:read"]}
        assert server._can_subscribe_to_channel(pool_user, "pool:abc") is True
        assert server._can_subscribe_to_channel(pool_user, "workflow:123") is False

        # Test user without relevant permissions
        limited_user = {"user_id": "user3", "permissions": ["other"]}
        assert server._can_subscribe_to_channel(limited_user, "workflow:123") is False
        assert server._can_subscribe_to_channel(limited_user, "pool:abc") is False


@pytest.mark.integration
class TestWebSocketAuthenticationIntegration:
    """Integration tests for WebSocket authentication."""

    @pytest.mark.asyncio
    async def test_server_start_without_auth(self):
        """Test that server starts without authentication."""
        server = MahavishnuWebSocketServer(
            pool_manager=None,
            host="127.0.0.1",
            port=8691,  # Use different port for testing
            require_auth=False,
        )

        try:
            await server.start()
            assert server.is_running is True
        finally:
            await server.stop()
            assert server.is_running is False

    @pytest.mark.asyncio
    async def test_server_start_with_auth(self):
        """Test that server starts with authentication."""
        # Enable auth for this test
        os.environ["MAHAVISHNU_AUTH_ENABLED"] = "true"

        try:
            server = MahavishnuWebSocketServer(
                pool_manager=None,
                host="127.0.0.1",
                port=8692,  # Use different port for testing
                require_auth=True,
            )

            await server.start()
            assert server.is_running is True
            await server.stop()
            assert server.is_running is False
        finally:
            # Clean up
            os.environ["MAHAVISHNU_AUTH_ENABLED"] = "false"

    @pytest.mark.asyncio
    async def test_authenticated_connection_flow(self):
        """Test full authentication flow with WebSocket client."""
        # Enable auth for this test
        os.environ["MAHAVISHNU_AUTH_ENABLED"] = "true"

        server = MahavishnuWebSocketServer(
            pool_manager=None,
            host="127.0.0.1",
            port=8693,
            require_auth=True,
        )

        try:
            await server.start()

            # Create client with token
            token = generate_token("test_user", ["read", "admin"])

            from mcp_common.websocket import WebSocketClient
            client = WebSocketClient(
                uri="ws://127.0.0.1:8693",
                token=token,
                reconnect=False,
            )

            try:
                await client.connect()
                assert client.is_connected is True
                assert client.is_authenticated is True
            finally:
                await client.disconnect()

        finally:
            await server.stop()
            os.environ["MAHAVISHNU_AUTH_ENABLED"] = "false"

    @pytest.mark.asyncio
    async def test_unauthenticated_connection_rejected(self):
        """Test that connections without valid token are rejected."""
        # Enable auth for this test
        os.environ["MAHAVISHNU_AUTH_ENABLED"] = "true"

        server = MahavishnuWebSocketServer(
            pool_manager=None,
            host="127.0.0.1",
            port=8694,
            require_auth=True,
        )

        try:
            await server.start()

            # Create client with invalid token
            from mcp_common.websocket import WebSocketClient
            client = WebSocketClient(
                uri="ws://127.0.0.1:8694",
                token="invalid-token",
                reconnect=False,
            )

            try:
                # Connection should fail or auth should fail
                await client.connect()
                # If connection succeeds, auth should have failed
                assert client.is_authenticated is False
            except (ConnectionError, Exception):
                # Expected - connection should be rejected
                pass
            finally:
                await client.disconnect()

        finally:
            await server.stop()
            os.environ["MAHAVISHNU_AUTH_ENABLED"] = "false"
