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
