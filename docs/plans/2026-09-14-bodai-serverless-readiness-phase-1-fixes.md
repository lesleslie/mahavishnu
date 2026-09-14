---
status: active
role: implementation
topic: serverless-readiness-precondition-fixes
date: 2026-09-14
last_reviewed: 2026-09-14
superseded_by: null
blocks_on:
  - docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md
related:
  - docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md
  - docs/adr/017-oneiric-shared-persistence-substrate.md
  - docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md
  - .claude/decisions/wire-up-contract.md
---

# Phase-1 Precondition Fixes — Serverless-Readiness Plan

**Date:** 2026-09-14
**Author:** Claude (post-promotion reviewer synthesis)
**Status:** `active`, `implementation` (precondition for Phase 4-8 execution of parent plan)

## Context

The serverless-readiness plan (`docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md`,
status: `active`) was promoted from `draft` after a 9-reviewer fanout
(8 pre-promotion + 1 architecture-council + 1 general-purpose
fresh-eyes). The two post-promotion reviewers returned 22 findings
(Appendix F of the parent plan); the user paused implementation
2026-09-14 and chose to roll 14 of them (8 MUST-FIX + 6 SHOULD-FIX)
into this precondition plan.

The remaining 8 (DELETE-CANDIDATE + MISSING) are deferred to
implementation-time or future plans. See parent plan Appendix F for
the full deferred list and rationale.

**Scope:** This plan addresses the 14 deferred findings in 4 phases.
**Out of scope:** Implementation of the parent plan's Phases 1-10
(which are unblocked by completing this plan's Phase A; partially
unblocked by Phase B; fully unblocked by Phase C+D).

**Effort:** ~4-6 hours. All 14 items are text edits, citations, or
small file additions. No new code paths.

## Why this is a precondition, not follow-up

The deferred findings are not "nice-to-haves." F.1.5 (add Phase 4 + 8
to never-cut list) directly affects whether the executor makes the
right call under scope pressure. F.1.8 (ADR 017 citation drift)
embeds a governance bug in a governance doc — exactly the failure
mode the parent plan's Rev-9 was supposed to prevent. Implementing
parent-plan Phase 4 or 8 without these fixes means the implementer
operates from a plan that contradicts itself.

## Phase A — Citation & cross-reference fixes (~1 hour)

**Goal:** Eliminate file:line citation drift before implementation
starts. These are the cheapest, highest-leverage items.

**Tasks:** REQ-FIX-A-001, REQ-FIX-A-002, REQ-FIX-A-003, REQ-FIX-A-004.

### REQ-FIX-A-001: §5 Phase 3 task list cleanup

**File:** `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md`

**Problem:** §5 Phase 3 task list still includes `REQ-ONEIRIC-MIRROR`
and `REQ-ONEIRIC-REPLICATOR` which §Rev-4 marks as `Closed` (superseded
by vendor CLIs per Rev-2). An implementer reading §5 will try to
build them.

**Fix:** Delete the two REQ entries from §5 Phase 3's task list
(retain them in §4.5 with status `Closed` for audit trail). Add
inline note: "REQ-ONEIRIC-MIRROR and REQ-ONEIRIC-REPLICOR are Closed
per §Rev-4; vendor CLIs handle sync (see `docs/ops/state-sync.md`)."

**Demonstrable by:** `grep -c "REQ-ONEIRIC-MIRROR\|REQ-ONEIRIC-REPLICATOR" <plan>` returns 0 occurrences in §5 task list.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.1.1
- **Returns to / updates:** Parent plan §5 Phase 3 task list
- **Rollback signal:** N/A (text edit)
- **Observability added:** Inline cross-reference to §Rev-4

### REQ-FIX-A-002: ADR 017 citation drift correction

**File:** `docs/adr/017-oneiric-shared-persistence-substrate.md`

**Problem:** Context section cites "line 1319 and 8 other direct dhara
package imports" in `mahavishnu/ingesters/otel_ingester.py`. §6 of the
parent plan cites lines 41, 289, 359 in that file (3 sites, not 1+8).
This is the exact bug Rev-9 was supposed to fix — embedding drift in
a new governance doc.

**Fix:** Either (a) verify the 1+8 claim via `grep -rn "from dhara" mahavishnu/ingesters/otel_ingester.py` and update with actual line numbers, or (b) drop the specific line numbers and replace with a `grep`-based verification command. **Prefer (a)** — exact citations are more useful.

**Demonstrable by:** Either (a) the new line numbers match `grep -n "from dhara\|from akosha" mahavishnu/ingesters/otel_ingester.py` output, or (b) the citation is replaced with a grep command.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.1.8
- **Returns to / updates:** ADR 017 Context section
- **Rollback signal:** N/A
- **Observability added:** N/A

### REQ-FIX-A-003: ADR 013 amendment cross-reference

**File:** `docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md`

**Problem:** Amendment (added 2026-09-14 in commit `0f1b4c0f`) notes
"ADR-013's Postgres-only assumption no longer holds" but doesn't
cross-reference the parent storage-consolidation plan
(`docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md`).

**Fix:** Add cross-reference paragraph in the Amendment section
pointing to the parent plan and stating "ADR-013 originally covered
the local-disk → single-Postgres path documented in this plan;
Phase 5 of the serverless-readiness plan extends that substrate
through Oneiric adapter selection."

**Demonstrable by:** `grep -c "2026-04-02-storage-consolidation" docs/adr/013-*.md` returns ≥1.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.2.2
- **Returns to / updates:** ADR 013 Amendment section
- **Rollback signal:** N/A
- **Observability added:** N/A

### REQ-FIX-A-004: Cut ordering rationale

**File:** `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md` §9 Risks

**Problem:** §9 ranks cut-order (Phase 7 → Neon → cache-snapshot) but
doesn't justify the ranking. Reviewer flagged this as ambiguous.

**Fix:** Add one-line rationale per cut candidate:
- Phase 7 (LangGraph): gated on external CVE situation; can wait indefinitely
- REQ-ONEIRIC-NEON: blocks write-heavy workloads (KV layer per REQ-MAHAVISHNU-KV); cut only if Phase 5 has alternative
- REQ-ONEIRIC-CACHE-SNAPSHOT: pure optimization; never critical-path

**Demonstrable by:** `grep -A 3 "Cut first" docs/plans/2026-09-14-...md` shows three rationale lines.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.2.4
- **Returns to / updates:** Parent plan §9 Risks
- **Rollback signal:** N/A
- **Observability added:** N/A

### Phase A exit criteria

- All 4 REQs landed
- `grep -c "REQ-ONEIRIC-MIRROR" <plan>` in §5 task list returns 0
- ADR 017 Context section either matches actual grep output OR uses grep command

## Phase B — Governance & process hardening (~1.5 hours)

**Goal:** Tighten the governance layer so future plans inherit
stricter audit invariants. This phase makes the plan robust to the
exact class of bug Rev-9 flagged.

**Tasks:** REQ-FIX-B-001, REQ-FIX-B-002, REQ-FIX-B-003, REQ-FIX-B-004.

### REQ-FIX-B-001: Cut list expansion (Phase 4 + Phase 8 never-cut)

**File:** `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md` §9

**Problem:** §9 says "Never cut: Phase 1 + Phase 9" but Phase 4 (Dhara
re-architecture) and Phase 8 (EventBridge WAL) are equally load-bearing
for §1 Outcome ("deployable on serverless"). An executor under scope
pressure could rationally cut Phase 4 thinking it's "Dhara cleanup."

**Fix:** Add to the "Never cut" list:
- "Phase 4 (Dhara re-architecture) — serverless gate for the persistence substrate; without it, §1 Outcome is not met for Dhara"
- "Phase 8 (EventBridge WAL) — serverless gate for cross-instance event routing; without it, EventBridge loses envelopes on cold start"

**Demonstrable by:** `grep "Never cut" -A 5 <plan>` shows four phases.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.1.5
- **Returns to / updates:** Parent plan §9 Risks
- **Rollback signal:** N/A
- **Observability added:** N/A

### REQ-FIX-B-002: Decision Rule severity tiers + per-tier action

**File:** `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md` §9

**Problem:** §9 Decision Rule says "if any new finding surfaces... re-evaluate." No severity threshold, no phase boundary, no per-tier action. Reviewer flagged as non-actionable.

**Fix:** Replace the one-sentence Decision Rule with:

```markdown
## Decision Rule

Findings that surface during execution are triaged into three tiers:

| Severity | Definition | Action |
|---|---|---|
| **Exit-criteria-breaking** | Finding invalidates a Phase's exit criteria or contradicts §1 Outcome | **Halt and replan.** Open a new precondition plan (analogous to this one) before continuing the affected Phase |
| **Scope-additive** | Finding adds work not covered by existing REQs but doesn't invalidate any | **Add REQ and continue.** Open a follow-up REQ in the current plan; do not halt |
| **Cosmetic** | Finding improves documentation/clarity but doesn't change behavior | **Document and proceed.** Add to a followups file (`docs/followups/<date>-<slug>.md`) |
```

**Demonstrable by:** Section is now ~10 lines with a table; not a single sentence.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.1.6
- **Returns to / updates:** Parent plan §9 Decision Rule
- **Rollback signal:** N/A
- **Observability added:** N/A

### REQ-FIX-B-003: Cross-component imports enforcement reassignment

**File:** `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md` Appendix C.1 + §5 Phase 5

**Problem:** Appendix C.1 says the "Mahavishnu → Akosha imports forbidden"
rule is enforced at "Phase 6 verification step." But the imports are
*removed* in Phase 5 (`REQ-MAHAVISHNU-IMPORTS`); Phase 6 strips
Akosha's surface after the dependency is already gone. The
enforcement check belongs to Phase 5's exit criteria.

**Fix:**
1. In Appendix C.1: change "Phase 6 verification step" → "Phase 5 exit criteria"
2. In §5 Phase 5 Integration Contract "Demonstrable by": add `grep -rn "from akosha.storage\|from dhara" mahavishnu/` returning empty as one of the demonstrable-by checks

**Demonstrable by:** `grep "Phase 5 exit criteria" <plan>` returns ≥1; `grep "from akosha.storage\|from dhara" -rn mahavishnu/` is in §5 Phase 5 demonstrable-by block.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.1.7
- **Returns to / updates:** Appendix C.1 + §5 Phase 5
- **Rollback signal:** N/A
- **Observability added:** N/A

### REQ-FIX-B-004: Audit invariant tolerance tightening

**File:** `.claude/decisions/wire-up-contract.md` (Integration contract — additional requirements section)

**Problem:** C.1's invariant is "file path resolves + line number is within 5 lines." A 4-line edit passes as no-drift. Surgical citations should be 0-2 lines; 5 masks the exact class of bug Rev-9 flagged.

**Fix:** Change "within 5 lines" → "within 2 lines for surgical citations, 5 lines only for `class`/`function` boundaries where the boundary line can shift". Update the example accordingly.

**Demonstrable by:** `grep -A 2 "within 2 lines" .claude/decisions/wire-up-contract.md` returns the new text.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.2.1
- **Returns to / updates:** `.claude/decisions/wire-up-contract.md`
- **Rollback signal:** N/A
- **Observability added:** N/A

### Phase B exit criteria

- All 4 REQs landed
- §9 cut list contains 4 phases (was 2)
- §9 Decision Rule contains a 3-tier table
- Appendix C.1 enforcement phase is "Phase 5" (was "Phase 6")
- wire-up-contract.md invariant is "2 lines / 5 only at boundaries"

## Phase C — Phase 8 deliverable detail (~1.5 hours)

**Goal:** Phase 8 (EventBridge Redis Streams WAL) currently has design
gaps that would surprise the implementer. Fill them before Phase 8
execution begins.

**Tasks:** REQ-FIX-C-001, REQ-FIX-C-002, REQ-FIX-C-003, REQ-FIX-C-004.

### REQ-FIX-C-001: Phase 8 consumer lifecycle details

**File:** `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md` Phase 8 deliverables

**Problem:** `eventbridge_consumer.py` describes `XREADGROUP` loop but
says nothing about graceful shutdown on SIGTERM, task cancellation,
startup ordering vs `bridge.emit()` registration (race: emit before
consumer group exists → lost message?), or what happens when Redis is
unreachable.

**Fix:** Add to the Phase 8 deliverable description for `eventbridge_consumer.py`:

```markdown
Lifecycle details:
- **Startup**: Consumer task spawned by `resolve_event_publisher()`
  AFTER `XGROUP CREATE envelopes:{topic} mahavishnu-shared $ MKSTREAM`
  (idempotent — catches BUSYGROUP error and continues). If
  `XGROUP CREATE` fails on any non-BUSYGROUP error, log at WARNING
  and disable WAL mode (fall back to in-process dispatch).
- **Shutdown**: Register `signal.SIGTERM`/`SIGINT` handlers that
  set an `asyncio.Event`; the `XREADGROUP BLOCK` loop checks the
  event before each iteration and exits cleanly. Pending entries
  are auto-claimed by surviving instances after `min_idle_time_ms`
  (default 60s).
- **Redis-unreachable**: The consumer task logs at ERROR and
  retries with exponential backoff (1s, 2s, 4s, ... capped at 60s).
  The `bridge.emit()` path is unaffected — emit always succeeds
  in-process even when the consumer is disconnected, but emits
  during the disconnection window are dropped (no local queue).
```

**Demonstrable by:** Phase 8 deliverable section contains the lifecycle details block.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.1.2
- **Returns to / updates:** Parent plan Phase 8 deliverables
- **Rollback signal:** N/A
- **Observability added:** WARNING logs for XGROUP CREATE failure, ERROR logs for Redis unreachable

### REQ-FIX-C-002: Phase 8 `_id` propagation contract

**File:** `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md` Phase 8 deliverables

**Problem:** `REQ-EVENTBRIDGE-IDEMPOTENCY-DOCS` says handlers dedupe on
envelope `_id`, but the deliverables don't specify where `_id` lives
in the XADD JSON.

**Fix:** Add to the Phase 8 deliverable description:

```markdown
`_id` propagation contract:
- The `_id` field is a uuid4 string generated by the emitter (in
  `bridge.emit()` or `eventbridge_wal.py`), NOT the Redis stream
  entry ID.
- `_id` lives at the top level of the envelope JSON: `{"_id":
  "<uuid4>", "topic": "...", "payload": {...}, "headers": {...}}`.
- The Redis stream entry ID (`XADD` return value) is recorded in
  the envelope's `_xadd_id` field for operator correlation.
- Handlers MUST treat `_id` as the idempotency key. The example
  in `docs/ops/eventbridge-wal.md` shows a handler that uses an
  LRU cache keyed on `_id` to drop duplicates.
```

**Demonstrable by:** Phase 8 deliverable section contains the `_id` contract block.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.1.3
- **Returns to / updates:** Parent plan Phase 8 deliverables
- **Rollback signal:** N/A
- **Observability added:** `_xadd_id` field for operator correlation

### REQ-FIX-C-003: Appendix B Phase 8 pre-flight

**File:** `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md` Appendix B

**Problem:** Phase 8 needs Redis running for integration tests. None of
the Redis-specific pre-flight is in Appendix B.

**Fix:** Add to Appendix B:

```markdown
- [ ] Redis ≥6.2 (Streams + consumer groups) running locally for Phase 8 development
- [ ] `redis-cli -u redis://localhost:6379 ping` returns PONG before Phase 8 starts
- [ ] `.env.test` (or test fixture) sets `MAHAVISHNU__EVENTBRIDGE__WAL__BACKEND=redis_streams`
- [ ] Production deployment sets `XADD envelopes:{topic} MAXLEN ~ 1000000` policy (default stream cap)
- [ ] Oneiric version pin: `oneiric>=0.21.0` (verified to ship `queue.redis_streams` adapter)
```

**Demonstrable by:** `grep -c "Redis ≥6.2\|redis://localhost" <plan>` returns ≥2.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.1.4
- **Returns to / updates:** Appendix B
- **Rollback signal:** N/A
- **Observability added:** N/A

### REQ-FIX-C-004: Phase 8 fallback adapter gap

**File:** `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md` Phase 8 dependency note

**Problem:** §5 Phase 8 says "if `redis_streams` missing, fall back to
`cloudtasks`/`kafka`" but no code path or settings key wires this
fallback.

**Fix:** Either (a) add a settings key `eventbridge.wal_fallback_backend: null` (default disabled) and a runtime check in `eventbridge_wal.py` that tries the primary then falls back, OR (b) remove the fallback claim from the Phase 8 dependency note.

**Recommendation:** Choose (b) — the fallback would be a meaningful feature (~200 LOC) and deserves its own REQ, not a parenthetical. Phase 8 ships with Redis Streams only; if Redis Streams is unavailable, Phase 8 is blocked until REQ-EVENTBRIDGE-WAL-FALLBACK is added.

**Demonstrable by:** Phase 8 dependency note no longer contains "fall back to `cloudtasks`/`kafka`" OR the fallback code path + settings key exist.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.2.6
- **Returns to / updates:** Phase 8 dependency note
- **Rollback signal:** N/A
- **Observability added:** N/A

### Phase C exit criteria

- All 4 REQs landed
- Phase 8 deliverables contain lifecycle, `_id` contract, pre-flight, and fallback decision blocks

## Phase D — Phase 1 + Phase 6.1 detail (~1 hour)

**Goal:** Make Phase 1 (wire-up cleanup) and Phase 6.1 (pre-step) execution-ready.

**Tasks:** REQ-FIX-D-001, REQ-FIX-D-002.

### REQ-FIX-D-001: Phase 1 per-REQ contracts

**File:** `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md` §5 Phase 1

**Problem:** Phase 1 says "template applied to each REQ-CLEAN" — that's
10 REQs without concrete Demonstrable-by.

**Fix:** Add a table mapping each REQ-CLEAN to a specific demonstrable check:

```markdown
| REQ | Demonstrable by |
|---|---|
| REQ-CLEAN-001 | `pytest tests/unit/test_task_router.py::TestIsAvailable` passes |
| REQ-CLEAN-002 | `ls mahavishnu/pools/fitness_analyzer.py` returns ENOENT |
| REQ-CLEAN-003 | `grep -c "aggregate_metrics" mahavishnu/pools/memory_aggregator.py` returns 0 |
| REQ-CLEAN-004 | `grep -c "emit_anomaly" mahavishnu/core/events/confidence_ceiling.py` returns 0 |
| REQ-CLEAN-005 | `grep -rn "_settle_dhara" mahavishnu/workers/contract/` returns ≥1 call site |
| REQ-CLEAN-006 | `grep -c "broadcast_settle_transition" mahavishnu/core/events/` returns ≥1 |
| REQ-CLEAN-007 | `grep -c "current_tmux" mahavishnu/workers/contract/` returns 0 (after removal) |
| REQ-CLEAN-008 | `ls crackerjack/ai_fix/*.backup 2>/dev/null | wc -l` returns 0 |
| REQ-CLEAN-009 | `ls -d crackerjack/intelligence/ 2>/dev/null` returns ENOENT |
| REQ-CLEAN-010 | `grep -c "AI agent" .claude/skills/crackerjack/SKILL.md` returns 0 |
```

**Demonstrable by:** Table exists in §5 Phase 1 with 10 rows.

**Integration Contract:**
- **Triggered from:** Reviewer finding F.2.5
- **Returns to / updates:** §5 Phase 1
- **Rollback signal:** N/A
- **Observability added:** N/A

### REQ-FIX-D-002: Phase 6.1 pre-step enumeration

**File:** `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md` §5 Phase 6.1

**Problem:** REQ-PHASE-6.1-PRE-STEP refers to "agents_catalog.md
Appendix C" which doesn't exist — Appendix C is governance docs. The
6 affected agent/skill catalogs should be enumerated inline.

**Fix:** Either (a) rename the appendix reference to a real file, or (b) enumerate the 6 catalogs inline.

**Recommendation:** Choose (b) — discoverable now via:
```bash
grep -rln "mcp__akosha__" .claude/agents/ .claude/skills/ | xargs -I {} \
  grep -l "list_conversations\|search_by_concept\|quick_search\|find_duplicates\|fingerprint_search\|reflection_stats" {}
```

The output (expected 6 files based on Akosha tool catalog in REQ-AKOSHA-STRIP) should be enumerated in REQ-PHASE-6.1-PRE-STEP. If the grep returns a different number, REQ-AKOSHA-STRIP should be re-scoped to match.

**Demonstrable by:** REQ-PHASE-6.1-PRE-STEP entry contains a list of 6 catalog file paths (or the actual count if different from 6).

**Integration Contract:**
- **Triggered from:** Reviewer finding F.2.3
- **Returns to / updates:** §4.5 REQ-PHASE-6.1-PRE-STEP row
- **Rollback signal:** If grep returns ≠6, flag REQ-AKOSHA-STRIP for re-scoping
- **Observability added:** N/A

### Phase D exit criteria

- All 2 REQs landed
- §5 Phase 1 contains the per-REQ demonstrable-by table
- REQ-PHASE-6.1-PRE-STEP row contains enumerated catalog file paths

## §6 Required Code Changes

None. This plan is text-only — no code paths, no test additions, no
build changes. The CI guard test (`tests/test_plan_citations.py`)
mentioned in `wire-up-contract.md` is out of scope; it ships as part
of parent plan Phase 9.

## §7 Validation Matrix

| Tool/Command | Expected outcome | Evidence |
|---|---|---|
| `grep -c "REQ-ONEIRIC-MIRROR" docs/plans/2026-09-14-...md` in §5 task list | 0 | shell exit code 0, no output |
| `grep -c "2026-04-02-storage-consolidation" docs/adr/013-*.md` | ≥1 | shell |
| `grep "within 2 lines" .claude/decisions/wire-up-contract.md` | ≥1 | shell |
| `grep "Phase 4\|Phase 8" docs/plans/2026-09-14-...md \| grep -A 4 "Never cut"` | Lists all 4 phases | shell |
| `grep -A 10 "Decision Rule" docs/plans/2026-09-14-...md \| grep -c "Severity"` | 3 (severity rows) | shell |
| `grep -A 20 "Phase 8 deliverable" docs/plans/2026-09-14-...md \| grep -c "lifecycle\|startup ordering\|graceful shutdown"` | ≥3 | shell |
| `grep -c "_id" docs/plans/2026-09-14-...md` (in Phase 8 deliverables section) | ≥3 | shell |
| `grep -c "Redis ≥6.2" docs/plans/2026-09-14-...md` | ≥1 | shell |
| `grep -c "fall back to" docs/plans/2026-09-14-...md` (in Phase 8) | 0 (fallback claim removed) | shell |

## §8 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Plan edits introduce new file:line drift | Low | Each Phase exit criterion includes a grep verification command |
| ADR 017 citation correction changes scope (reveals more imports than expected) | Low | If grep returns >1+8 imports, file a followup REQ to handle them |
| Phase 6.1 grep returns a different number than 6 | Medium | Trigger REQ-AKOSHA-STRIP re-scoping; document the actual count |
| Reviewer-disagreement on severity tier classification during execution | Medium | Tier escalation triggers halt-and-replan (§9 Decision Rule, post-Phase-B) |

## §9 Decision Rule

**Per the parent plan's revised Decision Rule (REQ-FIX-B-002):**

| Severity | Action |
|---|---|
| Exit-criteria-breaking | Halt and replan — open a new precondition plan before continuing the affected Phase |
| Scope-additive | Add REQ and continue |
| Cosmetic | Document and proceed |

Findings that surface during THIS plan's execution follow the same rule. The expected finding surface is small (text edits); any non-trivial deviation is exit-criteria-breaking.

## §10 Triage of remaining deferred findings

The 8 deferred items from parent plan Appendix F are NOT in this plan's scope:

- F.3 (DELETE-CANDIDATE): §6 stale (parent plan); Phase 7 already cut-first — both are implementation-time cleanup
- F.4.1 (no PR/branch strategy): implementation-time coordination, not a plan concern
- F.4.2 (no WAL rollout toggle): design decision; defer to Phase 8 implementation
- F.4.3 (`envelopes-replay:*` stream): feature addition; defer to a future plan
- F.4.4 (no shutdown handler): covered by REQ-FIX-C-001 (Phase 8 consumer lifecycle)
- F.4.5 (no Oneiric version pin): covered by REQ-FIX-C-003 (Phase 8 pre-flight)
- F.4.6 (metric collision): deferred; will surface during Phase 8 implementation
- F.4.7 (Phase 10 has no REQ): cosmetic; add if Phase 10 is reached
- F.4.8 (process REQs lack audit-invariant): partially addressed by REQ-FIX-B-004 (file:line invariant); full coverage deferred

## Appendix A — Cross-references

- Parent plan: `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md`
- Parent plan Appendix F: 22 deferred findings (this plan addresses 14)
- ADR 017: `docs/adr/017-oneiric-shared-persistence-substrate.md` (citation drift fixed by REQ-FIX-A-002)
- ADR 013: `docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md` (cross-ref added by REQ-FIX-A-003)
- Wire-up contract: `.claude/decisions/wire-up-contract.md` (invariant tightened by REQ-FIX-B-004)

## Appendix B — Pre-flight checklist

Before starting this plan's Phase A:
- [ ] Parent plan status is `active`
- [ ] Reviewer findings F.1 + F.2 are listed in parent plan Appendix F
- [ ] This plan's frontmatter `blocks_on` resolves to the parent plan
- [ ] Current branch is `main` (pre-1.0 merge policy per `bodai-pre-1.0-merge-policy.md`)

Before starting Phase C:
- [ ] Phase A exit criteria all green
- [ ] Phase B exit criteria all green
- [ ] No new findings surfaced during A or B that aren't already covered

Before closing this plan:
- [ ] All 14 REQs in Phases A-D are `Closed`
- [ ] All `grep` validation rows in §7 pass
- [ ] Parent plan Appendix F is updated to reference this plan's closure
- [ ] PLAN_INDEX.md regenerated via `scripts/regenerate_plan_index.py`
- [ ] Committed with attribution per CLAUDE.md § Process Discipline

## Appendix C — Effort tracking

| Phase | Tasks | Estimated effort |
|---|---|---|
| A | 4 REQs (all text edits) | 1 hour |
| B | 4 REQs (1 file:line invariant, 3 plan text edits) | 1.5 hours |
| C | 4 REQs (Phase 8 deliverable detail additions) | 1.5 hours |
| D | 2 REQs (per-REQ contract table + grep enumeration) | 1 hour |
| **Total** | **14 REQs** | **~5 hours** |
