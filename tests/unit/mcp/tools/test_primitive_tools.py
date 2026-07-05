from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
import pytest


@pytest.fixture
def server_with_tools() -> FastMCP:
    """Build a FastMCP server with a few representative tools for testing."""
    mcp = FastMCP("test-server")

    @mcp.tool()
    async def alpha(value: str) -> dict[str, Any]:
        """The alpha tool."""
        return {"value": value}

    @mcp.tool()
    async def beta(count: int = 5) -> dict[str, Any]:
        """The beta tool with a default."""
        return {"count": count}

    @mcp.tool()
    async def gamma() -> dict[str, Any]:
        """The gamma tool, no args."""
        return {}

    return mcp


@pytest.mark.unit
async def test_list_primitives_returns_dict_with_primitives_key(server_with_tools: FastMCP) -> None:
    """list_primitives returns a dict containing a 'primitives' list."""
    from mahavishnu.mcp.tools.primitive_tools import list_primitives

    result = await list_primitives(server=server_with_tools)

    assert isinstance(result, dict)
    assert "primitives" in result
    assert isinstance(result["primitives"], list)


@pytest.mark.unit
async def test_list_primitives_each_entry_has_required_fields(
    server_with_tools: FastMCP,
) -> None:
    """Each primitive entry exposes name, description, and category."""
    from mahavishnu.mcp.tools.primitive_tools import list_primitives

    result = await list_primitives(server=server_with_tools)
    primitives = result["primitives"]

    assert len(primitives) >= 3
    for entry in primitives:
        assert "name" in entry, f"missing 'name' in {entry!r}"
        assert "description" in entry, f"missing 'description' in {entry!r}"
        assert "category" in entry, f"missing 'category' in {entry!r}"
        assert isinstance(entry["name"], str)
        assert isinstance(entry["description"], str)
        assert isinstance(entry["category"], str)


@pytest.mark.unit
async def test_list_primitives_includes_registered_tools(server_with_tools: FastMCP) -> None:
    """list_primitives includes the actual tools registered on the FastMCP server."""
    from mahavishnu.mcp.tools.primitive_tools import list_primitives

    result = await list_primitives(server=server_with_tools)
    names = {p["name"] for p in result["primitives"]}

    assert "alpha" in names
    assert "beta" in names
    assert "gamma" in names


@pytest.mark.unit
async def test_list_primitives_filter_by_category(server_with_tools: FastMCP) -> None:
    """Optional category filter narrows the result list."""
    from mahavishnu.mcp.tools.primitive_tools import list_primitives

    result_all = await list_primitives(server=server_with_tools)
    all_count = len(result_all["primitives"])

    # Filter by a category that nothing matches must return empty list
    result_none = await list_primitives(server=server_with_tools, category="no-such-category")
    assert result_none["primitives"] == []
    assert result_none["category_filter"] == "no-such-category"

    # Filter by a wildcard category must include everything
    result_wild = await list_primitives(server=server_with_tools, category="*")
    assert len(result_wild["primitives"]) == all_count


@pytest.mark.unit
async def test_show_primitive_returns_full_detail(server_with_tools: FastMCP) -> None:
    """show_primitive returns name, description, and input schema for a known tool."""
    from mahavishnu.mcp.tools.primitive_tools import show_primitive

    result = await show_primitive("alpha", server=server_with_tools)

    assert result["name"] == "alpha"
    assert result["description"] == "The alpha tool."
    assert "parameters" in result
    assert result["parameters"]["type"] == "object"
    assert "value" in result["parameters"]["properties"]


@pytest.mark.unit
async def test_show_primitive_unknown_tool_raises(server_with_tools: FastMCP) -> None:
    """show_primitive raises a clear error for unknown tool names."""
    from mahavishnu.core.errors import MahavishnuError
    from mahavishnu.mcp.tools.primitive_tools import show_primitive

    with pytest.raises(MahavishnuError) as exc_info:
        await show_primitive("does-not-exist", server=server_with_tools)

    # Error must mention the missing tool name so callers can act on it
    assert "does-not-exist" in str(exc_info.value)


@pytest.mark.unit
async def test_show_primitive_includes_docstring(server_with_tools: FastMCP) -> None:
    """show_primitive exposes the full docstring, not a truncated version."""
    from mahavishnu.mcp.tools.primitive_tools import show_primitive

    result = await show_primitive("beta", server=server_with_tools)

    assert result["description"] == "The beta tool with a default."


@pytest.mark.unit
async def test_show_primitive_handles_tool_without_parameters(
    server_with_tools: FastMCP,
) -> None:
    """show_primitive handles tools that take no arguments."""
    from mahavishnu.mcp.tools.primitive_tools import show_primitive

    result = await show_primitive("gamma", server=server_with_tools)

    assert result["name"] == "gamma"
    assert result["parameters"]["type"] == "object"
    assert result["parameters"]["properties"] == {}
