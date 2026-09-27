# Runbook: Worktree Isolation (C-8)

Operational guide for the `pool_route_execute(worktree=WorktreeOptions(...))` feature. Per no-backcompat policy, `worktree_storage.enabled: false` is the kill switch — all calls fall back to host-isolation (no worktree, repo edited directly).

## When to use this runbook

- `worktree_creation_total{result="lock_conflict"}` rate spikes
- Operators see `worktree_conflict` envelopes in Akosha
- Idempotency store unavailable while worktree-isolated dispatch is in flight
- Disk usage from worktrees climbs (`worktree_disk_bytes` gauge)

## Scenario 1: `worktree_conflict` envelope flood

**Symptoms:**

- Akosha receives `anomaly.detected` events with `anomaly_type: worktree_lock_conflict`
- `worktree_creation_total{result="lock_conflict"}` rate >0.5/s for 5m
- `pool_route_execute_total{result="worktree_conflict"}` rate >0.1/s

**Diagnosis:**

1. Check active worktrees: `psql $DATABASE_URL -c "SELECT count(*) FROM audit.worktree_registry WHERE state='active'"`
1. Check lock holder: `git worktree list --porcelain | grep locked`
1. Check if the lock holder is hung: `ps -p <pid>` (the pid is in the worktree_registry row)
1. Verify dispatch concurrency: `cat settings/mahavishnu.yaml | grep -A5 worktree_storage`

**Recovery:**

1. **If lock holder is hung**: `kill -TERM <pid>`; the `finally` block in `pool_route_execute` cleans up the worktree
1. **If lock holder is a misbehaving test**: `pytest --collect-only` to find orphaned tests; cancel them with `pytest --exitfirst`
1. **If concurrent dispatches are over-subscribed**: lower `worktree_storage.max_concurrent` in settings; restart Mahavishnu
1. **If disk is full**: `git worktree remove --force <path>` for stale worktrees; check `worktree_disk_bytes > 80%` alert

**Verification:**

- `worktree_creation_total{result="lock_conflict"}` rate \<0.1/s within 5 minutes
- `worktree_active_count` returns to baseline within 1 minute
- No new `worktree_conflict` envelopes

**Postmortem template:**

- Lock holder PID + command
- Concurrent dispatch count at incident time
- Worktree base branch + repo nickname
- Whether `worktree_storage.max_concurrent` was appropriate for the workload

## Scenario 2: Idempotency store unavailable during worktree dispatch

**Symptoms:**

- `pool_route_execute` returns `{"status": "error", "error": "idempotency store unavailable"}`
- `eventbridge_publish_total{result="skip"}` rate increases (because safe_publish returns False on idempotency failure)
- No `worktree_created` Akosha envelopes (because the idempotency check happens BEFORE worktree creation)

**Diagnosis:**

1. Check `IdempotencyCircuitBreaker` state (if exposed) or `eventbridge_publish_total{result="error"}` rate
1. Check EventStore health: `curl http://localhost:8680/health | jq .event_store`
1. Check DB connection: `psql $DATABASE_URL -c "SELECT 1"` (round-trip latency should be \<10ms)

**Recovery:**

1. **If circuit breaker open**: wait for cooldown (default 30s); subsequent calls fast-fail until cooldown expires
1. **If DB unreachable**: `pg_ctl restart` or failover to replica (operator-specific)
1. **If EventStore has a transient bug**: restart Mahavishnu; idempotency state is durable in DB, no data loss

**Verification:**

- `eventbridge_publish_total{result="error"}` rate \<0.05/s
- `pool_route_execute` returns success on retry
- `worktree_created` Akosha envelopes resume

## Scenario 4: Idempotency circuit OPEN >5 minutes (FIX round-7 Tier 2)

**Symptoms:**

- `idempotency_circuit_state` gauge = 1 for >5 minutes (per SLO alert)
- `idempotency_circuit_transitions_total{transition="open"}` rate elevated
- `pool_route_execute_total{result="error"}` rate elevated with `error: "circuit open; event store unreachable"`
- All idempotent dispatches fast-fail; non-idempotent dispatches continue

**Diagnosis:**

1. Confirm circuit state: `curl http://localhost:8680/metrics | grep idempotency_circuit_state`
1. Check EventStore health: `curl http://localhost:8680/health | jq .event_store`
1. Check DB latency: `psql $DATABASE_URL -c "SELECT 1"` (round-trip should be \<10ms)
1. Check if circuit is in cooldown probe: `idempotency_circuit_transitions_total{transition="half_open"}` — frequent probes indicate sustained outage

**Recovery:**

1. **If DB genuinely down**: fix the DB outage first; circuit will self-recover on next successful probe after cooldown (default 30s)
1. **If circuit threshold too aggressive** (transient blips trip it): raise `idempotency.failure_threshold` in settings; restart Mahavishnu
1. **If probe storm overwhelming sick DB**: increase `idempotency.cooldown_seconds` to reduce probe frequency; restart Mahavishnu
1. **Restart clears in-memory breaker** but does NOT fix the underlying outage — restart only helps if the breaker is itself stuck (rare; bug)

**Verification:**

- `idempotency_circuit_state` gauge returns to 0 within 1 cooldown cycle
- `pool_route_execute_total{result="duplicate"}` rate resumes (idempotent dispatches start working again)
- `idempotency_circuit_transitions_total{transition="closed"}` increments at least once

## Scenario 3: Worktree leak detection

**Symptoms:**

- `worktree_disk_bytes` gauge grows monotonically over 24h
- `worktree_active_count` > `worktree_storage.max_concurrent` (impossible per spec)
- `ls ~/.local/share/mahavishnu/worktrees/` shows directories older than `ttl_seconds`

**Diagnosis:**

1. List worktrees by age: `find ~/.local/share/mahavishnu/worktrees/ -maxdepth 1 -type d -mmin +1440 | sort`
1. For each stale worktree, check whether the owning dispatch is still running: `ps aux | grep <branch_name>`
1. If no process holds the worktree, it's a leak (the `finally` block failed or the process was killed)

**Recovery:**

1. **Manual cleanup**: `git worktree remove --force <path>` for each leaked worktree
1. **Verify**: `git worktree list --porcelain` shows only active worktrees
1. **If leaks recur**: file a bug — the `finally` block in `pool_route_execute` may not be running on signal interrupts (consider adding `asyncio.shield()` around the cleanup call)

**Verification:**

- `worktree_disk_bytes` decreases to baseline
- `worktree_active_count` matches expected concurrent dispatches
- `git worktree list` shows no orphans

**Postmortem template:**

- Stale worktree count + total disk
- Time-to-leak (worktree creation time vs current time)
- Whether owner process was alive (and if so, what it was doing)
- Whether `finally` block ran in the trace logs

## Related

- [docs/adr/0001-mahavishnu-niche.md](../adr/0001-mahavishnu-niche.md) — niche filter that motivated the worktree REPLACEMENT
- [docs/plans/2026-09-26-impl-C-8-worktree-isolation.md](../plans/2026-09-26-impl-C-8-worktree-isolation.md) — implementation plan
- [docs/slos/2026-09-26-wireup-pool-dispatch.md](../slos/2026-09-26-wireup-pool-dispatch.md) — SLO targets
- `docs/runbooks/on_call_handbook.md` — escalation procedures
