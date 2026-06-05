#!/usr/bin/env python3
"""Audit the ``.gitignore`` files of every Bodai ecosystem repo.

A new contributor (or a stale Claude Code session) can drop runtime
artifacts into a repo's ``.claude/`` directory — handoff reports,
``settings.local.json``, worktree helpers, etc. — and the right
``.gitignore`` rule depends on whether ``.claude/`` is being used to
hold *project content* (the agent catalog, command library, etc.) or
*runtime state* (per-machine config).

This script walks every ecosystem repo, classifies its ``.claude/``
directory, and asserts the ``.gitignore`` has the right rule in the
right place. It does **not** auto-fix; it's an audit.

The classification rule and the matching patterns are encoded here so
that the audit, the rule, and the rationale live next to each other.
A new repo or a new shared subdir is a one-line addition.

Usage::

    python scripts/check_ecosystem_gitignores.py
    python scripts/check_ecosystem_gitignores.py --json
    python scripts/check_ecosystem_gitignores.py --repos /path/to/oneiric /path/to/akosha
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Ecosystem configuration
# ---------------------------------------------------------------------------


# The Bodai ecosystem. Add a new repo here when it joins the family.
# ``path`` is the absolute local working copy; ``name`` is the display
# label in the report and JSON.
DEFAULT_REPOS: list[tuple[str, str]] = [
    ("mahavishnu", "~/Projects/mahavishnu"),
    ("session-buddy", "~/Projects/session-buddy"),
    ("crackerjack", "~/Projects/crackerjack"),
    ("mcp-common", "~/Projects/mcp-common"),
    ("akosha", "~/Projects/akosha"),
    ("dhara", "~/Projects/dhara"),
    ("oneiric", "~/Projects/oneiric"),
]


# Subdirs of ``.claude/`` that count as *project content*. If any of
# these exist under ``.claude/``, the repo uses ``.claude/`` as a
# catalog and must use SELECTIVE ``.gitignore`` rules so the catalog
# is still tracked. A blanket ``.claude/*`` would hide the catalog.
SHARED_CLAUDE_SUBDIRS: frozenset[str] = frozenset({
    "agents",
    "commands",
    "decisions",
    "skills",
    "workflows",
    "templates",
    "schemas",
    "specs",
    "hooks",  # hook definitions are project content; only ``hooks/scripts/`` is runtime
    "tools",
    "prompts",
})


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class ClaudeDirState(NamedTuple):
    """How a repo's ``.claude/`` is being used."""

    present: bool
    """``.claude/`` exists on disk."""
    shared_subdirs: list[str]
    """Subdirs that are project content (catalog)."""
    runtime_entries: list[str]
    """Everything else in ``.claude/`` — config, handoffs, worktrees, etc."""


def classify_claude_dir(repo: Path) -> ClaudeDirState:
    """Inspect ``<repo>/.claude/`` and split its contents.

    Returns ``ClaudeDirState`` with the presence flag plus the list of
    shared-subdir hits and the list of everything-else. Empty
    ``.claude/`` returns ``present=True`` with empty lists.
    """
    claude_dir = repo / ".claude"
    if not claude_dir.is_dir():
        return ClaudeDirState(present=False, shared_subdirs=[], runtime_entries=[])
    shared: list[str] = []
    runtime: list[str] = []
    for child in sorted(claude_dir.iterdir()):
        if child.is_dir() and child.name in SHARED_CLAUDE_SUBDIRS:
            shared.append(child.name)
        else:
            runtime.append(child.name)
    return ClaudeDirState(present=True, shared_subdirs=shared, runtime_entries=runtime)


# ---------------------------------------------------------------------------
# .gitignore parsing
# ---------------------------------------------------------------------------


# A line that's *only* a comment (possibly with leading whitespace and
# trailing decoration) is treated as a section header. The previous
# header's "name" is everything after the leading ``#``-stripping
# whitespace. We don't try to be clever about the section name — it's
# only used for reporting, not for matching.
_SECTION_HEADER_RE = re.compile(r"^\s*#\s*(.+?)\s*#*\s*$")


def parse_gitignore_sections(text: str) -> list[tuple[str, list[str]]]:
    """Split a .gitignore into (section_name, [pattern_lines]) tuples.

    Two header styles are recognised:

    * **Decorative** (mahavishnu-style)::

          # ====...====
          # Section Title
          # ====...====
          <patterns>

    * **Plain** (oneiric-style)::

          # Section Title
          <patterns>

    A comment is classified as a section title when its surrounding
    non-blank lines are both "structural" — that is, each is either a
    decorative divider, a pattern line, or a file boundary (start of
    file for the first comment, end of patterns for the last).
    Multi-line descriptive comments that sit between two patterns
    (e.g. ``# Track canonical config (agents, ...); ignore ...``)
    are correctly *not* treated as titles because their preceding
    non-blank line is another comment.

    A bare-file gitignore (no comment headers) returns a single
    section named "(no header)".
    """
    divider_re = re.compile(r"^\s*#\s*[-_=*]{3,}\s*$")
    lines = text.splitlines()
    n = len(lines)

    def prev_nonblank(idx: int) -> int | None:
        j = idx - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j < 0:
            return None
        return j

    def next_nonblank(idx: int) -> int | None:
        j = idx + 1
        while j < n and not lines[j].strip():
            j += 1
        if j >= n:
            return None
        return j

    def is_structural(idx: int) -> bool:
        line = lines[idx]
        return divider_re.match(line) is not None or not line.strip().startswith("#")

    # Identify section-title line indices.
    title_indices: set[int] = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        if divider_re.match(line):
            continue
        prev_i = prev_nonblank(i)
        next_i = next_nonblank(i)
        # Title if: (no previous non-blank) OR (previous is structural)
        # AND: (no next non-blank) OR (next is structural).
        prev_ok = prev_i is None or is_structural(prev_i)
        next_ok = next_i is None or is_structural(next_i)
        if prev_ok and next_ok:
            title_indices.add(i)

    # Walk the file, opening a new section at each title.
    sections: list[tuple[str, list[str]]] = []
    current_name = "(no header)"
    current_patterns: list[str] = []
    has_emitted = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if i in title_indices:
            # Close the previous section only if it has content. An
            # empty pre-title buffer is dropped (avoids a stray
            # "(no header)" entry at the start of the result when
            # the first non-blank line is a title).
            if has_emitted or current_patterns:
                sections.append((current_name, current_patterns))
            current_name = stripped.lstrip("#").strip()
            current_patterns = []
            has_emitted = True
        elif divider_re.match(line):
            # Decorative dividers between titles are absorbed by the
            # title they adjoin (the title is closed when the next
            # title opens). Mid-section dividers are ignored.
            continue
        elif stripped.startswith("#"):
            # Mid-section descriptive comment. Skipped.
            continue
        else:
            current_patterns.append(stripped)
    if has_emitted or current_patterns:
        sections.append((current_name, current_patterns))
    return sections


# Patterns that count as "blanket" coverage of ``.claude/``:
#   - ``.claude/`` (the directory itself, with trailing slash)
#   - ``.claude/*`` (everything inside)
#   - ``/.claude/``, ``/.claude/*`` (root-anchored equivalents)
# We also accept a blanket-plus-exception pair: ``.claude/*`` plus a
# ``!.claude/<file>`` re-include line. That's a valid pattern for
# runtime-only repos that want a tracked config file (e.g.
# ``!.claude/settings.json`` in session-buddy).
_BLANKET_CLAUDE_PATTERNS = (
    ".claude/",
    ".claude/*",
    "/.claude/",
    "/.claude/*",
)


# Patterns that count as "selective" coverage of one specific ``.claude/``
# subdir. The actual pattern must be a specific subdir like
# ``.claude/handoff/`` or ``.claude/hooks/scripts/``, not a wildcard
# over all subdirs. Multi-segment subpaths are allowed (e.g.
# ``.claude/skills/*/.archive/``). The ``.`` in the segment class
# allows for hidden subdirs like ``.archive/``.
_SELECTIVE_CLAUDE_SUBPATH_RE = re.compile(
    r"^\s*[/\.]?\.claude/[A-Za-z0-9_*-.]+(?:/[A-Za-z0-9_*-.]+)*/\s*$"
)


class ClaudeIgnoreState(NamedTuple):
    """What the .gitignore currently does about ``.claude/``."""

    has_blanket: bool
    """True if a blanket ``.claude/`` or ``.claude/*`` is present."""
    has_exception: bool
    """True if at least one ``!.claude/<file>`` re-include is present."""
    selective_paths: list[str]
    """Specific ``.claude/<subdir>/`` entries (e.g. ``.claude/handoff/``)."""
    sections: list[tuple[str, list[str]]]
    """Full parsed structure, for reporting."""


def parse_claude_ignore(text: str) -> ClaudeIgnoreState:
    """Classify the ``.claude``-related rules in a .gitignore.

    The state captures both the blanket and selective forms. The
    decision logic lives in ``evaluate_repo`` — this function only
    surfaces the facts.
    """
    sections = parse_gitignore_sections(text)
    has_blanket = False
    has_exception = False
    selective: list[str] = []
    for _section_name, patterns in sections:
        for pat in patterns:
            if pat in _BLANKET_CLAUDE_PATTERNS:
                has_blanket = True
            elif pat.startswith("!.claude/") or pat.startswith("!/.claude/"):
                has_exception = True
            elif _SELECTIVE_CLAUDE_SUBPATH_RE.match(pat):
                selective.append(pat)
    return ClaudeIgnoreState(
        has_blanket=has_blanket,
        has_exception=has_exception,
        selective_paths=selective,
        sections=sections,
    )


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


class Verdict(NamedTuple):
    """Audit result for a single repo."""

    name: str
    repo: Path
    claude_state: ClaudeDirState
    ignore_state: ClaudeIgnoreState
    status: str  # "PASS" | "WARN" | "FAIL" | "SKIP"
    matched_rule: str | None
    """The pattern that satisfies the assertion (if any)."""
    section: str | None
    """The .gitignore section containing the matched rule (if known)."""
    issue: str | None
    """Human-readable explanation when status is not PASS."""


def _find_section_for(sections: list[tuple[str, list[str]]], pattern: str) -> str | None:
    """Return the section name containing ``pattern``, or None."""
    for name, patterns in sections:
        if pattern in patterns:
            return name
    return None


def evaluate_repo(name: str, repo: Path) -> Verdict:
    """Classify and audit a single repo's .gitignore.

    Decision tree:

    - No ``.claude/`` dir       → SKIP (no requirement)
    - ``.claude/`` has shared   → must use selective ignore. Blanket
      content (catalog)            with no per-subdir rule is FAIL.
                                  Blanket with exception that re-includes
                                  the catalog dirs is also FAIL (the
                                  pattern would still hide them by default).
    - ``.claude/`` is runtime   → blanket ``.claude/`` is PASS.
      only                        Selective rule also PASS. Missing rule
                                  entirely is FAIL.
    - ``.claude/`` exists but   → FAIL — the catalog would be
      uses blanket ignore          ignored.
    """
    claude_state = classify_claude_dir(repo)

    # No .claude dir at all: nothing to enforce.
    if not claude_state.present:
        return Verdict(
            name=name,
            repo=repo,
            claude_state=claude_state,
            ignore_state=ClaudeIgnoreState(
                has_blanket=False, has_exception=False, selective_paths=[], sections=[]
            ),
            status="SKIP",
            matched_rule=None,
            section=None,
            issue="No .claude/ directory present",
        )

    gitignore_path = repo / ".gitignore"
    if not gitignore_path.is_file():
        return Verdict(
            name=name,
            repo=repo,
            claude_state=claude_state,
            ignore_state=ClaudeIgnoreState(
                has_blanket=False, has_exception=False, selective_paths=[], sections=[]
            ),
            status="FAIL",
            matched_rule=None,
            section=None,
            issue=".gitignore is missing",
        )

    ignore_text = gitignore_path.read_text(encoding="utf-8", errors="ignore")
    ignore_state = parse_claude_ignore(ignore_text)

    if claude_state.shared_subdirs:
        # SHARED content — must use selective ignore, NOT blanket.
        if ignore_state.has_blanket and not ignore_state.selective_paths:
            return Verdict(
                name=name,
                repo=repo,
                claude_state=claude_state,
                ignore_state=ignore_state,
                status="FAIL",
                matched_rule=None,
                section=None,
                issue=(
                    f"Blanket .claude/ rule would hide the catalog "
                    f"({', '.join(claude_state.shared_subdirs)}); "
                    f"need selective .claude/<runtime>/ ignores"
                ),
            )
        if ignore_state.selective_paths:
            rule = ignore_state.selective_paths[0]
            return Verdict(
                name=name,
                repo=repo,
                claude_state=claude_state,
                ignore_state=ignore_state,
                status="PASS",
                matched_rule=rule,
                section=_find_section_for(ignore_state.sections, rule),
                issue=None,
            )
        return Verdict(
            name=name,
            repo=repo,
            claude_state=claude_state,
            ignore_state=ignore_state,
            status="FAIL",
            matched_rule=None,
            section=None,
            issue=(
                f"Catalog dirs ({', '.join(claude_state.shared_subdirs)}) "
                f"are tracked but no .claude/<subdir>/ ignore is set"
            ),
        )

    # RUNTIME-ONLY content — blanket rule is the canonical answer.
    if ignore_state.has_blanket:
        rule = next(
            p for p in _BLANKET_CLAUDE_PATTERNS
            if p in (pat for _name, pats in ignore_state.sections for pat in pats)
        )
        return Verdict(
            name=name,
            repo=repo,
            claude_state=claude_state,
            ignore_state=ignore_state,
            status="PASS",
            matched_rule=rule,
            section=_find_section_for(ignore_state.sections, rule),
            issue=None,
        )
    if ignore_state.selective_paths:
        rule = ignore_state.selective_paths[0]
        return Verdict(
            name=name,
            repo=repo,
            claude_state=claude_state,
            ignore_state=ignore_state,
            status="PASS",
            matched_rule=rule,
            section=_find_section_for(ignore_state.sections, rule),
            issue=None,
        )
    return Verdict(
        name=name,
        repo=repo,
        claude_state=claude_state,
        ignore_state=ignore_state,
        status="FAIL",
        matched_rule=None,
        section=None,
        issue=(
            "Runtime entries "
            f"({', '.join(claude_state.runtime_entries) or '(empty)'}) "
            f"in .claude/ are unignored"
        ),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


STATUS_BADGE = {
    "PASS": "✓ PASS",
    "WARN": "! WARN",
    "FAIL": "✗ FAIL",
    "SKIP": "- SKIP",
}


def render_text_report(verdicts: list[Verdict]) -> str:
    """Human-readable table."""
    name_w = max(len(v.name) for v in verdicts) if verdicts else 10
    lines: list[str] = [
        "Bodai ecosystem .gitignore audit",
        "=" * 32,
        "",
    ]
    for v in verdicts:
        badge = STATUS_BADGE[v.status]
        if v.status == "SKIP":
            detail = v.issue or "(skipped)"
        elif v.status == "FAIL":
            detail = v.issue or "unknown failure"
        else:
            where = f" [{v.section}]" if v.section else ""
            rule = v.matched_rule or "(no rule matched)"
            detail = f"{rule}{where}"
        lines.append(f"  {v.name:<{name_w}}  {badge}  {detail}")
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
    for v in verdicts:
        counts[v.status] += 1
    total = len(verdicts)
    summary = (
        f"{total} repos checked: "
        f"{counts['PASS']} PASS, {counts['WARN']} WARN, "
        f"{counts['FAIL']} FAIL, {counts['SKIP']} SKIP"
    )
    lines.append("")
    lines.append(summary)
    return "\n".join(lines) + "\n"


def render_json_report(verdicts: list[Verdict]) -> str:
    """JSON for CI consumption."""
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
    items: list[dict] = []
    for v in verdicts:
        counts[v.status] += 1
        items.append({
            "name": v.name,
            "path": str(v.repo),
            "status": v.status,
            "claude_dir": {
                "present": v.claude_state.present,
                "shared_subdirs": v.claude_state.shared_subdirs,
                "runtime_entries": v.claude_state.runtime_entries,
            },
            "gitignore": {
                "has_blanket": v.ignore_state.has_blanket,
                "has_exception": v.ignore_state.has_exception,
                "selective_paths": v.ignore_state.selective_paths,
            },
            "matched_rule": v.matched_rule,
            "section": v.section,
            "issue": v.issue,
        })
    payload = {
        "ecosystem": "Bodai",
        "summary": {
            "total": len(verdicts),
            "pass": counts["PASS"],
            "warn": counts["WARN"],
            "fail": counts["FAIL"],
            "skip": counts["SKIP"],
        },
        "repos": items,
    }
    return json.dumps(payload, indent=2) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _expand_user(p: str) -> Path:
    return Path(p).expanduser().resolve()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repos",
        nargs="+",
        default=None,
        help="Override the repo list with explicit paths. Accepts both "
        "absolute paths and 'name:path' pairs (e.g. 'akosha:~/Projects/akosha').",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the default text report.",
    )
    return parser.parse_args(argv)


def resolve_repos(override: list[str] | None) -> list[tuple[str, Path]]:
    """Return ``[(name, path), ...]`` from CLI or DEFAULT_REPOS."""
    if override is None:
        return [(name, _expand_user(path)) for name, path in DEFAULT_REPOS]
    out: list[tuple[str, Path]] = []
    for entry in override:
        if ":" in entry and not entry.startswith("/"):
            name, _, path = entry.partition(":")
            out.append((name, _expand_user(path)))
        else:
            # Use the directory's basename as the label.
            p = _expand_user(entry)
            out.append((p.name, p))
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repos = resolve_repos(args.repos)
    verdicts = [evaluate_repo(name, path) for name, path in repos]
    if args.json:
        sys.stdout.write(render_json_report(verdicts))
    else:
        sys.stdout.write(render_text_report(verdicts))
    # Exit non-zero if any FAIL — useful for CI.
    return 1 if any(v.status == "FAIL" for v in verdicts) else 0


if __name__ == "__main__":
    sys.exit(main())
