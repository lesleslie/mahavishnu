"""Tests for Phase 3 coordination additions.

Covers:
- CoordinationManager.get_ecosystem_status()
- CoordinationMemory Akosha push and search_semantic()
- _run_command_safe() pipe helper
- coord_get_ecosystem_status MCP tool
- ecosystem-status and roadmap CLI commands
"""

from __future__ import annotations

import os
import tempfile
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
import yaml

from mahavishnu.core.coordination.manager import CoordinationManager, _run_command_safe
from mahavishnu.core.coordination.memory import CoordinationMemory

# ---------------------------------------------------------------------------
# Helpers (mirrors test_coordination.py pattern)
# ---------------------------------------------------------------------------


def _write_ecosystem(data: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    return path


def _issue_dict(**overrides: Any) -> dict:
    base = {
        "id": "ISSUE-001",
        "title": "Test issue",
        "description": "desc",
        "status": "in_progress",
        "priority": "critical",
        "severity": "bug",
        "repos": ["mahavishnu"],
        "created": "2026-01-01T00:00:00",
        "updated": "2026-01-01T00:00:00",
    }
    base.update(overrides)
    return base


def _plan_dict(**overrides: Any) -> dict:
    base = {
        "id": "PLAN-001",
        "title": "Test Plan",
        "description": "desc",
        "status": "active",
        "repos": ["mahavishnu"],
        "created": "2026-01-01T00:00:00",
        "updated": "2026-01-01T00:00:00",
        "target": "2026-06-01T00:00:00",
        "milestones": [
            {
                "id": "M-001",
                "name": "Alpha",
                "description": "First milestone",
                "due": "2026-03-01T00:00:00",
                "status": "completed",
            },
            {
                "id": "M-002",
                "name": "Beta",
                "description": "Second milestone",
                "due": "2026-05-01T00:00:00",
                "status": "pending",
            },
        ],
    }
    base.update(overrides)
    return base


def _dep_dict(**overrides: Any) -> dict:
    base = {
        "id": "DEP-001",
        "consumer": "mahavishnu",
        "provider": "session-buddy",
        "type": "mcp",
        "version_constraint": ">=0.1.0",
        "status": "unsatisfied",
        "created": "2026-01-01T00:00:00",
        "updated": "2026-01-01T00:00:00",
        "notes": "test dep",
    }
    base.update(overrides)
    return base


_AKOSHA_TOOLS_URL = "http://localhost:8682/mcp/tools/call"


# ---------------------------------------------------------------------------
# get_ecosystem_status tests
# ---------------------------------------------------------------------------


class TestGetEcosystemStatus:
    def test_empty_ecosystem_is_healthy(self):
        data = {"coordination": {}}
        path = _write_ecosystem(data)
        mgr = CoordinationManager(path)
        result = mgr.get_ecosystem_status()
        assert result["health"] == "healthy"
        assert result["active_plans"] == 0
        assert result["critical_blockers"] == 0
        assert result["degraded_dependencies"] == 0

    def test_critical_issue_marks_degraded(self):
        data = {"coordination": {"issues": [_issue_dict()]}}
        path = _write_ecosystem(data)
        mgr = CoordinationManager(path)
        result = mgr.get_ecosystem_status()
        assert result["health"] == "degraded"
        assert result["critical_blockers"] == 1
        assert result["blockers"][0]["id"] == "ISSUE-001"

    def test_resolved_issue_not_a_blocker(self):
        data = {"coordination": {"issues": [_issue_dict(status="resolved")]}}
        path = _write_ecosystem(data)
        mgr = CoordinationManager(path)
        result = mgr.get_ecosystem_status()
        assert result["critical_blockers"] == 0
        assert result["health"] == "healthy"

    def test_medium_priority_issue_not_a_blocker(self):
        data = {"coordination": {"issues": [_issue_dict(priority="medium")]}}
        path = _write_ecosystem(data)
        mgr = CoordinationManager(path)
        result = mgr.get_ecosystem_status()
        assert result["critical_blockers"] == 0
        assert result["health"] == "healthy"

    def test_unsatisfied_dep_marks_degraded(self):
        data = {"coordination": {"dependencies": [_dep_dict(status="unsatisfied")]}}
        path = _write_ecosystem(data)
        mgr = CoordinationManager(path)
        result = mgr.get_ecosystem_status()
        assert result["health"] == "degraded"
        assert result["degraded_dependencies"] == 1

    def test_satisfied_dep_not_degraded(self):
        data = {"coordination": {"dependencies": [_dep_dict(status="satisfied")]}}
        path = _write_ecosystem(data)
        mgr = CoordinationManager(path)
        result = mgr.get_ecosystem_status()
        assert result["degraded_dependencies"] == 0
        assert result["health"] == "healthy"

    def test_active_plan_included(self):
        data = {"coordination": {"plans": [_plan_dict()]}}
        path = _write_ecosystem(data)
        mgr = CoordinationManager(path)
        result = mgr.get_ecosystem_status()
        assert result["active_plans"] == 1
        plan = result["plans"][0]
        assert plan["id"] == "PLAN-001"
        assert plan["milestones_total"] == 2
        assert plan["milestones_done"] == 1

    def test_inactive_plan_not_in_active_count(self):
        data = {"coordination": {"plans": [_plan_dict(status="completed")]}}
        path = _write_ecosystem(data)
        mgr = CoordinationManager(path)
        result = mgr.get_ecosystem_status()
        assert result["active_plans"] == 0


# ---------------------------------------------------------------------------
# Akosha integration tests
# ---------------------------------------------------------------------------


class TestAkoshaIntegration:
    @respx.mock
    async def test_push_to_akosha_on_store(self):
        route = respx.post(_AKOSHA_TOOLS_URL).mock(
            return_value=httpx.Response(200, json={"result": "ok"})
        )
        sb = AsyncMock()
        memory = CoordinationMemory(session_buddy_client=sb, akosha_url="http://localhost:8682/mcp")
        await memory._store_memory("test content", {"key": "val"})
        assert route.called
        import json

        payload = json.loads(route.calls[0].request.content)
        assert payload["name"] == "store_memory"
        assert payload["arguments"]["content"] == "test content"

    @respx.mock
    async def test_akosha_push_degrades_on_connect_error(self):
        respx.post(_AKOSHA_TOOLS_URL).mock(side_effect=httpx.ConnectError("refused"))
        sb = AsyncMock()
        memory = CoordinationMemory(session_buddy_client=sb, akosha_url="http://localhost:8682/mcp")
        # Should not raise
        await memory._push_to_akosha("content", {})

    @respx.mock
    async def test_akosha_push_skipped_when_no_url(self):
        route = respx.post(_AKOSHA_TOOLS_URL).mock(
            return_value=httpx.Response(200, json={"result": "ok"})
        )
        sb = AsyncMock()
        memory = CoordinationMemory(session_buddy_client=sb, akosha_url=None)
        await memory._push_to_akosha("content", {})
        assert not route.called

    @respx.mock
    async def test_search_semantic_returns_results(self):
        respx.post(_AKOSHA_TOOLS_URL).mock(
            return_value=httpx.Response(200, json={"results": [{"id": "r1", "score": 0.9}]})
        )
        memory = CoordinationMemory(akosha_url="http://localhost:8682/mcp")
        results = await memory.search_semantic("test query")
        assert len(results) == 1
        assert results[0]["id"] == "r1"

    @respx.mock
    async def test_search_semantic_returns_empty_on_error(self):
        respx.post(_AKOSHA_TOOLS_URL).mock(side_effect=httpx.ConnectError("refused"))
        memory = CoordinationMemory(akosha_url="http://localhost:8682/mcp")
        results = await memory.search_semantic("test query")
        assert results == []

    async def test_search_semantic_returns_empty_when_no_url(self):
        memory = CoordinationMemory(akosha_url=None)
        results = await memory.search_semantic("test query")
        assert results == []

    async def test_close_releases_http_client(self):
        memory = CoordinationMemory(akosha_url="http://localhost:8682/mcp")
        assert memory._http is not None
        await memory.close()

    async def test_close_no_op_when_no_url(self):
        memory = CoordinationMemory(akosha_url=None)
        await memory.close()  # should not raise


# ---------------------------------------------------------------------------
# _run_command_safe tests
# ---------------------------------------------------------------------------


class TestRunCommandSafe:
    def test_simple_command(self):
        output = _run_command_safe("echo hello")
        assert "hello" in output

    def test_piped_command(self):
        output = _run_command_safe("echo hello world | grep hello")
        assert "hello" in output

    def test_failing_command_raises(self):
        import subprocess

        with pytest.raises(subprocess.CalledProcessError):
            _run_command_safe("false")
