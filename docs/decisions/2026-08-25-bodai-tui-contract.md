---
status: active
role: canonical
date: 2026-08-25
last_reviewed: 2026-10-12
owner: les
topic: bodai-tui-contract
scope: bodai-tui-shell
purpose: capture the AdminShell reuse pattern, the bodai-TUI-as-aggregator pattern, and the per-component vs cross-component TUI split for the bodai/mahavishnu surfaces
superseded_by: null
---

# Bodai TUI Contract

## Context

The 2026-08-25 ultracode CLI audit split out Phase 6 (TUI verification +
polish) into its own plan: `docs/plans/2026-08-25-bodai-tui-shell-surface.md`.
The plan verifies three surfaces:

* `bodai shell` — IPython REPL pre-loaded with the Bodai ecosystem
  config + health probes + per-component variables.
* `bodai dashboard` — Textual TUI aggregating cross-component health.
* `mahavishnu monitor watch` — Textual TUI showing mahavishnu's
  internal pools and workers.

After Phase B-1 verification, three patterns emerged that need pinning
as decisions so future TUIs in the fleet don't drift.

## Decision rule

### Pattern 1 — AdminShell reuse (per-component IPython shells)

Every Core 7 component that exposes an IPython admin shell MUST
subclass `oneiric.shell.core.AdminShell` rather than rolling its own.
The base class provides:

* `IPython.terminal.embed.InteractiveShellEmbed` construction.
* `_build_namespace()`, `_register_magics()`, `_get_banner()` hooks
  subclasses override to pre-load their component's domain objects.
* The cross-shell UX standardization (uniform `--mode`, `--json`,
  `--confirm` flags) is Plan B future; do not preempt it.

`bodai shell` is the umbrella: it does NOT subclass AdminShell itself
(it aggregates across components) — instead it uses IPython's own
`start_ipython` and pre-loads `ecosystem`, `portmap`, `storage_map`,
`check_all()`, `check_component()`, and every registered component
name as a top-level variable. This is a thin convenience; deeper
component-specific shell context lives in each component's own
subclassed `AdminShell`.

### Pattern 2 — bodai-TUI-as-aggregator (cross-component Textual TUI)

`bodai dashboard` is a cross-component aggregator. It reads
`bodai.core.health.check_all()` (which fans out across all registered
ecosystem components) and renders a unified grid. It is NOT a wrapper
around per-component Textual apps.

This pattern decouples the aggregator's lifecycle from any single
component: adding a new Bodai component only requires it to register
in the ecosystem config; the dashboard picks it up automatically.

### Pattern 3 — per-component vs cross-component TUI split

| Surface | Scope | When to use |
|---------|-------|-------------|
| `bodai dashboard` | Cross-component (all 7+ registered) | Cross-system triage, "is anything red?" |
| `mahavishnu monitor watch` | mahavishnu-internal (pools + workers) | "What's mahavishnu doing right now?" |
| Per-component Textual apps (none yet — future) | Component-internal state | "Drill into ONE component" |

Today, only `bodai dashboard` (cross-component aggregator) and
`mahavishnu monitor watch` (mahavishnu-internal) exist. The 5 other
Core 7 components have IPython shells but no Textual TUIs.

**Rule**: a new Textual TUI must be one of these two scopes. Do not
build a Textual TUI that duplicates `bodai dashboard`'s cross-component
view inside a component, OR that duplicates `mahavishnu monitor`'s
internal pool view inside a higher-level orchestrator.

## Consequences

* Plan B (cross-shell UX standardization) can land later without
  rewriting the three surfaces — they're already split correctly.
* A new component joins `bodai dashboard` automatically via the
  ecosystem config; no dashboard code changes.
* `mahavishnu monitor watch` lives in `mahavishnu/cli/monitoring_cli.py`
  as `@app.command(name="watch")` (not `tui`); the command name
  reflects its role in the `monitor` namespace, not its UI paradigm.

## Status

Active. Last reviewed 2026-10-12 during the Phase B-1 polish pass.

## Cross-references

* Plan: `docs/plans/2026-08-25-bodai-tui-shell-surface.md`
* AdminShell base: `oneiric/oneiric/shell/core.py`
* `bodai shell` impl: `bodai/admin/shell.py`
* `bodai dashboard` impl: `bodai/tui/dashboard.py`
* `mahavishnu monitor watch` impl: `mahavishnu/cli/monitoring_cli.py`
* `mahavishnu` MonitorApp impl: `mahavishnu/tui/monitor_app.py`
* Canonical status vocabulary: `mahavishnu/core/ecosystem_status.py`
* Bodai health aggregator: `bodai/core/health.py::check_all()`
