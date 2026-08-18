"""Tool profile definitions for mahavishnu MCP server.

Maps ToolProfile levels from mcp-common to the set of ``_register_*()``
methods called during ``FastMCPServer.start()``.

Core inline tools (defined in ``FastMCPServer._register_tools()`` such as
``list_repos``, ``trigger_workflow``, ``get_health``, etc.) are always
registered regardless of profile -- they are fundamental workflow and
monitoring tools that every consumer needs.

The methods gated here are feature-specific tool groups that add
significant context overhead when registered but are only needed in
certain operational modes.

Configuration (precedence order):
    1. Environment variable: ``MAHAVISHNU_TOOL_PROFILE=standard``
    2. settings/local.yaml:  ``tool_profile: standard``
    3. Default: ``FULL`` (current behavior, no reduction)

Usage::

    from mahavishnu.mcp.tools.profiles import get_active_profile, PROFILE_REGISTRATIONS

    profile = get_active_profile()
    methods = PROFILE_REGISTRATIONS[profile]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_common.tools import ToolProfile

from ..bootstrap import (
    _register_adapter_registry_tools,
    _register_clone_tools,
    _register_ecosystem_tools,
    _register_git_analytics_tools,
    _register_goal_team_tools,
    _register_health_tools,
    _register_openhands_tools,
    _register_otel_tools,
    _register_pool_tools,
    _register_primitive_tools,
    _register_pycharm_tools,
    _register_repository_messaging_tools,
    _register_self_improvement_tools,
    _register_session_buddy_tools,
    _register_terminal_tools,
    _register_treesitter_tools,
    _register_webhook_tools,
    _register_worker_contract_tools,
    _register_worker_tools,
    _register_workflow_tools,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Registration method lists
# ---------------------------------------------------------------------------

# Methods called in start() that are feature-specific.
# Core inline tools in _register_tools() are ALWAYS registered.

MINIMAL_REGISTRATIONS: list[str] = [
    "_register_health_tools",
]

STANDARD_REGISTRATIONS: list[str] = MINIMAL_REGISTRATIONS + [
    "_register_terminal_tools",
    "_register_pool_tools",
    "_register_worker_tools",
    "_register_worker_contract_tools",
    "_register_repository_messaging_tools",
    "_register_git_analytics_tools",
    "_register_session_buddy_tools",
    "_register_openhands_tools",
    "_register_primitive_tools",
]

FULL_REGISTRATIONS: list[str] = STANDARD_REGISTRATIONS + [
    "_register_otel_tools",
    "_register_self_improvement_tools",
    "_register_clone_tools",
    "_register_goal_team_tools",
    "_register_treesitter_tools",
    "_register_adapter_registry_tools",
    "_register_pycharm_tools",
]

# Note: ``register_worktree_tools`` is async and conditionally registered
# based on whether WorktreeCoordinator is initialized. It is not included
# in any profile tier because it is gated by runtime state, not by profile.

PROFILE_REGISTRATIONS: dict[ToolProfile, list[str]] = {
    ToolProfile.MINIMAL: MINIMAL_REGISTRATIONS,
    ToolProfile.STANDARD: STANDARD_REGISTRATIONS,
    ToolProfile.FULL: FULL_REGISTRATIONS,
}

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def get_active_profile(
    env_var: str = "MAHAVISHNU_TOOL_PROFILE",
) -> ToolProfile:
    """Read the active tool profile from environment.

    Falls back to ``ToolProfile.FULL`` when the variable is unset or
    contains an unrecognised value, preserving full backward compatibility.

    Args:
        env_var: Environment variable name to read.

    Returns:
        The resolved ToolProfile.
    """
    return ToolProfile.from_env(env_var)


# ---------------------------------------------------------------------------
# W0 helper wiring (apply_tool_profile from mcp-common)
# ---------------------------------------------------------------------------


# Mapping from PROFILE_REGISTRATIONS string keys to per-group registration
# callables. Each callable takes the FastMCP (the W0 helper's contract) and
# delegates to the per-group function in `bootstrap.py` (which expects the
# FastMCPServer wrapper). The wrapper is recovered via the back-reference
# set in `FastMCPServer.__init__` (see ``_mhv_server`` helper).
REGISTRATION_MAP: dict[str, Callable] = {
    # Always-on groups (registered at every profile via mandatory_tools).
    "_register_health_tools": lambda s: _register_health_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_ecosystem_tools": lambda s: _register_ecosystem_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_workflow_tools": lambda s: _register_workflow_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_webhook_tools": lambda s: _register_webhook_tools(s._mhv_server),  # type: ignore[attr-defined]
    # STANDARD-tier groups.
    "_register_terminal_tools": lambda s: _register_terminal_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_pool_tools": lambda s: _register_pool_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_worker_tools": lambda s: _register_worker_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_worker_contract_tools": lambda s: _register_worker_contract_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_repository_messaging_tools": lambda s: _register_repository_messaging_tools(
        s._mhv_server
    ),  # type: ignore[attr-defined]
    "_register_git_analytics_tools": lambda s: _register_git_analytics_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_session_buddy_tools": lambda s: _register_session_buddy_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_openhands_tools": lambda s: _register_openhands_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_primitive_tools": lambda s: _register_primitive_tools(s._mhv_server),  # type: ignore[attr-defined]
    # FULL-tier groups.
    "_register_otel_tools": lambda s: _register_otel_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_self_improvement_tools": lambda s: _register_self_improvement_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_clone_tools": lambda s: _register_clone_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_goal_team_tools": lambda s: _register_goal_team_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_treesitter_tools": lambda s: _register_treesitter_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_adapter_registry_tools": lambda s: _register_adapter_registry_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_pycharm_tools": lambda s: _register_pycharm_tools(s._mhv_server),  # type: ignore[attr-defined]
}


# Per-repo mandatory group keys. The W0 helper's default MANDATORY_TOOLS set
# uses tool names ('get_liveness', etc.) but its dispatch loop looks them up
# in registration_map as keys. Mahavishnu's group keys are
# '_register_health_tools' etc., so we pass the per-repo subset below.
# See task-2-report.md W0 API gap for full analysis.
MAHAVISHNU_MANDATORY_TOOLS: set[str] = {
    "_register_health_tools",
    "_register_ecosystem_tools",
    "_register_workflow_tools",
    "_register_webhook_tools",
}


def settings_yaml_loader() -> dict | None:
    """Load ``tool_profile`` key from mahavishnu's settings (Oneiric layered).

    Returns ``{"tool_profile": <value>}`` when the key is set, else ``None``.
    The W0 helper uses this to fall back when ``MAHAVISHNU_TOOL_PROFILE`` is
    unset, preserving env > yaml > default precedence.
    """
    try:
        from mahavishnu.core.config import get_settings

        tool_profile = get_settings().tool_profile
        if tool_profile:
            return {"tool_profile": str(tool_profile)}
    except Exception:  # noqa: BLE001 - YAML loader is best-effort
        return None
    return None
