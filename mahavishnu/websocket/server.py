"""WebSocket server for Mahavishnu workflow orchestration.

This module implements a WebSocket server that broadcasts real-time updates
about workflow execution, worker pool status, and orchestration events.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from mcp_common.websocket import (
    MessageType,
    WebSocketMessage,
    WebSocketProtocol,
    WebSocketServer,
)

# Import EventTypes from protocol module
from mcp_common.websocket.protocol import EventTypes

# Import authentication
from mahavishnu.websocket.auth import get_authenticator

logger = logging.getLogger(__name__)


class MahavishnuWebSocketServer(WebSocketServer):
    """WebSocket server for Mahavishnu orchestration updates.

    Broadcasts real-time events for:
    - Workflow execution (started, stage_completed, completed, failed)
    - Worker pool status changes
    - Task assignments and completions
    - System orchestration metrics

    Channels:
    - workflow:{workflow_id} - Workflow-specific updates
    - pool:{pool_id} - Pool status updates
    - worker:{worker_id} - Worker-specific events
    - global - System-wide orchestration events

    Attributes:
        pool_manager: PoolManager instance for orchestration state
        host: Server host address
        port: Server port number (default: 8690)

    Example:
        >>> from mahavishnu.pools import PoolManager
        >>> from mahavishnu.websocket import MahavishnuWebSocketServer
        >>>
        >>> pool_mgr = PoolManager()
        >>> server = MahavishnuWebSocketServer(pool_manager=pool_mgr)
        >>> await server.start()
    """

    def __init__(
        self,
        pool_manager: Any,
        host: str = "127.0.0.1",
        port: int = 8690,
        max_connections: int = 1000,
        message_rate_limit: int = 100,
        require_auth: bool = False,
    ):
        """Initialize Mahavishnu WebSocket server.

        Args:
            pool_manager: PoolManager instance for orchestration state
            host: Server host address (default: "127.0.0.1")
            port: Server port number (default: 8690)
            max_connections: Maximum concurrent connections (default: 1000)
            message_rate_limit: Messages per second per connection (default: 100)
            require_auth: Require JWT authentication for connections
        """
        authenticator = get_authenticator()

        super().__init__(
            host=host,
            port=port,
            max_connections=max_connections,
            message_rate_limit=message_rate_limit,
            authenticator=authenticator,
            require_auth=require_auth,
        )

        self.pool_manager = pool_manager
        logger.info(
            f"MahavishnuWebSocketServer initialized: {host}:{port}"
        )

    async def on_connect(self, websocket: Any, connection_id: str) -> None:
        """Handle new WebSocket connection.

        Args:
            websocket: WebSocket connection object
            connection_id: Unique connection identifier
        """
        user = getattr(websocket, "user", None)
        user_id = user.get("user_id") if user else "anonymous"

        logger.info(f"Client connected: {connection_id} (user: {user_id})")

        # Send welcome message
        welcome = WebSocketProtocol.create_event(
            EventTypes.SESSION_CREATED,
            {
                "connection_id": connection_id,
                "server": "mahavishnu",
                "message": "Connected to Mahavishnu orchestration",
                "authenticated": user is not None,
            },
        )
        await websocket.send(WebSocketProtocol.encode(welcome))

    async def on_disconnect(self, websocket: Any, connection_id: str) -> None:
        """Handle WebSocket disconnection.

        Args:
            websocket: WebSocket connection object
            connection_id: Unique connection identifier
        """
        logger.info(f"Client disconnected: {connection_id}")

        # Clean up room subscriptions
        await self.leave_all_rooms(connection_id)

    async def on_message(self, websocket: Any, message: WebSocketMessage) -> None:
        """Handle incoming WebSocket message.

        Args:
            websocket: WebSocket connection object
            message: Decoded message
        """
        if message.type == MessageType.REQUEST:
            await self._handle_request(websocket, message)
        elif message.type == MessageType.EVENT:
            await self._handle_event(websocket, message)
        else:
            logger.warning(f"Unhandled message type: {message.type}")

    async def _handle_request(
        self, websocket: Any, message: WebSocketMessage
    ) -> None:
        """Handle request message (expects response).

        Args:
            websocket: WebSocket connection object
            message: Request message
        """
        # Get authenticated user from connection
        user = getattr(websocket, "user", None)

        if message.event == "subscribe":
            channel = message.data.get("channel")

            # Check authorization for this channel
            if user and not self._can_subscribe_to_channel(user, channel):
                error = WebSocketProtocol.create_error(
                    error_code="FORBIDDEN",
                    error_message=f"Not authorized to subscribe to {channel}",
                    correlation_id=message.correlation_id,
                )
                await websocket.send(WebSocketProtocol.encode(error))
                return

            if channel:
                connection_id = getattr(websocket, "id", str(uuid.uuid4()))
                await self.join_room(channel, connection_id)

                # Send confirmation
                response = WebSocketProtocol.create_response(
                    message,
                    {"status": "subscribed", "channel": channel}
                )
                await websocket.send(WebSocketProtocol.encode(response))

        elif message.event == "unsubscribe":
            channel = message.data.get("channel")
            if channel:
                connection_id = getattr(websocket, "id", str(uuid.uuid4()))
                await self.leave_room(channel, connection_id)

                # Send confirmation
                response = WebSocketProtocol.create_response(
                    message,
                    {"status": "unsubscribed", "channel": channel}
                )
                await websocket.send(WebSocketProtocol.encode(response))

        elif message.event == "get_pool_status":
            pool_id = message.data.get("pool_id")
            if pool_id and self.pool_manager:
                status = await self._get_pool_status(pool_id)
                response = WebSocketProtocol.create_response(message, status)
                await websocket.send(WebSocketProtocol.encode(response))

        elif message.event == "get_workflow_status":
            workflow_id = message.data.get("workflow_id")
            if workflow_id and self.pool_manager:
                status = await self._get_workflow_status(workflow_id)
                response = WebSocketProtocol.create_response(message, status)
                await websocket.send(WebSocketProtocol.encode(response))

        else:
            # Unknown request
            error = WebSocketProtocol.create_error(
                error_code="UNKNOWN_REQUEST",
                error_message=f"Unknown request event: {message.event}",
                correlation_id=message.correlation_id,
            )
            await websocket.send(WebSocketProtocol.encode(error))

    async def _handle_event(self, websocket: Any, message: WebSocketMessage) -> None:
        """Handle event message (no response expected).

        Args:
            websocket: WebSocket connection object
            message: Event message
        """
        # Client-sent events (e.g., client-side updates)
        logger.debug(f"Received client event: {message.event}")
        # Can be used for client telemetry, etc.

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

        if channel.startswith("worker:"):
            return "worker:read" in permissions

        # Default: deny
        return False

    async def _get_pool_status(self, pool_id: str) -> dict:
        """Get pool status from pool manager.

        Args:
            pool_id: Pool identifier

        Returns:
            Pool status dictionary
        """
        try:
            if hasattr(self.pool_manager, "pools") and pool_id in self.pool_manager.pools:
                pool = self.pool_manager.pools[pool_id]
                return {
                    "pool_id": pool_id,
                    "status": pool.status if hasattr(pool, "status") else "unknown",
                    "workers": pool.workers if hasattr(pool, "workers") else [],
                }
            else:
                return {"pool_id": pool_id, "status": "not_found"}
        except Exception as e:
            logger.error(f"Error getting pool status: {e}")
            return {"pool_id": pool_id, "status": "error", "error": str(e)}

    async def _get_workflow_status(self, workflow_id: str) -> dict:
        """Get workflow status.

        Args:
            workflow_id: Workflow identifier

        Returns:
            Workflow status dictionary
        """
        try:
            # Query workflow status from pool manager or storage
            # This is a placeholder - implementation depends on workflow tracking
            return {
                "workflow_id": workflow_id,
                "status": "running",  # Placeholder
                "stages_completed": 0,
                "total_stages": 10,
            }
        except Exception as e:
            logger.error(f"Error getting workflow status: {e}")
            return {"workflow_id": workflow_id, "status": "error", "error": str(e)}

    # Broadcast methods for orchestration events

    async def broadcast_workflow_started(
        self, workflow_id: str, metadata: dict
    ) -> None:
        """Broadcast workflow started event.

        Args:
            workflow_id: Workflow identifier
            metadata: Workflow metadata (prompt, adapter, etc.)
        """
        event = WebSocketProtocol.create_event(
            EventTypes.WORKFLOW_STARTED,
            {
                "workflow_id": workflow_id,
                "timestamp": self._get_timestamp(),
                **metadata
            },
            room=f"workflow:{workflow_id}"
        )
        await self.broadcast_to_room(f"workflow:{workflow_id}", event)

    async def broadcast_workflow_stage_completed(
        self, workflow_id: str, stage_name: str, result: dict
    ) -> None:
        """Broadcast workflow stage completed event.

        Args:
            workflow_id: Workflow identifier
            stage_name: Stage name
            result: Stage result
        """
        event = WebSocketProtocol.create_event(
            EventTypes.WORKFLOW_STAGE_COMPLETED,
            {
                "workflow_id": workflow_id,
                "stage_name": stage_name,
                "result": result,
                "timestamp": self._get_timestamp(),
            },
            room=f"workflow:{workflow_id}"
        )
        await self.broadcast_to_room(f"workflow:{workflow_id}", event)

    async def broadcast_workflow_completed(
        self, workflow_id: str, final_result: dict
    ) -> None:
        """Broadcast workflow completed event.

        Args:
            workflow_id: Workflow identifier
            final_result: Final workflow result
        """
        event = WebSocketProtocol.create_event(
            EventTypes.WORKFLOW_COMPLETED,
            {
                "workflow_id": workflow_id,
                "result": final_result,
                "timestamp": self._get_timestamp(),
            },
            room=f"workflow:{workflow_id}"
        )
        await self.broadcast_to_room(f"workflow:{workflow_id}", event)

    async def broadcast_workflow_failed(
        self, workflow_id: str, error: str
    ) -> None:
        """Broadcast workflow failed event.

        Args:
            workflow_id: Workflow identifier
            error: Error message
        """
        event = WebSocketProtocol.create_event(
            EventTypes.WORKFLOW_FAILED,
            {
                "workflow_id": workflow_id,
                "error": error,
                "timestamp": self._get_timestamp(),
            },
            room=f"workflow:{workflow_id}"
        )
        await self.broadcast_to_room(f"workflow:{workflow_id}", event)

    async def broadcast_worker_status_changed(
        self, worker_id: str, status: str, pool_id: str
    ) -> None:
        """Broadcast worker status changed event.

        Args:
            worker_id: Worker identifier
            status: New status (idle, busy, error, etc.)
            pool_id: Pool identifier
        """
        event = WebSocketProtocol.create_event(
            EventTypes.WORKER_STATUS_CHANGED,
            {
                "worker_id": worker_id,
                "status": status,
                "pool_id": pool_id,
                "timestamp": self._get_timestamp(),
            },
            room=f"pool:{pool_id}"
        )
        await self.broadcast_to_room(f"pool:{pool_id}", event)

    async def broadcast_pool_status_changed(
        self, pool_id: str, status: dict
    ) -> None:
        """Broadcast pool status changed event.

        Args:
            pool_id: Pool identifier
            status: Pool status (worker count, queue size, etc.)
        """
        event = WebSocketProtocol.create_event(
            EventTypes.POOL_STATUS_CHANGED,
            {
                "pool_id": pool_id,
                "status": status,
                "timestamp": self._get_timestamp(),
            },
            room=f"pool:{pool_id}"
        )
        await self.broadcast_to_room(f"pool:{pool_id}", event)

    def _get_timestamp(self) -> str:
        """Get current ISO timestamp.

        Returns:
            ISO-formatted timestamp string
        """
        from datetime import datetime, UTC

        return datetime.now(UTC).isoformat()
