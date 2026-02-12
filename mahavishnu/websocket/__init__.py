"""WebSocket server for Mahavishnu workflow orchestration.

This module provides real-time updates for:
- Workflow execution progress
- Worker pool status changes
- Task completion events
- System orchestration metrics

Example:
    >>> from mahavishnu.websocket import MahavishnuWebSocketServer
    >>> server = MahavishnuWebSocketServer(pool_manager)
    >>> await server.start()
"""

from .server import MahavishnuWebSocketServer
from .metrics import WebSocketMetrics, get_metrics, start_metrics_server

__all__ = [
    "MahavishnuWebSocketServer",
    "WebSocketMetrics",
    "get_metrics",
    "start_metrics_server",
]
