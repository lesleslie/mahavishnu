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
from datetime import UTC
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants — mirrors `crackerjack docs validate --allow-nonstandard`
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
# Vocabulary added in schema v1.1 (2026-09-13). `plan` is the default and
# is omitted from the registry table to keep the column readable — the
# per-kind section below surfaces it explicitly.
KIND_VALUES: tuple[str, ...] = (
    "plan",
    "template",
    "reference",
    "audit",
    "decision",
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

    rel: str  # repo-relative POSIX path
    store: str  # e.g. "docs/adr/"
    date: str  # ISO-8601 (YYYY-MM-DD), or "" if missing
    status: str  # lifecycle value, or "unknown" if missing
    role: str  # role value, or "unknown" if missing
    kind: str  # document kind, or "plan" if missing (per schema v1.1 default)
    topic: str  # topic slug, or "—" if missing
    title: str  # one-line title derived from first H1 / filename


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
            ds != store_rel and rel.startswith(ds.rstrip("/") + "/") for ds in skip_deeper_stores
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


def _entry_from_file(abs_path: Path, rel: str, store: str, yaml_module: Any) -> Entry | None:
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
    kind = front.get("kind") if isinstance(front.get("kind"), str) else "plan"
    topic = front.get("topic") if isinstance(front.get("topic"), str) else "—"
    fallback_title = abs_path.stem.replace("-", " ").replace("_", " ")
    title = _title_from_text(text, fallback=fallback_title)

    return Entry(
        rel=rel,
        store=store,
        date=date,
        status=status,
        role=role,
        kind=kind,
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
    return (repo_root / "docs" / "adr").is_dir() and (repo_root / "docs" / "superpowers").is_dir()


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
        "frontmatter contract lives in `crackerjack docs validate --allow-nonstandard`."
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
            "| `crackerjack docs validate --allow-nonstandard` |"
        )
    rows.append("| Discovered stores | " + " ".join(f"`{s}`" for s in stores) + " |")
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
            f"| {total} | " + " | ".join(cells) + " |"
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
        target = rel[len("docs/plans/") :]
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
    rows.append("| Path | Date | Status | Role | Kind | Topic | Title |")
    rows.append("|---|---|---|---|---|---|---|")
    if not entries:
        rows.append("| _no entries with valid frontmatter_ | | | | | | |")
        rows.append("")
        return "\n".join(rows)

    # Sort by date DESC, then by rel ASC for deterministic ordering when
    # two files share the same date.
    sorted_entries = sorted(entries, key=lambda e: (-_date_sort_key(e.date), e.rel))
    for entry in sorted_entries:
        link = _entry_link(entry.rel, entry.store)
        # `plan` is the default; omit the column value to keep rows readable.
        kind_cell = "" if entry.kind == "plan" else f"`{entry.kind}`"
        rows.append(
            f"| {link} "
            f"| {entry.date or '—'} "
            f"| `{entry.status}` "
            f"| `{entry.role}` "
            f"| {kind_cell} "
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
    rows.append(
        f"Counts of entries per (lifecycle, role) cell across all {store_count} stores. "
        "Useful as a sanity check that the registry above is internally consistent."
    )
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
        "| **Total** | " + " | ".join(f"**{t}**" for t in col_totals) + f" | **{grand_total}** |"
    )
    rows.append("")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Rendering — by-kind section
# ---------------------------------------------------------------------------


_KIND_DESCRIPTIONS: dict[str, str] = {
    "plan": "Work items. The bulk of the registry — see the per-store tables above for full detail with status/role/topic.",
    "template": "Scaffolding docs (TEMPLATE.md files). Permanent fixtures; never a work item.",
    "reference": "Index pages or reference docs (README files). Permanent fixtures; never a work item.",
    "audit": "Reports on past work (e.g., plan-audit documents). The audit itself is not a work item.",
    "decision": "Durable decision records — covers both ADRs in `docs/adr/` and repo-local policies in `.claude/decisions/`.",
}


def _render_by_kind(entries: list[Entry]) -> str:
    """Group entries by `kind` so scaffolding/audit/reference docs surface
    explicitly. `plan` (the default) is listed last to keep the focus on
    non-default kinds — readers looking for "is this doc actually a plan
    to be done?" find the answer here.
    """
    # Group; preserve KIND_VALUES ordering, put unknown kinds last.
    by_kind: dict[str, list[Entry]] = {k: [] for k in KIND_VALUES}
    for entry in entries:
        by_kind.setdefault(entry.kind, []).append(entry)

    rows: list[str] = []
    rows.append("## By Kind")
    rows.append("")
    rows.append(
        "Documents grouped by their `kind:` value. Templates, references, "
        "and audits appear here even if their `status:` is `active` — they "
        "are scaffolding or analysis documents, not work items. Use this "
        "section when answering 'is this an active plan to be done?'"
    )
    rows.append("")

    # Render non-default kinds first (more useful), then plan (the bulk).
    order = [k for k in KIND_VALUES if k != "plan"] + ["plan"]
    for kind in order:
        kind_entries = by_kind.get(kind, [])
        # Skip rendering empty sections (other than plan, which is the bulk
        # and we always render to keep the count visible).
        if not kind_entries and kind != "plan":
            continue
        count = len(kind_entries)
        noun = "entry" if count == 1 else "entries"
        rows.append(f"### `{kind}` ({count} {noun})")
        rows.append("")
        rows.append(_KIND_DESCRIPTIONS.get(kind, ""))
        rows.append("")
        if kind == "plan":
            # Plans are exhaustively listed in the per-store tables above;
            # don't repeat them here.
            rows.append(
                "Full per-store detail (with status, role, topic, date) is "
                "in the **Canonical and Active Plan Registry** section above."
            )
            rows.append("")
            continue
        if not kind_entries:
            rows.append("_No entries._")
            rows.append("")
            continue
        rows.append("| Path | Date | Title |")
        rows.append("|---|---|---|")
        for entry in sorted(kind_entries, key=lambda e: (-_date_sort_key(e.date), e.rel)):
            link = _entry_link(entry.rel, entry.store)
            rows.append(f"| {link} | {entry.date or '—'} | {entry.title} |")
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
    topic_value = "convergence-control-plane" if is_mahavishnu else "plan-registry"
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
    sections.append(_authority_matrix(repo_root, stores, entries_by_store).rstrip())
    sections.append("")
    sections.append(_review_entry_points(generated_at, store_count=len(stores)).rstrip())
    sections.append("")

    sections.append("## Canonical and Active Plan Registry")
    sections.append("")
    sections.append(
        "One table per store. Entries are sorted by `date` DESC, with ties broken "
        "by path ASC. Files without valid frontmatter are excluded; run "
        "`uv run crackerjack docs validate --allow-nonstandard` "
        "to surface them."
    )
    sections.append("")

    all_entries: list[Entry] = []
    for store in stores:
        store_entries = entries_by_store.get(store, [])
        all_entries.extend(store_entries)
        sections.append(_render_store_table(store, store_entries).rstrip())
        sections.append("")

    sections.append(_render_by_kind(all_entries).rstrip())
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


# ---------------------------------------------------------------------------
# Exclude-pattern resolution (--exclude / --exclude-from)
# ---------------------------------------------------------------------------


def _load_exclude_patterns(exclude_from: Path | None) -> list[str]:
    """Read gitignore-style patterns from a file. One per line; '#' is a
    comment. Empty lines are ignored. Returns the patterns verbatim — the
    matcher handles fnmatch semantics."""
    if exclude_from is None:
        return []
    if not exclude_from.is_file():
        sys.stderr.write(f"--exclude-from: file not found: {exclude_from}\n")
        return []
    out: list[str] = []
    try:
        text = exclude_from.read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"--exclude-from: could not read: {exc}\n")
        return []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


def _compile_exclude_matcher(patterns: list[str]) -> callable[[str], bool]:
    """Return a callable that maps a repo-relative POSIX path → True to skip.

    Each pattern is a glob (fnmatch-style). Leading '/' anchors the match at
    the repo root; a bare pattern matches anywhere in the path. A pattern
    prefixed with '!' negates the match (include-override). The matcher's
    contract: returns False unless a non-negated pattern matched and was
    not subsequently overridden by a later '!pattern'.
    """
    import fnmatch
    import re

    compiled: list[tuple[bool, re.Pattern[str]]] = []
    for raw in patterns:
        negate = raw.startswith("!")
        body = raw[1:] if negate else raw
        anchored = body.startswith("/")
        if anchored:
            body = body.lstrip("/")
        regex = _glob_to_regex(body, anchored=anchored)
        compiled.append((negate, re.compile(regex)))

    def match(rel: str) -> bool:
        excluded = False
        for negate, regex in compiled:
            if regex.search(rel):
                if negate:
                    excluded = False
                else:
                    excluded = True
        return excluded

    return match


def _glob_to_regex(pattern: str, *, anchored: bool) -> str:
    """Convert a gitignore-style glob to a regex string.

    - '*' matches any chars except '/'.
    - '**' matches any chars including '/'.
    - '?' matches a single char except '/'.
    - Other chars are escaped.
    """
    import re

    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    body = "".join(out)
    if anchored:
        return "^" + body + "(?:/.*)?$"
    return "(?:^|/)" + body + "(?:/.*)?$"


# ---------------------------------------------------------------------------
# Phase B — Dhara upsert via PlanIndexRebuilder
# ---------------------------------------------------------------------------


def _run_phase_b(
    repo_root: Path,
    records: list[Any],
    dhara_url: str,
) -> tuple[int, int]:
    """Run PlanIndexRebuilder.upsert_all against a real Dhara endpoint.

    Returns (success_count, error_count). Failures are non-fatal — the
    rebuilder continues past individual record errors.
    """
    import asyncio

    from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
    from mahavishnu.plan_index.store import PlanIndexStore

    from mahavishnu.core.dhara_adapter import DharaClient

    async def _upsert() -> tuple[int, int, list]:
        client = DharaClient(base_url=dhara_url, timeout=30.0)
        try:
            store = PlanIndexStore(client)  # type: ignore[arg-type]
            rebuilder = PlanIndexRebuilder()
            return await rebuilder.upsert_all(records, store)
        finally:
            await client.aclose()

    success, errors, _err_list = asyncio.run(_upsert())
    sys.stderr.write(f"phase-b: upserted {success} records to Dhara ({errors} errors)\n")
    return success, errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regenerate_plan_index",
        description=(
            "Regenerate docs/plans/PLAN_INDEX.md from the YAML frontmatter "
            "of every .md file under each auto-discovered documentation "
            "store in the repo. The orchestrator runs three phases: scan, "
            "(optional) Dhara upsert via PlanIndexRebuilder, and render."
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
            "Emit a JSON summary of counts (per store + total) on stderr. Useful for CI assertions."
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
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Diff rendered output against the current PLAN_INDEX.md; exit 1 if different. "
            "NOT equivalent to --dry-run: --check exits non-zero on drift, --dry-run exits 0."
        ),
    )
    parser.add_argument(
        "--skip-render",
        action="store_true",
        help="Skip writing PLAN_INDEX.md; Dhara upsert (Phase B) still runs when --dhara-url is set.",
    )
    parser.add_argument(
        "--rebuild-from",
        metavar="GIT_REF",
        default=None,
        help=(
            "One-shot backfill from git history (revision range or single SHA). "
            "When supplied, the scan reads plans at the given ref rather than the working tree."
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        metavar="PATTERN",
        default=[],
        help=(
            "Glob pattern (fnmatch-style) to exclude paths from indexing. Repeatable. "
            "Patterns are matched against the repo-relative POSIX path; a leading '/' "
            "anchors the match at the repo root."
        ),
    )
    parser.add_argument(
        "--exclude-from",
        metavar="FILE",
        default=None,
        help=(
            "Read exclude patterns (gitignore syntax) from this file. One pattern per line; "
            "lines starting with '#' are comments. Negation patterns ('!foo') are honored."
        ),
    )
    parser.add_argument(
        "--preflight-mode",
        choices=("strict", "lenient"),
        default="lenient",
        help=(
            "Migration pre-flight behavior: 'strict' aborts on any scan error, "
            "'lenient' (default) skips-and-counts so a single broken file does not block the run."
        ),
    )
    parser.add_argument(
        "--render-to",
        metavar="PATH",
        default=None,
        help=(
            "Write rendered PLAN_INDEX.md to this path instead of --out. "
            "Required by the migration golden workflow. Does not affect Dhara writes."
        ),
    )
    parser.add_argument(
        "--dhara-url",
        metavar="URL",
        default=None,
        help=(
            "Enable Phase B (Dhara upsert) by pointing the rebuilder at this Dhara base URL. "
            "When unset, Phase B is skipped and the script behaves as a pure renderer."
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

    # Compile --exclude / --exclude-from patterns into a path matcher.
    exclude_patterns: list[str] = list(args.exclude)
    if args.exclude_from is not None:
        exclude_patterns.extend(_load_exclude_patterns(Path(args.exclude_from).resolve()))
    is_excluded_by_user = _compile_exclude_matcher(exclude_patterns) if exclude_patterns else None

    # Phase A — scan the repo and collect entries.
    entries_by_store: dict[str, list[Entry]] = {}
    total_with_frontmatter = 0
    total_discovered = 0
    total_excluded = 0
    scan_errors: list[str] = []

    stores_set = set(stores)
    for store in stores:
        skip: frozenset[str] = frozenset(
            s for s in stores_set if s != store and s.startswith(store)
        )
        files = discover_files(repo_root, store, skip_deeper_stores=skip)
        store_entries: list[Entry] = []
        for abs_path, rel in files:
            if is_excluded_by_user is not None and is_excluded_by_user(rel):
                total_excluded += 1
                continue
            total_discovered += 1
            try:
                entry = _entry_from_file(abs_path, rel, store, yaml_module)
            except Exception as exc:
                msg = f"scan error: {rel}: {exc}"
                scan_errors.append(msg)
                if args.preflight_mode == "strict":
                    sys.stderr.write(f"strict-mode abort: {msg}\n")
                    return 1
                continue
            if entry is None:
                continue
            store_entries.append(entry)
        entries_by_store[store] = store_entries
        total_with_frontmatter += len(store_entries)

    # Phase B — optional Dhara upsert via PlanIndexRebuilder. Only runs
    # when --dhara-url is provided; otherwise the script is a pure renderer.
    phase_b_success = 0
    phase_b_errors = 0
    if args.dhara_url is not None and not args.dry_run:
        try:
            from mahavishnu.plan_index.cron_core import discover_records
        except ImportError as exc:
            sys.stderr.write(f"phase-b: cannot import plan_index.cron_core: {exc}\n")
        else:
            try:
                from mahavishnu.plan_index.record import PlanRecord  # noqa: TC001
                from mahavishnu.plan_index.rebuild import PlanIndexRebuilder

                records: list[PlanRecord] = discover_records(repo_root)
                phase_b_success, phase_b_errors = _run_phase_b(
                    repo_root,
                    records,
                    args.dhara_url,
                )
            except Exception as exc:
                sys.stderr.write(f"phase-b: dhara upsert failed: {exc}\n")
                phase_b_errors = -1  # sentinel for "unknown error count"

    # --rebuild-from is documented as a one-shot backfill hook. The current
    # implementation does not perform a git-history replay; it logs the
    # requested ref and continues with the working-tree scan. Future revisions
    # may shell out to `git log -p <ref> -- <paths>` and feed the diff through
    # the same PlanIndexRebuilder path.
    if args.rebuild_from is not None:
        sys.stderr.write(
            f"--rebuild-from {args.rebuild_from}: not yet implemented; "
            "continuing with working-tree scan.\n"
        )

    generated_at = datetime.datetime.now(UTC).date().isoformat()
    rendered = _render_index(
        repo_root,
        stores,
        entries_by_store,
        generated_at=generated_at,
    )

    # Determine the output target. --render-to takes priority over --out;
    # when neither is supplied, default to docs/plans/PLAN_INDEX.md.
    if args.render_to is not None:
        out_path = Path(args.render_to)
    elif args.out is not None:
        out_path = args.out
    else:
        out_path = Path("docs/plans/PLAN_INDEX.md")
    if not out_path.is_absolute():
        out_path = (repo_root / out_path).resolve()

    # --check: compare rendered output against current file; exit 1 on drift.
    if args.check:
        existing = ""
        if out_path.is_file():
            try:
                existing = out_path.read_text(encoding="utf-8")
            except OSError as exc:
                sys.stderr.write(f"--check: could not read {out_path}: {exc}\n")
        if rendered != existing:
            sys.stderr.write(f"--check: drift detected ({out_path}); rendered vs current differ.\n")
            return 1
        sys.stderr.write(f"--check: {out_path} is up-to-date.\n")
        return 0

    # --dry-run: print to stdout. No file writes, no Dhara upsert.
    if args.dry_run:
        sys.stdout.write(rendered)
        sys.stdout.flush()
    elif args.skip_render:
        sys.stderr.write("skip-render: PLAN_INDEX.md not written.\n")
    else:
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
            "excluded": total_excluded,
            "with_frontmatter": total_with_frontmatter,
            "stores": stores,
            "per_store": {store: len(entries_by_store.get(store, [])) for store in stores},
            "phase_b": {
                "ran": args.dhara_url is not None and not args.dry_run,
                "success": phase_b_success,
                "errors": phase_b_errors,
            },
            "scan_errors": scan_errors,
        }
        sys.stderr.write(json.dumps(summary, indent=2) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
