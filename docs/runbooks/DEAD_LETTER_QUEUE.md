# Dead Letter Queue Runbook

## What this is

The Dead Letter Queue (DLQ) holds workflow tasks that have failed
retries. The persistent copy lives in OpenSearch; if OpenSearch is
unavailable, the queue falls back to a per-process in-memory queue
to avoid losing tasks mid-flight. The trade-off is that an in-memory
fallback is **lost on process restart** — a data-loss risk for
multi-node production deployments.

The DLQ fail-closed opt-in policy (added 2026-07) trades that silent
fallback for an explicit error so a misconfigured orchestrator does
not silently drop failed tasks.

## The metric

```
mahavishnu_dlq_fallback_total{outcome="persisted|in_memory|rejected"}
```

- **`persisted`** — task was successfully written to OpenSearch.
- **`in_memory`** — task was enqueued but only the in-memory fallback
  holds it. Either OpenSearch was unavailable at enqueue time, or a
  configured client's write failed and the legacy silent-fallback
  path kept the task alive. **Lost on restart.**
- **`rejected`** — `fail_on_opensearch_unavailable=true` and the
  task could not be confirmed in OpenSearch. No phantom was created;
  the caller (workflow layer) is expected to surface the error and
  decide whether to retry or fail loudly.

## Enabling fail-closed

In `settings/local.yaml` (or wherever `MahavishnuSettings` is loaded):

```yaml
dlq:
  fail_on_opensearch_unavailable: true   # default: false
  max_size: 10000                         # default
```

Or via env var: `MAHAVISHNU_DLQ__FAIL_ON_OPENSEARCH_UNAVAILABLE=true`

Restart the orchestrator. There is no runtime toggle.

## Diagnosing an activated fallback

When the metric shows non-zero `outcome="in_memory"` or
`outcome="rejected"`:

1. **Check OpenSearch health.** `curl -s $MAHAVISHNU_OPENSEARCH_HOST/_cluster/health`
   should return `status: green` or `yellow`. If `red`, the cluster is
   the problem, not the orchestrator.
1. **Check the orchestrator's OpenSearch wiring.**
   `mahavishnu/engines/prefect_schedules.py` and `opensearch_integration.py`
   import `OPENSEARCH_AVAILABLE` from `mahavishnu/core/opensearch_constants.py`.
   A mismatch there means the library is installed in one place but not
   importable in another — rare, but the `test_no_duplicate_flag_declarations`
   guard in `tests/unit/core/test_opensearch_constants.py` is the check.
1. **Check the workflow-layer response.** When `outcome="rejected"`,
   the workflow that called `enqueue` receives `ExternalServiceError`;
   the workflow itself decides whether to retry, fail, or alert. The
   DLQ does not retry on the user's behalf.

## Why the default is `false`

Single-node dev environments with no OpenSearch should not break local
runs. Fail-closed is opt-in, per
`docs/followups/2026-06-29-dlq-silent-fallback.md` and
`docs/plans/2026-07-16-dlq-fail-closed-wiring.md`. Recommended for any
deployment that runs more than one Mahavishnu process, or any
deployment where losing failed tasks would be unacceptable.

## Related

- Plan: `docs/plans/2026-07-16-dlq-fail-closed-wiring.md`
- Followup: `docs/followups/2026-06-29-dlq-silent-fallback.md` (resolved 2026-07-16)
- Config: `mahavishnu/core/config.py::DLQConfig`
- Implementation: `mahavishnu/core/dead_letter_queue.py::DeadLetterQueue.enqueue`
- Metric module: `mahavishnu/core/dlq_metrics.py`
- Tests: `tests/unit/core/test_dlq_integration.py`, `test_dead_letter_queue_fail_closed.py`, `test_dlq_metrics.py`; `tests/integration/core/test_dead_letter_queue_failover.py`
