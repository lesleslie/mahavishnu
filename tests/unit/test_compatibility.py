"""Tests for core/compatibility.py — contract check helpers and report generation."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from mahavishnu.core.compatibility import (
    CONTRACT_MATRIX,
    ContractCheck,
    build_contract_app,
    build_contract_report,
    _check_adapter_lifecycle_contract,
    _check_adapter_metadata_contract,
    _check_tool_versions,
    is_concrete_adapter_contract,
    render_contract_report,
    write_contract_report,
)


# ---------------------------------------------------------------------------
# ContractCheck
# ---------------------------------------------------------------------------


class TestContractCheck:
    def test_basic_creation(self):
        cc = ContractCheck(name="test", component="c1", passed=True)
        assert cc.name == "test"
        assert cc.component == "c1"
        assert cc.passed is True
        assert cc.required is True
        assert cc.details == {}

    def test_all_fields(self):
        cc = ContractCheck(
            name="test",
            component="c1",
            passed=False,
            required=False,
            details={"missing": ["a"]},
        )
        assert cc.required is False
        assert cc.details == {"missing": ["a"]}

    def test_frozen(self):
        cc = ContractCheck(name="test", component="c1", passed=True)
        with pytest.raises(AttributeError):
            cc.name = "changed"

    def test_to_dict(self):
        cc = ContractCheck(
            name="my_check",
            component="comp",
            passed=True,
            details={"key": "val"},
        )
        d = cc.to_dict()
        assert d["name"] == "my_check"
        assert d["component"] == "comp"
        assert d["passed"] is True
        assert d["required"] is True
        assert d["details"] == {"key": "val"}

    def test_to_dict_roundtrip(self):
        cc = ContractCheck(name="x", component="y", passed=False, required=False)
        d = cc.to_dict()
        assert d == {
            "name": "x",
            "component": "y",
            "passed": False,
            "required": False,
            "details": {},
        }


# ---------------------------------------------------------------------------
# CONTRACT_MATRIX
# ---------------------------------------------------------------------------


class TestContractMatrix:
    def test_has_expected_entries(self):
        names = {entry["name"] for entry in CONTRACT_MATRIX}
        assert "mcp_core_tool_inventory" in names
        assert "mcp_health_tool_registration" in names
        assert "tool_version_registry" in names
        assert "adapter_lifecycle_contract" in names
        assert "adapter_metadata_contract" in names

    def test_each_entry_has_name_and_component(self):
        for entry in CONTRACT_MATRIX:
            assert "name" in entry
            assert "component" in entry

    def test_tuple_immutable(self):
        assert isinstance(CONTRACT_MATRIX, tuple)


# ---------------------------------------------------------------------------
# build_contract_app
# ---------------------------------------------------------------------------


class TestBuildContractApp:
    def test_returns_mock_app(self):
        app = build_contract_app()
        assert app is not None
        assert hasattr(app, "config")

    def test_has_repos(self):
        app = build_contract_app()
        repos = app.get_repos()
        assert isinstance(repos, list)
        assert len(repos) == 2

    def test_has_adapters(self):
        app = build_contract_app()
        assert "prefect" in app.adapters
        assert "agno" in app.adapters
        assert "llamaindex" in app.adapters

    def test_adapter_health(self):
        app = build_contract_app()
        for adapter in app.adapters.values():
            health = adapter.get_health.return_value
            assert health == {"status": "healthy"}

    def test_has_workflow_state_manager(self):
        app = build_contract_app()
        assert hasattr(app, "workflow_state_manager")

    def test_has_rbac_manager(self):
        app = build_contract_app()
        assert hasattr(app, "rbac_manager")
        assert "admin" in app.rbac_manager.roles

    def test_has_observability(self):
        app = build_contract_app()
        assert hasattr(app, "observability")


# ---------------------------------------------------------------------------
# _check_adapter_lifecycle_contract
# ---------------------------------------------------------------------------


class TestAdapterLifecycleContract:
    def test_passes(self):
        result = _check_adapter_lifecycle_contract()
        assert isinstance(result, ContractCheck)
        assert result.name == "adapter_lifecycle_contract"
        assert result.component == "core/adapters/base"


# ---------------------------------------------------------------------------
# _check_adapter_metadata_contract
# ---------------------------------------------------------------------------


class TestAdapterMetadataContract:
    def test_passes(self):
        result = _check_adapter_metadata_contract()
        assert isinstance(result, ContractCheck)
        assert result.name == "adapter_metadata_contract"
        assert result.component == "core/adapter_discovery"


# ---------------------------------------------------------------------------
# _check_tool_versions
# ---------------------------------------------------------------------------


class TestToolVersionsContract:
    def test_returns_contract_check(self):
        result = _check_tool_versions()
        assert isinstance(result, ContractCheck)
        assert result.name == "tool_version_registry"


# ---------------------------------------------------------------------------
# is_concrete_adapter_contract
# ---------------------------------------------------------------------------


class TestIsConcreteAdapterContract:
    def test_abstract_adapter_returns_false(self):
        from mahavishnu.core.adapters.base import OrchestratorAdapter

        assert is_concrete_adapter_contract(OrchestratorAdapter) is False

    def test_non_adapter_returns_false(self):
        class NotAnAdapter:
            pass

        assert is_concrete_adapter_contract(NotAnAdapter) is False

    def test_concrete_subclass(self):
        from mahavishnu.core.adapters.base import (
            AdapterCapabilities,
            AdapterType,
            OrchestratorAdapter,
        )

        class ConcreteAdapter(OrchestratorAdapter):
            async def initialize(self):
                pass

            async def execute(self, task, repos=None, user_id=None):
                pass

            async def get_health(self):
                pass

            @property
            def name(self):
                return "concrete"

            @property
            def capabilities(self):
                return AdapterCapabilities()

            @property
            def adapter_type(self):
                return AdapterType.PREFECT

        assert is_concrete_adapter_contract(ConcreteAdapter) is True


# ---------------------------------------------------------------------------
# render_contract_report
# ---------------------------------------------------------------------------


class TestRenderContractReport:
    def test_renders_all_passing(self):
        report = {
            "generated_at": "2026-01-01T00:00:00Z",
            "summary": {
                "total": 2,
                "passed": 2,
                "failed": 0,
                "pass_rate": 100.0,
            },
            "checks": [
                {"name": "check_a", "component": "c1", "passed": True, "required": True, "details": {}},
                {"name": "check_b", "component": "c2", "passed": True, "required": True, "details": {"x": 1}},
            ],
        }
        md = render_contract_report(report)
        assert "# Ecosystem Compatibility Report" in md
        assert "PASS **check_a**" in md
        assert "PASS **check_b**" in md
        assert "Pass rate: 100.0%" in md

    def test_renders_failing_check(self):
        report = {
            "generated_at": "2026-01-01T00:00:00Z",
            "summary": {"total": 1, "passed": 0, "failed": 1, "pass_rate": 0.0},
            "checks": [
                {
                    "name": "failing",
                    "component": "c",
                    "passed": False,
                    "required": True,
                    "details": {"missing": ["tool1"]},
                },
            ],
        }
        md = render_contract_report(report)
        assert "FAIL **failing**" in md
        assert "missing" in md

    def test_renders_no_details(self):
        report = {
            "generated_at": "2026-01-01T00:00:00Z",
            "summary": {"total": 1, "passed": 1, "failed": 0, "pass_rate": 100.0},
            "checks": [
                {"name": "ok", "component": "c", "passed": True, "required": True, "details": {}},
            ],
        }
        md = render_contract_report(report)
        # No details line when details is empty
        assert "Details:" not in md.split("ok")[1].split("\n")[0]


# ---------------------------------------------------------------------------
# write_contract_report
# ---------------------------------------------------------------------------


class TestWriteContractReport:
    def test_writes_json_and_md(self, tmp_path):
        report = {
            "generated_at": "2026-01-01",
            "summary": {"total": 1, "passed": 1, "failed": 0, "pass_rate": 100.0},
            "checks": [
                {"name": "ok", "component": "c", "passed": True, "required": True, "details": {}},
            ],
        }
        output = tmp_path / "reports" / "contract.json"
        write_contract_report(report, output)

        assert output.exists()
        assert output.with_suffix(".md").exists()

        # Verify JSON is valid
        data = json.loads(output.read_text())
        assert data["summary"]["passed"] == 1

        # Verify Markdown has content
        md = output.with_suffix(".md").read_text()
        assert "Ecosystem Compatibility Report" in md

    def test_creates_parent_dirs(self, tmp_path):
        report = {
            "generated_at": "2026-01-01",
            "summary": {"total": 0, "passed": 0, "failed": 0, "pass_rate": 100.0},
            "checks": [],
        }
        output = tmp_path / "deep" / "nested" / "dir" / "report.json"
        write_contract_report(report, output)
        assert output.exists()


# ---------------------------------------------------------------------------
# __all__ exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_all_exports(self):
        from mahavishnu.core import compatibility

        for name in compatibility.__all__:
            assert hasattr(compatibility, name)


# ---------------------------------------------------------------------------
# build_contract_report (async, covers lines 266-290)
# ---------------------------------------------------------------------------


class TestBuildContractReport:
    @pytest.mark.asyncio
    async def test_report_structure(self):
        report = await build_contract_report()
        assert "generated_at" in report
        assert "matrix" in report
        assert "checks" in report
        assert "summary" in report
        assert report["summary"]["total"] == 5
        assert "pass_rate" in report["summary"]

    @pytest.mark.asyncio
    async def test_checks_contain_all_contract_names(self):
        report = await build_contract_report()
        check_names = [c["name"] for c in report["checks"]]
        for entry in CONTRACT_MATRIX:
            assert entry["name"] in check_names


# ---------------------------------------------------------------------------
# render_contract_report with details
# ---------------------------------------------------------------------------


class TestRenderContractReportWithDetails:
    def test_render_with_details(self):
        report = {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "summary": {"total": 1, "passed": 0, "failed": 1, "pass_rate": 0.0},
            "checks": [
                {
                    "name": "test_check",
                    "component": "comp",
                    "passed": False,
                    "required": True,
                    "details": {"missing": ["tool_a"]},
                }
            ],
        }
        md = render_contract_report(report)
        assert "FAIL" in md
        assert "test_check" in md
        assert "Details:" in md

    def test_render_pass_and_fail_mixed(self):
        report = {
            "generated_at": "2026-01-01",
            "summary": {"total": 2, "passed": 1, "failed": 1, "pass_rate": 50.0},
            "checks": [
                {"name": "passing", "component": "c1", "passed": True},
                {"name": "failing", "component": "c2", "passed": False},
            ],
        }
        md = render_contract_report(report)
        assert "PASS" in md
        assert "FAIL" in md

    def test_render_includes_pass_rate(self):
        report = {
            "generated_at": "2026-01-01",
            "summary": {"total": 2, "passed": 2, "failed": 0, "pass_rate": 100.0},
            "checks": [],
        }
        md = render_contract_report(report)
        assert "100.0%" in md
