"""E2E smoke test for the ``mahavishnu executions`` CLI (C-12, REQ-019).

Verifies the sub-app is wired into the package-root ``_main_cli.py`` and
that ``--help`` lists both ``list`` and ``show`` against a real
``python -m mahavishnu`` invocation. Round-6 fix: smoke tests must
exercise the entry point, not the isolated Typer app — a CLI that
registers correctly in-process but fails to register in the parent
app must still fail e2e.
"""
from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.req(["REQ-019"])
@pytest.mark.e2e
@pytest.mark.slow
class TestExecutionsE2E:
    """End-to-end smoke against ``python -m mahavishnu executions``."""

    # The package entry point bootstraps MahavishnuApp (config, auth,
    # websocket infra). Cold start is ~10-15s on macOS; the per-call
    # timeout below (60s) leaves headroom for slower CI machines.
    _TIMEOUT_S = 60

    def test_cli_invokable_via_module(self) -> None:
        """``python -m mahavishnu executions --help`` returns successfully."""
        result = subprocess.run(
            [sys.executable, "-m", "mahavishnu", "executions", "--help"],
            capture_output=True,
            text=True,
            timeout=self._TIMEOUT_S,
            check=False,
        )
        assert result.returncode == 0, (
            f"executions --help failed: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        assert "list" in result.stdout
        assert "show" in result.stdout

    def test_list_subcommand_help(self) -> None:
        """``executions list --help`` returns successfully with usage."""
        result = subprocess.run(
            [sys.executable, "-m", "mahavishnu", "executions", "list", "--help"],
            capture_output=True,
            text=True,
            timeout=self._TIMEOUT_S,
            check=False,
        )
        assert result.returncode == 0, (
            f"executions list --help failed: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        assert "Usage:" in result.stdout

    def test_show_subcommand_help(self) -> None:
        """``executions show --help`` returns successfully with usage."""
        result = subprocess.run(
            [sys.executable, "-m", "mahavishnu", "executions", "show", "--help"],
            capture_output=True,
            text=True,
            timeout=self._TIMEOUT_S,
            check=False,
        )
        assert result.returncode == 0, (
            f"executions show --help failed: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        assert "Usage:" in result.stdout
        assert "execution_id" in result.stdout
