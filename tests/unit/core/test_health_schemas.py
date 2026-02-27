"""Tests for health check schemas."""

import pytest
from datetime import datetime

from mahavishnu.core.health_schemas import (
    HealthStatus,
    HealthResponse,
    DependencyStatus,
    ReadyResponse,
    HealthCheckResult,
    WaitResult,
)


class TestHealthStatus:
    """Tests for HealthStatus enum."""

    def test_health_status_values(self):
        """Test HealthStatus enum has expected values."""
        assert HealthStatus.OK == "ok"
        assert HealthStatus.DEGRADED == "degraded"
        assert HealthStatus.UNHEALTHY == "unhealthy"


class TestDependencyStatus:
    """Tests for DependencyStatus model."""

    def test_dependency_status_creation(self):
        """Test DependencyStatus model creation."""
        status = DependencyStatus(
            status=HealthStatus.OK,
            latency_ms=5.2,
        )
        assert status.status == HealthStatus.OK
        assert status.latency_ms == 5.2
        assert status.error is None
        assert status.last_check is None

    def test_dependency_status_with_error(self):
        """Test DependencyStatus with error."""
        status = DependencyStatus(
            status=HealthStatus.UNHEALTHY,
            error="Connection refused",
        )
        assert status.status == HealthStatus.UNHEALTHY
        assert status.error == "Connection refused"


class TestHealthResponse:
    """Tests for HealthResponse model."""

    def test_health_response_creation(self):
        """Test HealthResponse model creation."""
        response = HealthResponse(
            status=HealthStatus.OK,
            service="mahavishnu",
            version="0.3.2",
            uptime_seconds=3600,
        )
        assert response.status == HealthStatus.OK
        assert response.service == "mahavishnu"
        assert response.version == "0.3.2"
        assert response.uptime_seconds == 3600
        assert response.timestamp is not None

    def test_health_response_to_dict(self):
        """Test HealthResponse serialization."""
        response = HealthResponse(
            status=HealthStatus.OK,
            service="test",
            version="1.0.0",
            uptime_seconds=100,
        )
        data = response.model_dump()
        assert data["status"] == "ok"
        assert data["service"] == "test"
        assert data["version"] == "1.0.0"
        assert data["uptime_seconds"] == 100
        assert "timestamp" in data

    def test_health_response_json_serialization(self):
        """Test HealthResponse JSON serialization."""
        response = HealthResponse(
            status=HealthStatus.DEGRADED,
            service="test",
            version="1.0.0",
            uptime_seconds=50,
        )
        json_str = response.model_dump_json()
        assert '"status":"degraded"' in json_str
        assert '"service":"test"' in json_str

    def test_health_response_with_degraded_status(self):
        """Test HealthResponse with degraded status."""
        response = HealthResponse(
            status=HealthStatus.DEGRADED,
            service="mahavishnu",
            version="0.3.2",
            uptime_seconds=3600,
        )
        assert response.status == HealthStatus.DEGRADED


class TestReadyResponse:
    """Tests for ReadyResponse model."""

    def test_ready_response_creation(self):
        """Test ReadyResponse model creation."""
        response = ReadyResponse(
            ready=True,
            service="mahavishnu",
            dependencies={
                "session_buddy": DependencyStatus(status=HealthStatus.OK, latency_ms=5)
            },
            checks={"database": "ok"},
        )
        assert response.ready is True
        assert response.service == "mahavishnu"
        assert "session_buddy" in response.dependencies
        assert response.checks["database"] == "ok"

    def test_ready_response_not_ready(self):
        """Test ReadyResponse when not ready."""
        response = ReadyResponse(
            ready=False,
            service="mahavishnu",
            dependencies={
                "akosha": DependencyStatus(
                    status=HealthStatus.UNHEALTHY, error="Connection refused"
                )
            },
        )
        assert response.ready is False
        assert response.dependencies["akosha"].status == HealthStatus.UNHEALTHY

    def test_ready_response_empty_dependencies(self):
        """Test ReadyResponse with no dependencies."""
        response = ReadyResponse(
            ready=True,
            service="standalone",
        )
        assert response.ready is True
        assert response.dependencies == {}
        assert response.checks == {}


class TestHealthCheckResult:
    """Tests for HealthCheckResult model."""

    def test_health_check_result_success(self):
        """Test HealthCheckResult for successful check."""
        result = HealthCheckResult(
            service_name="session_buddy",
            status=HealthStatus.OK,
            latency_ms=5.2,
            response_data={"status": "ok"},
        )
        assert result.service_name == "session_buddy"
        assert result.status == HealthStatus.OK
        assert result.latency_ms == 5.2
        assert result.error is None

    def test_health_check_result_failure(self):
        """Test HealthCheckResult for failed check."""
        result = HealthCheckResult(
            service_name="akosha",
            status=HealthStatus.UNHEALTHY,
            error="Connection refused",
        )
        assert result.service_name == "akosha"
        assert result.status == HealthStatus.UNHEALTHY
        assert result.error == "Connection refused"


class TestWaitResult:
    """Tests for WaitResult model."""

    def test_wait_result_success(self):
        """Test WaitResult for successful wait."""
        result = WaitResult(
            success=True,
            dependencies={
                "session_buddy": HealthCheckResult(
                    service_name="session_buddy",
                    status=HealthStatus.OK,
                    latency_ms=5,
                )
            },
            total_wait_seconds=0.5,
        )
        assert result.success is True
        assert len(result.dependencies) == 1
        assert result.failed_required == []
        assert result.skipped_optional == []

    def test_wait_result_with_failures(self):
        """Test WaitResult with failed dependencies."""
        result = WaitResult(
            success=False,
            dependencies={
                "akosha": HealthCheckResult(
                    service_name="akosha",
                    status=HealthStatus.UNHEALTHY,
                    error="Timeout",
                )
            },
            total_wait_seconds=30,
            failed_required=["akosha"],
        )
        assert result.success is False
        assert result.failed_required == ["akosha"]

    def test_wait_result_with_skipped_optional(self):
        """Test WaitResult with skipped optional dependencies."""
        result = WaitResult(
            success=True,
            dependencies={
                "session_buddy": HealthCheckResult(
                    service_name="session_buddy",
                    status=HealthStatus.OK,
                )
            },
            total_wait_seconds=0.1,
            skipped_optional=["dhruva"],
        )
        assert result.success is True
        assert result.skipped_optional == ["dhruva"]
