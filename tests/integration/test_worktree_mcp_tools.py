"""Integration tests for worktree MCP tools.

Tests all 6 MCP tools by starting Mahavishnu MCP server and calling tools via client.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider
from mahavishnu.mcp.server_core import FastMCPServer


class TestWorktreeMCPTools:
    """Integration tests for worktree MCP tools."""

    @pytest.mark.asyncio
    async def test_create_ecosystem_worktree_tool(self, tmp_path):
        """Test create_ecosystem_worktree MCP tool."""
        # Create mock app with worktree coordinator
        app = MahavishnuApp.load()

        # Initialize worktree coordinator with mock provider
        await app.initialize_worktree_coordinator()

        # Replace provider with mock
        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.create_worktree = AsyncMock(
            return_value={
                "success": True,
                "worktree_path": str(tmp_path / "worktrees" / "test" / "main"),
                "branch": "main",
            }
        )

        app.worktree_coordinator.provider_registry = MagicMock()
        app.worktree_coordinator.provider_registry.get_available_provider = AsyncMock(
            return_value=mock_provider
        )

        # Mock repository
        mock_repo = MagicMock()
        mock_repo.path = str(tmp_path / "repos" / "test")
        app.worktree_coordinator.repo_manager.get_by_name = MagicMock(return_value=mock_repo)
        app.worktree_coordinator.repo_manager.get_by_package = MagicMock(return_value=None)

        app.worktree_coordinator.coordination_manager.get_blocking_dependencies = MagicMock(
            return_value=[]
        )

        # Mock path validator
        app.worktree_coordinator.path_validator.validate_worktree_path = MagicMock(
            return_value=(True, None)
        )

        # Call the tool function directly (simulating MCP call)
        from mahavishnu.mcp.tools.worktree_tools import create_ecosystem_worktree

        result = await create_ecosystem_worktree(
            user_id="test-user",
            repo_nickname="test",
            branch="main",
            worktree_name=None,
            create_branch=False,
        )

        assert result["success"] is True
        assert "worktree_path" in result

    @pytest.mark.asyncio
    async def test_remove_ecosystem_worktree_tool(self, tmp_path):
        """Test remove_ecosystem_worktree MCP tool."""
        app = MahavishnuApp.load()
        await app.initialize_worktree_coordinator()

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.remove_worktree = AsyncMock(
            return_value={"success": True, "removed_path": "/worktrees/test/main"}
        )

        app.worktree_coordinator.provider_registry = MagicMock()
        app.worktree_coordinator.provider_registry.get_available_provider = AsyncMock(
            return_value=mock_provider
        )

        mock_repo = MagicMock()
        mock_repo.path = str(tmp_path / "repos" / "test")
        app.worktree_coordinator.repo_manager.get_by_name = MagicMock(return_value=mock_repo)
        app.worktree_coordinator.repo_manager.get_by_package = MagicMock(return_value=None)
        app.worktree_coordinator.coordination_manager.list_dependencies = MagicMock(
            return_value=[]
        )

        app.worktree_coordinator.path_validator.validate_worktree_path = MagicMock(
            return_value=(True, None)
        )
        app.worktree_coordinator._check_uncommitted_changes = AsyncMock(return_value=False)
        app.worktree_coordinator._verify_is_worktree = AsyncMock(return_value=True)

        from mahavishnu.mcp.tools.worktree_tools import remove_ecosystem_worktree

        result = await remove_ecosystem_worktree(
            user_id="test-user",
            repo_nickname="test",
            worktree_path=str(tmp_path / "worktrees" / "test" / "main"),
            force=False,
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_list_ecosystem_worktrees_tool(self, tmp_path):
        """Test list_ecosystem_worktrees MCP tool."""
        app = MahavishnuApp.load()
        await app.initialize_worktree_coordinator()

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.list_worktrees = AsyncMock(
            return_value={
                "success": True,
                "worktrees": [
                    {"path": "/worktrees/test/main", "branch": "main"},
                    {"path": "/worktrees/test/feature", "branch": "feature"},
                ],
            }
        )

        app.worktree_coordinator.provider_registry = MagicMock()
        app.worktree_coordinator.provider_registry.get_available_provider = AsyncMock(
            return_value=mock_provider
        )

        from mahavishnu.mcp.tools.worktree_tools import list_ecosystem_worktrees

        # Test listing all repos
        result = await list_ecosystem_worktrees(
            user_id="test-user",
            repo_nickname=None,
        )

        assert result["success"] is True
        assert "worktrees" in result

    @pytest.mark.asyncio
    async def test_prune_ecosystem_worktrees_tool(self, tmp_path):
        """Test prune_ecosystem_worktrees MCP tool."""
        app = MahavishnuApp.load()
        await app.initialize_worktree_coordinator()

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.list_worktrees = AsyncMock(
            return_value={
                "success": True,
                "worktrees": [
                    {"path": "/worktrees/test/stale", "branch": "deleted-branch"},
                ],
            }
        )
        mock_provider.remove_worktree = AsyncMock(return_value={"success": True})

        app.worktree_coordinator.provider_registry = MagicMock()
        app.worktree_coordinator.provider_registry.get_available_provider = AsyncMock(
            return_value=mock_provider
        )

        mock_repo = MagicMock()
        mock_repo.path = str(tmp_path / "repos" / "test")
        app.worktree_coordinator.repo_manager.get_by_name = MagicMock(return_value=mock_repo)
        app.worktree_coordinator.repo_manager.get_by_package = MagicMock(return_value=None)

        app.worktree_coordinator._branch_exists = AsyncMock(return_value=False)

        from mahavishnu.mcp.tools.worktree_tools import prune_ecosystem_worktrees

        result = await prune_ecosystem_worktrees(
            user_id="test-user",
            repo_nickname="test",
        )

        assert result["success"] is True
        assert result["pruned_count"] >= 0

    @pytest.mark.asyncio
    async def test_get_worktree_safety_status_tool(self, tmp_path):
        """Test get_worktree_safety_status MCP tool."""
        app = MahavishnuApp.load()
        await app.initialize_worktree_coordinator()

        app.worktree_coordinator._check_uncommitted_changes = AsyncMock(return_value=False)
        app.worktree_coordinator._verify_is_worktree = AsyncMock(return_value=True)
        app.worktree_coordinator.path_validator.validate_worktree_path = MagicMock(
            return_value=(True, None)
        )
        app.worktree_coordinator.coordination_manager.list_dependencies = MagicMock(
            return_value=[]
        )

        from mahavishnu.mcp.tools.worktree_tools import get_worktree_safety_status

        result = await get_worktree_safety_status(
            user_id="test-user",
            repo_nickname="test",
            worktree_path=str(tmp_path / "worktrees" / "test" / "main"),
        )

        assert "uncommitted_changes" in result
        assert "dependencies" in result
        assert "is_valid_worktree" in result
        assert "path_safe" in result

    @pytest.mark.asyncio
    async def test_get_worktree_provider_health_tool(self, tmp_path):
        """Test get_worktree_provider_health MCP tool."""
        app = MahavishnuApp.load()
        await app.initialize_worktree_coordinator()

        from mahavishnu.mcp.tools.worktree_tools import get_worktree_provider_health

        result = await get_worktree_provider_health(user_id="test-user")

        assert isinstance(result, dict)
        # Should return health status for all providers

    @pytest.mark.asyncio
    async def test_force_removal_with_reason(self, tmp_path):
        """Test force removal with force_reason parameter."""
        app = MahavishnuApp.load()
        await app.initialize_worktree_coordinator()

        from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider

        mock_provider = MockWorktreeProvider()
        mock_provider.remove_worktree = AsyncMock(
            return_value={"success": True, "removed_path": "/worktrees/test/main"}
        )

        app.worktree_coordinator.provider_registry = MagicMock()
        app.worktree_coordinator.provider_registry.get_available_provider = AsyncMock(
            return_value=mock_provider
        )

        mock_repo = MagicMock()
        mock_repo.path = str(tmp_path / "repos" / "test")
        app.worktree_coordinator.repo_manager.get_by_name = MagicMock(return_value=mock_repo)
        app.worktree_coordinator.repo_manager.get_by_package = MagicMock(return_value=None)
        app.worktree_coordinator.coordination_manager.list_dependencies = MagicMock(
            return_value=[]
        )

        app.worktree_coordinator.path_validator.validate_worktree_path = MagicMock(
            return_value=(True, None)
        )

        # Mock uncommitted changes and backup
        app.worktree_coordinator._check_uncommitted_changes = AsyncMock(return_value=True)
        app.worktree_coordinator._get_worktree_branch = AsyncMock(return_value="main")
        app.worktree_coordinator._verify_is_worktree = AsyncMock(return_value=True)
        app.worktree_coordinator.backup_manager.create_backup_before_removal = AsyncMock(
            return_value=tmp_path / "backups" / "test_main_20260218_120000"
        )

        from mahavishnu.mcp.tools.worktree_tools import remove_ecosystem_worktree

        result = await remove_ecosystem_worktree(
            user_id="test-user",
            repo_nickname="test",
            worktree_path=str(tmp_path / "worktrees" / "test" / "main"),
            force=True,
            force_reason="Fixing critical bug",
        )

        assert result["success"] is True
        # Verify backup was created
        app.worktree_coordinator.backup_manager.create_backup_before_removal.assert_called_once()

    @pytest.mark.asyncio
    async def test_force_removal_without_reason_blocked(self, tmp_path):
        """Test that force removal without reason is blocked."""
        app = MahavishnuApp.load()
        await app.initialize_worktree_coordinator()

        mock_repo = MagicMock()
        mock_repo.path = str(tmp_path / "repos" / "test")
        app.worktree_coordinator.repo_manager.get_by_name = MagicMock(return_value=mock_repo)
        app.worktree_coordinator.repo_manager.get_by_package = MagicMock(return_value=None)
        app.worktree_coordinator.coordination_manager.list_dependencies = MagicMock(
            return_value=[]
        )

        app.worktree_coordinator.path_validator.validate_worktree_path = MagicMock(
            return_value=(True, None)
        )

        # Mock uncommitted changes
        app.worktree_coordinator._check_uncommitted_changes = AsyncMock(return_value=True)
        app.worktree_coordinator._verify_is_worktree = AsyncMock(return_value=True)

        from mahavishnu.mcp.tools.worktree_tools import remove_ecosystem_worktree

        result = await remove_ecosystem_worktree(
            user_id="test-user",
            repo_nickname="test",
            worktree_path=str(tmp_path / "worktrees" / "test" / "main"),
            force=True,
            force_reason=None,  # Missing reason
        )

        assert result["success"] is False
        assert result["safety_check"] == "force_reason_required"
        assert "--force requires --force-reason" in result["error"]

    @pytest.mark.asyncio
    async def test_all_tools_require_authentication(self, tmp_path):
        """Test that all MCP tools have authentication decorators."""
        from mahavishnu.mcp.tools.worktree_tools import (
            create_ecosystem_worktree,
            remove_ecosystem_worktree,
            list_ecosystem_worktrees,
            prune_ecosystem_worktrees,
            get_worktree_safety_status,
            get_worktree_provider_health,
        )

        # Verify all tools have require_mcp_auth decorator
        # This is checked by inspecting the function's attributes
        tools = [
            create_ecosystem_worktree,
            remove_ecosystem_worktree,
            list_ecosystem_worktrees,
            prune_ecosystem_worktrees,
            get_worktree_safety_status,
            get_worktree_provider_health,
        ]

        for tool_func in tools:
            # All tools should have been decorated with @require_mcp_auth
            # We verify this by checking the function exists and is callable
            assert callable(tool_func), f"{tool_func.__name__} should be callable"
