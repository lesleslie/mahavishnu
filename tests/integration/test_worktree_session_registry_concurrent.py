"""Integration test: flock correctness under concurrent writes.

Spawns N processes, each registering a unique session, then verifies
that all N entries land in the registry intact. Without proper flock
serialization across the read-modify-write, two writers can clobber
each other's entries (last-write wins per file replace).

This test uses a ``multiprocessing.Barrier`` to force all children to
start their RMW simultaneously — without the barrier, the natural
process startup stagger produces only intermittent failures (~33% per
prior observation), which masked the bug as flakiness.
"""
from __future__ import annotations

import multiprocessing
from pathlib import Path  # noqa: TC003 — type-only with __future__ annotations

import pytest

from mahavishnu.core.worktree_session_registry import SessionWorktreeRegistry


def _child_register(args: tuple) -> None:
    """Child-process worker: wait at barrier, then register and exit."""
    path_str, key, pid, barrier = args
    path = Path(path_str)
    registry = SessionWorktreeRegistry(path=path)
    # Synchronize all children at this point — release simultaneously to
    # maximize lock contention. Without this, the race window between
    # ``_read`` and ``_save_sessions`` is hit only ~33% of runs.
    barrier.wait(timeout=30)
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
    """8 parallel processes each register a unique session — all 8 survive.

    Uses ``multiprocessing.Barrier`` to force all children to start
    their RMW at the same instant, deterministically reproducing the
    lost-update race when ``register`` does not hold a single lock
    across the read and the write.
    """
    path = tmp_path / "session-worktrees.json"
    n = 8

    barrier = multiprocessing.Barrier(n)
    args = [
        (str(path), f"child{i:02d}", 1000 + i, barrier)
        for i in range(n)
    ]

    # Use spawn to avoid macOS fork issues with file descriptor state.
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_child_register, args=(a,)) for a in args]
    for p in procs:
        p.start()
    for p in procs:
        try:
            p.join(timeout=30)
            assert not p.is_alive(), "child hung"
            assert p.exitcode == 0, f"child failed: {p.exitcode}"
        finally:
            if p.is_alive():
                p.terminate()
                p.join()

    # Verify all N entries made it.
    registry = SessionWorktreeRegistry(path=path)
    sessions = registry.list_active(state=None)
    keys = {s["session_id_short"] for s in sessions}
    expected = {f"child{i:02d}" for i in range(n)}
    assert keys == expected, (
        f"missing or extra entries: missing={expected - keys}, extra={keys - expected}"
    )
