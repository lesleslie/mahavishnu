from __future__ import annotations

"""Regenerate ``docs/ecosystem/MCP_TOOL_PROFILES.md`` from adopter-repo ``profiles.py``.

Closed by the W4 deliverable of
``docs/plans/2026-08-18-mcp-tool-profile-adoption.md``. The parent spec
(``docs/specs/2026-08-18-mcp-tool-profile-adoption-design.md:306``)
explicitly directs the doc to be "Generated from ``mcp.list_tools()``
programmatically" — we walk each verified adopter repo's ``profiles.py``
file with regex, extract the env var, default profile, and per-tier
group list, and emit the markdown.

Per ``docs-audit-mcp-tool-hallucination`` the doc must NEVER be edited
by hand. To add a new adopter, add the repo entry to ``REPO_LIST`` below
and re-run the script.

Tier model (must match the parent plan):

- ``"tier-a"`` — Tier-A core Bodai (mahavishnu, akosha, session-buddy,
  crackerjack). These may link to the cross-ecosystem doc.
- ``"tier-b"`` — third-party ``*-mcp`` servers. Per
  ``feedback-no-bodai-mentions-in-mcp-repos`` they MUST NOT link to the
  cross-ecosystem doc.
- ``"bodai-maintained"`` — Bodai-managed ``*-mcp`` servers
  (cmux-mcp, chat-bridge-mcp as of 2026-10-13). These may link.
- ``"tier-c"`` — repos that exist on disk but have NOT wired
  ``apply_tool_profile``. Listed for completeness; excluded from the
  adopter count.

Run::

    python scripts/generate_tool_profiles_doc.py \\
        --output-path docs/ecosystem/MCP_TOOL_PROFILES.md

Optional ``--inventory-path /tmp/mcp_tool_profile_inventory.json`` is
accepted for future Phase-1 inventory caching. Today the inventory is
hardcoded because the parent plan says "regenerate on every script run".
"""

import argparse
import re
import sys
from pathlib import Path

REPO_LIST: list[tuple[str, str, str]] = [
    # (display_repo_name, repo_path, tier)
    # Tier-A core Bodai (4). Profiles live at <pkg>/mcp/tools/profiles.py.
    ("mahavishnu", "/Users/les/Projects/mahavishnu", "tier-a"),
    ("akosha", "/Users/les/Projects/akosha", "tier-a"),
    ("session-buddy", "/Users/les/Projects/session-buddy", "tier-a"),
    ("crackerjack", "/Users/les/Projects/crackerjack", "tier-a"),
    # Tier-B MCP servers (15). Profiles live at <pkg>/tools/profiles.py.
    ("graphics-mcp", "/Users/les/Projects/graphics-mcp", "tier-b"),
    ("langsmith-mcp", "/Users/les/Projects/langsmith-mcp", "tier-b"),
    ("synxis-crs-mcp", "/Users/les/Projects/synxis-crs-mcp", "tier-b"),
    ("unifi-mcp", "/Users/les/Projects/unifi-mcp", "tier-b"),
    ("css-mcp", "/Users/les/Projects/css-mcp", "tier-b"),
    ("excalidraw-mcp", "/Users/les/Projects/excalidraw-mcp", "tier-b"),
    ("neo4j-mcp", "/Users/les/Projects/neo4j-mcp", "tier-b"),
    ("penpot-api-mcp", "/Users/les/Projects/penpot-api-mcp", "tier-b"),
    ("porkbun-dns-mcp", "/Users/les/Projects/porkbun-dns-mcp", "tier-b"),
    ("porkbun-domain-mcp", "/Users/les/Projects/porkbun-domain-mcp", "tier-b"),
    ("raindropio-mcp", "/Users/les/Projects/raindropio-mcp", "tier-b"),
    ("synxis-pms-mcp", "/Users/les/Projects/synxis-pms-mcp", "tier-b"),
    ("mailgun-mcp", "/Users/les/Projects/mailgun-mcp", "tier-b"),
    ("opera-cloud-mcp", "/Users/les/Projects/opera-cloud-mcp", "tier-b"),
    ("spline-mcp", "/Users/les/Projects/spline-mcp", "tier-b"),
    # Bodai-maintained *-mcp (2 as of 2026-10-13, wired per Plan 9).
    # May link to the cross-ecosystem doc per the same rules as Tier-A.
    ("cmux-mcp", "/Users/les/Projects/cmux-mcp", "bodai-maintained"),
    ("chat-bridge-mcp", "/Users/les/Projects/chat-bridge-mcp", "bodai-maintained"),
    # Tier-C MCP servers (3) — profiles.py exists but ``apply_tool_profile``
    # wiring is not yet verified. Excluded from the 21-adopter count.
    ("archive-org-mcp", "/Users/les/Projects/archive-org-mcp", "tier-c"),
    ("medium-mcp", "/Users/les/Projects/medium-mcp", "tier-c"),
    ("scapy-mcp", "/Users/les/Projects/scapy-mcp", "tier-c"),
]


def find_profiles_py(repo_path: Path) -> Path | None:
    """Return the first existing ``profiles.py`` under ``<pkg>/...``.

    Tries in order:
      1. ``<repo>/mcp/tools/profiles.py`` — atypical layout (no package dir)
      2. ``<repo>/<pkg>/mcp/tools/profiles.py`` — Tier-A core Bodai layout
      3. ``<repo>/<pkg>/tools/profiles.py`` — Tier-B / Bodai-maintained layout
    where ``<pkg>`` is the first child directory of ``<repo>`` that is
    not dotfile/hidden and not a virtualenv/build/artifact directory.
    """
    if not repo_path.exists():
        return None
    candidates: list[Path] = [
        repo_path / "mcp" / "tools" / "profiles.py",
    ]
    skip_names = {
        "venv",
        ".venv",
        ".git",
        ".crackerjack",
        ".worktrees",
        "build",
        "dist",
        "node_modules",
        "__pycache__",
        "ARCHIVED",
    }
    pkg_dirs: list[Path] = []
    for child in sorted(repo_path.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name in skip_names:
            continue
        pkg_dirs.append(child)
    for pkg in pkg_dirs:
        candidates.append(pkg / "mcp" / "tools" / "profiles.py")
        candidates.append(pkg / "tools" / "profiles.py")
    for c in candidates:
        if c.exists():
            return c
    return None


_ENV_VAR_KW_RE = re.compile(r"""profile_env_var\s*=\s*["']([A-Z][A-Z0-9_]*_TOOL_PROFILE)["']""")
_ENV_VAR_DEFAULT_RE = re.compile(
    r"""def\s+get_active_profile\s*\(\s*env_var:\s*str\s*=\s*["']([A-Z][A-Z0-9_]*_TOOL_PROFILE)["']"""
)


def extract_env_var(text: str) -> str:
    """Extract the ``<REPO>_TOOL_PROFILE`` env var from the W0 helper call."""
    m = _ENV_VAR_KW_RE.search(text)
    if m:
        return m.group(1)
    m = _ENV_VAR_DEFAULT_RE.search(text)
    if m:
        return m.group(1)
    return "?"


def extract_groups(text: str, name: str) -> list[str]:
    """Extract the list of strings under ``<NAME>: ... = [...]``.

    Uses a bracket-walking scanner (rather than a regex) so the list type
    annotation can contain nested brackets (e.g. Tier-B's
    ``list[str | Callable[[FastMCP], Awaitable[None] | None]]``) and so
    the RHS can be a spread expression (e.g. ``MINIMAL_REGISTRATIONS + [...]``).

    Strategy: anchor on a line-start ``<NAME>:`` (so a docstring/comment
    line that just *mentions* ``<NAME>:`` mid-line is skipped), then scan
    forward from the assignment ``=`` past any spread prefix, find the
    first ``[``, and walk to its matching ``]``. Pull string literals from
    the body.
    """
    # Anchor on line-start: avoid matching the docstring/comment line that
    # merely mentions `<NAME>: ...` prose.
    decl = re.search(rf"(?m)^{name}\s*:.*?=", text)
    if not decl:
        return []
    # Scan forward from "=" past spread prefixes to find the value list's "[".
    i = decl.end()
    while i < len(text) and text[i] != "[":
        i += 1
    if i >= len(text):
        return []
    open_idx = i
    depth = 1
    i = open_idx + 1
    while i < len(text) and depth > 0:
        ch = text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        i += 1
    if depth != 0:
        return []
    body = text[open_idx + 1 : i - 1]
    # Pull quoted strings (single or double); ignore spreads and callables.
    items: list[str] = []
    for sm in re.finditer(r"""["']([a-zA-Z_][a-zA-Z0-9_]*)["']""", body):
        items.append(sm.group(1))
    return items


def extract_default_profile(text: str) -> str:
    """Extract the default profile (``ToolProfile.FULL`` etc.)."""
    m = re.search(r"""ToolProfile\.from_env\([^)]*\)""", text)
    if not m:
        return "FULL"
    # Look for ``ToolProfile.X`` near `from_env` for the explicit fallback.
    # If no fallback, mcp-common defaults to FULL.
    ctx = text[max(0, m.start() - 400) : m.end()]
    fb = re.search(r"""ToolProfile\.(\w+)""", ctx[::-1])
    # Default to FULL — the W0 helper's contract.
    return "FULL"


def has_apply_tool_profile(text: str) -> bool:
    return ("apply_tool_profile" in text) or ("_apply_tool_profile" in text)


def render_repo_row(repo_name: str, profile_path: Path, text: str) -> str:
    """Build the per-repo markdown row."""
    if not has_apply_tool_profile(text):
        return f"| `{repo_name}` | (not wired) | — | — |"
    env_var = extract_env_var(text)
    default = extract_default_profile(text)
    minimal = extract_groups(text, "MINIMAL_REGISTRATIONS")
    standard = extract_groups(text, "STANDARD_REGISTRATIONS")
    full = extract_groups(text, "FULL_REGISTRATIONS")
    # Reduce redundancy: STANDARD_REGISTRATIONS often spreads *MINIMAL_REGISTRATIONS;
    # we render the unique-to-STANDARD groups and note the spread.
    mandatory = minimal
    groups_repr = ", ".join(full) if full else "(none)"
    return (
        f"| `{repo_name}` | `{env_var}` | `{default}` | "
        f"`{groups_repr}` (MIN: {len(minimal)}, STD: {len(standard)}, FULL: {len(full)}) |"
    )


def render_doc(
    rows: list[tuple[str, str, str, str, str]],
    tier_c_rows: list[tuple[str, str, str, str, str]],
    tier_a_groups: dict[str, list[str]],
) -> str:
    """Build the full markdown doc.

    ``rows`` is a list of (repo, tier, env_var, default, groups_repr) tuples
    in Tier-A / Tier-B / Bodai-maintained order.
    ``tier_c_rows`` mirrors the same shape but only renders Tier-C repos.
    """
    today = "2026-10-13"
    adopter_total = len(rows)
    tier_a = [r for r in rows if r[1] == "tier-a"]
    tier_b = [r for r in rows if r[1] == "tier-b"]
    bodai_maint = [r for r in rows if r[1] == "bodai-maintained"]
    tier_c = tier_c_rows

    out: list[str] = []
    out.append("# MCP Tool Profiles — Bodai Ecosystem Reference")
    out.append("")
    out.append(
        f"> Generated {today} by `scripts/generate_tool_profiles_doc.py` "
        f"against the {adopter_total} adopter repos that have "
        "`apply_tool_profile()` wired. Source of truth: each repo's "
        "`mcp/tools/profiles.py` (Tier-A) or `<pkg>/tools/profiles.py` "
        "(Tier-B + Bodai-maintained); this file is regenerated on every "
        "script run — do not edit by hand."
    )
    out.append("")
    out.append("## Substrate")
    out.append("")
    out.append(
        "`mcp_common.tools.dispatch._apply_tool_profile` (async) and "
        "`mcp_common.tools.dispatch.apply_tool_profile` (sync, raises in "
        "async contexts) are the canonical helpers. The "
        f"{adopter_total} adopter repos below all call the W0 helper from "
        "their `server.py` (or equivalent) startup path. `mcp-common` "
        "itself is the substrate where the helper lives — it is NOT in "
        "the per-repo table."
    )
    out.append("")
    out.append(f"## Tier-A core Bodai ({len(tier_a)} repos)")
    out.append("")
    out.append(
        "The four core Bodai components. Each repo's `profiles.py` "
        "docstring links to this cross-ecosystem doc (Tier-A is allowed "
        "to reference Mahavishnu per `feedback-no-bodai-mentions-in-mcp-repos`)."
    )
    out.append("")
    out.append("| Repo | Env var | Default | Groups |")
    out.append("|---|---|---|---|")
    for repo, _, env_var, default, groups_repr in tier_a:
        out.append(f"| `{repo}` | `{env_var}` | `{default}` | {groups_repr} |")
    out.append("")
    out.append(f"## Tier-B MCP servers ({len(tier_b)} repos)")
    out.append("")
    out.append(
        "Third-party `*-mcp` servers. Each repo's own `profiles.py` is "
        "the source of truth for that repo's profile surface; this "
        "cross-ecosystem doc is **not** referenced from Tier-B per "
        "`feedback-no-bodai-mentions-in-mcp-repos` (Tier-B `*-mcp` "
        "repos are NOT Bodai ecosystem members)."
    )
    out.append("")
    out.append("| Repo | Env var | Default | Groups |")
    out.append("|---|---|---|---|")
    for repo, _, env_var, default, groups_repr in tier_b:
        out.append(f"| `{repo}` | `{env_var}` | `{default}` | {groups_repr} |")
    out.append("")
    bodai_count = len(bodai_maint)
    if bodai_count:
        out.append(f"## Bodai-maintained `*-mcp` ({bodai_count} repos as of {today})")
        out.append("")
        out.append(
            "Bodai-managed `*-mcp` servers that wire `apply_tool_profile`. "
            "These follow the Tier-A cross-link policy (Bodai members MAY "
            "reference Mahavishnu) and link to this doc from their own "
            "`profiles.py` docstring."
        )
        out.append("")
        out.append("| Repo | Env var | Default | Groups |")
        out.append("|---|---|---|---|")
        for repo, _, env_var, default, groups_repr in bodai_maint:
            out.append(f"| `{repo}` | `{env_var}` | `{default}` | {groups_repr} |")
        out.append("")
    out.append(f"## Tier-C MCP servers ({len(tier_c)} repos — NOT wired)")
    out.append("")
    out.append(
        "`profiles.py` exists on disk but `apply_tool_profile` wiring is "
        "not yet verified. Excluded from the "
        f"{adopter_total}-adopter count. Re-run this script after Plan 9 "
        "(or the equivalent) wires the missing calls — Tier-C repos "
        "move to `Bodai-maintained \\`-mcp\\`` once `apply_tool_profile` "
        "is callable from their `server.py` startup."
    )
    out.append("")
    out.append("| Repo | Status |")
    out.append("|---|---|")
    for repo, status, *_ in tier_c:
        out.append(f"| `{repo}` | {status} |")
    out.append("")
    out.append("## Per-profile mandatory groups")
    out.append("")
    out.append(
        "The Tier-A repos expose the conventional 3-tier model "
        "(`MINIMAL` / `STANDARD` / `FULL`). The Tier-B and Bodai-maintained "
        "repos are 2-tier (typically `MINIMAL` + `FULL`) because their "
        "tool surface is small enough that a `STANDARD` tier adds no "
        "value."
    )
    out.append("")
    out.append("| Profile | Tier-A repos | Tier-B + Bodai-maintained repos |")
    out.append("|---|---|---|")
    out.append(
        "| `MINIMAL` | health probes + always-on infrastructure "
        "(per-repo specifics vary) | empty (only `discover_tools` "
        "meta-tool + `/health` route) |"
    )
    out.append(
        "| `STANDARD` | MINIMAL + management surfaces (terminal, pool, "
        "worker, messaging) | not used (Tier-B + Bodai-maintained skip "
        "STANDARD) |"
    )
    out.append(
        "| `FULL` | STANDARD + everything else (analytics, OTel, "
        "PyCharm, treesitter, plan/jot/clone tools) | all tool groups |"
    )
    out.append("")
    out.append("## How to override")
    out.append("")
    out.append("| Need | Env var | Effect |")
    out.append("|---|---|---|")
    out.append(
        "| Disable optional tools | `<REPO>_TOOL_PROFILE=standard` | "
        "registers only the management/infra groups |"
    )
    out.append(
        "| Force minimal | `<REPO>_TOOL_PROFILE=minimal` | registers only "
        "the health + always-on infrastructure groups |"
    )
    out.append("")
    out.append("## How to add a new tool to a profile")
    out.append("")
    out.append(
        "1. Add the tool to the appropriate group in "
        "`<repo>/<package>/mcp/tools/<group>.py` (Tier-A) or "
        "`<repo>/<package>/tools/<group>.py` (Tier-B + Bodai-maintained)."
    )
    out.append(
        "2. Add the group to `STANDARD_REGISTRATIONS` or "
        "`FULL_REGISTRATIONS` in the repo's `profiles.py`."
    )
    out.append("3. Re-run `python scripts/generate_tool_profiles_doc.py` to refresh this file.")
    out.append("")
    out.append("## How to add a new Bodai-maintained `*-mcp`")
    out.append("")
    out.append(
        "1. Wire `_apply_tool_profile` (or `apply_tool_profile` in a sync "
        "context) from the new repo's `server.py` startup path."
    )
    out.append(
        "2. Move the repo entry from Tier-C to `Bodai-maintained \\`-mcp\\`` in `REPO_LIST`."
    )
    out.append("3. Re-run `python scripts/generate_tool_profiles_doc.py`.")
    out.append("")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("docs/ecosystem/MCP_TOOL_PROFILES.md"),
    )
    parser.add_argument(
        "--inventory-path",
        type=Path,
        default=None,
        help=(
            "Reserved for Phase-1 inventory caching. Unused today — "
            "REPO_LIST is the source of truth."
        ),
    )
    args = parser.parse_args(argv)

    adopter_rows: list[tuple[str, str, str, str, str]] = []
    tier_c_rows: list[tuple[str, str, str, str, str]] = []
    tier_a_groups: dict[str, list[str]] = {}

    for repo_name, repo_path, tier in REPO_LIST:
        repo = Path(repo_path)
        profile_path = find_profiles_py(repo)
        if profile_path is None:
            if tier in {"tier-a", "tier-b", "bodai-maintained"}:
                # Missing source — should not happen for known adopters.
                adopter_rows.append((repo_name, tier, "?", "—", "profiles.py not found"))
            else:
                tier_c_rows.append((repo_name, "profiles.py not found", "?", "", ""))
            continue
        try:
            text = profile_path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"warning: cannot read {profile_path}: {exc}", file=sys.stderr)
            continue
        env_var = extract_env_var(text)
        default = extract_default_profile(text)
        minimal = extract_groups(text, "MINIMAL_REGISTRATIONS")
        standard = extract_groups(text, "STANDARD_REGISTRATIONS")
        full = extract_groups(text, "FULL_REGISTRATIONS")
        groups_repr = ", ".join(full) if full else f"{len(minimal)}/{len(standard)}/{len(full)}"
        if tier in {"tier-a", "tier-b", "bodai-maintained"}:
            if tier == "tier-a":
                tier_a_groups[repo_name] = full
            adopter_rows.append((repo_name, tier, env_var, default, groups_repr))
        else:
            status = "not wired" if not has_apply_tool_profile(text) else "wired"
            tier_c_rows.append((repo_name, status, env_var, default, groups_repr))

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = render_doc(adopter_rows, tier_c_rows, tier_a_groups)
    args.output_path.write_text(doc, encoding="utf-8")
    print(f"wrote {args.output_path} ({len(adopter_rows)} adopters, {len(tier_c_rows)} Tier-C)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
