---
status: active
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: lifecycle
---

# Checkpoint — DLQ Fail-Closed Wiring (2026-07-16)

**Date**: 2026-07-16
**Working directory**: `/Users/les/Projects/mahavishnu`
**Mode**: Explanatory + ultracode (xhigh + dynamic workflow orchestration)
**Why this file exists**: Session-Buddy MCP transport dropped mid-call on
`mcp__session-buddy__checkpoint` (recurring `-32000` / transport-dropped
defect — see `docs/followups/2026-07-15-pickup-bodai-hooks-and-sb-debug.md`).
This file is the durable fallback so the next session can resume without
losing this thread's context.

## Checkpoint Notes

- **Decision**: Exhaustive audit of all 8 `docs/followups/` files + adopt
  the `.claude/decisions/` lifecycle convention in `docs/followups/`
  (README index + `.archive/` on completion) + execute the **Full #3**
  DLQ fix end-to-end (Phases 1+2+3) per the approved plan
  `docs/plans/2026-07-16-dlq-fail-closed-wiring.md`.
- **Reason**: The 2026-06-29 "Resolved" notes for #3 (DLQ) and #4
  (opensearch) were both re-verified against current code; #3 was
  genuinely broken (flag inert, runtime write-failure still swallowed),
  #4 was moot (residual only in deprecated `workflow_state.py`).
  The lifecycle ask was to make `docs/followups/` consistent with
  `.claude/decisions/` so the two follow-up stores share an index +
  archive rule.
- **Files changed** (all staged, none committed):
  - **New**:
    - `mahavishnu/core/dlq_metrics.py` — `mahavishnu_dlq_fallback_total{outcome=...}`
    - `tests/unit/core/test_dlq_metrics.py` — 5 tests
    - `tests/unit/core/test_dlq_integration.py` — 3 tests (config propagation)
    - `tests/integration/core/test_dead_letter_queue_failover.py` — 2 tests
    - `docs/runbooks/dead-letter-queue.md` — operator runbook
    - `docs/followups/README.md` — index + lifecycle policy
    - `docs/plans/2026-07-16-dlq-fail-closed-wiring.md` — approved plan
    - `.claude/decisions/followups-lifecycle.md` — lifecycle policy
    - `~/.mahavishnu/fallback-queue/dlq-fail-closed-2026-07-16.json` — replay marker
  - **Modified**:
    - `mahavishnu/core/config.py` — `DLQConfig.max_size` added (fixes `dlq_max_size` misread)
    - `mahavishnu/core/dead_letter_queue.py` — fail-closed now real end-to-end; dead duplicate docstring removed
    - `mahavishnu/core/dlq_integration.py` — propagates flag + max_size from `MahavishnuSettings.dlq`
    - `mahavishnu/_main_cli.py` — comment clarifying heal-path DLQ is inert
    - `tests/unit/core/test_dead_letter_queue_fail_closed.py` — 2 new (runtime write-failure)
    - `docs/followups/2026-06-29-dlq-silent-fallback.md` — Status: Resolved (cited tests)
    - `docs/followups/2026-06-29-opensearch-diverged-flags.md` — Status: Resolved for live paths
    - `.claude/decisions/README.md` — new row for followups-lifecycle
    - `.claude/decisions/test-matrix-review-followups.md` — false "no follow-ups dir" claim corrected
    - `.gitignore` — scoped negation for `docs/followups/.archive/`
  - **Renamed** (rename `R` preserved):
    - `docs/followups/2026-06-29-dlq-silent-fallback.md` → `docs/followups/.archive/2026-06-29-dlq-silent-fallback.md`
  - **Deleted** (per user request):
    - `mahavishnu/core/config.py.backup` — stray backup; confirmed removed
- **Tests passing**: 16/16 across `test_dlq_integration.py` (3) +
  `test_dead_letter_queue_fail_closed.py` (6) + `test_dlq_metrics.py` (5)
  + `test_dead_letter_queue_failover.py` (2). `ruff check` clean on all
  touched files. No regressions in the broader
  `tests/unit/core/test_dead_letter_queue.py` suite.
- **Next step**: Commit the work (none done — per project policy) +
  promote `docs/plans/2026-07-16-dlq-fail-closed-wiring.md` from `draft`
  to `shipped` in `PLAN_INDEX.md`. Optional: address the unrelated
  pre-existing dirty entries (`.mcp.json`, `uv.lock`, `.superpowers/`,
  `.playwright-mcp/`, several `*.png`) that were already dirty before
  this session and were left untouched.
- **Blockers**: None. Mahavishnu worker backend was unavailable
  (MHV-007 mcpretentious-open timeout); execution proceeded in
  **degraded mode** with explicit user consent and a replay marker
  dropped for an operator to re-run through a real pool later. The
  audit trail (Dhara/Akosha/Grafana) is therefore missing for this
  work — the local tests + ruff are the only validation.
- **Cross-reference**: The unresolved 2026-07-15 thread (Session-Buddy
  transport drops + Bodai hook audit + stash-clobber fix) is still
  open. Its resolution doc
  (`docs/followups/2026-07-15-bodai-hooks-sb-debug-resolution.md`) was
  not created in this session. This checkpoint is independent of that
  thread — the DLQ work stands on its own.
