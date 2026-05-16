"""Tests for WorktreeManager - Git worktree lifecycle management."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.worktree_manager import (
    WorktreeError,
    WorktreeInfo,
    WorktreeManager,
    WorktreeState,
)


@pytest.fixture
def mock_task_store() -> AsyncMock:
    """Create a mock TaskStore."""
    return AsyncMock()


@pytest.fixture
def mock_git_runner() -> MagicMock:
    """Create a mock git command runner."""
    runner = MagicMock()
    runner.run = AsyncMock()
    return runner


@pytest.fixture
def sample_worktree_info() -> WorktreeInfo:
    """Create a sample worktree info."""
    return WorktreeInfo(
        worktree_id="wt-123",
        task_id="task-1",
        path="/repos/mahavishnu-worktree-task-1",
        branch="feature/task-1",
        base_branch="main",
        state=WorktreeState.ACTIVE,
        created_at=datetime.now(UTC),
    )


class TestWorktreeState:
    """Tests for WorktreeState enum."""

    def test_worktree_states(self) -> None:
        """Test available worktree states."""
        assert WorktreeState.ACTIVE.value == "active"
        assert WorktreeState.COMPLETED.value == "completed"
        assert WorktreeState.ABANDONED.value == "abandoned"
        assert WorktreeState.MERGED.value == "merged"


class TestWorktreeInfo:
    """Tests for WorktreeInfo dataclass."""

    def test_create_worktree_info(self) -> None:
        """Create worktree info."""
        info = WorktreeInfo(
            worktree_id="wt-123",
            task_id="task-1",
            path="/path/to/worktree",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        assert info.worktree_id == "wt-123"
        assert info.task_id == "task-1"
        assert info.state == WorktreeState.ACTIVE

    def test_worktree_info_with_metadata(self) -> None:
        """Create worktree info with metadata."""
        info = WorktreeInfo(
            worktree_id="wt-456",
            task_id="task-2",
            path="/path/to/worktree2",
            branch="feature/task-2",
            base_branch="develop",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
            metadata={"description": "Implement feature X"},
        )

        assert info.metadata is not None
        assert info.metadata["description"] == "Implement feature X"

    def test_worktree_info_to_dict(self) -> None:
        """Convert worktree info to dictionary."""
        info = WorktreeInfo(
            worktree_id="wt-789",
            task_id="task-3",
            path="/path/to/worktree3",
            branch="bugfix/task-3",
            base_branch="main",
            state=WorktreeState.MERGED,
            created_at=datetime.now(UTC),
        )

        d = info.to_dict()
        assert d["worktree_id"] == "wt-789"
        assert d["task_id"] == "task-3"
        assert d["state"] == "merged"


class TestWorktreeManager:
    """Tests for WorktreeManager class."""

    @pytest.mark.asyncio
    async def test_git_runner_and_default_worktree_path_generation(
        self, mock_task_store: AsyncMock
    ) -> None:
        """Cover git runner success/failure and default path generation branches."""

        class _Process:
            def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
                self.returncode = returncode
                self._stdout = stdout
                self._stderr = stderr

            async def communicate(self) -> tuple[bytes, bytes]:
                return self._stdout, self._stderr

        runner = WorktreeManager(task_store=mock_task_store, git_runner=None)._git
        assert runner.__class__.__name__ == "GitRunner"

        async def _create_ok(*args, **kwargs):  # noqa: ANN001,ANN003
            return _Process(0, stdout=b"ok\n")

        async def _create_fail(*args, **kwargs):  # noqa: ANN001,ANN003
            return _Process(1, stderr=b"boom")

        with patch(
            "mahavishnu.core.worktree_manager.asyncio.create_subprocess_exec",
            side_effect=_create_ok,
        ):
            assert await runner.run("status", cwd="/tmp") == "ok"

        with (
            patch(
                "mahavishnu.core.worktree_manager.asyncio.create_subprocess_exec",
                side_effect=_create_fail,
            ),
            pytest.raises(Exception, match="boom"),
        ):
            await runner.run("status", cwd="/tmp")

        manager = WorktreeManager(
            task_store=mock_task_store, git_runner=MagicMock(), base_path="/repos"
        )
        assert manager._get_worktree_path("/repos/mahavishnu", "task-1") == "/repos/worktree-task-1"

        default_manager = WorktreeManager(task_store=mock_task_store, git_runner=MagicMock())
        assert (
            default_manager._get_worktree_path("/repos/mahavishnu", "task-1")
            == "/repos/mahavishnu-worktree-task-1"
        )

    @pytest.mark.asyncio
    async def test_create_worktree(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Create a new worktree for a task."""
        mock_git_runner.run.return_value = (
            "Preparing worktree (new branch 'feature/task-1')\nHEAD is now at abc123 Initial commit"
        )

        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
            base_path="/repos",
        )

        worktree = await manager.create_worktree(
            task_id="task-1",
            repo_path="/repos/mahavishnu",
            branch_name="feature/task-1",
        )

        assert worktree is not None
        assert worktree.task_id == "task-1"
        assert worktree.state == WorktreeState.ACTIVE
        assert "feature/task-1" in worktree.branch

    @pytest.mark.asyncio
    async def test_create_worktree_with_base_branch(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Create worktree from specific base branch."""
        mock_git_runner.run.return_value = "Preparing worktree (new branch)"

        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
            base_path="/repos",
        )

        worktree = await manager.create_worktree(
            task_id="task-2",
            repo_path="/repos/mahavishnu",
            branch_name="feature/task-2",
            base_branch="develop",
        )

        assert worktree is not None
        assert worktree.base_branch == "develop"

    @pytest.mark.asyncio
    async def test_list_worktrees(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """List all worktrees."""
        mock_git_runner.run.return_value = (
            "worktree /repos/mahavishnu\n"
            "HEAD abc123def456\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /repos/mahavishnu-worktree-task-1\n"
            "HEAD def456abc123\n"
            "branch refs/heads/feature/task-1\n"
        )

        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        # Add some tracked worktrees
        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/mahavishnu-worktree-task-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        worktrees = manager.list_worktrees()

        assert len(worktrees) == 1
        assert worktrees[0].task_id == "task-1"

    @pytest.mark.asyncio
    async def test_get_worktree_for_task(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Get worktree for a specific task."""
        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/worktree-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        worktree = manager.get_worktree_for_task("task-1")

        assert worktree is not None
        assert worktree.task_id == "task-1"

    @pytest.mark.asyncio
    async def test_get_nonexistent_worktree(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Get worktree for non-existent task."""
        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        worktree = manager.get_worktree_for_task("nonexistent")

        assert worktree is None

    @pytest.mark.asyncio
    async def test_complete_worktree(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Mark worktree as completed."""
        mock_git_runner.run.return_value = "Branch feature/task-1 merged into main"

        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/worktree-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        result = await manager.complete_worktree("wt-1", merge=True, repo_path="/repos/mahavishnu")

        assert result is True
        assert manager._worktrees["wt-1"].state == WorktreeState.MERGED

    @pytest.mark.asyncio
    async def test_complete_and_sync_error_branches(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Cover not-found and exception branches for lifecycle methods."""
        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        with pytest.raises(WorktreeError):
            await manager.complete_worktree("missing")

        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/worktree-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        mock_git_runner.run.side_effect = Exception("merge failed")
        with pytest.raises(WorktreeError, match="merge failed"):
            await manager.complete_worktree("wt-1", merge=True, repo_path="/repos/mahavishnu")

        assert await manager.abandon_worktree("missing") is False
        assert await manager.sync_with_base("missing") is False
        assert await manager.get_status("missing") is None

        mock_git_runner.run.side_effect = Exception("sync failed")
        manager._worktrees["wt-2"] = WorktreeInfo(
            worktree_id="wt-2",
            task_id="task-2",
            path="/repos/worktree-2",
            branch="feature/task-2",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )
        assert await manager.sync_with_base("wt-2") is False

        mock_git_runner.run.side_effect = Exception("status failed")
        manager._worktrees["wt-3"] = WorktreeInfo(
            worktree_id="wt-3",
            task_id="task-3",
            path="/repos/worktree-3",
            branch="feature/task-3",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )
        status = await manager.get_status("wt-3")
        assert status is not None
        assert status["error"] == "status failed"

    @pytest.mark.asyncio
    async def test_complete_worktree_without_merge(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Complete worktree without merging."""
        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/worktree-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        result = await manager.complete_worktree("wt-1", merge=False)

        assert result is True
        assert manager._worktrees["wt-1"].state == WorktreeState.COMPLETED

    @pytest.mark.asyncio
    async def test_abandon_worktree(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Abandon a worktree."""
        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/worktree-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        result = await manager.abandon_worktree("wt-1")

        assert result is True
        assert manager._worktrees["wt-1"].state == WorktreeState.ABANDONED

    @pytest.mark.asyncio
    async def test_cleanup_completed_worktrees(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Cleanup old completed worktrees."""
        mock_git_runner.run.return_value = "Worktree removed"

        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        # Add worktrees in different states
        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/worktree-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.MERGED,
            created_at=datetime.now(UTC),
        )
        manager._worktrees["wt-2"] = WorktreeInfo(
            worktree_id="wt-2",
            task_id="task-2",
            path="/repos/worktree-2",
            branch="feature/task-2",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        cleaned = await manager.cleanup_completed()

        assert cleaned >= 1  # At least one completed worktree cleaned

    @pytest.mark.asyncio
    async def test_cleanup_worktree(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Remove a single worktree."""
        mock_git_runner.run.return_value = "Worktree removed"

        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/worktree-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.COMPLETED,
            created_at=datetime.now(UTC),
        )

        result = await manager.cleanup_worktree("wt-1")

        assert result is True
        assert "wt-1" not in manager._worktrees

    @pytest.mark.asyncio
    async def test_cleanup_and_prune_error_branches(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cover cleanup git-remove and failure branches plus prune removal."""
        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        removable = tmp_path / "repos" / "worktree-1"
        removable.mkdir(parents=True, exist_ok=True)
        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path=str(removable),
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.COMPLETED,
            created_at=datetime.now(UTC),
        )

        mock_git_runner.run.return_value = "removed"
        assert await manager.cleanup_worktree("wt-1") is True
        assert "wt-1" not in manager._worktrees

        failing = tmp_path / "repos" / "worktree-2"
        failing.mkdir(parents=True, exist_ok=True)
        manager._worktrees["wt-2"] = WorktreeInfo(
            worktree_id="wt-2",
            task_id="task-2",
            path=str(failing),
            branch="feature/task-2",
            base_branch="main",
            state=WorktreeState.COMPLETED,
            created_at=datetime.now(UTC),
        )

        mock_git_runner.run.side_effect = Exception("cleanup failed")
        assert await manager.cleanup_worktree("wt-2") is False
        assert "wt-2" not in manager._worktrees

        existing = tmp_path / "repos" / "keep"
        existing.mkdir(parents=True, exist_ok=True)
        stale = tmp_path / "repos" / "stale"
        manager._worktrees["wt-3"] = WorktreeInfo(
            worktree_id="wt-3",
            task_id="task-3",
            path=str(stale),
            branch="feature/task-3",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )
        manager._worktrees["wt-4"] = WorktreeInfo(
            worktree_id="wt-4",
            task_id="task-4",
            path=str(existing),
            branch="feature/task-4",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        monkeypatch.setattr(
            "mahavishnu.core.worktree_manager.os.path.exists", lambda path: path == str(existing)
        )
        assert await manager.prune_stale() == 1
        assert "wt-3" not in manager._worktrees
        assert "wt-4" in manager._worktrees

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_worktree(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Cleanup non-existent worktree returns False."""
        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        result = await manager.cleanup_worktree("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_active_worktrees(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Get all active worktrees."""
        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/worktree-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )
        manager._worktrees["wt-2"] = WorktreeInfo(
            worktree_id="wt-2",
            task_id="task-2",
            path="/repos/worktree-2",
            branch="feature/task-2",
            base_branch="main",
            state=WorktreeState.COMPLETED,
            created_at=datetime.now(UTC),
        )
        manager._worktrees["wt-3"] = WorktreeInfo(
            worktree_id="wt-3",
            task_id="task-3",
            path="/repos/worktree-3",
            branch="feature/task-3",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        active = manager.get_active_worktrees()

        assert len(active) == 2
        assert all(w.state == WorktreeState.ACTIVE for w in active)

    @pytest.mark.asyncio
    async def test_sync_branch(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Sync worktree branch with base."""
        mock_git_runner.run.return_value = "Updated 5 files"

        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/worktree-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        result = await manager.sync_with_base("wt-1")

        assert result is True

    @pytest.mark.asyncio
    async def test_get_worktree_status(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Get status of a worktree."""
        # Mock multiple git command outputs
        mock_git_runner.run.side_effect = [
            "feature/task-1",  # branch --show-current
            " M file1.py\n M file2.py\n",  # status --short
            "2\t0",  # rev-list ahead/behind
        ]

        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/worktree-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        status = await manager.get_status("wt-1")

        assert status is not None
        assert "branch" in status
        assert status["branch"] == "feature/task-1"

    @pytest.mark.asyncio
    async def test_create_worktree_error_handling(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Handle errors during worktree creation."""
        mock_git_runner.run.side_effect = Exception("Git error: branch exists")

        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
            base_path="/repos",
        )

        with pytest.raises(WorktreeError):
            await manager.create_worktree(
                task_id="task-1",
                repo_path="/repos/mahavishnu",
                branch_name="feature/task-1",
            )

    @pytest.mark.asyncio
    async def test_worktree_path_generation(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Test worktree path generation."""
        mock_git_runner.run.return_value = "Preparing worktree"

        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
            base_path="/repos/worktrees",
        )

        worktree = await manager.create_worktree(
            task_id="task-123",
            repo_path="/repos/mahavishnu",
            branch_name="feature/task-123",
        )

        assert worktree is not None
        assert "task-123" in worktree.path
        assert "/repos/worktrees" in worktree.path or "worktree" in worktree.path.lower()

    @pytest.mark.asyncio
    async def test_get_worktree_summary(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Get summary of all worktrees."""
        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/worktree-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )
        manager._worktrees["wt-2"] = WorktreeInfo(
            worktree_id="wt-2",
            task_id="task-2",
            path="/repos/worktree-2",
            branch="feature/task-2",
            base_branch="main",
            state=WorktreeState.MERGED,
            created_at=datetime.now(UTC),
        )

        summary = manager.get_summary()

        assert summary["total_worktrees"] == 2
        assert summary["active_worktrees"] == 1
        assert summary["merged_worktrees"] == 1

    @pytest.mark.asyncio
    async def test_prune_stale_worktrees(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Prune stale worktrees (directory deleted)."""
        mock_git_runner.run.return_value = "Pruned 2 worktrees"

        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        pruned = await manager.prune_stale()

        assert pruned >= 0

    def test_worktree_exists(
        self,
        mock_task_store: AsyncMock,
        mock_git_runner: MagicMock,
    ) -> None:
        """Check if worktree exists."""
        manager = WorktreeManager(
            task_store=mock_task_store,
            git_runner=mock_git_runner,
        )

        manager._worktrees["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            task_id="task-1",
            path="/repos/worktree-1",
            branch="feature/task-1",
            base_branch="main",
            state=WorktreeState.ACTIVE,
            created_at=datetime.now(UTC),
        )

        assert manager.worktree_exists("wt-1") is True
        assert manager.worktree_exists("nonexistent") is False
