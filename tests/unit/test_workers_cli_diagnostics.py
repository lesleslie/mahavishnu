"""Diagnostics wiring for worker list-types CLI.

Covers Task 10 of the worker-readiness plan: the ``--ready`` and ``--all``
filters added to ``mahavishnu workers list-types``.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_list_types_ready_only(monkeypatch: pytest.MonkeyPatch) -> None:
    env = os.environ.copy()
    env["MAHAVISHNU_LOG_LEVEL"] = "ERROR"
    env["PATH"] = "/usr/bin:/bin"
    env.pop("MINIMAX_API_KEY", None)
    env.pop("OPENCLAW_GATEWAY_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "mahavishnu", "workers", "list-types", "--ready"],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0
    assert not any(
        "terminal-claude" in line and "READY" in line
        for line in result.stdout.splitlines()
    )
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
