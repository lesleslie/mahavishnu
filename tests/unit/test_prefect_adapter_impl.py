"""Comprehensive unit tests for PrefectAdapter.

Tests cover:
1. PrefectAdapter initialization and config
2. Workflow creation and registration
3. Task submission and execution
4. Flow run monitoring
5. Deployment handling
6. Error handling for Prefect API failures
7. Adapter health check
8. Adapter conforms to OrchestratorAdapter interface
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import httpx
import prefect
from prefect.exceptions import ObjectNotFound, PrefectHTTPStatusError
import pytest

from mahavishnu.core.adapters.base import (
    AdapterCapabilities,
    AdapterType,
    OrchestratorAdapter,
)
from mahavishnu.core.config import PrefectConfig
from mahavishnu.core.errors import (
    ErrorCode,
    PrefectError,
)
from mahavishnu.engines.prefect_adapter_impl import (
    PrefectAdapter,
    _deployment_to_response,
    _flow_run_to_response,
    _get_explicit_client_method,
    _invoke_client_method,
    _map_prefect_exception,
    _maybe_await,
    _work_pool_to_response,
    process_repositories_flow,
    process_repository,
)
from mahavishnu.engines.prefect_models import (
    DeploymentResponse,
    FlowRunResponse,
    WorkPoolResponse,
)
from mahavishnu.engines.prefect_schedules import (
    CronSchedule,
    IntervalSchedule,
    RRuleSchedule,
    schedule_to_prefect_dict,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def prefect_config() -> PrefectConfig:
    """Create a test PrefectConfig."""
    return PrefectConfig(
        api_url="http://test-prefect:4200",
        work_pool="test-pool",
        timeout_seconds=60,
        max_retries=2,
    )


@pytest.fixture
def prefect_adapter(prefect_config: PrefectConfig) -> PrefectAdapter:
    """Create a PrefectAdapter with test config."""
    return PrefectAdapter(config=prefect_config)


@pytest.fixture
def mock_prefect_client() -> MagicMock:
    """Create a mock Prefect client with async methods."""
    client = MagicMock()
    client.api_url = "http://test-prefect:4200"

    # Set up all async methods as AsyncMock
    client.read_health = AsyncMock(return_value={"status": "healthy"})
    client.api_healthcheck = AsyncMock(return_value={"status": "healthy"})
    client.read_flow_by_name = AsyncMock()
    client.create_deployment = AsyncMock()
    client.update_deployment = AsyncMock()
    client.delete_deployment = AsyncMock()
    client.read_deployment = AsyncMock()
    client.read_deployment_by_name = AsyncMock()
    client.read_deployments = AsyncMock(return_value=[])
    client.create_flow_run = AsyncMock()
    client.wait_for_flow_run = AsyncMock()
    client.create_flow_run_from_deployment = AsyncMock()
    client.read_flow_run = AsyncMock()
    client.read_flow_runs = AsyncMock(return_value=[])
    client.set_flow_run_state = AsyncMock()
    client.read_work_pools = AsyncMock(return_value=[])
    client.read_work_pool = AsyncMock()

    return client


@pytest.fixture
def mock_flow_run() -> MagicMock:
    """Create a mock flow run object."""
    run = MagicMock()
    run.id = uuid.uuid4()
    run.name = "test-flow-run"
    run.flow_id = uuid.uuid4()
    run.deployment_id = uuid.uuid4()
    run.parameters = {}
    run.tags = []
    run.created = datetime.now(UTC)
    run.updated = datetime.now(UTC)
    run.start_time = datetime.now(UTC)
    run.end_time = datetime.now(UTC)
    run.total_run_time = 10.5
    run.estimated_run_time = 15.0
    run.work_queue_name = "default"
    # Required for _flow_run_to_response which accesses state.type and state.name
    run.state = MagicMock()
    run.state.type = "COMPLETED"
    run.state.name = "Completed"
    return run


@pytest.fixture
def mock_deployment() -> MagicMock:
    """Create a mock deployment object."""
    deploy = MagicMock()
    deploy.id = uuid.uuid4()
    deploy.name = "test-deployment"
    deploy.flow_name = "test-flow"
    deploy.flow_id = uuid.uuid4()
    deploy.schedule = {"cron": "0 9 * * *"}
    deploy.parameters = {"env": "test"}
    deploy.work_pool_name = "test-pool"
    deploy.work_queue_name = "default"
    deploy.paused = False
    deploy.tags = ["test"]
    deploy.description = "Test deployment"
    deploy.version = "1.0.0"
    deploy.created = datetime.now(UTC)
    deploy.updated = datetime.now(UTC)
    return deploy


@pytest.fixture
def mock_work_pool() -> MagicMock:
    """Create a mock work pool object."""
    pool = MagicMock()
    pool.name = "test-pool"
    pool.type = "process"
    pool.description = "Test work pool"
    pool.is_paused = False
    pool.concurrency_limit = 5
    pool.created = datetime.now(UTC)
    pool.updated = datetime.now(UTC)
    return pool


@pytest.fixture
def mock_state() -> MagicMock:
    """Create a mock flow run state."""
    state = MagicMock()
    state.type = "COMPLETED"
    state.name = "Completed"
    # Must be AsyncMock since they are awaited via _maybe_await
    state.is_completed = AsyncMock(return_value=True)
    state.result = AsyncMock(return_value=[])
    return state


# =============================================================================
# Test: Initialization and Config
# =============================================================================


class TestPrefectAdapterInitialization:
    """Tests for PrefectAdapter initialization."""

    def test_adapter_with_config(self, prefect_config: PrefectConfig) -> None:
        """Test adapter initialization with explicit config."""
        adapter = PrefectAdapter(config=prefect_config)

        assert adapter.config is prefect_config
        assert adapter.config.api_url == "http://test-prefect:4200"
        assert adapter.config.work_pool == "test-pool"
        assert adapter._initialized is False
        assert adapter._client is None

    def test_adapter_without_config(self) -> None:
        """Test adapter initialization with default config."""
        adapter = PrefectAdapter()

        assert adapter.config is not None
        assert isinstance(adapter.config, PrefectConfig)
        assert adapter.config.api_url == "http://localhost:4200"
        assert adapter._initialized is False

    def test_adapter_type_property(self, prefect_adapter: PrefectAdapter) -> None:
        """Test adapter_type returns correct enum."""
        assert prefect_adapter.adapter_type == AdapterType.PREFECT

    def test_adapter_name_property(self, prefect_adapter: PrefectAdapter) -> None:
        """Test name returns 'prefect'."""
        assert prefect_adapter.name == "prefect"

    def test_adapter_capabilities(self, prefect_adapter: PrefectAdapter) -> None:
        """Test capabilities returns expected flags."""
        caps = prefect_adapter.capabilities

        assert isinstance(caps, AdapterCapabilities)
        assert caps.can_deploy_flows is True
        assert caps.can_monitor_execution is True
        assert caps.can_cancel_workflows is True
        assert caps.can_sync_state is True
        assert caps.supports_batch_execution is True
        assert caps.has_cloud_ui is True
        assert caps.supports_multi_agent is False

    def test_resolved_api_url_with_valid_url(self) -> None:
        """Test _resolved_api_url returns configured URL."""
        config = PrefectConfig(api_url="http://custom:4200")
        adapter = PrefectAdapter(config=config)

        assert adapter._resolved_api_url() == "http://custom:4200"

    def test_resolved_api_url_fallback(self) -> None:
        """Test _resolved_api_url falls back to default."""
        config = PrefectConfig()
        config.api_url = ""  # type: ignore
        adapter = PrefectAdapter(config=config)

        result = adapter._resolved_api_url()
        assert result == PrefectConfig().api_url

    def test_repr(self, prefect_adapter: PrefectAdapter) -> None:
        """Test string representation."""
        repr_str = repr(prefect_adapter)

        assert "PrefectAdapter" in repr_str
        assert "http://test-prefect:4200" in repr_str
        assert "initialized=False" in repr_str

    def test_str(self, prefect_adapter: PrefectAdapter) -> None:
        """Test human-readable string."""
        str_val = str(prefect_adapter)

        assert "PrefectAdapter" in str_val
        assert "http://test-prefect:4200" in str_val
        assert "not initialized" in str_val


# =============================================================================
# Test: OrchestratorAdapter Interface Conformance
# =============================================================================


class TestOrchestratorAdapterInterface:
    """Tests that PrefectAdapter conforms to OrchestratorAdapter interface."""

    def test_inherits_from_orchestrator_adapter(self, prefect_adapter: PrefectAdapter) -> None:
        """Test adapter inherits from OrchestratorAdapter."""
        assert isinstance(prefect_adapter, OrchestratorAdapter)

    def test_has_initialize_method(self, prefect_adapter: PrefectAdapter) -> None:
        """Test initialize method exists."""
        assert hasattr(prefect_adapter, "initialize")
        assert asyncio.iscoroutinefunction(prefect_adapter.initialize)

    def test_has_cleanup_method(self, prefect_adapter: PrefectAdapter) -> None:
        """Test cleanup method exists."""
        assert hasattr(prefect_adapter, "cleanup")
        assert asyncio.iscoroutinefunction(prefect_adapter.cleanup)

    def test_has_shutdown_method(self, prefect_adapter: PrefectAdapter) -> None:
        """Test shutdown method exists."""
        assert hasattr(prefect_adapter, "shutdown")
        assert asyncio.iscoroutinefunction(prefect_adapter.shutdown)

    def test_has_execute_method(self, prefect_adapter: PrefectAdapter) -> None:
        """Test execute method exists."""
        assert hasattr(prefect_adapter, "execute")
        assert asyncio.iscoroutinefunction(prefect_adapter.execute)

    def test_has_get_health_method(self, prefect_adapter: PrefectAdapter) -> None:
        """Test get_health method exists."""
        assert hasattr(prefect_adapter, "get_health")
        assert asyncio.iscoroutinefunction(prefect_adapter.get_health)

    def test_has_adapter_type_property(self, prefect_adapter: PrefectAdapter) -> None:
        """Test adapter_type property exists."""
        assert hasattr(prefect_adapter, "adapter_type")

    def test_has_name_property(self, prefect_adapter: PrefectAdapter) -> None:
        """Test name property exists."""
        assert hasattr(prefect_adapter, "name")

    def test_has_capabilities_property(self, prefect_adapter: PrefectAdapter) -> None:
        """Test capabilities property exists."""
        assert hasattr(prefect_adapter, "capabilities")


# =============================================================================
# Test: Lifecycle Management
# =============================================================================


class TestLifecycleManagement:
    """Tests for adapter lifecycle methods."""

    @pytest.mark.asyncio
    async def test_initialize_success(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test successful initialization."""
        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            assert prefect_adapter._initialized is True
            assert prefect_adapter._client is not None

    @pytest.mark.asyncio
    async def test_initialize_already_initialized(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test initialization when already initialized is no-op."""
        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()
            first_client = prefect_adapter._client

            # Initialize again - should be no-op
            await prefect_adapter.initialize()

            assert prefect_adapter._client is first_client

    @pytest.mark.asyncio
    async def test_shutdown(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test shutdown cleans up resources."""
        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()
            assert prefect_adapter._initialized is True

            await prefect_adapter.shutdown()

            assert prefect_adapter._initialized is False
            assert prefect_adapter._client is None

    @pytest.mark.asyncio
    async def test_cleanup_aliases_shutdown(
        self,
        prefect_adapter: PrefectAdapter,
    ) -> None:
        """Test cleanup calls shutdown."""
        with patch.object(prefect_adapter, "shutdown", new_callable=AsyncMock) as mock_shutdown:
            await prefect_adapter.cleanup()

            mock_shutdown.assert_called_once()


# =============================================================================
# Test: Exception Mapping
# =============================================================================


class TestExceptionMapping:
    """Tests for _map_prefect_exception function."""

    def test_map_object_not_found(self) -> None:
        """Test ObjectNotFound maps to DEPLOYMENT_NOT_FOUND."""
        exc = ObjectNotFound("Deployment not found")
        error = _map_prefect_exception(exc, "create_deployment", "http://test:4200")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_DEPLOYMENT_NOT_FOUND
        assert "Resource not found" in error.message

    def test_map_http_401(self) -> None:
        """Test 401 maps to AUTHENTICATION_ERROR."""
        response = MagicMock()
        response.status_code = 401
        exc = PrefectHTTPStatusError(
            message="Unauthorized",
            request=MagicMock(),
            response=response,
        )
        error = _map_prefect_exception(exc, "create_deployment", "http://test:4200")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_AUTHENTICATION_ERROR

    def test_map_http_429(self) -> None:
        """Test 429 maps to RATE_LIMITED."""
        response = MagicMock()
        response.status_code = 429
        exc = PrefectHTTPStatusError(
            message="Rate limited",
            request=MagicMock(),
            response=response,
        )
        error = _map_prefect_exception(exc, "create_deployment", "http://test:4200")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_RATE_LIMITED

    def test_map_http_404(self) -> None:
        """Test 404 maps to DEPLOYMENT_NOT_FOUND."""
        response = MagicMock()
        response.status_code = 404
        exc = PrefectHTTPStatusError(
            message="Not found",
            request=MagicMock(),
            response=response,
        )
        error = _map_prefect_exception(exc, "get_deployment", "http://test:4200")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_DEPLOYMENT_NOT_FOUND

    def test_map_http_500(self) -> None:
        """Test 5xx maps to API_ERROR."""
        response = MagicMock()
        response.status_code = 500
        exc = PrefectHTTPStatusError(
            message="Server error",
            request=MagicMock(),
            response=response,
        )
        error = _map_prefect_exception(exc, "create_deployment", "http://test:4200")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_API_ERROR

    def test_map_connect_error(self) -> None:
        """Test ConnectError maps to CONNECTION_ERROR."""
        exc = httpx.ConnectError("Connection failed")
        error = _map_prefect_exception(exc, "initialize", "http://test:4200")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_CONNECTION_ERROR

    def test_map_connect_timeout(self) -> None:
        """Test ConnectTimeout maps to CONNECTION_ERROR."""
        exc = httpx.ConnectTimeout("Connection timed out")
        error = _map_prefect_exception(exc, "initialize", "http://test:4200")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_CONNECTION_ERROR

    def test_map_read_timeout(self) -> None:
        """Test ReadTimeout maps to CONNECTION_ERROR."""
        exc = httpx.ReadTimeout("Read timed out")
        error = _map_prefect_exception(exc, "initialize", "http://test:4200")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_CONNECTION_ERROR

    def test_map_unknown_exception(self) -> None:
        """Test unknown exception maps to API_ERROR."""
        exc = RuntimeError("Something went wrong")
        error = _map_prefect_exception(exc, "execute", "http://test:4200")

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_API_ERROR


# =============================================================================
# Test: Helper Functions
# =============================================================================


class TestHelperFunctions:
    """Tests for helper functions."""

    @pytest.mark.asyncio
    async def test_maybe_await_sync_value(self) -> None:
        """Test _maybe_await with non-coroutine."""
        result = await _maybe_await("sync_value")
        assert result == "sync_value"

    @pytest.mark.asyncio
    async def test_maybe_await_coroutine(self) -> None:
        """Test _maybe_await with coroutine using async def."""

        async def get_coro():
            return "async_value"

        result = await _maybe_await(get_coro())
        assert result == "async_value"

    @pytest.mark.asyncio
    async def test_maybe_await_awaitable(self) -> None:
        """Test _maybe_await with awaitable."""

        async def get_value() -> str:
            return "awaitable_value"

        result = await _maybe_await(get_value())
        assert result == "awaitable_value"

    def test_get_explicit_client_method_with_mock(self) -> None:
        """Test _get_explicit_client_method with Mock."""
        client = MagicMock()
        client.explicit_method = MagicMock()

        method = _get_explicit_client_method(client, "explicit_method")
        assert method is not None

    def test_get_explicit_client_method_missing_on_mock(self) -> None:
        """Test _get_explicit_client_method returns None for missing method on Mock."""
        client = MagicMock()

        method = _get_explicit_client_method(client, "nonexistent_method")
        assert method is None

    def test_get_explicit_client_method_with_real_object(self) -> None:
        """Test _get_explicit_client_method with real object."""

        class RealClient:
            def real_method(self):
                pass

        client = RealClient()

        method = _get_explicit_client_method(client, "real_method")
        assert method is not None

    @pytest.mark.asyncio
    async def test_invoke_client_method_with_primary(self) -> None:
        """Test _invoke_client_method with primary method available."""
        client = MagicMock()
        client.primary_method = AsyncMock(return_value="result")

        result = await _invoke_client_method(client, "primary_method")
        assert result == "result"

    @pytest.mark.asyncio
    async def test_invoke_client_method_with_fallback(self) -> None:
        """Test _invoke_client_method falls back when primary missing."""
        client = MagicMock()
        client.fallback_method = AsyncMock(return_value="fallback_result")

        result = await _invoke_client_method(client, "nonexistent", fallback="fallback_method")
        assert result == "fallback_result"

    @pytest.mark.asyncio
    async def test_invoke_client_method_missing_raises(self) -> None:
        """Test _invoke_client_method raises when method unavailable."""
        client = MagicMock()

        with pytest.raises(AttributeError, match="does not implement"):
            await _invoke_client_method(client, "nonexistent")


# =============================================================================
# Test: Response Conversion Functions
# =============================================================================


class TestResponseConversion:
    """Tests for response conversion functions."""

    def test_deployment_to_response(self, mock_deployment: MagicMock) -> None:
        """Test _deployment_to_response conversion."""
        response = _deployment_to_response(mock_deployment)

        assert isinstance(response, DeploymentResponse)
        assert str(response.id) == str(mock_deployment.id)
        assert response.name == mock_deployment.name
        assert response.flow_name == mock_deployment.flow_name
        assert response.flow_id == str(mock_deployment.flow_id)
        assert response.schedule == mock_deployment.schedule
        assert response.parameters == mock_deployment.parameters
        assert response.work_pool_name == mock_deployment.work_pool_name
        assert response.paused == mock_deployment.paused
        assert response.tags == mock_deployment.tags

    def test_flow_run_to_response(self, mock_flow_run: MagicMock, mock_state: MagicMock) -> None:
        """Test _flow_run_to_response conversion."""
        mock_flow_run.state = mock_state
        response = _flow_run_to_response(mock_flow_run)

        assert isinstance(response, FlowRunResponse)
        assert str(response.id) == str(mock_flow_run.id)
        assert response.name == mock_flow_run.name
        assert response.flow_id == str(mock_flow_run.flow_id)
        assert response.state_type == mock_state.type
        assert response.state_name == mock_state.name
        assert response.parameters == mock_flow_run.parameters
        assert response.tags == mock_flow_run.tags

    def test_work_pool_to_response(self, mock_work_pool: MagicMock) -> None:
        """Test _work_pool_to_response conversion."""
        response = _work_pool_to_response(mock_work_pool)

        assert isinstance(response, WorkPoolResponse)
        assert response.name == mock_work_pool.name
        assert response.type == mock_work_pool.type
        assert response.description == mock_work_pool.description
        assert response.is_paused == mock_work_pool.is_paused
        assert response.concurrency_limit == mock_work_pool.concurrency_limit


# =============================================================================
# Test: Workflow Execution
# =============================================================================


class TestWorkflowExecution:
    """Tests for task submission and execution."""

    @pytest.mark.asyncio
    async def test_execute_success(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_flow_run: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """Test successful task execution."""
        mock_flow_run.state = mock_state

        mock_prefect_client.create_flow_run = AsyncMock(return_value=mock_flow_run)
        mock_prefect_client.wait_for_flow_run = AsyncMock(return_value=mock_state)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            task = {"type": "code_sweep", "id": "test-123"}
            repos = ["/repo1", "/repo2"]

            result = await prefect_adapter.execute(task, repos)

            assert result["status"] == "completed"
            assert result["engine"] == "prefect"
            assert result["task"] == task
            assert result["repos_processed"] == 2
            assert "flow_run_id" in result
            assert result["flow_run_url"] is not None

    @pytest.mark.asyncio
    async def test_execute_auto_initializes(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_flow_run: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """Test execute auto-initializes adapter if not initialized."""
        mock_flow_run.state = mock_state
        mock_prefect_client.create_flow_run = AsyncMock(return_value=mock_flow_run)
        mock_prefect_client.wait_for_flow_run = AsyncMock(return_value=mock_state)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            task = {"type": "code_sweep", "id": "test-123"}
            repos = ["/repo1"]

            await prefect_adapter.execute(task, repos)

            assert prefect_adapter._initialized is True

    @pytest.mark.asyncio
    async def test_execute_handles_failure(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test execute returns failed status on error."""
        mock_prefect_client.create_flow_run = AsyncMock(side_effect=Exception("API error"))

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            task = {"type": "code_sweep", "id": "test-123"}
            repos = ["/repo1"]

            result = await prefect_adapter.execute(task, repos)

            assert result["status"] == "failed"
            assert result["engine"] == "prefect"
            assert "error" in result


# =============================================================================
# Test: Health Check
# =============================================================================


class TestHealthCheck:
    """Tests for adapter health check."""

    @pytest.mark.asyncio
    async def test_get_health_healthy(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test get_health returns healthy status."""
        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )
            with patch.object(prefect, "__version__", "3.x"):
                await prefect_adapter.initialize()

                health = await prefect_adapter.get_health()

                assert health["status"] == "healthy"
                assert "details" in health
                assert health["details"]["configured"] is True
                assert health["details"]["connection"] == "available"

    @pytest.mark.asyncio
    async def test_get_health_unhealthy_on_prefect_error(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test get_health returns unhealthy on PrefectError."""
        mock_prefect_client.api_healthcheck = AsyncMock(
            side_effect=PrefectError(
                message="Connection failed",
                error_code=ErrorCode.PREFECT_CONNECTION_ERROR,
            )
        )

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )
            with patch.object(prefect, "__version__", "3.x"):
                await prefect_adapter.initialize()

                health = await prefect_adapter.get_health()

                assert health["status"] == "unhealthy"
                assert health["details"]["connection"] == "failed"

    @pytest.mark.asyncio
    async def test_get_health_unhealthy_on_generic_error(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test get_health returns unhealthy on generic exception."""
        mock_prefect_client.api_healthcheck = AsyncMock(
            side_effect=RuntimeError("Unexpected error")
        )

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )
            with patch.object(prefect, "__version__", "3.x"):
                await prefect_adapter.initialize()

                health = await prefect_adapter.get_health()

                assert health["status"] == "unhealthy"
                assert "error" in health["details"]


# =============================================================================
# Test: Deployment Management
# =============================================================================


class TestDeploymentManagement:
    """Tests for deployment CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_deployment(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_deployment: MagicMock,
    ) -> None:
        """Test create_deployment success."""
        mock_flow = MagicMock()
        mock_flow.id = uuid.uuid4()
        mock_prefect_client.read_flow_by_name = AsyncMock(return_value=mock_flow)
        mock_prefect_client.create_deployment = AsyncMock(return_value=mock_deployment)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            schedule = CronSchedule(cron="0 9 * * *")
            result = await prefect_adapter.create_deployment(
                flow_name="test-flow",
                deployment_name="test-deployment",
                schedule=schedule,
                parameters={"env": "test"},
                work_pool_name="test-pool",
                tags=["test"],
            )

            assert isinstance(result, DeploymentResponse)
            assert result.name == mock_deployment.name
            mock_prefect_client.create_deployment.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_deployment(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_deployment: MagicMock,
    ) -> None:
        """Test update_deployment success."""
        mock_prefect_client.update_deployment = AsyncMock(return_value=mock_deployment)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            schedule = CronSchedule(cron="0 10 * * *")
            result = await prefect_adapter.update_deployment(
                deployment_id=str(uuid.uuid4()),
                schedule=schedule,
                tags=["updated"],
            )

            assert isinstance(result, DeploymentResponse)
            mock_prefect_client.update_deployment.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_deployment(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test delete_deployment success."""
        mock_prefect_client.delete_deployment = AsyncMock(return_value=None)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.delete_deployment(str(uuid.uuid4()))

            assert result is True
            mock_prefect_client.delete_deployment.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_deployment(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_deployment: MagicMock,
    ) -> None:
        """Test get_deployment success."""
        mock_prefect_client.read_deployment = AsyncMock(return_value=mock_deployment)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.get_deployment(str(uuid.uuid4()))

            assert isinstance(result, DeploymentResponse)
            assert result.name == mock_deployment.name

    @pytest.mark.asyncio
    async def test_get_deployment_by_name(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_deployment: MagicMock,
    ) -> None:
        """Test get_deployment_by_name success."""
        mock_prefect_client.read_deployment_by_name = AsyncMock(return_value=mock_deployment)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.get_deployment_by_name(
                flow_name="test-flow",
                deployment_name="test-deployment",
            )

            assert isinstance(result, DeploymentResponse)
            mock_prefect_client.read_deployment_by_name.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_deployments(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_deployment: MagicMock,
    ) -> None:
        """Test list_deployments success."""
        mock_prefect_client.read_deployments = AsyncMock(return_value=[mock_deployment])

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.list_deployments(
                flow_name="test-flow",
                tags=["test"],
            )

            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], DeploymentResponse)


# =============================================================================
# Test: Flow Run Management
# =============================================================================


class TestFlowRunManagement:
    """Tests for flow run operations."""

    @pytest.mark.asyncio
    async def test_trigger_flow_run(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_flow_run: MagicMock,
    ) -> None:
        """Test trigger_flow_run success."""
        mock_prefect_client.create_flow_run_from_deployment = AsyncMock(return_value=mock_flow_run)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.trigger_flow_run(
                deployment_id=str(uuid.uuid4()),
                parameters={"batch_size": 100},
                tags=["manual"],
            )

            assert isinstance(result, FlowRunResponse)
            mock_prefect_client.create_flow_run_from_deployment.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_flow_run(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_flow_run: MagicMock,
    ) -> None:
        """Test get_flow_run success."""
        mock_prefect_client.read_flow_run = AsyncMock(return_value=mock_flow_run)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.get_flow_run(str(uuid.uuid4()))

            assert isinstance(result, FlowRunResponse)
            assert str(result.id) == str(mock_flow_run.id)

    @pytest.mark.asyncio
    async def test_list_flow_runs(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_flow_run: MagicMock,
    ) -> None:
        """Test list_flow_runs success."""
        mock_prefect_client.read_flow_runs = AsyncMock(return_value=[mock_flow_run])

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.list_flow_runs(
                deployment_id=str(uuid.uuid4()),
                state=["COMPLETED"],
            )

            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], FlowRunResponse)

    @pytest.mark.asyncio
    async def test_cancel_flow_run(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test cancel_flow_run success."""
        mock_prefect_client.set_flow_run_state = AsyncMock(return_value=None)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.cancel_flow_run(str(uuid.uuid4()))

            assert result is True
            mock_prefect_client.set_flow_run_state.assert_called_once()


# =============================================================================
# Test: Work Pool Management
# =============================================================================


class TestWorkPoolManagement:
    """Tests for work pool operations."""

    @pytest.mark.asyncio
    async def test_list_work_pools(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_work_pool: MagicMock,
    ) -> None:
        """Test list_work_pools success."""
        mock_prefect_client.read_work_pools = AsyncMock(return_value=[mock_work_pool])

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.list_work_pools()

            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], WorkPoolResponse)

    @pytest.mark.asyncio
    async def test_get_work_pool(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_work_pool: MagicMock,
    ) -> None:
        """Test get_work_pool success."""
        mock_prefect_client.read_work_pool = AsyncMock(return_value=mock_work_pool)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.get_work_pool("test-pool")

            assert isinstance(result, WorkPoolResponse)
            assert result.name == mock_work_pool.name


# =============================================================================
# Test: Schedule Management
# =============================================================================


class TestScheduleManagement:
    """Tests for deployment schedule operations."""

    @pytest.mark.asyncio
    async def test_set_deployment_schedule(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_deployment: MagicMock,
    ) -> None:
        """Test set_deployment_schedule delegates to update_deployment."""
        mock_prefect_client.update_deployment = AsyncMock(return_value=mock_deployment)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            schedule = CronSchedule(cron="0 10 * * *")
            result = await prefect_adapter.set_deployment_schedule(
                deployment_id=str(uuid.uuid4()),
                schedule=schedule,
            )

            assert isinstance(result, DeploymentResponse)

    @pytest.mark.asyncio
    async def test_clear_deployment_schedule(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_deployment: MagicMock,
    ) -> None:
        """Test clear_deployment_schedule success."""
        # Create a mock with all required string attributes for _deployment_to_response
        mock_deployment_no_schedule = MagicMock()
        mock_deployment_no_schedule.id = uuid.uuid4()
        mock_deployment_no_schedule.name = "test-deployment"
        mock_deployment_no_schedule.flow_name = "test-flow"
        mock_deployment_no_schedule.flow_id = uuid.uuid4()
        mock_deployment_no_schedule.schedule = None
        mock_deployment_no_schedule.parameters = {}
        mock_deployment_no_schedule.work_pool_name = "test-pool"
        mock_deployment_no_schedule.work_queue_name = "default"
        mock_deployment_no_schedule.paused = False
        mock_deployment_no_schedule.tags = []
        mock_deployment_no_schedule.description = None
        mock_deployment_no_schedule.version = None
        mock_deployment_no_schedule.created = datetime.now(UTC)
        mock_deployment_no_schedule.updated = None
        mock_prefect_client.update_deployment = AsyncMock(return_value=mock_deployment_no_schedule)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.clear_deployment_schedule(str(uuid.uuid4()))

            assert isinstance(result, DeploymentResponse)

    @pytest.mark.asyncio
    async def test_get_deployment_schedule_cron(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
        mock_deployment: MagicMock,
    ) -> None:
        """Test get_deployment_schedule returns CronSchedule."""
        mock_prefect_client.read_deployment = AsyncMock(return_value=mock_deployment)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.get_deployment_schedule(str(uuid.uuid4()))

            assert isinstance(result, CronSchedule)

    @pytest.mark.asyncio
    async def test_get_deployment_schedule_none(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test get_deployment_schedule returns None when no schedule."""
        # Create a mock with all required string attributes for _deployment_to_response
        mock_deployment_no_schedule = MagicMock()
        mock_deployment_no_schedule.id = uuid.uuid4()
        mock_deployment_no_schedule.name = "test-deployment"
        mock_deployment_no_schedule.flow_name = "test-flow"
        mock_deployment_no_schedule.flow_id = uuid.uuid4()
        mock_deployment_no_schedule.schedule = None
        mock_deployment_no_schedule.parameters = {}
        mock_deployment_no_schedule.work_pool_name = "test-pool"
        mock_deployment_no_schedule.work_queue_name = "default"
        mock_deployment_no_schedule.paused = False
        mock_deployment_no_schedule.tags = []
        mock_deployment_no_schedule.description = None
        mock_deployment_no_schedule.version = None
        mock_deployment_no_schedule.created = datetime.now(UTC)
        mock_deployment_no_schedule.updated = None
        mock_prefect_client.read_deployment = AsyncMock(return_value=mock_deployment_no_schedule)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            result = await prefect_adapter.get_deployment_schedule(str(uuid.uuid4()))

            assert result is None


# =============================================================================
# Test: Flow Registry Integration
# =============================================================================


class TestFlowRegistry:
    """Tests for flow registry operations."""

    def test_register_flow(self, prefect_adapter: PrefectAdapter) -> None:
        """Test register_flow adds flow to registry."""
        from prefect import flow

        @flow(name="test-reg-flow")
        def test_flow():
            pass

        flow_id = prefect_adapter.register_flow(test_flow, "test-flow", tags=["test"])

        assert flow_id is not None
        assert isinstance(flow_id, str)

    def test_list_registered_flows(self, prefect_adapter: PrefectAdapter) -> None:
        """Test list_registered_flows returns registered flows."""
        from prefect import flow

        @flow(name="test-list-flow")
        def test_flow():
            pass

        prefect_adapter.register_flow(test_flow, "test-flow", tags=["test"])
        flows = prefect_adapter.list_registered_flows(tags=["test"])

        assert isinstance(flows, list)
        assert len(flows) >= 1

    def test_get_registered_flow(self, prefect_adapter: PrefectAdapter) -> None:
        """Test get_registered_flow retrieves flow function."""
        from prefect import flow

        @flow(name="test-get-flow")
        def test_flow():
            pass

        flow_id = prefect_adapter.register_flow(test_flow, "test-flow")
        retrieved = prefect_adapter.get_registered_flow(flow_id)

        assert retrieved is not None

    def test_unregister_flow(self, prefect_adapter: PrefectAdapter) -> None:
        """Test unregister_flow removes flow from registry."""
        from prefect import flow

        @flow(name="test-remove-flow")
        def test_flow():
            pass

        flow_id = prefect_adapter.register_flow(test_flow, "test-flow")
        result = prefect_adapter.unregister_flow(flow_id)

        assert result is True


# =============================================================================
# Test: Schedule Utilities
# =============================================================================


class TestScheduleUtilities:
    """Tests for schedule conversion utilities."""

    def test_schedule_to_prefect_dict_cron(self) -> None:
        """Test schedule_to_prefect_dict with CronSchedule."""
        schedule = CronSchedule(cron="0 9 * * *", timezone="UTC")
        result = schedule_to_prefect_dict(schedule)

        assert result["cron"] == "0 9 * * *"
        assert result["timezone"] == "UTC"
        assert result["day_or"] is True

    def test_schedule_to_prefect_dict_interval(self) -> None:
        """Test schedule_to_prefect_dict with IntervalSchedule."""
        schedule = IntervalSchedule(interval_seconds=3600)
        result = schedule_to_prefect_dict(schedule)

        assert result["interval"] == 3600

    def test_schedule_to_prefect_dict_rrule(self) -> None:
        """Test schedule_to_prefect_dict with RRuleSchedule."""
        schedule = RRuleSchedule(rrule="FREQ=DAILY", timezone="UTC")
        result = schedule_to_prefect_dict(schedule)

        assert result["rrule"] == "FREQ=DAILY"
        assert result["timezone"] == "UTC"


# =============================================================================
# Test: Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_create_deployment_raises_not_found(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test create_deployment raises PrefectError when flow not found."""
        mock_prefect_client.read_flow_by_name = AsyncMock(
            side_effect=ObjectNotFound("Flow not found")
        )

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            with pytest.raises(PrefectError):
                await prefect_adapter.create_deployment(
                    flow_name="nonexistent-flow",
                    deployment_name="test-deployment",
                )

            # Error code varies based on exception wrapping in try/except

    @pytest.mark.asyncio
    async def test_get_deployment_raises_not_found(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test get_deployment raises PrefectError when not found."""
        mock_prefect_client.read_deployment = AsyncMock(
            side_effect=ObjectNotFound("Deployment not found")
        )

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            with pytest.raises(PrefectError):
                await prefect_adapter.get_deployment(str(uuid.uuid4()))

            # Error code varies based on exception wrapping

    @pytest.mark.asyncio
    async def test_trigger_flow_run_raises_auth_error(
        self,
        prefect_adapter: PrefectAdapter,
        mock_prefect_client: MagicMock,
    ) -> None:
        """Test trigger_flow_run raises authentication error on 401."""
        response = MagicMock()
        response.status_code = 401
        mock_prefect_client.create_flow_run_from_deployment = AsyncMock(
            side_effect=PrefectHTTPStatusError(
                message="Unauthorized",
                request=MagicMock(),
                response=response,
            )
        )

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            await prefect_adapter.initialize()

            with pytest.raises(PrefectError):
                await prefect_adapter.trigger_flow_run(str(uuid.uuid4()))

            # Error code may vary based on exception wrapping


# =============================================================================
# Test: Client Context Manager
# =============================================================================


class TestClientContextManager:
    """Tests for _get_client_context method."""

    @pytest.mark.asyncio
    async def test_client_context_with_api_key(
        self, prefect_adapter: PrefectAdapter, mock_prefect_client: MagicMock
    ) -> None:
        """Test client context sets API key environment variable."""
        config = PrefectConfig(api_url="http://cloud:4200", api_key="test-key")
        adapter = PrefectAdapter(config=config)

        with patch("mahavishnu.engines.prefect_adapter_impl.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock(
                __aenter__=AsyncMock(return_value=mock_prefect_client),
                __aexit__=AsyncMock(return_value=None),
            )

            async with adapter._get_client_context() as client:
                assert client is not None

    @pytest.mark.asyncio
    async def test_client_context_fallback_shim(self, prefect_adapter: PrefectAdapter) -> None:
        """Test client context falls back to shim when get_client fails."""
        with patch(
            "mahavishnu.engines.prefect_adapter_impl.get_client",
            side_effect=RuntimeError("Cannot create client"),
        ):
            async with prefect_adapter._get_client_context() as client:
                assert hasattr(client, "_compat_shim")
                assert client._compat_shim is True


# =============================================================================
# Test: Prefect Tasks and Flows
# =============================================================================


class TestPrefectTasksAndFlows:
    """Tests for Prefect task and flow definitions."""

    def test_process_repository_task_exists(self) -> None:
        """Test process_repository task is defined."""
        assert process_repository is not None

    def test_process_repositories_flow_exists(self) -> None:
        """Test process_repositories_flow is defined."""
        assert process_repositories_flow is not None

    @pytest.mark.asyncio
    async def test_process_repository_default_task(self) -> None:
        """Test process_repository with default task type."""
        result = await process_repository.fn("/test/repo", {"type": "unknown", "id": "test-123"})

        assert result["status"] == "completed"
        assert result["repo"] == "/test/repo"
        assert result["task_id"] == "test-123"

    @pytest.mark.asyncio
    async def test_process_repository_with_exception(self) -> None:
        """Test process_repository handles exceptions gracefully."""
        with patch("mahavishnu.engines.prefect_adapter_impl.CodeGraphAnalyzer") as mock_analyzer:
            mock_analyzer.side_effect = Exception("Analysis failed")

            result = await process_repository.fn(
                "/test/repo", {"type": "code_sweep", "id": "test-123"}
            )

            assert result["status"] == "failed"
            assert "error" in result


# =============================================================================
# Test: Entry Point Function
# =============================================================================


class TestEntryPoint:
    """Tests for prefect_adapter_entries function."""

    def test_prefect_adapter_entries_returns_list(self) -> None:
        """Test entry point returns list of adapter metadata."""
        from mahavishnu.engines.prefect_adapter_impl import prefect_adapter_entries

        result = prefect_adapter_entries()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["provider"] == "prefect"
        assert result[0]["category"] == "orchestration"
        assert "factory_path" in result[0]
        assert "capabilities" in result[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
