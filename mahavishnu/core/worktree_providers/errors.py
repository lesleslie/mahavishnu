"""Worktree provider exceptions."""

from typing import Any


class WorktreeOperationError(Exception):
    """Base exception for worktree operation failures.

    Attributes:
        message: Human-readable error message
        details: Additional error context
        providers: List of available providers (for registry failures)
    """

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        providers: list[str] | None = None,
    ) -> None:
        """Initialize worktree operation error.

        Args:
            message: Human-readable error message
            details: Additional error context (operation, params, etc.)
            providers: List of available providers (for registry errors)
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.providers = providers or []

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for API responses.

        Returns:
            Dictionary with error information
        """
        return {
            "error": self.message,
            "error_type": self.__class__.__name__,
            "details": self.details,
            "providers": self.providers,
        }


class WorktreeCreationError(WorktreeOperationError):
    """Raised when worktree creation fails."""

    pass


class WorktreeRemovalError(WorktreeOperationError):
    """Raised when worktree removal fails."""

    pass


class WorktreeValidationError(WorktreeOperationError):
    """Raised when worktree validation fails."""

    pass


class ProviderUnavailableError(WorktreeOperationError):
    """Raised when no worktree providers are available."""

    pass
