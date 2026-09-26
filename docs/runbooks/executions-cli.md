# Runbook: Executions CLI (C-12)

Operational guide for `mahavishnu executions {list,show}` and the `--watch` polling mode. Per round-5 critique: `--watch` polls every 1 second with a 5-retry failure limit before exiting.

## Scenario 1: `--watch` loses DB connection for 5 retries

**Symptoms:**
- `mahavishnu executions show <exec-id> --watch` exits with `Watch lost connection after 5 retries; aborting` after ~5 seconds
- Operator sees `ERROR: <traceback>` on stderr
- No progress indication during the 5-second silent period

**Diagnosis:**
1. Check DB latency: `psql $DATABASE_URL -c "SELECT 1"` (round-trip should be <10ms)
2. Check `execution_events` table size: `psql $DATABASE_URL -c "SELECT count(*) FROM execution_events"`
3. Check whether the execution has many events (>1000): `--watch` re-fetches all events each poll; large executions are slow

**Recovery:**
1. **If DB transient**: the operator can re-run `--watch` after the DB recovers. The watch exits cleanly; subsequent runs succeed.
2. **If DB chronically slow**: investigate slow queries; check `pg_stat_statements` for the `execution_events` query plan
3. **If execution has 100k+ events**: add `--since-id <N>` (round-5 devops finding, not yet implemented) to resume from a known event id rather than re-fetching all events
4. **If the operator wants progress indication** while waiting: add stderr heartbeat (round-5 devops finding):
   ```python
   typer.echo("waiting...", err=True)  # every second while polling
   ```

**Verification:**
- Re-running `--watch` succeeds after the underlying issue is fixed
- 5-second silent period is replaced with progress heartbeat (after the round-5 fix lands)

## Polling-mode limitations (per round-5 critique)

The `--watch` flag uses 1s polling + 5-retry failure limit. **It is NOT a push-based subscription.** A future revision can add a WebSocket subscription path; until then, polling is the simplest viable implementation.

**Polling trade-offs:**

| Polling behavior | Operator experience |
|---|---|
| Event arrives within 1s of write | Acceptable for human-driven inspection |
| DB slow (5s query) | Watch falls behind by ~5s/event |
| DB unavailable | Watch exits after 5 retries (~5s of silent "watch appears hung") |

## Known issues (round-5 devops critique)

1. **No `--since-id` flag**: `--watch` re-fetches ALL events for the execution each poll. For an execution with 100k events, the operator must wait for the first poll to complete before new events arrive.
2. **No exponential backoff**: 1s × 5 = 5s of failure before exit. Add backoff if the operator wants longer retry tolerance.
3. **No progress indication**: terminal appears hung during retries. Add stderr heartbeat (`typer.echo("waiting...", err=True)`) to fix.

These are deferred to follow-up commits; the current `--watch` is functional but unrefined.

## Related

- [docs/plans/2026-09-26-impl-C-12-executions-cli.md](../plans/2026-09-26-impl-C-12-executions-cli.md) — implementation plan
- [docs/runbooks/on_call_handbook.md](./on_call_handbook.md) — escalation procedures
