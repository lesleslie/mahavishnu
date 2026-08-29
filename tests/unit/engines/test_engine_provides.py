"""Tests verifying each engine declares its `provides: list[Capability]`.

Task 2.7 of the worker-registry-capability-refactor plan: the conductor
(Phase 3a) needs to resolve which engine satisfies which capability, so
each adapter must expose a `provides` property listing its `Capability` set.
"""
from __future__ import annotations

from typing import Any

import pytest

from mahavishnu.core.adapters.worker import WorkerOrchestratorAdapter
from mahavishnu.core.capabilities import Capability
from mahavishnu.engines.agno_adapter_impl import AgnoAdapter
from mahavishnu.engines.hatchet_adapter_impl import HatchetAdapterImpl
from mahavishnu.engines.llamaindex_adapter_impl import LlamaIndexAdapter
from mahavishnu.engines.prefect_adapter_impl import PrefectAdapter


# -----------------------------------------------------------------------------
# Stub WorkerManager so WorkerOrchestratorAdapter can be constructed in tests
# without spinning up a real terminal manager.
# -----------------------------------------------------------------------------


class _StubWorkerManager:
    async def execute_batch(self, worker_ids: list[str], tasks: list[dict[str, Any]]) -> dict[str, Any]:
        return {wid: type("R", (), {"is_success": lambda self: True, "status": type("S", (), {"value": "completed"})(), "output": "", "duration_seconds": 0.0, "has_output": lambda self: False})() for wid in worker_ids}

    async def spawn_workers(self, worker_type: str, count: int) -> list[str]:
        return [f"w{i}" for i in range(count)]

    async def health_check(self) -> dict[str, Any]:
        return {"workers_active": 0, "max_concurrent": 10}


@pytest.mark.parametrize("adapter_cls,expected_cap", [
    (PrefectAdapter, "engine:durable-flow"),
    (LlamaIndexAdapter, "engine:rag-retrieve"),
    (AgnoAdapter, "engine:multi-agent-team"),
    (HatchetAdapterImpl, "engine:durable-flow-alternative"),
    (WorkerOrchestratorAdapter, "engine:terminal-execution"),
])
def test_engine_declares_capability(adapter_cls: type, expected_cap: str) -> None:
    if adapter_cls is WorkerOrchestratorAdapter:
        adapter = adapter_cls(worker_manager=_StubWorkerManager())
    else:
        adapter = adapter_cls()
    cap_ids = {c.id for c in adapter.provides}
    assert expected_cap in cap_ids
    for cap in adapter.provides:
        assert isinstance(cap, Capability)
