"""Unit tests for mahavishnu.mcp.tools.coordination_tools.

The module decorates async functions with ``@mcp.tool()`` at module
import time. Tests reach into the registered FastMCP server via
``mcp.get_tool("...").fn(...)`` to invoke each function with mocked
``CoordinationManager``.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoTodo,
    IssueStatus,
    Priority,
    TodoStatus,
)
from mahavishnu.mcp.tools import coordination_tools as ct

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mcp_server() -> FastMCP:
    """Reuse the module-level FastMCP server (already has tools registered)."""
    return ct.mcp


@pytest.fixture
def fake_manager():
    """MagicMock stand-in for CoordinationManager.

    All public methods are pre-stubbed as AsyncMock-returning-MagicMock so
    tests can override the return value per-call.
    """
    mgr = MagicMock()
    mgr.list_issues = MagicMock(return_value=[])
    mgr.get_issue = MagicMock(return_value=None)
    mgr.create_issue = MagicMock()
    mgr.update_issue = MagicMock()
    mgr.delete_issue = MagicMock()
    mgr.list_todos = MagicMock(return_value=[])
    mgr.get_todo = MagicMock(return_value=None)
    mgr.list_plans = MagicMock(return_value=[])
    mgr.list_dependencies = MagicMock(return_value=[])
    mgr.get_blocking_issues = MagicMock(return_value=[])
    mgr.check_dependencies = MagicMock(return_value={"valid": True})
    mgr.get_repo_status = MagicMock(
        return_value={
            "issues": [],
            "todos": [],
            "dependencies_outgoing": [],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [],
        }
    )
    mgr.get_ecosystem_status = MagicMock(return_value={"health": "ok", "plans": [], "blockers": []})
    mgr.save = MagicMock()
    mgr._coordination = {"todos": []}
    return mgr


def _make_issue(issue_id: str = "ISSUE-001", **overrides) -> CrossRepoIssue:
    now = datetime.now().isoformat()
    defaults = {
        "id": issue_id,
        "title": "Test",
        "description": "desc",
        "status": IssueStatus.PENDING,
        "priority": Priority.MEDIUM,
        "severity": "normal",
        "repos": ["repo-a"],
        "created": now,
        "updated": now,
        "target": None,
        "dependencies": [],
        "blocking": [],
        "assignee": None,
        "labels": [],
        "metadata": {},
    }
    defaults.update(overrides)
    return CrossRepoIssue(**defaults)


def _make_todo(todo_id: str = "TODO-001", **overrides) -> CrossRepoTodo:
    now = datetime.now().isoformat()
    defaults = {
        "id": todo_id,
        "task": "Test task",
        "description": "desc",
        "repo": "repo-a",
        "status": TodoStatus.PENDING,
        "priority": Priority.MEDIUM,
        "created": now,
        "updated": now,
        "estimated_hours": 1.0,
        "actual_hours": None,
        "blocked_by": [],
        "blocking": [],
        "assignee": None,
        "labels": [],
        "acceptance_criteria": [],
    }
    defaults.update(overrides)
    return CrossRepoTodo(**defaults)


async def _invoke(mcp_server: FastMCP, name: str, **kwargs):
    """Convenience: pull the decorated function off the server and await it."""
    tool = await mcp_server.get_tool(name)
    return await tool.fn(**kwargs)


# =============================================================================
# Issues
# =============================================================================


class TestIssueTools:
    """coord_list_issues / coord_get_issue / coord_create_issue / etc."""

    @pytest.mark.asyncio
    async def test_list_issues_serializes_to_dicts(self, mcp_server, fake_manager):
        """list_issues should return model_dump JSON-ready dicts."""
        issue = _make_issue("ISSUE-001")
        fake_manager.list_issues.return_value = [issue]

        with patch.object(ct, "_get_manager", return_value=fake_manager):
            result = await _invoke(mcp_server, "coord_list_issues")

        assert isinstance(result, list)
        assert result[0]["id"] == "ISSUE-001"
        assert result[0]["priority"] == "medium"

    @pytest.mark.asyncio
    async def test_list_issues_invalid_status_raises(self, mcp_server, fake_manager):
        """An invalid status string should raise ValueError."""
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            with pytest.raises(ValueError, match="Invalid status"):
                await _invoke(mcp_server, "coord_list_issues", status="bogus")

    @pytest.mark.asyncio
    async def test_get_issue_returns_dict(self, mcp_server, fake_manager):
        """get_issue should return the model dump of the matching issue."""
        issue = _make_issue("ISSUE-X")
        fake_manager.get_issue.return_value = issue

        with patch.object(ct, "_get_manager", return_value=fake_manager):
            result = await _invoke(mcp_server, "coord_get_issue", issue_id="ISSUE-X")

        assert result["id"] == "ISSUE-X"

    @pytest.mark.asyncio
    async def test_get_issue_missing_raises(self, mcp_server, fake_manager):
        """Missing issue id should raise ValueError."""
        fake_manager.get_issue.return_value = None
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            with pytest.raises(ValueError, match="not found"):
                await _invoke(mcp_server, "coord_get_issue", issue_id="missing")

    @pytest.mark.asyncio
    async def test_create_issue_generates_id_and_saves(self, mcp_server, fake_manager):
        """create_issue should mint a new ISSUE-### id and call save()."""
        fake_manager.list_issues.return_value = []
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            result = await _invoke(
                mcp_server,
                "coord_create_issue",
                title="Bug",
                description="Something broken",
                repos=["r1"],
            )

        assert result["id"].startswith("ISSUE-")
        assert result["status"] == "pending"
        assert result["priority"] == "medium"
        fake_manager.create_issue.assert_called_once()
        fake_manager.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_issue_invalid_priority_raises(self, mcp_server, fake_manager):
        """Invalid priority should raise ValueError."""
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            with pytest.raises(ValueError, match="Invalid priority"):
                await _invoke(
                    mcp_server,
                    "coord_create_issue",
                    title="x",
                    description="x",
                    repos=["r1"],
                    priority="bogus",
                )

    @pytest.mark.asyncio
    async def test_update_issue_requires_at_least_one_field(self, mcp_server, fake_manager):
        """Calling update_issue with neither status nor priority should raise."""
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            with pytest.raises(ValueError, match="No updates specified"):
                await _invoke(mcp_server, "coord_update_issue", issue_id="ISSUE-1")

    @pytest.mark.asyncio
    async def test_update_issue_invalid_status_raises(self, mcp_server, fake_manager):
        """Invalid status string should raise ValueError."""
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            with pytest.raises(ValueError, match="Invalid status"):
                await _invoke(
                    mcp_server,
                    "coord_update_issue",
                    issue_id="ISSUE-1",
                    status="bogus",
                )

    @pytest.mark.asyncio
    async def test_update_issue_passes_through(self, mcp_server, fake_manager):
        """Valid status/priority should be passed to manager.update_issue."""
        fake_manager.get_issue.return_value = _make_issue("ISSUE-1", status=IssueStatus.IN_PROGRESS)
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            await _invoke(
                mcp_server,
                "coord_update_issue",
                issue_id="ISSUE-1",
                status="in_progress",
            )
        fake_manager.update_issue.assert_called_once()
        fake_manager.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_issue_marks_status_closed(self, mcp_server, fake_manager):
        """close_issue should send status='closed' to the manager."""
        fake_manager.get_issue.return_value = _make_issue("ISSUE-9", status=IssueStatus.CLOSED)
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            result = await _invoke(mcp_server, "coord_close_issue", issue_id="ISSUE-9")

        fake_manager.update_issue.assert_called_once_with("ISSUE-9", {"status": "closed"})
        assert result["status"] == "closed"


# =============================================================================
# Todos
# =============================================================================


class TestTodoTools:
    """coord_list_todos / coord_get_todo / coord_create_todo / coord_complete_todo."""

    @pytest.mark.asyncio
    async def test_list_todos_invalid_status_raises(self, mcp_server, fake_manager):
        """Invalid TodoStatus should raise ValueError."""
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            with pytest.raises(ValueError, match="Invalid status"):
                await _invoke(mcp_server, "coord_list_todos", status="bogus")

    @pytest.mark.asyncio
    async def test_get_todo_missing_raises(self, mcp_server, fake_manager):
        """Missing todo id should raise ValueError."""
        fake_manager.get_todo.return_value = None
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            with pytest.raises(ValueError, match="not found"):
                await _invoke(mcp_server, "coord_get_todo", todo_id="missing")

    @pytest.mark.asyncio
    async def test_create_todo_appends_to_coordination_dict(self, mcp_server, fake_manager):
        """create_todo should append a dict under _coordination['todos'] and save."""
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            result = await _invoke(
                mcp_server,
                "coord_create_todo",
                task="Implement X",
                description="detail",
                repo="repo-a",
                estimate_hours=2.0,
            )

        assert result["id"].startswith("TODO-")
        assert fake_manager._coordination["todos"], "todo was not appended"
        fake_manager.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_todo_invalid_priority_raises(self, mcp_server, fake_manager):
        """Invalid priority on create_todo should raise ValueError."""
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            with pytest.raises(ValueError, match="Invalid priority"):
                await _invoke(
                    mcp_server,
                    "coord_create_todo",
                    task="x",
                    description="x",
                    repo="r",
                    estimate_hours=1.0,
                    priority="bogus",
                )

    @pytest.mark.asyncio
    async def test_complete_todo_marks_status(self, mcp_server, fake_manager):
        """complete_todo should flip the matching todo to status='completed'."""
        existing = {
            "id": "TODO-1",
            "status": "pending",
            "updated": "old",
        }
        fake_manager._coordination = {"todos": [existing]}
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            result = await _invoke(mcp_server, "coord_complete_todo", todo_id="TODO-1")

        assert result["status"] == "completed"
        assert result["updated"] != "old"
        fake_manager.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_todo_missing_raises(self, mcp_server, fake_manager):
        """Missing todo id should raise ValueError."""
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            with pytest.raises(ValueError, match="not found"):
                await _invoke(mcp_server, "coord_complete_todo", todo_id="missing")


# =============================================================================
# Plans / Dependencies / Ecosystem
# =============================================================================


class TestPlansAndDeps:
    """coord_list_plans / coord_list_dependencies / coord_get_ecosystem_status."""

    @pytest.mark.asyncio
    async def test_list_plans_serializes(self, mcp_server, fake_manager):
        """list_plans should return model_dump dicts."""
        plan = SimpleNamespace(
            model_dump=MagicMock(return_value={"id": "PLAN-1", "status": "active"})
        )
        fake_manager.list_plans.return_value = [plan]
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            result = await _invoke(mcp_server, "coord_list_plans")

        assert result == [{"id": "PLAN-1", "status": "active"}]

    @pytest.mark.asyncio
    async def test_list_dependencies_passes_filters(self, mcp_server, fake_manager):
        """list_dependencies should forward all three filters to the manager."""
        fake_manager.list_dependencies.return_value = []
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            await _invoke(
                mcp_server,
                "coord_list_dependencies",
                consumer="c1",
                provider="p1",
                dependency_type="runtime",
            )
        fake_manager.list_dependencies.assert_called_once_with(
            consumer="c1", provider="p1", dependency_type="runtime"
        )

    @pytest.mark.asyncio
    async def test_get_blocking_issues(self, mcp_server, fake_manager):
        """get_blocking_issues should return issue dumps for a repo."""
        fake_manager.get_blocking_issues.return_value = [_make_issue("ISSUE-7")]
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            result = await _invoke(mcp_server, "coord_get_blocking_issues", repo="repo-a")

        assert result[0]["id"] == "ISSUE-7"

    @pytest.mark.asyncio
    async def test_check_dependencies_returns_dict(self, mcp_server, fake_manager):
        """check_dependencies should pass through the manager dict."""
        fake_manager.check_dependencies.return_value = {
            "valid": True,
            "issues": [],
        }
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            result = await _invoke(mcp_server, "coord_check_dependencies")

        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_get_repo_status_normalizes_dict(self, mcp_server, fake_manager):
        """get_repo_status should normalize the manager dict to a known shape."""
        fake_manager.get_repo_status.return_value = {
            "issues": [_make_issue()],
            "todos": [_make_todo()],
            "dependencies_outgoing": [],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [],
        }
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            result = await _invoke(mcp_server, "coord_get_repo_status", repo="r")

        assert result["issues"][0]["id"] == "ISSUE-001"
        assert result["todos"][0]["id"] == "TODO-001"
        assert result["dependencies_outgoing"] == []

    @pytest.mark.asyncio
    async def test_get_ecosystem_status_passes_through(self, mcp_server, fake_manager):
        """get_ecosystem_status should pass through the manager's return."""
        with patch.object(ct, "_get_manager", return_value=fake_manager):
            result = await _invoke(mcp_server, "coord_get_ecosystem_status")
        assert result == {"health": "ok", "plans": [], "blockers": []}


# =============================================================================
# Module-level: _get_manager helper
# =============================================================================


class TestGetManager:
    """The internal _get_manager should return a CoordinationManager instance."""

    def test_returns_coordination_manager(self):
        """_get_manager should construct and return a CoordinationManager."""
        with patch("mahavishnu.mcp.tools.coordination_tools.CoordinationManager") as MockMgr:
            ct._get_manager()
            MockMgr.assert_called_once()
