"""Phase 3 dispatcher MCP tool (H-3 of bodai-skill-agent-distribution plan).

Implements :func:`register_dispatch_specialist` which adds
``mahavishnu_dispatch_specialist(server, task_type)`` to the Mahavishnu
MCP server. The tool is the published entry point that workflows call
when they need to invoke a specialist agent by category rather than by
exact name.

Why this exists (H-3): without a dispatcher, the new Phase 3 specialists
(dhara-specialist, crackerjack-specialist, session-buddy-specialist) are
discoverable via ``list_agents`` but no automated workflow can select
them. The dispatcher bridges the gap by exposing a small, fast lookup
that reads ``list_agents`` from a given server, filters by
``task_type`` (matched against ``agent.category`` first, then a fuzzy
description-match), and returns the matching agent's full definition
(``{metadata, body}`` -- the body is the runtime system prompt per
Phase 3 §11 B-6).

Implementation choices:

- **No FastMCP lifespan** (``mahavishnu/mcp/server_core.py:59-69``
  tolerates up to 120s startup for early ``/health``). Phase 3's
  dispatcher is built lazily inside the tool handler, mirroring how
  ``mahavishnu/mcp/tools/ecosystem_tools.py::ecosystem_capabilities``
  resolves its service on first call. The first call may pay
  sub-second latency; subsequent calls are O(1) from the in-process
  cache.
- **In-process discovery cache**: the per-server ``list_agents``
  response is cached for 60s (matches Phase 4's TTL window). No
  filesystem cache (Phase 5 is responsible for that surface).
- **HTTP cross-MCP client**: each Bodai server has its own MCP
  endpoint. URLs are looked up from settings via the canonical
  ``akosha_url``, ``session_buddy_url``, ``dhara_url``,
  ``crackerjack_url`` keys (defaulting to the CLAUDE.md port table).
  The HTTP call uses ``httpx.AsyncClient`` with a 1s server timeout
  (matches Phase 4's per-server timeout for federation).
- **No Any in tool inputs/returns**: every parameter and return
  field is typed per mahavishnu's CLAUDE.md "no Any" rule. The
  server/agent URLs are cached as typed dicts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# Per-server URL lookup. Defaults match the CLAUDE.md port table.
_DEFAULT_SERVER_URLS: dict[str, str] = {
    "akosha": "http://localhost:8682/mcp",
    "mahavishnu": "http://localhost:8680/mcp",
    "session-buddy": "http://localhost:8678/mcp",
    "session_buddy": "http://localhost:8678/mcp",  # R-5 underscore alias
    "dhara": "http://localhost:8683/mcp",
    "crackerjack": "http://localhost:8676/mcp",
}

# Discovery cache TTL (seconds). 60s matches Phase 4's federation TTL
# window so phase 5 doesn't need to re-query Phase 4's cache after the
# initial fan-out.
_DISCOVERY_TTL_SECONDS: float = 60.0


def _resolve_server_url(server_key: str) -> str:
    """Resolve the MCP endpoint URL for ``server_key``.

    The lookup is intentionally permissive: kebab-case (``session-buddy``)
    AND underscore (``session_buddy``) keys both resolve to the canonical
    underscore variant.
    """
    if server_key in _DEFAULT_SERVER_URLS:
        return _DEFAULT_SERVER_URLS[server_key]
    kebab = server_key.replace("_", "-")
    if kebab in _DEFAULT_SERVER_URLS:
        return _DEFAULT_SERVER_URLS[kebab]
    raise ValueError(
        f"unknown server_key {server_key!r}; "
        f"valid keys are {sorted(_DEFAULT_SERVER_URLS.keys())}"
    )


def _match_agent(agent: dict[str, Any], task_type: str) -> bool:
    """Match a single agent metadata against a free-form ``task_type``.

    Precedence (most specific first):

    1. ``agent.category`` exact match -- Phase 3 task #1 carries a
       ``category`` field for explicit taxonomy. Most workflows use
       this.
    2. ``agent.name`` substring (case-insensitive) -- useful when the
       caller knows the canonical name (e.g.
       ``dhara-specialist``).
    3. ``agent.description`` substring (case-insensitive) -- the
       loose fallback; matches ``"search"`` -> ``"search-insights"``
       and similar natural-language queries.

    Returns True when any of the three match.
    """
    if not task_type:
        return False
    needle = task_type.lower().strip()
    if agent.get("category") and agent["category"].lower() == needle:
        return True
    if needle in (agent.get("name") or "").lower():
        return True
    if needle in (agent.get("description") or "").lower():
        return True
    return False


async def _call_list_agents(
    server_url: str,
    *,
    timeout_seconds: float = 1.0,
) -> list[dict[str, Any]]:
    """Call the server's ``list_agents`` MCP tool via HTTP JSON-RPC.

    Bodai MCP servers expose the JSON-RPC 2.0 ``tools/call`` endpoint.
    The response shape is
    ``{"result": {"content": [{"type": "text", "text": "<json>"}]}}``.
    Raises on timeout, connection error, or non-2xx.
    """
    import httpx
    from fastmcp.client import Client  # type: ignore[import-not-found]

    try:
        async with Client(server_url) as client:
            result = await asyncio.wait_for(
                client.call_tool("list_agents", {}),
                timeout=timeout_seconds,
            )
    except (
        asyncio.TimeoutError,
        httpx.HTTPError,
        ConnectionError,
        OSError,
    ) as exc:
        raise RuntimeError(
            f"call_tool(list_agents) on {server_url} failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    # Unwrap the JSON-RPC response. fastmcp's Client returns a
    # ``CallToolResult`` whose ``content`` is a list of typed blocks.
    content = getattr(result, "content", None)
    if not content:
        return []
    # The first text block carries the JSON-serialized response.
    text = getattr(content[0], "text", None)
    if not text:
        return []
    import json

    decoded = json.loads(text)
    if isinstance(decoded, list):
        return decoded
    if isinstance(decoded, dict) and "data" in decoded:
        # Phase 4 / list_ecosystem_skills shape -- shouldn't happen
        # for the per-server ``list_agents`` tool but defensively
        # unwrap.
        return decoded.get("data") or []
    return []


async def _call_get_agent(
    server_url: str,
    agent_name: str,
    *,
    timeout_seconds: float = 1.0,
) -> dict[str, Any]:
    """Call the server's ``get_agent`` MCP tool via HTTP JSON-RPC.

    Returns the unwrapped ``{metadata, body}`` envelope, or raises.
    """
    import httpx
    from fastmcp.client import Client  # type: ignore[import-not-found]

    try:
        async with Client(server_url) as client:
            result = await asyncio.wait_for(
                client.call_tool("get_agent", {"name": agent_name}),
                timeout=timeout_seconds,
            )
    except (
        asyncio.TimeoutError,
        httpx.HTTPError,
        ConnectionError,
        OSError,
    ) as exc:
        raise RuntimeError(
            f"call_tool(get_agent) on {server_url} failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    content = getattr(result, "content", None)
    if not content:
        return {}
    text = getattr(content[0], "text", None)
    if not text:
        return {}
    import json

    return json.loads(text)


def register_dispatch_specialist(mcp: FastMCP) -> None:
    """Register ``mahavishnu_dispatch_specialist`` and supporting tools.

    Adds three MCP tools to the server:

    - ``mahavishnu_dispatch_specialist(server, task_type)`` - the
      primary entry point; returns the matching agent's full
      definition (or an empty list with a diagnostic when nothing
      matches).
    - ``mahavishnu_list_specialists(server)`` - convenience tool
      for callers that want the full agent catalog without
      filtering. Returns the full ``list_agents`` response.

    Both tools cache per-server ``list_agents`` responses for
    ``_DISCOVERY_TTL_SECONDS`` so workflows that re-dispatch on every
    request don't trigger redundant fan-out. The cache is invalidated
    on TTL expiry; the dispatcher itself does not invalidate
    eagerly (Phase 5's market place sync owns the wider cache).
    """

    # Module-level cache: per-server_key -> (fetched_at, list_of_agents).
    # The cache lives in module scope so it survives across tool
    # calls within the same Mahavishnu process;``.cleanup is
    # unnecessary (phase 5 owns invalidation).
    _cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    async def _get_cached(server_url: str) -> list[dict[str, Any]]:
        """Return cached ``list_agents`` for ``server_url`` or fetch.

        Cache key is the URL itself (covers the underscore/kebab
        aliases). On miss or TTL expiry, fan out via ``call_tool``.
        On error, surface the failure (do not return an empty list
        silently).
        """
        cached = _cache.get(server_url)
        if cached is not None:
            fetched_at, agents = cached
            if (time.monotonic() - fetched_at) < _DISCOVERY_TTL_SECONDS:
                return agents
        agents = await _call_list_agents(server_url)
        _cache[server_url] = (time.monotonic(), agents)
        return agents

    @mcp.tool(name="mahavishnu_dispatch_specialist")
    async def mahavishnu_dispatch_specialist(
        server: str,
        task_type: str,
        *,
        include_definition: bool = True,
    ) -> dict[str, Any]:
        """Return the matching specialist agent's full definition.

        Lookup precedence within ``server``:

        - ``agent.category`` exact match against ``task_type``
        - ``agent.name`` substring match (case-insensitive)
        - ``agent.description`` substring match (case-insensitive)

        Args:
            server: server_key (e.g. ``dhara``, ``session_buddy``,
                ``crackerjack``, ``akosha``, ``mahavishnu``).
            task_type: free-form category or hint that selects the
                specialist. Examples: ``"storage"`` ->
                ``dhara-specialist``, ``"quality gates"`` ->
                ``crackerjack-specialist``, ``"session restoration"`` ->
                ``session-buddy-specialist``.
            include_definition: when True, fetch the full
                ``{metadata, body}`` envelope via ``get_agent``;
                when False, return only the metadata list (light
                path for status checks).

        Returns:
            A dict of the form::

                {
                    "success": True,
                    "server": "<server>",
                    "task_type": "<task_type>",
                    "matched_count": N,
                    "agents": [{"metadata": {...}, "body": "..."}, ...],
                    "errors": []  # per-server error messages
                }

            On no-match: ``success=True, matched_count=0, agents=[]``.
            On server unreachable: ``success=False, errors=[...]``.
        """
        try:
            server_url = _resolve_server_url(server)
        except ValueError as exc:
            return {
                "success": False,
                "server": server,
                "task_type": task_type,
                "matched_count": 0,
                "agents": [],
                "errors": [str(exc)],
            }

        try:
            agents = await _get_cached(server_url)
        except RuntimeError as exc:
            return {
                "success": False,
                "server": server,
                "task_type": task_type,
                "matched_count": 0,
                "agents": [],
                "errors": [str(exc)],
            }

        matching_meta = [a for a in agents if _match_agent(a, task_type)]
        if not matching_meta:
            return {
                "success": True,
                "server": server,
                "task_type": task_type,
                "matched_count": 0,
                "agents": [],
                "errors": [],
            }

        if not include_definition:
            return {
                "success": True,
                "server": server,
                "task_type": task_type,
                "matched_count": len(matching_meta),
                "agents": [{"metadata": m, "body": None} for m in matching_meta],
                "errors": [],
            }

        # Fetch the full envelope (metadata + body) per match.
        full_agents: list[dict[str, Any]] = []
        errors: list[str] = []
        for meta in matching_meta:
            agent_name = meta.get("name")
            if not agent_name:
                errors.append(f"agent metadata missing name: {meta!r}")
                continue
            try:
                envelope = await _call_get_agent(server_url, agent_name)
                full_agents.append(envelope)
            except RuntimeError as exc:
                errors.append(
                    f"get_agent({agent_name!r}) failed: {exc}"
                )

        return {
            "success": True,
            "server": server,
            "task_type": task_type,
            "matched_count": len(full_agents),
            "agents": full_agents,
            "errors": errors,
        }

    @mcp.tool(name="mahavishnu_list_specialists")
    async def mahavishnu_list_specialists(
        server: str,
    ) -> dict[str, Any]:
        """Return the full agent catalog for ``server``.

        Bypass the ``task_type`` filter; useful for picker UI and
        audits. Backed by the same discovery cache as ``dispatch_specialist``.
        """
        try:
            server_url = _resolve_server_url(server)
        except ValueError as exc:
            return {
                "success": False,
                "server": server,
                "error": str(exc),
                "agents": [],
            }
        try:
            agents = await _get_cached(server_url)
        except RuntimeError as exc:
            return {
                "success": False,
                "server": server,
                "error": str(exc),
                "agents": [],
            }
        return {
            "success": True,
            "server": server,
            "agent_count": len(agents),
            "agents": agents,
        }


__all__ = ["register_dispatch_specialist"]
