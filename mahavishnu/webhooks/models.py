"""Pydantic models for webhook validation.

This module provides secure Pydantic models for validating webhook requests
from external platforms like OpenClaw, preventing injection attacks and
ensuring type safety.

Design Reference:
- docs/plans/PRE_IMPLEMENTATION_CHECKLIST.md (P0-3)
- Security: Path traversal prevention, input validation

Usage:
    from mahavishnu.webhooks.models import OpenClawSweepRequest

    # Valid request
    req = OpenClawSweepRequest(tag="backend", adapter="agno")
    assert req.tag == "backend"

    # Invalid request (should raise ValidationError)
    try:
        OpenClawSweepRequest(tag="../../../etc/passwd", adapter="agno")
        assert False, "Should have raised"
    except ValueError:
        pass
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from mahavishnu.core.metrics_schema import AdapterType

# Valid tag pattern: alphanumeric, underscores, hyphens only
TAG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Valid repo path pattern: alphanumeric, underscores, hyphens, slashes, dots
REPO_PATH_PATTERN = re.compile(r"^[a-zA-Z0-9_/.-]+$")


class WebhookStatus(StrEnum):
    """Status of webhook processing."""

    SUCCESS = "success"
    ERROR = "error"
    PENDING = "pending"
    ACCEPTED = "accepted"


class OpenClawSweepRequest(BaseModel):
    """Request model for OpenClaw sweep webhook.

    Validates:
    - tag: Must be alphanumeric with underscores/hyphens only (no path traversal)
    - adapter: Must be valid AdapterType enum value
    - task_description: Optional task description
    - priority: Optional priority level

    Security:
    - Prevents path traversal attacks via tag field
    - Validates adapter against known enum values
    """

    tag: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Repository tag to sweep (alphanumeric, underscores, hyphens only)",
        examples=["backend", "python", "frontend-react"],
    )
    adapter: AdapterType = Field(
        default=AdapterType.AGNO,
        description="Orchestration adapter to use for the sweep",
    )
    task_description: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional description of the sweep task",
    )
    priority: str = Field(
        default="normal",
        pattern="^(low|normal|high|critical)$",
        description="Task priority level",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, only simulate the sweep without making changes",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for the sweep",
    )

    @field_validator("tag")
    @classmethod
    def validate_tag(cls, v: str) -> str:
        """Validate tag format to prevent path traversal.

        Args:
            v: Tag value to validate

        Returns:
            Validated tag value

        Raises:
            ValueError: If tag contains invalid characters
        """
        if not TAG_PATTERN.match(v):
            raise ValueError(
                f"Invalid tag '{v}'. Must contain only alphanumeric characters, "
                "underscores, and hyphens (no path traversal allowed)"
            )
        return v

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Limit metadata size to prevent DoS.

        Args:
            v: Metadata dictionary to validate

        Returns:
            Validated metadata

        Raises:
            ValueError: If metadata is too large
        """
        if len(str(v)) > 4096:
            raise ValueError("Metadata exceeds maximum size of 4KB")
        return v


class OpenClawWorkflowRequest(BaseModel):
    """Request model for OpenClaw workflow webhook.

    Validates:
    - repos: List of repository paths (validated for path traversal)
    - adapter: Must be valid AdapterType enum value
    - workflow_type: Type of workflow to execute

    Security:
    - Prevents path traversal attacks via repo paths
    - Limits number of repos to prevent DoS
    """

    repos: list[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of repository paths to include in workflow",
    )
    adapter: AdapterType = Field(
        default=AdapterType.PREFECT,
        description="Orchestration adapter to use for the workflow",
    )
    workflow_type: str = Field(
        default="code_sweep",
        max_length=64,
        description="Type of workflow to execute",
    )
    task_description: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional description of the workflow task",
    )
    parallel: bool = Field(
        default=True,
        description="Execute workflow in parallel across repos",
    )
    fail_fast: bool = Field(
        default=False,
        description="Stop workflow on first failure",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Workflow timeout in seconds (60-3600)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for the workflow",
    )

    @field_validator("repos")
    @classmethod
    def validate_repos(cls, v: list[str]) -> list[str]:
        """Validate repository paths to prevent path traversal.

        Args:
            v: List of repository paths to validate

        Returns:
            Validated list of repository paths

        Raises:
            ValueError: If any repo path contains invalid characters
        """
        for repo in v:
            # Check for path traversal patterns
            if ".." in repo or not REPO_PATH_PATTERN.match(repo):
                raise ValueError(
                    f"Invalid repository path '{repo}'. Must contain only "
                    "alphanumeric characters, underscores, hyphens, slashes, "
                    "and dots (no path traversal allowed)"
                )
            # Check for absolute path attempts
            if repo.startswith("/") or repo.startswith("~"):
                raise ValueError(f"Invalid repository path '{repo}'. Absolute paths not allowed")
        return v

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Limit metadata size to prevent DoS.

        Args:
            v: Metadata dictionary to validate

        Returns:
            Validated metadata

        Raises:
            ValueError: If metadata is too large
        """
        if len(str(v)) > 4096:
            raise ValueError("Metadata exceeds maximum size of 4KB")
        return v


class WebhookResponse(BaseModel):
    """Standard response model for webhook endpoints.

    Provides structured response with:
    - status: Success/error/pending status
    - message: Human-readable message
    - workflow_id: Optional workflow identifier for tracking
    - details: Additional response details
    """

    status: WebhookStatus = Field(
        default=WebhookStatus.SUCCESS,
        description="Processing status of the webhook",
    )
    message: str = Field(
        default="Webhook processed successfully",
        max_length=500,
        description="Human-readable status message",
    )
    workflow_id: str | None = Field(
        default=None,
        description="Unique identifier for tracking the workflow",
    )
    accepted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when webhook was accepted",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional response details",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "accepted",
                    "message": "Sweep workflow initiated for tag 'backend'",
                    "workflow_id": "wf-abc123",
                    "accepted_at": "2026-04-02T12:00:00Z",
                    "details": {"repos_count": 5, "adapter": "agno"},
                }
            ]
        }
    }


class WebhookErrorResponse(BaseModel):
    """Error response model for webhook endpoints.

    Provides structured error response with:
    - error_code: Machine-readable error code
    - message: Human-readable error message
    - recovery: List of recovery suggestions
    - details: Additional error details
    """

    status: WebhookStatus = Field(
        default=WebhookStatus.ERROR,
        description="Always 'error' for error responses",
    )
    error_code: str = Field(
        default="VALIDATION_ERROR",
        max_length=64,
        description="Machine-readable error code",
    )
    message: str = Field(
        max_length=500,
        description="Human-readable error message",
    )
    recovery: list[str] = Field(
        default_factory=list,
        description="List of suggested recovery actions",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional error details for debugging",
    )
    documentation_url: str | None = Field(
        default=None,
        description="Link to error documentation",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "error",
                    "error_code": "VALIDATION_ERROR",
                    "message": "Invalid tag format: path traversal detected",
                    "recovery": [
                        "Use only alphanumeric characters, underscores, and hyphens",
                        "Ensure tag does not contain '../' or absolute paths",
                    ],
                    "details": {"field": "tag", "value": "../../../etc/passwd"},
                    "documentation_url": "https://docs.mahavishnu.org/errors/validation",
                }
            ]
        }
    }


__all__ = [
    "WebhookStatus",
    "OpenClawSweepRequest",
    "OpenClawWorkflowRequest",
    "WebhookResponse",
    "WebhookErrorResponse",
]
