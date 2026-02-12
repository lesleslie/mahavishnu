"""Pool WebSocket integration for Mahavishnu.

This package provides integration between the pool management system
and the WebSocket server for real-time event broadcasting.
"""

from .broadcaster import WebSocketBroadcaster, create_broadcaster

__all__ = [
    "WebSocketBroadcaster",
    "create_broadcaster",
]
