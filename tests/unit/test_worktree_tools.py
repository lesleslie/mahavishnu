"""Tests for mcp/tools/worktree_tools.py — deprecated worktree MCP tools.

Tests cover the deprecation warning and tool behavior with/without coordinator.
"""

import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Suppress the import-time deprecation warning for test collection
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from mahavishnu.mcp.tools.worktree_tools import (
        create_ecosystem_worktree,
        get_worktree_provider_health,
        get_worktree_safety_status,
        list_ecosystem_worktrees,
        prune_ecosystem_worktrees,
        remove_ecosystem_worktree,
    )


# ---------------------------------------------------------------------------
# _get_coordinator returns None (no coordinator initialized)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestToolsWithoutCoordinator:
    async def test_create_returns_error(self):
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=None,
        ):
            result = await create_ecosystem_worktree(
                user_id="u1", repo_nickname="repo", branch="main",
            )
            assert result["success"] is False
            assert "not initialized" in result["error"].lower()

    async def test_remove_returns_error(self):
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=None,
        ):
            result = await remove_ecosystem_worktree(
                user_id="u1", repo_nickname="repo", worktree_path="/tmp/wt",
            )
            assert result["success"] is False

    async def test_list_returns_error(self):
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=None,
        ):
            result = await list_ecosystem_worktrees(user_id="u1")
            assert result["success"] is False

    async def test_prune_returns_error(self):
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=None,
        ):
            result = await prune_ecosystem_worktrees(
                user_id="u1", repo_nickname="repo",
            )
            assert result["success"] is False

    async def test_safety_status_returns_error(self):
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=None,
        ):
            result = await get_worktree_safety_status(
                user_id="u1", repo_nickname="repo", worktree_path="/tmp/wt",
            )
            assert result["success"] is False

    async def test_provider_health_returns_error(self):
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=None,
        ):
            result = await get_worktree_provider_health(user_id="u1")
            assert result["success"] is False


# ---------------------------------------------------------------------------
# With coordinator present — tools delegate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestToolsWithCoordinator:
    async def test_create_delegates(self):
        coord = MagicMock()
        coord.create_worktree = AsyncMock(return_value={"success": True, "path": "/wt"})
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=coord,
        ):
            result = await create_ecosystem_worktree(
                user_id="u1", repo_nickname="repo", branch="feat",
                worktree_name="my-wt", create_branch=True,
            )
            assert result["success"] is True
            coord.create_worktree.assert_called_once_with(
                repo_nickname="repo",
                branch="feat",
                worktree_name="my-wt",
                create_branch=True,
                user_id="u1",
            )

    async def test_remove_delegates(self):
        coord = MagicMock()
        coord.remove_worktree = AsyncMock(return_value={"success": True})
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=coord,
        ):
            result = await remove_ecosystem_worktree(
                user_id="u1", repo_nickname="repo", worktree_path="/wt",
                force=True, force_reason="cleanup",
            )
            assert result["success"] is True
            coord.remove_worktree.assert_called_once_with(
                repo_nickname="repo",
                worktree_path="/wt",
                force=True,
                force_reason="cleanup",
                user_id="u1",
            )

    async def test_list_delegates(self):
        coord = MagicMock()
        coord.list_worktrees = AsyncMock(return_value={"worktrees": []})
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=coord,
        ):
            result = await list_ecosystem_worktrees(
                user_id="u1", repo_nickname="repo",
            )
            coord.list_worktrees.assert_called_once_with(repo_nickname="repo")

    async def test_prune_delegates(self):
        coord = MagicMock()
        coord.prune_worktrees = AsyncMock(return_value={"pruned": 2})
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=coord,
        ):
            result = await prune_ecosystem_worktrees(
                user_id="u1", repo_nickname="repo",
            )
            coord.prune_worktrees.assert_called_once_with("repo")

    async def test_safety_status_delegates(self):
        coord = MagicMock()
        coord.get_worktree_safety_status = AsyncMock(return_value={"safe": True})
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=coord,
        ):
            result = await get_worktree_safety_status(
                user_id="u1", repo_nickname="repo", worktree_path="/wt",
            )
            coord.get_worktree_safety_status.assert_called_once_with(
                repo_nickname="repo",
                worktree_path="/wt",
            )

    async def test_provider_health_delegates(self):
        coord = MagicMock()
        coord.get_provider_health = AsyncMock(return_value={"healthy": True})
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=coord,
        ):
            result = await get_worktree_provider_health(user_id="u1")
            coord.get_provider_health.assert_called_once()


# ---------------------------------------------------------------------------
# Deprecation warning
# ---------------------------------------------------------------------------


class TestDeprecationWarning:
    def test_import_emits_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Re-import to trigger warning
            import importlib
            import mahavishnu.mcp.tools.worktree_tools as wt
            importlib.reload(wt)
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            assert "deprecated" in str(deprecation_warnings[0].message).lower()
