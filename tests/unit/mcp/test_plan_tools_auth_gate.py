"""Auth-gate enforcement for the ``plan_*`` MCP tools (REQ-PLAN-010).

Source-inspection test: the ``@require_mcp_auth`` decorator cannot be
observed at runtime once FastMCP has wrapped the tool, so this module
asserts the invariant statically. If someone removes the decorator from
one of the five tools, this test fails.

Two independent checks:

1. Raw source counts (the brief's contract) — five tool definitions and at
   least five ``@require_mcp_auth`` applications.
2. An AST walk pairing each ``plan_*`` tool with both its ``@mcp.tool``
   registration and a ``@require_mcp_auth(required_permission=
   Permission.READ_PLAN_INDEX)`` decorator. Counting alone would pass if a
   decorator were moved onto the wrong function; the AST check would not.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from mahavishnu.core.permissions import Permission
import mahavishnu.mcp.tools.plan_tools as plan_tools_module

TOOL_NAMES = (
    "plan_list",
    "plan_show",
    "plan_search",
    "plan_vitals",
    "plan_rebuild_status",
)


def _module_source() -> str:
    return inspect.getsource(plan_tools_module)


def _tool_functions() -> dict[str, ast.AsyncFunctionDef]:
    tree = ast.parse(_module_source())
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name in TOOL_NAMES
    }


def _decorator_names(node: ast.AsyncFunctionDef) -> list[str]:
    names: list[str] = []
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
    return names


class TestAuthGate:
    def test_all_five_tools_have_require_mcp_auth_decorator(self) -> None:
        """Raw source contract: five tools, at least five decorator applications."""
        source = _module_source()

        for name in TOOL_NAMES:
            assert source.count(f"async def {name}") == 1, f"{name} not defined exactly once"
        assert source.count("@require_mcp_auth") >= 5

    def test_every_tool_function_is_discovered(self) -> None:
        assert set(_tool_functions()) == set(TOOL_NAMES)

    @pytest.mark.parametrize("tool_name", TOOL_NAMES)
    def test_tool_carries_require_mcp_auth(self, tool_name: str) -> None:
        node = _tool_functions()[tool_name]

        assert "require_mcp_auth" in _decorator_names(node), (
            f"{tool_name} is missing @require_mcp_auth (REQ-PLAN-010)"
        )

    @pytest.mark.parametrize("tool_name", TOOL_NAMES)
    def test_tool_is_registered_with_mcp_tool(self, tool_name: str) -> None:
        node = _tool_functions()[tool_name]

        assert "tool" in _decorator_names(node), f"{tool_name} is missing @mcp.tool"

    @pytest.mark.parametrize("tool_name", TOOL_NAMES)
    def test_required_permission_is_read_plan_index(self, tool_name: str) -> None:
        """The gate must request READ_PLAN_INDEX, not a weaker permission."""
        node = _tool_functions()[tool_name]
        permissions: list[str] = []

        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if not (isinstance(dec.func, ast.Name) and dec.func.id == "require_mcp_auth"):
                continue
            for keyword in dec.keywords:
                if keyword.arg == "required_permission" and isinstance(
                    keyword.value, ast.Attribute
                ):
                    permissions.append(keyword.value.attr)

        assert permissions == ["READ_PLAN_INDEX"], (
            f"{tool_name} must be gated by Permission.READ_PLAN_INDEX, got {permissions}"
        )

    def test_permission_member_exists_with_expected_value(self) -> None:
        """Guard against the enum member being renamed out from under the tools."""
        assert Permission.READ_PLAN_INDEX.value == "read_plan_index"
