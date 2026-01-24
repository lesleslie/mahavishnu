"""Connection pooling for iTerm2 adapter.

This module provides a connection pool to reuse iTerm2 WebSocket connections
across multiple TerminalManager instances, reducing connection overhead.
"""
import asyncio
from logging import getLogger
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

try:
    import iterm2
    ITERM2_AVAILABLE = True
except ImportError:
    ITERM2_AVAILABLE = False

logger = getLogger(__name__)


class ITerm2ConnectionPool:
    """Pool for reusing iTerm2 WebSocket connections.

    Benefits:
    - Reduces connection overhead (WebSocket handshake is expensive)
    - Limits total connections to iTerm2 (prevents resource exhaustion)
    - Provides connection health checking and auto-reconnect

    Example:
        >>> pool = ITerm2ConnectionPool(max_size=5)
        >>> conn = await pool.acquire()
        >>> # Use connection...
        >>> await pool.release(conn)
    """

    def __init__(
        self,
        max_size: int = 3,
        idle_timeout: float = 300.0,
        health_check_interval: float = 60.0,
    ) -> None:
        """Initialize iTerm2 connection pool.

        Args:
            max_size: Maximum number of connections to pool
            idle_timeout: Close connections idle for this many seconds
            health_check_interval: Check connection health every N seconds
        """
        if not ITERM2_AVAILABLE:
            raise ImportError("iterm2 package is not available")

        self.max_size = max_size
        self.idle_timeout = timedelta(seconds=idle_timeout)
        self.health_check_interval = health_check_interval

        self._pool: Dict[str, Any] = {}  # conn_id -> {conn, created_at, last_used, in_use}
        self._lock = asyncio.Lock()
        self._health_check_task: Optional[asyncio.Task] = None

        logger.info(
            f"Initialized iTerm2 connection pool (max_size={max_size}, "
            f"idle_timeout={idle_timeout}s)"
        )

    async def acquire(self) -> Any:
        """Acquire a connection from the pool.

        Creates a new connection if pool is empty or all connections are in use.
        Reuses idle connections when available.

        Returns:
            iTerm2 connection object

        Raises:
            RuntimeError: If pool is full and no connections available
        """
        async with self._lock:
            # Try to find an idle connection
            for conn_id, conn_info in self._pool.items():
                if not conn_info["in_use"]:
                    # Check if connection is still healthy
                    if self._is_connection_healthy(conn_info["conn"]):
                        conn_info["in_use"] = True
                        conn_info["last_used"] = datetime.now()
                        logger.debug(f"Reusing pooled connection {conn_id}")
                        return conn_info["conn"]
                    else:
                        # Remove unhealthy connection
                        logger.warning(f"Removing unhealthy connection {conn_id}")
                        del self._pool[conn_id]

            # Create new connection if pool not full
            if len(self._pool) < self.max_size:
                conn = await self._create_connection()
                conn_id = f"conn_{datetime.now().timestamp()}"

                self._pool[conn_id] = {
                    "conn": conn,
                    "created_at": datetime.now(),
                    "last_used": datetime.now(),
                    "in_use": True,
                }

                logger.info(f"Created new iTerm2 connection {conn_id} (pool size: {len(self._pool)})")
                return conn

            # Pool is full
            raise RuntimeError(
                f"Connection pool exhausted (max_size={self.max_size}). "
                f"Wait for a connection to be released or increase pool size."
            )

    async def release(self, conn: Any) -> None:
        """Release a connection back to the pool.

        Args:
            conn: Connection to release
        """
        async with self._lock:
            # Find the connection in pool
            for conn_id, conn_info in self._pool.items():
                if conn_info["conn"] == conn:
                    conn_info["in_use"] = False
                    conn_info["last_used"] = datetime.now()
                    logger.debug(f"Released connection {conn_id}")
                    return

            logger.warning("Attempted to release unknown connection")

    async def close_all(self) -> None:
        """Close all connections in the pool.

        Should be called before shutdown.
        """
        async with self._lock:
            # Stop health check task
            if self._health_check_task:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
                self._health_check_task = None

            # Close all connections
            for conn_id, conn_info in self._pool.items():
                try:
                    await conn_info["conn"].close()
                    logger.debug(f"Closed connection {conn_id}")
                except Exception as e:
                    logger.warning(f"Error closing connection {conn_id}: {e}")

            self._pool.clear()
            logger.info("Closed all iTerm2 connections")

    async def _create_connection(self) -> Any:
        """Create a new iTerm2 connection.

        Returns:
            New iTerm2 connection

        Raises:
            RuntimeError: If connection fails
        """
        try:
            conn = await iterm2.Connection.async_connect()
            return conn
        except Exception as e:
            raise RuntimeError(f"Failed to create iTerm2 connection: {e}") from e

    def _is_connection_healthy(self, conn: Any) -> bool:
        """Check if a connection is healthy.

        Args:
            conn: Connection to check

        Returns:
            True if connection is healthy
        """
        try:
            # Basic health check: connection should have a valid WebSocket
            return hasattr(conn, "_websocket") and conn._websocket is not None
        except Exception:
            return False

    async def start_health_check(self) -> None:
        """Start background health check task.

        Periodically checks connection health and removes stale connections.
        """
        if self._health_check_task is not None:
            return  # Already running

        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("Started iTerm2 connection pool health check")

    async def _health_check_loop(self) -> None:
        """Background health check loop."""
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._remove_stale_connections()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")

    async def _remove_stale_connections(self) -> None:
        """Remove stale connections from the pool.

        A connection is stale if:
        - It's idle for longer than idle_timeout
        - It's not healthy (WebSocket closed)
        """
        async with self._lock:
            now = datetime.now()
            stale_ids = []

            for conn_id, conn_info in self._pool.items():
                # Skip in-use connections
                if conn_info["in_use"]:
                    continue

                # Check idle timeout
                idle_time = now - conn_info["last_used"]
                if idle_time > self.idle_timeout:
                    stale_ids.append(conn_id)
                    continue

                # Check health
                if not self._is_connection_healthy(conn_info["conn"]):
                    stale_ids.append(conn_id)

            # Remove stale connections
            for conn_id in stale_ids:
                conn_info = self._pool[conn_id]
                try:
                    await conn_info["conn"].close()
                except Exception as e:
                    logger.warning(f"Error closing stale connection {conn_id}: {e}")
                del self._pool[conn_id]
                logger.debug(f"Removed stale connection {conn_id}")

            if stale_ids:
                logger.info(f"Removed {len(stale_ids)} stale connections")

    def stats(self) -> Dict[str, Any]:
        """Get pool statistics.

        Returns:
            Dictionary with pool stats
        """
        total = len(self._pool)
        in_use = sum(1 for c in self._pool.values() if c["in_use"])
        idle = total - in_use

        return {
            "total_connections": total,
            "in_use": in_use,
            "idle": idle,
            "max_size": self.max_size,
            "utilization_percent": round((in_use / self.max_size) * 100, 1) if self.max_size > 0 else 0,
        }


# Global connection pool singleton
_global_pool: Optional[ITerm2ConnectionPool] = None
_pool_lock = asyncio.Lock()


async def get_global_pool() -> ITerm2ConnectionPool:
    """Get or create the global iTerm2 connection pool.

    Returns:
        Global connection pool instance
    """
    global _global_pool

    async with _pool_lock:
        if _global_pool is None:
            _global_pool = ITerm2ConnectionPool()
            await _global_pool.start_health_check()
            logger.info("Created global iTerm2 connection pool")

        return _global_pool


async def close_global_pool() -> None:
    """Close the global connection pool.

    Should be called on application shutdown.
    """
    global _global_pool

    async with _pool_lock:
        if _global_pool is not None:
            await _global_pool.close_all()
            _global_pool = None
            logger.info("Closed global iTerm2 connection pool")
