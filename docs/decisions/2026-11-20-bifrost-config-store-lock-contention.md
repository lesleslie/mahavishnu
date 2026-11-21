---
status: active
role: canonical
date: 2026-11-20
last_reviewed: 2026-11-20
topic: bifrost-config-store-contention
title: "Bifrost's config-store write contention is upstream, and it is a hygiene problem rather than an availability one"
---

## Context

The Bifrost gateway logs `database is locked` when one of its background jobs
cannot take the config store's write lock. The errors were first noticed on
2026-11-20 while upgrading the transport pin to v2.6.0, and they are
**not** a consequence of that upgrade.

**What the count actually is.** 316 occurrences, of which **309 fall in
November 2026** (1 on 2026-08-29, 4 on 2026-09-05, 2 on 2026-10-31). The
daily shape is bursty and not uniform: 96 on Nov 5, 104 on Nov 13, 53 on Nov
17, 24 on Nov 16, 19 on Nov 7, and 2 on Nov 20.

**Which database.** Every one of the 316 is a **config-store** operation.
Not one is a log-store write, which is the 675 MB `logs.db`. The failing
operations are all background jobs:

| count | operation |
|---:|---|
| 127 | per-user OAuth flow sweep |
| 79 | temp-token sweep |
| 35 | pricing sync (33) and background pricing sync (2) |
| 33 | background model-parameters sync |
| 26 | per-user headers expired-flow sweep |
| 9 | push-relay prune of terminal deliveries |
| 5 | virtual-key expiry cleanup |

**Why they lose the race.** Both stores are already in WAL mode. The reason
they still fail is `PRAGMA busy_timeout` = **0** on the config store: a
writer that cannot take the lock fails *immediately* rather than waiting for
the holder to release it. `busy_timeout` is a per-connection setting, so it
lives in Bifrost's Go code and cannot be changed from outside the process.

**It is not startup contention.** The failures are spread one or two per
minute across *hours* (Nov 13 ran from 00:49 to 05:13; Nov 17 from 04:54 to
06:32), not clustered in a burst. Only 1% of them fall within ±120 s of a
gateway boot. So something holds the write lock for long stretches and the
scheduled jobs lose every time they tick. The dashboard is not the holder:
on Nov 13 and Nov 17 the browser accounted for 65 and 120 requests against
9,099 and 6,617 API calls, and 10–12 WebSocket sessions.

**What it does and does not break.** It does **not** break provider
resolution — `could not auto resolve a provider` has zero occurrences, and
the `text-embedding-3-large` round trip resolves and embeds normally. It
does **not** break the model catalogue: the `falling back onto the static
datasheet` message has not appeared since 2026-04-08, months before this
started. What it *does* leave undone is **housekeeping**: expired OAuth
flows, expired temp tokens, expired per-user header flows, expired virtual
keys and old push-relay deliveries are not deleted on their sweep schedule,
so they accumulate.

## Decision rule

**Treat it as a hygiene problem, not an availability one, and do not
attribute it to whatever change happens to be running.** Three rules follow.

1. **Do not chase it as a regression.** A lock error in the gateway log on
   the day of a transport upgrade is not evidence that the upgrade caused
   it. The counts here predate v2.6.0 by three months, and the transport
   binary is not a writer of the config store.
2. **Do not treat it as invisible.** The gateway's own `/health` reports
   `db_pings: ok` while the sweeps are failing, because a ping tests
   connectivity and not contention, and nothing in the request path reads
   the sweeps. The only place the failure is recorded is the gateway's
   stderr, so that is where the fleet reads it: `mahavishnu bifrost
   status` reports the count of failed background writes in the last 24
   hours and the timestamp of the most recent one.
3. **Do not try to fix it from here.** `busy_timeout` is per-connection and
   lives upstream; the fleet does not write the config store at all (only
   `mahavishnu bifrost rebootstrap --drop-db` and the lifecycle backup
   touch it). The durable fix is upstream — Bifrost's background jobs
   should wait on `SQLITE_BUSY` rather than fail — so that is a report to
   `maximhq/bifrost`, not a patch here.

**What would change this assessment.** A `could not auto resolve a
provider` or `falling back onto the static datasheet` line appearing
alongside the lock errors would move this from hygiene to availability, and
the report would become urgent rather than informational.

## Status

Active — detected and surfaced 2026-11-20. `mahavishnu bifrost status`
reports the contention count (`config_store_contention()` in
`mahavishnu/bifrost/gateway.py`, covered by
`tests/unit/test_bifrost_transport_exec.py`). The upstream report to
`maximhq/bifrost` is **not** filed: it is an outward-facing action and needs
the operator's go-ahead.
