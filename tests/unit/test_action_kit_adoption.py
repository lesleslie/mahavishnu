"""Tests for Oneiric action-kit adoption in Mahavishnu.

Wave 3 (W3) additions:
- ``mahavishnu.core.http_probe.service_probe`` -> oneiric.actions.http.HttpFetchAction
- ``mahavishnu.core.retry_policy`` -> oneiric.actions.workflow.WorkflowRetryAction
- The existing ``HealthChecker`` in ``core/health.py`` continues to use
  ``HttpFetchAction`` (added in W3 prior wave).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx2 as httpx
import pytest

from mahavishnu.core.http_probe import _http_probe_action, service_probe
from mahavishnu.core.retry_policy import (
    _retry_action,
    compute_retry_delay,
    next_retry_decision,
)


@pytest.fixture(autouse=True)
def _reset_action_caches() -> None:
    _http_probe_action.cache_clear()
    _retry_action.cache_clear()
    yield
    _http_probe_action.cache_clear()
    _retry_action.cache_clear()


def _run(coro):
    return asyncio.run(coro)


def _action_with_transport(template_action, transport: httpx.MockTransport):
    """Return a copy of ``template_action`` whose client uses ``transport``.

    Used by happy-path tests that need to stub out real HTTP. The
    ``HttpFetchAction`` accepts a shared ``AsyncClient`` in its constructor;
    we build one wrapped around the mock transport.
    """
    from oneiric.actions.http import HttpFetchAction

    return HttpFetchAction(
        settings=template_action._settings,
        client=httpx.AsyncClient(transport=transport),
    )


def test_http_probe_action_is_canonical() -> None:
    action = _http_probe_action()
    assert action._settings.timeout_seconds == 10.0
    assert action._settings.verify_ssl is True
    assert action._settings.allow_redirects is False
    assert action._settings.raise_for_status is False
    assert action.metadata.key == "http.fetch"


async def test_service_probe_returns_canonical_envelope() -> None:
    """service_probe returns the canonical envelope shape regardless of outcome."""
    result = await service_probe("http://127.0.0.1:1", expected_status=200)
    assert "healthy" in result
    assert "status_code" in result
    assert "latency_ms" in result
    assert "error" in result
    assert "url" in result
    assert result["url"] == "http://127.0.0.1:1"
    # Connection refused → not healthy.
    assert result["healthy"] is False


async def test_service_probe_passes_method_and_headers() -> None:
    result = await service_probe(
        "http://127.0.0.1:1",
        method="HEAD",
        headers={"Authorization": "Bearer x"},
    )
    # Shape must be canonical even when the probe fails.
    assert set(result.keys()) >= {
        "healthy",
        "status_code",
        "latency_ms",
        "body",
        "error",
        "url",
    }


async def test_service_probe_returns_healthy_on_200() -> None:
    """BLOCKER 1 regression guard: a real 200 response must show healthy=True.

    Earlier W3 code read ``result["response"]["status_code"]`` from a nested
    key that doesn't exist; the kit returns a flat dict. That bug made
    every probe return ``healthy=False`` regardless of server state, and
    the failure-mode tests passed by coincidence. This test exercises the
    success path with an httpx MockTransport so the regression can't slip
    through again.
    """
    import httpx2 as httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "ok", "service": "probe-test"},
            headers={"content-type": "application/json"},
        )

    transport = httpx.MockTransport(handler)

    # Patch the lru_cache singleton so the next probe uses our transport.
    from mahavishnu.core import http_probe as http_probe_module

    real_action = http_probe_module._http_probe_action()
    patched_action = _action_with_transport(real_action, transport)
    http_probe_module._http_probe_action = lambda: patched_action
    try:
        result = await service_probe("https://probe.example/health", expected_status=200)
        assert result["healthy"] is True, (
            f"service_probe mis-classified healthy response: {result}"
        )
        assert result["status_code"] == 200
        assert result["body"] == {"status": "ok", "service": "probe-test"}
        assert result["error"] is None
    finally:
        http_probe_module._http_probe_action = real_action


def test_retry_action_uses_canonical_defaults() -> None:
    action = _retry_action()
    assert action._settings.max_attempts == 3
    assert action._settings.base_delay_seconds == 1.0
    assert action._settings.multiplier == 2.0
    assert action._settings.max_delay_seconds == 60.0
    assert action._settings.jitter == 0.1
    assert action.metadata.key == "workflow.retry"


async def test_compute_retry_delay_matches_exponential_curve() -> None:
    """The canonical delay curve matches base * multiplier**attempt."""
    # ``delay_seconds`` is the wait BEFORE the next attempt; at attempt=0
    # the kit returns base_delay * multiplier**0 = 1.0 + jitter, NOT 0.
    delay_0 = await compute_retry_delay(0)
    assert delay_0 > 0
    delay_1 = await compute_retry_delay(1)
    assert delay_1 > delay_0  # exponential growth (modulo jitter)
    delay_2 = await compute_retry_delay(2)
    assert delay_2 > delay_1


async def test_next_retry_decision_returns_full_envelope() -> None:
    result = await next_retry_decision(attempt=1, max_attempts=3)
    assert result["status"] == "scheduled"
    assert result["attempt"] == 1
    assert result["next_attempt"] == 2
    assert result["max_attempts"] == 3
    assert result["delay_seconds"] >= 0


async def test_next_retry_decision_marks_exhausted() -> None:
    result = await next_retry_decision(attempt=3, max_attempts=3)
    assert result["status"] == "exhausted"
    assert result["delay_seconds"] == 0.0


async def test_compute_retry_delay_returns_zero_on_exhausted() -> None:
    """BLOCKER 2 regression guard: exhausted branch must not raise KeyError.

    The kit omits ``delay_seconds`` from its exhausted-branch response.
    ``compute_retry_delay`` previously indexed ``result["delay_seconds"]``
    directly, raising ``KeyError`` on any exhausted call.
    """
    # attempt=3 with max_attempts=3 → exhausted
    delay = await compute_retry_delay(attempt=3, max_attempts=3)
    assert delay == 0.0
    # attempt far past max_attempts is also exhausted
    delay_late = await compute_retry_delay(attempt=10, max_attempts=3)
    assert delay_late == 0.0


async def test_service_probe_uses_oneiric_action_not_reimplemented_httpx() -> None:
    """Sanity check: the call path actually routes through HttpFetchAction."""
    captured: dict[str, Any] = {}
    original_execute = _http_probe_action().execute

    async def spy_execute(payload):
        captured["payload"] = payload
        return await original_execute(payload)

    class _Spy:
        execute = staticmethod(spy_execute)

    from mahavishnu.core import http_probe

    http_probe._http_probe_action = lambda: _Spy()
    try:
        await service_probe("http://127.0.0.1:1", method="HEAD")
    finally:
        http_probe._http_probe_action = _http_probe_action

    assert captured.get("payload", {}).get("method") == "HEAD"
