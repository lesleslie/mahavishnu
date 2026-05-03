"""Tests for core/rate_limiting.py — rate limiting configuration and helpers."""

from unittest.mock import MagicMock

import pytest

from mahavishnu.core.rate_limiting import (
    HAS_SLOWAPI,
    RATE_LIMITS,
    get_client_ip,
    limit_api_general,
    limit_embedding,
    limit_nlp,
    limit_task_create,
    limit_task_search,
    limit_webhook,
    rate_limit,
    rate_limit_exceeded_handler,
    setup_rate_limiting,
)

# ---------------------------------------------------------------------------
# RATE_LIMITS dict
# ---------------------------------------------------------------------------


class TestRateLimits:
    def test_all_expected_keys(self):
        expected = [
            "task_create",
            "task_update",
            "task_delete",
            "task_search",
            "repo_list",
            "repo_sync",
            "webhook_github",
            "webhook_gitlab",
            "api_general",
            "api_read",
            "api_write",
            "embedding",
            "nlp_parse",
            "websocket",
        ]
        for key in expected:
            assert key in RATE_LIMITS

    def test_limit_format(self):
        for key, value in RATE_LIMITS.items():
            assert "/" in value, f"{key}: {value} missing '/'"


# ---------------------------------------------------------------------------
# get_client_ip
# ---------------------------------------------------------------------------


class TestGetClientIP:
    def _make_request(self, forwarded_for=None, client_host="1.2.3.4"):
        request = MagicMock()
        request.headers = {}
        if forwarded_for is not None:
            request.headers["X-Forwarded-For"] = forwarded_for
        if client_host is not None:
            request.client = MagicMock()
            request.client.host = client_host
        else:
            request.client = None
        return request

    def test_forwarded_for_first_ip(self):
        request = self._make_request(forwarded_for="10.0.0.1, 2.0.0.3")
        assert get_client_ip(request) == "10.0.0.1"

    def test_forwarded_for_strip(self):
        request = self._make_request(forwarded_for="  10.0.0.1 ")
        assert get_client_ip(request) == "10.0.0.1"

    def test_client_host_fallback(self):
        request = self._make_request(forwarded_for=None, client_host="5.6.7.8")
        assert get_client_ip(request) == "5.6.7.8"

    def test_no_client_info(self):
        request = self._make_request(forwarded_for=None, client_host=None)
        assert get_client_ip(request) == "127.0.0.1"


# ---------------------------------------------------------------------------
# rate_limit_exceeded_handler
# ---------------------------------------------------------------------------


class TestRateLimitExceededHandler:
    @pytest.mark.asyncio
    async def test_handler_returns_429(self):
        request = MagicMock()
        exc = MagicMock()
        exc.detail = "10/minute"
        response = await rate_limit_exceeded_handler(request, exc)
        assert response.status_code == 429
        body = response.body
        if isinstance(body, bytes):
            import json

            body = json.loads(body)
        assert "MHV-006" in str(body)
        assert (
            response.headers.get("Retry-After") == "60"
            or response.headers.get("retry-after") == "60"
        )


# ---------------------------------------------------------------------------
# rate_limit decorator
# ---------------------------------------------------------------------------


class TestRateLimitDecorator:
    def test_decorator_returns_callable(self):
        # slowapi requires a "request" parameter in the function signature
        async def dummy(request=None):
            pass

        decorated = rate_limit("10/minute")(dummy)
        assert callable(decorated)

    def test_convenience_decorators(self):
        async def dummy(request=None):
            return "ok"

        for decorator in [
            limit_task_create,
            limit_task_search,
            limit_webhook,
            limit_api_general,
            limit_embedding,
            limit_nlp,
        ]:
            result = decorator(dummy)
            assert callable(result)
            if not HAS_SLOWAPI:
                assert result is dummy


# ---------------------------------------------------------------------------
# setup_rate_limiting
# ---------------------------------------------------------------------------


class TestSetupRateLimiting:
    def test_no_exception_on_call(self):
        app = MagicMock()
        setup_rate_limiting(app)
        # If slowapi not available, just logs warning and returns
