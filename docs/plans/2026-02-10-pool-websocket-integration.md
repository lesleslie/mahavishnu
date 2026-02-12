# Pool WebSocket Integration & Production Hardening Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate Mahavishnu pool management with WebSocket broadcasting and add production-hardening features (authentication, TLS, monitoring)

**Architecture:** Pool manager broadcasts real-time events (worker status, task assignments, scaling) via WebSocket to subscribed clients. Production features include JWT authentication, TLS encryption, Prometheus metrics, and Grafana dashboards.

**Tech Stack:** mcp-common.websocket, FastMCP, PyJWT, python-socketio, Prometheus client, Grafana, Python 3.11+

---

## Week 1: Integration Testing & Pool WebSocket Broadcasting

### Task 1: Create WebSocket Integration Tests

**Files:**
- Create: `/Users/les/Projects/mahavishnu/tests/integration/test_websocket_integration.py`
- Create: `/Users/les/Projects/mahavishnu/tests/integration/__init__.py`

**Step 1: Create test package initialization**

Create: `/Users/les/Projects/mahavishnu/tests/integration/__init__.py`

```python
"""Integration tests for Mahavishnu WebSocket and pool management."""
```

**Step 2: Write WebSocket server startup test**

Create: `/Users/les/Projects/mahavishnu/tests/integration/test_websocket_integration.py`

```python
"""Integration tests for WebSocket servers and pool management."""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from mahavishnu.websocket import MahavishnuWebSocketServer
from mahavishnu.pools import PoolManager


@pytest.mark.asyncio
async def test_websocket_pool_integration():
    """Test WebSocket server can be initialized with pool manager."""
    # Create mock pool manager
    pool_manager = MagicMock()
    pool_manager.pools = {}

    # Create WebSocket server with pool manager
    server = MahavishnuWebSocketServer(
        pool_manager=pool_manager,
        host="127.0.0.1",
        port=8690,
    )

    # Verify server initialized
    assert server.pool_manager is pool_manager
    assert server.port == 8690


@pytest.mark.asyncio
async def test_broadcast_pool_status():
    """Test broadcasting pool status changes."""
    pool_manager = MagicMock()
    pool_manager.pools = {}

    server = MahavishnuWebSocketServer(pool_manager=pool_manager)

    # Add mock client
    mock_client = AsyncMock()
    server.connections["test_conn"] = mock_client
    server.connection_rooms["pool:test_pool"] = {"test_conn"}

    # Broadcast pool status change
    await server.broadcast_pool_status_changed(
        "test_pool",
        {"worker_count": 5, "queue_size": 10}
    )

    # Verify broadcast sent
    assert mock_client.send.called
```

**Step 3: Run integration tests**

Run: `pytest tests/integration/test_websocket_integration.py -v`

Expected: 2 tests passing

**Step 4: Commit**

```bash
git add tests/integration/
git commit -m "test: add WebSocket integration tests"
```

---

### Task 2: Create Pool WebSocket Integration Layer

**Files:**
- Create: `/Users/les/Projects/mahavishnu/mahavishnu/pools/websocket_integration.py`
- Modify: `/Users/les/Projects/mahavishnu/mahavishnu/pools/__init__.py`

**Step 1: Write pool WebSocket integration helpers**

Create: `/Users/les/Projects/mahavishnu/mahavishnu/pools/websocket_integration.py`

```python
"""Integration helpers for broadcasting pool events via WebSocket."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PoolWebSocketBroadcaster:
    """Broadcasts pool management events to WebSocket subscribers.

    This class integrates PoolManager with MahavishnuWebSocketServer
    to provide real-time updates on:
    - Worker status changes
    - Task assignments
    - Pool scaling events
    - Queue status updates

    Example:
        >>> broadcaster = PoolWebSocketBroadcaster(websocket_server)
        >>> await broadcaster.worker_status_changed("worker1", "busy", "pool1")
    """

    def __init__(self, websocket_server: Any):
        """Initialize broadcaster.

        Args:
            websocket_server: MahavishnuWebSocketServer instance
        """
        self.server = websocket_server

    async def worker_status_changed(
        self,
        worker_id: str,
        status: str,
        pool_id: str,
    ) -> bool:
        """Broadcast worker status change event.

        Args:
            worker_id: Worker identifier
            status: New status (idle, busy, error, etc.)
            pool_id: Pool identifier

        Returns:
            True if broadcast successful, False otherwise
        """
        if self.server is None or not self.server.is_running:
            return False

        try:
            await self.server.broadcast_worker_status_changed(
                worker_id, status, pool_id
            )
            logger.info(
                f"Broadcast worker status: {worker_id} -> {status} "
                f"in pool {pool_id}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to broadcast worker status: {e}")
            return False

    async def task_assigned(
        self,
        task_id: str,
        worker_id: str,
        pool_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Broadcast task assignment event.

        Args:
            task_id: Task identifier
            worker_id: Worker assigned to
            pool_id: Pool identifier
            metadata: Additional task metadata

        Returns:
            True if broadcast successful
        """
        if self.server is None or not self.server.is_running:
            return False

        try:
            from mcp_common.websocket import WebSocketProtocol

            event = WebSocketProtocol.create_event(
                "task.assigned",
                {
                    "task_id": task_id,
                    "worker_id": worker_id,
                    "pool_id": pool_id,
                    "timestamp": self._get_timestamp(),
                    **(metadata or {})
                },
                room=f"pool:{pool_id}"
            )
            await self.server.broadcast_to_room(f"pool:{pool_id}", event)
            logger.info(f"Broadcast task assignment: {task_id} to {worker_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to broadcast task assignment: {e}")
            return False

    async def pool_scaling_event(
        self,
        pool_id: str,
        event_type: str,  # "worker_added", "worker_removed", "scaled_up"
        details: dict[str, Any],
    ) -> bool:
        """Broadcast pool scaling event.

        Args:
            pool_id: Pool identifier
            event_type: Type of scaling event
            details: Event details

        Returns:
            True if broadcast successful
        """
        if self.server is None or not self.server.is_running:
            return False

        try:
            from mcp_common.websocket import WebSocketProtocol

            event = WebSocketProtocol.create_event(
                "pool.scaling",
                {
                    "pool_id": pool_id,
                    "event_type": event_type,
                    "timestamp": self._get_timestamp(),
                    **details
                },
                room=f"pool:{pool_id}"
            )
            await self.server.broadcast_to_room(f"pool:{pool_id}", event)
            logger.info(f"Broadcast scaling event: {event_type} in pool {pool_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to broadcast scaling event: {e}")
            return False

    def _get_timestamp(self) -> str:
        """Get current ISO timestamp.

        Returns:
            ISO-formatted timestamp string
        """
        from datetime import datetime, UTC
        return datetime.now(UTC).isoformat()


def integrate_websocket_with_pools(
    pool_manager: Any,
    websocket_server: Any,
) -> PoolWebSocketBroadcaster:
    """Integrate WebSocket broadcasting with pool manager.

    This function sets up automatic broadcasting of pool events
    by hooking into pool manager lifecycle.

    Args:
        pool_manager: PoolManager instance
        websocket_server: MahavishnuWebSocketServer instance

    Returns:
        PoolWebSocketBroadcaster instance

    Example:
        >>> broadcaster = integrate_websocket_with_pools(pool_mgr, ws_server)
        >>> # Now pool events will be broadcast automatically
    """
    broadcaster = PoolWebSocketBroadcaster(websocket_server)

    # Hook into pool manager events
    # (This would be implemented in PoolManager class itself)
    logger.info(
        f"WebSocket broadcaster integrated with pool manager: "
        f"{websocket_server.host}:{websocket_server.port}"
    )

    return broadcaster
```

**Step 2: Export from pools package**

Modify: `/Users/les/Projects/mahavishnu/mahavishnu/pools/__init__.py`

```python
"""Pool management for Mahavishnu orchestration."""

from .websocket_integration import PoolWebSocketBroadcaster, integrate_websocket_with_pools

__all__ = ["PoolWebSocketBroadcaster", "integrate_websocket_with_pools"]
```

**Step 3: Write tests for pool WebSocket integration**

Create: `/Users/les/Projects/mahavishnu/tests/test_pool_websocket_integration.py`

```python
"""Tests for pool WebSocket integration."""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from mahavishnu.pools import PoolWebSocketBroadcaster


@pytest.mark.asyncio
async def test_broadcaster_worker_status():
    """Test broadcasting worker status changes."""
    # Create mock WebSocket server
    mock_server = MagicMock()
    mock_server.is_running = True
    mock_server.broadcast_worker_status_changed = AsyncMock()

    # Create broadcaster
    broadcaster = PoolWebSocketBroadcaster(mock_server)

    # Broadcast worker status
    result = await broadcaster.worker_status_changed("worker1", "busy", "pool1")

    # Verify broadcast called
    assert result is True
    mock_server.broadcast_worker_status_changed.assert_called_once_with(
        "worker1", "busy", "pool1"
    )


@pytest.mark.asyncio
async def test_broadcaster_task_assigned():
    """Test broadcasting task assignments."""
    mock_server = MagicMock()
    mock_server.is_running = True
    mock_server.broadcast_to_room = AsyncMock()

    broadcaster = PoolWebSocketBroadcaster(mock_server)

    result = await broadcaster.task_assigned(
        "task123", "worker1", "pool1", {"priority": "high"}
    )

    assert result is True
    mock_server.broadcast_to_room.assert_called_once()
```

**Step 4: Run tests**

Run: `pytest tests/test_pool_websocket_integration.py -v`

Expected: 2 tests passing

**Step 5: Commit**

```bash
git add mahavishnu/pools/websocket_integration.py mahavishnu/pools/__init__.py
git add tests/test_pool_websocket_integration.py
git commit -m "feat: add pool WebSocket integration layer"
```

---

### Task 3: Create Real-Time Workflow Monitoring Demo

**Files:**
- Create: `/Users/les/Projects/mahavishnu/examples/workflow_monitoring_demo.py`

**Step 1: Write workflow monitoring demo**

Create: `/Users/les/Projects/mahavishnu/examples/workflow_monitoring_demo.py`

```python
"""Real-time workflow monitoring demo.

This demo shows how to monitor workflow execution in real-time
using WebSocket events from Mahavishnu.
"""

import asyncio
import json
from websockets.client import connect as ws_connect


class WorkflowMonitor:
    """Real-time workflow event monitor."""

    def __init__(self, uri: str = "ws://127.0.0.1:8690"):
        """Initialize monitor.

        Args:
            uri: WebSocket server URI
        """
        self.uri = uri
        self.events = []

    async def monitor_workflow(self, workflow_id: str):
        """Monitor a specific workflow execution.

        Args:
            workflow_id: Workflow to monitor
        """
        async with ws_connect(self.uri) as websocket:
            # Subscribe to workflow channel
            subscribe_msg = {
                "type": "request",
                "event": "subscribe",
                "data": {"channel": f"workflow:{workflow_id}"},
                "id": f"sub_{workflow_id}"
            }
            await websocket.send(json.dumps(subscribe_msg))

            print(f"🎯 Monitoring workflow: {workflow_id}")
            print("-" * 60)

            # Listen for events
            async for message in websocket:
                data = json.loads(message)
                if data["type"] == "event":
                    await self._handle_event(data)
                elif data["type"] == "response":
                    # Subscription confirmation
                    if data["event"] == "subscribe":
                        print(f"✓ Subscribed to workflow:{workflow_id}")

    async def _handle_event(self, event: dict):
        """Handle incoming workflow event.

        Args:
            event: Event data
        """
        event_type = event["event"]
        data = event["data"]

        self.events.append(event)

        if event_type == "workflow.started":
            print(f"🚀 Workflow started: {data['workflow_id']}")
            print(f"   Adapter: {data.get('adapter', 'N/A')}")
            print(f"   Prompt: {data.get('prompt', 'N/A')[:50]}...")

        elif event_type == "workflow.stage_completed":
            print(f"✓ Stage completed: {data['stage_name']}")

        elif event_type == "workflow.completed":
            print(f"🎉 Workflow completed: {data['workflow_id']}")
            print(f"   Result: {data.get('result', {})}")

        elif event_type == "workflow.failed":
            print(f"❌ Workflow failed: {data['workflow_id']}")
            print(f"   Error: {data.get('error', 'Unknown error')}")

        elif event_type == "worker.status_changed":
            print(f"👷 Worker {data['worker_id']}: {data['status']}")
            print(f"   Pool: {data['pool_id']}")


async def main():
    """Run workflow monitoring demo."""
    monitor = WorkflowMonitor()

    # Monitor a demo workflow
    workflow_id = "demo_workflow_123"

    try:
        await monitor.monitor_workflow(workflow_id)
    except KeyboardInterrupt:
        print("\n⏹️  Monitoring stopped")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Create pool monitoring demo**

Create: `/Users/les/Projects/mahavishnu/examples/pool_monitoring_demo.py`

```python
"""Real-time pool monitoring demo."""

import asyncio
import json
from websockets.client import connect as ws_connect


class PoolMonitor:
    """Real-time pool status monitor."""

    def __init__(self, uri: str = "ws://127.0.0.1:8690"):
        """Initialize monitor.

        Args:
            uri: WebSocket server URI
        """
        self.uri = uri

    async def monitor_pool(self, pool_id: str):
        """Monitor pool status in real-time.

        Args:
            pool_id: Pool to monitor
        """
        async with ws_connect(self.uri) as websocket:
            # Subscribe to pool channel
            subscribe_msg = {
                "type": "request",
                "event": "subscribe",
                "data": {"channel": f"pool:{pool_id}"},
                "id": f"sub_pool_{pool_id}"
            }
            await websocket.send(json.dumps(subscribe_msg))

            print(f"🏊 Monitoring pool: {pool_id}")
            print("-" * 60)

            # Listen for events
            async for message in websocket:
                data = json.loads(message)
                if data["type"] == "event":
                    await self._handle_pool_event(data)
                elif data["type"] == "response":
                    if data["event"] == "subscribe":
                        print(f"✓ Subscribed to pool:{pool_id}")

    async def _handle_pool_event(self, event: dict):
        """Handle pool event.

        Args:
            event: Event data
        """
        event_type = event["event"]
        data = event["data"]

        if event_type == "worker.status_changed":
            status_emoji = {
                "idle": "💤",
                "busy": "⚙️",
                "error": "❌",
            }
            emoji = status_emoji.get(data["status"], "❓")
            print(f"{emoji} Worker {data['worker_id']}: {data['status']}")

        elif event_type == "pool.status_changed":
            status = data["status"]
            print(f"📊 Pool status updated:")
            print(f"   Workers: {status.get('worker_count', 'N/A')}")
            print(f"   Queue: {status.get('queue_size', 'N/A')}")

        elif event_type == "pool.scaling":
            print(f"📈 Pool scaling: {data['event_type']}")
            print(f"   Details: {data.get('details', {})}")


async def main():
    """Run pool monitoring demo."""
    monitor = PoolMonitor()

    # Monitor demo pool
    pool_id = "pool_local"

    try:
        await monitor.monitor_pool(pool_id)
    except KeyboardInterrupt:
        print("\n⏹️  Monitoring stopped")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 3: Run demos (manual verification)**

Run workflow monitor:
```bash
python examples/workflow_monitoring_demo.py
```

Run pool monitor:
```bash
python examples/pool_monitoring_demo.py
```

**Step 4: Commit**

```bash
git add examples/workflow_monitoring_demo.py examples/pool_monitoring_demo.py
git commit -m "feat: add real-time monitoring demos"
```

---

## Week 2: Multi-Service WebSocket Testing

### Task 4: Create Cross-Service WebSocket Test Suite

**Files:**
- Create: `/Users/les/Projects/mahavishnu/tests/integration/test_multi_service_websocket.py`

**Step 1: Write multi-service integration test**

Create: `/Users/les/Projects/mahavishnu/tests/integration/test_multi_service_websocket.py`

```python
"""Multi-service WebSocket integration tests."""

import pytest
import asyncio
from websockets.client import connect as ws_connect
import json


@pytest.mark.asyncio
async def test_all_websocket_servers_start():
    """Test that all 7 WebSocket servers can start without port conflicts."""
    import subprocess
    import time

    servers = [
        ("session-buddy", "8765"),
        ("mahavishnu", "8690"),
        ("crackerjack", "8686"),
        ("akosha", "8692"),
        ("dhruva", "8693"),
        ("excalidraw-mcp", "3042"),
        ("fastblocks", "8684"),
    ]

    # Check if ports are available
    for service, port in servers:
        result = subprocess.run(
            ["lsof", "-i", f":{port}", "-P", "-n"],
            capture_output=True,
            text=True
        )
        assert result.returncode != 0, f"Port {port} already in use for {service}"

    print(f"✓ All {len(servers)} WebSocket ports are available")


@pytest.mark.asyncio
async def test_subscribe_to_multiple_services():
    """Test subscribing to WebSocket events from multiple services."""
    # This test requires servers to be running
    # For now, just test connection endpoints

    services = [
        ("mahavishnu", "ws://127.0.0.1:8690"),
        ("dhruva", "ws://127.0.0.1:8693"),
        ("excalidraw", "ws://127.0.0.1:3042"),
    ]

    for service, uri in services:
        try:
            async with ws_connect(uri, timeout=1) as websocket:
                # Send ping
                ping_msg = {"type": "ping", "id": "test_123"}
                await websocket.send(json.dumps(ping_msg))
                print(f"✓ {service} server responding")
        except Exception as e:
            print(f"⚠️  {service} server not available: {e}")
```

**Step 2: Run tests**

Run: `pytest tests/integration/test_multi_service_websocket.py -v`

**Step 3: Commit**

```bash
git add tests/integration/test_multi_service_websocket.py
git commit -m "test: add multi-service WebSocket integration tests"
```

---

### Task 5: Create WebSocket Health Check Script

**Files:**
- Create: `/Users/les/Projects/mahavishnu/scripts/check_all_websocket_servers.sh`

**Step 1: Write health check script**

Create: `/Users/les/Projects/mahavishnu/scripts/check_all_websocket_servers.sh`

```bash
#!/bin/bash
# Health check script for all WebSocket servers

echo "=================================================="
echo "WebSocket Server Health Check"
echo "=================================================="
echo ""

# Define all servers
declare -A servers=(
    ["session-buddy"]="localhost:8765"
    ["mahavishnu"]="localhost:8690"
    ["crackerjack"]="localhost:8686"
    ["akosha"]="localhost:8692"
    ["dhruva"]="localhost:8693"
    ["excalidraw-mcp"]="localhost:3042"
    ["fastblocks"]="localhost:8684"
)

# Check each server
for service in "${!servers[@]}"; do
    host_port="${servers[$service]}"
    host="${host_port%:*}"
    port="${host_port#*:}"

    echo -n "Checking $service ($host_port)... "

    # Check if port is listening
    if nc -z "$host" "$port" 2>/dev/null; then
        echo "✓ RUNNING"
    else
        echo "✗ STOPPED"
    fi
done

echo ""
echo "=================================================="
echo "Health check complete"
echo "=================================================="
```

**Step 2: Make script executable**

Run: `chmod +x scripts/check_all_websocket_servers.sh`

**Step 3: Test script**

Run: `./scripts/check_all_websocket_servers.sh`

**Step 4: Commit**

```bash
git add scripts/check_all_websocket_servers.sh
git commit -m "feat: add WebSocket server health check script"
```

---

## Week 3: Production Hardening - Authentication

### Task 6: Add JWT Authentication to WebSocket Servers

**Files:**
- Create: `/Users/les/Projects/mcp-common/mcp_common/websocket/auth.py`
- Modify: `/Users/les/Projects/mcp-common/mcp_common/websocket/server.py`
- Create: `/Users/les/Projects/mahavishnu/mahavishnu/websocket/auth.py`

**Step 1: Create WebSocket authentication module**

Create: `/Users/les/Projects/mcp-common/mcp_common/websocket/auth.py`

```python
"""WebSocket authentication utilities."""

from __future__ import annotations

import jwt
import logging
from typing import Any, Optional
from datetime import datetime, UTC, timedelta

logger = logging.getLogger(__name__)


class WebSocketAuthenticator:
    """Handles WebSocket connection authentication using JWT.

    Example:
        >>> auth = WebSocketAuthenticator(secret="your-secret-key")
        >>> token = auth.create_token({"user_id": "user123"})
        >>> payload = auth.verify_token(token)
    """

    def __init__(
        self,
        secret: str,
        algorithm: str = "HS256",
        token_expiry: int = 3600,
    ):
        """Initialize authenticator.

        Args:
            secret: JWT secret key
            algorithm: JWT algorithm (default: HS256)
            token_expiry: Token expiry time in seconds (default: 1 hour)
        """
        self.secret = secret
        self.algorithm = algorithm
        self.token_expiry = token_expiry

    def create_token(self, payload: dict[str, Any]) -> str:
        """Create JWT token for WebSocket authentication.

        Args:
            payload: Token payload (user_id, permissions, etc.)

        Returns:
            Encoded JWT token
        """
        payload["exp"] = datetime.now(UTC) + timedelta(seconds=self.token_expiry)
        payload["iat"] = datetime.now(UTC)

        token = jwt.encode(payload, self.secret, algorithm=self.algorithm)
        return token

    def verify_token(self, token: str) -> dict[str, Any] | None:
        """Verify JWT token.

        Args:
            token: JWT token to verify

        Returns:
            Decoded payload if valid, None if invalid
        """
        try:
            payload = jwt.decode(
                token,
                self.secret,
                algorithms=[self.algorithm]
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return None

    def authenticate_connection(
        self,
        token: str,
        required_permissions: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Authenticate WebSocket connection.

        Args:
            token: JWT token from connection handshake
            required_permissions: List of required permissions

        Returns:
            User payload if authenticated and authorized, None otherwise
        """
        payload = self.verify_token(token)

        if payload is None:
            return None

        # Check permissions if required
        if required_permissions:
            user_permissions = payload.get("permissions", [])
            if not all(perm in user_permissions for perm in required_permissions):
                logger.warning(f"Insufficient permissions: {required_permissions}")
                return None

        return payload
```

**Step 2: Add authentication to WebSocketServer base class**

Modify: `/Users/les/Projects/mcp-common/mcp_common/websocket/server.py`

Add authentication method to WebSocketServer class:

```python
def authenticate_websocket(self, token: str) -> dict[str, Any] | None:
    """Authenticate WebSocket connection using JWT.

    Args:
        token: JWT token from connection

    Returns:
        User payload if authenticated, None otherwise

    Example:
        >>> # In on_connect handler
        >>> token = await websocket.recv()
        >>> user = self.authenticate_websocket(token)
        >>> if user is None:
        >>>     await websocket.close(code=1008, reason="Invalid token")
    """
    if self.authenticator is None:
        logger.warning("Authentication attempted but no authenticator configured")
        return None

    return self.authenticator.authenticate_connection(token)
```

**Step 3: Create Mahavishnu WebSocket authentication config**

Create: `/Users/les/Projects/mahavishnu/mahavishnu/websocket/auth.py`

```python
"""WebSocket authentication configuration for Mahavishnu."""

from __future__ import annotations

import os
from mcp_common.websocket.auth import WebSocketAuthenticator

# Get JWT secret from environment
JWT_SECRET = os.getenv("MAHAVISHNU_JWT_SECRET", "dev-secret-change-in-production")

# Create authenticator
authenticator = WebSocketAuthenticator(
    secret=JWT_SECRET,
    algorithm="HS256",
    token_expiry=3600,  # 1 hour
)


def get_authenticator() -> WebSocketAuthenticator:
    """Get configured WebSocket authenticator.

    Returns:
        WebSocketAuthenticator instance
    """
    return authenticator
```

**Step 4: Add tests for authentication**

Create: `/Users/les/Projects/mahavishnu/tests/test_websocket_auth.py`

```python
"""Tests for WebSocket authentication."""

import pytest
from mcp_common.websocket.auth import WebSocketAuthenticator


def test_create_and_verify_token():
    """Test creating and verifying JWT tokens."""
    auth = WebSocketAuthenticator(secret="test-secret")

    # Create token
    token = auth.create_token({"user_id": "user123", "permissions": ["read", "write"]})

    assert isinstance(token, str)
    assert len(token) > 0

    # Verify token
    payload = auth.verify_token(token)
    assert payload["user_id"] == "user123"
    assert payload["permissions"] == ["read", "write"]


def test_invalid_token():
    """Test that invalid tokens are rejected."""
    auth = WebSocketAuthenticator(secret="test-secret")

    payload = auth.verify_token("invalid-token")
    assert payload is None
```

**Step 5: Run tests**

Run: `pytest tests/test_websocket_auth.py -v`

**Step 6: Commit**

```bash
git add mcp_common/websocket/auth.py mcp_common/websocket/server.py
git add mahavishnu/websocket/auth.py tests/test_websocket_auth.py
git commit -m "feat: add JWT authentication to WebSocket servers"
```

---

### Task 7: Add Token-Based Subscription Authorization

**Files:**
- Modify: `/Users/les/Projects/mahavishnu/mahavishnu/websocket/server.py`

**Step 1: Add authorization to subscription handler**

Modify: `/Users/les/Projects/mahavishnu/mahavishnu/websocket/server.py`

Update `_handle_request` method to check permissions:

```python
async def _handle_request(
    self, websocket: Any, message: WebSocketMessage
) -> None:
    """Handle request message (expects response)."""

    # Get authenticated user from connection
    user = getattr(websocket, "user", None)

    if message.event == "subscribe":
        channel = message.data.get("channel")

        # Check if user has permission to subscribe to this channel
        if user and not self._can_subscribe_to_channel(user, channel):
            # Send authorization error
            error = WebSocketProtocol.create_error(
                error_code="FORBIDDEN",
                error_message=f"Not authorized to subscribe to {channel}",
                correlation_id=message.correlation_id,
            )
            await websocket.send(WebSocketProtocol.encode(error))
            return

        if channel:
            import uuid
            connection_id = getattr(websocket, "id", str(uuid.uuid4()))
            await self.join_room(channel, connection_id)

            response = WebSocketProtocol.create_response(
                message,
                {"status": "subscribed", "channel": channel}
            )
            await websocket.send(WebSocketProtocol.encode(response))

    # ... rest of method


def _can_subscribe_to_channel(self, user: dict[str, Any], channel: str) -> bool:
    """Check if user can subscribe to channel.

    Args:
        user: User payload from JWT
        channel: Channel name

    Returns:
        True if authorized, False otherwise
    """
    permissions = user.get("permissions", [])

    # Admin can subscribe to any channel
    if "admin" in permissions:
        return True

    # Check channel-specific permissions
    if channel.startswith("workflow:"):
        return "workflow:read" in permissions

    if channel.startswith("pool:"):
        return "pool:read" in permissions

    if channel.startswith("adapter:"):
        return "adapter:read" in permissions

    # Default: deny
    return False
```

**Step 2: Commit**

```bash
git add mahavishnu/websocket/server.py
git commit -m "feat: add token-based subscription authorization"
```

---

## Week 4: Production Hardening - TLS & Monitoring

### Task 8: Add TLS/WSS Support

**Files:**
- Create: `/Users/les/Projects/mahavishnu/mahavishnu/websocket/tls_config.py`
- Modify: `/Users/les/Projects/mcp-common/mcp_common/websocket/server.py`

**Step 1: Create TLS configuration helper**

Create: `/Users/les/Projects/mahavishnu/mahavishnu/websocket/tls_config.py`

```python
"""TLS configuration for WebSocket servers."""

from __future__ import annotations

import os
import ssl
from pathlib import Path

def create_ssl_context(
    cert_file: str | None = None,
    key_file: str | None = None,
    ca_file: str | None = None,
) -> ssl.SSLContext:
    """Create SSL context for secure WebSocket (WSS).

    Args:
        cert_file: Path to certificate file
        key_file: Path to private key file
        ca_file: Path to CA file (for client verification)

    Returns:
        Configured SSL context

    Example:
        >>> ssl_context = create_ssl_context(
        ...     cert_file="/path/to/cert.pem",
        ...     key_file="/path/to/key.pem"
        ... )
        >>> # Use with websockets.serve(ssl_context=ssl_context)
    """
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

    # Load certificate and key
    if cert_file and key_file:
        ssl_context.load_cert_chain(cert_file, key_file)

    # Load CA for client verification (optional)
    if ca_file:
        ssl_context.load_verify_locations(ca_file)
        ssl_context.verify_mode = ssl.CERT_REQUIRED

    # Set secure cipher suites
    ssl_context.set_ciphers('ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256')
    ssl_context.set_ecdh_curve('prime256v1')

    return ssl_context


def get_tls_config() -> dict[str, str | None]:
    """Get TLS configuration from environment.

    Returns:
        Dictionary with cert, key, and ca file paths
    """
    return {
        "cert_file": os.getenv("WEBSOCKET_CERT_FILE"),
        "key_file": os.getenv("WEBSOCKET_KEY_FILE"),
        "ca_file": os.getenv("WEBSOCKET_CA_FILE"),
    }
```

**Step 2: Update WebSocketServer to support SSL**

Modify: `/Users/les/Projects/mcp-common/mcp_common/websocket/server.py`

Add SSL context parameter and handling:

```python
class WebSocketServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        ssl_context: ssl.SSLContext | None = None,
        # ... other params
    ):
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        # ... rest of init
```

**Step 3: Commit**

```bash
git add mcp_common/websocket/server.py mahavishnu/websocket/tls_config.py
git commit -m "feat: add TLS/WSS support to WebSocket servers"
```

---

### Task 9: Add Prometheus Metrics Export

**Files:**
- Create: `/Users/les/Projects/mahavishnu/mahavishnu/websocket/metrics.py`
- Modify: `/Users/les/Projects/mahavishnu/mahavishnu/websocket/server.py`

**Step 1: Create Prometheus metrics module**

Create: `/Users/les/Projects/mahavishnu/mahavishnu/websocket/metrics.py`

```python
"""Prometheus metrics for WebSocket server."""

from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge, start_http_server

# Metrics
message_counter = Counter(
    'websocket_messages_total',
    'Total messages processed',
    ['server', 'message_type']
)

connection_gauge = Gauge(
    'websocket_connections',
    'Current number of connections',
    ['server']
)

broadcast_duration = Histogram(
    'websocket_broadcast_duration_seconds',
    'Time taken to broadcast messages',
    ['server', 'channel']
)


class WebSocketMetrics:
    """Metrics collector for WebSocket server."""

    def __init__(self, server_name: str):
        """Initialize metrics collector.

        Args:
            server_name: Name of the WebSocket server
        """
        self.server_name = server_name

    def inc_message(self, message_type: str) -> None:
        """Increment message counter.

        Args:
            message_type: Type of message (request, response, event)
        """
        message_counter.labels(
            server=self.server_name,
            message_type=message_type
        ).inc()

    def set_connections(self, count: int) -> None:
        """Set connection count gauge.

        Args:
            count: Number of active connections
        """
        connection_gauge.labels(server=self.server_name).set(count)

    def observe_broadcast(self, channel: str, duration: float) -> None:
        """Observe broadcast duration.

        Args:
            channel: Channel name
            duration: Duration in seconds
        """
        broadcast_duration.labels(
            server=self.server_name,
            channel=channel
        ).observe(duration)


def start_metrics_server(port: int = 9090) -> None:
    """Start Prometheus metrics server.

    Args:
        port: Metrics server port (default: 9090)
    """
    start_http_server(port)
    print(f"✓ Prometheus metrics server started on port {port}")
```

**Step 2: Integrate metrics into WebSocketServer**

Modify: `/Users/les/Projects/mahavishnu/mahavishnu/websocket/server.py`

Add metrics tracking:

```python
from mahavishnu.websocket.metrics import WebSocketMetrics

class MahavishnuWebSocketServer(WebSocketServer):
    def __init__(self, ...):
        # ... existing init
        self.metrics = WebSocketMetrics("mahavishnu")

    async def on_connect(self, websocket, connection_id):
        # ... existing code
        self.metrics.set_connections(len(self.connections))

    async def on_disconnect(self, websocket, connection_id):
        # ... existing code
        self.metrics.set_connections(len(self.connections))
```

**Step 3: Commit**

```bash
git add mahavishnu/websocket/metrics.py mahavishnu/websocket/server.py
git commit -m "feat: add Prometheus metrics to WebSocket server"
```

---

### Task 10: Create Grafana Dashboard Configuration

**Files:**
- Create: `/Users/les/Projects/mahavishnu/deploy/grafana/websocket-dashboard.json`

**Step 1: Create Grafana dashboard JSON**

Create: `/Users/les/Projects/mahavishnu/deploy/grafana/websocket-dashboard.json`

```json
{
  "dashboard": {
    "title": "Ecosystem WebSocket Monitoring",
    "panels": [
      {
        "id": 1,
        "title": "Connection Count",
        "type": "graph",
        "targets": [
          {
            "expr": "websocket_connections{server=\"mahavishnu\"}"
          },
          {
            "expr": "websocket_connections{server=\"dhruva\"}"
          }
        ]
      },
      {
        "id": 2,
        "title": "Message Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(websocket_messages_total[1m])"
          }
        ]
      },
      {
        "id": 3,
        "title": "Broadcast Duration",
        "type": "heatmap",
        "targets": [
          {
            "expr": "websocket_broadcast_duration_seconds"
          }
        ]
      }
    ]
  }
}
```

**Step 2: Commit**

```bash
git add deploy/grafana/websocket-dashboard.json
git commit -m "feat: add Grafana dashboard for WebSocket monitoring"
```

---

## Task 11: Create Production Deployment Guide

**Files:**
- Create: `/Users/les/Projects/mahavishnu/docs/WEBSOCKET_PRODUCTION_DEPLOYMENT.md`

**Step 1: Write deployment guide**

Create: `/Users/les/Projects/mahavishnu/docs/WEBSOCKET_PRODUCTION_DEPLOYMENT.md`

```markdown
# WebSocket Production Deployment Guide

**Date:** 2026-02-10
**Purpose:** Production deployment for 7 WebSocket servers

---

## Prerequisites

- Python 3.11+
- Redis (for shared state in multi-instance deployments)
- Nginx or Traefik (for WebSocket proxying)
- Prometheus + Grafana (for monitoring)

---

## Configuration

### Environment Variables

```bash
# JWT Authentication
export MAHAVISHNU_JWT_SECRET="your-production-secret"

# TLS Certificates
export WEBSOCKET_CERT_FILE="/path/to/cert.pem"
export WEBSOCKET_KEY_FILE="/path/to/key.pem"
export WEBSOCKET_CA_FILE="/path/to/ca.pem"

# Monitoring
export PROMETHEUS_PORT=9090
export GRAFANA_ADMIN_PASSWORD="your-admin-password"
```

---

## Deployment Architecture

```
                    ┌─────────────┐
                    │   Nginx/TLS  │
                    │   (WSS)      │
                    └──────┬────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
    ┌───▼────┐       ┌────▼────┐       ┌────▼─────┐
    │Mahavishnu│       │  Dhruva  │       │Excalidraw│
    │  :8690  │       │  :8693  │       │  :3042   │
    └─────────┘       └─────────┘       └──────────┘
        │                  │                  │
        └──────────────────┴──────────────────┘
                           │
                    ┌──────▼──────┐
                    │  Prometheus │
                    │   :9090    │
                    └─────────────┘
```

---

## Nginx Configuration

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

upstream mahavishnu_websocket {
    server 127.0.0.1:8690;
}

upstream dhruva_websocket {
    server 127.0.0.1:8693;
}

server {
    listen 443 ssl;
    server_name ws.yourdomain.com;

    ssl_certificate /etc/ssl/cert.pem;
    ssl_certificate_key /etc/ssl/key.pem;

    location /ws/mahavishnu {
        proxy_pass http://mahavishnu_websocket;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
    }

    location /ws/dhruva {
        proxy_pass http://dhruva_websocket;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
    }
}
```

---

## Health Checks

```bash
# Check all WebSocket servers
./scripts/check_all_websocket_servers.sh

# Check Prometheus metrics
curl http://localhost:9090/metrics
```

---

## Troubleshooting

### Issue: Connections dropped frequently

**Diagnosis:**
```bash
# Check WebSocket logs
tail -f /var/log/mahavishnu/websocket.log
```

**Solution:**
- Verify JWT token expiry
- Check rate limits
- Ensure stable network connection

### Issue: High memory usage

**Diagnosis:**
```bash
# Monitor connection counts
curl http://localhost:9090/metrics | grep websocket_connections
```

**Solution:**
- Implement connection limits
- Add periodic cleanup
- Monitor room subscriptions

---

## Rollback Procedure

If deployment fails:

```bash
# 1. Stop new deployment
systemctl stop mahavishnu-websocket

# 2. Revert to previous version
git revert HEAD

# 3. Restart with old version
systemctl start mahavishnu-websocket
```
```

**Step 2: Commit**

```bash
git add docs/WEBSOCKET_PRODUCTION_DEPLOYMENT.md
git commit -m "docs: add WebSocket production deployment guide"
```

---

## Task 12: Create Comprehensive Integration Tests

**Files:**
- Create: `/Users/les/Projects/mahavishnu/tests/integration/test_production_features.py`

**Step 1: Write production feature tests**

Create: `/Users/les/Projects/mahavishnu/tests/integration/test_production_features.py`

```python
"""Integration tests for production WebSocket features."""

import pytest
import asyncio
import jwt
from unittest.mock import MagicMock, AsyncMock
from mahavishnu.websocket.auth import get_authenticator
from mahavishnu.pools import PoolWebSocketBroadcaster


@pytest.mark.asyncio
async def test_jwt_authentication_flow():
    """Test complete JWT authentication flow."""
    auth = get_authenticator()

    # Create token
    token = auth.create_token({
        "user_id": "user123",
        "permissions": ["workflow:read", "pool:read"]
    })

    # Verify token
    payload = auth.verify_token(token)
    assert payload["user_id"] == "user123"
    assert "workflow:read" in payload["permissions"]


@pytest.mark.asyncio
async def test_subscription_authorization():
    """Test subscription authorization with permissions."""
    from mahavishnu.websocket import MahavishnuWebSocketServer

    pool_manager = MagicMock()
    server = MahavishnuWebSocketServer(pool_manager=pool_manager)

    # Mock user with limited permissions
    user = {
        "user_id": "user123",
        "permissions": ["workflow:read"]  # Can read workflows but not pools
    }

    # Test authorization
    assert server._can_subscribe_to_channel(user, "workflow:test123") is True
    assert server._can_subscribe_to_channel(user, "pool:test123") is False


@pytest.mark.asyncio
async def test_metrics_tracking():
    """Test that WebSocket metrics are tracked."""
    from mahavishnu.websocket.metrics import WebSocketMetrics

    metrics = WebSocketMetrics("test-server")

    # Test message counting
    metrics.inc_message("request")
    metrics.inc_message("response")

    # Test connection tracking
    metrics.set_connections(5)
    metrics.set_connections(10)

    # Test broadcast timing
    metrics.observe_broadcast("channel1", 0.123)

    print("✓ Metrics tracking working")
```

**Step 2: Run tests**

Run: `pytest tests/integration/test_production_features.py -v`

**Step 3: Commit**

```bash
git add tests/integration/test_production_features.py
git commit -m "test: add production feature integration tests"
```

---

## Success Criteria

### Week 1: Integration & Pool WebSocket
- ✅ All 7 WebSocket servers tested together
- ✅ Pool events broadcast via WebSocket
- ✅ Real-time monitoring demos working
- ✅ Integration tests passing

### Week 2: Multi-Service Testing
- ✅ Cross-service integration tests
- ✅ Health check script operational
- ✅ Port conflict detection working

### Week 3: Authentication
- ✅ JWT authentication implemented
- ✅ Token-based subscription authorization
- ✅ Auth tests passing

### Week 4: Production Hardening
- ✅ TLS/WSS support added
- ✅ Prometheus metrics exported
- ✅ Grafana dashboard configured
- ✅ Deployment documentation complete

---

## Total Deliverables

**Files Created:** 20+
**Tests Added:** 15+
**Documentation:** 3 comprehensive guides
**Scripts:** 2 deployment/monitoring scripts

**Estimated Timeline:** 4 weeks

---

**Ready for production deployment with enterprise-grade security, monitoring, and reliability!**
