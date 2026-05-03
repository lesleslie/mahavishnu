"""MCP tools for Mahavishnu."""

# Available tool modules:
# - terminal_tools: Terminal management tools
# - coordination_tools: Multi-agent coordination tools
# - otel_tools: OpenTelemetry trace management
# - pool_tools: Pool management tools
# - worker_tools: Worker orchestration tools
# - session_buddy_tools: Session Buddy integration tools
# - repository_messaging_tools: Inter-project messaging tools
# - git_analytics: Git analytics and cross-project aggregation
# - goal_team_tools: Goal-driven team creation and management tools
# - team_learning_tools: [DEPRECATED] De-authorized from live MCP (Bodai I0.4).
#   skill_governance.py is the canonical learning authority. Module retained
#   for CLI-only use and backward compat.
# - treesitter_tools: Tree-sitter code parsing and analysis tools
# - adapter_registry_tools: Hybrid adapter registry management tools
# - search_tools: Hybrid search (semantic + lexical) tools

from .adapter_registry_tools import register_adapter_registry_tools
from .goal_team_tools import register_goal_team_tools
from .search_tools import register_search_tools

# team_learning_tools de-authorized from MCP registration (Bodai I0.4).
# skill_governance.py is the canonical learning authority.
# Module still importable for CLI use via team_cli.py.
from .treesitter_tools import register_treesitter_tools

__all__ = [
    "register_adapter_registry_tools",
    "register_goal_team_tools",
    # "register_team_learning_tools" — de-authorized (Bodai I0.4)
    "register_treesitter_tools",
    "register_search_tools",
]
