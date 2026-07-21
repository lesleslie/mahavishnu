"""Diagnostics wiring for worker list-types CLI.

Covers Task 10 of the worker-readiness plan: the ``--ready`` and ``--all``
filters added to ``mahavishnu workers list-types``.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_list_types_ready_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCLAW_GATEWAY_URL", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    result = subprocess.run(
        [sys.executable, "-m", "mahavishnu", "workers", "list-types", "--ready"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0
    assert "terminal-claude" not in result.stdout
    assert "terminal-shell" in result.stdout


def test_list_types_all_flag_includes_registered() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mahavishnu", "workers", "list-types", "--all"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0
    assert "terminal-claude" in result.stdout
    assert "terminal-shell" in result.stdout
