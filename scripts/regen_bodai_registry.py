#!/usr/bin/env python3
"""Regenerate BODAI_REPO_REGISTRY.md from settings/ecosystem.yaml + settings/registry_metadata.yaml.

Authoritative source of repo catalog: settings/ecosystem.yaml
Authoritative source of registry annotations (phase, provenance, fastmcp_pin,
notes, exclusions): settings/registry_metadata.yaml
Authoritative source of per-machine registry entries (excluded_repos +
archived_repos): settings/registry_metadata.local.yaml (gitignored; merged
into the overlay at render time when present).
Generated doc: BODAI_REPO_REGISTRY.md

Run:
    python3 scripts/regen_bodai_registry.py [--check]

--check exits non-zero if the generated doc would differ from the current one
(useful as a CI gate to prevent hand edits from sneaking in).

Sections generated:
    1. Header + Discovery process (literal preamble)
    2. Core 6 (filtered from ecosystem.yaml: the ADR 019 fleet release set)
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
from collections import Counter
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required. Install with: uv pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Projects root
# ---------------------------------------------------------------------------
# This repo is public, so the published registry must not contain absolute
# paths: they would disclose the operator's account name and local directory
# layout to anyone who clones the repo.
#
# Every repo path in the catalog is therefore rendered *relative* to a
# "projects root" -- the directory that holds the fleet checkouts -- and the
# generated document declares how a consumer resolves that root back to a
# directory on disk.
#
# The root is *inferred* from the catalog's own geometry (the parent shared
# by the most repos) rather than configured, so the generator stays
# deterministic and needs no machine-specific setup. A repo that does not
# live under the inferred root falls back to its directory name alone, which
# leaks nothing.
#
# PROJECTS_ROOT_ENV_VAR is the consumer-side override: a machine whose
# checkouts live somewhere else sets it to point at its own root. The
# generator deliberately ignores it -- the catalog's geometry is the ground
# truth of where the repos are.

PROJECTS_ROOT_ENV_VAR = "BODAI_PROJECTS_ROOT"


def infer_projects_root(paths: Sequence[str]) -> Path | None:
    """Infer the projects root that holds the fleet checkouts.

    Returns the parent directory shared by the *most* repo paths. Using the
    mode rather than the common ancestor matters: one stray repo kept
    elsewhere must not drag the root up to the home directory, because the
    rendered relative paths would then re-disclose the account name.
    """
    parents = Counter(str(Path(p).parent) for p in paths)
    if not parents:
        return None
    root, _count = parents.most_common(1)[0]
    return Path(root)


def render_repo_path(repo_path: str, root: Path | None) -> str:
    """Render a repo path for the published registry.

    Root-relative when the repo lives under the inferred root; otherwise the
    directory name alone, so a repo kept outside the root can never leak the
    layout that holds it.
    """
    candidate = Path(repo_path)
    if root is not None:
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            pass
        else:
            return f"{relative.as_posix()}/"
    return f"{candidate.name}/"


# ---------------------------------------------------------------------------
# Repo -> section mapping
# ---------------------------------------------------------------------------
# NAME_SECTION overrides the role-based default. Use this for repos whose
# logical home in the registry differs from a naive role->section mapping.
# The Core 6 are listed explicitly. splashstand and excalidraw-mcp are
# logically MCP servers even though their roles are `app` and `visualizer`.
# The fastblocks transitives are listed under Web/framework though their
# roles are `extension` (they're conceptually part of fastblocks).

NAME_SECTION: dict[str, str] = {
    # Core 6 (streaming-tar rollout)
    "mcp-common": "core",
    "oneiric": "core",
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
    "tool": "mcp_server",
    "asset": "web_framework",
    "extension": "extensions",
    "app": "desktop",
    "orb": "meta",
    "builder": "web_framework",
    "visualizer": "extensions",
    # Roles that always go to core (rare; mostly covered by NAME_SECTION above)
    "orchestrator": "core",
    "seer": "core",
    "curator": "core",
    "inspector": "core",
    "resolver": "core",
    "foundation": "core",
    "aggregator": "core",
}


def resolve_section(name: str, role: str) -> str:
    """Section for a repo: explicit NAME_SECTION first, then role default, else 'meta'."""
    if name in NAME_SECTION:
        return NAME_SECTION[name]
    return ROLE_SECTION.get(role, "meta")


SECTION_ORDER: list[tuple[str, str]] = [
    ("core", "Core 6 (in-scope for streaming tar Phase 3)"),
    ("web_framework", "Web / framework libraries"),
    ("mcp_server", "Bodai MCP servers (standalone; per `bodai-mcp-servers-not-mycelium-core.md`)"),
    ("extensions", "Extensions"),
    ("desktop", "Desktop / GUI"),
    ("meta", "Meta"),
]

# Core 6 explicit ordering (the streaming-tar rollout phases).
# This is the fleet release-probe set defined by ADR 019
# (docs/adr/019-dhara-decommissioning.md): mahavishnu, akosha, session-buddy,
# crackerjack, oneiric, mcp-common -- six repos, not seven.
CORE_ORDER = [
    "mcp-common",
    "oneiric",
    "session-buddy",
    "akosha",
    "crackerjack",
    "mahavishnu",
]


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def merge_overlay_with_local(
    overlay: dict[str, Any],
    local_overlay_path: Path | None,
) -> dict[str, Any]:
    """Merge per-machine registry overlay (gitignored) into the tracked overlay.

    Local entries win on conflict for the two per-machine keys
    (``excluded_repos``, ``archived_repos``). All other overlay keys
    (``repos``, ``phase_order``, etc.) come from the tracked file unchanged.

    If ``local_overlay_path`` is None or the file doesn't exist, the overlay
    is returned unchanged (fresh-clone behavior).
    """
    if local_overlay_path is None or not local_overlay_path.is_file():
        return overlay
    local = load_yaml(local_overlay_path) or {}
    merged = dict(overlay)
    for key in ("excluded_repos", "archived_repos"):
        merged[key] = {**(overlay.get(key) or {}), **(local.get(key) or {})}
    return merged


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


def filter_active(repos: list[dict], excluded: Collection[str] = ()) -> list[dict]:
    """Keep the active repos that are not excluded.

    A repo named in the overlay's ``excluded_repos`` is dropped even when the
    per-machine catalog still lists it as active. The registry's own stated
    criterion is that a Bodai repo has a ``pyproject.toml``; a repo that
    fails it must not appear in the active tables *and* in the Excluded
    section at the same time.
    """
    excluded_names = set(excluded)
    return [r for r in repos if r.get("status") == "active" and r["name"] not in excluded_names]


def render_repo_row(repo: dict, overlay: dict, root: Path | None) -> str:
    name = repo["name"]
    path = render_repo_path(repo["path"], root)
    rp = parse_requires_python(repo["path"])
    notes_bits: list[str] = []
    o = overlay.get(name, {})
    if o.get("phase"):
        notes_bits.append(f"**{o['phase']}**")
    if o.get("registry_notes"):
        notes_bits.append(o["registry_notes"])
    if o.get("fastmcp_pin") and not o.get("phase"):
        notes_bits.append(
            f"FastMCP **{o['fastmcp_pin']}** as of {o.get('fastmcp_pin_as_of', 'unknown')}"
        )
    if o.get("fastmcp_pin") and o.get("phase"):
        notes_bits.append(
            f"FastMCP **{o['fastmcp_pin']}** (`{o.get('fastmcp_pin_as_of', 'unknown')}`)"
        )
    if not notes_bits:
        notes_bits.append(o.get("provenance", "active"))
    notes = ". ".join(notes_bits)
    return f"| {name} | {path} | {rp} | {notes} |"


def bucket_repos(repos: list[dict]) -> dict[str, list[dict]]:
    """Group the active repos into the sections the registry renders.

    The core section is driven by ``CORE_ORDER`` (the streaming-tar rollout
    order) and the remaining sections by name. Bucketing once and sharing it
    between the renderer and the summary keeps the two from disagreeing
    about how many repos the registry lists.
    """
    by_name = {r["name"]: r for r in repos}
    bucketed: dict[str, list[dict]] = {sec: [] for sec, _ in SECTION_ORDER}
    for name in CORE_ORDER:
        if name in by_name:
            bucketed["core"].append(by_name[name])
    for r in repos:
        if r["name"] in CORE_ORDER:
            continue
        sec = resolve_section(r["name"], r["role"])
        bucketed[sec].append(r)
    return bucketed


def render_core_section(core_repos: list[dict], overlay: dict, root: Path | None) -> str:
    out = [
        "### Core 6 (in-scope for streaming tar Phase 3)\n",
        "| Repo | Path | Current `requires-python` | Notes |",
        "|---|---|---|---|",
    ]
    for repo in core_repos:
        out.append(render_repo_row(repo, overlay, root))
    out.append("")
    return "\n".join(out)


def render_section(title: str, repos: list[dict], overlay: dict, root: Path | None) -> str:
    out = [
        f"### {title}\n",
        "| Repo | Path | Current `requires-python` | Notes |",
        "|---|---|---|---|",
    ]
    for r in sorted(repos, key=lambda r: r["name"]):
        out.append(render_repo_row(r, overlay, root))
    out.append("")
    return "\n".join(out)


def render_archived_section(archived: dict, root: Path | None) -> str:
    out = [
        "### Deprecated / Archived (moved to `~/Projects/ARCHIVED/`)\n",
        "| Repo | Archive path | `requires-python` | Notes |",
        "|---|---|---|---|",
    ]
    for name in sorted(archived):
        info = archived[name]
        archive_path = info.get("archive_path")
        rendered = render_repo_path(archive_path, root) if archive_path else "n/a"
        out.append(f"| {name} | {rendered} | n/a (archived) | {info.get('exclusion_reason', '')} |")
    out.append("")
    return "\n".join(out)


def render_excluded_section(excluded: dict, root: Path | None) -> str:
    out = ["## Excluded from scope (not a fleet member)\n"]
    for name in sorted(excluded):
        info = excluded[name]
        out.append(f"- `{name}/` — {info.get('exclusion_reason', 'excluded')}")
        if info.get("removed_from_ecosystem_yaml"):
            out.append(
                f"  Removed from `settings/ecosystem.yaml` {info['removed_from_ecosystem_yaml']}."
            )
        if info.get("archive_path"):
            rendered = render_repo_path(info["archive_path"], root)
            out.append(f"  Archived at: `{rendered}`.")
    out.append("")
    return "\n".join(out)


def render_summary(bucketed: dict[str, list[dict]], overlay: dict) -> str:
    """Summarize the repos the registry actually lists.

    The counts come from the same buckets the renderer uses, so the summary
    can never disagree with the tables above it.
    """
    counts: dict[str, int] = {sec: len(bucketed.get(sec, [])) for sec, _ in SECTION_ORDER}
    counts["archived"] = len(overlay.get("archived_repos", {}))
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

## Path resolution

The `Path` column is **relative to the projects root** — the directory that
holds the fleet checkouts. No absolute path appears in this file, so it is
machine-independent and safe to publish.

Resolve the projects root in this order:

1. `${PROJECTS_ROOT_ENV_VAR}` — explicit override.
1. The parent of this repository — this file lives at
   `<projects root>/mahavishnu/BODAI_REPO_REGISTRY.md`.
1. `~/Projects` — the standard developer layout.

A repo's location is then `<projects root>/<Path column>`.

## Discovery process (per Phase 0.0)

1. Read MEMORY.md for inventory hints (e.g., `bodai-mcp-servers-not-mycelium-core.md`)
1. `ls ~/Projects/` for git repos
1. For each candidate, read `pyproject.toml` head; confirm Bodai-authored + Python-pinned
1. Document in `settings/ecosystem.yaml` (gitignored per-machine catalog) — copy [`settings/ecosystem.yaml.example`](settings/ecosystem.yaml.example) and populate
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
> `docs/decisions/2026-08-24-bodai-mcp-routing-pattern.md`. Update
> this table whenever a project gains or loses MCP servers.

_(Hand-maintained. Not generated. See `settings/ecosystem.yaml` (gitignored
per-machine) for the authoritative per-project MCP server assignments; the
[`settings/ecosystem.yaml.example`](settings/ecosystem.yaml.example) template
documents the schema.)_

## Phase 4 (3.15) reuse

This registry is the canonical list for Phase 4. When Phase 4 lands,
update the `Current requires-python` column to `>=3.14` and start
fresh dependency-ordered sequencing. Note that `mahavishnu` already
declares `>=3.13, <3.15` in its own `pyproject.toml`, so it will
need a top-of-stack bump alongside the Phase 4 rollout.

_(Hand-maintained footer. Not generated.)_
"""


def generate(
    ecosystem_path: Path,
    overlay_path: Path,
    local_overlay_path: Path | None = None,
) -> str:
    eco = load_yaml(ecosystem_path)
    overlay = load_yaml(overlay_path)
    overlay = merge_overlay_with_local(overlay, local_overlay_path)
    excluded_repos = overlay.get("excluded_repos", {})
    repos = filter_active(eco.get("repos", []), excluded_repos)

    # The projects root is inferred from the catalog's own geometry so the
    # published paths stay relative (and leak-free). See the "Projects root"
    # section above.
    root = infer_projects_root([r["path"] for r in repos])

    # Bucket the active repos into the sections the registry renders.
    bucketed = bucket_repos(repos)

    # Compose final: header, core section, other catalog sections, archived,
    # summary, footer, excluded.
    final = []
    final.append(build_header(eco, overlay))
    final.append(render_core_section(bucketed["core"], overlay.get("repos", {}), root))
    for sec, title in SECTION_ORDER:
        if sec == "core":
            continue
        if bucketed[sec]:
            final.append(render_section(title, bucketed[sec], overlay.get("repos", {}), root))
    archived = overlay.get("archived_repos", {})
    if archived:
        final.append(render_archived_section(archived, root))
    final.append(render_summary(bucketed, overlay))
    final.append(build_footer())
    final.append(render_excluded_section(excluded_repos, root))
    return "\n".join(final)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if generated content differs from existing file",
    )
    parser.add_argument(
        "--ecosystem", default="settings/ecosystem.yaml", help="Path to ecosystem.yaml"
    )
    parser.add_argument(
        "--overlay",
        default="settings/registry_metadata.yaml",
        help="Path to registry_metadata.yaml",
    )
    parser.add_argument(
        "--local-overlay",
        default="settings/registry_metadata.local.yaml",
        help="Path to per-machine registry overlay (gitignored). Skipped if absent.",
    )
    parser.add_argument(
        "--output", default="BODAI_REPO_REGISTRY.md", help="Path to write generated registry doc"
    )
    args = parser.parse_args()

    eco = Path(args.ecosystem)
    overlay = Path(args.overlay)
    local_overlay = Path(args.local_overlay)
    out = Path(args.output)
    if not eco.is_file():
        # settings/ecosystem.yaml is gitignored (per-machine catalog);
        # fall back to the committed .example so the script still works
        # in fresh clones and CI. The link rendered in the generated
        # markdown always points to the .example (see build_header /
        # build_footer) so markdown link-checkers can resolve the
        # target regardless of the operator's local ecosystem.yaml.
        example = eco.with_name(eco.name + ".example")
        if example.is_file():
            print(
                f"NOTE: {eco} not found; falling back to {example}",
                file=sys.stderr,
            )
            eco = example
        else:
            print(f"ERROR: {eco} not found (and no {example} template)", file=sys.stderr)
            return 2
    if not overlay.is_file():
        print(f"ERROR: {overlay} not found", file=sys.stderr)
        return 2

    content = generate(eco, overlay, local_overlay)

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
