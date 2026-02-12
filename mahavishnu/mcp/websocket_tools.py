"""WebSocket integration tools for Mahavishnu MCP server.

This module provides MCP tools for:
- WebSocket server health monitoring
- WebSocket status queries
- Managing WebSocket connections
- Broadcasting test events (development)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..websocket.server import MahavishnuWebSocketServer

logger = logging.getLogger(__name__)


def register_websocket_tools(server, websocket_server):
    """Register WebSocket-related MCP tools.

    Args:
        server: FastMCP server instance
        websocket_server: MahavishnuWebSocketServer instance
    """

    @server.tool()
    async def websocket_health_check() -> dict:
        """Check WebSocket server health and status.

        Returns:
            Dictionary with server health information:
            {
                "status": "healthy" | "stopped" | "error",
                "host": "127.0.0.1",
                "port": 8690,
                "connections": 0,
                "rooms": 0,
                "uptime_seconds": 0
            }
        """
        try:
            if websocket_server is None:
                return {
                    "status": "not_initialized",
                    "host": "127.0.0.1",
                    "port": 8690,
                    "message": "WebSocket server not initialized",
                }

            if not websocket_server.is_running:
                return {
                    "status": "stopped",
                    "host": websocket_server.host,
                    "port": websocket_server.port,
                    "connections": 0,
                    "rooms": 0,
                    "message": "WebSocket server is not running",
                }

            # Get connection and room counts
            connection_count = len(websocket_server.connections)
            room_count = len(websocket_server.connection_rooms)

            return {
                "status": "healthy",
                "host": websocket_server.host,
                "port": websocket_server.port,
                "connections": connection_count,
                "rooms": room_count,
                "max_connections": websocket_server.max_connections,
                "message_rate_limit": websocket_server.message_rate_limit,
            }

        except Exception as e:
            logger.error(f"Error checking WebSocket health: {e}")
            return {
                "status": "error",
                "error": str(e),
                "host": "127.0.0.1",
                "port": 8690,
            }

    @server.tool()
    async def websocket_get_status() -> dict:
        """Get detailed WebSocket server status.

        Returns:
            Dictionary with detailed status information including:
            - Server state
            - Active connections
            - Room subscriptions
            - Pool manager status
        """
        try:
            if websocket_server is None or not websocket_server.is_running:
                return {
                    "server": {"status": "not_running"},
                    "connections": [],
                    "rooms": [],
                }

            # Get active connections
            connections = list(websocket_server.connections.keys())

            # Get room subscriptions
            rooms = {}
            for room_id, connection_set in websocket_server.connection_rooms.items():
                rooms[room_id] = {
                    "subscribers": len(connection_set),
                    "connection_ids": list(connection_set),
                }

            return {
                "server": {
                    "status": "running",
                    "host": websocket_server.host,
                    "port": websocket_server.port,
                },
                "connections": connections,
                "rooms": rooms,
                "total_connections": len(connections),
                "total_rooms": len(rooms),
            }

        except Exception as e:
            logger.error(f"Error getting WebSocket status: {e}")
            return {
                "error": str(e),
                "server": {"status": "error"},
                "connections": [],
                "rooms": [],
            }

    @server.tool()
    async def websocket_list_rooms() -> dict:
        """List all WebSocket rooms and their subscriber counts.

        Returns:
            Dictionary with room information:
            {
                "rooms": {
                    "workflow:abc123": {"subscribers": 2},
                    "pool:local": {"subscribers": 5}
                },
                "total_rooms": 2
            }
        """
        try:
            if websocket_server is None or not websocket_server.is_running:
                return {
                    "rooms": {},
                    "total_rooms": 0,
                    "message": "WebSocket server not running",
                }

            rooms = {}
            for room_id, connection_set in websocket_server.connection_rooms.items():
                rooms[room_id] = {"subscribers": len(connection_set)}

            return {
                "rooms": rooms,
                "total_rooms": len(rooms),
            }

        except Exception as e:
            logger.error(f"Error listing WebSocket rooms: {e}")
            return {
                "error": str(e),
                "rooms": {},
                "total_rooms": 0,
            }

    @server.tool()
    async def websocket_broadcast_test_event(
        event_type: str,
        room: str,
        data: dict | None = None,
    ) -> dict:
        """Broadcast a test event via WebSocket (development only).

        ⚠️ WARNING: This tool is for development and testing purposes only.
        Do not use in production environments.

        Args:
            event_type: Type of event to broadcast (e.g., "workflow.started")
            room: Room to broadcast to (e.g., "global", "workflow:test123")
            data: Optional event data payload

        Returns:
            Dictionary with broadcast result:
            {
                "status": "broadcasted" | "error",
                "event_type": str,
                "room": str,
                "subscribers": 0
            }
        """
        try:
            if websocket_server is None or not websocket_server.is_running:
                return {
                    "status": "error",
                    "error": "WebSocket server not running",
                    "event_type": event_type,
                    "room": room,
                }

            # Get subscriber count for room
            subscribers = len(websocket_server.connection_rooms.get(room, set()))

            # Create test event
            from mcp_common.websocket import WebSocketProtocol, EventTypes

            # Map common event types
            event_mapping = {
                "workflow.started": EventTypes.WORKFLOW_STARTED,
                "workflow.completed": EventTypes.WORKFLOW_COMPLETED,
                "workflow.failed": EventTypes.WORKFLOW_FAILED,
                "worker.status_changed": EventTypes.WORKER_STATUS_CHANGED,
                "pool.status_changed": EventTypes.POOL_STATUS_CHANGED,
            }

            mapped_event = event_mapping.get(event_type, event_type)

            # Build event data
            event_data = data or {}
            event_data.update({
                "timestamp": websocket_server._get_timestamp(),
                "test": True,
            })

            # Create and broadcast event
            event = WebSocketProtocol.create_event(
                mapped_event,
                event_data,
                room=room,
            )

            await websocket_server.broadcast_to_room(room, event)

            logger.info(
                f"Test event broadcast: {event_type} -> {room} "
                f"({subscribers} subscribers)"
            )

            return {
                "status": "broadcasted",
                "event_type": event_type,
                "room": room,
                "subscribers": subscribers,
                "message": "Test event broadcast successfully",
            }

        except Exception as e:
            logger.error(f"Error broadcasting test event: {e}")
            return {
                "status": "error",
                "error": str(e),
                "event_type": event_type,
                "room": room,
            }

    @server.tool()
    async def websocket_get_metrics() -> dict:
        """Get WebSocket server metrics.

        Returns:
            Dictionary with server metrics:
            {
                "uptime_seconds": 0,
                "total_broadcasts": 0,
                "average_message_rate": 0.0,
                "peak_connections": 0
            }
        """
        try:
            if websocket_server is None or not websocket_server.is_running:
                return {
                    "uptime_seconds": 0,
                    "total_broadcasts": 0,
                    "average_message_rate": 0.0,
                    "peak_connections": 0,
                    "message": "WebSocket server not running",
                }

            # Placeholder metrics - implement based on actual tracking
            return {
                "uptime_seconds": 0,  # TODO: Track server start time
                "total_broadcasts": 0,  # TODO: Track broadcast operations
                "average_message_rate": 0.0,  # TODO: Calculate from message counts
                "peak_connections": len(websocket_server.connections),
                "current_connections": len(websocket_server.connections),
            }

        except Exception as e:
            logger.error(f"Error getting WebSocket metrics: {e}")
            return {
                "error": str(e),
                "uptime_seconds": 0,
                "total_broadcasts": 0,
            }
