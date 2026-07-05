"""MCP tools for introspecting registered primitives.

Provides ``list_primitives`` and ``show_primitive`` MCP tools that let
callers enumerate and inspect the tools exposed by a Mahavishnu MCP server.
This is the in-house analog of Keystone's ``keystone_show`` /
``keystone_list_primitives`` pattern, applied to the Mahavishnu MCP surface.

The term *primitive* here means any MCP tool registered on a FastMCP server
instance -- it does not refer to a Keystone-style composed rule primitive
(which does not exist in Mahavishnu today).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mahavishnu.core.errors import ErrorCode, MahavishnuError

if TYPE_CHECKING:
    from fastmcp import FastMCP


# Names that are themselves meta-tools for introspecting primitives. We
# exclude them from category="primitives" results to avoid showing a tool
# that lists itself.
_PRIMITIVE_TOOL_NAMES: frozenset[str] = frozenset({"list_primitives", "show_primitive"})


def _categorize_tool(name: str) -> str:
    """Return a stable category string for a tool name.

    The category is derived from the leading underscore-separated segment of
    the tool name when present (e.g. ``pool_execute`` -> ``pool``,
    ``terminal_launch`` -> ``terminal``); otherwise the tool is bucketed
    under ``core``. ``list_primitives`` and ``show_primitive`` are
    bucketed under ``primitives``.
    """
    if name in _PRIMITIVE_TOOL_NAMES:
        return "primitives"
    if "_" in name:
        return name.split("_", 1)[0]
    return "core"


async def _fetch_tools(server: FastMCP) -> list[Any]:
    """Return the list of FastMCP ``Tool`` objects on ``server``.

    Uses the FastMCP 3.x public ``list_tools`` async API. Returns an empty
    list when the call raises -- callers must not crash because introspection
    failed.
    """
    try:
        tools = await server.list_tools()
    except Exception:  # noqa: BLE001 - introspection must never raise
        return []
    return list(tools)


async def list_primitives(
    server: FastMCP,
    category: str | None = None,
) -> dict[str, Any]:
    """List all primitives (MCP tools) registered on ``server``.

    Args:
        server: FastMCP server instance whose tools should be enumerated.
        category: Optional category filter; use ``"*"`` to match any tool,
            or a specific category name. ``None`` returns all primitives.

    Returns:
        Dict with keys:
            ``primitives``: list of dicts with ``name``, ``description``,
            ``category``.
            ``total_count``: total primitives matching the filter.
            ``category_filter``: echo of the ``category`` arg.
    """
    tools = await _fetch_tools(server)

    entries: list[dict[str, Any]] = []
    for tool in tools:
        name = getattr(tool, "name", None)
        if not isinstance(name, str) or not name:
            continue
        description = getattr(tool, "description", "") or ""
        entries.append(
            {
                "name": name,
                "description": description,
                "category": _categorize_tool(name),
            }
        )

    if category is not None and category != "*":
        entries = [e for e in entries if e["category"] == category]

    entries.sort(key=lambda e: e["name"])

    return {
        "primitives": entries,
        "total_count": len(entries),
        "category_filter": category,
    }


async def show_primitive(name: str, server: FastMCP) -> dict[str, Any]:
    """Show full detail for one primitive.

    Args:
        name: Tool name (must match a registered primitive).
        server: FastMCP server instance to inspect.

    Returns:
        Dict with ``name``, ``description``, ``category``, ``parameters``
        (JSON Schema for the tool's input), and ``title``.

    Raises:
        MahavishnuError: When ``name`` is not a registered tool.
    """
    tools = await _fetch_tools(server)

    match: Any | None = None
    for tool in tools:
        if getattr(tool, "name", None) == name:
            match = tool
            break

    if match is None:
        raise MahavishnuError(
            message=f"Primitive {name!r} is not registered on this MCP server",
            error_code=ErrorCode.CONFIGURATION_ERROR,
            recovery=[
                "Call list_primitives() to discover available primitive names",
                "Verify the tool name spelling and casing",
            ],
            details={"primitive_name": name},
        )

    parameters = getattr(match, "parameters", {}) or {}
    if not isinstance(parameters, dict):
        parameters = {}

    return {
        "name": getattr(match, "name", name),
        "title": getattr(match, "title", None),
        "description": getattr(match, "description", "") or "",
        "category": _categorize_tool(name),
        "parameters": parameters,
    }


def register_primitive_tools(mcp: FastMCP) -> None:
    """Register ``list_primitives`` and ``show_primitive`` MCP tools.

    These two tools enable Keystone-style introspection of the Mahavishnu
    MCP surface: callers can enumerate registered primitives and fetch
    full schema + docstring for any one of them. Both tools introspect
    ``mcp`` itself via the FastMCP public ``list_tools`` API, so they
    automatically reflect whatever tools have been registered up to that
    point.

    Args:
        mcp: FastMCP server instance to register the tools on.
    """

    @mcp.tool()
    async def list_primitives_tool(
        category: str | None = None,
    ) -> dict[str, Any]:
        """List primitives (MCP tools) registered on this server.

        Args:
            category: Optional category filter; use ``"*"`` to match any
                tool, or a specific category such as ``"pool"``,
                ``"worker"``, ``"terminal"``, or ``"core"``.

        Returns:
            Dict containing ``primitives`` (list of ``{name, description,
            category}`` entries), ``total_count``, and ``category_filter``.
        """
        return await list_primitives(server=mcp, category=category)

    @mcp.tool()
    async def show_primitive_tool(name: str) -> dict[str, Any]:
        """Show full detail (docstring + input schema) for one primitive.

        Args:
            name: Name of a registered MCP tool.

        Returns:
            Dict with ``name``, ``title``, ``description``, ``category``,
            and ``parameters`` (JSON Schema for the tool's input).

        Raises:
            MahavishnuError: If ``name`` is not a registered tool.
        """
        return await show_primitive(name=name, server=mcp)


__all__ = ["list_primitives", "show_primitive", "register_primitive_tools"]
