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
    _register_agents_tools,
    _register_capability_tools,
    _register_clone_tools,
    _register_dispatch_specialist_tools,
    _register_ecosystem_tools,
    _register_git_analytics_tools,
    _register_goal_team_tools,
    _register_health_tools,
    _register_openhands_tools,
    _register_otel_tools,
    _register_plan_tools,
    _register_pool_tools,
    _register_primitive_tools,
    _register_pycharm_tools,
    _register_repository_messaging_tools,
    _register_search_tools,
    _register_self_improvement_tools,
    _register_session_buddy_tools,
    _register_skills_signer_tools,
    _register_terminal_tools,
    _register_treesitter_tools,
    _register_webhook_tools,
    _register_worker_contract_tools,
    _register_worker_tools,
    _register_workflow_tools,
)
from .jot_tools import register as _register_jot_tools

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Registration method lists
# ---------------------------------------------------------------------------

# Methods called in start() that are feature-specific.
# Core inline tools in _register_tools() are ALWAYS registered.

MINIMAL_REGISTRATIONS: list[str] = [
    "_register_health_tools",
    # Phase 1.5 — skills_signer is infrastructure-critical (signing
    # verification is on every Phase 2/6 install). Per plan §10.3.1
    # it MUST be visible from MINIMAL upward.
    "_register_skills_signer_tools",
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
STANDARD_REGISTRATIONS.append("_register_capability_tools")

FULL_REGISTRATIONS: list[str] = STANDARD_REGISTRATIONS + [
    "_register_otel_tools",
    "_register_self_improvement_tools",
    "_register_clone_tools",
    "_register_goal_team_tools",
    "_register_treesitter_tools",
    "_register_adapter_registry_tools",
    "_register_pycharm_tools",
    "_register_search_tools",
    # Plan index tools (5 tools; Task 12). Delegates to the W0 helper via
    # ``_register_plan_tools`` which constructs a Dhara-backed store from
    # ``MahavishnuApp`` and binds all five ``plan_*`` tools in one call.
    "_register_plan_tools",
    # Jot inbox tools (8 tools; Task 13). Each key in REGISTRATION_MAP
    # delegates to the same ``register`` callable which is idempotent
    # (re-decorates all 8 tools against the FastMCP server).
    "jot_list",
    "jot_show",
    "jot_add",
    "jot_edit",
    "jot_done",
    "jot_reopen",
    "jot_vitals",
    "jot_search",
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
    # Phase 1.5 — skills_signer (per plan §10.3.1). The actual signer
    # init runs in start() because mahavishnu has no async lifespan.
    "_register_skills_signer_tools": lambda s: _register_skills_signer_tools(s._mhv_server),  # type: ignore[attr-defined]
    # Phase 3 — agents share the same signer feed state as Phase 1
    # skills_signer (per plan §11 B-6). Always-on for parity with the
    # skills_signer mandatory group.
    "_register_agents_tools": lambda s: _register_agents_tools(s._mhv_server),  # type: ignore[attr-defined]
    # Phase 3 task #5 (H-3) — specialist dispatcher. The dispatcher
    # is the entry point by which workflows resolve category-named
    # specialists (dhara-specialist, crackerjack-specialist, etc.);
    # without it the specialists are unreachable from a workflow.
    # Always-on for parity with the discovery surface.
    "_register_dispatch_specialist_tools": lambda s: _register_dispatch_specialist_tools(s._mhv_server),  # type: ignore[attr-defined]
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
    "_register_capability_tools": lambda s: _register_capability_tools(s._mhv_server),  # type: ignore[attr-defined]
    # FULL-tier groups.
    "_register_otel_tools": lambda s: _register_otel_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_self_improvement_tools": lambda s: _register_self_improvement_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_clone_tools": lambda s: _register_clone_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_goal_team_tools": lambda s: _register_goal_team_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_treesitter_tools": lambda s: _register_treesitter_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_adapter_registry_tools": lambda s: _register_adapter_registry_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_pycharm_tools": lambda s: _register_pycharm_tools(s._mhv_server),  # type: ignore[attr-defined]
    "_register_search_tools": lambda s: _register_search_tools(s._mhv_server),  # type: ignore[attr-defined]
    # Plan index tools (Task 12). ``_register_plan_tools`` resolves the
    # Dhara client from ``MahavishnuApp`` and registers the five
    # ``plan_*`` tools in one call. The store is constructed fresh per
    # registration, matching the per-tool closure pattern.
    "_register_plan_tools": lambda s: _register_plan_tools(s._mhv_server),  # type: ignore[attr-defined]
    # Jot inbox tools (Task 13). Each key delegates to the same
    # ``_register_jot_tools`` callable (imported from .jot_tools) which
    # is idempotent — the first call wraps the 8 tools against the
    # server, subsequent calls re-bind the wrappers harmlessly.
    "jot_list": lambda s: _register_jot_tools(s._mhv_server),  # type: ignore[attr-defined]
    "jot_show": lambda s: _register_jot_tools(s._mhv_server),  # type: ignore[attr-defined]
    "jot_add": lambda s: _register_jot_tools(s._mhv_server),  # type: ignore[attr-defined]
    "jot_edit": lambda s: _register_jot_tools(s._mhv_server),  # type: ignore[attr-defined]
    "jot_done": lambda s: _register_jot_tools(s._mhv_server),  # type: ignore[attr-defined]
    "jot_reopen": lambda s: _register_jot_tools(s._mhv_server),  # type: ignore[attr-defined]
    "jot_vitals": lambda s: _register_jot_tools(s._mhv_server),  # type: ignore[attr-defined]
    "jot_search": lambda s: _register_jot_tools(s._mhv_server),  # type: ignore[attr-defined]
}


# Per-repo always-on group keys. The W0 helper (now mcp-common
# mcp_common.tools.dispatch) walks this set AFTER per-profile registration
# so each listed group is guaranteed at every profile. Mahavishnu's health,
# ecosystem, workflow, and webhook groups are infrastructure-critical
# (K8s probes, observability, Mahavishnu's own async workflows) — they
# MUST be present at MINIMAL.
#
# W0.5 rename: this was previously MAHAVISHNU_MANDATORY_TOOLS because the
# pre-W0.5 helper conflated "always-on group keys" with "subset-check tool
# names". The old name was misleading; the new canonical parameter is
# `mandatory_groups` (dispatch driver) and the subset check is a separate
# `essential_tool_names` parameter (default: MANDATORY_TOOLS).
MAHAVISHNU_MANDATORY_GROUPS: set[str] = {
    "_register_health_tools",
    "_register_ecosystem_tools",
    "_register_workflow_tools",
    "_register_webhook_tools",
    # Phase 1.5 — see §10.3.1.
    "_register_skills_signer_tools",
    # Phase 3 — agents MUST be reachable at every tier (per plan §5
    # Phase 3 task #5). The specialist dispatcher reads list_agents
    # at runtime, so the metadata must be available even at MINIMAL.
    "_register_agents_tools",
    # Phase 3 task #5 — dispatcher is the entry point that workflows
    # invoke to resolve a category-named specialist (e.g.
    # ``mahavishnu_dispatch_specialist("dhara", "storage")``). Without
    # this dispatcher the 3 new specialists (dhara-specialist,
    # crackerjack-specialist, session-buddy-specialist) become
    # orphans: discoverable but never invoked from a workflow.
    "_register_dispatch_specialist_tools",
}


def settings_yaml_loader() -> dict | None:
    """Load ``tool_profile`` key from mahavishnu's settings (Oneiric layered).

    Returns ``{"tool_profile": <value>}`` when the key is set, else ``None``.
    The W0 helper uses this to fall back when ``MAHAVISHNU_TOOL_PROFILE`` is
    unset, preserving env > yaml > default precedence.
    """
    try:
        from mahavishnu.core.config import get_settings

        tool_profile = getattr(get_settings(), "tool_profile", None)
        if tool_profile:
            return {"tool_profile": str(tool_profile)}
    except Exception:  # noqa: BLE001 - YAML loader is best-effort
        return None
    return None
