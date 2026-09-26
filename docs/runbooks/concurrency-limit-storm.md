# Runbook: Concurrency Limit Storm (C-9)

Operational guide for the per-TaskCategory `ConcurrencyGate`. Per the round-4 finding: **the gate is per-process** — with N workers, the effective limit is N × spec.limit. This runbook documents the worker-count discovery formula and the two failure modes that surface in production.

## Critical pre-flight: discover worker count FIRST

```bash
# How many Mahavishnu worker processes are running?
ps aux | grep -c "mahavishnu.*--worker"
# Or, if using k8s:
kubectl get pods -l app=mahavishnu -o jsonpath='{.items[*].status.containerStatuses[*].ready}' | tr ' ' '\n' | grep -c true
```

The effective per-TaskCategory limit is:

```
effective_limit = worker_count × settings.concurrency_limits.by_category[<category>].concurrency_limit
```

**Example**: with 4 workers and `concurrency_limit: 2` for `CODE_GENERATION`, the effective limit is 8 dispatches, not 2. Operators who set the limit thinking they have 2 will see twice the expected throughput. **The gate does NOT enforce the per-TaskCategory limit across the cluster — only within a single worker process.**

## Scenario 1: `task_domain_rate_limited_total` flood

**Symptoms:**
- `task_domain_rate_limited_total{domain="CODE_GENERATION"}` rate >1/s for 5m
- `RateLimitError` exceptions in pool_route_execute logs
- Akosha receives `anomaly.detected` events for `domain_rate_limit_exceeded`

**Diagnosis:**
1. Check the active dispatch count: `curl http://localhost:8680/metrics | grep task_domain_concurrency`
2. Cross-reference with `task_domain_rate_limited_total` to find which domain is hot
3. Check whether the limit is appropriate:
   ```bash
   # Get current limit
   cat settings/mahavishnu.yaml | grep -A2 concurrency_limit
   # Get worker count (see formula above)
   ```
4. Check whether recent config changes raised or lowered limits: `git log -p settings/mahavishnu.yaml | head -30`

**Recovery:**
1. **If limits are too aggressive** (recent lowering): revert `settings/mahavishnu.yaml` and restart
2. **If legitimate load spike**: increase `concurrency_limit` for the affected category. **Divide target_total by worker_count first** to avoid over-allocation
3. **If one domain is monopolizing workers**: investigate why other domains can't acquire slots. The gate's `_shard_locks` LRUCache bounds memory, but contention is real under spike conditions
4. **If the gate is misbehaving** (denies when slots available): check the `LRUCache(maxsize=1024)` eviction — if the lock for a held `(category, pool_id)` was evicted, `release()` returns early and the slot leaks. Restart the worker to clear the leak.

**Verification:**
- `task_domain_rate_limited_total{domain="X"}` rate <0.1/s within 5 minutes
- `task_domain_concurrency{domain="X", pool_worker_id="..."}` returns to baseline within 1 minute
- No `RateLimitError` in the dispatch logs

## Scenario 2: Atomicity drift (`task_domain_concurrency_drift_total` incrementing)

**Symptoms:**
- `task_domain_concurrency_drift_total{domain="X"}` rate >0.1/s
- Atomicity violation metric fires (counter exceeded spec limit under contention)
- `task_domain_concurrency{domain="X"}` reading exceeds `concurrency_limit × worker_count`

**Diagnosis:**
1. Check whether multiple worker processes share the same `(category, pool_id)` — if so, drift is expected (per-process scope is documented)
2. Check whether the lock was evicted mid-acquire:
   - `LRUCache(maxsize=1024)` — if the same key is acquired >1024 times before the original holder releases, the lock may be evicted
   - Look for `release()` returning early in the logs (it logs nothing on early-return — add a metric if investigating)
3. Check whether the gate is being modified by external code: `git log --all -S "ConcurrencyGate"` for recent changes

**Recovery:**
1. **If drift is per-process expected** (multi-worker pool): no action needed; the metric exists to make this visible, not to alert
2. **If drift is unintended** (single-worker setup): restart Mahavishnu; the gate's `_counters` dict is per-process and a restart resets it
3. **If drift is from lock eviction**: increase `LRUCache(maxsize=...)` to bound the working set; the eviction is benign but the metric is alarming

**Verification:**
- `task_domain_concurrency_drift_total` rate <0.01/s within 10 minutes
- `task_domain_concurrency` reads match `worker_count × spec.concurrency_limit` (within ±5%)

## Per-process limitation disclosure (per ADR 0001)

The niche filter document (`docs/adr/0001-mahavishnu-niche.md`) does not require a per-cluster gate. The per-process gate is consistent with Mahavishnu's positioning as an LLM control plane + repo orchestrator. **A future fix path is a Redis/Dhara-backed shared counter** when cross-pool guarantees are required. This is out of scope for C-9.

## Related

- [docs/plans/2026-09-26-impl-C-9-concurrency-limits.md](../plans/2026-09-26-impl-C-9-concurrency-limits.md) — implementation plan
- [docs/slos/2026-09-26-wireup-pool-dispatch.md](../slos/2026-09-26-wireup-pool-dispatch.md) — SLO targets
- `docs/runbooks/on_call_handbook.md` — escalation procedures
