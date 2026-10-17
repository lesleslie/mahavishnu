---
name: runpod-status-truth
description: ``mahavishnu.pools.RunPodPool`` uses ``req.output()`` as the terminal oracle for job status; ``req.status()`` is a non-blocking snapshot and is NEVER used to infer terminal state.
---

**Context (2026-10-17):** A post-merge security review of the runpod SDK 2.0 migration (PR landed as `e71221ed`) found two related defects in `mahavishnu.pools.RunPodPool.execute_task`:

1. **fail-open-state-drift** — the dispatch envelope mapped the raw `req.status()` string to a pool status, and the `else` branch silently coerced any unknown status to `"completed"`. If the SDK ever ships a new terminal status we don't recognize (CANCELLED, TIMED_OUT, EXPIRED, etc.), the pool would report success to the caller. Same branch bumped `_tasks_completed`, so an unrecognized failure state would also be miscounted as a completion in `get_metrics()` / `health_check()`.

2. **logic-defeat** — `_dispatch` queried `req.status()` BEFORE calling `req.output()`. `req.status()` is a non-blocking query and can return `IN_QUEUE` / `IN_PROGRESS` mid-flight; `req.output()` is the authoritative terminal signal (returns on COMPLETED, raises on FAILED). The envelope's `status` field was therefore non-authoritative, and the `IN_QUEUE`/`IN_PROGRESS` branch was dead-but-active: it could fire and produce `{status: "in_progress", output: <valid output>}` — incoherent.

**Decision:** `req.output()` is the terminal oracle. The dispatch helper reorders so `.output()` blocks first; `.status()` is then consulted for telemetry only. The success path of `execute_task` collapses to "`.output()` returned without raising → `status="completed"`". The `IN_QUEUE`/`IN_PROGRESS → "in_progress"` branch and the `else → "completed"` fail-open branch both disappear. The `except Exception` branch already correctly handles FAILED via `.output()` raising, so the failure path is unchanged.

A defensive `logger.warning` fires when `req.status()` reports a value other than `COMPLETED` after a successful `.output()` return — guards against SDK contract drift adding new terminal status names — but the caller still receives `"completed"` because the oracle returned. The warning text includes the SDK-reported status and the job id so operators can correlate the anomaly.

**Why:** Job-status truth is the basis of every downstream retry / quota / health decision. A fail-open status mapping in this code path means the orchestrator can mark failed work as completed and the failure becomes invisible to the system. The cost of the fix is one test rewrite plus three new tests; the cost of leaving the fail-open in place is silent data loss on first unrecognized SDK status.

**Status:** merged; `mahavishnu/pools/runpod_pool.py` + `tests/unit/test_runpod_pool.py` updated on the `fix/runpod-status-truth` branch (squash-merged into `main`).

Reference: `docs/decisions/2026-10-17-runpod-flash-to-sdk-2.md` (predecessor migration).
