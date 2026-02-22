"""MCP tools for Mahavishnu."""

# Available tool modules:
# - terminal_tools: Terminal management tools
# - coordination_tools: Multi-agent coordination tools
# - otel_tools: OpenTelemetry trace management
# - pool_tools: Pool management tools
# - worker_tools: Worker orchestration tools
# - oneiric_tools: Oneiric configuration tools
# - session_buddy_tools: Session Buddy integration tools
# - repository_messaging_tools: Inter-project messaging tools
# - git_analytics: Git analytics and cross-project aggregation
# - goal_team_tools: Goal-driven team creation and management tools

from .goal_team_tools import register_goal_team_tools

__all__ = [
    "register_goal_team_tools",
]
