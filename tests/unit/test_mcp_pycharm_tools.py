"""Unit tests for mahavishnu.mcp.tools.pycharm_tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.pycharm_tools import (
    _extract_problems,
    _fallback_diagnostics,
    _fallback_search,
    register_pycharm_tools,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_mcp_client():
    """Build a mock MCP client with call_tool AsyncMock."""
    client = MagicMock()
    client.call_tool = AsyncMock()
    return client


@pytest.fixture
def mock_app(mock_mcp_client):
    """Build a mock MahavishnuApp with a worker_manager that has mcp_client."""
    app = MagicMock()
    app.worker_manager = MagicMock()
    app.worker_manager.mcp_client = mock_mcp_client
    return app


@pytest.fixture
def mock_app_no_client():
    """Build a mock MahavishnuApp with no mcp_client (fallback path)."""
    app = MagicMock()
    app.worker_manager = MagicMock()
    app.worker_manager.mcp_client = None
    return app


@pytest.fixture
def mock_app_no_wm():
    """Build a mock MahavishnuApp with no worker_manager at all."""
    app = MagicMock(spec=[])  # no worker_manager attribute
    return app


@pytest.fixture
def mock_mcp():
    """Build a mock FastMCP that captures tool functions."""
    mcp = MagicMock()
    mcp._tools = {}

    def tool_decorator():
        def wrapper(fn):
            mcp._tools[fn.__name__] = fn
            return fn

        return wrapper

    mcp.tool = MagicMock(side_effect=lambda: tool_decorator())
    return mcp


@pytest.fixture
def registered_mcp(mock_mcp, mock_app):
    """Register pycharm tools on a mock MCP with an app + mcp_client."""
    register_pycharm_tools(mock_mcp, mock_app)
    return mock_mcp


# =============================================================================
# _extract_problems
# =============================================================================


class TestExtractProblems:
    """Tests for the _extract_problems helper."""

    def test_none_returns_empty_list(self):
        """None input should return an empty list."""
        assert _extract_problems(None) == []

    def test_list_input_returned_as_is(self):
        """A list should be returned unchanged."""
        data = [{"message": "x"}]
        assert _extract_problems(data) == data

    def test_dict_with_problems_key(self):
        """A dict with 'problems' key returns that sublist."""
        data = {"problems": [{"message": "a"}, {"message": "b"}]}
        assert _extract_problems(data) == [{"message": "a"}, {"message": "b"}]

    def test_dict_with_content_list(self):
        """A dict with 'content' (list) returns that list."""
        data = {"content": [{"message": "x"}]}
        assert _extract_problems(data) == [{"message": "x"}]

    def test_dict_with_nonlist_content(self):
        """A dict with non-list 'content' falls through to wrap result."""
        data = {"content": "string", "x": 1}
        result = _extract_problems(data)
        # falls through to return [result] if result else []
        assert result == [data]

    def test_empty_dict_returns_empty(self):
        """An empty dict returns empty list."""
        assert _extract_problems({}) == []


# =============================================================================
# _fallback_diagnostics
# =============================================================================


class TestFallbackDiagnostics:
    """Tests for the _fallback_diagnostics helper."""

    def test_ruff_not_found(self):
        """When ruff is missing, return a warning message."""
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = _fallback_diagnostics("foo.py")
        assert result == [{"message": "ruff not installed", "severity": "warning"}]

    def test_ruff_timeout(self):
        """When ruff times out, return a warning message."""
        import subprocess

        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ruff", timeout=30),
        ):
            result = _fallback_diagnostics("foo.py")
        assert result == [{"message": "ruff check timed out", "severity": "warning"}]

    def test_ruff_clean(self):
        """When ruff returns 0, no diagnostics."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            return_value=mock_result,
        ):
            result = _fallback_diagnostics("foo.py")
        assert result == []

    def test_ruff_invalid_json(self):
        """When ruff returns non-JSON, return error dict with the raw output."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "Some non-JSON error"
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            return_value=mock_result,
        ):
            result = _fallback_diagnostics("foo.py")
        assert result == [{"message": "Some non-JSON error", "severity": "error"}]

    def test_ruff_json_findings(self):
        """When ruff returns valid JSON, parse findings."""
        findings = [
            {
                "message": "Unused import",
                "severity": "warning",
                "filename": "foo.py",
                "line": 1,
                "column": 1,
                "code": "F401",
            }
        ]
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = json.dumps(findings)
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            return_value=mock_result,
        ):
            result = _fallback_diagnostics("foo.py")
        assert len(result) == 1
        assert result[0]["code"] == "F401"
        assert result[0]["file"] == "foo.py"
        assert result[0]["severity"] == "warning"

    def test_ruff_errors_only_adds_select_flag(self):
        """errors_only=True should add --select E,F to the command."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            _fallback_diagnostics("foo.py", errors_only=True)
        # Verify the command includes --select and E,F
        cmd = mock_run.call_args.args[0]
        assert "--select" in cmd
        assert "E,F" in cmd


# =============================================================================
# _fallback_search
# =============================================================================


class TestFallbackSearch:
    """Tests for the _fallback_search helper."""

    def test_grep_not_found(self):
        """When grep is missing, return empty list."""
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = _fallback_search("pattern")
        assert result == []

    def test_grep_timeout(self):
        """When grep times out, return empty list."""
        import subprocess

        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="grep", timeout=15),
        ):
            result = _fallback_search("pattern")
        assert result == []

    def test_grep_results_parsed(self):
        """When grep returns results, parse them."""
        grep_output = "src/foo.py:10:    def bar():\nsrc/baz.py:5:x = 1\n"
        mock_result = MagicMock()
        mock_result.stdout = grep_output
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            return_value=mock_result,
        ):
            result = _fallback_search("pattern")
        assert len(result) == 2
        assert result[0]["file_path"] == "src/foo.py"
        assert result[0]["line_number"] == 10
        assert "def bar()" in result[0]["match_text"]

    def test_grep_results_capped_at_100(self):
        """When grep returns more than 100 lines, cap at 100."""
        lines = [f"file{i}.py:1:match{i}" for i in range(150)]
        mock_result = MagicMock()
        mock_result.stdout = "\n".join(lines)
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            return_value=mock_result,
        ):
            result = _fallback_search("pattern")
        assert len(result) == 100

    def test_grep_with_file_pattern(self):
        """When file_pattern is provided, it should be added to the command."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            _fallback_search("pattern", file_pattern="*.py")
        cmd = mock_run.call_args.args[0]
        assert "--include" in cmd
        assert "*.py" in cmd


# =============================================================================
# Tool Registration
# =============================================================================


class TestRegistration:
    """Tests for register_pycharm_tools."""

    def test_all_tools_registered(self, registered_mcp):
        """All 8 pycharm tools should be registered."""
        expected = {
            "pycharm_health",
            "pycharm_run_diagnostics",
            "pycharm_open_file",
            "pycharm_search_in_project",
            "pycharm_replace_in_file",
            "pycharm_reformat_file",
            "pycharm_refactor_symbol",
            "pycharm_list_problems",
        }
        assert expected.issubset(set(registered_mcp._tools.keys()))


# =============================================================================
# pycharm_health
# =============================================================================


class TestPycharmHealth:
    """Tests for the pycharm_health tool."""

    async def test_health_mcp_available(self, registered_mcp, mock_mcp_client):
        """When MCP responds, status should be healthy."""
        mock_mcp_client.call_tool = AsyncMock(return_value={"ok": True})
        result = await registered_mcp._tools["pycharm_health"]()
        assert result["status"] == "healthy"
        assert result["mcp_available"] is True
        assert result["fallback_active"] is False
        assert "PyCharm MCP server connected" in result["message"]

    async def test_health_mcp_unavailable(self, registered_mcp, mock_mcp_client):
        """When MCP call times out, status should be degraded."""
        mock_mcp_client.call_tool = AsyncMock(side_effect=TimeoutError("nope"))
        result = await registered_mcp._tools["pycharm_health"]()
        assert result["status"] == "degraded"
        assert result["mcp_available"] is False
        assert result["fallback_active"] is True
        assert "using subprocess fallbacks" in result["message"]

    async def test_health_listed_tools(self, mock_mcp, mock_app_no_client):
        """Even when fallback is active, all tool names should be listed."""
        register_pycharm_tools(mock_mcp, mock_app_no_client)
        result = await mock_mcp._tools["pycharm_health"]()
        assert "pycharm_run_diagnostics" in result["tools"]
        assert "pycharm_open_file" in result["tools"]


# =============================================================================
# pycharm_run_diagnostics
# =============================================================================


class TestPycharmRunDiagnostics:
    """Tests for the pycharm_run_diagnostics tool."""

    async def test_mcp_path(self, registered_mcp, mock_mcp_client):
        """When MCP responds, result source should be pycharm_mcp."""
        mock_mcp_client.call_tool = AsyncMock(return_value={"problems": [{"message": "x"}]})
        result = await registered_mcp._tools["pycharm_run_diagnostics"](file_path="src/foo.py")
        assert result["source"] == "pycharm_mcp"
        assert result["file_path"] == "src/foo.py"
        assert result["problems"] == [{"message": "x"}]

    async def test_fallback_path(self, mock_mcp, mock_app_no_client):
        """When MCP unavailable, fall back to ruff."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            return_value=mock_result,
        ):
            register_pycharm_tools(mock_mcp, mock_app_no_client)
            result = await mock_mcp._tools["pycharm_run_diagnostics"](file_path="src/foo.py")
        assert result["source"] == "ruff_fallback"
        assert result["fallback_active"] is True
        assert result["file_path"] == "src/foo.py"

    async def test_mcp_exception_falls_back(self, registered_mcp, mock_mcp_client):
        """An exception from the MCP client should trigger fallback."""
        mock_mcp_client.call_tool = AsyncMock(side_effect=RuntimeError("boom"))
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            return_value=mock_result,
        ):
            result = await registered_mcp._tools["pycharm_run_diagnostics"](file_path="src/foo.py")
        assert result["source"] == "ruff_fallback"
        assert result["fallback_active"] is True


# =============================================================================
# pycharm_open_file
# =============================================================================


class TestPycharmOpenFile:
    """Tests for the pycharm_open_file tool."""

    async def test_mcp_path(self, registered_mcp, mock_mcp_client):
        """When MCP responds, opened=True."""
        mock_mcp_client.call_tool = AsyncMock(return_value={"ok": True})
        result = await registered_mcp._tools["pycharm_open_file"](file_path="src/foo.py")
        assert result["source"] == "pycharm_mcp"
        assert result["opened"] is True
        assert result["file_path"] == "src/foo.py"

    async def test_mcp_path_with_line(self, registered_mcp, mock_mcp_client):
        """When line is provided, it should be passed to the MCP client."""
        mock_mcp_client.call_tool = AsyncMock(return_value={"ok": True})
        await registered_mcp._tools["pycharm_open_file"](file_path="src/foo.py", line=42)
        call_args = mock_mcp_client.call_tool.await_args
        assert call_args.args[0] == "jetbrains__open_file"
        assert call_args.args[1]["line"] == 42

    async def test_exception_returns_fallback(self, registered_mcp, mock_mcp_client):
        """Exception from MCP returns fallback error."""
        mock_mcp_client.call_tool = AsyncMock(side_effect=RuntimeError("nope"))
        result = await registered_mcp._tools["pycharm_open_file"](file_path="src/foo.py")
        assert result["source"] == "fallback"
        assert result["opened"] is False
        assert "nope" in result["error"]
        assert result["fallback_active"] is True


# =============================================================================
# pycharm_search_in_project
# =============================================================================


class TestPycharmSearchInProject:
    """Tests for the pycharm_search_in_project tool."""

    async def test_mcp_path(self, registered_mcp, mock_mcp_client):
        """When MCP responds, source should be pycharm_mcp."""
        mock_mcp_client.call_tool = AsyncMock(return_value=[{"line": 1}])
        result = await registered_mcp._tools["pycharm_search_in_project"](pattern="def")
        assert result["source"] == "pycharm_mcp"
        assert result["results"] == [{"line": 1}]

    async def test_fallback_path(self, mock_mcp, mock_app_no_client):
        """When MCP unavailable, use grep fallback."""
        mock_result = MagicMock()
        mock_result.stdout = "src/foo.py:1:def bar():\n"
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            return_value=mock_result,
        ):
            register_pycharm_tools(mock_mcp, mock_app_no_client)
            result = await mock_mcp._tools["pycharm_search_in_project"](pattern="def")
        assert result["source"] == "grep_fallback"
        assert result["fallback_active"] is True
        assert len(result["results"]) == 1

    async def test_mcp_with_file_pattern(self, registered_mcp, mock_mcp_client):
        """file_pattern is forwarded to MCP call."""
        mock_mcp_client.call_tool = AsyncMock(return_value=[])
        await registered_mcp._tools["pycharm_search_in_project"](pattern="def", file_pattern="*.py")
        call_args = mock_mcp_client.call_tool.await_args
        assert call_args.args[1]["file_pattern"] == "*.py"


# =============================================================================
# pycharm_replace_in_file
# =============================================================================


class TestPycharmReplaceInFile:
    """Tests for the pycharm_replace_in_file tool."""

    async def test_mcp_path(self, registered_mcp, mock_mcp_client):
        """When MCP responds, replaced should be True."""
        mock_mcp_client.call_tool = AsyncMock(return_value=True)
        result = await registered_mcp._tools["pycharm_replace_in_file"](
            file_path="foo.py", search_text="old", replace_text="new"
        )
        assert result["source"] == "pycharm_mcp"
        assert result["replaced"] is True

    async def test_mcp_exception(self, registered_mcp, mock_mcp_client):
        """MCP exception returns fallback error."""
        mock_mcp_client.call_tool = AsyncMock(side_effect=RuntimeError("nope"))
        result = await registered_mcp._tools["pycharm_replace_in_file"](
            file_path="foo.py", search_text="old", replace_text="new"
        )
        assert result["source"] == "fallback"
        assert result["replaced"] is False
        assert "nope" in result["error"]


# =============================================================================
# pycharm_reformat_file
# =============================================================================


class TestPycharmReformatFile:
    """Tests for the pycharm_reformat_file tool."""

    async def test_mcp_path(self, registered_mcp, mock_mcp_client):
        """When MCP responds, reformatted should be True."""
        mock_mcp_client.call_tool = AsyncMock(return_value=True)
        result = await registered_mcp._tools["pycharm_reformat_file"](file_path="foo.py")
        assert result["source"] == "pycharm_mcp"
        assert result["reformatted"] is True

    async def test_mcp_exception(self, registered_mcp, mock_mcp_client):
        """MCP exception returns fallback error."""
        mock_mcp_client.call_tool = AsyncMock(side_effect=RuntimeError("nope"))
        result = await registered_mcp._tools["pycharm_reformat_file"](file_path="foo.py")
        assert result["source"] == "fallback"
        assert result["reformatted"] is False
        assert "nope" in result["error"]


# =============================================================================
# pycharm_refactor_symbol
# =============================================================================


class TestPycharmRefactorSymbol:
    """Tests for the pycharm_refactor_symbol tool."""

    async def test_mcp_path(self, registered_mcp, mock_mcp_client):
        """When MCP responds, refactored should be True."""
        mock_mcp_client.call_tool = AsyncMock(return_value=True)
        result = await registered_mcp._tools["pycharm_refactor_symbol"](
            symbol_name="old_name", new_name="new_name"
        )
        assert result["source"] == "pycharm_mcp"
        assert result["refactored"] is True

    async def test_default_scope(self, registered_mcp, mock_mcp_client):
        """Default scope should be 'project'."""
        mock_mcp_client.call_tool = AsyncMock(return_value=True)
        await registered_mcp._tools["pycharm_refactor_symbol"](symbol_name="x", new_name="y")
        call_args = mock_mcp_client.call_tool.await_args
        assert call_args.args[1]["scope"] == "project"

    async def test_mcp_exception(self, registered_mcp, mock_mcp_client):
        """MCP exception returns fallback error."""
        mock_mcp_client.call_tool = AsyncMock(side_effect=RuntimeError("nope"))
        result = await registered_mcp._tools["pycharm_refactor_symbol"](
            symbol_name="x", new_name="y"
        )
        assert result["source"] == "fallback"
        assert result["refactored"] is False
        assert "nope" in result["error"]


# =============================================================================
# pycharm_list_problems
# =============================================================================


class TestPycharmListProblems:
    """Tests for the pycharm_list_problems tool."""

    async def test_mcp_path(self, registered_mcp, mock_mcp_client):
        """When MCP responds, source should be pycharm_mcp."""
        mock_mcp_client.call_tool = AsyncMock(return_value={"problems": [{"message": "p"}]})
        result = await registered_mcp._tools["pycharm_list_problems"](file_path="foo.py")
        assert result["source"] == "pycharm_mcp"
        assert result["problems"] == [{"message": "p"}]

    async def test_mcp_path_with_severity(self, registered_mcp, mock_mcp_client):
        """severity is forwarded to MCP call."""
        mock_mcp_client.call_tool = AsyncMock(return_value={"problems": []})
        await registered_mcp._tools["pycharm_list_problems"](file_path="foo.py", severity="error")
        call_args = mock_mcp_client.call_tool.await_args
        assert call_args.args[1]["severity"] == "error"

    async def test_fallback_severity_error(self, mock_mcp, mock_app_no_client):
        """Severity 'error' triggers errors_only=True in fallback."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            register_pycharm_tools(mock_mcp, mock_app_no_client)
            await mock_mcp._tools["pycharm_list_problems"](file_path="foo.py", severity="error")
        cmd = mock_run.call_args.args[0]
        assert "--select" in cmd
        assert "E,F" in cmd

    async def test_fallback_severity_warning(self, mock_mcp, mock_app_no_client):
        """Severity 'warning' should not add --select flag."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch(
            "mahavishnu.mcp.tools.pycharm_tools.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            register_pycharm_tools(mock_mcp, mock_app_no_client)
            await mock_mcp._tools["pycharm_list_problems"](file_path="foo.py", severity="warning")
        cmd = mock_run.call_args.args[0]
        assert "--select" not in cmd
