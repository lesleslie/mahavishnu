"""Feature flag utilities for Goal-Driven Teams.

This module provides feature flag checking and enforcement utilities
for controlling access to Goal-Driven Teams features.

Created: 2026-02-21
Version: 1.1
Related: Goal-Driven Teams Phase 1 - Feature flag integration
"""

from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

from mahavishnu.core.errors import FeatureDisabledError

F = TypeVar("F", bound=Callable[..., Any])


class GoalTeamsFeatureFlags(BaseModel):
    """Feature flags for Goal-Driven Teams.

    These flags control access to various Goal-Driven Teams features
    and can be configured via settings/mahavishnu.yaml.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under goal_teams.feature_flags
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__MCP_TOOLS_ENABLED, etc.

    Note: The master switch `enabled` is in GoalTeamsConfig, not here.
    This class only contains granular feature flags.

    Example YAML:
        goal_teams:
          enabled: true  # Master switch (in GoalTeamsConfig)
          feature_flags:
            mcp_tools_enabled: true
            cli_commands_enabled: true
            llm_fallback_enabled: true
            websocket_broadcasts_enabled: true
            prometheus_metrics_enabled: true
            learning_system_enabled: false
            auto_mode_selection_enabled: true
            custom_skills_enabled: false
    """

    # Core feature flags
    mcp_tools_enabled: bool = True
    cli_commands_enabled: bool = True

    # Advanced feature flags
    llm_fallback_enabled: bool = True
    websocket_broadcasts_enabled: bool = True
    prometheus_metrics_enabled: bool = True

    # Experimental features
    learning_system_enabled: bool = False  # Phase 3
    auto_mode_selection_enabled: bool = True
    custom_skills_enabled: bool = False

    model_config = {"extra": "forbid"}


# Context variable for config access
_config: ContextVar[Any | None] = ContextVar("mahavishnu_config", default=None)


def set_config(config: Any) -> None:
    """Set the configuration in context for feature flag access.

    Args:
        config: The MahavishnuSettings instance
    """
    _config.set(config)


def get_config() -> Any:
    """Get the configuration from context.

    Returns:
        The MahavishnuSettings instance

    Raises:
        RuntimeError: If config is not set in context
    """
    config = _config.get()
    if config is None:
        raise RuntimeError(
            "Configuration not set in context. "
            "Call set_config() during application initialization."
        )
    return config


def is_feature_enabled(feature_name: str) -> bool:
    """Check if a feature flag is enabled.

    Special feature names:
    - "enabled": Checks the master switch (goal_teams.enabled)

    This function checks the feature flags in the following order:
    1. Master switch (goal_teams.enabled) - all features depend on this
    2. Individual feature flag (goal_teams.feature_flags.{feature_name})

    Args:
        feature_name: Name of the feature flag to check.
                     Examples: "enabled" (master switch), "mcp_tools_enabled",
                     "cli_commands_enabled"

    Returns:
        True if the feature is enabled, False otherwise

    Example:
        >>> if is_feature_enabled("enabled"):  # Check master switch
        ...     # Goal-Driven Teams is enabled
        ...     pass
        >>> if is_feature_enabled("mcp_tools_enabled"):
        ...     # MCP tools are available
        ...     pass
    """
    try:
        config = _config.get()
        if config is None:
            # Config not set, use defaults
            return _get_default_flag(feature_name)

        goal_teams = getattr(config, "goal_teams", None)
        if goal_teams is None:
            return _get_default_flag(feature_name)

        # Check master switch first (for all features except "enabled" itself)
        if feature_name != "enabled":
            if not getattr(goal_teams, "enabled", False):
                return False

        # If checking the master switch itself
        if feature_name == "enabled":
            return getattr(goal_teams, "enabled", False)

        # Check feature_flags attribute
        feature_flags = getattr(goal_teams, "feature_flags", None)
        if feature_flags is None:
            return _get_default_flag(feature_name)

        # Check specific feature flag
        return getattr(feature_flags, feature_name, False)

    except Exception:
        # On any error, return default
        return _get_default_flag(feature_name)


def _get_default_flag(feature_name: str) -> bool:
    """Get the default value for a feature flag.

    Args:
        feature_name: Name of the feature flag

    Returns:
        Default value for the flag
    """
    if feature_name == "enabled":
        return False  # Master switch defaults to disabled
    defaults = GoalTeamsFeatureFlags()
    return getattr(defaults, feature_name, False)


def require_feature(feature_name: str) -> Callable[[F], F]:
    """Decorator to require a feature flag for a function.

    If the feature is disabled, raises FeatureDisabledError.
    Works with both sync and async functions.

    Args:
        feature_name: Name of the required feature flag

    Returns:
        Decorated function that checks feature flag before execution

    Raises:
        FeatureDisabledError: If the feature is not enabled

    Example:
        >>> @require_feature("mcp_tools_enabled")
        ... async def team_from_goal(goal: str) -> dict:
        ...     # This will only execute if mcp_tools_enabled is True
        ...     return {"team_id": "..."}

    Example with master switch:
        >>> @require_feature("enabled")  # Checks goal_teams.enabled
        ... async def create_team(goal: str) -> dict:
        ...     return {"team_id": "..."}
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not is_feature_enabled(feature_name):
                raise FeatureDisabledError(
                    feature_name=feature_name,
                    details={
                        "suggestion": f"Enable {feature_name} in settings/mahavishnu.yaml under goal_teams.feature_flags",
                        "config_path": "goal_teams.feature_flags." + feature_name,
                    },
                )
            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not is_feature_enabled(feature_name):
                raise FeatureDisabledError(
                    feature_name=feature_name,
                    details={
                        "suggestion": f"Enable {feature_name} in settings/mahavishnu.yaml under goal_teams.feature_flags",
                        "config_path": "goal_teams.feature_flags." + feature_name,
                    },
                )
            return func(*args, **kwargs)

        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


def check_feature(feature_name: str) -> None:
    """Check if a feature is enabled and raise if not.

    This is a non-decorator version of require_feature for
    imperative style checks.

    Args:
        feature_name: Name of the feature flag to check

    Raises:
        FeatureDisabledError: If the feature is not enabled

    Example:
        >>> def some_function():
        ...     check_feature("mcp_tools_enabled")
        ...     # Continue with feature-specific logic
    """
    if not is_feature_enabled(feature_name):
        raise FeatureDisabledError(
            feature_name=feature_name,
            details={
                "suggestion": f"Enable {feature_name} in settings/mahavishnu.yaml under goal_teams.feature_flags",
                "config_path": "goal_teams.feature_flags." + feature_name,
            },
        )


def get_all_feature_flags() -> dict[str, bool]:
    """Get all feature flags and their current status.

    Returns:
        Dictionary of feature flag names to their enabled status,
        including the master switch "enabled"

    Example:
        >>> flags = get_all_feature_flags()
        >>> print(flags)
        {
            "enabled": True,
            "mcp_tools_enabled": True,
            "cli_commands_enabled": True,
            ...
        }
    """
    result = {"enabled": is_feature_enabled("enabled")}
    defaults = GoalTeamsFeatureFlags()

    for field_name in defaults.model_fields:
        result[field_name] = is_feature_enabled(field_name)

    return result


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Classes
    "GoalTeamsFeatureFlags",
    # Context management
    "set_config",
    "get_config",
    # Feature checking
    "is_feature_enabled",
    "require_feature",
    "check_feature",
    "get_all_feature_flags",
]
