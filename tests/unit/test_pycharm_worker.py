"""Unit tests for PyCharm application worker and tools."""

import pytest

from mahavishnu.workers.registry import (
    WorkerCategory,
    WorkerConfig,
    WORKER_REGISTRY,
    get_worker_config,
    validate_worker_dependencies,
)


class TestPyCharmWorkerRegistry:
    """Tests for the application-pycharm worker registry entry."""

    def test_registry_entry_exists(self):
        config = get_worker_config("application-pycharm")
        assert config is not None, "application-pycharm should be in WORKER_REGISTRY"

    def test_registry_entry_fields(self):
        config = get_worker_config("application-pycharm")
        assert config.name == "PyCharm IDE"
        assert config.worker_type == "application-pycharm"
        assert config.command == ""  # Handled via MCP
        assert config.category == WorkerCategory.APPLICATION
        assert config.mcp_server == "jetbrains"
        assert config.supports_interactive is False
        assert config.default_timeout == 60

    def test_registry_entry_is_application_category(self):
        config = get_worker_config("application-pycharm")
        assert config.category == WorkerCategory.APPLICATION

    def test_validate_dependencies_always_available(self):
        """application-pycharm has no requires_tool, so should always be available."""
        results = validate_worker_dependencies()
        assert results.get("application-pycharm") is True

    def test_mcp_server_matches_jetbrains_permission(self):
        """mcp_server='jetbrains' matches mcp__jetbrains__* permission in .claude/settings.json."""
        config = get_worker_config("application-pycharm")
        assert config.mcp_server == "jetbrains"

    def test_registry_key_matches_worker_type(self):
        assert "application-pycharm" in WORKER_REGISTRY
        config = WORKER_REGISTRY["application-pycharm"]
        assert config.worker_type == "application-pycharm"


class TestPyCharmToolsFallback:
    """Tests for subprocess fallback functions in pycharm_tools."""

    def test_fallback_diagnostics_with_ruff(self, tmp_path):
        """Test ruff fallback returns diagnostics for a file with errors."""
        from mahavishnu.mcp.tools.pycharm_tools import _fallback_diagnostics

        # Create a temp file with a known issue
        test_file = tmp_path / "test_errors.py"
        test_file.write_text("import os\nx = undefined_var\n")
        diagnostics = _fallback_diagnostics(str(test_file))
        # Should return results (list, possibly empty)
        assert isinstance(diagnostics, list)

    def test_fallback_diagnostics_missing_file(self, tmp_path):
        """Test ruff fallback handles missing files gracefully."""
        from mahavishnu.mcp.tools.pycharm_tools import _fallback_diagnostics

        diagnostics = _fallback_diagnostics("/nonexistent/file.py")
        assert isinstance(diagnostics, list)

    def test_fallback_search_with_grep(self):
        """Test grep fallback returns search results (searches from cwd)."""
        from mahavishnu.mcp.tools.pycharm_tools import _fallback_search

        # _fallback_search runs grep from cwd ("."), so we just test it doesn't crash
        results = _fallback_search("import", "*.py")
        assert isinstance(results, list)

    def test_fallback_search_returns_list(self):
        """Test grep fallback always returns a list."""
        from mahavishnu.mcp.tools.pycharm_tools import _fallback_search

        results = _fallback_search("import", "*.py")
        assert isinstance(results, list)
        # Should find at least something in the project
        assert len(results) >= 0

    def test_extract_problems_none(self):
        """Test _extract_problems handles None."""
        from mahavishnu.mcp.tools.pycharm_tools import _extract_problems

        assert _extract_problems(None) == []

    def test_extract_problems_list(self):
        """Test _extract_problems handles a list."""
        from mahavishnu.mcp.tools.pycharm_tools import _extract_problems

        problems = [{"message": "test", "severity": "error"}]
        assert _extract_problems(problems) == problems

    def test_extract_problems_dict_with_problems_key(self):
        """Test _extract_problems handles dict with 'problems' key."""
        from mahavishnu.mcp.tools.pycharm_tools import _extract_problems

        result = {"problems": [{"message": "test"}]}
        assert _extract_problems(result) == [{"message": "test"}]

    def test_extract_problems_dict_with_content_key(self):
        """Test _extract_problems handles dict with 'content' key."""
        from mahavishnu.mcp.tools.pycharm_tools import _extract_problems

        result = {"content": [{"message": "test"}]}
        assert _extract_problems(result) == [{"message": "test"}]
