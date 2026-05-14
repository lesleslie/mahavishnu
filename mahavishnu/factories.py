"""Factory functions for singleton management.

Provides singleton access to expensive resources:
- PoolManager (multi-pool orchestration)
- MahavishnuWebSocketServer (real-time updates)
- TerminalManager (terminal sessions)

This module prevents the expensive re-initialization of these resources in every
 function call, the which is critical for integration implementations where
 new PoolManager() instances are created
 frequently.

Design Reference:
- docs/plans/PRE_IMPLEMENTATION_CHECKLIST.md (P0-2)

Usage:
    from mahavishnu.factories import (
        get_pool_manager,
        get_websocket_server,
        get_terminal_manager
        initialize_websocket_server
        reset_all_factories
    )

    # Singleton pattern for easy testing
    pool_mgr = get_pool_manager()
    pool_mgr2 = get_pool_manager()  # Same instance
    assert pool_mgr is pool_mgr_2
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from mahavishnu.pools import PoolManager
from mahavishnu.websocket import MahavishnuWebSocketServer

if TYPE_CHECKING:
    from mahavishnu.terminal import TerminalManager

logger = logging.getLogger(__name__)

# Singleton instances
_pool_manager: PoolManager | None = None
_websocket_server: MahavishnuWebSocketServer | None = None
_terminal_manager: TerminalManager | None = None

_pool_lock = threading.Lock()
_ws_lock = threading.Lock()
_tm_lock = threading.Lock()


def get_pool_manager(
    terminal_manager: TerminalManager | None = None,
    session_buddy_client: Any = None,
    message_bus: Any = None,
    event_publisher: Any = None,
    dhara_state: Any = None,
) -> PoolManager:
    """Get or create singleton PoolManager instance.

    Returns singleton PoolManager, reusing existing instance if available.

    Args:
        terminal_manager: Optional TerminalManager (will use get_terminal_manager() if not provided)
        session_buddy_client: Optional Session-Buddy client
        message_bus: Optional MessageBus instance
    """
    global _pool_manager, _pool_lock

    if _pool_manager is not None:
        return _pool_manager

    with _pool_lock:
        if _pool_manager is None:
            # Get terminal manager singleton first
            tm = get_terminal_manager()

            _pool_manager = PoolManager(
                terminal_manager=tm,
                session_buddy_client=session_buddy_client,
                message_bus=message_bus,
                event_publisher=event_publisher,
                dhara_state=dhara_state,
            )

    return _pool_manager


def get_websocket_server(
    pool_manager: PoolManager | None = None,
    host: str = "127.0.0.1",
    port: int = 8690,
    max_connections: int = 1000,
    message_rate_limit: int = 100,
    require_auth: bool = False,
    tls_enabled: bool = False,
    cert_file: str | None = None,
    key_file: str | None = None,
) -> MahavishnuWebSocketServer:
    """Get or create singleton WebSocketServer instance.

    Returns singleton MahavishnuWebSocketServer, reusing existing instance if available.

    Args:
        pool_manager: PoolManager instance for orchestration state
        host: Server host address
        port: Server port number
        max_connections: Maximum concurrent connections
        message_rate_limit: Messages per second per connection
        require_auth: Require JWT authentication
        tls_enabled: Enable TLS
        cert_file: Path to TLS certificate file
        key_file: Path to TLS private key file
    """
    global _websocket_server, _ws_lock

    if _websocket_server is not None:
        return _websocket_server

    with _ws_lock:
        if _websocket_server is None:
            # Ensure pool_manager is available
            if pool_manager is None:
                pool_manager = get_pool_manager()

            _websocket_server = MahavishnuWebSocketServer(
                pool_manager=pool_manager,
                host=host,
                port=port,
                max_connections=max_connections,
                message_rate_limit=message_rate_limit,
                require_auth=require_auth,
                tls_enabled=tls_enabled,
                cert_file=cert_file,
                key_file=key_file,
            )

    return _websocket_server


def get_terminal_manager(
    adapter: Any = None,
    config: Any = None,
) -> TerminalManager:
    """Get or create singleton TerminalManager instance.

    This is a fallback for when terminal_manager is needed but not provided.
    Most code should use get_pool_manager() instead.

    Args:
        adapter: Optional terminal adapter
        config: Optional terminal settings
    """
    global _terminal_manager, _tm_lock

    if _terminal_manager is not None:
        return _terminal_manager

    with _tm_lock:
        if _terminal_manager is None:
            # Import here to avoid circular imports
            from mahavishnu.terminal import TerminalManager as TerminalManagerCls

            _terminal_manager = TerminalManagerCls(adapter=adapter, config=config)

    return _terminal_manager


def initialize_websocket_server(
    pool_manager: PoolManager | None = None,
    host: str = "127.0.0.1",
    port: int = 8690,
    max_connections: int = 1000,
    message_rate_limit: int = 100,
    require_auth: bool = False,
    tls_enabled: bool = False,
    cert_file: str | None = None,
    key_file: str | None = None,
) -> None:
    """Initialize WebSocket server with optional auto-start.

    This is a convenience function for application startup.

    Args:
        pool_manager: PoolManager instance for orchestration state
        host: Server host address
        port: Server port number
        max_connections: Maximum concurrent connections
        message_rate_limit: Messages per second per connection
        require_auth: Require JWT authentication
        tls_enabled: Enable TLS
        cert_file: Path to TLS certificate file
        key_file: Path to TLS private key file
    """
    global _websocket_server

    get_websocket_server(
        pool_manager=pool_manager,
        host=host,
        port=port,
        max_connections=max_connections,
        message_rate_limit=message_rate_limit,
        require_auth=require_auth,
        tls_enabled=tls_enabled,
        cert_file=cert_file,
        key_file=key_file,
    )

    # Note: Caller should await server.start() if needed
    logger.info(f"WebSocket server initialized on {host}:{port}")


def reset_all_factories() -> None:
    """Reset all singleton instances.

    This is primarily intended for testing purposes.
    """
    global _pool_manager, _websocket_server, _terminal_manager
    global _pool_lock, _ws_lock, _tm_lock

    with _pool_lock:
        _pool_manager = None

    with _ws_lock:
        _websocket_server = None

    with _tm_lock:
        _terminal_manager = None

    logger.info("All factory singletons reset")


__all__ = [
    "get_pool_manager",
    "get_websocket_server",
    "get_terminal_manager",
    "initialize_websocket_server",
    "reset_all_factories",
]
