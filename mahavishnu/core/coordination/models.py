"""
Data models for cross-repository coordination.

This module defines Pydantic models for issues, plans, todos, and dependencies
that enable coordination work across multiple repositories.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class IssueStatus(str, Enum):
    """Status of a cross-repository issue."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Priority(str, Enum):
    """Priority level for issues and todos."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PlanStatus(str, Enum):
    """Status of a cross-repository plan."""

    DRAFT = "draft"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TodoStatus(str, Enum):
    """Status of a task/todo item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DependencyType(str, Enum):
    """Type of dependency between repositories."""

    RUNTIME = "runtime"
    DEVELOPMENT = "development"
    MCP = "mcp"
    TEST = "test"
    DOCUMENTATION = "documentation"


class DependencyStatus(str, Enum):
    """Status of a dependency."""

    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"
    DEPRECATED = "deprecated"


class Milestone(BaseModel):
    """A milestone within a cross-repository plan."""

    id: str = Field(..., description="Unique milestone identifier (e.g., MILESTONE-001)")
    name: str = Field(..., description="Milestone name")
    description: str = Field(..., description="Detailed description of the milestone")
    due: str = Field(..., description="Due date (ISO 8601 format)")
    status: TodoStatus = Field(default=TodoStatus.PENDING, description="Milestone status")
    dependencies: list[str] = Field(
        default_factory=list, description="List of milestone IDs this depends on"
    )
    completion_criteria: list[str] = Field(
        default_factory=list,
        description="Criteria that must be met for completion",
    )
    deliverables: list[str] = Field(
        default_factory=list,
        description="List of deliverables for this milestone",
    )

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}


class CrossRepoIssue(BaseModel):
    """An issue affecting multiple repositories."""

    id: str = Field(..., description="Unique issue identifier (e.g., ISSUE-001)")
    title: str = Field(..., description="Issue title")
    description: str = Field(..., description="Detailed issue description")
    status: IssueStatus = Field(default=IssueStatus.PENDING, description="Current status")
    priority: Priority = Field(default=Priority.MEDIUM, description="Issue priority")
    severity: str = Field(
        default="normal", description="Severity level (bug, feature, migration, etc.)"
    )
    repos: list[str] = Field(..., description="List of repository nicknames affected by this issue")
    created: str = Field(..., description="Creation date (ISO 8601 format)")
    updated: str = Field(..., description="Last update date (ISO 8601 format)")
    target: str | None = Field(default=None, description="Target completion date (ISO 8601 format)")
    dependencies: list[str] = Field(
        default_factory=list, description="List of issue IDs this depends on"
    )
    blocking: list[str] = Field(
        default_factory=list, description="List of issue IDs blocked by this"
    )
    assignee: str | None = Field(default=None, description="Assignee username")
    labels: list[str] = Field(default_factory=list, description="Labels for categorization")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @field_validator("repos")
    @classmethod
    def validate_repos(cls, v: list[str]) -> list[str]:
        """Validate that at least one repository is specified."""
        if not v:
            raise ValueError("At least one repository must be specified")
        return v

    @field_validator("target")
    @classmethod
    def validate_target_date(cls, v: str | None) -> str | None:
        """Validate target date format if provided."""
        if v:
            try:
                datetime.fromisoformat(v)
            except ValueError as e:
                raise ValueError(f"Invalid target date format: {e}") from e
        return v


class CrossRepoPlan(BaseModel):
    """A cross-repository plan or roadmap."""

    id: str = Field(..., description="Unique plan identifier (e.g., PLAN-001)")
    title: str = Field(..., description="Plan title")
    description: str = Field(..., description="Detailed plan description")
    status: PlanStatus = Field(default=PlanStatus.DRAFT, description="Current status")
    repos: list[str] = Field(..., description="List of repository nicknames involved in this plan")
    created: str = Field(..., description="Creation date (ISO 8601 format)")
    updated: str = Field(..., description="Last update date (ISO 8601 format)")
    target: str = Field(..., description="Target completion date (ISO 8601 format)")
    milestones: list[Milestone] = Field(default_factory=list, description="List of milestones")

    @field_validator("repos")
    @classmethod
    def validate_repos(cls, v: list[str]) -> list[str]:
        """Validate that at least one repository is specified."""
        if not v:
            raise ValueError("At least one repository must be specified")
        return v


class CrossRepoTodo(BaseModel):
    """A decomposed task/todo item for execution."""

    id: str = Field(..., description="Unique todo identifier (e.g., TODO-001)")
    task: str = Field(..., description="Task description")
    description: str = Field(..., description="Detailed task description")
    repo: str = Field(..., description="Repository nickname where this task should be executed")
    status: TodoStatus = Field(default=TodoStatus.PENDING, description="Current status")
    priority: Priority = Field(default=Priority.MEDIUM, description="Task priority")
    created: str = Field(..., description="Creation date (ISO 8601 format)")
    updated: str = Field(..., description="Last update date (ISO 8601 format)")
    estimated_hours: float = Field(..., description="Estimated time to complete (in hours)")
    actual_hours: float | None = Field(default=None, description="Actual time spent (in hours)")
    blocked_by: list[str] = Field(
        default_factory=list, description="List of issue/todo IDs blocking this task"
    )
    blocking: list[str] = Field(
        default_factory=list, description="List of todo IDs blocked by this task"
    )
    assignee: str | None = Field(default=None, description="Assignee username")
    labels: list[str] = Field(default_factory=list, description="Labels for categorization")
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Criteria that must be met for completion",
    )

    @field_validator("estimated_hours")
    @classmethod
    def validate_estimated_hours(cls, v: float) -> float:
        """Validate that estimated hours is positive."""
        if v <= 0:
            raise ValueError("Estimated hours must be positive")
        return v


class DependencyValidation(BaseModel):
    """Validation method for a dependency."""

    command: str | None = Field(default=None, description="Shell command to validate dependency")
    expected_pattern: str | None = Field(
        default=None, description="Expected output pattern (regex)"
    )
    health_check: str | None = Field(default=None, description="HTTP health check endpoint")
    expected_status: int | None = Field(default=None, description="Expected HTTP status code")


class Dependency(BaseModel):
    """A dependency between two repositories."""

    id: str = Field(..., description="Unique dependency identifier (e.g., DEP-001)")
    consumer: str = Field(..., description="Consumer repository nickname")
    provider: str = Field(..., description="Provider repository nickname")
    type: DependencyType = Field(..., description="Type of dependency")
    version_constraint: str = Field(..., description="Version constraint (e.g., '>=0.2.0')")
    status: DependencyStatus = Field(
        default=DependencyStatus.UNKNOWN, description="Dependency status"
    )
    created: str = Field(..., description="Creation date (ISO 8601 format)")
    updated: str = Field(..., description="Last update date (ISO 8601 format)")
    notes: str = Field(..., description="Additional notes about this dependency")
    validation: DependencyValidation | None = Field(default=None, description="Validation method")

    @field_validator("consumer", "provider")
    @classmethod
    def validate_repos(cls, v: str) -> str:
        """Validate that repository nickname is not empty."""
        if not v or not v.strip():
            raise ValueError("Repository nickname cannot be empty")
        return v


# Example data for documentation and testing
EXAMPLE_ISSUE = CrossRepoIssue(
    id="ISSUE-001",
    title="Update all repos to Python 3.13",
    description="Comprehensive Python 3.13 migration across ecosystem",
    status=IssueStatus.IN_PROGRESS,
    priority=Priority.HIGH,
    severity="migration",
    repos=["mahavishnu", "session-buddy", "crackerjack", "fastblocks"],
    created="2026-01-31T00:00:00",
    updated="2026-01-31T00:00:00",
    target="2026-02-15T00:00:00",
    dependencies=[],
    blocking=[],
    assignee="les",
    labels=["migration", "python", "breaking"],
    metadata={
        "migration_guide": "docs/python-3.13-migration.md",
        "test_plan": "tests/test_python_3_13_compatibility.py",
    },
)


EXAMPLE_TODO = CrossRepoTodo(
    id="TODO-001",
    task="Implement unified memory service",
    description="Create MahavishnuMemoryIntegration class",
    repo="mahavishnu",
    status=TodoStatus.PENDING,
    priority=Priority.HIGH,
    created="2026-01-31T00:00:00",
    updated="2026-01-31T00:00:00",
    estimated_hours=24.0,
    blocked_by=["ISSUE-001"],
    blocking=["TODO-002", "TODO-003"],
    assignee="les",
    labels=["memory", "integration"],
    acceptance_criteria=[
        "Implements MahavishnuMemoryIntegration class",
        "Passes all unit tests",
        "Documented in docs/MEMORY_INTEGRATION.md",
    ],
)


EXAMPLE_DEPENDENCY = Dependency(
    id="DEP-001",
    consumer="fastblocks",
    provider="oneiric",
    type=DependencyType.RUNTIME,
    version_constraint=">=0.2.0",
    status=DependencyStatus.SATISFIED,
    created="2026-01-15T00:00:00",
    updated="2026-01-30T00:00:00",
    notes="FastBlocks requires Oneiric 0.2.0+ for lifecycle management",
    validation=DependencyValidation(
        command="pip show oneiric | grep Version",
        expected_pattern="^Version: 0\\.2\\.",
    ),
)
