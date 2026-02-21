"""Token bucket rate limiter for WebSocket connections.

This module provides a specialized rate limiter for WebSocket message handling,
using the token bucket algorithm for smooth rate limiting with burst control.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RateLimitResult:
    """Result of a rate limit check.

    Attributes:
        allowed: Whether the message is allowed
        retry_after: Seconds until the client can retry (if limited)
        tokens_remaining: Number of tokens remaining in the bucket
        limited: Whether the message was rate limited
    """

    allowed: bool = True
    retry_after: float = 0.0
    tokens_remaining: float = 0.0
    limited: bool = False


class TokenBucketRateLimiter:
    """Token bucket rate limiter for WebSocket connections.

    Implements per-connection rate limiting using the token bucket algorithm:
    - Tokens are added at a fixed rate (message_rate_limit per second)
    - Each message consumes one token
    - Bucket has a maximum capacity (burst_size)
    - Messages are rejected when bucket is empty

    This provides smooth rate limiting while allowing short bursts.

    Example:
        >>> limiter = TokenBucketRateLimiter(rate=100, burst_size=150)
        >>> result = limiter.check("connection_123")
        >>> if result.allowed:
        ...     # Process message
        ...     pass
        ... else:
        ...     # Send rate limit error
        ...     print(f"Rate limited, retry after {result.retry_after}s")
    """

    def __init__(
        self,
        rate: float = 100.0,
        burst_size: float | None = None,
        cleanup_interval: float = 300.0,
    ):
        """Initialize the token bucket rate limiter.

        Args:
            rate: Messages per second allowed (default: 100)
            burst_size: Maximum tokens in bucket (default: 1.5x rate)
            cleanup_interval: Seconds between cleanup of idle connections
        """
        self.rate = rate
        self.burst_size = burst_size if burst_size is not None else rate * 1.5
        self.cleanup_interval = cleanup_interval

        # Per-connection token buckets: {connection_id: tokens}
        self._tokens: dict[str, float] = {}

        # Last update time for each connection: {connection_id: timestamp}
        self._last_update: dict[str, float] = {}

        # Track rate limit events for logging
        self._rate_limit_events: dict[str, list[float]] = defaultdict(list)

        # Last cleanup time
        self._last_cleanup = time.time()

        logger.info(
            f"TokenBucketRateLimiter initialized: rate={rate}/s, "
            f"burst_size={self.burst_size}, cleanup_interval={cleanup_interval}s"
        )

    def _get_or_create_bucket(self, connection_id: str) -> tuple[float, float]:
        """Get or create a token bucket for a connection.

        Args:
            connection_id: Unique connection identifier

        Returns:
            Tuple of (current_tokens, last_update_time)
        """
        now = time.time()

        if connection_id not in self._tokens:
            # New connection starts with full bucket
            self._tokens[connection_id] = self.burst_size
            self._last_update[connection_id] = now
            return self.burst_size, now

        return self._tokens[connection_id], self._last_update[connection_id]

    def _refill_tokens(
        self,
        connection_id: str,
        tokens: float,
        last_update: float,
    ) -> float:
        """Refill tokens based on time elapsed.

        Args:
            connection_id: Connection identifier
            tokens: Current token count
            last_update: Last update timestamp

        Returns:
            Updated token count
        """
        now = time.time()
        elapsed = now - last_update

        # Add tokens based on elapsed time
        new_tokens = tokens + (elapsed * self.rate)

        # Cap at burst size
        new_tokens = min(new_tokens, self.burst_size)

        return new_tokens

    def check(self, connection_id: str) -> RateLimitResult:
        """Check if a message is allowed for the given connection.

        This method:
        1. Gets or creates the token bucket for the connection
        2. Refills tokens based on time elapsed
        3. Attempts to consume a token
        4. Returns the result

        Args:
            connection_id: Unique connection identifier

        Returns:
            RateLimitResult with allowed status and retry info
        """
        # Periodic cleanup
        self._maybe_cleanup()

        # Get or create bucket
        tokens, last_update = self._get_or_create_bucket(connection_id)

        # Refill tokens
        now = time.time()
        tokens = self._refill_tokens(connection_id, tokens, last_update)

        # Check if we have tokens
        if tokens >= 1.0:
            # Consume a token
            tokens -= 1.0
            self._tokens[connection_id] = tokens
            self._last_update[connection_id] = now

            return RateLimitResult(
                allowed=True,
                tokens_remaining=tokens,
                limited=False,
            )

        # No tokens available - rate limited
        # Calculate retry_after based on tokens needed
        tokens_needed = 1.0 - tokens
        retry_after = tokens_needed / self.rate

        # Update state
        self._tokens[connection_id] = tokens
        self._last_update[connection_id] = now

        # Track rate limit event
        self._rate_limit_events[connection_id].append(now)

        # Log rate limit event (throttled)
        self._log_rate_limit(connection_id, retry_after)

        return RateLimitResult(
            allowed=False,
            retry_after=retry_after,
            tokens_remaining=tokens,
            limited=True,
        )

    def _log_rate_limit(self, connection_id: str, retry_after: float) -> None:
        """Log rate limit event (throttled to avoid spam).

        Args:
            connection_id: Connection identifier
            retry_after: Seconds until retry
        """
        now = time.time()
        events = self._rate_limit_events[connection_id]

        # Only log once per second per connection
        recent_events = [e for e in events if now - e < 1.0]

        if len(recent_events) == 1:
            # First event in this second - log it
            logger.warning(
                f"Rate limit applied to connection {connection_id}: retry_after={retry_after:.3f}s"
            )

    def _maybe_cleanup(self) -> None:
        """Periodically clean up idle connection buckets."""
        now = time.time()

        if now - self._last_cleanup < self.cleanup_interval:
            return

        self._last_cleanup = now
        self._cleanup_idle_buckets()

    def _cleanup_idle_buckets(self) -> None:
        """Remove buckets for connections idle > cleanup_interval."""
        now = time.time()
        cutoff = now - self.cleanup_interval

        # Find idle connections
        idle_connections = [
            conn_id for conn_id, last_update in self._last_update.items() if last_update < cutoff
        ]

        # Remove idle buckets
        for conn_id in idle_connections:
            del self._tokens[conn_id]
            del self._last_update[conn_id]
            if conn_id in self._rate_limit_events:
                del self._rate_limit_events[conn_id]

        if idle_connections:
            logger.debug(f"Cleaned up {len(idle_connections)} idle rate limit buckets")

    def remove_connection(self, connection_id: str) -> None:
        """Remove a connection's rate limit bucket.

        Call this when a connection disconnects to free memory.

        Args:
            connection_id: Connection identifier to remove
        """
        self._tokens.pop(connection_id, None)
        self._last_update.pop(connection_id, None)
        self._rate_limit_events.pop(connection_id, None)

        logger.debug(f"Removed rate limit bucket for connection {connection_id}")

    def get_stats(self, connection_id: str | None = None) -> dict[str, Any]:
        """Get rate limiting statistics.

        Args:
            connection_id: Optional specific connection to get stats for

        Returns:
            Dictionary with rate limit statistics
        """
        now = time.time()

        if connection_id:
            # Stats for specific connection
            tokens = self._tokens.get(connection_id, self.burst_size)
            last_update = self._last_update.get(connection_id, now)
            events = self._rate_limit_events.get(connection_id, [])

            # Count recent rate limit events (last minute)
            recent_events = [e for e in events if now - e < 60]

            return {
                "connection_id": connection_id,
                "tokens": tokens,
                "burst_size": self.burst_size,
                "rate": self.rate,
                "last_update": last_update,
                "rate_limit_events_last_minute": len(recent_events),
            }

        # Global stats
        total_connections = len(self._tokens)
        total_rate_limited = sum(
            len([e for e in events if now - e < 60]) for events in self._rate_limit_events.values()
        )

        # Average tokens across all connections
        avg_tokens = (
            sum(self._tokens.values()) / len(self._tokens) if self._tokens else self.burst_size
        )

        return {
            "total_connections": total_connections,
            "rate": self.rate,
            "burst_size": self.burst_size,
            "average_tokens": avg_tokens,
            "rate_limit_events_last_minute": total_rate_limited,
            "cleanup_interval": self.cleanup_interval,
        }

    def reset(self, connection_id: str | None = None) -> None:
        """Reset rate limit state.

        Args:
            connection_id: Optional specific connection to reset (all if None)
        """
        if connection_id:
            self._tokens[connection_id] = self.burst_size
            self._last_update[connection_id] = time.time()
            self._rate_limit_events.pop(connection_id, None)
            logger.debug(f"Reset rate limit for connection {connection_id}")
        else:
            self._tokens.clear()
            self._last_update.clear()
            self._rate_limit_events.clear()
            logger.info("Reset all rate limit state")


# Module-level singleton for shared rate limiter
_rate_limiter: TokenBucketRateLimiter | None = None


def get_rate_limiter(
    rate: float = 100.0,
    burst_size: float | None = None,
) -> TokenBucketRateLimiter:
    """Get or create the shared rate limiter instance.

    Args:
        rate: Messages per second (only used on first call)
        burst_size: Maximum burst size (only used on first call)

    Returns:
        Shared TokenBucketRateLimiter instance
    """
    global _rate_limiter

    if _rate_limiter is None:
        _rate_limiter = TokenBucketRateLimiter(rate=rate, burst_size=burst_size)

    return _rate_limiter


def reset_rate_limiter() -> None:
    """Reset the shared rate limiter (useful for testing)."""
    global _rate_limiter
    _rate_limiter = None
