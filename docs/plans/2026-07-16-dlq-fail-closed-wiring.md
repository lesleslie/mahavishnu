---
status: shipped
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: persistence
---

# DLQ Fail-Closed Wiring + Observability (Full #3)

**Date:** 2026-07-16
**Status:** shipped, implementation — all three phases complete (2026-07-16)  <!-- legacy status — see YAML frontmatter -->
**Owner:** Claude Code (session 854beabd)
**Scope:** Make the opt-in DLQ fail-closed policy actually work in production, close the runtime OpenSearch-write data-loss window, and add the observability the original followup requested.
**Purpose:** The `2026-06-29-dlq-silent-fallback.md` followup self-declared "Resolved," but a 2026-07-16 audit found the shipped flag is inert in production and a runtime write failure still silently drops failed tasks to a per-process in-memory deque. This plan closes that gap.

## 1. Outcome

- Setting `dlq.fail_on_opensearch_unavailable: true` in `settings/*.yaml` (or `MAHAVISHNU_DLQ__FAIL_ON_OPENSEARCH_UNAVAILABLE=true`) causes the production DLQ to actually refuse tasks when OpenSearch is unreachable — instead of the flag being silently ignored.
- When fail-closed is on, a failed OpenSearch *write* (not just a missing client) raises `ExternalServiceError` and does **not** leave a phantom in-memory-only task.
- Operators can see fallback/rejection activity via a `mahavishnu_dlq_fallback_total` metric and a diagnosis runbook.

**Success signal:** new tests pass (`test_dlq_integration.py`, extended `test_dead_letter_queue_fail_closed.py`, `tests/integration/core/test_dead_letter_queue_failover.py`); `curl .../metrics | grep mahavishnu_dlq_fallback_total` shows a non-zero counter after a forced fallback.

## 2. Goals

1. Propagate `MahavishnuSettings.dlq.fail_on_opensearch_unavailable` into every production `DeadLetterQueue` construction (`dlq_integration.py:387`, `_main_cli.py:366`).
1. Make `enqueue` honor fail-closed on a *runtime* OpenSearch write failure, not only on a missing client/library.
1. Add the `mahavishnu_dlq_fallback_total` metric, a failover integration test, and a DLQ operator runbook.
1. Clean up the duplicated dead docstring in `DeadLetterQueue.__init__`.

## 3. Non-Goals

1. `#4` opensearch-diverged-flags hygiene (the residual lives only in the deprecated, test-only `workflow_state.py`; documented as moot — see `docs/followups/README.md`).
1. Redesigning DLQ persistence backends (Redis/Postgres) — out of scope; OpenSearch stays the single backend.
1. Changing the default policy — `fail_on_opensearch_unavailable` stays `False` (back-compat). This plan only makes the opt-in real.
1. Fixing the unrelated `dlq_max_size` flat-attr misread is **optional** (Phase 1, tagged), not a required goal.

## 4. Current Findings

- Flag + unit tests exist: `DLQConfig.fail_on_opensearch_unavailable` (`config.py:725`), `DeadLetterQueue.__init__(..., fail_on_opensearch_unavailable=False)` (`dead_letter_queue.py:203`), `_assert_opensearch_or_fail_closed` (`:372-406`), `tests/unit/core/test_dead_letter_queue_fail_closed.py` (4 tests).
- **Gap 1 (wiring):** neither production construction site passes the flag. `dlq_integration.py:387-393` passes only `max_size`/`opensearch_client`/`observability_manager`; `_main_cli.py:366` is a bare `DeadLetterQueue()`. `grep fail_on_opensearch_unavailable` hits only `config.py`, `dead_letter_queue.py`, and tests.
- **Gap 2 (runtime write):** `_assert_opensearch_or_fail_closed` (`:384-387`) only checks client presence + `OPENSEARCH_AVAILABLE`. `_persist_task` (`:414-422`) wraps `self._opensearch.index(...)` in `try/except Exception` that logs and swallows. So with a *configured* client whose write fails at runtime, `enqueue` appends to `_queue` (`:345`) then swallows the persist error (`:349`) — the task survives only in memory and is lost on restart.
- **Gap 3 (observability):** no `mahavishnu_dlq_fallback_total` metric, no `tests/integration/core/test_dead_letter_queue_failover.py`, no DLQ runbook (all confirmed absent).
- **Incidental:** `DeadLetterQueue.__init__` has a duplicated dead docstring (`:223-229`). `DLQConfig` has no `max_size` field, yet `dlq_integration.py:388` reads a non-existent flat `app.config.dlq_max_size` (always defaults to 10000).

## 5. Implementation Phases

### Phase 1: Wire the flag into production construction (C1)

**Goal:** The config value reaches every production DLQ constructor.
**Tasks:**
- `mahavishnu/core/dlq_integration.py:387` — pass `fail_on_opensearch_unavailable=app.config.dlq.fail_on_opensearch_unavailable`.
- `mahavishnu/_main_cli.py:366` — construct the heal-path DLQ with the flag from settings for consistency (note: this path only `list_tasks`, never `enqueue`, so the flag is inert here — add a comment saying so).
- Remove the duplicated docstring block in `DeadLetterQueue.__init__` (`:223-229`).
- *(Optional, tagged)* add `max_size: int = Field(default=10000)` to `DLQConfig` and read `app.config.dlq.max_size`, fixing the `dlq_max_size` misread.
- New test `tests/unit/core/test_dlq_integration.py::test_fail_closed_flag_propagates_from_config`.

**Exit criteria:** the new propagation test passes; `grep` shows the flag passed at both call sites.

#### Integration Contract

- **Triggered from**: `create_dlq_integration(app)` (`mahavishnu/core/dlq_integration.py`), invoked during app DLQ setup; `_async_heal_workflows` via the `mahavishnu heal-workflows` CLI path.
- **Returns to / updates**: constructs `app.dlq` with `_fail_on_opensearch_unavailable` sourced from `MahavishnuSettings.dlq`.
- **Demonstrable by**: `pytest tests/unit/core/test_dlq_integration.py::test_fail_closed_flag_propagates_from_config`.
- **Rollback signal**: unexpected `ExternalServiceError` / log `"DLQ fail-closed: refusing to enqueue"` in a single-node dev env → set flag back to `false` (default) or revert.
- **Observability added**: none in this phase (relies on existing WARN/ERROR logs); metric added Phase 3.

### Phase 2: Fail-closed on runtime write failure (C2)

**Goal:** With fail-closed on, a failed OpenSearch write raises rather than leaving a memory-only phantom.
**Tasks:**
- In `enqueue`, when `self._fail_on_opensearch_unavailable` is on: attempt persist first and only append to `_queue` on success; on persist failure raise `ExternalServiceError` (do not append). When off: preserve current order/best-effort behavior exactly.
- Give `_persist_task` a strict variant (or a `strict: bool` param) that re-raises instead of swallowing, used only on the fail-closed path.
- Extend `tests/unit/core/test_dead_letter_queue_fail_closed.py`: configured client whose `.index` raises → `enqueue` raises `ExternalServiceError` and the task is **not** in `_queue`; and the flag-off path is unchanged.

**Exit criteria:** new tests prove both the raise-and-no-phantom (flag on) and unchanged behavior (flag off).

#### Integration Contract

- **Triggered from**: `DeadLetterQueue.enqueue(...)`, called from workflow-failure handling and `DLQIntegration`.
- **Returns to / updates**: persists to OpenSearch index `mahavishnu_dlq` on success; raises `ExternalServiceError` on fail-closed write failure with no in-memory phantom.
- **Demonstrable by**: `pytest tests/unit/core/test_dead_letter_queue_fail_closed.py::test_runtime_write_failure_raises_when_fail_closed`.
- **Rollback signal**: spike in enqueue `ExternalServiceError` / `mahavishnu_dlq_fallback_total{outcome="rejected"}` climbing → revert to flag-off.
- **Observability added**: increments the Phase 3 counter on both the rejected and in-memory-fallback branches.

### Phase 3: Observability + integration test + runbook (C3)

**Goal:** Fallback/rejection is visible and diagnosable.
**Tasks:**
- Add `mahavishnu_dlq_fallback_total` Counter (labels: `outcome=persisted|in_memory|rejected`), registered on the same Prometheus registry the `metrics_cli` / observability surface exports; increment in the enqueue/persist branches.
- Add `tests/integration/core/test_dead_letter_queue_failover.py`: OpenSearch-down + flag off → task in memory + `outcome="in_memory"` increment; flag on → raises + `outcome="rejected"` increment.
- Add `docs/runbooks/dead-letter-queue.md`: what the metric means, how to enable fail-closed, how to diagnose an activated fallback.

**Exit criteria:** metric appears on the `/metrics` scrape after a forced fallback; integration test passes; runbook committed.

#### Integration Contract

- **Triggered from**: the enqueue/persist fallback + rejection branches in `dead_letter_queue.py`.
- **Returns to / updates**: Prometheus counter exported via the metrics endpoint; new runbook doc.
- **Demonstrable by**: `curl -s localhost:<metrics-port>/metrics | grep mahavishnu_dlq_fallback_total` shows a non-zero series after a forced fallback.
- **Rollback signal**: metric missing, or label-cardinality growth in the scrape → drop/adjust the counter.
- **Observability added**: `mahavishnu_dlq_fallback_total{outcome=...}` — the deliverable itself.

## 6. Required Code Changes

- [ ] `mahavishnu/core/dlq_integration.py` — pass fail-closed flag (+ optional `max_size`) from `app.config.dlq`.
- [ ] `mahavishnu/_main_cli.py` — construct heal-path DLQ with flag from settings (+ inert-here comment).
- [ ] `mahavishnu/core/dead_letter_queue.py` — remove dead docstring; strict-persist path; fail-closed reordering in `enqueue`; metric increments.
- [ ] `mahavishnu/core/config.py` — *(optional)* add `DLQConfig.max_size`.
- [ ] metrics/observability module — register `mahavishnu_dlq_fallback_total`.
- [ ] `tests/unit/core/test_dlq_integration.py` — new (propagation).
- [ ] `tests/unit/core/test_dead_letter_queue_fail_closed.py` — extend (runtime write).
- [ ] `tests/integration/core/test_dead_letter_queue_failover.py` — new.
- [ ] `docs/runbooks/dead-letter-queue.md` — new.
- [ ] `docs/followups/2026-06-29-dlq-silent-fallback.md` — flip Status to Resolved (with cited tests) and `git mv` to `.archive/`; update `docs/followups/README.md`.

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|----------------|------------------|-------------------|
| `pytest tests/unit/core/test_dlq_integration.py` | flag propagates from config | test output |
| `pytest tests/unit/core/test_dead_letter_queue_fail_closed.py` | runtime-write-failure raises; flag-off unchanged | test output |
| `pytest tests/integration/core/test_dead_letter_queue_failover.py -m integration` | both outcomes + metric increments | test output |
| `crackerjack run` | quality gate green (≥80% cov, ruff/mypy/pyright) | crackerjack report |
| `curl .../metrics \| grep mahavishnu_dlq_fallback_total` | non-zero series after forced fallback | metrics scrape |
| `python scripts/audit_orphans.py` | no new orphaned symbols | audit output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Reordering `enqueue` changes semantics for existing callers | Medium | Gate all new behavior behind `fail_on_opensearch_unavailable`; flag-off path byte-for-byte unchanged; regression test asserts it. |
| Metric label cardinality growth | Low | Fixed enum labels (`persisted\|in_memory\|rejected`) only. |
| Enabling fail-closed in a mis-configured single-node dev env breaks local runs | Medium | Default stays `False`; runbook documents the tradeoff. |
| `max_size` optional change touches `DLQConfig` schema | Low | Keep optional/tagged; ship separately if it risks the gate. |

## 9. Decision Rule

Done-enough = Phases 1 and 2 shipped (flag propagates **and** runtime write-failure is honored under fail-closed) with green tests. Phase 3's runbook and integration test are the first cuts under scope pressure; the metric ships with Phase 2 because the Rollback signals depend on it. `#4` and `dlq_max_size` are never blockers.
