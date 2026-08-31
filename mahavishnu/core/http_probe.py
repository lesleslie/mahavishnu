"""Canonical HTTP probe helpers built on Oneiric ``HttpFetchAction``.

Wave 3 (W3): the existing ``HealthChecker`` in ``mahavishnu.core.health`` already
adopted ``HttpFetchAction`` for service health probes. This module factors
that pattern into a reusable ``service_probe`` helper so any cross-component
HTTP probe inherits the canonical envelope:

* automatic OpenTelemetry trace-context propagation
* centralized timeout / SSL / retry configuration
* uniform response shape consumable by Akosha + Dhara
"""

from __future__ import annotations

from functools import lru_cache
import time
from typing import TYPE_CHECKING, Any

from httpx2 import HTTPError
from oneiric.actions.http import HttpActionSettings, HttpFetchAction

if TYPE_CHECKING:
    from httpx2 import AsyncClient

# Module-level settings so the client override path doesn't need to reach
# into ``HttpFetchAction._settings`` (a private attribute).
_PROBE_SETTINGS = HttpActionSettings(
    timeout_seconds=10.0,
    verify_ssl=True,
    allow_redirects=False,
    raise_for_status=False,
)


@lru_cache(maxsize=1)
def _http_probe_action() -> HttpFetchAction:
    """Return the process-wide ``HttpFetchAction`` used by ``service_probe``."""
    return HttpFetchAction(settings=_PROBE_SETTINGS)


async def service_probe(
    url: str,
    *,
    method: str = "GET",
    expected_status: int = 200,
    timeout_seconds: float | None = None,
    client: AsyncClient | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Probe a service URL and return a canonical probe envelope.

    Args:
        url: The full URL to probe (e.g., ``http://localhost:8678/health``).
        method: HTTP method, defaults to GET.
        expected_status: HTTP status code that counts as healthy.
        timeout_seconds: Per-request timeout override.
        client: Optional shared httpx ``AsyncClient`` (for connection reuse).
        headers: Extra headers (e.g., ``Authorization``).

    Returns:
        Dict with keys: ``healthy`` (bool), ``status_code`` (int|None),
        ``latency_ms`` (float), ``body`` (dict|str|None), ``error``
        (str|None), and ``url`` (str).

    Note:
        ``HttpFetchAction.execute()`` returns a flat dict with ``status``,
        ``status_code``, ``ok``, ``headers``, ``elapsed_ms``, ``json``, and
        ``text`` at the top level (see ``oneiric.actions.http``). Earlier
        W3 code read a nested ``response`` key — that was a bug that made
        every probe return ``healthy=False``. The fix here reads the flat
        shape and prefers ``json`` (parsed) over ``text`` for the body.
    """
    payload: dict[str, Any] = {
        "method": method,
        "url": url,
    }
    if timeout_seconds is not None:
        payload["timeout"] = timeout_seconds
    if headers:
        payload["headers"] = headers

    start = time.monotonic()
    if client is not None:
        action = HttpFetchAction(settings=_PROBE_SETTINGS, client=client)
    else:
        action = _http_probe_action()
    try:
        result = await action.execute(payload)
    except (HTTPError, OSError) as exc:
        latency_ms = (time.monotonic() - start) * 1000.0
        return {
            "healthy": False,
            "status_code": None,
            "latency_ms": round(latency_ms, 2),
            "body": None,
            "error": f"{type(exc).__name__}: {exc}",
            "url": url,
        }
    latency_ms = (time.monotonic() - start) * 1000.0

    status_code = result.get("status_code")
    body = result.get("json")
    if body is None:
        body = result.get("text")

    ok = bool(result.get("ok"))
    healthy = ok and status_code == expected_status
    return {
        "healthy": healthy,
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "body": body,
        "error": None if healthy else f"unexpected status {status_code}",
        "url": url,
    }


__all__ = ["service_probe"]
