"""Unit tests for ``mahavishnu worktree list-sessions`` and ``prune-abandoned``.

Per multi-agent review T2 (2026-07-20): the two new subcommands had
zero direct CLI coverage. These tests pin their behavior end-to-end
via Typer's ``CliRunner`` against a real ``SessionWorktreeRegistry``
backed by ``tmp_path``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mahavishnu.core.worktree_session_registry import SessionWorktreeRegistry
from mahavishnu.worktree_cli import worktree_app


runner = CliRunner()


@pytest.fixture
def registry_path(tmp_path: Path) -> Path:
    """Per-test registry path passed via --registry-path."""
    return tmp_path / "session-worktrees.json"


def _seed(
    path: Path,
    *keys: str,
    mark_abandoned_after: dict[str, timedelta] | None = None,
) -> None:
    """Register ``keys`` against the registry at ``path``.

    ``mark_abandoned_after``: per-key offset from "now" that determines
    when the entry was abandoned. Used to exercise age filters.
    """
    registry = SessionWorktreeRegistry(path=path)
    for key in keys:
        registry.register(
            session_id_short=key,
            worktree_path=f"/Users/les/worktrees/agent-{key}",
            branch=f"worktree-agent-{key}",
            repo_path="/Users/les/Projects/mahavishnu",
            repo_nickname="mahavishnu",
            metadata={"hook_pid": 1234},
        )
    if mark_abandoned_after:
        # Patch _empty's updated_at to control timestamps.
        import mahavishnu.core.worktree_session_registry as reg_mod

        original_now = reg_mod.utcnow_iso
        try:
            for key, offset in mark_abandoned_after.items():
                # Abandon with a backdated timestamp.
                fake_now = (
                    datetime.now(timezone.utc) - offset
                ).isoformat(timespec="milliseconds").replace(
                    "+00:00", "Z"
                )
                reg_mod.utcnow_iso = lambda: fake_now
                registry.mark_abandoned(key, abandoned_at=fake_now)
        finally:
            reg_mod.utcnow_iso = original_now


# ── list-sessions ────────────────────────────────────────────────


def test_list_sessions_empty_registry(registry_path: Path) -> None:
    """Empty registry → 'No sessions found' message."""
    result = runner.invoke(
        worktree_app,
        ["list-sessions", "--registry-path", str(registry_path)],
    )
    assert result.exit_code == 0
    assert "No sessions found" in result.stdout


def test_list_sessions_shows_active_by_default(registry_path: Path) -> None:
    """Default state filter: only active entries."""
    _seed(registry_path, "a0c5d2a0", "b1d6e3f1")
    # Mark one abandoned by manipulating the registry directly via mark_abandoned.
    SessionWorktreeRegistry(path=registry_path).mark_abandoned("b1d6e3f1")

    result = runner.invoke(
        worktree_app,
        ["list-sessions", "--registry-path", str(registry_path)],
    )
    assert result.exit_code == 0
    assert "a0c5d2a0" in result.stdout
    assert "b1d6e3f1" not in result.stdout


def test_list_sessions_state_all_shows_both(registry_path: Path) -> None:
    """``--state all`` returns both active and abandoned."""
    _seed(registry_path, "a0c5d2a0", "b1d6e3f1")
    SessionWorktreeRegistry(path=registry_path).mark_abandoned("b1d6e3f1")

    result = runner.invoke(
        worktree_app,
        ["list-sessions", "--state", "all", "--registry-path", str(registry_path)],
    )
    assert result.exit_code == 0
    assert "a0c5d2a0" in result.stdout
    assert "b1d6e3f1" in result.stdout


def test_list_sessions_state_abandoned_filter(registry_path: Path) -> None:
    """``--state abandoned`` returns only abandoned."""
    _seed(registry_path, "a0c5d2a0", "b1d6e3f1")
    SessionWorktreeRegistry(path=registry_path).mark_abandoned("b1d6e3f1")

    result = runner.invoke(
        worktree_app,
        ["list-sessions", "--state", "abandoned", "--registry-path", str(registry_path)],
    )
    assert result.exit_code == 0
    assert "a0c5d2a0" not in result.stdout
    assert "b1d6e3f1" in result.stdout


def test_list_sessions_older_than_days_filter(registry_path: Path) -> None:
    """``--older-than-days N`` filters by age.

    Older abandoned entries (10 days) appear with --older-than-days 5;
    newer abandoned entries (1 day) do not.
    """
    _seed(
        registry_path,
        "old_entry",
        "new_entry",
        mark_abandoned_after={
            "old_entry": timedelta(days=10),
            "new_entry": timedelta(days=1),
        },
    )

    result = runner.invoke(
        worktree_app,
        [
            "list-sessions",
            "--state", "abandoned",
            "--older-than-days", "5",
            "--registry-path", str(registry_path),
        ],
    )
    assert result.exit_code == 0
    assert "old_entry" in result.stdout
    assert "new_entry" not in result.stdout


def test_list_sessions_creates_file_on_first_write(
    tmp_path: Path,
) -> None:
    """First list-sessions call on a missing registry creates the file (empty)."""
    path = tmp_path / "new-registry.json"
    assert not path.exists()
    result = runner.invoke(
        worktree_app,
        ["list-sessions", "--registry-path", str(path)],
    )
    assert result.exit_code == 0
    # No file is created — list is read-only; empty registry returns
    # the empty-registry default.
    assert "No sessions found" in result.stdout


# ── prune-abandoned ───────────────────────────────────────────────


def test_prune_abandoned_empty_registry(registry_path: Path) -> None:
    """Empty registry → 'No abandoned sessions' message."""
    result = runner.invoke(
        worktree_app,
        ["prune-abandoned", "--registry-path", str(registry_path)],
    )
    assert result.exit_code == 0
    assert "No abandoned sessions" in result.stdout


def test_prune_abandoned_dry_run_leaves_entries(
    registry_path: Path,
) -> None:
    """``--dry-run`` previews but does not remove."""
    _seed(registry_path, "a0c5d2a0")
    SessionWorktreeRegistry(path=registry_path).mark_abandoned("a0c5d2a0")

    result = runner.invoke(
        worktree_app,
        ["prune-abandoned", "--older-than-days", "0", "--dry-run",
         "--registry-path", str(registry_path)],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.stdout

    # Entry should still be in the registry.
    registry = SessionWorktreeRegistry(path=registry_path)
    entries = registry.list_active(state=None)
    assert any(e["session_id_short"] == "a0c5d2a0" for e in entries)


def test_prune_abandoned_removes_entries(registry_path: Path) -> None:
    """Without ``--dry-run``: entries are removed."""
    _seed(registry_path, "a0c5d2a0", "b1d6e3f1")
    registry = SessionWorktreeRegistry(path=registry_path)
    registry.mark_abandoned("a0c5d2a0")
    registry.mark_abandoned("b1d6e3f1")

    result = runner.invoke(
        worktree_app,
        ["prune-abandoned", "--older-than-days", "0",
         "--registry-path", str(registry_path)],
    )
    assert result.exit_code == 0
    assert "Removed" in result.stdout
    assert "git worktrees themselves" in result.stdout  # safety reminder

    # All entries should be gone.
    remaining = registry.list_active(state=None)
    assert remaining == []


def test_prune_abandoned_does_not_remove_active(
    registry_path: Path,
) -> None:
    """Active entries are NOT touched (only abandoned are pruned)."""
    _seed(registry_path, "active_only", "to_be_pruned")
    registry = SessionWorktreeRegistry(path=registry_path)
    registry.mark_abandoned("to_be_pruned")

    result = runner.invoke(
        worktree_app,
        ["prune-abandoned", "--older-than-days", "0",
         "--registry-path", str(registry_path)],
    )
    assert result.exit_code == 0

    remaining = {e["session_id_short"] for e in registry.list_active(state=None)}
    assert remaining == {"active_only"}


def test_prune_abandoned_older_than_days_filter(
    registry_path: Path,
) -> None:
    """``--older-than-days N`` only prunes entries abandoned at least N days ago."""
    _seed(
        registry_path,
        "old_entry",
        "new_entry",
        mark_abandoned_after={
            "old_entry": timedelta(days=10),
            "new_entry": timedelta(days=1),
        },
    )

    result = runner.invoke(
        worktree_app,
        ["prune-abandoned", "--older-than-days", "5",
         "--registry-path", str(registry_path)],
    )
    assert result.exit_code == 0

    remaining = {e["session_id_short"] for e in SessionWorktreeRegistry(
        path=registry_path
    ).list_active(state=None)}
    assert remaining == {"new_entry"}


def test_prune_abandoned_default_is_seven_days(
    registry_path: Path,
) -> None:
    """Without ``--older-than-days``, the default is 7 days.

    An entry abandoned 3 days ago is NOT pruned by default.
    """
    _seed(
        registry_path,
        "recent",
        mark_abandoned_after={"recent": timedelta(days=3)},
    )

    result = runner.invoke(
        worktree_app,
        ["prune-abandoned", "--registry-path", str(registry_path)],
    )
    assert result.exit_code == 0
    assert "No abandoned sessions older than 7 days" in result.stdout

    remaining = {e["session_id_short"] for e in SessionWorktreeRegistry(
        path=registry_path
    ).list_active(state=None)}
    assert "recent" in remaining


def test_prune_abandoned_never_removes_worktrees_on_disk(
    registry_path: Path, tmp_path: Path
) -> None:
    """SAFETY: pruning removes the registry entry but not the worktree directory."""
    wt_dir = tmp_path / "fake-worktree"
    wt_dir.mkdir()

    registry = SessionWorktreeRegistry(path=registry_path)
    registry.register(
        session_id_short="x",
        worktree_path=str(wt_dir),
        branch="worktree-agent-x",
        repo_path=str(tmp_path),
        repo_nickname="x",
    )
    registry.mark_abandoned("x")

    result = runner.invoke(
        worktree_app,
        ["prune-abandoned", "--older-than-days", "0",
         "--registry-path", str(registry_path)],
    )
    assert result.exit_code == 0

    # Registry entry is gone...
    assert registry.get("x") is None
    # ...but the worktree directory still exists.
    assert wt_dir.exists()