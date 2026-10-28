---
status: complete
role: implementation
date: 2026-10-28
last_reviewed: 2026-10-28
superseded_by: null
topic: registry-paths
title: "Registry path disclosure — root-relative paths in BODAI_REPO_REGISTRY.md"
---

# Registry path disclosure — root-relative paths in `BODAI_REPO_REGISTRY.md`

## 1. Outcome

`BODAI_REPO_REGISTRY.md` contains **no absolute path and no account name**.
Its `Path` column is relative to a declared *projects root*, and the document
states the resolution rule that turns a row back into a location on disk.

Success signal: `grep -c "/Users/" BODAI_REPO_REGISTRY.md` returns `0`, and
`python3 scripts/regen_bodai_registry.py --check` still passes.

**Status: shipped.** All five requirements are implemented; see §10 for the
evidence.

## 2. Goals

1. The published registry discloses neither the operator's account name nor
   their filesystem layout.
2. The registry stays **machine-usable**: every consumer can still resolve a
   row to a real directory on disk without configuration.
3. The change is confined to the registry, its generator, and its three
   consumers — no unrelated repo-wide sweep.

## 3. Non-Goals

1. **Not** sweeping the remaining ~211 tracked files in this repo that
   contain an operator's home path (106 docs, 38 tests, 31 scripts, …).
   Separate pass.
   Two of those scripts are worth calling out for the follow-up:
   `scripts/audit_cli_inventory.py` hardcodes an absolute home path as
   its repo-root default, and `docs/mcp/SERVER_MIGRATION_TRACKER.md` still holds
   37 absolute paths from an older audit run.
2. **Not** promoting path redaction into a shared `oneiric` action kit.
   Crackerjack does not depend on `oneiric`; adding that dependency is a
   larger decision than this change.
3. **Not** changing the registry's *section layout* or column set — except
   the "Core 7" heading, which ADR 019 made factually wrong (see §4).
4. **Not** changing the port table or the MCP scoping section.

## 4. Current Findings

**The registry is published.** `github.com/lesleslie/mahavishnu` is a
**public** repository. `BODAI_REPO_REGISTRY.md` is tracked and world-readable,
so an absolute path discloses the operator's account name and local
directory layout to anyone who clones or visits the repo.

**Three disclosure sites, one of them a literal regex:**

| Site | File | Kind |
|---|---|---|
| 37 table rows | `BODAI_REPO_REGISTRY.md` | generated |
| `ls <home>/Projects/` | `scripts/regen_bodai_registry.py:300` | literal in the generator |
| a regex anchored on one machine's absolute path | `scripts/audit_mcp_launchers.py:199` | hardcoded |

**The path column is functional data, not documentation.** Three consumers
parse it to locate repos on disk:

| Consumer | Repo | What it needs the path for |
|---|---|---|
| `crackerjack/checks/bodai_registry.py` | crackerjack | `load_fleet_repo_paths()` → `Path.is_dir()` for gitignore conformance |
| `crackerjack/tests/unit/test_bodai_build_system_guard.py` | crackerjack | reads `<repo>/pyproject.toml` |
| `scripts/audit_mcp_launchers.py` | mahavishnu | probes each repo's MCP entry points |

This is why the fix cannot be a crackerjack-side redaction: the value has to
stay machine-usable while becoming machine-*independent*.

**Every repo shares one parent.** All 37 active repos in
`settings/ecosystem.yaml` sit under one shared parent, so "relative to
a root" is exact here, not an approximation.

**The registry was already drifted.** `regen_bodai_registry.py --check` failed
before this change: the gitignored local overlay had gained 2 archived repos
and 1 excluded repo since the last generation (2026-10-14). Regenerating
without fixing the archived/excluded sections would have *added* three more
absolute paths (including `ARCHIVED/…` entries).

**The exclusions were never applied — and the guard test knew it.**
`TestBodaiBuildSystemGuard::test_registry_matches_known_active_repos` pins
the registry at **34** active repos and explains the number: "Updated from
36 → 34 after moving jinja2-custom-delimiters to Excluded from scope". But
`settings/registry_metadata.yaml` has carried an **empty** `excluded_repos`
map in every commit that introduced it, and the generator rendered the
Excluded section without removing those repos from the active tables. So the
registry listed 36 rows while the guard insisted on 34 — two guards failing
for a reason nobody could reproduce.

**`dhara` was in the registry's core bucket but not in its core table.**
`CORE_ORDER` still listed `"mcp"` — the pre-decomposition name — after
`mcp` was split into `dhara` (2026-09-14). `dhara` therefore fell through
both render paths: counted in the summary ("Core 7: 7", "Total 37"), absent
from the tables. ADR 019 then settled the membership question outright:

> as of 2026-10-17, the user explicitly clarified that Dhara is still
> maintained by Bodai but is no longer a core component. The in-scope set for
> any fleet release probe becomes `{mahavishnu, akosha, session-buddy,
> crackerjack, oneiric, mcp-common}` — six repos, not seven.

The registry had already dropped `dhara`'s row by hand on 2026-10-09
(commit `84a66f8b`), so the generator was the only thing still disagreeing.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-001
    title: "Generator renders registry paths relative to the projects root"
  - id: REQ-002
    title: "Published registry declares the projects-root resolution rule"
  - id: REQ-003
    title: "Registry consumers resolve relative paths against the projects root"
  - id: REQ-004
    title: "Published registry contains no absolute path or account name"
  - id: REQ-005
    title: "Registry catalog lists only fleet-member Python packages"
```

## 5. Implementation Phases

### Phase 1: Generator renders root-relative paths

**Goal:** the generator emits root-relative paths and declares how to
resolve them. *(REQ-001, REQ-002, REQ-004)*

**Tasks:**

- `scripts/regen_bodai_registry.py`:
  - `infer_projects_root(paths)` — the parent directory shared by the most
    repos. "Most common parent", not "common ancestor": one stray repo kept
    elsewhere must not drag the root up to the home directory, which would
    re-leak the account name through the rendered relative paths.
  - `render_repo_path(repo_path, root)` — root-relative when the repo is
    under the root; otherwise the directory name alone (leak-free fallback).
  - `render_repo_row()` and `render_archived_section()` /
    `render_excluded_section()` render through it.
  - `build_header()` — add the `## Path resolution` section; replace the
    literal `ls <home>/Projects/` with `ls ~/Projects/`.
- Regenerate `BODAI_REPO_REGISTRY.md`.

**Exit criteria:** no `/Users/` in the artifact; `--check` passes.

#### Integration Contract

- **Triggered from**: `python3 scripts/regen_bodai_registry.py` (operator
  run) or `python3 scripts/regen_bodai_registry.py --check` (drift gate).
- **Returns to / updates**: `BODAI_REPO_REGISTRY.md` at the repo root.
- **Demonstrable by**: `grep -c "/Users/" BODAI_REPO_REGISTRY.md` → `0`;
  `python3 scripts/regen_bodai_registry.py --check` → `OK`.
- **Rollback signal**: `--check` reports `DRIFT` after a regeneration that
  did not go through this generator.
- **Observability added**: the generator's `Path resolution` section is the
  contract consumers parse; no new runtime signal (build-time artifact).

### Phase 2: Consumers resolve relative paths

**Goal:** all three consumers locate repos through the shared resolution
chain. *(REQ-003)*

**Tasks:**

- `crackerjack/checks/bodai_registry.py`:
  - `PROJECTS_ROOT_ENV_VAR = "BODAI_PROJECTS_ROOT"`.
  - `resolve_projects_root(registry_path)` — `$BODAI_PROJECTS_ROOT`, then the
    registry's own location (`<root>/mahavishnu/BODAI_REPO_REGISTRY.md`), then
    `~/Projects`.
  - `_TABLE_ROW_RE` accepts a root-relative path; `parse_registry_repo_paths()`
    and `load_fleet_repo_paths()` join against the resolved root.
  - Every row is resolved against the trusted root and **rejected unless it
    stays inside it**. The registry is an input — `$CRACKERJACK_BODAI_REGISTRY`
    can point at any file — so a row must not steer the fleet tools at an
    arbitrary directory. The check runs on the *resolved* path, so `..`
    segments and symlinks whose target escapes the root are both rejected.
    An absolute path is honoured only when it lands inside the root, which
    keeps a registry generated before the relative-path format working.
  - One row iterator (`_iter_table_paths`) now backs both parsers; the two
    hand-rolled parsers had drifted.
- `scripts/audit_mcp_launchers.py`: same resolution chain, with the same
  containment check; the registry's path is joined with the root before
  being compared against `settings/ecosystem.yaml`'s absolute path; the
  emitted `path` column is rendered relative so the audit's output cannot
  re-leak the account name.
- `crackerjack/tests/unit/test_bodai_build_system_guard.py`: extract repos
  through the root-aware parser.

**Exit criteria:** the build-system guard passes; `audit_mcp_launchers.py`
still resolves every repo and emits no absolute path.

#### Integration Contract

- **Triggered from**: `crackerjack run -v -f` (build-system guard) and
  `.venv/bin/python scripts/audit_mcp_launchers.py` (launcher audit).
- **Returns to / updates**: `crackerjack/checks/gitignore_conformance.py`'s
  fleet-member set (via `load_fleet_repo_paths()`), and
  `docs/mcp/SERVER_MIGRATION_TRACKER.md`'s source data (via the audit
  script).
- **Demonstrable by**:
  `.venv/bin/python -m pytest tests/unit/test_bodai_build_system_guard.py -q`
  → `4 passed`; `.venv/bin/python scripts/audit_mcp_launchers.py | grep -c
  "/Users/"` → `0`.
- **Rollback signal**: `load_fleet_repo_paths()` returns an empty set (the
  gitignore gate would silently become a no-op) — logged as
  "Bodai registry not found".
- **Observability added**: the existing `Bodai registry not found` warning
  now also covers an unresolvable projects root.

### Phase 3: Catalog accuracy

**Goal:** the registry lists exactly the fleet's Python-package repos, and
the generator enforces that rather than leaving it to a per-machine overlay.
*(REQ-005)*

**Tasks:**

- `scripts/regen_bodai_registry.py`:
  - `filter_active()` drops repos named in the overlay's `excluded_repos`,
    so a repo cannot appear both as an active fleet member and as excluded.
  - `bucket_repos()` is shared by the renderer and the summary, so the
    "Total active Bodai repos" count can no longer disagree with the tables.
  - `CORE_ORDER` drops the stale `"mcp"` entry (dhara's pre-decomposition
    name) and the section heading becomes "Core 6", matching ADR 019's
    six-repo fleet release set.
- `settings/registry_metadata.yaml` — populate `excluded_repos` with the
  three exclusions and their reasons. The *reasons* are shared (a property
  of the repo); the *archive locations* stay in the gitignored local overlay.
- `settings/ecosystem.yaml` (gitignored) — mark the three repos non-active
  so the local catalog agrees with the published registry.
- `docs/ECOSYSTEM.md` — no change needed: it already said "34 active",
  which is what the corrected registry reports.

**Exit criteria:** the build-system guard passes with no failures; the
registry reports 34 active repos and its summary matches its tables.

#### Integration Contract

- **Triggered from**: `python3 scripts/regen_bodai_registry.py` regenerating
  from the edited sources.
- **Returns to / updates**: `BODAI_REPO_REGISTRY.md` (Excluded section,
  summary counts) and `settings/registry_metadata.yaml`.
- **Demonstrable by**:
  `.venv/bin/python -m pytest tests/unit/test_bodai_build_system_guard.py -q`
  → `4 passed`; `grep "Total active Bodai repos" BODAI_REPO_REGISTRY.md` →
  `**Total active Bodai repos: 34**`.
- **Rollback signal**: the guard test's pinned repo count no longer matches
  the parsed registry — the test fails loudly rather than silently.
- **Observability added**: none (catalog correction, not a runtime path).

## 6. Required Code Changes

**mahavishnu**

- [x] `scripts/regen_bodai_registry.py` — root inference, relative
      rendering, header contract, exclusion enforcement, shared bucketing
- [x] `BODAI_REPO_REGISTRY.md` — regenerated
- [x] `scripts/audit_mcp_launchers.py` — root-aware registry parsing,
      root-relative output
- [x] `settings/registry_metadata.yaml` — populate `excluded_repos`
- [x] `settings/ecosystem.yaml` — mark the three excluded repos non-active
      (gitignored; affects only the local catalog)
- [x] `tests/unit/test_bodai_registry_paths.py` — generator + artifact guards
- [x] `docs/plans/2026-10-28-registry-root-relative-paths.md` — this plan

**crackerjack**

- [x] `crackerjack/checks/bodai_registry.py` — `resolve_projects_root()`,
      root-aware table parsing, one shared row iterator
- [x] `crackerjack/tests/unit/test_bodai_build_system_guard.py` — root-aware
      extraction
- [x] `tests/unit/test_bodai_registry.py` — root-resolution tests

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `grep -c "/Users/" BODAI_REPO_REGISTRY.md` | `0` | terminal |
| `python3 scripts/regen_bodai_registry.py --check` | `OK` | terminal |
| `python3 -m pytest tests/unit/test_bodai_registry_paths.py -q` | `9 passed` | terminal |
| `python3 -m pytest tests/unit/test_bodai_build_system_guard.py -q` (crackerjack) | `4 passed` | terminal |
| `python3 -m pytest tests/unit/test_bodai_registry.py -q` (crackerjack) | `14 passed` | terminal |
| `python3 scripts/audit_mcp_launchers.py \| grep -c "/Users/"` | `0` | terminal |
| `git grep -n "/Users/" -- BODAI_REPO_REGISTRY.md scripts/regen_bodai_registry.py scripts/audit_mcp_launchers.py` | no hits | terminal |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| A consumer outside this repo parses the path column expecting an absolute path | Low — the fleet-wide grep found only the three consumers | The published header states the resolution rule; `pathlib` joining tolerates absolute paths |
| The inferred root is wrong (repos live in two places) | Low — all 37 share one parent | "Most common parent" plus a leak-free fallback for out-of-root repos |
| `$BODAI_PROJECTS_ROOT` is set but wrong | Low | Explicit override wins; consumers skip non-existent dirs, as they already do |
| The local overlay's per-machine entries leak into the published artifact | Medium | Paths render root-relative, so the machine's home directory never appears |
| Excluding `dhara` drops a still-maintained repo from the roster | Low — ADR 019 and the 2026-10-09 removal agree | The exclusion records ADR 019 and states that Dhara is still maintained by Bodai, just outside the fleet release set |

## 9. Decision Rule

This plan is done when the registry publishes no absolute path, all three
consumers resolve repos through the declared chain, the build-system guard
passes, and `--check` is green. The 211-file repo-wide sweep is explicitly
out of scope and is a separate plan.

## 10. Evidence

- `BODAI_REPO_REGISTRY.md`: `grep -c "/Users/"` → `0`; summary reports
  "Total active Bodai repos: 34"; the "Path resolution" section names
  `$BODAI_PROJECTS_ROOT`, the registry's own location, and `~/Projects`.
- `python3 scripts/regen_bodai_registry.py --check` → `OK`.
- crackerjack `tests/unit/test_bodai_build_system_guard.py` → `4 passed`
  (was 2 passed / 2 failed before this change).
- crackerjack `tests/unit/test_bodai_registry.py` → `14 passed`.
- mahavishnu `tests/unit/test_bodai_registry_paths.py` → `9 passed`.
- `scripts/audit_mcp_launchers.py` → exit 0, 26 repos audited, `0`
  absolute paths in the emitted table.
- `ruff check` and `ty check` clean on every changed file in both repos.
- Path traversal: a registry row that resolves outside the projects root is
  rejected by `crackerjack/checks/bodai_registry.py::_resolve_under_root`
  (traversal segments, escaping symlinks, and absolute paths outside the
  root). Covered by three tests in `tests/unit/test_bodai_registry.py`.

---

## References

- `docs/decisions/wire-up-contract.md` — the policy this plan implements.
- `docs/adr/019-dhara-decommissioning.md` — the six-repo core fleet set.
- `docs/plans/TEMPLATE.md` — the plan shape.
- `crackerjack/docs/plans/2026-10-28-path-disclosure-redaction.md` — the
  crackerjack-side half of the same effort.
