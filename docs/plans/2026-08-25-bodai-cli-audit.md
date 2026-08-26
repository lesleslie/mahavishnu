---
status: active
role: implementation
date: 2026-08-25
last_reviewed: 2026-08-25
owner: les
topic: bodai-cli-audit
scope: bodai-cli
purpose: comprehensive critical audit of CLI commands across the Bodai Core 7, plus phased standardization via BodaiCLIBase and bodai-as-umbrella composition
superseded_by: null
---

# Bodai Core 7 CLI Audit & Standardization

## What & Why (for the human reviewer)

**Goal**: every Core 7 CLI exposes consistent `version`, `doctor`,
`health` global commands. A single `bodai` umbrella CLI composes all
seven via entry-point discovery. Library-only `mcp-common` stays as-is.

**Origin**: ultracode-style comprehensive critical audit, 2026-08-25.

**Read order** (pick one):
- **5 min skim**: §1 Outcome + §3 Non-Goals + §5.0 phase index
- **20 min review**: above + §5 phases (skim Integration Contracts)
- **60 min deep read**: everything; cross-check §4 findings against
  the actual repo state

**Concerns to flag**: §3 Non-Goals drift, §8 Risks (now 11 rows after
round-2 review; see §5.0 for the per-phase structure).

---

> **Companion research note**: 7 parallel subagents (one per Core 7
> repo) confirmed the IPython admin shell lives in **`oneiric`** (not
> mcp-common as initially assumed), with `AdminShell` as the base
> class for cross-component subclasses. Full findings live in the
> research baseline file (see §10 Cross-references); Phase 1 will
> supersede them with the inventory tool output.

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
   TUI over `bodai.core.health.check_all`). **Implementation lives in
   companion plan `2026-08-25-bodai-tui-shell-surface.md` (Plan B);
   this plan delivers the `BodaiCLIBase` foundation Plan B depends on.**
   Round-1 review caught that this Goal cross-references Phase 6 work
   that the original plan deferred to Plan B without explicit
   acknowledgement; this annotation closes the cross-reference.
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

### §5.0 Phase index (at-a-glance)

| Phase | Goal | Depends on | Commits | Smoke-test command |
|---|---|---|---|---|
| **0.0** | Pre-flight: mcp-common factory syntax fix | — | 1 | `git grep -n 'except.*,' mcp-common/mcp_common/cli/factory.py` returns zero matches |
| **0.0.5** | Pre-flight: CHANGELOG.md audit (round-1 F18) | — | 6 (one per repo that lacks one) | every Core 7 repo has `CHANGELOG.md` with `## [Unreleased]` header |
| **0** | Inventory tool (`audit_cli_inventory.py`) + per-repo inventories | — | 1 (script) + 6 (Phase 1) | `python scripts/audit_cli_inventory.py --all` exits 0; 6 JSON files in `docs/audit-inventory/` |
| **1** | Per-repo inventories + staleness signals | 0 | 6 + 1 mcp-common confirmation | `ls docs/audit-inventory/*-cli-inventory.json \| wc -l` = 6 |
| **2** | Cross-repo synthesis + findings.md | 1 | 1 | `wc -l docs/audit-inventory/findings.md` ≤ 250 (CI gate); per-repo pre-commit hook installed (round-1 F13) |
| **3** | Gap closure (REMOVE / UPDATE / ADD-NEW / staleness) | 2 (for staleness table) | ~10 parallel per-repo commits | per-finding commit testable in isolation |
| **4** | `BodaiCLIBase` standardization | 0.0 (pre-flight) | 1 (oneiric base class) + 1 (mcp-common factory extension) + 6 (per-repo conversions, each with 4.1.5 dep bump) + 1 (umbrella CI job in `bodai` repo per round-1 F2) + 1 (manual oneiric publish per round-1 F4) | per-repo CI: `pytest` exits 0; `<repo> version` exits 0; umbrella CI: per-repo smoke loop in `bodai/.github/workflows/umbrella-ci.yml` |
| **5** | `bodai` umbrella + entry-points | 4 | 6 (per-repo entry-points) + 2 (bodai `_discover_apps` + `version`/`apps`) + 1 (umbrella CI extension for `bodai --help`, deferred from Phase 4 per round-1 F1) | umbrella CI: `bodai --help` lists 7 sub-CLIs |
| **6** | Verify `bodai shell` / `bodai dashboard` / `mahavishnu monitor --tui` | 5 (and **3.2.5** for 6.3 specifically — must land after parallel-files consolidation) | 1 (mahavishnu `tui` wire) + 1 (bodai try/except removal) + 1 (tests) + 1 (CI smoke for shell/dashboard/TUI commands per round-1 F21) | per-CI: `pytest bodai/tests/test_dashboard.py` passes; `bodai shell --help`, `bodai dashboard --help`, `mahavishnu monitor tui --help` all exit 0 |
| **7** | Verification + sign-off + quarterly staleness cadence | 6 | 2 (registry update + cadence note + Linux/CI cadence path per round-1 MINOR) | `diff_inventories.py` exits 0; 0 critical findings; `bodai --help \| wc -l` matches |

**Critical-path items** (block the most downstream work):
- **0.0** — 4-character fix, lands today, unblocks Phase 4.2.
- **0.0.5** — CHANGELOG.md audit, lands before Phase 3+ commits that include CHANGELOG updates.
- **4.0** — oneiric package conversion, lands before Phase 4.1.
- **4.1** — `BodaiCLIBase` (with the round-1 revised unified callback), lands before Phase 4.3.
- **4.1.5** — oneiric dep declaration in each converting repo's `pyproject.toml`, lands as part of each Phase 4.3 conversion.
- **4.2** — `register_lifecycle_handlers` (with `prefix=` arg), lands before Phase 4.3.
- **4.4.1** — manual oneiric publish (per `crackerjack-version-bumping-manual.md`), lands between 4.1 and any 4.3 consumer.
- **5** entry-point commits depend on each repo's Phase 4.3 file moves/renames + 4.4.1 publish.

**Parallelizable** (no inter-dependencies):
- Phase 3 sub-phases (each per-repo commit is independent)
- Phase 4.3 per-repo conversions (after 4.0+4.1+4.2)
- Phase 5.1 per-repo entry-point declarations (after 4.3's file moves land)
- Phase 6 TUI verifications (after 5's entry-points are visible)

**Net wall-clock** if all parallelization applied: **~12-16 days
parallelized** (vs ~20-28 days serialized; see round-2 time-to-implementation
reviewer's adjustments — oneiric 3K-line package conversion is real work,
per-repo pytest full-suite gate catches test regressions requiring 1-2
fix commits per active repo). **Phase 3.4 staleness remediation** can
parallelize with Phase 4.3 / 5.1.

**Per-commit landing pattern** (every multi-repo phase — 3.1, 3.2, 4.3,
5.1, 5.5): each per-repo commit lands in its own worktree branch
(`<worktree>/<phase>-<repo>`), then fast-forwards `main` via
`git update-ref refs/heads/main <branch> && git push` from the main
checkout. **Do NOT run cross-worktree file ops in the main checkout** —
Bash classifier blocks per
`mahavishname-worktree-isolation-guard-is-bash-classifier`. Refresh
main checkout's working tree manually between merges. Reference:
MEMORY.md `git-update-ref-from-worktree`, `bodai-pre-1.0-merge-policy`.

### Phase 0 — Inventory tool (precondition for the audit)

**Goal**: a shared static-inventory tool that walks each Core 7's Typer app
recursively and captures the per-command schema.

**Tasks:**

- 0.0 — **Pre-flight fix** (land BEFORE anything else): fix Python 2
  `except ValueError, OSError:` syntax in
  `mcp-common/mcp_common/cli/factory.py` at lines 530 and 745 →
  `except (ValueError, OSError):`. Latent bug (same shape as
  crackerjack `session_compat.py:75` finding). 4-character change,
  unblocks Phase 4.2's `register_lifecycle_handlers` extension. 1
  commit in mcp-common. **This is moved up from the original Phase 3.2.6
  because it has zero dependency on the inventory/synthesis and the
  parallelization review flagged it as a critical-path item that
  doesn't need to be critical-path.**
- 0.0.5 — **CHANGELOG.md audit** (round-1 F18): every Core 7 repo's
  `pyproject.toml` or working tree may lack a `CHANGELOG.md`. Phase 3
  and Phase 4 commits mandate `CHANGELOG.md` updates per the global
  constraint (`**BREAKING:**` prefix where applicable). For each
  repo that lacks `CHANGELOG.md`, create one with at minimum:
  ```markdown
  ## [Unreleased]

  ### Changed

  ### Added

  ### Removed

  ### Deprecated

  ### Fixed

  ### Security
  ```
  One commit per repo that lacks one (likely 1-3 commits; most Core 7
  repos may already have one — verify via `git ls-tree HEAD --name-only
  | grep '^CHANGELOG\.md$' | wc -l`). Lands BEFORE Phase 3 commits
  (any Phase 3 commit with CHANGELOG updates requires the file to
  exist).
- 0.1 — Write `scripts/audit_cli_inventory.py` in mahavishnu (reusable
  across all 7 repos; no per-repo forks).
  **Location decision**: the script lives in `mahavishnu/scripts/` per
  the established `audit_no_secrets_in_mcp.py` precedent. Phase 1
  subagents either (a) install mahavishnu before running, or (b) copy
  the script into their own `scripts/` for the duration of the agent
  task (not committed; throwaway).
- 0.2 — Walk each repo's Typer `app` recursively via the in-process API;
  fall back to `subprocess --help` if a repo's CLI is broken.
- 0.3 — Per-command fields captured: `repo`, `entry_point`, `command_path`,
  `module`, `function`, `short_help`, `deprecated`, `hidden`,
  `experimental`, `first_added_sha`, `last_modified_sha`,
  `last_modified_date`, `tests_present`, `doc_referenced`,
  `subcommand_count`, `notes`.
  **Plus staleness signals** (per user requirement that "all CLI
  commands be audited to make sure they still reflect current
  features"): `todo_markers` (count of `TODO|FIXME|XXX|HACK` in the
  command's source), `last_activity_days` (days since last git
  commit touching the command's source module), `short_help_vs_impl_drift`
  (manual flag, set by Phase 1 agent during review), `staleness_verdict`
  (one of `current`/`stale`/`deprecated`/`unknown`).
- 0.4 — Emit both `docs/audit-inventory/<repo>-cli-inventory.json`
  (machine-readable) and `docs/audit-inventory/<repo>-cli-inventory.md`
  (human-readable).
- 0.5 — Smoke-test against mahavishnu (largest CLI surface) before Phase 1.
- 0.6 — Save `docs/audit-inventory/PHASE_0_BASELINE.json` as the
  committed baseline snapshot. Phase 7 diffs against this file.

**Integration Contract (Phase 0):**

- **Triggered from**: operator runs `python scripts/audit_cli_inventory.py
  --repo <r>` (or `--all`).
- **Returns to / updates**: writes
  `docs/audit-inventory/<r>-cli-inventory.{json,md}` and
  `PHASE_0_BASELINE.json`; exits 0/1 per repo.
- **Demonstrable by**:
  - `jq '.commands | length'
    docs/audit-inventory/mahavishnu-cli-inventory.json` ≥ 50
    (matches the 20+ `*_cli.py` files plus expected subcommands)
  - `jq '.commands | length'
    docs/audit-inventory/mcp-common-cli-inventory.json` = 0 (with
    `notes: ["library-only; no CLI surface"]`)
  - `jq '.commands[].command_path' mahavishnu-cli-inventory.json | sort -u | wc -l`
    matches `mahavishnu --help 2>&1 | awk '/^  [A-Za-z]/ {print $1}' | sort -u | wc -l`
    (inventory vs runtime parity check)
  - `scripts/audit_cli_inventory.py --all` exits 0 against current state
- **Rollback signal**: `audit_cli_inventory.py --all` exits non-zero,
  OR any `*.json` file in `docs/audit-inventory/` is invalid JSON,
  OR any file's `notes` contains `inventory_failed`. Skip Phases 1-7
  until cleared; do not block existing per-repo tests.
- **Observability added**: per-repo inventory JSON+MD files;
  `PHASE_0_BASELINE.json` committed; Phase 7 enriches the registry
  with per-repo CLI surface summary columns.

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
inconsistencies, and staleness.

**Tasks:**

- 2.1 — Single synthesis subagent consumes all 6 JSON inventories + their
  markdown summaries.
- 2.2 — Produce `docs/audit-inventory/findings.md` with tables,
  **and install the CLI-inventory gate across all 7 Core 7 repos**
  (round-1 F13 fix — the prior plan installed the gate only in
  mahavishnu's `.git/hooks/pre-commit`, which meant a developer
  adding `@app.command("foo")` in akosha could land without ever
  touching the gate):
  - **Pre-CI gate** (preventive, not reactive): each Core 7 repo's
    `.git/hooks/pre-commit` runs
    `python /Users/les/Projects/mahavishnu/scripts/audit_cli_inventory.py --repo <self> --check-stale`.
    Installer: `cd /Users/les/Projects/<repo> && uv run mahavishnu index install-hooks .`
    (canonical hook installer per
    `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md`).
    One commit per repo (7 commits) that adds the hook to `.git/hooks/pre-commit`
    (`.git/hooks/` is per-clone gitignored; the installer is invoked
    once per clone, not committed). **Verification**: after install,
    `cd /Users/les/Projects/<repo> && echo "TODO" >> some_file && git add some_file && git commit -m test`
    must fail with "audit_cli_inventory: stale/deprecated commands".
  - **Typer-side guard** (alternative preventive gate; pick one per repo
    based on test-coverage preference): `BodaiCLIBase.__init_subclass__`
    records every registered command into a sidecar file
    `cli-inventory-sidecar.json` checked into the repo. CI fails when
    the sidecar diverges from the Phase 1 inventory. This is
    stronger than the pre-commit gate because it captures the
    actual Typer `app` runtime, not the source-file regex match.
    Default: pre-commit gate for now; Typer-side guard as a Phase 8
    enhancement.
  - Per-repo command counts (sorted descending)
  - Cross-repo command-name duplications (e.g., `shell`, `health`,
    `version`) — with citation to the inventory rows
  - Orphan sub-CLI modules per repo (drift from `app = ...`)
  - Hidden/deprecated commands still referenced in docs
  - Top-10 most-changed commands (signal of where design is settling)
  - **Stale commands table** (Phase 3.4 input): per-command
    `staleness_verdict` from `audit_cli_inventory.py --check-stale`,
    grouped by repo, with the staleness reason (TODO markers,
    short-help vs impl drift, no recent activity, etc.)
- 2.3 — Each row in the duplications table cites the inventory rows
  that surfaced it (so the reviewer can dismiss false positives).

**Integration Contract (Phase 2):**

- **Triggered from**: Phase 1 completed.
- **Returns to / updates**: `findings.md` ≤ 250 lines (CI-gated).
- **Demonstrable by**:
  - `test "$(wc -l < docs/audit-inventory/findings.md)" -le 250`
  - `python scripts/validate_findings.py docs/audit-inventory/findings.md`
    passes (parses every cited inventory row; verifies the inventory
    file exists; verifies the cited row index is in range)
  - `scripts/audit_cli_inventory.py --check-stale --repo <r>` for each
    repo produces a list; Phase 3.4's table consumes those lists.
- **Rollback signal**: `findings.md > 250 lines` (CI gate); or
  `validate_findings.py` exits non-zero (broken inventory links);
  or `check-stale` reports > 5 stale commands (regenerate).
- **Observability added**: `findings.md` (human-readable, links to
  inventory JSON); `validate_findings.py` + `wc -l` gate (CI).

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

#### Phase 3.4 — Staleness remediation (per user requirement)

Per the requirement that "all CLI commands be audited to make sure
they still reflect current features and have not been
deprecated/obsoleted":

- 3.4.1 — For each Phase 1 inventory row with `staleness_verdict` in
  `{stale, deprecated}`: emit a finding row in `findings.md` with the
  per-command staleness reason (TODO markers, no recent activity,
  short-help vs implementation drift).
- 3.4.2 — Per-stale-command remediation: either deprecate (add
  `deprecated=True` to Typer decorator + add deprecation note to
  short_help), implement the missing functionality, or REMOVE the
  command (with grep guard for `~/.zshrc`, `scripts/`, and docs).
- 3.4.3 — Per-repo test: `audit_cli_inventory.py --repo <r> --check-stale`
  exits 0 only when no commands are marked `stale` (post-remediation).
  Wire into per-repo CI.

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
  **Verification step**: after conversion, run
  `python -m oneiric --help` and diff against the pre-conversion
  command list. If anything changes, the conversion missed a
  top-level reference or order-sensitive import — fix and re-run.
- 4.1 — Add `oneiric/cli/base.py` with `BodaiCLIBase(typer.Typer)` and
  `ExitCode`. Provides:
  - `version` command (auto-registers from `importlib.metadata.version`)
  - `doctor` command (calls `_doctor_checks()` subclass hook)
  - `health` command (calls `_health_probe()` subclass hook)
  - `--json` global option (Typer context-var; when set, every
    command emits JSON via per-command `_format_json()` hook)
  - Standardized exit codes via `ExitCode` enum
  - Tests in `oneiric/tests/cli/test_base.py`
  - **Constraint (revised after round-1 review)**: `BodaiCLIBase`
    DOES register a single `@app.callback(invoke_without_command=True)`
    that wires `--json` (sets `ctx.obj["json_output"] = True`) and
    `--version`/`-V` (prints version + emits `DeprecationWarning` to
    stderr for one release, then dispatches to the `version` subcommand).
    Typer's `no_args_is_help=True` is also set so empty-args invokes
    `--help`. This is the standard Typer mechanism for global options;
    round-1 review confirmed the alternative (`sys.argv` mutation)
    is broken under `CliRunner`. Existing callbacks at (verified
    2026-08-25):
    - oneiric `cli.py:1959` (config setup) → **MERGE into BodaiCLIBase's
      unified callback body** (preserve config-setup behavior; BodaiCLIBase's
      callback runs first, then defers to subclass-supplied `_pre_callback`
      hook for repo-specific setup)
    - akosha `cli.py:54` (`@app.callback(invoke_without_command=True) def main`
      — shows help when no subcommand) → **PRESERVE** by merging into the
      unified callback body via akosha's `_pre_callback` override (the
      `no_args_is_help` behavior is orthogonal; both paths trigger on
      the same condition and are designed to merge)
    - crackerjack `__main__.py:138` (`@app.callback(invoke_without_command=True) def version_option`
      — handles `--version` flag) → **REMOVE** (the new `BodaiCLIBase`'s
      `--version` Typer option replaces it)
    - dhara `cli.py:706` (`@app.callback() def global_options` — handles `--version` flag) → **REMOVE**
    - session-buddy `cli/__init__.py:218` (`@app.callback(invoke_without_command=True) def _root`
      — handles `--version` flag) → **REMOVE**
    - **mahavishnu has NO `@app.callback` (verified — `app = typer.Typer(name="mahavishnu")` at `_main_cli.py:81`)**.
  Phase 4.3 conversions MUST:
  - Preserve akosha's `main` callback body via the `_pre_callback` hook
    (merged into the unified callback)
  - **REMOVE** crackerjack/dhara/session-buddy's `--version` callbacks
    (the new `BodaiCLIBase` registers `--version` as a Typer option in
    its unified callback; Typer allows only one callback per app, and
    the unified callback subsumes the old behavior)
  - `--json` and `--version` are registered as Typer options in the
    unified `@app.callback`, NOT via context-var mutation of `sys.argv`
    or per-command parametrize (round-1 review confirmed the `sys.argv`
    mutation shim is broken under `CliRunner` tests)
- 4.2 — Extend `mcp_common/cli/factory.py::MCPServerCLIFactory` with a
  `register_lifecycle_handlers(app: typer.Typer, *, prefix: str = "mcp-") -> None`
  method that mounts the factory's `start`/`stop`/`restart`/`status`/
  `health` handlers onto an external Typer instance, **prefixed** to
  avoid the `health` name collision with `BodaiCLIBase.health` (round-1
  review confirmed the collision silently overwrites whichever is
  registered second; the `prefix=` arg resolves it cleanly). Each repo
  that needs lifecycle verbs builds its own
  `factory = MCPServerCLIFactory(...)`, constructs `app = BodaiCLIBase(...)`,
  then calls `factory.register_lifecycle_handlers(app)` (3-step recipe;
  see Phase 4.3 dhara example). **The default prefix `mcp-` mounts
  lifecycle handlers as `mcp-start`/`mcp-stop`/`mcp-restart`/
  `mcp-status`/`mcp-health`**; lifecycle-bearing repos may pass
  `prefix=""` if they want the bare names (only safe when no other code
  registers `health` on the same app).
  - **Pre-condition** (Phase 0.5 fix lands first): fix Python 2
    `except ValueError, OSError:` syntax at factory lines 530 and 745
    before exposing handlers externally — these are latent bugs that
    would re-mount silently broken handlers onto every Core 7's
    `BodaiCLIBase`.
  - **Round-1 test gap** (review finding): the test asserting
    `register_lifecycle_handlers` mounted correctly uses bare
    `typer.Typer()`, not `BodaiCLIBase`. The `BodaiCLIBase`-bearing test
    must also assert that all 5 prefixed lifecycle commands AND the
    base class's `version`/`doctor`/`health` coexist in `--help`. This
    test guards the Phase 4.3 conversion integration point.
- 4.3 — Convert each Core 7's `app` definition. Six per-repo
  conversions are **independent** and can land as parallel commits
  once Phase 4.0 + 4.1 + 4.2 + **4.1.5 (oneiric dep declaration)** +
  **4.4.1 (oneiric publish)** land:
  - `oneiric/cli/__init__.py` (after package conversion in 4.0):
    `app = BodaiCLIBase(component_name="oneiric", ...)`.
    Preserves existing `cli.py:1959` callback body via `_pre_callback` hook.
  - `dhara/cli.py`: 3-step factory recipe:
    ```python
    factory = MCPServerCLIFactory(component_name="dhara", ...)
    app = BodaiCLIBase(component_name="dhara", ...)
    factory.register_lifecycle_handlers(app)  # mounts as mcp-start, mcp-stop, etc.
    ```
    REMOVES existing `cli.py:706` `--version` callback (replaced by
    `BodaiCLIBase`'s unified callback's `--version` option).
  - `session_buddy/cli/__init__.py` (NOT `cli.py` — `app` is in the
    package's `__init__.py:204`): same factory recipe as dhara.
    REMOVES existing `cli/__init__.py:218` `--version` callback.
  - `crackerjack/cli/__init__.py` (new file; move `app =
    factory.create_app()` from `__main__.py:104` here):
    factory recipe. REMOVES existing `__main__.py:138` `--version`
    callback.
  - `akosha/cli.py`: `app = BodaiCLIBase(component_name="akosha", ...)`.
    **PRESERVES** existing `cli.py:54` `@app.callback(invoke_without_command=True) def main`
    callback body via the `_pre_callback` hook (merged into the unified
    callback; the `no_args_is_help` behavior is orthogonal and merges
    cleanly per round-1 review).
  - `mahavishnu/_main_cli.py`: `app = BodaiCLIBase(component_name="mahavishnu", ...)`.
    **Note**: the `_main_cli.py` underscore prefix is non-idiomatic for
    a public entry-point declaration. Either rename to `main_cli.py`
    (drop underscore) OR explicitly document that the entry-point
    name is `mahavishnu._main_cli:app`. Default: rename.
  - **Umbrella CI gate** (revised after round-1 review): each
    per-repo commit triggers the umbrella CI in the `bodai` repo
    (NOT mahavishnu — see Phase 4.5 revised). The umbrella CI installs
    the published oneiric from PyPI (after Task 4.4.1 publishes) and
    the converting repo's `uv pip install -e .` from its worktree.
    The umbrella CI's smoke loop covers **only** per-repo `version` /
    `doctor` / `--json version` exits 0; **the `bodai --help` smoke is
    deferred to Phase 5.4** (after `_discover_apps()` and the per-repo
    `bodai.apps` entry-points land — round-1 review confirmed Task 4.3
    lands Day 9 but Task 5.1+5.2 land Day 11, so the original Task 4.3
    smoke ran before its prerequisites).
- 4.4 — Each repo implements the two hooks `_doctor_checks()` and
  `_health_probe()` returning the existing per-repo health-check logic.
  Per-repo CI test asserts (concrete template, added after round-1
  review — the prior plan left "Add test" to subagent discretion):
  ```python
  # tests/cli/test_base.py in each converting repo
  import pytest
  from typer.testing import CliRunner

  from oneiric.cli.base import BodaiCLIBase, ExitCode


  def test_app_is_bodai_cli_base():
      from <repo>.cli import app  # noqa: PLC0415
      assert isinstance(app, BodaiCLIBase)
      assert app.component_name == "<repo>"


  def test_doctor_returns_real_checks():
      from <repo>.cli import app  # noqa: PLC0415
      checks = app._doctor_checks()
      assert isinstance(checks, dict)
      assert len(checks) >= 1
      for name, check in checks.items():
          assert hasattr(check, "status")


  def test_health_probe_returns_real_data():
      from <repo>.cli import app  # noqa: PLC0415
      snapshot = app._health_probe()
      assert isinstance(snapshot, dict)
      assert "status" in snapshot


  def test_global_json_flag_accepted():
      from <repo>.cli import app  # noqa: PLC0415
      runner = CliRunner()
      result = runner.invoke(app, ["--json", "version"])
      assert result.exit_code == ExitCode.SUCCESS


  def test_global_version_flag_accepted():
      from <repo>.cli import app  # noqa: PLC0415
      runner = CliRunner()
      result = runner.invoke(app, ["--version"])
      assert result.exit_code == ExitCode.SUCCESS
      assert "<repo>" in result.output  # or whatever the version string is
  ```
  Guards against vacuous implementations AND tests the new Typer-option
  registration (round-1 review confirmed the prior `_intercept_version_flag`
  `sys.argv` mutation was broken under `CliRunner`).
- 4.1.5 — **Cross-repo dep declaration** (NEW after round-1 review):
  Add `oneiric>=<X.Y.Z>` to each converting repo's
  `[project.dependencies]` in `pyproject.toml`, where `<X.Y.Z>` is the
  oneiric version published in Task 4.4.1. Without this, fresh
  `uv pip install -e .` of each converting repo fails with
  `ModuleNotFoundError: No module named 'oneiric.cli.base'`. Per-repo
  CI guard test:
  ```python
  def test_oneiric_bodai_cli_base_importable():
      from oneiric.cli.base import BodaiCLIBase
      assert BodaiCLIBase is not None
  ```
  Lands as part of each Phase 4.3 conversion commit (the dep bump is
  scoped to that repo's `pyproject.toml`).
- 4.4.1 — **Manual oneiric publish step** (NEW after round-1 review):
  Between Task 4.1 (lands BodaiCLIBase on oneiric's main) and the
  first Phase 4.3 conversion (consumes `oneiric.cli.base`), the operator
  bumps oneiric's version and publishes. Per
  `crackerjack-version-bumping-manual.md` ("user initiates bumps and
  PyPI publishes; flag those steps in plans"), this is a **manual**
  step the user runs:
  ```bash
  cd /Users/les/Projects/oneiric
  uv version --bump minor
  git add pyproject.toml
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com \
      commit -m "chore(release): bump version to <X.Y.Z> for BodaiCLIBase"
  uv build
  uv publish
  ```
  **Pre-Phase-4.3 verification** (must pass before any consumer's CI
  runs against the new oneiric):
  ```bash
  python -c "from importlib.metadata import version; \
             import oneiric.cli.base; \
             print(version('oneiric'))"
  ```
  The umbrella CI's smoke loop installs oneiric from PyPI for the
  published version; only the repo currently under test uses
  `uv pip install -e .` (round-1 review confirmed editable-only install
  breaks any consumer outside `/Users/les/Projects/oneiric`).
- 4.5 — Document the "Bodai CLI contract" in
  `.claude/decisions/2026-08-25-bodai-cli-contract.md`. **Also add a
  row to `.claude/decisions/README.md` index** (the wire-up-contract
  policy forbids unindexed decisions; matches the
  `2026-08-24-bodai-mcp-routing-pattern.md` precedent).
  - **Umbrella CI (revised after round-1 review)**: lives in the
    **`bodai` repo**, NOT mahavishnu (the prior plan put it in
    mahavishnu's `.github/workflows/`, which had two structural
    defects: (a) `actions/checkout@v4` only clones mahavishnu so
    `BODAI_ROOT: ${{ github.workspace }}/../` points to an empty
    directory, and (b) GitHub Actions `paths:` filters only match
    files in the workflow's own repo, so pushes to oneiric's `main`
    never trigger the umbrella CI even though the umbrella exists
    precisely to catch cross-repo breakages). The revised workflow:
    1. Lives at `bodai/.github/workflows/umbrella-ci.yml`
    2. Has 7 explicit `actions/checkout@v4` steps (one per Core 7 repo,
       each with `repository: lesleslie/<repo>` and `path: ../<repo>`)
    3. Triggers on `push: branches: [main]` to `bodai`'s `main`
       (the umbrella lives in `bodai`, so this catches both `bodai`
       changes AND any `repository_dispatch` webhook from sibling repos)
    4. **No `paths:` filter** — the workflow's job is to test all 7
       repos every time `bodai` itself changes (and via webhook when
       any sibling pushes). Filtering by file path is no longer
       meaningful once the workflow lives in `bodai`
    5. Per-repo smoke loop:
       `(cd "$REPO_ROOT/$repo" && uv pip install -e . --quiet) && \
        "$repo" version && "$repo" doctor && "$repo" --json version`
       All three must exit 0 for the repo to pass. **No `bodai --help`
       assertion in this workflow** (moved to Phase 5.4).
    6. Coverage assertion (added after round-1 review): for each
       converting repo, `uv run pytest --cov=<pkg> --cov-fail-under=89`
       must pass; this guards against vacuous `_doctor_checks()` /
       `_health_probe()` implementations that pass the smoke loop
       but drop coverage.
    7. **Worktree-to-main landing step** (added after round-1 review):
       each per-repo conversion commit lands in a worktree branch
       (`<worktree>/phase-4.3-<repo>`), then fast-forwards `main` via
       `git update-ref refs/heads/main <branch>` from the **main
       checkout** (NOT the worktree — the Bash classifier blocks
       cross-worktree file ops per
       `mahavishname-worktree-isolation-guard-is-bash-classifier`). The
       worktree's agent dispatches a separate "merge agent" to run
       the `git update-ref` + `git push` from the main checkout. The
       umbrella CI fires on the push and validates. Without this
       landing step, commits sit on detached branches and Phase 4.3
       appears to succeed locally but breaks downstream consumers
       (round-1 finding).

**Integration Contract (Phase 4):**

- **Triggered from**: Phase 3 completed (no open critical findings).
- **Returns to / updates**: 1 commit per CLI-bearing Core 7 repo (6
  total: oneiric, dhara, session-buddy, akosha, crackerjack,
  mahavishnu — mcp-common is library-only and needs no CLI
  conversion); 1 commit in mcp-common (factory extension); 1 commit
  in oneiric (base class); 1 new decision doc.
- **Demonstrable by**:
  - **Per-CI** (each repo): `<repo> version` exits 0;
    `<repo> doctor` exits 0 (or documented `ExitCode.UNAVAILABLE` if
    not yet implemented); `pytest tests/cli/test_base.py` passes
    (asserts `isinstance(app, BodaiCLIBase)`); `pytest` (full suite)
    passes (catches "BodaiCLIBase adoption broke my test" per Risk
    Row 6).
  - **Umbrella CI** (mahavishnu job installs all 7): for each repo,
    `<repo> version`, `<repo> doctor`, `<repo> --json version` all
    exit 0; one shell loop covers all 7.
- **Rollback signal**: any converted repo's `pytest` exits non-zero →
  revert that one repo's commit (per-repo rollback). The umbrella CI
  job surfaces the failing repo by name in CI log output.
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
  Concrete target per repo (verified 2026-08-25):

  | Repo | Entry-point target | Notes |
  |---|---|---|
  | `oneiric` | `oneiric.cli:app` | after package conversion (4.0) |
  | `dhara` | `dhara.cli:app` | add `app = create_cli()` at module-level; or have bodai's `_discover_apps` call the factory and catch the result. **Test for no import side-effects**: `python -c "import dhara.cli; import unittest.mock as m; with m.patch.object(dhara.cli, 'create_cli') as f: assert f.call_count == 0"` |
  | `session-buddy` | `session_buddy.cli:app` | **app lives in `cli/__init__.py:204`, NOT a `cli.py` file**. Must add module-level `app = create_session_buddy_cli()` (currently `app` is local to `create_session_buddy_cli()` and returned via the factory). **Entry-point conflict**: `session-buddy/pyproject.toml` already declares `session_buddy = "session_buddy.__main__:main"`. REPLACE with `session-buddy = "session_buddy.cli:app"` (the existing `session_buddy` entry-point stays untouched; the new `session-buddy` is the kebab-case bodai entry-point). |
  | `akosha` | `akosha.cli:app` | verified |
  | `crackerjack` | `crackerjack.cli:app` | after moving `app` from `__main__.py` per Phase 4.3 |
  | `mahavishnu` | `mahavishnu.cli:app` | after rename in Phase 4.3; `_main_cli.py` → `main_cli.py` |

  One commit per repo (6 commits). For repos with crackerjack's
  `app` move or session-buddy's entry-point conflict, verify
  with: `pip install -e <repo> && <repo> --help | head -5` after
  commit.
- 5.2 — `bodai/cli.py`: add `_discover_apps()` helper:
  ```python
  def _discover_apps(app: typer.Typer) -> None:
      """Mount registered Bodai apps via the bodai.apps entry-point group."""
      from importlib.metadata import entry_points
      try:
          eps = entry_points(group="bodai.apps")
      except Exception as e:  # pragma: no cover
          console.print(f"[yellow]No bodai.apps entry points available: {e}[/yellow]")
          return
      for ep in sorted(eps, key=lambda e: e.name):
          try:
              sub_app = ep.load()
          except (ImportError, ModuleNotFoundError) as e:
              console.print(f"[yellow]Skipping {ep.name}: import failed ({e})[/yellow]")
              continue
          except Exception as e:  # noqa: BLE001 - boundary handler catches all errors
              console.print(f"[yellow]Skipping {ep.name}: load failed ({e})[/yellow]")
              continue
          app.add_typer(sub_app, name=ep.name)
  ```
  Catches `ImportError`/`ModuleNotFoundError` per-app (skip + warn),
  NOT bare `Exception` (which would hide real bugs). When 0 entry
  points are registered, `bodai --help` still works (no sub-CLIs).
- 5.3 — Smoke-test: with all 7 repos installed (umbrella CI), `bodai
  --help` lists all 7 sub-CLIs; `bodai akosha --help` lists akosha
  commands; etc.
- 5.4 — **Umbrella CI extension** (round-1 F1 fix — `bodai --help` smoke
  deferred from Phase 4.3 because `_discover_apps()` and the per-repo
  `bodai.apps` entry-points don't land until Phase 5.1+5.2): the
  umbrella CI workflow in `bodai/.github/workflows/umbrella-ci.yml`
  gains a second job (or second step in the existing job) that
  asserts
  `bodai --help | grep -E '^\s+(oneiric|akosha|crackerjack|dhara|session-buddy|mahavishnu)\b'`
  returns 6 matches and `bodai version | wc -l` returns 6 (or 7 if
  mcp-common gets an entry-point). This task is what the Phase 4.3
  smoke was supposed to verify; round-1 review confirmed it can't
  run until Tasks 5.1+5.2 land (Day 11, vs Day 9 for 4.3). Lands as a
  separate PR on the umbrella CI workflow after Phase 5.2 commits.
- 5.4 — Add `tests/test_umbrella.py` in bodai that uses mock
  entry-points (via `monkeypatch.setattr(bodai.cli, 'entry_points', ...)`)
  to verify the composition logic without requiring all 7 repos in
  per-repo CI. **Specific tests**:
  - `test_discover_apps_with_mock_entry_points` — registers 7 fake
    entry-points; asserts all 7 sub-CLIs appear in `bodai --help`.
  - `test_discover_apps_skips_broken_import` — registers 1 broken
    entry-point + 6 healthy; asserts `bodai --help` lists 6 (broken
    skipped with warning, no crash).
  - `test_discover_apps_no_entry_points` — empty entry-points group;
    asserts `bodai --help` works and shows "no bodai.apps registered"
    message.
- 5.5 — Implement two cross-component aggregation commands
  (promised in Phase 5 Observability but never assigned a task):
  - `bodai version` — walks `_discover_apps()` output, prints each
    registered app's `importlib.metadata.version(<dist-name>)` as a
    2-column table.
  - `bodai apps` — lists entry-point names and their target module
    path (`bodai.apps.<dist-name> = <module>:<attr>`).
  Per-CI test: `bodai version | wc -l >= 1` (with mock apps) or 7
  (umbrella CI).

**Integration Contract (Phase 5):**

- **Triggered from**: Phase 4 completed (all apps use `BodaiCLIBase`).
  Phase 3.1 critical findings closed (so demonstrable
  `bodai akosha shell` actually works).
- **Returns to / updates**: 6 per-repo pyproject commits + 1 bodai
  commit (`_discover_apps`) + 1 bodai commit (`version`/`apps` +
  tests) = 8 commits total.
- **Demonstrable by**:
  - **Per-CI** (bodai repo only): `pytest
    bodai/tests/test_umbrella.py` passes (3 test cases above).
  - **Umbrella CI** (after `pip install -e bodai oneiric akosha
    crackerjack dhara session-buddy mahavishnu mcp-common`):
    `bodai --help | grep -E '^\s+(oneiric|akosha|crackerjack|dhara|session-buddy|mahavishnu)\b'`
    returns 6 matches; `bodai version | wc -l` returns 6 lines (or 7
    if mcp-common gets an entry-point).
- **Rollback signal**: `pytest bodai/tests/test_umbrella.py` fails
  → revert the bodai/cli.py `_discover_apps` commit. Per-repo CI
  failures → revert that repo's entry-point commit.
- **Observability added**: `bodai version` (aggregates versions
  across all 7); `bodai apps` (lists registered apps + targets);
  per-repo entry-points visible via `importlib.metadata`.

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
- 6.6 — **CI smoke for the three TUI/shell commands** (round-1 F21
  fix — the spec claimed "smoke test in CI" but the impl plan had
  no actual CI step asserting these work): the umbrella CI gains
  a step that runs
  `timeout 5 bodai shell --help`,
  `timeout 5 bodai dashboard --help`, and
  `timeout 5 mahavishnu monitor tui --help`. Each must exit 0
  (verifies imports + command registration; not interactive).
  Per-repo CI (bodai + mahavishnu) adds the same step.
- 6.7 — **Typer-CLI-Runner assertion** for the three commands (added
  after round-1 review to match the `--json` / `--version` test
  pattern from Phase 4.4): for each of `bodai shell`, `bodai
  dashboard`, `mahavishnu monitor tui`, a `typer.testing.CliRunner`
  invocation that asserts `--help` exits 0 and the `__doc__` /
  short-help is non-empty. This catches import failures and broken
  registration that the timeout smoke wouldn't (the timeout smoke
  could pass if the command hangs but never imports).

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

**Goal**: confirm net improvement vs. baseline; establish ongoing
staleness re-audit cadence.

**Tasks:**

- 7.1 — Re-run `audit_cli_inventory.py --all` and diff against
  `docs/audit-inventory/PHASE_0_BASELINE.json` via
  `scripts/diff_inventories.py`. Per-repo command count must be
  within ±2 of baseline (excludes Phase 3 ADD-NEW findings explicitly
  tracked in `findings.md`).
- 7.2 — Confirm: 0 critical findings remain (gate via
  `jq '[.[] | select(.severity == "critical")] | length == 0' findings.json`,
  after encoding severity in inventory JSON); 0 orphan sub-CLI modules;
  0 hidden commands referenced in docs; `bodai --help` lists all 7
  registered sub-CLIs.
- 7.3 — Update `BODAI_REPO_REGISTRY.md` with per-repo CLI surface
  summary (entry point + command count + BodaiCLIBase adoption).
- 7.4 — Update `.claude/decisions/2026-08-25-bodai-cli-contract.md`
  `last_reviewed:` field.
- 7.5 — **Quarterly staleness re-audit cadence** (per user
  requirement that commands be audited for obsolescence): add a
  cron-style reminder or a session-buddy reminder entry that runs
  `scripts/audit_cli_inventory.py --check-stale --all` every 90 days
  and writes the output to `docs/audit-inventory/staleness-<date>.json`.
  Each new finding that emerges between plan executions gets added
  to Phase 3.4 retroactively. The mechanism is a one-line cron +
  the existing inventory script; no new infrastructure.

**Integration Contract (Phase 7):**

- **Triggered from**: Phase 6 completed.
- **Returns to / updates**: 1 commit in mahavishnu for the registry
  update; the decision doc gets a `last_reviewed` bump; a
  `.claude/decisions/bodai-cli-staleness-cadence.md` note captures the
  quarterly re-audit mechanism.
- **Demonstrable by**:
  - `BODAI_REPO_REGISTRY.md` carries the per-repo CLI surface summary.
  - `scripts/diff_inventories.py PHASE_0_BASELINE.json docs/audit-inventory/`
    exits 0 (within ±2 per repo).
  - `jq '[.findings[] | select(.severity == "critical")] | length'
    findings.json` returns 0.
  - `bodai --help | grep -c '^\s\+\(oneiric\|akosha\|crackerjack\|dhara\|session-buddy\|mahavishnu\)\b'`
    returns 6.
- **Rollback signal**: any per-repo `len(commands)` exceeds baseline +
  2 → identify offending Phase 3.x commit via `git log --oneline
  docs/audit-inventory/<repo>-cli-inventory.json` and revert.
- **Observability added**: per-repo CLI surface visible in the
  registry; quarterly staleness cadence captured; future audits
  have a baseline + automated diff.

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
- [ ] `/Users/les/Projects/mahavishnu/.github/workflows/umbrella-ci.yml` (NEW — Umbrella CI job: install all 7 packages + run multi-repo smoke loop. Demonstrable gate for every Phase 4.3 conversion and Phase 5 entry-point. NEW commit; does not currently exist.)

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

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| 1 | Inventory script misparses Typer app (hidden nested sub-apps, dynamic registration) | medium | dry-run against mahavishnu first (largest CLI surface); iterate until counts match `mahavishnu --help` recursive walk; per-repo minimum-threshold gate (`commands.length >= known_min`) catches silent undercounts |
| 2 | Phase-1 subagents hit stale-worktree bugs | medium | EnterWorktree + `git reset --hard main` per repo before each agent (matches established pattern) |
| 3 | Phase-1 subagent context budget exceeded on mahavishnu (largest CLI, 20+ `*_cli.py`) | medium | chunk inventory by subcommand tree; merge in Phase 2 |
| 4 | REMOVE breaks user scripts (e.g. `dhara db client`) | low | grep `/Users/les/Projects/*/scripts/`, `~/.zshrc`, and docs for each command before REMOVE; deprecate-not-delete when in doubt |
| 5 | Cross-repo synthesis sees "duplication" where there isn't (coordinated by design) | medium | synthesis agent cites specific evidence (command paths + docstrings) per duplication row; reviewer dismisses false positives |
| 6 | `BodaiCLIBase` adoption breaks per-repo tests that import `app` | medium | each per-repo CI runs `pytest` full suite after conversion; if `<repo> pytest` exits non-zero, revert that one repo's commit (umbrella CI job surfaces the failing repo by name) |
| 7 | Entry-point discovery at `bodai` runtime finds broken imports | medium | `_discover_apps()` catches per-app `ImportError`/`ModuleNotFoundError` and warns to stderr instead of crashing; per-CI test asserts this with a mock broken entry-point |
| 8 | **`BodaiCLIBase` collides with existing `@app.callback` in 4 of 6 conversion targets** (Typer allows only one). Verified: oneiric `cli.py:1959`, akosha `cli.py:54` (preserve), crackerjack `__main__.py:138` (REMOVE), dhara `cli.py:706` (REMOVE), session-buddy `cli/__init__.py:218` (REMOVE). mahavishnu has no callback. | high | Phase 4.1 enumerates each repo's existing callback with the preserve-or-remove decision; Phase 4.3 per-repo conversions execute those decisions; each conversion runs `python <repo> --help` smoke test before commit |
| 9 | **session-buddy conversion target file is wrong** (`cli.py` doesn't exist; `app` is in `cli/__init__.py:204`) | high | Phase 4.3 explicitly targets `session_buddy/cli/__init__.py:204`; entry-point declaration uses `session-buddy = "session_buddy.cli:app"` (the `session-buddy` kebab-case replaces the existing `session_buddy` underscore entry-point) |
| 10 | dhara factory-instance state lost when `register_lifecycle_handlers` mounts onto external Typer | medium | Phase 4.1's `register_lifecycle_handlers` is a method on the factory instance, not a class method; Phase 4.3 dhara recipe shows the 3-step pattern (`factory = MCPServerCLIFactory(...); app = BodaiCLIBase(...); factory.register_lifecycle_handlers(app)`); per-repo CI test asserts `dhara --help | grep -E '^(start|stop|restart|status|health)$'` returns 5 matches |
| 11 | `bodai shell` import fails on systems where `ipython` isn't installed (genuine; `from IPython.terminal.embed import InteractiveShellEmbed` is lazy-imported inside `AdminShell.start()` but `from oneiric.shell import AdminShell` is eager) | low | bodai `pyproject.toml` declares `ipython>=8.0.0` as runtime dep; Phase 6.4 removes the defensive try/except and replaces it with a real error message including the install command (`uv pip install bodai[shell]`) |
| 12 | **Umbrella CI in mahavishnu's repo can't see sibling repos** (round-1 CRITICAL): `actions/checkout@v4` only clones mahavishnu; `${{ github.workspace }}/../` is empty on the runner | high | Phase 4.5 moves the workflow to `bodai/.github/workflows/umbrella-ci.yml` with 7 explicit `actions/checkout@v4` steps (one per Core 7 repo) |
| 13 | **`BodaiCLIBase.health` collides with `factory.register_lifecycle_handlers`'s `health` handler** (round-1 CRITICAL): Click/Typer duplicate-name behavior varies by version; one of the two definitions is silently lost | high | Phase 4.2 adds `prefix: str = "mcp-"` parameter to `register_lifecycle_handlers` so lifecycle commands mount as `mcp-start`/`mcp-stop`/etc. by default; the test in Phase 4.2 asserts all prefixed commands AND `BodaiCLIBase`'s `version`/`doctor`/`health` coexist |
| 14 | **`oneiric.cli.base` import fails in 5 converting repos because `oneiric` is not in their `[project.dependencies]`** (round-1 CRITICAL) | high | Phase 4.1.5 adds `oneiric>=<X.Y.Z>` to each converting repo's `pyproject.toml` as part of the Phase 4.3 conversion commit; per-repo CI guard test asserts `from oneiric.cli.base import BodaiCLIBase` succeeds in fresh `uv pip install -e .` |
| 15 | **`--json` global option never populated because `BodaiCLIBase.__init__` doesn't register `@app.callback`** (round-1 CRITICAL): the constraint forbidding BodaiCLIBase from registering its own callback was incompatible with Typer's mechanism for global options | high | Phase 4.1's constraint is **revised**: `BodaiCLIBase` now registers a single unified `@app.callback(invoke_without_command=True)` that wires `--json` (sets `ctx.obj["json_output"]`) and `--version`/`-V` (prints version + deprecation warning, then dispatches to `version` subcommand); akosha's preserved callback merges via `_pre_callback` hook |
| 16 | **`_intercept_version_flag()` mutates `sys.argv` at `__init__` time, broken under `CliRunner`** (round-1 MAJOR): CliRunner invokes Typer with its own `args` parameter, not `sys.argv`, so the shim never fires; the shim also pollutes global state at import time | high | Replaced by Typer-native `--version` option in the unified callback (Risk 15); no `sys.argv` mutation |
| 17 | **Phase 4.3's `bodai --help` smoke can't pass because `_discover_apps()` and `bodai.apps` entry-points don't land until Phase 5.1+5.2** (round-1 CRITICAL): Task 4.3 lands Day 9, Task 5.1+5.2 land Day 11; the smoke would fail for ~2 days | high | Phase 4.3 drops the `bodai --help` smoke; Phase 5.4 adds it after Phase 5.1+5.2 land |
| 18 | **Manual oneiric publish step missing between Phase 4.1 and Phase 4.3** (round-1 MAJOR): BodaiCLIBase lands on oneiric's `main` but PyPI still ships the pre-`BodaiCLIBase` version; any consumer outside `/Users/les/Projects/oneiric` fails `from oneiric.cli.base import BodaiCLIBase` | medium | Phase 4.4.1 adds an explicit manual publish step (per `crackerjack-version-bumping-manual.md`); pre-Phase-4.3 verification checks `importlib.metadata.version('oneiric')` against the new release |
| 19 | **Per-worktree commits never land on `main` because the Bash classifier blocks `git update-ref` cross-worktree** (round-1 MAJOR): each per-repo commit block ends with `git commit` but never `git update-ref refs/heads/main <branch> && git push`; commits sit on detached branches and downstream tasks silently fail | high | Phase 4.5 mandates a separate "merge agent" dispatched to the **main checkout** (NOT the worktree) that runs the `git update-ref` + `git push` between per-repo conversion commits and the umbrella CI's run |
| 20 | **Inventory script hardcodes module paths that change in Phase 4.3** (round-1 MAJOR): `mahavishnu._main_cli` → `mahavishnu.main_cli` rename and `crackerjack.__main__` → `crackerjack.cli` move break the `entry_points` dict in `audit_cli_inventory.py` | medium | Task 0.1 reads entry-point targets from `importlib.metadata.entry_points(group="console_scripts")` instead of the hardcoded dict |
| 21 | **`_discover_apps()` at module load runs BEFORE test mocks can take effect** (round-1 MAJOR): `with patch("bodai.cli.entry_points", ...)` is too late; module-load has already called `_discover_apps(app)` with real entry points | medium | Task 5.1 makes `_discover_apps()` lazy — called explicitly inside `__main__.py` or gated behind `if __name__ == "__main__"`; the test constructs a fresh Typer app and calls `_discover_apps(test_app)` with the mock in place |
| 22 | **`entry_points(group=...)` requires Python 3.10+** (round-1 MAJOR): the 3.9 API is `entry_points().get(group, [])`; on 3.10+ it's `entry_points(group=...)` | low | Task 5.1 adds a version-check shim at the top of `bodai/cli.py`: if `sys.version_info < (3, 10)`, dispatch to the 3.9 API; otherwise use the 3.10+ API. Decision doc records the 3.10+ requirement |
| 23 | **`audit_cli_inventory.py --repo` test doesn't enforce spec's minimum command counts** (round-1 MAJOR): `>=50` for mahavishnu, `==0` for mcp-common | medium | Task 0.1's test asserts the minimum count for at least one known repo (`>= 50` for mahavishnu, `== 0` for mcp-common) |
| 24 | **No `--cov-fail-under=89` enforcement across 6 repos with new code** (round-1 MAJOR): a stub `_doctor_checks() → {}` would pass `pytest` but drop coverage below the 89% gate | medium | Phase 4.5 umbrella CI smoke loop adds `uv run pytest --cov=<pkg> --cov-fail-under=89` for each converting repo |
| 25 | **CHANGELOG.md precondition missing in repos that lack one** (round-1 MAJOR): `git add CHANGELOG.md` in every commit block fails if the file doesn't exist | high | Phase 0.0.5 audits each Core 7 repo and creates an empty `CHANGELOG.md` with `## [Unreleased]` header in any repo that lacks one |
| 26 | **Phase 2.2 gate is reactive (250-line budget), not preventive** (round-1 MAJOR): lives only in mahavishnu's `.git/hooks/pre-commit`; a developer adding `@app.command("foo")` in akosha bypasses the gate entirely | medium | Phase 2.2 installs the per-repo pre-commit hook in all 7 Core 7 repos via `mahavishnu index install-hooks .`; preventive gate asserts the new command is in the inventory before commit |
| 27 | **Quarterly staleness cadence is launchd/macOS-only** (round-1 MINOR): the 6 consumer repos may run on Linux CI; the launchd plist only fires on macOS | low | Phase 7.5 adds a `schedule: - cron: '0 9 25 */3 *'` GitHub Actions trigger to `bodai/.github/workflows/quarterly-staleness.yml`; launchd plist remains the operator's local-reminder surface |

## 9. Out of Scope (explicit non-goals)

*(See §3 Non-Goals — this section intentionally duplicated §3 was deleted per round-2 pattern-alignment review.)*

## 10. Cross-references

- **Decision doc**: `.claude/decisions/2026-08-25-bodai-cli-contract.md`
  (NEW, written in Phase 4.5; **also add a row to
  `.claude/decisions/README.md` index** per wire-up-contract policy)
- **Research baseline**: `docs/audit-inventory/2026-08-25-research-findings.md`
  (NEW — moves §11's research data out of the spec body. Phase 1
  inventory supersedes it. Link here when created in Phase 1)
- **Companion decision**: `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md` (env audit decisions)
- **`BODAI_REPO_REGISTRY.md`** — per-repo CLI surface summary (Phase 7.3)
- **`oneiric.shell` package** — `AdminShell` base class for admin shells
- **`mcp_common.cli.MCPServerCLIFactory`** — lifecycle handler source
- **`bodai/cli.py`** — existing meta-CLI; gains `_discover_apps()` in Phase 5
- **Umbrella CI job** (Phase 4 + Phase 5 demonstrables) — new
  GitHub Actions job in **`bodai/.github/workflows/umbrella-ci.yml`**
  (revised after round-1 review — was mahavishnu's `.github/workflows/`
  which had two structural defects: empty `${{ github.workspace }}/../`
  and `paths:` filter that never fires on sibling pushes). The
  workflow has 7 explicit `actions/checkout@v4` steps (one per Core 7
  repo), runs the per-repo smoke loop, and is gated on Phase 4.3
  conversions + Phase 5 entry-points.

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

## 12. Reviewer checklist (run before approving)

- [ ] **§1 Outcome** — each "Concrete signal" bullet is verifiable with the
  listed command in current state (no placeholders, no aspirational
  signals)
- [ ] **§2 Goals vs §3 Non-Goals** — no scope creep; each Goal maps to
  one or more Phase tasks
- [ ] **§5 phase dependencies** — Phase N's "Triggered from" matches
  Phase M's "Returns to / updates" (the dependency graph is
  bidirectional)
- [ ] **§5.0 phase index** — every phase appears in the index table;
  no orphan phases, no missing phases
- [ ] **§6 Required Code Changes** — each checkbox matches the
  corresponding Phase task (no contradictions; correct file paths)
- [ ] **§8 Risks** — each row has a concrete mitigation; no bare
  "low likelihood" entries
- [ ] **§10 Cross-references** — all referenced files exist or are
  marked as NEW with their target path
- [ ] **§7 Decision Rule** — every "done enough" item maps to a
  runnable CI gate (per-CI for the converted repo, umbrella CI for
  cross-component)
