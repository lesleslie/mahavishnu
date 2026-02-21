"""Unit tests for PrefectAdapter Phase 3: Schedule Management and Flow Registry.

These tests cover the Phase 3 features:
- Schedule helper functions (create_hourly_schedule, create_daily_schedule, etc.)
- Schedule management methods (set_deployment_schedule, clear_deployment_schedule, get_deployment_schedule)
- Flow registry functionality (FlowRegistry class, register_flow, list_registered_flows)

Tests use mocked Prefect clients to avoid requiring a real Prefect server.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.config import PrefectConfig
from mahavishnu.core.errors import PrefectError
from mahavishnu.engines.prefect_adapter import PrefectAdapter
from mahavishnu.engines.prefect_registry import (
    FlowRegistry,
    get_flow_registry,
    reset_flow_registry,
)
from mahavishnu.engines.prefect_schedules import (
    CronSchedule,
    IntervalSchedule,
    RRuleSchedule,
    create_daily_schedule,
    create_hourly_schedule,
    create_monthly_schedule,
    create_weekly_schedule,
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


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the global flow registry before and after each test."""
    reset_flow_registry()
    yield
    reset_flow_registry()


# =============================================================================
# Schedule Helper Function Tests
# =============================================================================


class TestCreateHourlySchedule:
    """Tests for create_hourly_schedule helper function."""

    def test_create_hourly_schedule_default(self):
        """Test creating hourly schedule with default parameters."""
        schedule = create_hourly_schedule()
        assert isinstance(schedule, IntervalSchedule)
        assert schedule.interval_seconds == 3600
        assert schedule.anchor_date is not None
        assert schedule.anchor_date.minute == 0

    def test_create_hourly_schedule_with_minute(self):
        """Test creating hourly schedule with specific minute."""
        schedule = create_hourly_schedule(minute=30)
        assert isinstance(schedule, IntervalSchedule)
        assert schedule.interval_seconds == 3600
        assert schedule.anchor_date.minute == 30

    def test_create_hourly_schedule_minute_zero(self):
        """Test creating hourly schedule at minute 0."""
        schedule = create_hourly_schedule(minute=0)
        assert schedule.anchor_date.minute == 0

    def test_create_hourly_schedule_minute_59(self):
        """Test creating hourly schedule at minute 59."""
        schedule = create_hourly_schedule(minute=59)
        assert schedule.anchor_date.minute == 59

    def test_create_hourly_schedule_invalid_minute_low(self):
        """Test that negative minute raises ValueError."""
        with pytest.raises(ValueError, match="minute must be between 0 and 59"):
            create_hourly_schedule(minute=-1)

    def test_create_hourly_schedule_invalid_minute_high(self):
        """Test that minute > 59 raises ValueError."""
        with pytest.raises(ValueError, match="minute must be between 0 and 59"):
            create_hourly_schedule(minute=60)


class TestCreateDailySchedule:
    """Tests for create_daily_schedule helper function."""

    def test_create_daily_schedule_default(self):
        """Test creating daily schedule with default minute."""
        schedule = create_daily_schedule(hour=9)
        assert isinstance(schedule, CronSchedule)
        assert schedule.cron == "0 9 * * *"
        assert schedule.timezone == "UTC"

    def test_create_daily_schedule_with_minute(self):
        """Test creating daily schedule with specific minute."""
        schedule = create_daily_schedule(hour=14, minute=30)
        assert isinstance(schedule, CronSchedule)
        assert schedule.cron == "30 14 * * *"

    def test_create_daily_schedule_with_timezone(self):
        """Test creating daily schedule with custom timezone."""
        schedule = create_daily_schedule(
            hour=9,
            minute=0,
            timezone="America/New_York",
        )
        assert schedule.timezone == "America/New_York"

    def test_create_daily_schedule_midnight(self):
        """Test creating daily schedule at midnight."""
        schedule = create_daily_schedule(hour=0, minute=0)
        assert schedule.cron == "0 0 * * *"

    def test_create_daily_schedule_23_59(self):
        """Test creating daily schedule at 23:59."""
        schedule = create_daily_schedule(hour=23, minute=59)
        assert schedule.cron == "59 23 * * *"

    def test_create_daily_schedule_invalid_hour_low(self):
        """Test that negative hour raises ValueError."""
        with pytest.raises(ValueError, match="hour must be between 0 and 23"):
            create_daily_schedule(hour=-1)

    def test_create_daily_schedule_invalid_hour_high(self):
        """Test that hour > 23 raises ValueError."""
        with pytest.raises(ValueError, match="hour must be between 0 and 23"):
            create_daily_schedule(hour=24)

    def test_create_daily_schedule_invalid_minute_low(self):
        """Test that negative minute raises ValueError."""
        with pytest.raises(ValueError, match="minute must be between 0 and 59"):
            create_daily_schedule(hour=9, minute=-1)

    def test_create_daily_schedule_invalid_minute_high(self):
        """Test that minute > 59 raises ValueError."""
        with pytest.raises(ValueError, match="minute must be between 0 and 59"):
            create_daily_schedule(hour=9, minute=60)


class TestCreateWeeklySchedule:
    """Tests for create_weekly_schedule helper function."""

    def test_create_weekly_schedule_monday(self):
        """Test creating weekly schedule for Monday."""
        schedule = create_weekly_schedule(day_of_week=1, hour=9)
        assert isinstance(schedule, CronSchedule)
        assert schedule.cron == "0 9 * * 1"

    def test_create_weekly_schedule_friday(self):
        """Test creating weekly schedule for Friday."""
        schedule = create_weekly_schedule(day_of_week=5, hour=17, minute=30)
        assert schedule.cron == "30 17 * * 5"

    def test_create_weekly_schedule_sunday(self):
        """Test creating weekly schedule for Sunday (0)."""
        schedule = create_weekly_schedule(day_of_week=0, hour=0)
        assert schedule.cron == "0 0 * * 0"

    def test_create_weekly_schedule_saturday(self):
        """Test creating weekly schedule for Saturday (6)."""
        schedule = create_weekly_schedule(day_of_week=6, hour=23, minute=59)
        assert schedule.cron == "59 23 * * 6"

    def test_create_weekly_schedule_with_timezone(self):
        """Test creating weekly schedule with custom timezone."""
        schedule = create_weekly_schedule(
            day_of_week=1,
            hour=9,
            timezone="Europe/London",
        )
        assert schedule.timezone == "Europe/London"

    def test_create_weekly_schedule_invalid_day_low(self):
        """Test that negative day_of_week raises ValueError."""
        with pytest.raises(ValueError, match="day_of_week must be between 0"):
            create_weekly_schedule(day_of_week=-1, hour=9)

    def test_create_weekly_schedule_invalid_day_high(self):
        """Test that day_of_week > 6 raises ValueError."""
        with pytest.raises(ValueError, match="day_of_week must be between 0"):
            create_weekly_schedule(day_of_week=7, hour=9)


class TestCreateMonthlySchedule:
    """Tests for create_monthly_schedule helper function."""

    def test_create_monthly_schedule_first(self):
        """Test creating monthly schedule for the 1st."""
        schedule = create_monthly_schedule(day_of_month=1, hour=0)
        assert isinstance(schedule, CronSchedule)
        assert schedule.cron == "0 0 1 * *"

    def test_create_monthly_schedule_15th(self):
        """Test creating monthly schedule for the 15th."""
        schedule = create_monthly_schedule(day_of_month=15, hour=12, minute=30)
        assert schedule.cron == "30 12 15 * *"

    def test_create_monthly_schedule_31st(self):
        """Test creating monthly schedule for the 31st."""
        schedule = create_monthly_schedule(day_of_month=31, hour=23, minute=59)
        assert schedule.cron == "59 23 31 * *"

    def test_create_monthly_schedule_with_timezone(self):
        """Test creating monthly schedule with custom timezone."""
        schedule = create_monthly_schedule(
            day_of_month=1,
            hour=0,
            timezone="Asia/Tokyo",
        )
        assert schedule.timezone == "Asia/Tokyo"

    def test_create_monthly_schedule_invalid_day_low(self):
        """Test that day_of_month < 1 raises ValueError."""
        with pytest.raises(ValueError, match="day_of_month must be between 1"):
            create_monthly_schedule(day_of_month=0, hour=9)

    def test_create_monthly_schedule_invalid_day_high(self):
        """Test that day_of_month > 31 raises ValueError."""
        with pytest.raises(ValueError, match="day_of_month must be between 1"):
            create_monthly_schedule(day_of_month=32, hour=9)


# =============================================================================
# Flow Registry Tests
# =============================================================================


class TestFlowRegistry:
    """Tests for FlowRegistry class."""

    def test_flow_registry_initialization(self):
        """Test that FlowRegistry initializes empty."""
        registry = FlowRegistry()
        assert registry.count() == 0

    def test_register_flow(self):
        """Test registering a flow function."""
        registry = FlowRegistry()

        def my_flow():
            pass

        flow_id = registry.register_flow(my_flow, "my-flow", tags=["test"])
        assert flow_id is not None
        assert registry.count() == 1

    def test_register_flow_with_prefect_decorator(self):
        """Test registering a flow with @flow decorator attributes."""

        def flow_func():
            pass

        flow_func.__name__ = "flow_func"
        flow_func.name = "prefect-flow-name"

        registry = FlowRegistry()
        flow_id = registry.register_flow(flow_func, "my-flow")
        assert flow_id is not None

        metadata = registry.get_flow_metadata(flow_id)
        assert metadata["prefect_name"] == "prefect-flow-name"

    def test_register_flow_non_callable_raises(self):
        """Test that registering non-callable raises ValueError."""
        registry = FlowRegistry()

        with pytest.raises(ValueError, match="must be callable"):
            registry.register_flow("not a function", "test-flow")

    def test_get_flow(self):
        """Test retrieving a registered flow."""
        registry = FlowRegistry()

        def my_flow():
            return "result"

        flow_id = registry.register_flow(my_flow, "my-flow")
        retrieved = registry.get_flow(flow_id)

        assert retrieved is my_flow
        assert retrieved() == "result"

    def test_get_flow_not_found(self):
        """Test retrieving a non-existent flow returns None."""
        registry = FlowRegistry()
        assert registry.get_flow("non-existent-id") is None

    def test_list_flows_all(self):
        """Test listing all registered flows."""
        registry = FlowRegistry()

        def flow1():
            pass

        def flow2():
            pass

        registry.register_flow(flow1, "flow1", tags=["tag1"])
        registry.register_flow(flow2, "flow2", tags=["tag2"])

        flows = registry.list_flows()
        assert len(flows) == 2
        names = [f["name"] for f in flows]
        assert "flow1" in names
        assert "flow2" in names

    def test_list_flows_filter_by_tags(self):
        """Test listing flows filtered by tags."""
        registry = FlowRegistry()

        def flow1():
            pass

        def flow2():
            pass

        def flow3():
            pass

        registry.register_flow(flow1, "flow1", tags=["etl", "production"])
        registry.register_flow(flow2, "flow2", tags=["etl", "staging"])
        registry.register_flow(flow3, "flow3", tags=["reporting", "production"])

        # Filter by single tag
        etl_flows = registry.list_flows(tags=["etl"])
        assert len(etl_flows) == 2

        # Filter by multiple tags (AND logic)
        prod_etl = registry.list_flows(tags=["etl", "production"])
        assert len(prod_etl) == 1
        assert prod_etl[0]["name"] == "flow1"

    def test_list_flows_empty_tags(self):
        """Test listing flows with empty tag list returns all."""
        registry = FlowRegistry()

        def flow1():
            pass

        registry.register_flow(flow1, "flow1", tags=["test"])

        flows = registry.list_flows(tags=[])
        assert len(flows) == 1

    def test_unregister_flow(self):
        """Test unregistering a flow."""
        registry = FlowRegistry()

        def my_flow():
            pass

        flow_id = registry.register_flow(my_flow, "my-flow")
        assert registry.count() == 1

        result = registry.unregister_flow(flow_id)
        assert result is True
        assert registry.count() == 0
        assert registry.get_flow(flow_id) is None

    def test_unregister_flow_not_found(self):
        """Test unregistering a non-existent flow returns False."""
        registry = FlowRegistry()
        result = registry.unregister_flow("non-existent-id")
        assert result is False

    def test_get_flow_metadata(self):
        """Test getting flow metadata."""
        registry = FlowRegistry()

        def my_flow():
            pass

        flow_id = registry.register_flow(my_flow, "my-flow", tags=["etl"])

        metadata = registry.get_flow_metadata(flow_id)
        assert metadata is not None
        assert metadata["name"] == "my-flow"
        assert metadata["tags"] == ["etl"]
        assert metadata["id"] == flow_id
        assert "registered_at" in metadata

    def test_get_flow_metadata_not_found(self):
        """Test getting metadata for non-existent flow returns None."""
        registry = FlowRegistry()
        assert registry.get_flow_metadata("non-existent") is None

    def test_clear(self):
        """Test clearing all flows from registry."""
        registry = FlowRegistry()

        def flow1():
            pass

        def flow2():
            pass

        registry.register_flow(flow1, "flow1")
        registry.register_flow(flow2, "flow2")
        assert registry.count() == 2

        count = registry.clear()
        assert count == 2
        assert registry.count() == 0

    def test_count(self):
        """Test counting registered flows."""
        registry = FlowRegistry()
        assert registry.count() == 0

        def flow():
            pass

        registry.register_flow(flow, "flow1")
        assert registry.count() == 1

        registry.register_flow(flow, "flow2")
        assert registry.count() == 2

    def test_find_by_name(self):
        """Test finding flows by name."""
        registry = FlowRegistry()

        def flow1():
            pass

        def flow2():
            pass

        registry.register_flow(flow1, "my-flow")
        registry.register_flow(flow2, "other-flow")

        matches = registry.find_by_name("my-flow")
        assert len(matches) == 1
        assert matches[0]["name"] == "my-flow"

        no_matches = registry.find_by_name("non-existent")
        assert len(no_matches) == 0

    def test_find_by_prefect_name(self):
        """Test finding flows by Prefect name."""

        def flow_func():
            pass

        flow_func.name = "prefect-flow-name"

        registry = FlowRegistry()
        registry.register_flow(flow_func, "my-flow")

        matches = registry.find_by_prefect_name("prefect-flow-name")
        assert len(matches) == 1


class TestGlobalFlowRegistry:
    """Tests for global flow registry functions."""

    def test_get_flow_registry_singleton(self):
        """Test that get_flow_registry returns singleton."""
        registry1 = get_flow_registry()
        registry2 = get_flow_registry()
        assert registry1 is registry2

    def test_reset_flow_registry(self):
        """Test that reset_flow_registry creates new registry."""
        registry1 = get_flow_registry()

        def flow():
            pass

        registry1.register_flow(flow, "test-flow")
        assert registry1.count() == 1

        reset_flow_registry()

        registry2 = get_flow_registry()
        assert registry2 is not registry1
        assert registry2.count() == 0


# =============================================================================
# PrefectAdapter Schedule Management Tests
# =============================================================================


class TestSetDeploymentSchedule:
    """Tests for set_deployment_schedule method."""

    @pytest.mark.asyncio
    async def test_set_deployment_schedule_cron(self, adapter, mock_prefect_client, mock_deployment):
        """Test setting a cron schedule on a deployment."""
        mock_deployment.schedule = {"cron": "30 14 * * *", "timezone": "UTC", "day_or": True}
        mock_prefect_client.update_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        schedule = CronSchedule(cron="30 14 * * *")
        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.set_deployment_schedule("deployment-123", schedule)

        assert result is not None
        call_kwargs = mock_prefect_client.update_deployment.call_args[1]
        assert "schedule" in call_kwargs

    @pytest.mark.asyncio
    async def test_set_deployment_schedule_interval(self, adapter, mock_prefect_client, mock_deployment):
        """Test setting an interval schedule on a deployment."""
        mock_prefect_client.update_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        schedule = IntervalSchedule(interval_seconds=1800)
        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.set_deployment_schedule("deployment-123", schedule)

        assert result is not None

    @pytest.mark.asyncio
    async def test_set_deployment_schedule_with_helper(self, adapter, mock_prefect_client, mock_deployment):
        """Test setting schedule using helper function."""
        mock_prefect_client.update_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        schedule = create_daily_schedule(hour=9, minute=30)
        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.set_deployment_schedule("deployment-123", schedule)

        assert result is not None
        call_kwargs = mock_prefect_client.update_deployment.call_args[1]
        assert call_kwargs["schedule"]["cron"] == "30 9 * * *"


class TestClearDeploymentSchedule:
    """Tests for clear_deployment_schedule method."""

    @pytest.mark.asyncio
    async def test_clear_deployment_schedule(self, adapter, mock_prefect_client, mock_deployment):
        """Test clearing a deployment's schedule."""
        mock_deployment.schedule = None
        mock_prefect_client.update_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.clear_deployment_schedule("deployment-123")

        assert result is not None
        call_kwargs = mock_prefect_client.update_deployment.call_args[1]
        assert call_kwargs["schedule"] is None

    @pytest.mark.asyncio
    async def test_clear_deployment_schedule_auto_initializes(self, prefect_config, mock_prefect_client, mock_deployment):
        """Test that clear_deployment_schedule auto-initializes."""
        adapter = PrefectAdapter(prefect_config)
        adapter._initialized = False

        mock_deployment.schedule = None
        mock_prefect_client.update_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            await adapter.clear_deployment_schedule("deployment-123")

        assert adapter._initialized is True
        await adapter.shutdown()


class TestGetDeploymentSchedule:
    """Tests for get_deployment_schedule method."""

    @pytest.mark.asyncio
    async def test_get_deployment_schedule_cron(self, adapter, mock_prefect_client, mock_deployment):
        """Test getting a cron schedule from a deployment."""
        mock_deployment.schedule = {"cron": "0 9 * * *", "timezone": "UTC", "day_or": True}
        mock_prefect_client.read_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            schedule = await adapter.get_deployment_schedule("deployment-123")

        assert schedule is not None
        assert isinstance(schedule, CronSchedule)
        assert schedule.cron == "0 9 * * *"
        assert schedule.timezone == "UTC"

    @pytest.mark.asyncio
    async def test_get_deployment_schedule_interval(self, adapter, mock_prefect_client, mock_deployment):
        """Test getting an interval schedule from a deployment."""
        mock_deployment.schedule = {"interval": 3600}
        mock_prefect_client.read_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            schedule = await adapter.get_deployment_schedule("deployment-123")

        assert schedule is not None
        assert isinstance(schedule, IntervalSchedule)
        assert schedule.interval_seconds == 3600

    @pytest.mark.asyncio
    async def test_get_deployment_schedule_with_anchor(self, adapter, mock_prefect_client, mock_deployment):
        """Test getting interval schedule with anchor date."""
        mock_deployment.schedule = {
            "interval": 1800,
            "anchor_date": "2024-01-01T00:30:00",
        }
        mock_prefect_client.read_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            schedule = await adapter.get_deployment_schedule("deployment-123")

        assert schedule is not None
        assert isinstance(schedule, IntervalSchedule)
        assert schedule.anchor_date is not None
        assert schedule.anchor_date.minute == 30

    @pytest.mark.asyncio
    async def test_get_deployment_schedule_rrule(self, adapter, mock_prefect_client, mock_deployment):
        """Test getting an RRULE schedule from a deployment."""
        mock_deployment.schedule = {"rrule": "FREQ=DAILY;BYDAY=MO,WE,FR", "timezone": "UTC"}
        mock_prefect_client.read_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            schedule = await adapter.get_deployment_schedule("deployment-123")

        assert schedule is not None
        assert isinstance(schedule, RRuleSchedule)
        assert schedule.rrule == "FREQ=DAILY;BYDAY=MO,WE,FR"

    @pytest.mark.asyncio
    async def test_get_deployment_schedule_none(self, adapter, mock_prefect_client, mock_deployment):
        """Test getting schedule from deployment with no schedule."""
        mock_deployment.schedule = None
        mock_prefect_client.read_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            schedule = await adapter.get_deployment_schedule("deployment-123")

        assert schedule is None


# =============================================================================
# PrefectAdapter Flow Registry Integration Tests
# =============================================================================


class TestAdapterRegisterFlow:
    """Tests for adapter flow registry methods."""

    def test_register_flow(self, adapter):
        """Test registering a flow through the adapter."""
        def my_flow():
            return "result"

        flow_id = adapter.register_flow(my_flow, "my-flow", tags=["etl"])
        assert flow_id is not None

        # Verify it was registered
        flows = adapter.list_registered_flows()
        assert len(flows) == 1
        assert flows[0]["name"] == "my-flow"
        assert flows[0]["tags"] == ["etl"]

    def test_register_flow_no_tags(self, adapter):
        """Test registering a flow without tags."""
        def my_flow():
            pass

        flow_id = adapter.register_flow(my_flow, "my-flow")
        assert flow_id is not None

        metadata = adapter._flow_registry.get_flow_metadata(flow_id)
        assert metadata["tags"] == []

    def test_list_registered_flows_all(self, adapter):
        """Test listing all registered flows through adapter."""
        def flow1():
            pass

        def flow2():
            pass

        adapter.register_flow(flow1, "flow1", tags=["tag1"])
        adapter.register_flow(flow2, "flow2", tags=["tag2"])

        flows = adapter.list_registered_flows()
        assert len(flows) == 2

    def test_list_registered_flows_filter_tags(self, adapter):
        """Test listing flows filtered by tags through adapter."""
        def flow1():
            pass

        def flow2():
            pass

        adapter.register_flow(flow1, "flow1", tags=["production", "etl"])
        adapter.register_flow(flow2, "flow2", tags=["staging", "etl"])

        prod_flows = adapter.list_registered_flows(tags=["production"])
        assert len(prod_flows) == 1
        assert prod_flows[0]["name"] == "flow1"

    def test_get_registered_flow(self, adapter):
        """Test getting a registered flow through adapter."""
        def my_flow():
            return "executed"

        flow_id = adapter.register_flow(my_flow, "my-flow")
        retrieved = adapter.get_registered_flow(flow_id)

        assert retrieved is my_flow
        assert retrieved() == "executed"

    def test_get_registered_flow_not_found(self, adapter):
        """Test getting non-existent flow returns None."""
        result = adapter.get_registered_flow("non-existent-id")
        assert result is None

    def test_unregister_flow(self, adapter):
        """Test unregistering a flow through adapter."""
        def my_flow():
            pass

        flow_id = adapter.register_flow(my_flow, "my-flow")
        assert len(adapter.list_registered_flows()) == 1

        result = adapter.unregister_flow(flow_id)
        assert result is True
        assert len(adapter.list_registered_flows()) == 0

    def test_unregister_flow_not_found(self, adapter):
        """Test unregistering non-existent flow returns False."""
        result = adapter.unregister_flow("non-existent-id")
        assert result is False

    def test_adapter_registry_lazy_initialization(self, prefect_config):
        """Test that adapter initializes registry lazily."""
        adapter = PrefectAdapter(prefect_config)
        assert adapter._flow_registry is None

        # Accessing registry methods should initialize it
        def my_flow():
            pass

        adapter.register_flow(my_flow, "test-flow")
        assert adapter._flow_registry is not None


# =============================================================================
# Integration Tests (Schedule Helpers with Adapter)
# =============================================================================


class TestScheduleHelpersWithAdapter:
    """Integration tests using schedule helpers with adapter methods."""

    @pytest.mark.asyncio
    async def test_create_deployment_with_daily_schedule_helper(self, adapter, mock_prefect_client, mock_deployment):
        """Test creating deployment with create_daily_schedule helper."""
        mock_flow = MagicMock()
        mock_flow.id = "flow-456"
        mock_prefect_client.read_flow_by_name = AsyncMock(return_value=mock_flow)
        mock_prefect_client.create_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        schedule = create_daily_schedule(hour=9, minute=30, timezone="America/New_York")
        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.create_deployment(
                flow_name="test-flow",
                deployment_name="test-deployment",
                schedule=schedule,
            )

        assert result is not None
        call_kwargs = mock_prefect_client.create_deployment.call_args[1]
        assert call_kwargs["schedule"]["cron"] == "30 9 * * *"
        assert call_kwargs["schedule"]["timezone"] == "America/New_York"

    @pytest.mark.asyncio
    async def test_create_deployment_with_hourly_schedule_helper(self, adapter, mock_prefect_client, mock_deployment):
        """Test creating deployment with create_hourly_schedule helper."""
        mock_flow = MagicMock()
        mock_flow.id = "flow-456"
        mock_prefect_client.read_flow_by_name = AsyncMock(return_value=mock_flow)
        mock_prefect_client.create_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        schedule = create_hourly_schedule(minute=15)
        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.create_deployment(
                flow_name="test-flow",
                deployment_name="test-deployment",
                schedule=schedule,
            )

        assert result is not None
        call_kwargs = mock_prefect_client.create_deployment.call_args[1]
        assert call_kwargs["schedule"]["interval"] == 3600

    @pytest.mark.asyncio
    async def test_update_deployment_with_weekly_schedule_helper(self, adapter, mock_prefect_client, mock_deployment):
        """Test updating deployment with create_weekly_schedule helper."""
        mock_prefect_client.update_deployment = AsyncMock(return_value=mock_deployment)

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=mock_prefect_client)
        context_manager.__aexit__ = AsyncMock()

        schedule = create_weekly_schedule(day_of_week=1, hour=9)  # Monday at 9 AM
        with patch.object(adapter, "_get_client_context", return_value=context_manager):
            result = await adapter.update_deployment(
                deployment_id="deployment-123",
                schedule=schedule,
            )

        assert result is not None
        call_kwargs = mock_prefect_client.update_deployment.call_args[1]
        assert call_kwargs["schedule"]["cron"] == "0 9 * * 1"


# =============================================================================
# Markers
# =============================================================================


# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit
