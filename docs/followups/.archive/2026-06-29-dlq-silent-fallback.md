# Dead-Letter Queue Silent Fallback — Data-Loss Followup

**Status:** Resolved (2026-07-16). The opt-in flag (`dlq.fail_on_opensearch_unavailable`, default `False`) now reaches the production DLQ at `dlq_integration.py:387` from `MahavishnuSettings.dlq` (verified by `tests/unit/core/test_dlq_integration.py::test_fail_closed_flag_propagates_from_config`). Runtime OpenSearch write failures also honor fail-closed: `enqueue` reorders to persist-then-append when the flag is on, so a failing write raises `ExternalServiceError` with **no memory-only phantom** (verified by `tests/unit/core/test_dead_letter_queue_fail_closed.py::test_runtime_write_failure_raises_when_fail_closed`); the flag-off path is byte-for-byte unchanged (verified by `test_flag_off_swallows_runtime_write_failure`). The `mahavishnu_dlq_fallback_total` metric (`mahavishnu/core/dlq_metrics.py`) is incremented on every enqueue branch. Runbook: `docs/runbooks/dead-letter-queue.md`. Plan: `docs/plans/2026-07-16-dlq-fail-closed-wiring.md`. Discovered during the bodai-crow-server runbook + `local.yaml.example` PR audit.
**Refs:** Related to `2026-06-29-opensearch-diverged-flags.md` (root cause is the same module family).

## Background

`mahavishnu/core/dead_letter_queue.py` uses the same silent-fallback pattern as `opensearch_integration.py`, but with a sharper failure mode than search/observability: the path is the *last* line of defense for failed tasks.

When OpenSearch is unreachable, the DLQ stores failed tasks in an in-memory `collections.deque`. Three concrete consequences follow:

1. **Per-process state.** The deque lives in the Python process that observed the failure. In a multi-node deployment, each Mahavishnu instance accumulates a *divergent* queue that no other node can see.
1. **Lost on restart.** A SIGTERM, OOM, or rolling deploy drops every queued task on the floor. There is no persistence, no journal, no replay.
1. **Silent.** Nothing is logged at WARN or higher when the fallback activates. Operators learn the DLQ is dropping only after a postmortem compares "expected N retries" against "got 0 retries in OpenSearch".

The relevant fallback sites inside `dead_letter_queue.py`:

- `dead_letter_queue.py:175` — initial `try: ... except Exception` around the OpenSearch write path, drops into in-memory deque.
- `dead_letter_queue.py:197` — second-tier fallback when the deque itself errors (e.g. non-serializable payload), currently a no-op.
- `dead_letter_queue.py:213` — fallback in the read path: if OpenSearch query fails, returns an empty list rather than raising. Callers cannot distinguish "no failed tasks" from "DLQ is offline".

The integration layer at `mahavishnu/core/dlq_integration.py` calls into `dead_letter_queue.py` and inherits its silent behavior at the orchestration boundary — pool workers, retry policy, and the workflow event stream all "see" successful enqueue when in fact the task was dropped.

## Why out of scope

This is a code change, not a config change. A real fix requires either:

- A real shared broker (Redis is already in the Bodai ecosystem; RabbitMQ or shared OpenSearch/Postgres are alternatives), **or**
- A fail-closed policy (refuse tasks when the DLQ is unavailable, surfaced as a `ConfigurationError` rather than a silent drop).

Both are substantial, multi-file, schema-and-migration-adjacent changes. They are out of scope for the current runbook + `local.yaml.example` PR, which is scoped to operator-facing defaults and operational documentation. Folding in a DLQ backend swap would (a) require schema/version decisions the runbook PR is not the venue for, and (b) inflate the PR's blast radius into a hot path that orchestrates task lifecycle.

## Proposed remediation

Three options, in increasing order of invasiveness. **Option A is recommended** because Redis is already a Bodai component and avoids new infrastructure.

### Option A — Redis-backed shared DLQ (recommended)

1. Add `dlq.backend: "redis"` (default) and `dlq.redis_url: "${MAHAVISHNU_REDIS_URL}"` to `settings/mahavishnu.yaml`.

1. Replace the in-memory `collections.deque` in `dead_letter_queue.py` with a thin Redis client wrapper:

   ```python
   await redis_client.lpush(f"mahavishnu:dlq:{node_id}", json.dumps(payload))
   await redis_client.ltrim(f"mahavishnu:dlq:{node_id}", 0, max_len - 1)
   ```

1. Add per-node uniqueness to the DLQ ID space (`f"mahavishnu:dlq:{socket.gethostname()}:{pid}"`) so debugging can identify which node dropped which task.

1. On Redis failure, escalate to ERROR log and raise `DLQUnavailable` rather than silently swallowing — but keep the *write* path non-blocking so a Redis blip doesn't stall workflow execution.

1. Replay tooling: add `mahavishnu dlq replay --node <name> --limit 100` to push entries back through the retry queue.

### Option B — Postgres-backed DLQ

- Requires a schema migration (new `dlq_entries` table with `node_id`, `task_id`, `payload jsonb`, `created_at`).
- Higher durability than Redis (WAL-backed), slower writes.
- Heavier operational footprint; only justified if Redis is intentionally excluded.

### Option C — Fail-closed on DLQ unavailability

- Smallest code change. When OpenSearch is down, `DeadLetterQueue.enqueue()` raises `DLQUnavailable` instead of writing to the in-memory deque.
- The workflow layer must catch this and decide: refuse the task, retry-later, or mark as "unrecoverable, ops intervention required".
- **Trade-off:** trades silent data loss for loud task refusals. Good for correctness, bad for availability — operators may prefer the silent loss in low-stakes workflows.

### Common requirements regardless of option

- **Logging.** The fallback path must log at WARN (current silent-drop) or ERROR (fail-closed). The line `dead_letter_queue.py:175` is the single point where this is decided today.
- **Metric emission.** Add a `mahavishnu_dlq_fallback_total{backend="memory|redis|postgres"}` counter so dashboards can alert on fallback frequency.
- **Test coverage.** Add a `tests/integration/core/test_dead_letter_queue_failover.py` that stubs OpenSearch and asserts (a) no in-memory writes occur, (b) the correct backend is hit, (c) errors raise rather than swallow.
- **Operator runbook.** Update `docs/runbooks/` with "DLQ fallback activated — what to check" guidance once the remediation lands.

## References

- `mahavishnu/core/dead_letter_queue.py:175` — initial fallback into in-memory deque
- `mahavishnu/core/dead_letter_queue.py:197` — second-tier fallback (silent no-op)
- `mahavishnu/core/dead_letter_queue.py:213` — read-path fallback returning empty list
- `mahavishnu/core/dlq_integration.py` — orchestration boundary that inherits the silent behavior
- `mahavishnu/core/opensearch_integration.py:38-44` — same pattern, different module (see `2026-06-29-opensearch-diverged-flags.md`)
