"""Engines module for Mahavishnu orchestrator.

All adapters are lazily imported via __getattr__ to avoid pulling in
optional heavy dependencies (LlamaIndex, Prefect, etc.) at package import time.

``load_engine_registrations`` (Task 2.7.1) is the single entry point for the
conductor to discover enabled engines and their ``provides`` lists, without
each callsite importing engine modules directly. Engines listed in
``settings.engines.disabled`` are skipped. Adapters behind optional
dependency groups (pydantic_ai) are silently skipped when the underlying
module is not importable.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from mahavishnu.core.capabilities import EngineRegistration

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings

__all__ = [
    "AgnoAdapter",
    "GoalDrivenTeamFactory",
    "LlamaIndexAdapter",
    "ParsedGoal",
    "PrefectAdapter",
    "SkillConfig",
    "load_engine_registrations",
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

_LAZY_MODULES = {
    "agno_adapter_impl",
    "goal_team_factory",
    "llamaindex_adapter_impl",
    "prefect_adapter_impl",
}


def __getattr__(name: str):
    """Lazy import to avoid heavy initialization on package import."""
    if entry := _LAZY_IMPORTS.get(name):
        from importlib import import_module

        module = import_module(entry[0], __name__)
        return getattr(module, entry[1])
    if name in _LAZY_MODULES:
        from importlib import import_module
        import sys

        module_name = f"{__name__}.{name}"
        if module_name in sys.modules:
            return sys.modules[module_name]
        return import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Engine registration helper (Task 2.7.1)
# ---------------------------------------------------------------------------


def _async_return(value: Any):
    """Build a no-op coroutine returning ``value`` (used by stub worker manager)."""

    async def _coro() -> Any:
        return value

    return _coro


def _make_stub_worker_manager():
    """Return a minimal WorkerManager stub for capability-loading only.

    The full WorkerOrchestratorAdapter constructor requires either a real
    ``WorkerManager`` or a MahavishnuSettings config — both too heavy for
    the capability-loader call site. This stub satisfies the constructor
    (``worker_manager=...`` branch) without wiring any real terminals.
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        execute_batch=lambda *a, **kw: {},
        spawn_workers=lambda *a, **kw: [],
        collect_results=lambda *a, **kw: {},
        health_check=lambda: _async_return({"workers_active": 0, "max_concurrent": 0}),
    )


# (engine_id, import_path, class_name, init_kwargs). Resolved lazily so lean
# installs (no `ai` dep group) don't hard-fail.
_ENGINE_LOCATIONS: list[tuple[str, str, str, dict[str, object]]] = [
    ("prefect", "mahavishnu.engines.prefect_adapter_impl", "PrefectAdapter", {}),
    ("llamaindex", "mahavishnu.engines.llamaindex_adapter_impl", "LlamaIndexAdapter", {}),
    ("agno", "mahavishnu.engines.agno_adapter_impl", "AgnoAdapter", {}),
    ("hatchet", "mahavishnu.engines.hatchet_adapter_impl", "HatchetAdapterImpl", {}),
    ("pydantic_ai", "mahavishnu.adapters.ai.pydantic_ai_adapter", "PydanticAIAdapter", {}),
    (
        "worker",
        "mahavishnu.core.adapters.worker",
        "WorkerOrchestratorAdapter",
        {"worker_manager": _make_stub_worker_manager()},
    ),
]


def _try_load_adapter(import_path: str, class_name: str, init_kwargs: dict[str, object]):
    """Return an adapter instance, or None if the module is missing."""
    try:
        module = importlib.import_module(import_path)
    except ImportError:
        return None
    return getattr(module, class_name)(**init_kwargs)


def load_engine_registrations(
    settings: "MahavishnuSettings",
) -> list[EngineRegistration]:
    """Materialize an ``EngineRegistration`` per enabled adapter.

    Skips engines listed in ``settings.engines.disabled`` and silently
    drops adapters whose backing module cannot be imported (e.g.
    pydantic_ai when the optional ``ai`` dependency group is not
    installed). The conductor (Phase 3a) consumes this list to resolve
    ``requires`` capabilities against ``provides`` lists.
    """
    disabled = set(settings.engines.disabled)
    regs: list[EngineRegistration] = []
    for engine_id, import_path, class_name, init_kwargs in _ENGINE_LOCATIONS:
        if engine_id in disabled:
            continue
        adapter = _try_load_adapter(import_path, class_name, init_kwargs)
        if adapter is None:
            continue  # optional dep group not installed
        regs.append(
            EngineRegistration(
                engine_id=engine_id,
                provides=adapter.provides,
                enabled=True,
            )
        )
    return regs
