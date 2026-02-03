"""Rate limiting integration for FastMCP tools.

Provides decorators and utilities for rate limiting individual MCP tools.
Designed to work with FastMCP's tool-based architecture.
"""

from collections.abc import Callable
from functools import wraps
from logging import getLogger
from typing import Any

from ..core.rate_limit import RateLimitConfig, RateLimiter

logger = getLogger(__name__)


# Global rate limiter instance
_global_limiter: RateLimiter | None = None

# Rate limit statistics by tool
_tool_stats: dict[str, dict[str, Any]] = {}


def get_global_limiter(config: RateLimitConfig | None = None) -> RateLimiter:
    """Get or create the global rate limiter instance.

    Args:
        config: Optional rate limit configuration

    Returns:
        Global RateLimiter instance
    """
    global _global_limiter

    if _global_limiter is None:
        if config:
            _global_limiter = RateLimiter(
                per_minute=config.requests_per_minute,
                per_hour=config.requests_per_hour,
                per_day=config.requests_per_day,
                burst_size=config.burst_size,
            )
        else:
            # Default limits
            _global_limiter = RateLimiter(
                per_minute=60,
                per_hour=1000,
                per_day=10000,
                burst_size=10,
            )

    return _global_limiter


def rate_limit_tool(
    requests_per_minute: int = 60,
    requests_per_hour: int = 1000,
    burst_size: int = 10,
    key_func: Callable[[dict[str, Any]], str] | None = None,
):
    """Decorator for rate limiting FastMCP tool functions.

    Example:
        ```python
        @rate_limit_tool(requests_per_minute=10)
        async def expensive_tool(param: str) -> dict[str, Any]:
            # Tool implementation
            return {"result": "success"}
        ```

    Args:
        requests_per_minute: Maximum requests per minute
        requests_per_hour: Maximum requests per hour
        burst_size: Maximum burst size
        key_func: Optional function to extract rate limit key from tool params

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        tool_name = func.__name__

        # Initialize stats for this tool
        if tool_name not in _tool_stats:
            _tool_stats[tool_name] = {
                "total_calls": 0,
                "rate_limited_calls": 0,
                "last_limited": None,
            }

        # Create rate limiter for this tool
        limiter = RateLimiter(
            per_minute=requests_per_minute,
            per_hour=requests_per_hour,
            burst_size=burst_size,
        )

        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Update stats
            _tool_stats[tool_name]["total_calls"] += 1

            # Get rate limit key from params if function provided
            key = "default"
            if key_func and kwargs:
                try:
                    key = key_func(kwargs)
                except Exception as e:
                    logger.warning(f"Failed to get rate limit key: {e}")
                    key = "default"

            # Try to extract user_id or IP from kwargs
            # FastMCP tools receive params as kwargs
            user_id = kwargs.get("user_id")
            if user_id:
                key = f"user:{user_id}"

            # Check rate limit
            allowed, rate_limit_info = await limiter.is_allowed(key)

            if not allowed:
                # Update violation stats
                limiter.record_violation(key)
                _tool_stats[tool_name]["rate_limited_calls"] += 1
                _tool_stats[tool_name]["last_limited"] = rate_limit_info.reset_time

                logger.warning(
                    f"Rate limit exceeded for tool {tool_name} "
                    f"(key={key}, retry_after={rate_limit_info.retry_after})"
                )

                # Return error response instead of raising exception
                # This is more appropriate for MCP tools
                return {
                    "error": "Rate limit exceeded",
                    "error_type": "rate_limit_exceeded",
                    "tool_name": tool_name,
                    "retry_after": rate_limit_info.retry_after,
                    "reset_time": rate_limit_info.reset_time,
                }

            # Call original function
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                # Log error but don't wrap it
                logger.error(f"Error in rate-limited tool {tool_name}: {e}")
                raise

        return wrapper

    return decorator


def get_tool_rate_limit_stats(tool_name: str) -> dict[str, Any]:
    """Get rate limit statistics for a specific tool.

    Args:
        tool_name: Name of the tool to get stats for

    Returns:
        Dictionary with rate limit statistics
    """
    if tool_name not in _tool_stats:
        return {
            "tool_name": tool_name,
            "error": "Tool not found or no stats available",
        }

    return {
        "tool_name": tool_name,
        **_tool_stats[tool_name],
    }


def get_all_rate_limit_stats() -> dict[str, Any]:
    """Get rate limit statistics for all tools.

    Returns:
        Dictionary with statistics for all tools
    """
    total_calls = sum(stats.get("total_calls", 0) for stats in _tool_stats.values())
    total_rate_limited = sum(stats.get("rate_limited_calls", 0) for stats in _tool_stats.values())

    return {
        "total_calls": total_calls,
        "total_rate_limited": total_rate_limited,
        "rate_limit_rate": (total_rate_limited / total_calls if total_calls > 0 else 0),
        "tools": dict(_tool_stats),
    }


def reset_tool_stats(tool_name: str | None = None):
    """Reset rate limit statistics.

    Args:
        tool_name: Optional specific tool to reset, or None to reset all
    """
    global _tool_stats

    if tool_name:
        if tool_name in _tool_stats:
            _tool_stats[tool_name] = {
                "total_calls": 0,
                "rate_limited_calls": 0,
                "last_limited": None,
            }
    else:
        _tool_stats.clear()
