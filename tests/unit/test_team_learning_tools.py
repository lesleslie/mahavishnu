"""Tests for deprecated team_learning MCP tools."""

from __future__ import annotations

import importlib
import warnings


def test_import_emits_deprecation_warning() -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import mahavishnu.mcp.tools.team_learning_tools as team_learning_tools

        importlib.reload(team_learning_tools)
        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert dep_warnings
        assert "de-authorized" in str(dep_warnings[0].message).lower()


class _StubMCP:
    def tool(self):
        def decorator(fn):
            return fn

        return decorator


def test_registration_emits_deprecation_warning() -> None:
    from mahavishnu.mcp.tools.team_learning_tools import register_team_learning_tools

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        register_team_learning_tools(_StubMCP())
        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert dep_warnings
        assert "deprecated" in str(dep_warnings[0].message).lower()
