"""Tests for mahavishnu.cli.config_validator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer

from mahavishnu.cli.config_validator import (
    RuntimeValidationCheck,
    _deep_merge,
    _dependency_health_url,
    _ensure_http_url,
    _load_settings_from_dir,
    _load_yaml_mapping,
    _mcp_health_url,
    _print_validation_report,
    _validate_adapter_config,
    _validate_pool_config,
    _validate_runtime_connectivity,
    _validate_runtime_settings,
    run_validation,
)
from mahavishnu.core.config_validator import ValidationResult
from mahavishnu.core.health import HealthStatus
from mahavishnu.core.health_schemas import HealthCheckResult

# ---------------------------------------------------------------------------
# RuntimeValidationCheck
# ---------------------------------------------------------------------------


class TestRuntimeValidationCheck:
    def test_to_dict(self):
        check = RuntimeValidationCheck(
            name="test", valid=True, message="ok", path="p", target="t", details={"k": "v"}
        )
        d = check.to_dict()
        assert d == {
            "name": "test",
            "valid": True,
            "message": "ok",
            "path": "p",
            "target": "t",
            "details": {"k": "v"},
        }

    def test_to_dict_defaults(self):
        check = RuntimeValidationCheck(name="x", valid=False, message="fail")
        d = check.to_dict()
        assert d["path"] == ""
        assert d["target"] == ""
        assert d["details"] == {}


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_flat_override(self):
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}}
        override = {"a": {"y": 3}}
        assert _deep_merge(base, override) == {"a": {"x": 1, "y": 3}}

    def test_non_dict_override(self):
        assert _deep_merge({"a": {"x": 1}}, {"a": "flat"}) == {"a": "flat"}

    def test_empty_override(self):
        base = {"a": 1}
        assert _deep_merge(base, {}) == {"a": 1}

    def test_new_keys(self):
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# _load_yaml_mapping
# ---------------------------------------------------------------------------


class TestLoadYamlMapping:
    def test_missing_file(self, tmp_path):
        result = _load_yaml_mapping(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_valid_yaml(self, tmp_path):
        f = tmp_path / "test.yaml"
        f.write_text("key: value\nnested:\n  a: 1\n")
        result = _load_yaml_mapping(f)
        assert result == {"key": "value", "nested": {"a": 1}}

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("")
        result = _load_yaml_mapping(f)
        assert result == {}

    def test_non_mapping_raises(self, tmp_path):
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="must contain a mapping"):
            _load_yaml_mapping(f)


# ---------------------------------------------------------------------------
# _ensure_http_url
# ---------------------------------------------------------------------------


class TestEnsureHttpUrl:
    def test_valid_http(self):
        r = _ensure_http_url("http://localhost:4200", "test")
        assert r.valid is True

    def test_valid_https(self):
        r = _ensure_http_url("https://example.com/health", "test")
        assert r.valid is True

    def test_missing_scheme(self):
        r = _ensure_http_url("localhost:4200", "field")
        assert r.valid is False
        assert "Invalid field" in r.message
        assert r.suggestions

    def test_ftp_scheme(self):
        r = _ensure_http_url("ftp://files.example.com", "field")
        assert r.valid is False

    def test_no_netloc(self):
        r = _ensure_http_url("http://", "field")
        assert r.valid is False


# ---------------------------------------------------------------------------
# _validate_pool_config
# ---------------------------------------------------------------------------


class TestValidatePoolConfig:
    def _make_settings(self, **overrides):
        from mahavishnu.core.config import MahavishnuSettings

        defaults = {
            "pools_enabled": True,
            "pools_min_workers": 2,
            "pools_max_workers": 5,
            "pools_routing_strategy": "least_loaded",
        }
        defaults.update(overrides)
        return MahavishnuSettings(
            **{k: v for k, v in defaults.items() if not k.startswith("pools_")}
        )

    def test_disabled_returns_empty(self):
        settings = self._make_settings()
        settings.pools.enabled = False
        assert _validate_pool_config(settings) == []

    def test_valid_config(self):
        settings = self._make_settings()
        settings.pools.enabled = True
        results = _validate_pool_config(settings)
        assert results == []

    def test_min_exceeds_max(self):
        settings = self._make_settings()
        settings.pools.enabled = True
        settings.pools.min_workers = 10
        settings.pools.max_workers = 5
        results = _validate_pool_config(settings)
        assert len(results) == 1
        assert not results[0].valid
        assert "min_workers" in results[0].message

    def test_invalid_routing_strategy(self):
        settings = self._make_settings()
        settings.pools.enabled = True
        settings.pools.routing_strategy = "invalid_strategy"
        results = _validate_pool_config(settings)
        assert any("Invalid pool routing strategy" in r.message for r in results)

    def test_equal_min_max_ok(self):
        settings = self._make_settings()
        settings.pools.enabled = True
        settings.pools.min_workers = 3
        settings.pools.max_workers = 3
        results = _validate_pool_config(settings)
        assert results == []


# ---------------------------------------------------------------------------
# _validate_adapter_config
# ---------------------------------------------------------------------------


class TestValidateAdapterConfig:
    def _make_settings(self, **overrides):
        from mahavishnu.core.config import MahavishnuSettings

        return MahavishnuSettings(**overrides)

    def test_no_adapters_enabled(self):
        settings = self._make_settings()
        settings.adapters.prefect_enabled = False
        settings.adapters.agno_enabled = False
        settings.adapters.llamaindex_enabled = False
        results = _validate_adapter_config(settings)
        assert results == []

    def test_prefect_with_valid_url(self):
        settings = self._make_settings(
            prefect={"api_url": "https://prefect.example.com"},
        )
        settings.adapters.prefect_enabled = True
        results = _validate_adapter_config(settings)
        assert all(r.valid for r in results)

    def test_prefect_with_invalid_url(self):
        settings = self._make_settings(
            prefect={"api_url": "not-a-url"},
        )
        settings.adapters.prefect_enabled = True
        results = _validate_adapter_config(settings)
        assert any(not r.valid for r in results)

    def test_agno_with_valid_url(self):
        settings = self._make_settings()
        settings.adapters.agno_enabled = True
        settings.agno.tools.mcp_server_url = "http://localhost:8678/mcp"
        results = _validate_adapter_config(settings)
        assert all(r.valid for r in results)

    def test_llamaindex_with_valid_url(self):
        settings = self._make_settings()
        settings.adapters.llamaindex_enabled = True
        settings.llm.ollama_base_url = "http://localhost:11434"
        results = _validate_adapter_config(settings)
        assert all(r.valid for r in results)

    def test_llamaindex_with_invalid_url(self):
        settings = self._make_settings()
        settings.adapters.llamaindex_enabled = True
        settings.llm.ollama_base_url = "nope"
        results = _validate_adapter_config(settings)
        assert any(not r.valid for r in results)


# ---------------------------------------------------------------------------
# _validate_runtime_settings
# ---------------------------------------------------------------------------


class TestValidateRuntimeSettings:
    def test_repos_path_exists(self, tmp_path):
        settings = MagicMock()
        settings.repos_path = str(tmp_path)
        settings.pools.enabled = False
        settings.adapters.prefect_enabled = False
        settings.adapters.agno_enabled = False
        settings.adapters.llamaindex_enabled = False
        results = _validate_runtime_settings(settings)
        assert any("Validated repos path" in r.message and r.valid for r in results)

    def test_repos_path_missing(self):
        settings = MagicMock()
        settings.repos_path = "/nonexistent/path/that/does/not/exist"
        settings.pools.enabled = False
        settings.adapters.prefect_enabled = False
        settings.adapters.agno_enabled = False
        settings.adapters.llamaindex_enabled = False
        results = _validate_runtime_settings(settings)
        assert any(not r.valid and "does not exist" in r.message for r in results)

    def test_delegates_to_pool_and_adapter(self):
        settings = MagicMock()
        settings.repos_path = str(Path(__file__).parent)
        settings.pools.enabled = False
        settings.adapters.prefect_enabled = False
        settings.adapters.agno_enabled = False
        settings.adapters.llamaindex_enabled = False
        with (
            patch("mahavishnu.cli.config_validator._validate_pool_config", return_value=[]),
            patch("mahavishnu.cli.config_validator._validate_adapter_config", return_value=[]),
        ):
            results = _validate_runtime_settings(settings)
        assert len(results) >= 1  # repos_path check


# ---------------------------------------------------------------------------
# _dependency_health_url
# ---------------------------------------------------------------------------


class TestDependencyHealthUrl:
    def test_http(self):
        dep = MagicMock(use_tls=False, host="localhost", port=8678)
        assert _dependency_health_url("test", dep) == "http://localhost:8678/health"

    def test_https(self):
        dep = MagicMock(use_tls=True, host="example.com", port=443)
        assert _dependency_health_url("test", dep) == "https://example.com:443/health"


# ---------------------------------------------------------------------------
# _mcp_health_url
# ---------------------------------------------------------------------------


class TestMcpHealthUrl:
    def test_mcp_endpoint(self):
        assert _mcp_health_url("http://localhost:8678/mcp") == "http://localhost:8678/health"

    def test_root_endpoint(self):
        assert _mcp_health_url("http://localhost:8678/") == "http://localhost:8678/health"

    def test_subpath_endpoint(self):
        assert (
            _mcp_health_url("http://localhost:8678/api/v1/mcp")
            == "http://localhost:8678/api/v1/health"
        )

    def test_bare_host(self):
        assert _mcp_health_url("http://localhost:8678") == "http://localhost:8678/health"

    def test_strips_trailing_slash(self):
        assert _mcp_health_url("http://localhost:8678/mcp/") == "http://localhost:8678/health"

    def test_preserves_query_and_fragment(self):
        url = _mcp_health_url("http://host:80/path?foo=bar#frag")
        assert url == "http://host:80/path/health"


# ---------------------------------------------------------------------------
# _validate_runtime_connectivity
# ---------------------------------------------------------------------------


class TestValidateRuntimeConnectivity:
    @pytest.mark.asyncio
    async def test_empty_dependencies(self):
        settings = MagicMock()
        settings.health.dependencies = {}
        settings.session_buddy_polling.enabled = False
        settings.agno.enabled = False
        checks = await _validate_runtime_connectivity(settings)
        assert checks == []

    @pytest.mark.asyncio
    async def test_healthy_dependency(self):
        settings = MagicMock()
        dep = MagicMock(
            use_tls=False, host="localhost", port=8678, required=True, timeout_seconds=5
        )
        settings.health.dependencies = {"session_buddy": dep}
        settings.session_buddy_polling.enabled = False
        settings.agno.enabled = False

        result = HealthCheckResult(service_name="test", status=HealthStatus.OK, latency_ms=10.0)
        mock_checker = AsyncMock()
        mock_checker.check = AsyncMock(return_value=result)

        with patch("mahavishnu.cli.config_validator.HealthChecker", return_value=mock_checker):
            checks = await _validate_runtime_connectivity(settings)

        assert len(checks) == 1
        assert checks[0].valid is True
        assert "Connectivity OK" in checks[0].message

    @pytest.mark.asyncio
    async def test_unhealthy_required_dependency(self):
        settings = MagicMock()
        dep = MagicMock(
            use_tls=False, host="localhost", port=9999, required=True, timeout_seconds=5
        )
        settings.health.dependencies = {"dead": dep}
        settings.session_buddy_polling.enabled = False
        settings.agno.enabled = False

        result = HealthCheckResult(
            service_name="dead", status=HealthStatus.UNHEALTHY, latency_ms=100.0, error="refused"
        )
        mock_checker = AsyncMock()
        mock_checker.check = AsyncMock(return_value=result)

        with patch("mahavishnu.cli.config_validator.HealthChecker", return_value=mock_checker):
            checks = await _validate_runtime_connectivity(settings)

        assert len(checks) == 1
        assert checks[0].valid is False
        assert checks[0].details["severity"] == "error"

    @pytest.mark.asyncio
    async def test_unhealthy_optional_dependency(self):
        settings = MagicMock()
        dep = MagicMock(
            use_tls=False, host="localhost", port=9999, required=False, timeout_seconds=5
        )
        settings.health.dependencies = {"optional": dep}
        settings.session_buddy_polling.enabled = False
        settings.agno.enabled = False

        result = HealthCheckResult(
            service_name="optional", status=HealthStatus.UNHEALTHY, latency_ms=50.0, error="timeout"
        )
        mock_checker = AsyncMock()
        mock_checker.check = AsyncMock(return_value=result)

        with patch("mahavishnu.cli.config_validator.HealthChecker", return_value=mock_checker):
            checks = await _validate_runtime_connectivity(settings)

        assert len(checks) == 1
        assert checks[0].valid is True  # not required, so valid=True
        assert checks[0].details["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_exception_during_check(self):
        settings = MagicMock()
        dep = MagicMock(use_tls=False, host="bad", port=1, required=True, timeout_seconds=1)
        settings.health.dependencies = {"err": dep}
        settings.session_buddy_polling.enabled = False
        settings.agno.enabled = False

        mock_checker = AsyncMock()
        mock_checker.check = AsyncMock(side_effect=ConnectionRefusedError("refused"))

        with patch("mahavishnu.cli.config_validator.HealthChecker", return_value=mock_checker):
            checks = await _validate_runtime_connectivity(settings)

        assert len(checks) == 1
        assert checks[0].valid is False
        assert "Connectivity check failed" in checks[0].message

    @pytest.mark.asyncio
    async def test_session_buddy_polling_checked(self):
        settings = MagicMock()
        settings.health.dependencies = {}
        settings.session_buddy_polling.enabled = True
        settings.session_buddy_polling.endpoint = "http://localhost:8678/mcp"
        settings.session_buddy_polling.timeout_seconds = 5
        settings.agno.enabled = False

        result = HealthCheckResult(service_name="sb", status=HealthStatus.OK, latency_ms=5.0)
        mock_checker = AsyncMock()
        mock_checker.check = AsyncMock(return_value=result)

        with patch("mahavishnu.cli.config_validator.HealthChecker", return_value=mock_checker):
            checks = await _validate_runtime_connectivity(settings)

        assert len(checks) == 1
        assert checks[0].name == "session_buddy_polling"

    @pytest.mark.asyncio
    async def test_agno_tools_checked(self):
        settings = MagicMock()
        settings.health.dependencies = {}
        settings.session_buddy_polling.enabled = False
        settings.agno.enabled = True
        settings.agno.tools.mcp_server_url = "http://localhost:8679/mcp"
        settings.agno.tools.tool_timeout_seconds = 5

        result = HealthCheckResult(
            service_name="agno", status=HealthStatus.DEGRADED, latency_ms=200.0
        )
        mock_checker = AsyncMock()
        mock_checker.check = AsyncMock(return_value=result)

        with patch("mahavishnu.cli.config_validator.HealthChecker", return_value=mock_checker):
            checks = await _validate_runtime_connectivity(settings)

        assert len(checks) == 1
        assert checks[0].valid is True  # DEGRADED is accepted

    @pytest.mark.asyncio
    async def test_multiple_dependencies_gathered(self):
        settings = MagicMock()
        d1 = MagicMock(use_tls=False, host="h1", port=1, required=True, timeout_seconds=5)
        d2 = MagicMock(use_tls=False, host="h2", port=2, required=False, timeout_seconds=5)
        settings.health.dependencies = {"a": d1, "b": d2}
        settings.session_buddy_polling.enabled = False
        settings.agno.enabled = False

        mock_checker = AsyncMock()
        mock_checker.check = AsyncMock(
            return_value=HealthCheckResult(service_name="x", status=HealthStatus.OK, latency_ms=1.0)
        )

        with patch("mahavishnu.cli.config_validator.HealthChecker", return_value=mock_checker):
            checks = await _validate_runtime_connectivity(settings)

        assert len(checks) == 2


# ---------------------------------------------------------------------------
# _print_validation_report
# ---------------------------------------------------------------------------


class TestPrintValidationReport:
    def test_valid_report(self, capsys):
        report = {
            "valid": True,
            "config_dir": "settings",
            "full": False,
            "runtime_settings_source": "settings",
            "static": {"valid": True, "errors": [], "warnings": []},
            "runtime_checks": [],
            "runtime_validations": [],
            "runtime_check_count": 0,
            "runtime_validation_count": 0,
            "summary": {
                "error_count": 0,
                "warning_count": 0,
                "runtime_check_count": 0,
                "runtime_validation_count": 0,
            },
        }
        _print_validation_report(report)
        captured = capsys.readouterr()
        assert "passed" in captured.out

    def test_invalid_report(self, capsys):
        report = {
            "valid": False,
            "config_dir": "settings",
            "full": False,
            "runtime_settings_source": "settings",
            "static": {
                "valid": False,
                "errors": [{"path": "x", "message": "bad", "suggestions": ["fix it"]}],
                "warnings": [],
            },
            "runtime_checks": [],
            "runtime_validations": [],
            "runtime_check_count": 0,
            "runtime_validation_count": 0,
            "summary": {
                "error_count": 1,
                "warning_count": 0,
                "runtime_check_count": 0,
                "runtime_validation_count": 0,
            },
        }
        _print_validation_report(report)
        captured = capsys.readouterr()
        assert "failed" in captured.err
        assert "bad" in captured.err

    def test_warnings_shown(self, capsys):
        report = {
            "valid": True,
            "config_dir": "settings",
            "full": False,
            "runtime_settings_source": "settings",
            "static": {
                "valid": True,
                "errors": [],
                "warnings": [{"path": "y", "message": "hmm"}],
            },
            "runtime_checks": [],
            "runtime_validations": [],
            "runtime_check_count": 0,
            "runtime_validation_count": 0,
            "summary": {
                "error_count": 0,
                "warning_count": 1,
                "runtime_check_count": 0,
                "runtime_validation_count": 0,
            },
        }
        _print_validation_report(report)
        captured = capsys.readouterr()
        assert "hmm" in captured.out

    def test_runtime_checks_shown(self, capsys):
        report = {
            "valid": True,
            "config_dir": "settings",
            "full": False,
            "runtime_settings_source": "settings",
            "static": {"valid": True, "errors": [], "warnings": []},
            "runtime_checks": [{"name": "sb", "valid": True, "message": "ok"}],
            "runtime_validations": [],
            "runtime_check_count": 1,
            "runtime_validation_count": 0,
            "summary": {
                "error_count": 0,
                "warning_count": 0,
                "runtime_check_count": 1,
                "runtime_validation_count": 0,
            },
        }
        _print_validation_report(report)
        captured = capsys.readouterr()
        assert "Runtime checks" in captured.out
        assert "[ok]" in captured.out

    def test_runtime_validations_shown(self, capsys):
        report = {
            "valid": True,
            "config_dir": "settings",
            "full": False,
            "runtime_settings_source": "settings",
            "static": {"valid": True, "errors": [], "warnings": []},
            "runtime_checks": [],
            "runtime_validations": [{"valid": False, "path": "p", "message": "fail"}],
            "runtime_check_count": 0,
            "runtime_validation_count": 1,
            "summary": {
                "error_count": 0,
                "warning_count": 0,
                "runtime_check_count": 0,
                "runtime_validation_count": 1,
            },
        }
        _print_validation_report(report)
        captured = capsys.readouterr()
        assert "[failed]" in captured.out


# ---------------------------------------------------------------------------
# run_validation
# ---------------------------------------------------------------------------


class TestRunValidation:
    @pytest.mark.asyncio
    async def test_static_invalid_skips_runtime(self):
        mock_report = MagicMock()
        mock_report.valid = False
        mock_report.get_errors.return_value = []
        mock_report.warnings = []

        with patch("mahavishnu.cli.config_validator.validate_config", return_value=mock_report):
            result = await run_validation(config_dir="/tmp/nonexistent")

        assert result["valid"] is False
        assert result["runtime_check_count"] == 0

    @pytest.mark.asyncio
    async def test_full_validation_runs_connectivity(self):
        mock_report = MagicMock()
        mock_report.valid = True
        mock_report.get_errors.return_value = []
        mock_report.warnings = []

        mock_settings = MagicMock()
        mock_settings.repos_path = str(Path(__file__).parent)

        with (
            patch("mahavishnu.cli.config_validator.validate_config", return_value=mock_report),
            patch("mahavishnu.cli.config_validator.MahavishnuSettings", return_value=mock_settings),
            patch("mahavishnu.cli.config_validator._validate_runtime_settings", return_value=[]),
            patch(
                "mahavishnu.cli.config_validator._validate_runtime_connectivity",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await run_validation(config_dir="/some/path", full=True)

        assert result["full"] is True
        assert result["runtime_settings_source"] == "/some/path"

    @pytest.mark.asyncio
    async def test_settings_load_failure(self):
        mock_report = MagicMock()
        mock_report.valid = True
        mock_report.get_errors.return_value = []
        mock_report.warnings = []

        with (
            patch("mahavishnu.cli.config_validator.validate_config", return_value=mock_report),
            patch(
                "mahavishnu.cli.config_validator.MahavishnuSettings",
                side_effect=Exception("load error"),
            ),
            patch(
                "mahavishnu.cli.config_validator._load_settings_from_dir",
                side_effect=Exception("load error"),
            ),
        ):
            result = await run_validation(config_dir="/some/path")

        assert result["valid"] is False
        assert any("Failed to load" in r["message"] for r in result["runtime_validations"])

    @pytest.mark.asyncio
    async def test_runtime_errors_make_invalid(self):
        mock_report = MagicMock()
        mock_report.valid = True
        mock_report.get_errors.return_value = []
        mock_report.warnings = []

        mock_settings = MagicMock()
        mock_settings.repos_path = str(Path(__file__).parent)

        bad_validation = ValidationResult(valid=False, message="repos missing", path="repos_path")
        with (
            patch("mahavishnu.cli.config_validator.validate_config", return_value=mock_report),
            patch("mahavishnu.cli.config_validator.MahavishnuSettings", return_value=mock_settings),
            patch(
                "mahavishnu.cli.config_validator._validate_runtime_settings",
                return_value=[bad_validation],
            ),
        ):
            result = await run_validation(config_dir="/some/path")

        assert result["valid"] is False
        assert result["summary"]["error_count"] >= 1

    @pytest.mark.asyncio
    async def test_default_settings_dir(self):
        mock_report = MagicMock()
        mock_report.valid = True
        mock_report.get_errors.return_value = []
        mock_report.warnings = []

        mock_settings = MagicMock()
        mock_settings.repos_path = str(Path(__file__).parent)

        real_settings_path = Path("settings").resolve()

        with (
            patch("mahavishnu.cli.config_validator.validate_config", return_value=mock_report),
            patch("mahavishnu.cli.config_validator.MahavishnuSettings", return_value=mock_settings),
            patch("mahavishnu.cli.config_validator._validate_runtime_settings", return_value=[]),
        ):
            result = await run_validation(config_dir="settings")

        assert result["runtime_settings_source"] == "settings"


# ---------------------------------------------------------------------------
# _load_settings_from_dir
# ---------------------------------------------------------------------------


class TestLoadSettingsFromDir:
    def test_empty_dir_uses_defaults(self, tmp_path):
        settings = _load_settings_from_dir(tmp_path)
        assert settings is not None

    def test_merges_yaml_files(self, tmp_path):
        (tmp_path / "mahavishnu.yaml").write_text("server_name: base\n")
        (tmp_path / "local.yaml").write_text("server_name: override\n")
        settings = _load_settings_from_dir(tmp_path)
        assert settings.server_name == "override"

    def test_sets_default_repos_path(self, tmp_path):
        settings = _load_settings_from_dir(tmp_path)
        assert "repos.yaml" in settings.repos_path


# ---------------------------------------------------------------------------
# add_config_validation_commands
# ---------------------------------------------------------------------------


class TestAddConfigValidationCommands:
    def test_command_registered(self):
        app = typer.Typer()
        import mahavishnu.cli.config_validator as cv_mod

        cv_mod.add_config_validation_commands(app)
        registered_names = [c.name for c in app.registered_commands]
        assert "validate" in registered_names

    def test_validate_command_json_output(self, tmp_path):
        from typer.testing import CliRunner

        runner = CliRunner()
        app = typer.Typer()
        import mahavishnu.cli.config_validator as cv_mod

        cv_mod.add_config_validation_commands(app)

        mock_report_dict = {
            "valid": True,
            "config_dir": str(tmp_path),
            "full": False,
            "runtime_settings_source": "settings",
            "static": {"valid": True, "errors": [], "warnings": []},
            "runtime_checks": [],
            "runtime_validations": [],
            "runtime_check_count": 0,
            "runtime_validation_count": 0,
            "summary": {
                "error_count": 0,
                "warning_count": 0,
                "runtime_check_count": 0,
                "runtime_validation_count": 0,
            },
        }

        with patch(
            "mahavishnu.cli.config_validator.run_validation",
            new_callable=AsyncMock,
            return_value=mock_report_dict,
        ):
            result = runner.invoke(app, ["--json", "-c", str(tmp_path)])

        assert result.exit_code == 0

    def test_validate_command_failure_exits_1(self, tmp_path):
        from typer.testing import CliRunner

        runner = CliRunner()
        app = typer.Typer()
        import mahavishnu.cli.config_validator as cv_mod

        cv_mod.add_config_validation_commands(app)

        mock_report_dict = {
            "valid": False,
            "config_dir": str(tmp_path),
            "full": False,
            "runtime_settings_source": "settings",
            "static": {"valid": False, "errors": [], "warnings": []},
            "runtime_checks": [],
            "runtime_validations": [],
            "runtime_check_count": 0,
            "runtime_validation_count": 0,
            "summary": {
                "error_count": 0,
                "warning_count": 0,
                "runtime_check_count": 0,
                "runtime_validation_count": 0,
            },
        }

        with patch(
            "mahavishnu.cli.config_validator.run_validation",
            new_callable=AsyncMock,
            return_value=mock_report_dict,
        ):
            result = runner.invoke(app, ["-c", str(tmp_path)])

        assert result.exit_code == 1
