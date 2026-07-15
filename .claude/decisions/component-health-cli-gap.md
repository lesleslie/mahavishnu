# Component-Health CLI Gap

## Context

The Bodai ecosystem has two coexisting surfaces for "what is the
health of component X right now":

1. **`mcp__mahavishnu__ecosystem_status(sections=[...])`** — the canonical,
   cross-component health report. Defined by the unified
   `ecosystem_status` aggregator; produces a single schema-validated
   envelope with `services`, `adapters`, `capabilities`, `workflows`,
   `alerts`, and (optionally) `recommendations` sections.
2. **Per-component CLI tools** — `mahavishnu mcp status`,
   `mahavishnu mcp health`, `mahavishnu metrics bodai`, and a handful of
   `scripts/probe_*.py` scripts. These each hit one specific service or
   one specific data source and render a smaller, component-shaped view.

The two surfaces overlap. `ecosystem_status` already includes a
`services` section that lists every dependency with its `host`,
`port`, `status`, and per-section detail. CLI users still reach for
`mahavishnu mcp status` first because it is faster, narrower, and
prints to a terminal without JSON parsing.

This is a real gap, not a design flaw. `ecosystem_status` exists for
machine consumers (CI, alerting, dashboards); the per-component CLIs
exist for human operators. Both surfaces need to keep working.

## Decision rule

1. **`ecosystem_status` is the canonical source of truth.** Any
   per-component CLI that returns health information must treat the
   `services` section of `ecosystem_status` as authoritative and may
   only supplement it (e.g. with a process pid, queue depth, or
   subscriber-state file) — never contradict it. If a CLI and
   `ecosystem_status` disagree, the CLI must log a warning that names
   the disagreement so the operator knows which surface to trust.

1. **Per-component CLIs are compatibility wrappers.** They are kept
   because operators have muscle memory and because they expose
   surfaces `ecosystem_status` deliberately omits (queue depth,
   subscriber state files, drop counts). Do not delete them. Do not
   "promote" them to canonical — they will always be the secondary
   surface.

1. **New health features ship in `ecosystem_status` first.** When a
   component adds a new health dimension (e.g. ultracode's
   verification reject rate, routing-decision quota usage), the
   canonical `ecosystem_status` schema gets the field. A matching CLI
   subcommand may follow — and the metrics CLI subcommands added
   2026-07-15 (`verification`, `dispatch`) are the precedent — but the
   CLI must read from Dhara, not duplicate the aggregation logic.

1. **Future work: optional `--json` mode for `ecosystem_status`.**
   Today, `ecosystem_status` already returns JSON-shaped data via the
   MCP server's `output_schema`, but no CLI prints it. A future
   `mahavishnu ecosystem status --json` (in `mahavishnu/cli/`)
   would let humans pipe the canonical envelope into `jq`. Filed as
   an open gap; not blocking.

## Why the two surfaces are not interchangeable

- `ecosystem_status` is **schema-validated and machine-stable**. CI
  pipelines and Akosha's pattern detector parse its output; breaking
  the schema breaks downstream automation.
- Per-component CLIs are **operator-facing and tolerantly shaped**.
  They print to terminals in rich tables, accept convenience flags
  (`--queue-cap`, `--state-path`), and degrade gracefully when a
  single dependency is missing. They cannot be the canonical surface
  because every CLI caller has a different degradation tolerance.

## Status

Active. The 2026-07-15 metrics CLI additions (`verification`,
`dispatch`) follow this rule: they read Dhara and render summary
tables, never claim to be authoritative for component health. The
existing `mahavishnu metrics bodai` command predates this decision
but already complies (it reads from the local queue file and does not
contradict `ecosystem_status.services.akosha`).

## References

- `mahavishnu/mcp/tools/ecosystem_health_tools.py` — `ecosystem_status`
- `mahavishnu/metrics_cli.py` — `bodai`, `verification`, `dispatch`
- `mahavishnu/core/state_backends/dhara.py` — Dhara read path
- `.claude/decisions/bodai-observability-pattern.md` — single
  subscriber, single bus (related: do not build parallel observability
  surfaces)
