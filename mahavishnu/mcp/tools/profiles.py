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

from mcp_common.tools import ToolProfile

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
    "_register_repository_messaging_tools",
    "_register_git_analytics_tools",
    "_register_session_buddy_tools",
]

FULL_REGISTRATIONS: list[str] = STANDARD_REGISTRATIONS + [
    "_register_otel_tools",
    "_register_self_improvement_tools",
    "_register_goal_team_tools",
    # "_register_team_learning_tools" — de-authorized (Bodai I0.4)
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
