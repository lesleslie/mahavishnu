#!/usr/bin/env uv run python
"""Regenerate docs/plans/PLAN_INDEX.md from per-store frontmatter.

Walks the repository's documentation stores, parses YAML frontmatter on
each ``.md`` file, and emits a deterministic index grouped by store and
sorted by date DESC within each store. The output mirrors the structure
of the previous hand-edited PLAN_INDEX.md (status legend, authority
matrix, review entry points, registry tables, lifecycle-by-role
distribution) but every registry entry is mechanically derived from
`status:` / `role:` / `topic:` on the source files, so the index cannot
drift from the corpus.

Store discovery
---------------

Stores are **auto-discovered**: every directory under the repo root that
contains at least two ``.md`` files with valid YAML frontmatter is treated
as a store. The following system directories are skipped (anywhere in the
tree): ``.git``, ``.venv``, ``venv``, ``__pycache__``, ``node_modules``,
``htmlcov``, ``dist``, ``.pytest_cache``, ``.archive``, ``archive``,
``backups``, ``coverage_report``, ``assets``. The script's own output
(``docs/plans/PLAN_INDEX.md``) and the ``docs/plans/drafts/`` working tree
are also self-excluded. A small static override map (``STORE_LABELS``)
gives descriptive headings to well-known stores (e.g. ``docs/adr/`` →
"Architecture Decision Records"); other stores use a label derived from
the directory name.

CLI overrides
-------------

- ``--stores <comma-separated-paths>``    REPLACES auto-discovery.
- ``--extra-stores <comma-separated-paths>``    ADDS to auto-discovery.
- ``--dry-run``    prints to stdout instead of writing.
- ``--out PATH``    output path (default ``docs/plans/PLAN_INDEX.md``).
- ``--json-summary``    emit counts on stderr.

Authority matrix
----------------

When the repo contains a Mahavishnu-style layout (detected by the
presence of both ``docs/adr/`` and ``docs/superpowers/``), the matrix
section preserves the original Mahavishnu/Bodai authority rows. On
non-Mahavishnu repos the matrix is generated dynamically from the
discovered stores, listing each store's path and per-status document
counts.

Exit codes:
    0 = success (file written or --dry-run)
    2 = bad CLI args or missing dependency
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants — mirrors validate_document_frontmatter.py
# ---------------------------------------------------------------------------

LIFECYCLE_VALUES: tuple[str, ...] = (
    "draft",
    "active",
    "partial",
    "shipped",
    "complete",
)
ROLE_VALUES: tuple[str, ...] = (
    "canonical",
    "implementation",
    "umbrella",
    "historical",
    "superseded",
)

# Directories skipped wholesale during auto-discovery. Compared against any
# path segment so a nested ``node_modules`` is still skipped. ``archive`` /
# ``.archive`` are also rejected later as a per-file PATH-segment guard, so
# auto-discovery need not be exhaustive on its own.
SYSTEM_DIR_PARTS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "htmlcov",
        "dist",
        ".pytest_cache",
        ".archive",
        "archive",
        "backups",
        ".backups",
        "coverage_report",
        "assets",
        ".vscode",
        ".idea",
        "cache",
        ".cache",
        ".playwright-mcp",
    }
)

# Minimum number of .md files (with valid frontmatter) required in a
# directory before it is promoted to a "store". Two is conservative — a
# single README.md hanging at the repo root should not become a store.
MIN_STORE_DOCS: int = 2

# Optional display-label overrides for well-known stores. Keys are POSIX
# relative paths terminated with a trailing slash. Stores without an entry
# fall back to a label derived from the directory name.
STORE_LABELS: dict[str, str] = {
    "docs/adr/": "Architecture Decision Records (`docs/adr/`)",
    "docs/plans/": "Plans & Specifications (`docs/plans/`)",
    "docs/superpowers/specs/": "Superpowers Specs (`docs/superpowers/specs/`)",
    "docs/superpowers/plans/": "Superpowers Plans (`docs/superpowers/plans/`)",
    ".claude/decisions/": "Repo-local Decisions (`.claude/decisions/`)",
    "docs/followups/": "Follow-up Notes (`docs/followups/`)",
}

# Always-excluded entries (per-file, after auto-discovery has nominated a
# directory as a store).
SELF_SKIP_REL = "docs/plans/PLAN_INDEX.md"
DRAFTS_PREFIX = "docs/plans/drafts/"
ARCHIVE_PARTS = ("archive", ".archive")
BACKUP_SUFFIXES = (".backup", ".backup.json")

# Frontmatter regex — captures the YAML block between the opening and
# closing `---` fences. Anchored at start of file (DOTALL via the inner
# pattern but \A prevents matches inside the body).
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    """One row in the registry — a file with parsed frontmatter."""

    rel: str           # repo-relative POSIX path
    store: str         # e.g. "docs/adr/"
    date: str          # ISO-8601 (YYYY-MM-DD), or "" if missing
    status: str        # lifecycle value, or "unknown" if missing
    role: str          # role value, or "unknown" if missing
    topic: str         # topic slug, or "—" if missing
    title: str         # one-line title derived from first H1 / filename


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def _load_yaml_module() -> Any:
    """PyYAML is part of crackerjack's env. Defer import so the script's
    error message names the missing dependency instead of a Traceback."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised only on bare envs
        sys.stderr.write(
            "PyYAML is required to parse document frontmatter. "
            "Install with: uv pip install pyyaml\n"
            f"Original error: {exc}\n"
        )
        raise SystemExit(2) from exc
    return yaml


def extract_frontmatter(text: str, yaml_module: Any) -> dict[str, Any] | None:
    """Return the parsed YAML mapping from `text`, or None when no
    frontmatter block is present. Returns {} for an empty `---` block."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None
    raw = match.group(1)
    parsed = yaml_module.safe_load(raw)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        # Not a mapping — treat as malformed so the entry is filtered later.
        return None
    return parsed


def _coerce_date(value: Any) -> str:
    """PyYAML parses bare `date: 2026-07-16` into datetime.date; coerce
    both that and string forms to YYYY-MM-DD."""
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return ""


def _title_from_text(text: str, fallback: str) -> str:
    """First level-1 heading text, or `fallback` (typically the filename
    stem) when the document has no H1."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


# ---------------------------------------------------------------------------
# File discovery & filtering
# ---------------------------------------------------------------------------


def _is_excluded(rel: str) -> bool:
    if rel == SELF_SKIP_REL:
        return True
    if rel.startswith(DRAFTS_PREFIX):
        return True
    parts = rel.split("/")
    for part in parts:
        if part in ARCHIVE_PARTS:
            return True
    for suffix in BACKUP_SUFFIXES:
        if rel.endswith(suffix):
            return True
    return False


def discover_files(
    repo_root: Path,
    store_rel: str,
    *,
    skip_deeper_stores: frozenset[str] = frozenset(),
) -> list[tuple[Path, str]]:
    """Return [(absolute_path, repo_relative_posix_path)] for every .md
    file under the given store, after applying exclusion rules.

    When ``skip_deeper_stores`` is provided, files that live inside any
    of the listed deeper store directories are omitted. This keeps a
    "parent" store (e.g. ``docs/``) from duplicating entries that the
    matching "child" store (e.g. ``docs/schemas/``) will own. The
    keyword-only argument avoids duplicating the existing single-store
    call sites that don't care about overlap."""
    root = repo_root / store_rel.rstrip("/")
    if not root.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(repo_root).as_posix()
        if _is_excluded(rel):
            continue
        if any(
            ds != store_rel and rel.startswith(ds.rstrip("/") + "/")
            for ds in skip_deeper_stores
        ):
            continue
        out.append((path, rel))
    return out


def _has_frontmatter(path: Path, yaml_module: Any) -> bool:
    """Cheap check that the leading bytes of `path` look like a YAML
    frontmatter block. Used during store discovery — a directory only
    counts as a store if enough of its .md children actually carry
    frontmatter (>= MIN_STORE_DOCS)."""
    try:
        with path.open("rb") as fh:
            head = fh.read(4096)
    except OSError:
        return False
    if not head.startswith(b"---"):
        return False
    rest = head[3:]
    # Trim optional leading whitespace / blank lines after the opener.
    rest = rest.lstrip(b"\r\n").lstrip()
    if not rest:
        return False
    # Reject the unlikely-but-legal case of a single `---` file with no
    # closing fence within the first 4 KiB.
    if b"\n---" not in rest and b"\r---" not in rest:
        return False
    try:
        text = head.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return False
    return extract_frontmatter(text, yaml_module) is not None


def discover_stores(repo_root: Path, yaml_module: Any) -> list[str]:
    """Walk `repo_root` and return POSIX-relative store paths, ordered
    deterministically. A directory is a "store" iff it is not a system
    directory, is not the repo root itself, contains no system-segment in
    any parent path, and contains at least ``MIN_STORE_DOCS`` .md files
    with valid frontmatter.

    Returned paths are POSIX-style with a trailing slash, matching the
    conventions the rest of the module uses (e.g. ``"docs/adr/"``)."""
    seen: dict[str, int] = {}

    # Walk every directory under repo root but stop descending into
    # SYSTEM_DIR_PARTS. Use os.walk with pruning for efficiency on big
    # repos (skipping node_modules/.git/etc.).
    import os

    repo_root_str = str(repo_root.resolve())
    for dirpath, dirnames, filenames in os.walk(repo_root_str, followlinks=False):
        # Prune system directories in-place so the walker skips them.
        dirnames[:] = [d for d in dirnames if d not in SYSTEM_DIR_PARTS]
        # Only consider directories that actually contain .md files.
        md_files = [f for f in filenames if f.endswith(".md")]
        if not md_files:
            continue
        # Map the absolute dirpath back to a POSIX relative path.
        abs_dir = Path(dirpath)
        rel_dir = abs_dir.resolve().relative_to(repo_root.resolve()).as_posix()
        # The repo root itself is never a store — a flat README.md does
        # not constitute a documentation store.
        if rel_dir == ".":
            continue
        store_rel = rel_dir + "/"
        # Count how many .md children actually have frontmatter.
        frontmatter_count = 0
        for fname in md_files:
            if _has_frontmatter(abs_dir / fname, yaml_module):
                frontmatter_count += 1
                if frontmatter_count >= MIN_STORE_DOCS:
                    break
        if frontmatter_count >= MIN_STORE_DOCS:
            seen[store_rel] = max(seen.get(store_rel, 0), frontmatter_count)

    # Deterministic order: alphabetical by relative path. Putting docs/
    # directories before .claude/ etc. falls out of natural sort.
    return sorted(seen)


def _label_for_store(store_rel: str) -> str:
    """Return a heading-friendly label for `store_rel`, falling back to a
    derived title-case phrase based on the directory name when no
    override entry exists."""
    if store_rel in STORE_LABELS:
        return STORE_LABELS[store_rel]
    name = store_rel.rstrip("/").rsplit("/", 1)[-1]
    # Title-case the leaf segment for display ("implementation-plans" ->
    # "Implementation Plans"), but keep dotted names verbatim so
    # `.claude/decisions/` renders as "Claude Decisions" not ".Claude
    # Decisions".
    display = name.lstrip(".")
    titled = display.replace("-", " ").replace("_", " ").title()
    return f"{titled} (`{store_rel}`)"


# ---------------------------------------------------------------------------
# Per-file entry construction
# ---------------------------------------------------------------------------


def _entry_from_file(
    abs_path: Path, rel: str, store: str, yaml_module: Any
) -> Entry | None:
    """Parse one file. Returns None when the file has no valid frontmatter
    or fails to read — those are silently skipped because PLAN_INDEX only
    indexes docs that have frontmatter (the validator's contract)."""
    try:
        text = abs_path.read_text(encoding="utf-8")
    except OSError:
        return None
    front = extract_frontmatter(text, yaml_module)
    if front is None:
        return None
    if not isinstance(front, dict):
        return None

    date = _coerce_date(front.get("date"))
    status = front.get("status") if isinstance(front.get("status"), str) else "unknown"
    role = front.get("role") if isinstance(front.get("role"), str) else "unknown"
    topic = front.get("topic") if isinstance(front.get("topic"), str) else "—"
    fallback_title = abs_path.stem.replace("-", " ").replace("_", " ")
    title = _title_from_text(text, fallback=fallback_title)

    return Entry(
        rel=rel,
        store=store,
        date=date,
        status=status,
        role=role,
        topic=topic,
        title=title,
    )


# ---------------------------------------------------------------------------
# Rendering — fixed (static) sections
# ---------------------------------------------------------------------------

# Status legend copied verbatim from docs/schemas/document-frontmatter-v1.md
# (Vocabulary — Lifecycle + Vocabulary — Role).
STATUS_LEGEND = """\
## Status Legend

The vocabulary is defined canonically in
[`docs/schemas/document-frontmatter-v1.md`](../schemas/document-frontmatter-v1.md)
and reproduced here for index readability.

- **Lifecycle (`status`)** — five values:
  - `draft` — in preparation; not yet approved for implementation or adoption.
  - `active` — approved and in current use; being executed or applied as policy.
  - `partial` — approved and partially implemented; remaining work documented.
  - `shipped` — delivered and verified in production; closed.
  - `complete` — delivered; verification or follow-up may still be open.
- **Role (`role`)** — five values:
  - `canonical` — authoritative reference; source of truth for its topic.
  - `implementation` — a plan, spec, or followup that drives concrete work.
  - `umbrella` — aggregates multiple child plans or decisions under one banner.
  - `historical` — records decisions or outcomes after they were acted on.
  - `superseded` — replaced by a newer document; always paired with `superseded_by`.
- Legal combinations read as lifecycle + role, e.g. `active, implementation`,
  `draft, umbrella`, `shipped, canonical`.
"""


def _is_mahavishnu_layout(repo_root: Path) -> bool:
    """True iff the repo looks like Mahavishnu's own docs layout (both
    ``docs/adr/`` and ``docs/superpowers/`` present). Used to switch the
    Authority Matrix between the rich Mahavishnu-specific table and the
    generic dynamic one."""
    return (repo_root / "docs" / "adr").is_dir() and (
        repo_root / "docs" / "superpowers"
    ).is_dir()


def _authority_matrix(
    repo_root: Path,
    stores: list[str],
    entries_by_store: dict[str, list[Entry]],
) -> str:
    """Render the Authority Matrix section.

    On Mahavishnu-shaped repos the hardcoded PLAN_INDEX-style matrix is
    preserved for human navigability. On every other repo a generic
    dynamic matrix lists every discovered store with its relative path
    and a per-status document count, so the section is meaningful without
    Mahavishnu-specific plan references."""
    if _is_mahavishnu_layout(repo_root):
        return """\
## Authority Matrix

| Concern | Authority |
|---|---|
| Plan navigation and current ownership | `docs/plans/PLAN_INDEX.md` (this file, regenerated from frontmatter) |
| Frontmatter vocabulary and migration contract | `docs/schemas/document-frontmatter-v1.md` |
| Cross-repo LLM provider defaults and Bifrost routing | `docs/plans/2026-05-10-minimax27-provider-migration.md` |
| Legacy backlog item details | `docs/plans/2026-05-07-mahavishnu-master-backlog.md` |
| Bodai control-plane convergence C0–C7 | `docs/plans/2026-05-10-bodai-control-plane-convergence-plan.md` |
| Bodai-wide observability surface | `docs/plans/2026-07-11-phase-6-bodai-observability.md` |
| Repo-local decisions index | `.claude/decisions/README.md` |
| Follow-up tracker index | `docs/followups/README.md` |
| Source plan defining this index | `docs/superpowers/plans/2026-07-16-plan-lifecycle-unification.md` |
"""

    # Generic matrix — list every discovered store with status breakdown.
    rows: list[str] = []
    rows.append("## Authority Matrix")
    rows.append("")
    rows.append(
        "The table below is auto-generated from the stores discovered in this "
        "repository. `Plan navigation` row points at this file (and its "
        "`scripts/regenerate_plan_index.py`); `Frontmatter vocabulary` rows "
        "point at the canonical schema if it exists, otherwise the local "
        "frontmatter contract lives in `scripts/validate_document_frontmatter.py`."
    )
    rows.append("")
    rows.append("| Concern | Authority |")
    rows.append("|---|---|")
    rows.append(
        "| Plan navigation and current ownership "
        "| `docs/plans/PLAN_INDEX.md` (this file, regenerated from frontmatter) |"
    )
    canonical_schema = repo_root / "docs" / "schemas" / "document-frontmatter-v1.md"
    if canonical_schema.is_file():
        rows.append(
            "| Frontmatter vocabulary and migration contract "
            "| `docs/schemas/document-frontmatter-v1.md` |"
        )
    else:
        rows.append(
            "| Frontmatter vocabulary and migration contract "
            "| `scripts/validate_document_frontmatter.py` |"
        )
    rows.append("| Discovered stores | "
                 + " ".join(f"`{s}`" for s in stores)
                 + " |")
    rows.append("")

    # Per-store status breakdown table.
    rows.append("### Discovered stores by lifecycle status")
    rows.append("")
    rows.append(
        "| Store | Path | Total | `draft` | `active` | `partial` | `shipped` | `complete` | `unknown` |"
    )
    rows.append("|---|---|---|---|---|---|---|---|---|")
    for store in stores:
        entries = entries_by_store.get(store, [])
        total = len(entries)
        by_status: Counter[str] = Counter()
        for entry in entries:
            by_status[entry.status or "unknown"] += 1
        cells = [
            str(by_status.get("draft", 0)),
            str(by_status.get("active", 0)),
            str(by_status.get("partial", 0)),
            str(by_status.get("shipped", 0)),
            str(by_status.get("complete", 0)),
            str(by_status.get("unknown", 0)),
        ]
        rows.append(
            f"| {_label_for_store(store).split(' (')[0]} "
            f"| `{store}` "
            f"| {total} | "
            + " | ".join(cells)
            + " |"
        )
    rows.append("")
    return "\n".join(rows)


def _review_entry_points(generated_at: str, store_count: int) -> str:
    return f"""\
## Review Entry Points

This file is regenerated mechanically from the per-file YAML frontmatter
across the {store_count} auto-discovered stores. The registry tables below
are sorted by `date` DESC within each store and group entries by store.
The lifecycle × role distribution at the bottom is a quick consistency
check — it should match the counts of the registry rows modulo files in
skipped directories (see exclusion rules in the script header).

Before implementing from any entry:

1. Confirm the file's lifecycle is `active` or `partial` and its role is
   `implementation` or `canonical`. Files with `role: historical`,
   `role: superseded`, or `status: shipped` are reference material only.
1. If the file has a populated `superseded_by:` field, jump to the
   successor before reading further.
1. If the file has a non-empty `blocks_on:` list, verify every entry
   has shipped before scheduling the dependent work.

Last regenerated: {generated_at}.
"""


# ---------------------------------------------------------------------------
# Rendering — registry tables
# ---------------------------------------------------------------------------


def _entry_link(rel: str, store: str) -> str:
    """POSIX link to the file from the index's home at docs/plans/PLAN_INDEX.md.

    The index is TWO levels below the repo root (docs/plans/PLAN_INDEX.md),
    so anything under docs/ or .claude/ at repo root needs ``../../``.

    - docs/plans/<x>          → same dir, target is just <x>
    - docs/<y>/<x>            → up past plans/, up past docs/ → ../../docs/<y>/<x>
    - .claude/<x>             → up past plans/, up past docs/ → ../../.claude/<x>
    """
    if rel.startswith("docs/plans/"):
        target = rel[len("docs/plans/"):]
    elif rel.startswith("docs/") or rel.startswith(".claude/"):
        target = "../../" + rel
    else:
        target = "../../" + rel
    return f"[`{rel}`]({target})"


def _render_store_table(store: str, entries: list[Entry]) -> str:
    label = _label_for_store(store)
    rows: list[str] = []
    rows.append(f"### {label}")
    rows.append("")
    rows.append(
        "| Path | Date | Status | Role | Topic | Title |"
    )
    rows.append(
        "|---|---|---|---|---|---|"
    )
    if not entries:
        rows.append("| _no entries with valid frontmatter_ | | | | | |")
        rows.append("")
        return "\n".join(rows)

    # Sort by date DESC, then by rel ASC for deterministic ordering when
    # two files share the same date.
    sorted_entries = sorted(entries, key=lambda e: (-_date_sort_key(e.date), e.rel))
    for entry in sorted_entries:
        link = _entry_link(entry.rel, entry.store)
        rows.append(
            f"| {link} "
            f"| {entry.date or '—'} "
            f"| `{entry.status}` "
            f"| `{entry.role}` "
            f"| `{entry.topic}` "
            f"| {entry.title} |"
        )
    rows.append("")
    return "\n".join(rows)


def _date_sort_key(value: str) -> int:
    """Encode YYYY-MM-DD as a sortable int (yyyymmdd); empty/invalid keys
    sort to 0 so unknown dates cluster at the bottom."""
    if not value:
        return 0
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", value)
    if not match:
        return 0
    return int(match.group(1)) * 10000 + int(match.group(2)) * 100 + int(match.group(3))


# ---------------------------------------------------------------------------
# Rendering — lifecycle × role distribution
# ---------------------------------------------------------------------------


def _render_distribution(entries: list[Entry], store_count: int) -> str:
    counts: Counter[tuple[str, str]] = Counter()
    for e in entries:
        # Skip "unknown" rows so they don't pollute the matrix.
        if e.status == "unknown" or e.role == "unknown":
            continue
        counts[(e.status, e.role)] += 1

    rows: list[str] = []
    rows.append("## Lifecycle × Role Distribution")
    rows.append("")
    rows.append(f"Counts of entries per (lifecycle, role) cell across all {store_count} stores. "
                 "Useful as a sanity check that the registry above is internally consistent.")
    rows.append("")
    # Build a header: blank corner + each lifecycle.
    header = "| Role \\\\ Lifecycle | " + " | ".join(LIFECYCLE_VALUES) + " | Total |"
    sep = "|---|" + "|".join(["---"] * (len(LIFECYCLE_VALUES) + 1)) + "|"
    rows.append(header)
    rows.append(sep)

    for role in ROLE_VALUES:
        cells: list[str] = []
        row_total = 0
        for lifecycle in LIFECYCLE_VALUES:
            cell_value = counts.get((lifecycle, role), 0)
            row_total += cell_value
            cells.append(str(cell_value) if cell_value else "·")
        rows.append(f"| `{role}` | " + " | ".join(cells) + f" | **{row_total}** |")
    rows.append("")

    # Column totals row.
    col_totals: list[str] = []
    grand_total = 0
    for lifecycle in LIFECYCLE_VALUES:
        col_sum = sum(counts.get((lifecycle, role), 0) for role in ROLE_VALUES)
        grand_total += col_sum
        col_totals.append(str(col_sum) if col_sum else "·")
    rows.append(
        "| **Total** | "
        + " | ".join(f"**{t}**" for t in col_totals)
        + f" | **{grand_total}** |"
    )
    rows.append("")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Top-level composition
# ---------------------------------------------------------------------------


def _render_index(
    repo_root: Path,
    stores: list[str],
    entries_by_store: dict[str, list[Entry]],
    generated_at: str,
) -> str:
    repo_name = repo_root.name or "this repository"
    is_mahavishnu = _is_mahavishnu_layout(repo_root)
    frontmatter_date = generated_at if is_mahavishnu else generated_at

    purpose_subject = "Mahavishnu/Bodai plans" if is_mahavishnu else f"{repo_name} plans"
    topic_value = (
        "convergence-control-plane" if is_mahavishnu else "plan-registry"
    )
    blocks_on_value: str | None = (
        "docs/schemas/document-frontmatter-v1.md" if is_mahavishnu else None
    )

    sections: list[str] = []
    fm_lines: list[str] = [
        "---",
        "status: active",
        "role: canonical",
        f"date: {frontmatter_date}",
        f"last_reviewed: {frontmatter_date}",
        "superseded_by: null",
    ]
    if blocks_on_value is not None:
        fm_lines.extend(["blocks_on:", f"  - {blocks_on_value}"])
    else:
        fm_lines.extend(["blocks_on: []"])
    fm_lines.append(f"topic: {topic_value}")
    fm_lines.append("---")
    sections.append("\n".join(fm_lines))
    sections.append("")
    sections.append("# Plan Index")
    sections.append("")
    sections.append(f"**Date:** {frontmatter_date}")
    sections.append(f"**Last regenerated:** {generated_at}")
    sections.append(
        f"**Purpose:** Navigation map for finding and reviewing active {purpose_subject}. "
        "Generated by `scripts/regenerate_plan_index.py`. Do not edit by hand."
    )
    sections.append("")
    sections.append(
        "Use this file as the first stop before reviewing plan work. Older plans "
        "remain useful as source material, but the authority matrix below defines "
        "which document owns each kind of decision."
    )
    sections.append("")
    sections.append(STATUS_LEGEND.rstrip())
    sections.append("")
    sections.append(
        _authority_matrix(repo_root, stores, entries_by_store).rstrip()
    )
    sections.append("")
    sections.append(
        _review_entry_points(generated_at, store_count=len(stores)).rstrip()
    )
    sections.append("")

    sections.append("## Canonical and Active Plan Registry")
    sections.append("")
    sections.append(
        "One table per store. Entries are sorted by `date` DESC, with ties broken "
        "by path ASC. Files without valid frontmatter are excluded; run "
        "`uv run python scripts/validate_document_frontmatter.py --allow-nonstandard` "
        "to surface them."
    )
    sections.append("")

    all_entries: list[Entry] = []
    for store in stores:
        store_entries = entries_by_store.get(store, [])
        all_entries.extend(store_entries)
        sections.append(_render_store_table(store, store_entries).rstrip())
        sections.append("")

    sections.append(_render_distribution(all_entries, store_count=len(stores)).rstrip())

    return "\n".join(sections) + "\n"


# ---------------------------------------------------------------------------
# CLI + main
# ---------------------------------------------------------------------------


def _csv_list(value: str) -> list[str]:
    """Normalize a comma-separated CLI argument into a clean list of
    POSIX-style trailing-slash store paths (deduped, ordered by first
    appearance)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in value.split(","):
        item = raw.strip()
        if not item:
            continue
        # Normalize: strip surrounding slashes, re-add a single trailing slash.
        item = item.strip("/")
        if not item:
            continue
        item = item + "/"
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regenerate_plan_index",
        description=(
            "Regenerate docs/plans/PLAN_INDEX.md from the YAML frontmatter "
            "of every .md file under each auto-discovered documentation "
            "store in the repo."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated index to stdout instead of writing the file.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/plans/PLAN_INDEX.md"),
        help="Output path (default: docs/plans/PLAN_INDEX.md).",
    )
    parser.add_argument(
        "--stores",
        type=_csv_list,
        default=[],
        metavar="PATH,PATH,...",
        help=(
            "Comma-separated POSIX-relative store paths that REPLACE "
            "auto-discovery entirely. Example: --stores 'docs/plans/,docs/adr/'"
        ),
    )
    parser.add_argument(
        "--extra-stores",
        type=_csv_list,
        default=[],
        metavar="PATH,PATH,...",
        help=(
            "Comma-separated POSIX-relative store paths that are ADDED to "
            "the auto-discovered list. Use for directories that fall below "
            "the auto-discovery threshold (e.g. single-doc drafts)."
        ),
    )
    parser.add_argument(
        "--json-summary",
        action="store_true",
        help=(
            "Emit a JSON summary of counts (per store + total) on stderr. "
            "Useful for CI assertions."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help=(
            "Override the repository root for store discovery (default: "
            "the parent directory of this script). Useful when running "
            "the script against a different repo from outside it."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code != 0 else 0

    if args.repo_root is not None:
        repo_root = args.repo_root.resolve()
    else:
        # Default: scan the caller's current working directory rather than
        # the script's own parent. This lets operators invoke the script
        # against a sibling repo by `cd`ing in and running it from there.
        # Pass --repo-root to override.
        repo_root = Path.cwd().resolve()
    yaml_module = _load_yaml_module()

    # Resolve the final list of stores. --stores replaces auto-discovery;
    # --extra-stores is additive on top of whatever the selected path produced.
    if args.stores:
        stores: list[str] = list(args.stores)
    else:
        stores = discover_stores(repo_root, yaml_module)
    if args.extra_stores:
        for extra in args.extra_stores:
            if extra not in stores:
                stores.append(extra)
    # Final deterministic ordering.
    stores = sorted(set(stores))

    entries_by_store: dict[str, list[Entry]] = {}
    total_with_frontmatter = 0
    total_discovered = 0

    # Pre-compute the set of "deeper" stores for each store so we can
    # avoid duplicating entries in nested stores (e.g. docs/ and
    # docs/schemas/ both qualify — but files inside docs/schemas/ should
    # belong only to that deeper store in the registry).
    stores_set = set(stores)
    for store in stores:
        skip: frozenset[str] = frozenset(
            s for s in stores_set if s != store and s.startswith(store)
        )
        files = discover_files(repo_root, store, skip_deeper_stores=skip)
        store_entries: list[Entry] = []
        for abs_path, rel in files:
            total_discovered += 1
            entry = _entry_from_file(abs_path, rel, store, yaml_module)
            if entry is None:
                continue
            store_entries.append(entry)
        entries_by_store[store] = store_entries
        total_with_frontmatter += len(store_entries)

    generated_at = datetime.date.today().isoformat()
    rendered = _render_index(
        repo_root,
        stores,
        entries_by_store,
        generated_at=generated_at,
    )

    if args.dry_run:
        sys.stdout.write(rendered)
        sys.stdout.flush()
    else:
        out_path = args.out
        if not out_path.is_absolute():
            out_path = (repo_root / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: tempfile in the same directory + rename.
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(out_path.parent),
            prefix=f".{out_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(rendered)
            tmp_path = Path(tmp.name)
        try:
            tmp_path.replace(out_path)
        except OSError:
            # Fallback for cross-device moves etc.
            tmp_path.replace(out_path)

    if args.json_summary:
        import json
        summary = {
            "generated_at": generated_at,
            "discovered": total_discovered,
            "with_frontmatter": total_with_frontmatter,
            "stores": stores,
            "per_store": {
                store: len(entries_by_store.get(store, []))
                for store in stores
            },
        }
        sys.stderr.write(json.dumps(summary, indent=2) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
