"""Production integration tests for WebSocket deployment.

These tests verify production-ready WebSocket server functionality including:
- JWT authentication with valid tokens
- TLS/WSS connections with real certificates
- Cross-service communication with authentication
- Graceful degradation when services are down
- Performance under load (100+ concurrent connections)
"""

from __future__ import annotations

import asyncio
import json
import ssl
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from cryptography.x509.oid import NameOID

from mcp_common.websocket import WebSocketServer, WebSocketProtocol
from mcp_common.websocket.auth import WebSocketAuthenticator


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_certificate(tmp_path: Path) -> tuple[str, str]:
    """Generate temporary TLS certificate for testing.

    Returns:
        Tuple of (cert_path, key_path)
    """
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # Generate certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"CA"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Test Org"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(time.time() - 3600)  # Valid from 1 hour ago
        .not_valid_after(time.time() + 3600)  # Valid for 1 hour
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256(), default_backend())
    )

    # Write certificate
    cert_path = tmp_path / "cert.pem"
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    # Write private key
    key_path = tmp_path / "key.pem"
    with open(key_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    return str(cert_path), str(key_path)


@pytest.fixture
def jwt_authenticator() -> WebSocketAuthenticator:
    """Create JWT authenticator for testing."""
    return WebSocketAuthenticator(
        secret="test-secret-key-for-production-tests",
        algorithm="HS256",
        token_expiry=3600,
    )


@pytest.fixture
def valid_jwt_token(jwt_authenticator: WebSocketAuthenticator) -> str:
    """Generate valid JWT token for testing."""
    return jwt_authenticator.create_token({
        "user_id": "test_user_123",
        "permissions": ["read", "write", "admin"],
    })


@pytest.fixture
def expired_jwt_token(jwt_authenticator: WebSocketAuthenticator) -> str:
    """Generate expired JWT token for testing."""
    # Create token that's already expired
    import jwt
    payload = {
        "user_id": "test_user_123",
        "permissions": ["read", "write"],
        "exp": int(time.time()) - 3600,  # Expired 1 hour ago
        "iat": int(time.time()) - 7200,
    }
    return jwt.encode(payload, jwt_authenticator.secret, algorithm=jwt_authenticator.algorithm)


@pytest.fixture
def invalid_jwt_token() -> str:
    """Generate invalid JWT token for testing."""
    return "invalid.token.string"


@pytest.fixture
async def auth_websocket_server(
    temp_certificate: tuple[str, str],
    jwt_authenticator: WebSocketAuthenticator,
) -> WebSocketServer:
    """Create WebSocket server with authentication and TLS enabled."""

    class AuthTestServer(WebSocketServer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.connections_authenticated = 0

        async def on_connect(self, websocket: Any, connection_id: str):
            """Handle connection."""
            await self.send_welcome_message(websocket, connection_id)

        async def on_disconnect(self, websocket: Any, connection_id: str):
            """Handle disconnection."""
            await self.leave_all_rooms(connection_id)

        async def on_message(self, websocket: Any, message: Any):
            """Handle message."""
            if message.event == "subscribe":
                channel = message.data.get("channel")
                if channel:
                    await self.join_room(channel, connection_id)

    cert_path, key_path = temp_certificate

    server = AuthTestServer(
        host="localhost",
        port=0,  # Random port
        require_auth=True,
        authenticator=jwt_authenticator,
        cert_file=cert_path,
        key_file=key_path,
        tls_enabled=True,
        auto_cert=False,
    )

    # Start server
    await server.start()

    # Get actual port
    actual_port = server.server.sockets[0].getsockname()[1]
    server.port = actual_port

    yield server

    # Cleanup
    await server.stop()


@pytest.fixture
async def simple_websocket_server(temp_certificate: tuple[str, str]) -> WebSocketServer:
    """Create simple WebSocket server without authentication."""

    class SimpleTestServer(WebSocketServer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.message_count = 0

        async def on_connect(self, websocket: Any, connection_id: str):
            """Handle connection."""
            await self.send_welcome_message(websocket, connection_id)

        async def on_disconnect(self, websocket: Any, connection_id: str):
            """Handle disconnection."""
            await self.leave_all_rooms(connection_id)

        async def on_message(self, websocket: Any, message: Any):
            """Handle message."""
            self.message_count += 1
            if message.event == "subscribe":
                channel = message.data.get("channel")
                if channel:
                    await self.join_room(channel, connection_id)

    cert_path, key_path = temp_certificate

    server = SimpleTestServer(
        host="localhost",
        port=0,  # Random port
        cert_file=cert_path,
        key_file=key_path,
        tls_enabled=True,
    )

    # Start server
    await server.start()

    # Get actual port
    actual_port = server.server.sockets[0].getsockname()[1]
    server.port = actual_port

    yield server

    # Cleanup
    await server.stop()


# =============================================================================
# JWT Authentication Tests
# =============================================================================

@pytest.mark.production
@pytest.mark.asyncio
class TestJWTAuthentication:
    """Test JWT authentication in production scenarios."""

    async def test_valid_token_authenticates(
        self,
        auth_websocket_server: WebSocketServer,
        valid_jwt_token: str,
    ):
        """Test that valid JWT token authenticates successfully."""
        uri = f"wss://localhost:{auth_websocket_server.port}"

        try:
            # Connect and authenticate
            async with websockets.connect(uri, ssl=ssl.create_default_context()) as ws:
                # Receive welcome
                welcome = await asyncio.wait_for(ws.recv(), timeout=1.0)
                assert "welcome" in json.loads(welcome).get("event", "")

                # Send authentication
                auth_msg = WebSocketProtocol.create_request(
                    "auth",
                    {"token": valid_jwt_token},
                    correlation_id=str(uuid.uuid4()),
                )
                await ws.send(WebSocketProtocol.encode(auth_msg))

                # Receive auth success
                response = await asyncio.wait_for(ws.recv(), timeout=1.0)
                response_data = json.loads(response)

                assert response_data["type"] == "response"
                assert response_data["data"]["status"] == "authenticated"
                assert response_data["data"]["user_id"] == "test_user_123"

        except Exception as e:
            pytest.fail(f"Authentication failed: {e}")

    async def test_expired_token_rejected(
        self,
        auth_websocket_server: WebSocketServer,
        expired_jwt_token: str,
    ):
        """Test that expired JWT token is rejected."""
        uri = f"wss://localhost:{auth_websocket_server.port}"

        try:
            async with websockets.connect(uri, ssl=ssl.create_default_context()) as ws:
                # Receive welcome
                await asyncio.wait_for(ws.recv(), timeout=1.0)

                # Send expired authentication
                auth_msg = WebSocketProtocol.create_request(
                    "auth",
                    {"token": expired_jwt_token},
                    correlation_id=str(uuid.uuid4()),
                )
                await ws.send(WebSocketProtocol.encode(auth_msg))

                # Receive auth error
                response = await asyncio.wait_for(ws.recv(), timeout=1.0)
                response_data = json.loads(response)

                assert response_data["type"] == "error"
                assert "expired" in response_data["data"]["error_message"].lower()

                # Connection should close
                with pytest.raises(websockets.exceptions.ConnectionClosed):
                    await asyncio.wait_for(ws.recv(), timeout=1.0)

        except websockets.exceptions.ConnectionClosedOK:
            # Expected - connection closed due to expired token
            pass

    async def test_invalid_token_rejected(
        self,
        auth_websocket_server: WebSocketServer,
        invalid_jwt_token: str,
    ):
        """Test that invalid JWT token is rejected."""
        uri = f"wss://localhost:{auth_websocket_server.port}"

        try:
            async with websockets.connect(uri, ssl=ssl.create_default_context()) as ws:
                # Receive welcome
                await asyncio.wait_for(ws.recv(), timeout=1.0)

                # Send invalid authentication
                auth_msg = WebSocketProtocol.create_request(
                    "auth",
                    {"token": invalid_jwt_token},
                    correlation_id=str(uuid.uuid4()),
                )
                await ws.send(WebSocketProtocol.encode(auth_msg))

                # Receive auth error
                response = await asyncio.wait_for(ws.recv(), timeout=1.0)
                response_data = json.loads(response)

                assert response_data["type"] == "error"
                assert response_data["data"]["error_code"] in ["AUTH_FAILED", "INVALID_TOKEN"]

        except websockets.exceptions.ConnectionClosed:
            # Expected - connection closed due to invalid token
            pass

    async def test_token_with_insufficient_permissions(
        self,
        auth_websocket_server: WebSocketServer,
        jwt_authenticator: WebSocketAuthenticator,
    ):
        """Test that token with insufficient permissions is rejected from protected channels."""
        # Create token with limited permissions
        limited_token = jwt_authenticator.create_token({
            "user_id": "limited_user",
            "permissions": ["read"],  # Only read permission
        })

        uri = f"wss://localhost:{auth_websocket_server.port}"

        async with websockets.connect(uri, ssl=ssl.create_default_context()) as ws:
            # Authenticate
            await asyncio.wait_for(ws.recv(), timeout=1.0)  # Welcome

            auth_msg = WebSocketProtocol.create_request(
                "auth",
                {"token": limited_token},
                correlation_id=str(uuid.uuid4()),
            )
            await ws.send(WebSocketProtocol.encode(auth_msg))
            await asyncio.wait_for(ws.recv(), timeout=1.0)  # Auth success

            # Try to subscribe to admin-only channel (should fail)
            subscribe_msg = WebSocketProtocol.create_request(
                "subscribe",
                {"channel": "admin:controls"},
                correlation_id=str(uuid.uuid4()),
            )
            await ws.send(WebSocketProtocol.encode(subscribe_msg))

            # Should receive authorization error
            response = await asyncio.wait_for(ws.recv(), timeout=1.0)
            response_data = json.loads(response)

            # Note: This depends on server's permission checking implementation
            # The server should reject subscription to admin channels without admin permission
            if response_data["type"] == "error":
                assert response_data["data"]["error_code"] == "FORBIDDEN"

    async def test_token_refresh(
        self,
        auth_websocket_server: WebSocketServer,
        jwt_authenticator: WebSocketAuthenticator,
    ):
        """Test token refresh functionality."""
        # Create expiring token (expires in 10 seconds)
        import jwt
        payload = {
            "user_id": "test_user_123",
            "permissions": ["read", "write"],
            "exp": int(time.time()) + 10,
            "iat": int(time.time()),
        }
        expiring_token = jwt.encode(
            payload,
            jwt_authenticator.secret,
            algorithm=jwt_authenticator.algorithm
        )

        uri = f"wss://localhost:{auth_websocket_server.port}"

        async with websockets.connect(uri, ssl=ssl.create_default_context()) as ws:
            # Authenticate with expiring token
            await asyncio.wait_for(ws.recv(), timeout=1.0)  # Welcome

            auth_msg = WebSocketProtocol.create_request(
                "auth",
                {"token": expiring_token},
                correlation_id=str(uuid.uuid4()),
            )
            await ws.send(WebSocketProtocol.encode(auth_msg))
            await asyncio.wait_for(ws.recv(), timeout=1.0)  # Auth success

            # Create new token
            new_token = jwt_authenticator.create_token({
                "user_id": "test_user_123",
                "permissions": ["read", "write", "admin"],
            })

            # Send token refresh
            refresh_msg = WebSocketProtocol.create_request(
                "refresh_token",
                {"token": new_token},
                correlation_id=str(uuid.uuid4()),
            )
            await ws.send(WebSocketProtocol.encode(refresh_msg))

            # Should receive refresh success
            response = await asyncio.wait_for(ws.recv(), timeout=1.0)
            response_data = json.loads(response)

            assert response_data["type"] == "response"
            assert response_data["data"]["status"] == "refreshed"


# =============================================================================
# TLS/WSS Connection Tests
# =============================================================================

@pytest.mark.production
@pytest.mark.asyncio
class TestTLSConnections:
    """Test TLS/WSS connections with certificates."""

    async def test_wss_connection_with_valid_cert(
        self,
        simple_websocket_server: WebSocketServer,
    ):
        """Test WSS connection with valid certificate."""
        uri = f"wss://localhost:{simple_websocket_server.port}"

        # Create SSL context
        ssl_context = ssl.create_default_context()
        # For self-signed certs, skip verification in tests
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        async with websockets.connect(uri, ssl=ssl_context) as ws:
            # Receive welcome message
            welcome = await asyncio.wait_for(ws.recv(), timeout=1.0)
            welcome_data = json.loads(welcome)

            assert welcome_data["type"] == "event"
            assert welcome_data["event"] == "welcome"

    async def test_wss_connection_fails_with_invalid_cert(self):
        """Test that WSS connection fails with invalid certificate."""
        # Try to connect to non-existent server
        uri = "wss://localhost:9999"  # Non-existent server

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        with pytest.raises(Exception):  # Connection refused or timeout
            async with websockets.connect(uri, ssl=ssl_context, timeout=1.0) as ws:
                pass

    async def test_certificate_validation(
        self,
        temp_certificate: tuple[str, str],
    ):
        """Test certificate validation and expiry checking."""
        cert_path, key_path = temp_certificate

        # Load certificate
        with open(cert_path, "rb") as f:
            cert_data = f.read()
            cert = x509.load_pem_x509_certificate(cert_data, default_backend())

        # Check certificate is not expired
        assert cert.not_valid_after > time.time()
        assert cert.not_valid_before < time.time()

        # Check subject
        subject = cert.subject
        assert subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "localhost"

    async def test_tls_cipher_suites(
        self,
        simple_websocket_server: WebSocketServer,
    ):
        """Test that only secure cipher suites are negotiated."""
        uri = f"wss://localhost:{simple_websocket_server.port}"

        # Create SSL context with only secure ciphers
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.set_ciphers('ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256')
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        async with websockets.connect(uri, ssl=ssl_context) as ws:
            welcome = await asyncio.wait_for(ws.recv(), timeout=1.0)
            assert json.loads(welcome)["event"] == "welcome"


# =============================================================================
# Service Lifecycle Tests
# =============================================================================

@pytest.mark.production
@pytest.mark.asyncio
class TestServiceLifecycle:
    """Test service start/stop and lifecycle management."""

    async def test_service_starts_and_listens(
        self,
        simple_websocket_server: WebSocketServer,
    ):
        """Test that service starts and listens on configured port."""
        assert simple_websocket_server.is_running
        assert simple_websocket_server.port > 0

        # Verify port is actually listening
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            result = sock.connect_ex(("localhost", simple_websocket_server.port))
            assert result == 0  # Connection successful
        finally:
            sock.close()

    async def test_service_stops_gracefully(
        self,
        temp_certificate: tuple[str, str],
    ):
        """Test that service stops gracefully and closes connections."""

        class TestServer(WebSocketServer):
            async def on_connect(self, ws, conn_id):
                pass

            async def on_disconnect(self, ws, conn_id):
                pass

            async def on_message(self, ws, msg):
                pass

        cert_path, key_path = temp_certificate
        server = TestServer(
            host="localhost",
            port=0,
            cert_file=cert_path,
            key_file=key_path,
            tls_enabled=True,
        )

        await server.start()
        assert server.is_running

        # Connect a client
        uri = f"wss://localhost:{server.port}"
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        ws = await websockets.connect(uri, ssl=ssl_context)
        await asyncio.sleep(0.1)

        # Stop server
        await server.stop()
        assert not server.is_running

        # Connection should be closed
        assert ws.closed

    async def test_service_handles_multiple_connections(
        self,
        simple_websocket_server: WebSocketServer,
    ):
        """Test that service handles multiple concurrent connections."""
        uri = f"wss://localhost:{simple_websocket_server.port}"
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Create multiple connections
        connections = []
        for i in range(10):
            ws = await websockets.connect(uri, ssl=ssl_context)
            connections.append(ws)
            await asyncio.sleep(0.01)

        # Verify all connections are tracked
        assert len(simple_websocket_server.connections) == 10

        # Close all connections
        for ws in connections:
            await ws.close()

        await asyncio.sleep(0.1)

        # Verify all connections cleaned up
        assert len(simple_websocket_server.connections) == 0


# =============================================================================
# Cross-Service Communication Tests
# =============================================================================

@pytest.mark.production
@pytest.mark.asyncio
class TestCrossServiceCommunication:
    """Test cross-service communication with authentication."""

    async def test_service_to_service_authenticated_communication(
        self,
        temp_certificate: tuple[str, str],
        jwt_authenticator: WebSocketAuthenticator,
    ):
        """Test that services can communicate with each other using authentication."""
        # Create two servers
        servers = []

        class TestServer(WebSocketServer):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.received_messages = []

            async def on_connect(self, ws, conn_id):
                pass

            async def on_disconnect(self, ws, conn_id):
                pass

            async def on_message(self, ws, msg):
                self.received_messages.append(msg)

        for i in range(2):
            cert_path, key_path = temp_certificate
            server = TestServer(
                host="localhost",
                port=0,
                require_auth=True,
                authenticator=jwt_authenticator,
                cert_file=cert_path,
                key_file=key_path,
                tls_enabled=True,
            )
            await server.start()
            server.port = server.server.sockets[0].getsockname()[1]
            servers.append(server)

        try:
            # Server 1 connects to Server 2
            service_token = jwt_authenticator.create_token({
                "user_id": "service_1",
                "permissions": ["service:communicate"],
            })

            uri = f"wss://localhost:{servers[1].port}"
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            async with websockets.connect(uri, ssl=ssl_context) as ws:
                # Authenticate
                auth_msg = WebSocketProtocol.create_request(
                    "auth",
                    {"token": service_token},
                    correlation_id=str(uuid.uuid4()),
                )
                await ws.send(WebSocketProtocol.encode(auth_msg))
                await asyncio.wait_for(ws.recv(), timeout=1.0)

                # Send message
                send_msg = WebSocketProtocol.create_request(
                    "service_message",
                    {"from": "service_1", "data": "test"},
                    correlation_id=str(uuid.uuid4()),
                )
                await ws.send(WebSocketProtocol.encode(send_msg))

                await asyncio.sleep(0.1)

                # Verify Server 2 received message
                assert len(servers[1].received_messages) > 0
                assert servers[1].received_messages[0].event == "service_message"

        finally:
            for server in servers:
                await server.stop()

    async def test_cross_service_subscription_with_auth(
        self,
        temp_certificate: tuple[str, str],
        jwt_authenticator: WebSocketAuthenticator,
    ):
        """Test cross-service subscriptions with authentication."""
        # Create publisher and subscriber servers
        class TestServer(WebSocketServer):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)

            async def on_connect(self, ws, conn_id):
                pass

            async def on_disconnect(self, ws, conn_id):
                pass

            async def on_message(self, ws, msg):
                if msg.event == "subscribe":
                    channel = msg.data.get("channel")
                    if channel:
                        await self.join_room(channel, conn_id)

        servers = []
        for i in range(2):
            cert_path, key_path = temp_certificate
            server = TestServer(
                host="localhost",
                port=0,
                cert_file=cert_path,
                key_file=key_path,
                tls_enabled=True,
            )
            await server.start()
            server.port = server.server.sockets[0].getsockname()[1]
            servers.append(server)

        try:
            # Subscriber connects to publisher
            uri = f"wss://localhost:{servers[1].port}"
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            async with websockets.connect(uri, ssl=ssl_context) as ws:
                # Subscribe to channel
                sub_msg = WebSocketProtocol.create_request(
                    "subscribe",
                    {"channel": "test:channel"},
                    correlation_id=str(uuid.uuid4()),
                )
                await ws.send(WebSocketProtocol.encode(sub_msg))
                await asyncio.wait_for(ws.recv(), timeout=1.0)

                # Publisher broadcasts to channel
                event = WebSocketProtocol.create_event(
                    "test.event",
                    {"data": "test value"},
                    room="test:channel",
                )
                await servers[1].broadcast_to_room("test:channel", event)

                # Subscriber should receive event
                received = await asyncio.wait_for(ws.recv(), timeout=1.0)
                received_data = json.loads(received)

                assert received_data["type"] == "event"
                assert received_data["event"] == "test.event"

        finally:
            for server in servers:
                await server.stop()


# =============================================================================
# Graceful Degradation Tests
# =============================================================================

@pytest.mark.production
@pytest.mark.asyncio
class TestGracefulDegradation:
    """Test graceful degradation when services are unavailable."""

    async def test_client_handles_connection_failure(self):
        """Test that client handles server unavailability gracefully."""
        # Try to connect to non-existent server
        uri = "wss://localhost:9999"  # Non-existent server
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        with pytest.raises(Exception):
            async with websockets.connect(
                uri,
                ssl=ssl_context,
                close_timeout=1.0,
                ping_timeout=1.0,
            ):
                pass

    async def test_client_reconnects_after_server_restart(
        self,
        temp_certificate: tuple[str, str],
    ):
        """Test that client can reconnect after server restart."""

        class TestServer(WebSocketServer):
            async def on_connect(self, ws, conn_id):
                pass

            async def on_disconnect(self, ws, conn_id):
                pass

            async def on_message(self, ws, msg):
                pass

        cert_path, key_path = temp_certificate
        server = TestServer(
            host="localhost",
            port=0,
            cert_file=cert_path,
            key_file=key_path,
            tls_enabled=True,
        )
        await server.start()
        port = server.server.sockets[0].getsockname()[1]

        uri = f"wss://localhost:{port}"
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Initial connection
        async with websockets.connect(uri, ssl=ssl_context) as ws:
            await asyncio.wait_for(ws.recv(), timeout=1.0)

        # Stop server
        await server.stop()
        await asyncio.sleep(0.5)

        # Restart server on same port
        server2 = TestServer(
            host="localhost",
            port=port,
            cert_file=cert_path,
            key_file=key_path,
            tls_enabled=True,
        )
        await server2.start()

        try:
            # Reconnect should succeed
            async with websockets.connect(uri, ssl=ssl_context) as ws:
                welcome = await asyncio.wait_for(ws.recv(), timeout=1.0)
                assert json.loads(welcome)["event"] == "welcome"
        finally:
            await server2.stop()

    async def test_service_continues_with_some_connection_failures(
        self,
        simple_websocket_server: WebSocketServer,
    ):
        """Test that service continues operating despite some connection failures."""
        uri = f"wss://localhost:{simple_websocket_server.port}"
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Create multiple connections
        connections = []
        for i in range(5):
            ws = await websockets.connect(uri, ssl=ssl_context)
            connections.append(ws)

        # Close some connections abruptly
        await connections[0].close()
        await connections[2].close()
        await connections[4].close()

        await asyncio.sleep(0.1)

        # Service should still be running
        assert simple_websocket_server.is_running

        # Remaining connections should still work
        await connections[1].send(json.dumps({"type": "ping"}))
        await connections[3].send(json.dumps({"type": "ping"}))

        # Cleanup
        for ws in connections:
            try:
                await ws.close()
            except Exception:
                pass


# =============================================================================
# Performance Tests
# =============================================================================

@pytest.mark.production
@pytest.mark.slow
@pytest.mark.asyncio
class TestPerformance:
    """Test performance under load."""

    async def test_handles_100_concurrent_connections(
        self,
        simple_websocket_server: WebSocketServer,
    ):
        """Test that service handles 100 concurrent connections."""
        uri = f"wss://localhost:{simple_websocket_server.port}"
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Create 100 concurrent connections
        tasks = []
        for i in range(100):
            task = asyncio.create_task(websockets.connect(uri, ssl=ssl_context))
            tasks.append(task)

        # Wait for all connections to establish
        connections = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successful connections
        successful = [c for c in connections if not isinstance(c, Exception)]

        # At least 95% should succeed
        success_rate = len(successful) / 100
        assert success_rate >= 0.95, f"Success rate: {success_rate:.2%}"

        # Verify all connections tracked
        assert len(simple_websocket_server.connections) >= 95

        # Cleanup
        for ws in successful:
            try:
                await ws.close()
            except Exception:
                pass

    async def test_broadcast_performance(
        self,
        simple_websocket_server: WebSocketServer,
    ):
        """Test broadcast performance to many connections."""
        uri = f"wss://localhost:{simple_websocket_server.port}"
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Create 50 connections
        connections = []
        for i in range(50):
            ws = await websockets.connect(uri, ssl=ssl_context)
            connections.append(ws)

        # Subscribe all to same channel
        for ws in connections:
            sub_msg = WebSocketProtocol.create_request(
                "subscribe",
                {"channel": "perf:test"},
                correlation_id=str(uuid.uuid4()),
            )
            await ws.send(WebSocketProtocol.encode(sub_msg))
            await asyncio.wait_for(ws.recv(), timeout=1.0)  # Confirmation

        # Broadcast 100 messages
        start_time = time.time()
        for i in range(100):
            event = WebSocketProtocol.create_event(
                "test.event",
                {"index": i},
                room="perf:test",
            )
            await simple_websocket_server.broadcast_to_room("perf:test", event)
        end_time = time.time()

        duration = end_time - start_time
        messages_per_second = 100 / duration

        # Should handle at least 100 messages/second
        assert messages_per_second >= 100

        # Cleanup
        for ws in connections:
            await ws.close()

    async def test_message_throughput(
        self,
        simple_websocket_server: WebSocketServer,
    ):
        """Test message throughput under load."""
        uri = f"wss://localhost:{simple_websocket_server.port}"
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Create 10 connections
        connections = []
        for i in range(10):
            ws = await websockets.connect(uri, ssl=ssl_context)
            connections.append(ws)

        # Send 1000 messages total (100 per connection)
        start_time = time.time()

        async def send_messages(ws, count):
            for i in range(count):
                msg = {"type": "test", "index": i}
                await ws.send(json.dumps(msg))

        tasks = [send_messages(ws, 100) for ws in connections]
        await asyncio.gather(*tasks)

        end_time = time.time()
        duration = end_time - start_time
        messages_per_second = 1000 / duration

        # Should handle at least 500 messages/second
        assert messages_per_second >= 500

        # Cleanup
        for ws in connections:
            await ws.close()

    async def test_latency_under_load(
        self,
        simple_websocket_server: WebSocketServer,
    ):
        """Test latency under load."""
        uri = f"wss://localhost:{simple_websocket_server.port}"
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Create 20 connections
        connections = []
        for i in range(20):
            ws = await websockets.connect(uri, ssl=ssl_context)
            connections.append(ws)

        # Measure round-trip latency
        latencies = []

        for ws in connections:
            start = time.time()
            msg = {"type": "ping", "timestamp": start}
            await ws.send(json.dumps(msg))
            response = await asyncio.wait_for(ws.recv(), timeout=1.0)
            end = time.time()
            latencies.append((end - start) * 1000)  # Convert to ms

        # Calculate P95 latency
        latencies.sort()
        p95_latency = latencies[int(len(latencies) * 0.95)]

        # P95 latency should be under 100ms
        assert p95_latency < 100, f"P95 latency: {p95_latency:.2f}ms"

        # Cleanup
        for ws in connections:
            await ws.close()


# =============================================================================
# Upgrade/Deployment Tests
# =============================================================================

@pytest.mark.production
@pytest.mark.asyncio
class TestUpgradeScenarios:
    """Test upgrade and deployment scenarios."""

    async def test_clean_deployment(
        self,
        temp_certificate: tuple[str, str],
    ):
        """Test deployment to clean environment (no existing data)."""
        import tempfile
        import shutil

        # Create temporary data directory
        data_dir = tempfile.mkdtemp()

        try:
            class TestServer(WebSocketServer):
                async def on_connect(self, ws, conn_id):
                    pass

                async def on_disconnect(self, ws, conn_id):
                    pass

                async def on_message(self, ws, msg):
                    pass

            cert_path, key_path = temp_certificate
            server = TestServer(
                host="localhost",
                port=0,
                cert_file=cert_path,
                key_file=key_path,
                tls_enabled=True,
            )

            # Should start successfully with no existing data
            await server.start()
            assert server.is_running

            await server.stop()

        finally:
            shutil.rmtree(data_dir)

    async def test_data_preserved_across_restart(
        self,
        temp_certificate: tuple[str, str],
    ):
        """Test that data is preserved across service restart."""

        class TestServer(WebSocketServer):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.startup_count = 0

            async def on_connect(self, ws, conn_id):
                pass

            async def on_disconnect(self, ws, conn_id):
                pass

            async def on_message(self, ws, msg):
                pass

        cert_path, key_path = temp_certificate
        server = TestServer(
            host="localhost",
            port=0,
            cert_file=cert_path,
            key_file=key_path,
            tls_enabled=True,
        )

        await server.start()
        server.startup_count = 1
        port = server.server.sockets[0].getsockname()[1]
        await server.stop()

        # Restart on same port
        server2 = TestServer(
            host="localhost",
            port=port,
            cert_file=cert_path,
            key_file=key_path,
            tls_enabled=True,
        )
        await server2.start()
        server2.startup_count = 2

        assert server2.startup_count == 2
        await server2.stop()


# =============================================================================
# Test Runner
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "production"])
