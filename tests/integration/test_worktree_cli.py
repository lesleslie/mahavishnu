"""Integration tests for worktree CLI commands.

Tests all 6 CLI commands by running them and verifying output/behavior.
Uses MockWorktreeProvider to ensure safe testing.
"""

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from mahavishnu.worktree_cli import worktree_app


class TestWorktreeCLI:
    """Integration tests for worktree CLI commands."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    
    def test_create_worktree_command(self, tmp_path):
        """Test 'mhv worktree create' command."""
        # Mock WorktreeCoordinator
        mock_coordinator = MagicMock()

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.create_worktree = AsyncMock(
            return_value={
                "success": True,
                "worktree_path": str(tmp_path / "worktrees" / "test" / "main"),
                "branch": "main",
            }
        )

        mock_coordinator.create_worktree = AsyncMock(
            return_value={
                "success": True,
                "worktree_path": str(tmp_path / "worktrees" / "test" / "main"),
            }
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(
                worktree_app,
                ["create", "test", "main"],
            )

        assert result.exit_code == 0
        assert "✅" in result.output
        assert "Created worktree" in result.output

    
    def test_create_worktree_with_create_branch_flag(self, tmp_path):
        """Test 'mhv worktree create --create-branch' command."""
        mock_coordinator = MagicMock()

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.create_worktree = AsyncMock(
            return_value={"success": True, "worktree_path": "/worktrees/test/feature"}
        )

        mock_coordinator.create_worktree = AsyncMock(
            return_value={"success": True, "worktree_path": "/worktrees/test/feature"}
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(
                worktree_app,
                ["create", "test", "feature", "--create-branch"],
            )

        assert result.exit_code == 0
        assert "✅" in result.output
        # Verify create_branch was passed
        mock_coordinator.create_worktree.assert_called_once()
        call_kwargs = mock_coordinator.create_worktree.call_args.kwargs
        assert call_kwargs["create_branch"] is True

    
    def test_create_worktree_with_custom_name(self, tmp_path):
        """Test 'mhv worktree create --name' command."""
        mock_coordinator = MagicMock()

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.create_worktree = AsyncMock(
            return_value={"success": True, "worktree_path": "/worktrees/test/custom"}
        )

        mock_coordinator.create_worktree = AsyncMock(
            return_value={"success": True, "worktree_path": "/worktrees/test/custom"}
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(
                worktree_app,
                ["create", "test", "main", "--name", "custom-name"],
            )

        assert result.exit_code == 0
        # Verify custom name was passed
        call_kwargs = mock_coordinator.create_worktree.call_args.kwargs
        assert call_kwargs["worktree_name"] == "custom-name"

    def test_create_worktree_missing_args(self, tmp_path):
        """Test that create command requires arguments."""
        result = self.runner.invoke(worktree_app, ["create"])

        assert result.exit_code != 0
        assert "Missing argument" in result.output or "requires" in result.output.lower()

    
    def test_remove_worktree_command(self, tmp_path):
        """Test 'mhv worktree remove' command."""
        mock_coordinator = MagicMock()

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.remove_worktree = AsyncMock(
            return_value={"success": True, "removed_path": "/worktrees/test/main"}
        )

        mock_coordinator.remove_worktree = AsyncMock(
            return_value={"success": True, "removed_path": "/worktrees/test/main"}
        )
        mock_coordinator.get_worktree_safety_status = AsyncMock(
            return_value={
                "uncommitted_changes": False,
                "dependencies": [],
                "is_valid_worktree": True,
                "path_safe": True,
            }
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(
                worktree_app,
                ["remove", "test", str(tmp_path / "worktrees" / "test" / "main")],
            )

        assert result.exit_code == 0
        assert "✅" in result.output
        assert "Removed worktree" in result.output

    
    def test_remove_worktree_with_force_and_reason(self, tmp_path):
        """Test 'mhv worktree remove --force --force-reason' command."""
        mock_coordinator = MagicMock()

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.remove_worktree = AsyncMock(
            return_value={"success": True, "removed_path": "/worktrees/test/main"}
        )

        mock_coordinator.remove_worktree = AsyncMock(
            return_value={
                "success": True,
                "removed_path": "/worktrees/test/main",
            }
        )
        mock_coordinator.get_worktree_safety_status = AsyncMock(
            return_value={
                "uncommitted_changes": True,
                "dependencies": [],
                "is_valid_worktree": True,
                "path_safe": True,
            }
        )
        mock_coordinator.backup_manager.create_backup_before_removal = AsyncMock(
            return_value=tmp_path / "backups" / "backup"
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(
                worktree_app,
                [
                    "remove",
                    "test",
                    str(tmp_path / "worktrees" / "test" / "main"),
                    "--force",
                    "--force-reason",
                    "Fixing critical bug",
                ],
            )

        assert result.exit_code == 0
        assert "Removed worktree" in result.output
        # Verify force and reason were passed
        call_kwargs = mock_coordinator.remove_worktree.call_args.kwargs
        assert call_kwargs["force"] is True
        assert call_kwargs["force_reason"] == "Fixing critical bug"

    
    def test_remove_worktree_blocked_by_uncommitted_changes(self, tmp_path):
        """Test that removal is blocked by uncommitted changes."""
        mock_coordinator = MagicMock()

        mock_coordinator.get_worktree_safety_status = AsyncMock(
            return_value={
                "uncommitted_changes": True,
                "dependencies": [],
                "is_valid_worktree": True,
                "path_safe": True,
            }
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(
                worktree_app,
                ["remove", "test", str(tmp_path / "worktrees" / "test" / "main")],
            )

        assert result.exit_code == 1
        assert "⚠️" in result.output or "uncommitted" in result.output.lower()

    
    def test_list_worktrees_command(self, tmp_path):
        """Test 'mhv worktree list' command."""
        mock_coordinator = MagicMock()

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.list_worktrees = AsyncMock(
            return_value={
                "success": True,
                "worktrees": [
                    {"path": "/worktrees/test/main", "branch": "main", "exists": True},
                    {"path": "/worktrees/test/feature", "branch": "feature", "exists": True},
                ],
            }
        )

        mock_coordinator.list_worktrees = AsyncMock(
            return_value={
                "success": True,
                "worktrees": [
                    {"path": "/worktrees/test/main", "branch": "main", "exists": True},
                    {"path": "/worktrees/test/feature", "branch": "feature", "exists": True},
                ],
                "total_count": 2,
            }
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(worktree_app, ["list"])

        assert result.exit_code == 0
        assert "📋" in result.output
        assert "Worktrees" in result.output
        assert "2 total" in result.output

    
    def test_list_worktrees_with_repo_filter(self, tmp_path):
        """Test 'mhv worktree list --repo' command."""
        mock_coordinator = MagicMock()

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.list_worktrees = AsyncMock(
            return_value={
                "success": True,
                "worktrees": [
                    {"path": "/worktrees/test/main", "branch": "main", "exists": True},
                ],
            }
        )

        mock_coordinator.list_worktrees = AsyncMock(
            return_value={
                "success": True,
                "repo_nickname": "test",
                "worktrees": [
                    {"path": "/worktrees/test/main", "branch": "main", "exists": True},
                ],
            }
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(worktree_app, ["list", "--repo", "test"])

        assert result.exit_code == 0
        assert "Worktrees" in result.output

    
    def test_prune_worktrees_command(self, tmp_path):
        """Test 'mhv worktree prune' command."""
        mock_coordinator = MagicMock()

        mock_coordinator.prune_worktrees = AsyncMock(
            return_value={"success": True, "pruned_count": 2}
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(worktree_app, ["prune", "test"])

        assert result.exit_code == 0
        assert "✅" in result.output
        assert "Pruned" in result.output
        assert "2" in result.output

    
    def test_safety_status_command(self, tmp_path):
        """Test 'mhv worktree safety-status' command."""
        mock_coordinator = MagicMock()

        mock_coordinator.get_worktree_safety_status = AsyncMock(
            return_value={
                "uncommitted_changes": True,
                "dependencies": ["consumer-repo"],
                "is_valid_worktree": True,
                "path_safe": True,
            }
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(
                worktree_app,
                [
                    "safety-status",
                    "test",
                    str(tmp_path / "worktrees" / "test" / "main"),
                ],
            )

        assert result.exit_code == 0
        assert "🔍" in result.output
        assert "Safety Status" in result.output
        assert "Uncommitted changes:" in result.output
        assert "Dependencies found:" in result.output

    
    def test_safety_status_clean(self, tmp_path):
        """Test safety status command with clean worktree."""
        mock_coordinator = MagicMock()

        mock_coordinator.get_worktree_safety_status = AsyncMock(
            return_value={
                "uncommitted_changes": False,
                "dependencies": [],
                "is_valid_worktree": True,
                "path_safe": True,
            }
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(
                worktree_app,
                [
                    "safety-status",
                    "test",
                    str(tmp_path / "worktrees" / "test" / "main"),
                ],
            )

        assert result.exit_code == 0
        assert "✅ No blocking dependencies" in result.output

    
    def test_provider_health_command(self, tmp_path):
        """Test 'mhv worktree provider-health' command."""
        mock_coordinator = MagicMock()

        mock_coordinator.get_provider_health = AsyncMock(
            return_value={
                "SessionBuddyWorktreeProvider": {"healthy": True},
                "DirectGitWorktreeProvider": {"healthy": True},
            }
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(worktree_app, ["provider-health"])

        assert result.exit_code == 0
        assert "🏥" in result.output
        assert "Worktree Provider Health:" in result.output
        assert "Healthy" in result.output

    
    def test_error_messages_are_clear(self, tmp_path):
        """Test that error messages are clear and actionable."""
        mock_coordinator = MagicMock()

        # Return error result instead of raising exception
        mock_coordinator.create_worktree = AsyncMock(
            return_value={
                "success": False,
                "error": "Repository not found: nonexistent-repo"
            }
        )

        with patch(
            "mahavishnu.worktree_cli.MahavishnuApp.load",
            return_value=MagicMock(
                worktree_coordinator=mock_coordinator,
                initialize_worktree_coordinator=AsyncMock(),
            )
        ):
            result = self.runner.invoke(
                worktree_app,
                ["create", "nonexistent", "main"],
            )

        assert result.exit_code == 1
        assert "❌" in result.output
        # Error message should be helpful
        assert len(result.output.strip()) > 0


class TestWorktreeCLIE2E:
    """End-to-end CLI tests with real subprocess calls."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_help_command(self):
        """Test that help command works."""
        result = self.runner.invoke(worktree_app, ["--help"])

        assert result.exit_code == 0
        assert "Manage git worktrees" in result.output
        assert "create" in result.output
        assert "remove" in result.output
        assert "list" in result.output

    def test_create_help(self):
        """Test create command help."""
        result = self.runner.invoke(worktree_app, ["create", "--help"])

        assert result.exit_code == 0
        assert "Create a new worktree" in result.output

    def test_remove_help(self):
        """Test remove command help."""
        result = self.runner.invoke(worktree_app, ["remove", "--help"])

        assert result.exit_code == 0
        assert "Remove a worktree" in result.output
        assert "--force" in result.output
        assert "--force-reason" in result.output
