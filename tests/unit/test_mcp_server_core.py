"""Tests for FastMCPServer core functionality in mahavishnu.mcp.server_core.

Covers initialization, tool registration, telemetry middleware,
HTTP health endpoint registration, lifecycle, and tool-registration metrics.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_common.fastmcp import FastMCP
import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.mcp.server_core import (
    FastMCPServer,
    run_server,
)
from monitoring.metrics import mcp_tools_registered

# =============================================================================
# Fixtures
# =============================================================================


def _make_settings(**overrides: Any) -> MahavishnuSettings:
    """Build a MahavishnuSettings instance with safe defaults for tests."""
    defaults: dict[str, Any] = {
        "server_name": "Test Server",
        "observability_enabled": False,
        "terminal_enabled": False,
        "pools": {"enabled": False},
        "workers": {"enabled": False},
        "otel_storage": {"enabled": False},
    }
    defaults.update(overrides)
    return MahavishnuSettings(**defaults)


@pytest.fixture
def mock_settings() -> MahavishnuSettings:
    """Create baseline mock settings for server core tests."""
    return _make_settings()


@pytest.fixture
def mock_app(mock_settings: MahavishnuSettings) -> MagicMock:
    """Create a MagicMock spec'd to MahavishnuApp for FastMCPServer init."""
    app = MagicMock(spec=MahavishnuApp)
    app.config = mock_settings
    app.get_repos = MagicMock(return_value=[])
    app.is_healthy = MagicMock(return_value=True)
    app.adapters = {}
    app.workflow_state_manager = MagicMock()
    app.rbac_manager = MagicMock()
    app.observability = MagicMock()
    app.opensearch_integration = MagicMock()
    app.error_recovery_manager = MagicMock()
    app.monitoring_service = MagicMock()
    app.pool_manager = None
    app.worktree_coordinator = None
    return app


@pytest.fixture(autouse=True)
def reset_all_metrics() -> None:
    """Reset all prometheus metric values to ensure test isolation.

    The parent conftest's clean_prometheus_registry only strips prefect
    collectors, missing the mahavishnu monitoring metrics. Multiple
    test files increment these counters; without this reset, tests
    that depend on counter initial values fail in the full suite.
    """
    from prometheus_client import REGISTRY

    for collector in list(REGISTRY._collector_to_names.keys()):
        try:
            collector._metrics.clear()
        except AttributeError:
            pass  # some collectors (like gauges) may not have _metrics
    yield


@pytest.fixture
def server(mock_app: MagicMock) -> FastMCPServer:
    """Create a FastMCPServer bound to a mocked MahavishnuApp."""
    return FastMCPServer(app=mock_app)


# =============================================================================
# FastMCPServer.__init__ Tests
# =============================================================================


class TestFastMCPServerInit:
    """Test suite for FastMCPServer.__init__ behavior."""

    def test_init_with_explicit_app(self, mock_app: MagicMock) -> None:
        """Server should accept and store an explicit app instance."""
        with patch("mahavishnu.mcp.server_core.get_auth_from_config"):
            srv = FastMCPServer(app=mock_app)

        assert srv.app is mock_app
        assert isinstance(srv.server, FastMCP)

    def test_init_creates_mahavishnu_app_when_app_is_none(self) -> None:
        """Server should auto-construct MahavishnuApp when app=None."""
        cfg = _make_settings()
        with (
            patch("mahavishnu.mcp.server_core.MahavishnuApp") as mock_app_cls,
            patch("mahavishnu.mcp.server_core.get_auth_from_config"),
        ):
            mock_instance = MagicMock()
            mock_instance.config = cfg
            mock_app_cls.return_value = mock_instance

            FastMCPServer(app=None, config=cfg)

            mock_app_cls.assert_called_once_with(cfg)

    def test_init_uses_explicit_config(self) -> None:
        """Server should pass provided config to MahavishnuApp."""
        cfg = _make_settings(server_name="Explicit Config")
        with (
            patch("mahavishnu.mcp.server_core.MahavishnuApp") as mock_app_cls,
            patch("mahavishnu.mcp.server_core.get_auth_from_config"),
        ):
            mock_instance = MagicMock()
            mock_instance.config = cfg
            mock_app_cls.return_value = mock_instance

            srv = FastMCPServer(app=None, config=cfg)

            assert srv.app.config.server_name == "Explicit Config"
            mock_app_cls.assert_called_once_with(cfg)

    def test_init_tracks_registered_tool_count(self, server: FastMCPServer) -> None:
        """Server should expose a tool count attribute starting at zero or more."""
        assert hasattr(server, "_registered_tool_count")
        assert isinstance(server._registered_tool_count, int)
        assert server._registered_tool_count >= 0

    def test_init_with_tracing_disabled_skips_middleware(self, mock_app: MagicMock) -> None:
        """Telemetry middleware should NOT be added when tracing is disabled."""
        mock_app.config.observability = MagicMock(tracing_enabled=False)

        with (
            patch("mahavishnu.mcp.server_core.get_auth_from_config"),
            patch.object(FastMCP, "add_middleware") as mock_add,
        ):
            FastMCPServer(app=mock_app)

            mock_add.assert_not_called()

    def test_init_with_tracing_enabled_adds_middleware(self, mock_app: MagicMock) -> None:
        """Telemetry middleware should be added when tracing is enabled."""
        # Import via mahavishnu.mcp.server_core (not mcp_common.server.telemetry)
        # because test_fastmcp_version.py evicts mcp_common from sys.modules.
        # Re-fetching from the already-loaded mahavishnu module namespace gives
        # us the SAME class object the production code uses to build the
        # middleware, so isinstance() matches after the eviction.
        from mahavishnu.mcp.server_core import FastMCPOpenTelemetryMiddleware

        mock_app.config.observability = MagicMock(tracing_enabled=True, environment="testing")

        # Explicit patcher.start()/stop() instead of parenthesized
        # ``with`` blocks — pytest's parenthesized-with handling under
        # xdist can leave the patched attribute unbound, so the
        # ``FastMCPServer(app=mock_app)`` call below bypasses the
        # patch and ``mock_add.called`` stays False.
        auth_patcher = patch("mahavishnu.mcp.server_core.get_auth_from_config")
        add_patcher = patch.object(FastMCP, "add_middleware")
        auth_patcher.start()
        mock_add = add_patcher.start()
        try:
            FastMCPServer(app=mock_app)

            # Confirm middleware is an instance of the OTel middleware
            assert mock_add.called
            middleware_arg = mock_add.call_args.args[0]
            assert isinstance(middleware_arg, FastMCPOpenTelemetryMiddleware)
        finally:
            add_patcher.stop()
            auth_patcher.stop()


# =============================================================================
# _register_telemetry_middleware Tests
# =============================================================================


class TestRegisterTelemetryMiddleware:
    """Test suite for _register_telemetry_middleware."""

    def test_middleware_not_added_when_observability_missing(self, server: FastMCPServer) -> None:
        """No middleware when observability attribute is None."""
        server.app.config.observability = None

        with patch.object(server.server, "add_middleware") as mock_add:
            server._register_telemetry_middleware()
            mock_add.assert_not_called()

    def test_middleware_not_added_when_tracing_disabled(self, server: FastMCPServer) -> None:
        """No middleware when observability.tracing_enabled is False."""
        server.app.config.observability = MagicMock(tracing_enabled=False)

        with patch.object(server.server, "add_middleware") as mock_add:
            server._register_telemetry_middleware()
            mock_add.assert_not_called()

    def test_middleware_added_when_tracing_enabled(self, server: FastMCPServer) -> None:
        """Middleware is added with correct service name and environment."""
        # Import via mahavishnu.mcp.server_core (not mcp_common.server.telemetry)
        # because test_fastmcp_version.py evicts mcp_common from sys.modules.
        # Re-fetching from the already-loaded mahavishnu module namespace gives
        # us the SAME class object the production code uses to build the
        # middleware, so isinstance() matches after the eviction.
        from mahavishnu.mcp.server_core import FastMCPOpenTelemetryMiddleware

        server.app.config.observability = MagicMock(tracing_enabled=True, environment="ci")
        server.app.config.server_name = "test-server"

        with patch.object(server.server, "add_middleware") as mock_add:
            server._register_telemetry_middleware()

            mock_add.assert_called_once()
            middleware = mock_add.call_args.args[0]
            assert isinstance(middleware, FastMCPOpenTelemetryMiddleware)
            assert middleware.service_name == "test-server"
            assert middleware.environment == "ci"

    def test_middleware_defaults_environment_to_production(self, server: FastMCPServer) -> None:
        """When no environment is configured, fallback to 'production'."""
        server.app.config.observability = MagicMock(tracing_enabled=True, environment=None)
        server.app.config.server_name = "fallback-server"

        with patch.object(server.server, "add_middleware") as mock_add:
            server._register_telemetry_middleware()

            middleware = mock_add.call_args.args[0]
            assert middleware.environment == "production"


# =============================================================================
# _register_tools and tool-registration metrics
# =============================================================================


class TestRegisterTools:
    """Test suite for tool registration and count tracking."""

    @pytest.mark.asyncio
    async def test_register_tools_populates_count(self, server: FastMCPServer) -> None:
        """Initial registration should yield a non-zero tool count."""
        # Force re-registration to assert count was at zero before
        server._registered_tool_count = 0
        server._register_tools()
        assert server._registered_tool_count > 0

    @pytest.mark.asyncio
    async def test_tool_count_matches_registered_tools(self, server: FastMCPServer) -> None:
        """The internal counter should match FastMCP's reported tool list."""
        tools = await server.server.list_tools()
        tool_names = {t.name for t in tools}
        assert len(tool_names) == server._registered_tool_count

    @pytest.mark.asyncio
    async def test_known_core_tools_are_registered(self, server: FastMCPServer) -> None:
        """Critical core tools should be present in the FastMCP registry."""
        tools = await server.server.list_tools()
        tool_names = {t.name for t in tools}

        expected = {
            "list_repos",
            "trigger_workflow",
            "get_workflow_status",
            "list_workflows",
            "cancel_workflow",
            "create_user",
            "check_permission",
            "get_health",
            "list_adapters",
            "get_observability_metrics",
            "discover_tools",
            "get_tool_versions",
        }
        missing = expected - tool_names
        assert not missing, f"Missing tools: {missing}"

    def test_metric_gauge_matches_count(self, server: FastMCPServer) -> None:
        """mcp_tools_registered gauge should reflect the current count."""
        server._update_registered_tool_metrics()
        gauge_value = mcp_tools_registered.labels(server=server.app.config.server_name)
        assert gauge_value._value.get() == server._registered_tool_count

    def test_metric_gauge_uses_default_when_name_missing(self, mock_app: MagicMock) -> None:
        """Gauge label should fall back to 'mahavishnu' for empty/missing names."""
        mock_app.config.server_name = ""
        with patch("mahavishnu.mcp.server_core.get_auth_from_config"):
            srv = FastMCPServer(app=mock_app)

        srv._update_registered_tool_metrics()
        gauge_value = mcp_tools_registered.labels(server="mahavishnu")
        assert gauge_value._value.get() == srv._registered_tool_count

    @pytest.mark.asyncio
    async def test_get_health_returns_structured_content_when_app_is_healthy_async(
        self, mock_app: MagicMock
    ) -> None:
        """Regression: ``get_health`` must await ``app.is_healthy()``.

        Real ``MahavishnuApp.is_healthy`` is async, so the handler must await
        it.  Previously the call was unawaited, which placed a coroutine object
        into the response dict; FastMCP's ``pydantic_core.to_jsonable_python``
        then raised ``PydanticSerializationError`` and ``convert_result``
        dropped ``structured_content``.  With ``outputSchema`` still set on the
        tool, the MCP SDK normalizer raised
        ``Output validation error: outputSchema defined but no structured
        output returned``.

        This fixture mirrors the real async signature so the bug is caught.
        """

        # Mirror the real async signature: is_healthy is a coroutine function.
        async def fake_is_healthy() -> bool:
            return True

        async def fake_opensearch_health() -> dict[str, Any]:
            return {"status": "healthy"}

        async def fake_list_workflows(limit: int = 1) -> list[Any]:
            return []

        mock_app.is_healthy = fake_is_healthy
        mock_app.opensearch_integration.health_check = fake_opensearch_health
        mock_app.workflow_state_manager.list_workflows = fake_list_workflows
        mock_app.rbac_manager.roles = {"admin": MagicMock()}

        with patch("mahavishnu.mcp.server_core.get_auth_from_config"):
            srv = FastMCPServer(app=mock_app)

        # Use the FastMCP in-memory client to drive through the same
        # FastMCP + MCP SDK normalizer path that the live HTTP transport uses.
        from fastmcp import Client

        async with Client(srv.server) as client:
            tools = await client.list_tools()
            gh_tool = next(t for t in tools if t.name == "get_health")
            # Sanity: outputSchema is generated (the previous fix ensured this).
            assert gh_tool.outputSchema is not None

            result = await client.call_tool("get_health", {})

        # If is_healthy() was unawaited, structured_content would be missing
        # AND is_error would be True with the "outputSchema defined but no
        # structured output returned" message.  With the await in place, the
        # dict serializes cleanly.
        assert result.is_error is False, (
            f"get_health returned an error result: "
            f"{[c.text for c in result.content if hasattr(c, 'text')]}"
        )
        assert result.structured_content is not None
        assert result.structured_content.get("status") in {"healthy", "degraded"}


# =============================================================================
# HTTP health endpoint registration
# =============================================================================


class TestHealthEndpoint:
    """Test suite for the /health and /ready HTTP endpoints."""

    def test_health_endpoint_registered(self, server: FastMCPServer) -> None:
        """GET /health should be reachable on the underlying FastMCP ASGI app."""
        http_app = server.server.http_app()
        paths = {route.path for route in http_app.routes if hasattr(route, "path")}

        assert "/health" in paths

    def test_healthz_endpoint_registered(self, server: FastMCPServer) -> None:
        """GET /healthz should also be exposed for k8s-style health checks."""
        http_app = server.server.http_app()
        paths = {route.path for route in http_app.routes if hasattr(route, "path")}

        assert "/healthz" in paths

    def test_metrics_endpoint_registered(self, server: FastMCPServer) -> None:
        """GET /metrics should be exposed for Prometheus scrapers."""
        http_app = server.server.http_app()
        paths = {route.path for route in http_app.routes if hasattr(route, "path")}

        assert "/metrics" in paths


# =============================================================================
# Lifecycle Tests
# =============================================================================


class TestLifecycle:
    """Test suite for FastMCPServer.start / stop / register_worktree_tools."""

    @pytest.mark.asyncio
    async def test_start_invokes_run_http_async(self, server: FastMCPServer) -> None:
        """start() should call run_http_async with the provided host/port."""
        server.server.run_http_async = AsyncMock()

        await server.start(host="127.0.0.1", port=4001)

        server.server.run_http_async.assert_awaited_once_with(
            host="127.0.0.1",
            port=4001,
            uvicorn_config={"timeout_graceful_shutdown": 30},
        )

    @pytest.mark.asyncio
    async def test_start_uses_default_host_and_port(self, server: FastMCPServer) -> None:
        """start() should default to 127.0.0.1:3000 when not specified."""
        server.server.run_http_async = AsyncMock()

        await server.start()

        server.server.run_http_async.assert_awaited_once_with(
            host="127.0.0.1",
            port=3000,
            uvicorn_config={"timeout_graceful_shutdown": 30},
        )

    @pytest.mark.asyncio
    async def test_stop_is_noop_when_mcp_client_absent(self, server: FastMCPServer) -> None:
        """stop() should be a no-op when server.mcp_client is not set.

        Since mcpretentious removal (2026-08-12), the legacy McpretentiousMCPClient
        wrapper is gone, so FastMCPServer no longer pre-populates ``mcp_client``.
        The lifecycle helper guards with ``hasattr`` so stop() is silent.
        """
        # No mcp_client attribute is set on the server.
        assert not hasattr(server, "mcp_client") or server.mcp_client is None

        # Should NOT raise.
        await server.stop()

    @pytest.mark.asyncio
    async def test_stop_invokes_client_stop_when_present(
        self, mock_app: MagicMock
    ) -> None:
        """stop() should call _client.stop when mcp_client IS configured."""
        mock_client = MagicMock()
        mock_client._client.stop = AsyncMock()
        # Inject mcp_client only for this test.
        with patch(
            "mahavishnu.mcp.server_core.get_auth_from_config",
        ):
            server = FastMCPServer(app=mock_app)
        server.mcp_client = mock_client

        await server.stop()

        mock_client._client.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_worktree_tools_noop_when_coordinator_missing(
        self, server: FastMCPServer
    ) -> None:
        """register_worktree_tools should be a no-op when coordinator is None."""
        server.app.worktree_coordinator = None

        # Should not raise and should not register anything new
        await server.register_worktree_tools()


# =============================================================================
# run_server helper
# =============================================================================


class TestRunServerHelper:
    """Test the module-level run_server coroutine."""

    @pytest.mark.asyncio
    async def test_run_server_constructs_and_starts(self) -> None:
        """run_server() should build a FastMCPServer and call start()."""
        with patch("mahavishnu.mcp.server_core.FastMCPServer") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.start = AsyncMock()
            mock_cls.return_value = mock_instance

            await run_server(config=None)

            mock_cls.assert_called_once()
            mock_instance.start.assert_awaited_once()


# =============================================================================
# Tool-handler wrapping
# =============================================================================


class TestToolHandlerWrapping:
    """Test suite for _wrap_tool_handler and _classify_tool_result."""

    @pytest.mark.asyncio
    async def test_async_wrapper_records_success_metric(self, server: FastMCPServer) -> None:
        """An async tool returning a normal value should be classified as success."""
        from monitoring.metrics import mcp_tool_calls_total

        async def my_tool() -> dict[str, str]:
            return {"hello": "world"}

        wrapped = server._wrap_tool_handler(my_tool)
        result = await wrapped()
        assert result == {"hello": "world"}

        counter = mcp_tool_calls_total.labels(tool_name="my_tool", status="success")
        assert counter._value.get() >= 1

    @pytest.mark.asyncio
    async def test_async_wrapper_records_error_metric(self, server: FastMCPServer) -> None:
        """An async tool that raises should be classified as error."""
        from monitoring.metrics import mcp_tool_calls_total

        async def failing_tool() -> None:
            raise RuntimeError("nope")

        wrapped = server._wrap_tool_handler(failing_tool)
        with pytest.raises(RuntimeError, match="nope"):
            await wrapped()

        counter = mcp_tool_calls_total.labels(tool_name="failing_tool", status="error")
        assert counter._value.get() >= 1

    def test_classify_tool_result_with_error_key(self, server: FastMCPServer) -> None:
        """A dict containing an 'error' key should be classified as 'error'."""
        assert server._classify_tool_result({"error": "bad"}) == "error"
        assert server._classify_tool_result({"status": "error"}) == "error"
        assert server._classify_tool_result({"status": "failed"}) == "error"
        assert server._classify_tool_result({"status": "success"}) == "success"
        assert server._classify_tool_result({"hello": "world"}) == "success"
        # Non-dict inputs are always 'success'
        assert server._classify_tool_result("plain string") == "success"
        assert server._classify_tool_result(None) == "success"

    def test_async_wrapper_preserves_original_annotations_and_wrapped(
        self, server: FastMCPServer
    ) -> None:
        """Async wrapper must keep __wrapped__ and __annotations__ from the original.

        Regression for get_health: FastMCP builds the output_schema from the wrapper's
        signature, so losing the return annotation causes 'outputSchema defined but
        no structured output returned' validation errors downstream.
        """
        import inspect

        async def get_health() -> dict[str, Any]:
            return {"status": "healthy"}

        wrapped = server._wrap_tool_handler(get_health)

        # __wrapped__ points back to the original function so inspect.unwrap can
        # follow it to recover the real signature.
        assert wrapped.__wrapped__ is get_health

        # __annotations__ must be the original annotations (return type is
        # ``dict[str, Any]``), NOT the wrapper's ``-> Any``.
        assert wrapped.__annotations__ == get_health.__annotations__
        # The wrapper's own annotation was ``-> Any``; that MUST NOT leak into
        # the preserved annotations.
        assert wrapped.__annotations__["return"] != "Any"

        # inspect.signature on the wrapper should report the original return type
        # because inspect.unwrap follows __wrapped__ (and PEP 563 keeps annotations
        # as strings under ``from __future__ import annotations``).
        sig = inspect.signature(wrapped)
        assert sig.return_annotation == "dict[str, Any]"

    def test_sync_wrapper_preserves_original_annotations_and_wrapped(
        self, server: FastMCPServer
    ) -> None:
        """Sync wrapper must keep __wrapped__ and __annotations__ from the original."""
        import inspect

        def get_info() -> dict[str, str]:
            return {"k": "v"}

        wrapped = server._wrap_tool_handler(get_info)

        assert wrapped.__wrapped__ is get_info
        assert wrapped.__annotations__ == get_info.__annotations__
        assert wrapped.__annotations__["return"] != "Any"

        sig = inspect.signature(wrapped)
        assert sig.return_annotation == "dict[str, str]"


# =============================================================================
# Server identity and version
# =============================================================================


class TestServerIdentity:
    """Test suite for server name/version metadata."""

    def test_server_name(self, server: FastMCPServer) -> None:
        """The FastMCP server should be named 'Mahavishnu Orchestrator'."""
        assert server.server.name == "Mahavishnu Orchestrator"

    def test_server_has_version_string(self, server: FastMCPServer) -> None:
        """A version string should be set on the FastMCP instance."""
        assert isinstance(server.server.version, str)
        assert server.server.version
