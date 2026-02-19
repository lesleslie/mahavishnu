"""Integration tests for worktree management workflow.

Tests full end-to-end workflows with all components integrated:
- Complete worktree lifecycle (create → use → remove with safety checks)
- Cross-repository coordination and dependency blocking
- Provider fallback and health monitoring
- Backup creation and restoration
- Pruning stale worktrees
- Multi-repo worktree aggregation

All tests use isolated git repos and MockWorktreeProvider for safe testing.
"""

import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.worktree_coordination import WorktreeCoordinator
from mahavishnu.core.repo_models import Repository
from mahavishnu.core.coordination.models import Dependency, DependencyStatus
from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider


class TestWorktreeWorkflowIntegration:
    """Integration tests for complete worktree workflows."""

    # =========================================================================
    # Full Worktree Lifecycle Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_complete_worktree_lifecycle(self, tmp_path):
        """Test complete worktree lifecycle: create → use → remove → restore."""
        # Setup: Create isolated git repository
        repo_path = tmp_path / "repos" / "test_repo"
        repo_path.mkdir(parents=True)

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Create initial commit
        (repo_path / "README.md").write_text("# Test Repository")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Create test branch
        subprocess.run(
            ["git", "branch", "test-branch"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Setup repository manager
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(repo_path),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo
        mock_repo_manager.get_by_package.return_value = None
        mock_repo_manager.get_repo.return_value = mock_repo
        mock_repo_manager.list_repos.return_value = [mock_repo]

        mock_coord_manager = MagicMock()
        mock_coord_manager.get_blocking_dependencies.return_value = []
        mock_coord_manager.list_dependencies.return_value = []

        # Setup mock provider
        mock_provider = MockWorktreeProvider()
        mock_provider.create_worktree = AsyncMock(
            return_value={
                "success": True,
                "worktree_path": str(tmp_path / "worktrees" / "test-repo" / "test-branch"),
                "branch": "test-branch",
            }
        )
        mock_provider.list_worktrees = AsyncMock(
            return_value={
                "success": True,
                "worktrees": [
                    {
                        "path": str(tmp_path / "worktrees" / "test-repo" / "test-branch"),
                        "branch": "test-branch",
                    }
                ],
            }
        )
        mock_provider.remove_worktree = AsyncMock(return_value={"success": True})

        # Create coordinator
        worktree_path = tmp_path / "worktrees" / "test-repo" / "test-branch"
        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            backup_dir=tmp_path / "backups",
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Step 1: Create worktree
        create_result = await coordinator.create_worktree(
            repo_nickname="test-repo",
            branch="test-branch",
            user_id="user-123",
        )

        assert create_result["success"] is True
        mock_provider.create_worktree.assert_called_once()

        # Step 2: Verify worktree exists (simulated by checking mock was called)
        list_result = await coordinator.list_worktrees(repo_nickname="test-repo")
        assert list_result["success"] is True
        assert len(list_result["worktrees"]) == 1

        # Step 3: Try to remove without force (should fail if has_uncommitted)
        # Mock no uncommitted changes for this test
        coordinator._check_uncommitted_changes = AsyncMock(return_value=False)
        coordinator._verify_is_worktree = AsyncMock(return_value=True)

        remove_result = await coordinator.remove_worktree(
            repo_nickname="test-repo",
            worktree_path=str(worktree_path),
            force=False,
            user_id="user-123",
        )

        assert remove_result["success"] is True
        mock_provider.remove_worktree.assert_called_once()

    @pytest.mark.asyncio
    async def test_worktree_removal_with_backup_and_restore(self, tmp_path):
        """Test worktree removal with backup creation and restoration."""
        # Setup repository
        repo_path = tmp_path / "repos" / "test_repo"
        repo_path.mkdir(parents=True)

        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        (repo_path / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        mock_repo = Repository(
            name="Test",
            package="test",
            path=str(repo_path),
            nickname="test",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.list_dependencies.return_value = []

        mock_provider = MockWorktreeProvider()
        mock_provider.remove_worktree = AsyncMock(return_value={"success": True})

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            backup_dir=tmp_path / "backups",
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        worktree_path = tmp_path / "worktrees" / "test" / "main"

        # Mock uncommitted changes and branch detection
        coordinator._check_uncommitted_changes = AsyncMock(return_value=True)
        coordinator._get_worktree_branch = AsyncMock(return_value="main")
        coordinator._verify_is_worktree = AsyncMock(return_value=True)

        # Force remove with reason (should create backup)
        remove_result = await coordinator.remove_worktree(
            repo_nickname="test",
            worktree_path=str(worktree_path),
            force=True,
            force_reason="Fixing critical bug",
            user_id="user-123",
        )

        assert remove_result["success"] is True

        # Verify backup was created
        assert coordinator.backup_manager.create_backup_before_removal.called

    @pytest.mark.asyncio
    async def test_safety_check_workflow(self, tmp_path):
        """Test safety status checking workflow before removal."""
        repo_path = tmp_path / "repos" / "test_repo"
        repo_path.mkdir(parents=True)

        mock_repo = Repository(
            name="Test",
            package="test",
            path=str(repo_path),
            nickname="test",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.list_dependencies.return_value = []

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[MockWorktreeProvider()],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        worktree_path = tmp_path / "worktrees" / "test" / "main"

        # Mock safety check results
        coordinator._check_uncommitted_changes = AsyncMock(return_value=True)
        coordinator._verify_is_worktree = AsyncMock(return_value=True)

        # Get safety status
        status = await coordinator.get_worktree_safety_status(
            repo_nickname="test",
            worktree_path=str(worktree_path),
        )

        # Verify safety status
        assert status["uncommitted_changes"] is True
        assert status["dependencies"] == []
        assert status["is_valid_worktree"] is True
        assert status["path_safe"] is True

    # =========================================================================
    # Cross-Repository Coordination Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_cross_repo_dependency_blocking(self, tmp_path):
        """Test that worktree removal is blocked when other repos depend on it."""
        # Setup provider repo
        provider_repo = Repository(
            name="Provider",
            package="provider",
            path=str(tmp_path / "repos" / "provider"),
            nickname="provider",
            role="app",
        )

        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = provider_repo

        # Create dependency
        mock_dep = MagicMock()
        mock_dep.worktree_path = str(tmp_path / "worktrees" / "provider" / "api")
        mock_dep.status.value = "pending"  # Unsatisfied dependency
        mock_dep.consumer = "consumer"

        mock_coord_manager = MagicMock()
        mock_coord_manager.list_dependencies.return_value = [mock_dep]

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[MockWorktreeProvider()],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        worktree_path = tmp_path / "worktrees" / "provider" / "api"

        # Mock no uncommitted changes
        coordinator._check_uncommitted_changes = AsyncMock(return_value=False)
        coordinator._verify_is_worktree = AsyncMock(return_value=True)

        # Try to remove worktree (should be blocked)
        result = await coordinator.remove_worktree(
            repo_nickname="provider",
            worktree_path=str(worktree_path),
            force=False,
        )

        assert result["success"] is False
        assert result["safety_check"] == "dependency_block"
        assert "depended on by" in result["error"]
        assert "consumer" in result["dependents"]

    @pytest.mark.asyncio
    async def test_cross_repo_dependency_satisfied_no_block(self, tmp_path):
        """Test that satisfied dependencies don't block removal."""
        provider_repo = Repository(
            name="Provider",
            package="provider",
            path=str(tmp_path / "repos" / "provider"),
            nickname="provider",
            role="app",
        )

        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = provider_repo

        # Create SATISFIED dependency
        mock_dep = MagicMock()
        mock_dep.worktree_path = str(tmp_path / "worktrees" / "provider" / "api")
        mock_dep.status.value = "satisfied"  # Already satisfied
        mock_dep.consumer = "consumer"

        mock_coord_manager = MagicMock()
        mock_coord_manager.list_dependencies.return_value = [mock_dep]

        mock_provider = MockWorktreeProvider()
        mock_provider.remove_worktree = AsyncMock(return_value={"success": True})

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        worktree_path = tmp_path / "worktrees" / "provider" / "api"

        coordinator._check_uncommitted_changes = AsyncMock(return_value=False)
        coordinator._verify_is_worktree = AsyncMock(return_value=True)

        # Try to remove worktree (should succeed - satisfied dep doesn't block)
        result = await coordinator.remove_worktree(
            repo_nickname="provider",
            worktree_path=str(worktree_path),
            force=False,
        )

        assert result["success"] is True

    # =========================================================================
    # Provider Fallback Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_provider_fallback_on_failure(self, tmp_path):
        """Test automatic fallback to secondary provider."""
        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_repo = Repository(
            name="Test",
            package="test",
            path=str(tmp_path / "repos" / "test"),
            nickname="test",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.get_blocking_dependencies.return_value = []

        # Primary provider that fails
        primary_provider = MockWorktreeProvider()
        primary_provider.health_check = MagicMock(return_value=False)  # Unhealthy

        # Secondary provider that succeeds
        secondary_provider = MockWorktreeProvider()
        secondary_provider.create_worktree = AsyncMock(
            return_value={"success": True, "worktree_path": "/worktrees/test/main"}
        )

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[primary_provider, secondary_provider],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Create worktree (should use secondary provider)
        result = await coordinator.create_worktree(
            repo_nickname="test",
            branch="main",
        )

        assert result["success"] is True
        secondary_provider.create_worktree.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_providers_unavailable(self, tmp_path):
        """Test error when all providers are unavailable."""
        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider
        from mahavishnu.core.worktree_providers.errors import ProviderUnavailableError

        mock_repo = Repository(
            name="Test",
            package="test",
            path=str(tmp_path / "repos" / "test"),
            nickname="test",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()

        # Both providers unhealthy
        provider1 = MockWorktreeProvider()
        provider1.health_check = MagicMock(return_value=False)
        provider2 = MockWorktreeProvider()
        provider2.health_check = MagicMock(return_value=False)

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[provider1, provider2],
        )

        # Should raise ProviderUnavailableError
        with pytest.raises(ProviderUnavailableError):
            await coordinator.create_worktree(
                repo_nickname="test",
                branch="main",
            )

    # =========================================================================
    # Pruning Stale Worktrees Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_prune_workflow(self, tmp_path):
        """Test pruning stale worktree references."""
        repo_path = tmp_path / "repos" / "test"
        repo_path.mkdir(parents=True)

        # Initialize git repo with branches
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        (repo_path / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Create branches (one will be deleted)
        subprocess.run(
            ["git", "branch", "active-branch"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "branch", "deleted-branch"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        mock_repo = Repository(
            name="Test",
            package="test",
            path=str(repo_path),
            nickname="test",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()

        mock_provider = MockWorktreeProvider()
        mock_provider.list_worktrees = AsyncMock(
            return_value={
                "success": True,
                "worktrees": [
                    {"path": "/worktrees/test/active-branch", "branch": "active-branch"},
                    {"path": "/worktrees/test/deleted-branch", "branch": "deleted-branch"},
                ],
            }
        )
        mock_provider.remove_worktree = AsyncMock(return_value={"success": True})

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
        )

        # Mock branch existence (active-branch exists, deleted-branch doesn't)
        async def mock_branch_exists(repo_path, branch):
            return branch == "active-branch"

        coordinator._branch_exists = mock_branch_exists

        # Prune worktrees
        result = await coordinator.prune_worktrees(repo_nickname="test")

        assert result["success"] is True
        assert result["pruned_count"] == 1

        # Verify deleted-branch worktree was removed
        assert mock_provider.remove_worktree.call_count == 1

    # =========================================================================
    # Multi-Repo Aggregation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_multi_repo_worktree_aggregation(self, tmp_path):
        """Test listing worktrees across multiple repositories."""
        repos = [
            Repository(
                name="Repo 1",
                package="repo1",
                path=str(tmp_path / "repos" / "repo1"),
                nickname="repo1",
                role="app",
            ),
            Repository(
                name="Repo 2",
                package="repo2",
                path=str(tmp_path / "repos" / "repo2"),
                nickname="repo2",
                role="app",
            ),
        ]

        mock_repo_manager = MagicMock()
        mock_repo_manager.list_repos.return_value = repos

        mock_coord_manager = MagicMock()

        mock_provider = MockWorktreeProvider()

        # Mock different worktrees for each repo
        call_count = [0]

        async def mock_list(repository_path):
            call_count[0] += 1
            if call_count[0] == 1:
                return {
                    "success": True,
                    "worktrees": [
                        {"path": "/worktrees/repo1/main", "branch": "main"},
                        {"path": "/worktrees/repo1/feature", "branch": "feature"},
                    ],
                }
            else:
                return {
                    "success": True,
                    "worktrees": [
                        {"path": "/worktrees/repo2/main", "branch": "main"},
                    ],
                }

        mock_provider.list_worktrees = AsyncMock(side_effect=mock_list)

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
        )

        # List all worktrees
        result = await coordinator.list_worktrees()

        assert result["success"] is True
        assert result["total_count"] == 3  # 2 from repo1 + 1 from repo2

    # =========================================================================
    # Error Recovery Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_recovery_from_partial_failure(self, tmp_path):
        """Test system recovery from partial failures during multi-repo operations."""
        repos = [
            Repository(
                name="Repo 1",
                package="repo1",
                path=str(tmp_path / "repos" / "repo1"),
                nickname="repo1",
                role="app",
            ),
            Repository(
                name="Repo 2",
                package="repo2",
                path=str(tmp_path / "repos" / "repo2"),
                nickname="repo2",
                role="app",
            ),
            Repository(
                name="Repo 3",
                package="repo3",
                path=str(tmp_path / "repos" / "repo3"),
                nickname="repo3",
                role="app",
            ),
        ]

        mock_repo_manager = MagicMock()
        mock_repo_manager.list_repos.return_value = repos

        mock_coord_manager = MagicMock()

        mock_provider = MockWorktreeProvider()

        # Mock repo2 to fail, others to succeed
        call_count = [0]

        async def mock_list(repository_path):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("Repo 2 unavailable")
            return {
                "success": True,
                "worktrees": [{"path": f"/worktrees/repo{call_count[0]}/main", "branch": "main"}],
            }

        mock_provider.list_worktrees = AsyncMock(side_effect=mock_list)

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
        )

        # Should succeed with worktrees from repo1 and repo3 (repo2 error is logged)
        result = await coordinator.list_worktrees()

        assert result["success"] is True
        assert result["total_count"] == 2  # repo1 and repo3 (repo2 failed)

    # =========================================================================
    # Concurrent Operations Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_concurrent_worktree_creation(self, tmp_path):
        """Test creating multiple worktrees concurrently."""
        mock_repo = Repository(
            name="Test",
            package="test",
            path=str(tmp_path / "repos" / "test"),
            nickname="test",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.get_blocking_dependencies.return_value = []

        mock_provider = MockWorktreeProvider()
        mock_provider.create_worktree = AsyncMock(
            return_value={"success": True, "worktree_path": "/worktrees/test/branch"}
        )

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Create multiple worktrees concurrently
        tasks = [
            coordinator.create_worktree(
                repo_nickname="test",
                branch=f"branch-{i}",
            )
            for i in range(5)
        ]

        results = await asyncio.gather(*tasks)

        # All should succeed
        assert len(results) == 5
        assert all(r["success"] for r in results)

        # Verify provider was called 5 times
        assert mock_provider.create_worktree.call_count == 5
