#!/usr/bin/env python3
"""Regenerate BODAI_REPO_REGISTRY.md from settings/ecosystem.yaml + settings/registry_metadata.yaml.

Authoritative source of repo catalog: settings/ecosystem.yaml
Authoritative source of registry annotations (phase, provenance, fastmcp_pin,
notes, exclusions): settings/registry_metadata.yaml
Generated doc: BODAI_REPO_REGISTRY.md

Run:
    python3 scripts/regen_bodai_registry.py [--check]

--check exits non-zero if the generated doc would differ from the current one
(useful as a CI gate to prevent hand edits from sneaking in).

Sections generated:
    1. Header + Discovery process (literal preamble)
    2. Core 7 (filtered from ecosystem.yaml: role == orchestrator OR name in core set)
    3. Web / framework libraries (role == foundation + framework transitive)
    4. Bodai MCP servers (role == tool + mcp != native)
    5. Extensions (role == extension)
    6. Desktop / GUI (role == app)
    7. Meta (role == orb | resolver | manager | seer | curator not in core)
    8. Deprecated / Archived (from overlay archived_repos)
    9. Per-project MCP server and agent scoping (literal; hand-maintained)
    10. Excluded from scope (from overlay excluded_repos)
    11. Summary counts (computed)
    12. Phase 4 (3.15) reuse footer

The generator intentionally does not write the "Per-project MCP server and
agent scoping" section or the "Phase 4 reuse" footer; those are hand-maintained
because they reference decisions that the generator cannot infer.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required. Install with: uv pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Repo -> section mapping
# ---------------------------------------------------------------------------
# NAME_SECTION overrides the role-based default. Use this for repos whose
# logical home in the registry differs from a naive role->section mapping.
# The Core 7 are listed explicitly. splashstand and excalidraw-mcp are
# logically MCP servers even though their roles are `app` and `visualizer`.
# The fastblocks transitives are listed under Web/framework though their
# roles are `extension` (they're conceptually part of fastblocks).

NAME_SECTION: dict[str, str] = {
    # Core 7 (streaming-tar rollout)
    "mcp-common": "core",
    "oneiric": "core",
    "dhara": "core",
    "session-buddy": "core",
    "akosha": "core",
    "crackerjack": "core",
    "mahavishnu": "core",
    # Web / framework libraries (the fastblocks cluster)
    "fastblocks": "web_framework",
    "fastblocks-ui": "web_framework",
    "jinja2-async-environment": "web_framework",
    "jinja2-inflection": "web_framework",
    "starlette-async-jinja": "web_framework",
    # MCP servers (overrides for visualizer + app roles)
    "excalidraw-mcp": "mcp_server",
    "splashstand": "mcp_server",
}

# Role-based default for repos not in NAME_SECTION
ROLE_SECTION: dict[str, str] = {
    "tool":         "mcp_server",
    "asset":        "web_framework",
    "extension":    "extensions",
    "app":          "desktop",
    "orb":          "meta",
    "builder":      "web_framework",
    "visualizer":   "extensions",
    # Roles that always go to core (rare; mostly covered by NAME_SECTION above)
    "orchestrator": "core",
    "seer":         "core",
    "curator":      "core",
    "inspector":    "core",
    "resolver":     "core",
    "foundation":   "core",
    "aggregator":   "core",
}


def resolve_section(name: str, role: str) -> str:
    """Section for a repo: explicit NAME_SECTION first, then role default, else 'meta'."""
    if name in NAME_SECTION:
        return NAME_SECTION[name]
    return ROLE_SECTION.get(role, "meta")

SECTION_ORDER: list[tuple[str, str]] = [
    ("core",          "Core 7 (in-scope for streaming tar Phase 3)"),
    ("web_framework", "Web / framework libraries"),
    ("mcp_server",    "Bodai MCP servers (standalone; per `bodai-mcp-servers-not-mycelium-core.md`)"),
    ("extensions",    "Extensions"),
    ("desktop",       "Desktop / GUI"),
    ("meta",          "Meta"),
]

# Core 7 explicit ordering (the streaming-tar rollout phases)
CORE_ORDER = [
    "mcp-common", "oneiric", "dhara", "session-buddy", "akosha",
    "crackerjack", "mahavishnu",
]


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def parse_requires_python(repo_path: str) -> str:
    """Read pyproject.toml head to extract requires-python. Fallback to 'n/a'."""
    pyp = Path(repo_path) / "pyproject.toml"
    if not pyp.is_file():
        return "n/a"
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return "n/a (pyproject.toml unreadable)"
    try:
        data = tomllib.loads(pyp.read_text())
    except Exception:
        return "n/a"
    proj = data.get("project", {})
    rp = proj.get("requires-python")
    return str(rp) if rp else "n/a"


def filter_active(repos: list[dict]) -> list[dict]:
    return [r for r in repos if r.get("status") == "active"]


def render_repo_row(repo: dict, overlay: dict) -> str:
    name = repo["name"]
    path = repo["path"] + "/"
    rp = parse_requires_python(repo["path"])
    notes_bits: list[str] = []
    o = overlay.get(name, {})
    if o.get("phase"):
        notes_bits.append(f"**{o['phase']}**")
    if o.get("registry_notes"):
        notes_bits.append(o["registry_notes"])
    if o.get("fastmcp_pin") and not o.get("phase"):
        notes_bits.append(f"FastMCP **{o['fastmcp_pin']}** as of {o.get('fastmcp_pin_as_of', 'unknown')}")
    if o.get("fastmcp_pin") and o.get("phase"):
        notes_bits.append(f"FastMCP **{o['fastmcp_pin']}** (`{o.get('fastmcp_pin_as_of', 'unknown')}`)")
    if not notes_bits:
        notes_bits.append(o.get("provenance", "active"))
    notes = ". ".join(notes_bits)
    return f"| {name} | {path} | {rp} | {notes} |"


def render_core_section(repos: list[dict], overlay: dict) -> str:
    by_name = {r["name"]: r for r in repos}
    out = ["### Core 7 (in-scope for streaming tar Phase 3)\n",
           "| Repo | Path | Current `requires-python` | Notes |",
           "|---|---|---|---|"]
    for name in CORE_ORDER:
        if name not in by_name:
            continue
        out.append(render_repo_row(by_name[name], overlay))
    out.append("")
    return "\n".join(out)


def render_section(title: str, repos: list[dict], overlay: dict) -> str:
    out = [f"### {title}\n",
           "| Repo | Path | Current `requires-python` | Notes |",
           "|---|---|---|---|"]
    for r in sorted(repos, key=lambda r: r["name"]):
        out.append(render_repo_row(r, overlay))
    out.append("")
    return "\n".join(out)


def render_archived_section(archived: dict) -> str:
    out = ["### Deprecated / Archived (moved to `~/Projects/ARCHIVED/`)\n",
           "| Repo | Archive path | `requires-python` | Notes |",
           "|---|---|---|---|"]
    for name in sorted(archived):
        info = archived[name]
        out.append(
            f"| {name} | {info.get('archive_path', 'n/a')} | n/a (archived) | {info.get('exclusion_reason', '')} |"
        )
    out.append("")
    return "\n".join(out)


def render_excluded_section(excluded: dict) -> str:
    out = ["## Excluded from scope (verified non-Bodai or non-Python)\n"]
    for name in sorted(excluded):
        info = excluded[name]
        out.append(f"- `{name}/` — {info.get('exclusion_reason', 'excluded')}")
        if info.get("removed_from_ecosystem_yaml"):
            out.append(f"  Removed from `settings/ecosystem.yaml` {info['removed_from_ecosystem_yaml']}.")
        if info.get("archive_path"):
            out.append(f"  Archived at: `{info['archive_path']}`.")
    out.append("")
    return "\n".join(out)


def render_summary(active: list[dict], overlay: dict) -> str:
    counts: dict[str, int] = {sec: 0 for sec, _ in SECTION_ORDER}
    counts["archived"] = len(overlay.get("archived_repos", {}))
    for r in active:
        sec = resolve_section(r["name"], r["role"])
        counts[sec] = counts.get(sec, 0) + 1
    total_active = sum(counts[s] for s, _ in SECTION_ORDER)
    out = ["## Summary counts\n"]
    for sec, title in SECTION_ORDER:
        out.append(f"- {title}: {counts[sec]}")
    out.append(f"- Deprecated/Archived: {counts['archived']}")
    out.append("")
    out.append(f"**Total active Bodai repos: {total_active}**")
    out.append("")
    return "\n".join(out)


def build_header(eco: dict, overlay: dict) -> str:
    last_updated = eco.get("last_updated", "unknown")
    maintainer = eco.get("maintainer", "unknown")
    return f"""# Bodai Repo Registry

Maintained by `{maintainer}` and the Bodai ecosystem. Authoritative source for
Python version coordination, dependency mapping, and Phase 4 (3.15) planning.

<!--
  ⚠️  THIS FILE IS GENERATED FROM settings/ecosystem.yaml + settings/registry_metadata.yaml.

  Regenerate with:    python3 scripts/regen_bodai_registry.py
  Drift check (CI):   python3 scripts/regen_bodai_registry.py --check

  Do NOT hand-edit the catalog tables below; edit the sources and regenerate.
  The "Per-project MCP server and agent scoping" section and the "Phase 4"
  footer are exempt from generation and may be edited by hand.
-->

## Discovery process (per Phase 0.0)

1. Read MEMORY.md for inventory hints (e.g., `bodai-mcp-servers-not-mycelium-core.md`)
1. `ls /Users/les/Projects/` for git repos
1. For each candidate, read `pyproject.toml` head; confirm Bodai-authored + Python-pinned
1. Document in [`settings/ecosystem.yaml`](settings/ecosystem.yaml) — the canonical source
1. Add registry-only annotations (Phase, FastMCP pin, provenance) to [`settings/registry_metadata.yaml`](settings/registry_metadata.yaml)
1. **Verification step** — every entry below is generated from the YAML files above; run `python3 scripts/regen_bodai_registry.py --check` to detect registry-vs-source drift.

A repo is **Bodai-maintained** if: (a) `pyproject.toml` exists, (b) author = `Les Leslie`
(variants: `les@wedgwoodwebworks.com`, `les@wedgwood.us`, `les@lesleslie.com`) or the
`fastblocks-ui.dev` team (a Bodai team alias), (c) `requires-python` is pinned to >=3.13
or higher.

## Confirmed Bodai repos (>=3.13 currently; bumping to >=3.14 in Phases 0.1–0.N)

"""


def build_footer() -> str:
    return """## Per-project MCP server and agent scoping

> Established 2026-08-24 per the post-audit architectural decision
> `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md`. Update
> this table whenever a project gains or loses MCP servers.

_(Hand-maintained. Not generated. See `settings/ecosystem.yaml` for the
authoritative per-project MCP server assignments.)_

## Phase 4 (3.15) reuse

This registry is the canonical list for Phase 4. When Phase 4 lands,
update the `Current requires-python` column to `>=3.14` and start
fresh dependency-ordered sequencing. Note that `mahavishnu` already
declares `>=3.13, <3.15` in its own `pyproject.toml`, so it will
need a top-of-stack bump alongside the Phase 4 rollout.

_(Hand-maintained footer. Not generated.)_
"""


def generate(ecosystem_path: Path, overlay_path: Path) -> str:
    eco = load_yaml(ecosystem_path)
    overlay = load_yaml(overlay_path)
    repos = filter_active(eco.get("repos", []))

    sections: list[str] = []
    sections.append(build_header(eco, overlay))

    # Core section
    sections.append(render_core_section(repos, overlay.get("repos", {})))

    # Bucket remaining active repos by section
    bucketed: dict[str, list[dict]] = {sec: [] for sec, _ in SECTION_ORDER}
    for r in repos:
        if r["name"] in CORE_ORDER:
            continue
        sec = resolve_section(r["name"], r["role"])
        bucketed[sec].append(r)

    for sec, title in SECTION_ORDER:
        if sec == "core":
            continue
        if bucketed[sec]:
            sections.append(render_section(title, bucketed[sec], overlay.get("repos", {})))

    # Archived (from overlay)
    archived = overlay.get("archived_repos", {})
    if archived:
        sections.append(render_archived_section(archived))

    summary = render_summary(repos, overlay)
    excluded = render_excluded_section(overlay.get("excluded_repos", {}))

    # Compose final: header, core section, other catalog sections, archived,
    # summary, footer, excluded.
    final = []
    final.append(build_header(eco, overlay))
    final.append(render_core_section(repos, overlay.get("repos", {})))
    for sec, title in SECTION_ORDER:
        if sec == "core":
            continue
        if bucketed[sec]:
            final.append(render_section(title, bucketed[sec], overlay.get("repos", {})))
    if archived:
        final.append(render_archived_section(archived))
    final.append(summary)
    final.append(build_footer())
    final.append(excluded)
    return "\n".join(final)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Exit non-zero if generated content differs from existing file")
    parser.add_argument("--ecosystem", default="settings/ecosystem.yaml",
                        help="Path to ecosystem.yaml")
    parser.add_argument("--overlay", default="settings/registry_metadata.yaml",
                        help="Path to registry_metadata.yaml")
    parser.add_argument("--output", default="BODAI_REPO_REGISTRY.md",
                        help="Path to write generated registry doc")
    args = parser.parse_args()

    eco = Path(args.ecosystem)
    overlay = Path(args.overlay)
    out = Path(args.output)
    if not eco.is_file():
        print(f"ERROR: {eco} not found", file=sys.stderr)
        return 2
    if not overlay.is_file():
        print(f"ERROR: {overlay} not found", file=sys.stderr)
        return 2

    content = generate(eco, overlay)

    if args.check:
        if out.is_file() and out.read_text() == content:
            print(f"OK: {out} matches generated content")
            return 0
        print(f"DRIFT: {out} differs from generated content; run without --check to regenerate")
        return 1

    out.write_text(content)
    print(f"Wrote {out} ({len(content.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
