"""Tests for health check system."""

from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.core.config import DependencyConfig, HealthConfig
from mahavishnu.core.health import (
    DependencyTimeoutError,
    DependencyUnavailableError,
    DependencyWaiter,
    HealthChecker,
    HealthCheckError,
    HealthCheckResult,
    HealthEndpoint,
    HealthStatus,
    ServiceInfo,
)
from monitoring.metrics import expose_metrics


class TestServiceInfo:
    """Tests for ServiceInfo dataclass."""

    def test_service_info_creation(self):
        """Test ServiceInfo creation."""
        info = ServiceInfo(name="mahavishnu", version="0.3.2")
        assert info.name == "mahavishnu"
        assert info.version == "0.3.2"
        assert info.uptime_seconds >= 0

    def test_service_info_uptime_increases(self):
        """Test that uptime increases over time."""
        import time

        info = ServiceInfo(name="test", version="1.0")
        time.sleep(0.1)
        assert info.uptime_seconds >= 0.1


class TestHealthChecker:
    """Tests for HealthChecker class."""

    @pytest.fixture
    def health_config(self):
        """Create test health configuration."""
        return HealthConfig(
            enabled=True,
            check_timeout_seconds=5,
        )

    @pytest.fixture
    def checker(self, health_config):
        """Create health checker with config."""
        return HealthChecker(config=health_config)

    @pytest.mark.asyncio
    async def test_check_healthy_service(self, checker):
        """Test checking a healthy service."""
        with patch.object(
            checker._http_action,
            "execute",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = {
                "ok": True,
                "status_code": 200,
                "json": {"status": "ok", "service": "test"},
            }

            result = await checker.check("http://localhost:8678/health")

            assert result.status == HealthStatus.OK
            assert result.error is None

    @pytest.mark.asyncio
    async def test_check_unhealthy_service(self, checker):
        """Test checking an unhealthy service."""
        with patch.object(
            checker._http_action,
            "execute",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = {
                "ok": False,
                "status_code": 503,
                "json": None,
            }

            result = await checker.check("http://localhost:8678/health")

            assert result.status == HealthStatus.UNHEALTHY
            assert "503" in result.error

    @pytest.mark.asyncio
    async def test_check_degraded_service(self, checker):
        """Test checking a degraded service."""
        with patch.object(
            checker._http_action,
            "execute",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = {
                "ok": True,
                "status_code": 200,
                "json": {"status": "degraded"},
            }

            result = await checker.check("http://localhost:8678/health")

            assert result.status == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_check_connection_refused(self, checker):
        """Test handling connection refused."""
        import httpx

        with patch.object(
            checker._http_action,
            "execute",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            result = await checker.check("http://localhost:9999/health")

            assert result.status == HealthStatus.UNHEALTHY
            assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_check_timeout(self, checker):
        """Test handling timeout."""
        with patch.object(
            checker._http_action,
            "execute",
            new_callable=AsyncMock,
            side_effect=TimeoutError(),
        ):
            result = await checker.check("http://localhost:9999/health")

            assert result.status == HealthStatus.UNHEALTHY
            assert "Timeout" in result.error

    @pytest.mark.asyncio
    async def test_check_generic_exception(self, checker):
        """Test handling an unexpected exception."""
        with patch.object(
            checker._http_action,
            "execute",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await checker.check("http://localhost:9999/health")

            assert result.status == HealthStatus.UNHEALTHY
            assert "boom" in result.error

    @pytest.mark.asyncio
    async def test_check_unknown_status_maps_to_unhealthy(self, checker):
        """Test that unknown status strings map to unhealthy."""
        with patch.object(
            checker._http_action,
            "execute",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = {
                "ok": True,
                "status_code": 200,
                "json": {"status": "mystery"},
            }

            result = await checker.check("http://localhost:8678/health")

            assert result.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_check_records_dependency_metrics(self, checker):
        """Health checks should update shared dependency metrics."""
        with patch.object(
            checker._http_action,
            "execute",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = {
                "ok": True,
                "status_code": 200,
                "json": {"status": "ok"},
            }

            await checker.check("http://localhost:8678/health")

        metrics_text = expose_metrics().decode()
        assert "mahavishnu_dependency_requests_total" in metrics_text
        assert 'dependency="localhost:8678"' in metrics_text
        assert 'status="ok"' in metrics_text

    def test_extract_service_name_falls_back_on_parse_failure(self, checker):
        """Test URL parsing fallback path when urlparse fails."""
        with patch("urllib.parse.urlparse", side_effect=RuntimeError("boom")):
            assert checker._extract_service_name("bad://url") == "bad://url"

    def test_check_message_bus_uses_canonical_transport(self, monkeypatch):
        import mahavishnu.health as health_module

        class _FakeTransport:
            def __init__(self) -> None:
                self.created = True

        monkeypatch.setattr(
            "mahavishnu.core.events.contract.InMemoryEventTransport",
            _FakeTransport,
        )

        assert health_module._check_message_bus() is True


class TestDependencyWaiter:
    """Tests for DependencyWaiter class."""

    @pytest.fixture
    def health_config(self):
        """Create test health configuration."""
        return HealthConfig(
            enabled=True,
            check_timeout_seconds=1,
            retry_base_delay_seconds=0.1,
            retry_max_delay_seconds=1.0,  # Minimum allowed is 1.0
        )

    @pytest.fixture
    def waiter(self, health_config):
        """Create dependency waiter with config."""
        return DependencyWaiter(config=health_config)

    @pytest.mark.asyncio
    async def test_wait_for_all_healthy(self, waiter):
        """Test waiting for all healthy dependencies."""
        dependencies = {
            "session_buddy": DependencyConfig(
                host="localhost",
                port=8678,
                required=True,
                timeout_seconds=5,
            ),
        }

        # Mock the checker to return healthy
        mock_result = HealthCheckResult(
            service_name="session_buddy",
            status=HealthStatus.OK,
            latency_ms=5.0,
        )

        with patch.object(
            waiter._checker,
            "check",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await waiter.wait_for_all(dependencies)

            assert result.success
            assert len(result.failed_required) == 0

    @pytest.mark.asyncio
    async def test_wait_for_all_with_failure(self, waiter):
        """Test waiting with failed required dependency."""
        dependencies = {
            "akosha": DependencyConfig(
                host="localhost",
                port=8682,
                required=True,
                timeout_seconds=1,  # Short timeout for test
            ),
        }

        # Mock the checker to return unhealthy
        mock_result = HealthCheckResult(
            service_name="akosha",
            status=HealthStatus.UNHEALTHY,
            error="Connection refused",
        )

        with patch.object(
            waiter._checker,
            "check",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await waiter.wait_for_all(dependencies)

            assert not result.success
            assert "akosha" in result.failed_required

    @pytest.mark.asyncio
    async def test_wait_for_all_handles_checker_exception(self, waiter):
        """Test wait_for_all records exceptions from dependency tasks."""
        dependencies = {
            "session_buddy": DependencyConfig(
                host="localhost",
                port=8678,
                required=True,
                timeout_seconds=1,
            ),
        }

        with patch.object(
            waiter,
            "_wait_for_single",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await waiter.wait_for_all(dependencies)

            assert not result.success
            assert "session_buddy" in result.failed_required
            assert result.dependencies["session_buddy"].status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_wait_for_optional_skipped(self, waiter):
        """Test that optional dependencies can be skipped."""
        dependencies = {
            "dhara": DependencyConfig(
                host="localhost",
                port=8683,
                required=False,
                timeout_seconds=1,
            ),
        }

        # Mock the checker to return unhealthy
        mock_result = HealthCheckResult(
            service_name="dhara",
            status=HealthStatus.UNHEALTHY,
            error="Connection refused",
        )

        with patch.object(
            waiter._checker,
            "check",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await waiter.wait_for_all(dependencies)

            # Should succeed because dhara is optional
            assert result.success
            assert "dhara" in result.skipped_optional

    @pytest.mark.asyncio
    async def test_wait_for_optional_healthy(self, waiter):
        """Test that healthy optional dependencies are tracked without skips."""
        dependencies = {
            "dhara": DependencyConfig(
                host="localhost",
                port=8683,
                required=False,
                timeout_seconds=1,
            ),
        }

        mock_result = HealthCheckResult(
            service_name="dhara",
            status=HealthStatus.OK,
            latency_ms=2.0,
        )

        with patch.object(
            waiter._checker,
            "check",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await waiter.wait_for_all(dependencies)

            assert result.success
            assert result.dependencies["dhara"].status == HealthStatus.OK
            assert result.skipped_optional == []

    @pytest.mark.asyncio
    async def test_wait_for_optional_unhealthy_records_skip(self, waiter):
        """Test optional dependency unhealthy path before skip fallback."""
        dependencies = {
            "dhara": DependencyConfig(
                host="localhost",
                port=8683,
                required=False,
                timeout_seconds=1,
            ),
        }

        unhealthy_result = HealthCheckResult(
            service_name="dhara",
            status=HealthStatus.UNHEALTHY,
            error="Connection refused",
        )

        with patch.object(
            waiter,
            "_wait_for_single",
            new_callable=AsyncMock,
            return_value=unhealthy_result,
        ):
            result = await waiter.wait_for_all(dependencies)

            assert result.success
            assert result.dependencies["dhara"].status == HealthStatus.UNHEALTHY
            assert "dhara" in result.skipped_optional

    @pytest.mark.asyncio
    async def test_wait_for_single_degraded(self, waiter):
        """Test that degraded dependencies return immediately."""
        dependency = DependencyConfig(
            host="localhost",
            port=8683,
            required=False,
            timeout_seconds=1,
        )
        mock_result = HealthCheckResult(
            service_name="dhara",
            status=HealthStatus.DEGRADED,
            latency_ms=3.0,
        )

        with patch.object(
            waiter._checker,
            "check",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await waiter._wait_for_single("dhara", dependency)

            assert isinstance(result, HealthCheckResult)
            assert result.status == HealthStatus.DEGRADED


class TestHealthEndpoint:
    """Tests for HealthEndpoint class."""

    @pytest.fixture
    def service_info(self):
        """Create test service info."""
        return ServiceInfo(name="mahavishnu", version="0.3.2")

    @pytest.fixture
    def health_config(self):
        """Create test health configuration."""
        return HealthConfig(enabled=True)

    @pytest.fixture
    def endpoint(self, service_info, health_config):
        """Create health endpoint with config."""
        return HealthEndpoint(
            service_info=service_info,
            config=health_config,
        )

    @pytest.mark.asyncio
    async def test_liveness(self, endpoint):
        """Test liveness endpoint."""
        response = await endpoint.liveness()

        assert response.status == HealthStatus.OK
        assert response.service == "mahavishnu"
        assert response.version == "0.3.2"
        assert response.uptime_seconds >= 0

    @pytest.mark.asyncio
    async def test_readiness_no_dependencies(self, endpoint):
        """Test readiness with no dependencies."""
        response = await endpoint.readiness()

        assert response.ready
        assert response.service == "mahavishnu"
        assert response.checks["process"] == "ok"

    @pytest.mark.asyncio
    async def test_readiness_with_healthy_dependencies(self, endpoint):
        """Test readiness with healthy dependencies."""
        dependencies = {
            "session_buddy": DependencyConfig(
                host="localhost",
                port=8678,
                required=True,
            ),
        }

        # Mock the checker
        mock_result = HealthCheckResult(
            service_name="session_buddy",
            status=HealthStatus.OK,
            latency_ms=5.0,
        )

        with patch.object(
            endpoint._checker,
            "check",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await endpoint.readiness(dependencies)

            assert response.ready
            assert "session_buddy" in response.dependencies
            assert response.dependencies["session_buddy"].status == HealthStatus.OK

    @pytest.mark.asyncio
    async def test_readiness_with_unhealthy_required(self, endpoint):
        """Test readiness with unhealthy required dependency."""
        dependencies = {
            "akosha": DependencyConfig(
                host="localhost",
                port=8682,
                required=True,
            ),
        }

        # Mock the checker
        mock_result = HealthCheckResult(
            service_name="akosha",
            status=HealthStatus.UNHEALTHY,
            error="Connection refused",
        )

        with patch.object(
            endpoint._checker,
            "check",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await endpoint.readiness(dependencies)

            assert not response.ready
            assert response.dependencies["akosha"].status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_readiness_handles_checker_exception(self, endpoint):
        """Test readiness when a dependency check raises."""
        dependencies = {
            "session_buddy": DependencyConfig(
                host="localhost",
                port=8678,
                required=True,
            ),
        }

        with patch.object(
            endpoint._checker,
            "check",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            response = await endpoint.readiness(dependencies)

            assert not response.ready
            assert response.dependencies["session_buddy"].status == HealthStatus.UNHEALTHY
            assert "boom" in response.dependencies["session_buddy"].error


class TestHealthErrors:
    """Tests for health check error classes."""

    def test_health_check_error(self):
        """Test HealthCheckError."""
        error = HealthCheckError("Test error", {"key": "value"})
        assert "Test error" in str(error)
        assert error.details == {"key": "value"}

    def test_dependency_timeout_error(self):
        """Test DependencyTimeoutError."""
        error = DependencyTimeoutError("session_buddy", 30)
        assert "session_buddy" in str(error)
        assert "30" in str(error)
        assert error.details["service"] == "session_buddy"
        assert error.details["timeout_seconds"] == 30

    def test_dependency_unavailable_error(self):
        """Test DependencyUnavailableError."""
        error = DependencyUnavailableError("akosha", "Connection refused")
        assert "akosha" in str(error)
        assert "Connection refused" in str(error)
        assert error.details["service"] == "akosha"
        assert error.details["error"] == "Connection refused"
