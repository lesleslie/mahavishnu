---
title: Master Plan Index + Centralized Regenerator (Round 3 Revision)
description: Replace the 7 forked `regenerate_plan_index.py` scripts with a oneiric-hosted shared library. mahavishnu's `docs/plans/PLAN_INDEX.md` becomes the master fleet index via pull-on-regeneration across `settings/ecosystem.yaml`. Crackerjack's existing `plan_index_sync` phase (NOT a fast-hook — opt-in publish-time phase) rewires to the shared library behind a transition feature flag. The Dhara-canonical CRUD layer (`mahavishnu/plan_index/`) and its 5 MCP tools are OUT OF SCOPE — handled by a separate decommission workstream.
audience: oneiric maintainer + mahavishnu maintainer + crackerjack maintainer + every Bodai core component owner
created: 2026-10-19
status: draft
role: canonical
topic: convergence-control-plane
date: 2026-10-19
last_reviewed: 2026-10-19
superseded_by: null
blocks_on:
  - docs/schemas/document-frontmatter-v1.md
---

# Master Plan Index + Centralized Regenerator — Design Spec (Round 3)

## Goal

A single `PLAN_INDEX.md` in `mahavishnu/docs/plans/` (the "master") that aggregates the plan/decision/spec corpus across the 6 Bodai core components. The 7 forked `regenerate_plan_index.py` scripts collapse into one shared library in `oneiric.plan_index`. Pull-on-regeneration, no federation layer, no push surface in siblings.

**Out of scope (handled by separate workstreams — see "Workstreams not in this spec" below):**
- Removing the Dhara-canonical CRUD layer (`mahavishnu/plan_index/{store,rebuild,render,cron,cron_core,record,types,testing,errors,paths,url}.py`) and the 5 `mcp__mahavishnu__plan_*` tools it powers.
- Renaming Dhara-named decision files outside `oneiric/.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md`.
- Removing Dhara references from `oneiric/adapters/tracked_settings.py`, `docs/runbooks/MIGRATE_PLAN_INDEX_DHARA.md`, etc.

## Background

Today (2026-10-19):
- 7 Bodai core repos each ship their own copy of `regenerate_plan_index.py` (and mahavishnu has 5 additional plan-index scripts: `audit_plan_index.py`, `bootstrap_plan_index.py`, `backup_plan_index.py`, `restore_plan_index_backup.py`, `backfill_plan_spec_titles.py`, `_apply_plan_audit_2026_09_12.py`).
- `mahavishnu/docs/plans/PLAN_INDEX.md` frontmatter claims `topic: convergence-control-plane` ("Navigation map for finding and reviewing active Mahavishnu/Bodai plans") but the regenerator only walks mahavishnu's own tree. The claim is aspirational; the artifact doesn't deliver.
- **`mahavishnu/plan_index/` exists with completely different semantics** — it's a 12-file Dhara-canonical CRUD layer (`PlanIndexStore`, `PlanIndexRebuilder`, etc.) powering 5 live MCP tools (`mcp__mahavishnu__plan_{list,show,vitals,search,rebuild_status}`) and the `mahavishnu plan {list,show,vitals,search,purge}` CLI. **This spec does not modify that layer.** Its decommission is a separate workstream.
- **`plan_index_sync` is an opt-in publish-time PHASE in crackerjack** (per commit `e2656170 fix(crackerjack): ratchet path + plan-index-sync to phase`), NOT a fast-hook. Four tests in `crackerjack/tests/core/test_plan_index_sync_phase.py` pin the no-fast-hook invariant. Spec must respect this.
- The `crackerjack run -v -f` (merge gate per `feedback-crackerjack-merge-gate-is-vf`) does NOT run `plan_index_sync`. Only `--publish` (when `settings.documentation.auto_plan_index_sync_on_publish: true`) or explicit `--plan-index-sync` does.
- Open bug surfaced during Round 1 design: `crackerjack/crackerjack/tools/plan_index_sync.py:DEFAULT_STORES` had a verbatim duplicate `docs/plans/` listing. **Already fixed as a side task on 2026-10-19**; the new library pins the singleton invariant so this can't regress.

## Architecture

The regenerator logic moves into `oneiric/plan_index/` as a shared library. Per-repo regeneration goes through crackerjack's existing `plan_index_sync` PHASE (NOT a fast-hook), which now imports the library instead of carrying its own implementation. The master regenerator lives at `mahavishnu/fleet_index/` (a NEW package; **not** at `mahavishnu/plan_index/`) and consumes the same library for each `emit_in_master: true` entry in `settings/ecosystem.yaml`, appending a `## Cross-repo plans` section to mahavishnu's local `PLAN_INDEX.md`. There are no inbound surfaces in sibling repos: they keep generating their own `PLAN_INDEX.md` locally; the master pulls them at regeneration time.

Crackerjack's per-repo hook carries a **transition feature flag** (`settings.documentation.use_shared_regenerator: bool`) so Phase 1 (oneiric land) and Phase 2 (crackerjack rewires) can ship independently of Phase 3 (per-sibling deletion). Until a sibling sets the flag and deletes its fork, that sibling still works on the legacy path.

## Decisions (locked in brainstorming + Round 2 fixes)

1. **Master PLAN_INDEX.md lives in `mahavishnu/docs/plans/PLAN_INDEX.md`** — single file with both mahavishnu-local content and a `## Cross-repo plans` section (variant A).
2. **Shared regenerator library lives in `oneiric/plan_index/`**.
3. **Sync model: pull on regeneration** — master walks siblings at regen time. No push surface in sibling repos. No cron, no webhook.
4. **Discovery reads `mahavishnu/settings/ecosystem.yaml`** (the canonical manifest, per `settings/repos.yaml:1`'s explicit DEPRECATED notice). Add optional `emit_in_master: bool = False` AND required `slug: str` fields to `mahavishnu/core/ecosystem.py:RepositoryConfig` (`slug` defaults to `name.lower()` for backward compatibility; explicit `slug` required when `emit_in_master: true`). `mahavishnu/plan_index/store.py:PlanIndexStore` and any other consumer must be updated to handle the new fields (Pydantic-v2 strict mode → existing `repos_path` loaders will fail without default values on the new fields; both default to `None`/`False` for backward compat).
5. **Fork disposition: delete the 7 forks** per `feedback-no-backwards-compat-pre-1.0.md`. Crackerjack's `crackerjack/tools/plan_index_sync.py` rewires to `oneiric.plan_index` and remains the per-repo phase.
6. **New master package: `mahavishnu/fleet_index/`** (NOT `mahavishnu/plan_index/`). The existing `mahavishnu/plan_index/` package (Dhara-canonical CRUD) is preserved untouched — different feature, separate workstream. The new CLI is `mahavishnu fleet regenerate` (NOT `mahavishnu plan-index regenerate`) — avoids namespace collision with `mahavishnu plan {list,show,vitals,search,purge}`.
7. **CLI placement: `oneiric/cli/plan_index.py`** declaring `plan_index_app = typer.Typer(...)`, registered in `oneiric/cli/__init__.py` next to the existing `app.add_typer(mcp_app, name="mcp")` block at line 282 — NOT `oneiric/core/cli.py` (that module only contains `MCPServerCLIFactory` and `MCPServerBase`; there is no module-level `app` symbol there). This uses the shared `OneiricCLIBase` (`--json`/`version`/`doctor` semantics).
8. **Frontmatter parsing** is lifted VERBATIM from `mahavishnu/scripts/regenerate_plan_index.py:200-230` (`extract_frontmatter` — the line-anchored parser; 8-key schema from `oneiric/schemas/document-frontmatter-v1.md` line 57-66 with `decision_date` ADR-only + `id` optional = up to 9 keys) into `oneiric/plan_index/frontmatter.py`. **No new vocabulary**. **No reuse of `oneiric.schemas.document_frontmatter` as a Python module** — that module doesn't exist; only `.md` schema documents live in `oneiric/schemas/`. The library validates against the schema definition in the `.md` doc; the parser code is lifted from the existing script.
9. **Public library API exposes `scan_entries(repo_root) -> dict[str, list[Entry]]`** as a first-class function. `regenerate()` becomes a thin composition of `scan_entries + render_index + atomic_write`. Master regenerator composes `scan_entries + render_index` per sibling; no markdown round-trip in the consumer.
10. **Crackerjack transition: feature flag per repo** (`settings.documentation.use_shared_regenerator: false` by default). Phase 2 ships the new phase body; each sibling flips the flag in its own release AND deletes the legacy `scripts/regenerate_plan_index.py` (Phase 3). The legacy path is removable in the next crackerjack release after all 6 siblings have flipped (Phase 6).
11. **`Entry` public-API has 8 fields, not 7**: `rel, store, date, status, role, kind, topic, title` (kind matches the current `scripts/regenerate_plan_index.py:166-177` `Entry` shape; without it, the rendered per-store table is missing the Kind column visible in the live `PLAN_INDEX.md`).
12. **`repos.yaml` is DEPRECATED**. Spec does not edit `repos.yaml`. Per `tests/unit/test_registry_sync.py`, `ecosystem.yaml` must remain a superset; that sync-guard test pins the invariant.

## Component responsibilities

### `oneiric/plan_index/` (new shared library)

```
oneiric/plan_index/
    __init__.py            # public surface: re-exports Entry, discover_stores, discover_files, scan_entries, render_index, regenerate
    entry.py               # Entry dataclass: rel, store, date, status, role, kind, topic, title
    frontmatter.py         # VERBATIM lift of scripts/regenerate_plan_index.py:200-230 extract_frontmatter()
    discovery.py           # discover_stores(repo_root) — auto-discover docs/* directories; DEDUP invariant: Sequence[str] preserves first-seen order, never duplicates
    exclusions.py          # shared rules: drafts/, archive/, .backup suffixes, self-skip on PLAN_INDEX.md
    render.py              # render_index(entries_by_store, *, generated_at=...) -> str (includes the distribution footer at the bottom)
    regenerate.py          # regenerate(repo_root, *, out_path=None, exclude=(), check=False) -> int

oneiric/cli/plan_index.py  # NEW: plan_index_app = typer.Typer(...) entry; registered in oneiric/cli/__init__.py
oneiric/cli/__init__.py   # existing — see line 282 for the existing add_typer() block; add a parallel registration for plan_index_app
```

Public API (importable by mahavishnu + crackerjack):

```python
from oneiric.plan_index import (
    Entry,                         # frozen dataclass: rel, store, date, status, role, kind, topic, title
    discover_stores,               # (repo_root: Path) -> Sequence[str]; dedup invariant pinned by test
    discover_files,                # (repo_root: Path, store: str) -> list[tuple[Path, Path]]; first Path is absolute, second is repo-relative
    scan_entries,                  # (repo_root: Path) -> dict[str, list[Entry]]; SKIPS the markdown round-trip
    render_index,                  # (entries_by_store, *, generated_at=...) -> str; emits per-store tables + distribution footer at the bottom
    regenerate,                    # (repo_root: Path, *, out_path: Path | None = None, exclude=(), check=False) -> int
)
```

`regenerate` returns the count of entries written. Default `out_path` is `<repo_root>/docs/plans/PLAN_INDEX.md` (matches the existing crackerjack convention). When `check=True`, it diffs the rendered output against the existing file and exits 1 on drift. The library does **not** accept the legacy script's flags (`--rebuild-from`, `--mcp-url`, `--preflight-mode`, `--stores`, `--extra-stores`, `--json-summary`, `--exclude`, `--exclude-from`, `--render-to`, `--dry-run`, `--skip-render`) — those were Dhara/Phase-B-specific (the `--mcp-url` flag specifically routed to `PlanIndexRebuilder.upsert_all`) and are now out of scope per Decision #4. Crackerjack's `plan_index_sync` phase translates its `--dry-run` flag to `check=True` when calling the new library (see "Crackerjack hook" below).

`MIN_STORE_DOCS: int = 2` is a module-level constant in `discovery.py` (the threshold for auto-promoting a directory to a store). `SYSTEM_DIR_PARTS` is also a module-level constant in `discovery.py`; the full exclusion list is:

```python
SYSTEM_DIR_PARTS = frozenset({
    ".git", ".venv", "venv", "__pycache__", "node_modules", "htmlcov",
    "dist", ".pytest_cache", ".archive", "archive", "backups", ".backups",
    "coverage_report", "assets", ".vscode", ".idea", "cache", ".cache",
    ".playwright-mcp", "worktree-snapshots",
})
```

This list is a verbatim lift from `scripts/regenerate_plan_index.py:99-127`. Tests pin every entry in `test_discovery.py::test_system_dir_parts_pinned`.

### `mahavishnu/fleet_index/` (NEW — master regenerator, NOT a new `plan_index/`)

```
mahavishnu/fleet_index/
    __init__.py            # public surface: re-exports oneiric.plan_index public API
    master.py              # FleetRegenerator: walks ecosystem.yaml, calls oneiric.plan_index.scan_entries for each emit_in_master entry, merges cross-repo section
    format.py              # render_cross_repo_section(entries_by_origin) -> str; per-repo subsections tagged with origin: <slug>
    cli.py                 # `mahavishnu fleet regenerate` Typer entry; registered in mahavishnu/_main_cli.py
```

`FleetRegenerator.regenerate(out_path)` produces `mahavishnu/docs/plans/PLAN_INDEX.md`:

1. Render mahavishnu-local sections via `oneiric.plan_index.regenerate(repo_root=Path("."), out_path=tempfile1)`.
2. For each `ecosystem.yaml` entry with `emit_in_master: true`: call `oneiric.plan_index.scan_entries(repo_root=Path(entry.path))`; tag each entry with `origin: <entry.slug>`.
3. Concatenate: local body (sans distribution footer) + `## Cross-repo plans` section + a single shared distribution footer (via `oneiric.plan_index.render_index(entries_by_store_full, generated_at=...)` re-emitting the footer once with the full entries set).
4. Atomic rename to final path.
5. Return exit code: 0 if all siblings regenerated cleanly OR `--check` mode reports no drift; 1 if any sibling failed OR drift detected.

`mahavishnu/settings/ecosystem.yaml` gets two new fields on each entry (the schema migration per Decision #4):

```yaml
- name: oneiric
  package: oneiric
  path: /Users/les/Projects/oneiric
  slug: "oneir"     # NEW: stable, distinct from basename; required when emit_in_master: true
  ...
  emit_in_master: true        # NEW: include in master fleet aggregation
```

**Schema migration (Pydantic-v2 strict mode → must specify defaults):**

`mahavishnu/core/ecosystem.py:22-55`'s `RepositoryConfig` gains:

```python
slug: str | None = None                    # NEW: defaults to None; when emit_in_master=true, the loader requires it to be non-empty
emit_in_master: bool = False              # NEW: opt-in default false
```

Both default to safe values so existing entries in `ecosystem.yaml` (39 entries) don't break the loader. The master's sync-guard test (in `mahavishnu/tests/integration/fleet_index/test_ecosystem_yaml_validation.py`) pins: "every `emit_in_master: true` entry has a non-empty `slug` AND a path that exists".

### `mahavishnu/plan_index/` (EXISTING — preserved untouched)

This package is the Dhara-canonical CRUD layer. It powers `mcp__mahavishnu__plan_*` and `mahavishnu plan {list,show,...}`. **This spec does not modify it.** Its decommission is a separate workstream (see "Workstreams not in this spec").

### `crackerjack/crackerjack/tools/plan_index_sync.py` (per-repo phase, rewritten with transition flag)

Becomes a thin wrapper with a feature flag. The actual argparse plumbing:

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()  # argparse, NOT Typer — preserves the existing --repo-root, --out, --dry-run surface
    args = parser.parse_args(argv)
    settings = load_settings()  # crackerjack/config/settings.py:load_settings()
    use_shared = bool(
        getattr(settings.documentation, "use_shared_regenerator", False)
    )
    if use_shared:
        from oneiric.plan_index import regenerate
        # Translate --dry-run into check=True (per test coverage I-1)
        return regenerate(
            repo_root=args.repo_root.resolve(),
            out_path=(args.out.resolve() if args.out else None),
            check=bool(args.dry_run),  # dry-run ≡ check
        )
    # legacy path: existing local implementation
    return _legacy_render(args)
```

`settings/crackerjack.yaml:documentation:` block (lines 14-66) gets a new entry documenting the new flag:

```yaml
documentation:
  ...
  use_shared_regenerator: false    # NEW: opt-in per sibling; flip when oneiric.plan_index is available in this repo's dep tree
```

Per `feedback-mcp-common-version-bump-is-user.md`, the version bump in `crackerjack/pyproject.toml` that this dispatcher refactor ships under is operator-controlled. The spec describes WHAT changes; the version field is set at release time.

### `crackerjack/tests/core/test_plan_index_sync_phase.py` (existing — preserved untouched)

The 4 tests pinning the no-fast-hook invariant (L79, L111, L149, L169) stay in place. Phase 2 of this spec does not touch them.

### Sibling repos (after refactor)

For each of `oneiric`, `akosha`, `session-buddy`, `crackerjack`, `mcp-common`, `mahavishnu`:

- **DELETE**: `scripts/regenerate_plan_index.py` (the forked regenerator) — only after Phase 2 ships the new dispatcher AND the sibling has flipped `use_shared_regenerator: true`
- **DELETE** (mahavishnu only): `scripts/audit_plan_index.py`, `scripts/bootstrap_plan_index.py`, `scripts/backup_plan_index.py`, `scripts/restore_plan_index_backup.py`, `scripts/backfill_plan_spec_titles.py`, `_apply_plan_audit_2026_09_12.py`
- **KEEP**: `docs/plans/PLAN_INDEX.md` (regenerated by crackerjack's phase + shared library)
- **KEEP**: `tests/unit/test_*plan_index*` and `tests/integration/plan_index/*` — moved to `oneiric/tests/plan_index/` ONLY in Phase 2 (NOT Phase 1) so crackerjack's CI stays green between phases

## Data Flow

### Per-repo regeneration (crackerjack's `plan_index_sync` phase → local PLAN_INDEX.md)

```
crackerjack run [--plan-index-sync | --publish with auto_plan_index_sync_on_publish: true]
    └── plan_index_sync PHASE (between documentation_cleanup and fast_hooks — NOT a fast-hook itself)
        └── read settings.documentation.use_shared_regenerator
            ├── True:  oneiric.plan_index.regenerate(repo_root=<local>, out_path=docs/plans/PLAN_INDEX.md, check=args.dry_run)
            │           ├── scan_entries(repo_root) → dict[str, list[Entry]]   [NEW public API; 8 fields]
            │           ├── render_index(entries_by_store, generated_at=today)  [includes distribution footer]
            │           └── atomic write to out_path (or diff+exit-1 on check=True)
            └── False: legacy local implementation (deleted in Phase 3 of each sibling)
```

Note: the per-repo phase fires at **publish-time** by default (gated on `auto_plan_index_sync_on_publish: true`), NOT on every commit. The merge gate (`crackerjack run -v -f`) does NOT run `plan_index_sync`. Master drift is caught separately by `mahavishnu fleet regenerate --check` running in CI.

### Master regeneration (mahavishnu CLI → master PLAN_INDEX.md)

```
mahavishnu fleet regenerate [--check] [--dry-run]
    └── mahavishnu.fleet_index.cli → FleetRegenerator.regenerate()
        ├── oneiric.plan_index.regenerate(repo_root=mahavishnu) → local body (per-store tables + distribution footer)
        ├── for each entry in ecosystem.yaml with emit_in_master=true:
        │   ├── oneiric.plan_index.scan_entries(repo_root=<entry.path>) → sibling entries
        │   └── tag entries with origin: <entry.slug>
        ├── assemble: local body (sans footer) + "## Cross-repo plans" section + shared distribution footer (re-rendered once with full entries set)
        └── atomic write to docs/plans/PLAN_INDEX.md; exit code = aggregate (0/1)
```

The master registrator's registry is registered as `app.add_typer(fleet_app, name="fleet")` in `mahavishnu/_main_cli.py` next to the existing `app.add_typer(plan_app, name="plan")` at line 1488.

## Trigger surface

| Action | Command | Frequency |
|--------|---------|-----------|
| Per-repo local regeneration (new path) | `crackerjack run --plan-index-sync` (auto-routed via feature flag) | Explicit invocation OR auto at publish-time per `settings.documentation.auto_plan_index_sync_on_publish: true` |
| Per-repo local regeneration (legacy path) | `crackerjack run --plan-index-sync` (when `use_shared_regenerator: false`) | Until Phase 3 in that sibling |
| Master fleet regeneration | `mahavishnu fleet regenerate` | On-demand |
| Master drift check (no write) | `mahavishnu fleet regenerate --check` | Per-CI / pre-merge in mahavishnu's pipeline |
| Manual one-off via Python | `python -c "from oneiric.plan_index import regenerate; regenerate()"` | Per any consumer |

There is **no** scheduled regeneration. Master freshness is whatever the operator's last `mahavishnu fleet regenerate` produced.

## Master PLAN_INDEX.md format (variant A)

The rendered master looks like:

```markdown
---
status: active
role: canonical
date: 2026-10-19
last_reviewed: 2026-10-19
superseded_by: null
blocks_on:
  - docs/schemas/document-frontmatter-v1.md
topic: convergence-control-plane
---

# Plan Index

**Date:** 2026-10-19
**Last regenerated:** 2026-10-19
**Purpose:** Navigation map for finding and reviewing active Mahavishnu/Bodai plans.
Generated by `mahavishnu.fleet_index.FleetRegenerator` (oneiric.plan_index.scan_entries + render_index).
Do not edit by hand.

[... existing per-store tables: Architecture Decision Records, Plans & Specifications, etc. — unchanged ...]

[... Lifecycle × Role Distribution ...]

## Cross-repo plans

_One section per sibling repo with `emit_in_master: true`. Each row carries the origin repo (via the `slug` field) in the link text._

### `oneir` (substrate/foundation)

| Path | Date | Status | Role | Kind | Topic | Title |
|---|---|---|---|---|---|---|
| [`oneir/docs/plans/2026-10-11-move-llm-and-prompting-from-mcp-common-to-oneiric.md`](../../oneir/docs/plans/2026-10-11-move-llm-and-prompting-from-mcp-common-to-oneiric.md) | 2026-10-11 | `active` | `implementation` | `plan` | `adapter-registry` | Move LLM and Prompting Subsystems from mcp-common to oneir |
```

Each cross-repo sub-section uses the same per-store table format as local sections (note: the `Kind` column is back per Decision #11). Link target uses `ecosystem.yaml` entry's `slug` field prefixed by `../../`. Algorithm: `target = "../../" + entry.slug + "/" + entry.rel`, computed per render and emitted as the markdown link href.

The "hand-curated" sections at the top of mahavishnu's existing `PLAN_INDEX.md` (Status Legend, Authority Matrix, Review Entry Points) are preserved by `fleet_index/format.py`'s prepending step — the spec is wrong if it suggests they're regenerator-owned. Per "Non-goals" below, these stay hand-curated. (Round 2's C6 was about the golden-fixture byte-equality claim, NOT about regenerating these sections.)

## Error handling

| Condition | Behavior | Exit code |
|-----------|----------|-----------|
| `ecosystem.yaml` missing or unparseable | Abort with clear error: "Cannot read ecosystem.yaml at <path>" | 2 |
| `emit_in_master: true` entry missing `slug` field | Abort with clear error: "<name> has emit_in_master but no slug"; do not emit partial master | 2 |
| Sibling repo path doesn't exist | Log warning: "skipping <name>: path <p> does not exist"; continue | 1 (any sibling failure → 1) |
| Sibling PLAN_INDEX.md missing | Log warning: "skipping <name>: no PLAN_INDEX.md at <path>"; continue | 1 |
| Sibling scan fails (frontmatter parse error, I/O) | Log warning: "skipping <name>: <error>"; continue | 1 |
| Sibling path unreadable | Log warning: "skipping <name>: permission denied on <path>"; continue | 1 |
| Local repo path doesn't exist (master regen) | Abort (operator error) | 2 |
| Master regen `--check` mode detects drift | Log "drift detected; <details>"; abort | 1 |
| **Final aggregate** | Log "regenerated: N / M; failed: [list]"; exit 0 if all clean, 1 if any failed | 0/1 |

Per-repo regeneration: abort on local failure (operator pointed the hook at it).

## Migration plan (sequence)

Per `feedback-bodai-push-is-user-controlled.md`, every push is user-controlled. Each phase lands in its own `main` push on its own repo. The user owns the merge order.

1. **Phase 1 — Lift to oneiric**: Oneiric lands `oneiric/plan_index/*` plus tests. Public API includes `scan_entries`, `discover_stores` (with dedup invariant), `discover_files`, `render_index`, `regenerate`. CLI added at `oneiric/cli/plan_index.py` and registered in `oneiric/cli/__init__.py`. **Tests are NOT moved from siblings yet** (crackerjack's CI still relies on them; moving them now would break CI between Phase 1 and Phase 2).
2. **Phase 2 — Rewire crackerjack**: crackerjack's `plan_index_sync.py:main()` reads `settings.documentation.use_shared_regenerator` and dispatches to either the new shared library or the legacy local implementation. The legacy path is preserved for one release. `settings/crackerjack.yaml:documentation:` block gets `use_shared_regenerator: false`. **Now (and only now)** the canonical tests move from each sibling's `tests/unit/test_*plan_index*` and `tests/integration/plan_index/*` into `oneiric/tests/plan_index/`. Crackerjack's `tests/core/test_plan_index_sync_phase.py` stays in place (the 4 invariant tests are phase-ordering, not library behavior).
3. **Phase 3 — Delete the 7 forks (per sibling, gated)**: Each sibling flips `use_shared_regenerator: true` in its own release AND deletes `scripts/regenerate_plan_index.py`. mahavishnu additionally deletes the 5 extras (`audit_plan_index.py`, `bootstrap_plan_index.py`, `backup_plan_index.py`, `restore_plan_index_backup.py`, `backfill_plan_spec_titles.py`, `_apply_plan_audit_2026_09_12.py`). No replacement shims per `feedback-no-backwards-compat-pre-1.0.md`. The flag becomes irrelevant; the legacy path can be removed in the next crackerjack release.
4. **Phase 4 — Master generator**: `mahavishnu/fleet_index/*` lands. `mahavishnu fleet regenerate` CLI exposed (registered as `app.add_typer(fleet_app, name="fleet")` in `mahavishnu/_main_cli.py`). `settings/ecosystem.yaml` gets `emit_in_master: true` + `slug` on each of the 6 Bodai core entries (oneiric, akosha, session-buddy, crackerjack, mcp-common, mahavishnu). Schema migration lands in `mahavishnu/core/ecosystem.py:RepositoryConfig` (defaults `slug: str | None = None`, `emit_in_master: bool = False`). Master regenerator tested in integration against a tmp tree with 6 fake sibling checkouts (NOT real repos — keeps CI hermetic).
5. **Phase 5 — One-off cleanup**: Rename `oneiric/.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md` → `2026-10-11-substrate-refs-cleanup.md` (per the user's 2026-10-19 directive: don't surface Dhara in bodai context). Regenerate oneiric's local PLAN_INDEX.md to reflect the rename. (Larger Dhara decommission is the separate workstream — see "Workstreams not in this spec".)
7. **Phase 6 — Transition cleanup (deferred)**: Remove the legacy path in crackerjack's `plan_index_sync.py:main()` after all 6 siblings have flipped the flag. Maintenance signal: a manual cross-repo check (see Risk #4) — no automated roll-call. Drop the `use_shared_regenerator` setting after the legacy path is gone.

Per `feedback-mcp-common-version-bump-is-user.md`, no `pyproject.toml` version bumps in this work.

## Testing strategy

### Unit (in `oneiric/tests/plan_index/`)

- `test_frontmatter.py` — line-anchored parser; rejects malformed YAML; honors the 8-key schema (status/role/date/last_reviewed/superseded_by/blocks_on/topic + kind). Includes 4 parametrized cases: (a) unclosed `---`, (b) single-dash `---` (not a boundary), (c) valid YAML missing required key, (d) invalid enum value.
- `test_discovery.py` — `discover_stores` honors `SYSTEM_DIR_PARTS` pruning (every entry in the 20-item list pinned by `test_system_dir_parts_pinned`); auto-promotes directories with ≥2 frontmatter'd files (via exported `MIN_STORE_DOCS: int = 2`, boundary cases at 0/1/2/3); **dedup invariant pinned** — `test_dedup_handles_duplicate_dirs_in_scan` ensures `discover_stores` returns a `Sequence` (not a `Set`) so duplicates from filesystem anomalies are de-duplicated while preserving first-seen order.
- `test_exclusions.py` — drafts/ subdirectory skipped; archive/ paths skipped; `.backup` / `.backup.json` suffixes skipped; self-skip on PLAN_INDEX.md. **Negative cases**: `docs/plans/drafts-archive/foo.md` (hyphenated dir) NOT excluded; `docs/archived.md` (top-level file) NOT excluded.
- `test_render.py` — per-store table format includes the Kind column; stable sorting by date DESC, path ASC; distribution matrix; local-only (cross-repo link math moved to `test_link_math.py`).
- `test_scan_entries.py` — direct consumer-side test of the new public API; verifies `scan_entries` returns the same data that `regenerate` would write, without any markdown round-trip; includes the 8 fields including `kind`.
- `test_regenerate.py` — atomic write (tempfile + rename); `--check` mode (drift → exit 1, no-drift → exit 0); `--out` override; default `out_path` resolves to `<repo_root>/docs/plans/PLAN_INDEX.md`; **identity test**: `regenerate(repo_root=X)` produces output identical to `render_index(scan_entries(X), generated_at=...)` written atomically.
- `test_atomic_writes.py` — concurrent regens against the same output file: `os.replace` overwrites atomically on POSIX; last writer wins; no `.bak` file produced.

### Integration (in `mahavishnu/tests/integration/fleet_index/`)

- `test_master_regenerate.py` — fleet regen over a tmp tree with 6 fake sibling checkouts; verifies Cross-repo section is appended; verifies per-repo entries are tagged with `origin: <slug>`; **section order test**: local table for A precedes Cross-repo heading for X, distribution footer appears exactly once, `generated_at` appears exactly once.
- `test_ecosystem_yaml_validation.py` — `ecosystem.yaml` parsing; opt-in default (`emit_in_master` missing → excluded); malformed YAML → clear error; missing `slug` on `emit_in_master: true` entry → clear error; relative path → clear error.
- `test_master_error_handling.py` — missing sibling path → warn + continue + exit 1; unparseable sibling → warn + continue + exit 1; final stderr summary lists failed siblings.
- `test_master_check.py` — `--check` mode detects drift → exit 1; `--check` mode no-drift → exit 0; `--check` mode one-sibling-missing → exit 1.
- `test_link_math.py` — cross-repo link target is `../../` + `<slug>` + `/` + `<entry.rel>`; pin against absolute-path drift; **slug-vs-basename collision test** (`akosha` and `akosha-experimental` both present; link target for entry with `rel: docs/plans/akosha-some-other.md` resolves to `akosha-experimental/...` not `akosha/...`).
- `test_master_dedup.py` — two siblings with identical `ecosystem.yaml` paths but different `slug` fields → dedupe by path (warn, take the first); two entries with same `slug` → reject at parse.
- `test_dedup.py` — sibling whose local `PLAN_INDEX.md` has same plan listed twice → master renders each row once (first-wins, deterministic).
- `test_missing_local_index.py` — sibling with `docs/plans/` but no `PLAN_INDEX.md` → master regen skips + warn + exit 1; operator runs sibling's per-repo phase once to populate, then re-runs master.
- `test_e2e_smoke.py` — marked `@pytest.mark.slow` (per project convention `>10s`). End-to-end: 6 fake sibling checkouts, full master pipeline.

### Regression

- The crackerjack test phase (`tests/unit/test_plan_index_sync.py` and `tests/core/test_plan_index_sync_phase.py`) stays in crackerjack through Phase 1. In Phase 2, `tests/unit/test_plan_index_sync.py` moves to `oneiric/tests/plan_index/test_crackerjack_hook.py` (the dispatcher contract). `tests/core/test_plan_index_sync_phase.py` STAYS in crackerjack (phase-ordering is a crackerjack concern, not library behavior). The 4 invariant tests (L79, L111, L149, L169) remain unchanged.

### Snapshot / golden fixture (PARTIAL, NOT byte-equivalent)

- `oneiric/tests/plan_index/fixtures/PLAN_INDEX.golden.body.md` — snapshot of mahavishnu's CURRENT `PLAN_INDEX.md` body, **regenerator-owned portion only** (per-store tables + distribution footer). Phase 1 asserts byte-equivalence on this partial. The hand-curated STATUS_LEGEND + _authority_matrix + _review_entry_points at the top of the live PLAN_INDEX.md are NOT in the fixture — they're hand-curated per the "Non-goals" section and the fleet master prepends them via `format.py`.

### Test independence

- All unit tests use `tmp_path` fixtures (no `REPO_ROOT` constants pointing at the live checkout). `conftest.py` mandates this pattern. This protects against the "tests pin to a worktree, not the real repo" trap.

## Risks

1. **Sibling staleness**: The master pulls at regen time. If a sibling's local index is stale (only regenerated at publish-time per sibling), the master is stale. Mitigated by `--check` mode catching drift in CI. Per `crackerjack/crackerjack/runtime/oneiric_workflow.py:505-506`, `plan_index_sync` only runs when `--plan-index-sync` is explicitly true OR `--publish` is set; the merge gate `crackerjack run -v -f` does NOT regenerate PLAN_INDEX.md.
2. **Path configuration drift**: `ecosystem.yaml` `path:` fields are absolute paths. If a sibling repo moves, the entry silently points at nothing. The graceful-skip-on-missing behavior turns this into a stderr warning + exit code 1, surfacing the drift in CI.
3. **Cross-repo link drift**: Cross-repo link targets depend on `slug` fields in `ecosystem.yaml`. If an operator renames a slug, links break. The sync-guard test pins the invariant.
4. **Phase 6 maintenance signal**: Phase 6 ("remove the legacy path") has no automated roll-call. Operators must manually verify all 6 siblings have flipped `use_shared_regenerator: true` before Phase 6 lands. Maintenance signal: a `scripts/verify_transition_complete.py` (Phase 6 deliverable) that greps each sibling's `pyproject.toml` for the oneiric version that includes `plan_index`.
5. **Phase ordering with the separate Dhara-decommission workstream**: If that workstream deletes `mahavishnu/plan_index/store.py` (and breaks the 5 `mcp__mahavishnu__plan_*` tools) before this spec ships Phase 4, the test fixtures that depend on the live `mcp__mahavishnu__plan_*` surface break. Mitigation: this spec's e2e tests use the new filesystem-scanner master, not the MCP-backed CRUD store. Coordinate with the Dhara-decommission workstream via shared Phase sequencing.
6. **Pydantic-v2 strict validation in `RepositoryConfig`**: The schema migration adds two fields with `None`/`False` defaults. Existing `ecosystem.yaml` entries continue to load without modification. But Pydantic-v2 strict mode means any entry that flips `emit_in_master: true` MUST also set `slug` (no default); the sync-guard test pins this.

## Non-goals

- Real-time master freshness (webhooks, cron). Pull-on-demand only.
- Bidirectional cross-repo plan linking (e.g., "this plan depends on that plan in another repo"). Future work.
- Inline plan content aggregation. We surface metadata (date, status, role, kind, topic, title) not full plan bodies.
- Permissions / ACLs on who can run the master regenerator. Assumed: any operator with filesystem write access to `mahavishnu/docs/plans/PLAN_INDEX.md`.
- Removing the Dhara-canonical CRUD layer. See "Workstreams not in this spec".
- **Inline PLAN_INDEX.md header sections (status legend, authority matrix, review entry points)** — those are hand-curated today and stay hand-curated post-Phase 4. The regenerator renders only the per-store tables and the distribution footer.

## Workstreams not in this spec (explicit pointers)

The user's 2026-10-19 directive ("Dhara should not be used in any way by any bodai core components anymore") defines a separate workstream that **must** follow this one. Each item below is its own spec, plan, and release train:

1. **`mahavishnu/plan_index/` Dhara-canonical CRUD decommission** — `store.py`, `rebuild.py`, `render.py`, `cron.py`, `cron_core.py`, `writer.py`, `health.py`, `record.py`, `types.py`, `testing.py`, `errors.py`, `paths.py`, `url.py` → delete OR migrate to oneiric equivalent. Affected: 5 `mcp__mahavishnu__plan_*` tools, `mahavishnu plan {list,show,vitals,search,purge}` CLI, `mahavishnu/permissions.py:30 READ_PLAN_INDEX` constant, `mahavishnu/core/state_backends/mcp_kv.py:7`, `mahavishnu/mcp/tools/kv_tools.py:88`, `mahavishnu/mcp/lifecycle.py:39-40, 88, 105-106, 202, 316`, `mahavishnu/mcp/bootstrap.py:289, 1028, 1304`.
2. **`oneiric/adapters/tracked_settings.py` Dhara push removal** — `dhara_url` POST at lines 116, 137, 150, 160, 169 is a live runtime dependency on Dhara. Replace with oneiric-native persistence (or in-memory config if the wiring doesn't need cross-restart durability).
3. **Dhara-named doc cleanup** — `docs/runbooks/MIGRATE_PLAN_INDEX_DHARA.md` (obsolete after the CRUD layer retires), `docs/feature-tracking/plan-index-dhara.md` (status flip + `superseded_by:`), `docs/specs/2026-09-10-plan-index-dhara-design.md` (`superseded_by:` pointing at this spec), and the 5+ plan/followup files referencing `scripts/regenerate_plan_index.py` (which Phase 3 deletes).
4. **Skill migration** — `.claude/skills/bodai-status/SKILL.md:50` and `.claude/skills/mahavishnu-status/SKILL.md:60` currently route plan-level queries through `mcp__mahavishnu__plan_list({status: "active"})`. When the CRUD layer retires, these skills switch to filesystem reads of the regenerated `PLAN_INDEX.md` and surface staleness via `mahavishnu fleet regenerate --check`.

## Out of scope (single sentence)

- Migrating `dhara_client` / `_FakeDharaClient` references out of mahavishnu's source. Already done per the existing `bodai-mcp-client-rename.md` memory; tracked elsewhere.

## Review focus

Five input classes the spec implies but no test in any task explicitly exercises:

1. **An `ecosystem.yaml` entry with `emit_in_master: true` but a relative path** (e.g., `path: ./oneir` instead of absolute) — expected behavior: reject at parse time with a clear error. *Pinned to: `mahavishnu/tests/integration/fleet_index/test_ecosystem_yaml_validation.py::test_relative_path_rejected`.*
2. **Two siblings with identical `ecosystem.yaml` paths but different `slug` fields** — expected behavior: dedupe by path (warn, take the first); don't emit duplicate "in this section". *Pinned to: `mahavishnu/tests/integration/fleet_index/test_master_dedup.py::test_duplicate_repo_path_dedupes`.*
3. **A sibling whose local `PLAN_INDEX.md` has the same plan listed twice** (the very bug we fixed in oneir) — expected behavior: master renders each row once (first-wins, deterministic). *Pinned to: `mahavishnu/tests/integration/fleet_index/test_dedup.py::test_duplicate_plan_first_wins`.*
4. **The master PLAN_INDEX.md is regenerated while a previous regeneration is still in flight** (concurrent runs against the same output file) — expected behavior: `os.replace` overwrites atomically on POSIX; last writer wins; no `.bak` file is produced. *Pinned to: `oneiric/tests/plan_index/test_atomic_writes.py::test_concurrent_writes_last_writer_wins`.*
5. **A sibling that has a `docs/plans/` directory but no `PLAN_INDEX.md`** (no local regen has ever run) — expected behavior: master regen skips it with a warning + exit 1; operator runs the sibling's per-repo phase once to populate its local PLAN_INDEX.md, then re-runs the master. *Pinned to: `mahavishnu/tests/integration/fleet_index/test_missing_local_index.py`.*

## Acceptance criteria carried into the Plan (from Round 2 test coverage)

- **I-1 (parameter translation)**: crackerjack's `--dry-run` flag must translate to `oneiric.plan_index.regenerate(check=True)`. Pinned by `oneiric/tests/plan_index/test_crackerjack_hook.py::test_dry_run_translates_to_check`.
- **I-4 (aggregation order + singleton footer)**: the master renders local + cross-repo sections in order, with the distribution footer exactly once. Pinned by `mahavishnu/tests/integration/fleet_index/test_master_regenerate.py::test_section_order_and_singleton_footer`.