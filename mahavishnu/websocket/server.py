"""WebSocket server for Mahavishnu workflow orchestration.

This module implements a WebSocket server that broadcasts real-time updates
about workflow execution, worker pool status, and orchestration events.

Security Features:
- Token bucket rate limiting per connection
- JWT authentication support
- TLS/WSS encryption
- Connection limits
"""

from __future__ import annotations

import logging
from typing import Any
import uuid

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

# Import metrics
from mahavishnu.websocket.metrics import get_metrics

# Import rate limiting
from mahavishnu.websocket.rate_limiter import RateLimitResult, TokenBucketRateLimiter

# Import TLS configuration
from mahavishnu.websocket.tls_config import get_websocket_tls_config, load_ssl_context

logger = logging.getLogger(__name__)


class MahavishnuWebSocketServer(WebSocketServer):
    """WebSocket server for Mahavishnu orchestration updates.

    Broadcasts real-time events for:
    - Workflow execution (started, stage_completed, completed, failed)
    - Worker pool status changes
    - Task assignments and completions
    - System orchestration metrics
    - Goal-driven team events (created, parsed, execution, errors)

    Security Features:
    - Token bucket rate limiting per connection (configurable)
    - JWT authentication support
    - TLS/WSS encryption
    - Maximum connection limits

    Channels:
    - workflow:{workflow_id} - Workflow-specific updates
    - pool:{pool_id} - Pool status updates
    - worker:{worker_id} - Worker-specific events
    - goal-teams - Global goal-driven team events
    - goal-teams:{user_id} - User-specific team events
    - global - System-wide orchestration events

    Attributes:
        pool_manager: PoolManager instance for orchestration state
        host: Server host address
        port: Server port number (default: 8690)
        rate_limiter: TokenBucketRateLimiter for message rate limiting

    Example:
        >>> from mahavishnu.pools import PoolManager
        >>> from mahavishnu.websocket import MahavishnuWebSocketServer
        >>>
        >>> pool_mgr = PoolManager()
        >>> server = MahavishnuWebSocketServer(pool_manager=pool_mgr)
        >>> await server.start()

    With TLS:
        >>> server = MahavishnuWebSocketServer(
        ...     pool_manager=pool_mgr,
        ...     cert_file="/path/to/cert.pem",
        ...     key_file="/path/to/key.pem"
        ... )
        >>> await server.start()

    With auto-generated development certificate:
        >>> server = MahavishnuWebSocketServer(
        ...     pool_manager=pool_mgr,
        ...     tls_enabled=True
        ... )
        >>> await server.start()

    With custom rate limiting:
        >>> server = MahavishnuWebSocketServer(
        ...     pool_manager=pool_mgr,
        ...     message_rate_limit=50  # 50 messages per second
        ... )
    """

    def __init__(
        self,
        pool_manager: Any,
        host: str = "127.0.0.1",
        port: int = 8690,
        max_connections: int = 1000,
        message_rate_limit: int = 100,
        require_auth: bool = False,
        cert_file: str | None = None,
        key_file: str | None = None,
        ca_file: str | None = None,
        tls_enabled: bool = False,
        verify_client: bool = False,
        auto_cert: bool = False,
    ):
        """Initialize Mahavishnu WebSocket server.

        Args:
            pool_manager: PoolManager instance for orchestration state
            host: Server host address (default: "127.0.0.1")
            port: Server port number (default: 8690)
            max_connections: Maximum concurrent connections (default: 1000)
            message_rate_limit: Messages per second per connection (default: 100)
            require_auth: Require JWT authentication for connections
            cert_file: Path to TLS certificate file (PEM format)
            key_file: Path to TLS private key file (PEM format)
            ca_file: Path to CA file for client verification
            tls_enabled: Enable TLS (generates self-signed cert if no cert provided)
            verify_client: Verify client certificates
            auto_cert: Auto-generate self-signed certificate for development
        """
        authenticator = get_authenticator()

        # Load TLS configuration if enabled
        ssl_context = None
        if tls_enabled or cert_file or key_file:
            tls_config = load_ssl_context(
                cert_file=cert_file,
                key_file=key_file,
                ca_file=ca_file,
                verify_client=verify_client,
            )
            ssl_context = tls_config["ssl_context"]

        # If TLS enabled but no context yet, check environment
        if tls_enabled and ssl_context is None:
            env_config = get_websocket_tls_config()
            if env_config["tls_enabled"] and env_config["cert_file"]:
                tls_config = load_ssl_context()
                ssl_context = tls_config["ssl_context"]

        super().__init__(
            host=host,
            port=port,
            max_connections=max_connections,
            message_rate_limit=message_rate_limit,
            authenticator=authenticator,
            require_auth=require_auth,
            ssl_context=ssl_context,
            cert_file=cert_file,
            key_file=key_file,
            ca_file=ca_file,
            tls_enabled=tls_enabled,
            verify_client=verify_client,
            auto_cert=auto_cert,
        )

        # Initialize metrics
        self.metrics = get_metrics("mahavishnu")

        # Initialize rate limiter with configured rate
        # Burst size is 1.5x the rate to allow small bursts
        self.rate_limiter = TokenBucketRateLimiter(
            rate=float(message_rate_limit),
            burst_size=float(message_rate_limit) * 1.5,
        )

        self.pool_manager = pool_manager

        # Track connection IDs for rate limiting
        self._connection_ids: dict[Any, str] = {}

        # Security warning for non-localhost without TLS
        if not tls_enabled and host not in ("127.0.0.1", "localhost", "::1"):
            logger.warning(
                "SECURITY WARNING: WebSocket server running without TLS on non-localhost "
                f"interface {host}. This exposes traffic to interception. "
                "Set tls_enabled=True or bind to 127.0.0.1 for development."
            )

        logger.info(
            f"MahavishnuWebSocketServer initialized: {host}:{port} "
            f"(TLS: {ssl_context is not None}, rate_limit: {message_rate_limit}/s)"
        )

    async def on_connect(self, websocket: Any, connection_id: str) -> None:
        """Handle new WebSocket connection.

        Initializes rate limiting bucket for the connection and sends
        welcome message with connection metadata.

        Args:
            websocket: WebSocket connection object
            connection_id: Unique connection identifier
        """
        user = getattr(websocket, "user", None)
        user_id = user.get("user_id") if user else "anonymous"

        # Store connection ID mapping for rate limiting
        self._connection_ids[websocket] = connection_id

        logger.info(f"Client connected: {connection_id} (user: {user_id})")

        # Track connection metrics
        self.metrics.adjust_connections(1)

        # Send welcome message
        welcome = WebSocketProtocol.create_event(
            EventTypes.SESSION_CREATED,
            {
                "connection_id": connection_id,
                "server": "mahavishnu",
                "message": "Connected to Mahavishnu orchestration",
                "authenticated": user is not None,
                "secure": self.ssl_context is not None,
                "rate_limit": self.message_rate_limit,
            },
        )
        await websocket.send(WebSocketProtocol.encode(welcome))

    async def on_disconnect(self, websocket: Any, connection_id: str) -> None:
        """Handle WebSocket disconnection.

        Cleans up rate limiting bucket and room subscriptions.

        Args:
            websocket: WebSocket connection object
            connection_id: Unique connection identifier
        """
        logger.info(f"Client disconnected: {connection_id}")

        # Track connection metrics
        self.metrics.adjust_connections(-1)

        # Clean up rate limiter bucket for this connection
        self.rate_limiter.remove_connection(connection_id)

        # Clean up connection ID mapping
        self._connection_ids.pop(websocket, None)

        # Clean up room subscriptions
        await self.leave_all_rooms(connection_id)

    async def on_message(self, websocket: Any, message: WebSocketMessage) -> None:
        """Handle incoming WebSocket message with rate limiting.

        Applies token bucket rate limiting before processing messages.
        Messages exceeding the rate limit are dropped and an error is sent.

        Args:
            websocket: WebSocket connection object
            message: Decoded message
        """
        # Get connection ID for rate limiting
        connection_id = self._connection_ids.get(websocket)
        if not connection_id:
            connection_id = getattr(websocket, "id", str(uuid.uuid4()))
            self._connection_ids[websocket] = connection_id

        # Apply rate limiting
        rate_result = self.rate_limiter.check(connection_id)

        if rate_result.limited:
            # Message rate limited - send error and drop
            await self._send_rate_limit_error(websocket, message, rate_result)
            return

        # Process message normally
        if message.type == MessageType.REQUEST:
            await self._handle_request(websocket, message)
        elif message.type == MessageType.EVENT:
            await self._handle_event(websocket, message)
        else:
            logger.warning(f"Unhandled message type: {message.type}")

    async def _send_rate_limit_error(
        self,
        websocket: Any,
        message: WebSocketMessage,
        rate_result: RateLimitResult,
    ) -> None:
        """Send rate limit error to client.

        Args:
            websocket: WebSocket connection object
            message: Original message that was rate limited
            rate_result: Rate limit check result
        """
        # Track rate limit error in metrics
        self.metrics.inc_error("rate_limit")

        # Create and send error response
        error = WebSocketProtocol.create_error(
            error_code="RATE_LIMIT_EXCEEDED",
            error_message=(
                f"Message rate limit exceeded. Retry after {rate_result.retry_after:.3f} seconds."
            ),
            correlation_id=message.correlation_id,
        )

        try:
            await websocket.send(WebSocketProtocol.encode(error))
        except Exception as e:
            logger.debug(f"Failed to send rate limit error: {e}")

    async def _handle_request(self, websocket: Any, message: WebSocketMessage) -> None:
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
                connection_id = self._connection_ids.get(websocket, str(uuid.uuid4()))
                await self.join_room(channel, connection_id)

                # Send confirmation
                response = WebSocketProtocol.create_response(
                    message, {"status": "subscribed", "channel": channel}
                )
                await websocket.send(WebSocketProtocol.encode(response))

        elif message.event == "unsubscribe":
            channel = message.data.get("channel")
            if channel:
                connection_id = self._connection_ids.get(websocket, str(uuid.uuid4()))
                await self.leave_room(channel, connection_id)

                # Send confirmation
                response = WebSocketProtocol.create_response(
                    message, {"status": "unsubscribed", "channel": channel}
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

        if channel.startswith("goal-teams"):
            return "team:read" in permissions

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

    def get_rate_limit_stats(self, connection_id: str | None = None) -> dict[str, Any]:
        """Get rate limiting statistics.

        Args:
            connection_id: Optional specific connection to get stats for

        Returns:
            Dictionary with rate limit statistics
        """
        return self.rate_limiter.get_stats(connection_id)

    # Broadcast methods for orchestration events

    async def broadcast_workflow_started(self, workflow_id: str, metadata: dict) -> None:
        """Broadcast workflow started event.

        Args:
            workflow_id: Workflow identifier
            metadata: Workflow metadata (prompt, adapter, etc.)
        """
        event = WebSocketProtocol.create_event(
            EventTypes.WORKFLOW_STARTED,
            {"workflow_id": workflow_id, "timestamp": self._get_timestamp(), **metadata},
            room=f"workflow:{workflow_id}",
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
            room=f"workflow:{workflow_id}",
        )
        await self.broadcast_to_room(f"workflow:{workflow_id}", event)

    async def broadcast_workflow_completed(self, workflow_id: str, final_result: dict) -> None:
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
            room=f"workflow:{workflow_id}",
        )
        await self.broadcast_to_room(f"workflow:{workflow_id}", event)

    async def broadcast_workflow_failed(self, workflow_id: str, error: str) -> None:
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
            room=f"workflow:{workflow_id}",
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
            room=f"pool:{pool_id}",
        )
        await self.broadcast_to_room(f"pool:{pool_id}", event)

    async def broadcast_pool_status_changed(self, pool_id: str, status: dict) -> None:
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
            room=f"pool:{pool_id}",
        )
        await self.broadcast_to_room(f"pool:{pool_id}", event)

    # Broadcast methods for Goal-Driven Teams events

    async def broadcast_team_created(
        self,
        team_id: str,
        team_name: str,
        goal: str,
        mode: str,
        user_id: str | None = None,
    ) -> None:
        """Broadcast when a new goal-driven team is created.

        Args:
            team_id: Unique team identifier
            team_name: Human-readable team name
            goal: The natural language goal that created this team
            mode: Collaboration mode (coordinate, route, broadcast, collaborate)
            user_id: Optional user ID for user-specific channel
        """
        event_data = {
            "team_id": team_id,
            "team_name": team_name,
            "goal": goal,
            "mode": mode,
            "timestamp": self._get_timestamp(),
        }

        # Broadcast to global goal-teams channel
        event = WebSocketProtocol.create_event(
            "team.created",
            event_data,
            room="goal-teams",
        )
        await self.broadcast_to_room("goal-teams", event)

        # Also broadcast to user-specific channel if user_id provided
        if user_id:
            user_room = f"goal-teams:{user_id}"
            user_event = WebSocketProtocol.create_event(
                "team.created",
                event_data,
                room=user_room,
            )
            await self.broadcast_to_room(user_room, user_event)

    async def broadcast_team_parsed(
        self,
        goal: str,
        intent: str,
        skills: list[str],
        confidence: float,
        user_id: str | None = None,
    ) -> None:
        """Broadcast when a goal is parsed.

        This event fires when goal parsing completes, showing how the
        natural language goal was interpreted.

        Args:
            goal: The original natural language goal
            intent: Parsed intent (review, build, test, fix, etc.)
            skills: List of detected skills required
            confidence: Parsing confidence score (0.0-1.0)
            user_id: Optional user ID for user-specific channel
        """
        event_data = {
            "goal": goal,
            "intent": intent,
            "skills": skills,
            "confidence": round(confidence, 3),
            "timestamp": self._get_timestamp(),
        }

        # Broadcast to global goal-teams channel
        event = WebSocketProtocol.create_event(
            "team.parsed",
            event_data,
            room="goal-teams",
        )
        await self.broadcast_to_room("goal-teams", event)

        # Also broadcast to user-specific channel if user_id provided
        if user_id:
            user_room = f"goal-teams:{user_id}"
            user_event = WebSocketProtocol.create_event(
                "team.parsed",
                event_data,
                room=user_room,
            )
            await self.broadcast_to_room(user_room, user_event)

    async def broadcast_team_execution_started(
        self,
        team_id: str,
        task: str,
        user_id: str | None = None,
    ) -> None:
        """Broadcast when team execution starts.

        This event fires when auto_run begins executing a team.

        Args:
            team_id: Unique team identifier
            task: The task being executed
            user_id: Optional user ID for user-specific channel
        """
        event_data = {
            "team_id": team_id,
            "task": task[:200] if len(task) > 200 else task,  # Truncate long tasks
            "timestamp": self._get_timestamp(),
        }

        # Broadcast to global goal-teams channel
        event = WebSocketProtocol.create_event(
            "team.execution_started",
            event_data,
            room="goal-teams",
        )
        await self.broadcast_to_room("goal-teams", event)

        # Also broadcast to user-specific channel if user_id provided
        if user_id:
            user_room = f"goal-teams:{user_id}"
            user_event = WebSocketProtocol.create_event(
                "team.execution_started",
                event_data,
                room=user_room,
            )
            await self.broadcast_to_room(user_room, user_event)

    async def broadcast_team_execution_completed(
        self,
        team_id: str,
        success: bool,
        duration_ms: float,
        user_id: str | None = None,
    ) -> None:
        """Broadcast when team execution completes.

        This event fires when auto_run finishes executing a team,
        whether successfully or with errors.

        Args:
            team_id: Unique team identifier
            success: Whether execution succeeded
            duration_ms: Execution duration in milliseconds
            user_id: Optional user ID for user-specific channel
        """
        event_data = {
            "team_id": team_id,
            "success": success,
            "duration_ms": round(duration_ms, 2),
            "timestamp": self._get_timestamp(),
        }

        # Broadcast to global goal-teams channel
        event = WebSocketProtocol.create_event(
            "team.execution_completed",
            event_data,
            room="goal-teams",
        )
        await self.broadcast_to_room("goal-teams", event)

        # Also broadcast to user-specific channel if user_id provided
        if user_id:
            user_room = f"goal-teams:{user_id}"
            user_event = WebSocketProtocol.create_event(
                "team.execution_completed",
                event_data,
                room=user_room,
            )
            await self.broadcast_to_room(user_room, user_event)

    async def broadcast_team_error(
        self,
        team_id: str,
        error_code: str,
        message: str,
        user_id: str | None = None,
    ) -> None:
        """Broadcast when a team operation fails.

        This event fires when team creation, parsing, or execution fails.

        Args:
            team_id: Unique team identifier (may be empty if creation failed)
            error_code: Error code from ErrorCode enum
            message: Human-readable error message
            user_id: Optional user ID for user-specific channel
        """
        event_data = {
            "team_id": team_id,
            "error_code": error_code,
            "message": message,
            "timestamp": self._get_timestamp(),
        }

        # Broadcast to global goal-teams channel
        event = WebSocketProtocol.create_event(
            "team.error",
            event_data,
            room="goal-teams",
        )
        await self.broadcast_to_room("goal-teams", event)

        # Also broadcast to user-specific channel if user_id provided
        if user_id:
            user_room = f"goal-teams:{user_id}"
            user_event = WebSocketProtocol.create_event(
                "team.error",
                event_data,
                room=user_room,
            )
            await self.broadcast_to_room(user_room, user_event)

    def _get_timestamp(self) -> str:
        """Get current ISO timestamp.

        Returns:
            ISO-formatted timestamp string
        """
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat()
