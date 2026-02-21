"""Response models for Prefect API responses.

This module provides Pydantic models for type-safe handling of Prefect API responses.
These models are used by PrefectAdapter methods to return structured data.

Example:
    ```python
    from mahavishnu.engines.prefect_models import DeploymentResponse

    deployment: DeploymentResponse = await adapter.create_deployment(...)
    print(f"Created deployment: {deployment.name} (ID: {deployment.id})")
    ```
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DeploymentResponse(BaseModel):
    """Response model for Prefect deployment.

    Represents a deployed flow with its configuration including schedule,
    parameters, and work pool assignment.

    Attributes:
        id: Unique deployment identifier (UUID)
        name: Deployment name
        flow_name: Name of the deployed flow
        flow_id: Unique identifier of the flow
        schedule: Schedule configuration (cron/interval/rrule)
        parameters: Default parameters for flow runs
        work_pool_name: Name of the work pool for execution
        work_queue_name: Name of the work queue within the pool
        paused: Whether the deployment is paused
        tags: List of tags for organization
        description: Human-readable description
        version: Deployment version string
        created_at: Timestamp when deployment was created
        updated_at: Timestamp when deployment was last updated

    Example:
        ```python
        deployment = DeploymentResponse(
            id="abc-123",
            name="production-deployment",
            flow_name="my-flow",
            flow_id="flow-456",
            schedule={"cron": "0 9 * * *"},
            parameters={"env": "prod"},
            work_pool_name="default",
            paused=False,
            created_at=datetime.now(),
        )
        ```
    """

    id: str = Field(..., description="Unique deployment identifier (UUID)")
    name: str = Field(..., description="Deployment name")
    flow_name: str = Field(..., description="Name of the deployed flow")
    flow_id: str = Field(..., description="Unique identifier of the flow")
    schedule: dict[str, Any] | None = Field(
        default=None,
        description="Schedule configuration (cron/interval/rrule)",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Default parameters for flow runs",
    )
    work_pool_name: str | None = Field(
        default=None,
        description="Name of the work pool for execution",
    )
    work_queue_name: str | None = Field(
        default=None,
        description="Name of the work queue within the pool",
    )
    paused: bool = Field(
        default=False,
        description="Whether the deployment is paused",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="List of tags for organization",
    )
    description: str | None = Field(
        default=None,
        description="Human-readable description",
    )
    version: str | None = Field(
        default=None,
        description="Deployment version string",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when deployment was created",
    )
    updated_at: datetime | None = Field(
        default=None,
        description="Timestamp when deployment was last updated",
    )


class FlowRunResponse(BaseModel):
    """Response model for Prefect flow run.

    Represents a single execution of a deployed flow.

    Attributes:
        id: Unique flow run identifier (UUID)
        name: Flow run name
        flow_id: ID of the flow being executed
        deployment_id: ID of the deployment (if from deployment)
        state_type: Current state type (PENDING, RUNNING, COMPLETED, FAILED, etc.)
        state_name: Human-readable state name
        parameters: Parameters for this flow run
        tags: List of tags for this run
        created_at: Timestamp when run was created
        updated_at: Timestamp when run was last updated
        start_time: Timestamp when run started executing
        end_time: Timestamp when run completed
        total_run_time_seconds: Total execution time in seconds
        estimated_run_time_seconds: Estimated total run time
        work_queue_name: Name of the work queue executing this run

    Example:
        ```python
        flow_run = await adapter.get_flow_run("run-123")
        if flow_run.state_type == "COMPLETED":
            print(f"Run completed in {flow_run.total_run_time_seconds}s")
        ```
    """

    id: str = Field(..., description="Unique flow run identifier (UUID)")
    name: str = Field(..., description="Flow run name")
    flow_id: str = Field(..., description="ID of the flow being executed")
    deployment_id: str | None = Field(
        default=None,
        description="ID of the deployment (if from deployment)",
    )
    state_type: str = Field(
        ...,
        description="Current state type (PENDING, RUNNING, COMPLETED, FAILED, etc.)",
    )
    state_name: str = Field(..., description="Human-readable state name")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters for this flow run",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="List of tags for this run",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when run was created",
    )
    updated_at: datetime | None = Field(
        default=None,
        description="Timestamp when run was last updated",
    )
    start_time: datetime | None = Field(
        default=None,
        description="Timestamp when run started executing",
    )
    end_time: datetime | None = Field(
        default=None,
        description="Timestamp when run completed",
    )
    total_run_time_seconds: float | None = Field(
        default=None,
        description="Total execution time in seconds",
    )
    estimated_run_time_seconds: float | None = Field(
        default=None,
        description="Estimated total run time",
    )
    work_queue_name: str | None = Field(
        default=None,
        description="Name of the work queue executing this run",
    )


class ScheduleResponse(BaseModel):
    """Response model for Prefect deployment schedule.

    Represents a schedule attached to a deployment.

    Attributes:
        id: Unique schedule identifier (UUID)
        deployment_id: ID of the deployment this schedule belongs to
        schedule: Schedule configuration dictionary
        active: Whether the schedule is active
        created_at: Timestamp when schedule was created
        updated_at: Timestamp when schedule was last updated

    Example:
        ```python
        schedules = await adapter.list_schedules("deployment-123")
        for schedule in schedules:
            if schedule.active:
                print(f"Active schedule: {schedule.schedule}")
        ```
    """

    id: str = Field(..., description="Unique schedule identifier (UUID)")
    deployment_id: str = Field(
        ...,
        description="ID of the deployment this schedule belongs to",
    )
    schedule: dict[str, Any] = Field(
        ...,
        description="Schedule configuration dictionary",
    )
    active: bool = Field(..., description="Whether the schedule is active")
    created_at: datetime = Field(
        ...,
        description="Timestamp when schedule was created",
    )
    updated_at: datetime | None = Field(
        default=None,
        description="Timestamp when schedule was last updated",
    )


class WorkPoolResponse(BaseModel):
    """Response model for Prefect work pool.

    Represents a pool of workers that can execute flow runs.

    Attributes:
        name: Work pool name
        type: Work pool type (process, kubernetes, etc.)
        description: Human-readable description
        is_paused: Whether the pool is paused
        concurrency_limit: Maximum concurrent flow runs
        created_at: Timestamp when pool was created
        updated_at: Timestamp when pool was last updated

    Example:
        ```python
        pools = await adapter.list_work_pools()
        for pool in pools:
            if not pool.is_paused:
                print(f"Active pool: {pool.name} (limit: {pool.concurrency_limit})")
        ```
    """

    name: str = Field(..., description="Work pool name")
    type: str = Field(..., description="Work pool type (process, kubernetes, etc.)")
    description: str | None = Field(
        default=None,
        description="Human-readable description",
    )
    is_paused: bool = Field(
        default=False,
        description="Whether the pool is paused",
    )
    concurrency_limit: int | None = Field(
        default=None,
        description="Maximum concurrent flow runs",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when pool was created",
    )
    updated_at: datetime | None = Field(
        default=None,
        description="Timestamp when pool was last updated",
    )


class LogEntry(BaseModel):
    """Log entry from a Prefect flow or task run.

    Represents a single log message from flow/task execution.

    Attributes:
        timestamp: When the log was created
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        message: Log message content
        flow_run_id: ID of the flow run
        task_run_id: ID of the task run (if from a task)

    Example:
        ```python
        logs = await adapter.get_flow_run_logs("run-123")
        for log in logs:
            if log.level == "ERROR":
                print(f"[{log.timestamp}] {log.message}")
        ```
    """

    timestamp: datetime = Field(..., description="When the log was created")
    level: str = Field(
        ...,
        description="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    message: str = Field(..., description="Log message content")
    flow_run_id: str = Field(..., description="ID of the flow run")
    task_run_id: str | None = Field(
        default=None,
        description="ID of the task run (if from a task)",
    )


__all__ = [
    "DeploymentResponse",
    "FlowRunResponse",
    "ScheduleResponse",
    "WorkPoolResponse",
    "LogEntry",
]
