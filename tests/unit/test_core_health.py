# tests/unit/test_health.py
"""Unit tests for mahavishnu.core.health module."""

from __future__ import annotations

from datetime import UTC, datetime

from mahavishnu.core.health import (
    DependencyStatus,
    HealthResponse,
    HealthStatus,
)


class TestHealthStatus:
    """Unit tests for HealthStatus enum."""

    def test_health_status_values(self):
        """Test HealthStatus enum values."""
        assert HealthStatus.OK == "ok"
        assert HealthStatus.DEGRADED == "degraded"
        assert HealthStatus.UNHEALTHY == "unhealthy"

    def test_health_status_is_str_enum(self):
        """Test HealthStatus is a string enum."""
        assert isinstance(HealthStatus.OK, str)
        assert HealthStatus.OK == "ok"


class TestDependencyStatus:
    """Unit tests for DependencyStatus model."""

    def test_dependency_status_creation(self):
        """Test basic DependencyStatus creation."""
        status = DependencyStatus(status=HealthStatus.OK)

        assert status.status == HealthStatus.OK
        assert status.latency_ms is None
        assert status.error is None
        assert status.last_check is None

    def test_dependency_status_with_all_fields(self):
        """Test DependencyStatus with all fields populated."""
        now = datetime.now(UTC)
        status = DependencyStatus(
            status=HealthStatus.DEGRADED,
            latency_ms=150.5,
            error="Connection timeout",
            last_check=now,
        )

        assert status.status == HealthStatus.DEGRADED
        assert status.latency_ms == 150.5
        assert status.error == "Connection timeout"
        assert status.last_check == now

    def test_dependency_status_unhealthy(self):
        """Test DependencyStatus for unhealthy dependency."""
        status = DependencyStatus(
            status=HealthStatus.UNHEALTHY,
            error="Service unavailable",
        )

        assert status.status == HealthStatus.UNHEALTHY
        assert status.error == "Service unavailable"


class TestHealthResponse:
    """Unit tests for HealthResponse model."""

    def test_health_response_creation(self):
        """Test basic HealthResponse creation."""
        response = HealthResponse(
            status=HealthStatus.OK,
            service="mahavishnu",
            version="0.7.1",
            uptime_seconds=3600.0,
        )

        assert response.status == HealthStatus.OK
        assert response.service == "mahavishnu"
        assert response.version == "0.7.1"
        assert response.uptime_seconds == 3600.0
        assert response.timestamp is not None

    def test_health_response_default_timestamp(self):
        """Test HealthResponse has default timestamp."""
        response = HealthResponse(
            status=HealthStatus.OK,
            service="mahavishnu",
            version="0.7.1",
            uptime_seconds=0.0,
        )

        assert response.timestamp is not None
        assert isinstance(response.timestamp, datetime)

    def test_health_response_json_schema_extra(self):
        """Test HealthResponse model_config contains json_schema_extra."""
        config = HealthResponse.model_config
        assert "json_schema_extra" in config
