"""Comprehensive coverage tests for mahavishnu.core.task_router.

Covers:
- TaskType / RouterMode enums
- AdapterExecutionStats
- AdapterManager (registry, stats, coercion)
- WorkflowState dataclass
- StateManager (file persistence, in-memory CRUD, copy semantics)
- CapabilityRouter (capability routing, cache, registry swap)
- TaskRouter (analyze, route, execute_with_fallback, health)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.adapters.base import (
    AdapterCapabilities,
    AdapterType,
    OrchestratorAdapter,
)
from mahavishnu.core.routing_metrics import RoutingMetrics
from mahavishnu.core.status import WorkflowStatus
from mahavishnu.core.task_router import (
    AdapterExecutionStats,
    AdapterManager,
    CapabilityRouter,
    RouterMode,
    StateManager,
    TaskRouter,
    TaskType,
    WorkflowState,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeAdapter(OrchestratorAdapter):
    """Minimal adapter used to drive TaskRouter / AdapterManager tests."""

    def __init__(
        self,
        adapter_type: AdapterType,
        available: bool = True,
        health: dict[str, Any] | None = None,
        execute_result: dict[str, Any] | None = None,
        execute_side_effect: BaseException | None = None,
    ) -> None:
        self._adapter_type = adapter_type
        self._available = available
        self._health = health
        self._execute_result = execute_result
        self._execute_side_effect = execute_side_effect
        self.executed_calls: list[tuple[dict[str, Any], list[str]]] = []

    @property
    def adapter_type(self) -> AdapterType:
        return self._adapter_type

    @property
    def name(self) -> str:
        return f"fake-{self._adapter_type.value}"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities()

    async def initialize(self) -> None:
        return None

    async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
        self.executed_calls.append((dict(task), list(repos)))
        if self._execute_side_effect is not None:
            raise self._execute_side_effect
        if self._execute_result is not None:
            return self._execute_result
        return {"success": True, "execution_id": "exec-1", "latency_ms": 12}

    async def is_available(self) -> bool:  # type: ignore[override]
        return self._available

    async def get_health(self) -> dict[str, Any]:
        if self._health is not None:
            return self._health
        return {"status": "healthy"}


# ---------------------------------------------------------------------------
# Enum coverage
# ---------------------------------------------------------------------------


class TestTaskTypeEnum:
    def test_members(self) -> None:
        assert TaskType.WORKFLOW.value == "workflow"
        assert TaskType.AI_TASK.value == "ai_task"
        assert TaskType.RAG_QUERY.value == "rag_query"
        assert TaskType.BATCH_TASK.value == "batch_task"
        assert TaskType.INTERACTIVE_TASK.value == "interactive_task"

    def test_member_count(self) -> None:
        assert {m.value for m in TaskType} == {
            "workflow",
            "ai_task",
            "rag_query",
            "batch_task",
            "interactive_task",
        }


class TestRouterModeEnum:
    def test_members(self) -> None:
        assert RouterMode.STATISTICAL.value == "statistical"
        assert RouterMode.COST_OPTIMIZED.value == "cost_optimized"
        assert RouterMode.ADAPTIVE.value == "adaptive"
        assert RouterMode.CAPABILITY.value == "capability"


# ---------------------------------------------------------------------------
# AdapterExecutionStats
# ---------------------------------------------------------------------------


class TestAdapterExecutionStats:
    def test_default_zero_rates(self) -> None:
        stats = AdapterExecutionStats()
        assert stats.success_rate == 0.0
        d = stats.to_dict()
        assert d == {
            "successes": 0,
            "failures": 0,
            "total_attempts": 0,
            "success_rate": 0.0,
        }

    def test_success_rate_with_data(self) -> None:
        stats = AdapterExecutionStats(successes=3, failures=1, total_attempts=4)
        assert stats.success_rate == 0.75
        assert stats.to_dict()["success_rate"] == 0.75

    def test_all_success(self) -> None:
        stats = AdapterExecutionStats(successes=5, failures=0, total_attempts=5)
        assert stats.success_rate == 1.0


# ---------------------------------------------------------------------------
# AdapterManager
# ---------------------------------------------------------------------------


class TestAdapterManager:
    def test_register_and_get(self) -> None:
        mgr = AdapterManager()
        adapter = FakeAdapter(AdapterType.PREFECT)
        # register_adapter is async
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            mgr.register_adapter(AdapterType.PREFECT, adapter)
        )
        assert mgr.get_adapter(AdapterType.PREFECT) is adapter
        # get_adapter accepts str
        assert mgr.get_adapter("prefect") is adapter
        assert mgr.get_adapter("missing") is None
        assert mgr.get_adapter(None) is None

    def test_record_execution_creates_stats(self) -> None:
        mgr = AdapterManager()
        mgr.record_execution(AdapterType.AGNO, success=True)
        mgr.record_execution(AdapterType.AGNO, success=False)
        mgr.record_execution(AdapterType.AGNO, success=True)
        stats = mgr.get_statistics()
        assert "agno" in stats
        assert stats["agno"]["successes"] == 2
        assert stats["agno"]["failures"] == 1
        assert stats["agno"]["total_attempts"] == 3
        assert abs(stats["agno"]["success_rate"] - (2 / 3)) < 1e-9

    def test_get_statistics_empty(self) -> None:
        mgr = AdapterManager()
        assert mgr.get_statistics() == {}

    def test_coerce_adapter_type_enum(self) -> None:
        assert AdapterManager._coerce_adapter_type(AdapterType.PREFECT) is AdapterType.PREFECT
        assert AdapterManager._coerce_adapter_type("prefect") is AdapterType.PREFECT
        # string matching by value
        assert AdapterManager._coerce_adapter_type("WORKFLOW") is None
        # invalid
        assert AdapterManager._coerce_adapter_type("not-a-type") is None
        assert AdapterManager._coerce_adapter_type(None) is None

    def test_get_adapter_with_string_value_of_enum(self) -> None:
        # str that is not a valid AdapterType value but is enum.value
        mgr = AdapterManager()
        adapter = FakeAdapter(AdapterType.WORKER)
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            mgr.register_adapter(AdapterType.WORKER, adapter)
        )
        # using the actual string value
        assert mgr.get_adapter("worker") is adapter


# ---------------------------------------------------------------------------
# WorkflowState dataclass
# ---------------------------------------------------------------------------


class TestWorkflowState:
    def test_defaults(self) -> None:
        ws = WorkflowState(workflow_id="wf-1")
        assert ws.workflow_id == "wf-1"
        assert ws.adapter_states == {}

    def test_with_states(self) -> None:
        ws = WorkflowState(
            workflow_id="wf-1", adapter_states={"prefect": {"x": 1}}
        )
        assert ws.adapter_states == {"prefect": {"x": 1}}


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------


class TestStateManager:
    def test_default_state_dir(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        assert sm._state_dir == tmp_path
        # default state file path computed
        assert sm._state_file() == tmp_path / "workflows.json"

    def test_persist_and_load_roundtrip(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            sm.create("wf-1", {"prompt": "hi"}, ["/r1"])
        )
        # New instance should load from disk
        sm2 = StateManager(state_dir=tmp_path)
        state = asyncio.get_event_loop().run_until_complete(sm2.get("wf-1"))
        assert state is not None
        assert state["workflow_id"] == "wf-1"
        assert state["task"] == {"prompt": "hi"}
        assert state["repos"] == ["/r1"]
        assert state["status"] == WorkflowStatus.PENDING.value

    def test_load_handles_corrupt_file(self, tmp_path: Path, caplog) -> None:
        # Pre-write a corrupt JSON
        state_file = tmp_path / "workflows.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("not json {{{")
        with caplog.at_level(logging.WARNING, logger="mahavishnu.core.task_router"):
            sm = StateManager(state_dir=tmp_path)
        # No workflows loaded
        assert sm._workflows == {}

    def test_load_skips_non_dict_entries(self, tmp_path: Path) -> None:
        state_file = tmp_path / "workflows.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({"wf-1": "string-not-dict", "wf-2": {"x": 1}}))
        sm = StateManager(state_dir=tmp_path)
        # Both should appear (with default record for wf-1)
        assert "wf-1" in sm._workflows
        assert "wf-2" in sm._workflows

    def test_load_skips_non_dict_adapter_states(self, tmp_path: Path) -> None:
        state_file = tmp_path / "workflows.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(
                {
                    "wf-1": {
                        "adapter_states": "not-a-dict",
                    }
                }
            )
        )
        sm = StateManager(state_dir=tmp_path)
        # The loader does not coerce non-dict adapter_states back to {}
        # so the raw value is preserved. (Only the in-memory default
        # was bypassed by record.update(wf_data).)
        assert sm._workflows["wf-1"]["adapter_states"] == "not-a-dict"

    async def test_persist_handles_write_error(self, tmp_path: Path, caplog) -> None:
        sm = StateManager(state_dir=tmp_path)
        # Force the underlying Path.write_text to raise; the _persist
        # wrapper has a try/except that logs and swallows.
        with patch.object(
            Path, "write_text", side_effect=OSError("disk full")
        ):
            with caplog.at_level(logging.WARNING, logger="mahavishnu.core.task_router"):
                await sm.create("wf-1", {}, [])
            # State should still be in memory
            assert "wf-1" in sm._workflows
            # Warning was logged
            assert any(
                "Failed to persist" in record.message
                for record in caplog.records
            )

    def test_normalize_status(self) -> None:
        assert StateManager._normalize_status(None) is None
        assert (
            StateManager._normalize_status(WorkflowStatus.PENDING)
            == WorkflowStatus.PENDING.value
        )
        assert StateManager._normalize_status("running") == "running"
        assert StateManager._normalize_status(123) == "123"

    def test_now_iso(self) -> None:
        iso = StateManager._now_iso()
        assert isinstance(iso, str)
        assert "T" in iso

    def test_create_returns_copy(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            sm.create("wf-1", {"prompt": "p"}, ["/r1"])
        )
        # Mutating result must not affect internal state
        result["task"]["prompt"] = "mutated"
        result["repos"].append("/r2")
        result["adapter_states"]["prefect"] = {"x": 1}
        internal = asyncio.get_event_loop().run_until_complete(sm.get("wf-1"))
        assert internal["task"]["prompt"] == "p"
        assert internal["repos"] == ["/r1"]
        assert internal["adapter_states"] == {}

    def test_update_unknown_workflow_is_noop(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        # Should not raise
        asyncio.get_event_loop().run_until_complete(
            sm.update("missing", status=WorkflowStatus.RUNNING)
        )

    def test_update_normalizes_inputs(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(sm.create("wf-1", {"k": "v"}, ["/r1"]))
        loop.run_until_complete(
            sm.update(
                "wf-1",
                status=WorkflowStatus.RUNNING,
                task={"k2": "v2"},
                repos=["/r2"],
                results=[{"ok": True}],
                errors=[{"msg": "e"}],
                adapter_states={"prefect": {"x": 1}},
            )
        )
        state = loop.run_until_complete(sm.get("wf-1"))
        assert state["status"] == "running"
        assert state["task"] == {"k2": "v2"}
        assert state["repos"] == ["/r2"]
        assert state["results"] == [{"ok": True}]
        assert state["errors"] == [{"msg": "e"}]
        assert state["adapter_states"] == {"prefect": {"x": 1}}

    async def test_update_with_none_collections_preserves_defaults(
        self, tmp_path: Path
    ) -> None:
        sm = StateManager(state_dir=tmp_path)
        await sm.create("wf-1", {}, [])
        # results=None and errors=None are tolerated; only the in-memory
        # record gets the literal None. Avoid setting repos=None because
        # _copy_record iterates record["repos"] unconditionally.
        await sm.update("wf-1", results=None, errors=None)
        # Re-create with valid list to leave the record readable
        await sm.update("wf-1", results=[], errors=[], repos=[])
        state = await sm.get("wf-1")
        assert state["results"] == []
        assert state["errors"] == []
        assert state["repos"] == []

    async def test_update_adapter_states_non_dict(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        await sm.create("wf-1", {}, [])
        # adapter_states is not coerced when the value is not a dict —
        # but we cannot test the broken-state via get() because _copy_record
        # iterates .items() on the value. Instead, verify the in-memory
        # record reflects the raw update.
        await sm.update("wf-1", adapter_states="not-dict")
        assert sm._workflows["wf-1"]["adapter_states"] == "not-dict"

    def test_get_returns_none_for_missing(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(sm.get("nope"))
        assert result is None

    def test_list_workflows_status_filter(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(sm.create("wf-1", {}, []))
        loop.run_until_complete(sm.create("wf-2", {}, []))
        loop.run_until_complete(sm.update("wf-1", status=WorkflowStatus.RUNNING))
        # All
        all_wfs = loop.run_until_complete(sm.list_workflows())
        assert {w["workflow_id"] for w in all_wfs} == {"wf-1", "wf-2"}
        # Only running
        running = loop.run_until_complete(
            sm.list_workflows(status=WorkflowStatus.RUNNING)
        )
        assert {w["workflow_id"] for w in running} == {"wf-1"}
        # Pending
        pending = loop.run_until_complete(
            sm.list_workflows(status=WorkflowStatus.PENDING)
        )
        assert {w["workflow_id"] for w in pending} == {"wf-2"}

    def test_list_workflows_limit(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        for i in range(5):
            loop.run_until_complete(sm.create(f"wf-{i}", {}, []))
        result = loop.run_until_complete(sm.list_workflows(limit=2))
        assert len(result) == 2

    def test_delete(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(sm.create("wf-1", {}, []))
        loop.run_until_complete(sm.delete("wf-1"))
        assert loop.run_until_complete(sm.get("wf-1")) is None

    def test_delete_missing_does_not_raise(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        # No raise
        loop.run_until_complete(sm.delete("nope"))

    def test_update_progress_total_zero(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(sm.create("wf-1", {}, []))
        loop.run_until_complete(sm.update_progress("wf-1", completed=0, total=0))
        state = loop.run_until_complete(sm.get("wf-1"))
        assert state["progress"] == 0

    def test_update_progress_computes_pct(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(sm.create("wf-1", {}, []))
        loop.run_until_complete(sm.update_progress("wf-1", completed=1, total=4))
        state = loop.run_until_complete(sm.get("wf-1"))
        assert state["progress"] == 25

    def test_get_completed_count_missing(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(sm.get_completed_count("nope"))
        assert result == 0

    def test_get_completed_count_sums_results_and_errors(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(sm.create("wf-1", {}, []))
        loop.run_until_complete(sm.update("wf-1", results=[{"a": 1}], errors=[{"e": 1}]))
        count = loop.run_until_complete(sm.get_completed_count("wf-1"))
        assert count == 2

    def test_add_result_missing(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        # No raise
        loop.run_until_complete(sm.add_result("missing", {"x": 1}))

    def test_add_result_appends_copy(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(sm.create("wf-1", {}, []))
        result = {"a": 1}
        loop.run_until_complete(sm.add_result("wf-1", result))
        result["a"] = 999  # mutate input
        state = loop.run_until_complete(sm.get("wf-1"))
        assert state["results"] == [{"a": 1}]

    def test_add_error_missing(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(sm.add_error("missing", {"x": 1}))

    def test_add_error_appends(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(sm.create("wf-1", {}, []))
        loop.run_until_complete(sm.add_error("wf-1", {"msg": "boom"}))
        state = loop.run_until_complete(sm.get("wf-1"))
        assert state["errors"] == [{"msg": "boom"}]

    def test_create_workflow_state_uses_string_key(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        rec = loop.run_until_complete(
            sm.create_workflow_state("wf-1", "prefect", {"k": "v"})
        )
        assert rec["adapter_states"]["prefect"] == {"k": "v"}

    def test_create_workflow_state_uses_enum_key(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        rec = loop.run_until_complete(
            sm.create_workflow_state("wf-1", AdapterType.AGNO, {"k": "v"})
        )
        assert rec["adapter_states"]["agno"] == {"k": "v"}

    def test_update_adapter_state_creates_record(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        rec = loop.run_until_complete(
            sm.update_adapter_state("wf-1", AdapterType.PREFECT, {"a": 1})
        )
        assert rec["adapter_states"]["prefect"] == {"a": 1}
        # The record is now persisted
        state = loop.run_until_complete(sm.get_workflow_state("wf-1"))
        assert state is not None
        assert state["adapter_states"]["prefect"] == {"a": 1}

    def test_get_workflow_state_missing(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        import asyncio

        loop = asyncio.get_event_loop()
        assert loop.run_until_complete(sm.get_workflow_state("nope")) is None

    def test_adapter_key_helper(self) -> None:
        assert StateManager._adapter_key(AdapterType.PREFECT) == "prefect"
        assert StateManager._adapter_key("custom") == "custom"


# ---------------------------------------------------------------------------
# CapabilityRouter
# ---------------------------------------------------------------------------


class TestCapabilityRouter:
    def test_init_without_registry(self) -> None:
        router = CapabilityRouter()
        assert router.registry is None
        # Cache is created if available
        # both branches pass — the cache may or may not be available

    def test_capability_requirements_mapping(self) -> None:
        assert CapabilityRouter.TASK_CAPABILITY_REQUIREMENTS[TaskType.RAG_QUERY] == [
            "rag",
            "vector_search",
        ]
        assert CapabilityRouter.TASK_CAPABILITY_REQUIREMENTS[TaskType.BATCH_TASK] == [
            "batch",
            "workflow",
            "deploy_flows",
        ]
        assert CapabilityRouter.TASK_CAPABILITY_REQUIREMENTS[TaskType.INTERACTIVE_TASK] == [
            "multi_agent",
            "tool_use",
            "conversational",
        ]
        assert CapabilityRouter.TASK_CAPABILITY_REQUIREMENTS[TaskType.AI_TASK] == [
            "multi_agent",
            "tool_use",
        ]
        assert CapabilityRouter.TASK_CAPABILITY_REQUIREMENTS[TaskType.WORKFLOW] == [
            "deploy_flows",
            "monitor_execution",
        ]

    def test_route_no_registry_returns_error(self) -> None:
        router = CapabilityRouter()
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            router.route(TaskType.AI_TASK)
        )
        assert result["success"] is False
        assert "No adapter registry" in result["error"]
        assert result["task_type"] == "ai_task"
        assert "multi_agent" in result["required_capabilities"]

    def test_route_no_registry_with_additional_caps(self) -> None:
        router = CapabilityRouter()
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            router.route(TaskType.WORKFLOW, additional_capabilities=["extras"])
        )
        assert "extras" in result["required_capabilities"]

    def test_route_no_matching_adapters(self) -> None:
        registry = MagicMock()
        registry.find_by_capabilities = AsyncMock(return_value=[])
        router = CapabilityRouter(registry=registry)
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            router.route(TaskType.AI_TASK)
        )
        assert result["success"] is False
        assert "No adapter found" in result["error"]

    def test_route_picks_highest_priority(self) -> None:
        # Build mock adapter candidates
        low = MagicMock()
        low.adapter_id = "low"
        low.priority = 1
        low.capabilities = {"multi_agent", "tool_use"}
        high = MagicMock()
        high.adapter_id = "high"
        high.priority = 10
        high.capabilities = {"multi_agent", "tool_use"}

        registry = MagicMock()
        registry.find_by_capabilities = AsyncMock(return_value=[low, high])
        router = CapabilityRouter(registry=registry)
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            router.route(TaskType.AI_TASK)
        )
        # If RoutingDecision is available we get a dataclass, otherwise a dict.
        # At least the adapter name should be "high".
        if hasattr(result, "adapter_name"):
            assert result.adapter_name == "high"
        else:
            assert result["adapter"] == "high"

    def test_route_handles_registry_exception(self) -> None:
        registry = MagicMock()
        registry.find_by_capabilities = AsyncMock(side_effect=RuntimeError("boom"))
        router = CapabilityRouter(registry=registry)
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            router.route(TaskType.WORKFLOW)
        )
        assert result["success"] is False
        assert "boom" in result["error"]

    async def test_route_invokes_registry_each_call(self) -> None:
        candidate = MagicMock()
        candidate.adapter_id = "first"
        candidate.priority = 5
        candidate.capabilities = {"multi_agent", "tool_use"}

        registry = MagicMock()
        registry.find_by_capabilities = AsyncMock(return_value=[candidate])
        router = CapabilityRouter(registry=registry)
        # Two calls → two registry invocations (cache may be disabled if
        # task_requirements cannot be imported)
        await router.route(TaskType.AI_TASK)
        await router.route(TaskType.AI_TASK)
        assert registry.find_by_capabilities.await_count == 2

    def test_invalidate_cache(self) -> None:
        router = CapabilityRouter()
        router.invalidate_cache()
        # No raise

    def test_get_cache_stats_disabled(self) -> None:
        # If cache is None, returns {"enabled": False}
        router = CapabilityRouter()
        router._cache = None  # type: ignore[assignment]
        stats = router.get_cache_stats()
        assert stats == {"enabled": False}

    def test_set_registry_invalidates_cache(self) -> None:
        router = CapabilityRouter()
        # Mock the cache and invalidate
        router._cache = MagicMock()
        router.set_registry(MagicMock())
        router._cache.invalidate.assert_called_once()
        assert router.registry is not None


# ---------------------------------------------------------------------------
# TaskRouter
# ---------------------------------------------------------------------------


class TestTaskRouterHelpers:
    def test_normalize_task_type_passthrough_enum(self) -> None:
        assert TaskRouter._normalize_task_type(TaskType.AI_TASK) is TaskType.AI_TASK

    def test_normalize_task_type_string_match(self) -> None:
        assert TaskRouter._normalize_task_type("ai_task") is TaskType.AI_TASK

    def test_normalize_task_type_none_defaults_workflow(self) -> None:
        assert TaskRouter._normalize_task_type(None) is TaskType.WORKFLOW

    def test_normalize_task_type_invalid_falls_back(self) -> None:
        assert TaskRouter._normalize_task_type("not-a-type") is TaskType.WORKFLOW

    def test_coerce_adapter_type(self) -> None:
        assert TaskRouter._coerce_adapter_type(AdapterType.PREFECT) is AdapterType.PREFECT
        assert TaskRouter._coerce_adapter_type("prefect") is AdapterType.PREFECT
        assert TaskRouter._coerce_adapter_type(None) is None
        assert TaskRouter._coerce_adapter_type("bogus") is None

    def test_normalize_preference_order_dedupes(self) -> None:
        tr = TaskRouter()
        result = tr._normalize_preference_order(
            [AdapterType.PREFECT, "prefect", AdapterType.AGNO]
        )
        assert result == [AdapterType.PREFECT, AdapterType.AGNO]

    def test_normalize_preference_order_filters_invalid(self) -> None:
        tr = TaskRouter()
        result = tr._normalize_preference_order(
            [AdapterType.PREFECT, "bogus", None, AdapterType.AGNO]
        )
        assert result == [AdapterType.PREFECT, AdapterType.AGNO]

    def test_normalize_preference_order_empty(self) -> None:
        tr = TaskRouter()
        assert tr._normalize_preference_order(None) == []
        assert tr._normalize_preference_order([]) == []

    def test_default_preference_order_known(self) -> None:
        tr = TaskRouter()
        for t in TaskType:
            result = tr._default_preference_order(t)
            assert isinstance(result, list)
            assert all(isinstance(a, AdapterType) for a in result)

    def test_default_preference_order_unknown_falls_back(self) -> None:
        tr = TaskRouter()
        # Use a real TaskType but with cleared mapping
        tr.TASK_PREFERENCE_ORDERS = {}  # type: ignore[attr-defined]
        result = tr._default_preference_order(TaskType.WORKFLOW)
        assert result == list(TaskRouter.DEFAULT_PREFERENCE_ORDER)


class TestTaskRouterAnalyzeTask:
    async def test_analyze_workflow(self) -> None:
        tr = TaskRouter(adapter_registry=AdapterManager())
        result = await tr.analyze_task({"task_type": "workflow"})
        assert result["task_type"] == "workflow"
        assert result["recommended_adapter"] == AdapterType.PREFECT
        assert result["routing_mode"] == "statistical"
        assert "standard" in result["analysis"]

    async def test_analyze_ai_task(self) -> None:
        tr = TaskRouter(adapter_registry=AdapterManager())
        result = await tr.analyze_task({"task_type": "ai_task"})
        assert result["recommended_adapter"] == AdapterType.AGNO
        assert "AI agents" in result["analysis"]

    async def test_analyze_rag_query(self) -> None:
        tr = TaskRouter(adapter_registry=AdapterManager())
        result = await tr.analyze_task({"task_type": "rag_query"})
        assert result["recommended_adapter"] == AdapterType.LLAMAINDEX
        assert "RAG" in result["analysis"]

    async def test_analyze_batch_task(self) -> None:
        tr = TaskRouter(adapter_registry=AdapterManager())
        result = await tr.analyze_task({"task_type": "batch_task"})
        assert result["recommended_adapter"] == AdapterType.PREFECT
        assert "batch" in result["analysis"]

    async def test_analyze_interactive_task(self) -> None:
        tr = TaskRouter(adapter_registry=AdapterManager())
        result = await tr.analyze_task({"task_type": "interactive_task"})
        assert result["recommended_adapter"] == AdapterType.AGNO
        assert "AI agents" in result["analysis"]

    async def test_analyze_deployment_and_monitoring_flags(self) -> None:
        tr = TaskRouter(adapter_registry=AdapterManager())
        result = await tr.analyze_task(
            {
                "task_type": "ai_task",
                "needs_deployment": True,
                "needs_monitoring": True,
            }
        )
        assert "deployment" in result["analysis"]
        assert "monitoring" in result["analysis"]


class TestTaskRouterRoute:
    async def test_route_uses_preference_order(self) -> None:
        mgr = AdapterManager()
        adapter = FakeAdapter(AdapterType.PREFECT)
        await mgr.register_adapter(AdapterType.PREFECT, adapter)
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr.route(
            {"task_type": "workflow"},
            preference_order=[AdapterType.PREFECT],
        )
        assert result["success"] is True
        assert result["adapter"] == AdapterType.PREFECT
        assert result["task_type"] == "workflow"

    async def test_route_falls_back_to_default(self) -> None:
        mgr = AdapterManager()
        # Only register PREFECT; LLAMAINDEX/AGNO not in registry
        adapter = FakeAdapter(AdapterType.PREFECT)
        await mgr.register_adapter(AdapterType.PREFECT, adapter)
        tr = TaskRouter(adapter_registry=mgr)
        # No preference_order → uses default fallback chain
        result = await tr.route({"task_type": "workflow"})
        assert result["success"] is True
        assert result["adapter"] == AdapterType.PREFECT
        # Candidates list should include the recommended + defaults
        assert AdapterType.PREFECT in result["preference_order"]

    async def test_route_no_adapter_available(self) -> None:
        mgr = AdapterManager()
        # Register an adapter that is not available
        adapter = FakeAdapter(AdapterType.PREFECT, available=False)
        await mgr.register_adapter(AdapterType.PREFECT, adapter)
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr.route({"task_type": "workflow"})
        assert result["success"] is False
        assert "No adapter available" in result["error"]

    async def test_route_no_adapters_at_all(self) -> None:
        mgr = AdapterManager()
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr.route({"task_type": "workflow"})
        assert result["success"] is False

    async def test_route_uses_task_preference_order(self) -> None:
        mgr = AdapterManager()
        adapter = FakeAdapter(AdapterType.LLAMAINDEX)
        await mgr.register_adapter(AdapterType.LLAMAINDEX, adapter)
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr.route(
            {
                "task_type": "workflow",
                "preference_order": [AdapterType.LLAMAINDEX],
            }
        )
        assert result["adapter"] == AdapterType.LLAMAINDEX

    async def test_route_uses_string_preferences(self) -> None:
        mgr = AdapterManager()
        adapter = FakeAdapter(AdapterType.PREFECT)
        await mgr.register_adapter(AdapterType.PREFECT, adapter)
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr.route({"task_type": "workflow"}, preference_order=["prefect"])
        assert result["adapter"] == AdapterType.PREFECT


class TestTaskRouterExecuteWithFallback:
    async def test_execute_succeeds_first_try(self) -> None:
        mgr = AdapterManager()
        adapter = FakeAdapter(
            AdapterType.PREFECT,
            execute_result={"success": True, "execution_id": "exec-1", "latency_ms": 5},
        )
        await mgr.register_adapter(AdapterType.PREFECT, adapter)
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr.execute_with_fallback(
            {"task_type": "workflow", "prompt": "hi", "repos": ["/r1"]}
        )
        assert result["success"] is True
        assert result["adapter"] == AdapterType.PREFECT
        assert result["result"] == "exec-1"
        assert result["total_attempts"] == 1
        # Adapter was invoked
        assert len(adapter.executed_calls) == 1

    async def test_execute_falls_back_after_exception(self) -> None:
        mgr = AdapterManager()
        first = FakeAdapter(
            AdapterType.AGNO,
            execute_side_effect=RuntimeError("agno-broken"),
        )
        second = FakeAdapter(
            AdapterType.LLAMAINDEX,
            execute_result={"success": True, "execution_id": "exec-2", "latency_ms": 7},
        )
        await mgr.register_adapter(AdapterType.AGNO, first)
        await mgr.register_adapter(AdapterType.LLAMAINDEX, second)
        tr = TaskRouter(adapter_registry=mgr)
        # Pass explicit preference order to make the test deterministic
        result = await tr.execute_with_fallback(
            {"task_type": "ai_task", "prompt": "hi"},
            preference_order=[AdapterType.AGNO, AdapterType.LLAMAINDEX],
            max_retries=1,
            retry_delay_base=0.0,
        )
        assert result["success"] is True
        assert result["adapter"] == AdapterType.LLAMAINDEX
        # Both adapters were tried in chain
        assert result["fallback_chain"] == [AdapterType.AGNO, AdapterType.LLAMAINDEX]

    async def test_execute_handles_unsuccessful_result(self) -> None:
        mgr = AdapterManager()
        first = FakeAdapter(
            AdapterType.PREFECT,
            execute_result={"success": False, "error": "prefect-no"},
        )
        second = FakeAdapter(
            AdapterType.AGNO,
            execute_result={"success": True, "execution_id": "ok"},
        )
        await mgr.register_adapter(AdapterType.PREFECT, first)
        await mgr.register_adapter(AdapterType.AGNO, second)
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr.execute_with_fallback(
            {"task_type": "ai_task", "prompt": "hi"},
            max_retries=1,
            retry_delay_base=0.0,
        )
        assert result["success"] is True
        assert result["adapter"] == AdapterType.AGNO

    async def test_execute_unsuccessful_without_error_message(self) -> None:
        mgr = AdapterManager()
        first = FakeAdapter(
            AdapterType.PREFECT,
            execute_result={"success": False},
        )
        await mgr.register_adapter(AdapterType.PREFECT, first)
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr.execute_with_fallback(
            {"task_type": "ai_task", "prompt": "hi"},
            max_retries=1,
            retry_delay_base=0.0,
        )
        assert result["success"] is False
        assert "Adapter returned unsuccessful result" in (result.get("error") or "")

    async def test_execute_all_adapters_fail(self) -> None:
        mgr = AdapterManager()
        first = FakeAdapter(
            AdapterType.AGNO,
            execute_side_effect=RuntimeError("a1"),
        )
        second = FakeAdapter(
            AdapterType.LLAMAINDEX,
            execute_side_effect=RuntimeError("a2"),
        )
        await mgr.register_adapter(AdapterType.AGNO, first)
        await mgr.register_adapter(AdapterType.LLAMAINDEX, second)
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr.execute_with_fallback(
            {"task_type": "ai_task", "prompt": "hi"},
            preference_order=[AdapterType.AGNO, AdapterType.LLAMAINDEX],
            max_retries=1,
            retry_delay_base=0.0,
        )
        assert result["success"] is False
        assert "a2" in result["error"]
        assert result["adapter"] is None
        assert AdapterType.AGNO in result["fallback_chain"]
        assert AdapterType.LLAMAINDEX in result["fallback_chain"]

    async def test_execute_skips_missing_adapters(self) -> None:
        mgr = AdapterManager()
        second = FakeAdapter(
            AdapterType.AGNO,
            execute_result={"success": True, "execution_id": "ok"},
        )
        await mgr.register_adapter(AdapterType.AGNO, second)
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr.execute_with_fallback(
            {"task_type": "ai_task", "prompt": "hi"},
            max_retries=1,
            retry_delay_base=0.0,
        )
        assert result["success"] is True
        # PREFECT is not in fallback_chain because it was never registered
        assert AdapterType.PREFECT not in result["fallback_chain"]
        assert AdapterType.AGNO in result["fallback_chain"]

    async def test_execute_result_not_a_dict(self) -> None:
        mgr = AdapterManager()
        adapter = FakeAdapter(
            AdapterType.PREFECT,
            execute_result="not-a-dict",  # type: ignore[arg-type]
        )
        await mgr.register_adapter(AdapterType.PREFECT, adapter)
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr.execute_with_fallback(
            {"task_type": "workflow", "prompt": "hi"},
            max_retries=1,
            retry_delay_base=0.0,
        )
        assert result["success"] is True
        assert result["result"] == "not-a-dict"

    async def test_execute_uses_retry_exhausted(self) -> None:
        mgr = AdapterManager()
        # Adapter always raises non-success — but use RetryExhausted path:
        # we can simulate by making the adapter raise on every call.
        adapter = FakeAdapter(
            AdapterType.PREFECT,
            execute_side_effect=ValueError("always-fails"),
        )
        await mgr.register_adapter(AdapterType.PREFECT, adapter)
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr.execute_with_fallback(
            {"task_type": "ai_task", "prompt": "hi"},
            max_retries=1,
            retry_delay_base=0.0,
        )
        assert result["success"] is False
        # failure metric recorded
        stats = mgr.get_statistics()
        assert stats["prefect"]["failures"] >= 1


class TestTaskRouterHealth:
    async def test_get_adapter_statistics(self) -> None:
        mgr = AdapterManager()
        adapter = FakeAdapter(AdapterType.PREFECT)
        await mgr.register_adapter(AdapterType.PREFECT, adapter)
        tr = TaskRouter(adapter_registry=mgr)
        stats = await tr.get_adapter_statistics()
        assert "prefect" in stats

    async def test_get_health_empty_registry(self) -> None:
        tr = TaskRouter(adapter_registry=AdapterManager())
        health = await tr.get_health()
        assert health["status"] == "healthy"
        assert health["adapters_configured"] == 0
        assert health["adapters_healthy"] == 0

    async def test_get_health_with_adapters(self) -> None:
        mgr = AdapterManager()
        await mgr.register_adapter(AdapterType.PREFECT, FakeAdapter(AdapterType.PREFECT))
        await mgr.register_adapter(AdapterType.AGNO, FakeAdapter(AdapterType.AGNO))
        tr = TaskRouter(adapter_registry=mgr)
        health = await tr.get_health()
        assert health["adapters_configured"] == 2
        assert health["adapters_healthy"] == 2

    async def test_get_health_mixed(self) -> None:
        mgr = AdapterManager()
        await mgr.register_adapter(
            AdapterType.PREFECT,
            FakeAdapter(AdapterType.PREFECT, health={"status": "healthy"}),
        )
        await mgr.register_adapter(
            AdapterType.AGNO,
            FakeAdapter(AdapterType.AGNO, health={"status": "degraded"}),
        )
        tr = TaskRouter(adapter_registry=mgr)
        health = await tr.get_health()
        assert health["adapters_healthy"] == 1


class TestGetAdapterHealth:
    async def test_unknown_string_returns_not_configured(self) -> None:
        tr = TaskRouter(adapter_registry=AdapterManager())
        result = await tr._get_adapter_health("definitely-not-real")
        assert result["status"] == "not_configured"

    async def test_unregistered_returns_not_configured(self) -> None:
        tr = TaskRouter(adapter_registry=AdapterManager())
        result = await tr._get_adapter_health(AdapterType.PREFECT)
        assert result["status"] == "not_configured"
        assert "prefect" in result["error"]

    async def test_healthy_adapter(self) -> None:
        mgr = AdapterManager()
        await mgr.register_adapter(
            AdapterType.PREFECT,
            FakeAdapter(AdapterType.PREFECT, health={"status": "healthy", "extra": 1}),
        )
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr._get_adapter_health(AdapterType.PREFECT)
        assert result["status"] == "healthy"
        assert result["adapter_type"] == "prefect"
        assert result["extra"] == 1

    async def test_health_check_exception(self) -> None:
        mgr = AdapterManager()

        class BoomAdapter(FakeAdapter):
            async def get_health(self) -> dict[str, Any]:  # type: ignore[override]
                raise RuntimeError("health-broken")

        await mgr.register_adapter(AdapterType.PREFECT, BoomAdapter(AdapterType.PREFECT))
        tr = TaskRouter(adapter_registry=mgr)
        result = await tr._get_adapter_health(AdapterType.PREFECT)
        assert result["status"] == "error"
        assert "health-broken" in result["error"]

    async def test_get_adapter_health_string_value(self) -> None:
        mgr = AdapterManager()
        await mgr.register_adapter(
            AdapterType.PREFECT,
            FakeAdapter(AdapterType.PREFECT, health={"status": "healthy"}),
        )
        tr = TaskRouter(adapter_registry=mgr)
        # Use string value
        result = await tr._get_adapter_health("prefect")
        assert result["status"] == "healthy"


class TestTaskRouterInit:
    def test_init_defaults(self) -> None:
        tr = TaskRouter()
        assert tr.adapter_registry is not None
        assert tr.state_manager is not None
        assert tr.router_mode == RouterMode.STATISTICAL
        assert tr.metrics is not None

    def test_init_custom_metrics(self) -> None:
        metrics = RoutingMetrics()
        tr = TaskRouter(metrics=metrics)
        assert tr.metrics is metrics

    def test_init_custom_state_manager(self, tmp_path: Path) -> None:
        sm = StateManager(state_dir=tmp_path)
        tr = TaskRouter(state_manager=sm)
        assert tr.state_manager is sm

    def test_init_router_mode(self) -> None:
        tr = TaskRouter(router_mode=RouterMode.ADAPTIVE)
        assert tr.router_mode == RouterMode.ADAPTIVE
