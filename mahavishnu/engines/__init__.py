"""Engines module for Mahavishnu orchestrator.

Adapters are imported with lazy loading to avoid dependency issues.
Individual adapters can be imported when needed.
"""

from .agno_adapter import AgnoAdapter
from .goal_team_factory import GoalDrivenTeamFactory, ParsedGoal, SkillConfig

# Try to import LlamaIndex adapter (may fail if dependencies not installed)
try:
    from .llamaindex_adapter import LlamaIndexAdapter

    _llamaindex_available = True
except ImportError:
    LlamaIndexAdapter = None
    _llamaindex_available = False

# Try to import Prefect adapter (may fail if prefect not installed)
try:
    from .prefect_adapter import PrefectAdapter

    _prefect_available = True
except ImportError:
    PrefectAdapter = None
    _prefect_available = False

__all__ = [
    "AgnoAdapter",
    "GoalDrivenTeamFactory",
    "ParsedGoal",
    "SkillConfig",
]

# Only add adapters that are available
if _llamaindex_available:
    __all__.append("LlamaIndexAdapter")

if _prefect_available:
    __all__.append("PrefectAdapter")
