"""Integration tests for the consolidated worktree MCP tool."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.worktree_coordination import WorktreeCoordinator
from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider


def _make_worktree_coordinator(tmp_path: Path) -> WorktreeCoordinator:
    repo_manager = MagicMock()
    coord_manager = MagicMock()
    coordinator = WorktreeCoordinator(
        repo_manager=repo_manager,
        coordination_manager=coord_manager,
        providers=[MockWorktreeProvider()],
        allowed_worktree_roots=[tmp_path / "worktrees"],
    )
    return coordinator


class TestWorktreeMCPTools:
    """Integration tests for the consolidated worktree MCP tool."""

    @pytest.mark.asyncio
    async def test_manage_create_worktree(self, tmp_path):
        app = MahavishnuApp.load()
        app.worktree_coordinator = _make_worktree_coordinator(tmp_path)
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

        mock_repo = MagicMock()
        mock_repo.path = str(tmp_path / "repos" / "test")
        app.worktree_coordinator.repo_manager.get_by_name = MagicMock(return_value=mock_repo)
        app.worktree_coordinator.repo_manager.get_by_package = MagicMock(return_value=None)
        app.worktree_coordinator.coordination_manager.get_blocking_dependencies = MagicMock(
            return_value=[]
        )
        app.worktree_coordinator.path_validator.validate_worktree_path = MagicMock(
            return_value=(True, None)
        )

        with patch("mahavishnu.core.app.MahavishnuApp.load", return_value=app):
            from mahavishnu.mcp.tools.worktree_tools import worktree_manage

            result = await worktree_manage(
                action="create",
                user_id="test-user",
                repo_nickname="test",
                branch="main",
                worktree_name=None,
                create_branch=False,
            )

        assert result["success"] is True
        assert "worktree_path" in result

    @pytest.mark.asyncio
    async def test_manage_remove_worktree(self, tmp_path):
        app = MahavishnuApp.load()
        app.worktree_coordinator = _make_worktree_coordinator(tmp_path)
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
        app.worktree_coordinator.coordination_manager.list_dependencies = MagicMock(return_value=[])
        app.worktree_coordinator.path_validator.validate_worktree_path = MagicMock(
            return_value=(True, None)
        )
        app.worktree_coordinator._check_uncommitted_changes = AsyncMock(return_value=False)
        app.worktree_coordinator._verify_is_worktree = AsyncMock(return_value=True)

        with patch("mahavishnu.core.app.MahavishnuApp.load", return_value=app):
            from mahavishnu.mcp.tools.worktree_tools import worktree_manage

            result = await worktree_manage(
                action="remove",
                user_id="test-user",
                repo_nickname="test",
                worktree_path=str(tmp_path / "worktrees" / "test" / "main"),
                force=False,
            )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_manage_list_worktrees(self, tmp_path):
        app = MahavishnuApp.load()
        app.worktree_coordinator = _make_worktree_coordinator(tmp_path)
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

        with patch("mahavishnu.core.app.MahavishnuApp.load", return_value=app):
            from mahavishnu.mcp.tools.worktree_tools import worktree_manage

            result = await worktree_manage(
                action="list",
                user_id="test-user",
                repo_nickname=None,
            )

        assert result["success"] is True
        assert "worktrees" in result

    @pytest.mark.asyncio
    async def test_manage_prune_worktrees(self, tmp_path):
        app = MahavishnuApp.load()
        app.worktree_coordinator = _make_worktree_coordinator(tmp_path)
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

        with patch("mahavishnu.core.app.MahavishnuApp.load", return_value=app):
            from mahavishnu.mcp.tools.worktree_tools import worktree_manage

            result = await worktree_manage(
                action="prune",
                user_id="test-user",
                repo_nickname="test",
            )

        assert result["success"] is True
        assert result["pruned_count"] >= 0

    @pytest.mark.asyncio
    async def test_manage_safety_status(self, tmp_path):
        app = MahavishnuApp.load()
        app.worktree_coordinator = _make_worktree_coordinator(tmp_path)

        app.worktree_coordinator._check_uncommitted_changes = AsyncMock(return_value=False)
        app.worktree_coordinator._verify_is_worktree = AsyncMock(return_value=True)
        app.worktree_coordinator.path_validator.validate_worktree_path = MagicMock(
            return_value=(True, None)
        )
        app.worktree_coordinator.coordination_manager.list_dependencies = MagicMock(return_value=[])

        with patch("mahavishnu.core.app.MahavishnuApp.load", return_value=app):
            from mahavishnu.mcp.tools.worktree_tools import worktree_manage

            result = await worktree_manage(
                action="safety_status",
                user_id="test-user",
                repo_nickname="test",
                worktree_path=str(tmp_path / "worktrees" / "test" / "main"),
            )

        assert "uncommitted_changes" in result
        assert "dependencies" in result
        assert "is_valid_worktree" in result
        assert "path_safe" in result

    @pytest.mark.asyncio
    async def test_manage_provider_health(self, tmp_path):
        app = MahavishnuApp.load()
        app.worktree_coordinator = _make_worktree_coordinator(tmp_path)

        with patch("mahavishnu.core.app.MahavishnuApp.load", return_value=app):
            from mahavishnu.mcp.tools.worktree_tools import worktree_manage

            result = await worktree_manage(action="provider_health", user_id="test-user")

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_manage_force_removal_with_reason(self, tmp_path):
        app = MahavishnuApp.load()
        app.worktree_coordinator = _make_worktree_coordinator(tmp_path)
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
        app.worktree_coordinator.coordination_manager.list_dependencies = MagicMock(return_value=[])

        app.worktree_coordinator.path_validator.validate_worktree_path = MagicMock(
            return_value=(True, None)
        )
        app.worktree_coordinator._check_uncommitted_changes = AsyncMock(return_value=True)
        app.worktree_coordinator._get_worktree_branch = AsyncMock(return_value="main")
        app.worktree_coordinator._verify_is_worktree = AsyncMock(return_value=True)
        app.worktree_coordinator.backup_manager.create_backup_before_removal = AsyncMock(
            return_value=tmp_path / "backups" / "test_main_20260218_120000"
        )

        with patch("mahavishnu.core.app.MahavishnuApp.load", return_value=app):
            from mahavishnu.mcp.tools.worktree_tools import worktree_manage

            result = await worktree_manage(
                action="remove",
                user_id="test-user",
                repo_nickname="test",
                worktree_path=str(tmp_path / "worktrees" / "test" / "main"),
                force=True,
                force_reason="Fixing critical bug",
            )

        assert result["success"] is True
        app.worktree_coordinator.backup_manager.create_backup_before_removal.assert_called_once()

    @pytest.mark.asyncio
    async def test_manage_force_removal_without_reason_blocked(self, tmp_path):
        app = MahavishnuApp.load()
        app.worktree_coordinator = _make_worktree_coordinator(tmp_path)

        mock_repo = MagicMock()
        mock_repo.path = str(tmp_path / "repos" / "test")
        app.worktree_coordinator.repo_manager.get_by_name = MagicMock(return_value=mock_repo)
        app.worktree_coordinator.repo_manager.get_by_package = MagicMock(return_value=None)
        app.worktree_coordinator.coordination_manager.list_dependencies = MagicMock(return_value=[])

        app.worktree_coordinator.path_validator.validate_worktree_path = MagicMock(
            return_value=(True, None)
        )
        app.worktree_coordinator._check_uncommitted_changes = AsyncMock(return_value=True)
        app.worktree_coordinator._verify_is_worktree = AsyncMock(return_value=True)

        with patch("mahavishnu.core.app.MahavishnuApp.load", return_value=app):
            from mahavishnu.mcp.tools.worktree_tools import worktree_manage

            result = await worktree_manage(
                action="remove",
                user_id="test-user",
                repo_nickname="test",
                worktree_path=str(tmp_path / "worktrees" / "test" / "main"),
                force=True,
                force_reason=None,
            )

        assert result["success"] is False
        assert result["safety_check"] == "force_reason_required"
        assert "--force requires --force-reason" in result["error"]

    def test_register_worktree_tools_registers_manage_tool_only(self):
        class FakeMCP:
            def __init__(self):
                self.registered: list[str] = []

            def tool(self):
                def decorator(func):
                    self.registered.append(func.__name__)
                    return func

                return decorator

        fake_mcp = FakeMCP()

        from mahavishnu.mcp.tools.worktree_tools import register_worktree_tools

        register_worktree_tools(fake_mcp)

        assert fake_mcp.registered == ["worktree_manage"]
