---
status: active
role: canonical
kind: plan
date: 2026-11-21
last_reviewed: 2026-11-21
superseded_by:
topic: redis-stream-consumer-groups
title: "Task-orphan sweeper group hygiene — reclaim, prune, honest health"
requirements:
  - id: REQ-SWEEPERHYGIENE-001
    title: "The sweeper reads the messages it is delivered"
  - id: REQ-SWEEPERHYGIENE-002
    title: "The sweeper reclaims pending entries held by dead consumers"
  - id: REQ-SWEEPERHYGIENE-003
    title: "Zombie PEL entries left by stream trimming are purged"
  - id: REQ-SWEEPERHYGIENE-004
    title: "Stale consumers are pruned so the consumer table stays bounded"
  - id: REQ-SWEEPERHYGIENE-005
    title: "Recovered entries go through the same recovery path as live ones"
  - id: REQ-SWEEPERHYGIENE-006
    title: "Health reports the sweeper's real counters instead of a bare ok"
---

# Task-orphan sweeper group hygiene — reclaim, prune, honest health

## 1. Outcome

The `bodai-task-orphan-sweeper` consumer group on the `bodai:events`
Redis Stream stops accumulating garbage, and the sweeper starts doing
the job it was built for.

Concretely, after this ships:

- The sweeper **reads and recovers orphan handoffs**. Today it reads
  nothing at all: it delivered 18,198 messages into its group's
  pending list and acknowledged 5.
- `XPENDING bodai:events bodai-task-orphan-sweeper` reads **0** and
  stays near 0, instead of growing by one for every message the
  stream trimmed away.
- `XINFO CONSUMERS bodai:events bodai-task-orphan-sweeper` reads a
  small constant instead of growing by one per process start.
- `/health` reports the sweeper's counters, and reports `degraded`
  when the group is in a bad state.

## 2. Goals

1. Recover orphan-handoff events that were delivered to a consumer
   that died before acknowledging them — and, at the root, make the
   sweeper read the stream at all.
2. Purge PEL entries whose stream data has been trimmed away. These
   are permanently un-ackable and make every `XPENDING`/`XINFO
   CONSUMERS` call more expensive forever.
3. Keep the consumer table bounded by pruning consumers that no
   longer exist.
4. Make `/health` tell the truth about the sweeper's state.

## 3. Non-Goals

1. **Not** changing the `bodai:events` stream's trim policy. The
   publisher's `MAXLEN` is a separate decision; this plan makes the
   sweeper resilient to it.
2. **Not** changing the `mahavishnu-claude-observers` group. It has the
   same zombie-PEL shape (3,001 pending, all trimmed) but a stable
   consumer name, so it has no leak. It is a separate subscriber
   (`mahavishnu/core/events/bodai_subscriber.py`) that does not use
   this handle. Follow-up.
3. **Not** changing the sweeper's idempotency guard.
4. **Not** adding `reclaim()`/`delete_consumer()` to oneiric's
   `RedisStreamsQueueAdapter`. See §4.4.
5. **Not** wiring `settings/mahavishnu.yaml`'s `task_orphan_sweeper`
   block, which is dead config today — see §7.2.

## 4. Current Findings

All figures below were measured against the live Redis on 2026-11-21.

### 4.1 D0 — the sweeper read nothing (the root cause)

Oneiric's `RedisStreamsQueueAdapter._format_entries` normalises
coredis 6.x's `XREADGROUP` reply. coredis answers with a **mapping
keyed by the stream name as bytes**, holding `StreamEntry` objects
whose field names and values are also bytes. The adapter compares that
bytes key against the configured **str** stream name:

```python
for stream_key, messages in pairs:
    if stream_key != self._settings.stream:   # bytes != str, always
        continue
```

`b"bodai:events" != "bodai:events"` is always true, so **every entry
was discarded**. Proven against the installed adapter with a real
orphan in the stream:

```
adapter.read() -> []
LEN: 0
```

`XREADGROUP` delivers server-side, so the messages still landed in the
group's pending list — the sweeper just never saw them and therefore
never acked them. Measured: the stream reports `entries-added: 18203`
and `length: 14399` (3,804 trimmed away), and the group reported
**18,198 pending** — the sweeper had acked **5 messages ever**.

Consequences: no orphan was ever recovered; `entities_count` stayed
at 0; the pending list grew without bound; and `health()` reported
`healthy` throughout.

### 4.2 D1 — the consumer table grows by one per process start

`TaskOrphanSweeper.__init__` sets
`consumer=consumer_name or f"mahavishnu-{os.getpid()}"`. Redis
registers a consumer the first time it reads under a name, and never
expires it. Measured: **437 consumers**, of which **357 hold zero
pending**, with idle times up to **36 days**.

### 4.3 D2 — pending entries are never reclaimed

The sweeper reads with `streams={stream: ">"}`, which delivers only
*new* messages. An entry delivered to a consumer that died before
`XACK` stays in the PEL forever; nothing in the sweeper path ever
re-reads it. The sweeper's job is to recover orphaned handoffs, and it
never recovered any entry it had already taken delivery of.

### 4.4 D3 — stream trimming orphans the PEL

**Redis does not trim a group's pending list when the stream is
trimmed.** A `XTRIM`/`XDEL` of a message leaves its PEL entry behind,
pointing at an id that no longer exists: permanently un-ackable, and
invisible to `>` reads. Measured: the stream spans `2026-10-09` →
`2026-11-21` while the pending entries span `2026-09-16` → `2026-11-21`;
**0 of 200 sampled pending ids resolve in the stream**. Confirmed on a
scratch stream: after `XDEL`, `pending` stayed at 4; `XAUTOCLAIM` then
removed them.

### 4.5 D4 — health reports `healthy` while all of the above holds

`TaskOrphanSweeper.health()` returned `self._consecutive_read_failures
< 3` — it said nothing about the group. The live payload was
`task_orphan_sweeper: {"ok": true, "status": "healthy"}` while 18,198
entries were pending and 437 consumers had leaked. The sweeper's
docstring promised `entities_count` / `cycles_total` / `errors_total`
/ `last_updated_timestamp`; none of them reached the health payload.

### 4.6 The fix Redis already provides

`XAUTOCLAIM` does both jobs in one call, and the split is what makes
it safe:

- Entries that **still have data** come back in the *claimed* array,
  with their payload — these are the orphans to re-process.
- Entries whose **data is gone** come back in the *deleted-ids* array,
  and Redis removes them from the PEL as a side effect.

Measured on a scratch stream: with `min_idle_time=60000` and a
1.2-second-old entry, `claimed=0` but `deleted=['…']` — **the zombie
purge is independent of `min_idle_time`**. A single call with a safe
idle threshold therefore purges zombies unconditionally while
claiming only genuinely-stale live entries, and never steals work the
live process is still doing.

### 4.7 The working example

`akosha/akosha/ingestion/bodai_event_subscriber.py` already does all of
this for the same stream: a stable consumer name, `XAUTOCLAIM` with a
carried cursor, and `XGROUP DELCONSUMER` on stop — **guarded** so it
only removes a consumer that owns no pending messages ("a stale
consumer is recoverable, a destroyed message is not"). This plan
mirrors that proven pattern rather than inventing one.

### 4.8 Why the handle lives in mahavishnu, not in oneiric

`RedisStreamsQueueAdapter` (oneiric 0.39.0) exposes `read`, `ack`,
`enqueue` and `pending`, but not `xautoclaim` or `xgroup_delconsumer`.
Adding them there is the tidiest layering, but mahavishnu pins
`oneiric>=0.39.0`; adding public API to an already-published version
means a fresh `uv sync` installs oneiric 0.39.0 *without* those
methods and mahavishnu breaks. Per the publish-first rule, the oneiric
release is the operator's. The handle therefore lands in mahavishnu,
using **coredis** — already a direct dependency (`coredis>=6.9.0`,
`cache` group) and the same client the adapter uses, so no new
dependency is introduced.

## 4.9 Requirements

| ID | Requirement |
|----|-------------|
| REQ-SWEEPERHYGIENE-001 | The sweeper reads the messages it is delivered |
| REQ-SWEEPERHYGIENE-002 | The sweeper reclaims pending entries held by dead consumers |
| REQ-SWEEPERHYGIENE-003 | Zombie PEL entries left by stream trimming are purged |
| REQ-SWEEPERHYGIENE-004 | Stale consumers are pruned so the consumer table stays bounded |
| REQ-SWEEPERHYGIENE-005 | Recovered entries go through the same recovery path as live ones |
| REQ-SWEEPERHYGIENE-006 | Health reports the sweeper's real counters instead of a bare `ok` |

## 5. Implementation Phases

### Phase 1: The group handle

**Goal:** A focused, testable owner-side handle for a Redis Stream
consumer group — the thing the adapter should have been.

**Tasks:**
- New `mahavishnu/core/events/redis_stream_group.py`:
  - `read()` — normalises coredis's reply, **decoding the stream key
    and the field names/values to text**, which is the D0 fix.
  - `ack()`, `enqueue()`.
  - `reclaim(min_idle_ms, count, max_rounds)` → `ReclaimResult`
    (claimed entries + purged zombie ids).
  - `prune_consumers(keep, prefix, stale_after_ms)` → names removed.
  - `group_state()` → `GroupState` (pending, consumers, lag).
  - `init()` — opens the pool and **creates the consumer group**;
    every command against a group that does not exist fails with
    NOGROUP, the read included.
- The client is injectable so tests never touch Redis.

**Exit criteria:** 21 unit tests, each pinned to one behaviour.

#### Integration Contract

- **Triggered from**: `RedisStreamGroup.read` / `.ack` / `.enqueue` /
  `.reclaim` / `.prune_consumers` / `.group_state`, called by
  `TaskOrphanSweeper`.
- **Returns to / updates**: the `bodai:events` stream's
  `bodai-task-orphan-sweeper` consumer group — its PEL and its
  consumer registry.
- **Demonstrable by**: `pytest tests/unit/core/events/test_redis_stream_group.py -v`.
- **Rollback signal**: `RedisStreamGroup` raising on every call —
  the sweeper logs `task_orphan_sweeper: hygiene pass failed` and
  keeps reading; no message is lost.
- **Observability added**: `reclaimed_total`, `purged_total`,
  `pruned_consumers_total`, `pending_last`, `consumers_last`.

### Phase 2: The sweeper maintains its group

**Goal:** The sweeper reads through the handle, reclaims, prunes, and
re-processes what it reclaims.

**Tasks:**
- `TaskOrphanSweeper` owns a `RedisStreamGroup` for its group.
- `init()` runs one hygiene pass (reclaim, then prune) before the read
  loop starts.
- `_run_once()` runs a hygiene pass every `hygiene_interval_cycles`
  cycles, and feeds reclaimed entries through the **same** per-entry
  recovery path as live entries (REQ-SWEEPERHYGIENE-005).
- Prune order is **reclaim first, then prune**, so a message is never
  destroyed before it has had a chance to be recovered.
- `health()` returns `False` when the read-failure streak reaches 3
  **or** the hygiene-failure streak reaches 3.

**Exit criteria:** Unit tests prove a claimed orphan is recovered and
acked, a zombie is purged, a stale consumer is pruned, a consumer
holding pending is kept, and `health()` degrades on hygiene failure.

#### Integration Contract

- **Triggered from**: `TaskOrphanSweeper.init()` and
  `TaskOrphanSweeper._run_once()` (via `run_forever()`), spawned by
  `mahavishnu/mcp/lifecycle.py:start_server`.
- **Returns to / updates**: the `bodai:events` stream group; and, for
  reclaimed orphans, the session-buddy task record's `workflow_id`
  (via `tasks_link_workflow`).
- **Demonstrable by**: `pytest tests/unit/test_task_orphan_sweeper.py -v`
  and `pytest tests/integration/test_task_orphan_sweeper_e2e.py -v`.
- **Rollback signal**: `task_orphan_sweeper: hygiene pass failed`
  appearing on every cycle — the sweeper keeps reading and acking, so
  the failure is inert; revert the branch.
- **Observability added**: the five counters above, surfaced in
  `/health` (Phase 3).

### Phase 3: Honest health

**Goal:** `/health` stops saying `healthy` when the sweeper's group is
in a bad state, and starts carrying the counters.

**Tasks:**
- `TaskOrphanSweeper.feed_state()` — the feed owns the shape of its
  own numbers, mirroring `plan_index`'s `as_dict()`, so the health
  endpoint never has to know which attribute holds which counter.
- Extend the `task_orphan_sweeper` check in
  `mahavishnu/mcp/bootstrap.py` with it.
- `TaskOrphanSweeper.health()` reflects hygiene failures.

**Exit criteria:** A test asserts the health payload carries the
counters, and that a sweeper whose hygiene keeps failing reports
`degraded`.

#### Integration Contract

- **Triggered from**: `GET /health` (and the MCP `get_health` tool,
  which shares the builder).
- **Returns to / updates**: the `checks.task_orphan_sweeper` entry of
  the `/health` body.
- **Demonstrable by**: `curl -s http://127.0.0.1:8680/health | jq
  .checks.task_orphan_sweeper`.
- **Rollback signal**: `/health` flipping to `degraded` in a healthy
  fleet — the sweeper's counters would be miscounting.
- **Observability added**: `pending_total`, `consumers_total`,
  `reclaimed_total`, `purged_total`, `pruned_consumers_total` in the
  health payload.

### Phase 4: Live cleanup

**Goal:** The live group's garbage is actually removed.

**Tasks:**
- Run one hygiene pass against the live group (reclaim → prune).
- Re-measure: `XPENDING` and `XINFO CONSUMERS` before/after.
- Record the before/after numbers in this plan.

**Exit criteria:** `XPENDING` reads 0; `XINFO CONSUMERS` reads a
small constant; the live `/health` shows the counters moving.

## 6. Required Code Changes

- [x] `mahavishnu/core/events/redis_stream_group.py` (new)
- [x] `mahavishnu/mcp/sweepers/task_orphan_sweeper.py` (modify)
- [x] `mahavishnu/mcp/bootstrap.py` (modify — health check payload)
- [x] `tests/unit/core/events/test_redis_stream_group.py` (new)
- [x] `tests/unit/test_task_orphan_sweeper.py` (modify)
- [x] `tests/integration/test_task_orphan_sweeper_e2e.py` (modify)
- [x] `tests/integration/plan_index/test_health_check_aggregates.py` (modify)

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence |
|---|---|---|
| `pytest tests/unit/core/events/test_redis_stream_group.py` | 21 passed | Phase 1 |
| `pytest tests/unit/test_task_orphan_sweeper.py` | passed | Phase 2 |
| `pytest tests/integration/test_task_orphan_sweeper_e2e.py` | passed | Phase 2, live Redis |
| `pytest tests/integration/plan_index/test_health_check_aggregates.py` | passed | Phase 3 |
| Related suite (lifecycle, server_core, events, plan_index) | 174 passed, 5 skipped | Phase 3 |
| `crackerjack run -v -f` | exit 0 | merge gate |
| `XPENDING bodai:events bodai-task-orphan-sweeper` | 0 | Phase 4 |
| `XINFO CONSUMERS bodai:events bodai-task-orphan-sweeper` | small constant | Phase 4 |
| `curl -s http://127.0.0.1:8680/health` | counters present | Phase 3 |

### 7.1 Defects found but not fixed here

1. **oneiric's `RedisStreamsQueueAdapter._format_entries` still drops
   every entry** for any consumer that uses `read()` with coredis 6.x.
   The sweeper no longer depends on it, but the adapter is public API
   in oneiric and the bug is live there. The fix is one line —
   compare the stream key as text — but it needs an oneiric release
   before mahavishnu's pin is satisfied, which is the operator's call.
2. **`settings/mahavishnu.yaml`'s `task_orphan_sweeper` block is dead
   config.** `lifecycle.py` constructs the sweeper with only
   `session_buddy_client=`, so `enabled`, `stream`, `consumer_group`,
   `block_ms` and `count` are never read. The constructor's defaults
   happen to match the file's values, which is why nobody noticed.

### 7.2 The e2e test was already broken

`tests/integration/test_task_orphan_sweeper_e2e.py` asserted that
`tasks_update` was called with `metadata={"workflow_id": ...}` — the
shape that never bound anything. The sweeper moved to the typed
`tasks_link_workflow` channel in `61f5916a` and the test was never
updated, so it has been failing on `main` since. Verified by running
it in the main checkout against HEAD's sweeper: the same
`AssertionError: expected one tasks_update, got 0`. The test is
updated here to the typed channel, and now proves the recovery
end-to-end against live Redis for the first time.

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Reclaiming steals an entry the live process is mid-flight on | Low | `min_idle_ms` well above any single entry's processing time; the live consumer is never pruned |
| `XGROUP DELCONSUMER` destroys an unrecovered message | Low | prune only after reclaim, and only consumers with `pending == 0` (akosha's guard) |
| A hygiene pass raises and takes the sweeper down | Low | hygiene runs inside its own try/except; the read/ack path is untouched |
| Reclaimed orphan is processed twice | Low | the sweeper's existing idempotency guard (`_is_already_handed_off`) makes a repeat a no-op |
| The live cleanup races the running sweeper | Medium | reclaim only claims entries idle beyond the threshold; the live consumer is `keep`-listed |

## 8.5 Phase 5 — hardening (security review)

A security review of the merged branch raised four findings against
the new code. All four are addressed here.

**H1 — a failed probe was published as a zero.** `group_state()`
returned an empty `GroupState` and `prune_consumers()` returned `[]`
when their Redis command raised, so "could not be determined" was
indistinguishable from "nothing is wrong" and the health body read as
pristine on a group that could not be inspected. Both now raise; the
sweeper counts the failure in its hygiene streak and leaves the last
known values in place. `feed_state()` publishes `pending_total: None`
and `consumers_total: None` when the last probe failed, plus a
`group_state_ok` flag, so the body cannot read as clean on a group
nobody measured.

**H2 — the prune could destroy a message.** `XGROUP DELCONSUMER`
returns how many pending messages the consumer owned; a non-zero
return means messages that were never acknowledged have just become
unrecoverable. The listing that precedes the delete is inherently
racy — a consumer can take delivery of a message in between. The
consumer's own pending list is therefore re-read immediately before
the delete, and a consumer that owns anything is left in place.

That re-check was itself a race: reading the pending list and
deleting the consumer are two commands, so an `XREADGROUP` could
interleave between them. The check and the delete are now **one
atomic server-side operation** — a Lua script that calls `XPENDING`
for that exact consumer and calls `XGROUP DELCONSUMER` only when the
result is empty. Redis runs a script atomically, so no read can
interleave. Verified against Redis 7.4 through the real code path: a
consumer holding a pending message is left in place, and a consumer
with none is removed.

The delete's return value is still captured, logged at ERROR, counted
in `destroyed_messages_total`, and surfaced in the health payload, so
a loss that slips past the script is visible rather than silent.

**H3 — the bound was on the scan, not the work.** The reclaim
accumulated every claimed entry, and each entry costs several round
trips, so a large backlog could monopolise the event loop in one
pass. `max_entries` now bounds the entries handed back; the scan
continues past the cap so the zombies beyond it are still purged, and
the surplus stays pending for a later pass. The sweeper also yields
between entries.

**H4 — a transient failure was acked away.** The sweeper acked every
entry after the recovery attempt, success or failure. A session-buddy
timeout therefore dropped the handoff permanently — the one thing the
sweeper exists to prevent. The ack is now reserved for outcomes that
will never change: a successful recovery, an already-handed-off task,
an orphan with no workflow id, and a malformed payload (which is
permanent and is logged at ERROR). A transient failure leaves the
entry pending, and the reclaim retries it once it has been idle long
enough.

The at-most-once contract is therefore refined rather than dropped: it
still holds for every terminal outcome, and it no longer discards work
that a later attempt could still complete. The contract was a code
decision, not a requirement of the v1.1 task-system spec.

## 9. Decision Rule

Done when: the live group's `XPENDING` reads 0 and its consumer count
is a small constant, the health payload carries the sweeper's counters,
the scoped test suite and the Crackerjack gate pass, and the branch is
squash-merged to local `main`.

If scope must be cut, cut in this order: Phase 3's counter surfacing
(keep the `health()` degradation), then Phase 2's periodic pass (keep
the init-time pass). Phase 1 and Phase 4 are the irreducible core —
without Phase 1 the sweeper still reads nothing, and without Phase 4
the live garbage stays.
