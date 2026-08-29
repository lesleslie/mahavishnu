---
status: active
role: operational
date: 2026-08-25
last_reviewed: 2026-08-29
superseded_by: null
topic: bodai-cli-staleness-cadence
---

# Bodai CLI Staleness Cadence

## Decision

Per the 2026-08-25 audit, the Bodai CLI surface is inventoried quarterly
for staleness via `scripts/audit_cli_inventory.py all --check-stale`.

## Schedule

Every 90 days. Next due: 2026-11-25.

## Mechanism

A launchd plist at `~/Library/LaunchAgents/com.bodai.staleness-audit.plist`
runs:

```bash
cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_cli_inventory.py all --check-stale
```

Output is written to `docs/audit-inventory/staleness-<date>.log`.

## When staleness is detected

The cadence doc surfaces findings for review:

1. Run `uv run python scripts/audit_cli_inventory.py all --check-stale`
   and capture output to `docs/audit-inventory/staleness-<date>.log`.
2. If stale/deprecated commands exist, regenerate
   `docs/audit-inventory/findings-staleness.md` via the script in
   Plan Task 3.4.1.
3. For each finding: decide keep-as-deprecated, refactor, or delete.
   Track decisions in the staleness log footer.

## Why quarterly

The Core 7 CLIs change at a steady pace (Phase 4 added `OneiricCLIBase`,
Phase 5 added `bodai.apps`, every release touches `mahavishnu`). Quarterly
matches the natural release cadence without creating review churn.

## Validation

After every quarterly run, append a one-line summary to
`docs/audit-inventory/staleness-history.md`:
`<date>: <repos-swept>, <stale-count>, <new-count>`.