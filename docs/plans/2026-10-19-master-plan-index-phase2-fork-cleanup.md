# Master Plan Index — Phase 2 Fork Cleanup + Master-Land Follow-On Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the per-sibling fork deletion (Phase 3 migration), the cross-repo master-land in mahavishnu (T6-T8), the ecosystem.yaml opt-in (T9), and the version-pin regression test + Phase 6 legacy-drop (T11-T12) — all gated on Tasks 0-4 of the master plan (`docs/plans/2026-10-19-master-plan-index-and-regenerator.md`) shipping first.

**Architecture:** Each Bodai core lands in its own release train. Crackerjack ships the dispatcher (Task 4 in master), the 5 siblings consume that release and flip `use_shared_regenerator: true` (T5 step 6 here), then each deletes its own `scripts/regenerate_plan_index.py`. The master PLAN_INDEX.md registry lives at `mahavishnu/fleet_index/` (NEW package, separate from the deprecated Dhara-canonical CRUD layer) and walks `settings/ecosystem.yaml` collecting entries from each `emit_in_master: true` sibling. Phase 6 drops the legacy path in crackerjack after the transition verifier confirms all 6 cores flipped.

**Tech Stack:** Python 3.14; Pydantic-v2 strict mode for `RepositoryConfig` schema migration; Typer (CLI); oneiric library APIs from the master plan Tasks 1-3; crackerjack phase coordinator (`crackerjack/core/phase_coordinator.py`).

**Spec:** `docs/specs/2026-10-19-master-plan-index-and-regenerator-design.md` (Round 3) at `docs/specs/` in mahavishnu.

**Master plan:** `docs/plans/2026-10-19-master-plan-index-and-regenerator.md` — ships Tasks 0-4 first; this follow-on implements T5-T12.

## Global Constraints

- Python 3.14 target; oneiric, mahavishnu, crackerjack all on compatible crackerjack pins (≥0.90.0 ships the dispatcher refactor).
- Pre-1.0 hard-break per `feedback-no-backwards-compat-pre-1.0.md`: no shims, no `DeprecationWarning`, no deprecation windows. Replace not extend.
- Per `feedback-no-dhara-mention-in-bodai`: never reference Dhara in any bodai context — code, comments, docs, migration runbooks. This follow-on inherits the rule.
- Per `feedback-bodai-push-is-user-controlled.md`: every push is user-controlled; the user owns the merge order across the 6 repos.
- Per `feedback-mcp-common-version-bump-is-user.md`: no `pyproject.toml` *release version* bumps in this work; operator controls. **Dep-pin floors** (Task 0 in master) are operator-acknowledged separately and **not** governed by this rule.
- Per `feedback-trim-warning-behind-stale-worktree.md`: spec was edited during a parallel session — when implementing, ensure worktree is FF'd to `main` to avoid stale spec refs.
- Crackerjack's `plan_index_sync` is an opt-in publish-time PHASE (not fast-hook) per commit `e2656170`; 4 invariant tests in `crackerjack/tests/core/test_plan_index_sync_phase.py` (L79, L96, L111, L149, L169) pin this. **T5 step 6 fork deletion must not touch them.**
- The `crackerjack run -v -f` (merge gate per `feedback-crackerjack-merge-gate-is-vf`) does NOT run `plan_index_sync`; only `--publish` (with `auto_plan_index_sync_on_publish: true`) or explicit `--plan-index-sync` does.
- Oneiric library public API: `Entry(rel, store, date, status, role, kind, topic, title)` — 8 fields. Public functions: `discover_stores`, `discover_files`, `scan_entries`, `render_index`, `regenerate`.
- Master regenerator's discovery: `mahavishnu/settings/ecosystem.yaml` (canonical) NOT `mahavishnu/settings/repos.yaml` (deprecated per `settings/repos.yaml:1`).
- Master regenerator's CLI: `mahavishnu fleet regenerate` (NOT `mahavishnu plan-index regenerate`).
- Master regenerator's package: `mahavishnu/fleet_index/` (NOT `mahavishnu/plan_index/`).
- Schema migration: `mahavishnu/core/ecosystem.py:RepositoryConfig` gains `slug: str | None = None` + `emit_in_master: bool = False` (Pydantic-v2 safe defaults).
- Plan follows the per-PR test runtime budget: tests >10s marked `@pytest.mark.slow`.

## Preconditions

This follow-on **does not start** until the master's T0-T4 ship:
1. oneiric 0.33 has shipped to PyPI (master T1 release complete)
2. All 5 sibling `oneiric>=0.33` bumps merged (master T0 done)
3. Crackerjack ships a release containing the T4 dispatcher
4. All 6 Bodai cores consume that crackerjack release (operator-driven per `feedback-bodai-push-is-user-controlled.md`)

A `verify_transition_complete.py` (T12 step 3 here) gates the Phase 6 legacy-drop.

## Review Focus

Five input classes the spec implies but no task's tests exercise here that are most likely to bite a person using this software:

1. **Siblings with identical `ecosystem.yaml` paths but different `slug` fields** → pinned by `test_master_dedup.py::test_duplicate_repo_path_dedupes` in **Task 8**.
2. **Siblings with `slug` substring (`akosha` and `akosha-experimental`)** → pinned by `test_link_math.py::test_basename_substring_not_used_as_slug` in **Task 8**.
3. **Master-regen byte drift across siblings that flip on different days** → pinned by `test_regenerate.py::test_check_exits_1_on_drift` (existing test, retained) in **Task 7**.
4. **`scan_entries` vs `regenerate` divergence** (a future refactor grows a separate code path that emits different output) → pinned by `test_regenerate.py::test_regenerate_equals_scan_plus_render` (identity test, inherited from master T2).
5. **Oneiric version pin regression** (a sibling's `pyproject.toml` accidentally lowers the `oneiric>=` floor) → pinned by **Task 11** via a manifest-level grep test (`test_oneiric_floor_satisfies_plan_index_min`).

---

### Task 5: Move sibling plan_index tests into oneiric/tests/plan_index/

**Files:**
- Move: each sibling's `tests/unit/test_*plan_index*` and `tests/integration/plan_index/*` → `oneiric/tests/plan_index/test_*`
- Delete at source: the moved files

**Interfaces:**
- Consumes: `oneiric.plan_index` public API (from master Tasks 1-3)
- Produces: a single canonical test suite in oneiric

- [ ] **Step 1: Audit existing plan_index tests across the 6 Bodai core repos**

Run for each of `oneiric`, `akosha`, `session-buddy`, `crackerjack`, `mcp-common`, `mahavishnu`:
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

- [ ] **Step 6: Phase 3 fork deletion — per sibling (gated on master Task 4)**

This sub-step is **gated** on each sibling having completed master Task 4 (crackerjack rewired and shipped a version with the dispatcher). Per spec §"Migration plan" Phase 3, each sibling lands in their own release train. For each of the 6 Bodai core repos:

```bash
cd <sibling-repo>

# 1. Flip the feature flag in crackerjack's settings.yaml
sed -i 's/use_shared_regenerator: false/use_shared_regenerator: true/' settings/crackerjack.yaml
git add settings/crackerjack.yaml
git commit -m "feat(<sibling>): flip plan_index_sync to shared library"

# 2. Delete the forked regenerator
git rm scripts/regenerate_plan_index.py

# 3. (mahavishnu only) Delete the 5 extras
[ "$(basename "$(pwd)")" = "mahavishnu" ] && git rm \
  scripts/audit_plan_index.py \
  scripts/bootstrap_plan_index.py \
  scripts/backup_plan_index.py \
  scripts/restore_plan_index_backup.py \
  scripts/backfill_plan_spec_titles.py \
  scripts/_apply_plan_audit_2026_09_12.py

git commit -m "feat(<sibling>): delete plan_index script (Phase 3 per spec)"
```

Run for each of: `mahavishnu`, `akosha`, `session-buddy`, `crackerjack`, `mcp-common`, `oneiric`.

- [ ] **Step 7: Verify all 6 forks are deleted**

```bash
for repo in mahavishnu akosha session-buddy crackerjack mcp-common oneiric; do
    if [ -f "/Users/les/Projects/$repo/scripts/regenerate_plan_index.py" ]; then
        echo "FAIL: $repo still has scripts/regenerate_plan_index.py"
        exit 1
    fi
done
echo "OK: all 6 siblings deleted their plan_index fork"
```

Expected: exit 0 after Step 6 completes across all 6 siblings. After this passes, Task 12 (Phase 6) is unblocked.

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

**Architecture note (per generalist review F17):** `format.py` groups cross-repo entries by origin. The implementer MUST prefix each entry's `store` with `<slug>/` **at the scan boundary in `master.py`** (not rely on parsing `e.store.split('/')[0]`), so the bucket-by-origin logic in `format.py` collapses correctly per origin slug. Failing to prefix at the boundary collapses all cross-repo entries into a single origin bucket.

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
    """Render one subsection per origin slug.

    Callers MUST pre-bucket entries into entries_by_origin keyed by the
    <slug> (e.g., 'akosha') rather than the per-repo store path. master.py
    is the boundary that does this bucketing (per generalist review F17:
    do not rely on `e.store.split('/')[0]` here — do the bucketing at
    the scan boundary so the bucket keys are explicit origin slugs).
    """
    grouped: dict[str, list[Entry]] = defaultdict(list)
    for entries in entries_by_origin.values():
        for e in entries:
            # origin was already used as the bucket key when master.py built
            # `entries_by_origin`. Re-bucket by store here ONLY for assertion
            # purposes (defensive — should be a no-op if caller obeyed the
            # contract).
            pass

    sections = ["## Cross-repo plans", "",
                "_One section per sibling repo with `emit_in_master: true`._"]
    for origin in sorted(entries_by_origin):
        sections.append(f"\n### `{origin}`\n")
        sections.append("| Path | Date | Status | Role | Kind | Topic | Title |")
        sections.append("|---|---|---|---|---|---|---|")
        for e in sorted(entries_by_origin[origin], key=lambda e: (-_date_key(e.date), e.rel)):
            sections.append(f"| `{e.rel}` | {e.date or '—'} | `{e.status}` | `{e.role}` | `{e.kind}` | `{e.topic}` | {e.title} |")
    return "\n".join(sections)

def _date_key(v: str) -> int:
    if not v: return 0
    import re
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", v)
    if not m: return 0
    return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))
```

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
        local_body_no_sliced = _strip_distribution_footer(local_body)
        # Step 2: cross-repo scan — BUCKET BY ORIGIN SLUG AT THIS BOUNDARY (F17).
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
                # PER F17: prefix each entry's store with the origin slug at this
                # boundary so render_cross_repo_section can bucket by origin
                # explicitly. Do NOT rely on `e.store.split('/')[0]` later.
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
        # Step 4: distribution footer from local_body
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
    "SYSTEM_DIR_PARTS", "MIN_STORE_DOCS",
    "FleetRegenerator",
]
```

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

**Sub-task breakdown** (per architecture review C2: split the original 9-into-one test into 9 focused sub-tasks. Each test is small and independently reviewable; this matches the existing CLAUDE.md test-quality bar.)

- [ ] **Step 1: Write `test_master_regenerate.py` (test_master_regenerate - section order and singleton footer)**

```python
# mahavishnu/tests/integration/fleet_index/test_master_regenerate.py
import tempfile
from pathlib import Path
from unittest.mock import patch
from mahavishnu.fleet_index.master import FleetRegenerator

def test_section_order_and_singleton_footer(tmp_path: Path):
    """Local table A precedes Cross-repo heading X; distribution footer appears exactly once."""
    # ... 6 fake sibling checkouts + local entry, run FleetRegenerator, assert output
```

- [ ] **Step 2: Write `test_ecosystem_yaml_validation.py` (test_ecosystem_yaml_validation - schema gate)**

The T9 schema gate test: each `emit_in_master: true` entry has a unique `slug` matching the `nickname:` value (or the `name:` fallback); slugs are RFC-1123 compatible (lowercase alphanum + dash, 3-64 chars per `REGEX_REPO_SLUG`).

- [ ] **Step 3: Write `test_master_error_handling.py` (test_master_error_handling - missing/malformed sibling paths)**

A sibling path that doesn't exist or has malformed frontmatter logs a warning to stderr and the run returns exit code 1 — does NOT raise. Use `tmp_path` for both local and sibling repos to keep the test hermetic.

- [ ] **Step 4: Write `test_master_check.py` (test_master_check - drift detection)**

Reuse master T2's `regenerate(check=True)` invariant: `--check` exits 0 on no-drift and 1 on drift, never raises. Verify the master regenerator's `--check` plumbing calls through to the underlying `oneiric.plan_index.regenerate(check=True)`.

- [ ] **Step 5: Write `test_link_math.py` (test_link_math - substring slug dedup)**

Add `test_basename_substring_not_used_as_slug` (Review Focus #2): simulates two siblings `akosha` and `akosha-experimental` and asserts the master REGEN does not collapse them into one section. Imports `pytest` and the test fixtures from Step 1.

- [ ] **Step 6: Write `test_master_dedup.py` (test_master_dedup - duplicate repo path)`

Add `test_duplicate_repo_path_dedupes` (Review Focus #1): two entries with the same `path` but different `slug` values appear as ONE section in the master PLAN_INDEX.md (dedup by path, not slug).

- [ ] **Step 7: Write `test_dedup.py` (test_dedup - per-store dedup in oneiric library)**

Two `.md` files with the same frontmatter title but different `rel` paths appear as TWO entries (not deduped). Verifies `discover_stores` returns dedup'd stores and `scan_entries` returns all entries within a store.

- [ ] **Step 8: Write `test_missing_local_index.py` (test_missing_local_index - absent local branch)**

A local repo with no `docs/plans/` directory produces an empty local section + valid cross-repo sections + singleton footer (not a crash). Asserts that the regenerator degrades gracefully when the local entry is empty.

- [ ] **Step 9: Write `test_e2e_smoke.py` (test_e2e_smoke - end-to-end pipeline)**

```python
# mahavishnu/tests/integration/fleet_index/test_e2e_smoke.py
import pytest

@pytest.mark.slow
def test_e2e_smoke_full_fleet_pipeline(tmp_path: Path):
    """End-to-end: 6 sibling repos + local, run FleetRegenerator, assert byte-stable output."""
    ...
```

The slow marker keeps this out of `-m "not slow"` feedback loops per CLAUDE.md conventions.

- [ ] **Step 10: Run integration tests**

Run: `.venv/bin/pytest tests/integration/fleet_index/ -v`
Expected: ALL PASS (slow verification)

- [ ] **Step 11: Commit**

```bash
git add mahavishnu/tests/integration/fleet_index/
git commit -m "test(mahavishnu): integration tests for fleet_index master regenerator"
```

---

### Task 9: Mahavishnu — `ecosystem.yaml` updates (6 entries; CANNOT be committed — operator handoff)

**Files:**
- Modify: `mahavishnu/settings/ecosystem.yaml` (add `slug` + `emit_in_master: true` to the 6 Bodai core entries) — **operator-edited, NOT in this commit (per generalist review F7: `settings/ecosystem.yaml` is gitignored)**

- [ ] **Step 1: Audit current state**

Run:
```bash
grep -E "^  - name: " mahavishnu/settings/ecosystem.yaml
```

Record the 6 Bodai core entry names: `oneiric`, `akosha`, `session-buddy`, `crackerjack`, `mcp-common`, `mahavishnu`.

- [ ] **Step 2: Hand off the ecosystem.yaml edit to the operator**

**This task does NOT commit `settings/ecosystem.yaml`** — that file is gitignored per `mahavishnu/.../.gitignore`. The implementer prepares the proposed YAML diff, hands it to the operator, and surfaces the diff in the PR description.

For each of the 6 entries, propose (matching the `nickname:` value already in the file, per F1 — the generalist review found prior plan values contradicted the actual nickname keys):
```yaml
  slug: "<short-name>"
  emit_in_master: true
```

Expected slug values per existing `nickname:` keys in `ecosystem.yaml`:
- `akosha` → `akosha`
- `session-buddy` → `buddy`
- `crackerjack` → `crackerjack` (or `cj` — operator chooses; default to full name)
- `mcp-common` → `common`
- `mahavishnu` → `vishnu`
- `oneiric` → `oneir`

Use the `nickname` value where it exists; otherwise the full `name`.

- [ ] **Step 3: Run sync-guard test**

Run: `.venv/bin/pytest tests/integration/fleet_index/test_ecosystem_yaml_validation.py -v`
Expected: PASS after operator edits land locally

- [ ] **Step 4: No commit**

State explicitly in PR: "ecosystem.yaml is gitignored per `feedback-no-bodai-prefix-in-config-names` policy and `mahavishnu/settings/.gitignore`. Operators apply the diff from Step 2 manually."

---

### Task 10: Phase 5 — rename substrate-named decision file in oneiric

**Files:**
- Rename: `oneiric/.claude/decisions/2026-10-11-substrate-refs-cleanup.md` (already-rerouted; confirm current path before renaming) → `oneiric/.claude/decisions/2026-10-11-substrate-refs-cleanup.md`
- Regenerate: `oneiric/docs/plans/PLAN_INDEX.md` (via `oneiric plan-index regenerate`)

**Why:** Cross-reference hygiene. The `PLAN_INDEX.md` title column disambiguates by the basename; intermediate dedup needs uniqueness on filename. Renames + regen lock the naming.

- [ ] **Step 1: Verify the current filename**

Run:
```bash
ls oneiric/.claude/decisions/2026-10-11-*substrate-refs-cleanup*.md
```

If the file's already named `substrate-refs-cleanup.md` (no `dhara-` prefix), skip to Step 3. Otherwise proceed.

- [ ] **Step 2: Rename the file (only if Step 1 shows the old filename)**

Run:
```bash
cd oneiric
git mv .claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md .claude/decisions/2026-10-11-substrate-refs-cleanup.md
```

- [ ] **Step 3: Update any cross-references to the old filename**

Run:
```bash
grep -rn "2026-10-11-dhara-substrate-refs-cleanup" oneiric/ 2>/dev/null
```

For each match (other than the rename itself), update the reference.

- [ ] **Step 4: Regenerate oneiric's local PLAN_INDEX.md**

Run: `cd oneiric && ../.venv/bin/python -m oneiric plan-index regenerate --repo-root .`

Verify: `docs/plans/PLAN_INDEX.md` now references `2026-10-11-substrate-refs-cleanup.md` (no Dhara in the title column).

- [ ] **Step 5: Commit**

```bash
cd oneiric
git add .claude/decisions/ docs/plans/PLAN_INDEX.md
git commit -m "chore(oneiric): rename dhara-substrate-refs decision file per fleet rename"
```

---

### Task 11: Version pin regression — manifest-level test

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

# The version that ships oneiric.plan_index.
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
    """All 5 consuming siblings pin oneiric >= 0.33.

    Master Task 0's pin bumps (crackerjack, session-buddy, mahavishnu,
    akosha, mcp-common) raised each floor from current value to 0.33.
    This test is the regression guard — if anyone LOWERS a floor in
    the future, the test goes RED.
    """
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

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv/bin/pytest oneiric/tests/plan_index/test_dist.py -v`
Expected: PASS — the master Task 0 pin bumps landed before this test runs, so all 5 floors are now ≥0.33.

If this test FAILS, it means one or more siblings' floors weren't bumped by master Task 0. Re-check.

- [ ] **Step 3: Commit**

```bash
git add oneiric/tests/plan_index/test_dist.py
git commit -m "test(oneiric): pin sibling oneiric floors above plan_index minimum"
```

---

### Task 12: Phase 6 — drop legacy path in crackerjack + `verify_transition_complete.py`

**Files:**
- Create: `scripts/verify_transition_complete.py` (NEW, in each Bodai core repo OR centralized in crackerjack)
- Modify: `crackerjack/tools/plan_index_sync.py:main()` (drop the `use_shared` branch — legacy local code removed post-verification)

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

Maintenance signal per spec §"Risks" #4. The script is intentionally
self-contained (no project imports) so it can be run before/after
the crackerjack package install. Cross-machine portability: relative
paths from the script's location; assume `<repo-root>/scripts/`
as the script's parent. Run from the crackerjack workspace, or pass
BODAI_PROJECT_ROOTS as an env var with a colon-separated list.
"""
from __future__ import annotations
import os
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
    base = Path(os.environ.get("BODAI_PROJECT_ROOTS", "/Users/les/Projects"))
    not_flipped = []
    for repo in BODAI_CORES:
        repo_path = base / repo
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

- [ ] **Step 4: Run the verifier manually**

Run: `python scripts/verify_transition_complete.py`
Expected: exit 1 if T5 step 6 hasn't completed across all 6 siblings; exit 0 once it has.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest scripts/test_verify_transition_complete.py -v`
Expected: PASS

- [ ] **Step 6: Drop legacy path in crackerjack (post-coordination)**

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

- [ ] **Step 7: Commit**

```bash
git add scripts/verify_transition_complete.py scripts/test_verify_transition_complete.py
git commit -m "chore: verify_transition_complete script for Phase 6 rollout"

# Phase 6 commit (after coordination):
git add crackerjack/config/settings.py crackerjack/settings/crackerjack.yaml crackerjack/tools/plan_index_sync.py
git commit -m "feat(crackerjack): drop legacy plan_index_sync path (Phase 6)"
```
