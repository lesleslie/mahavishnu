---
status: built
role: canonical
date: 2026-09-10
last_reviewed: 2026-09-10
superseded_by: null
topic: plan-index-dhara
---

# Feature: Plan Index Dhara-canonical metadata layer

Status: **built**

## What this tracks

The lifecycle of the plan_index Dhara-canonical layer per
`docs/superpowers/specs/2026-09-10-plan-index-dhara-design.md`.

## State transitions

- **built** (this file) — code shipped, integration tests pass, but
  not yet deployed to production instances.
- **wired** — registered with the MCP server, available in FULL
  profile, smoke tests green.
- **adopted** — bodai-status / mahavishnu-status skills migrated;
  step 8 of the migration plan may execute.

## State — pick one

- [x] **built** (code merged, no callers wired)
- [ ] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

## Built (yes/no)

yes — `mahavishnu/plan_index/` ships `record.py`, `store.py`, `rebuild.py`,
`render.py`, `writer.py`, `health.py` with unit coverage under
`tests/unit/plan_index/`.

## Wired (yes/no)

no — the module is importable and exercised by tests, but no production
instance reads the Dhara-canonical index yet; `docs/plans/PLAN_INDEX.md`
is still produced by `scripts/regenerate_plan_index.py`.

## Trigger path

`PlanIndexRebuilder` (`mahavishnu.plan_index.rebuild`) scans the
filesystem and upserts through `PlanIndexStore`
(`mahavishnu.plan_index.store`); `mahavishnu.plan_index.render.render`
turns the stored records back into `docs/plans/PLAN_INDEX.md`.

## Integration point

Dhara key namespace `plan_index/*` (primary + status/topic secondary
indexes, 24h TTL) and the rendered artifact at `docs/plans/PLAN_INDEX.md`.

## End-to-end check

```bash
python scripts/audit_plan_index.py --repo-root .
```

Exits 0 when `PLAN_INDEX.md`, the filesystem, and — when
`--dhara-records` is supplied — the Dhara records agree.

## Drift detection

`scripts/audit_plan_index.py` performs the three-way consistency check.
Failures:

1. a path in `PLAN_INDEX.md` with no file on disk;
1. a frontmatter-bearing `.md` file missing from `PLAN_INDEX.md`;
1. a Dhara record missing from `PLAN_INDEX.md`.

Indexed paths with no Dhara record are reported as a warning, not a
failure — records carry a 24h TTL and the rendered artifact is allowed
to lag an expiry.

## Blocker

State is `built`: the MCP tools that expose the Dhara-canonical index are
not yet registered in the FULL profile, and the `bodai-status` /
`mahavishnu-status` skills still read the filesystem-scanned index. Until
both move, the layer has no production reader.

## Next action

Register the plan_index MCP tools and run the audit script in CI —
Core Eng, on the cut-over date.

## Step 8 gate

`scripts/check_step8_ready.py` prints `ready: yes` only when the cut-over
date plus 14 days has passed (and, when supplied, the jot sub-plan 3 ship
date plus 14 days) *and* this file's `status` is `adopted`.

## Related

- Plan: `docs/superpowers/specs/2026-09-10-plan-index-dhara-design.md`
- Audit evidence: `scripts/audit_plan_index.py`
- Gate: `scripts/check_step8_ready.py`
