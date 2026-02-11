"""WebSocket integration helper for Mahavishnu application.

This module provides helper functions for integrating WebSocket server
with main Mahavishnu application and MCP server.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..core.config import MahavishnuSettings
from .server import MahavishnuWebSocketServer
from .tls_config import get_websocket_tls_config, load_ssl_context

logger = logging.getLogger(__name__)


async def start_websocket_server(
    pool_manager,
    settings: MahavishnuSettings,
    host: str | None = None,
    port: int | None = None,
    tls_enabled: bool | None = None,
    cert_file: str | None = None,
    key_file: str | None = None,
    ca_file: str | None = None,
    verify_client: bool = False,
    auto_cert: bool = False,
) -> MahavishnuWebSocketServer | None:
    """Start WebSocket server for Mahavishnu.

    Args:
        pool_manager: PoolManager instance for orchestration state
        settings: MahavishnuSettings configuration
        host: Server host address (default: from settings or 127.0.0.1)
        port: Server port number (default: from settings or 8690)
        tls_enabled: Enable TLS (default: from environment)
        cert_file: Path to TLS certificate file
        key_file: Path to TLS private key file
        ca_file: Path to CA file for client verification
        verify_client: Verify client certificates
        auto_cert: Auto-generate self-signed certificate for development

    Returns:
        MahavishnuWebSocketServer instance if enabled, None otherwise
    """
    # Check if WebSocket is enabled in settings
    websocket_enabled = getattr(settings, "websocket_enabled", True)

    if not websocket_enabled:
        logger.info("WebSocket server disabled in settings")
        return None

    # Use provided values or fall back to settings/environment
    host = host or getattr(settings, "websocket_host", "127.0.0.1")
    port = port or getattr(settings, "websocket_port", 8690)

    # Get TLS configuration from environment if not explicitly provided
    if tls_enabled is None:
        env_tls = get_websocket_tls_config()
        tls_enabled = env_tls["tls_enabled"]
        cert_file = cert_file or env_tls["cert_file"]
        key_file = key_file or env_tls["key_file"]
        ca_file = ca_file or env_tls["ca_file"]
        verify_client = verify_client or env_tls.get("verify_client", False)

    try:
        # Create WebSocket server
        server = MahavishnuWebSocketServer(
            pool_manager=pool_manager,
            host=host,
            port=port,
            max_connections=1000,
            message_rate_limit=100,
            cert_file=cert_file,
            key_file=key_file,
            ca_file=ca_file,
            tls_enabled=tls_enabled,
            verify_client=verify_client,
            auto_cert=auto_cert,
        )

        # Start server
        await server.start()

        scheme = "wss" if server.ssl_context else "ws"
        logger.info(f"WebSocket server started on {scheme}://{host}:{port}")

        return server

    except Exception as e:
        logger.error(f"Failed to start WebSocket server: {e}")
        return None


async def stop_websocket_server(
    server: MahavishnuWebSocketServer | None,
) -> None:
    """Stop WebSocket server.

    Args:
        server: MahavishnuWebSocketServer instance (can be None)
    """
    if server is None:
        return

    try:
        await server.stop()
        logger.info("WebSocket server stopped")
    except Exception as e:
        logger.error(f"Error stopping WebSocket server: {e}")


def get_websocket_status(server: MahavishnuWebSocketServer | None) -> dict:
    """Get WebSocket server status.

    Args:
        server: MahavishnuWebSocketServer instance (can be None)

    Returns:
        Status dictionary
    """
    if server is None:
        return {
            "enabled": False,
            "status": "not_initialized",
            "host": "127.0.0.1",
            "port": 8690,
            "secure": False,
        }

    scheme = "wss" if server.ssl_context else "ws"

    return {
        "enabled": True,
        "status": "running" if server.is_running else "stopped",
        "host": server.host,
        "port": server.port,
        "uri": server.uri,
        "secure": server.ssl_context is not None,
        "connections": len(server.connections) if server.is_running else 0,
        "rooms": len(server.connection_rooms) if server.is_running else 0,
    }


async def broadcast_workflow_event(
    server: MahavishnuWebSocketServer | None,
    event_type: str,
    workflow_id: str,
    data: dict,
) -> bool:
    """Broadcast a workflow event via WebSocket.

    Args:
        server: MahavishnuWebSocketServer instance (can be None)
        event_type: Type of event (started, completed, failed, etc.)
        workflow_id: Workflow identifier
        data: Event data

    Returns:
        True if broadcast successful, False otherwise
    """
    if server is None or not server.is_running:
        return False

    try:
        # Map event type to broadcast method
        if event_type == "started":
            await server.broadcast_workflow_started(workflow_id, data)
        elif event_type == "stage_completed":
            await server.broadcast_workflow_stage_completed(
                workflow_id,
                data.get("stage_name", "unknown"),
                data.get("result", {}),
            )
        elif event_type == "completed":
            await server.broadcast_workflow_completed(workflow_id, data)
        elif event_type == "failed":
            await server.broadcast_workflow_failed(
                workflow_id,
                data.get("error", "Unknown error"),
            )
        else:
            logger.warning(f"Unknown workflow event type: {event_type}")
            return False

        return True

    except Exception as e:
        logger.error(f"Error broadcasting workflow event: {e}")
        return False


async def broadcast_pool_event(
    server: MahavishnuWebSocketServer | None,
    event_type: str,
    pool_id: str,
    data: dict,
) -> bool:
    """Broadcast a pool event via WebSocket.

    Args:
        server: MahavishnuWebSocketServer instance (can be None)
        event_type: Type of event (status_changed, etc.)
        pool_id: Pool identifier
        data: Event data

    Returns:
        True if broadcast successful, False otherwise
    """
    if server is None or not server.is_running:
        return False

    try:
        if event_type == "status_changed":
            await server.broadcast_pool_status_changed(pool_id, data)
        elif event_type == "worker_status_changed":
            await server.broadcast_worker_status_changed(
                data.get("worker_id", "unknown"),
                data.get("status", "unknown"),
                pool_id,
            )
        else:
            logger.warning(f"Unknown pool event type: {event_type}")
            return False

        return True

    except Exception as e:
        logger.error(f"Error broadcasting pool event: {e}")
        return False


class WebSocketBroadcaster:
    """Helper class for broadcasting events via WebSocket.

    Provides a convenient interface for broadcasting events from
    within workflow execution and pool management code.

    Example:
        >>> broadcaster = WebSocketBroadcaster(websocket_server)
        >>> await broadcaster.workflow_started("wf_123", {"prompt": "Write code"})
        >>> await broadcaster.workflow_stage_completed("wf_123", "stage1", {})
    """

    def __init__(self, server: MahavishnuWebSocketServer | None):
        """Initialize broadcaster.

        Args:
            server: MahavishnuWebSocketServer instance (can be None)
        """
        self.server = server

    async def workflow_started(self, workflow_id: str, metadata: dict) -> bool:
        """Broadcast workflow started event."""
        return await broadcast_workflow_event(
            self.server, "started", workflow_id, metadata
        )

    async def workflow_stage_completed(
        self, workflow_id: str, stage_name: str, result: dict
    ) -> bool:
        """Broadcast workflow stage completed event."""
        return await broadcast_workflow_event(
            self.server,
            "stage_completed",
            workflow_id,
            {"stage_name": stage_name, "result": result},
        )

    async def workflow_completed(self, workflow_id: str, result: dict) -> bool:
        """Broadcast workflow completed event."""
        return await broadcast_workflow_event(
            self.server, "completed", workflow_id, result
        )

    async def workflow_failed(self, workflow_id: str, error: str) -> bool:
        """Broadcast workflow failed event."""
        return await broadcast_workflow_event(
            self.server, "failed", workflow_id, {"error": error}
        )

    async def pool_status_changed(self, pool_id: str, status: dict) -> bool:
        """Broadcast pool status changed event."""
        return await broadcast_pool_event(
            self.server, "status_changed", pool_id, status
        )

    async def worker_status_changed(
        self, worker_id: str, status: str, pool_id: str
    ) -> bool:
        """Broadcast worker status changed event."""
        return await broadcast_pool_event(
            self.server,
            "worker_status_changed",
            pool_id,
            {"worker_id": worker_id, "status": status},
        )
