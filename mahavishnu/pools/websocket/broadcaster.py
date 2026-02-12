"""Pool WebSocket broadcasting integration layer.

This module provides integration between Mahavishnu's pool management system
and the WebSocket server for real-time event broadcasting.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, UTC
from typing import Any

from mcp_common.websocket import WebSocketProtocol

logger = logging.getLogger(__name__)


class WebSocketBroadcaster:
    """Broadcasts pool management events to WebSocket subscribers.

    This class integrates PoolManager with MahavishnuWebSocketServer
    to provide real-time updates on:
    - Worker status changes
    - Task assignments and completions
    - Pool scaling events
    - Pool lifecycle events

    Features:
    - Automatic reconnection on connection drop
    - Graceful degradation if WebSocket unavailable
    - Event buffering when disconnected (optional)
    - Non-blocking broadcast operations

    Example:
        >>> from mahavishnu.pools.websocket import WebSocketBroadcaster
        >>>
        >>> broadcaster = WebSocketBroadcaster(websocket_server)
        >>> await broadcaster.broadcast_pool_spawned("pool_abc", config)
        >>> await broadcaster.broadcast_worker_added("pool_abc", "worker_1")
    """

    def __init__(
        self,
        websocket_server: Any | None = None,
        buffer_size: int = 1000,
        buffer_enabled: bool = False,
    ):
        """Initialize WebSocket broadcaster.

        Args:
            websocket_server: MahavishnuWebSocketServer instance (optional)
            buffer_size: Maximum number of events to buffer when disconnected
            buffer_enabled: Whether to buffer events when disconnected
        """
        self.server = websocket_server
        self._buffer_enabled = buffer_enabled
        self._event_buffer: deque[dict[str, Any]] = deque(maxlen=buffer_size)
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5

    # Pool lifecycle events

    async def broadcast_pool_spawned(
        self,
        pool_id: str,
        config: dict[str, Any],
    ) -> bool:
        """Broadcast pool spawned event.

        Args:
            pool_id: Pool identifier
            config: Pool configuration

        Returns:
            True if broadcast successful, False otherwise
        """
        event_data = {
            "pool_id": pool_id,
            "config": config,
            "timestamp": self._get_timestamp(),
        }

        return await self._broadcast(
            event="pool.spawned",
            event_data=event_data,
            room=f"pool:{pool_id}",
        )

    async def broadcast_pool_scaled(
        self,
        pool_id: str,
        worker_count: int,
    ) -> bool:
        """Broadcast pool scaled event.

        Args:
            pool_id: Pool identifier
            worker_count: New worker count

        Returns:
            True if broadcast successful, False otherwise
        """
        event_data = {
            "pool_id": pool_id,
            "worker_count": worker_count,
            "timestamp": self._get_timestamp(),
        }

        return await self._broadcast(
            event="pool.scaled",
            event_data=event_data,
            room=f"pool:{pool_id}",
        )

    async def broadcast_pool_status_changed(
        self,
        pool_id: str,
        status: str | dict[str, Any],
    ) -> bool:
        """Broadcast pool status changed event.

        Args:
            pool_id: Pool identifier
            status: New status (string or status dict)

        Returns:
            True if broadcast successful, False otherwise
        """
        if isinstance(status, str):
            status = {"state": status}

        event_data = {
            "pool_id": pool_id,
            "status": status,
            "timestamp": self._get_timestamp(),
        }

        return await self._broadcast(
            event="pool.status_changed",
            event_data=event_data,
            room=f"pool:{pool_id}",
        )

    # Worker events

    async def broadcast_worker_added(
        self,
        pool_id: str,
        worker_id: str,
    ) -> bool:
        """Broadcast worker added event.

        Args:
            pool_id: Pool identifier
            worker_id: Worker identifier

        Returns:
            True if broadcast successful, False otherwise
        """
        event_data = {
            "pool_id": pool_id,
            "worker_id": worker_id,
            "timestamp": self._get_timestamp(),
        }

        return await self._broadcast(
            event="worker.added",
            event_data=event_data,
            room=f"pool:{pool_id}",
        )

    async def broadcast_worker_removed(
        self,
        pool_id: str,
        worker_id: str,
    ) -> bool:
        """Broadcast worker removed event.

        Args:
            pool_id: Pool identifier
            worker_id: Worker identifier

        Returns:
            True if broadcast successful, False otherwise
        """
        event_data = {
            "pool_id": pool_id,
            "worker_id": worker_id,
            "timestamp": self._get_timestamp(),
        }

        return await self._broadcast(
            event="worker.removed",
            event_data=event_data,
            room=f"pool:{pool_id}",
        )

    async def broadcast_worker_status_changed(
        self,
        pool_id: str,
        worker_id: str,
        status: str,
    ) -> bool:
        """Broadcast worker status changed event.

        Args:
            pool_id: Pool identifier
            worker_id: Worker identifier
            status: New status (idle, busy, error, etc.)

        Returns:
            True if broadcast successful, False otherwise
        """
        event_data = {
            "pool_id": pool_id,
            "worker_id": worker_id,
            "status": status,
            "timestamp": self._get_timestamp(),
        }

        return await self._broadcast(
            event="worker.status_changed",
            event_data=event_data,
            room=f"pool:{pool_id}",
        )

    # Task events

    async def broadcast_task_assigned(
        self,
        pool_id: str,
        worker_id: str,
        task: dict[str, Any],
    ) -> bool:
        """Broadcast task assigned event.

        Args:
            pool_id: Pool identifier
            worker_id: Worker assigned to
            task: Task specification

        Returns:
            True if broadcast successful, False otherwise
        """
        event_data = {
            "pool_id": pool_id,
            "worker_id": worker_id,
            "task": task,
            "timestamp": self._get_timestamp(),
        }

        return await self._broadcast(
            event="task.assigned",
            event_data=event_data,
            room=f"pool:{pool_id}",
        )

    async def broadcast_task_completed(
        self,
        pool_id: str,
        worker_id: str,
        result: dict[str, Any],
    ) -> bool:
        """Broadcast task completed event.

        Args:
            pool_id: Pool identifier
            worker_id: Worker that completed task
            result: Task result

        Returns:
            True if broadcast successful, False otherwise
        """
        event_data = {
            "pool_id": pool_id,
            "worker_id": worker_id,
            "result": result,
            "timestamp": self._get_timestamp(),
        }

        return await self._broadcast(
            event="task.completed",
            event_data=event_data,
            room=f"pool:{pool_id}",
        )

    # Connection management

    async def broadcast_pool_closed(
        self,
        pool_id: str,
    ) -> bool:
        """Broadcast pool closed event.

        Args:
            pool_id: Pool identifier

        Returns:
            True if broadcast successful, False otherwise
        """
        event_data = {
            "pool_id": pool_id,
            "timestamp": self._get_timestamp(),
        }

        return await self._broadcast(
            event="pool.closed",
            event_data=event_data,
            room=f"pool:{pool_id}",
        )

    # Internal broadcasting methods

    async def _broadcast(
        self,
        event: str,
        event_data: dict[str, Any],
        room: str,
    ) -> bool:
        """Internal broadcast method with error handling and buffering.

        Args:
            event: Event name
            event_data: Event data
            room: Target room

        Returns:
            True if broadcast successful, False otherwise
        """
        if self.server is None:
            logger.debug(f"WebSocket server not configured, skipping broadcast: {event}")
            if self._buffer_enabled:
                self._buffer_event(event, event_data, room)
            return False

        if not hasattr(self.server, "is_running") or not self.server.is_running:
            logger.debug(f"WebSocket server not running, skipping broadcast: {event}")
            if self._buffer_enabled:
                self._buffer_event(event, event_data, room)
            return False

        try:
            message = WebSocketProtocol.create_event(
                event=event,
                data=event_data,
                room=room,
            )
            await self.server.broadcast_to_room(room, message)
            logger.debug(f"Broadcast {event} to {room}")
            return True

        except Exception as e:
            logger.warning(f"Failed to broadcast {event}: {e}")
            if self._buffer_enabled:
                self._buffer_event(event, event_data, room)

            # Try to reconnect on connection errors
            if self._is_connection_error(e):
                await self._attempt_reconnect()

            return False

    def _buffer_event(
        self,
        event: str,
        event_data: dict[str, Any],
        room: str,
    ) -> None:
        """Buffer event when WebSocket is disconnected.

        Args:
            event: Event name
            event_data: Event data
            room: Target room
        """
        if not self._buffer_enabled:
            return

        buffered_event = {
            "event": event,
            "event_data": event_data,
            "room": room,
        }

        self._event_buffer.append(buffered_event)
        logger.debug(f"Buffered event: {event} (buffer size: {len(self._event_buffer)})")

    # Symbiotic Ecosystem Events

    async def broadcast_learning_metrics(
        self,
        patterns_strengthened: int = 0,
        patterns_weakened: int = 0,
        model_retrains: int = 0,
        avg_confidence_score: float = 0.0,
        user_id: str | None = None,
    ) -> bool:
        """Broadcast continuous learning metrics from symbiotic ecosystem.

        Args:
            patterns_strengthened: Number of patterns strengthened
            patterns_weakened: Number of patterns weakened
            model_retrains: Number of model retrains
            avg_confidence_score: Average confidence score (0-100)
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            True if broadcast successful, False otherwise
        """
        event_data = {
            "patterns_strengthened": patterns_strengthened,
            "patterns_weakened": patterns_weakened,
            "model_retrains": model_retrains,
            "avg_confidence_score": round(avg_confidence_score, 2),
            "timestamp": self._get_timestamp(),
        }

        return await self._broadcast(
            event="learning.metrics",
            event_data=event_data,
            room="symbiotic:ecosystem",
        )

    async def broadcast_skill_effectiveness(
        self,
        skill_name: str,
        success_rate: float,
        total_attempts: int = 0,
        avg_confidence: float = 0.0,
        user_id: str | None = None,
    ) -> bool:
        """Broadcast skill effectiveness metrics.

        Args:
            skill_name: Name of skill (e.g., RefactoringAgent, TestAgent)
            success_rate: Success percentage (0-100)
            total_attempts: Total number of attempts
            avg_confidence: Average confidence score
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            True if broadcast successful, False otherwise
        """
        event_data = {
            "skill_name": skill_name,
            "success_rate": round(success_rate, 2),
            "total_attempts": total_attempts,
            "avg_confidence": round(avg_confidence, 2),
            "timestamp": self._get_timestamp(),
        }

        return await self._broadcast(
            event="skill.effectiveness",
            event_data=event_data,
            room="symbiotic:ecosystem",
        )

    async def broadcast_strategy_recommender_metrics(
        self,
        recommendations_made: int = 0,
        high_confidence_count: int = 0,
        avg_success_rate: float = 0.0,
        user_id: str | None = None,
    ) -> bool:
        """Broadcast strategy recommender performance metrics.

        Args:
            recommendations_made: Total recommendations made
            high_confidence_count: High confidence recommendations
            avg_success_rate: Average success rate
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            True if broadcast successful, False otherwise
        """
        event_data = {
            "recommendations_made": recommendations_made,
            "high_confidence_count": high_confidence_count,
            "avg_success_rate": round(avg_success_rate, 2),
            "timestamp": self._get_timestamp(),
        }

        return await self._broadcast(
            event="strategy.recommender",
            event_data=event_data,
            room="symbiotic:ecosystem",
        )

    async def flush_buffer(self) -> int:
        """Flush buffered events to WebSocket server.

        Returns:
            Number of events successfully flushed

        Example:
            >>> broadcaster = WebSocketBroadcaster(server, buffer_enabled=True)
            >>> # ... events broadcast while disconnected ...
            >>> await broadcaster.flush_buffer()  # Flush after reconnect
        """
        if not self._event_buffer:
            return 0

        flushed = 0
        failed_events = []

        while self._event_buffer:
            buffered = self._event_buffer.popleft()

            try:
                success = await self._broadcast(
                    event=buffered["event"],
                    event_data=buffered["event_data"],
                    room=buffered["room"],
                )
                if success:
                    flushed += 1
                else:
                    failed_events.append(buffered)

            except Exception as e:
                logger.error(f"Error flushing buffered event: {e}")
                failed_events.append(buffered)

        # Put failed events back in buffer
        for event in failed_events:
            self._event_buffer.append(event)

        if flushed > 0:
            logger.info(f"Flushed {flushed} buffered events")

        return flushed

    def _is_connection_error(self, error: Exception) -> bool:
        """Check if error is a connection error.

        Args:
            error: Exception to check

        Returns:
            True if connection error, False otherwise
        """
        error_msg = str(error).lower()
        connection_indicators = [
            "connection",
            "websocket",
            "network",
            "broken pipe",
            "connection reset",
        ]
        return any(indicator in error_msg for indicator in connection_indicators)

    async def _attempt_reconnect(self) -> None:
        """Attempt to reconnect WebSocket server."""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.error("Max reconnection attempts reached")
            return

        self._reconnect_attempts += 1
        logger.info(f"Attempting reconnection (attempt {self._reconnect_attempts})")

        # Exponential backoff
        await asyncio.sleep(2**self._reconnect_attempts)

        # Reset attempts after backoff
        if self._reconnect_attempts >= 3:
            self._reconnect_attempts = 0

    def set_server(self, websocket_server: Any) -> None:
        """Set or update WebSocket server instance.

        Args:
            websocket_server: MahavishnuWebSocketServer instance

        Example:
            >>> broadcaster = WebSocketBroadcaster()
            >>> # ... later ...
            >>> broadcaster.set_server(server_instance)
        """
        self.server = websocket_server
        logger.info("WebSocket server updated")

    def clear_buffer(self) -> int:
        """Clear event buffer.

        Returns:
            Number of events cleared
        """
        count = len(self._event_buffer)
        self._event_buffer.clear()
        logger.debug(f"Cleared {count} buffered events")
        return count

    @staticmethod
    def _get_timestamp() -> str:
        """Get current ISO timestamp.

        Returns:
            ISO-formatted timestamp string
        """
        return datetime.now(UTC).isoformat()


def create_broadcaster(
    websocket_server: Any | None = None,
    buffer_enabled: bool = False,
    buffer_size: int = 1000,
) -> WebSocketBroadcaster:
    """Create WebSocket broadcaster instance.

    Factory function for creating WebSocketBroadcaster with sensible defaults.

    Args:
        websocket_server: MahavishnuWebSocketServer instance
        buffer_enabled: Whether to buffer events when disconnected
        buffer_size: Maximum buffer size

    Returns:
        WebSocketBroadcaster instance

    Example:
        >>> from mahavishnu.pools.websocket import create_broadcaster
        >>>
        >>> broadcaster = create_broadcaster(server, buffer_enabled=True)
        >>> await broadcaster.broadcast_pool_spawned("pool_abc", config)
    """
    return WebSocketBroadcaster(
        websocket_server=websocket_server,
        buffer_enabled=buffer_enabled,
        buffer_size=buffer_size,
    )
