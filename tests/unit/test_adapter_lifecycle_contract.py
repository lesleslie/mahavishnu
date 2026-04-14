"""Lifecycle contract tests for orchestrator adapters."""

from __future__ import annotations

import inspect

from mahavishnu.core.adapter_discovery import AdapterMetadata as DiscoveryAdapterMetadata
from mahavishnu.core.adapters.base import AdapterMetadata, OrchestratorAdapter
from mahavishnu.core.adapters.worker import WorkerOrchestratorAdapter
from mahavishnu.engines.agno_adapter_impl import AgnoAdapter
from mahavishnu.engines.llamaindex_adapter_impl import LlamaIndexAdapter
from mahavishnu.engines.prefect_adapter_impl import PrefectAdapter


def test_adapter_metadata_is_re_exported() -> None:
    """The base adapter module should re-export discovery metadata."""
    assert AdapterMetadata is DiscoveryAdapterMetadata


def test_orchestrator_adapter_requires_lifecycle_and_execution_contract() -> None:
    """The abstract base should require the lifecycle and execution contract."""
    assert {
        "initialize",
        "execute",
        "get_health",
    }.issubset(OrchestratorAdapter.__abstractmethods__)


def test_concrete_adapters_conform_to_lifecycle_contract() -> None:
    """Concrete adapters should fully implement the lifecycle contract."""
    adapters = [PrefectAdapter, AgnoAdapter, LlamaIndexAdapter, WorkerOrchestratorAdapter]

    for adapter_cls in adapters:
        assert not adapter_cls.__abstractmethods__
        assert inspect.iscoroutinefunction(adapter_cls.initialize)
        assert inspect.iscoroutinefunction(adapter_cls.cleanup)
        assert inspect.iscoroutinefunction(adapter_cls.shutdown)
        assert inspect.iscoroutinefunction(adapter_cls.get_health)
