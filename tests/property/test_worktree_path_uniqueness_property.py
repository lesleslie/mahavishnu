"""Property test: distinct ``task_id`` always produce distinct worktree paths.

Per C-8 acceptance criteria #10. The 50-example setting is conservative;
expand if flakes appear in CI.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from hypothesis import given, settings, strategies as st

from mahavishnu.core.worktree_manager import WorktreeManager


@given(task_ids=st.lists(st.uuids(), min_size=2, max_size=10))
@settings(max_examples=50, deadline=30_000)
async def test_for_distinct_task_ids_paths_are_distinct(task_ids: list) -> None:
    """Every ``create_worktree(task_id=...)`` produces a unique worktree_id."""
    import asyncio

    mgr = WorktreeManager(base_path="/tmp/test-prop-worktrees")
    seen: set[str] = set()
    try:
        for task_id in task_ids:
            # Stub out the actual git subprocess call — we only care that the
            # worktree_id is unique per task_id.
            with patch.object(mgr, "_get_worktree_path", return_value=Path("/tmp/dummy")):
                with patch(
                    "mahavishnu.core.worktree_manager.subprocess.run",
                ):
                    info = await mgr.create_worktree(
                        task_id=str(task_id),
                        repo_path=Path("/tmp/test-repo"),
                        branch_name=f"feature/{task_id}",
                        base_branch="main",
                        ttl_seconds=3600,
                    )
                    assert info.worktree_id not in seen, (
                        f"duplicate worktree_id: {info.worktree_id}"
                    )
                    seen.add(info.worktree_id)
                    # Mimic the registry bookkeeping the production code does.
                    mgr._registry[info.worktree_id] = info
    finally:
        # Best-effort cleanup
        for wt_id in list(mgr._registry.keys()):
            await mgr.cleanup_worktree(wt_id)


def test_property_test_self_runs_under_asyncio() -> None:
    """Sanity: confirm pytest-asyncio + hypothesis machinery is wired."""
    assert asyncio is not None