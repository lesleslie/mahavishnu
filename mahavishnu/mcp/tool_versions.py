"""Tool version registry for external consumer compatibility tracking.

Maps each MCP tool to a semantic version that increments when the
tool's input schema, output schema, or behavior changes in a way
that could break external consumers.

Version Policy:
- MAJOR: Breaking change (removed field, changed type, different semantics)
- MINOR: Additive change (new optional field, new enum value)
- PATCH: Bug fix or internal change (no schema impact)

Usage:
    from mahavishnu.mcp.tool_versions import TOOL_VERSIONS, get_tool_version

    version = get_tool_version("list_repos")  # "1.0.0"
    all_versions = TOOL_VERSIONS  # dict[str, str]
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Tool version registry
# ---------------------------------------------------------------------------

# Core workflow tools (server_core.py inline)
TOOL_VERSIONS: dict[str, str] = {
    # Workflow orchestration
    "list_repos": "1.0.0",
    "trigger_workflow": "1.1.0",
    "get_workflow_status": "1.0.0",
    "list_workflows": "1.0.0",
    "cancel_workflow": "1.0.0",
    # RBAC
    "create_user": "1.0.0",
    "check_permission": "1.0.0",
    # Observability
    "get_observability_metrics": "1.0.0",
    "search_logs": "1.0.0",
    "search_workflows": "1.0.0",
    "get_workflow_statistics": "1.0.0",
    "get_log_statistics": "1.0.0",
    "get_recovery_metrics": "1.0.0",
    # Backup / recovery
    "create_backup": "2.0.0",
    "list_backups": "1.0.0",
    "restore_backup": "1.0.0",
    "run_disaster_recovery_check": "1.0.0",
    "heal_workflows": "1.0.0",
    # Monitoring
    "get_monitoring_dashboard": "2.0.0",
    "get_active_alerts": "1.0.0",
    "acknowledge_alert": "1.0.0",
    "trigger_test_alert": "1.0.0",
    "flush_metrics": "1.0.0",
    # Adapter / health
    "list_adapters": "1.0.0",
    "get_health": "1.0.0",
    # Terminal tools (terminal_tools.py)
    "terminal_launch": "1.0.0",
    "terminal_send": "1.0.0",
    "terminal_capture": "1.0.0",
    "terminal_capture_all": "1.0.0",
    "terminal_list": "1.0.0",
    "terminal_close": "1.0.0",
    "terminal_close_all": "1.0.0",
    "terminal_list_adapters": "1.0.0",
    "terminal_current_adapter": "1.0.0",
    "terminal_switch_adapter": "1.0.0",
    # Pool tools (pool_tools.py)
    "pool_scale": "1.0.0",
    "pool_close": "1.0.0",
    "pool_close_all": "1.0.0",
    "pool_list": "1.0.0",
    "pool_health": "1.0.0",
    "pool_monitor": "1.0.0",
    "pool_search_memory": "1.0.0",
    # Worker tools (worker_tools.py)
    # Repository messaging tools (repository_messaging_tools.py)
    "send_repository_message": "1.0.0",
    "get_repository_messages": "1.0.0",
    "acknowledge_repository_message": "1.0.0",
    "broadcast_repository_message": "1.0.0",
    "notify_repository_changes": "1.0.0",
    "notify_workflow_status": "1.0.0",
    "send_quality_alert": "1.0.0",
    # Session-Buddy tools (session_buddy_tools.py)
    "index_code_graph": "1.0.0",
    "find_related_code": "1.0.0",
    "get_function_context": "1.0.0",
    "search_documentation": "1.0.0",
    "list_project_messages": "1.0.0",
    "get_repository_health": "1.0.0",
    # OTel tools (otel_tools.py)
    # Health tools (health_tools.py)
    "health_check_service": "1.0.0",
    "health_check_all": "1.0.0",
    "get_liveness": "1.0.0",
    "get_readiness": "1.0.0",
    "mcp_list_tools": "1.0.0",
    "mcp_test_connection": "1.0.0",
    "mcp_get_metrics": "1.0.0",
    "wait_for_dependency": "1.0.0",
    # Self-improvement tools
    "review_and_fix": "1.0.0",
    "get_pending_approvals": "1.0.0",
    "respond_to_approval": "1.0.0",
    "request_approval": "1.0.0",
    # Version query (this module)
    "get_tool_versions": "1.0.0",
    # Tool discovery (server_core.py inline)
    "discover_tools": "1.0.0",
    # Primitive introspection (primitive_tools.py) -- Keystone keystone_show analog
    # Search tools (search_tools.py)
    "delete_document": "1.0.0",
    # OTel tools (otel_tools.py)
    "ingest_otel_traces": "1.0.0",
    "index_document": "1.0.0",
    "get_otel_trace": "1.0.0",
    "otel_ingester_stats": "1.0.0",
    "search_otel_traces": "1.0.0",
    "hybrid_search": "1.0.0",
    "search_by_repository": "1.0.0",
    # Ecosystem/Git analytics tools
    "get_cross_project_patterns": "1.0.0",
    "get_git_velocity_dashboard": "1.0.0",
    # Goal-driven team tools (goal_team_tools.py)
    "list_team_skills": "1.0.0",
    "parse_goal": "1.0.0",
    "team_from_goal": "1.0.0",
    "send_project_message": "1.0.0",
    # Tree-sitter tools (treesitter_tools.py)
    "treesitter_batch_analyze": "1.0.0",
    "treesitter_cache_stats": "1.0.0",
    "treesitter_clear_cache": "1.0.0",
    "treesitter_extract_symbols": "1.0.0",
    "treesitter_find_usages": "1.0.0",
    "treesitter_parse": "1.0.0",
    "treesitter_query": "1.0.0",
    # Worktree tools
    # Health tools - wait
    "wait_for_all_dependencies": "1.0.0",
    # Documentation indexing
    "index_documentation": "1.0.0",
    # Ecosystem status tools (ecosystem_tools.py) -- Control Plane Phase 3
    "ecosystem_status": "1.0.0",
    "ecosystem_capabilities": "1.0.0",
    "ecosystem_routing_readiness": "1.0.0",
    # Workflow outcome tools (workflow_tools.py)
    "workflow_get_outcome_tool": "1.0.0",
    # Primitive introspection wrappers (primitive_tools.py)
    "list_primitives_tool": "1.0.0",
    "show_primitive_tool": "1.0.0",
    # Clone detection / refactor tools (clone_tools.py)
    "clone_detect_ecosystem": "1.0.0",
    "clone_refactor_group": "1.0.0",
    "clone_refactor_status": "1.0.0",
    "get_verification_result": "1.0.0",
    # Session-Buddy channel tools (session_buddy_tools.py)
    "track_channel_session": "1.0.0",
    "get_channel_sessions": "1.0.0",
    # Self-improvement tools (self_improvement_tools.py)
    "self_improvement_analyze_failures": "1.0.0",
    "self_improvement_generate": "1.0.0",
    "self_improvement_status": "1.0.0",
    # OpenTelemetry local trace query (otel_tools.py)
    "query_local_traces": "2.0.0",
    # PyCharm IDE tools (pycharm_tools.py)
    "pycharm_health": "1.0.0",
    "pycharm_run_diagnostics": "1.0.0",
    "pycharm_open_file": "1.0.0",
    "pycharm_search_in_project": "1.0.0",
    "pycharm_replace_in_file": "1.0.0",
    "pycharm_reformat_file": "1.0.0",
    "pycharm_refactor_symbol": "1.0.0",
    "pycharm_list_problems": "1.0.0",
    # Webhook replay tool (webhook_tools.py)
    "webhook_replay_tool": "1.0.0",
    # Capability resolver/planner/executor tools (capability_tools.py)
    "execute_capability": "1.0.0",
    "list_capabilities": "1.0.0",
    # MCP envelope reader (get_capability_result_tool.py)
    "get_capability_result": "1.0.0",
    # Worker contract tools (worker_contract_tools.py)
    "cancel_worker": "1.0.0",
    "capture_output": "1.0.0",
    "launch_worker": "1.0.0",
    "send_input": "1.0.0",
    "wait_for_state": "1.0.0",
    "worker_revoke": "1.0.0",
    "worker_run_with_settle": "1.0.0",
    "worker_settle": "1.0.0",
    "worker_status": "1.0.0",
    # Pool tools (pool_tools.py) -- additions
    "pool_bootstrap": "1.0.0",
    "pool_route_execute": "1.0.0",
    "pool_spawn": "1.0.0",
    # OpenHands tools (openhands_tools.py) -- component-prefixed
    "openhands_openhands_cancel": "1.0.0",
    "openhands_openhands_health": "1.0.0",
    "openhands_openhands_run": "1.0.0",
    "openhands_openhands_status": "1.0.0",
    # Jot inbox tools (jot_tools.py)
    "jot_add": "1.0.0",
    "jot_defer": "1.0.0",
    "jot_delete": "1.0.0",
    "jot_done": "1.0.0",
    "jot_drain": "1.0.0",
    "jot_dispatch": "1.0.0",
    "jot_edit": "1.0.0",
    "jot_export_markdown": "1.0.0",
    "jot_list": "1.0.0",
    "jot_reopen": "1.0.0",
    "jot_resurface": "1.0.0",
    "jot_retry": "1.0.0",
    "jot_search": "1.0.0",
    "jot_show": "1.0.0",
    "jot_vitals": "1.0.0",
    # Plan index tools (plan_tools.py)
    "plan_capability": "1.0.0",
    "plan_list": "1.0.0",
    "plan_rebuild_status": "1.0.0",
    "plan_search": "1.0.0",
    "plan_show": "1.0.0",
    "plan_vitals": "1.0.0",
    # Capability resolver (capability_tools.py) -- additions
    "resolve_capabilities": "1.0.0",
    # Agent and skill catalogue tools (agents_tools.py, skill_tools.py)
    "mahavishnu_get_agent": "1.0.0",
    "mahavishnu_list_agents": "1.0.0",
    "mahavishnu_get_skill": "1.0.0",
    "mahavishnu_list_skills": "1.0.0",
    # Ecosystem service registry and event log
    "mahavishnu_get_publish_url": "1.0.0",
    "mahavishnu_get_service": "1.0.0",
    "mahavishnu_list_events": "1.0.0",
    "mahavishnu_list_services": "1.0.0",
    "mahavishnu_record_event": "1.0.0",
    "mahavishnu_upsert_service": "1.0.0",
    # Key-value state store (core/state_backends/mcp_kv.py)
    "mahavishnu_kv_delete": "1.0.0",
    "mahavishnu_kv_get": "1.0.0",
    "mahavishnu_kv_list": "1.0.0",
    "mahavishnu_kv_put": "1.0.0",
    # Specialist dispatch (dispatch_specialist.py)
    "mahavishnu_dispatch_specialist": "1.0.0",
    "mahavishnu_list_specialists": "1.0.0",
    # Budget enforcement (budget_tools.py)
    "mahavishnu_budget_enforce": "1.0.0",
    # Health audit (audit_health_tool.py)
    "audit_health": "1.0.0",
    # Cross-repo search (core/cross_repo_search.py)
    "cross_repo_search": "1.0.0",
    # Bodai task system dispatch edge (server_core.py inline)
    "tasks_handoff_to_workflow": "1.0.0",
}


def get_tool_version(tool_name: str) -> str | None:
    """Get version string for a named tool.

    Args:
        tool_name: Name of the MCP tool.

    Returns:
        Semver string (e.g. "1.0.0") or None if unregistered.
    """
    return TOOL_VERSIONS.get(tool_name)


def get_all_tool_versions() -> dict[str, str]:
    """Return copy of the full version registry."""
    return dict(TOOL_VERSIONS)


# ---------------------------------------------------------------------------
# Deprecation registry
# ---------------------------------------------------------------------------

# Tools that previously had a deprecation marker with a replacement tool
# have been promoted to their replacement. Each entry maps the deprecated
# tool name to the canonical replacement (or ``None`` if no direct
# replacement exists). Used by ``get_tool_deprecation`` / ``is_tool_deprecated``
# and consumed by health_tools.py's deprecation-warning logic.
DEPRECATED_TOOLS: dict[str, str | None] = {
    # health_tools.py: the bulk-aggregate call replaces the per-service one.
    "health_check_service": "health_check_all",
    # Session-Buddy code-intel tools — moved into ``code_index`` /
    # ``treesitter_tools`` / ``search_tools`` once those MCP groups landed.
    "index_code_graph": "code_index.index_repo",
    "find_related_code": "treesitter_tools",
    "index_documentation": "code_index.index_repo",
    "search_documentation": "search_tools.hybrid_search",
    # Legacy monitoring dashboard is the new ecosystem_status aggregator.
    "get_monitoring_dashboard": "ecosystem_status",
}


def get_tool_deprecation(tool_name: str) -> str | None:
    """Return the preferred replacement tool for a deprecated tool.

    Returns ``None`` for non-deprecated tools or when no direct replacement
    exists yet.
    """
    return DEPRECATED_TOOLS.get(tool_name)


def is_tool_deprecated(tool_name: str) -> bool:
    """Return whether a tool is marked deprecated."""
    return tool_name in DEPRECATED_TOOLS


__all__ = [
    "DEPRECATED_TOOLS",
    "TOOL_VERSIONS",
    "get_all_tool_versions",
    "get_tool_deprecation",
    "get_tool_version",
    "is_tool_deprecated",
]
