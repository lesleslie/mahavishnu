---
status: active
role: implementation
date: 2026-08-25
last_reviewed: 2026-08-25
owner: les
topic: bodai-tui-shell-surface
scope: bodai-tui-shell
purpose: verify and polish the bodai shell + dashboard TUIs and the mahavishnu monitor --tui; standardize the AdminShell subclass pattern across Core 7
superseded_by: null
---

# Bodai TUI & Admin Shell Surface

## What & Why (for the human reviewer)

**Goal**: the `bodai shell` IPython REPL, the `bodai dashboard` Textual
TUI, and the `mahavishnu monitor --tui` command all work end-to-end.
The `AdminShell` base class (in `oneiric`) is the foundation that all
five per-repo admin shells build on; this plan ensures the bodai-level
TUIs reuse the same pattern instead of duplicating it.

**Origin**: Phase 6 of the 2026-08-25 ultracode CLI audit, split out
into its own plan for focused review. Phase 6 was originally bundled
with the CLI standardization plan
(`docs/plans/2026-08-25-bodai-cli-audit.md`) but its scope (TUI
verification + AdminShell reuse) is distinct from the CLI command
audit work.

**Companion plan**: CLI command standardization lives in
`docs/plans/2026-08-25-bodai-cli-audit.md` (Plan A). This plan
**assumes Plan A's `BodaiCLIBase` foundation is in place** — Phase 4
of Plan A converts each Core 7 to `BodaiCLIBase`, which makes the
monitoring_cli integration straightforward.

**Read order** (pick one):
- **5 min skim**: §1 Outcome + §3 Non-Goals + §5 phases
- **20 min review**: above + §6 Required Code Changes
- **60 min deep read**: everything; cross-check §4 findings against
  the actual repo state via `grep`

---

## 1. Outcome

User-observable change: `bodai shell` opens a real IPython REPL with
the Bodai ecosystem (7 Core 7 components, ecosystem config, portmap,
storage map) pre-loaded; `bodai dashboard` opens a Textual TUI showing
a live grid of all 7 components with health, role, and port columns;
`mahavishnu monitor --tui` opens a separate Textual TUI showing
mahavishnu's pools and workers.

Concrete signal:

- `pip install -e bodai && python -c "from bodai.admin.shell import launch_shell"` exits 0
- `python -c "from bodai.tui.dashboard import BodaiDashboard"` exits 0
- `bodai shell` opens IPython REPL with namespace containing `app`, `oneiric`, `ecosystem`, `portmap`, `storage_map`, all 7 sub-CLIs (where installed)
- `bodai dashboard` opens Textual TUI; refreshes every 2-5s; shows health of all 7 components
- `mahavishnu monitor --tui` opens Textual TUI; refreshes every 5s; shows pools + workers
- The defensive `try/except ImportError` in `bodai/cli.py` is removed; real import errors surface loudly
- `git grep -l 'Shell not yet implemented' docs/` returns zero (the "stub" message is gone)

## 2. Goals

1. **Verify `bodai shell`** opens an IPython REPL end-to-end (the
   `launch_shell()` implementation already exists in `bodai/admin/shell.py`
   per 2026-08-25 verification; the work is smoke-testing + namespace
   review).
2. **Verify `bodai dashboard`** opens a Textual TUI showing all 7
   components (the `BodaiDashboard` implementation already exists in
   `bodai/tui/dashboard.py`; the work is smoke-testing + layout review).
3. **Wire `mahavishnu monitor --tui`** if not already wired (the
   `MonitorApp` Textual app exists in `mahavishnu/tui/monitor_app.py`;
   the CLI command that invokes it may be missing).
4. **Remove the defensive `try/except ImportError`** in `bodai/cli.py`
   for `shell` and `dashboard` commands — once verified, the catch
   hides real import errors and prints the misleading "not yet
   implemented" message.
5. **Document the "Bodai TUI contract"** in
   `.claude/decisions/2026-08-25-bodai-tui-contract.md` describing
   the `AdminShell` reuse pattern, the bodai-TUI-as-aggregator
   pattern, and the per-component-vs-cross-component TUI split.
6. **Cross-shell UX standardization** (future phase): align flag
   conventions across the 5 per-repo shells (`oneiric shell`,
   `dhara admin --confirm`, `akosha shell --mode --verbose`,
   `mahavishnu shell` config-gated). Out of scope for this plan;
   tracked as Plan B future.

## 3. Non-Goals

- **Adding NEW TUIs** to Core 7 repos that don't already have one
  (mcp-common stays library-only). The 5 existing shells (oneiric,
  dhara, session-buddy, akosha, mahavishnu) are verified; no new
  shell is created for crackerjack (its `crackerjack shell` already
  exists).
- **Replacing any TUI implementation** (e.g., rewriting
  `mahavishnu/tui/monitor_app.py` from Textual to a different
  framework). Pure verification + polish, not implementation.
- **Adding `bodai` sub-CLIs** (the umbrella composition is Plan A
  Phase 5; this plan only verifies `bodai shell` and `bodai dashboard`).
- **Replacing the `mahavishnu monitor` rich-based wizard** (the
  `--interactive` flag) — it's a different feature from the
  `monitor_app` Textual TUI; both coexist.

## 4. Current Findings (TUI-focused)

The 2026-08-25 research and audit surfaced these TUI/admin-shell findings:

### 4.1 Process-discipline findings (TUI)

| Finding | Severity |
|---|---|
| `bodai/admin/shell.py` and `bodai/tui/dashboard.py` **already exist** with full implementations; the `try/except ImportError` in `bodai/cli.py` is defensive safety, not evidence of missing code. Phase 6 work is verification + polish, not implementation. | high (misframed) |
| `mahavishnu monitor --tui` command that invokes `MonitorApp` may not be wired (verify). | medium |
| The `AdminShell` base class (in `oneiric/shell/core.py`) is the foundation for all 5 per-repo shells (`OneiricShell`, `DharaShell`, `SessionBuddyShell`, `AkoshaShell`, `MahavishnuShell`). The `bodai shell` should reuse this pattern (extend `AdminShell`, not roll its own). | medium |
| Defensive `try/except ImportError` in `bodai/cli.py` prints "Shell not yet implemented" / "TUI not yet implemented" — misleading once modules are verified importable. | medium |
| The dual TUIs (bodai's aggregator + mahavishnu's monitor) have different scopes; both are needed but the spec is unclear about who shows what. Decided 2026-08-25: `bodai dashboard` = cross-component aggregator; `mahavishnu monitor --tui` = mahavishnu-internal pools/workers. | drift |

### 4.2 UX inconsistencies

The 5 per-repo shells have different flag conventions:

- `oneiric shell` — no flags
- `dhara admin --confirm` — confirmation gate
- `akosha shell --mode --verbose` — operational mode
- `crackerjack shell` — no flags
- `mahavishnu shell` — config-gated by `shell_enabled: bool`

These inconsistencies are NOT in scope for this plan (Plan A's
`BodaiCLIBase` standardizes the OUTER CLI surface; the inner admin
shell is a different surface). Tracked as Plan B future.

## 5. Implementation Phase

### Phase B-1 — Verify & polish the three TUI surfaces

**Goal**: `bodai shell`, `bodai dashboard`, `mahavishnu monitor --tui`
all work end-to-end. The implementations already exist (verified
2026-08-25); this phase verifies, wires missing command (if any),
and removes the defensive try/except.

**Tasks:**

- B-1.1 — Verify `from bodai.admin.shell import launch_shell` succeeds
  in a fresh `bodai` install (verified 2026-08-25 in editable install:
  imports OK). If anything in the dependency chain fails, add the
  missing imports to `bodai/pyproject.toml`.
- B-1.2 — Verify `from bodai.tui.dashboard import BodaiDashboard`
  succeeds and `bodai dashboard` launches the TUI in a smoke test.
  Refine the cross-component aggregator as needed (uses
  `bodai.core.health.check_all()` + canonical status types from
  `mahavishnu/core/ecosystem_status.py`).
- B-1.3 — Wire `mahavishnu monitor --tui` pointing at
  `mahavishnu/tui/monitor_app.py`. If no CLI command currently invokes
  `MonitorApp`, register it via `@monitoring_cli.app.command("tui")`
  in `mahavishnu/cli/monitoring_cli.py`. Naming convention: the
  command is `tui` (the `monitor` namespace already exists).
- B-1.4 — **Remove the defensive `try/except`** in `bodai/cli.py` once
  the modules are verified importable. The current
  `except ImportError: ... "Shell not yet implemented"` pattern hides
  real import errors. Replace with a **friendly error** that
  preserves real-error visibility while giving the user a fix:
  ```python
  try:
      from bodai.admin.shell import launch_shell
  except ImportError as e:
      console.print(f"[red]bodai shell requires ipython: {e}[/red]")
      console.print("[yellow]Install with: uv pip install 'bodai[shell]' or 'uv pip install ipython'[/yellow]")
      raise typer.Exit(1)
  ```
  Same pattern for `bodai dashboard` (`bodai/tui/dashboard.py`).
  This preserves the spirit of "real error visibility" while giving
  fresh-install users an actionable fix (without the message, they
  see a stack trace and have to google it).
- B-1.5 — Tests:
  - `bodai/tests/test_shell.py::test_launch_shell_invokes_ipython_with_namespace`
    — patch `IPython.terminal.embed.InteractiveShellEmbed`, assert
    it's called with a namespace containing `from oneiric.shell import ...`.
  - `bodai/tests/test_dashboard.py::test_dashboard_renders_with_mock_check_all`
    — patch `bodai.core.health.check_all`, run `BodaiDashboard().run(test_mode=True)`
    or use Textual's `Pilot` harness.
  - `mahavishnu/tests/cli/test_monitor_tui.py::test_monitor_tui_invokes_monitor_app`
    — patch `MonitorApp.run`, assert it's invoked by `@monitoring_cli.app`
    registered as `tui`.

**Integration Contract (Phase B-1):**

- **Triggered from**: Plan A's Phase 5 completed (BodaiCLIBase
  foundation in place; `monitoring_cli.py` is using the base class).
- **Returns to / updates**: 1-2 verification commits (no new modules);
  1 commit to wire `mahavishnu monitor --tui`; 1 commit to remove
  the defensive try/except; 1 test commit.
- **Demonstrable by**:
  - `pytest bodai/tests/test_shell.py` passes (per-CI).
  - `pytest bodai/tests/test_dashboard.py` passes (per-CI; uses
    Textual `Pilot` harness — does NOT require a real TTY).
  - `pytest mahavishnu/tests/cli/test_monitor_tui.py` passes
    (per-CI; mocks `MonitorApp.run`).
  - **Manual smoke test** (release checklist, NOT CI): launch
    `bodai shell` / `bodai dashboard` / `mahavishnu monitor --tui`
    on a workstation with all packages installed; verify they
    open and respond to Ctrl+C.
- **Rollback signal**: any of the 3 per-CI pytest tests exits
  non-zero → block merge; smoke-test failures → release-block.
- **Observability added**: the previously-stubbed commands now
  have real backing code; `try/except` removed so real failures
  surface loudly; both TUIs observable as separate
  cross-component vs component-scoped surfaces.

## 6. Required Code Changes

- [ ] `/Users/les/Projects/bodai/bodai/cli.py` (modify — remove defensive
  `try/except ImportError` for `shell` and `dashboard` once modules
  verify)
- [ ] `/Users/les/Projects/mahavishnu/mahavishnu/cli/monitoring_cli.py`
  (modify — add `@app.command("tui")` if missing; must land AFTER
  Plan A Phase 3.2.5's parallel-files consolidation)
- [ ] `/Users/les/Projects/bodai/tests/test_shell.py` (NEW)
- [ ] `/Users/les/Projects/bodai/tests/test_dashboard.py` (NEW)
- [ ] `/Users/les/Projects/mahavishnu/tests/cli/test_monitor_tui.py` (NEW)
- [ ] `/Users/les/Projects/mahavishnu/.claude/decisions/2026-08-25-bodai-tui-contract.md`
  (NEW — documents the AdminShell reuse pattern, the
  bodai-TUI-as-aggregator pattern, and the per-component vs
  cross-component split. **Also add a row to
  `.claude/decisions/README.md` index**)
- [ ] `/Users/les/Projects/bodai/README.md` (modify — document
  `bodai shell` and `bodai dashboard`)
- [ ] `/Users/les/Projects/mahavishnu/README.md` (modify — document
  `mahavishnu monitor --tui`)

## 7. Decision Rule

This plan is **done enough** when:

1. `pytest bodai/tests/test_shell.py` passes
2. `pytest bodai/tests/test_dashboard.py` passes
3. `pytest mahavishnu/tests/cli/test_monitor_tui.py` passes
4. `bodai shell` opens a real IPython REPL on manual smoke test
5. `bodai dashboard` opens a live cross-component Textual grid on
   manual smoke test
6. `mahavishnu monitor --tui` opens mahavishnu's pool/worker view on
   manual smoke test
7. The defensive `try/except ImportError` is removed from
   `bodai/cli.py` for both `shell` and `dashboard`
8. `.claude/decisions/2026-08-25-bodai-tui-contract.md` is committed
   AND indexed in `.claude/decisions/README.md`

## 8. Risks

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| 1 | `bodai shell` import fails on systems where `ipython` isn't installed (`from IPython.terminal.embed import InteractiveShellEmbed` is lazy-imported inside `AdminShell.start()` but `from oneiric.shell import AdminShell` is eager) | low | bodai `pyproject.toml` declares `ipython>=8.0.0` as runtime dep; the new direct call surfaces real `ImportError` tracebacks (better UX than the misleading "not implemented" message). Document install command in error. |
| 2 | TUI smoke tests are interactive (CI is non-interactive). The per-CI pytest tests use mocks/Pilot, but the real TUIs are untested in CI. | medium | release-block smoke test (manual or via Xvfb); document in release checklist. NOT a CI gate (real TUIs need real terminals). |
| 3 | `mahavishnu/cli/monitoring_cli.py` may be consolidated in Plan A Phase 3.2.5 (parallel-files drift). Phase B-1.3 must land AFTER 3.2.5, not before. | medium | §5 explicitly notes this dependency; release plan sequences phases. |
| 4 | Removing defensive `try/except ImportError` regresses users who install bodai without optional deps | low | bodai's `pyproject.toml` declares `ipython` as runtime, not optional; users who strip it deliberately accept the consequence. The traceback tells them why. |
| 5 | Textual `Pilot` harness may not fully simulate real TUI rendering | medium | per-CI test verifies the call signature and namespace; full render verification is smoke-test only. |

## 9. Cross-references

- **Companion plan**: `docs/plans/2026-08-25-bodai-cli-audit.md` (Plan A).
  Phase B-1 depends on Plan A's Phase 5 (BodaiCLIBase foundation +
  `monitoring_cli.py` consolidation complete).
- **Decision doc** (NEW, Phase B-1 deliverable):
  `.claude/decisions/2026-08-25-bodai-tui-contract.md`
- **AdminShell base class**: `oneiric/oneiric/shell/core.py::AdminShell`
  (already provides `IPython.terminal.embed.InteractiveShellEmbed`
  construction; subclasses override `_build_namespace`,
  `_register_magics`, `_get_banner`)
- **bodai shell implementation** (verify): `bodai/admin/shell.py`
- **bodai dashboard implementation** (verify):
  `bodai/tui/dashboard.py`
- **mahavishnu TUI implementation** (verify):
  `mahavishnu/tui/monitor_app.py::MonitorApp`
- **Canonical status vocabulary**:
  `mahavishnu/core/ecosystem_status.py::CanonicalStatus` (the
  cross-component status types used in `bodai dashboard`)
- **bodai health aggregation**: `bodai/core/health.py::check_all()`
  (powers `bodai dashboard`'s row data)

## 10. Future Phases (out of scope for this plan)

These are tracked as follow-up work; not delivered in this plan.

### Phase B-2 — Cross-shell UX standardization

- Standardize flag conventions across the 5 per-repo shells:
  - `--confirm` gate where appropriate (currently only `dhara admin`)
  - `--mode lite|standard|full` consistently (currently only
    `akosha shell`)
  - `--json` output mode (uniform across all shells)
- Align magic command naming:
  - `%status` (oneiric) vs `%ps/top/errors` (mahavishnu) — pick one
- Add `AkoshaShell` magics (currently akosha has none; the other
  4 shells inherit from oneiric which provides `%help_shell`,
  `%status`)

### Phase B-3 — Implement akosha stub commands

- The 5 akosha IPython namespace stubs (`aggregate`, `search`,
  `detect`, `graph`, `trends`) currently return placeholder TODOs.
- Either implement them against real adapters or deprecate with
  a clear "alpha" gate (Plan A Phase 3.2.1 handles the gate).

### Phase B-4 — bodai shell with cross-component CLI mount

- Extend the `bodai shell` IPython REPL to pre-import all 7
  Core 7 sub-CLIs (currently it pre-imports `ecosystem`, `portmap`,
  `storage_map`, but not `akosha_app`, `mahavishnu_app`, etc.)
- This lets a user type `akosha_app.shell()` from inside `bodai shell`
  to drop into the akosha shell programmatically.

### Phase B-5 — bodai dashboard real-time event stream

- Wire the dashboard to Session-Buddy's session-event stream so
  recent activity (last N events) shows as a sidebar panel.
- Currently the dashboard only shows check_all() snapshots; adding
  event-stream makes it a true live monitor.

## 11. Reviewer checklist (run before approving)

- [ ] **§1 Outcome** — each "Concrete signal" bullet is verifiable with
  the listed command in current state
- [ ] **§3 Non-Goals** — no scope creep from §2
- [ ] **§5 Phase B-1** — depends on Plan A Phase 5; coordination
  explicit
- [ ] **§6 Required Code Changes** — each checkbox matches Phase B-1
  task; correct file paths
- [ ] **§8 Risks** — each row has concrete mitigation
- [ ] **§10 Cross-references** — all referenced files exist or are
  marked as NEW with their target path
- [ ] **§7 Decision Rule** — every "done enough" item maps to a
  runnable gate (per-CI for mock-based tests, manual smoke for
  real TUIs)
