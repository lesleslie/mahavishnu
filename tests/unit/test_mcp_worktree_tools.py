"""Unit tests for mahavishnu.mcp.tools.worktree_tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.worktree_tools import (
    _ACTION_REQUIRED_FIELDS,
    _SUPPORTED_ACTIONS,
    _check_required_fields,
    _dispatch_worktree_action,
    _get_coordinator,
    _missing_coordinator_payload,
    _missing_fields_payload,
    _unsupported_action_payload,
    register_worktree_tools,
    worktree_manage,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_coordinator():
    """Build a coordinator with AsyncMock methods for every supported action."""
    coord = MagicMock()
    coord.create_worktree = AsyncMock(return_value={"success": True, "action": "create"})
    coord.remove_worktree = AsyncMock(return_value={"success": True, "action": "remove"})
    coord.list_worktrees = AsyncMock(return_value={"success": True, "worktrees": []})
    coord.prune_worktrees = AsyncMock(return_value={"success": True, "pruned": 0})
    coord.get_worktree_safety_status = AsyncMock(return_value={"safe": True})
    coord.get_provider_health = AsyncMock(return_value={"healthy": True})
    return coord


# =============================================================================
# Constants
# =============================================================================


class TestConstants:
    """Tests for the static action metadata."""

    def test_supported_actions(self):
        """Six actions should be supported."""
        assert _SUPPORTED_ACTIONS == (
            "create",
            "remove",
            "list",
            "prune",
            "safety_status",
            "provider_health",
        )

    def test_action_required_fields(self):
        """Required fields mapping should cover all gated actions."""
        assert "create" in _ACTION_REQUIRED_FIELDS
        assert "remove" in _ACTION_REQUIRED_FIELDS
        assert "prune" in _ACTION_REQUIRED_FIELDS
        assert "safety_status" in _ACTION_REQUIRED_FIELDS
        # list and provider_health have no required fields
        assert "list" not in _ACTION_REQUIRED_FIELDS
        assert "provider_health" not in _ACTION_REQUIRED_FIELDS


# =============================================================================
# _check_required_fields
# =============================================================================


class TestCheckRequiredFields:
    """Tests for the _check_required_fields helper."""

    def test_returns_none_when_all_fields_present(self):
        """If all required fields are present, return None."""
        fields = {"repo_nickname": "r", "branch": "main"}
        assert _check_required_fields("create", fields) is None

    def test_returns_error_when_fields_missing(self):
        """If a required field is missing, return an error payload."""
        fields = {"repo_nickname": "r"}  # branch missing
        result = _check_required_fields("create", fields)
        assert result is not None
        assert result["success"] is False
        assert result["action"] == "create"
        assert "branch" in result["missing_fields"]

    def test_no_required_fields_returns_none(self):
        """Unknown actions have empty required list and pass."""
        assert _check_required_fields("not_a_real_action", {}) is None

    def test_list_action_no_required_fields(self):
        """'list' has no required fields and should always pass."""
        assert _check_required_fields("list", {}) is None


# =============================================================================
# Payload helpers
# =============================================================================


class TestPayloadHelpers:
    """Tests for the small payload constructors."""

    def test_missing_coordinator_payload(self):
        """Missing coordinator payload is shaped as expected."""
        payload = _missing_coordinator_payload("create")
        assert payload == {
            "success": False,
            "action": "create",
            "error": "WorktreeCoordinator not initialized",
        }

    def test_missing_fields_payload(self):
        """Missing fields payload reports action and missing list."""
        payload = _missing_fields_payload("create", ["branch"])
        assert payload["success"] is False
        assert payload["action"] == "create"
        assert payload["missing_fields"] == ["branch"]
        assert "Missing required fields" in payload["error"]

    def test_unsupported_action_payload(self):
        """Unsupported action payload reports the supported actions."""
        payload = _unsupported_action_payload("bad")
        assert payload["success"] is False
        assert payload["action"] == "bad"
        assert "Unsupported worktree action" in payload["error"]
        assert payload["supported_actions"] == list(_SUPPORTED_ACTIONS)


# =============================================================================
# _dispatch_worktree_action
# =============================================================================


class TestDispatchWorktreeAction:
    """Tests for the _dispatch_worktree_action helper."""

    async def test_dispatch_create(self, mock_coordinator):
        """create action calls coordinator.create_worktree."""
        fields = {
            "user_id": "u1",
            "repo_nickname": "r1",
            "branch": "main",
            "worktree_name": None,
            "create_branch": False,
        }
        result = await _dispatch_worktree_action(mock_coordinator, "create", fields)
        assert result["action"] == "create"
        mock_coordinator.create_worktree.assert_awaited_once()

    async def test_dispatch_remove(self, mock_coordinator):
        """remove action calls coordinator.remove_worktree."""
        fields = {
            "user_id": "u1",
            "repo_nickname": "r1",
            "worktree_path": "/tmp/wt",
            "force": False,
            "force_reason": None,
        }
        result = await _dispatch_worktree_action(mock_coordinator, "remove", fields)
        mock_coordinator.remove_worktree.assert_awaited_once()
        assert result["action"] == "remove"

    async def test_dispatch_list(self, mock_coordinator):
        """list action calls coordinator.list_worktrees."""
        fields = {"user_id": "u1", "repo_nickname": "r1"}
        await _dispatch_worktree_action(mock_coordinator, "list", fields)
        mock_coordinator.list_worktrees.assert_awaited_once()

    async def test_dispatch_prune(self, mock_coordinator):
        """prune action calls coordinator.prune_worktrees."""
        fields = {"user_id": "u1", "repo_nickname": "r1"}
        await _dispatch_worktree_action(mock_coordinator, "prune", fields)
        mock_coordinator.prune_worktrees.assert_awaited_once_with("r1")

    async def test_dispatch_safety_status(self, mock_coordinator):
        """safety_status action calls coordinator.get_worktree_safety_status."""
        fields = {
            "user_id": "u1",
            "repo_nickname": "r1",
            "worktree_path": "/tmp/wt",
        }
        await _dispatch_worktree_action(mock_coordinator, "safety_status", fields)
        mock_coordinator.get_worktree_safety_status.assert_awaited_once()

    async def test_dispatch_provider_health(self, mock_coordinator):
        """provider_health action calls coordinator.get_provider_health."""
        fields = {"user_id": "u1"}
        await _dispatch_worktree_action(mock_coordinator, "provider_health", fields)
        mock_coordinator.get_provider_health.assert_awaited_once()

    async def test_dispatch_unsupported_returns_payload(self, mock_coordinator):
        """Unknown action returns the unsupported-action payload without coordinator call."""
        result = await _dispatch_worktree_action(mock_coordinator, "totally-bogus", {})
        assert result["success"] is False
        assert "Unsupported" in result["error"]


# =============================================================================
# worktree_manage
# =============================================================================


class TestWorktreeManage:
    """Tests for the worktree_manage function."""

    async def test_missing_coordinator(self):
        """When _get_coordinator returns None, return missing-coordinator payload."""
        with patch("mahavishnu.mcp.tools.worktree_tools._get_coordinator", return_value=None):
            result = await worktree_manage(
                action="create",
                user_id="u1",
                repo_nickname="r1",
                branch="main",
            )
        assert result["success"] is False
        assert "WorktreeCoordinator not initialized" in result["error"]

    async def test_missing_required_fields(self):
        """If required fields are missing, return missing-fields payload."""
        coord = MagicMock()
        with patch("mahavishnu.mcp.tools.worktree_tools._get_coordinator", return_value=coord):
            result = await worktree_manage(
                action="create",
                user_id="u1",
                repo_nickname="r1",
                # branch missing
            )
        assert result["success"] is False
        assert "branch" in result["missing_fields"]

    async def test_successful_dispatch(self, mock_coordinator):
        """A well-formed call should reach _dispatch and return coordinator result."""
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=mock_coordinator,
        ):
            result = await worktree_manage(
                action="create",
                user_id="u1",
                repo_nickname="r1",
                branch="main",
                worktree_name="feature-x",
                create_branch=True,
            )
        assert result["success"] is True
        mock_coordinator.create_worktree.assert_awaited_once()

    async def test_action_normalized_to_lowercase(self, mock_coordinator):
        """Action should be normalized to lowercase and stripped."""
        with patch(
            "mahavishnu.mcp.tools.worktree_tools._get_coordinator",
            return_value=mock_coordinator,
        ):
            result = await worktree_manage(
                action="  CREATE  ",
                user_id="u1",
                repo_nickname="r1",
                branch="main",
            )
        assert result["action"] == "create"

    async def test_dispatch_exception_caught(self):
        """If the coordinator raises, return success=False with error message."""
        coord = MagicMock()
        coord.create_worktree = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("mahavishnu.mcp.tools.worktree_tools._get_coordinator", return_value=coord):
            result = await worktree_manage(
                action="create",
                user_id="u1",
                repo_nickname="r1",
                branch="main",
            )
        assert result["success"] is False
        assert result["action"] == "create"
        assert "boom" in result["error"]


# =============================================================================
# _get_coordinator
# =============================================================================


class TestGetCoordinator:
    """Tests for the _get_coordinator helper."""

    def test_get_coordinator_returns_app_worktree_coordinator(self):
        """_get_coordinator should return app.worktree_coordinator."""
        mock_app = MagicMock()
        mock_app.worktree_coordinator = MagicMock()
        with patch(
            "mahavishnu.mcp.tools.worktree_tools.MahavishnuApp.load",
            return_value=mock_app,
        ):
            result = _get_coordinator()
        assert result is mock_app.worktree_coordinator


# =============================================================================
# register_worktree_tools
# =============================================================================


class TestRegisterWorktreeTools:
    """Tests for the register_worktree_tools function."""

    def test_registers_worktree_manage(self):
        """register_worktree_tools should register worktree_manage on mcp."""
        mcp = MagicMock()
        mcp.tool = MagicMock()
        register_worktree_tools(mcp)
        mcp.tool.assert_called()
        # The decorator should be applied to worktree_manage
        # Check at least one tool registration happened
        assert mcp.tool.call_count >= 1
