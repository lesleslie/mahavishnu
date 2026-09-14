#!/usr/bin/env python3
"""Migrate no-frontmatter plans to schema v1.1.

Per docs/schemas/document-frontmatter-v1.md, every .md file in the four
plan stores (docs/plans/, docs/superpowers/plans/, docs/superpowers/specs/,
docs/followups/) must carry a parseable ---\\n...\\n--- YAML frontmatter
block. As of 2026-09-13, 38 such files are missing it.

Default mode is DRY-RUN: prints per-file proposals, no writes.
Pass --apply to actually write. Pass --store <name> to limit scope.

Idempotent: files with parseable frontmatter are skipped.

Detection strategy:
1. Code-block-aware scan of first 50 lines for legacy status markers
   (both '**Status:** <word>' and bare 'Status: <word>' variants —
   the openclaw-hermes spec uses the bare form).
2. Code-block-aware scan for date markers (similar variants).
3. Filename date as fallback (the YYYY-MM-DD-... prefix).
4. H1 title for human readability of the report (not written into
   frontmatter; PLAN_INDEX uses its own format).

Heuristic status mapping per the schema's § Legacy Mapping table.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO = Path("/Users/les/Projects/mahavishnu")
TODAY = "2026-09-13"

STORES = [
    "docs/plans",
    "docs/superpowers/plans",
    "docs/superpowers/specs",
    "docs/followups",
]

# Default status when no legacy marker is found (per plan §5 Phase 1)
DEFAULT_STATUS = {
    "docs/superpowers/plans": "active",
    "docs/superpowers/specs": "draft",
    "docs/plans": "active",
    "docs/followups": "active",
}

# Default role per schema § Legacy Mapping: "(no frontmatter) -> draft, implementation"
# but specs/plans/followups/plans are still implementation role unless overridden.
DEFAULT_ROLE = {
    "docs/superpowers/plans": "implementation",
    "docs/superpowers/specs": "implementation",
    "docs/plans": "implementation",
    "docs/followups": "implementation",
}

# Per schema § Legacy Mapping.
# (legacy_keyword) -> (new_status, role_override_or_None)
# Note: keywords are matched case-insensitively against the FIRST WORD of the
# captured status phrase. "(brainstorming complete...)" and "(pending review)"
# qualifiers are ignored — they do not change the lifecycle bucket.
LEGACY_STATUS_MAP: dict[str, tuple[str, str | None]] = {
    # accepted / approved
    "accepted": ("active", None),
    "approved": ("active", None),
    "in progress": ("active", None),
    "active": ("active", None),
    # proposed / draft
    "proposed": ("draft", None),
    "draft": ("draft", None),
    "drafted": ("draft", None),
    "ready": ("draft", "implementation"),
    "brainstormed": ("draft", None),
    "deferred": ("draft", None),
    # complete
    "complete": ("complete", None),
    "completed": ("complete", None),
    "delivered": ("complete", None),
    # shipped
    "shipped": ("shipped", None),
    # resolved (historical)
    "resolved": ("complete", "historical"),
    # superseded
    "superseded": ("complete", "superseded"),
}

FENCE_RE = re.compile(r"^---\s*$", re.MULTILINE)
HAS_FRONT_RE = re.compile(r"\A---\s*\n")

# Code-block-aware patterns: we strip fenced ``` blocks before matching.
CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
# Match status, accepting **Status:** or bare Status: variants. Capture the
# first word of the phrase (legacy keys are single words).
STATUS_RE = re.compile(
    r"^\s*\*?\s*[Ss]tatus\s*:\s*\*?\s*([A-Z][A-Za-z]*)",
    re.MULTILINE,
)
# Match date (YYYY-MM-DD), with or without ** markers.
DATE_RE = re.compile(
    r"^\s*\*?\s*[Dd]ate\s*:\s*\*?\s*(\d{4}-\d{2}-\d{2})",
    re.MULTILINE,
)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
FILENAME_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


class Proposal(NamedTuple):
    path: Path
    store: str
    h1_title: str | None
    legacy_status_phrase: str | None
    proposed_status: str
    proposed_role: str
    proposed_date: str
    topic: str


def strip_code_blocks(text: str) -> str:
    return CODE_BLOCK_RE.sub("```...```", text)


def has_frontmatter(text: str) -> bool:
    if not HAS_FRONT_RE.match(text):
        return False
    # Look for closing fence in first 2000 chars. A real frontmatter block
    # closes within a few hundred chars; if no closing fence is found within
    # this window, the frontmatter is broken (missing `---` terminator) and
    # the file is NOT considered already-migrated.
    return len(FENCE_RE.findall(text, 0, 2000)) >= 2


def detect_status(text: str) -> str | None:
    """Return the first-word status phrase from the head of the doc, or None."""
    head = "\n".join(strip_code_blocks(text).splitlines()[:50])
    m = STATUS_RE.search(head)
    return m.group(1) if m else None


def detect_date(text: str) -> str | None:
    head = "\n".join(strip_code_blocks(text).splitlines()[:50])
    m = DATE_RE.search(head)
    return m.group(1) if m else None


def detect_h1(text: str) -> str | None:
    m = H1_RE.search(text)
    return m.group(1).strip() if m else None


def slugify_topic(path: Path) -> str:
    """Derive a topic slug from filename stem (YYYY-MM-DD-foo-bar-design)."""
    stem = path.stem
    stem = FILENAME_DATE_RE.sub("", stem)  # strip date prefix
    stem = re.sub(r"-design$", "", stem)  # strip -design suffix
    stem = re.sub(r"-+", "-", stem)
    return stem.strip("-")


def propose(path: Path) -> Proposal | None:
    text = path.read_text()
    if has_frontmatter(text):
        return None

    rel = path.relative_to(REPO)
    store = str(rel.parent)

    legacy_phrase = detect_status(text)
    date = detect_date(text)
    h1 = detect_h1(text)

    if not date:
        m = FILENAME_DATE_RE.match(path.name)
        if m:
            date = m.group(1)
    if not date:
        date = TODAY

    if legacy_phrase:
        key = legacy_phrase.lower()
        mapping = LEGACY_STATUS_MAP.get(key)
        if mapping:
            proposed_status, role_override = mapping
        else:
            # Unknown legacy phrase — fall back to store default
            proposed_status = DEFAULT_STATUS.get(store, "draft")
            role_override = None
    else:
        proposed_status = DEFAULT_STATUS.get(store, "draft")
        role_override = None

    proposed_role = role_override or DEFAULT_ROLE.get(store, "implementation")

    return Proposal(
        path=path,
        store=store,
        h1_title=h1,
        legacy_status_phrase=legacy_phrase,
        proposed_status=proposed_status,
        proposed_role=proposed_role,
        proposed_date=date,
        topic=slugify_topic(path),
    )


def render_frontmatter(p: Proposal) -> str:
    return (
        "---\n"
        f"status: {p.proposed_status}\n"
        f"role: {p.proposed_role}\n"
        f"kind: plan\n"
        f"date: {p.proposed_date}\n"
        f"last_reviewed: {TODAY}\n"
        f"superseded_by: null\n"
        f"blocks_on: []\n"
        f"topic: {p.topic}\n"
        "---\n\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes (default: dry-run, prints proposals only)",
    )
    parser.add_argument(
        "--store",
        choices=STORES,
        help="Limit to one store",
    )
    parser.add_argument(
        "--only",
        help="Limit to filenames containing this substring",
    )
    args = parser.parse_args()

    targets = [args.store] if args.store else STORES

    proposals: list[Proposal] = []
    skipped_existing: list[Path] = []

    for store in targets:
        store_path = REPO / store
        if not store_path.exists():
            print(f"MISSING: {store}", file=sys.stderr)
            continue
        for md in sorted(store_path.glob("*.md")):
            if args.only and args.only not in md.name:
                continue
            p = propose(md)
            if p is None:
                skipped_existing.append(md)
            else:
                proposals.append(p)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== Migrator {mode} ===")
    print(f"Files needing migration: {len(proposals)}")
    print(f"Files already migrated (skipped): {len(skipped_existing)}")
    print()

    by_store: dict[str, list[Proposal]] = {}
    for p in proposals:
        by_store.setdefault(p.store, []).append(p)

    for store in targets:
        items = by_store.get(store, [])
        if not items:
            continue
        print(f"\n--- {store}/ ({len(items)} files) ---")
        for p in items:
            legacy_note = (
                f"  (legacy: {p.legacy_status_phrase!r})"
                if p.legacy_status_phrase
                else "  (no legacy marker — store default)"
            )
            print(f"  {p.path.name}")
            print(f"    status: {p.proposed_status}{legacy_note}")
            print(f"    role:   {p.proposed_role}")
            print(f"    date:   {p.proposed_date}")
            print(f"    topic:  {p.topic}")

    if args.apply:
        print(f"\n=== Writing {len(proposals)} files ===")
        for p in proposals:
            text = p.path.read_text()
            new = render_frontmatter(p) + text
            p.path.write_text(new)
            print(f"  WROTE: {p.path.name}")
    else:
        print(f"\n=== Dry run only. Re-run with --apply to write. ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())
