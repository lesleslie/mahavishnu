---
status: adopted
role: canonical
date: 2026-09-10
last_reviewed: 2026-09-10
superseded_by: null
topic: plan-index-metadata
---

# Feature: Plan Index MCP-canonical metadata layer

Status: **adopted**

## What this tracks

The lifecycle of the plan_index MCP-canonical layer per
`docs/feature-tracking/plan-index-metadata.md`.

## State transitions

- **built** (this file) — code shipped, integration tests pass, but
  not yet deployed to production instances.
- **wired** — registered with the MCP server, available in FULL
  profile, smoke tests green.
- **adopted** — bodai-status / mahavishnu-status skills migrated;
  step 8 of the migration plan may execute.

## State — pick one

- [x] **built** (code merged, no callers wired)
- [x] **wired** (entry-point exists; integration contract executed end-to-end)
- [x] **adopted** (in active use by ≥1 user/workflow/agent)

## Built (yes/no)

yes — `mahavishnu/plan_index/` ships `record.py`, `store.py`, `rebuild.py`,
`render.py`, `writer.py`, `health.py` with unit coverage under
`tests/unit/plan_index/`.

## Wired (yes/no)

yes — the MCP tools exposing the MCP-canonical index are registered
in the FULL profile; smoke tests green; `docs/plans/PLAN_INDEX.md` is
produced by `mahavishnu/plan_index/render.py` from the durable key-value records.

## Trigger path

`PlanIndexRebuilder` (`mahavishnu.plan_index.rebuild`) scans the
filesystem and upserts through `PlanIndexStore`
(`mahavishnu.plan_index.store`); `mahavishnu.plan_index.render.render`
turns the stored records back into `docs/plans/PLAN_INDEX.md`.

## Integration point

Durable key-value namespace `plan_index/*` (primary + status/topic secondary
indexes, 24h TTL) and the rendered artifact at `docs/plans/PLAN_INDEX.md`.

## End-to-end check

```bash
python scripts/audit_plan_index.py --repo-root .
```

Exits 0 when `PLAN_INDEX.md`, the filesystem, and — when
`--mcp-records` is supplied — the durable key-value records agree.

## Drift detection

`scripts/audit_plan_index.py` performs the three-way consistency check.
Failures:

1. a path in `PLAN_INDEX.md` with no file on disk;
1. a frontmatter-bearing `.md` file missing from `PLAN_INDEX.md`;
1. a durable key-value record missing from `PLAN_INDEX.md`.

Indexed paths with no durable key-value record are reported as a warning, not a
failure — records carry a 24h TTL and the rendered artifact is allowed
to lag an expiry.

## Blocker

None at the adoption gate. Step 8 (full decommission of the legacy
filesystem-scanned index) is gated by `scripts/check_step8_ready.py`
and remains conditional on the cut-over + 14 day grace period.

## Next action

Step 8 (legacy index decommission) — gated by `scripts/check_step8_ready.py`
which returns `ready: yes` only after cut-over + 14d grace AND this file's
status is `adopted`.

## Step 8 gate

`scripts/check_step8_ready.py` prints `ready: yes` only when the cut-over
date plus 14 days has passed (and, when supplied, the jot sub-plan 3 ship
date plus 14 days) *and* this file's `status` is `adopted`.

## Related

- Plan: `docs/feature-tracking/plan-index-metadata.md`
- Audit evidence: `scripts/audit_plan_index.py`
- Gate: `scripts/check_step8_ready.py`
