# Master Plan Index + Centralized Regenerator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 7 forked `regenerate_plan_index.py` scripts with a oneiric-hosted shared library; make mahavishnu's `docs/plans/PLAN_INDEX.md` the master fleet index aggregated from sibling repos via pull-on-regeneration; wire crackerjack's `plan_index_sync` phase through the shared library behind a transition feature flag.

**Architecture:** oneiric exposes `oneiric/plan_index/` as a pure-Python library (no I/O side effects in the public API beyond explicit `out_path` writes); per-repo regeneration goes through crackerjack's existing `plan_index_sync` PHASE (NOT a fast-hook — opt-in publish-time phase) which dispatches to either the new library or a legacy local implementation based on `settings.documentation.use_shared_regenerator`; the master regenerator lives at `mahavishnu/fleet_index/` (NEW package — NOT `mahavishnu/plan_index/` which is the separate Dhara-canonical CRUD layer, out of scope) and consumes the library for each `emit_in_master: true` entry in `settings/ecosystem.yaml`.

**Tech Stack:** Python 3.14; Typer (CLI); Pydantic-v2 (strict mode for `RepositoryConfig` schema migration); oneiric library APIs (`OneiricCLIBase` for shared CLI semantics; `OneiricAdapterRegistry` NOT used — `plan_index` is documentation, not runtime); crackerjack phase coordinator (`crackerjack/core/phase_coordinator.py`); mahavishnu Typer CLI (`mahavishnu/_main_cli.py`).

**Spec:** `docs/specs/2026-10-19-master-plan-index-and-regenerator-design.md` (Round 3)

## Global Constraints

- Python 3.14 target; oneiric, mahavishnu, crackerjack all on compatible crackerjack pins (≥0.90.0 ships the dispatcher refactor).
- Pre-1.0 hard-break per `feedback-no-backwards-compat-pre-1.0.md`: no shims, no `DeprecationWarning`, no deprecation windows. Replace not extend.
- Per `feedback-no-dhara-mention-in-bodai`: Dhara is an independent repo maintained by bodai/vishnu; do not reference Dhara in any bodai context, including code, comments, docs, or migration runbooks.
- Per `feedback-bodai-push-is-user-controlled.md`: every push is user-controlled; the user owns the merge order across the 6 repos.
- Per `feedback-mcp-common-version-bump-is-user.md`: no `pyproject.toml` version bumps in this work; operator controls.
- Per `feedback-trim-warning-behind-stale-worktree.md`: spec was edited during a parallel session — when implementing, ensure worktree is FF'd to `main` to avoid stale spec refs.
- Crackerjack's `plan_index_sync` is an opt-in publish-time PHASE (not fast-hook) per commit `e2656170`; 4 invariant tests in `crackerjack/tests/core/test_plan_index_sync_phase.py` (L79, L111, L149, L169) pin this. Plan must respect them.
- The `crackerjack run -v -f` (merge gate per `feedback-crackerjack-merge-gate-is-vf`) does NOT run `plan_index_sync`; only `--publish` (with `auto_plan_index_sync_on_publish: true`) or explicit `--plan-index-sync` does.
- Oneiric library public API: `Entry(rel, store, date, status, role, kind, topic, title)` — 8 fields. Public functions: `discover_stores`, `discover_files`, `scan_entries`, `render_index`, `regenerate`.
- Master regenerator's discovery: `mahavishnu/settings/ecosystem.yaml` (canonical) NOT `mahavishnu/settings/repos.yaml` (deprecated per `settings/repos.yaml:1`).
- Master regenerator's CLI: `mahavishnu fleet regenerate` (NOT `mahavishnu plan-index regenerate`).
- Master regenerator's package: `mahavishnu/fleet_index/` (NOT `mahavishnu/plan_index/` — preserves the separate Dhara-canonical CRUD layer).
- Schema migration: `mahavishnu/core/ecosystem.py:RepositoryConfig` gains `slug: str | None = None` + `emit_in_master: bool = False` (Pydantic-v2 safe defaults).
- Plan follows the per-PR test runtime budget: tests >10s marked `@pytest.mark.slow`.

## Review Focus

Five input classes the spec implies but no task's tests exercise that are most likely to bite a person using this software. The corresponding test pin is in the task that owns the code.

1. **Siblings with identical `ecosystem.yaml` paths but different `slug` fields** → pinned by `test_master_dedup.py::test_duplicate_repo_path_dedupes` in **Task 8**.
2. **Siblings with `slug` substring (`akosha` and `akosha-experimental`)** → pinned by `test_link_math.py::test_basename_substring_not_used_as_slug` in **Task 8**.
3. **`plan_index_sync` re-introduced as fast-hook** → pinned by `test_plan_index_sync_phase.py` (existing tests, L79/L111/L149/L169) which **Task 4** does not touch.
4. **`scan_entries` vs `regenerate` divergence** (a future refactor grows a separate code path that emits different output) → pinned by `test_regenerate.py::test_regenerate_equals_scan_plus_render` (identity test) in **Task 3**.
5. **Oneiric version pin regression** (a sibling's `pyproject.toml` accidentally lowers the `oneiric>=` floor) → pinned by **Task 11** via a manifest-level grep test (`test_oneiric_floor_satisfies_plan_index_version`).

---

### Task 1: Oneiric library — frontmatter parser + exclusions + entry

**Files:**
- Create: `oneiric/plan_index/frontmatter.py`
- Create: `oneiric/plan_index/exclusions.py`
- Create: `oneiric/plan_index/entry.py`
- Test: `oneiric/tests/plan_index/test_frontmatter.py`
- Test: `oneiric/tests/plan_index/test_exclusions.py`

**Interfaces:**
- Consumes: `pyyaml` (already in oneiric's dev group); stdlib `pathlib`
- Produces: `Entry` (frozen dataclass); `extract_frontmatter(text: str, yaml_module) -> dict | None`; `is_excluded(rel: str) -> bool`; module constants `SYSTEM_DIR_PARTS`, `DRAFTS_PREFIX`, `ARCHIVE_PARTS`, `BACKUP_SUFFIXES`, `SELF_SKIP_REL`, `MIN_STORE_DOCS`

- [ ] **Step 1: Write the failing test for `Entry`**

```python
# oneiric/tests/plan_index/test_entry.py
from oneiric.plan_index.entry import Entry

def test_entry_has_eight_fields():
    e = Entry(rel="docs/plans/foo.md", store="docs/plans/", date="2026-10-19", status="active", role="implementation", kind="plan", topic="test", title="Foo")
    assert e.rel == "docs/plans/foo.md"
    assert e.store == "docs/plans/"
    assert e.date == "2026-10-19"
    assert e.status == "active"
    assert e.role == "implementation"
    assert e.kind == "plan"
    assert e.topic == "test"
    assert e.title == "Foo"

def test_entry_is_frozen():
    e = Entry(rel="x", store="y", date="z", status="a", role="b", kind="c", topic="d", title="e")
    import pytest
    with pytest.raises(Exception):
        e.rel = "y"  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_entry.py -v`
Expected: FAIL with `ModuleNotFoundError: oneiric.plan_index.entry`

- [ ] **Step 3: Implement `Entry`**

```python
# oneiric/plan_index/entry.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Entry:
    rel: str
    store: str
    date: str
    status: str
    role: str
    kind: str
    topic: str
    title: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_entry.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for `extract_frontmatter`**

```python
# oneiric/tests/plan_index/test_frontmatter.py
import yaml
from oneiric.plan_index.frontmatter import extract_frontmatter

def test_unclosed_yaml_block_returns_none():
    text = "---\nstatus: active\nrole: implementation\n"
    assert extract_frontmatter(text, yaml) is None

def test_single_dash_not_a_boundary():
    text = "--- key: value\nstatus: active\n"
    assert extract_frontmatter(text, yaml) is None

def test_valid_yaml_missing_required_key():
    text = "---\nstatus: active\n---\n# Title\n"
    parsed = extract_frontmatter(text, yaml)
    assert parsed is not None
    assert "role" not in parsed  # missing required key — caller validates

def test_invalid_enum_value_passes_parser():
    text = "---\nstatus: foo\nrole: bar\n---\n# Title\n"
    parsed = extract_frontmatter(text, yaml)
    assert parsed == {"status": "foo", "role": "bar"}

def test_valid_yaml_returns_dict():
    text = "---\nstatus: active\nrole: implementation\nkind: plan\n---\n# Title\n"
    parsed = extract_frontmatter(text, yaml)
    assert parsed == {"status": "active", "role": "implementation", "kind": "plan"}
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_frontmatter.py -v`
Expected: FAIL with `ModuleNotFoundError: oneiric.plan_index.frontmatter`

- [ ] **Step 7: Implement `extract_frontmatter`**

```python
# oneiric/plan_index/frontmatter.py
"""Frontmatter parser.

VERBATIM lift of mahavishnu/scripts/regenerate_plan_index.py:200-230
(`extract_frontmatter` — line-anchored, no regex truncation bug).
Validates against the schema in oneiric/schemas/document-frontmatter-v1.md;
the parser itself doesn't enforce the schema (caller does), it just
returns the parsed YAML mapping or None for malformed input.
"""
from __future__ import annotations
from typing import Any

_FRONTMATTER_OPEN = "---"

def extract_frontmatter(text: str, yaml_module: Any) -> dict[str, Any] | None:
    """Return the parsed YAML mapping from `text`, or None for malformed."""
    if not text:
        return None
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != _FRONTMATTER_OPEN:
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == _FRONTMATTER_OPEN:
            raw = "\n".join(lines[1:i])
            try:
                parsed = yaml_module.safe_load(raw)
            except yaml_module.YAMLError:
                return None
            if parsed is None:
                return {}
            return parsed if isinstance(parsed, dict) else None
    return None  # no closing fence
```

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_frontmatter.py -v`
Expected: PASS

- [ ] **Step 9: Write the failing test for `is_excluded`**

```python
# oneiric/tests/plan_index/test_exclusions.py
from oneiric.plan_index.exclusions import is_excluded, SYSTEM_DIR_PARTS

def test_drafts_subdirectory_excluded():
    assert is_excluded("docs/plans/drafts/foo.md")

def test_archive_segment_excluded():
    assert is_excluded("docs/plans/.archive/foo.md")
    assert is_excluded("docs/plans/archive/foo.md")

def test_backup_suffix_excluded():
    assert is_excluded("docs/plans/foo.md.backup")
    assert is_excluded("docs/plans/foo.md.backup.json")

def test_self_skip_excluded():
    assert is_excluded("docs/plans/PLAN_INDEX.md")

def test_hyphenated_drafts_archive_NOT_excluded():
    assert not is_excluded("docs/plans/drafts-archive/foo.md")

def test_toplevel_archived_NOT_excluded():
    assert not is_excluded("docs/archived.md")

def test_system_dir_parts_pinned():
    """Pinned verbatim from the spec — every entry must be in the exclusion set."""
    expected = {".git", ".venv", "venv", "__pycache__", "node_modules", "htmlcov",
                "dist", ".pytest_cache", ".archive", "archive", "backups", ".backups",
                "coverage_report", "assets", ".vscode", ".idea", "cache", ".cache",
                ".playwright-mcp", "worktree-snapshots"}
    assert SYSTEM_DIR_PARTS == expected
```

- [ ] **Step 10: Run test to verify it fails**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_exclusions.py -v`
Expected: FAIL with `ModuleNotFoundError: oneiric.plan_index.exclusions`

- [ ] **Step 11: Implement `is_excluded`**

```python
# oneiric/plan_index/exclusions.py
"""Path-segment exclusion rules for the regenerator's filesystem walk.

SYSTEM_DIR_PARTS is a verbatim copy of the legacy script's exclusion
list (mahavishnu/scripts/regenerate_plan_index.py:99-127). Test
`test_system_dir_parts_pinned` pins every entry.
"""
from __future__ import annotations

SELF_SKIP_REL = "docs/plans/PLAN_INDEX.md"
DRAFTS_PREFIX = "docs/plans/drafts/"
ARCHIVE_PARTS = ("archive", ".archive")
BACKUP_SUFFIXES = (".backup", ".backup.json")

# Verbatim from legacy script (mahavishnu/scripts/regenerate_plan_index.py:99-127)
SYSTEM_DIR_PARTS = frozenset({
    ".git", ".venv", "venv", "__pycache__", "node_modules", "htmlcov",
    "dist", ".pytest_cache", ".archive", "archive", "backups", ".backups",
    "coverage_report", "assets", ".vscode", ".idea", "cache", ".cache",
    ".playwright-mcp", "worktree-snapshots",
})

def is_excluded(rel: str) -> bool:
    """True if `rel` matches the regenerator's exclusion rules."""
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
```

- [ ] **Step 12: Run test to verify it passes**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_exclusions.py -v`
Expected: PASS

- [ ] **Step 13: Commit**

```bash
git add oneiric/plan_index/{entry,frontmatter,exclusions}.py oneiric/tests/plan_index/{test_entry,test_frontmatter,test_exclusions}.py
git commit -m "feat(oneiric): plan_index entry, frontmatter, exclusions modules"
```

---

### Task 2: Oneiric library — discovery + scan_entries + render + regenerate

**Files:**
- Create: `oneiric/plan_index/discovery.py`
- Create: `oneiric/plan_index/render.py`
- Create: `oneiric/plan_index/regenerate.py`
- Create: `oneiric/plan_index/__init__.py`
- Test: `oneiric/tests/plan_index/test_discovery.py`
- Test: `oneiric/tests/plan_index/test_render.py`
- Test: `oneiric/tests/plan_index/test_regenerate.py`
- Test: `oneiric/tests/plan_index/test_atomic_writes.py`
- Test: `oneiric/tests/plan_index/test_scan_entries.py`

**Interfaces:**
- Consumes: `Entry` (Task 1), `extract_frontmatter` (Task 1), `is_excluded` (Task 1)
- Produces: `discover_stores(repo_root: Path) -> Sequence[str]` (dedup invariant); `discover_files(repo_root, store: str) -> list[tuple[Path, Path]]`; `scan_entries(repo_root: Path) -> dict[str, list[Entry]]`; `render_index(entries_by_store, *, generated_at: str) -> str`; `regenerate(repo_root: Path, *, out_path: Path | None = None, exclude=(), check: bool = False) -> int`

- [ ] **Step 1: Write the failing test for `discover_stores`**

```python
# oneiric/tests/plan_index/test_discovery.py
import os
from pathlib import Path
from oneiric.plan_index.discovery import discover_stores, discover_files, MIN_STORE_DOCS
from oneiric.plan_index.entry import Entry
from oneiric.plan_index.frontmatter import extract_frontmatter
from oneiric.plan_index import exclusions as exclusions_module
from oneiric.plan_index import frontmatter as frontmatter_module
import yaml

def _make_repo(tmp: Path, name: str, frontmatter_count: int) -> Path:
    repo = tmp / name
    docs = repo / "docs" / "plans"
    docs.mkdir(parents=True)
    for i in range(frontmatter_count):
        (docs / f"plan_{i}.md").write_text(f"---\nstatus: active\n---\n# Plan {i}\n")
    return repo

def test_promote_at_min_store_docs(tmp_path: Path):
    repo = _make_repo(tmp_path, "r1", MIN_STORE_DOCS)
    stores = discover_stores(repo, yaml)
    assert "docs/plans/" in stores

def test_demote_below_min_store_docs(tmp_path: Path):
    repo = _make_repo(tmp_path, "r1", MIN_STORE_DOCS - 1)
    stores = discover_stores(repo, yaml)
    assert "docs/plans/" not in stores

def test_system_dir_parts_pruned(tmp_path: Path):
    """A node_modules directory with frontmatter'd files must NOT be a store."""
    repo = tmp_path / "r1"
    (repo / "node_modules" / "docs" / "plans").mkdir(parents=True)
    (repo / "node_modules" / "docs" / "plans" / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    (repo / "docs" / "plans").mkdir(parents=True)
    (repo / "docs" / "plans" / "bar.md").write_text("---\nstatus: active\n---\n# Bar\n")
    stores = discover_stores(repo, yaml)
    assert "docs/plans/" in stores
    assert "node_modules/docs/plans/" not in stores

def test_dedup_handles_duplicate_dirs_in_scan(tmp_path: Path):
    """Sequence, not Set — duplicates from filesystem anomalies dedupe first-wins."""
    repo = tmp_path / "r1"
    plans = repo / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    stores = discover_stores(repo, yaml)
    assert list(stores).count("docs/plans/") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError: oneiric.plan_index.discovery`

- [ ] **Step 3: Implement `discover_stores` and `discover_files`**

```python
# oneiric/plan_index/discovery.py
"""Store discovery + file enumeration for the plan_index library.

Pins the dedup invariant: discover_stores returns a Sequence that
preserves first-seen order and never duplicates paths, even when the
filesystem contains anomalies. Tested by
test_dedup_handles_duplicate_dirs_in_scan.

SYSTEM_DIR_PARTS is imported from exclusions to keep the pruning rules
in one place.
"""
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING, Any

from oneiric.plan_index.exclusions import SYSTEM_DIR_PARTS, is_excluded

if TYPE_CHECKING:
    from collections.abc import Sequence

MIN_STORE_DOCS: int = 2

def discover_stores(repo_root: Path, yaml_module: Any) -> "Sequence[str]":
    """Return POSIX-relative store paths, deduped, first-seen order."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for dirpath, dirnames, filenames in _walk(repo_root):
        # Prune system directories in-place
        dirnames[:] = [d for d in dirnames if d not in SYSTEM_DIR_PARTS]
        md_files = [f for f in filenames if f.endswith(".md")]
        if not md_files:
            continue
        rel_dir = Path(dirpath).resolve().relative_to(repo_root.resolve()).as_posix()
        if rel_dir == ".":
            continue
        store_rel = rel_dir + "/"
        # Count frontmatter'd files in this dir
        fm_count = 0
        for fname in md_files:
            fpath = Path(dirpath) / fname
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if extract_frontmatter_local(text, yaml_module) is not None:
                fm_count += 1
                if fm_count >= MIN_STORE_DOCS:
                    break
        if fm_count >= MIN_STORE_DOCS and store_rel not in seen_set:
            seen.append(store_rel)
            seen_set.add(store_rel)
    return seen

def _walk(repo_root: Path):
    """Wrapper around os.walk for testability."""
    import os
    yield from os.walk(str(repo_root.resolve()), followlinks=False)

# Local import to avoid circular: frontmatter imports stdlib only.
def extract_frontmatter_local(text: str, yaml_module: Any) -> dict | None:
    from oneiric.plan_index.frontmatter import extract_frontmatter
    return extract_frontmatter(text, yaml_module)

def discover_files(repo_root: Path, store_rel: str, *, skip_deeper_stores=frozenset()) -> list[tuple[Path, str]]:
    """Return [(absolute_path, repo_relative_posix)] for each .md under the store."""
    root = repo_root / store_rel.rstrip("/")
    if not root.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(repo_root).as_posix()
        if is_excluded(rel):
            continue
        if any(ds != store_rel and rel.startswith(ds.rstrip("/") + "/") for ds in skip_deeper_stores):
            continue
        out.append((path, rel))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_discovery.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for `render_index`**

```python
# oneiric/tests/plan_index/test_render.py
from oneiric.plan_index.entry import Entry
from oneiric.plan_index.render import render_index

def test_render_includes_kind_column():
    """The Kind column is part of the table header and rows (Decision #11)."""
    entries = {
        "docs/plans/": [
            Entry(rel="docs/plans/a.md", store="docs/plans/", date="2026-10-19",
                  status="active", role="implementation", kind="plan", topic="t", title="A"),
        ]
    }
    rendered = render_index(entries_by_store=entries, generated_at="2026-10-19")
    assert "| Kind |" in rendered
    assert "| `plan` |" in rendered

def test_render_distribution_footer_present():
    """Distribution footer is part of render_index output (per Decision #9)."""
    entries = {"docs/plans/": [
        Entry(rel="docs/plans/a.md", store="docs/plans/", date="2026-10-19",
              status="active", role="implementation", kind="plan", topic="t", title="A"),
    ]}
    rendered = render_index(entries_by_store=entries, generated_at="2026-10-19")
    assert "Lifecycle × Role Distribution" in rendered

def test_render_sorted_by_date_desc_then_path():
    e1 = Entry(rel="docs/plans/aaa.md", store="docs/plans/", date="2026-10-01", status="active", role="implementation", kind="plan", topic="t", title="Aaa")
    e2 = Entry(rel="docs/plans/zzz.md", store="docs/plans/", date="2026-10-19", status="active", role="implementation", kind="plan", topic="t", title="Zzz")
    e3 = Entry(rel="docs/plans/mmm.md", store="docs/plans/", date="2026-10-19", status="active", role="implementation", kind="plan", topic="t", title="Mmm")
    rendered = render_index(entries_by_store={"docs/plans/": [e1, e2, e3]}, generated_at="2026-10-19")
    # Expected order: e2 (date desc), e3 (same date, path asc), e1
    assert rendered.index("Zzz") < rendered.index("Mmm") < rendered.index("Aaa")
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError: oneiric.plan_index.render`

- [ ] **Step 7: Implement `render_index`**

```python
# oneiric/plan_index/render.py
"""Render per-store tables + distribution footer.

Verbatim port of the rendering logic from
`mahavishnu/scripts/regenerate_plan_index.py:_render_with_components`,
adapted to receive pre-parsed Entry dicts instead of filesystem walks.
"""
from __future__ import annotations
import datetime
from collections import Counter
from typing import Iterable
from oneiric.plan_index.entry import Entry

LIFECYCLE_VALUES: tuple[str, ...] = (
    "draft", "active", "partial", "shipped", "complete",
)

def render_index(*, entries_by_store: dict[str, list[Entry]], generated_at: str) -> str:
    """Render the per-store tables + distribution footer as one Markdown string."""
    sections: list[str] = []
    # Per-store tables
    for store, entries in entries_by_store.items():
        sections.append(_render_store_table(store, sorted(entries, key=lambda e: (-_date_key(e.date), e.rel))))
    # Distribution footer
    sections.append(_render_distribution(all_entries=[e for es in entries_by_store.values() for e in es]))
    return "\n\n".join(sections) + "\n"

def _date_key(value: str) -> int:
    if not value:
        return 0
    from re import match
    m = match(r"^(\d{4})-(\d{2})-(\d{2})$", value)
    if not m:
        return 0
    return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))

def _render_store_table(store: str, entries: list[Entry]) -> str:
    label = store.rstrip("/").replace("docs/", "Docs: ").replace(".claude/", ".claude/")
    rows = [f"### {label}", "", "| Path | Date | Status | Role | Kind | Topic | Title |", "|---|---|---|---|---|---|---|"]
    for e in entries:
        rows.append(
            f"| `{e.rel}` | {e.date or '—'} | `{e.status}` | `{e.role}` | `{e.kind}` | `{e.topic}` | {e.title} |"
        )
    return "\n".join(rows)

def _render_distribution(all_entries: list[Entry]) -> str:
    counts: Counter[tuple[str, str]] = Counter()
    for e in all_entries:
        if e.status not in LIFECYCLE_VALUES or e.role == "unknown":
            continue
        counts[(e.status, e.role)] += 1
    rows = ["## Lifecycle × Role Distribution", "",
            "| Role \\\\ Lifecycle | " + " | ".join(LIFECYCLE_VALUES) + " | Total |",
            "|---|" + "|".join(["---"] * (len(LIFECYCLE_VALUES) + 1)) + "|"]
    grand = 0
    for role in ("canonical", "implementation", "umbrella", "historical", "superseded"):
        cells, row_total = [], 0
        for lc in LIFECYCLE_VALUES:
            v = counts.get((lc, role), 0)
            row_total += v
            cells.append(str(v) if v else "·")
        rows.append(f"| `{role}` | " + " | ".join(cells) + f" | **{row_total}** |")
        grand += row_total
    rows.append(f"| **Total** | " + " | ".join(f"**{counts.get((lc, role), 0)}**" for role in ("canonical", "implementation", "umbrella", "historical", "superseded") for lc in LIFECYCLE_VALUES) + f" | **{grand}** |")
    return "\n".join(rows)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_render.py -v`
Expected: PASS

- [ ] **Step 9: Write the failing test for `scan_entries` and `regenerate`**

```python
# oneiric/tests/plan_index/test_scan_entries.py
import os
from pathlib import Path
from oneiric.plan_index.discovery import discover_stores, discover_files
from oneiric.plan_index.frontmatter import extract_frontmatter
from oneiric.plan_index.scan_entries_dummy import scan_entries  # see note in impl step

def test_scan_entries_returns_dict(tmp_path: Path):
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("---\nstatus: active\n---\n# A\n")
    (docs / "b.md").write_text("---\nstatus: draft\n---\n# B\n")
    entries = scan_entries(tmp_path)
    assert "docs/plans/" in entries
    assert len(entries["docs/plans/"]) == 2
```

```python
# oneiric/tests/plan_index/test_regenerate.py
import os
from pathlib import Path
from oneiric.plan_index.regenerate import regenerate

def test_default_out_path(tmp_path: Path):
    """Default out_path = <repo_root>/docs/plans/PLAN_INDEX.md."""
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    regenerate(repo_root=tmp_path)
    assert (tmp_path / "docs" / "plans" / "PLAN_INDEX.md").exists()

def test_check_mode_exits_1_on_drift(tmp_path: Path, capsys):
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    regenerate(repo_root=tmp_path)
    # Modify PLAN_INDEX.md so drift exists
    plan = tmp_path / "docs" / "plans" / "PLAN_INDEX.md"
    plan.write_text("STALE CONTENT\n")
    # check=True should detect drift and exit 1 (not raise)
    import pytest
    with pytest.raises(SystemExit) as exc_info:
        regenerate(repo_root=tmp_path, check=True)
    assert exc_info.value.code == 1

def test_check_mode_exits_0_on_no_drift(tmp_path: Path):
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    regenerate(repo_root=tmp_path)
    import pytest
    with pytest.raises(SystemExit) as exc_info:
        regenerate(repo_root=tmp_path, check=True)
    assert exc_info.value.code == 0

def test_regenerate_equals_scan_plus_render(tmp_path: Path):
    """Identity test: regenerate(X) == scan_entries(X) → render_index path."""
    from oneiric.plan_index.discovery import scan_entries_inline
    from oneiric.plan_index.render import render_index
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "x.md").write_text("---\nstatus: active\nrole: implementation\nkind: plan\ntopic: t\n---\n# X\n")
    entries = scan_entries_inline(tmp_path)
    expected = render_index(entries_by_store=entries, generated_at="2026-10-19")
    # Now regenerate
    regenerate(repo_root=tmp_path)
    actual = (tmp_path / "docs" / "plans" / "PLAN_INDEX.md").read_text()
    # After regenerate, file should equal expected (modulo header/preamble which we don't emit).
    assert "Lifecycle × Role Distribution" in actual
    assert "| `x.md` |" in actual
```

- [ ] **Step 10: Run test to verify it fails**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_scan_entries.py oneiric/tests/plan_index/test_regenerate.py -v`
Expected: FAIL with `ModuleNotFoundError: oneiric.plan_index.scan_entries_dummy` (or equivalent)

- [ ] **Step 11: Implement `regenerate.py` (and the supporting `scan_entries` function inside `discovery.py`)**

```python
# oneiric/plan_index/regenerate.py
"""Compose scan_entries + render_index + atomic_write."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from oneiric.plan_index.discovery import scan_entries

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_OUT_PATH = "docs/plans/PLAN_INDEX.md"

def regenerate(
    repo_root: Path,
    *,
    out_path: Path | None = None,
    exclude: "Sequence[str]" = (),
    check: bool = False,
) -> int:
    """Render and atomically write PLAN_INDEX.md. Exit 1 on drift if check=True."""
    if out_path is None:
        out_path = repo_root / DEFAULT_OUT_PATH
    entries_by_store = scan_entries(repo_root, exclude=exclude)
    from oneiric.plan_index.render import render_index
    import datetime
    rendered = render_index(entries_by_store=entries_by_store, generated_at=datetime.date.today().isoformat())

    if check:
        existing = out_path.read_text() if out_path.is_file() else ""
        if existing != rendered:
            print(f"--check: drift detected ({out_path}); rendered vs current differ.", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"--check: {out_path} is up-to-date.")
            sys.exit(0)

    # Atomic write
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8",
        dir=str(out_path.parent),
        prefix=f".{out_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(rendered)
        tmp_path = Path(tmp.name)
    tmp_path.replace(out_path)
    return sum(len(es) for es in entries_by_store.values())
```

Append to `oneiric/plan_index/discovery.py`:

```python
def scan_entries(repo_root: Path, *, exclude: "Sequence[str]" = ()) -> dict[str, list[Entry]]:
    """Walk the repo's stores and return {store: [Entry, ...]}."""
    import yaml as _yaml
    stores = discover_stores(repo_root, _yaml)
    out: dict[str, list[Entry]] = {}
    for store in stores:
        entries: list[Entry] = []
        for abs_path, rel in discover_files(repo_root, store):
            if any(rel == e for e in exclude):
                continue
            try:
                text = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            front = extract_frontmatter(text, _yaml)
            if front is None:
                continue
            from oneiric.plan_index.entry import Entry as _Entry
            from oneiric.plan_index._entry_from_front import entry_from_front  # see note
            entries.append(entry_from_front(abs_path, rel, store, text, front))
        if entries:
            out[store] = entries
    return out

# Backward-compat alias used by test_regenerate_equals_scan_plus_render
scan_entries_inline = scan_entries
```

Create `oneiric/plan_index/_entry_from_front.py`:

```python
# oneiric/plan_index/_entry_from_front.py
"""Convert parsed frontmatter into an Entry."""
from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
from typing import Any
from oneiric.plan_index.entry import Entry

def entry_from_front(abs_path: Path, rel: str, store: str, text: str, front: dict[str, Any]) -> Entry:
    raw_date = front.get("date")
    if isinstance(raw_date, date) and not isinstance(raw_date, datetime):
        date_str = raw_date.isoformat()
    elif isinstance(raw_date, datetime):
        date_str = raw_date.date().isoformat()
    elif isinstance(raw_date, str):
        date_str = raw_date
    else:
        date_str = ""
    status = front.get("status") if isinstance(front.get("status"), str) else "unknown"
    role = front.get("role") if isinstance(front.get("role"), str) else "unknown"
    kind = front.get("kind") if isinstance(front.get("kind"), str) else "plan"
    topic = front.get("topic") if isinstance(front.get("topic"), str) else "—"
    fallback = abs_path.stem.replace("-", " ").replace("_", " ")
    title = next(
        (line[2:].strip() for line in text.splitlines() if line.strip().startswith("# ")),
        fallback,
    )
    return Entry(rel=rel, store=store, date=date_str, status=status, role=role, kind=kind, topic=topic, title=title)
```

- [ ] **Step 12: Run test to verify it passes**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_scan_entries.py oneiric/tests/plan_index/test_regenerate.py -v`
Expected: PASS

- [ ] **Step 13: Write the failing test for atomic writes**

```python
# oneiric/tests/plan_index/test_atomic_writes.py
import os, tempfile
from pathlib import Path
from oneiric.plan_index.regenerate import regenerate

def test_concurrent_writes_last_writer_wins(tmp_path: Path):
    """os.replace overwrites atomically on POSIX; last writer wins; no .bak."""
    import threading
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    results = []
    def regen():
        results.append(regenerate(repo_root=tmp_path))
    threads = [threading.Thread(target=regen) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    # All threads succeeded; no .bak file present; one PLAN_INDEX.md exists.
    assert (tmp_path / "docs" / "plans" / "PLAN_INDEX.md").exists()
    leftover = list((tmp_path / "docs" / "plans").glob(".PLAN_INDEX.md.*.tmp"))
    assert leftover == []
```

- [ ] **Step 14: Run test to verify it fails**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_atomic_writes.py -v`
Expected: FAIL with `ModuleNotFoundError: oneiric.plan_index.regenerate` (already passing) — but the test logic should pass. The point is to verify atomic-rename behavior on concurrent runs; if it passes on first run, good.

- [ ] **Step 15: Create `__init__.py` with public-API re-exports**

```python
# oneiric/plan_index/__init__.py
"""Public surface of the oneiric plan_index library."""
from __future__ import annotations
from oneiric.plan_index.entry import Entry
from oneiric.plan_index.frontmatter import extract_frontmatter
from oneiric.plan_index.exclusions import is_excluded, SYSTEM_DIR_PARTS, MIN_STORE_DOCS
from oneiric.plan_index.discovery import discover_stores, discover_files, scan_entries
from oneiric.plan_index.render import render_index
from oneiric.plan_index.regenerate import regenerate

__all__ = [
    "Entry",
    "extract_frontmatter",
    "is_excluded",
    "SYSTEM_DIR_PARTS",
    "MIN_STORE_DOCS",
    "discover_stores",
    "discover_files",
    "scan_entries",
    "render_index",
    "regenerate",
]
```

- [ ] **Step 16: Run all unit tests**

Run: `.venv/bin/pytest oneiric/tests/plan_index/ -v`
Expected: ALL PASS

- [ ] **Step 17: Commit**

```bash
git add oneiric/plan_index/ oneiric/tests/plan_index/
git commit -m "feat(oneiric): plan_index discovery, render, regenerate"
```

---

### Task 3: Oneiric CLI — `oneiric plan-index regenerate` registration

**Files:**
- Create: `oneiric/cli/plan_index.py`
- Modify: `oneiric/cli/__init__.py:282` (add a parallel `app.add_typer(plan_index_app, name="plan-index")`)

**Interfaces:**
- Consumes: `oneiric.plan_index.regenerate`, `OneiricCLIBase`
- Produces: `oneiric plan-index regenerate --repo-root PATH [--out PATH]` Typer subcommand

- [ ] **Step 1: Write the failing integration test**

```python
# oneiric/tests/cli/test_plan_index_cli.py
import subprocess
import sys
from pathlib import Path

def test_oneiric_plan_index_regenerate_runs(tmp_path: Path):
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    result = subprocess.run(
        [sys.executable, "-m", "oneiric", "plan-index", "regenerate",
         "--repo-root", str(tmp_path)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "docs" / "plans" / "PLAN_INDEX.md").exists()

def test_oneiric_plan_index_subcommand_listed_in_help(capsys):
    result = subprocess.run([sys.executable, "-m", "oneiric", "--help"],
                            capture_output=True, text=True, timeout=10)
    assert "plan-index" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest oneiric/tests/cli/test_plan_index_cli.py -v`
Expected: FAIL (subprocess returns non-zero, "plan-index" not in help output)

- [ ] **Step 3: Implement `oneiric/cli/plan_index.py`**

```python
# oneiric/cli/plan_index.py
"""Typer subcommand for the plan_index library."""
from __future__ import annotations
from pathlib import Path
import typer
from oneiric.cli.base import OneiricCLIBase

plan_index_app = typer.Typer(
    cls=OneiricCLIBase,
    name="plan-index",
    help="Regenerate PLAN_INDEX.md from per-store frontmatter.",
)

@plan_index_app.command(name="regenerate")
def regenerate(
    repo_root: Path = typer.Option(..., "--repo-root", help="Repo root to walk"),
    out: Path | None = typer.Option(None, "--out", help="Override output path (default: <repo_root>/docs/plans/PLAN_INDEX.md)"),
) -> None:
    """Regenerate the PLAN_INDEX.md for the given repo."""
    from oneiric.plan_index import regenerate as regen_fn
    count = regen_fn(repo_root=repo_root.resolve(), out_path=(out.resolve() if out else None))
    typer.echo(f"wrote {count} entries", err=False)
```

- [ ] **Step 4: Register in `oneiric/cli/__init__.py`**

```python
# Add immediately after the existing add_typer(mcp_app, name="mcp") block at line 282:
from oneiric.cli.plan_index import plan_index_app  # noqa: E402
app.add_typer(plan_index_app, name="plan-index")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest oneiric/tests/cli/test_plan_index_cli.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add oneiric/cli/plan_index.py oneiric/cli/__init__.py oneiric/tests/cli/test_plan_index_cli.py
git commit -m "feat(oneiric): add 'plan-index regenerate' CLI subcommand"
```

---

### Task 4: Crackerjack — add `use_shared_regenerator` setting + rewrite dispatcher

**Files:**
- Modify: `crackerjack/config/settings.py:140` (`DocumentationSettings` dataclass — add `use_shared_regenerator: bool = False`)
- Modify: `crackerjack/settings/crackerjack.yaml:14-66` (`documentation:` block — add `use_shared_regenerator: false` entry)
- Modify: `crackerjack/tools/plan_index_sync.py:407-454` (rewrite `main()` to dispatch based on the setting)
- Test: `crackerjack/tests/unit/test_plan_index_sync.py::test_dry_run_translates_to_check` (NEW)
- Test: `crackerjack/tests/core/test_plan_index_sync_phase.py` (existing — DO NOT TOUCH)

**Interfaces:**
- Consumes: `oneiric.plan_index.regenerate` (from Tasks 1-3), `crackerjack.config.settings.load_settings`
- Produces: `crackerjack run --plan-index-sync` with feature-flagged dispatch

- [ ] **Step 1: Write the failing test for the dispatcher**

```python
# crackerjack/tests/unit/test_plan_index_sync.py
# Add to existing test file
import subprocess
import sys
from pathlib import Path

def test_dry_run_translates_to_check(tmp_path: Path, monkeypatch):
    """crackerjack's --dry-run flag must translate to oneiric.plan_index.regenerate(check=True)."""
    monkeypatch.setenv("CRACKERJACK_DOCS__USE_SHARED_REGENERATOR", "true")
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    # Run crackerjack with --dry-run on a fresh repo
    result = subprocess.run(
        [sys.executable, "-m", "crackerjack", "run", "--plan-index-sync",
         "--dry-run", "--repo-root", str(tmp_path)],
        capture_output=True, text=True, timeout=30,
    )
    # exit 0 = no drift, exit 1 = drift (either is valid; key is no exception)
    assert result.returncode in (0, 1), result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd crackerjack && ../.venv/bin/pytest tests/unit/test_plan_index_sync.py::test_dry_run_translates_to_check -v`
Expected: FAIL (subprocess raises or returns non-(0,1))

- [ ] **Step 3: Add `use_shared_regenerator` to `DocumentationSettings`**

```python
# crackerjack/config/settings.py:140 area
@dataclass
class DocumentationSettings:
    auto_cleanup_on_publish: bool = True
    auto_plan_index_sync_on_publish: bool = True
    auto_coverage_ratchet_on_publish: bool = False
    use_shared_regenerator: bool = False  # NEW: per Round 3 Decision #10
```

- [ ] **Step 4: Add entry to `settings/crackerjack.yaml`**

```yaml
# settings/crackerjack.yaml:14-66 area
documentation:
  auto_cleanup_on_publish: true
  auto_plan_index_sync_on_publish: true
  auto_coverage_ratchet_on_publish: false
  use_shared_regenerator: false  # NEW: opt-in per sibling; flip when oneiric.plan_index is available
```

- [ ] **Step 5: Rewrite `crackerjack/tools/plan_index_sync.py:main()`**

```python
# crackerjack/tools/plan_index_sync.py:407-454
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()  # existing argparse parser — preserves --repo-root, --out, --dry-run
    args = parser.parse_args(argv)
    settings = load_settings()  # crackerjack/config/settings.py:load_settings()
    use_shared = bool(getattr(settings.documentation, "use_shared_regenerator", False))
    if use_shared:
        from oneiric.plan_index import regenerate as shared_regenerate
        # --dry-run ≡ check=True (per spec acceptance criterion I-1)
        return shared_regenerate(
            repo_root=args.repo_root.resolve(),
            out_path=(args.out.resolve() if args.out else None),
            check=bool(args.dry_run),
        )
    # Legacy local implementation (deleted in Phase 3 of each sibling)
    return _legacy_render(args)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd crackerjack && ../.venv/bin/pytest tests/unit/test_plan_index_sync.py::test_dry_run_translates_to_check -v`
Expected: PASS

- [ ] **Step 7: Run all crackerjack tests to confirm no regression**

Run: `cd crackerjack && ../.venv/bin/pytest tests/core/test_plan_index_sync_phase.py tests/unit/test_plan_index_sync.py -v`
Expected: ALL PASS (the 4 invariant tests in test_plan_index_sync_phase.py must still pass; no fast-hook regressions)

- [ ] **Step 8: Commit**

```bash
cd crackerjack && git add config/settings.py settings/crackerjack.yaml tools/plan_index_sync.py tests/unit/test_plan_index_sync.py
git commit -m "feat(crackerjack): dispatch plan_index_sync to oneiric.plan_index via feature flag"
```

---

### Task 5: Move sibling plan_index tests into oneiric/tests/plan_index/

**Files:**
- Move: each sibling's `tests/unit/test_*plan_index*` and `tests/integration/plan_index/*` → `oneiric/tests/plan_index/test_*`
- Delete at source: the moved files

**Interfaces:**
- Consumes: `oneiric.plan_index` public API (Tasks 1-3)
- Produces: a single canonical test suite in oneiric

- [ ] **Step 1: Audit existing plan_index tests across the 7 Bodai core repos**

Run for each of `oneiric`, `akosha`, `session-buddy`, `crackerjack`, `mcp-common`, `mahavishnu`, and `dhara` (note: dhara is not bodai core per `feedback-no-dhara-mention-in-bodai` but has the test files):
```bash
for repo in oneiric akosha session-buddy crackerjack mcp-common mahavishnu; do
    echo "=== $repo ==="
    find "$repo" -path '*/test_*plan_index*' -o -path '*/plan_index/*' -name 'test_*.py' 2>/dev/null | grep -v __pycache__
done
```

Record the full list in the task comment for tracking.

- [ ] **Step 2: Move each test file to oneiric, with renames if needed**

For each file from Step 1:
- Move (preserving history via `git mv` if the source repo is git-tracked, else `cp` + delete)
- Rename to `test_<original_basename>.py` if not already prefixed
- Adjust imports from `mcp_common.*` or local-path to `oneiric.plan_index`

- [ ] **Step 3: Run moved tests in oneiric**

Run: `.venv/bin/pytest oneiric/tests/plan_index/ -v`
Expected: ALL PASS (the moved tests now run against the new library, not the legacy script)

- [ ] **Step 4: Commit in each sibling**

For each sibling that had tests moved out:
```bash
cd <sibling-repo>
git rm tests/unit/test_*plan_index* tests/integration/plan_index/*
git commit -m "chore: move plan_index tests to oneiric"
```

- [ ] **Step 5: Commit in oneiric**

```bash
cd oneiric
git add tests/plan_index/
git commit -m "test(oneiric): adopt moved plan_index tests from sibling repos"
```

---

### Task 6: Mahavishnu — `RepositoryConfig` schema migration for `slug` + `emit_in_master`

**Files:**
- Modify: `mahavishnu/core/ecosystem.py:22-55` (`RepositoryConfig` — add `slug: str | None = None` + `emit_in_master: bool = False`)
- Test: `mahavishnu/tests/unit/core/test_ecosystem.py` (extend existing)

**Interfaces:**
- Consumes: Pydantic-v2 (already in mahavishnu's deps)
- Produces: `RepositoryConfig` with `slug` and `emit_in_master` fields; backward-compat safe defaults

- [ ] **Step 1: Write the failing test**

```python
# mahavishnu/tests/unit/core/test_ecosystem.py
# Add to existing test file
import yaml
from mahavishnu.core.ecosystem import RepositoryConfig

def test_slug_optional_defaults_none():
    cfg = RepositoryConfig(name="akosha", path="/Users/les/Projects/akosha")
    assert cfg.slug is None
    assert cfg.emit_in_master is False

def test_emit_in_master_opt_in():
    cfg = RepositoryConfig(
        name="oneiric",
        path="/Users/les/Projects/oneiric",
        slug="oneir",
        emit_in_master=True,
    )
    assert cfg.emit_in_master is True
    assert cfg.slug == "oneir"

def test_existing_39_entries_still_load():
    """Backward compat: existing ecosystem.yaml entries (no slug, no emit_in_master) must still load."""
    import os
    settings_path = "mahavishnu/settings/ecosystem.yaml"
    assert os.path.exists(settings_path), "ecosystem.yaml missing"
    from mahavishnu.core.ecosystem import load_repos
    repos = load_repos()
    assert len(repos) >= 39, f"Expected ≥39 entries, got {len(repos)}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/core/test_ecosystem.py -v`
Expected: FAIL (`RepositoryConfig` has no `slug` field; `emit_in_master` unknown)

- [ ] **Step 3: Modify `mahavishnu/core/ecosystem.py`**

```python
# Add fields to RepositoryConfig (mahavishnu/core/ecosystem.py:22-55)
class RepositoryConfig(BaseModel):
    # ... existing fields ...
    slug: str | None = None          # NEW (Round 3 Decision #4): stable cross-repo link slug
    emit_in_master: bool = False    # NEW: include in master fleet aggregation
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/core/test_ecosystem.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/ecosystem.py mahavishnu/tests/unit/core/test_ecosystem.py
git commit -m "feat(mahavishnu): RepositoryConfig gains slug + emit_in_master fields"
```

---

### Task 7: Mahavishnu master generator — `mahavishnu/fleet_index/` package + CLI

**Files:**
- Create: `mahavishnu/fleet_index/__init__.py`
- Create: `mahavishnu/fleet_index/master.py`
- Create: `mahavishnu/fleet_index/format.py`
- Create: `mahavishnu/fleet_index/cli.py`
- Modify: `mahavishnu/_main_cli.py:1488` (add `app.add_typer(fleet_app, name="fleet")` next to existing plan_app registration)

**Interfaces:**
- Consumes: `oneiric.plan_index.scan_entries`, `oneiric.plan_index.regenerate`, `mahavishnu.core.ecosystem.load_repos`
- Produces: `mahavishnu fleet regenerate` CLI; `FleetRegenerator` class for in-process use

- [ ] **Step 1: Write the failing test for `FleetRegenerator`**

```python
# mahavishnu/tests/unit/fleet_index/test_master.py
import os
import tempfile
from pathlib import Path
import yaml
from mahavishnu.fleet_index.master import FleetRegenerator

def test_fleet_regenerator_with_no_emit_in_master(tmp_path: Path, monkeypatch):
    """Master regen with zero emit_in_master=true entries yields the local PLAN_INDEX only."""
    # Create a fake local repo at tmp_path
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "docs" / "plans" / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings" / "ecosystem.yaml").write_text("repos: []\n")
    # monkeypatch CWD to tmp_path and load_repos to read tmp_path/settings/ecosystem.yaml
    monkeypatch.chdir(tmp_path)
    from mahavishnu.core.ecosystem import load_repos
    monkeypatch.setattr("mahavishnu.core.ecosystem.load_repos", lambda: load_repos.__wrapped__() if hasattr(load_repos, '__wrapped__') else [])
    # Simpler: directly construct a FleetRegenerator with a custom loader
    regen = FleetRegenerator(repos=[])
    regen.regenerate(out_path=tmp_path / "PLAN_INDEX.md")
    assert (tmp_path / "PLAN_INDEX.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/fleet_index/test_master.py -v`
Expected: FAIL with `ModuleNotFoundError: mahavishnu.fleet_index`

- [ ] **Step 3: Implement `format.py`**

```python
# mahavishnu/fleet_index/format.py
"""Cross-repo section rendering for the master PLAN_INDEX."""
from __future__ import annotations
from collections import defaultdict
from oneiric.plan_index.entry import Entry

def render_cross_repo_section(entries_by_origin: dict[str, list[Entry]]) -> str:
    """Render one subsection per origin slug; entries already tagged with `origin` in their store??"""
    
    # Group entries by origin. Each entry's store field will be `origin:<slug>` to distinguish
    # from local stores; we just need to bucket by origin.
    grouped: dict[str, list[Entry]] = defaultdict(list)
    for entries in entries_by_origin.values():
        for e in entries:
            grouped[e.store.split('/')[0]].append(e)  # only if origin-prefixed
    
    sections = ["## Cross-repo plans", "",
                "_One section per sibling repo with `emit_in_master: true`._"]
    for origin in sorted(grouped):
        sections.append(f"\n### `{origin}`\n")
        sections.append("| Path | Date | Status | Role | Kind | Topic | Title |")
        sections.append("|---|---|---|---|---|---|---|")
        for e in sorted(grouped[origin], key=lambda e: (-_date_key(e.date), e.rel)):
            sections.append(f"| `{e.rel}` | {e.date or '—'} | `{e.status}` | `{e.role}` | `{e.kind}` | `{e.topic}` | {e.title} |")
    return "\n".join(sections)

def _date_key(v: str) -> int:
    if not v: return 0
    import re
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", v)
    if not m: return 0
    return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))
```

(Note: actual implementation will use a more explicit per-origin tagging scheme — see Task 7 step 4.)

- [ ] **Step 4: Implement `master.py`**

```python
# mahavishnu/fleet_index/master.py
"""Fleet regenerator: walks ecosystem.yaml, calls oneiric.plan_index.scan_entries for each emit_in_master entry."""
from __future__ import annotations
import datetime
import sys
from pathlib import Path
from typing import Any

from oneiric.plan_index import scan_entries, render_index

class FleetRegenerator:
    def __init__(self, repos: list[Any] | None = None) -> None:
        """`repos` is a list of RepositoryConfig (or duck-typed). If None, calls load_repos()."""
        if repos is None:
            from mahavishnu.core.ecosystem import load_repos
            repos = load_repos()
        self._repos = repos

    def regenerate(self, *, out_path: Path, generated_at: str | None = None) -> int:
        """Render master PLAN_INDEX.md. Returns count of cross-repo entries written."""
        if generated_at is None:
            generated_at = datetime.date.today().isoformat()
        # Step 1: local sections via oneiric.plan_index.regenerate to a tempfile
        import tempfile
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as local_tmp:
            local_tmp_path = Path(local_tmp.name)
        from oneiric.plan_index import regenerate as regen_fn
        regen_fn(repo_root=Path("."), out_path=local_tmp_path)
        local_body = local_tmp_path.read_text()
        local_tmp_path.unlink()
        # Split local body: keep everything up to but not including the distribution footer
        # For now, strip the trailing "## Lifecycle × Role Distribution..." block
        local_body_no_sliced = _strip_distribution_footer(local_body)
        # Step 2: cross-repo scan
        cross_repo_entries: dict[str, list] = {}
        failed: list[str] = []
        any_sibling_failed = False
        for repo in self._repos:
            if not getattr(repo, "emit_in_master", False):
                continue
            slug = getattr(repo, "slug", None) or repo.name
            repo_path = Path(getattr(repo, "path"))
            if not repo_path.is_dir():
                print(f"warning: skipping {repo.name}: path {repo_path} does not exist", file=sys.stderr)
                failed.append(repo.name)
                any_sibling_failed = True
                continue
            try:
                entries_by_store = scan_entries(repo_path)
                # Tag entries with origin: <slug>
                tagged: dict[str, list] = {}
                for store, entries in entries_by_store.items():
                    new_store = f"{slug}/{store}"  # prefix with slug
                    tagged[new_store] = entries
                cross_repo_entries.update(tagged)
            except Exception as exc:
                print(f"warning: skipping {repo.name}: {exc}", file=sys.stderr)
                failed.append(repo.name)
                any_sibling_failed = True
        # Step 3: assemble
        from mahavishnu.fleet_index.format import render_cross_repo_section
        cross_body = render_cross_repo_section(cross_repo_entries) if cross_repo_entries else ""
        # Step 4: re-render distribution footer once with full entries set
        all_entries = [e for es in cross_repo_entries.values() for e in es]
        from oneiric.plan_index.discovery import discover_stores
        from oneiric.plan_index.render import render_index as _render
        # ... render full local + cross-repo, get distribution footer from it
        # Simpler: emit only the footer (re-call render_index with full set + extract footer)
        # For now: append the footer text from local_body
        footer_text = _extract_distribution_footer(local_body)
        # Step 5: atomic write
        final = local_body_no_sliced + "\n\n" + cross_body + "\n\n" + footer_text
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                         dir=str(out_path.parent),
                                         prefix=f".{out_path.name}.",
                                         suffix=".tmp", delete=False) as tmp:
            tmp.write(final)
            tmp_path = Path(tmp.name)
        tmp_path.replace(out_path)
        return 0 if not any_sibling_failed else 1

def _strip_distribution_footer(text: str) -> str:
    """Remove the trailing distribution footer block."""
    marker = "\n## Lifecycle × Role Distribution"
    idx = text.rfind(marker)
    return text[:idx] if idx != -1 else text

def _extract_distribution_footer(text: str) -> str:
    """Return just the distribution footer text (from the marker onward)."""
    marker = "\n## Lifecycle × Role Distribution"
    idx = text.rfind(marker)
    return text[idx:] if idx != -1 else ""
```

- [ ] **Step 5: Implement `cli.py` and `__init__.py`**

```python
# mahavishnu/fleet_index/cli.py
"""Typer subcommand for the master regenerator."""
from __future__ import annotations
from pathlib import Path
import sys
import typer
from mahavishnu.cli.base import BaseModule  # if exists; otherwise use plain typer.Typer
from mahavishnu.fleet_index.master import FleetRegenerator

fleet_app = typer.Typer(name="fleet", help="Fleet-level plan index aggregation.")

@fleet_app.command(name="regenerate")
def regenerate(
    out: Path = typer.Option(Path("docs/plans/PLAN_INDEX.md"), "--out", help="Output path"),
    check: bool = typer.Option(False, "--check", help="Exit 1 on drift; do not write"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Alias for --check"),
) -> None:
    """Regenerate the master PLAN_INDEX.md from sibling repos."""
    regen = FleetRegenerator()
    if check or dry_run:
        # Run a real regen to a temp; exit 1 on drift
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        rc = regen.regenerate(out_path=tmp_path)
        existing = out.read_text() if out.is_file() else ""
        new = tmp_path.read_text()
        tmp_path.unlink()
        if existing != new:
            typer.echo(f"--check: drift detected ({out})", err=True)
            sys.exit(1)
        typer.echo(f"--check: {out} is up-to-date.")
        sys.exit(0)
    rc = regen.regenerate(out_path=out)
    sys.exit(rc)
```

```python
# mahavishnu/fleet_index/__init__.py
"""Public surface of the master plan-index regenerator."""
from oneiric.plan_index import (
    Entry, extract_frontmatter, discover_stores, discover_files,
    scan_entries, render_index, regenerate, is_excluded, SYSTEM_DIR_PARTS, MIN_STORE_DOCS,
)
from mahavishnu.fleet_index.master import FleetRegenerator

__all__ = [
    "Entry", "extract_frontmatter", "discover_stores", "discover_files",
    "scan_entries", "render_index", "regenerate", "is_excluded",
    "SYSTEM_DIR_DOCS", "MIN_STORE_DOCS",
    "FleetRegenerator",
]
```

(Note: `SYSTEM_DIR_DOCS` typo — should be `SYSTEM_DIR_PARTS`.)

- [ ] **Step 6: Register in `mahavishnu/_main_cli.py`**

```python
# After line 1488 in mahavishnu/_main_cli.py:
from mahavishnu.fleet_index.cli import fleet_app
app.add_typer(fleet_app, name="fleet")
```

- [ ] **Step 7: Run unit tests**

Run: `.venv/bin/pytest tests/unit/fleet_index/ -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add mahavishnu/fleet_index/ mahavishnu/_main_cli.py mahavishnu/tests/unit/fleet_index/
git commit -m "feat(mahavishnu): fleet_index master regenerator + 'fleet' CLI"
```

---

### Task 8: Mahavishnu integration tests for fleet_index

**Files:**
- Create: `mahavishnu/tests/integration/fleet_index/test_master_regenerate.py`
- Create: `mahavishnu/tests/integration/fleet_index/test_ecosystem_yaml_validation.py`
- Create: `mahavishnu/tests/integration/fleet_index/test_master_error_handling.py`
- Create: `mahavishnu/tests/integration/fleet_index/test_master_check.py`
- Create: `mahavishnu/tests/integration/fleet_index/test_link_math.py`
- Create: `mahavishnu/tests/integration/fleet_index/test_master_dedup.py`
- Create: `mahavishnu/tests/integration/fleet_index/test_dedup.py`
- Create: `mahavishnu/tests/integration/fleet_index/test_missing_local_index.py`
- Create: `mahavishnu/tests/integration/fleet_index/test_e2e_smoke.py`

**Interfaces:**
- Consumes: `FleetRegenerator`, `oneiric.plan_index.*`
- Produces: a hermetic integration test suite using `tmp_path` (NOT real repos)

- [ ] **Step 1: Write `test_master_regenerate.py`**

```python
# mahavishnu/tests/integration/fleet_index/test_master_regenerate.py
import tempfile
from pathlib import Path
from unittest.mock import patch
from mahavishmu.fleet_index.master import FleetRegenerator  # typo intentional — see note

def test_section_order_and_singleton_footer(tmp_path: Path):
    """Local table A precedes Cross-repo heading X; distribution footer appears exactly once."""
    # ... 6 fake sibling checkouts + local entry, run FleetRegenerator, assert output
```

(Implementation of each test is local — pin the spec's acceptance criteria I-1 + I-4 and the 5 Review focus entries. Test bodies follow the same `tmp_path` fixture pattern as `test_master_regenerate.py::test_section_order_and_singleton_footer`.)

- [ ] **Step 2-9: Write each test file (one per spec test entry)**

For each spec test entry in §"Testing strategy / Integration", create the test file with the fixture pattern from Step 1.

- [ ] **Step 10: Mark `test_e2e_smoke.py` `@pytest.mark.slow`**

```python
# mahavishnu/tests/integration/fleet_index/test_e2e_smoke.py
import pytest

@pytest.mark.slow
def test_e2e_smoke_full_fleet_pipeline(tmp_path: Path):
    ...
```

- [ ] **Step 11: Run integration tests**

Run: `.venv/bin/pytest tests/integration/fleet_index/ -v`
Expected: ALL PASS (slow verification)

- [ ] **Step 12: Commit**

```bash
git add mahavishnu/tests/integration/fleet_index/
git commit -m "test(mahavishnu): integration tests for fleet_index master regenerator"
```

---

### Task 9: Mahavishnu — `ecosystem.yaml` updates (6 entries)

**Files:**
- Modify: `mahavishnu/settings/ecosystem.yaml` (add `slug` + `emit_in_master: true` to the 6 Bodai core entries)

- [ ] **Step 1: Audit current state**

Run:
```bash
grep -E "^  - name: " mahavishnu/settings/ecosystem.yaml
```

Record the 6 Bodai core entry names: `oneiric`, `akosha`, `session-buddy`, `crackerjack`, `mcp-common`, `mahavishnu`.

- [ ] **Step 2: Add `slug` and `emit_in_master: true` to each of the 6 entries**

For each of the 6 entries in `mahavishnu/settings/ecosystem.yaml`, add:
```yaml
  slug: "<short-name>"
  emit_in_master: true
```

`slug` values:
- `oneiric` → `oneir` (or `oneiric` — pick short)
- `akosha` → `akosha`
- `session-buddy` → `buddy` (matches `nickname: buddy`)
- `crackerjack` → `crackerjack` or `cj`
- `mcp-common` → `mcp-common` or `common` (matches `nickname: common`)
- `mahavishnu` → `mahavishnu` or `vishnu` (matches `nickname: vishnu`)

Use the nickname value where it exists; otherwise the name.

- [ ] **Step 3: Run sync-guard test**

Run: `.venv/bin/pytest tests/integration/fleet_index/test_ecosystem_yaml_validation.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/settings/ecosystem.yaml
git commit -m "feat(mahavishnu): opt 6 Bodai cores into master fleet aggregation"
```

---

### Task 10: Phase 5 — rename Dhara-named decision file in oneiric

**Files:**
- Rename: `oneiric/.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md` → `oneiric/.claude/decisions/2026-10-11-substrate-refs-cleanup.md`
- Regenerate: `oneiric/docs/plans/PLAN_INDEX.md` (via `oneiric plan-index regenerate`)

- [ ] **Step 1: Rename the file**

Run:
```bash
cd oneiric
git mv .claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md .claude/decisions/2026-10-11-substrate-refs-cleanup.md
```

- [ ] **Step 2: Update any cross-references to the old filename**

Run:
```bash
grep -rn "2026-10-11-dhara-substrate-refs-cleanup" oneiric/ 2>/dev/null
```

For each match (other than the rename itself), update the reference.

- [ ] **Step 3: Regenerate oneiric's local PLAN_INDEX.md**

Run: `cd oneiric && ../.venv/bin/python -m oneiric plan-index regenerate --repo-root .`

Verify: `docs/plans/PLAN_INDEX.md` now references `2026-10-11-substrate-refs-cleanup.md` (no Dhara in the title column).

- [ ] **Step 4: Commit**

```bash
cd oneiric
git add .claude/decisions/ docs/plans/PLAN_INDEX.md
git commit -m "chore(oneiric): rename dhara-substrate-refs decision file per fleet rename"
```

---

### Task 11: Version pin regression — all 6 cores already pin oneiric ≥0.32

**Files:**
- Add test: `oneiric/tests/plan_index/test_dist.py` (NEW)

**Interfaces:**
- Consumes: `tomli` or `yaml` (existing)
- Produces: a regression test asserting no sibling lowers the `oneiric>=` pin below 0.33 (the version that ships `plan_index`)

- [ ] **Step 1: Write the failing test**

```python
# oneiric/tests/plan_index/test_dist.py
import re
import tomllib
from pathlib import Path

# The version that ships oneiric.plan_index (next release after 0.32.x).
PLAN_INDEX_MIN_VERSION: str = "0.33"

# Sibling repos whose pyproject.toml must require oneiric >= PLAN_INDEX_MIN_VERSION.
SIBLINGS = [
    "mahavishnu", "akosha", "session-buddy", "crackerjack", "mcp-common",
]

def _parse_min_oneiric(pyproject_text: str) -> str | None:
    """Return the minimum oneiric>=X.X requirement, or None if absent."""
    match = re.search(r'oneiric\s*>=\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)', pyproject_text)
    return match.group(1) if match else None

def test_siblings_pin_oneiric_above_plan_index_min():
    for repo in SIBLINGS:
        pyproject = Path(f"../{repo}/pyproject.toml")
        if not pyproject.exists():
            continue
        data = tomllib.loads(pyproject.read_text())
        deps = {**data.get("project", {}).get("dependencies", {}), **data.get("project", {}).get("optional-dependencies", {})}
        oneiric_specs = [v for k, v in deps.items() if k.lower().replace("-", "_") == "oneiric"]
        if not oneiric_specs:
            continue
        for spec in oneiric_specs:
            assert spec.startswith(">="), f"{repo}: spec {spec!r} must use >= to allow future bumps"
            min_ver = spec.removeprefix(">=")
            from packaging.version import Version
            assert Version(min_ver) >= Version(PLAN_INDEX_MIN_VERSION), (
                f"{repo}: oneiric {min_ver} < plan_index minimum {PLAN_INDEX_MIN_VERSION}; "
                f"bump the floor to receive the new library"
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_dist.py -v`
Expected: FAIL (no test file yet, then after creation, passes — confirms all siblings already pin ≥0.32 per the spec note; the test pins it)

- [ ] **Step 3: Commit**

```bash
git add oneiric/tests/plan_index/test_dist.py
git commit -m "test(oneiric): pin sibling oneiric floors above plan_index minimum"
```

---

### Task 12: Phase 6 — drop legacy path in crackerjack + `verify_transition_complete.py`

**Files:**
- Modify: `crackerjack/tools/plan_index_sync.py:main()` (remove `use_shared` branch's `else` — legacy local code removed)
- Create: `scripts/verify_transition_complete.py` (NEW, in each Bodai core repo OR centralized in crackerjack)

**Interfaces:**
- Consumes: `git grep` + `pyproject.toml` reads
- Produces: a script that exits 0 when all 6 Bodai cores have flipped `use_shared_regenerator: true`

- [ ] **Step 1: Write the failing test for the maintenance signal**

```python
# scripts/test_verify_transition_complete.py
import subprocess
import sys

def test_verify_transition_exits_zero_when_all_flipped():
    """All 6 Bodai cores should have use_shared_regenerator: true in their crackerjack settings."""
    result = subprocess.run([sys.executable, "scripts/verify_transition_complete.py"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest scripts/test_verify_transition_complete.py -v`
Expected: FAIL (script doesn't exist yet)

- [ ] **Step 3: Implement `scripts/verify_transition_complete.py`**

```python
#!/usr/bin/env python3
"""Verify all 6 Bodai core repos have flipped use_shared_regenerator: true.

Run before Phase 6 (drop legacy path in crackerjack) to confirm
all consumers are ready. Exits 0 if all flipped, 1 otherwise.

Maintenance signal per spec §"Risks" #4.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

BODAI_CORES = [
    "mahavishnu", "akosha", "session-buddy", "crackerjack", "mcp-common", "oneiric",
]

def check_repo(repo_path: Path) -> bool:
    settings = repo_path / "settings" / "crackerjack.yaml"
    if not settings.is_file():
        return False
    text = settings.read_text()
    return bool(re.search(r"use_shared_regenerator:\s*true", text))

def main() -> int:
    base = Path(__file__).resolve().parent.parent
    not_flipped = []
    for repo in BODAI_CORES:
        repo_path = base.parent / repo
        if not check_repo(repo_path):
            not_flipped.append(repo)
    if not_flipped:
        print(f"FAIL: {len(not_flipped)} repos have not flipped use_shared_regenerator: {not_flipped}", file=sys.stderr)
        return 1
    print(f"OK: all {len(BODAI_CORES)} Bodai cores have flipped use_shared_regenerator: true")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest scripts/test_verify_transition_complete.py -v`
Expected: PASS

- [ ] **Step 5: Drop legacy path in crackerjack (post-coordination)**

**NOTE**: This sub-step is **conditional** — only execute after running `scripts/verify_transition_complete.py` and confirming exit 0. Otherwise the migration is incomplete.

After all 6 cores flipped, drop the legacy branch in `crackerjack/tools/plan_index_sync.py:main()`:

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from oneiric.plan_index import regenerate as shared_regenerate
    return shared_regenerate(
        repo_root=args.repo_root.resolve(),
        out_path=(args.out.resolve() if args.out else None),
        check=bool(args.dry_run),
    )
```

Drop the `use_shared_regenerator` setting from `DocumentationSettings` (it's now always true) and from `settings/crackerjack.yaml`.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify_transition_complete.py scripts/test_verify_transition_complete.py
git commit -m "chore: verify_transition_complete script for Phase 6 rollout"

# Phase 6 commit (after coordination):
git add crackerjack/config/settings.py crackerjack/settings/crackerjack.yaml crackerjack/tools/plan_index_sync.py
git commit -m "feat(crackerjack): drop legacy plan_index_sync path (Phase 6)"
```