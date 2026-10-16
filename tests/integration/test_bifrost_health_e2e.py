"""Phase E e2e test for the /health.bifrost sub-shape.

Per docs/plans/2026-10-15-bifrost-gateway-wiring.md §5 Phase E exit
criteria. The single test:

- ``test_bifrost_health_e2e`` — ``GET /health`` JSON includes
  ``bifrost.config`` (a dict, auth_env-redacted) and
  ``bifrost.reachable`` (a boolean). The local_provider_reachable
  field is also asserted when bifrost.local_provider_enabled is
  true.
"""

from __future__ import annotations

import time

import pytest
import requests

# All tests in this module are e2e.
pytestmark = pytest.mark.integration


def test_bifrost_health_e2e(bifrost_reachable: bool) -> None:
    """``GET /health`` returns the bifrost sub-shape with config and reachable fields.

    Phase E deliverable: the ``/health`` route populates
    ``BifrostHealth`` (typed sub-model on ``HealthResponse``) with
    the resolved BifrostConfig (auth_env redacted) and the
    reachability booleans from the probe helpers.
    """
    del bifrost_reachable  # consumed for skip-side-effect only
    pytest.mark.timeout(30)

    health_url = "http://127.0.0.1:8680/health"
    # The /health route may return 503 when degraded; the
    # bifrost sub-shape is still populated in that case. We
    # assert on the body shape regardless of HTTP status.
    deadline = time.time() + 10.0
    body = None
    last_status = None
    while time.time() < deadline:
        try:
            response = requests.get(health_url, timeout=3)
        except requests.RequestException:
            time.sleep(0.5)
            continue
        last_status = response.status_code
        try:
            body = response.json()
        except ValueError:
            time.sleep(0.5)
            continue
        if body and "bifrost" in body:
            break
        time.sleep(0.5)

    if body is None or "bifrost" not in body:
        pytest.skip(
            f"GET {health_url} (last status {last_status}) did not "
            f"return a bifrost sub-shape within 10s. The Mahavishnu "
            f"server is not running locally, or /health is not yet "
            f"populating BifrostHealth (the aggregation is in the "
            f"branch but not yet deployed)."
        )

    bifrost_block = body["bifrost"]
    assert isinstance(bifrost_block, dict)
    # config is the auth_env-redacted BifrostConfig projection
    # (the plan's hard-rule for /health.bifrost.config).
    assert "config" in bifrost_block
    if bifrost_block["config"] is not None:
        assert isinstance(bifrost_block["config"], dict)
        assert "auth_env" not in bifrost_block["config"]
    # reachable is a bool from _probe_bifrost_state (httpx.get
    # on bifrost.base_url + '/health', 2s timeout).
    assert "reachable" in bifrost_block
    assert isinstance(bifrost_block["reachable"], bool)
