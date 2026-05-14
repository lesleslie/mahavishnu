"""Tests for mcp/tools/worktree_tools.py — consolidated worktree MCP tool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.worktree_tools import register_worktree_tools, worktree_manage


@pytest.mark.asyncio
class TestWorktreeManage:
    @pytest.mark.parametrize(
        ("action", "kwargs", "method_name", "method_kwargs"),
        [
            (
                "create",
                {"user_id": "u1", "repo_nickname": "repo", "branch": "main"},
                "create_worktree",
                {
                    "repo_nickname": "repo",
                    "branch": "main",
                    "worktree_name": None,
                    "create_branch": False,
                    "user_id": "u1",
                },
            ),
            (
                "remove",
                {"user_id": "u1", "repo_nickname": "repo", "worktree_path": "/tmp/wt"},
                "remove_worktree",
                {
                    "repo_nickname": "repo",
                    "worktree_path": "/tmp/wt",
                    "force": False,
                    "force_reason": None,
                    "user_id": "u1",
                },
            ),
            (
                "list",
                {"user_id": "u1", "repo_nickname": "repo"},
                "list_worktrees",
                {"repo_nickname": "repo"},
            ),
            (
                "prune",
                {"user_id": "u1", "repo_nickname": "repo"},
                "prune_worktrees",
                ("repo",),
            ),
            (
                "safety_status",
                {"user_id": "u1", "repo_nickname": "repo", "worktree_path": "/tmp/wt"},
                "get_worktree_safety_status",
                {"repo_nickname": "repo", "worktree_path": "/tmp/wt"},
            ),
            (
                "provider_health",
                {"user_id": "u1"},
                "get_provider_health",
                (),
            ),
        ],
    )
    async def test_manage_delegates(self, action, kwargs, method_name, method_kwargs):
        coord = MagicMock()
        method = AsyncMock(return_value={"success": True, "action": action})
        setattr(coord, method_name, method)

        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=coord,
        ):
            result = await worktree_manage(action=action, **kwargs)

        assert result["success"] is True
        if isinstance(method_kwargs, tuple):
            method.assert_called_once_with(*method_kwargs)
        else:
            method.assert_called_once_with(**method_kwargs)

    async def test_manage_missing_coordinator(self):
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=None,
        ):
            result = await worktree_manage(
                action="create",
                user_id="u1",
                repo_nickname="repo",
                branch="main",
            )

        assert result["success"] is False
        assert result["action"] == "create"

    async def test_manage_invalid_action(self):
        coord = MagicMock()
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=coord,
        ):
            result = await worktree_manage(action="bogus", user_id="u1")

        assert result["success"] is False
        assert result["action"] == "bogus"
        assert "supported_actions" in result

    async def test_manage_missing_required_fields(self):
        coord = MagicMock()
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=coord,
        ):
            result = await worktree_manage(action="remove", user_id="u1")

        assert result["success"] is False
        assert result["missing_fields"] == ["repo_nickname", "worktree_path"]


class TestRegistration:
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

        register_worktree_tools(fake_mcp)

        assert fake_mcp.registered == ["worktree_manage"]
