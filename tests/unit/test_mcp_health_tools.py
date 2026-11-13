"""Unit tests for mahavishnu.mcp.tools.health_tools.

The six shared health tools are owned by ``mcp_common.health`` and are
tested there. What Mahavishnu owns is:

* that the shared surface is mounted on this server with THIS server's
  identity, dependency map and deprecation map;
* that exactly one implementation is registered behind each shared name;
* that the three Mahavishnu-specific MCP tools behave as documented.

The behaviour of the shared tools themselves is deliberately NOT duplicated
here - mcp-common owns that implementation and its tests. Duplicating it
would let the two copies drift, which is the defect the de-vendoring
removes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import warnings

import pytest

from mcp_common.health import HealthCheckResult as SharedHealthCheckResult
from mcp_common.health import HealthStatus as SharedHealthStatus

from mahavishnu.core.health import (
    HealthCheckResult,
    HealthResponse,
    HealthStatus,
    ReadyResponse,
    ServiceInfo,
    WaitResult,
)
from mahavishnu.mcp.tools.health_tools import (
    DEPRECATED_TOOLS,
    register_health_tools,
)

pytestmark = pytest.mark.unit


#: The six names mcp_common.health owns, and the three Mahavishnu keeps.
SHARED_TOOL_NAMES = frozenset(
    {
        "health_check_service",
        "health_check_all",
        "wait_for_dependency",
        "wait_for_all_dependencies",
        "get_liveness",
        "get_readiness",
    }
)
MAHAVISHNU_TOOL_NAMES = frozenset(
    {
        "mahavishnu_mcp_list_tools",
        "mahavishnu_mcp_test_connection",
        "mahavishnu_mcp_get_metrics",
    }
)


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
        """All nine health tools should be registered."""
        expected = SHARED_TOOL_NAMES | MAHAVISHNU_TOOL_NAMES
        assert expected.issubset(set(registered_mcp._tools.keys()))

    def test_shared_tools_come_from_mcp_common(self, registered_mcp):
        """Each shared name must have exactly one implementation: mcp-common's."""
        for name in SHARED_TOOL_NAMES:
            fn = registered_mcp._tools[name]
            assert fn.__module__ == "mcp_common.health", (
                f"{name} is implemented by {fn.__module__}, not mcp_common.health. "
                "The vendored fork must not come back."
            )

    def test_mahavishnu_tools_stay_local(self, registered_mcp):
        """The three Mahavishnu-specific tools are implemented here."""
        for name in MAHAVISHNU_TOOL_NAMES:
            fn = registered_mcp._tools[name]
            assert fn.__module__ == "mahavishnu.mcp.tools.health_tools"

    def test_registering_twice_does_not_duplicate(self, mock_mcp):
        """A second registration on the same server is a no-op.

        Mahavishnu mounts the health surface from both the legacy path
        (``server_core._register_tools``) and the profile path
        (``apply_tool_profile`` -> ``_register_health_tools``). FastMCP
        replaces a duplicate registration and leaves the first copy
        shadowed, so the guard is what keeps one registration per name.
        """
        register_health_tools(mock_mcp)
        first = dict(mock_mcp._tools)
        register_health_tools(mock_mcp)
        register_health_tools(mock_mcp)

        assert set(mock_mcp._tools) == set(first)
        assert len(mock_mcp._tools) == len(SHARED_TOOL_NAMES | MAHAVISHNU_TOOL_NAMES)


# =============================================================================
# Shared-surface contract
# =============================================================================


class TestSharedSurfaceContract:
    """What Mahavishnu contributes to the shared mcp-common health surface."""

    async def test_liveness_envelope_reports_mahavishnu_identity(self, registered_mcp):
        """The shared liveness tool reports THIS server's identity."""
        result = await registered_mcp._tools["get_liveness"]()
        assert result["service"] == "mahavishnu"
        assert result["status"] == "ok"

    async def test_server_name_from_app_config_reaches_the_envelope(self, mock_mcp):
        """An app-provided server_name overrides the default."""
        app = MagicMock()
        app.config.server_name = "my-custom-server"
        app.config.health.dependencies = {}
        register_health_tools(mock_mcp, app=app)

        result = await mock_mcp._tools["get_liveness"]()
        assert result["service"] == "my-custom-server"

    async def test_dependency_map_reaches_the_shared_surface(self, mock_mcp):
        """Mahavishnu's configured dependencies are the ones the shared tool checks."""
        app = MagicMock()
        app.config.server_name = "mahavishnu"
        dependency = MagicMock()
        dependency.host = "localhost"
        dependency.port = 8678
        dependency.required = True
        dependency.timeout_seconds = 30
        dependency.use_tls = False
        app.config.health.dependencies = {"session_buddy": dependency}
        register_health_tools(mock_mcp, app=app)

        checked: list[str] = []

        async def _check(self, url, **kwargs):
            checked.append(url)
            return SharedHealthCheckResult(
                service_name="session_buddy",
                status=SharedHealthStatus.HEALTHY,
                latency_ms=1.0,
            )

        with patch(
            "mcp_common.health.HealthChecker.check",
            new=_check,
        ):
            result = await mock_mcp._tools["health_check_all"]()

        assert checked, "the shared health_check_all did not probe any dependency"
        assert "8678" in checked[0]
        assert result["status"] == "healthy"
        assert result["total_services"] == 1

    async def test_deprecation_map_reaches_the_shared_surface(self, registered_mcp):
        """A name in the deprecation map warns when it is called."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with patch(
                "mcp_common.health.HealthChecker.check",
                new=AsyncMock(
                    return_value=SharedHealthCheckResult(
                        service_name="svc",
                        status=SharedHealthStatus.HEALTHY,
                    )
                ),
            ):
                await registered_mcp._tools["health_check_service"](service_name="svc")

        assert any(issubclass(w.category, DeprecationWarning) for w in caught)

    async def test_canonical_tools_do_not_warn(self, registered_mcp):
        """A name outside the deprecation map stays silent."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            await registered_mcp._tools["health_check_all"]()

        assert not any(issubclass(w.category, DeprecationWarning) for w in caught)

    def test_deprecation_map_carries_the_fork_shim_forward(self):
        """The deprecations the fork owned must survive the de-vendoring."""
        assert DEPRECATED_TOOLS["health_check_service"] == "health_check_all"
        assert DEPRECATED_TOOLS["get_liveness"] == "mahavishnu_ecosystem_status"
        assert DEPRECATED_TOOLS["get_readiness"] == "mahavishnu_ecosystem_status"

    async def test_readiness_extra_contributes_the_workers_fold(self, mock_mcp):
        """Mahavishnu's worker-capability state reaches the readiness payload.

        The MCP tool and the ``/ready`` HTTP route are documented to carry
        the same payload, so the workers fold the fork used to inline must
        survive the de-vendoring.
        """
        app = MagicMock()
        app.config.server_name = "mahavishnu"
        app.config.health.dependencies = {}
        register_health_tools(mock_mcp, app=app)

        workers = {"status": "healthy", "worker_reports": {"terminal-claude": "ready"}}
        with patch(
            "mahavishnu.core.health.aggregate_readiness",
            new=AsyncMock(return_value=workers),
        ):
            result = await mock_mcp._tools["get_readiness"]()

        assert result["workers"] == workers


# =============================================================================
# mahavishnu_mcp_list_tools
# =============================================================================


class TestMcpListTools:
    """Tests for the mahavishnu_mcp_list_tools tool."""

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
        result = await mcp._tools["mahavishnu_mcp_list_tools"]()
        assert result["status"] == "success"
        assert result["total_tools"] == 1
        assert result["tools"][0]["name"] == "alpha"
        assert result["tools"][0]["version"] == "1.0"

    async def test_empty_tool_list(self):
        """No tools should return zero counts."""
        mcp = self._make_mock_mcp()
        mcp.list_tools = AsyncMock(return_value=[])
        register_health_tools(mcp)
        result = await mcp._tools["mahavishnu_mcp_list_tools"]()
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
# mahavishnu_mcp_test_connection
# =============================================================================


class TestMcpTestConnection:
    """Tests for the mahavishnu_mcp_test_connection tool."""

    async def test_connected(self, registered_mcp, mock_health_check_result):
        """Healthy result should report connected=True."""
        with patch(
            "mahavishnu.core.health.HealthChecker.check",
            new=AsyncMock(return_value=mock_health_check_result),
        ):
            result = await registered_mcp._tools["mahavishnu_mcp_test_connection"](
                service_name="svc"
            )
        assert result["status"] == "ok"
        assert result["connected"] is True
        assert result["service_name"] == "svc"

    async def test_not_connected(self, registered_mcp, mock_unhealthy_result):
        """Unhealthy result should report connected=False."""
        with patch(
            "mahavishnu.core.health.HealthChecker.check",
            new=AsyncMock(return_value=mock_unhealthy_result),
        ):
            result = await registered_mcp._tools["mahavishnu_mcp_test_connection"](
                service_name="svc"
            )
        assert result["status"] == "unhealthy"
        assert result["connected"] is False
        assert result["error"] == "connection refused"

    async def test_custom_health_path(self, registered_mcp, mock_health_check_result):
        """health_path should be honored."""
        with patch(
            "mahavishnu.core.health.HealthChecker.check",
            new=AsyncMock(return_value=mock_health_check_result),
        ):
            result = await registered_mcp._tools["mahavishnu_mcp_test_connection"](
                service_name="svc", health_path="/ready"
            )
        assert "/ready" in result["url"]


# =============================================================================
# mahavishnu_mcp_get_metrics
# =============================================================================


class TestMcpGetMetrics:
    """Tests for the mahavishnu_mcp_get_metrics tool."""

    async def test_returns_metrics(self):
        """Should return metrics snapshot."""
        mcp = TestMcpListTools._make_mock_mcp()
        mcp.list_tools = AsyncMock(return_value=[])
        register_health_tools(mcp)
        result = await mcp._tools["mahavishnu_mcp_get_metrics"]()
        assert result["status"] == "success"
        assert "metric_families" in result
        assert "metrics_text" in result
        assert "metrics_preview" in result
        assert isinstance(result["metrics_preview"], list)


# =============================================================================
# App-aware registration
# =============================================================================


class TestRegistrationWithApp:
    """Tests for register_health_tools with an app instance."""

    def test_server_name_from_app_config(self, mock_mcp):
        """When an app with config.server_name is provided, the tools should use it."""
        app = MagicMock()
        app.config.server_name = "my-custom-server"
        app.config.health.dependencies = {}
        register_health_tools(mock_mcp, app=app)
        assert "mahavishnu_mcp_list_tools" in mock_mcp._tools

    def test_default_server_name(self, mock_mcp):
        """When no app is provided, default to 'mahavishnu'."""
        register_health_tools(mock_mcp, app=None)
        assert "mahavishnu_mcp_list_tools" in mock_mcp._tools


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

    def test_liveness_response_model(self):
        """HealthResponse still carries the liveness envelope shape."""
        response = HealthResponse(
            status=HealthStatus.OK,
            service="mahavishnu",
            version="1.0",
            uptime_seconds=1.0,
        )
        assert response.service == "mahavishnu"

    def test_ready_response_model(self):
        """ReadyResponse still carries the readiness envelope shape."""
        response = ReadyResponse(
            ready=True,
            service="mahavishnu",
            dependencies={},
            checks={},
        )
        assert response.ready is True
