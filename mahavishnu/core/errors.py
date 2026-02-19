"""
Error code system for Mahavishnu Task Orchestration.

This module provides a structured error handling system with:
- Error codes (MHV-001 to MHV-399)
- Recovery guidance for each error
- Structured error responses for API/MCP tools

Created: 2026-02-18
Version: 3.1
Related: 4-Agent Opus Review P0 issue - error code system
"""

from enum import Enum
from typing import ClassVar
from datetime import datetime, timezone


class ErrorCode(str, Enum):
    """
    Error code system for Mahavishnu Task Orchestration.

    Error codes follow format: MHV-XXX
    - MHV-001 to MHV-099: System errors
    - MHV-100 to MHV-199: Task errors
    - MHV-200 to MHV-299: Repository errors
    - MHV-300 to MHV-399: External integration errors

    Each error code has:
    - A descriptive name
    - Recovery guidance for users
    - Documentation URL
    """

    # System errors (001-099)
    CONFIGURATION_ERROR = "MHV-001"
    DATABASE_CONNECTION_ERROR = "MHV-002"
    VALIDATION_ERROR = "MHV-003"
    AUTHENTICATION_ERROR = "MHV-004"
    AUTHORIZATION_ERROR = "MHV-005"
    RATE_LIMIT_EXCEEDED = "MHV-006"
    INTERNAL_ERROR = "MHV-007"
    TIMEOUT_ERROR = "MHV-008"
    RESOURCE_NOT_FOUND = "MHV-009"
    OPERATION_CANCELLED = "MHV-010"

    # Task errors (100-199)
    TASK_NOT_FOUND = "MHV-100"
    TASK_CREATION_FAILED = "MHV-101"
    TASK_UPDATE_FAILED = "MHV-102"
    TASK_DELETION_FAILED = "MHV-103"
    TASK_ALREADY_COMPLETED = "MHV-104"
    TASK_BLOCKED = "MHV-105"
    TASK_INVALID_STATUS = "MHV-106"
    TASK_DEADLINE_PASSED = "MHV-107"
    TASK_ASSIGNMENT_FAILED = "MHV-108"
    TASK_DEPENDENCY_CYCLE = "MHV-109"

    # Repository errors (200-299)
    REPOSITORY_NOT_FOUND = "MHV-200"
    REPOSITORY_NOT_CONFIGURED = "MHV-201"
    WORKTREE_CREATION_FAILED = "MHV-202"
    WORKTREE_NOT_FOUND = "MHV-203"
    WORKTREE_CLEANUP_FAILED = "MHV-204"
    REPOSITORY_CLONE_FAILED = "MHV-205"
    REPOSITORY_ACCESS_DENIED = "MHV-206"

    # External integration errors (300-399)
    WEBHOOK_SIGNATURE_INVALID = "MHV-300"
    WEBHOOK_REPLAY_DETECTED = "MHV-301"
    GITHUB_API_ERROR = "MHV-302"
    GITLAB_API_ERROR = "MHV-303"
    EMBEDDING_SERVICE_ERROR = "MHV-304"
    NLP_PARSER_ERROR = "MHV-305"
    EXTERNAL_SERVICE_UNAVAILABLE = "MHV-306"


class MahavishnuError(Exception):
    """
    Base exception with error code and recovery guidance.

    All errors in Mahavishnu should use this base class to ensure
    consistent error handling and user experience.

    Attributes:
        message: Human-readable error message
        error_code: Structured error code (MHV-XXX)
        recovery: List of recovery steps for the user
        details: Additional context about the error
    """

    # Recovery guidance mapping - default guidance for each error code
    RECOVERY_GUIDANCE: ClassVar[dict[str, list[str]]] = {
        ErrorCode.CONFIGURATION_ERROR: [
            "Check settings/repos.yaml for syntax errors",
            "Run 'mhv validate-config' to verify configuration",
            "See documentation: https://docs.mahavishnu.org/config",
        ],
        ErrorCode.DATABASE_CONNECTION_ERROR: [
            "Check database connectivity",
            "Verify database credentials in environment",
            "Check if PostgreSQL is running",
            "Run 'docker-compose up -d postgres' if using Docker",
        ],
        ErrorCode.VALIDATION_ERROR: [
            "Check input values match expected format",
            "Ensure required fields are provided",
            "See API documentation for field requirements",
        ],
        ErrorCode.AUTHENTICATION_ERROR: [
            "Verify your authentication credentials",
            "Check if JWT token has expired",
            "Re-authenticate and try again",
        ],
        ErrorCode.AUTHORIZATION_ERROR: [
            "You don't have permission for this action",
            "Contact administrator for access",
            "Check your role assignments",
        ],
        ErrorCode.RATE_LIMIT_EXCEEDED: [
            "Wait a moment before retrying",
            "Reduce request frequency",
            "Contact support if limit seems incorrect",
        ],
        ErrorCode.INTERNAL_ERROR: [
            "An unexpected error occurred",
            "Try the operation again",
            "Check logs for more details",
            "Report issue if problem persists",
        ],
        ErrorCode.TIMEOUT_ERROR: [
            "The operation took too long",
            "Try again with a simpler request",
            "Check system health if timeouts persist",
        ],
        ErrorCode.RESOURCE_NOT_FOUND: [
            "The requested resource does not exist",
            "Check the resource identifier",
            "Verify resource hasn't been deleted",
        ],
        ErrorCode.OPERATION_CANCELLED: [
            "The operation was cancelled",
            "Check if timeout was reached",
            "Retry the operation if needed",
        ],
        ErrorCode.TASK_NOT_FOUND: [
            "Verify the task ID is correct",
            "Check if task was deleted",
            "Use 'mhv tl' to see available tasks",
            "Task IDs are case-sensitive",
        ],
        ErrorCode.TASK_CREATION_FAILED: [
            "Check that all required fields are provided",
            "Verify repository name is valid",
            "Ensure title is 3-500 characters",
            "Run 'mhv tc --help' for usage",
        ],
        ErrorCode.TASK_UPDATE_FAILED: [
            "Verify the task ID is correct",
            "Check that at least one field is being updated",
            "Ensure task is not deleted",
            "Run 'mhv tu --help' for usage",
        ],
        ErrorCode.TASK_DELETION_FAILED: [
            "Verify the task ID is correct",
            "Check if task has dependencies",
            "Remove dependencies first if needed",
        ],
        ErrorCode.TASK_ALREADY_COMPLETED: [
            "Task is already marked as completed",
            "No further action needed",
            "Use 'mhv tu' to change status if needed",
        ],
        ErrorCode.TASK_BLOCKED: [
            "Task has unresolved dependencies",
            "Complete blocking tasks first",
            "Use 'mhv tl' to check dependency status",
        ],
        ErrorCode.TASK_INVALID_STATUS: [
            "Invalid status transition attempted",
            "Check valid status values: pending, in_progress, completed, failed, cancelled, blocked",
            "Some transitions may require intermediate steps",
        ],
        ErrorCode.TASK_DEADLINE_PASSED: [
            "Task deadline has passed",
            "Update deadline if more time needed",
            "Mark task as failed if no longer relevant",
        ],
        ErrorCode.TASK_ASSIGNMENT_FAILED: [
            "Could not assign task to user",
            "Verify user email or username is correct",
            "Check user has appropriate permissions",
        ],
        ErrorCode.TASK_DEPENDENCY_CYCLE: [
            "Circular dependency detected",
            "Remove one of the dependencies to break the cycle",
            "Use 'mhv tl' to view task relationships",
        ],
        ErrorCode.REPOSITORY_NOT_FOUND: [
            "Add repository to settings/repos.yaml",
            "Run 'mhv validate-config' to verify",
            "Check repository path is correct",
            "Use 'mhv lr' to list configured repos",
        ],
        ErrorCode.REPOSITORY_NOT_CONFIGURED: [
            "Repository is not in configuration",
            "Add entry to settings/repos.yaml",
            "Run 'mhv init' to create default config",
        ],
        ErrorCode.WORKTREE_CREATION_FAILED: [
            "Check git repository is valid",
            "Ensure branch name is correct",
            "Verify disk space is available",
        ],
        ErrorCode.WORKTREE_NOT_FOUND: [
            "Worktree does not exist",
            "Check worktree path is correct",
            "Use 'git worktree list' to see worktrees",
        ],
        ErrorCode.WORKTREE_CLEANUP_FAILED: [
            "Could not remove worktree",
            "Check for uncommitted changes",
            "Manually remove if needed",
        ],
        ErrorCode.REPOSITORY_CLONE_FAILED: [
            "Check repository URL is correct",
            "Verify network connectivity",
            "Ensure git credentials are configured",
        ],
        ErrorCode.REPOSITORY_ACCESS_DENIED: [
            "Permission denied for repository",
            "Check file system permissions",
            "Verify git credentials",
        ],
        ErrorCode.WEBHOOK_SIGNATURE_INVALID: [
            "Webhook signature verification failed",
            "Verify webhook secret configuration",
            "Check if payload was modified in transit",
        ],
        ErrorCode.WEBHOOK_REPLAY_DETECTED: [
            "This webhook was already processed",
            "No action needed if this was an automatic retry",
            "Contact support if you see this unexpectedly",
        ],
        ErrorCode.GITHUB_API_ERROR: [
            "GitHub API request failed",
            "Check GITHUB_TOKEN is set",
            "Verify API rate limits",
            "Try again in a few minutes",
        ],
        ErrorCode.GITLAB_API_ERROR: [
            "GitLab API request failed",
            "Check GITLAB_TOKEN is set",
            "Verify GitLab instance is accessible",
        ],
        ErrorCode.EMBEDDING_SERVICE_ERROR: [
            "Embedding service is unavailable",
            "Try using local embeddings (Ollama/fastembed)",
            "Check OpenAI API status if using OpenAI",
            "Run 'ollama serve' if using Ollama",
        ],
        ErrorCode.NLP_PARSER_ERROR: [
            "Could not parse natural language input",
            "Try rephrasing your request",
            "Use structured command syntax instead",
            "Example: 'mhv tc \"Task title\" -r repo'",
        ],
        ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE: [
            "External service is not responding",
            "Check service status",
            "Try again later",
            "Use fallback options if available",
        ],
    }

    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        recovery: list[str] | None = None,
        details: dict | None = None,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.recovery = recovery or self.RECOVERY_GUIDANCE.get(
            error_code.value, ["Contact support for assistance"]
        )
        self.details = details or {}
        self.timestamp = datetime.now(timezone.utc)
        super().__init__(f"[{error_code.value}] {message}")

    def to_dict(self) -> dict:
        """
        Convert error to dictionary for API responses.

        Returns:
            Dictionary with error details for JSON serialization
        """
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "recovery": self.recovery,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "documentation": f"https://docs.mahavishnu.org/errors/{self.error_code.value.lower()}",
        }

    def __str__(self) -> str:
        recovery_text = "\n  ".join(f"{i+1}. {step}" for i, step in enumerate(self.recovery))
        return f"[{self.error_code.value}] {self.message}\n\nRecovery steps:\n  {recovery_text}\n\nDocumentation: https://docs.mahavishnu.org/errors/{self.error_code.value.lower()}\n"


# Convenience exception classes for common errors

class ConfigurationError(MahavishnuError):
    """Configuration-related error."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, ErrorCode.CONFIGURATION_ERROR, details=details)


class ValidationError(MahavishnuError):
    """Input validation error."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, ErrorCode.VALIDATION_ERROR, details=details)


class TaskNotFoundError(MahavishnuError):
    """Task not found error."""

    def __init__(self, task_id: int | str, details: dict | None = None) -> None:
        super().__init__(
            f"Task not found: {task_id}",
            ErrorCode.TASK_NOT_FOUND,
            details={"task_id": str(task_id), **(details or {})},
        )


class RepositoryNotFoundError(MahavishnuError):
    """Repository not found error."""

    def __init__(self, repository: str, details: dict | None = None) -> None:
        super().__init__(
            f"Repository not found: {repository}",
            ErrorCode.REPOSITORY_NOT_FOUND,
            details={"repository": repository, **(details or {})},
        )


class WebhookAuthError(MahavishnuError):
    """Webhook authentication error."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.WEBHOOK_SIGNATURE_INVALID,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, error_code, details=details)


class RateLimitError(MahavishnuError):
    """Rate limit exceeded error."""

    def __init__(self, limit: str, retry_after: int | None = None) -> None:
        details = {"limit": limit}
        if retry_after:
            details["retry_after_seconds"] = retry_after
        super().__init__(
            f"Rate limit exceeded: {limit}",
            ErrorCode.RATE_LIMIT_EXCEEDED,
            details=details,
        )


class AdapterError(MahavishnuError):
    """
    Adapter-related error for orchestration engine failures.

    Used when an adapter (LlamaIndex, Prefect, Agno, etc.) fails to
    initialize or execute tasks.
    """

    def __init__(
        self,
        message: str,
        details: dict | None = None,
        adapter_name: str | None = None,
    ) -> None:
        # If adapter_name provided in details or as arg, include it
        if adapter_name:
            message = f"Adapter '{adapter_name}' error: {message}"
        super().__init__(
            message,
            ErrorCode.INTERNAL_ERROR,
            details=details,
        )


class AuthenticationError(MahavishnuError):
    """
    Authentication error for credential/validation failures.

    Used for JWT validation, subscription checks, and auth provider failures.
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        details: dict | None = None,
    ) -> None:
        super().__init__(message, ErrorCode.AUTHENTICATION_ERROR, details=details)


class AuthorizationError(MahavishnuError):
    """
    Authorization error for permission/access failures.

    Used when a user lacks permission for an action.
    """

    def __init__(
        self,
        message: str = "Access denied",
        details: dict | None = None,
    ) -> None:
        super().__init__(message, ErrorCode.AUTHORIZATION_ERROR, details=details)


class TimeoutError(MahavishnuError):
    """
    Timeout error for operations that exceed time limits.

    Note: Named TimeoutError to match the error code, but inherits from
    MahavishnuError rather than built-in TimeoutError to maintain
    consistent error handling across the codebase.
    """

    def __init__(
        self,
        operation: str,
        timeout_seconds: float | None = None,
        details: dict | None = None,
    ) -> None:
        message = f"Operation '{operation}' timed out"
        if timeout_seconds:
            message += f" after {timeout_seconds}s"
        super().__init__(
            message,
            ErrorCode.TIMEOUT_ERROR,
            details={"operation": operation, **(details or {})},
        )


class DatabaseError(MahavishnuError):
    """Database connection or query error."""

    def __init__(
        self,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, ErrorCode.DATABASE_CONNECTION_ERROR, details=details)


class ExternalServiceError(MahavishnuError):
    """External service (GitHub, GitLab, embedding service) error."""

    def __init__(
        self,
        service: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(
            f"External service '{service}' error: {message}",
            ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE,
            details={"service": service, **(details or {})},
        )


class WorkflowError(MahavishnuError):
    """
    Workflow execution error.

    Used for workflow orchestration failures, step execution errors,
    and workflow state management issues.
    """

    def __init__(
        self,
        workflow_id: str,
        message: str,
        step: str | None = None,
        details: dict | None = None,
    ) -> None:
        error_message = f"Workflow '{workflow_id}' error: {message}"
        if step:
            error_message = f"Workflow '{workflow_id}' step '{step}' error: {message}"
        super().__init__(
            error_message,
            ErrorCode.INTERNAL_ERROR,
            details={"workflow_id": workflow_id, "step": step, **(details or {})},
        )


# ============================================================================
# Error Helper Functions
# ============================================================================


def get_contextual_help(error_code: ErrorCode, context: dict | None = None) -> str:
    """Get contextual help message for an error.

    Args:
        error_code: The error code to get help for
        context: Optional context dict with additional info

    Returns:
        Formatted help string with recovery steps
    """
    guidance = MahavishnuError.RECOVERY_GUIDANCE.get(error_code.value, ["Contact support for assistance"])

    help_text = f"\n{'='*60}\n"
    help_text += f"Error: {error_code.name.replace('_', ' ')}\n"
    help_text += f"Code: {error_code.value}\n"
    help_text += f"{'='*60}\n\n"
    help_text += "How to resolve:\n"
    for i, step in enumerate(guidance, 1):
        help_text += f"  {i}. {step}\n"

    if context:
        help_text += f"\nContext:\n"
        for key, value in context.items():
            help_text += f"  • {key}: {value}\n"

    help_text += f"\nDocumentation: https://docs.mahavishnu.org/errors/{error_code.value.lower()}\n"

    return help_text


def format_error_for_cli(error: MahavishnuError, verbose: bool = False) -> str:
    """Format an error for CLI display.

    Args:
        error: The error to format
        verbose: Include full details if True

    Returns:
        Formatted error string for terminal
    """
    if verbose:
        return str(error)

    # Brief format
    lines = [
        f"Error [{error.error_code.value}]: {error.message}",
    ]

    if error.recovery:
        lines.append(f"Try: {error.recovery[0]}")

    lines.append("Run with --verbose for more details")

    return "\n".join(lines)


def create_error_from_exception(
    exc: Exception,
    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
    context: dict | None = None,
) -> MahavishnuError:
    """Create a MahavishnuError from a generic exception.

    Useful for wrapping third-party exceptions with recovery guidance.

    Args:
        exc: The original exception
        error_code: Error code to use
        context: Additional context

    Returns:
        MahavishnuError with recovery guidance
    """
    details = {
        "original_type": type(exc).__name__,
        "original_message": str(exc),
        **(context or {}),
    }

    return MahavishnuError(
        message=str(exc),
        error_code=error_code,
        details=details,
    )


# ============================================================================
# Error Templates for Common Scenarios
# ============================================================================

class ErrorTemplates:
    """Templates for common error scenarios."""

    @staticmethod
    def task_create_validation(title: str, repository: str, issues: list[str]) -> ValidationError:
        """Create a validation error for task creation.

        Args:
            title: Task title that failed validation
            repository: Repository name
            issues: List of validation issues

        Returns:
            ValidationError with detailed recovery steps
        """
        recovery = []
        if any("title" in i.lower() for i in issues):
            recovery.append("Title must be 3-500 characters")
        if any("repository" in i.lower() for i in issues):
            recovery.append("Repository must be configured in repos.yaml")
            recovery.append("Use 'mhv lr' to list available repositories")

        recovery.extend([
            "Example: mhv tc \"Valid task title\" -r mahavishnu",
            "Run 'mhv tc --help' for all options",
        ])

        return ValidationError(
            message=f"Task creation failed: {'; '.join(issues)}",
            details={
                "title": title,
                "repository": repository,
                "issues": issues,
            },
        )

    @staticmethod
    def database_connection_failed(host: str, port: int, original_error: str) -> DatabaseError:
        """Create a database connection error with context.

        Args:
            host: Database host
            port: Database port
            original_error: Original error message

        Returns:
            DatabaseError with recovery steps
        """
        return DatabaseError(
            message=f"Could not connect to database at {host}:{port}",
            details={
                "host": host,
                "port": port,
                "original_error": original_error,
            },
        )

    @staticmethod
    def search_failed(query: str, reason: str) -> ExternalServiceError:
        """Create a search error with context.

        Args:
            query: Search query that failed
            reason: Reason for failure

        Returns:
            ExternalServiceError with recovery steps
        """
        return ExternalServiceError(
            service="embedding",
            message=f"Search failed for '{query}': {reason}",
            details={
                "query": query,
                "reason": reason,
            },
        )

    @staticmethod
    def config_file_error(file_path: str, issue: str) -> ConfigurationError:
        """Create a configuration file error.

        Args:
            file_path: Path to config file
            issue: Description of the issue

        Returns:
            ConfigurationError with recovery steps
        """
        return ConfigurationError(
            message=f"Configuration error in {file_path}: {issue}",
            details={
                "file_path": file_path,
                "issue": issue,
            },
        )

    @staticmethod
    def webhook_failed(event_type: str, reason: str, payload_id: str | None = None) -> WebhookAuthError:
        """Create a webhook error with context.

        Args:
            event_type: Type of webhook event
            reason: Reason for failure
            payload_id: Optional payload ID

        Returns:
            WebhookAuthError with recovery steps
        """
        details = {
            "event_type": event_type,
            "reason": reason,
        }
        if payload_id:
            details["payload_id"] = payload_id

        return WebhookAuthError(
            message=f"Webhook processing failed: {reason}",
            details=details,
        )
