"""Rate limiting and DDoS protection for Mahavishnu MCP server.

Implements in-memory rate limiting with configurable limits and strategies.
Supports IP-based, user-based, and token-based rate limiting.
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from logging import getLogger
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting.

    Args:
        requests_per_minute: Maximum requests per minute
        requests_per_hour: Maximum requests per hour
        requests_per_day: Maximum requests per day
        burst_size: Maximum burst size (token bucket)
        enabled: Whether rate limiting is enabled
        exempt_ips: Set of IP addresses to exempt from rate limiting
        exempt_user_ids: Set of user IDs to exempt from rate limiting
    """

    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    requests_per_day: int = 10000
    burst_size: int = 10
    enabled: bool = True
    exempt_ips: set[str] = field(default_factory=set)
    exempt_user_ids: set[str] = field(default_factory=set)


@dataclass
class RateLimitInfo:
    """Rate limit information for a client.

    Args:
        request_count: Number of requests made
        window_start: Start of the current window
        reset_time: When the rate limit window resets
        limited: Whether the client is currently rate limited
        retry_after: Seconds until client can retry (if limited)
    """

    request_count: int = 0
    window_start: float = field(default_factory=time.time)
    reset_time: float = field(default_factory=lambda: time.time() + 60)
    limited: bool = False
    retry_after: int | None = None


class RateLimiter:
    """In-memory rate limiter using sliding window and token bucket algorithms.

    Supports multiple rate limiting strategies:
    - Sliding window for per-minute/hour/day limits
    - Token bucket for burst control
    - IP-based, user-based, and token-based tracking

    Example:
        ```python
        limiter = RateLimiter(
            per_minute=60,
            per_hour=1000,
            burst_size=10
        )

        # Check if request is allowed
        if await limiter.is_allowed(ip_address="192.168.1.1"):
            # Process request
            pass
        else:
            # Return rate limit error
            pass
        ```
    """

    def __init__(
        self,
        per_minute: int = 60,
        per_hour: int = 1000,
        per_day: int = 10000,
        burst_size: int = 10,
        cleanup_interval: int = 300,  # 5 minutes
    ):
        """Initialize the rate limiter.

        Args:
            per_minute: Maximum requests per minute per client
            per_hour: Maximum requests per hour per client
            per_day: Maximum requests per day per client
            burst_size: Maximum burst size (token bucket)
            cleanup_interval: Seconds between cleanup of old entries
        """
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.per_day = per_day
        self.burst_size = burst_size
        self.cleanup_interval = cleanup_interval

        # Sliding window tracking: {key: [(timestamp, count), ...]}
        self._requests: dict[str, list[tuple[float, int]]] = defaultdict(list)

        # Token bucket tracking: {key: tokens}
        self._tokens: dict[str, float] = defaultdict(lambda: burst_size)

        # Last update time for token buckets
        self._last_update: dict[str, float] = defaultdict(time.time)

        # Rate limit violations tracking
        self._violations: dict[str, list[float]] = defaultdict(list)

        # Start cleanup task
        self._cleanup_task: asyncio.Task | None = None

    def _cleanup_old_entries(self):
        """Remove old entries from tracking dictionaries."""
        now = time.time()
        cutoff_time = now - self.cleanup_interval

        # Clean up request history
        for key in list(self._requests.keys()):
            self._requests[key] = [
                (ts, count) for ts, count in self._requests[key] if ts > cutoff_time
            ]
            if not self._requests[key]:
                del self._requests[key]

        # Clean up violations
        for key in list(self._violations.keys()):
            self._violations[key] = [ts for ts in self._violations[key] if ts > cutoff_time]
            if not self._violations[key]:
                del self._violations[key]

    async def is_allowed(
        self,
        key: str,
        config: RateLimitConfig | None = None,
    ) -> tuple[bool, RateLimitInfo]:
        """Check if a request is allowed under rate limits.

        Args:
            key: Unique identifier for the client (IP, user ID, etc.)
            config: Optional rate limit configuration

        Returns:
            Tuple of (allowed: bool, rate_limit_info: RateLimitInfo)
        """
        if config and not config.enabled:
            return True, RateLimitInfo(limited=False)

        if config and key in config.exempt_ips:
            return True, RateLimitInfo(limited=False)

        now = time.time()

        # Check if key is currently in violation cooldown
        if key in self._violations and self._violations[key]:
            # Check if there was a recent violation (within last minute)
            recent_violations = [v for v in self._violations[key] if now - v < 60]
            if len(recent_violations) >= 5:
                # Too many recent violations, extend rate limit
                retry_after = 300  # 5 minutes
                return False, RateLimitInfo(
                    limited=True,
                    retry_after=retry_after,
                    reset_time=now + retry_after,
                )

        # Check per-minute limit
        minute_ago = now - 60
        recent_requests = [(ts, count) for ts, count in self._requests[key] if ts > minute_ago]

        # Check token bucket for burst control
        tokens = self._tokens[key]
        last_update = self._last_update[key]
        time_passed = now - last_update

        # Refill tokens based on time passed (1 token per second)
        refill_rate = 1.0
        tokens = min(self.burst_size, tokens + time_passed * refill_rate)
        self._tokens[key] = tokens
        self._last_update[key] = now

        # Check if we have tokens for this request
        if tokens < 1:
            # Token bucket exhausted
            retry_after = int((1 - tokens) / refill_rate) + 1
            return False, RateLimitInfo(
                limited=True,
                retry_after=retry_after,
                reset_time=now + retry_after,
            )

        # Consume a token
        self._tokens[key] = tokens - 1

        # Check per-minute limit (sum of recent request counts)
        total_requests = sum(count for _, count in recent_requests)

        if total_requests >= self.per_minute:
            # Rate limited
            retry_after = 60 - int(now - recent_requests[0][0]) if recent_requests else 60
            return False, RateLimitInfo(
                limited=True,
                retry_after=retry_after,
                reset_time=now + retry_after,
            )

        # Check per-hour limit
        hour_ago = now - 3600
        hour_requests = sum(count for ts, count in self._requests[key] if ts > hour_ago)

        if hour_requests >= self.per_hour:
            retry_after = 3600 - int(now - hour_ago) + 1
            return False, RateLimitInfo(
                limited=True,
                retry_after=retry_after,
                reset_time=now + retry_after,
            )

        # Check per-day limit
        day_ago = now - 86400
        day_requests = sum(count for ts, count in self._requests[key] if ts > day_ago)

        if day_requests >= self.per_day:
            retry_after = 86400 - int(now - day_ago) + 1
            return False, RateLimitInfo(
                limited=True,
                retry_after=retry_after,
                reset_time=now + retry_after,
            )

        # Request is allowed, record it
        self._requests[key].append((now, 1))

        return True, RateLimitInfo(
            request_count=total_requests + 1,
            window_start=recent_requests[0][0] if recent_requests else now,
            reset_time=now + 60 - (now - recent_requests[0][0]) if recent_requests else now + 60,
            limited=False,
        )

    def record_violation(self, key: str):
        """Record a rate limit violation.

        Args:
            key: Unique identifier for the client
        """
        self._violations[key].append(time.time())

    def get_stats(self, key: str | None = None) -> dict[str, Any]:
        """Get rate limiting statistics.

        Args:
            key: Optional specific key to get stats for

        Returns:
            Dictionary with rate limit statistics
        """
        now = time.time()

        if key:
            # Get stats for specific key
            minute_ago = now - 60
            hour_ago = now - 3600
            day_ago = now - 86400

            requests = self._requests.get(key, [])
            minute_requests = sum(count for ts, count in requests if ts > minute_ago)
            hour_requests = sum(count for ts, count in requests if ts > hour_ago)
            day_requests = sum(count for ts, count in requests if ts > day_ago)
            violations = len(self._violations.get(key, []))

            return {
                "key": key,
                "requests_per_minute": minute_requests,
                "requests_per_hour": hour_requests,
                "requests_per_day": day_requests,
                "violations": violations,
                "current_tokens": self._tokens.get(key, self.burst_size),
            }

        # Get global stats
        total_clients = len(self._requests)
        total_violations = sum(len(v) for v in self._violations.values())

        # Calculate total requests across all clients
        total_requests = sum(
            sum(count for _, count in requests) for requests in self._requests.values()
        )

        return {
            "total_clients": total_clients,
            "total_requests": total_requests,
            "total_violations": total_violations,
            "active_clients": len(
                [
                    k
                    for k, v in self._requests.items()
                    if any(ts > now - 300 for ts, _ in v)  # Active in last 5 minutes
                ]
            ),
        }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware for rate limiting HTTP requests.

    Example:
        ```python
        from starlette.applications import Starlette

        app = Starlette()
        rate_limit_config = RateLimitConfig(
            requests_per_minute=60,
            requests_per_hour=1000
        )
        app.add_middleware(
            RateLimitMiddleware,
            config=rate_limit_config
        )
        ```
    """

    def __init__(
        self,
        app,
        config: RateLimitConfig | None = None,
        limiter: RateLimiter | None = None,
    ):
        """Initialize the rate limit middleware.

        Args:
            app: ASGI application
            config: Rate limit configuration
            limiter: Optional custom rate limiter instance
        """
        super().__init__(app)
        self.config = config or RateLimitConfig()
        self.limiter = limiter or RateLimiter(
            per_minute=self.config.requests_per_minute,
            per_hour=self.config.requests_per_hour,
            per_day=self.config.requests_per_day,
            burst_size=self.config.burst_size,
        )

    async def dispatch(self, request: Request, call_next):
        """Process request through rate limiting middleware.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware or route handler

        Returns:
            HTTP response (either rate limited or normal response)
        """
        # Get client identifier (IP address or user ID)
        client_ip = self._get_client_ip(request)

        # Check if user is authenticated
        user_id = request.headers.get("X-User-ID")
        if user_id and user_id in self.config.exempt_user_ids:
            # Exempt user, proceed normally
            return await call_next(request)

        # Use user ID as key if authenticated, otherwise use IP
        key = user_id if user_id else client_ip

        # Check rate limit
        allowed, rate_limit_info = await self.limiter.is_allowed(key, self.config)

        # Add rate limit headers to response
        headers = {
            "X-RateLimit-Limit": str(self.config.requests_per_minute),
            "X-RateLimit-Remaining": str(
                max(0, self.config.requests_per_minute - rate_limit_info.request_count)
            ),
            "X-RateLimit-Reset": str(int(rate_limit_info.reset_time)),
        }

        if not allowed:
            # Rate limited, record violation
            self.limiter.record_violation(key)

            logger.warning(f"Rate limit exceeded for {key} (IP: {client_ip}, User: {user_id})")

            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "retry_after": rate_limit_info.retry_after,
                    "reset_time": rate_limit_info.reset_time,
                },
                headers={
                    **headers,
                    "Retry-After": str(rate_limit_info.retry_after or 60),
                },
            )

        # Process request normally
        response = await call_next(request)

        # Add rate limit headers to response
        for key, value in headers.items():
            response.headers[key] = value

        return response

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request.

        Handles proxies and load balancers by checking X-Forwarded-For header.

        Args:
            request: Incoming HTTP request

        Returns:
            Client IP address as string
        """
        # Check for proxy headers
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs, take the first one (original client)
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct connection IP
        if request.client:
            return request.client.host

        return "unknown"


def rate_limit(
    requests_per_minute: int = 60,
    requests_per_hour: int = 1000,
    burst_size: int = 10,
    key_func: Callable[[Request], str] | None = None,
):
    """Decorator for rate limiting individual tool functions.

    Example:
        ```python
        @rate_limit(requests_per_minute=10)
        async def expensive_tool(param: str) -> dict:
            # Tool implementation
            pass
        ```

    Args:
        requests_per_minute: Maximum requests per minute
        requests_per_hour: Maximum requests per hour
        burst_size: Maximum burst size
        key_func: Optional function to extract rate limit key from request

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        # Create rate limiter for this tool
        limiter = RateLimiter(
            per_minute=requests_per_minute,
            per_hour=requests_per_hour,
            burst_size=burst_size,
        )

        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Try to extract request from arguments
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            # Get rate limit key
            if key_func and request:
                key = key_func(request)
            elif request:
                # Default key: IP address or user ID
                key = request.headers.get("X-User-ID") or rate_limit_middleware._get_client_ip(
                    request
                )
            else:
                # No request context, skip rate limiting
                return await func(*args, **kwargs)

            # Check rate limit
            allowed, rate_limit_info = await limiter.is_allowed(key)

            if not allowed:
                limiter.record_violation(key)

                raise RateLimitError(
                    f"Rate limit exceeded for {func.__name__}",
                    retry_after=rate_limit_info.retry_after,
                )

            # Call original function
            return await func(*args, **kwargs)

        return wrapper

    return decorator


class RateLimitError(Exception):
    """Exception raised when rate limit is exceeded.

    Args:
        message: Error message
        retry_after: Seconds until client can retry
    """

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


# Global rate limit middleware instance (for use in key_func)
rate_limit_middleware = RateLimitMiddleware(app=None)
