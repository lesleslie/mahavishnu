"""Compatibility contract helpers for the Bodai ecosystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import inspect
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

from .adapter_discovery import AdapterMetadata
from .adapters.base import OrchestratorAdapter

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class ContractCheck:
    """Single compatibility check result."""

    name: str
    component: str
    passed: bool
    required: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the contract check."""
        return {
            "name": self.name,
            "component": self.component,
            "passed": self.passed,
            "required": self.required,
            "details": self.details,
        }


CONTRACT_MATRIX: tuple[dict[str, Any], ...] = (
    {
        "name": "mcp_core_tool_inventory",
        "component": "mcp/server_core",
        "required_tools": (
            "list_repos",
            "trigger_workflow",
            "get_workflow_status",
            "list_workflows",
            "get_health",
            "get_monitoring_dashboard",
            "get_tool_versions",
        ),
    },
    {
        "name": "mcp_health_tool_registration",
        "component": "mcp/tools/health_tools",
        "required_tools": ("mcp_list_tools", "mcp_test_connection", "mcp_get_metrics"),
    },
    {
        "name": "tool_version_registry",
        "component": "mcp/tool_versions",
        "required_versions": (
            "get_tool_versions",
            "mcp_list_tools",
            "mcp_test_connection",
            "mcp_get_metrics",
        ),
    },
    {
        "name": "adapter_lifecycle_contract",
        "component": "core/adapters/base",
        "required_methods": ("initialize", "execute", "get_health"),
    },
    {
        "name": "adapter_metadata_contract",
        "component": "core/adapter_discovery",
        "required_keys": (
            "adapter_id",
            "domain",
            "category",
            "provider",
            "capabilities",
            "factory_path",
            "source",
        ),
    },
)


def build_contract_app() -> Any:
    """Build a lightweight app fixture for MCP contract evaluation."""
    from .config import MahavishnuSettings

    settings = MahavishnuSettings(
        server_name="Contract Test Server",
        observability_enabled=False,
        terminal_enabled=False,
        pools={"enabled": False},
        workers={"enabled": False},
        otel_storage={"enabled": False},
    )

    app = Mock()
    app.config = settings
    app.get_repos = Mock(return_value=["/repo1", "/repo2"])
    app.execute_workflow_parallel = AsyncMock(
        return_value={
            "workflow_id": "wf_contract_1",
            "status": "completed",
            "repos_processed": 2,
            "successful_repos": 2,
            "failed_repos": 0,
        }
    )
    app.workflow_state_manager = Mock()
    app.workflow_state_manager.create = AsyncMock()
    app.workflow_state_manager.get = AsyncMock(return_value={"status": "completed"})
    app.workflow_state_manager.update = AsyncMock()
    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
    app.rbac_manager = Mock()
    app.rbac_manager.check_permission = AsyncMock(return_value=True)
    app.rbac_manager.create_user = AsyncMock()
    app.rbac_manager.roles = {"admin": Mock()}
    app.observability = Mock()
    app.observability.get_performance_metrics = Mock(return_value={})
    app.observability.get_logs = Mock(return_value=[])
    app.observability.flush_metrics = AsyncMock()
    app.opensearch_integration = Mock()
    app.opensearch_integration.search_logs = AsyncMock(return_value=[])
    app.opensearch_integration.search_workflows = AsyncMock(return_value=[])
    app.opensearch_integration.get_workflow_stats = AsyncMock(return_value={})
    app.opensearch_integration.get_log_stats = AsyncMock(return_value={})
    app.opensearch_integration.health_check = AsyncMock(return_value={"status": "healthy"})
    app.error_recovery_manager = Mock()
    app.error_recovery_manager.get_recovery_metrics = AsyncMock(return_value={})
    app.error_recovery_manager.monitor_and_heal_workflows = AsyncMock()
    app.monitoring_service = Mock()
    app.monitoring_service.get_dashboard_data = AsyncMock(return_value={})
    app.monitoring_service.alert_manager = Mock()
    app.monitoring_service.alert_manager.get_active_alerts = AsyncMock(return_value=[])
    app.monitoring_service.alert_manager.trigger_alert = AsyncMock(return_value=Mock(id="a1"))
    app.monitoring_service.acknowledge_alert = AsyncMock(return_value=True)
    app.adapters = {
        "prefect": Mock(),
        "agno": Mock(),
        "llamaindex": Mock(),
    }
    for adapter in app.adapters.values():
        adapter.get_health = AsyncMock(return_value={"status": "healthy"})

    return app


async def collect_mcp_tool_inventory() -> list[str]:
    """Collect the tool inventory from a FastMCP server instance."""
    from ..mcp.server_core import FastMCPServer

    server = FastMCPServer(app=build_contract_app())
    tools = await server.server.list_tools()
    return sorted(tool.name for tool in tools)


async def collect_health_tool_inventory() -> list[str]:
    """Collect the tool inventory from the health-tool registration helper."""
    from fastmcp import FastMCP

    from ..mcp.tools.health_tools import register_health_tools

    mcp = FastMCP(name="contract-health-tools")
    register_health_tools(mcp, build_contract_app())
    tools = await mcp.list_tools()
    return sorted(tool.name for tool in tools)


def collect_tool_versions() -> dict[str, str]:
    """Collect the version registry."""
    from ..mcp.tool_versions import get_all_tool_versions

    return get_all_tool_versions()


def _check_adapter_lifecycle_contract() -> ContractCheck:
    required_methods = {"initialize", "execute", "get_health"}
    missing = sorted(required_methods - set(OrchestratorAdapter.__abstractmethods__))
    return ContractCheck(
        name="adapter_lifecycle_contract",
        component="core/adapters/base",
        passed=not missing,
        details={"missing": missing},
    )


def _check_adapter_metadata_contract() -> ContractCheck:
    metadata = AdapterMetadata(
        adapter_id="mahavishnu.contract",
        domain="orchestration",
        category="workflow",
        provider="contract",
        capabilities=["execute"],
        factory_path="mahavishnu.contract:Adapter",
        source="test",
    )
    payload = metadata.to_dict()
    required_keys = next(
        check["required_keys"]
        for check in CONTRACT_MATRIX
        if check["name"] == "adapter_metadata_contract"
    )
    missing = sorted(key for key in required_keys if key not in payload)
    return ContractCheck(
        name="adapter_metadata_contract",
        component="core/adapter_discovery",
        passed=not missing,
        details={"missing": missing, "payload_keys": sorted(payload)},
    )


async def _check_mcp_tool_inventory() -> ContractCheck:
    inventory = await collect_mcp_tool_inventory()
    required_tools = next(
        check["required_tools"]
        for check in CONTRACT_MATRIX
        if check["name"] == "mcp_core_tool_inventory"
    )
    missing = sorted(tool for tool in required_tools if tool not in inventory)
    return ContractCheck(
        name="mcp_core_tool_inventory",
        component="mcp/server_core",
        passed=not missing,
        details={"missing": missing, "inventory": inventory},
    )


async def _check_health_tool_registration() -> ContractCheck:
    inventory = await collect_health_tool_inventory()
    required_tools = next(
        check["required_tools"]
        for check in CONTRACT_MATRIX
        if check["name"] == "mcp_health_tool_registration"
    )
    missing = sorted(tool for tool in required_tools if tool not in inventory)
    return ContractCheck(
        name="mcp_health_tool_registration",
        component="mcp/tools/health_tools",
        passed=not missing,
        details={"missing": missing, "inventory": inventory},
    )


def _check_tool_versions() -> ContractCheck:
    versions = collect_tool_versions()
    required_versions = next(
        check["required_versions"]
        for check in CONTRACT_MATRIX
        if check["name"] == "tool_version_registry"
    )
    missing = sorted(name for name in required_versions if name not in versions)
    return ContractCheck(
        name="tool_version_registry",
        component="mcp/tool_versions",
        passed=not missing,
        details={
            "missing": missing,
            "versions": {name: versions.get(name) for name in required_versions},
        },
    )


async def build_contract_report() -> dict[str, Any]:
    """Build the release-blocking compatibility report."""
    checks = [
        _check_adapter_lifecycle_contract(),
        _check_adapter_metadata_contract(),
        _check_tool_versions(),
    ]
    checks.append(await _check_mcp_tool_inventory())
    checks.append(await _check_health_tool_registration())

    passed = sum(1 for check in checks if check.passed)
    total = len(checks)
    failed = total - passed
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "matrix": list(CONTRACT_MATRIX),
        "checks": [check.to_dict() for check in checks],
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round((passed / total) * 100, 2) if total else 100.0,
        },
    }
    return report


def render_contract_report(report: dict[str, Any]) -> str:
    """Render the compatibility report as Markdown."""
    lines = [
        "# Ecosystem Compatibility Report",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Total checks: {report['summary']['total']}",
        f"- Passed: {report['summary']['passed']}",
        f"- Failed: {report['summary']['failed']}",
        f"- Pass rate: {report['summary']['pass_rate']}%",
        "",
        "## Checks",
    ]
    for check in report["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        lines.append(f"- {status} **{check['name']}** ({check['component']})")
        if check.get("details"):
            lines.append(f"  - Details: `{json.dumps(check['details'], sort_keys=True)}`")
    return "\n".join(lines) + "\n"


def write_contract_report(report: dict[str, Any], output_path: Path) -> None:
    """Write JSON and Markdown report artifacts."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    markdown_path = output_path.with_suffix(".md")
    markdown_path.write_text(render_contract_report(report))


def is_concrete_adapter_contract(cls: type[Any]) -> bool:
    """Check whether a class is a non-abstract orchestrator adapter."""
    return issubclass(cls, OrchestratorAdapter) and not inspect.isabstract(cls)


__all__ = [
    "CONTRACT_MATRIX",
    "ContractCheck",
    "build_contract_report",
    "collect_mcp_tool_inventory",
    "collect_tool_versions",
    "is_concrete_adapter_contract",
    "render_contract_report",
    "write_contract_report",
]
