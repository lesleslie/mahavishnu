"""Tests for health check endpoints."""

import pytest
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from mahavishnu.core.metrics_schema import AdapterType, TaskType
from mahavishnu.core.routing_metrics import get_routing_metrics, reset_routing_metrics
from mahavishnu.health import create_health_app


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def startup_time():
    """Fixture for server startup time."""
    return datetime.now(UTC)


@pytest.fixture
def health_app(startup_time):
    """Fixture for health check FastAPI app."""
    return create_health_app(
        server_name="test_mahavishnu",
        startup_time=startup_time,
    )


@pytest.fixture
def client(health_app):
    """Fixture for test client."""
    return TestClient(health_app)


@pytest.fixture
def reset_prometheus_metrics():
    """Reset routing metrics state for tests that mutate the registry."""
    reset_routing_metrics()
    yield
    reset_routing_metrics()


# =============================================================================
# HEALTH CHECK TESTS
# =============================================================================


class TestHealthEndpoint:
    """Test /health endpoint."""

    def test_health_endpoint_returns_200(self, client):
        """Test health endpoint returns 200 OK."""
        response = client.get("/health")

        assert response.status_code == 200

    def test_health_response_structure(self, client):
        """Test health response has correct structure."""
        response = client.get("/health")

        data = response.json()

        assert "status" in data
        assert "service" in data
        assert "version" in data
        assert "uptime_seconds" in data
        assert data["status"] == "ok"
        assert data["service"] == "test_mahavishnu"

    def test_health_uptime_increases(self, client):
        """Test that uptime increases over time."""
        import time

        response1 = client.get("/health")
        uptime1 = response1.json()["uptime_seconds"]

        time.sleep(0.1)

        response2 = client.get("/health")
        uptime2 = response2.json()["uptime_seconds"]

        assert uptime2 > uptime1


class TestReadinessEndpoint:
    """Test /ready endpoint."""

    def test_ready_endpoint_returns_200(self, client):
        """Test readiness endpoint returns 200 OK."""
        response = client.get("/ready")

        assert response.status_code == 200

    def test_readiness_response_structure(self, client):
        """Test readiness response has correct structure."""
        response = client.get("/ready")

        data = response.json()

        assert "ready" in data
        assert "service" in data
        assert "dependencies" in data
        assert "checks" in data
        assert isinstance(data["checks"], dict)

    def test_readiness_includes_component_checks(self, client):
        """Test readiness check includes all components."""
        response = client.get("/ready")

        data = response.json()

        # Check for expected components
        checks = data["checks"]
        expected_checks = ["server", "database", "message_bus", "adapters"]

        for check_name in expected_checks:
            assert check_name in checks
            assert checks[check_name] in {"ok", "unhealthy"}


class TestMetricsEndpoint:
    """Test /metrics endpoint."""

    def test_metrics_endpoint_returns_200(self, client):
        """Test metrics endpoint returns 200 OK."""
        response = client.get("/metrics")

        assert response.status_code == 200

    def test_metrics_response_format(self, client):
        """Test metrics endpoint returns Prometheus text exposition."""
        response = client.get("/metrics")

        assert "text/plain" in response.headers["content-type"]
        assert "# HELP" in response.text
        assert "mcp_http_requests_total" in response.text

    def test_metrics_includes_routing_metrics_on_main_surface(
        self,
        client,
        reset_prometheus_metrics,
    ):
        """Routing metrics should be exposed on the main /metrics endpoint."""
        metrics = get_routing_metrics("mahavishnu")
        metrics.record_routing_decision(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            preference_order=1,
        )

        response = client.get("/metrics")

        assert response.status_code == 200
        assert "mahavishnu_routing_decisions_total" in response.text
        assert 'server="mahavishnu"' in response.text


class TestRootEndpoint:
    """Test root endpoint."""

    def test_root_endpoint_returns_200(self, client):
        """Test root endpoint returns 200 OK."""
        response = client.get("/")

        assert response.status_code == 200

    def test_root_response_includes_service_info(self, client):
        """Test root response includes service information."""
        response = client.get("/")

        data = response.json()

        assert "service" in data
        assert "status" in data
        assert "health_endpoint" in data
        assert "readiness_endpoint" in data
        assert "metrics_endpoint" in data
        assert data["service"] == "test_mahavishnu"


# =============================================================================
# APPLICATION CREATION TESTS
# =============================================================================


class TestHealthAppCreation:
    """Test health app creation."""

    def test_create_health_app_with_defaults(self):
        """Test creating health app with default parameters."""
        app = create_health_app()

        assert app is not None
        assert app.title == "Mahavishnu Health API"

    def test_create_health_app_with_custom_name(self):
        """Test creating health app with custom server name."""
        app = create_health_app(server_name="custom_server")

        assert app is not None
        # FastAPI auto-capitalizes the title
        assert "Custom_Server" in app.title or "custom_server" in app.title

    def test_create_health_app_with_custom_startup_time(self):
        """Test creating health app with custom startup time."""
        startup_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        app = create_health_app(startup_time=startup_time)

        assert app is not None

        # Test that uptime is calculated correctly
        client = TestClient(app)
        response = client.get("/health")
        data = response.json()

        # Uptime should be positive (time since 2025-01-01)
        assert data["uptime_seconds"] > 0

    def test_create_health_app_exposes_service_and_version(self):
        """Test health response includes service metadata."""
        app = create_health_app(server_name="custom_service", version="9.9.9")

        client = TestClient(app)
        data = client.get("/health").json()

        assert data["service"] == "custom_service"
        assert data["version"] == "9.9.9"
