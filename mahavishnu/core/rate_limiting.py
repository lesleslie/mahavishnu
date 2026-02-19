"""
Rate limiting for Mahavishnu Task Orchestration.

This module provides rate limiting using slowapi (FastAPI-compatible)
with configurable limits for different endpoints.

Created: 2026-02-18
Version: 3.1
Related: 4-Agent Opus Review P0 issue - rate limiting middleware
"""

import logging
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Rate limit configuration for different operations
RATE_LIMITS = {
    # Task operations
    "task_create": "10/minute",       # 10 task creations per minute
    "task_update": "30/minute",       # 30 task updates per minute
    "task_delete": "10/minute",       # 10 task deletions per minute
    "task_search": "30/minute",       # 30 searches per minute

    # Repository operations
    "repo_list": "60/minute",         # 60 repo list requests per minute
    "repo_sync": "5/minute",          # 5 repo syncs per minute

    # Webhook processing
    "webhook_github": "100/minute",   # 100 GitHub webhooks per minute
    "webhook_gitlab": "100/minute",   # 100 GitLab webhooks per minute

    # API general
    "api_general": "60/minute",       # 60 general API calls per minute
    "api_read": "120/minute",         # 120 read operations per minute
    "api_write": "30/minute",         # 30 write operations per minute

    # Embedding/NLP operations (more expensive)
    "embedding": "20/minute",         # 20 embedding requests per minute
    "nlp_parse": "30/minute",         # 30 NLP parsing requests per minute

    # WebSocket
    "websocket": "10/minute",         # 10 WebSocket connections per minute
}

# Try to import slowapi, but provide fallback if not available
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    HAS_SLOWAPI = True
except ImportError:
    HAS_SLOWAPI = False
    logger.warning("slowapi not installed, rate limiting will be disabled")


def get_client_ip(request: Request) -> str:
    """
    Get client IP address from request.

    Handles proxied requests by checking X-Forwarded-For header.

    Args:
        request: FastAPI request object

    Returns:
        Client IP address as string
    """
    # Check for proxied requests
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    # Fall back to direct client IP
    if request.client:
        return request.client.host

    return "127.0.0.1"


# Create limiter instance (or None if slowapi not available)
if HAS_SLOWAPI:
    limiter = Limiter(key_func=get_client_ip)
else:
    limiter = None


def setup_rate_limiting(app: FastAPI) -> None:
    """
    Configure rate limiting for the FastAPI app.

    Usage:
        app = FastAPI()
        setup_rate_limiting(app)

    Args:
        app: FastAPI application instance
    """
    if not HAS_SLOWAPI:
        logger.warning("Rate limiting disabled - slowapi not installed")
        return

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    logger.info("Rate limiting configured successfully")


async def rate_limit_exceeded_handler(
    request: Request,
    exc: RateLimitExceeded,
) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors.

    Returns a structured JSON response with error code MHV-006.

    Args:
        request: FastAPI request object
        exc: RateLimitExceeded exception

    Returns:
        JSON response with rate limit error details
    """
    from mahavishnu.core.errors import ErrorCode

    response = JSONResponse(
        status_code=429,
        content={
            "error_code": ErrorCode.RATE_LIMIT_EXCEEDED.value,
            "message": "Rate limit exceeded. Please slow down.",
            "recovery": [
                "Wait a moment before retrying",
                "Reduce request frequency",
                f"Limit: {exc.detail}",
            ],
            "detail": exc.detail,
            "documentation": "https://docs.mahavishnu.org/errors/mhv-006",
        },
    )
    response.headers["Retry-After"] = "60"
    response.headers["X-RateLimit-Reset"] = "60"
    return response


# Decorator for rate limiting (with fallback if slowapi not available)
def rate_limit(limit: str) -> Callable:
    """
    Decorator for rate limiting endpoints.

    Usage:
        @app.post("/tasks")
        @rate_limit("10/minute")
        async def create_task(request: Request, ...):
            ...

    Args:
        limit: Rate limit string (e.g., "10/minute", "100/hour")

    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        if HAS_SLOWAPI and limiter is not None:
            return limiter.limit(limit)(func)
        return func
    return decorator


# Convenience decorators for common rate limits
def limit_task_create(func: Callable) -> Callable:
    """Apply task creation rate limit."""
    return rate_limit(RATE_LIMITS["task_create"])(func)


def limit_task_search(func: Callable) -> Callable:
    """Apply task search rate limit."""
    return rate_limit(RATE_LIMITS["task_search"])(func)


def limit_webhook(func: Callable) -> Callable:
    """Apply webhook rate limit."""
    return rate_limit(RATE_LIMITS["webhook_github"])(func)


def limit_api_general(func: Callable) -> Callable:
    """Apply general API rate limit."""
    return rate_limit(RATE_LIMITS["api_general"])(func)


def limit_embedding(func: Callable) -> Callable:
    """Apply embedding service rate limit."""
    return rate_limit(RATE_LIMITS["embedding"])(func)


def limit_nlp(func: Callable) -> Callable:
    """Apply NLP parsing rate limit."""
    return rate_limit(RATE_LIMITS["nlp_parse"])(func)
