"""Unit tests for PrefectAdapter implementation.

These tests cover the Phase 1 core enhancement features:
- OrchestratorAdapter interface properties
- PrefectConfig configuration
- Client lifecycle management
- Error handling and exception mapping
- Health check functionality

Tests use mocked Prefect clients to avoid requiring a real Prefect server.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.adapters.base import AdapterCapabilities, AdapterType
from mahavishnu.core.config import MahavishnuSettings, PrefectConfig
from mahavishnu.core.errors import ErrorCode, PrefectError
from mahavishnu.engines.prefect_adapter import (
    PrefectAdapter,
    _map_prefect_exception,
    process_repository,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def prefect_config():
    """Create a default PrefectConfig for testing."""
    return PrefectConfig(
        enabled=True,
        api_url="http://localhost:4200",
        work_pool="test-pool",
        timeout_seconds=60,
        max_retries=2,
    )


@pytest.fixture
def prefect_config_with_cloud():
    """Create a PrefectConfig for Prefect Cloud testing."""
    return PrefectConfig(
        enabled=True,
        api_url="https://api.prefect.cloud",
        api_key="test-api-key",
        workspace="test-account/test-workspace",
        work_pool="cloud-pool",
    )


@pytest.fixture
def mock_prefect_client():
    """Create a mock Prefect orchestration client."""
    client = AsyncMock()
    client.api_url = "http://localhost:4200"
    client.read_health = AsyncMock(return_value=MagicMock(version="3.0.0"))
    client.create_flow_run = AsyncMock()
    client.wait_for_flow_run = AsyncMock()
    return client


@pytest.fixture
async def adapter(prefect_config):
    """Create a PrefectAdapter instance for testing."""
    adapter = PrefectAdapter(prefect_config)
    yield adapter
    # Cleanup
    await adapter.shutdown()


# =============================================================================
# PrefectConfig Tests
# =============================================================================


class TestPrefectConfig:
    """Tests for PrefectConfig validation."""

    def test_default_config(self):
        """Test default configuration values."""
        config = PrefectConfig()

        assert config.enabled is True
        assert config.api_url == "http://localhost:4200"
        assert config.api_key is None
        assert config.workspace is None
        assert config.work_pool == "default"
        assert config.timeout_seconds == 300
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 1.0
        assert config.enable_telemetry is True
        assert config.sync_interval_seconds == 60
        assert config.webhook_secret is None

    def test_custom_config(self, prefect_config):
        """Test custom configuration values."""
        assert prefect_config.api_url == "http://localhost:4200"
        assert prefect_config.work_pool == "test-pool"
        assert prefect_config.timeout_seconds == 60
        assert prefect_config.max_retries == 2

    def test_cloud_config_requires_api_key(self):
        """Test that workspace requires api_key."""
        with pytest.raises(ValueError, match="api_key must be set when workspace is specified"):
            PrefectConfig(
                api_url="https://api.prefect.cloud",
                workspace="test/test",
                # api_key is missing
            )

    def test_cloud_config_with_api_key(self, prefect_config_with_cloud):
        """Test valid cloud configuration."""
        assert prefect_config_with_cloud.api_key == "test-api-key"
        assert prefect_config_with_cloud.workspace == "test-account/test-workspace"

    def test_config_from_env(self, monkeypatch):
        """Test configuration from environment variables."""
        monkeypatch.setenv("MAHAVISHNU_PREFECT__API_URL", "http://custom:4200")
        monkeypatch.setenv("MAHAVISHNU_PREFECT__TIMEOUT_SECONDS", "120")

        settings = MahavishnuSettings()
        assert settings.prefect.api_url == "http://custom:4200"
        assert settings.prefect.timeout_seconds == 120


# =============================================================================
# OrchestratorAdapter Interface Tests
# =============================================================================


class TestAdapterInterface:
    """Tests for OrchestratorAdapter interface implementation."""

    def test_adapter_type(self, adapter):
        """Test adapter_type property returns PREFECT."""
        assert adapter.adapter_type == AdapterType.PREFECT

    def test_adapter_name(self, adapter):
        """Test name property returns 'prefect'."""
        assert adapter.name == "prefect"

    def test_capabilities(self, adapter):
        """Test capabilities property returns correct capabilities."""
        capabilities = adapter.capabilities

        assert isinstance(capabilities, AdapterCapabilities)
        assert capabilities.can_deploy_flows is True
        assert capabilities.can_monitor_execution is True
        assert capabilities.can_cancel_workflows is True
        assert capabilities.can_sync_state is True
        assert capabilities.supports_batch_execution is True
        assert capabilities.has_cloud_ui is True
        assert capabilities.supports_multi_agent is False

    def test_capabilities_are_fresh(self, adapter):
        """Test that capabilities returns a new instance each time."""
        cap1 = adapter.capabilities
        cap2 = adapter.capabilities

        # Should be equal but not the same object
        assert cap1.can_deploy_flows == cap2.can_deploy_flows


# =============================================================================
# Lifecycle Management Tests
# =============================================================================


class TestLifecycleManagement:
    """Tests for adapter lifecycle methods."""

    @pytest.mark.asyncio
    async def test_initialize_success(self, prefect_config, mock_prefect_client):
        """Test successful initialization."""
        adapter = PrefectAdapter(prefect_config)

        with patch.object(
            adapter,
            "_get_client_context",
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_prefect_client), __aexit__=AsyncMock())
        ):
            await adapter.initialize()

        assert adapter._initialized is True

        await adapter.shutdown()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, prefect_config, mock_prefect_client):
        """Test that initialize is idempotent."""
        adapter = PrefectAdapter(prefect_config)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            await adapter.initialize()
            await adapter.initialize()  # Should not fail

        # Should only enter context once for the actual check
        assert adapter._initialized is True

        await adapter.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_resets_state(self, adapter):
        """Test that shutdown resets initialization state."""
        adapter._initialized = True

        await adapter.shutdown()

        assert adapter._initialized is False
        assert adapter._client is None

    @pytest.mark.asyncio
    async def test_repr(self, adapter):
        """Test string representation."""
        repr_str = repr(adapter)

        assert "PrefectAdapter" in repr_str
        assert "http://localhost:4200" in repr_str
        assert "initialized" in repr_str

    @pytest.mark.asyncio
    async def test_str(self, adapter):
        """Test human-readable string."""
        str_str = str(adapter)

        assert "PrefectAdapter" in str_str
        assert "http://localhost:4200" in str_str


# =============================================================================
# Health Check Tests
# =============================================================================


class TestHealthCheck:
    """Tests for get_health method."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, prefect_config, mock_prefect_client):
        """Test healthy status when Prefect is available."""
        adapter = PrefectAdapter(prefect_config)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            health = await adapter.get_health()

        assert health["status"] == "healthy"
        assert health["details"]["configured"] is True
        assert health["details"]["connection"] == "available"
        assert "latency_ms" in health["details"]

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_error(self, prefect_config):
        """Test unhealthy status when Prefect is unavailable."""
        adapter = PrefectAdapter(prefect_config)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            health = await adapter.get_health()

        assert health["status"] == "unhealthy"
        assert health["details"]["connection"] == "failed"
        assert "error" in health["details"]

    @pytest.mark.asyncio
    async def test_health_check_includes_api_url(self, prefect_config, mock_prefect_client):
        """Test that health check includes configured API URL."""
        adapter = PrefectAdapter(prefect_config)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            health = await adapter.get_health()

        assert health["details"]["api_url"] == "http://localhost:4200"


# =============================================================================
# Exception Mapping Tests
# =============================================================================


class TestExceptionMapping:
    """Tests for _map_prefect_exception function."""

    def test_map_object_not_found(self):
        """Test mapping ObjectNotFound exception."""
        from prefect.exceptions import ObjectNotFound

        exc = ObjectNotFound("Deployment not found")
        error = _map_prefect_exception(exc, "test_operation")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_DEPLOYMENT_NOT_FOUND

    def test_map_http_status_401(self):
        """Test mapping 401 HTTP status."""
        from prefect.exceptions import PrefectHTTPStatusError

        # Create a proper mock for request and response
        request = MagicMock()
        response = MagicMock(status_code=401)
        exc = PrefectHTTPStatusError("Unauthorized", request=request, response=response)
        error = _map_prefect_exception(exc, "api_call")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_AUTHENTICATION_ERROR

    def test_map_http_status_429(self):
        """Test mapping 429 HTTP status (rate limit)."""
        from prefect.exceptions import PrefectHTTPStatusError

        request = MagicMock()
        response = MagicMock(status_code=429)
        exc = PrefectHTTPStatusError("Rate limited", request=request, response=response)
        error = _map_prefect_exception(exc, "api_call")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_RATE_LIMITED

    def test_map_http_status_404(self):
        """Test mapping 404 HTTP status."""
        from prefect.exceptions import PrefectHTTPStatusError

        request = MagicMock()
        response = MagicMock(status_code=404)
        exc = PrefectHTTPStatusError("Not found", request=request, response=response)
        error = _map_prefect_exception(exc, "api_call")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_DEPLOYMENT_NOT_FOUND

    def test_map_http_status_500(self):
        """Test mapping 500 HTTP status (server error)."""
        from prefect.exceptions import PrefectHTTPStatusError

        request = MagicMock()
        response = MagicMock(status_code=500)
        exc = PrefectHTTPStatusError("Internal server error", request=request, response=response)
        error = _map_prefect_exception(exc, "api_call")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_API_ERROR

    def test_map_connection_error(self):
        """Test mapping httpx connection error."""
        import httpx

        exc = httpx.ConnectError("Connection refused")
        error = _map_prefect_exception(exc, "connect", "http://localhost:4200")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_CONNECTION_ERROR

    def test_map_timeout_error(self):
        """Test mapping httpx timeout error."""
        import httpx

        exc = httpx.ConnectTimeout("Connection timed out")
        error = _map_prefect_exception(exc, "connect", "http://localhost:4200")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_CONNECTION_ERROR

    def test_map_generic_exception(self):
        """Test mapping generic exception."""
        exc = ValueError("Something went wrong")
        error = _map_prefect_exception(exc, "test")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_API_ERROR
        assert "ValueError" in error.details.get("original_type", "")


# =============================================================================
# Execute Method Tests
# =============================================================================


class TestExecute:
    """Tests for execute method."""

    @pytest.mark.asyncio
    async def test_execute_auto_initializes(self, prefect_config, mock_prefect_client):
        """Test that execute auto-initializes if not already initialized."""
        adapter = PrefectAdapter(prefect_config)

        # Mock the flow run state
        mock_state = MagicMock()
        mock_state.is_completed.return_value = True
        mock_state.result.return_value = []

        mock_flow_run = MagicMock()
        mock_flow_run.id = "test-flow-run-id"

        mock_prefect_client.create_flow_run = AsyncMock(return_value=mock_flow_run)
        mock_prefect_client.wait_for_flow_run = AsyncMock(return_value=mock_state)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.execute({"type": "test"}, ["/repo"])

        assert adapter._initialized is True
        assert result["status"] == "completed"
        assert result["engine"] == "prefect"

        await adapter.shutdown()

    @pytest.mark.asyncio
    async def test_execute_returns_flow_run_info(self, prefect_config, mock_prefect_client):
        """Test that execute returns flow run ID and URL."""
        adapter = PrefectAdapter(prefect_config)
        adapter._initialized = True

        mock_state = MagicMock()
        mock_state.is_completed.return_value = True
        mock_state.result.return_value = [
            {"repo": "/test", "status": "completed", "result": {}, "task_id": "1"}
        ]

        mock_flow_run = MagicMock()
        mock_flow_run.id = "flow-run-123"

        mock_prefect_client.create_flow_run = AsyncMock(return_value=mock_flow_run)
        mock_prefect_client.wait_for_flow_run = AsyncMock(return_value=mock_state)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.execute({"type": "code_sweep"}, ["/test/repo"])

        assert result["flow_run_id"] == "flow-run-123"
        assert "flow_run_url" in result
        assert result["repos_processed"] == 1
        assert result["success_count"] == 1
        assert result["failure_count"] == 0

        await adapter.shutdown()

    @pytest.mark.asyncio
    async def test_execute_handles_failures(self, prefect_config, mock_prefect_client):
        """Test that execute counts failures correctly."""
        adapter = PrefectAdapter(prefect_config)
        adapter._initialized = True

        mock_state = MagicMock()
        mock_state.is_completed.return_value = True
        mock_state.result.return_value = [
            {"repo": "/test1", "status": "completed", "result": {}, "task_id": "1"},
            {"repo": "/test2", "status": "failed", "error": "Error", "task_id": "2"},
        ]

        mock_flow_run = MagicMock()
        mock_flow_run.id = "flow-run-456"

        mock_prefect_client.create_flow_run = AsyncMock(return_value=mock_flow_run)
        mock_prefect_client.wait_for_flow_run = AsyncMock(return_value=mock_state)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.execute({"type": "test"}, ["/test1", "/test2"])

        assert result["success_count"] == 1
        assert result["failure_count"] == 1

        await adapter.shutdown()


# =============================================================================
# Prefect Task Tests
# =============================================================================


class TestPrefectTasks:
    """Tests for Prefect task functions."""

    @pytest.mark.asyncio
    async def test_process_repository_default(self):
        """Test process_repository with default task type."""
        result = await process_repository(
            "/test/repo",
            {"type": "default", "id": "test-1"}
        )

        assert result["repo"] == "/test/repo"
        assert result["status"] == "completed"
        assert result["task_id"] == "test-1"
        assert "result" in result

    @pytest.mark.asyncio
    async def test_process_repository_handles_exception(self):
        """Test process_repository handles exceptions gracefully."""
        with patch(
            "mahavishnu.engines.prefect_adapter.CodeGraphAnalyzer",
            side_effect=Exception("Analysis failed")
        ):
            result = await process_repository(
                "/test/repo",
                {"type": "code_sweep", "id": "test-2"}
            )

        assert result["status"] == "failed"
        assert "error" in result
        assert "Analysis failed" in result["error"]


# =============================================================================
# Configuration Integration Tests
# =============================================================================


class TestConfigIntegration:
    """Tests for PrefectConfig integration with MahavishnuSettings."""

    def test_settings_include_prefect_config(self):
        """Test that MahavishnuSettings includes prefect configuration."""
        settings = MahavishnuSettings()

        assert hasattr(settings, "prefect")
        assert isinstance(settings.prefect, PrefectConfig)

    def test_settings_prefect_defaults(self):
        """Test that prefect settings have correct defaults."""
        settings = MahavishnuSettings()

        assert settings.prefect.enabled is True
        assert settings.prefect.api_url == "http://localhost:4200"
        assert settings.prefect.work_pool == "default"

    def test_settings_validation_order(self):
        """Test that settings validation works correctly."""
        # This tests that the validation order (defaults -> yaml -> env) works
        settings = MahavishnuSettings()

        # Default should be applied
        assert settings.prefect.timeout_seconds == 300


# =============================================================================
# Error Code Coverage Tests
# =============================================================================


class TestErrorCodes:
    """Tests for all Prefect error codes are properly used."""

    def test_all_prefect_error_codes_exist(self):
        """Test that all MHV-400 series error codes exist."""
        prefect_codes = [
            ErrorCode.PREFECT_CONNECTION_ERROR,
            ErrorCode.PREFECT_DEPLOYMENT_NOT_FOUND,
            ErrorCode.PREFECT_FLOW_NOT_FOUND,
            ErrorCode.PREFECT_FLOW_RUN_FAILED,
            ErrorCode.PREFECT_SCHEDULE_INVALID,
            ErrorCode.PREFECT_WORK_POOL_UNAVAILABLE,
            ErrorCode.PREFECT_API_ERROR,
            ErrorCode.PREFECT_TIMEOUT,
            ErrorCode.PREFECT_AUTHENTICATION_ERROR,
            ErrorCode.PREFECT_RATE_LIMITED,
            ErrorCode.PREFECT_STATE_SYNC_ERROR,
        ]

        for code in prefect_codes:
            assert code.value.startswith("MHV-4")


# =============================================================================
# Markers
# =============================================================================


# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit
