"""
Dependency Injection Context for Mahavishnu.

This module provides ContextVar-based dependency injection for components
that need to be accessed across the application without explicit passing.

Context Variables:
    - llm_factory: Factory for creating LLM instances
    - agno_adapter: Agno adapter instance for team execution

Usage:
    from mahavishnu.core.context import get_llm_factory, get_agno_adapter

    # In application initialization
    from mahavishnu.core.context import set_app_context
    set_app_context(llm_factory=my_factory, agno_adapter=my_adapter)

    # In any module
    llm_factory = get_llm_factory()
    agno_adapter = get_agno_adapter()

Created: 2026-02-21
Version: 1.0
Related: Goal-Driven Teams Phase 1 foundation
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

from .errors import ContextNotInitializedError

if TYPE_CHECKING:
    from ..engines.agno_adapter import AgnoAdapter


@runtime_checkable
class LLMFactory(Protocol):
    """Protocol for LLM factory implementations.

    An LLM factory creates LLM instances for use by agents and teams.
    Implementations should handle provider-specific configuration.
    """

    def create_llm(
        self,
        provider: str | None = None,
        model_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Create an LLM instance.

        Args:
            provider: Optional provider override (e.g., "ollama", "anthropic")
            model_id: Optional model ID override
            **kwargs: Additional provider-specific arguments

        Returns:
            Configured LLM instance
        """
        ...

    def get_default_provider(self) -> str:
        """Get the default LLM provider name.

        Returns:
            Default provider name (e.g., "ollama", "anthropic")
        """
        ...

    def get_default_model(self) -> str:
        """Get the default model ID.

        Returns:
            Default model ID (e.g., "qwen2.5:7b", "claude-sonnet-4-6")
        """
        ...


# Context variables for dependency injection
_llm_factory: ContextVar[LLMFactory | None] = ContextVar("llm_factory", default=None)
_agno_adapter: ContextVar["AgnoAdapter | None"] = ContextVar("agno_adapter", default=None)


# Re-export ContextNotInitializedError from errors for convenience
# (already imported at top of file)


def get_llm_factory() -> LLMFactory:
    """Get the LLM factory from context.

    Returns:
        The LLM factory instance

    Raises:
        ContextNotInitializedError: If LLM factory is not set in context

    Example:
        >>> factory = get_llm_factory()
        >>> llm = factory.create_llm(provider="ollama", model_id="qwen2.5:7b")
    """
    factory = _llm_factory.get()
    if factory is None:
        raise ContextNotInitializedError(
            context_name="llm_factory",
            details={
                "suggestion": "Call set_app_context(llm_factory=...) during app initialization",
            },
        )
    return factory


def get_agno_adapter() -> "AgnoAdapter":
    """Get the Agno adapter from context.

    Returns:
        The AgnoAdapter instance

    Raises:
        ContextNotInitializedError: If Agno adapter is not set in context

    Example:
        >>> adapter = get_agno_adapter()
        >>> result = await adapter.execute_team("team_id", task)
    """
    adapter = _agno_adapter.get()
    if adapter is None:
        raise ContextNotInitializedError(
            context_name="agno_adapter",
            details={
                "suggestion": "Call set_app_context(agno_adapter=...) during app initialization",
            },
        )
    return adapter


def set_app_context(
    llm_factory: LLMFactory | None = None,
    agno_adapter: "AgnoAdapter | None" = None,
) -> None:
    """Set application context variables for dependency injection.

    This function should be called during MahavishnuApp initialization
    to make core components available throughout the application.

    Args:
        llm_factory: Optional LLM factory for creating LLM instances
        agno_adapter: Optional Agno adapter for team execution

    Example:
        >>> from mahavishnu.core.context import set_app_context
        >>> set_app_context(
        ...     llm_factory=my_llm_factory,
        ...     agno_adapter=app.adapters.get("agno"),
        ... )
    """
    if llm_factory is not None:
        _llm_factory.set(llm_factory)

    if agno_adapter is not None:
        _agno_adapter.set(agno_adapter)


def clear_app_context() -> None:
    """Clear all application context variables.

    This is primarily useful for testing to reset context between tests.

    Example:
        >>> clear_app_context()
        >>> get_llm_factory()  # Raises ContextNotInitializedError
    """
    _llm_factory.set(None)
    _agno_adapter.set(None)


def is_context_initialized() -> bool:
    """Check if application context is initialized.

    Returns:
        True if both llm_factory and agno_adapter are set

    Example:
        >>> if is_context_initialized():
        ...     factory = get_llm_factory()
    """
    return _llm_factory.get() is not None and _agno_adapter.get() is not None


# ============================================================================
# Convenience Functions
# ============================================================================


def require_llm_factory() -> Callable[[], LLMFactory]:
    """Decorator/marker that requires LLM factory to be available.

    Use this as a type hint or documentation marker for functions
    that require the LLM factory.

    Example:
        >>> def generate_response(prompt: str) -> str:
        ...     '''
        ...     Generate a response using the LLM.
        ...     Requires: require_llm_factory()
        ...     '''
        ...     factory = get_llm_factory()
        ...     llm = factory.create_llm()
        ...     return llm.generate(prompt)
    """
    return get_llm_factory


def require_agno_adapter() -> Callable[[], "AgnoAdapter"]:
    """Decorator/marker that requires Agno adapter to be available.

    Use this as a type hint or documentation marker for functions
    that require the Agno adapter.

    Example:
        >>> async def execute_goal(goal: str) -> dict:
        ...     '''
        ...     Execute a goal using a team.
        ...     Requires: require_agno_adapter()
        ...     '''
        ...     adapter = get_agno_adapter()
        ...     return await adapter.execute_goal_team(goal)
    """
    return get_agno_adapter


# ============================================================================
# Context Manager for Testing
# ============================================================================


class AppContext:
    """Context manager for temporarily setting application context.

    Useful for testing or isolated operations that need specific context.

    Example:
        >>> with AppContext(llm_factory=test_factory):
        ...     factory = get_llm_factory()
        ...     assert factory is test_factory
    """

    def __init__(
        self,
        llm_factory: LLMFactory | None = None,
        agno_adapter: "AgnoAdapter | None" = None,
    ) -> None:
        """Initialize context manager.

        Args:
            llm_factory: Optional LLM factory
            agno_adapter: Optional Agno adapter
        """
        self._llm_factory = llm_factory
        self._agno_adapter = agno_adapter
        self._old_llm_factory: LLMFactory | None = None
        self._old_agno_adapter: "AgnoAdapter | None" = None

    def __enter__(self) -> "AppContext":
        """Enter context and set variables."""
        self._old_llm_factory = _llm_factory.get()
        self._old_agno_adapter = _agno_adapter.get()

        if self._llm_factory is not None:
            _llm_factory.set(self._llm_factory)
        if self._agno_adapter is not None:
            _agno_adapter.set(self._agno_adapter)

        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context and restore previous values."""
        _llm_factory.set(self._old_llm_factory)
        _agno_adapter.set(self._old_agno_adapter)


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Protocol
    "LLMFactory",
    # Context getters
    "get_llm_factory",
    "get_agno_adapter",
    # Context setters
    "set_app_context",
    "clear_app_context",
    "is_context_initialized",
    # Convenience functions
    "require_llm_factory",
    "require_agno_adapter",
    # Context manager
    "AppContext",
    # Exceptions
    "ContextNotInitializedError",
]
