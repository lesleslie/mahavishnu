---
name: tui
status: wired
date: 2026-07-26
last_reviewed: 2026-07-27
owner: mahavishnu
role: canonical
plan: docs/plans/2026-07-26-mahavishnu-acp-server.md
spec: docs/superpowers/specs/2026-07-15-mahavishnu-acp-server-design.md
related: docs/feature-tracking/worktree-autoremove.md
---

# In-House Textual TUI — feature tracking

## State: wired

Code is merged and ships as the `mahavishnu` optional `[tui]` extra
(`textual>=8.2.7` per `pyproject.toml:153-156`). Two entry points are wired in
the CLI:

- `mahavishnu dashboard` → `DashboardApp` (`mahavishnu/tui/app.py`)
- `mahavishnu monitor watch` → `MonitorApp` (`mahavishnu/tui/monitor_app.py`)
  with a real `_DefaultMonitorDataProvider` (not no-op)

The four blocking defects from the 2026-07-26 audit all landed on
2026-07-27 (see Wired section below). The TUI is now honestly
"wired" — entry points register, integration contracts execute
end-to-end at least once, observability hooks are in place.

The companion `mahavishnu shell` (`mahavishnu/shell/`) is a separate
IPython REPL and is not tracked here.

## Built

- New `mahavishnu/tui/` package: `__init__.py`, `app.py`, `monitor_app.py`,
  `widgets.py`, `command_palette.py`
- New `DashboardApp` with 12 tabs (Overview / Sweep / Routing / Alerts /
  Reviews / Session / Recovery / Approvals / Files / Events / Agno / Trace)
  and 30s auto-refresh (`R` to force)
- New `MonitorApp` for 5s pool/worker monitoring
- New `Ctrl+K` command palette (12 default commands, optional provider)
- Approve/reject keystrokes (`a`/`x`) wired through a forwarder in
  `app.py:901-971` (so the dashboard is not fully read-only)
- Optional dependency group `tui` in `pyproject.toml:153-156` (PEP 735)
- ~126 TUI-related tests across
  `tests/unit/test_tui_dashboard.py`, `test_command_palette.py`,
  `tui/test_tui_availability.py`, plus 2 in `test_bodai_phase1a_regression.py`

## Wired (all four defects closed, 2026-07-27)

The four blocking defects from the 2026-07-26 audit all landed on
2026-07-27. The TUI is now honestly "wired" — entry points register,
integration contracts execute end-to-end at least once, observability
hooks are in place, and the rollback signals are defined.

1. **Install-instruction drift — FIXED.** All three sites unified to
   `uv sync --group tui` / `uv add --group tui textual` (the PEP 735
   group form, which is what `pyproject.toml:153-156` declares):
   - `mahavishnu/_main_cli.py:1934` — now `uv sync --group tui`
   - `mahavishnu/tui/monitor_app.py:84-85` — now `uv add --group tui textual`
   - `mahavishnu/cli/monitoring_cli.py:231` — now `uv add --group tui textual`

2. **Docstring rot — FIXED.** `mahavishnu/tui/app.py:3` now says
   "Twelve tabs:" (was "Eleven tabs:"). The docstring matches the
   enumerated 12-tab list at `:4-15`.

3. **Stale CLI help — FIXED.** `mahavishnu/_main_cli.py:1924-1926` now
   reads "Provides twelve screens: Overview, Sweep, Routing, Alerts,
   Reviews, Session, Recovery, Approvals, Files, Events, Agno, Trace."
   Matches the actual 12-tab render surface.

4. **Untested monitor + dead module — FIXED.**
   - `tests/unit/tui/test_tui_availability.py` extended with three
     new tests: `test_default_monitor_data_provider_returns_lists`,
     `test_monitor_app_constructor_accepts_data_provider`, and
     `test_monitor_app_action_refresh_with_mock_provider`
   - `mahavishnu monitor watch` (`cli/monitoring_cli.py:220-235`) now
     passes `_DefaultMonitorDataProvider()` to `MonitorApp(...)`,
     so the 5s refresh loop populates the pool/worker containers
     with at least an aggregate row (better than empty)
   - `mahavishnu/core/task_dashboard.py` and
     `tests/unit/test_task_dashboard.py` deleted via `git rm` (the
     module had no production wiring and 485 lines of stale tests;
     the only other importers of `task_dashboard` were worktree
     copies, not live code)
   - `mahavishnu/tui/command_palette.py:326-327` no longer raises on
     no-action commands; logs at `level=info` and returns `None`
     (commands without actions are informational placeholders)

## Adopted (NOT YET)

- Operator has run `mahavishnu dashboard` against a live session-buddy /
  pool / dhara and used the command palette to perform a real action
  (approve a pending approval, drill into a recovery checkpoint, etc.)
- Operator has run `mahavishnu monitor watch` and observed a live
  pool/worker feed (not the one-shot metrics fallback)
- At least one Toad / ACP client integration is documented as a follow-on
  to the ACP server build (so the TUI either becomes the recommended
  client OR is formally retired in favor of Toad)

## Toad decision (gate to `adopted`)

The TUI's relationship to Toad is intentionally deferred per three prior
plans (2026-06-19 Track3, 2026-06-19 External Integrations, 2026-07-15
Constellation). The `docs/plans/2026-07-26-mahavishnu-acp-server.md` build
plan (companion) is the prerequisite for a real comparison: once ACP exists
in Mahavishnu, Toad can drive it directly, and the question becomes
"keep our Textual TUI, replace it with Toad, or run them side-by-side"
rather than the current "we have neither" state.

## Blocker

None. The TUI is wired and ready for the operator trial that flips
it to `adopted`. The Toad decision (deferred per three prior plans)
is gated on the ACP server build (`docs/plans/2026-07-26-mahavishnu-acp-server.md`,
now `active`); that gate is unblocked but not yet shipped.

## Next action

- [ ] Schedule a 1-week operator trial: `mahavishnu dashboard` +
  `mahavishnu monitor watch` against a real session-buddy / pool / dhara
- [ ] Run the new test suite (`pytest tests/unit/tui/ -v`) and confirm
  the new tests pass on the operator's environment (textual installed)
- [ ] After the trial + the ACP server build ships, make the Toad
  decision and flip to `adopted`

## Related

- Spec: `docs/superpowers/specs/2026-07-15-mahavishnu-acp-server-design.md`
  (the prerequisite for the Toad decision)
- Plan: `docs/plans/2026-07-26-mahavishnu-acp-server.md` (companion, in
  construction)
- Defer history: `docs/superpowers/plans/2026-06-19-track3-toad-tui.md`
  (draft), `docs/superpowers/specs/2026-06-19-external-integrations-design.md:324-380`
  (Toad ACP deferred), `docs/superpowers/specs/2026-07-15-constellation-tui-design.md:10-16,41-47`
  and `docs/superpowers/plans/2026-07-15-constellation-tui.md:59-63`
  (Track2 Toad/ACP out of scope)
- Sibling feature tracker: `docs/feature-tracking/worktree-autoremove.md`
  (newer YAML-frontmatter style; this file mirrors it)

## Session-Buddy

- Reflection ID: <to be filled by `mcp__session-buddy__store_reflection`>
- Saved at: <ISO timestamp>
