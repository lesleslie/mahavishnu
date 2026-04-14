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
    "create_backup": "1.0.0",
    "list_backups": "1.0.0",
    "restore_backup": "1.0.0",
    "run_disaster_recovery_check": "1.0.0",
    "heal_workflows": "1.0.0",
    # Monitoring
    "get_monitoring_dashboard": "1.0.0",
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
    "terminal_launch_with_profile": "1.0.0",
    "terminal_list_profiles": "1.0.0",
    # Pool tools (pool_tools.py)
    "pool_spawn": "1.0.0",
    "pool_execute": "1.0.0",
    "pool_route_execute": "1.0.0",
    "pool_scale": "1.0.0",
    "pool_close": "1.0.0",
    "pool_close_all": "1.0.0",
    "pool_list": "1.0.0",
    "pool_health": "1.0.0",
    "pool_monitor": "1.0.0",
    "pool_search_memory": "1.0.0",
    # Worker tools (worker_tools.py)
    "worker_spawn": "1.0.0",
    "worker_execute": "1.0.0",
    "worker_execute_batch": "1.0.0",
    "worker_collect_results": "1.0.0",
    "worker_list": "1.0.0",
    "worker_close": "1.0.0",
    "worker_close_all": "1.0.0",
    "worker_health": "1.0.0",
    "worker_monitor": "1.0.0",
    # Coordination tools (coordination_tools.py)
    "list_issues": "1.0.0",
    "create_issue": "1.0.0",
    "update_issue": "1.0.0",
    "list_todos": "1.0.0",
    "create_todo": "1.0.0",
    "update_todo": "1.0.0",
    "list_dependencies": "1.0.0",
    "add_dependency": "1.0.0",
    "remove_dependency": "1.0.0",
    "get_dependency_graph": "1.0.0",
    "detect_circular_dependencies": "1.0.0",
    "get_critical_path": "1.0.0",
    "generate_mermaid_diagram": "1.0.0",
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
    "store_code_graph_from_mahavishnu": "1.0.0",
    "list_project_messages": "1.0.0",
    "get_repository_health": "1.0.0",
    # OTel tools (otel_tools.py)
    "otel_ingest_trace": "1.0.0",
    "otel_search_traces": "1.0.0",
    "otel_get_trace": "1.0.0",
    "otel_get_stats": "1.0.0",
    # Health tools (health_tools.py)
    "health_check": "1.0.0",
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
    # Adapter registry tools (adapter_registry_tools.py)
    "adapter_cache_invalidate": "1.0.0",
    "adapter_discover": "1.0.0",
    "adapter_enable": "1.0.0",
    "adapter_health": "1.0.0",
    "adapter_list": "1.0.0",
    "adapter_metadata": "1.0.0",
    "adapter_resolve": "1.0.0",
    # Desktop automation tools (desktop_automation_tools.py)
    "automation_activate_app": "1.0.0",
    "automation_check_permissions": "1.0.0",
    "automation_click": "1.0.0",
    "automation_click_menu": "1.0.0",
    "automation_close": "1.0.0",
    "automation_close_window": "1.0.0",
    "automation_drag": "1.0.0",
    "automation_get_active_app": "1.0.0",
    "automation_get_security_config": "1.0.0",
    "automation_get_ui_elements": "1.0.0",
    "automation_launch_app": "1.0.0",
    "automation_list_apps": "1.0.0",
    "automation_list_menus": "1.0.0",
    "automation_list_screens": "1.0.0",
    "automation_list_windows": "1.0.0",
    "automation_move_window": "1.0.0",
    "automation_press_key": "1.0.0",
    "automation_quit_app": "1.0.0",
    "automation_resize_window": "1.0.0",
    "automation_screenshot": "1.0.0",
    "automation_scroll": "1.0.0",
    "automation_status": "1.0.0",
    "automation_type_text": "1.0.0",
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
    # Coordination tools (coordination_tools.py - extended)
    "coord_check_dependencies": "1.0.0",
    "coord_close_issue": "1.0.0",
    "coord_complete_todo": "1.0.0",
    "coord_create_issue": "1.0.0",
    "coord_create_todo": "1.0.0",
    "coord_get_blocking_issues": "1.0.0",
    "coord_get_issue": "1.0.0",
    "coord_get_repo_status": "1.0.0",
    "coord_get_todo": "1.0.0",
    "coord_list_dependencies": "1.0.0",
    "coord_list_issues": "1.0.0",
    "coord_list_plans": "1.0.0",
    "coord_list_todos": "1.0.0",
    "coord_update_issue": "1.0.0",
    # Ecosystem/Git analytics tools
    "get_cross_project_patterns": "1.0.0",
    "get_git_velocity_dashboard": "1.0.0",
    # Goal-driven team tools (goal_team_tools.py)
    "get_learning_stats": "1.0.0",
    "get_learning_summary": "1.0.0",
    "get_recommended_mode": "1.0.0",
    "list_team_skills": "1.0.0",
    "parse_goal": "1.0.0",
    "record_team_outcome": "1.0.0",
    "record_user_feedback": "1.0.0",
    "team_from_goal": "1.0.0",
    "send_project_message": "1.0.0",
    # Oneiric integration tools
    "oneiric_check_health": "1.0.0",
    "oneiric_get_adapter": "1.0.0",
    "oneiric_health_check": "1.0.0",
    "oneiric_invalidate_cache": "1.0.0",
    "oneiric_list_adapters": "1.0.0",
    "oneiric_resolve_adapter": "1.0.0",
    # Tree-sitter tools (treesitter_tools.py)
    "treesitter_batch_analyze": "1.0.0",
    "treesitter_cache_stats": "1.0.0",
    "treesitter_clear_cache": "1.0.0",
    "treesitter_extract_symbols": "1.0.0",
    "treesitter_find_usages": "1.0.0",
    "treesitter_parse": "1.0.0",
    "treesitter_query": "1.0.0",
    # Worktree tools
    "create_ecosystem_worktree": "1.0.0",
    "get_worktree_provider_health": "1.0.0",
    "get_worktree_safety_status": "1.0.0",
    "list_ecosystem_worktrees": "1.0.0",
    "prune_ecosystem_worktrees": "1.0.0",
    "remove_ecosystem_worktree": "1.0.0",
    # Health tools - wait
    "wait_for_all_dependencies": "1.0.0",
    # Documentation indexing
    "index_documentation": "1.0.0",
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


__all__ = [
    "TOOL_VERSIONS",
    "get_tool_version",
    "get_all_tool_versions",
]
