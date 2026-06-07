"""Unit tests for mahavishnu.mcp.tools.health_tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import warnings

import pytest

from mahavishnu.core.health import (
    HealthCheckResult,
    HealthResponse,
    HealthStatus,
    ReadyResponse,
    ServiceInfo,
    WaitResult,
)
from mahavishnu.mcp.tools.health_tools import register_health_tools

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_mcp():
    """Build a mock FastMCP that captures tool functions and supports list_tools."""
    mcp = MagicMock()
    mcp._tools = {}

    def tool_decorator():
        def wrapper(fn):
            mcp._tools[fn.__name__] = fn
            return fn

        return wrapper

    mcp.tool = MagicMock(side_effect=lambda: tool_decorator())
    return mcp


@pytest.fixture
def mock_health_check_result():
    """Build a healthy HealthCheckResult for mocking."""
    return HealthCheckResult(
        service_name="test-svc",
        status=HealthStatus.OK,
        latency_ms=12.5,
        error=None,
        response_data={"status": "ok"},
    )


@pytest.fixture
def mock_unhealthy_result():
    """Build an unhealthy HealthCheckResult for mocking."""
    return HealthCheckResult(
        service_name="test-svc",
        status=HealthStatus.UNHEALTHY,
        latency_ms=200.0,
        error="connection refused",
        response_data=None,
    )


@pytest.fixture
def registered_mcp(mock_mcp, mock_health_check_result):
    """Register health tools on the mock MCP."""
    register_health_tools(mock_mcp)
    return mock_mcp


# =============================================================================
# Tool Registration
# =============================================================================


class TestRegistration:
    """Tests for register_health_tools."""

    def test_all_tools_registered(self, registered_mcp):
        """All health tools should be registered."""
        expected = {
            "health_check_service",
            "mcp_list_tools",
            "mcp_test_connection",
            "mcp_get_metrics",
            "health_check_all",
            "wait_for_dependency",
            "wait_for_all_dependencies",
            "get_liveness",
            "get_readiness",
        }
        assert expected.issubset(set(registered_mcp._tools.keys()))


# =============================================================================
# health_check_service
# =============================================================================


class TestHealthCheckService:
    """Tests for the deprecated health_check_service tool."""

    async def test_ok_response(self, registered_mcp, mock_health_check_result):
        """A successful check should return status/latency/url."""
        with (
            patch(
                "mahavishnu.core.health.HealthChecker.check",
                new=AsyncMock(return_value=mock_health_check_result),
            ),
            warnings.catch_warnings(record=True) as w,
        ):
            warnings.simplefilter("always")
            result = await registered_mcp._tools["health_check_service"](
                service_name="svc", host="example.com", port=9000
            )
            assert any(issubclass(x.category, DeprecationWarning) for x in w)
        assert result["status"] == "ok"
        assert result["latency_ms"] == 12.5
        assert result["url"] == "http://example.com:9000/health"
        assert result["service_name"] == "svc"
        assert "response" in result

    async def test_unhealthy_response_includes_error(self, registered_mcp, mock_unhealthy_result):
        """An unhealthy result should include the error message."""
        with (
            patch(
                "mahavishnu.core.health.HealthChecker.check",
                new=AsyncMock(return_value=mock_unhealthy_result),
            ),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore")
            result = await registered_mcp._tools["health_check_service"](service_name="svc")
        assert result["status"] == "unhealthy"
        assert result["error"] == "connection refused"

    async def test_https_scheme(self, registered_mcp, mock_health_check_result):
        """use_tls=True should result in https:// URL."""
        with (
            patch(
                "mahavishnu.core.health.HealthChecker.check",
                new=AsyncMock(return_value=mock_health_check_result),
            ),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore")
            result = await registered_mcp._tools["health_check_service"](
                service_name="svc", use_tls=True
            )
        assert result["url"].startswith("https://")


# =============================================================================
# mcp_list_tools
# =============================================================================


class TestMcpListTools:
    """Tests for the mcp_list_tools tool."""

    async def test_returns_tool_list(self):
        """Should return a sorted list of tool summaries."""
        # Build a fake tool object
        tool = MagicMock()
        tool.name = "alpha"
        tool.version = "1.0"
        tool.title = "Alpha Tool"
        tool.description = "An alpha tool"
        tool.tags = {"fast"}
        tool.parameters = {"x": "int"}
        tool.timeout = None

        mcp = self._make_mock_mcp()
        mcp.list_tools = AsyncMock(return_value=[tool])
        register_health_tools(mcp)
        result = await mcp._tools["mcp_list_tools"]()
        assert result["status"] == "success"
        assert result["total_tools"] == 1
        assert result["tools"][0]["name"] == "alpha"
        assert result["tools"][0]["version"] == "1.0"

    async def test_empty_tool_list(self):
        """No tools should return zero counts."""
        mcp = self._make_mock_mcp()
        mcp.list_tools = AsyncMock(return_value=[])
        register_health_tools(mcp)
        result = await mcp._tools["mcp_list_tools"]()
        assert result["total_tools"] == 0
        assert result["tools"] == []

    @staticmethod
    def _make_mock_mcp():
        """Build a mock MCP that captures tool functions."""
        mcp = MagicMock()
        mcp._tools = {}

        def tool_decorator():
            def wrapper(fn):
                mcp._tools[fn.__name__] = fn
                return fn

            return wrapper

        mcp.tool = MagicMock(side_effect=lambda: tool_decorator())
        return mcp


# =============================================================================
# mcp_test_connection
# =============================================================================


class TestMcpTestConnection:
    """Tests for the mcp_test_connection tool."""

    async def test_connected(self, registered_mcp, mock_health_check_result):
        """Healthy result should report connected=True."""
        with patch(
            "mahavishnu.core.health.HealthChecker.check",
            new=AsyncMock(return_value=mock_health_check_result),
        ):
            result = await registered_mcp._tools["mcp_test_connection"](service_name="svc")
        assert result["status"] == "ok"
        assert result["connected"] is True
        assert result["service_name"] == "svc"

    async def test_not_connected(self, registered_mcp, mock_unhealthy_result):
        """Unhealthy result should report connected=False."""
        with patch(
            "mahavishnu.core.health.HealthChecker.check",
            new=AsyncMock(return_value=mock_unhealthy_result),
        ):
            result = await registered_mcp._tools["mcp_test_connection"](service_name="svc")
        assert result["status"] == "unhealthy"
        assert result["connected"] is False
        assert result["error"] == "connection refused"

    async def test_custom_health_path(self, registered_mcp, mock_health_check_result):
        """health_path should be honored."""
        with patch(
            "mahavishnu.core.health.HealthChecker.check",
            new=AsyncMock(return_value=mock_health_check_result),
        ):
            result = await registered_mcp._tools["mcp_test_connection"](
                service_name="svc", health_path="/ready"
            )
        assert "/ready" in result["url"]


# =============================================================================
# mcp_get_metrics
# =============================================================================


class TestMcpGetMetrics:
    """Tests for the mcp_get_metrics tool."""

    async def test_returns_metrics(self):
        """Should return metrics snapshot."""
        mcp = TestMcpListTools._make_mock_mcp()
        mcp.list_tools = AsyncMock(return_value=[])
        register_health_tools(mcp)
        result = await mcp._tools["mcp_get_metrics"]()
        assert result["status"] == "success"
        assert "metric_families" in result
        assert "metrics_text" in result
        assert "metrics_preview" in result
        assert isinstance(result["metrics_preview"], list)


# =============================================================================
# health_check_all
# =============================================================================


class TestHealthCheckAll:
    """Tests for the health_check_all tool."""

    async def test_no_dependencies(self, registered_mcp):
        """When settings have no dependencies, return ok with no services."""
        with patch("mahavishnu.core.config.MahavishnuSettings") as mock_settings_cls:
            settings = MagicMock()
            settings.health.dependencies = {}
            settings.health.check_timeout_seconds = 5
            mock_settings_cls.return_value = settings
            result = await registered_mcp._tools["health_check_all"]()
        assert result["status"] == "ok"
        assert result["services"] == {}
        assert "No dependencies configured" in result["message"]

    async def test_all_healthy(self, registered_mcp, mock_health_check_result):
        """When all dependencies are healthy, status should be ok."""
        with (
            patch("mahavishnu.core.config.MahavishnuSettings") as mock_settings_cls,
            patch(
                "mahavishnu.core.health.HealthChecker.check",
                new=AsyncMock(return_value=mock_health_check_result),
            ),
        ):
            settings = MagicMock()
            settings.health.dependencies = {
                "svc1": MagicMock(host="h1", port=1, use_tls=False),
                "svc2": MagicMock(host="h2", port=2, use_tls=False),
            }
            settings.health.check_timeout_seconds = 5
            mock_settings_cls.return_value = settings
            result = await registered_mcp._tools["health_check_all"]()
        assert result["status"] == "ok"
        assert result["total_services"] == 2
        assert result["healthy_services"] == 2

    async def test_some_unhealthy(self, registered_mcp, mock_unhealthy_result):
        """When any dependency is unhealthy, overall should be unhealthy."""
        with (
            patch("mahavishnu.core.config.MahavishnuSettings") as mock_settings_cls,
            patch(
                "mahavishnu.core.health.HealthChecker.check",
                new=AsyncMock(return_value=mock_unhealthy_result),
            ),
        ):
            settings = MagicMock()
            settings.health.dependencies = {"svc1": MagicMock(host="h1", port=1, use_tls=False)}
            settings.health.check_timeout_seconds = 5
            mock_settings_cls.return_value = settings
            result = await registered_mcp._tools["health_check_all"]()
        assert result["status"] == "unhealthy"
        assert "svc1" in result["services"]

    async def test_check_exception(self, registered_mcp):
        """A check that raises should be reported as unhealthy."""
        with (
            patch("mahavishnu.core.config.MahavishnuSettings") as mock_settings_cls,
            patch(
                "mahavishnu.core.health.HealthChecker.check",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            settings = MagicMock()
            settings.health.dependencies = {"svc1": MagicMock(host="h1", port=1, use_tls=False)}
            settings.health.check_timeout_seconds = 5
            mock_settings_cls.return_value = settings
            result = await registered_mcp._tools["health_check_all"]()
        assert result["status"] == "unhealthy"
        assert "boom" in result["services"]["svc1"]["error"]


# =============================================================================
# wait_for_dependency
# =============================================================================


class TestWaitForDependency:
    """Tests for the wait_for_dependency tool."""

    async def test_success(self, registered_mcp, mock_health_check_result):
        """A successful wait should return success."""
        with patch(
            "mahavishnu.core.health.DependencyWaiter.wait_for_all",
            new=AsyncMock(
                return_value=WaitResult(
                    success=True,
                    dependencies={"svc1": mock_health_check_result},
                    total_wait_seconds=0.1,
                    failed_required=[],
                    skipped_optional=[],
                )
            ),
        ):
            result = await registered_mcp._tools["wait_for_dependency"](service_name="svc1")
        assert result["service_name"] == "svc1"
        assert result["success"] is True
        assert result["status"] == "ok"

    async def test_required_timeout(self, registered_mcp):
        """A required dependency that doesn't become healthy should report failure."""
        failed = HealthCheckResult(
            service_name="svc1",
            status=HealthStatus.UNHEALTHY,
            latency_ms=None,
            error="timeout",
        )
        with patch(
            "mahavishnu.core.health.DependencyWaiter.wait_for_all",
            new=AsyncMock(
                return_value=WaitResult(
                    success=False,
                    dependencies={"svc1": failed},
                    total_wait_seconds=30.0,
                    failed_required=["svc1"],
                    skipped_optional=[],
                )
            ),
        ):
            result = await registered_mcp._tools["wait_for_dependency"](
                service_name="svc1", required=True
            )
        assert result["success"] is False
        assert "did not become healthy" in result["message"]


# =============================================================================
# wait_for_all_dependencies
# =============================================================================


class TestWaitForAllDependencies:
    """Tests for the wait_for_all_dependencies tool."""

    async def test_no_dependencies(self, registered_mcp):
        """No dependencies returns success=True with empty deps."""
        with patch("mahavishnu.core.config.MahavishnuSettings") as mock_settings_cls:
            settings = MagicMock()
            settings.health.dependencies = {}
            mock_settings_cls.return_value = settings
            result = await registered_mcp._tools["wait_for_all_dependencies"]()
        assert result["success"] is True
        assert result["dependencies"] == {}

    async def test_all_success(self, registered_mcp, mock_health_check_result):
        """All deps healthy should return success=True."""
        with (
            patch("mahavishnu.core.config.MahavishnuSettings") as mock_settings_cls,
            patch(
                "mahavishnu.core.health.DependencyWaiter.wait_for_all",
                new=AsyncMock(
                    return_value=WaitResult(
                        success=True,
                        dependencies={"svc1": mock_health_check_result},
                        total_wait_seconds=0.1,
                        failed_required=[],
                        skipped_optional=[],
                    )
                ),
            ),
        ):
            settings = MagicMock()
            settings.health.dependencies = {"svc1": MagicMock()}
            mock_settings_cls.return_value = settings
            result = await registered_mcp._tools["wait_for_all_dependencies"]()
        assert result["success"] is True
        assert "svc1" in result["dependencies"]

    async def test_failed_required(self, registered_mcp):
        """A failed required dependency should produce a failure message."""
        failed = HealthCheckResult(
            service_name="svc1",
            status=HealthStatus.UNHEALTHY,
            error="boom",
        )
        with (
            patch("mahavishnu.core.config.MahavishnuSettings") as mock_settings_cls,
            patch(
                "mahavishnu.core.health.DependencyWaiter.wait_for_all",
                new=AsyncMock(
                    return_value=WaitResult(
                        success=False,
                        dependencies={"svc1": failed},
                        total_wait_seconds=30.0,
                        failed_required=["svc1"],
                        skipped_optional=[],
                    )
                ),
            ),
        ):
            settings = MagicMock()
            settings.health.dependencies = {"svc1": MagicMock()}
            mock_settings_cls.return_value = settings
            result = await registered_mcp._tools["wait_for_all_dependencies"]()
        assert result["success"] is False
        assert "Failed to connect" in result["message"]


# =============================================================================
# get_liveness / get_readiness
# =============================================================================


class TestGetLiveness:
    """Tests for the deprecated get_liveness tool."""

    async def test_liveness_response(self, registered_mcp):
        """Should return the liveness response dict."""
        with (
            patch("mahavishnu.core.config.MahavishnuSettings") as mock_settings_cls,
            patch(
                "mahavishnu.core.health.HealthEndpoint.liveness",
                new=AsyncMock(
                    return_value=HealthResponse(
                        status=HealthStatus.OK,
                        service="mahavishnu",
                        version="0.3.2",
                        uptime_seconds=10.0,
                    )
                ),
            ),
        ):
            settings = MagicMock()
            settings.health.dependencies = {}
            mock_settings_cls.return_value = settings
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = await registered_mcp._tools["get_liveness"]()
                assert any(issubclass(x.category, DeprecationWarning) for x in w)
        assert result["status"] == "ok"
        assert result["service"] == "mahavishnu"


class TestGetReadiness:
    """Tests for the deprecated get_readiness tool."""

    async def test_readiness_response(self, registered_mcp):
        """Should return the readiness response dict."""
        ready_response = ReadyResponse(
            ready=True,
            service="mahavishnu",
            dependencies={},
            checks={},
        )
        with (
            patch("mahavishnu.core.config.MahavishnuSettings") as mock_settings_cls,
            patch(
                "mahavishnu.core.health.HealthEndpoint.readiness",
                new=AsyncMock(return_value=ready_response),
            ),
        ):
            settings = MagicMock()
            settings.health.dependencies = {}
            mock_settings_cls.return_value = settings
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = await registered_mcp._tools["get_readiness"]()
                assert any(issubclass(x.category, DeprecationWarning) for x in w)
        assert result["ready"] is True
        assert result["service"] == "mahavishnu"


# =============================================================================
# App-aware registration
# =============================================================================


class TestRegistrationWithApp:
    """Tests for register_health_tools with an app instance."""

    def test_server_name_from_app_config(self, mock_mcp):
        """When an app with config.server_name is provided, the tools should use it."""
        app = MagicMock()
        app.config.server_name = "my-custom-server"
        register_health_tools(mock_mcp, app=app)
        # The server name is captured at registration time in _server_name closure.
        # Just verify registration succeeded.
        assert "mcp_list_tools" in mock_mcp._tools

    def test_default_server_name(self, mock_mcp):
        """When no app is provided, default to 'mahavishnu'."""
        register_health_tools(mock_mcp, app=None)
        assert "mcp_list_tools" in mock_mcp._tools


# =============================================================================
# HealthCheckResult / WaitResult models
# =============================================================================


class TestHealthModels:
    """Tests for the health data models."""

    def test_health_check_result_construction(self):
        """HealthCheckResult can be constructed with all fields."""
        r = HealthCheckResult(
            service_name="x",
            status=HealthStatus.OK,
            latency_ms=1.5,
            error=None,
        )
        assert r.service_name == "x"
        assert r.status == HealthStatus.OK

    def test_wait_result_construction(self):
        """WaitResult can be constructed with all fields."""
        wr = WaitResult(
            success=True,
            dependencies={},
            total_wait_seconds=1.0,
            failed_required=[],
            skipped_optional=[],
        )
        assert wr.success is True

    def test_service_info_uptime(self):
        """ServiceInfo.uptime_seconds should be > 0 after a sleep."""
        import time

        info = ServiceInfo(name="x", version="1.0")
        time.sleep(0.01)
        assert info.uptime_seconds > 0
