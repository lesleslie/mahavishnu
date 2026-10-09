"""Fleet-wide audit MCP tool — Phase 2 of MCP /health enrichment.

Calls ``GET /health`` on each Bodai core repo and reports the
silent-degraded case (HTTP 200 returned while the body claims
``status: degraded | failed``). This is the mcp-backend-wiring
gap the akosha ``cd4733b`` pilot surfaced fleet-wide: a server
that returns 200 even though its feeds are degraded, which fools
load balancers and operators alike.

Mirrors the sibling :mod:`mahavishnu.mcp.tools.health_tools`
shape: each tool is an inline ``async`` function so FastMCP's
``@mcp.tool()`` decorator can introspect the function name and
signature for the MCP tool schema. The leaf logic (HTTP fetch +
silent-degraded classification) lives in module-level coroutines
on :func:`audit_health_async` so it stays testable in isolation
without spinning up a FastMCP server.

Auth: this is a read-only probe — no ``@require_mcp_auth`` gate
needed. The audit is meant to be runnable from ``mahavishnu mcp
audit_health --all-repos`` by any operator or cron job, and the
5-core list is the canonical source of ports (mirrors
``CLAUDE.md``'s port table).

REQ-HC-004 (Phase 2) from
``docs/plans/2026-10-09-mcp-health-check-enrichment.md``:

- ``mahavishnu mcp audit_health --all-repos`` returns a JSON
  report listing per-repo status + silent-degraded flags.
- ``mcp__mahavishnu__audit_health()`` (MCP tool) returns the same
  envelope so callers don't care which surface they hit.
- Cadence: monthly, owned by the operator (see
  ``docs/operations/health-audit.md``).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any

import httpx2 as httpx
from oneiric.core.logging import get_logger
import yaml

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Bodai core repo port table (mirror CLAUDE.md "Ecosystem Context")
# ---------------------------------------------------------------------------
#
# Oneiric has no MCP server of its own (it's the foundation library
# the other 4 import from), so its port is ``None`` and the audit
# skips it with a ``skipped: True`` row. Keep this list and
# ``CLAUDE.md`` "Ecosystem Context" in sync.

BODAI_CORE_REPOS: dict[str, dict[str, Any]] = {
    "mahavishnu": {"host": "127.0.0.1", "port": 8680},
    "akosha": {"host": "127.0.0.1", "port": 8682},
    "crackerjack": {"host": "127.0.0.1", "port": 8676},
    "session-buddy": {"host": "127.0.0.1", "port": 8678},
    # Foundation library — no MCP server to probe.
    "oneiric": {"host": "127.0.0.1", "port": None},
}

DEFAULT_TIMEOUT_SECONDS = 5.0
HEALTH_PATH = "/health"

# Status values that count as "degraded-or-worse" for the
# silent-degraded classifier. ``WARMING_UP`` is intentionally NOT
# in this set — a fresh server returning 200 + WARMING_UP is
# serving traffic and should not be flagged.
SILENT_DEGRADED_STATUSES: frozenset[str] = frozenset({"degraded", "failed"})

# Status values that count as "healthy" for the aggregate count.
HEALTHY_STATUSES: frozenset[str] = frozenset({"healthy", "ok", "warming_up"})


def _is_silent_degraded(http_code: int | None, body_status: str | None) -> bool:
    """M6 contract: silent-degraded = http_code=200 AND body in {degraded, failed}.

    Addresses the M6 refuter concern — makes the silent-degraded
    classification a concrete predicate rather than a vibe check.
    A server that returns 200 while its body says it is degraded
    is the exact bug mcp-backend-wiring-discipline.md §"Audit
    cadence" warns about.
    """
    if http_code != 200:
        return False
    return body_status in SILENT_DEGRADED_STATUSES


def _resolve_ecosystem_path() -> Path | None:
    """Find the canonical ecosystem.yaml path.

    Search order (first hit wins):
      1. ``$MAHAVISHNU_ECOSYSTEM_PATH`` env var (operator override)
      2. ``settings/ecosystem.yaml`` relative to ``Path.cwd()`` (the
         standard deployment layout where Mahavishnu is invoked
         from its own repo root)

    Returns ``None`` if neither path is readable — the audit
    caller treats that as "no ecosystem registry available" and
    falls back to auditing all 5 core repos.
    """
    env_path = os.environ.get("MAHAVISHNU_ECOSYSTEM_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.is_file():
            return candidate

    cwd_candidate = Path.cwd() / "settings" / "ecosystem.yaml"
    if cwd_candidate.is_file():
        return cwd_candidate

    return None


def _load_ecosystem_repo_names() -> set[str]:
    """Return the set of ``name`` fields in settings/ecosystem.yaml.

    Used as a filter: only audit Bodai core repos that are also
    listed in the operator's ecosystem manifest. If the manifest
    is missing or empty, the caller falls back to all 5.
    """
    ecosystem_path = _resolve_ecosystem_path()
    if ecosystem_path is None:
        return set()

    try:
        with ecosystem_path.open() as handle:
            data: Any = yaml.safe_load(handle)
    except (yaml.YAMLError, OSError) as exc:
        logger.debug(
            "audit_health: failed to read %s: %s",
            ecosystem_path,
            exc,
        )
        return set()

    if not isinstance(data, dict):
        return set()

    repos_field = data.get("repos", [])
    if not isinstance(repos_field, list):
        return set()

    names: set[str] = set()
    for entry in repos_field:
        if isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    return names


async def audit_one_repo(
    name: str,
    host: str,
    port: int | None,
    *,
    path: str = HEALTH_PATH,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Probe a single repo's /health endpoint and return a per-repo row.

    Returns a dict with at minimum: ``repo``, ``host``, ``port``,
    ``silent_degraded`` (bool). HTTP-layer failures surface as
    ``http_code: None`` plus an ``error`` string — never raise —
    so the audit can always summarize a partial fleet.
    """
    if port is None:
        return {
            "repo": name,
            "host": host,
            "port": None,
            "skipped": True,
            "reason": "no port configured",
            "silent_degraded": False,
        }

    url = f"http://{host}:{port}{path}"
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
    except httpx.TimeoutException:
        return {
            "repo": name,
            "host": host,
            "port": port,
            "url": url,
            "http_code": None,
            "body_status": None,
            "error": "timeout",
            "silent_degraded": False,
        }
    except httpx.HTTPError as exc:
        return {
            "repo": name,
            "host": host,
            "port": port,
            "url": url,
            "http_code": None,
            "body_status": None,
            "error": f"{type(exc).__name__}: {exc}",
            "silent_degraded": False,
        }
    except Exception as exc:  # noqa: BLE001 - audit boundary absorbs all errors
        return {
            "repo": name,
            "host": host,
            "port": port,
            "url": url,
            "http_code": None,
            "body_status": None,
            "error": f"{type(exc).__name__}: {exc}",
            "silent_degraded": False,
        }

    elapsed_ms = round((time.time() - started) * 1000, 2)

    body_status: str | None = None
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 - opaque body, audit proceeds
            payload = None
        if isinstance(payload, dict):
            # Prefer canonical_status (Phase 1.1 addition) when present;
            # fall back to the legacy ``status`` field for repos that
            # have not yet adopted the mcp-common HealthSnapshot envelope.
            raw_status = payload.get("canonical_status")
            if not isinstance(raw_status, str):
                raw_status = payload.get("status")
            if isinstance(raw_status, str):
                body_status = raw_status

    return {
        "repo": name,
        "host": host,
        "port": port,
        "url": url,
        "http_code": response.status_code,
        "body_status": body_status,
        "latency_ms": elapsed_ms,
        "silent_degraded": _is_silent_degraded(response.status_code, body_status),
    }


async def audit_health_async(
    repos: list[str] | None = None,
    *,
    all_repos: bool = False,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Audit /health endpoints across Bodai core repos.

    Args:
        repos: Explicit subset of repo names to audit. Names not in
            :data:`BODAI_CORE_REPOS` are silently dropped (the audit
            is fleet-bounded — it does not probe arbitrary repos).
        all_repos: When ``True``, audit every entry in
            :data:`BODAI_CORE_REPOS` regardless of ``ecosystem.yaml``.
            Required for the monthly operator cadence.
        timeout: HTTP timeout per request in seconds.

    Returns:
        A dict with keys ``results`` (per-repo rows),
        ``total``, ``silent_degraded_count``, ``skipped_count``,
        ``healthy_count``, and ``degraded_count``. Designed to be
        JSON-serializable as-is for both the CLI's stdout and the
        MCP tool's response envelope.
    """
    if repos is not None:
        selected = [name for name in repos if name in BODAI_CORE_REPOS]
    elif all_repos:
        selected = list(BODAI_CORE_REPOS.keys())
    else:
        active = _load_ecosystem_repo_names()
        if not active:
            selected = list(BODAI_CORE_REPOS.keys())
        else:
            selected = [name for name in BODAI_CORE_REPOS if name in active]

    if not selected:
        return {
            "results": [],
            "total": 0,
            "silent_degraded_count": 0,
            "skipped_count": 0,
            "healthy_count": 0,
            "degraded_count": 0,
            "warning": "no repos selected for audit",
        }

    probes = [
        audit_one_repo(
            name,
            host=BODAI_CORE_REPOS[name]["host"],
            port=BODAI_CORE_REPOS[name]["port"],
            timeout=timeout,
        )
        for name in selected
    ]
    results = await asyncio.gather(*probes)

    silent_degraded_count = sum(1 for r in results if r.get("silent_degraded"))
    skipped_count = sum(1 for r in results if r.get("skipped"))
    healthy_count = sum(
        1 for r in results if r.get("http_code") == 200 and r.get("body_status") in HEALTHY_STATUSES
    )
    degraded_count = sum(
        1
        for r in results
        if r.get("http_code") == 200 and r.get("body_status") in SILENT_DEGRADED_STATUSES
    )

    return {
        "results": list(results),
        "total": len(results),
        "silent_degraded_count": silent_degraded_count,
        "skipped_count": skipped_count,
        "healthy_count": healthy_count,
        "degraded_count": degraded_count,
    }


def register_audit_health_tools(mcp: FastMCP, app: Any = None) -> None:
    """Register the ``mcp__mahavishnu__audit_health`` MCP tool.

    Args:
        mcp: FastMCP server instance
        app: Optional ``MahavishnuApp`` for dependency injection.
            Currently unused; kept for symmetry with
            :func:`mahavishnu.mcp.tools.health_tools.register_health_tools`.
    """

    @mcp.tool()
    async def audit_health(
        repos: list[str] | None = None,
        all_repos: bool = False,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Audit /health endpoints across Bodai core MCP servers.

        Calls ``GET /health`` on each of the 5 Bodai core repos
        (mahavishnu, akosha, crackerjack, session-buddy, oneiric)
        and reports the silent-degraded case — HTTP 200 returned
        while the body claims ``status: degraded | failed``. That
        case is the mcp-backend-wiring gap the akosha ``cd4733b``
        pilot surfaced fleet-wide.

        When ``repos`` is provided, only the named subset is
        audited. When ``all_repos`` is true, every entry in
        :data:`BODAI_CORE_REPOS` is probed regardless of
        ``settings/ecosystem.yaml``. Otherwise the audit is
        filtered to repos listed in the operator's ecosystem
        manifest (with a fallback to all 5 if the manifest is
        missing).

        Do NOT use for in-band health checks of a single repo —
        use ``mcp_test_connection`` (single) or
        ``health_check_all`` (configured dependencies). This tool
        is the fleet-wide monthly audit; it is not a hot-path
        probe.

        Returns:
            A JSON-serializable dict with per-repo rows + aggregate
            counters. ``silent_degraded_count > 0`` is the bug
            indicator the monthly cadence is looking for.
        """
        return await audit_health_async(
            repos=repos,
            all_repos=all_repos,
            timeout=timeout,
        )


__all__ = [
    "BODAI_CORE_REPOS",
    "DEFAULT_TIMEOUT_SECONDS",
    "HEALTHY_STATUSES",
    "HEALTH_PATH",
    "SILENT_DEGRADED_STATUSES",
    "audit_health_async",
    "audit_one_repo",
    "register_audit_health_tools",
]
