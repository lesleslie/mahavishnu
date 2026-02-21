"""Unit tests for PrefectAdapter Phase 2 deployment management.

These tests cover the Phase 2 features:
- Deployment CRUD operations
- Flow run management
- Work pool management
- Schedule validation and conversion

Tests use mocked Prefect clients to avoid requiring a real Prefect server.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.config import PrefectConfig
from mahavishnu.core.errors import ErrorCode, PrefectError
from mahavishnu.engines.prefect_adapter import (
    PrefectAdapter,
    _deployment_to_response,
    _flow_run_to_response,
    _work_pool_to_response,
    _map_prefect_exception,
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
def mock_prefect_client():
    """Create a mock Prefect orchestration client."""
    client = AsyncMock()
    client.api_url = "http://localhost:4200"
    client.read_health = AsyncMock(return_value=MagicMock(version="3.0.0"))
    return client


@pytest.fixture
async def adapter(prefect_config):
    """Create a PrefectAdapter instance for testing."""
    adapter = PrefectAdapter(prefect_config)
    adapter._initialized = True  # Skip initialization for most tests
    yield adapter
    await adapter.shutdown()


@pytest.fixture
def mock_deployment():
    """Create a mock Prefect deployment object."""
    deployment = MagicMock()
    deployment.id = "deployment-123"
    deployment.name = "test-deployment"
    deployment.flow_name = "test-flow"
    deployment.flow_id = "flow-456"
    deployment.schedule = {"cron": "0 9 * * *"}
    deployment.parameters = {"env": "test"}
    deployment.work_pool_name = "default"
    deployment.work_queue_name = None
    deployment.paused = False
    deployment.tags = ["test", "unit"]
    deployment.description = "Test deployment"
    deployment.version = "1.0.0"
    deployment.created = datetime(2024, 1, 1, 12, 0, 0)
    deployment.updated = datetime(2024, 1, 2, 12, 0, 0)
    return deployment


@pytest.fixture
def mock_flow_run():
    """Create a mock Prefect flow run object."""
    flow_run = MagicMock()
    flow_run.id = "flow-run-123"
    flow_run.name = "test-flow-run"
    flow_run.flow_id = "flow-456"
    flow_run.deployment_id = "deployment-123"

    state = MagicMock()
    state.type = "COMPLETED"
    state.name = "Completed"
    flow_run.state = state

    flow_run.parameters = {"env": "test"}
    flow_run.tags = ["manual"]
    flow_run.created = datetime(2024, 1, 1, 12, 0, 0)
    flow_run.updated = datetime(2024, 1, 1, 13, 0, 0)
    flow_run.start_time = datetime(2024, 1, 1, 12, 1, 0)
    flow_run.end_time = datetime(2024, 1, 1, 12, 30, 0)
    flow_run.total_run_time = 1740.0  # 29 minutes
    flow_run.estimated_run_time = 1800.0
    flow_run.work_queue_name = "default"
    return flow_run


@pytest.fixture
def mock_work_pool():
    """Create a mock Prefect work pool object."""
    work_pool = MagicMock()
    work_pool.name = "test-pool"
    work_pool.type = "process"
    work_pool.description = "Test work pool"
    work_pool.is_paused = False
    work_pool.concurrency_limit = 10
    work_pool.created = datetime(2024, 1, 1, 12, 0, 0)
    work_pool.updated = None
    return work_pool


# =============================================================================
# Schedule Model Tests
# =============================================================================


class TestCronSchedule:
    """Tests for CronSchedule model."""

    def test_valid_cron_expression(self):
        """Test creating a valid cron schedule."""
        schedule = CronSchedule(cron="0 9 * * *")
        assert schedule.cron == "0 9 * * *"
        assert schedule.timezone == "UTC"
        assert schedule.day_or is True
        assert schedule.type == "cron"

    def test_custom_timezone(self):
        """Test cron schedule with custom timezone."""
        schedule = CronSchedule(
            cron="0 9 * * *",
            timezone="America/New_York",
            day_or=False,
        )
        assert schedule.timezone == "America/New_York"
        assert schedule.day_or is False

    def test_invalid_cron_expression(self):
        """Test that invalid cron expressions raise validation error."""
        with pytest.raises(ValueError, match="Invalid cron expression"):
            CronSchedule(cron="not-valid-cron")


class TestIntervalSchedule:
    """Tests for IntervalSchedule model."""

    def test_valid_interval(self):
        """Test creating a valid interval schedule."""
        schedule = IntervalSchedule(interval_seconds=3600)
        assert schedule.interval_seconds == 3600
        assert schedule.anchor_date is None
        assert schedule.type == "interval"

    def test_interval_with_anchor(self):
        """Test interval schedule with anchor date."""
        anchor = datetime(2024, 1, 1, 0, 0, 0)
        schedule = IntervalSchedule(
            interval_seconds=1800,
            anchor_date=anchor,
        )
        assert schedule.interval_seconds == 1800
        assert schedule.anchor_date == anchor

    def test_interval_validation_min(self):
        """Test that interval must be at least 1 second."""
        with pytest.raises(ValueError):
            IntervalSchedule(interval_seconds=0)

    def test_interval_validation_max(self):
        """Test that interval cannot exceed 1 year."""
        with pytest.raises(ValueError):
            IntervalSchedule(interval_seconds=31536001)  # 1 year + 1 second


class TestRRuleSchedule:
    """Tests for RRuleSchedule model."""

    def test_valid_rrule(self):
        """Test creating a valid RRULE schedule."""
        schedule = RRuleSchedule(rrule="FREQ=DAILY;BYDAY=MO,WE,FR")
        assert schedule.rrule == "FREQ=DAILY;BYDAY=MO,WE,FR"
        assert schedule.timezone == "UTC"
        assert schedule.type == "rrule"

    def test_invalid_rrule(self):
        """Test that invalid RRULE raises validation error."""
        with pytest.raises(ValueError, match="Invalid RRULE"):
            RRuleSchedule(rrule="INVALID")


class TestScheduleConversion:
    """Tests for schedule_to_prefect_dict function."""

    def test_cron_conversion(self):
        """Test converting CronSchedule to Prefect format."""
        schedule = CronSchedule(cron="0 9 * * *", timezone="UTC")
        result = schedule_to_prefect_dict(schedule)
        assert result == {
            "cron": "0 9 * * *",
            "timezone": "UTC",
            "day_or": True,
        }

    def test_interval_conversion(self):
        """Test converting IntervalSchedule to Prefect format."""
        schedule = IntervalSchedule(interval_seconds=3600)
        result = schedule_to_prefect_dict(schedule)
        assert result == {"interval": 3600}

    def test_interval_with_anchor_conversion(self):
        """Test converting IntervalSchedule with anchor to Prefect format."""
        anchor = datetime(2024, 1, 1, 0, 0, 0)
        schedule = IntervalSchedule(interval_seconds=1800, anchor_date=anchor)
        result = schedule_to_prefect_dict(schedule)
        assert result["interval"] == 1800
        assert "anchor_date" in result

    def test_rrule_conversion(self):
        """Test converting RRuleSchedule to Prefect format."""
        schedule = RRuleSchedule(rrule="FREQ=DAILY;BYDAY=MO,WE,FR")
        result = schedule_to_prefect_dict(schedule)
        assert result == {
            "rrule": "FREQ=DAILY;BYDAY=MO,WE,FR",
            "timezone": "UTC",
        }


# =============================================================================
# Response Model Tests
# =============================================================================


class TestDeploymentResponse:
    """Tests for DeploymentResponse model."""

    def test_deployment_response_creation(self):
        """Test creating a DeploymentResponse."""
        response = DeploymentResponse(
            id="dep-123",
            name="test-deployment",
            flow_name="test-flow",
            flow_id="flow-456",
            schedule={"cron": "0 9 * * *"},
            parameters={"env": "test"},
            paused=False,
            created_at=datetime.now(),
        )
        assert response.id == "dep-123"
        assert response.name == "test-deployment"
        assert response.tags == []

    def test_deployment_response_defaults(self):
        """Test DeploymentResponse default values."""
        response = DeploymentResponse(
            id="dep-123",
            name="test",
            flow_name="flow",
            flow_id="flow-456",
            created_at=datetime.now(),
        )
        assert response.parameters == {}
        assert response.tags == []
        assert response.paused is False
        assert response.schedule is None


class TestFlowRunResponse:
    """Tests for FlowRunResponse model."""

    def test_flow_run_response_creation(self):
        """Test creating a FlowRunResponse."""
        response = FlowRunResponse(
            id="run-123",
            name="test-run",
            flow_id="flow-456",
            state_type="COMPLETED",
            state_name="Completed",
            created_at=datetime.now(),
        )
        assert response.id == "run-123"
        assert response.deployment_id is None

    def test_flow_run_with_deployment(self):
        """Test FlowRunResponse with deployment."""
        response = FlowRunResponse(
            id="run-123",
            name="test-run",
            flow_id="flow-456",
            deployment_id="dep-789",
            state_type="RUNNING",
            state_name="Running",
            created_at=datetime.now(),
        )
        assert response.deployment_id == "dep-789"


# =============================================================================
# Response Conversion Tests
# =============================================================================


class TestResponseConversions:
    """Tests for response conversion functions."""

    def test_deployment_to_response(self, mock_deployment):
        """Test converting mock deployment to response."""
        response = _deployment_to_response(mock_deployment)
        assert isinstance(response, DeploymentResponse)
        assert response.id == "deployment-123"
        assert response.name == "test-deployment"
        assert response.flow_name == "test-flow"
        assert response.schedule == {"cron": "0 9 * * *"}
        assert response.parameters == {"env": "test"}
        assert response.tags == ["test", "unit"]

    def test_flow_run_to_response(self, mock_flow_run):
        """Test converting mock flow run to response."""
        response = _flow_run_to_response(mock_flow_run)
        assert isinstance(response, FlowRunResponse)
        assert response.id == "flow-run-123"
        assert response.state_type == "COMPLETED"
        assert response.state_name == "Completed"
        assert response.total_run_time_seconds == 1740.0

    def test_work_pool_to_response(self, mock_work_pool):
        """Test converting mock work pool to response."""
        response = _work_pool_to_response(mock_work_pool)
        assert isinstance(response, WorkPoolResponse)
        assert response.name == "test-pool"
        assert response.type == "process"
        assert response.concurrency_limit == 10


# =============================================================================
# Deployment CRUD Tests
# =============================================================================


class TestCreateDeployment:
    """Tests for create_deployment method."""

    @pytest.mark.asyncio
    async def test_create_deployment_success(self, adapter, mock_prefect_client, mock_deployment):
        """Test successful deployment creation."""
        mock_flow = MagicMock()
        mock_flow.id = "flow-456"
        mock_prefect_client.read_flow_by_name = AsyncMock(return_value=mock_flow)
        mock_prefect_client.create_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.create_deployment(
                flow_name="test-flow",
                deployment_name="test-deployment",
                parameters={"env": "test"},
                tags=["test"],
            )

        assert isinstance(result, DeploymentResponse)
        assert result.name == "test-deployment"
        mock_prefect_client.create_deployment.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_deployment_with_schedule(self, adapter, mock_prefect_client, mock_deployment):
        """Test deployment creation with cron schedule."""
        mock_flow = MagicMock()
        mock_flow.id = "flow-456"
        mock_prefect_client.read_flow_by_name = AsyncMock(return_value=mock_flow)
        mock_prefect_client.create_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        schedule = CronSchedule(cron="0 9 * * *")
        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.create_deployment(
                flow_name="test-flow",
                deployment_name="scheduled-deployment",
                schedule=schedule,
            )

        assert result is not None
        call_kwargs = mock_prefect_client.create_deployment.call_args[1]
        assert "schedule" in call_kwargs

    @pytest.mark.asyncio
    async def test_create_deployment_auto_initializes(self, prefect_config, mock_prefect_client, mock_deployment):
        """Test that create_deployment auto-initializes if needed."""
        adapter = PrefectAdapter(prefect_config)
        adapter._initialized = False

        mock_flow = MagicMock()
        mock_flow.id = "flow-456"
        mock_prefect_client.read_flow_by_name = AsyncMock(return_value=mock_flow)
        mock_prefect_client.create_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            await adapter.create_deployment(
                flow_name="test-flow",
                deployment_name="test-deployment",
            )

        assert adapter._initialized is True
        await adapter.shutdown()


class TestUpdateDeployment:
    """Tests for update_deployment method."""

    @pytest.mark.asyncio
    async def test_update_deployment_pause(self, adapter, mock_prefect_client, mock_deployment):
        """Test pausing a deployment."""
        mock_deployment.paused = True
        mock_prefect_client.update_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.update_deployment(
                deployment_id="deployment-123",
                paused=True,
            )

        assert result.paused is True
        call_kwargs = mock_prefect_client.update_deployment.call_args[1]
        assert call_kwargs["paused"] is True

    @pytest.mark.asyncio
    async def test_update_deployment_schedule(self, adapter, mock_prefect_client, mock_deployment):
        """Test updating deployment schedule."""
        mock_prefect_client.update_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        schedule = IntervalSchedule(interval_seconds=3600)
        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.update_deployment(
                deployment_id="deployment-123",
                schedule=schedule,
            )

        assert result is not None
        call_kwargs = mock_prefect_client.update_deployment.call_args[1]
        assert "schedule" in call_kwargs


class TestDeleteDeployment:
    """Tests for delete_deployment method."""

    @pytest.mark.asyncio
    async def test_delete_deployment_success(self, adapter, mock_prefect_client):
        """Test successful deployment deletion."""
        mock_prefect_client.delete_deployment = AsyncMock()

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.delete_deployment("deployment-123")

        assert result is True
        mock_prefect_client.delete_deployment.assert_called_once_with("deployment-123")


class TestGetDeployment:
    """Tests for get_deployment and get_deployment_by_name methods."""

    @pytest.mark.asyncio
    async def test_get_deployment_by_id(self, adapter, mock_prefect_client, mock_deployment):
        """Test getting deployment by ID."""
        mock_prefect_client.read_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.get_deployment("deployment-123")

        assert result.id == "deployment-123"
        mock_prefect_client.read_deployment.assert_called_once_with("deployment-123")

    @pytest.mark.asyncio
    async def test_get_deployment_by_name(self, adapter, mock_prefect_client, mock_deployment):
        """Test getting deployment by flow/deployment name."""
        mock_prefect_client.read_deployment_by_name = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.get_deployment_by_name("test-flow", "test-deployment")

        assert result.name == "test-deployment"
        mock_prefect_client.read_deployment_by_name.assert_called_once_with("test-flow/test-deployment")


class TestListDeployments:
    """Tests for list_deployments method."""

    @pytest.mark.asyncio
    async def test_list_all_deployments(self, adapter, mock_prefect_client, mock_deployment):
        """Test listing all deployments."""
        mock_prefect_client.read_deployments = AsyncMock(
            return_value=[mock_deployment, mock_deployment]
        )

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            results = await adapter.list_deployments()

        assert len(results) == 2
        assert all(isinstance(r, DeploymentResponse) for r in results)

    @pytest.mark.asyncio
    async def test_list_deployments_with_filter(self, adapter, mock_prefect_client, mock_deployment):
        """Test listing deployments with filters."""
        mock_prefect_client.read_deployments = AsyncMock(return_value=[mock_deployment])

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            results = await adapter.list_deployments(
                flow_name="test-flow",
                tags=["production"],
                limit=50,
            )

        assert len(results) == 1
        call_kwargs = mock_prefect_client.read_deployments.call_args[1]
        assert call_kwargs["flow_name"] == "test-flow"
        assert call_kwargs["tags"] == ["production"]
        assert call_kwargs["limit"] == 50


# =============================================================================
# Flow Run Management Tests
# =============================================================================


class TestTriggerFlowRun:
    """Tests for trigger_flow_run method."""

    @pytest.mark.asyncio
    async def test_trigger_flow_run_success(self, adapter, mock_prefect_client, mock_flow_run):
        """Test triggering a flow run."""
        mock_prefect_client.create_flow_run_from_deployment = AsyncMock(
            return_value=mock_flow_run
        )

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.trigger_flow_run(
                deployment_id="deployment-123",
                parameters={"batch_size": 100},
            )

        assert result.id == "flow-run-123"
        assert result.state_type == "COMPLETED"

    @pytest.mark.asyncio
    async def test_trigger_flow_run_with_idempotency(self, adapter, mock_prefect_client, mock_flow_run):
        """Test triggering flow run with idempotency key."""
        mock_prefect_client.create_flow_run_from_deployment = AsyncMock(
            return_value=mock_flow_run
        )

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            await adapter.trigger_flow_run(
                deployment_id="deployment-123",
                idempotency_key="unique-key",
            )

        call_kwargs = mock_prefect_client.create_flow_run_from_deployment.call_args[1]
        assert call_kwargs["idempotency_key"] == "unique-key"


class TestGetFlowRun:
    """Tests for get_flow_run method."""

    @pytest.mark.asyncio
    async def test_get_flow_run(self, adapter, mock_prefect_client, mock_flow_run):
        """Test getting flow run details."""
        mock_prefect_client.read_flow_run = AsyncMock(return_value=mock_flow_run)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.get_flow_run("flow-run-123")

        assert result.id == "flow-run-123"
        assert result.state_type == "COMPLETED"


class TestListFlowRuns:
    """Tests for list_flow_runs method."""

    @pytest.mark.asyncio
    async def test_list_flow_runs(self, adapter, mock_prefect_client, mock_flow_run):
        """Test listing flow runs."""
        mock_prefect_client.read_flow_runs = AsyncMock(
            return_value=[mock_flow_run]
        )

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            results = await adapter.list_flow_runs(
                deployment_id="deployment-123",
                state=["COMPLETED"],
            )

        assert len(results) == 1
        call_kwargs = mock_prefect_client.read_flow_runs.call_args[1]
        assert call_kwargs["deployment_id"] == "deployment-123"
        assert call_kwargs["state"] == ["COMPLETED"]


class TestCancelFlowRun:
    """Tests for cancel_flow_run method."""

    @pytest.mark.asyncio
    async def test_cancel_flow_run(self, adapter, mock_prefect_client):
        """Test cancelling a flow run."""
        mock_prefect_client.set_flow_run_state = AsyncMock()

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.cancel_flow_run("flow-run-123")

        assert result is True
        mock_prefect_client.set_flow_run_state.assert_called_once_with(
            "flow-run-123",
            state="CANCELLED",
        )


# =============================================================================
# Work Pool Management Tests
# =============================================================================


class TestListWorkPools:
    """Tests for list_work_pools method."""

    @pytest.mark.asyncio
    async def test_list_work_pools(self, adapter, mock_prefect_client, mock_work_pool):
        """Test listing work pools."""
        mock_prefect_client.read_work_pools = AsyncMock(
            return_value=[mock_work_pool]
        )

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            results = await adapter.list_work_pools()

        assert len(results) == 1
        assert results[0].name == "test-pool"
        assert results[0].type == "process"


class TestGetWorkPool:
    """Tests for get_work_pool method."""

    @pytest.mark.asyncio
    async def test_get_work_pool(self, adapter, mock_prefect_client, mock_work_pool):
        """Test getting work pool details."""
        mock_prefect_client.read_work_pool = AsyncMock(return_value=mock_work_pool)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.get_work_pool("test-pool")

        assert result.name == "test-pool"
        assert result.concurrency_limit == 10


# =============================================================================
# Error Mapping Tests (Direct function tests)
# =============================================================================


class TestExceptionMapping:
    """Tests for _map_prefect_exception function - Phase 2 coverage."""

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
# Markers
# =============================================================================


# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit
