"""Ecosystem publish-URL MCP tool — sibling-tool for crackerjack's probe.

Crackerjack (sibling Bodai component) probes this tool at startup via
its layered publish-URL resolution. The probe is a JSON-RPC
``tools/call`` to Mahavishnu's MCP server; this module is the server
side.

The contract: ``get_publish_url(repo_path) -> str | None``. Path-matches
``repo_path`` against the ``path`` field of every entry in
``settings/ecosystem.yaml`` (resolved to absolute paths on both
sides), and returns ``publish.url`` for the matching repo, or
``None`` if no match. The tool is read-only and has no side effects.

Mirrors the sibling :mod:`mahavishnu.mcp.tools.ecosystem_state_tools`
shape: each tool is an inline ``async`` function so FastMCP's
``@mcp.tool()`` decorator can introspect the function name + signature
for the MCP tool schema. The leaf logic (path-matching + reading
ecosystem.yaml) lives in private helpers below for testability.

Auth: this is a public, read-only tool — no ``@require_mcp_auth`` gate
needed. The probe is invoked by sibling components during their own
startup; gating it would make crackerjack depend on a Mahavishnu
service account just to learn where to publish.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from oneiric.core.logging import get_logger
import yaml

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

logger = get_logger(__name__)


def _resolve_ecosystem_path() -> Path | None:
    """Find the canonical ecosystem.yaml path.

    Search order (first hit wins):
      1. ``$MAHAVISHNU_ECOSYSTEM_PATH`` env var (operator override)
      2. ``settings/ecosystem.yaml`` relative to ``Path.cwd()`` (the
         standard deployment layout where Mahavishnu is invoked from
         its own repo root)

    Returns ``None`` if neither path exists or is readable — the tool
    caller treats that as "no ecosystem registry available" and the
    probe soft-falls-back to defaults.
    """
    import os

    env_path = os.environ.get("MAHAVISHNU_ECOSYSTEM_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.is_file():
            return candidate

    cwd_candidate = Path.cwd() / "settings" / "ecosystem.yaml"
    if cwd_candidate.is_file():
        return cwd_candidate

    return None


def _load_publish_url(repo_path: str) -> str | None:
    """Read ecosystem.yaml and return the ``publish.url`` for ``repo_path``.

    Path matching is exact (``Path.resolve()`` on both sides) so a
    typo'd repo path can't silently route to a different repo. Returns
    ``None`` for: missing file, no matching entry, matched entry has
    no ``publish`` block, matched entry has ``publish.url: null`` or
    unset.

    Failures are swallowed and logged at DEBUG — the caller treats
    ``None`` as "no override" and falls back to defaults.
    """
    ecosystem_path = _resolve_ecosystem_path()
    if ecosystem_path is None:
        logger.debug(
            "ecosystem_publish_url: no ecosystem.yaml resolvable "
            "(MAHAVISHNU_ECOSYSTEM_PATH unset, settings/ecosystem.yaml missing)"
        )
        return None

    try:
        with ecosystem_path.open() as handle:
            data: Any = yaml.safe_load(handle)
    except (yaml.YAMLError, OSError) as exc:
        logger.debug(
            "ecosystem_publish_url: failed to read %s: %s",
            ecosystem_path,
            exc,
        )
        return None

    if not isinstance(data, dict):
        return None
    repos = data.get("repos")
    if not isinstance(repos, list):
        return None

    try:
        target_resolved = Path(repo_path).expanduser().resolve()
    except OSError, RuntimeError:
        return None

    for entry in repos:
        if not isinstance(entry, dict):
            continue
        entry_path_str = entry.get("path")
        if not isinstance(entry_path_str, str):
            continue
        try:
            entry_resolved = Path(entry_path_str).expanduser().resolve()
        except OSError, RuntimeError:
            continue
        if entry_resolved != target_resolved:
            continue

        publish = entry.get("publish")
        if not isinstance(publish, dict):
            return None
        url = publish.get("url")
        if isinstance(url, str) and url:
            return url
        return None

    return None


def register(mcp: FastMCP) -> None:
    """Register the ``mahavishnu_get_publish_url`` MCP tool with the FastMCP server.

    Tool name follows the existing ``mahavishnu_<verb>_<noun>`` convention
    used by sibling tools (e.g. ``mahavishnu_upsert_service``,
    ``mahavishnu_list_services``). FastMCP's ``@mcp.tool()`` decorator
    uses the function name as the registered tool name, so the
    sibling-side probe in
    ``crackerjack.services.mahavishnu_discovery.probe_publish_url``
    must call ``mahavishnu_get_publish_url`` to match.

    Called from ``mahavishnu.mcp.bootstrap._register_ecosystem_publish_url_tool``
    during profile-driven startup. Idempotent under FastMCP's decorator
    contract: re-registering replaces the prior binding.
    """

    @mcp.tool()
    async def mahavishnu_get_publish_url(repo_path: str) -> str | None:
        """Return the registered ``publish.url`` for ``repo_path``.

        Args:
            repo_path: Absolute path to the repo being published.
                Path-matched (via ``Path.resolve()``) against registered
                entries in ``settings/ecosystem.yaml``.

        Returns:
            The publish URL string (e.g.
            ``"https://gitlab.com/api/v4/projects/123/packages/pypi/upload"``),
            or ``None`` if no matching repo is registered or the
            matching entry has no ``publish.url``.

        Raises:
            Never. All failure modes (missing file, no match,
            malformed YAML, OS errors) return ``None`` by design —
            this is a soft-fallback probe consumed by sibling Bodai
            components at their startup. Sibling components that get
            ``None`` fall through to their default publish target.
        """
        return _load_publish_url(repo_path)


__all__ = ["register"]
