"""Bodai Phase 0 regression tests.

Validates boundary hardening items from the Bodai I0 checklist:
- I0.1/I0.2: Task-class-aware routing (no global Prefect-first)
- I0.5: StateManager persistence (survives restart)
- I0.6: workflow_state.py deprecation
- I0.7: Agno memory defaults (NONE, not SQLite)
- I0.8/I0.9: team_learning de-authorization and TUI read-only
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mahavishnu.core.adapters.base import AdapterCapabilities, AdapterType, OrchestratorAdapter
import mahavishnu.core.task_router as tr


class _StubAdapter(OrchestratorAdapter):
    def __init__(self, adapter_type: AdapterType) -> None:
        self._adapter_type = adapter_type
        self._caps = AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            supports_batch_execution=True,
            supports_multi_agent=True,
        )

    async def initialize(self) -> None: ...
    @property
    def adapter_type(self) -> AdapterType: return self._adapter_type
    @property
    def name(self) -> str: return self._adapter_type.value
    @property
    def capabilities(self) -> AdapterCapabilities: return self._caps
    async def execute(self, task: dict, repos: list) -> dict: return {}
    async def get_health(self) -> dict: return {"status": "healthy"}
    async def is_available(self) -> bool: return True


@pytest.fixture
async def router():
    mgr = tr.AdapterManager()
    for at in AdapterType:
        await mgr.register_adapter(at, _StubAdapter(at))
    return tr.TaskRouter(adapter_registry=mgr, state_manager=tr.StateManager())


# ── I0.1/I0.2: Task-class-aware routing ──────────────────────────────


@pytest.mark.asyncio
async def test_ai_task_routes_to_agno_first(router) -> None:
    result = await router.route({"task_type": "ai_task"})
    assert result["success"]
    assert result["adapter"] == AdapterType.AGNO


@pytest.mark.asyncio
async def test_rag_query_routes_to_llamaindex_first(router) -> None:
    result = await router.route({"task_type": "rag_query"})
    assert result["success"]
    assert result["adapter"] == AdapterType.LLAMAINDEX


@pytest.mark.asyncio
async def test_workflow_routes_to_prefect_first(router) -> None:
    result = await router.route({"task_type": "workflow"})
    assert result["success"]
    assert result["adapter"] == AdapterType.PREFECT


@pytest.mark.asyncio
async def test_batch_task_routes_to_prefect_first(router) -> None:
    result = await router.route({"task_type": "batch_task"})
    assert result["success"]
    assert result["adapter"] == AdapterType.PREFECT


@pytest.mark.asyncio
async def test_interactive_task_routes_to_agno_first(router) -> None:
    result = await router.route({"task_type": "interactive_task"})
    assert result["success"]
    assert result["adapter"] == AdapterType.AGNO


# ── I0.5: StateManager persistence ────────────────────────────────────


@pytest.mark.asyncio
async def test_state_manager_persists_to_file(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    sm1 = tr.StateManager(state_dir=state_dir)
    await sm1.create_workflow_state("w1", AdapterType.PREFECT, {"step": 1})
    await sm1.update_adapter_state("w1", AdapterType.AGNO, {"step": 2})

    # Simulate restart: new StateManager reading from same dir
    sm2 = tr.StateManager(state_dir=state_dir)
    state = await sm2.get_workflow_state("w1")
    assert state is not None
    assert state["workflow_id"] == "w1"
    assert state["adapter_states"]["prefect"]["step"] == 1
    assert state["adapter_states"]["agno"]["step"] == 2


@pytest.mark.asyncio
async def test_state_manager_survives_missing_file(tmp_path: Path) -> None:
    sm = tr.StateManager(state_dir=tmp_path / "nonexistent")
    assert await sm.get_workflow_state("missing") is None
    assert await sm.list_workflows() == []


@pytest.mark.asyncio
async def test_state_manager_list_workflows_across_restart(tmp_path: Path) -> None:
    sm1 = tr.StateManager(state_dir=tmp_path / "state")
    await sm1.create_workflow_state("w1", AdapterType.PREFECT, {})
    await sm1.create_workflow_state("w2", AdapterType.AGNO, {})

    sm2 = tr.StateManager(state_dir=tmp_path / "state")
    listed = await sm2.list_workflows()
    ids = {w["workflow_id"] for w in listed}
    assert ids == {"w1", "w2"}


# ── I0.6: workflow_state.py deprecation ────────────────────────────────


def test_workflow_state_module_is_deprecated() -> None:
    """Importing WorkflowState should emit a deprecation warning."""
    with pytest.warns(DeprecationWarning, match="legacy"):
        from mahavishnu.core.workflow_state import WorkflowState

        _ = WorkflowState()


# ── I0.7: Agno memory defaults ────────────────────────────────────────


def test_agno_memory_defaults_to_none() -> None:
    from mahavishnu.engines.agno_adapter_impl import AgnoMemoryConfig, MemoryBackend

    config = AgnoMemoryConfig()
    assert config.enabled is False
    assert config.backend == MemoryBackend.NONE


# ── I0.8: team_learning de-authorization ──────────────────────────────


def test_team_learning_not_in_mcp_tools_all() -> None:
    from mahavishnu.mcp.tools import __all__ as tools_all

    assert "register_team_learning_tools" not in tools_all


def test_team_learning_not_in_full_profile() -> None:
    from mahavishnu.mcp.tools.profiles import FULL_REGISTRATIONS

    assert "_register_team_learning_tools" not in FULL_REGISTRATIONS


# ── I0.9: TUI read-only boundary ─────────────────────────────────────


def test_tui_modules_have_no_persistence_writes() -> None:
    """TUI code should not write to any database or state store."""
    tui_dir = Path(__file__).resolve().parent.parent.parent / "mahavishnu" / "tui"
    if not tui_dir.is_dir():
        pytest.skip("TUI directory not found")

    py_files = list(tui_dir.rglob("*.py"))
    for f in py_files:
        src = f.read_text()
        # No direct DB writes
        assert ".write(" not in src or ".write_text(" not in src, (
            f"{f.relative_to(tui_dir)}: unexpected .write() call"
        )
        # No open-for-write patterns
        assert 'open(' not in src or '"w"' not in src, (
            f"{f.relative_to(tui_dir)}: unexpected file open for write"
        )


# ── TaskType enum completeness ──────────────────────────────────────────


def test_task_type_enum_has_all_required_types() -> None:
    expected = {"workflow", "ai_task", "rag_query", "batch_task", "interactive_task"}
    actual = {t.value for t in tr.TaskType}
    assert actual == expected
