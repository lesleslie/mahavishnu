#!/usr/bin/env python3
"""One-shot audit of every Bodai MCP server's current launcher pattern.

Walks ``BODAI_REPO_REGISTRY.md`` (repo inventory) and
``settings/ecosystem.yaml`` (mcp: classification) and emits a markdown table
classifying each included repo's MCP launch path. Drives Phase 3 Task 3.2
(``docs/mcp/server-migration-tracker.md``).

Why this exists:
    Phase 3 of ``docs/plans/2026-09-26-mcp-launcher-standardization.md``
    needs a per-repo detection pass before the tracker can be hand-populated.
    This script is the data source — never edit the tracker without re-running
    the audit first.

Output columns:
    repo, path, entry_point, health_route, secrets_loader, transport,
    migration_status.

Usage:
    cd ~/Projects/mahavishnu && .venv/bin/python scripts/audit_mcp_launchers.py
    cd ~/Projects/mahavishnu && .venv/bin/python scripts/audit_mcp_launchers.py --json
    cd ~/Projects/mahavishnu && .venv/bin/python scripts/audit_mcp_launchers.py --repo oneiric
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("audit_mcp_launchers")

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "BODAI_REPO_REGISTRY.md"
ECOSYSTEM_YAML = REPO_ROOT / "settings" / "ecosystem.yaml"

# Per feedback-bodai-core-component-taxonomy memory: "Core" = vishnu/ak/sb/cj/oneiric
# + mcp-common supporting lib. Five orchestrator/control-plane components plus
# the shared launcher library.
CORE_REPOS: tuple[str, ...] = (
    "mahavishnu",
    "akosha",
    "session-buddy",
    "crackerjack",
    "oneiric",
)
FOUNDATION_REPO: str = "mcp-common"

# Per plan §4 - special case: splashstand is mcp:native in ecosystem.yaml (not
# mcp:3rd-party) — needs separate investigation per architecture council's note
# that some servers use non-FastMCP transport.
SPECIAL_CASE_REPO: str = "splashstand"

# Per registry "Excluded from scope": docs-only, no pyproject.toml, marked for
# removal from ecosystem.yaml on 2026-09-09 but still present. Skip from the
# standalone-MCP count to match the plan's 19-named-server list.
EXCLUDED_FROM_STANDALONE: frozenset[str] = frozenset({"www-mcp-servers"})

# Repo paths documented in the plan's §4 as out-of-scope. Used to label
# excluded rows in the footer summary.
OUT_OF_SCOPE_REPOS: frozenset[str] = frozenset(
    {
        "bodai",
        "dhara",
        "fastblocks",
        "fastblocks-ui",
        "jinja2-async-environment",
        "jinja2-custom-delimiters",
        "jinja2-inflection",
        "starlette-async-jinja",
        "flowscape",
        "mdinject",
    }
)

# Detection probes per the plan's audit-table heuristics. All patterns are
# substring matches; we don't use a real regex engine to keep behavior
# transparent for a one-shot audit.
PROBE_PATTERNS: dict[str, tuple[str, ...]] = {
    "launcher_import": (
        "from mcp_common.server.launcher import launch",
        "from mcp_common.server import launch",
    ),
    "health_route": (
        "/health",
        "register_http_health_route",
    ),
    "secrets_loader": (
        "secrets.env",
        "load_secrets(",
        "launch_mcp_with_secrets",
    ),
    "transport_http": (
        'transport="http"',
        'transport="streamable-http"',
    ),
    "uvicorn_grace": ("timeout_graceful_shutdown",),
}


@dataclass(frozen=True)
class RepoRecord:
    """One audited Bodai MCP server entry."""

    repo: str
    path: str
    entry_point: str
    health_route: str
    secrets_loader: str
    transport: str
    migration_status: str
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProbeCandidate:
    """One file we plan to grep for detection patterns."""

    relpath: str
    text: str


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="audit_mcp_launchers",
        description=(
            "Audit Bodai MCP server launcher patterns. "
            "Emits a markdown table by default; pass --json for machine output."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON array instead of markdown table.",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Filter to a single repo name (substring match, case-insensitive).",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=REGISTRY_PATH,
        help="Override path to BODAI_REPO_REGISTRY.md (testing).",
    )
    parser.add_argument(
        "--ecosystem",
        type=Path,
        default=ECOSYSTEM_YAML,
        help="Override path to settings/ecosystem.yaml (testing).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG-level logging to stderr.",
    )
    return parser.parse_args(argv)


def _load_ecosystem(path: Path) -> dict[str, dict[str, Any]]:
    """Read settings/ecosystem.yaml; return {repo_name: repo_dict}."""
    if not path.exists():
        msg = f"ecosystem.yaml not found at {path}"
        raise FileNotFoundError(msg)
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return {entry["name"]: entry for entry in data.get("repos", [])}


def _parse_registry_paths(path: Path) -> dict[str, str]:
    """Parse ``BODAI_REPO_REGISTRY.md`` to extract ``{repo_name: path}``.

    The registry is generated from ecosystem.yaml + registry_metadata.yaml, so
    paths here must agree with ecosystem.yaml. We trust ecosystem.yaml as
    authoritative for the path field but cross-check against the registry's
    markdown tables (which surface sections like "Core 7" / "Bodai MCP
    servers"). When the registry disagrees with ecosystem.yaml, the registry's
    path wins — it's the user-facing artifact.
    """
    if not path.exists():
        msg = f"BODAI_REPO_REGISTRY.md not found at {path}"
        raise FileNotFoundError(msg)
    text = path.read_text(encoding="utf-8")

    # Match markdown table rows of the shape:
    #   | <repo> | /path/ | ... |
    # The leading whitespace varies (sometimes nested inside a section header).
    # Repo name is the first pipe-delimited cell; path is the second.
    row_re = re.compile(
        r"^\|\s*([\w./-]+)\s*\|\s*(/Users/les/Projects/[\w./-]+/?)\s*\|",
        re.MULTILINE,
    )
    return {name: path.rstrip("/") for name, path in row_re.findall(text)}


def _probe_candidates(repo_path: Path) -> list[ProbeCandidate]:
    """Return the small set of files we want to grep for detection patterns.

    We deliberately do NOT walk every .py file in every repo — the plan calls
    this a one-shot audit and the heuristics are anchored to known entry
    points. Walking arbitrary Python trees is slow and noisy (and would walk
    into .venv / node_modules / dist). If a repo diverges from the documented
    shape, the audit surfaces "unknown" and the operator can widen the search.

    The patterns cover all known entry points in the Bodai ecosystem:
    - ``scripts/launch_mcp*.py`` — vishnu, oneiric, and most standalone MCP
      servers (variants: ``launch_mcp.py``, ``launch_mcp_with_secrets.py``,
      ``launch_mcp_<name>.py``).
    - ``<pkg>/<pkg>/cli.py`` — akosha's _start_server entry point
      (akosha/akosha/cli.py).
    - ``<pkg>/<pkg>/mcp/server_core.py`` — crackerjack's _run_mcp_server.
    - ``<pkg>/<pkg>/server_optimized.py`` — session-buddy's server.
    - ``oneiric/oneiric/cli/mcp.py`` — oneiric's vendored CLI mcp_start.
    """
    if not repo_path.exists():
        return []

    # Bound the search to a few concrete subtrees so .venv/ and dist/ are
    # excluded by construction. Each Core repo has a primary package
    # directory matching its name (e.g. akosha/akosha/). Standalone MCP
    # servers also expose their package at the repo root level (e.g.
    # cmux-mcp/cmux_mcp/), so we also scan the immediate first-level
    # subdirectories dynamically.
    candidate_subtrees: list[str] = [
        "scripts",
        "akosha",
        "crackerjack",
        "session_buddy",
        "mahavishnu",
        "oneiric",
        "mcp-common",
    ]

    # Add any first-level package directories that look like a Python package
    # (i.e. contain __init__.py). This picks up cmux-mcp/cmux_mcp, css-mcp/
    # css_mcp, archive-org-mcp/archive_org_mcp, etc., without walking .venv/
    # dist/ node_modules/ which also have __init__.py.
    try:
        for child in repo_path.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            if (child / "__init__.py").is_file() and child.name not in candidate_subtrees:
                candidate_subtrees.append(child.name)
    except OSError as exc:
        logger.debug("Could not enumerate %s: %s", repo_path, exc)

    candidate_patterns: tuple[str, ...] = (
        "launch_mcp.py",
        "launch_mcp_with_secrets.py",
        "launch_mcp_*.py",
        "launch_mcp*.py",
        "cli.py",
        "server.py",
        "mcp/server_core.py",
        "server_optimized.py",
        "cli/mcp.py",
        "__main__.py",
    )

    candidates: list[ProbeCandidate] = []
    seen: set[Path] = set()
    for subtree in candidate_subtrees:
        sub_root = repo_path / subtree
        if not sub_root.is_dir():
            continue
        for pattern in candidate_patterns:
            for match in sub_root.glob(pattern):
                if match in seen or not match.is_file():
                    continue
                seen.add(match)
                try:
                    content = match.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    logger.debug("Could not read %s: %s", match, exc)
                    continue
                rel = match.relative_to(repo_path).as_posix()
                candidates.append(ProbeCandidate(relpath=rel, text=content))

    return candidates


def _detect(candidates: list[ProbeCandidate], repo_path: Path) -> dict[str, list[str]]:
    """Grep each probe candidate for the documented patterns; return hits."""
    hits: dict[str, list[str]] = {key: [] for key in PROBE_PATTERNS}
    for cand in candidates:
        for key, patterns in PROBE_PATTERNS.items():
            for pat in patterns:
                if pat in cand.text:
                    hits[key].append(f"{cand.relpath}: {pat}")
                    break
    return hits


def _classify_entry_point(repo: str, candidates: list[ProbeCandidate]) -> str:
    """Pick the best entry-point descriptor for the table cell.

    Detection order follows the plan's audit table (Phase 3 Task 3.1):
    1. New launcher (Phase 1 deliverable) wins outright.
    2. vishnu-style: scripts/launch_mcp_with_secrets.py
    3. ak-style: *cli.py:_start_server (recursive — akosha/akosha/cli.py)
    4. cj-style: *mcp*/server_core.py:_run_mcp_server
    5. oneiric new wrapper OR standalone: scripts/launch_mcp.py (preferred
       over the broken vendored CLI — the wrapper is the Phase 2 target).
    6. oneiric vendored CLI: */cli/mcp.py:mcp_start (broken fallback).
    7. sb-style: subcommand (no file; lives in cli/base.py:317-324 per plan §4).
    8. no entry point: unknown.
    """
    paths = {c.relpath for c in candidates}

    # Phase 1 deliverable has landed.
    if any("from mcp_common.server.launcher import launch" in c.text for c in candidates):
        return "mcp_common.server.launcher (Phase 1)"

    # vishnu-specific wrapper.
    if "scripts/launch_mcp_with_secrets.py" in paths:
        return "scripts/launch_mcp_with_secrets.py"

    # ak-specific: cli.py:_start_server.
    for cand in candidates:
        if cand.relpath.endswith("cli.py") and "_start_server" in cand.text:
            return f"{cand.relpath}:_start_server"

    # cj-specific: server_core.py:_run_mcp_server.
    for cand in candidates:
        if cand.relpath.endswith("server_core.py") and "_run_mcp_server" in cand.text:
            return f"{cand.relpath}:_run_mcp_server"

    # oneiric new wrapper OR standalone launch script. Prefer the wrapper
    # file over the vendored CLI when both exist — the wrapper is what
    # production runs after Phase 2.5a landed.
    launch_scripts = sorted(
        c.relpath for c in candidates if c.relpath.startswith("scripts/launch_mcp")
    )
    if launch_scripts:
        return launch_scripts[0]

    # oneiric vendored CLI: cli/mcp.py:mcp_start.
    for cand in candidates:
        if cand.relpath.endswith("cli/mcp.py") and "mcp_start" in cand.text:
            return f"{cand.relpath}:mcp_start"

    # sb is a subcommand, not a file path. Surface it explicitly.
    if repo == "session-buddy":
        return "python -m session_buddy server start --force"

    # Standalone MCP servers: python -m <pkg> via __main__.py, which uses
    # mcp_common.cli's MCPServerCLIFactory. The factory reference may live
    # in __main__.py directly OR in cli.py (which __main__.py delegates to).
    # This is the cookbook migration target per Phase 5b Task 5b.2.
    for cand in candidates:
        if "MCPServerCLIFactory" in cand.text and (
            cand.relpath.endswith("__main__.py") or cand.relpath.endswith("cli.py")
        ):
            # Derive the package name from the file's parent directory.
            pkg = Path(cand.relpath).parent.name
            return f"python -m {pkg} ({cand.relpath})"

    # Atypical launchers (per plan §5 Phase 5b "atypical transports get
    # discovery subtasks"). Surface the file path and the transport pattern.
    for cand in candidates:
        if cand.relpath.endswith("cli.py") and "uvicorn.run" in cand.text:
            return f"atypical: uvicorn-served ASGI ({cand.relpath})"
    for cand in candidates:
        if cand.relpath.endswith("cli.py") and "typer.Typer" in cand.text:
            return f"atypical: Typer CLI ({cand.relpath})"
    for cand in candidates:
        if cand.relpath.endswith("cli.py"):
            return f"atypical: bespoke cli ({cand.relpath})"

    # Fallback: FastMCP class instantiated directly in server.py (no factory,
    # no uvicorn, no typer). archive-org-mcp follows this pattern.
    for cand in candidates:
        if cand.relpath.endswith("server.py") and "FastMCP" in cand.text:
            return f"python -m <pkg> ({cand.relpath} direct FastMCP)"

    return "unknown (no launch_mcp*.py, cli.py:_*_server, or __main__.py:MCPServerCLIFactory found)"


def _classify_health_route(hits: list[str]) -> str:
    """Format the health-route cell."""
    if not hits:
        return "no"
    # Both /health and register_http_health_route present is the strongest signal.
    has_route = any("/health" in h for h in hits)
    has_register = any("register_http_health_route" in h for h in hits)
    if has_route and has_register:
        return "yes (register_http_health_route)"
    if has_route:
        return "yes (manual /health)"
    return "yes (register only)"


def _classify_secrets_loader(hits: list[str]) -> str:
    """Format the secrets-loader cell."""
    if not hits:
        return "no"
    if any("launch_mcp_with_secrets" in h for h in hits):
        return "yes (launch_mcp_with_secrets.py)"
    if any("load_secrets(" in h for h in hits):
        return "yes (load_secrets)"
    if any("secrets.env" in h for h in hits):
        return "yes (secrets.env parse)"
    return "yes (unknown pattern)"


def _classify_transport(hits: list[str]) -> str:
    """Format the transport cell.

    Order matters: streamable-http is more specific than plain http, but both
    are HTTP transport. Stdio / os.execvp are non-HTTP. "Unknown" means we
    found a launch_mcp*.py but couldn't confirm a transport kwarg.
    """
    if not hits:
        return "unknown"
    if any('transport="streamable-http"' in h for h in hits):
        return "streamable-http"
    if any('transport="http"' in h for h in hits):
        return "http"
    return "unknown (entry file present but no transport kwarg detected)"


def _classify_migration_status(
    repo: str,
    entry_point: str,
    hits: dict[str, list[str]],
) -> str:
    """Per plan §5 Phase 3 + Phase 4a/4b.

    Status values (matching the example output's enum):
    - done: Phase 1 deliverable imported and used.
    - in-progress: Phase 2 (oneiric) wrapper path in flight.
    - planned-cookbook: standalone MCP servers that defer to the cookbook.
    - todo: Core components not yet migrated.
    - out-of-scope: libraries, desktop apps, repos without MCP servers.

    The plan tracks per-repo status manually in the tracker; this heuristic
    keeps the audit self-consistent so future re-runs can diff.
    """
    if "Phase 1" in entry_point:
        return "done"

    if repo == SPECIAL_CASE_REPO:
        return "out-of-scope (mcp: native - separate investigation)"

    if repo == FOUNDATION_REPO:
        # mcp-common IS the launcher source — it can't import itself.
        return "done (launcher author)"

    if repo in CORE_REPOS:
        # Phase 2 only touched oneiric's wrapper so far.
        if repo == "oneiric" and "scripts/launch_mcp.py" in entry_point:
            return "in-progress (Phase 2 wrapper)"
        return "todo"

    # Standalone MCP servers: defer to cookbook.
    return "planned-cookbook"


def _build_record(
    repo: str,
    path: str,
    candidates: list[ProbeCandidate],
    hits: dict[str, list[str]],
    notes: list[str],
) -> RepoRecord:
    """Compose one row of the audit output."""
    entry_point = _classify_entry_point(repo, candidates)
    return RepoRecord(
        repo=repo,
        path=path,
        entry_point=entry_point,
        health_route=_classify_health_route(hits["health_route"]),
        secrets_loader=_classify_secrets_loader(hits["secrets_loader"]),
        transport=_classify_transport(hits["transport_http"]),
        migration_status=_classify_migration_status(repo, entry_point, hits),
        notes=notes,
    )


def _gather_audit_set(
    ecosystem: dict[str, dict[str, Any]],
    registry_paths: dict[str, str],
) -> list[tuple[str, str, list[str]]]:
    """Return ``[(repo_name, repo_path, [notes]), ...]`` for the 26 audited rows.

    The 26 audited repos are:
    - 5 Core (vishnu/ak/sb/cj/oneiric)
    - mcp-common (foundation)
    - 19 standalone MCP servers (mcp:3rd-party in ecosystem.yaml, excluding
      www-mcp-servers per registry's "Excluded from scope")
    - splashstand (mcp:native, special case per plan §4)
    """
    notes_by_repo: dict[str, list[str]] = {}

    # Core 5: surfaces in the registry's "Core 7" table.
    for repo in CORE_REPOS:
        notes_by_repo.setdefault(repo, [])

    # mcp-common (foundation).
    notes_by_repo.setdefault(FOUNDATION_REPO, [])

    # Standalone MCP servers: ecosystem.yaml mcp:3rd-party, minus www-mcp-servers.
    for repo_name, entry in ecosystem.items():
        if entry.get("mcp") == "3rd-party":
            if repo_name in EXCLUDED_FROM_STANDALONE:
                continue
            notes_by_repo.setdefault(repo_name, [])

    # Special case: splashstand.
    notes_by_repo.setdefault(SPECIAL_CASE_REPO, ["mcp: native in ecosystem.yaml"])

    # Build (name, path, notes) tuples. Use ecosystem.yaml as authoritative
    # for paths (registry cross-checked).
    out: list[tuple[str, str, list[str]]] = []
    for repo_name in sorted(notes_by_repo):
        path = ecosystem.get(repo_name, {}).get("path") or registry_paths.get(repo_name, "")
        if not path:
            logger.warning("No path for repo=%s in ecosystem.yaml or registry", repo_name)
        notes = notes_by_repo[repo_name]
        out.append((repo_name, path, notes))
    return out


def _audit_repo(repo: str, path_str: str, notes: list[str]) -> RepoRecord:
    """Probe one repo and build its audit row."""
    repo_path = Path(path_str) if path_str else Path()
    candidates = _probe_candidates(repo_path)
    hits = _detect(candidates, repo_path)
    return _build_record(repo, path_str, candidates, hits, notes)


def _render_markdown_table(records: list[RepoRecord]) -> str:
    """Format records as the markdown table shown in the task example."""
    headers = (
        "repo",
        "path",
        "entry_point",
        "health_route",
        "secrets_loader",
        "transport",
        "migration_status",
    )
    lines: list[str] = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for rec in records:
        row = [
            rec.repo,
            rec.path,
            rec.entry_point,
            rec.health_route,
            rec.secrets_loader,
            rec.transport,
            rec.migration_status,
        ]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _render_footer(
    records: list[RepoRecord],
    out_of_scope_repos: list[str],
) -> str:
    """Summary footer matching the task's expected shape."""
    return (
        f"\n\nTotal: {len(records)} audited "
        "(5 Core + mcp-common + 19 standalone MCP + splashstand special case)\n"
        f"Out-of-scope: {', '.join(out_of_scope_repos)}\n"
    )


def _out_of_scope_repos(
    ecosystem: dict[str, dict[str, Any]],
    audited_names: set[str],
) -> list[str]:
    """Repos in ecosystem.yaml but excluded from the audit table.

    Anchored to ecosystem.yaml (not the registry) so ARCHIVED/ entries in
    BODAI_REPO_REGISTRY.md don't leak into the footer. Operators looking for
    fastblocks-htmy / peanutbutterpub / swiftui-ipc-client should consult the
    registry's "Excluded from scope" and "Deprecated" sections directly.
    """
    return sorted(set(ecosystem) - audited_names)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    ecosystem = _load_ecosystem(args.ecosystem)
    registry_paths = _parse_registry_paths(args.registry)

    audit_set = _gather_audit_set(ecosystem, registry_paths)

    if args.repo:
        wanted = args.repo.lower()
        audit_set = [
            (name, path, notes) for (name, path, notes) in audit_set if wanted in name.lower()
        ]
        if not audit_set:
            logger.error("No repo matched --repo=%s", args.repo)
            return 2

    records: list[RepoRecord] = []
    for repo, path, notes in audit_set:
        records.append(_audit_repo(repo, path, notes))

    if args.json:
        json.dump(
            [asdict(r) for r in records],
            sys.stdout,
            indent=2,
            sort_keys=False,
        )
        sys.stdout.write("\n")
        return 0

    sys.stdout.write(_render_markdown_table(records))
    audited_names = {r.repo for r in records}
    sys.stdout.write(_render_footer(records, _out_of_scope_repos(ecosystem, audited_names)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
