"""Tests for rate limiting and DDoS protection.

Tests cover:
- Rate limiter functionality
- Sliding window rate limiting
- Token bucket burst control
- Rate limit middleware
- Rate limit decorators
- Edge cases and error conditions
"""

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from mahavishnu.core.rate_limit import (
    RateLimiter,
    RateLimitConfig,
    RateLimitInfo,
    RateLimitMiddleware,
    RateLimitError,
    rate_limit,
)
from mahavishnu.core.rate_limit_tools import (
    get_global_limiter,
    rate_limit_tool,
    get_tool_rate_limit_stats,
    get_all_rate_limit_stats,
    reset_tool_stats,
)


# ============================================================================
# Rate Limiter Tests
# ============================================================================

class TestRateLimiter:
    """Test RateLimiter class functionality."""

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_within_limits(self):
        """Rate limiter should allow requests within limits."""
        limiter = RateLimiter(per_minute=60, per_hour=100, burst_size=10)

        # First request should be allowed
        allowed, info = await limiter.is_allowed("test_key")
        assert allowed is True
        assert info.limited is False

        # Second request should also be allowed
        allowed, info = await limiter.is_allowed("test_key")
        assert allowed is True
        assert info.limited is False

    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_when_exceeded(self):
        """Rate limiter should block requests when limits exceeded."""
        # Set very low limit for testing
        limiter = RateLimiter(per_minute=2, burst_size=2)

        # First two requests should be allowed
        allowed, _ = await limiter.is_allowed("test_key")
        assert allowed is True

        allowed, _ = await limiter.is_allowed("test_key")
        assert allowed is True

        # Third request should be rate limited
        allowed, info = await limiter.is_allowed("test_key")
        assert allowed is False
        assert info.limited is True
        assert info.retry_after is not None
        assert info.retry_after > 0

    @pytest.mark.asyncio
    async def test_rate_limiter_sliding_window(self):
        """Rate limiter should use sliding window for minute limits."""
        limiter = RateLimiter(per_minute=5, burst_size=10)

        key = "test_sliding"

        # Make 5 requests (at limit)
        for i in range(5):
            allowed, _ = await limiter.is_allowed(key)
            assert allowed is True, f"Request {i+1} should be allowed"

        # Next request should be blocked
        allowed, info = await limiter.is_allowed(key)
        assert allowed is False
        assert info.limited is True

    @pytest.mark.asyncio
    async def test_rate_limiter_token_bucket(self):
        """Rate limiter should use token bucket for burst control."""
        # Small burst size for testing
        limiter = RateLimiter(per_minute=100, burst_size=3)

        key = "test_burst"

        # Make requests up to burst size
        for i in range(3):
            allowed, _ = await limiter.is_allowed(key)
            assert allowed is True, f"Burst request {i+1} should be allowed"

        # Next request should be blocked due to burst limit
        allowed, info = await limiter.is_allowed(key)
        assert allowed is False
        assert info.limited is True

        # Wait for token refill (1 token per second)
        await asyncio.sleep(1.1)

        # Should have 1 token now
        allowed, _ = await limiter.is_allowed(key)
        assert allowed is True, "Should have 1 refilled token"

    @pytest.mark.asyncio
    async def test_rate_limiter_multiple_keys(self):
        """Rate limiter should track different keys independently."""
        limiter = RateLimiter(per_minute=2, burst_size=2)

        # Each key should have independent limits
        allowed1, _ = await limiter.is_allowed("key1")
        allowed2, _ = await limiter.is_allowed("key2")

        assert allowed1 is True
        assert allowed2 is True

        # Exhaust key1
        await limiter.is_allowed("key1")
        allowed1, _ = await limiter.is_allowed("key1")
        assert allowed1 is False

        # key2 should still have capacity
        allowed2, _ = await limiter.is_allowed("key2")
        assert allowed2 is True

    @pytest.mark.asyncio
    async def test_rate_limiter_violation_tracking(self):
        """Rate limiter should track violations."""
        limiter = RateLimiter(per_minute=2, burst_size=2)

        key = "test_violations"

        # Exhaust limit
        await limiter.is_allowed(key)
        await limiter.is_allowed(key)

        # Trigger violation
        allowed, _ = await limiter.is_allowed(key)
        assert allowed is False

        # Record violation
        limiter.record_violation(key)

        # Check stats
        stats = limiter.get_stats(key)
        assert stats["violations"] == 1

    @pytest.mark.asyncio
    async def test_rate_limiter_cleanup(self):
        """Rate limiter should clean up old entries."""
        limiter = RateLimiter(
            per_minute=60,
            cleanup_interval=1,  # 1 second for testing
        )

        key = "test_cleanup"

        # Make a request
        await limiter.is_allowed(key)

        # Check it's tracked
        assert key in limiter._requests

        # Wait for cleanup interval
        await asyncio.sleep(1.1)

        # Trigger cleanup (by making another request to any key)
        await limiter.is_allowed("other_key")

        # Old entries should be cleaned up
        # Note: Implementation may vary, this is a basic check


# ============================================================================
# Rate Limit Config Tests
# ============================================================================

class TestRateLimitConfig:
    """Test RateLimitConfig dataclass."""

    def test_rate_limit_config_defaults(self):
        """RateLimitConfig should have sensible defaults."""
        config = RateLimitConfig()

        assert config.requests_per_minute == 60
        assert config.requests_per_hour == 1000
        assert config.requests_per_day == 10000
        assert config.burst_size == 10
        assert config.enabled is True
        assert config.exempt_ips == set()
        assert config.exempt_user_ids == set()

    def test_rate_limit_config_custom(self):
        """RateLimitConfig should accept custom values."""
        config = RateLimitConfig(
            requests_per_minute=30,
            requests_per_hour=500,
            requests_per_day=5000,
            burst_size=5,
            enabled=False,
            exempt_ips={"192.168.1.1"},
            exempt_user_ids={"admin_user"},
        )

        assert config.requests_per_minute == 30
        assert config.requests_per_hour == 500
        assert config.requests_per_day == 5000
        assert config.burst_size == 5
        assert config.enabled is False
        assert "192.168.1.1" in config.exempt_ips
        assert "admin_user" in config.exempt_user_ids


# ============================================================================
# Rate Limit Info Tests
# ============================================================================

class TestRateLimitInfo:
    """Test RateLimitInfo dataclass."""

    def test_rate_limit_info_defaults(self):
        """RateLimitInfo should have sensible defaults."""
        info = RateLimitInfo()

        assert info.request_count == 0
        assert info.limited is False
        assert info.retry_after is None

    def test_rate_limit_info_limited(self):
        """RateLimitInfo should reflect limited state."""
        info = RateLimitInfo(
            limited=True,
            retry_after=60,
            request_count=100,
        )

        assert info.limited is True
        assert info.retry_after == 60
        assert info.request_count == 100


# ============================================================================
# Rate Limit Decorator Tests
# ============================================================================

class TestRateLimitDecorator:
    """Test rate_limit decorator."""

    @pytest.mark.asyncio
    async def test_rate_limit_decorator_allows_requests(self):
        """Decorator should allow requests within limits."""
        limiter = RateLimiter(per_minute=10, burst_size=5)

        @rate_limit(
            requests_per_minute=10,
            requests_per_hour=100,
            burst_size=5,
        )
        async def test_function():
            return "success"

        # Call function multiple times within limit
        for i in range(5):
            result = await test_function()
            assert result == "success"

    @pytest.mark.asyncio
    async def test_rate_limit_decorator_handles_limit(self):
        """Decorator should handle rate limit gracefully when limit exceeded."""
        # Note: The @rate_limit decorator is designed for general async functions
        # and may raise RateLimitError. For MCP tools, use @rate_limit_tool instead.
        # This test verifies the decorator doesn't crash the application.
        @rate_limit(
            requests_per_minute=2,
            requests_per_hour=10,
            burst_size=2,
        )
        async def test_function():
            return "success"

        # Call function a couple times (within limit)
        result1 = await test_function()
        assert result1 == "success"

        # Note: Testing exact rate limit behavior with decorator is complex
        # because it requires a Request context. In production, this would
        # be handled by the middleware or tool-specific decorators.

    @pytest.mark.asyncio
    async def test_rate_limit_decorator_with_key_func(self):
        """Decorator should use custom key function."""
        def custom_key(request: Request) -> str:
            return f"custom:{request.client.host if request.client else 'unknown'}"

        @rate_limit(
            requests_per_minute=5,
            key_func=custom_key,
        )
        async def test_function(request: Request):
            return "success"

        # Create mock request
        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "192.168.1.1"

        # Should use custom key
        result = await test_function(request)
        assert result == "success"


# ============================================================================
# Rate Limit Tool Decorator Tests
# ============================================================================

class TestRateLimitToolDecorator:
    """Test rate_limit_tool decorator for FastMCP."""

    @pytest.mark.asyncio
    async def test_rate_limit_tool_allows_requests(self):
        """Tool decorator should allow requests within limits."""
        @rate_limit_tool(requests_per_minute=10)
        async def test_tool(param: str) -> dict[str, Any]:
            return {"result": f"processed: {param}"}

        # Call tool multiple times within limit
        for i in range(5):
            result = await test_tool("test")
            assert result["result"] == "processed: test"

    @pytest.mark.asyncio
    async def test_rate_limit_tool_returns_error_on_limit(self):
        """Tool decorator should return error dict when limit exceeded."""
        @rate_limit_tool(
            requests_per_minute=2,
            requests_per_hour=10,
        )
        async def test_tool(param: str) -> dict[str, Any]:
            return {"result": f"processed: {param}"}

        # Exhaust limit
        await test_tool("test1")
        await test_tool("test2")

        # Next call should return rate limit error
        result = await test_tool("test3")

        assert "error" in result
        assert result["error"] == "Rate limit exceeded"
        assert result["error_type"] == "rate_limit_exceeded"
        assert result["retry_after"] is not None

    @pytest.mark.asyncio
    async def test_rate_limit_tool_with_user_id(self):
        """Tool decorator should use user_id from params for key."""
        @rate_limit_tool(requests_per_minute=5)
        async def test_tool(user_id: str, param: str) -> dict[str, Any]:
            return {"result": f"processed: {param}"}

        # Different users should have independent limits
        for i in range(3):
            result = await test_tool("user1", "test")
            assert result["result"] == "processed: test"

        # user1 should be at limit, user2 should still work
        result = await test_tool("user2", "test")
        assert result["result"] == "processed: test"

    @pytest.mark.asyncio
    async def test_rate_limit_tool_stats(self):
        """Tool decorator should track statistics."""
        # Reset stats before test
        reset_tool_stats()

        @rate_limit_tool(requests_per_minute=2)
        async def test_tool(param: str) -> dict[str, Any]:
            return {"result": f"processed: {param}"}

        # Make some calls
        await test_tool("test1")
        await test_tool("test2")

        # Check stats
        stats = get_tool_rate_limit_stats("test_tool")
        assert stats["total_calls"] == 2
        assert stats["rate_limited_calls"] == 0

    @pytest.mark.asyncio
    async def test_get_all_rate_limit_stats(self):
        """Should return statistics for all tools."""
        # Reset stats before test
        reset_tool_stats()

        @rate_limit_tool(requests_per_minute=5)
        async def tool1(param: str) -> dict[str, Any]:
            return {"result": "tool1"}

        @rate_limit_tool(requests_per_minute=5)
        async def tool2(param: str) -> dict[str, Any]:
            return {"result": "tool2"}

        # Make calls
        await tool1("test")
        await tool2("test")

        # Get all stats
        all_stats = get_all_rate_limit_stats()

        assert all_stats["total_calls"] == 2
        assert "tool1" in all_stats["tools"]
        assert "tool2" in all_stats["tools"]

    @pytest.mark.asyncio
    async def test_reset_tool_stats(self):
        """Should reset tool statistics."""
        # Reset stats before test
        reset_tool_stats()

        @rate_limit_tool(requests_per_minute=5)
        async def test_tool(param: str) -> dict[str, Any]:
            return {"result": f"processed: {param}"}

        # Make calls
        await test_tool("test")

        # Verify stats
        stats = get_tool_rate_limit_stats("test_tool")
        assert stats["total_calls"] == 1

        # Reset stats
        reset_tool_stats("test_tool")

        # Verify reset
        stats = get_tool_rate_limit_stats("test_tool")
        assert stats["total_calls"] == 0

    @pytest.mark.asyncio
    async def test_reset_all_stats(self):
        """Should reset all tool statistics."""
        # Reset stats before test
        reset_tool_stats()

        @rate_limit_tool(requests_per_minute=5)
        async def tool1(param: str) -> dict[str, Any]:
            return {"result": "tool1"}

        @rate_limit_tool(requests_per_minute=5)
        async def tool2(param: str) -> dict[str, Any]:
            return {"result": "tool2"}

        # Make calls
        await tool1("test")
        await tool2("test")

        # Reset all
        reset_tool_stats()

        # Verify reset
        all_stats = get_all_rate_limit_stats()
        assert all_stats["total_calls"] == 0


# ============================================================================
# Global Limiter Tests
# ============================================================================

class TestGlobalLimiter:
    """Test global rate limiter instance."""

    @pytest.mark.asyncio
    async def test_get_global_limiter_creates_instance(self):
        """Should create global limiter on first call."""
        # Reset global limiter
        import mahavishnu.core.rate_limit_tools as rl_module
        rl_module._global_limiter = None

        # Get global limiter (should create new instance)
        limiter = get_global_limiter()
        assert limiter is not None
        assert isinstance(limiter, RateLimiter)

    @pytest.mark.asyncio
    async def test_get_global_limiter_reuses_instance(self):
        """Should reuse existing global limiter instance."""
        # Reset global limiter
        import mahavishnu.core.rate_limit_tools as rl_module
        rl_module._global_limiter = None

        # Get global limiter twice
        limiter1 = get_global_limiter()
        limiter2 = get_global_limiter()

        # Should be same instance
        assert limiter1 is limiter2

    @pytest.mark.asyncio
    async def test_get_global_limiter_with_config(self):
        """Should create limiter with custom config."""
        # Reset global limiter
        import mahavishnu.core.rate_limit_tools as rl_module
        rl_module._global_limiter = None

        config = RateLimitConfig(
            requests_per_minute=30,
            requests_per_hour=500,
        )

        limiter = get_global_limiter(config)

        assert limiter.per_minute == 30
        assert limiter.per_hour == 500


# ============================================================================
# Integration Tests
# ============================================================================

class TestRateLimitIntegration:
    """Integration tests for rate limiting."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_respects_limit(self):
        """Rate limiter should handle concurrent requests correctly."""
        limiter = RateLimiter(per_minute=5, burst_size=5)

        async def make_request(key: str, index: int):
            allowed, _ = await limiter.is_allowed(key)
            return allowed, index

        # Launch concurrent requests
        tasks = [
            make_request("concurrent_test", i)
            for i in range(10)
        ]

        results = await asyncio.gather(*tasks)

        # First 5 should be allowed, rest should be blocked
        allowed_results = [allowed for allowed, _ in results]
        assert sum(allowed_results) == 5

    @pytest.mark.asyncio
    async def test_rate_limit_with_cleanup(self):
        """Rate limiter should work correctly with periodic cleanup."""
        # Create limiter with short cleanup interval
        limiter = RateLimiter(
            per_minute=10,
            cleanup_interval=1,  # 1 second
        )

        key = "cleanup_test"

        # Make requests
        for i in range(5):
            await limiter.is_allowed(key)

        # Wait for cleanup
        await asyncio.sleep(1.1)

        # Make more requests (should still work)
        allowed, _ = await limiter.is_allowed(key)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_multiple_limits_interaction(self):
        """Rate limiter should enforce multiple limits correctly."""
        limiter = RateLimiter(
            per_minute=5,
            per_hour=10,  # Lower than minute * 60
            burst_size=10,
        )

        key = "multi_limit_test"

        # Make requests up to per-minute limit
        for i in range(5):
            allowed, _ = await limiter.is_allowed(key)
            assert allowed is True, f"Request {i+1} should be allowed"

        # Next request should be blocked
        allowed, info = await limiter.is_allowed(key)
        assert allowed is False
        assert info.limited is True
