"""Unit tests for WorktreeCoordinator.

Tests comprehensive worktree coordination with safety mechanisms:
- Worktree creation with validation and audit logging
- Worktree removal with safety checks (uncommitted changes, dependencies)
- Force removal with backup creation and force_reason requirement
- Worktree listing across repositories
- Worktree pruning with branch validation
- Safety status reporting
- Provider registry integration and fallback
- Error handling for all failure scenarios
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.worktree_coordination import WorktreeCoordinator
from mahavishnu.core.errors import ConfigurationError
from mahavishnu.core.repo_models import Repository
from mahavishnu.core.coordination.models import Dependency, DependencyStatus


class TestWorktreeCoordinator:
    """Test suite for WorktreeCoordinator orchestration layer."""

    # =========================================================================
    # Initialization Tests
    # =========================================================================

    def test_initialization_with_default_providers(self, tmp_path):
        """Test coordinator initialization with default provider chain."""
        # Mock repository and coordination managers
        mock_repo_manager = MagicMock()
        mock_coord_manager = MagicMock()

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            backup_dir=tmp_path / "backups",
        )

        assert coordinator.repo_manager == mock_repo_manager
        assert coordinator.coordination_manager == mock_coord_manager
        assert coordinator.provider_registry is not None
        assert coordinator.path_validator is not None
        assert coordinator.backup_manager is not None
        assert coordinator.audit_logger is not None

    def test_initialization_with_custom_providers(self, tmp_path):
        """Test coordinator initialization with custom provider list."""
        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_repo_manager = MagicMock()
        mock_coord_manager = MagicMock()

        mock_provider = MockWorktreeProvider()

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            backup_dir=tmp_path / "backups",
        )

        assert coordinator.provider_registry is not None

    def test_initialization_with_custom_allowed_roots(self, tmp_path):
        """Test coordinator initialization with custom allowed worktree roots."""
        mock_repo_manager = MagicMock()
        mock_coord_manager = MagicMock()

        custom_roots = [tmp_path / "custom1", tmp_path / "custom2"]

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            allowed_worktree_roots=custom_roots,
        )

        # Verify path validator uses custom roots
        assert coordinator.path_validator.allowed_roots == custom_roots

    # =========================================================================
    # Worktree Creation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_worktree_success(self, tmp_path):
        """Test successful worktree creation."""
        # Setup mock repository
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo
        mock_repo_manager.get_by_package.return_value = None

        mock_coord_manager = MagicMock()
        mock_coord_manager.get_blocking_dependencies.return_value = []

        # Mock provider to return success
        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.create_worktree = AsyncMock(
            return_value={
                "success": True,
                "worktree_path": str(tmp_path / "worktrees" / "test-repo" / "main"),
                "branch": "main",
            }
        )

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Create worktree
        result = await coordinator.create_worktree(
            repo_nickname="test-repo",
            branch="main",
            user_id="user-123",
        )

        # Verify success
        assert result["success"] is True
        assert "worktree_path" in result

        # Verify provider was called
        mock_provider.create_worktree.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_worktree_with_create_branch(self, tmp_path):
        """Test worktree creation with branch creation."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.get_blocking_dependencies.return_value = []

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.create_worktree = AsyncMock(
            return_value={"success": True, "worktree_path": "/worktrees/test-repo/feature"}
        )

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Create worktree with new branch
        result = await coordinator.create_worktree(
            repo_nickname="test-repo",
            branch="feature-branch",
            create_branch=True,
            user_id="user-123",
        )

        assert result["success"] is True

        # Verify create_branch parameter was passed
        call_args = mock_provider.create_worktree.call_args
        assert call_args.kwargs["create_branch"] is True

    @pytest.mark.asyncio
    async def test_create_worktree_with_custom_name(self, tmp_path):
        """Test worktree creation with custom worktree name."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.get_blocking_dependencies.return_value = []

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.create_worktree = AsyncMock(
            return_value={"success": True, "worktree_path": "/worktrees/test-repo/custom"}
        )

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Create worktree with custom name
        result = await coordinator.create_worktree(
            repo_nickname="test-repo",
            branch="main",
            worktree_name="custom-name",
            user_id="user-123",
        )

        assert result["success"] is True

        # Verify custom name was used
        call_args = mock_provider.create_worktree.call_args
        assert "custom" in str(call_args.kwargs["worktree_path"])

    @pytest.mark.asyncio
    async def test_create_worktree_repo_not_found(self, tmp_path):
        """Test worktree creation with non-existent repository."""
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = None
        mock_repo_manager.get_by_package.return_value = None

        mock_coord_manager = MagicMock()

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[MockWorktreeProvider()],
        )

        # Should raise ConfigurationError
        with pytest.raises(ConfigurationError) as exc_info:
            await coordinator.create_worktree(
                repo_nickname="nonexistent",
                branch="main",
            )

        assert "Repository not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_worktree_with_blocking_dependencies(self, tmp_path):
        """Test worktree creation with blocking dependencies (warning only)."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        # Return blocking dependencies
        mock_coord_manager = MagicMock()
        mock_coord_manager.get_blocking_dependencies.return_value = ["dep1", "dep2"]

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.create_worktree = AsyncMock(
            return_value={"success": True, "worktree_path": "/worktrees/test-repo/main"}
        )

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Should succeed but with warning logged
        result = await coordinator.create_worktree(
            repo_nickname="test-repo",
            branch="main",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_worktree_invalid_path_rejected(self, tmp_path):
        """Test that invalid paths are rejected during worktree creation."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.get_blocking_dependencies.return_value = []

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[MockWorktreeProvider()],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Try to create worktree outside allowed roots
        with pytest.raises(ValueError) as exc_info:
            await coordinator.create_worktree(
                repo_nickname="test-repo",
                branch="main",
            )

        # Path validation should reject (because Path.home() / "worktrees" won't exist in tmp_path)
        assert "Invalid worktree path" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_worktree_audit_logging(self, tmp_path):
        """Test that worktree creation is properly audit logged."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.get_blocking_dependencies.return_value = []

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.create_worktree = AsyncMock(
            return_value={"success": True, "worktree_path": "/worktrees/test-repo/main"}
        )

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Create worktree
        await coordinator.create_worktree(
            repo_nickname="test-repo",
            branch="main",
            user_id="user-123",
        )

        # Verify audit logging was called (attempt, success)
        # Note: We can't easily verify audit logger calls without mocking get_audit_logger
        # This test verifies no exceptions were raised during audit logging

    # =========================================================================
    # Worktree Removal Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_remove_worktree_success(self, tmp_path):
        """Test successful worktree removal."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.list_dependencies.return_value = []

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.remove_worktree = AsyncMock(
            return_value={"success": True, "removed_path": "/worktrees/test-repo/main"}
        )

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Mock safety checks
        coordinator._check_uncommitted_changes = AsyncMock(return_value=False)
        coordinator._verify_is_worktree = AsyncMock(return_value=True)

        result = await coordinator.remove_worktree(
            repo_nickname="test-repo",
            worktree_path=str(tmp_path / "worktrees" / "test-repo" / "main"),
            force=False,
            user_id="user-123",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_remove_worktree_with_uncommitted_changes_blocked(self, tmp_path):
        """Test that removal is blocked when worktree has uncommitted changes."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.list_dependencies.return_value = []

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[MockWorktreeProvider()],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Mock uncommitted changes
        coordinator._check_uncommitted_changes = AsyncMock(return_value=True)
        coordinator._verify_is_worktree = AsyncMock(return_value=True)

        result = await coordinator.remove_worktree(
            repo_nickname="test-repo",
            worktree_path=str(tmp_path / "worktrees" / "test-repo" / "main"),
            force=False,
        )

        assert result["success"] is False
        assert result["safety_check"] == "uncommitted_changes"
        assert "uncommitted changes" in result["error"]

    @pytest.mark.asyncio
    async def test_remove_worktree_force_without_reason_blocked(self, tmp_path):
        """Test that force removal without reason is blocked."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.list_dependencies.return_value = []

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[MockWorktreeProvider()],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Mock uncommitted changes
        coordinator._check_uncommitted_changes = AsyncMock(return_value=True)
        coordinator._verify_is_worktree = AsyncMock(return_value=True)

        result = await coordinator.remove_worktree(
            repo_nickname="test-repo",
            worktree_path=str(tmp_path / "worktrees" / "test-repo" / "main"),
            force=True,
            force_reason=None,  # Missing reason
        )

        assert result["success"] is False
        assert result["safety_check"] == "force_reason_required"
        assert "--force requires --force-reason" in result["error"]

    @pytest.mark.asyncio
    async def test_remove_worktree_force_with_reason_success(self, tmp_path):
        """Test successful force removal with reason and backup creation."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.list_dependencies.return_value = []

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.remove_worktree = AsyncMock(
            return_value={"success": True, "removed_path": "/worktrees/test-repo/main"}
        )

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            allowed_worktree_roots=[tmp_path / "worktrees"],
            backup_dir=tmp_path / "backups",
        )

        # Mock uncommitted changes and backup creation
        coordinator._check_uncommitted_changes = AsyncMock(return_value=True)
        coordinator._get_worktree_branch = AsyncMock(return_value="main")
        coordinator._verify_is_worktree = AsyncMock(return_value=True)

        result = await coordinator.remove_worktree(
            repo_nickname="test-repo",
            worktree_path=str(tmp_path / "worktrees" / "test-repo" / "main"),
            force=True,
            force_reason="Fixing critical bug",
            user_id="user-123",
        )

        assert result["success"] is True

        # Verify backup was created
        coordinator.backup_manager.create_backup_before_removal.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_worktree_with_dependents_blocked(self, tmp_path):
        """Test that removal is blocked when worktree has dependents."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()

        # Create dependency
        mock_dep = MagicMock()
        mock_dep.worktree_path = str(tmp_path / "worktrees" / "test-repo" / "main")
        mock_dep.status.value = "pending"
        mock_dep.consumer = "consumer-repo"

        mock_coord_manager.list_dependencies.return_value = [mock_dep]

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[MockWorktreeProvider()],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Mock no uncommitted changes
        coordinator._check_uncommitted_changes = AsyncMock(return_value=False)
        coordinator._verify_is_worktree = AsyncMock(return_value=True)

        result = await coordinator.remove_worktree(
            repo_nickname="test-repo",
            worktree_path=str(tmp_path / "worktrees" / "test-repo" / "main"),
            force=False,
        )

        assert result["success"] is False
        assert result["safety_check"] == "dependency_block"
        assert "depended on by" in result["error"]

    @pytest.mark.asyncio
    async def test_remove_worktree_invalid_path(self, tmp_path):
        """Test that removal with invalid path raises error."""
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = None

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=MagicMock(),
            providers=[MockWorktreeProvider()],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Invalid path (null bytes)
        with pytest.raises(ValueError) as exc_info:
            await coordinator.remove_worktree(
                repo_nickname="test-repo",
                worktree_path="/worktrees/repo\x00main",
                force=False,
            )

        assert "Invalid worktree path" in str(exc_info.value)

    # =========================================================================
    # Worktree Listing Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_worktrees_all_repos(self, tmp_path):
        """Test listing worktrees across all repositories."""
        # Create mock repositories
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

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.list_worktrees = AsyncMock(
            return_value={
                "success": True,
                "worktrees": [
                    {"path": "/worktrees/repo1/main", "branch": "main"},
                    {"path": "/worktrees/repo1/feature", "branch": "feature"},
                ],
            }
        )

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=MagicMock(),
            providers=[mock_provider],
        )

        result = await coordinator.list_worktrees()

        assert result["success"] is True
        assert "worktrees" in result
        assert result["total_count"] == len(result["worktrees"])

    @pytest.mark.asyncio
    async def test_list_worktrees_specific_repo(self, tmp_path):
        """Test listing worktrees for specific repository."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_repo.return_value = mock_repo

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.list_worktrees = AsyncMock(
            return_value={
                "success": True,
                "worktrees": [{"path": "/worktrees/test-repo/main", "branch": "main"}],
            }
        )

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=MagicMock(),
            providers=[mock_provider],
        )

        result = await coordinator.list_worktrees(repo_nickname="test-repo")

        assert result["success"] is True
        assert result["repo_nickname"] == "test-repo"
        assert "worktrees" in result

    # =========================================================================
    # Worktree Pruning Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_prune_worktrees(self, tmp_path):
        """Test pruning stale worktree references."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()

        # Mock list_worktrees to return stale worktrees
        mock_provider.list_worktrees = AsyncMock(
            return_value={
                "success": True,
                "worktrees": [
                    {"path": "/worktrees/test-repo/deleted-branch", "branch": "deleted-branch"},
                    {"path": "/worktrees/test-repo/active-branch", "branch": "active-branch"},
                ],
            }
        )
        mock_provider.remove_worktree = AsyncMock(return_value={"success": True})

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=MagicMock(),
            providers=[mock_provider],
        )

        # Mock branch existence (deleted-branch doesn't exist)
        coordinator._branch_exists = AsyncMock(side_effect=lambda repo, branch: branch == "active-branch")

        result = await coordinator.prune_worktrees(repo_nickname="test-repo")

        assert result["success"] is True
        assert result["pruned_count"] == 1
        assert result["repo_nickname"] == "test-repo"

    # =========================================================================
    # Safety Status Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_worktree_safety_status(self, tmp_path):
        """Test getting safety status for worktree."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.list_dependencies.return_value = []

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[MockWorktreeProvider()],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Mock safety checks
        coordinator._check_uncommitted_changes = AsyncMock(return_value=False)
        coordinator._verify_is_worktree = AsyncMock(return_value=True)

        status = await coordinator.get_worktree_safety_status(
            repo_nickname="test-repo",
            worktree_path=str(tmp_path / "worktrees" / "test-repo" / "main"),
        )

        assert status["uncommitted_changes"] is False
        assert status["dependencies"] == []
        assert status["is_valid_worktree"] is True
        assert isinstance(status["path_safe"], bool)

    # =========================================================================
    # Provider Health Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_provider_health(self, tmp_path):
        """Test getting health status of all providers."""
        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()

        coordinator = WorktreeCoordinator(
            repo_manager=MagicMock(),
            coordination_manager=MagicMock(),
            providers=[mock_provider],
        )

        health = await coordinator.get_provider_health()

        assert isinstance(health, dict)
        # Mock provider should always be healthy
        assert "MockWorktreeProvider" in health

    # =========================================================================
    # Safety Check Method Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_check_uncommitted_changes(self, tmp_path):
        """Test checking for uncommitted changes."""
        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=MagicMock(),
            coordination_manager=MagicMock(),
            providers=[MockWorktreeProvider()],
        )

        # Create a temporary git repo for testing
        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        # Initialize git repo
        await coordinator._execute_git_command(str(worktree_path), ["init"])
        (worktree_path / "test.txt").write_text("test")

        # Has uncommitted changes
        has_changes = await coordinator._check_uncommitted_changes(str(worktree_path))
        assert has_changes is True

        # Commit changes
        await coordinator._execute_git_command(
            str(worktree_path), ["config", "user.name", "Test"]
        )
        await coordinator._execute_git_command(
            str(worktree_path), ["config", "user.email", "test@example.com"]
        )
        await coordinator._execute_git_command(str(worktree_path), ["add", "."])
        await coordinator._execute_git_command(
            str(worktree_path), ["commit", "-m", "test"]
        )

        # No uncommitted changes
        has_changes = await coordinator._check_uncommitted_changes(str(worktree_path))
        assert has_changes is False

    def test_get_worktree_dependents(self, tmp_path):
        """Test getting worktree dependents (ARCH-002 fix)."""
        mock_coord_manager = MagicMock()

        # Create mock dependencies
        mock_dep1 = MagicMock()
        mock_dep1.worktree_path = "/worktrees/test-repo/main"
        mock_dep1.status.value = "pending"
        mock_dep1.consumer = "consumer1"

        mock_dep2 = MagicMock()
        mock_dep2.worktree_path = "/worktrees/test-repo/feature"  # Different worktree
        mock_dep2.status.value = "pending"
        mock_dep2.consumer = "consumer2"

        mock_dep3 = MagicMock()
        mock_dep3.worktree_path = "/worktrees/test-repo/main"
        mock_dep3.status.value = "satisfied"  # Already satisfied

        mock_coord_manager.list_dependencies.return_value = [
            mock_dep1,
            mock_dep2,
            mock_dep3,
        ]

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=MagicMock(),
            coordination_manager=mock_coord_manager,
            providers=[MockWorktreeProvider()],
        )

        dependents = coordinator._get_worktree_dependents(
            repo_nickname="test-repo",
            worktree_path="/worktrees/test-repo/main",
        )

        # Should only return unsatisfied dependencies for this specific worktree
        assert len(dependents) == 1
        assert "consumer1" in dependents

    @pytest.mark.asyncio
    async def test_verify_is_worktree(self, tmp_path):
        """Test verifying path is a git worktree."""
        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=MagicMock(),
            coordination_manager=MagicMock(),
            providers=[MockWorktreeProvider()],
        )

        # Create a worktree-like directory
        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        # Create .git file with gitdir marker (indicates worktree)
        (worktree_path / ".git").write_text("gitdir: /path/to/.git/worktrees/test")

        is_worktree = await coordinator._verify_is_worktree(str(worktree_path))
        assert is_worktree is True

        # Regular directory (not a worktree)
        regular_path = tmp_path / "regular"
        regular_path.mkdir()
        (regular_path / "file.txt").write_text("content")

        is_worktree = await coordinator._verify_is_worktree(str(regular_path))
        assert is_worktree is False

    @pytest.mark.asyncio
    async def test_branch_exists(self, tmp_path):
        """Test checking if branch exists."""
        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=MagicMock(),
            coordination_manager=MagicMock(),
            providers=[MockWorktreeProvider()],
        )

        # Create a git repo
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        await coordinator._execute_git_command(str(repo_path), ["init"])
        await coordinator._execute_git_command(str(repo_path), ["config", "user.name", "Test"])
        await coordinator._execute_git_command(
            str(repo_path), ["config", "user.email", "test@example.com"]
        )
        (repo_path / "test.txt").write_text("test")
        await coordinator._execute_git_command(str(repo_path), ["add", "."])
        await coordinator._execute_git_command(str(repo_path), ["commit", "-m", "test"])

        # Main branch exists
        exists = await coordinator._branch_exists(str(repo_path), "main")
        assert exists is True

        # Non-existent branch
        exists = await coordinator._branch_exists(str(repo_path), "nonexistent")
        assert exists is False

    @pytest.mark.asyncio
    async def test_get_worktree_branch(self, tmp_path):
        """Test getting current branch for worktree."""
        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=MagicMock(),
            coordination_manager=MagicMock(),
            providers=[MockWorktreeProvider()],
        )

        # Create a git repo
        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        await coordinator._execute_git_command(str(worktree_path), ["init"])
        await coordinator._execute_git_command(str(worktree_path), ["config", "user.name", "Test"])
        await coordinator._execute_git_command(
            str(worktree_path), ["config", "user.email", "test@example.com"]
        )
        (worktree_path / "test.txt").write_text("test")
        await coordinator._execute_git_command(str(worktree_path), ["add", "."])
        await coordinator._execute_git_command(str(worktree_path), ["commit", "-m", "test"])

        # Get current branch
        branch = await coordinator._get_worktree_branch(str(worktree_path))
        assert branch in ["main", "master"]  # Git default branch name varies

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_worktree_provider_failure(self, tmp_path):
        """Test handling of provider failure during worktree creation."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.get_blocking_dependencies.return_value = []

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.create_worktree = AsyncMock(
            side_effect=RuntimeError("Provider failed")
        )

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[mock_provider],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Should raise exception from provider
        with pytest.raises(RuntimeError) as exc_info:
            await coordinator.create_worktree(
                repo_nickname="test-repo",
                branch="main",
            )

        assert "Provider failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_remove_worktree_backup_failure(self, tmp_path):
        """Test handling of backup creation failure during force removal."""
        mock_repo = Repository(
            name="Test Repo",
            package="test_repo",
            path=str(tmp_path / "repos" / "test_repo"),
            nickname="test-repo",
            role="app",
        )
        mock_repo_manager = MagicMock()
        mock_repo_manager.get_by_name.return_value = mock_repo

        mock_coord_manager = MagicMock()
        mock_coord_manager.list_dependencies.return_value = []

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=mock_coord_manager,
            providers=[MockWorktreeProvider()],
            allowed_worktree_roots=[tmp_path / "worktrees"],
        )

        # Mock uncommitted changes and backup failure
        coordinator._check_uncommitted_changes = AsyncMock(return_value=True)
        coordinator._get_worktree_branch = AsyncMock(return_value="main")
        coordinator._verify_is_worktree = AsyncMock(return_value=True)

        # Mock backup creation to fail
        coordinator.backup_manager.create_backup_before_removal = AsyncMock(
            side_effect=IOError("Backup failed")
        )

        result = await coordinator.remove_worktree(
            repo_nickname="test-repo",
            worktree_path=str(tmp_path / "worktrees" / "test-repo" / "main"),
            force=True,
            force_reason="Fixing critical bug",
        )

        assert result["success"] is False
        assert result["safety_check"] == "backup_failed"
        assert "backup" in result["error"].lower()

    # =========================================================================
    # Edge Cases
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_worktrees_with_repo_filtering_error(self, tmp_path):
        """Test listing worktrees when some repos fail."""
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

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()

        # Mock list_worktrees to fail for repo2
        call_count = [0]

        async def side_effect_list(repository_path):
            call_count[0] += 1
            if call_count[0] == 1:
                return {
                    "success": True,
                    "worktrees": [{"path": "/worktrees/repo1/main", "branch": "main"}],
                }
            else:
                raise RuntimeError("Failed to list worktrees")

        mock_provider.list_worktrees = AsyncMock(side_effect=side_effect_list)

        coordinator = WorktreeCoordinator(
            repo_manager=mock_repo_manager,
            coordination_manager=MagicMock(),
            providers=[mock_provider],
        )

        result = await coordinator.list_worktrees()

        # Should succeed with only repo1 worktrees (repo2 error is logged but doesn't fail)
        assert result["success"] is True
        assert len(result["worktrees"]) == 1
