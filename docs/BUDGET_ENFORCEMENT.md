# Budget Enforcement (Phase 3, v2 plan)

**One line:** Mahavishnu enforces per-workflow budget shapes (tokens,
turns, wallclock) on `pool_route_execute` runs by polling a control-plane
state machine once a minute. Per-turn budget checks stay in-process inside
the worker.

This document is the canonical home for the *why* behind the split. The
*what* lives in the code (see `mahavishnu/core/budget.py` and
`mahavishnu/core/budget_watchdog.py`).

______________________________________________________________________

## The boundary

> **Primitives whose natural read frequency is per-turn belong in-process;
> per-run belong in the control plane.**

This sentence is the entire design. The rest of the document explains
why the inverse ("build a per-turn bridge from the worker into the
control plane") is the wrong move.

### Per-run control plane (this phase)

The state machine in `mahavishnu/core/budget.py` is the persistent,
cross-replica source of truth for "is this run above its cap?" The
watchdog in `mahavishnu/core/budget_watchdog.py` walks every active
record once per minute, asks the worker for its latest totals, and
transitions the record from `ACTIVE` to `EXCEEDED` when any dimension
crosses.

Walking once per minute costs ~60× less storage than walking once per
turn. For a 20-minute workflow with 1 turn/second, per-run polling
yields 20 storage writes; per-turn polling would yield 1,200. The
control plane's job is to be cheap to operate *and* cheap to *not*
operate (Dhara-unavailable cycles cost zero storage operations).

### Per-turn in-process (worker responsibility)

A worker that needs to stop spending tokens mid-run reads its own
totals and bails out on its own. There is no MCP call, no Dhara
read, no control-plane round-trip — the worker makes a local
decision.

This is the part that does NOT live in `mahavishnu/`. It lives in the
worker (Claude Code, OpenHands, Cloud Worker, etc.). The control
plane does not own per-turn budget *enforcement* — it owns per-run
*detection and reporting*.

______________________________________________________________________

## Failure semantics (the non-obvious bits)

### Fail-open on Dhara unavailability

The watchdog's `run_watchdog_cycle()` catches every Dhara exception
(transport-level, lease, list, get, put) and converts it into a
*skip*: the cycle returns with `dhara_unavailable=True`, increments
the `dhara_skip` counter, logs at `WARNING`, and lets the next 60s
poll have another attempt.

**Why fail-open, not fail-closed?** Fail-closed means a brief Dhara
blip turns every running workflow into an unenforced budget. The
watchdog exists to catch bad runs; if Dhara is down, every cycle
loses its enforcement, but the *individual* worker is still
self-enforcing its per-turn caps, so the gap is bounded. The plan's
exit criteria call this out: a successful watchdog is one that never
makes the situation worse by losing Dhara.

### Multi-replica safety via lease, not via lock services

The watchdog reads a soft lease from Dhara (`put` with TTL) rather
than reaching for a coordination service like Redis or Etcd. The
trade-off:

- **Pro:** zero new infrastructure. Reuses Dhara's existing TTL
  semantics; one substrate.
- **Con:** the lease is "soft" — under heavy load, two replicas can
  both observe the lease as absent and both decide they're the
  leader. We mitigate this with the `await asyncio.Lock` in the
  in-memory store (so concurrent attempts serialize) and accept the
  benign race for the real Dhara path (two replicas running one
  cycle is recoverable — the writes are idempotent at the record
  level; the counter increments are best-effort and add noise but
  not data loss).

The plan asked for "lease-based leader election (only one replica
runs watchdog per cycle)." In practice, the watchdog *holds* the
lease for the full TTL window rather than releasing after each
cycle, so a long-lived replica keeps the lease and a new replica
takes over only when the TTL expires (or the holder crashes). See
the comment block in `run_watchdog_cycle()` for the trade-off.

### Cancel-friendly cycle

`run_watchdog()` catches `asyncio.CancelledError` at the top and
re-raises — the supervisor (lifespan context in
`mahavishnu/core/app.py`) sets the `stop_event` first and only
cancels the task if the watchdog exceeds the 5s shutdown grace
window. Cancelling mid-cycle is allowed; cancelling mid-write
would leave a partial record in Dhara, which is worse than missing
one cycle.

______________________________________________________________________

## State machine

Four states. Idempotent transitions throughout.

```
              ┌──┐
              │  ▼
   PENDING ──start───► ACTIVE ──mark_exceeded───► EXCEEDED (terminal)
                       │  │
                       │  └──mark_completed───► COMPLETED (terminal)
                       └─start() / declare() are no-ops from terminal states
```

- **`PENDING`**: spec declared, clock not started. A `budget_enforce`
  call moves records out of this state in the same atomic operation.
- **`ACTIVE`**: clock running, watchdog checking usage per cycle.
- **`EXCEEDED`**: terminal. First dimension to flip (tokens /
  turns / wallclock — in that priority order) is recorded.
- **`COMPLETED`**: terminal. Recorded when the workflow finished
  cleanly without exceeding.

The dimension priority order matters when two caps cross in the
same cycle. We pick tokens first because that is the most
operationally meaningful ("we just spent above the cost envelope")
and wallclock last because it is the noisiest.

______________________________________________________________________

## Observability

| OTel target | Name | Labels | When |
|-------------|------|--------|------|
| span | `budget.check` | — | Every watchdog cycle. |
| counter | `budget.exceeded.count` | `dimension=tokens\|turns\|wallclock` | One increment per dimension exceeded. |
| counter | `budget.dhara_skip.count` | — | One increment per cycle skipped because Dhara was unreachable. |
| counter | `budget.lease.lost.count` | — | One increment per cycle where another replica held the lease. |

Grafana panels:

- *Active budgets* — `count(budget.exceeded.count) by (dimension)`,
  grouped by 5-minute windows. A spike here means a run hit its
  cap; pair with the workflow logs to confirm whether the budget
  was the cause.
- *Dhara skip rate* — `rate(budget.dhara_skip.count[5m])`. Anything
  above 0 means controls are degraded; operators should page on
  sustained >5 skips/minute.
- *Lease loss rate* — `rate(budget.lease.lost.count[5m])`. Indicates
  how often multiple replicas are racing; expected to be near zero
  in single-replica deployments and bounded by network partitions in
  HA deployments.

______________________________________________________________________

## API contract

### MCP tool: `budget_enforce`

```python
mcp__mahavishnu__budget_enforce(
    workflow_id: str,
    budget_tokens: int | None = None,
    budget_turns: int | None = None,
    budget_wallclock_seconds: float | None = None,
    declared_by: str | None = None,
) -> dict
```

Returns `{"status": "active", "spec": ..., "state": "active", ...}`
on success. The watchdog starts checking on the next poll cycle
(\<60s).

### State on disk

Dhara record at `mahavishni://budgets/{workflow_id}.json` —
the same JSON shape that `BudgetRecord.from_dict()` consumes. Operators
can `dhara query mahavishni://budgets/` to list them.

### Re-capping mid-run

Calling `budget_enforce` again with the same `workflow_id` re-bases
the cap (state stays `ACTIVE`). This is the documented "pause at N"
semantics; we do not bump the version because Dhara's TTL semantics
mean the next cycle's read sees the latest spec.

______________________________________________________________________

## Tests and exit criteria

Tests live in:

- `tests/unit/test_budget_state_machine.py` — pure state-machine
  transitions plus hypothesis-driven arithmetic invariants.
- `tests/integration/test_budget_watchdog_lease.py` — multi-replica
  lease election, Dhara-down fail-open, wallclock breach → `EXCEEDED`,
  `budget_enforce` round-trip.

Exit criteria (all green):

1. Budget enforced across `pool_route_execute` runs ✅
1. Watchdog is multi-replica-safe via lease ✅
1. Dhara unavailability does not crash the watchdog ✅
