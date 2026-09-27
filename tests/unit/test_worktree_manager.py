"""Tests for WorktreeManager (post C-8 / REQ-010).

The ``WorktreeInfo`` shape was REPLACED (no longer carries ``task_id``,
``path``, ``branch``, ``state``, ``completed_at``, or ``metadata``).
``WorktreeState`` and ``GitRunner`` were dropped per the no-backcompat
policy. ``WorktreeManager`` now takes ``base_path`` + ``event_store``.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.core.worktree_manager import (
    WorktreeCompletion,
    WorktreeError,
    WorktreeInfo,
    WorktreeManager,
)


class TestWorktreeInfo:
    """Tests for the REPLACED ``WorktreeInfo`` dataclass."""

    def test_create_worktree_info_minimal(self) -> None:
        info = WorktreeInfo(
            worktree_id="wt-123",
            repo_path=Path("/tmp/repo"),
            branch_name="feature/wt-123",
            base_branch="main",
            created_at=datetime.now(UTC),
            ttl_seconds=3600,
        )
        assert info.worktree_id == "wt-123"
        assert info.repo_path == Path("/tmp/repo")
        assert info.branch_name == "feature/wt-123"
        # New fields default to empty
        assert info.diff == ""
        assert info.merge is False
        assert info.files_touched == []

    def test_worktree_info_to_dict_includes_new_fields(self) -> None:
        info = WorktreeInfo(
            worktree_id="wt-001",
            repo_path=Path("/tmp/repo"),
            branch_name="feature/wt-001",
            base_branch="main",
            created_at=datetime.now(UTC),
            ttl_seconds=3600,
        )
        info.diff = "diff content"
        info.merge = True
        info.files_touched = ["a.py", "b.py"]
        d = info.to_dict()
        assert d["worktree_id"] == "wt-001"
        assert d["diff"] == "diff content"
        assert d["merge"] is True
        assert d["files_touched"] == ["a.py", "b.py"]
        assert d["repo_path"] == "/tmp/repo"


class TestWorktreeCompletion:
    """Tests for ``WorktreeCompletion`` wrapper."""

    def test_wraps_worktree_info(self) -> None:
        info = WorktreeInfo(
            worktree_id="wt-002",
            repo_path=Path("/tmp/repo"),
            branch_name="feature/wt-002",
            base_branch="main",
            created_at=datetime.now(UTC),
            ttl_seconds=3600,
        )
        completion = WorktreeCompletion(info=info)
        assert completion.info is info


class TestWorktreeManagerConstructor:
    """Tests for the REPLACED WorktreeManager constructor."""

    def test_constructor_default(self) -> None:
        mgr = WorktreeManager()
        assert mgr._registry == {}

    def test_constructor_with_base_path(self, tmp_path: Path) -> None:
        mgr = WorktreeManager(base_path=str(tmp_path / "worktrees"))
        assert mgr._base_path == str(tmp_path / "worktrees")

    def test_constructor_with_event_store(self) -> None:
        mock_es = AsyncMock()
        mgr = WorktreeManager(event_store=mock_es)
        assert mgr._registry == {}


class TestWorktreeManagerPathGeneration:
    def test_worktree_path_generation(self, tmp_path: Path) -> None:
        mgr = WorktreeManager(base_path=str(tmp_path / "worktrees"))
        path = mgr._get_worktree_path(Path("/tmp/repo"), "wt-123")
        assert path == Path("/tmp/repo/.worktrees/wt-123")

    def test_worktree_path_legacy(self) -> None:
        mgr = WorktreeManager(base_path="")
        path = mgr._get_worktree_path(Path("/repos/mahavishnu"), "wt-1")
        assert path == Path("/repos/mahavishnu/.worktrees/wt-1")


class TestWorktreeManagerRegistry:
    def test_get_missing_worktree(self) -> None:
        mgr = WorktreeManager()
        assert mgr.get_worktree("missing") is None
        assert mgr.worktree_exists("missing") is False

    def test_list_worktrees_empty(self) -> None:
        mgr = WorktreeManager()
        assert mgr.list_worktrees() == []

    def test_get_summary(self) -> None:
        mgr = WorktreeManager()
        mgr._registry["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            repo_path=Path("/tmp/repo"),
            branch_name="feature/wt-1",
            base_branch="main",
            created_at=datetime.now(UTC),
            ttl_seconds=3600,
        )
        summary = mgr.get_summary()
        assert summary["total_worktrees"] == 1
        assert summary["active_worktrees"] == 1


class TestCreateWorktree:
    @pytest.mark.asyncio
    async def test_create_worktree_success(self, tmp_path: Path) -> None:
        # Set up a real git repo so ``git worktree add`` can run.
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        (repo / "README.md").write_text("hi\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        wt_root = tmp_path / "worktrees"
        wt_root.mkdir()
        mgr = WorktreeManager(base_path=str(wt_root))
        try:
            info = await mgr.create_worktree(
                task_id="task-1",
                repo_path=repo,
                branch_name="feature/task-1",
                base_branch="main",
                ttl_seconds=3600,
            )
            assert info.worktree_id.startswith("wt-")
            assert info.branch_name == "feature/task-1"
            assert info.base_branch == "main"
            assert info.ttl_seconds == 3600
            assert info.diff == ""
            assert mgr.worktree_exists(info.worktree_id)
        finally:
            # Best-effort cleanup
            subprocess.run(
                ["git", "worktree", "remove", "--force"],
                cwd=repo,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "branch", "-D", "feature/task-1"],
                cwd=repo,
                capture_output=True,
                check=False,
            )

    @pytest.mark.asyncio
    async def test_create_worktree_git_error_raises(self) -> None:
        """When git fails, WorktreeError is raised."""
        mgr = WorktreeManager()
        with patch.object(
            mgr,
            "_get_worktree_path",
            return_value=Path("/nonexistent/wt"),
        ):
            # Force the subprocess.run inside _git_worktree_add to raise
            with patch(
                "mahavishnu.core.worktree_manager.subprocess.run",
                side_effect=subprocess.CalledProcessError(128, "git", stderr=b"fatal: bad"),
            ):
                with pytest.raises(WorktreeError, match="git diff failed|Failed to create"):
                    await mgr.create_worktree(
                        task_id="task-1",
                        repo_path=Path("/nonexistent/repo"),
                        branch_name="feature/task-1",
                    )


class TestCompleteWorktree:
    @pytest.mark.asyncio
    async def test_complete_unknown_worktree_raises(self) -> None:
        mgr = WorktreeManager()
        with pytest.raises(WorktreeError, match="not found"):
            await mgr.complete_worktree("missing", merge=False)

    @pytest.mark.asyncio
    async def test_complete_without_merge_populates_diff(self, tmp_path: Path) -> None:
        # Real repo with initial commit + worktree + change + second commit.
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        (repo / "README.md").write_text("hi\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        wt_root = tmp_path / "worktrees"
        wt_root.mkdir()
        mgr = WorktreeManager(base_path=str(wt_root))
        try:
            info = await mgr.create_worktree(
                task_id="task-cw",
                repo_path=repo,
                branch_name="feature/task-cw",
                base_branch="main",
                ttl_seconds=3600,
            )
            wt_path = repo / ".worktrees" / info.worktree_id
            (wt_path / "new_file.txt").write_text("hello\n")
            subprocess.run(["git", "add", "new_file.txt"], cwd=wt_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "add file"],
                cwd=wt_path,
                check=True,
                capture_output=True,
            )
            completion = await mgr.complete_worktree(
                worktree_id=info.worktree_id,
                merge=False,
                repo_path=repo,
            )
            assert isinstance(completion, WorktreeCompletion)
            assert "new_file.txt" in completion.info.files_touched
            assert "new_file.txt" in completion.info.diff
            assert completion.info.merge is False
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force"],
                cwd=repo,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "branch", "-D", "feature/task-cw"],
                cwd=repo,
                capture_output=True,
                check=False,
            )

    @pytest.mark.asyncio
    async def test_complete_missing_repo_path_raises_when_merge(self) -> None:
        mgr = WorktreeManager()
        mgr._registry["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            repo_path=Path("/tmp/repo"),
            branch_name="feature/wt-1",
            base_branch="main",
            created_at=datetime.now(UTC),
            ttl_seconds=3600,
        )
        with pytest.raises(WorktreeError, match="repo_path required"):
            await mgr.complete_worktree("wt-1", merge=True, repo_path=None)


class TestCleanupWorktree:
    @pytest.mark.asyncio
    async def test_cleanup_missing_returns_false(self) -> None:
        mgr = WorktreeManager()
        assert await mgr.cleanup_worktree("missing") is False

    @pytest.mark.asyncio
    async def test_cleanup_known_worktree_returns_true(self, tmp_path: Path) -> None:
        mgr = WorktreeManager(base_path=str(tmp_path / "wt"))
        mgr._registry["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            repo_path=tmp_path,
            branch_name="feature/wt-1",
            base_branch="main",
            created_at=datetime.now(UTC),
            ttl_seconds=3600,
        )
        assert await mgr.cleanup_worktree("wt-1") is True
        assert "wt-1" not in mgr._registry


class TestAbandonWorktree:
    @pytest.mark.asyncio
    async def test_abandon_missing_returns_false(self) -> None:
        mgr = WorktreeManager()
        assert await mgr.abandon_worktree("missing") is False

    @pytest.mark.asyncio
    async def test_abandon_known_returns_true(self) -> None:
        mgr = WorktreeManager()
        mgr._registry["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            repo_path=Path("/tmp/repo"),
            branch_name="feature/wt-1",
            base_branch="main",
            created_at=datetime.now(UTC),
            ttl_seconds=3600,
        )
        assert await mgr.abandon_worktree("wt-1") is True
