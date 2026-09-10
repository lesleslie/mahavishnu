---
name: tier2-math-deferred
status: deferred
date: 2026-09-10
last_reviewed: 2026-09-10
owner: bodai-orchestrator
role: deferred
---

# Feature: tier2-math-deferred

**Owner:** bodai-orchestrator
**Created:** 2026-09-10
**Last updated:** 2026-09-10
**Repo(s):** `/Users/les/Projects/mahavishnu`, `/Users/les/Projects/akosha`, `/Users/les/Projects/session-buddy`

## State — pick one

- [ ] **built** (code merged, no callers wired)
- [ ] **wired** (entry-point exists; integration contract executed end-to-end)
- [x] **deferred** (re-evaluation triggers documented; activation criteria written; no implementation work scheduled)

This entry tracks the three Tier 2 / Phase D initiatives deferred
from
[`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md):

| Sub-initiative | Trigger | Activation criteria |
|----------------|---------|---------------------|
| Optimal transport for Akosha pattern comparison | `akosha.patterns.cross_system_snapshot_count >= 10,000` over 30-day window | See [`docs/followups/2026-09-10-tier2-optimal-transport.md`](../followups/2026-09-10-tier2-optimal-transport.md) |
| Hyperbolic embeddings for Session-Buddy code graphs | `session_buddy.code_graph.node_count >= 10,000` AND coverage `>= 0.60` of indexed repos | See [`docs/followups/2026-09-10-tier2-hyperbolic-embeddings.md`](../followups/2026-09-10-tier2-hyperbolic-embeddings.md) |
| Cross-repo Phase D (Akosha detector wiring) | Tier 1 Phase 8 `adopted` AND `>= 1 week` of production operation | See [`docs/followups/2026-09-10-tier2-phase-d-cross-repo.md`](../followups/2026-09-10-tier2-phase-d-cross-repo.md) |
| Multi-metric drift detection (operational follow-on) | `>= 3` distinct metrics requested by operators in 30-day window | See [`docs/followups/2026-09-10-tier2-multi-metric-drift.md`](../followups/2026-09-10-tier2-multi-metric-drift.md) |

## Wiring checklist

- [x] Re-evaluation triggers documented (one per sub-initiative)
- [x] Trigger path identified: `scripts/feature_eligibility.py` (REQ-007)
- [x] Returns / state updates land in expected destination: `docs/followups/<trigger>.md` (status: `active` blocks exit-1)
- [x] End-to-end smoke check documented: `make tier2-eligibility` (top-level Makefile, wired in Phase 9)
- [x] Observability hook in place: monthly CI run via `make tier2-eligibility` is the recurring signal
- [x] Rollback signal defined: `--dry-run` flag for the script; `status: draft` flips a followup to non-blocking

## Built (yes/no)

yes (script + 4 followup docs + this tracking entry + Makefile target)

## Wired (yes/no)

yes (script wired to monthly CI via `make tier2-eligibility`; the
`feature_eligibility.py` script imports the trigger logic and is
importable as a Python module — `tests/unit/test_feature_eligibility.py`
exercises the trigger logic end-to-end)

## Trigger path

- `scripts/feature_eligibility.py` (entry point, run by CI)
- Data sources: `mcp__akosha__akosha_get_system_metrics`,
  `mcp__session-buddy__get_intelligence_stats`,
  `docs/feature-tracking/2026-09-10-observability-changepoint.md`
  frontmatter (Phase 8 status), `~/.mahavishnu/metric_requests.json`
  (operator metric requests via `mcp__mahavishnu__discover_tools`)
- Output: one-line-per-trigger status report; exit 1 when a
  trigger fires without a corresponding followup doc

## Integration point

- `docs/followups/<trigger>.md` (status field; flipped to
  `in_progress` when the Tier 2 plan opens)
- `docs/plans/PLAN_INDEX.md` (Tier 2 plan rows added when the
  trigger fires and the follow-on plan opens)

## End-to-end check

```bash
# Smoke: every trigger below threshold, no followups
python scripts/feature_eligibility.py --dry-run
# Expected: triggers_fired=0 followon_plans_missing=0; exit 0

# Mock: trigger fires, followup exists
echo '{"akosha_patterns_cross_system_snapshot_count": 50000}' > /tmp/feat.json
python scripts/feature_eligibility.py --mcp-config /tmp/feat.json
# Expected: optimal_transport: state=above fired=True ... exit 0
#          (because docs/followups/2026-09-10-tier2-optimal-transport.md exists with status: active)

# CI monthly: make tier2-eligibility
# Expected: same as above, exit 0 with all 4 followups present
```

## Blocker

Nothing is preventing these from staying `deferred` — by design.
The triggers in
[`scripts/feature_eligibility.py`](../../scripts/feature_eligibility.py)
are the activation mechanism. When a trigger fires, the Tier 2 plan
opens, this entry flips to `built` → `wired` → `adopted`.

## Next action

Wait for the next monthly CI run of `make tier2-eligibility`. If
any trigger fires, draft the corresponding Tier 2 plan (paths in
the table above) and update this entry to `built`.

## Related

- Plan: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) (Tier 1 §4.7, Phase 9)
- Eligibility script: [`scripts/feature_eligibility.py`](../../scripts/feature_eligibility.py)
- Followups: `docs/followups/2026-09-10-tier2-*.md`
- Top-level Makefile: `Makefile` (target: `tier2-eligibility`)

## Session-Buddy

- Reflection ID: (saved at Tier 1 promotion)
- Saved at: 2026-09-10
