"""Additional unit tests for core.task_router non-fallback paths."""

from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace

import pytest

from mahavishnu.core.adapters.base import AdapterCapabilities, AdapterType, OrchestratorAdapter
from mahavishnu.core.status import WorkflowStatus
import mahavishnu.core.task_router as tr


class _AvailableAdapter(OrchestratorAdapter):
    def __init__(self, adapter_type: AdapterType, available: bool = True) -> None:
        self._adapter_type = adapter_type
        self._available = available
        self._caps = AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            supports_batch_execution=True,
            supports_multi_agent=True,
        )

    async def initialize(self) -> None:
        return None

    @property
    def adapter_type(self) -> AdapterType:
        return self._adapter_type

    @property
    def name(self) -> str:
        return self._adapter_type.value

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._caps

    async def execute(self, task: dict[str, object], repos: list[str]) -> dict[str, object]:
        return {"execution_id": "01" + "B" * 24}

    async def get_health(self) -> dict[str, object]:
        return {"status": "healthy"}

    async def is_available(self) -> bool:
        return self._available


class _NoHealthAdapter(_AvailableAdapter):
    async def get_health(self) -> dict[str, object]:  # pragma: no cover - intentionally shadowed
        raise RuntimeError("should not be called")


@pytest.mark.asyncio
async def test_adapter_manager_and_state_manager_basics() -> None:
    manager = tr.AdapterManager()
    adapter = _AvailableAdapter(AdapterType.PREFECT)
    await manager.register_adapter(AdapterType.PREFECT, adapter)

    assert manager.get_adapter(AdapterType.PREFECT) is adapter
    assert manager.get_adapter("prefect") is adapter
    assert manager.get_adapter("missing") is None

    manager.record_execution(AdapterType.PREFECT, success=True)
    manager.record_execution(AdapterType.PREFECT, success=False)
    stats = manager.get_statistics()["prefect"]
    assert stats["successes"] == 1
    assert stats["failures"] == 1
    assert stats["total_attempts"] == 2
    assert stats["success_rate"] == 0.5

    state_mgr = tr.StateManager()
    created = await state_mgr.create("w1", {"task_type": "workflow"}, ["repo-a"])
    assert created["workflow_id"] == "w1"
    assert created["status"] == WorkflowStatus.PENDING.value

    await state_mgr.update("w1", status=WorkflowStatus.RUNNING.value, progress=10)
    current = await state_mgr.get("w1")
    assert current is not None
    assert current["status"] == WorkflowStatus.RUNNING.value
    assert current["progress"] == 10

    await state_mgr.create_workflow_state("w1", AdapterType.PREFECT, {"step": 1})
    await state_mgr.update_adapter_state("w1", AdapterType.AGNO, {"step": 2})
    state = await state_mgr.get_workflow_state("w1")
    assert state is not None
    assert state["workflow_id"] == "w1"
    assert "prefect" in state["adapter_states"]
    assert "agno" in state["adapter_states"]

    await state_mgr.add_result("w1", {"repo": "repo-a", "success": True})
    await state_mgr.add_error("w1", {"repo": "repo-b", "error": "boom"})
    assert await state_mgr.get_completed_count("w1") == 2

    listed = await state_mgr.list_workflows(limit=1)
    assert len(listed) == 1
    assert await state_mgr.get_workflow_state("missing") is None
    await state_mgr.delete("w1")
    assert await state_mgr.get("w1") is None


@pytest.mark.asyncio
async def test_task_router_analyze_route_and_health_paths() -> None:
    manager = tr.AdapterManager()
    await manager.register_adapter(
        AdapterType.PREFECT, _AvailableAdapter(AdapterType.PREFECT, True)
    )
    await manager.register_adapter(AdapterType.AGNO, _AvailableAdapter(AdapterType.AGNO, True))
    await manager.register_adapter(
        AdapterType.LLAMAINDEX, _AvailableAdapter(AdapterType.LLAMAINDEX, True)
    )
    router = tr.TaskRouter(adapter_registry=manager, state_manager=tr.StateManager())

    analysis = await router.analyze_task({"task_type": "workflow", "needs_monitoring": True})
    assert analysis["task_type"] == "workflow"
    assert analysis["recommended_adapter"] == AdapterType.PREFECT
    assert analysis["routing_mode"] == router.router_mode.value

    routed = await router.route({"task_type": "workflow"})
    assert routed["success"] is True
    assert routed["adapter"] == AdapterType.PREFECT

    ai_routed = await router.route({"task_type": "ai_task"})
    assert ai_routed["success"] is True
    assert ai_routed["adapter"] == AdapterType.AGNO

    rag_routed = await router.route({"task_type": "rag_query"})
    assert rag_routed["success"] is True
    assert rag_routed["adapter"] == AdapterType.LLAMAINDEX

    custom_router = tr.TaskRouter(
        adapter_registry=tr.AdapterManager(), state_manager=tr.StateManager()
    )
    failed = await custom_router.route({"task_type": "workflow"}, preference_order=["agno"])
    assert failed["success"] is False
    assert "No adapter available" in failed["error"]

    health = await router.get_health()
    assert health["status"] == "healthy"
    assert health["adapters_configured"] == 3


@pytest.mark.asyncio
async def test_task_router_adapter_health_branches() -> None:
    manager = tr.AdapterManager()
    router = tr.TaskRouter(adapter_registry=manager, state_manager=tr.StateManager())

    # not configured: invalid adapter
    invalid = await router._get_adapter_health("nope")
    assert invalid["status"] == "not_configured"

    # configured but returns health
    good = _AvailableAdapter(AdapterType.PREFECT)
    await manager.register_adapter(AdapterType.PREFECT, good)
    ok = await router._get_adapter_health(AdapterType.PREFECT)
    assert ok["status"] == "healthy"

    # configured but health check raises
    class _BadAdapter(_AvailableAdapter):
        async def get_health(self) -> dict[str, object]:
            raise RuntimeError("boom")

    await manager.register_adapter(AdapterType.AGNO, _BadAdapter(AdapterType.AGNO))
    bad = await router._get_adapter_health(AdapterType.AGNO)
    assert bad["status"] == "error"
    assert "boom" in bad["error"]

    all_health = await router._get_all_adapter_health()
    assert "prefect" in all_health and "agno" in all_health


@pytest.mark.asyncio
async def test_capability_router_no_registry_and_exception_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tr, "CAPABILITY_ROUTING_AVAILABLE", False)
    router = tr.CapabilityRouter(registry=None)

    no_registry = await router.route(tr.TaskType.AI_TASK, additional_capabilities=["x"])
    assert no_registry["success"] is False
    assert "No adapter registry" in no_registry["error"]
    assert "multi_agent" in no_registry["required_capabilities"]
    assert "x" in no_registry["required_capabilities"]

    class _BadRegistry:
        async def find_by_capabilities(self, caps: list[str]):
            raise RuntimeError("registry failed")

    router.set_registry(_BadRegistry())
    failed = await router.route(tr.TaskType.WORKFLOW)
    assert failed["success"] is False
    assert "registry failed" in failed["error"]
    assert router.get_cache_stats() == {"enabled": False}


@pytest.mark.asyncio
async def test_capability_router_success_without_capability_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tr, "CAPABILITY_ROUTING_AVAILABLE", False)

    class _Match(SimpleNamespace):
        pass

    class _Registry:
        async def find_by_capabilities(self, caps: list[str]):
            return [
                _Match(adapter_id="low", capabilities=caps, priority=1),
                _Match(adapter_id="high", capabilities=caps, priority=9),
            ]

    router = tr.CapabilityRouter(registry=_Registry())
    result = await router.route(tr.TaskType.RAG_QUERY, additional_capabilities=["custom"])
    assert result["success"] is True
    assert result["adapter"] == "high"
    assert "custom" in result["matched_capabilities"]


@pytest.mark.asyncio
async def test_capability_router_with_cache_and_routing_decision_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeCache:
        def __init__(self, ttl_seconds: int = 300) -> None:
            self.ttl_seconds = ttl_seconds
            self.store: dict[str, object] = {}
            self.invalidated = False

        def get(self, key: str):
            return self.store.get(key)

        def set(self, key: str, value: object) -> None:
            self.store[key] = value

        def invalidate(self) -> None:
            self.invalidated = True
            self.store.clear()

        def get_stats(self) -> dict[str, object]:
            return {"enabled": True, "size": len(self.store)}

    class _RoutingDecision:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            self.__dict__.update(kwargs)

    class _Match(SimpleNamespace):
        pass

    class _Registry:
        async def find_by_capabilities(self, caps: list[str]):
            return [_Match(adapter_id="agno", capabilities=caps, priority=10)]

    monkeypatch.setattr(tr, "CAPABILITY_ROUTING_AVAILABLE", True)
    monkeypatch.setattr(tr, "ResolutionCache", _FakeCache)
    monkeypatch.setattr(tr, "RoutingDecision", _RoutingDecision)

    router = tr.CapabilityRouter(registry=_Registry())
    decision = await router.route(tr.TaskType.AI_TASK, additional_capabilities=["x"])
    assert isinstance(decision, _RoutingDecision)
    assert decision.adapter_name == "agno"
    assert "x" in decision.matched_capabilities

    # cache hit path
    decision2 = await router.route(tr.TaskType.AI_TASK, additional_capabilities=["x"])
    assert decision2 is decision

    # cache stats + invalidate branch
    stats = router.get_cache_stats()
    assert stats["enabled"] is True
    router.invalidate_cache()
    assert router._cache is not None and router._cache.invalidated is True


@pytest.mark.asyncio
async def test_capability_router_no_matching_adapter_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tr, "CAPABILITY_ROUTING_AVAILABLE", False)

    class _Registry:
        async def find_by_capabilities(self, caps: list[str]):
            return []

    router = tr.CapabilityRouter(registry=_Registry())
    result = await router.route(tr.TaskType.WORKFLOW)
    assert result["success"] is False
    assert "No adapter found" in result["error"]


@pytest.mark.asyncio
async def test_task_router_normalization_and_analysis_branches() -> None:
    manager = tr.AdapterManager()
    await manager.register_adapter(AdapterType.PREFECT, _AvailableAdapter(AdapterType.PREFECT))
    await manager.register_adapter(AdapterType.AGNO, _AvailableAdapter(AdapterType.AGNO))
    await manager.register_adapter(
        AdapterType.LLAMAINDEX, _AvailableAdapter(AdapterType.LLAMAINDEX)
    )
    router = tr.TaskRouter(adapter_registry=manager, state_manager=tr.StateManager())

    assert router._normalize_task_type(tr.TaskType.AI_TASK) == tr.TaskType.AI_TASK
    assert router._normalize_task_type("rag_query") == tr.TaskType.RAG_QUERY
    assert router._normalize_task_type("unknown") == tr.TaskType.WORKFLOW
    assert router._coerce_adapter_type(None) is None
    assert router._coerce_adapter_type("prefect") == AdapterType.PREFECT
    assert router._coerce_adapter_type("does-not-exist") is None
    assert router._normalize_preference_order(
        [AdapterType.AGNO, "agno", "llamaindex", "missing"]
    ) == [AdapterType.AGNO, AdapterType.LLAMAINDEX]

    ai_analysis = await router.analyze_task({"task_type": "ai_task"})
    assert ai_analysis["recommended_adapter"] == AdapterType.AGNO
    rag_analysis = await router.analyze_task({"task_type": "rag_query"})
    assert rag_analysis["recommended_adapter"] == AdapterType.LLAMAINDEX


@pytest.mark.asyncio
async def test_execute_with_fallback_edge_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = tr.AdapterManager()
    router = tr.TaskRouter(adapter_registry=manager, state_manager=tr.StateManager())

    # branch: adapter missing in registry -> continue
    result = await router.execute_with_fallback(
        {"task_type": "workflow"},
        preference_order=[AdapterType.PREFECT],
        max_retries=1,
    )
    assert result["success"] is False
    assert result["fallback_chain"] == []

    # branch: adapter returns unsuccessful dict -> RuntimeError path
    class _BadResultAdapter(_AvailableAdapter):
        async def execute(self, task: dict[str, object], repos: list[str]) -> dict[str, object]:
            return {"success": False, "error": "adapter failed"}

    await manager.register_adapter(AdapterType.PREFECT, _BadResultAdapter(AdapterType.PREFECT))
    result2 = await router.execute_with_fallback(
        {"task_type": "workflow"},
        preference_order=[AdapterType.PREFECT],
        max_retries=1,
    )
    assert result2["success"] is False
    assert "adapter failed" in result2["error"]

    # branch: generic exception from retry_async call
    async def _raise_generic(*args, **kwargs):  # noqa: ANN002,ANN003
        raise RuntimeError("retry blew up")

    monkeypatch.setattr(tr, "retry_async", _raise_generic)
    result3 = await router.execute_with_fallback(
        {"task_type": "workflow"},
        preference_order=[AdapterType.PREFECT],
        max_retries=1,
    )
    assert result3["success"] is False
    assert "retry blew up" in result3["error"]


@pytest.mark.asyncio
async def test_adapter_coercion_and_unknown_analysis_and_health_branches() -> None:
    class _ToggleEquality:
        def __init__(self, target: str) -> None:
            self.target = target
            self.calls = 0

        def __eq__(self, other: object) -> bool:
            self.calls += 1
            return self.calls > 1 and other == self.target

        __hash__ = None

    class _UnknownTask:
        value = "custom"

    manager = tr.AdapterManager()
    router = tr.TaskRouter(adapter_registry=manager, state_manager=tr.StateManager())

    assert manager._coerce_adapter_type(None) is None
    assert manager._coerce_adapter_type("prefect") == AdapterType.PREFECT
    assert router._coerce_adapter_type("prefect") == AdapterType.PREFECT

    manager_fallback = _ToggleEquality("prefect")
    router_fallback = _ToggleEquality("prefect")
    assert manager._coerce_adapter_type(manager_fallback) == AdapterType.PREFECT
    assert router._coerce_adapter_type(router_fallback) == AdapterType.PREFECT

    monkey_task = _UnknownTask()
    router._normalize_task_type = lambda _task: monkey_task  # type: ignore[method-assign]
    analysis = await router.analyze_task({"task_type": "ignored"})
    assert analysis["task_type"] == "custom"
    assert analysis["recommended_adapter"] == AdapterType.PREFECT

    missing = await router._get_adapter_health(AdapterType.PREFECT)
    assert missing["status"] == "not_configured"

    manager.adapters[AdapterType.PREFECT] = SimpleNamespace()
    no_check = await router._get_adapter_health(AdapterType.PREFECT)
    assert no_check["status"] == "available_but_no_health_check"


def test_capability_routing_import_success_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("mahavishnu.core.task_requirements")

    class _ResolutionCache:
        def __init__(self, ttl_seconds: int = 300) -> None:
            self.ttl_seconds = ttl_seconds

        def get(self, key: str):  # noqa: ANN001
            return None

        def set(self, key: str, value: object) -> None:  # noqa: ANN001
            return None

        def invalidate(self) -> None:
            return None

        def get_stats(self) -> dict[str, object]:
            return {"enabled": True}

    class _RoutingDecision:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            self.__dict__.update(kwargs)

    fake.TaskRequirements = object
    fake.RoutingDecision = _RoutingDecision
    fake.ResolutionCache = _ResolutionCache
    fake.TASK_CAPABILITY_REQUIREMENTS = {}

    monkeypatch.setitem(sys.modules, "mahavishnu.core.task_requirements", fake)
    reloaded = importlib.reload(tr)
    assert reloaded.CAPABILITY_ROUTING_AVAILABLE is True


@pytest.mark.asyncio
async def test_execute_with_fallback_success_retry_exhausted_and_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ExecAdapter(_AvailableAdapter):
        async def execute(self, task: dict[str, object], repos: list[str]) -> dict[str, object]:
            return {"execution_id": "exec-1", "latency_ms": 12, "success": True}

    manager = tr.AdapterManager()
    await manager.register_adapter(AdapterType.PREFECT, _ExecAdapter(AdapterType.PREFECT))
    router = tr.TaskRouter(adapter_registry=manager, state_manager=tr.StateManager())

    async def _retry_success(fn, policy, operation, dependency):  # noqa: ANN001,ANN003
        return await fn(), 2

    monkeypatch.setattr(tr, "retry_async", _retry_success)
    success = await router.execute_with_fallback({"task_type": "workflow"})
    assert success["success"] is True
    assert success["result"] == "exec-1"
    assert success["fallback_chain"] == [AdapterType.PREFECT]
    assert success["total_attempts"] == 2

    async def _retry_exhausted(fn, policy, operation, dependency):  # noqa: ANN001,ANN003
        raise tr.RetryExhaustedError(RuntimeError("retry failed"), 3)

    monkeypatch.setattr(tr, "retry_async", _retry_exhausted)
    failed = await router.execute_with_fallback(
        {"task_type": "workflow"},
        preference_order=[AdapterType.PREFECT],
        max_retries=2,
    )
    assert failed["success"] is False
    assert "retry failed" in failed["error"]

    stats = await router.get_adapter_statistics()
    assert stats["prefect"]["successes"] == 1
    assert stats["prefect"]["failures"] == 1
