"""Unit tests for ``mahavishnu.health``.

These tests exercise the FastAPI application built by ``create_health_app``:

- ``GET /health`` -- liveness probe (always 200 while the process is alive)
- ``GET /ready``  -- readiness probe (200 only when sub-checks pass)
- ``GET /metrics``-- Prometheus exposition (delegates to ``monitoring.metrics``)
- ``GET /``       -- root metadata block

The readiness sub-checks depend on heavy modules (``EncryptedSQLite``,
``InMemoryEventTransport``, ``MahavishnuSettings``).  We mock them at the
``mahavishnu.health`` boundary so the tests stay fast and dependency-free.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sys
from types import ModuleType

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
import pytest

from mahavishnu.health import create_health_app

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
def fake_metrics_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Inject a fake ``monitoring.metrics`` module.

    The ``/metrics`` endpoint imports ``monitoring.metrics.metrics_endpoint``
    lazily, so we register a stub module in :data:`sys.modules` to keep the
    test isolated from the real Prometheus plumbing.
    """
    fake = ModuleType("monitoring.metrics")

    async def _endpoint() -> Response:
        return Response(content="mock_metrics", media_type="text/plain")

    fake.metrics_endpoint = _endpoint
    monkeypatch.setitem(sys.modules, "monitoring.metrics", fake)
    return fake


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
    assert app.title == "My-svc Health API"


def test_create_health_app_accepts_health_config() -> None:
    """Passing a ``HealthConfig`` does not raise during construction."""
    from mahavishnu.core.config import HealthConfig

    app = create_health_app(health_config=HealthConfig())
    assert isinstance(app, FastAPI)


# ---------------------------------------------------------------------------
# GET /health (liveness)
# ---------------------------------------------------------------------------


def test_health_endpoint_returns_200(client: TestClient) -> None:
    """Liveness probe always returns 200 while the process is alive."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_endpoint_status_is_ok(client: TestClient) -> None:
    """The response declares ``status='ok'``."""
    body = client.get("/health").json()
    assert body["status"] == "ok"


def test_health_endpoint_response_schema(client: TestClient) -> None:
    """Liveness response carries the documented fields."""
    body = client.get("/health").json()
    expected = {"status", "service", "version", "uptime_seconds", "timestamp"}
    assert expected.issubset(body.keys())
    assert body["service"] == "test-mahavishnu"
    assert body["version"] == "9.9.9"
    # ``timestamp`` is a Pydantic-managed ISO 8601 string.
    assert isinstance(body["timestamp"], str)


def test_health_endpoint_uptime_is_nonnegative(client: TestClient) -> None:
    """Uptime is non-negative when the supplied ``startup_time`` is in the past."""
    body = client.get("/health").json()
    assert body["uptime_seconds"] >= 0


def test_health_endpoint_reflects_custom_version() -> None:
    """The ``version`` parameter flows through to the response body."""
    app = create_health_app(version="1.2.3", startup_time=datetime.now(UTC))
    with TestClient(app) as c:
        body = c.get("/health").json()
    assert body["version"] == "1.2.3"


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
    """Readiness response contains ``ready``, ``service``, ``dependencies``, ``checks``."""
    body = client.get("/ready").json()
    assert set(body.keys()) == {"ready", "service", "dependencies", "checks"}
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
# GET /metrics
# ---------------------------------------------------------------------------


def test_metrics_endpoint_returns_200(client: TestClient, fake_metrics_module: ModuleType) -> None:
    """The metrics endpoint returns 200 and the delegated payload."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.text == "mock_metrics"
    assert response.headers["content-type"].startswith("text/plain")


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
