# Prefect Adapter Completion Plan

**Created:** 2026-02-20
**Status:** Draft
**Priority:** High
**Estimated Duration:** 4-6 weeks

## Executive Summary

This plan outlines the implementation of a production-ready Prefect 3.x adapter for Mahavishnu. The current implementation in `mahavishnu/engines/prefect_adapter.py` is partially functional but lacks:

1. Full Prefect 3.x SDK integration (deployments, schedules, work pools)
2. Comprehensive state synchronization with Prefect server
3. Schedule management (cron, interval, event-based)
4. OpenTelemetry instrumentation
5. Robust error handling with structured error codes
6. Complete OrchestratorAdapter interface implementation

## 1. Architecture Overview

### 1.1 Current State

The existing Prefect adapter (`mahavishnu/engines/prefect_adapter.py`) provides:
- Basic flow execution via `@flow` and `@task` decorators
- Simple repository processing with CodeGraphAnalyzer
- Retry logic using tenacity
- Health check stub

**Limitations:**
- No deployment management (create/update/delete deployments)
- No schedule configuration (cron, interval, rrule)
- No work pool integration for distributed execution
- No state synchronization between Mahavishnu and Prefect
- Limited observability (no OpenTelemetry spans)
- No flow run cancellation or pausing
- Missing `adapter_type`, `name`, `capabilities` properties from base interface

### 1.2 Target Architecture

```
+--------------------------------------------------+
|              Mahavishnu Application              |
|  - Configuration (Oneiric patterns)              |
|  - Error Handling (MahavishnuError hierarchy)    |
|  - Observability (OpenTelemetry)                 |
+----------------------+---------------------------+
                       |
                       v
+--------------------------------------------------+
|            PrefectAdapter (New)                  |
|  - Implements OrchestratorAdapter interface      |
|  - Manages Prefect client lifecycle              |
|  - Deployment CRUD operations                    |
|  - Schedule management                           |
|  - State synchronization                         |
|  - OpenTelemetry instrumentation                 |
+----------------------+---------------------------+
                       |
         +-------------+-------------+
         |                           |
         v                           v
+------------------+        +------------------+
| Prefect Server   |        | Prefect Cloud    |
| (Self-hosted)    |        | (SaaS)           |
| - REST API       |        | - REST API       |
| - PostgreSQL DB  |        | - GraphQL API    |
| - UI Dashboard   |        | - Enhanced UI    |
+------------------+        +------------------+
```

### 1.3 Key Components

1. **PrefectAdapter Class** (`mahavishnu/adapters/workflow/prefect_adapter.py`)
   - Enhanced version of current HTTP stub
   - Full Prefect 3.x SDK integration
   - Comprehensive error handling

2. **Prefect Configuration** (`mahavishnu/core/config.py`)
   - Add `PrefectConfig` nested model
   - Support for API URL, work pool, workspace settings

3. **Schedule Models** (`mahavishnu/adapters/workflow/schedules.py`)
   - CronSchedule, IntervalSchedule, RRuleSchedule
   - Pydantic models for type safety

4. **State Synchronization** (`mahavishnu/adapters/workflow/prefect_sync.py`)
   - Bidirectional state sync between Mahavishnu and Prefect
   - Webhook handlers for Prefect events

5. **OpenTelemetry Integration** (`mahavishnu/adapters/workflow/prefect_telemetry.py`)
   - Span creation for all operations
   - Metrics for flow/task execution

## 2. Phase Breakdown

### Phase 1: Core Adapter Enhancement (Week 1-2)

**Goal:** Transform the HTTP stub into a fully functional Prefect SDK adapter.

**Tasks:**

1. **Implement Full OrchestratorAdapter Interface**
   - Add `adapter_type`, `name`, `capabilities` properties
   - Implement proper `execute()` method using Prefect SDK
   - Enhance `get_health()` with actual connectivity checks

2. **Prefect Client Management**
   - Async context manager for client lifecycle
   - Connection pooling and retry configuration
   - Support for both Prefect Server and Prefect Cloud

3. **Error Handling Integration**
   - Map Prefect exceptions to MahavishnuError hierarchy
   - Add Prefect-specific error codes (MHV-400 series)
   - Implement structured recovery guidance

4. **Configuration Enhancement**
   - Create `PrefectConfig` Pydantic model
   - Add to `MahavishnuSettings` in `core/config.py`
   - Support environment variable overrides

**Deliverables:**
- Working PrefectAdapter with full interface implementation
- Configuration schema for Prefect settings
- Unit tests for core functionality

### Phase 2: Deployment Management (Week 2-3)

**Goal:** Enable full CRUD operations for Prefect deployments.

**Tasks:**

1. **Deployment Operations**
   ```python
   async def create_deployment(
       self,
       flow_name: str,
       deployment_name: str,
       schedule: ScheduleConfig | None = None,
       parameters: dict[str, Any] | None = None,
       work_pool_name: str | None = None,
       tags: list[str] | None = None,
   ) -> DeploymentResponse: ...

   async def update_deployment(
       self,
       deployment_id: str,
       **updates: Any,
   ) -> DeploymentResponse: ...

   async def delete_deployment(
       self,
       deployment_id: str,
   ) -> bool: ...

   async def list_deployments(
       self,
       flow_name: str | None = None,
       tags: list[str] | None = None,
   ) -> list[DeploymentResponse]: ...

   async def get_deployment(
       self,
       deployment_id: str,
   ) -> DeploymentResponse: ...
   ```

2. **Flow Registration**
   - Register Mahavishnu workflows as Prefect flows
   - Support for dynamic flow creation
   - Flow versioning support

3. **Deployment Scheduling**
   - Create deployments with schedules
   - Update schedules without redeployment
   - Pause/resume scheduled runs

**Deliverables:**
- Complete deployment management API
- Integration tests with mock Prefect server
- Documentation for deployment operations

### Phase 3: Schedule Management (Week 3-4)

**Goal:** Comprehensive schedule management with multiple schedule types.

**Tasks:**

1. **Schedule Type Support**
   ```python
   # models/schedules.py
   class CronSchedule(BaseModel):
       cron: str  # e.g., "0 9 * * *"
       timezone: str = "UTC"
       day_or: bool = True

   class IntervalSchedule(BaseModel):
       interval_seconds: int
       anchor_date: datetime | None = None

   class RRuleSchedule(BaseModel):
       rrule: str  # iCal RRULE format
       timezone: str = "UTC"
   ```

2. **Schedule CRUD Operations**
   ```python
   async def create_schedule(
       self,
       deployment_id: str,
       schedule: CronSchedule | IntervalSchedule | RRuleSchedule,
   ) -> ScheduleResponse: ...

   async def list_schedules(
       self,
       deployment_id: str,
   ) -> list[ScheduleResponse]: ...

   async def delete_schedule(
       self,
       deployment_id: str,
       schedule_id: str,
   ) -> bool: ...
   ```

3. **Schedule Validation**
   - Validate cron expressions
   - Validate RRule strings
   - Check for schedule conflicts

**Deliverables:**
- Schedule models with Pydantic validation
- Schedule management methods
- Tests for all schedule types

### Phase 4: State Synchronization (Week 4-5)

**Goal:** Bidirectional state sync between Mahavishnu and Prefect.

**Tasks:**

1. **State Mapping**
   ```python
   PREFECT_STATE_MAP = {
       "PENDING": WorkflowStatus.PENDING,
       "RUNNING": WorkflowStatus.RUNNING,
       "COMPLETED": WorkflowStatus.COMPLETED,
       "FAILED": WorkflowStatus.FAILED,
       "CANCELLED": WorkflowStatus.CANCELLED,
       "PAUSED": WorkflowStatus.PAUSED,
       "CRASHED": WorkflowStatus.FAILED,
   }
   ```

2. **State Query Methods**
   ```python
   async def get_flow_run_state(
       self,
       flow_run_id: str,
   ) -> FlowRunState: ...

   async def get_task_run_states(
       self,
       flow_run_id: str,
   ) -> list[TaskRunState]: ...

   async def list_flow_runs(
       self,
       deployment_id: str | None = None,
       state: list[str] | None = None,
       limit: int = 100,
   ) -> list[FlowRunSummary]: ...
   ```

3. **Webhook Integration**
   - Receive Prefect automations webhooks
   - Update Mahavishnu workflow state on Prefect events
   - Emit WebSocket events for real-time updates

4. **Flow Run Operations**
   ```python
   async def cancel_flow_run(
       self,
       flow_run_id: str,
   ) -> bool: ...

   async def pause_flow_run(
       self,
       flow_run_id: str,
   ) -> bool: ...

   async def resume_flow_run(
       self,
       flow_run_id: str,
   ) -> bool: ...

   async def retry_flow_run(
       self,
       flow_run_id: str,
   ) -> str: ...  # Returns new flow run ID
   ```

**Deliverables:**
- State synchronization service
- Webhook handler endpoints
- Flow run control methods
- Integration tests for state transitions

### Phase 5: OpenTelemetry Instrumentation (Week 5)

**Goal:** Comprehensive observability for all Prefect operations.

**Tasks:**

1. **Span Creation**
   ```python
   @tracer.start_as_current_span("prefect.deploy_flow")
   async def deploy_workflow(...):
       span = trace.get_current_span()
       span.set_attribute("workflow.name", workflow_name)
       span.set_attribute("workflow.adapter", "prefect")
       ...

   @tracer.start_as_current_span("prefect.execute_flow")
   async def execute_workflow(...):
       span = trace.get_current_span()
       span.set_attribute("flow.run_id", flow_run_id)
       span.set_attribute("flow.deployment_id", deployment_id)
       ...
   ```

2. **Metrics Collection**
   ```python
   # Counters
   prefect_flow_runs_total = meter.create_counter(
       "prefect.flow.runs.total",
       description="Total number of Prefect flow runs",
   )

   prefect_task_runs_total = meter.create_counter(
       "prefect.task.runs.total",
       description="Total number of Prefect task runs",
   )

   # Histograms
   prefect_flow_duration = meter.create_histogram(
       "prefect.flow.duration",
       description="Duration of Prefect flow runs in seconds",
       unit="s",
   )

   # Gauges
   prefect_active_flows = meter.create_gauge(
       "prefect.flows.active",
       description="Number of active Prefect flow runs",
   )
   ```

3. **Trace Context Propagation**
   - Inject trace context into Prefect flow runs
   - Extract trace context from Prefect webhooks
   - Correlate Mahavishnu traces with Prefect traces

**Deliverables:**
- OpenTelemetry instrumentation module
- Metrics definitions
- Trace correlation logic
- Grafana dashboard for Prefect metrics

### Phase 6: Testing & Documentation (Week 5-6)

**Goal:** Comprehensive test coverage and documentation.

**Tasks:**

1. **Unit Tests**
   - Test all adapter methods in isolation
   - Mock Prefect client responses
   - Test error handling paths

2. **Integration Tests**
   - Test against Prefect Server (Docker)
   - Test against Prefect Cloud (with test workspace)
   - Test state synchronization

3. **Property-Based Tests**
   - Generate random schedule configurations
   - Generate random flow parameters
   - Test invariant properties

4. **Documentation**
   - API reference documentation
   - Usage examples
   - Configuration guide
   - Troubleshooting guide

**Deliverables:**
- 90%+ test coverage
- Integration test suite
- Comprehensive documentation

## 3. API Design

### 3.1 PrefectAdapter Class

```python
from mahavishnu.core.adapters.base import OrchestratorAdapter, AdapterType, AdapterCapabilities
from mahavishnu.core.errors import MahavishnuError, ErrorCode

class PrefectAdapter(OrchestratorAdapter):
    """Production-ready Prefect 3.x adapter for workflow orchestration.

    Features:
    - Full Prefect 3.x SDK integration
    - Deployment management (CRUD)
    - Schedule management (cron, interval, rrule)
    - State synchronization with Prefect server
    - Flow run control (cancel, pause, resume, retry)
    - OpenTelemetry instrumentation
    - Comprehensive error handling

    Configuration (settings/mahavishnu.yaml):
        prefect:
            api_url: "http://localhost:4200"
            api_key: null  # Set via MAHAVISHNU_PREFECT__API_KEY
            workspace: null  # For Prefect Cloud: "account/workspace"
            work_pool: "default"
            timeout_seconds: 300
            max_retries: 3
            enable_telemetry: true
    """

    def __init__(
        self,
        api_url: str = "http://localhost:4200",
        api_key: str | None = None,
        workspace: str | None = None,
        work_pool: str = "default",
        timeout_seconds: int = 300,
        max_retries: int = 3,
        enable_telemetry: bool = True,
    ) -> None: ...

    # === OrchestratorAdapter Interface ===

    @property
    def adapter_type(self) -> AdapterType:
        return AdapterType.PREFECT

    @property
    def name(self) -> str:
        return "prefect"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            can_cancel_workflows=True,
            can_sync_state=True,
            supports_batch_execution=True,
            has_cloud_ui=True,
            supports_multi_agent=False,  # Prefect is not an agent framework
        )

    async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
        """Execute a workflow using Prefect."""
        ...

    async def get_health(self) -> dict[str, Any]:
        """Get adapter health status."""
        ...

    # === Lifecycle Management ===

    async def initialize(self) -> None:
        """Initialize Prefect client and verify connectivity."""
        ...

    async def shutdown(self) -> None:
        """Shutdown Prefect client and cleanup resources."""
        ...

    # === Deployment Management ===

    async def create_deployment(
        self,
        flow_name: str,
        deployment_name: str,
        schedule: "CronSchedule | IntervalSchedule | RRuleSchedule | None" = None,
        parameters: dict[str, Any] | None = None,
        work_pool_name: str | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
        version: str | None = None,
        enforce_parameter_schema: bool = True,
    ) -> "DeploymentResponse": ...

    async def update_deployment(
        self,
        deployment_id: str,
        schedule: "CronSchedule | IntervalSchedule | RRuleSchedule | None" = None,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
        paused: bool | None = None,
    ) -> "DeploymentResponse": ...

    async def delete_deployment(
        self,
        deployment_id: str,
    ) -> bool: ...

    async def get_deployment(
        self,
        deployment_id: str,
    ) -> "DeploymentResponse": ...

    async def get_deployment_by_name(
        self,
        flow_name: str,
        deployment_name: str,
    ) -> "DeploymentResponse": ...

    async def list_deployments(
        self,
        flow_name: str | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list["DeploymentResponse"]: ...

    # === Flow Run Management ===

    async def trigger_flow_run(
        self,
        deployment_id: str,
        parameters: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> "FlowRunResponse": ...

    async def get_flow_run(
        self,
        flow_run_id: str,
    ) -> "FlowRunResponse": ...

    async def list_flow_runs(
        self,
        deployment_id: str | None = None,
        state: list[str] | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list["FlowRunResponse"]: ...

    async def cancel_flow_run(
        self,
        flow_run_id: str,
    ) -> bool: ...

    async def pause_flow_run(
        self,
        flow_run_id: str,
    ) -> bool: ...

    async def resume_flow_run(
        self,
        flow_run_id: str,
    ) -> bool: ...

    async def retry_flow_run(
        self,
        flow_run_id: str,
    ) -> str:  # Returns new flow run ID
        ...

    # === Schedule Management ===

    async def set_deployment_schedule(
        self,
        deployment_id: str,
        schedule: "CronSchedule | IntervalSchedule | RRuleSchedule",
    ) -> "ScheduleResponse": ...

    async def pause_deployment_schedule(
        self,
        deployment_id: str,
        schedule_id: str,
    ) -> bool: ...

    async def resume_deployment_schedule(
        self,
        deployment_id: str,
        schedule_id: str,
    ) -> bool: ...

    # === Work Pool Management ===

    async def list_work_pools(self) -> list["WorkPoolResponse"]: ...

    async def get_work_pool(self, work_pool_name: str) -> "WorkPoolResponse": ...

    # === State Synchronization ===

    async def sync_state_from_prefect(
        self,
        flow_run_id: str,
    ) -> dict[str, Any]:
        """Pull state from Prefect and update local workflow state."""
        ...

    async def get_flow_run_logs(
        self,
        flow_run_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list["LogEntry"]: ...
```

### 3.2 Schedule Models

```python
# mahavishnu/adapters/workflow/schedules.py

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator
import croniter

class CronSchedule(BaseModel):
    """Cron-based schedule configuration."""

    type: Literal["cron"] = "cron"
    cron: str = Field(..., description="Cron expression (e.g., '0 9 * * *')")
    timezone: str = Field(default="UTC", description="Timezone for schedule")
    day_or: bool = Field(default=True, description="Use day OR logic for cron")

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        """Validate cron expression syntax."""
        try:
            croniter.croniter(v)
        except (ValueError, croniter.CroniterError) as e:
            raise ValueError(f"Invalid cron expression: {v}. Error: {e}")
        return v


class IntervalSchedule(BaseModel):
    """Interval-based schedule configuration."""

    type: Literal["interval"] = "interval"
    interval_seconds: int = Field(
        ...,
        ge=1,
        le=31536000,  # Max 1 year
        description="Interval in seconds between runs"
    )
    anchor_date: datetime | None = Field(
        default=None,
        description="Anchor date for interval alignment"
    )


class RRuleSchedule(BaseModel):
    """RRule-based schedule configuration (iCalendar recurrence rule)."""

    type: Literal["rrule"] = "rrule"
    rrule: str = Field(..., description="iCal RRULE string (e.g., 'FREQ=DAILY;BYDAY=MO,WE,FR')")
    timezone: str = Field(default="UTC", description="Timezone for schedule")

    @field_validator("rrule")
    @classmethod
    def validate_rrule(cls, v: str) -> str:
        """Validate RRULE syntax."""
        from dateutil.rrule import rrulestr
        try:
            rrulestr(v)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid RRULE expression: {v}. Error: {e}")
        return v


# Union type for all schedule types
ScheduleConfig = CronSchedule | IntervalSchedule | RRuleSchedule
```

### 3.3 Response Models

```python
# mahavishnu/adapters/workflow/responses.py

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field

class DeploymentResponse(BaseModel):
    """Response model for Prefect deployment."""

    id: str
    name: str
    flow_id: str
    flow_name: str
    description: str | None = None
    version: str | None = None
    tags: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    schedule: dict[str, Any] | None = None
    work_pool_name: str | None = None
    work_queue_name: str | None = None
    paused: bool = False
    created_at: datetime
    updated_at: datetime | None = None


class FlowRunResponse(BaseModel):
    """Response model for Prefect flow run."""

    id: str
    name: str
    flow_id: str
    deployment_id: str | None = None
    state_type: str
    state_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    total_run_time_seconds: float | None = None
    estimated_run_time_seconds: float | None = None
    work_queue_name: str | None = None


class ScheduleResponse(BaseModel):
    """Response model for Prefect schedule."""

    id: str
    deployment_id: str
    schedule: dict[str, Any]
    active: bool
    created_at: datetime
    updated_at: datetime | None = None


class WorkPoolResponse(BaseModel):
    """Response model for Prefect work pool."""

    name: str
    type: str
    description: str | None = None
    is_paused: bool = False
    concurrency_limit: int | None = None
    created_at: datetime
    updated_at: datetime | None = None


class LogEntry(BaseModel):
    """Log entry from Prefect flow run."""

    timestamp: datetime
    level: str
    message: str
    task_run_id: str | None = None
    flow_run_id: str
```

## 4. Code Structure

### 4.1 Files to Create/Modify

```
mahavishnu/
  adapters/
    workflow/
      __init__.py                  # Export PrefectAdapter
      prefect_adapter.py           # Main adapter implementation (enhance existing)
      schedules.py                 # Schedule models (NEW)
      responses.py                 # Response models (NEW)
      prefect_sync.py              # State synchronization (NEW)
      prefect_telemetry.py         # OpenTelemetry integration (NEW)
      errors.py                    # Prefect-specific errors (NEW)
  core/
    config.py                      # Add PrefectConfig (MODIFY)
  engines/
    prefect_adapter.py             # Keep as legacy/shim (MODIFY - add deprecation warning)

tests/
  unit/
    adapters/
      workflow/
        test_prefect_adapter.py    # Unit tests (NEW)
        test_schedules.py          # Schedule validation tests (NEW)
  integration/
    test_prefect_integration.py    # Integration tests with mock server (NEW)
  property/
    test_prefect_properties.py     # Property-based tests (NEW)

docs/
  adapters/
    prefect.md                     # Adapter documentation (NEW)
```

### 4.2 Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| `prefect_adapter.py` | Main adapter implementing OrchestratorAdapter |
| `schedules.py` | Schedule type definitions with validation |
| `responses.py` | Pydantic response models for type safety |
| `prefect_sync.py` | State synchronization logic |
| `prefect_telemetry.py` | OpenTelemetry spans and metrics |
| `errors.py` | Prefect-specific error codes and handling |

## 5. Prefect SDK Integration

### 5.1 Key Prefect 3.x Concepts

1. **Deployments**: Deployed flows with schedules and parameters
2. **Flow Runs**: Individual executions of a deployment
3. **Task Runs**: Individual task executions within a flow run
4. **Work Pools**: Groups of workers for execution
5. **Work Queues**: Priority queues within work pools
6. **Schedules**: Cron, interval, or rrule-based triggers
7. **Automations**: Event-driven workflows and notifications

### 5.2 Prefect Client Usage

```python
from prefect.client.orchestration import get_client
from prefect.client.schemas import FlowRun, Deployment

async def example_usage():
    async with get_client() as client:
        # Create deployment
        deployment = await client.create_deployment(
            flow_id="my-flow-id",
            name="production-deployment",
            schedule={"cron": "0 9 * * *"},
            parameters={"env": "production"},
        )

        # Trigger flow run
        flow_run = await client.create_flow_run_from_deployment(
            deployment_id=deployment.id,
            parameters={"additional": "params"},
        )

        # Wait for completion
        flow_run = await client.wait_for_flow_run(flow_run.id)

        # Get logs
        logs = await client.read_flow_run_logs(flow_run.id)
```

### 5.3 Prefect Cloud vs Server

| Feature | Prefect Server | Prefect Cloud |
|---------|---------------|---------------|
| API URL | `http://localhost:4200` | `https://api.prefect.cloud` |
| Auth | Optional API key | Required API key |
| Workspace | N/A | `{account}/{workspace}` |
| Rate Limits | None | Per-tier limits |
| Automations | Limited | Full support |
| Cost | Free | Tiered pricing |

## 6. Testing Strategy

### 6.1 Unit Tests

Test all adapter methods with mocked Prefect client:

```python
# tests/unit/adapters/workflow/test_prefect_adapter.py

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from mahavishnu.adapters.workflow.prefect_adapter import PrefectAdapter
from mahavishnu.adapters.workflow.schedules import CronSchedule

@pytest.fixture
def mock_prefect_client():
    """Create a mock Prefect client."""
    with patch("prefect.client.orchestration.get_client") as mock:
        client = AsyncMock()
        mock.return_value.__aenter__.return_value = client
        yield client

@pytest.fixture
async def adapter():
    """Create adapter instance for testing."""
    adapter = PrefectAdapter(api_url="http://localhost:4200")
    await adapter.initialize()
    return adapter

class TestPrefectAdapter:
    """Unit tests for PrefectAdapter."""

    @pytest.mark.asyncio
    async def test_initialize_success(self, mock_prefect_client):
        """Test successful initialization."""
        mock_prefect_client.read_health.return_value = {"status": "ok"}

        adapter = PrefectAdapter()
        await adapter.initialize()

        assert adapter._client is not None

    @pytest.mark.asyncio
    async def test_create_deployment(self, adapter, mock_prefect_client):
        """Test deployment creation."""
        mock_prefect_client.create_deployment.return_value = MagicMock(
            id="dep-123",
            name="test-deployment",
            flow_id="flow-456",
        )

        schedule = CronSchedule(cron="0 9 * * *")
        result = await adapter.create_deployment(
            flow_name="my-flow",
            deployment_name="test-deployment",
            schedule=schedule,
        )

        assert result.id == "dep-123"
        mock_prefect_client.create_deployment.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_flow_run(self, adapter, mock_prefect_client):
        """Test flow run triggering."""
        mock_prefect_client.create_flow_run_from_deployment.return_value = MagicMock(
            id="run-789",
            state_type="PENDING",
        )

        result = await adapter.trigger_flow_run(
            deployment_id="dep-123",
            parameters={"key": "value"},
        )

        assert result.id == "run-789"

    @pytest.mark.asyncio
    async def test_error_handling(self, adapter, mock_prefect_client):
        """Test error handling with PrefectError."""
        from prefect.exceptions import PrefectHTTPStatusError

        mock_prefect_client.create_deployment.side_effect = PrefectHTTPStatusError(
            "Not found",
            response=MagicMock(status_code=404),
        )

        with pytest.raises(PrefectError) as exc_info:
            await adapter.create_deployment(
                flow_name="missing-flow",
                deployment_name="test",
            )

        assert exc_info.value.error_code == ErrorCode.PREFECT_DEPLOYMENT_NOT_FOUND
```

### 6.2 Integration Tests

Test against a real Prefect server (Docker):

```python
# tests/integration/test_prefect_integration.py

import pytest
import docker
import httpx
from mahavishnu.adapters.workflow.prefect_adapter import PrefectAdapter

@pytest.fixture(scope="module")
def prefect_server():
    """Start Prefect server in Docker for integration tests."""
    client = docker.from_env()
    container = client.containers.run(
        "prefecthq/prefect:3-latest",
        command="prefect server start --host 0.0.0.0",
        ports={"4200/tcp": 4200},
        detach=True,
        remove=True,
    )

    # Wait for server to be ready
    for _ in range(30):
        try:
            httpx.get("http://localhost:4200/api/health")
            break
        except httpx.ConnectError:
            import time
            time.sleep(1)

    yield "http://localhost:4200"

    container.stop()

@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_workflow_lifecycle(prefect_server):
    """Test complete workflow lifecycle."""
    adapter = PrefectAdapter(api_url=prefect_server)
    await adapter.initialize()

    # Create deployment
    deployment = await adapter.create_deployment(
        flow_name="test-flow",
        deployment_name="integration-test",
        schedule=CronSchedule(cron="0 9 * * *"),
    )

    # Trigger flow run
    flow_run = await adapter.trigger_flow_run(
        deployment_id=deployment.id,
        parameters={"test": True},
    )

    # Wait for completion
    result = await adapter.wait_for_flow_run(flow_run.id, timeout=60)

    assert result.state_type == "COMPLETED"

    # Cleanup
    await adapter.delete_deployment(deployment.id)
```

### 6.3 Property-Based Tests

Test schedule validation with Hypothesis:

```python
# tests/property/test_prefect_properties.py

from hypothesis import given, strategies as st
from mahavishnu.adapters.workflow.schedules import CronSchedule, IntervalSchedule

@given(st.builds(CronSchedule))
def test_cron_schedule_validation(schedule: CronSchedule):
    """Test that all generated cron schedules are valid."""
    assert schedule.type == "cron"
    assert schedule.timezone is not None

@given(
    interval_seconds=st.integers(min_value=1, max_value=31536000)
)
def test_interval_schedule_validation(interval_seconds: int):
    """Test interval schedule with random values."""
    schedule = IntervalSchedule(interval_seconds=interval_seconds)
    assert schedule.interval_seconds == interval_seconds
    assert schedule.type == "interval"
```

## 7. Configuration

### 7.1 PrefectConfig Model

```python
# Add to mahavishnu/core/config.py

class PrefectConfig(BaseModel):
    """Prefect adapter configuration."""

    enabled: bool = Field(
        default=True,
        description="Enable Prefect adapter for workflow orchestration",
    )
    api_url: str = Field(
        default="http://localhost:4200",
        description="Prefect API URL (Server or Cloud)",
    )
    api_key: str | None = Field(
        default=None,
        description="Prefect API key (required for Prefect Cloud)",
    )
    workspace: str | None = Field(
        default=None,
        description="Prefect Cloud workspace (format: account/workspace)",
    )
    work_pool: str = Field(
        default="default",
        description="Default work pool for flow execution",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Default timeout for API operations (10-3600)",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed operations",
    )
    retry_delay_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Base delay between retries (exponential backoff)",
    )
    enable_telemetry: bool = Field(
        default=True,
        description="Enable OpenTelemetry instrumentation",
    )
    sync_interval_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Interval for state synchronization (10-600)",
    )
    webhook_secret: str | None = Field(
        default=None,
        description="Secret for validating Prefect webhooks",
    )

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_cloud_config(self) -> "PrefectConfig":
        """Validate configuration for Prefect Cloud."""
        if self.workspace and not self.api_key:
            raise ValueError(
                "api_key must be set when workspace is specified. "
                "Set via MAHAVISHNU_PREFECT__API_KEY environment variable."
            )
        return self
```

### 7.2 YAML Configuration

```yaml
# settings/mahavishnu.yaml

# Prefect adapter configuration
prefect:
  enabled: true
  api_url: "http://localhost:4200"  # Use Prefect Cloud: "https://api.prefect.cloud"
  # api_key: null  # Set via MAHAVISHNU_PREFECT__API_KEY
  # workspace: "my-account/my-workspace"  # Required for Prefect Cloud
  work_pool: "default"
  timeout_seconds: 300
  max_retries: 3
  retry_delay_seconds: 1.0
  enable_telemetry: true
  sync_interval_seconds: 60
  # webhook_secret: null  # Set via MAHAVISHNU_PREFECT__WEBHOOK_SECRET
```

### 7.3 Environment Variables

```bash
# Prefect Cloud configuration
export MAHAVISHNU_PREFECT__API_URL="https://api.prefect.cloud"
export MAHAVISHNU_PREFECT__API_KEY="pnu_xxxxxxxxxxxxx"
export MAHAVISHNU_PREFECT__WORKSPACE="my-account/my-workspace"

# Webhook secret for state synchronization
export MAHAVISHNU_PREFECT__WEBHOOK_SECRET="your-webhook-secret"
```

## 8. Dependencies

### 8.1 Required Packages

```toml
# pyproject.toml (already in [project.optional-dependencies.prefect])

prefect = [
    # Core Prefect SDK (already present)
    "prefect>=3.6.13",

    # Additional dependencies for enhanced functionality
    "croniter>=2.0.0",        # Cron expression parsing and validation
    "python-dateutil>=2.9.0", # RRule parsing (part of Prefect deps)
]
```

### 8.2 Version Compatibility

| Package | Minimum | Tested | Notes |
|---------|---------|--------|-------|
| prefect | 3.6.0 | 3.6.13 | Prefect 3.x required |
| croniter | 2.0.0 | 2.0.5 | For cron validation |
| python-dateutil | 2.9.0 | 2.9.0 | For rrule support |
| httpx | 0.27.0 | 0.28.0 | Already in dependencies |
| pydantic | 2.12.0 | 2.12.5 | Already in dependencies |

## 9. Risk Assessment

### 9.1 Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Prefect API changes | High | Low | Use stable SDK methods, version pinning |
| State sync complexity | Medium | Medium | Thorough testing, rollback support |
| Prefect Cloud rate limits | Medium | Medium | Implement backoff, caching |
| OpenTelemetry overhead | Low | Low | Make telemetry optional |
| Work pool scaling issues | Medium | Low | Support multiple work pools |

### 9.2 Complexity Areas

1. **State Synchronization** (High complexity)
   - Bidirectional sync between systems
   - Conflict resolution strategies
   - Webhook reliability

2. **Schedule Management** (Medium complexity)
   - Multiple schedule types
   - Validation across timezones
   - Schedule conflicts

3. **Error Handling** (Medium complexity)
   - Mapping Prefect errors to Mahavishnu errors
   - Recovery guidance generation
   - Partial failure handling

### 9.3 Mitigation Strategies

1. **Phased Implementation**
   - Start with core functionality
   - Add advanced features incrementally
   - Continuous testing throughout

2. **Comprehensive Testing**
   - Unit tests for all components
   - Integration tests with mock server
   - Property-based tests for schedules

3. **Documentation**
   - Clear API documentation
   - Usage examples
   - Troubleshooting guides

## 10. Success Criteria

### 10.1 Functional Requirements

- [ ] Full OrchestratorAdapter interface implementation
- [ ] Deployment CRUD operations working
- [ ] All schedule types supported (cron, interval, rrule)
- [ ] Flow run management (trigger, cancel, pause, resume, retry)
- [ ] State synchronization with Prefect server
- [ ] OpenTelemetry instrumentation complete
- [ ] Error handling with MahavishnuError codes

### 10.2 Quality Requirements

- [ ] 90%+ test coverage
- [ ] All tests passing (unit, integration, property)
- [ ] No security vulnerabilities (bandit scan)
- [ ] Type checking passing (pyright)
- [ ] Linting passing (ruff)
- [ ] Code complexity < 15 per function

### 10.3 Performance Requirements

- [ ] API operations complete within 5 seconds
- [ ] Support 100 concurrent flow runs
- [ ] State sync completes within 10 seconds
- [ ] Memory usage < 500MB under load

### 10.4 Documentation Requirements

- [ ] API reference complete
- [ ] Configuration guide written
- [ ] Usage examples provided
- [ ] Troubleshooting guide available
- [ ] Architecture decision record (ADR) created

## 11. Timeline

| Week | Phase | Deliverables |
|------|-------|--------------|
| 1-2 | Phase 1: Core Enhancement | Working adapter, configuration |
| 2-3 | Phase 2: Deployments | Deployment management API |
| 3-4 | Phase 3: Scheduling | Schedule management |
| 4-5 | Phase 4: State Sync | State synchronization service |
| 5 | Phase 5: Telemetry | OpenTelemetry integration |
| 5-6 | Phase 6: Testing | Test suite, documentation |

## 12. References

- [Prefect 3.x Documentation](https://docs.prefect.io/3.0/)
- [Prefect Python SDK](https://docs.prefect.io/3.0/api-ref/prefect/)
- [Prefect REST API](https://docs.prefect.io/3.0/api-ref/rest-api/)
- [Temporal Workflow Patterns](../docs/patterns/temporal-workflows.md)
- [Mahavishnu ADRs](../docs/adr/)
- [MCP Tools Specification](./MCP_TOOLS_SPECIFICATION.md)
