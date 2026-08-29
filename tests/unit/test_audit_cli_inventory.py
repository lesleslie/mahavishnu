"""Tests for scripts/audit_cli_inventory.py.

Per Bodai CLI Audit Phase 0 Task 0.1 — verify that inventory_one_repo
returns the per-command schema required by the Phase 1 inventory
subagents and the Phase 7 quarterly staleness cadence.
"""
from __future__ import annotations

from pathlib import Path

from scripts.audit_cli_inventory import inventory_one_repo


def test_inventory_mahavishnu_returns_per_command_fields(tmp_path):
    out = tmp_path / "mahavishnu-cli-inventory.json"
    # Use this repo's own checkout (works inside the worktree where the
    # inventory script lives); the production CLI hardcodes the canonical
    # /Users/les/Projects/mahavishnu path per the spec.
    repo_path = str(Path(__file__).resolve().parents[2])
    data = inventory_one_repo("mahavishnu", repo_path, out)
    assert data["repo"] == "mahavishnu"
    assert "commands" in data
    assert isinstance(data["commands"], list)
    # Per-command schema (every command must have these keys)
    for cmd in data["commands"]:
        assert set(cmd.keys()) >= {
            "command_path",
            "module",
            "function",
            "short_help",
            "tests_present",
            "staleness_verdict",
        }
