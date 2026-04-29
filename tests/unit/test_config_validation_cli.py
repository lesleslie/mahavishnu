"""Tests for the configuration validation CLI."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from mahavishnu._main_cli import app
from mahavishnu.cli.config_validator import DriftReport, run_validation
from mahavishnu.core.health_schemas import HealthStatus

if TYPE_CHECKING:
    from pathlib import Path


def _write_validation_config(tmp_path: Path) -> Path:
    """Create a minimal, valid config directory for validation tests."""
    config_dir = tmp_path / "settings"
    config_dir.mkdir()

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    (config_dir / "repos.yaml").write_text(
        f"""
repos:
  - name: test-repo
    path: {repo_dir}
    role: tool
    tags: [mcp, test]
""".strip()
    )

    (config_dir / "mahavishnu.yaml").write_text(
        f"""
repos_path: {config_dir / "repos.yaml"}
prefect:
  enabled: true
  api_url: http://localhost:4200
agno:
  enabled: true
  tools:
    mcp_server_url: http://localhost:8678/mcp
session_buddy_polling:
  enabled: true
  endpoint: http://localhost:8678/mcp
health:
  enabled: true
  dependencies:
    session_buddy:
      host: localhost
      port: 8678
      required: true
      timeout_seconds: 5
""".strip()
    )

    return config_dir


class TestValidateCommand:
    """Validate CLI wiring for the configuration validator."""

    def test_validate_command_is_exposed(self):
        """The top-level CLI should expose validate with the expected flags."""
        runner = CliRunner()
        result = runner.invoke(app, ["validate", "--help"])

        assert result.exit_code == 0
        assert "Validate configuration files and runtime connectivity" in result.stdout
        assert "--full" in result.stdout
        assert "--config-dir" in result.stdout

    def test_validate_command_json_output(self, monkeypatch):
        """The validate command should emit structured JSON when requested."""
        runner = CliRunner()

        monkeypatch.setattr(
            "mahavishnu.cli.config_validator.run_validation",
            AsyncMock(
                return_value={
                    "valid": True,
                    "config_dir": "settings",
                    "full": False,
                    "runtime_settings_source": "settings",
                    "static": {"errors": [], "warnings": []},
                    "runtime_checks": [],
                    "summary": {"error_count": 0, "warning_count": 0, "runtime_check_count": 0},
                }
            ),
        )

        result = runner.invoke(app, ["validate", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["valid"] is True
        assert payload["summary"]["error_count"] == 0


class TestValidationHelper:
    """Validate the helper used by the CLI command."""

    @pytest.mark.asyncio
    async def test_run_validation_full_checks_connectivity(self, tmp_path: Path):
        """Full validation should include runtime connectivity checks."""
        config_dir = _write_validation_config(tmp_path)
        fake_result = SimpleNamespace(
            status=HealthStatus.OK,
            latency_ms=12.5,
            error=None,
            response_data={"status": "ok"},
        )

        with patch(
            "mahavishnu.cli.config_validator.HealthChecker.check",
            new=AsyncMock(return_value=fake_result),
        ), patch(
            "mahavishnu.cli.config_validator.check_skill_agent_drift",
            return_value=DriftReport(),
        ):
            report = await run_validation(config_dir=config_dir, full=True)

        assert report["valid"] is True
        assert report["runtime_check_count"] >= 2
        assert any(
            check["name"] == "session_buddy" and check["valid"] is True
            for check in report["runtime_checks"]
        )
        assert any(
            check["name"] == "session_buddy_polling" and check["valid"] is True
            for check in report["runtime_checks"]
        )

    @pytest.mark.asyncio
    async def test_run_validation_blocks_bad_pool_config(self, tmp_path: Path):
        """Cross-field pool validation should fail when min_workers exceeds max_workers."""
        config_dir = tmp_path / "settings"
        config_dir.mkdir()
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        (config_dir / "repos.yaml").write_text(
            f"""
repos:
  - name: test-repo
    path: {repo_dir}
""".strip()
        )
        (config_dir / "mahavishnu.yaml").write_text(
            f"""
repos_path: {config_dir / "repos.yaml"}
pools:
  enabled: true
  min_workers: 8
  max_workers: 2
""".strip()
        )

        report = await run_validation(config_dir=config_dir, full=False)

        assert report["valid"] is False
        assert report["summary"]["error_count"] >= 1
        assert any(
            "min_workers" in item["path"] for item in report["runtime_validations"]
        )
