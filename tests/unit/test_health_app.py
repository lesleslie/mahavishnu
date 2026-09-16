"""Unit tests for ``mahavishnu.health``.

These tests exercise the FastAPI application built by ``create_health_app``:

- ``GET /health`` -- aggregated liveness probe (Phase 4). Delegates to
  ``mahavishnu.core.health_aggregator.aggregate_mahavishnu_health``
  and returns 200 for healthy/warming_up, 503 for degraded/failed.
- ``GET /ready``  -- readiness probe (200 only when sub-checks pass)
- ``GET /metrics``-- Prometheus text exposition. Serves the four PromQL
  metrics emitted by the health aggregator
  (``health_feed_status`` / ``health_feed_errors_within_window`` /
  ``mcp_common_health_halflife_seconds`` /
  ``mcp_common_health_aggregate_duration_ms``) from a private
  ``CollectorRegistry``. See ``config/prometheus/health_aggregator_
  alerts.yml``.
- ``GET /``       -- root metadata block

The readiness sub-checks depend on heavy modules (``EncryptedSQLite``,
``InMemoryEventTransport``, ``MahavishnuSettings``).  We mock them at the
``mahavishnu.health`` boundary so the tests stay fast and dependency-free.

The Phase 4 aggregator is mocked via the ``healthy_aggregator`` /
``degraded_aggregator`` fixtures (also at the ``mahavishnu.health``
boundary) so the unit tests don't pull in real probes / metrics
infrastructure. The end-to-end wiring (real aggregator + real
``/metrics`` exposition) lives in
``tests/integration/mcp/test_health_aggregator.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from mahavishnu.health import create_health_app

if TYPE_CHECKING:
    from mahavishnu.core.health_aggregator import MahavishnuHealthVerdict


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """Health app with a known startup time so uptime is deterministic."""
    startup = datetime.now(UTC) - timedelta(seconds=10)
    return create_health_app(
        server_name="test-mahavishnu",
        startup_time=startup,
        version="9.9.9",
    )


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Synchronous test client wrapping the health app."""
    return TestClient(app)


@pytest.fixture
def all_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every readiness sub-check return ``True``.

    Tests that exercise failure paths can re-patch a single attribute on top of
    this fixture to flip exactly the dependency they care about.
    """
    monkeypatch.setattr("mahavishnu.health._check_database", lambda: True)
    monkeypatch.setattr("mahavishnu.health._check_message_bus", lambda: True)
    monkeypatch.setattr("mahavishnu.health._check_adapters", lambda: True)


@pytest.fixture
def healthy_aggregator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the Phase 4 aggregator to return a healthy verdict.

    Pins the ``/health`` body to a deterministic worst-case
    ``StatusValue.HEALTHY`` + 200 HTTP code. Avoids pulling in
    real probes (EncryptedSQLite, InMemoryEventTransport,
    MahavishnuSettings) so the unit test stays fast and
    dependency-free.
    """
    from mcp_common.health.feed import StatusValue

    def _fake_aggregate(*, repo: str) -> MahavishnuHealthVerdict:
        snap = {
            "status": StatusValue.HEALTHY,
            "checks": {
                "storage": {
                    "status": StatusValue.HEALTHY,
                    "healthy": True,
                    "reason_codes": [],
                },
                "message_bus": {
                    "status": StatusValue.HEALTHY,
                    "healthy": True,
                    "reason_codes": [],
                },
                "adapters": {
                    "status": StatusValue.HEALTHY,
                    "healthy": True,
                    "reason_codes": [],
                },
            },
            "reason_codes": [],
        }

        from mahavishnu.core.health_aggregator import MahavishnuHealthVerdict

        return MahavishnuHealthVerdict(
            snapshot=snap,
            worst_status=StatusValue.HEALTHY,
            http_status=200,
            duration_ms=0.42,
        )

    monkeypatch.setattr(
        "mahavishnu.health.aggregate_mahavishnu_health", _fake_aggregate
    )


@pytest.fixture
def degraded_aggregator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the Phase 4 aggregator to return a degraded verdict.

    Pins the ``/health`` body to ``StatusValue.DEGRADED`` + 503
    HTTP code. Mirrors the failure-path tests for readiness
    sub-checks.
    """
    from mcp_common.health.feed import ReasonCode, StatusValue

    def _fake_aggregate(*, repo: str) -> MahavishnuHealthVerdict:
        snap = {
            "status": StatusValue.DEGRADED,
            "checks": {
                "storage": {
                    "status": StatusValue.HEALTHY,
                    "healthy": True,
                    "reason_codes": [],
                },
                "message_bus": {
                    "status": StatusValue.DEGRADED,
                    "healthy": False,
                    "reason_codes": [ReasonCode.FEED_NEVER_POPULATED],
                },
                "adapters": {
                    "status": StatusValue.HEALTHY,
                    "healthy": True,
                    "reason_codes": [],
                },
            },
            "reason_codes": [ReasonCode.FEED_NEVER_POPULATED],
        }

        from mahavishnu.core.health_aggregator import MahavishnuHealthVerdict

        return MahavishnuHealthVerdict(
            snapshot=snap,
            worst_status=StatusValue.DEGRADED,
            http_status=503,
            duration_ms=0.85,
        )

    monkeypatch.setattr(
        "mahavishnu.health.aggregate_mahavishnu_health", _fake_aggregate
    )


# ---------------------------------------------------------------------------
# App instantiation
# ---------------------------------------------------------------------------


def test_create_health_app_returns_fastapi_instance() -> None:
    """The factory returns a ``FastAPI`` instance."""
    app = create_health_app()
    assert isinstance(app, FastAPI)


def test_create_health_app_uses_server_name_in_title() -> None:
    """The server name is reflected in the OpenAPI title."""
    app = create_health_app(server_name="my-svc")
    assert app.title == "My-Svc Health API"


def test_create_health_app_accepts_health_config() -> None:
    """Passing a ``HealthConfig`` does not raise during construction."""
    from mahavishnu.core.config import HealthConfig

    app = create_health_app(health_config=HealthConfig())
    assert isinstance(app, FastAPI)


# ---------------------------------------------------------------------------
# GET /health (aggregated liveness, Phase 4)
# ---------------------------------------------------------------------------


def test_health_endpoint_returns_200_when_aggregator_healthy(
    client: TestClient, healthy_aggregator: None
) -> None:
    """``/health`` returns 200 when the worst-case aggregator status
    is ``healthy`` (or ``warming_up``).

    Mirrors the spec §4.8 threshold contract: healthy + warming_up
    → 200, degraded + failed → 503.
    """
    response = client.get("/health")
    assert response.status_code == 200


def test_health_endpoint_returns_503_when_aggregator_degraded(
    client: TestClient, degraded_aggregator: None
) -> None:
    """``/health`` returns 503 when the worst-case aggregator status
    is ``degraded`` (or ``failed``).

    Spec §4.8 contract: degraded + failed → 503 (load balancers
    pull this pod out of rotation).
    """
    response = client.get("/health")
    assert response.status_code == 503


def test_health_endpoint_status_is_ok_when_healthy(
    client: TestClient, healthy_aggregator: None
) -> None:
    """The response declares ``status='ok'`` when the aggregator is healthy.

    ``StatusValue.HEALTHY`` and ``StatusValue.WARMING_UP`` both map
    to ``HealthStatus.OK`` (the orchestrator is operational).
    """
    body = client.get("/health").json()
    assert body["status"] == "ok"


def test_health_endpoint_status_is_unhealthy_when_degraded(
    client: TestClient, degraded_aggregator: None
) -> None:
    """The response declares ``status='degraded'`` when the aggregator is degraded.

    ``StatusValue.DEGRADED`` maps to ``HealthStatus.DEGRADED``;
    ``StatusValue.FAILED`` would map to ``HealthStatus.UNHEALTHY``.
    """
    body = client.get("/health").json()
    assert body["status"] == "degraded"


def test_health_endpoint_response_schema(client: TestClient, healthy_aggregator: None) -> None:
    """Liveness response carries the documented fields.

    Backward compat: legacy 5 fields (status / service / version /
    uptime_seconds / timestamp) are still present. Phase 4 added 4
    aggregator fields (worst_status / feed_states / reason_codes /
    aggregate_duration_ms). Pydantic v2 with model_config=extra='allow'
    is implicit on the response body — we round-trip via dict and
    only assert on the keys we care about.
    """
    body = client.get("/health").json()
    expected_legacy = {"status", "service", "version", "uptime_seconds", "timestamp"}
    assert expected_legacy.issubset(body.keys())
    assert body["service"] == "test-mahavishnu"
    assert body["version"] == "9.9.9"
    # ``timestamp`` is a Pydantic-managed ISO 8601 string.
    assert isinstance(body["timestamp"], str)
    # Phase 4 aggregator fields present.
    assert "worst_status" in body
    assert body["worst_status"] == "healthy"
    assert set(body["feed_states"].keys()) == {"storage", "message_bus", "adapters"}
    assert body["reason_codes"] == []
    assert body["aggregate_duration_ms"] == 0.42


def test_health_endpoint_uptime_is_nonnegative(client: TestClient, healthy_aggregator: None) -> None:
    """Uptime is non-negative when the supplied ``startup_time`` is in the past."""
    body = client.get("/health").json()
    assert body["uptime_seconds"] >= 0


def test_health_endpoint_reflects_custom_version() -> None:
    """The ``version`` parameter flows through to the response body."""
    app = create_health_app(version="1.2.3", startup_time=datetime.now(UTC))
    with TestClient(app) as c:
        body = c.get("/health").json()
    assert body["version"] == "1.2.3"


def test_health_endpoint_surfaces_per_feed_state(
    client: TestClient, degraded_aggregator: None
) -> None:
    """The response body surfaces per-feed ``status`` + ``reason_codes``.

    Operators see the worst feed's reasoning without parsing logs.
    The aggregator's worst-case rollup carries the union of
    worst-status feeds' ``reason_codes``; the per-feed
    ``FeedSnapshot`` carries the diagnostic context for each feed
    individually.
    """
    body = client.get("/health").json()

    assert body["worst_status"] == "degraded"
    assert body["feed_states"]["message_bus"]["status"] == "degraded"
    assert body["feed_states"]["message_bus"]["healthy"] is False
    assert body["feed_states"]["message_bus"]["reason_codes"] == [
        "feed_never_populated"
    ]
    assert body["reason_codes"] == ["feed_never_populated"]


# ---------------------------------------------------------------------------
# GET /ready (readiness)
# ---------------------------------------------------------------------------


def test_ready_endpoint_returns_200_when_all_checks_ok(
    client: TestClient, all_healthy: None
) -> None:
    """Readiness returns 200 with ``ready=True`` when every sub-check passes."""
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["service"] == "test-mahavishnu"
    assert all(value == "ok" for value in body["checks"].values())


def test_ready_endpoint_response_schema(client: TestClient, all_healthy: None) -> None:
    """Readiness response contains ``ready``, ``service``, ``dependencies``, ``checks``.

    Uses ``>=`` (subset check) rather than ``==`` because the
    ``/ready`` endpoint may include additional optional fields like
    ``merge_driver`` (carried by the round-4 review M1 fix that
    surfaces the mergiraf probe). Future additive fields should
    not break this assertion.
    """
    body = client.get("/ready").json()
    assert {"ready", "service", "dependencies", "checks"}.issubset(body.keys())
    assert body["dependencies"] == {}
    assert isinstance(body["checks"], dict)


def test_ready_endpoint_database_unhealthy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, all_healthy: None
) -> None:
    """Failing the database sub-check flips ``ready`` to False and marks the check."""
    monkeypatch.setattr("mahavishnu.health._check_database", lambda: False)
    body = client.get("/ready").json()
    assert body["ready"] is False
    assert body["checks"]["database"] == "unhealthy"
    # Sibling checks stay green.
    assert body["checks"]["message_bus"] == "ok"
    assert body["checks"]["adapters"] == "ok"


def test_ready_endpoint_message_bus_unhealthy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, all_healthy: None
) -> None:
    """Failing the message-bus sub-check flips ``ready`` to False."""
    monkeypatch.setattr("mahavishnu.health._check_message_bus", lambda: False)
    body = client.get("/ready").json()
    assert body["ready"] is False
    assert body["checks"]["message_bus"] == "unhealthy"


def test_ready_endpoint_adapters_unhealthy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, all_healthy: None
) -> None:
    """Failing the adapters sub-check flips ``ready`` to False."""
    monkeypatch.setattr("mahavishnu.health._check_adapters", lambda: False)
    body = client.get("/ready").json()
    assert body["ready"] is False
    assert body["checks"]["adapters"] == "unhealthy"


def test_ready_endpoint_server_check_always_ok(client: TestClient, all_healthy: None) -> None:
    """The ``server`` sub-check is hard-coded to ``ok`` in the source."""
    body = client.get("/ready").json()
    assert body["checks"]["server"] == "ok"


# ---------------------------------------------------------------------------
# GET /metrics (Phase 4 Prometheus exposition)
# ---------------------------------------------------------------------------


def test_metrics_endpoint_returns_prometheus_text_format(
    client: TestClient,
) -> None:
    """The ``/metrics`` endpoint returns ``text/plain; version=0.0.4``.

    Pre-Phase-4 this endpoint imported ``from monitoring.metrics
    import metrics_endpoint`` which didn't exist; the endpoint
    returned 500 on any call. Phase 4 replaces the broken import
    with a direct ``prometheus_client.generate_latest(registry)``
    call on the private health-aggregator ``CollectorRegistry``.

    The unit test mocks ``aggregate_mahavishnu_health`` at the
    ``mahavishnu.health`` boundary (so the test doesn't pull in
    real probes), but that means the mock doesn't actually call
    ``update_health_metrics``. To populate the registry, the
    test calls ``update_health_metrics`` directly with a
    fixture-built ``HealthSnapshot``. The end-to-end integration
    path (real aggregator + real ``/metrics`` exposition) lives
    in ``tests/integration/mcp/test_health_aggregator.py``.
    """
    from mcp_common.health.feed import StatusValue
    from mcp_common.health.metrics import update_health_metrics

    from mahavishnu.core.health_aggregator import get_health_metrics_registry

    # Force at least one emission so the metric instances are
    # registered on the private registry (lazy-init pattern in
    # mcp-common's update_health_metrics).
    update_health_metrics(
        registry=get_health_metrics_registry(),
        snap={
            "status": StatusValue.HEALTHY,
            "checks": {
                "storage": {
                    "status": StatusValue.HEALTHY,
                    "healthy": True,
                    "reason_codes": [],
                },
            },
            "reason_codes": [],
        },
        repo="test-mahavishnu-metrics",
        halflife_seconds=300,
        duration_ms=0.42,
    )

    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")

    # The four PromQL metrics referenced by the alerts at
    # config/prometheus/health_aggregator_alerts.yml must appear
    # in the exposition output.
    expected_metrics = (
        "health_feed_status",
        "health_feed_errors_within_window",
        "mcp_common_health_halflife_seconds",
        "mcp_common_health_aggregate_duration_ms",
    )
    for metric_name in expected_metrics:
        assert metric_name in response.text, (
            f"PromQL metric {metric_name!r} missing from /metrics exposition"
        )


# ---------------------------------------------------------------------------
# GET / (root)
# ---------------------------------------------------------------------------


def test_root_endpoint_returns_200(client: TestClient) -> None:
    """The root endpoint returns 200 with a status payload."""
    response = client.get("/")
    assert response.status_code == 200


def test_root_endpoint_lists_endpoints(client: TestClient) -> None:
    """The root payload points at /health, /ready, /metrics, /docs."""
    body = client.get("/").json()
    assert body == {
        "service": "test-mahavishnu",
        "status": "running",
        "health_endpoint": "/health",
        "readiness_endpoint": "/ready",
        "metrics_endpoint": "/metrics",
        "docs": "/docs",
    }
