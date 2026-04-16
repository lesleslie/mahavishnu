"""Unit tests for core.unified_orchestrator."""

from __future__ import annotations

import builtins
import importlib
from types import SimpleNamespace

import pytest

import mahavishnu.core.unified_orchestrator as uo
from mahavishnu.core.errors import MahavishnuError


class _FakeStateManager:
    def __init__(self) -> None:
        self.states: dict[str, dict] = {}
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []

    async def create_workflow_state(
        self,
        workflow_id: str,
        adapter_type: str,
        initial_state: dict,
    ) -> dict:
        self.create_calls.append(
            {
                "workflow_id": workflow_id,
                "adapter_type": adapter_type,
                "initial_state": initial_state,
            }
        )
        self.states[workflow_id] = {
            "workflow_id": workflow_id,
            "adapter_states": {adapter_type: dict(initial_state)},
        }
        return self.states[workflow_id]

    async def update_adapter_state(self, workflow_id: str, adapter_type: str, state: dict) -> dict:
        self.update_calls.append(
            {"workflow_id": workflow_id, "adapter_type": adapter_type, "state": dict(state)}
        )
        wf = self.states.setdefault(workflow_id, {"workflow_id": workflow_id, "adapter_states": {}})
        wf["adapter_states"][str(adapter_type)] = dict(state)
        return wf

    async def get_workflow_state(self, workflow_id: str):
        return self.states.get(workflow_id)


class _Adapter:
    def __init__(self, *, cancel_error: Exception | None = None, health_error: Exception | None = None):
        self.cancel_calls: list[str] = []
        self.cancel_error = cancel_error
        self.health_error = health_error

    async def cancel_workflow(self, workflow_id: str) -> None:
        self.cancel_calls.append(workflow_id)
        if self.cancel_error is not None:
            raise self.cancel_error

    async def get_health(self) -> dict:
        if self.health_error is not None:
            raise self.health_error
        return {"status": "healthy"}


class _AdapterManager:
    def __init__(self, adapters: dict) -> None:
        self.adapters = adapters

    def get_adapter(self, name):  # noqa: ANN001
        # unified_orchestrator passes string adapter names from saved state.
        return self.adapters.get(name)


class _FakeTaskRouter:
    def __init__(self, execution_results: list[dict] | None = None, adapters: dict | None = None):
        self.state_manager = _FakeStateManager()
        self.adapter_manager = _AdapterManager(adapters or {})
        self._execution_results = execution_results or []
        self.execute_calls: list[dict] = []

    async def execute_with_fallback(self, **kwargs):  # noqa: ANN003
        self.execute_calls.append(kwargs)
        if self._execution_results:
            return self._execution_results.pop(0)
        return {"success": True, "adapter": uo.AdapterType.PREFECT, "result": "exec", "fallback_chain": [uo.AdapterType.PREFECT], "total_attempts": 1}

    async def get_health(self) -> dict:
        return {"status": "healthy", "routing_mode": "statistical"}


@pytest.mark.asyncio
async def test_init_uses_default_or_custom_task_router(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = _FakeTaskRouter()
    orchestrator = uo.UnifiedOrchestrator(task_router=sentinel)
    assert orchestrator.task_router is sentinel

    created: list[_FakeTaskRouter] = []

    def factory():  # noqa: ANN202
        inst = _FakeTaskRouter()
        created.append(inst)
        return inst

    monkeypatch.setattr(uo, "TaskRouter", factory)
    orch2 = uo.UnifiedOrchestrator()
    assert orch2.task_router is created[0]


@pytest.mark.asyncio
async def test_execute_workflow_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uo, "generate_config_id", lambda: "wf-fixed-id")
    router = _FakeTaskRouter(
        execution_results=[
            {
                "success": True,
                "adapter": uo.AdapterType.PREFECT,
                "result": "exec-1",
                "fallback_chain": [uo.AdapterType.PREFECT],
                "total_attempts": 1,
            },
            {
                "success": True,
                "adapter": uo.AdapterType.AGNO,
                "result": "exec-2",
                "fallback_chain": [uo.AdapterType.PREFECT, uo.AdapterType.AGNO],
                "total_attempts": 2,
            },
        ]
    )
    orchestrator = uo.UnifiedOrchestrator(task_router=router)

    workflow_id = await orchestrator.execute_workflow(
        workflow_name="my-flow",
        workflow_type="workflow",
        tasks=[{"task_type": "workflow"}, {"task_type": "ai_task"}],
        repos=["/repo"],
    )
    assert workflow_id == "wf-fixed-id"
    state = await router.state_manager.get_workflow_state("wf-fixed-id")
    assert state["adapter_states"]["task_router"]["status"] == "completed"
    assert len(state["adapter_states"]["task_router"]["results"]) == 2
    assert state["adapter_states"][uo.AdapterType.PREFECT]["execution_id"] == "exec-1"
    assert state["adapter_states"][uo.AdapterType.AGNO]["execution_id"] == "exec-2"
    assert all("preference_order" not in call for call in router.execute_calls)


@pytest.mark.asyncio
async def test_execute_workflow_failure_marks_failed_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uo, "generate_config_id", lambda: "wf-fail-id")
    router = _FakeTaskRouter(
        execution_results=[
            {
                "success": False,
                "error": "all adapters failed",
                "fallback_chain": [uo.AdapterType.PREFECT, uo.AdapterType.AGNO],
            }
        ]
    )
    orchestrator = uo.UnifiedOrchestrator(task_router=router)

    with pytest.raises(MahavishnuError, match="Workflow execution failed"):
        await orchestrator.execute_workflow(
            workflow_name="broken",
            tasks=[{"task_type": "workflow"}],
        )

    state = await router.state_manager.get_workflow_state("wf-fail-id")
    assert state["adapter_states"]["task_router"]["status"] == "failed"
    assert "all adapters failed" in state["adapter_states"]["task_router"]["error"]


@pytest.mark.asyncio
async def test_get_workflow_status_found_and_not_found() -> None:
    router = _FakeTaskRouter()
    orchestrator = uo.UnifiedOrchestrator(task_router=router)
    router.state_manager.states["wf-1"] = {"workflow_id": "wf-1", "adapter_states": {}}

    found = await orchestrator.get_workflow_status("wf-1")
    assert found["workflow_id"] == "wf-1"

    with pytest.raises(MahavishnuError, match="not found"):
        await orchestrator.get_workflow_status("missing")


@pytest.mark.asyncio
async def test_cancel_workflow_success_with_partial_adapter_failures() -> None:
    good = _Adapter()
    bad = _Adapter(cancel_error=RuntimeError("cancel failed"))
    adapters = {"prefect": good, "agno": bad}
    router = _FakeTaskRouter(adapters=adapters)
    router.state_manager.states["wf-2"] = {
        "workflow_id": "wf-2",
        "adapter_states": {"task_router": {"status": "running"}, "prefect": {}, "agno": {}},
    }
    orchestrator = uo.UnifiedOrchestrator(task_router=router)

    result = await orchestrator.cancel_workflow("wf-2")
    assert result is True
    assert good.cancel_calls == ["wf-2"]
    assert bad.cancel_calls == ["wf-2"]
    state = await router.state_manager.get_workflow_state("wf-2")
    assert state["adapter_states"]["task_router"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_workflow_not_found_raises() -> None:
    orchestrator = uo.UnifiedOrchestrator(task_router=_FakeTaskRouter())
    with pytest.raises(MahavishnuError, match="not found"):
        await orchestrator.cancel_workflow("missing")


@pytest.mark.asyncio
async def test_get_adapter_health_collects_errors() -> None:
    adapters = {
        "prefect": _Adapter(),
        "agno": _Adapter(health_error=RuntimeError("health down")),
    }
    router = _FakeTaskRouter(adapters=adapters)
    orchestrator = uo.UnifiedOrchestrator(task_router=router)

    health = await orchestrator.get_adapter_health()
    assert health["task_router"]["status"] == "healthy"
    assert health["adapters"]["prefect"]["status"] == "healthy"
    assert health["adapters"]["agno"]["status"] == "error"
    assert "health down" in health["adapters"]["agno"]["error"]


def test_generate_config_id_fallback_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name == "oneiric.core.ulid" or name.startswith("oneiric.core.ulid"):
            raise ImportError("oneiric missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    reloaded = importlib.reload(uo)
    generated = reloaded.generate_config_id()
    assert isinstance(generated, str)
    assert len(generated) == 32
