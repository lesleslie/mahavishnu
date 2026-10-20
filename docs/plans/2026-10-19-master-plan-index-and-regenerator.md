# Master Plan Index + Centralized Regenerator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-sibling forked `regenerate_plan_index.py` scripts (one per Bodai core) with a oneiric-hosted shared library; make mahavishnu's `docs/plans/PLAN_INDEX.md` the master fleet index aggregated from sibling repos via pull-on-regeneration; wire crackerjack's `plan_index_sync` phase through the shared library behind a transition feature flag.

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
4. **`scan_entries` vs `regenerate` divergence** (a future refactor grows a separate code path that emits different output) → pinned by `test_regenerate.py::test_regenerate_equals_scan_plus_render` (identity test) in **Task 2**.
5. **Oneiric version pin regression** (a sibling's `pyproject.toml` accidentally lowers the `oneiric>=` floor) → pinned by **Task 11** (deferred to follow-on plan) via a manifest-level grep test (`test_oneiric_floor_satisfies_plan_index_version`).

---

### Task 0: Bump sibling `oneiric>=` pin floors to ≥0.33 (prerequisite for T4)

**Files:**
- Modify: 5 sibling `pyproject.toml` files (one edit each — dep floor only, not release version)

**Interfaces:**
- Consumes: existing pyproject.toml `dependencies` block
- Produces: 5 siblings pin `oneiric>=0.33`

**Why first:** T4 step 5 imports `from oneiric.plan_index import regenerate`, which requires `oneiric>=0.33` on the install path. None of the 5 consuming siblings currently meet that floor — actual on-disk `oneiric>=` values are `crackerjack=0.32`, `session-buddy=0.32`, `mahavishnu=0.28.0`, `akosha=0.20`, `mcp-common=0.26.4` (crackerjack-specialist review, finding C2). Without these floors bumped, T4's import raises `ImportError` on first run. Memory `feedback-mcp-common-version-bump-is-user.md` governs Bodai *release* versions, not *dep pin floors* — dep pins are operator-acknowledged here.

- [ ] **Step 1: Bump `oneiric>=` in each sibling's `pyproject.toml`**

For each of the following files, raise the `oneiric>=X.Y` floor to `>=0.33`:
- `crackerjack/pyproject.toml` (current: `0.32`)
- `session-buddy/pyproject.toml` (current: `0.32`)
- `mahavishnu/pyproject.toml` (current: `0.28.0`)
- `akosha/pyproject.toml` (current: `0.20`)
- `mcp-common/pyproject.toml` (current: `0.26.4`)

Read the current value, then edit `oneiric>=X.Y` → `oneiric>=0.33`. **Do not bump the sibling's own release version** — only the dep floor.

- [ ] **Step 2: Per-sibling commit (one commit per repo)**

For each sibling:
```bash
cd <sibling-repo>
git add pyproject.toml
git commit -m "chore(deps): bump oneiric>= to 0.33 (plan_index library floor)"
```

Order between siblings does not matter, but Task 1 (oneiric library) **must release 0.33** before Task 4 (crackerjack dispatcher) ships. Confirm with the user that oneiric 0.33 has shipped before merging any sibling flip; until it has, the bumped floor simply waits in the local checkout (uv will resolve against the future 0.33 once it hits PyPI).

- [ ] **Step 3: Verify Task 11 (deferred) test will pass on first run after the bumps**

Task 11's `test_siblings_pin_oneiric_above_plan_index_min` (deferred to follow-on plan) will assert all 5 siblings pin `oneiric>=0.33`. After Step 2 lands, that test should go GREEN on first execution. If it stays RED, one of the floors wasn't bumped or the regex doesn't match — re-check.

- [ ] **Step 4: Commit gate**

Do NOT proceed to Task 1 until all 5 sibling commits land. If the operator cannot release oneiric 0.33 immediately, hold the bumps in feature branches across the 5 siblings and merge them in lockstep when oneiric 0.33 ships.

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
from oneiric.plan_index import scan_entries  # exported via oneiric/plan_index/__init__.py (Task 2 step 15)

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
    from oneiric.plan_index import scan_entries
    from oneiric.plan_index.render import render_index
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "x.md").write_text("---\nstatus: active\nrole: implementation\nkind: plan\ntopic: t\n---\n# X\n")
    entries = scan_entries(tmp_path)
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
- Modify: `crackerjack/settings/crackerjack.yaml:89-95` (`documentation:` block — add `use_shared_regenerator: false` entry; the YAML key is added explicitly even though `DocumentationSettings` would coerce from the Pydantic default, to keep the operator-visible intent explicit)
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
    """crackerjack's --dry-run flag must translate to oneiric.plan_index.regenerate(check=True).

    Invokes the dispatcher module DIRECTLY (NOT `crackerjack run`). The
    `crackerjack run` CLI does not bind `--repo-root` (`grep` of
    `crackerjack/cli/options.py` and `crackerjack/__main__.py:806`
    confirms); `PhaseCoordinator` constructs `--repo-root` itself from
    `process.cwd` (`crackerjack/core/phase_coordinator.py:858`). Calling
    `crackerjack run --plan-index-sync --dry-run --repo-root <tmp>` would
    silently ignore the `--repo-root` flag and run against the worktree's
    cwd, NOT against `tmp_path`. Mirror the existing pattern at
    `crackerjack/tests/unit/test_plan_index_sync.py:18` (the `_tool_help()`
    probe) — direct module invocation only.
    """
    monkeypatch.setenv("CRACKERJACK_DOCS__USE_SHARED_REGENERATOR", "true")
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    # Run the dispatcher module directly with --dry-run
    result = subprocess.run(
        [sys.executable, "-m", "crackerjack.tools.plan_index_sync",
         "--repo-root", str(tmp_path), "--dry-run"],
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
    # Pydantic-v2 types `use_shared_regenerator` as bool; no bool() cast needed.
    use_shared = getattr(settings.documentation, "use_shared_regenerator", False)
    if use_shared:
        from oneiric.plan_index import regenerate as shared_regenerate
        # --dry-run ≡ check=True (per spec acceptance criterion I-1)
        return shared_regenerate(
            repo_root=args.repo_root.resolve(),
            out_path=(args.out.resolve() if args.out else None),
            check=bool(args.dry_run),
        )
    # LEGACY BRANCH: inline the pre-dispatch body of main() (originally
    # at crackerjack/tools/plan_index_sync.py:407-454 before this rewrite).
    #
    # Per crackerjack-specialist review C3: do NOT extract to
    # `_legacy_render(args)`. Inlining is preferable — fewer new symbols,
    # tighter review diff, and the legacy branch is small once the
    # shared import is removed. The implementer reads the current
    # crackerjack/tools/plan_index_sync.py, copies the original render
    # logic verbatim into this else-branch (the
    # argparse-parse → render_plan_index → dry-run-vs-write → return int
    # sequence), and DOES NOT touch the existing CLI surface
    # (`--repo-root`, `--out`, `--dry-run` flags stay identical so the
    # existing `test_help_smoke` continues to pass).
    #
    # ALSO per crackerjack-specialist review I1: the legacy
    # `_render_index()` and argparse `description` strings embed the
    # string `(fast-hook)` at plan_index_sync.py:368 and `:412` —
    # update those to `(phase)` while inlining, so the legacy output
    # post-T4 doesn't lie about being a fast-hook that no longer exists.
    ...legacy body inlined here, with the (fast-hook) → (phase) tagline update...
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

### Tasks 5-12: Deferred to follow-on plan

Tasks 5-12 (sibling fork cleanup, master-land, version-pin regression, ecosystem.yaml opt-in, dhara-named-decision-file rename, transition verification) are deferred to their own release-train follow-on plan:

**`docs/plans/2026-10-19-master-plan-index-phase2-fork-cleanup.md`**

That plan lands T5-T12 in their own release. Reasoning and task-level steps live there; the in-flight master (Tasks 0-4) ships independently with `crackerjack run -v -f` as the merge gate per `feedback-crackerjack-merge-gate-is-vf.md` and the per-PR squash-merge from the trunk-based agent-review workflow.

**Cross-references in this master that now live in the follow-on:**
- Review Focus entries 5 (version-pin regression test) → T11 in the follow-on
- Architecture CRITICAL C1 (hidden crackerjack version-bump prerequisite per sibling) → addressed by Task 0 (this master)
- Architecture CRITICAL C3 (T7 master.py/format.py live planning commentary) → T7 in the follow-on (cleaned up before promotion)
- Generalist CRITICAL F1 (T9 slug values vs `ecosystem.yaml` nicknames) → T9 in the follow-on (uses `akosha/buddy/common/oneir/crackerjack/vishnu` matching the actual nickname keys)
- Generalist CRITICAL F7 (`settings/ecosystem.yaml` is gitignored) → T9 in the follow-on tasks the operator with the explicit handoff to land the bump out-of-band
- Generalist CRITICAL F14 (typos `SYSTEM_DIR_DOCS` and `mahavishmu`) → applied here in this master file; the follow-on re-applies on copy
- Generalist CRITICAL F17 (T7 `format.py` uses `e.store.split('/')[0]` against non-prefixed entries) → T7 in the follow-on now prefixes entries with `<slug>/` before reaching `format.py`

**Per-PR preconditions for follow-on landing:**
1. oneiric 0.33 has shipped to PyPI (Task 1 in this master released)
2. All 5 sibling `oneiric>=` pin bumps merged (Task 0 in this master landed)
3. Crackerjack ships a release containing T4 (the dispatcher)
4. All 6 siblings consume that crackerjack release (operator-driven, per `feedback-bodai-push-is-user-controlled.md`)
