"""Integration test: flock correctness under concurrent writes.

Spawns N processes, each registering a unique session, then verifies
that all N entries land in the registry intact. Without proper flock
serialization, two writers can clobber each other's entries (last-write
wins per file replace, partial JSON on race).
"""
from __future__ import annotations

import multiprocessing
import sys
import tempfile
import time
from pathlib import Path

import pytest

from mahavishnu.core.worktree_session_registry import SessionWorktreeRegistry


def _child_register(args: tuple[str, str, int, float]) -> None:
    """Child-process worker: register a session, then exit."""
    path_str, key, pid, sleep_before = args
    path = Path(path_str)
    # Spawn a fresh registry per child — each process should hit the same file.
    registry = SessionWorktreeRegistry(path=path)
    # Small stagger so processes don't all flock at the same instant.
    if sleep_before > 0:
        time.sleep(sleep_before)
    registry.register(
        session_id_short=key,
        worktree_path=f"/tmp/wt-{key}",
        branch=f"worktree-agent-{key}",
        repo_path="/Users/les/Projects/mahavishnu",
        repo_nickname="mahavishnu",
        metadata={"hook_pid": pid},
    )


@pytest.mark.integration
def test_register_atomic_under_concurrent_writes(tmp_path: Path) -> None:
    """8 parallel processes each register a unique session — all 8 survive."""
    path = tmp_path / "session-worktrees.json"
    n = 8

    # Each child needs a unique key. Use a stagger so writes don't all
    # happen at the exact same instant (more realistic contention).
    args = [
        (str(path), f"child{i:02d}", 1000 + i, 0.0)
        for i in range(n)
    ]

    # Use spawn to avoid macOS fork issues with flusing state.
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_child_register, args=(a,)) for a in args]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert not p.is_alive(), "child hung"
        assert p.exitcode == 0, f"child failed: {p.exitcode}"

    # Verify all N entries made it.
    registry = SessionWorktreeRegistry(path=path)
    sessions = registry.list_active(state=None)
    keys = {s["session_id_short"] for s in sessions}
    expected = {f"child{i:02d}" for i in range(n)}
    assert keys == expected, (
        f"missing or extra entries: missing={expected - keys}, extra={keys - expected}"
    )
