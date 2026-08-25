---
status: active
role: implementation
date: 2026-08-25
last_reviewed: 2026-08-25
owner: les
topic: bodai-cli-audit
scope: bodai-cli
purpose: comprehensive critical audit of CLI commands across the Bodai Core 7, plus phased standardization via BodaiCLIBase and bodai-as-umbrella composition
---

# Bodai Core 7 CLI Audit & Standardization

> **Origin**: ultracode-style comprehensive critical audit dispatched 2026-08-25
> covering CLI command surfaces across the Bodai Core 7 control plane
> (mcp-common, oneiric, dhara, session-buddy, akosha, crackerjack, mahavishnu),
> the `bodai` meta-CLI, and the existing IPython admin shell infra.
>
> **Companion research**: 7 parallel subagents (one per Core 7 repo) confirmed
> the IPython admin shell lives in **`oneiric`** (not mcp-common as I initially
> misremembered), with `AdminShell` as the base class for cross-component
> subclasses. Full findings are in §11 (Cross-shell landscape).

## 1. Outcome

User-observable change: every Bodai CLI is consistent, documented, and
discoverable. `<repo> --help` shows the same global commands (`version`,
`doctor`, `health`) across all 7 components; `bodai` is the umbrella CLI
that composes them via Typer `add_typer` and the `bodai.apps` entry-point
group; `session-buddy shell` is wired (was library-only); `bodai shell` and
`bodai dashboard` are real (were stubs).

Concrete signal:

- `bodai --help` lists all 7 Core 7 sub-CLIs without import errors
- `akosha --help`, `dhara --help`, `mahavishnu --help` etc. each show
  identical `version` and `doctor` subcommands
- `python -m <repo> --help` exits 0 for every Core 7 repo
- `python scripts/audit_cli_inventory.py --all` produces parseable JSON for
  every Core 7 repo; per-repo `docs/audit-inventory/<repo>-cli-inventory.json`
  exists
- `git grep -l 'shell_type="ipython"'` returns zero stale references to
  shell commands that no longer exist

## 2. Goals

1. **Inventory** the full CLI command surface across the Core 7 (entry
   points + sub-CLI modules, per scope decision 2026-08-25).
2. **Surface drift, dead code, missing wire-up, undocumented commands** in
   a machine-readable per-repo inventory (`docs/audit-inventory/*.json`).
3. **Standardize the per-repo CLI** via `oneiric.cli.base.BodaiCLIBase` so
   every `<repo>` exposes `version`, `doctor`, and a uniform exit-code set.
4. **Wire `session-buddy shell`** (currently library-only; `SessionBuddyShell`
   exists with tests but no CLI command invokes it).
5. **Compose Core 7 CLIs into `bodai`** via Typer `add_typer` and the
   `bodai.apps` entry-point group.
6. **Implement the two existing `bodai` stubs**: `bodai shell` (IPython
   REPL using `oneiric.shell.AdminShell`) and `bodai dashboard` (Textual
   TUI over `bodai.core.health.check_all`).
7. **Document the new "Bodai CLI contract"** in
   `.claude/decisions/2026-08-25-bodai-cli-contract.md` so future components
   know how to register.

## 3. Non-Goals

- **Migrating the 10 noise MCP servers (chart-antv, css, excalidraw, etc.)
  to plugins** — separate plan, deferred per the 2026-08-24 env audit.
- **Removing `scripts/*.py` and `*.sh` utility scripts from any repo** —
  out of CLI scope per the audit scope decision (entry points + sub-CLI
  modules only).
- **Replacing `MCPServerCLIFactory` outright** — extended (gains a
  `register_lifecycle_handlers()` method that mounts its start/stop/restart
  handlers onto an external `BodaiCLIBase` instance), not replaced.
- **Adding new CLI commands proactively** — `ADD-NEW` findings from the
  audit are limited to the two existing `bodai` stubs (`shell`,
  `dashboard`) and any cross-repo gaps surfaced by Phase 2 synthesis.
- **A standalone `bodai-cli` repo** — `bodai` is the umbrella home, full stop.
  No new meta-repo.

## 4. Current Findings (preliminary, from research)

The 7 parallel subagent searches (2026-08-25) surfaced these findings without
yet running the inventory tool. The inventory (Phase 1) will surface more.

### 4.1 Process-discipline findings (built-but-not-wired)

| Finding | Repo | Severity |
|---|---|---|
| `SessionBuddyShell(AdminShell)` exists with tests but **no CLI command wires it** — operators must write their own Python entry point | session-buddy | critical |
| `bodai shell` is a stub — `from bodai.admin.shell import launch_shell` raises `ImportError` → user sees "Shell not yet implemented" | bodai | high |
| `bodai dashboard` is a stub — `from bodai.tui.dashboard import BodaiDashboard` raises `ImportError` → user sees "TUI not yet implemented" | bodai | high |
| `oneiric/shell/event_models.py` and `docs/archive/summaries/MCP_ADMIN_CLI_SUMMARY.md` reference `MahavishnuShell` docstrings as "planned" — but `MahavishnuShell` is **fully implemented** with tests, magics, formatters, and a wired `mahavishnu shell` CLI. The archive summary is stale. | mahavishnu / oneiric | drift |

### 4.2 Drift / duplications

| Finding | Severity |
|---|---|
| `dhara admin` (modern `DharaShell(AdminShell)`) AND `dhara db client` (legacy direct `IPython.terminal.embed` import in `dhara/__main__.py`) — duplicate IPython entry points | high |
| Akosha exposes 5 stub shell commands (`aggregate`, `search`, `detect`, `graph`, `trends`) that each return placeholder TODOs | high |
| Akosha does not declare `ipython` as a direct dep in `pyproject.toml`; arrives transitively via oneiric. Crackerjack correctly declares `ipython>=9.14.1`; mahavishnu correctly declares `ipython>=9.16.1`. Risk for users who install akosha without oneiric. | medium |
| Crackerjack `crackerjack/shell/session_compat.py:75` has Python 2 syntax `except ImportError, AttributeError:` — under Python 3 this binds `AttributeError` as the alias, not as a second exception type | medium (latent bug) |
| Crackerjack ships **two parallel interactive modules**: `crackerjack/interactive.py` (legacy, 750 lines, `WorkflowManager`/`TaskDefinition`/`TaskStatus`) and `crackerjack/cli/interactive.py` (newer, 496 lines, `live.run_workflow`) | medium |
| Inconsistent shell-command UX across the 5 repos that have one: `oneiric shell` (no flags), `dhara admin --confirm`, `akosha shell --mode --verbose`, `crackerjack shell` (no flags), `mahavishnu shell` (config-gated) | drift |

### 4.3 Documentation drift

- `dhara admin` and `dhara db client` both referenced in README but only one
  is the modern path.
- `akosha shell` documentation lists the 5 stub commands as if they were
  functional.
- `oneiric shell` and `mahavishnu shell` are well-documented; the others
  have partial docs.

## 5. Implementation Phases

### Phase 0 — Inventory tool (precondition for the audit)

**Goal**: a shared static-inventory tool that walks each Core 7's Typer app
recursively and captures the per-command schema.

**Tasks:**

- 0.1 — Write `scripts/audit_cli_inventory.py` in mahavishnu (reusable
  across all 7 repos; no per-repo forks).
- 0.2 — Walk each repo's Typer `app` recursively via the in-process API;
  fall back to `subprocess --help` if a repo's CLI is broken.
- 0.3 — Per-command fields captured: `repo`, `entry_point`, `command_path`,
  `module`, `function`, `short_help`, `deprecated`, `hidden`,
  `experimental`, `first_added_sha`, `last_modified_sha`,
  `last_modified_date`, `tests_present`, `doc_referenced`,
  `subcommand_count`, `notes`.
- 0.4 — Emit both `docs/audit-inventory/<repo>-cli-inventory.json`
  (machine-readable) and `docs/audit-inventory/<repo>-cli-inventory.md`
  (human-readable).
- 0.5 — Smoke-test against mahavishnu (largest CLI surface) before Phase 1.

**Integration Contract (Phase 0):**

- **Triggered from**: operator runs `python scripts/audit_cli_inventory.py
  --repo <r>` (or `--all`).
- **Returns to / updates**: writes
  `docs/audit-inventory/<r>-cli-inventory.{json,md}`; exits 0/1 per repo.
- **Demonstrable by**: `jq '.commands | length'
  docs/audit-inventory/mahavishnu-cli-inventory.json` returns a non-zero
  integer; `jq '.commands | length'
  docs/audit-inventory/mcp-common-cli-inventory.json` returns 0 (with
  `notes: ["library-only; no CLI surface"]`).
- **Rollback signal**: inventory script broken in CI → skip audit phases
  until fixed; do not block existing tests.
- **Observability added**: per-repo inventory JSON files; baseline
  command-count column in `BODAI_REPO_REGISTRY.md` after Phase 4.

### Phase 1 — Per-repo parallel inventory

**Goal**: produce 6 per-repo inventory JSON+MD files (mcp-common gets a
"library-only confirmation" instead of an inventory).

**Tasks:**

- 1.1 — Dispatch 6 subagents (one per CLI-bearing repo: oneiric, dhara,
  session-buddy, akosha, crackerjack, mahavishnu). Each runs the
  inventory tool against its repo and commits the resulting
  `<repo>-cli-inventory.{json,md}` in a worktree.
- 1.2 — mcp-common gets a 7th agent that confirms "library-only, no
  console script, no `cli.py`" and writes
  `docs/audit-inventory/mcp-common-cli-inventory.md` with that
  confirmation.
- 1.3 — Each agent commits ONLY the inventory files in its worktree; no
  source edits.

**Integration Contract (Phase 1):**

- **Triggered from**: Phase 0 completed.
- **Returns to / updates**: 6 inventory JSON files + 6 MD summaries + 1
  mcp-common confirmation in `docs/audit-inventory/`.
- **Demonstrable by**: `ls docs/audit-inventory/*-cli-inventory.json | wc -l`
  returns 6; `ls docs/audit-inventory/mcp-common-cli-inventory.md` exists.
- **Rollback signal**: `git revert` on each agent's inventory commit.
- **Observability added**: per-repo command-count visible via
  `jq '.commands | length' docs/audit-inventory/<repo>-cli-inventory.json`.

### Phase 2 — Cross-repo synthesis

**Goal**: cross-reference all 6 inventories to surface duplications, gaps,
and inconsistencies.

**Tasks:**

- 2.1 — Single synthesis subagent consumes all 6 JSON inventories + their
  markdown summaries.
- 2.2 — Produce `docs/audit-inventory/findings.md` with tables:
  - Per-repo command counts (sorted descending)
  - Cross-repo command-name duplications (e.g., `shell`, `health`,
    `version`) — with citation to the inventory rows
  - Orphan sub-CLI modules per repo (drift from `app = ...`)
  - Hidden/deprecated commands still referenced in docs
  - Top-10 most-changed commands (signal of where design is settling)
- 2.3 — Each row in the duplications table cites the inventory rows
  that surfaced it (so the reviewer can dismiss false positives).

**Integration Contract (Phase 2):**

- **Triggered from**: Phase 1 completed.
- **Returns to / updates**: `findings.md` ≤ 250 lines.
- **Demonstrable by**: each row links to a JSON inventory row.
- **Rollback signal**: synthesis produced contradictions → revise and
  re-run.
- **Observability added**: `findings.md` becomes input to Phases 3-5.

### Phase 3 — Gap closure (REMOVE / UPDATE / ADD-NEW, by severity)

Subdivided by severity. Each subphase ships in its own commit per affected
repo.

#### Phase 3.1 — Critical (REMOVE / wire-up)

- 3.1.1 — Wire `session-buddy shell` (currently library-only). Add
  `@app.command("shell")` to `session_buddy/__main__.py` that invokes
  `SessionBuddyShell(manager).start()`. Update `session-buddy/CLAUDE.md`
  and `docs/` to reference the new command.
- 3.1.2 — Remove legacy `dhara db client` IPython path
  (`dhara/__main__.py::interactive_client`). Consolidate onto
  `dhara admin --confirm`. Update README and docs.

#### Phase 3.2 — High (UPDATE / remediation)

- 3.2.1 — Akosha stub commands: either implement `aggregate`, `search`,
  `detect`, `graph`, `trends` against real adapters, OR add a
  "preview/alpha" gate (config flag) so users know they're stubs. Default:
  gate them behind `akosha.alpha_shell_commands_enabled: bool = False`.
- 3.2.2 — Akosha `pyproject.toml`: add `ipython>=9.14.0` to direct
  runtime deps (crackerjack and mahavishnu already do this).
- 3.2.3 — Crackerjack `crackerjack/shell/session_compat.py:75`: fix
  Python 2 syntax `except ImportError, AttributeError:` → modern
  `except (ImportError, AttributeError):`.
- 3.2.4 — Crackerjack: consolidate `crackerjack/interactive.py` and
  `crackerjack/cli/interactive.py`. Default: keep `cli/interactive.py`
  (newer), deprecate the older one with a deprecation warning, plan
  removal in Phase 5 of a follow-up audit.
- 3.2.5 — Mahavishnu: consolidate `mahavishnu/monitoring_cli.py` and
  `mahavishnu/cli/monitoring_cli.py` (parallel-files pattern, same
  drift as crackerjack). Same remediation strategy as 3.2.4.

#### Phase 3.3 — Drift (doc sync)

- 3.3.1 — `dhara/README.md`: remove `dhara db client` reference; update
  the CLI table to show `dhara admin` as the only shell entry.
- 3.3.2 — `akosha/docs/ADMIN_SHELL.md`: mark stub commands as preview.
- 3.3.3 — `oneiric/docs/ONEIRIC_ADMIN_SHELL.md` and
  `mahavishnu/docs/ADMIN_SHELL.md`: cross-link so users know all 5 shells
  share the `AdminShell` base.

**Integration Contract (Phase 3):**

- **Triggered from**: Phase 2 findings.
- **Returns to / updates**: per-repo commits that close specific findings.
- **Demonstrable by**: each affected command has either a working CLI
  entry, a deprecation marker, or a doc fix.
- **Rollback signal**: `git revert` per repo's commit.
- **Observability added**: per-repo CHANGELOG entry + the per-finding
  inventory row's `notes` field updated to "fixed".

### Phase 4 — `BodaiCLIBase` standardization

**Goal**: every Core 7 `<repo>` exposes the same global commands
(`version`, `doctor`, `health`) via a shared Typer base class.

**Tasks:**

- 4.1 — Add `oneiric/cli/base.py` with `BodaiCLIBase(typer.Typer)` and
  `ExitCode`. Provides:
  - `version` command (auto-registers from `importlib.metadata.version`)
  - `doctor` command (calls `_doctor_checks()` subclass hook)
  - `health` command (calls `_health_probe()` subclass hook)
  - Standardized exit codes via `ExitCode` enum
  - Tests in `oneiric/tests/cli/test_base.py`
- 4.2 — Extend `mcp_common/cli/factory.py::MCPServerCLIFactory` with a
  `register_lifecycle_handlers(app: typer.Typer) -> None` method that
  mounts the factory's `start`/`stop`/`restart`/`status`/`health`
  handlers onto an external Typer instance (preserves the factory's
  behavior while letting each repo put `start`/`stop` on its own
  `BodaiCLIBase`).
- 4.3 — Convert each Core 7's `app` definition:
  - `oneiric/cli.py`: `app = BodaiCLIBase(component_name="oneiric", ...)`
  - `dhara/cli.py`: same; `factory.register_lifecycle_handlers(app)`
  - `session_buddy/__main__.py`: same; `factory.register_lifecycle_handlers(app)`
  - `crackerjack/__main__.py`: move `app = factory.create_app()` to
    `crackerjack/cli/__init__.py` and convert; or convert in place
    - Move `app` definition out of `__main__.py` to make importable
  - `akosha/cli.py`: `app = BodaiCLIBase(component_name="akosha", ...)`
  - `mahavishnu/_main_cli.py`: `app = BodaiCLIBase(component_name="mahavishnu", ...)`
- 4.4 — Each repo implements the two hooks `_doctor_checks()` and
  `_health_probe()` returning the existing per-repo health-check logic.
- 4.5 — Document the "Bodai CLI contract" in
  `.claude/decisions/2026-08-25-bodai-cli-contract.md`.

**Integration Contract (Phase 4):**

- **Triggered from**: Phase 3 completed (no open critical findings).
- **Returns to / updates**: 1 commit per Core 7 repo (7 total); 1 commit
  in mcp-common (factory extension); 1 commit in oneiric (base class);
  1 new decision doc.
- **Demonstrable by**: `<repo> version` exits 0 across all 7 repos;
  `<repo> doctor` exits 0 (or documented `ExitCode.UNAVAILABLE` if not
  implemented); `<repo> --json` flag accepted by all 7.
- **Rollback signal**: any repo's tests fail after the conversion →
  revert that one repo's commit.
- **Observability added**: per-repo `version` subcommand; `doctor`
  subcommand; uniform exit codes across the ecosystem.

### Phase 5 — Compose Core 7 into `bodai` CLI

**Goal**: `bodai --help` lists Core 7 sub-CLIs; `bodai akosha shell`,
`bodai mahavishnu pool list`, etc. work.

**Tasks:**

- 5.1 — Each Core 7's `pyproject.toml` adds:
  ```toml
  [project.entry-points."bodai.apps"]
  <repo> = "<repo>.<module>:app"
  ```
  One commit per repo (6 commits).
- 5.2 — `bodai/cli.py`: add `_discover_apps()` helper that walks
  `importlib.metadata.entry_points(group="bodai.apps")` and calls
  `app.add_typer(sub_app, name=ep.name)` for each. Lazy-import on
  failure (skip + warn, don't crash).
- 5.3 — Smoke-test: with all 7 repos installed, `bodai --help` lists
  all 7 sub-CLIs; `bodai akosha --help` lists akosha commands; etc.
- 5.4 — Add `tests/test_umbrella.py` in bodai that uses mock entry-points
  to verify the composition logic without requiring all 7 repos in CI.

**Integration Contract (Phase 5):**

- **Triggered from**: Phase 4 completed (all apps use `BodaiCLIBase`).
- **Returns to / updates**: 6 per-repo pyproject commits + 1 bodai
  commit + 1 bodai test commit.
- **Demonstrable by**: `pip install bodai && bodai --help` shows all 7
  sub-CLIs (or 0 if none installed, with "no bodai.apps registered"
  message); `bodai akosha shell` works.
- **Rollback signal**: entry-point discovery raises on import → skip
  core, log warning, continue.
- **Observability added**: `bodai version` aggregation command (built
  from `importlib.metadata.version`); `bodai apps` shows registered apps.

### Phase 6 — Implement the two `bodai` stubs

**Goal**: `bodai shell` and `bodai dashboard` are real, not stubs.
Decided TUI scope (2026-08-25): the dashboard is a **cross-component
aggregator that lives in bodai**, not a replacement for mahavishnu's
mahavishnu-scoped TUI (pools/workers). Both TUIs coexist.

| Surface | Lives in | Shows |
|---|---|---|
| **`bodai dashboard`** (NEW; was stub) | `bodai/tui/dashboard.py` | All 7 Core 7 components: name, role, port, status, version, recent events. Aggregator using `bodai.core.health.check_all()` + canonical status types. Refresh 2-5s. |
| **`mahavishnu monitor --tui`** (existing; rename if needed) | `mahavishnu/tui/monitor_app.py` (already 142 LOC) | Mahavishnu-only: pools, workers, workflow state. Already scope-correct; just needs the CLI command wired if not already. |

**Tasks:**

- 6.1 — Implement `bodai/admin/shell.py::launch_shell()` using
  `oneiric.shell.AdminShell` (or a `BodaiShell(AdminShell)` subclass
  that imports `app`, `oneiric`, all 7 sub-CLIs into the namespace).
- 6.2 — Implement `bodai/tui/dashboard.py::BodaiDashboard` as a
  **cross-component aggregator** (NOT a replacement for mahavishnu's
  pools/workers TUI). Uses Textual; grid view over
  `bodai.core.health.check_all()` results plus the canonical status
  vocabulary in `mahavishnu/core/ecosystem_status.py` (`CanonicalStatus`,
  `DegradationTrend`). Refreshes every 2-5s. ~100 LOC.
- 6.3 — Verify or wire `mahavishnu monitor --tui` (or equivalent)
  pointing at `mahavishnu/tui/monitor_app.py`. Currently `monitor_app.py`
  defines `MonitorApp` but the CLI command that invokes it isn't
  confirmed — add `@monitoring_cli.app.command("tui")` (or name TBD) if
  missing.
- 6.4 — Update `bodai/cli.py` so `bodai shell` and `bodai dashboard`
  reach the new modules (currently they catch `ImportError` and print
  "not yet implemented").
- 6.5 — Tests: `bodai/tests/test_shell.py` exercises `BodaiShell`
  (mocked AdminShell); `bodai/tests/test_dashboard.py` exercises the
  Textual app with a fake `check_all`.

**Integration Contract (Phase 6):**

- **Triggered from**: Phase 5 completed.
- **Returns to / updates**: 1 commit per stub (2 commits); 1 commit to
  wire `mahavishnu monitor --tui`; 1 test commit.
- **Demonstrable by**: `bodai shell` opens an IPython REPL with
  `app`, `oneiric`, all 7 sub-CLIs pre-imported; `bodai dashboard`
  opens a live cross-component Textual grid; `mahavishnu monitor --tui`
  opens mahavishnu's pool/worker view independently.
- **Rollback signal**: stub still raises `ImportError` → blocked, not
  silently broken.
- **Observability added**: the previously stubbed commands now exist
  with real backing code; both TUIs observable as separate
  cross-component vs component-scoped surfaces.

### Phase 7 — Verification + sign-off

**Goal**: confirm net improvement vs. baseline.

**Tasks:**

- 7.1 — Re-run `audit_cli_inventory.py --all` and diff against Phase 0
  baseline.
- 7.2 — Confirm: 0 critical findings remain; 0 orphan sub-CLI modules;
  0 hidden commands referenced in docs; `bodai --help` lists all 7
  registered sub-CLIs.
- 7.3 — Update `BODAI_REPO_REGISTRY.md` with per-repo CLI surface
  summary (entry point + command count + BodaiCLIBase adoption).
- 7.4 — Update `.claude/decisions/2026-08-25-bodai-cli-contract.md`
  `last_reviewed:` field.

**Integration Contract (Phase 7):**

- **Triggered from**: Phase 6 completed.
- **Returns to / updates**: 1 commit in mahavishnu for the registry
  update; the decision doc gets a `last_reviewed` bump.
- **Demonstrable by**: `BODAI_REPO_REGISTRY.md` carries the per-repo CLI
  surface summary.
- **Rollback signal**: net command count increased (regressions).
- **Observability added**: per-repo CLI surface visible in the
  registry; future audits have a baseline.

## 6. Required Code Changes (high-level)

- [ ] `/Users/les/Projects/mahavishnu/scripts/audit_cli_inventory.py` (NEW)
- [ ] `/Users/les/Projects/oneiric/oneiric/cli/base.py` (NEW)
- [ ] `/Users/les/Projects/mcp-common/mcp_common/cli/factory.py` (modify — add `register_lifecycle_handlers`)
- [ ] Per-repo inventory JSON+MD × 6 (`docs/audit-inventory/*.json|md`)
- [ ] `/Users/les/Projects/akosha/akosha/shell/adapter.py` (modify — gate stubs)
- [ ] `/Users/les/Projects/akosha/pyproject.toml` (modify — add `ipython` direct dep)
- [ ] `/Users/les/Projects/crackerjack/crackerjack/shell/session_compat.py` (modify — fix Python 2 syntax)
- [ ] `/Users/les/Projects/crackerjack/crackerjack/__main__.py` (modify — move `app` to `cli/__init__.py`)
- [ ] `/Users/les/Projects/dhara/dhara/__main__.py` (modify — remove legacy `interactive_client`)
- [ ] `/Users/les/Projects/session-buddy/session_buddy/__main__.py` (modify — wire `shell` command)
- [ ] `/Users/les/Projects/{oneiric,dhara,session-buddy,akosha,crackerjack,mahavishnu}/{cli,__main__,_main_cli}.py` (modify — adopt `BodaiCLIBase`)
- [ ] `/Users/les/Projects/{oneiric/oneiric/cli/__init__.py,akosha/akosha/cli.py,...}` (modify — `BodaiCLIBase(component_name=...)`)
- [ ] `/Users/les/Projects/{oneiric,akosha,dhara,session-buddy,crackerjack,mahavishnu}/pyproject.toml` (modify — add `[project.entry-points."bodai.apps"]`)
- [ ] `/Users/les/Projects/bodai/bodai/cli.py` (modify — add `_discover_apps()`)
- [ ] `/Users/les/Projects/bodai/bodai/admin/shell.py` (NEW)
- [ ] `/Users/les/Projects/bodai/bodai/tui/dashboard.py` (NEW)
- [ ] `/Users/les/Projects/bodai/tests/test_umbrella.py` (NEW)
- [ ] `/Users/les/Projects/bodai/tests/test_shell.py` (NEW)
- [ ] `/Users/les/Projects/bodai/tests/test_dashboard.py` (NEW)
- [ ] `/Users/les/Projects/mahavishnu/.claude/decisions/2026-08-25-bodai-cli-contract.md` (NEW)
- [ ] `/Users/les/Projects/mahavishnu/BODAI_REPO_REGISTRY.md` (modify — CLI surface summary)
- [ ] `/Users/les/Projects/bodai/README.md` (modify — document `bodai akosha shell` etc.)

## 7. Decision Rule

This plan is **done enough** when:

1. `scripts/audit_cli_inventory.py --all` exits 0 against current state;
   `docs/audit-inventory/` carries 6 inventory JSON files + 6 MD
   summaries + 1 mcp-common confirmation.
2. **0 critical** Phase 3.1 findings remain (session-buddy shell wired;
   dhara `db client` removed).
3. **All 7 Core 7 repos** have `BodaiCLIBase(component_name=...)` as
   their `app` definition.
4. `pip install bodai` then `bodai --help` lists all 7 sub-CLIs (or
   gracefully says "no bodai.apps registered" if none installed).
5. `bodai shell` opens a real IPython REPL (was a stub).
6. `bodai dashboard` opens a real Textual TUI (was a stub).

If scope pressure forces a cut: ship Phases 0-3 (audit + gap closure)
only. Phases 4-6 (standardization + composition + bodai stubs) are
tracked as future work in the decision doc.

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Inventory script misparses Typer app (hidden nested sub-apps, dynamic registration) | medium | dry-run against mahavishnu first (largest CLI surface); iterate until counts match `mahavishnu --help` recursive walk |
| Phase-1 subagents hit stale-worktree bugs | medium | EnterWorktree + `git reset --hard main` per repo before each agent (matches established pattern) |
| Phase-1 subagent context budget exceeded on mahavishnu (largest CLI) | medium | chunk inventory by subcommand tree; merge in Phase 2 |
| REMOVE breaks user scripts (e.g. `dhara db client`) | low | grep `/Users/les/Projects/*/scripts/`, `~/.zshrc`, and docs for each command before REMOVE; deprecate-not-delete when in doubt |
| Cross-repo synthesis sees "duplication" where there isn't (coordinated by design) | medium | synthesis agent cites specific evidence (command paths + docstrings) per duplication row; reviewer dismisses false positives |
| `BodaiCLIBase` adoption breaks per-repo tests that import `app` | medium | run per-repo test suite after conversion; revert per-repo commit if any test fails |
| Entry-point discovery at `bodai` runtime finds broken imports | medium | `_discover_apps()` catches per-app import errors and warns instead of crashing the whole umbrella |
| `bodai admin/shell.py` introduces cyclic import (oneiric → mcp-common → bodai) | low | bodai already imports `oneiric`; new shell imports `oneiric.shell` only; verify with smoke test |
| `MCPServerCLIFactory.register_lifecycle_handlers` change breaks crackerjack/dhara/session-buddy | low | preserve the old `create_app()` API alongside the new method; verify with smoke tests on all three |

## 9. Out of Scope (explicit non-goals)

See §3.

## 10. Cross-references

- Decision doc: `docs/adr/...` (TBD after spec review)
- Companion decision: `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md` (env audit decisions)
- `BODAI_REPO_REGISTRY.md` — per-repo CLI surface summary (Phase 7)
- `oneiric.shell` package — `AdminShell` base class for admin shells
- `mcp_common.cli.MCPServerCLIFactory` — lifecycle handler source
- `bodai/cli.py` — existing meta-CLI; gains `_discover_apps()` in Phase 5

---

## 11. Appendix: Cross-shell landscape (from 2026-08-25 research)

7 parallel subagents searched each Core 7 repo for IPython/REPL/shell
integration. Key findings, normalized:

### 11.1 Shared admin shell infrastructure

The shared IPython admin shell lives in **`oneiric`** (NOT mcp-common as
this author initially misremembered). `oneiric/shell/core.py::AdminShell`
is the base class; `oneiric/shell/adapter.py::OneiricShell` is the
Oneiric-specific subclass; `IPython.terminal.embed.InteractiveShellEmbed`
is constructed inside `AdminShell.start()`. Each Core 7 that wants a
shell subclasses `AdminShell` and registers the shell as a Typer
command.

### 11.2 Per-repo shell status

| Repo | `AdminShell` subclass | CLI command | Magics | Notable issue |
|---|---|---|---|---|
| oneiric | defines `AdminShell` + `OneiricShell` | `oneiric shell` | `%help_shell`, `%status` | Foundation |
| dhara | `DharaShell` | `dhara admin --confirm` + legacy `dhara db client` | (inherits) | Legacy direct-IPython duplicate in `dhara/__main__.py` |
| session-buddy | `SessionBuddyShell` | **NONE** | (inherits) | **Built but never wired to CLI** |
| akosha | `AkoshaShell` | `akosha shell --mode --verbose` | (none) | 5 stub commands; transitive `ipython` (not in `pyproject.toml`) |
| crackerjack | `CrackerjackShell` | `crackerjack shell` | (inherits) | Python 2 syntax bug `crackerjack/shell/session_compat.py:75`; two parallel interactive modules (`crackerjack/interactive.py` 750 lines legacy + `crackerjack/cli/interactive.py` 496 lines newer) |
| mahavishnu | `MahavishnuShell` | `mahavishnu shell` (config-gated by `shell_enabled`) | `%repos`, `%workflow` | Most fully-developed; 5 dedicated test files |
| mcp-common | — | — | — | Library-only (intentional); `prompt_toolkit` only |
| **bodai** | — | `bodai shell` is a **stub** (no `bodai/admin/shell.py` exists yet) | — | Plus `bodai dashboard` stub |

### 11.3 `bodai` meta-CLI status (as of 2026-08-25)

`bodai/cli.py` already exists and has these commands: `health`,
`start`, `stop`, `restart`, `status`, `dashboard` (stub),
`shell` (stub), `config show`, `config validate`. Uses Typer `app`
with `add_typer(config_app, name="config")` — the exact pattern
proposed for the umbrella composition in Phase 5. `bodai = "bodai.cli:app"`
is already declared as a console script in `bodai/pyproject.toml`.

The `bodai shell` and `bodai dashboard` stubs are evidence the
umbrella was always intended to host a cross-component IPython REPL
and Textual TUI; both were deferred when the per-repo shells were
built first. Phase 6 implements them.

### 11.4 Cross-repo session tracking

Each `AdminShell` subclass emits `SessionStartEvent` / `SessionEndEvent`
to Session-Buddy MCP via `oneiric.shell.session_tracker.SessionEventEmitter`.
The umbrella `bodai shell` (Phase 6) will reuse this pattern.

### 11.5 IPython dependency declarations

| Repo | `ipython` in `pyproject.toml`? |
|---|---|
| oneiric | ✓ direct dep `>=9.15.0` |
| dhara | ✓ direct dep `>=9.14.0` |
| session-buddy | ✗ (transitive via oneiric) |
| akosha | ✗ (transitive via oneiric) — **finding** |
| crackerjack | ✓ direct dep `>=9.14.1` |
| mahavishnu | ✓ direct dep `>=9.16.1` |
| bodai | ✓ direct dep `>=8.0.0` |
| mcp-common | ✗ (no IPython) |

Phase 3.2.2 closes the akosha gap.

---

## 12. Self-review checklist (per brainstorming skill)

- [x] **Placeholder scan**: no TBD/TODO markers; all phases concrete
- [x] **Internal consistency**: phases 0→1→2→3→4→5→6→7 sequence is
      linear and dependency-ordered
- [x] **Scope check**: focused on a single audit + standardization
      cycle; decomposition unnecessary
- [x] **Ambiguity check**: each Phase's "Triggered from / Returns to /
      Demonstrable by / Rollback signal / Observability added" is
      concrete
