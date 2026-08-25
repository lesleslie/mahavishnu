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
- `git grep -l '<Component>Shell'` returns zero stale references to
  shell classes whose backing CLI command was removed (e.g. if a
  Core 7's `shell` Typer command is REMOVE'd in Phase 3, the grep
  should surface any doc/comment still naming `ComponentShell`).

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
   know how to register. **Also add the new decision doc to
   `.claude/decisions/README.md` index** (the wire-up-contract policy
   forbids "documented but not indexed" drift).
8. **Pre-1.0 merge policy**: per Bodai pre-1.0 convention
   (`.claude/decisions/worktree-autoremove-policy.md`,
   MEMORY.md `bodai-pre-1.0-merge-policy`), Bodai components merge
   **directly to main** with no PRs. The 6 per-repo commits in Phase
   5.1, the **6** CLI-bearing-repo conversion commits in Phase 4.3
   (oneiric, dhara, session-buddy, akosha, crackerjack, mahavishnu —
   mcp-common is library-only and needs no CLI conversion), and all
   remediation commits in Phase 3 land on `main` (or worktree-branches
   that fast-forward to `main` via `git update-ref`). No branch
   protection or PR workflow.

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
  command-count column in `BODAI_REPO_REGISTRY.md` (Phase 7 adds the
  registry row; Phase 0 only captures the baseline numbers in
  the inventories themselves).

### Phase 1 — Per-repo parallel inventory

**Goal**: produce 6 per-repo inventory JSON+MD files (mcp-common gets a
"library-only confirmation" instead of an inventory).

**Tasks:**

- 1.1 — Dispatch 6 subagents (one per CLI-bearing repo: oneiric, dhara,
  session-buddy, akosha, crackerjack, mahavishnu). Each runs the
  inventory tool against its repo and commits the resulting
  `<repo>-cli-inventory.{json,md}` in a worktree.
  **Scope reminder**: the inventory must enumerate **every** Typer
  command — including ones not enumerated in §11 of this spec.
  Concretely:
  - **mahavishnu** has 20+ `*_cli.py` files (12 in `mahavishnu/cli/`,
    11 in the package root). All must be inventoried.
  - **crackerjack** has ~28 commands (`run`, `run_tests`, `health`,
    `qa_health`, `shell`, plus sub-apps `docs`, `mcp`, `hypothesis-lock`,
    `audit`, `skills`, `coverage-ratchet`).
  - **dhara** has 8+ top-level commands (`admin`, `db {client,start,pack}`,
    `mcp`, `adapters`, `storage`).
  - **akosha** has 5 Typer commands (`shell`, `start`, `mcp start`,
    `version`, `info`, `modes`); the 5 "stub" methods
    (`aggregate`/`search`/etc.) are IPython namespace helpers, not
    CLI commands.
  - **session-buddy** has its `app` in `cli.py` (not `__main__.py` —
    `__main__.py` is a thin delegate). The Phase 1 agent surfaces this
    as the target for Phase 3.1.1.
  - **oneiric** has `shell` at `cli.py:3031-3058` plus lifecycle
    (`start`/`stop`/`restart`/`health` via `MCPServerCLIFactory`),
    secret rotation, `config`, and adapter management.
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
  `@app.command("shell")` to `session_buddy/cli.py` (NOT
  `__main__.py` — `__main__.py` is a thin delegate; the `app` lies in
  `cli.py`). The command invokes
  `SessionBuddyShell(manager).start()`. Update `session-buddy/CLAUDE.md`
  and `docs/` to reference the new command. Also flag
  `session_buddy/analytics/cli.py` (a separate CLI module that
  Phase 1 should surface) for documentation in Phase 2 synthesis.
- 3.1.2 — Consolidate `dhara admin` (modern `DharaShell(AdminShell)`)
  and `dhara db client` (legacy direct-IPython) — both Typer
  commands exist. The legacy path uses
  `dhara/__main__.py::interactive_client`, which is **also imported
  by** the modern `dhara/cli.py::db client` command (line 571). Do
  NOT delete `interactive_client` — it's still required by the
  modern `db client` Typer command. The fix is: (a) keep both Typer
  commands but `dhara db client` keeps the legacy IPython path
  intentionally (it's a different surface than `dhara admin`), (b)
  add a doc note explaining when to use each. Update README and docs.
- 3.1.3 — Add `dhara mcp` (start/status/health/stop), `dhara adapters`,
  `dhara storage`, `dhara db start`, `dhara db pack` to the
  `docs/audit-inventory/dhara-cli-inventory.md` so Phase 2 synthesis
  sees dhara's full surface (8+ commands, not 2).

#### Phase 3.2 — High (UPDATE / remediation)

- 3.2.1 — Akosha **shell namespace** methods (`aggregate`, `search`,
  `detect`, `graph`, `trends` — these are **IPython shell namespace
  helpers, not Typer CLI commands**): either implement against real
  adapters, OR add a "preview/alpha" gate so users know they're stubs.
  Default: gate them behind
  `akosha.alpha_shell_commands_enabled: bool = False`. Also document
  the actual akosha CLI commands `start`, `mcp start`, `version`,
  `info`, `modes` in `akosha/docs/CLI.md` so the inventory rows in
  Phase 2 reflect reality.
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
- 3.2.6 — mcp-common: fix Python 2 `except ValueError, OSError:` syntax
  in `mcp_common/cli/factory.py` at lines 530 and 745 →
  `except (ValueError, OSError):`. Latent bug (same shape as crackerjack
  `session_compat.py:75` finding) that would re-mount silently broken
  handlers onto every Core 7's `BodaiCLIBase` if not fixed before
  Phase 4.2's `register_lifecycle_handlers` extension.

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

- 4.0 — **Package conversion precondition** (oneiric only):
  `oneiric/cli.py` is currently a 3217-line flat module. Adding
  `oneiric/cli/base.py` would create a Python path conflict. Convert
  `oneiric/cli.py` to a package: move its contents to
  `oneiric/cli/__init__.py`, then add `oneiric/cli/base.py` for
  `BodaiCLIBase`. No other Core 7 has this issue (dhara, crackerjack,
  etc. already use `cli/` directories).
- 4.1 — Add `oneiric/cli/base.py` with `BodaiCLIBase(typer.Typer)` and
  `ExitCode`. Provides:
  - `version` command (auto-registers from `importlib.metadata.version`)
  - `doctor` command (calls `_doctor_checks()` subclass hook)
  - `health` command (calls `_health_probe()` subclass hook)
  - Standardized exit codes via `ExitCode` enum
  - Tests in `oneiric/tests/cli/test_base.py`
  - **Constraint**: `BodaiCLIBase` MUST NOT register its own
    `@app.callback`; Typer allows only one callback per app, and
    oneiric (`oneiric/cli.py:1959`) and mahavishnu (`_main_cli.py`)
    each define `@app.callback(invoke_without_command=True)` for their
    own state initialization. Subclasses retain callback registration.
- 4.2 — Extend `mcp_common/cli/factory.py::MCPServerCLIFactory` with a
  `register_lifecycle_handlers(app: typer.Typer) -> None` method that
  mounts the factory's `start`/`stop`/`restart`/`status`/`health`
  handlers onto an external Typer instance (preserves the factory's
  behavior while letting each repo put `start`/`stop` on its own
  `BodaiCLIBase`).
  - **Pre-condition** (Phase 3.2.6 first): fix Python 2
    `except ValueError, OSError:` syntax at factory lines 530 and 745
    before exposing handlers externally — these are latent bugs that
    would re-mount silently broken handlers onto every Core 7's
    `BodaiCLIBase`.
- 4.3 — Convert each Core 7's `app` definition:
  - `oneiric/cli/__init__.py` (after package conversion in 4.0):
    `app = BodaiCLIBase(component_name="oneiric", ...)`
  - `dhara/cli.py`: same; `factory.register_lifecycle_handlers(app)`
  - `session_buddy/cli.py` (NOT `__main__.py` — `app` is here):
    same; `factory.register_lifecycle_handlers(app)`
  - `crackerjack/__main__.py`: move `app = factory.create_app()` to
    `crackerjack/cli/__init__.py` and convert; or convert in place
    - Move `app` definition out of `__main__.py` to make importable
  - `akosha/cli.py`: `app = BodaiCLIBase(component_name="akosha", ...)`
  - `mahavishnu/_main_cli.py`: `app = BodaiCLIBase(component_name="mahavishnu", ...)`.
    **Note**: the `_main_cli.py` underscore prefix is non-idiomatic for
    a public entry-point declaration. Either rename to `main_cli.py`
    (drop underscore) OR explicitly document that the entry-point
    name is `mahavishnu._main_cli:app`. Default: rename.
- 4.4 — Each repo implements the two hooks `_doctor_checks()` and
  `_health_probe()` returning the existing per-repo health-check logic.
- 4.5 — Document the "Bodai CLI contract" in
  `.claude/decisions/2026-08-25-bodai-cli-contract.md`. **Also add a
  row to `.claude/decisions/README.md` index** (the wire-up-contract
  policy forbids unindexed decisions; matches the
  `2026-08-24-bodai-mcp-routing-pattern.md` precedent).

**Integration Contract (Phase 4):**

- **Triggered from**: Phase 3 completed (no open critical findings).
- **Returns to / updates**: 1 commit per CLI-bearing Core 7 repo (6
  total: oneiric, dhara, session-buddy, akosha, crackerjack,
  mahavishnu — mcp-common is library-only and needs no CLI
  conversion); 1 commit in mcp-common (factory extension); 1 commit
  in oneiric (base class); 1 new decision doc.
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
  Concrete target per repo (verify in Phase 1 inventory):
  - `oneiric = "oneiric.cli:app"` (after package conversion)
  - `dhara = "dhara.cli:create_cli"` — **dhara exposes a factory, not
    a module-level `app`**; the entry-point must invoke the factory,
    or `bodai/cli.py::_discover_apps()` must call `create_cli()` and
    mount its return value. Default: add `app = create_cli()` at
    module-level in `dhara/cli.py` and use `"dhara.cli:app"`.
  - `session-buddy = "session_buddy.cli:app"`
  - `akosha = "akosha.cli:app"`
  - `crackerjack = "crackerjack.cli:app"` (after moving `app` from
    `__main__.py` per Phase 4.3)
  - `mahavishnu = "mahavishnu.cli:app"` (after rename in Phase 4.3;
    note that `mahavishnu/cli/__init__.py:36` re-exports `app` from
    `_main_cli` via a lazy attribute, which works but underscore paths
    in entry-points are non-idiomatic)
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

### Phase 6 — Verify & polish the two `bodai` surface commands

**Goal**: `bodai shell` and `bodai dashboard` work end-to-end. The
implementations **already exist** (verified 2026-08-25: `bodai/admin/shell.py`
contains `launch_shell()` with full IPython namespace setup; `bodai/tui/dashboard.py`
contains `BodaiDashboard` Textual app). Phase 6 work is verification +
polish, not implementation.

| Surface | Lives in | Status (2026-08-25) |
|---|---|---|
| **`bodai shell`** | `bodai/admin/shell.py` | Implemented (`launch_shell()` exists with namespace preloading); wired in `bodai/cli.py`. Try/except catches ImportError defensively. Verify imports work after `pip install bodai`. |
| **`bodai dashboard`** | `bodai/tui/dashboard.py` | Implemented (`BodaiDashboard` Textual app exists). Wired in `bodai/cli.py`. Verify imports work after install. |
| **`mahavishnu monitor --tui`** | `mahavishnu/tui/monitor_app.py` (142 LOC) | Implemented (`MonitorApp` Textual app). Verify CLI command that invokes it is wired; if missing, add `@monitoring_cli.app.command("tui")` in `mahavishnu/cli/monitoring_cli.py`. |

Decided TUI scope (2026-08-25): `bodai dashboard` is a **cross-component
aggregator that lives in bodai**, not a replacement for mahavishnu's
mahavishnu-scoped TUI (pools/workers). Both TUIs coexist.

**Tasks:**

- 6.1 — Verify `from bodai.admin.shell import launch_shell` succeeds
  in a fresh `bodai` install (verified 2026-08-25 in editable install:
  imports OK). If anything in the dependency chain fails, add the
  missing imports to `bodai/pyproject.toml`.
- 6.2 — Verify `from bodai.tui.dashboard import BodaiDashboard` succeeds
  and `bodai dashboard` launches the TUI in a smoke test. Refine the
  cross-component aggregator as needed (uses `bodai.core.health.check_all()`
  + canonical status types from `mahavishnu/core/ecosystem_status.py`).
- 6.3 — Wire `mahavishnu monitor --tui` pointing at
  `mahavishnu/tui/monitor_app.py`. If no CLI command currently invokes
  `MonitorApp`, register it via `@monitoring_cli.app.command("tui")`
  in `mahavishnu/cli/monitoring_cli.py`. Naming convention: the command
  is `tui` (the `monitor` namespace already exists).
- 6.4 — **Remove the defensive try/except** in `bodai/cli.py` once the
  modules are verified importable. The current `except ImportError: ...
  "Shell not yet implemented"` pattern hides real import errors.
  Replace with a direct call and a real error message if the import
  fails for any reason.
- 6.5 — Tests: `bodai/tests/test_shell.py` exercises the IPython shell
  path; `bodai/tests/test_dashboard.py` exercises the Textual app
  with a fake `check_all`.

**Integration Contract (Phase 6):**

- **Triggered from**: Phase 5 completed.
- **Returns to / updates**: 1-2 verification commits (no new modules);
  1 commit to wire `mahavishnu monitor --tui`; 1 commit to remove the
  defensive try/except; 1 test commit.
- **Demonstrable by**: `bodai shell` opens a real IPython REPL;
  `bodai dashboard` opens a live cross-component Textual grid;
  `mahavishnu monitor --tui` opens mahavishnu's pool/worker view
  independently. All three verified via smoke test in CI.
- **Rollback signal**: smoke test fails → block merge.
- **Observability added**: both TUIs observable as separate
  cross-component vs component-scoped surfaces; defensive try/except
  removed so real failures surface loudly.

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
- [ ] `/Users/les/Projects/oneiric/oneiric/cli.py` (modify — convert flat module to package: move contents to `oneiric/cli/__init__.py`)
- [ ] `/Users/les/Projects/oneiric/oneiric/cli/base.py` (NEW — `BodaiCLIBase` + `ExitCode`)
- [ ] `/Users/les/Projects/mcp-common/mcp_common/cli/factory.py` (modify — fix Python 2 `except` syntax at lines 530, 745 → `except (ValueError, OSError):` per Phase 3.2.6, BEFORE the factory extension in Phase 4.2)
- [ ] `/Users/les/Projects/mcp-common/mcp_common/cli/factory.py` (modify — add `register_lifecycle_handlers` per Phase 4.2, AFTER the syntax fix)
- [ ] Per-repo inventory JSON+MD × 6 (`docs/audit-inventory/*.json|md`)
- [ ] `/Users/les/Projects/akosha/akosha/shell/adapter.py` (modify — gate 5 IPython namespace stubs behind `alpha_shell_commands_enabled` flag)
- [ ] `/Users/les/Projects/akosha/pyproject.toml` (modify — add `ipython>=9.14.0` direct dep)
- [ ] `/Users/les/Projects/crackerjack/crackerjack/shell/session_compat.py` (modify — fix Python 2 syntax)
- [ ] `/Users/les/Projects/crackerjack/crackerjack/__main__.py` (modify — move `app = factory.create_app()` to `crackerjack/cli/__init__.py`)
- [ ] `/Users/les/Projects/dhara/dhara/__main__.py` (modify — **DO NOT** remove legacy `interactive_client`; it is still imported by the modern `dhara db client` Typer command at `dhara/cli.py:571`. The Phase 3.1.2 fix is to add a doc note explaining when to use `dhara admin` vs `dhara db client`.)
- [ ] `/Users/les/Projects/session-buddy/session_buddy/cli.py` (modify — wire `shell` command; `__main__.py` is a thin delegate and the `app` lives in `cli.py`)
- [ ] `/Users/les/Projects/{oneiric/cli/__init__.py,dhara/cli.py,session-buddy/cli.py,akosha/cli.py,crackerjack/cli/__init__.py,mahavishnu/_main_cli.py}` (modify — adopt `BodaiCLIBase(component_name=...)`)
- [ ] `/Users/les/Projects/{oneiric,akosha,dhara,session-buddy,crackerjack,mahavishnu}/pyproject.toml` (modify — add `[project.entry-points."bodai.apps"]`)
- [ ] `/Users/les/Projects/bodai/bodai/cli.py` (modify — add `_discover_apps()` AND remove defensive `try/except ImportError` for `shell`/`dashboard` once their modules verify)
- [ ] `/Users/les/Projects/mahavishnu/mahavishnu/_main_cli.py` (consider rename to `main_cli.py` for non-underscored entry-point path)
- [ ] `/Users/les/Projects/bodai/bodai/cli.py` (modify — Phase 6 verification: confirm `bodai shell` / `bodai dashboard` work end-to-end; remove defensive try/except)
- [ ] `/Users/les/Projects/bodai/tests/test_umbrella.py` (NEW — verify `_discover_apps` composes via mock entry-points)
- [ ] `/Users/les/Projects/mahavishnu/.claude/decisions/2026-08-25-bodai-cli-contract.md` (NEW)
- [ ] `/Users/les/Projects/mahavishnu/.claude/decisions/README.md` (modify — add row for the new decision per wire-up-contract policy)
- [ ] `/Users/les/Projects/mahavishnu/BODAI_REPO_REGISTRY.md` (modify — add per-repo CLI surface summary column)
- [ ] `/Users/les/Projects/bodai/README.md` (modify — document `bodai akosha shell` etc.)
- [ ] `/Users/les/Projects/dhara/README.md` (modify — clarify `dhara admin` vs `dhara db client`)

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

- Decision doc: `.claude/decisions/2026-08-25-bodai-cli-contract.md`
  (NEW, written in Phase 4.5)
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
| akosha | `AkoshaShell` | `akosha shell --mode --verbose` | (none) | 5 stub shell-namespace helpers (`aggregate`/`search`/`detect`/`graph`/`trends` — these are IPython helpers, NOT Typer CLI commands); transitive `ipython` (not in `pyproject.toml`); real Typer commands are `start`/`mcp start`/`version`/`info`/`modes` |
| crackerjack | `CrackerjackShell` | `crackerjack shell` | (inherits) | ~28 Typer commands total (`run`, `run_tests`, `health`, `qa_health`, `shell`, + sub-apps `docs`, `mcp`, `hypothesis-lock`, `audit`, `skills`, `coverage-ratchet`); Python 2 syntax bug `crackerjack/shell/session_compat.py:75`; two parallel interactive modules (`crackerjack/interactive.py` 750 lines legacy + `crackerjack/cli/interactive.py` 496 lines newer) |
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

The `bodai shell` and `bodai dashboard` **implementations already exist**
(`bodai/admin/shell.py::launch_shell()` and
`bodai/tui/dashboard.py::BodaiDashboard`); the `try/except ImportError`
in `bodai/cli.py` is defensive safety, not evidence of missing code.
Verified 2026-08-25: `pip install -e .` on bodai makes both modules
importable. The "not yet implemented" message only surfaces when the
package itself isn't installed (e.g. fresh env without
`uv pip install bodai`). Phase 6 verifies and polishes; it does not
implement.

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
