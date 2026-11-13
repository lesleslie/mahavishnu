"""Release-blocking compatibility tests for the Bodai ecosystem."""

from __future__ import annotations

import inspect

import pytest

from oneiric.adapters.metadata import AdapterMetadata as DiscoveryAdapterMetadata
from mahavishnu.core.adapters.base import AdapterMetadata
from mahavishnu.core.adapters.worker import WorkerOrchestratorAdapter
from mahavishnu.core.compatibility import (
    CONTRACT_MATRIX,
    build_contract_report,
    collect_mcp_tool_inventory,
    collect_tool_versions,
    is_concrete_adapter_contract,
)
from mahavishnu.engines.agno_adapter_impl import AgnoAdapter
from mahavishnu.engines.llamaindex_adapter_impl import LlamaIndexAdapter
from mahavishnu.engines.prefect_adapter_impl import PrefectAdapter


def test_contract_matrix_covers_expected_surfaces() -> None:
    """The compatibility matrix should define the release-blocking surfaces."""
    names = {entry["name"] for entry in CONTRACT_MATRIX}

    assert names == {
        "mcp_core_tool_inventory",
        "mcp_health_tool_registration",
        "tool_version_registry",
        "adapter_lifecycle_contract",
        "adapter_metadata_contract",
    }


@pytest.mark.asyncio
async def test_mcp_tool_inventory_includes_required_tools() -> None:
    """The MCP server should expose the required contract tools."""
    inventory = await collect_mcp_tool_inventory()

    required = {
        "mahavishnu_list_repos",
        "mahavishnu_trigger_workflow",
        "mahavishnu_get_workflow_status",
        "get_health",
        "mahavishnu_get_monitoring_dashboard",
        "mahavishnu_get_tool_versions",
    }

    assert required.issubset(set(inventory))


@pytest.mark.asyncio
async def test_health_tool_registration_includes_required_tools() -> None:
    """The health tool registration helper should expose the utility tools."""
    from mahavishnu.core.compatibility import collect_health_tool_inventory

    inventory = await collect_health_tool_inventory()

    required = {
        "mahavishnu_mcp_list_tools",
        "mahavishnu_mcp_test_connection",
        "mahavishnu_mcp_get_metrics",
    }

    assert required.issubset(set(inventory))


def test_tool_version_registry_includes_contract_tools() -> None:
    """Tool versions should be published for the contract tools."""
    versions = collect_tool_versions()

    for name in (
        "mahavishnu_get_tool_versions",
        "mahavishnu_mcp_list_tools",
        "mahavishnu_mcp_test_connection",
        "mahavishnu_mcp_get_metrics",
    ):
        assert versions[name]


def test_adapter_contracts_are_concrete_and_complete() -> None:
    """Concrete adapters should fully satisfy the lifecycle contract."""
    adapters = [
        PrefectAdapter,
        AgnoAdapter,
        LlamaIndexAdapter,
        WorkerOrchestratorAdapter,
    ]

    for adapter_cls in adapters:
        assert is_concrete_adapter_contract(adapter_cls)
        assert not adapter_cls.__abstractmethods__
        assert inspect.iscoroutinefunction(adapter_cls.initialize)
        assert inspect.iscoroutinefunction(adapter_cls.cleanup)
        assert inspect.iscoroutinefunction(adapter_cls.shutdown)
        assert inspect.iscoroutinefunction(adapter_cls.get_health)


@pytest.mark.asyncio
async def test_contract_report_is_deterministic_and_complete() -> None:
    """The report generator should produce a stable compatibility artifact."""
    report = await build_contract_report()

    assert report["summary"]["total"] == 5
    assert report["summary"]["failed"] == 0
    assert report["summary"]["pass_rate"] == 100.0
    assert {check["name"] for check in report["checks"]} == {
        "mcp_core_tool_inventory",
        "mcp_health_tool_registration",
        "tool_version_registry",
        "adapter_lifecycle_contract",
        "adapter_metadata_contract",
    }
