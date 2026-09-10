"""Tests for `mahavishnu.cli.plan_cli` (Task 10)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mahavishnu.cli.plan_cli import plan_app

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestPlanCLI:
    def test_help_renders(self, runner: CliRunner) -> None:
        result = runner.invoke(plan_app, ["--help"])
        assert result.exit_code == 0
        assert "list" in result.stdout
        assert "show" in result.stdout
        assert "vitals" in result.stdout
        assert "purge" in result.stdout

    def test_list_runs_against_fake_dhara(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        runner: CliRunner,
    ) -> None:
        # Ensure dev path is exercised (no MAHAVISHNU_DHARA_URL set).
        monkeypatch.delenv("MAHAVISHNU_DHARA_URL", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        result = runner.invoke(plan_app, ["list"])
        assert result.exit_code == 0
