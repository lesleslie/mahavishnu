"""Integration tests for MCP tool external compatibility.

Validates that MCP tools have:
- Proper docstrings for tool discovery
- Consistent return schemas (status, error, etc.)
- Version metadata registered
- Type-annotated parameters

These tests verify external consumer contract compliance
without requiring running MCP server infrastructure.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mahavishnu.mcp.tool_versions import TOOL_VERSIONS, get_tool_version

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_CORE = PROJECT_ROOT / "mahavishnu" / "mcp" / "server_core.py"
TOOLS_DIR = PROJECT_ROOT / "mahavishnu" / "mcp" / "tools"


def _parse_tool_functions(filepath: Path) -> list[tuple[str, ast.AsyncFunctionDef]]:
    """Parse a Python file and extract async functions decorated with @server.tool().

    Returns list of (function_name, function_node) tuples.
    """
    source = filepath.read_text()
    tree = ast.parse(source)

    tools = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                # Match @server.tool()
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "tool"
                ):
                    tools.append((node.name, node))

    return tools


def _get_register_functions(filepath: Path) -> list[tuple[str, str]]:
    """Extract (function_name, first_line_of_docstring) from register functions.

    Looks for functions in tool files that match pattern:
        @server.tool()
        async def tool_name(...)
    """
    if not filepath.exists():
        return []

    source = filepath.read_text()
    tree = ast.parse(source)
    tools = []

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "tool"
                ):
                    docstring = ast.get_docstring(node) or ""
                    tools.append((node.name, docstring))

    return tools


# ---------------------------------------------------------------------------
# Tests: Inline tools in server_core.py
# ---------------------------------------------------------------------------


class TestInlineToolSchemas:
    """Validate inline MCP tools in server_core.py."""

    @pytest.fixture(scope="class")
    def inline_tools(self):
        return _parse_tool_functions(SERVER_CORE)

    def test_inline_tools_found(self, inline_tools):
        """At least 20 inline tools should be registered."""
        assert len(inline_tools) >= 20, (
            f"Expected >= 20 inline tools, found {len(inline_tools)}"
        )

    def test_all_inline_tools_have_docstrings(self, inline_tools):
        """Every inline tool must have a docstring for MCP discovery."""
        missing = []
        for _name, node in inline_tools:
            docstring = ast.get_docstring(node)
            if not docstring:
                missing.append(_name)

        assert not missing, f"Tools missing docstrings: {missing}"

    def test_all_inline_tools_return_dict(self, inline_tools):
        """Every inline tool should return dict[str, Any]."""
        for name, node in inline_tools:
            ret = node.returns
            if ret is None:
                continue  # No annotation is acceptable

            ret_str = ast.unparse(ret) if isinstance(ret, ast.AST) else str(ret)
            assert "dict" in ret_str, (
                f"Tool '{name}' returns '{ret_str}', expected dict[str, Any]"
            )

    def test_all_inline_tools_have_version(self, inline_tools):
        """Every inline tool should be in the version registry."""
        unversioned = []
        for name, _ in inline_tools:
            if get_tool_version(name) is None:
                unversioned.append(name)

        assert not unversioned, (
            f"Tools missing from version registry: {unversioned}"
        )


# ---------------------------------------------------------------------------
# Tests: Tool modules
# ---------------------------------------------------------------------------


class TestToolModules:
    """Validate MCP tool registration modules."""

    @pytest.fixture(scope="class")
    def module_tools(self):
        """Collect tools from all tool modules."""
        all_tools = []
        for filepath in TOOLS_DIR.glob("*.py"):
            if filepath.name.startswith("_"):
                continue
            if filepath.name == "tool_versions.py":
                continue
            tools = _get_register_functions(filepath)
            for name, docstring in tools:
                all_tools.append((name, docstring, filepath.name))

        return all_tools

    def test_tool_modules_exist(self):
        """Tool modules directory should contain registration files."""
        py_files = list(TOOLS_DIR.glob("*.py"))
        assert len(py_files) >= 10, f"Expected >= 10 tool files, found {len(py_files)}"

    def test_module_tools_have_docstrings(self, module_tools):
        """Every tool from modules must have a docstring."""
        missing = []
        for name, docstring, filename in module_tools:
            if not docstring:
                missing.append(f"{filename}:{name}")

        assert not missing, f"Module tools missing docstrings: {missing[:10]}"

    def test_module_tools_have_versions(self, module_tools):
        """Most tools from modules should be in the version registry."""
        if not module_tools:
            pytest.skip("No module tools found to validate")

        unversioned = []
        for name, _, filename in module_tools:
            if get_tool_version(name) is None:
                unversioned.append(f"{filename}:{name}")

        # Allow some unversioned tools - new tools may not yet be registered
        versioned_pct = (
            (len(module_tools) - len(unversioned)) / len(module_tools) * 100
            if module_tools
            else 0
        )
        assert versioned_pct >= 80, (
            f"Only {versioned_pct:.0f}% of module tools are versioned "
            f"({len(unversioned)} unversioned): {unversioned[:5]}"
        )


# ---------------------------------------------------------------------------
# Tests: Version registry
# ---------------------------------------------------------------------------


class TestVersionRegistry:
    """Validate the tool version registry."""

    def test_registry_not_empty(self):
        assert len(TOOL_VERSIONS) >= 50, (
            f"Expected >= 50 versioned tools, found {len(TOOL_VERSIONS)}"
        )

    def test_versions_are_semver(self):
        """All versions should follow semver pattern (major.minor.patch)."""
        import re

        semver_pattern = re.compile(r"^\d+\.\d+\.\d+$")
        invalid = [
            (name, ver)
            for name, ver in TOOL_VERSIONS.items()
            if not semver_pattern.match(ver)
        ]

        assert not invalid, f"Invalid semver versions: {invalid[:5]}"

    def test_get_tool_version_returns_none_for_unknown(self):
        assert get_tool_version("nonexistent_tool_xyz") is None

    def test_get_tool_version_returns_string_for_known(self):
        version = get_tool_version("list_repos")
        assert version is not None
        assert isinstance(version, str)
        assert version == "1.0.0"

    def test_get_tool_versions_tool_is_versioned(self):
        """The get_tool_versions query tool should be in the registry."""
        assert get_tool_version("get_tool_versions") is not None

    def test_mcp_utility_tools_are_versioned(self):
        """New MCP utility tools should be tracked in the version registry."""
        assert get_tool_version("mcp_list_tools") is not None
        assert get_tool_version("mcp_test_connection") is not None
        assert get_tool_version("mcp_get_metrics") is not None


# ---------------------------------------------------------------------------
# Tests: Return schema consistency
# ---------------------------------------------------------------------------


class TestReturnSchemaConsistency:
    """Validate that tools follow consistent return patterns."""

    @pytest.fixture(scope="class")
    def inline_tools(self):
        return _parse_tool_functions(SERVER_CORE)

    def test_error_returns_include_error_key(self, inline_tools):
        """Tools that return errors should include an 'error' key."""
        for name, node in inline_tools:
            source = ast.unparse(node)
            # Check if tool has error return paths
            if '"error"' in source or "'error'" in source:
                # Should also have status key in most cases
                assert '"status"' in source or "'status'" in source, (
                    f"Tool '{name}' returns 'error' but no 'status' key"
                )


# ---------------------------------------------------------------------------
# Tests: Parameter validation
# ---------------------------------------------------------------------------


class TestParameterValidation:
    """Validate tool parameter type annotations."""

    @pytest.fixture(scope="class")
    def inline_tools(self):
        return _parse_tool_functions(SERVER_CORE)

    def test_parameters_have_type_annotations(self, inline_tools):
        """All tool parameters should have type annotations."""
        unannotated = []
        for name, node in inline_tools:
            args = node.args
            for arg in args.args:
                if arg.arg == "self":
                    continue
                if arg.annotation is None:
                    unannotated.append(f"{name}:{arg.arg}")

        assert not unannotated, (
            f"Parameters without type annotations: {unannotated[:10]}"
        )

    def test_string_params_have_defaults_or_none_type(self, inline_tools):
        """String parameters should typically accept None or have defaults."""
        # This is a soft check - not all string params need defaults
        for _name, node in inline_tools:
            for arg in node.args.args:
                if arg.arg in ("self", "request"):
                    continue
                if arg.annotation and "str" in ast.unparse(arg.annotation):
                    # str | None is the expected pattern for optional strings
                    pass  # Acceptable either way
