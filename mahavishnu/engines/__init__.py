"""Engines module for Mahavishnu orchestrator.

All adapters are lazily imported via __getattr__ to avoid pulling in
optional heavy dependencies (LlamaIndex, Prefect, etc.) at package import time.
"""

__all__ = [
    "AgnoAdapter",
    "GoalDrivenTeamFactory",
    "ParsedGoal",
    "SkillConfig",
    "LlamaIndexAdapter",
    "PrefectAdapter",
]

# Mapping of export name -> (relative_module, attribute_name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "AgnoAdapter": (".agno_adapter_impl", "AgnoAdapter"),
    "GoalDrivenTeamFactory": (".goal_team_factory", "GoalDrivenTeamFactory"),
    "ParsedGoal": (".goal_team_factory", "ParsedGoal"),
    "SkillConfig": (".goal_team_factory", "SkillConfig"),
    "LlamaIndexAdapter": (".llamaindex_adapter_impl", "LlamaIndexAdapter"),
    "PrefectAdapter": (".prefect_adapter_impl", "PrefectAdapter"),
}


def __getattr__(name: str):
    """Lazy import to avoid heavy initialization on package import."""
    if entry := _LAZY_IMPORTS.get(name):
        from importlib import import_module

        module = import_module(entry[0], __name__)
        return getattr(module, entry[1])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
