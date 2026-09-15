---
title: Health Reason Codes
status: active
role: runbook
date: 2026-09-15
last_reviewed: 2026-09-15
superseded_by: null
blocks_on: []
topic: health-aggregator
---

# Health Reason Codes Runbook

Phase 4 of
[`docs/plans/2026-09-14-common-mcp-client-transport-unification.md`](../plans/2026-09-14-common-mcp-client-transport-unification.md)
replaces the per-repo hand-rolled ``ok=True/False`` health probes
with a canonical aggregator:
[`mcp_common.health.aggregator.aggregate_feed_states`](https://github.com/lesleslie/mcp-common/blob/main/mcp_common/health/aggregator.py).
Each data feed surfaces a per-feed ``status`` (one of
``healthy`` / ``warming_up`` / ``degraded`` / ``failed``) and a list of
``reason_codes`` drawn from the
[`ReasonCode`](https://github.com/lesleslie/mcp-common/blob/main/mcp_common/health/feed.py)
enum. Operators triaging a ``/health=503`` incident see this runbook's
per-reason-code guidance to know what action to take.

## Quick reference

| ReasonCode                     | Status     | Severity | Action |
|--------------------------------|------------|----------|--------|
| `warming_up_empty_feed`        | warming_up | monitor  | none — producer is loading data |
| `feed_never_populated`         | degraded   | investigate | producer broke on first cycle (HNSW hardening) |
| `error_within_halflife`        | degraded   | investigate | upstream regression inside the halflife window |
| `recent_error_in_window`      | degraded   | investigate | same as `error_within_halflife`; redundant surfacing |
| `error_outside_halflife`       | healthy    | ignore   | transient error decayed past halflife |
| `ingester_not_running`         | failed     | escalate | producer task died; restart may be needed |

The remaining `ReasonCode` enum values
(`warming_up_never_cycled`, `no_producer_ever_cycled`,
`producer_not_alive`) are forward-compatibility slots reserved for
future use; current probes don't emit them.

---

## `warming_up_empty_feed`

**What you see**: feed reported as `warming_up`; HTTP ``/health`` returns
200 (warming_up is intentionally NOT a 503 so the launchd wrapper
isn't taken down during normal startup).

**What it does NOT mean**: the producer is broken. The producer is
alive, has cycled at least once, and is mid-stride to filling the
feed. ``entities_count=0`` is the normal startup state.

**Action to take**: monitor for 60 seconds. If the feed stays
warming_up for longer than 5 minutes, see ``feed_never_populated``
(the HNSW hardening case).

**Action explicitly NOT to take**: do not restart the server. The
producer is alive; restarting won't help.

**When to escalate**: warming_up persists >5min AND
`cycles_total > 0` AND `last_poll_at` is recent → the producer is
alive but the data pipeline is broken. Open an incident.

---

## `feed_never_populated`

**What you see**: feed reported as `degraded`; HTTP ``/health`` returns
503. The aggregator's HNSW hardening surfaces this for a producer
that reports ``ingester_running=True`` but has never completed a
single cycle (cycles_total=0).

**What it does NOT mean**: this is NOT the normal warming_up state.
A producer in this state is broken-before-first-success — it
started but the very first cycle raised an exception, so
``cycles_total`` never advanced.

**Common root causes** (ak osha-specific examples):
- HNSW-on-DuckDB index creation failure on first ingest attempt
  (fixed in Phase 5 of the unification plan — see CHANGELOG
  ``0.17.4``).
- pgvector backend misconfigured (wrong ``DATABASE_URL``,
  missing ``storage-pg`` dependency group).
- Session-Buddy endpoint unreachable from the MCP server (wrong
  ``SESSION_BUDDY_MCP_URL``, Session-Buddy not started).

**Action to take**: read the akosha stderr log
(``~/.local/state/mcp/logs/akosha.err``) for the traceback that
fired on the first cycle. The traceback names the broken
dependency.

**Action explicitly NOT to take**: do not restart blindly. The
producer will fail the same way on the next cycle. Fix the
underlying dependency first.

**When to escalate**: traceback isn't reachable, OR the broken
dependency is shared across multiple producers → page the on-call.

---

## `error_within_halflife`

**What you see**: feed reported as `degraded`; HTTP ``/health`` returns
503. A producer recorded an error inside the time-bounded decay
window (default 300s = 5 minutes).

**What it does NOT mean**: the producer is permanently broken. A
single transient error within the halflife window can flip the
verdict; the next successful cycle will reset ``errors_within_window``
and clear the degraded state.

**Common root causes**:
- Upstream API rate limit hit briefly.
- Network blip on the producer's poll target.
- Embedding service transient unavailability.
- Database connection pool exhausted momentarily.

**Action to take**: read the producer's stderr log for the
exception. Most transient errors self-heal within the halflife
window; if the degraded state persists across two halflife windows
(10 minutes by default), treat it as a stuck producer — see
``feed_never_populated``.

**Action explicitly NOT to take**: do not restart unless the
degraded state persists >10min. A restart loses the watermark
state and may cause data re-ingestion.

**Disable-decay escape hatch**: if a known upstream regression is
firing repeated transient errors that would otherwise mask real
downstream faults, start the server with
``--health-disable-decay``. This sets
``HEALTH_FEED_HALFLIFE_SECONDS=0`` and the aggregator stops
escalating transient errors to DEGRADED. Emits a WARNING at
startup + an OTel event ``health.aggregate.decay_disabled``.

**When to escalate**: degraded state persists >10min, OR the
underlying error is clearly upstream (network partition, third-party
API outage) → coordinate with the upstream team before escalating.

---

## `recent_error_in_window`

**What you see**: same as ``error_within_halflife``. This reason code
is emitted alongside ``error_within_halflife`` as a redundant
signal — both fire on branch 1 of ``is_healthy``. Operators reading
the JSON can identify either.

**Action to take**: see ``error_within_halflife``. The two codes
always co-occur.

---

## `error_outside_halflife`

**What you see**: feed reported as `healthy`; HTTP ``/health`` returns
200. The producer recorded an error, but the error timestamp is
older than the halflife window (default 300s ago). The aggregator
considers the error decayed.

**What it does NOT mean**: there is no error. The producer recorded
an error at some point in the past; the aggregator is reporting
that the error is no longer "recent" enough to escalate the feed.

**Action to take**: none. This is informational. If the operator
wants a clean slate, restart the server (clears the
``last_error_at`` watermark).

**Action explicitly NOT to take**: do not assume the feed is fully
healthy just because HTTP returns 200 — the body still surfaces
this code in the per-feed ``reason_codes`` array. Operators reading
the JSON should interpret the absence of ``error_within_halflife``
as "no recent errors".

---

## `ingester_not_running`

**What you see**: feed reported as `failed`; HTTP ``/health`` returns
503. The producer task is not alive (the asyncio task is
``done()``, cancelled, or never started).

**What it does NOT mean**: a transient blip. The producer task
either died unexpectedly or was never started by the lifespan.

**Common root causes**:
- Lifespan exited but the probe is still being called (process
  shutdown in progress — operators should ignore).
- ``AKOSHA_SKIP_*=1`` env var was set, suppressing the producer's
  start (intentional — operators set this for unit tests).
- Producer crashed on ``start()`` due to an unrecoverable import
  error or dependency failure.

**Action to take**: check the lifespan logs (``akosha`` /
``session-buddy`` / ``mahavishnu`` / ``dhara`` / ``crackerjack``
startup banner). If the lifespan logs show the producer starting
and then dying, the traceback is in stderr.

**Action explicitly NOT to take**: do not assume this is an
operator-configured skip (e.g., ``AKOSHA_SKIP_OTEL_INGESTER=1``)
without first checking the env vars. A producer that *should* be
running but isn't is a bug.

**When to escalate**: producer crashed during startup with an
unrecoverable error → page the on-call; the server is in a broken
state and needs a code fix, not just a config tweak.

---

## Forward-compatibility codes

These ``ReasonCode`` enum values are reserved for future use but
no current probe emits them:

- `warming_up_never_cycled` — reserved for a future probe shape
  that distinguishes "never cycled" (warming_up) from "never
  populated" (degraded). Current probes emit
  ``feed_never_populated`` directly via the HNSW hardening branch.
- `no_producer_ever_cycled` — reserved for a future probe shape
  that surfaces per-producer state in a multi-producer feed.
- `producer_not_alive` — synonym for ``ingester_not_running``;
  reserved for a future rename.

If you see these codes in production logs, the code is from a
newer ``mcp-common`` version that introduced them. Update this
runbook with the new action guidance.

---

## Related

- [`docs/plans/2026-09-14-common-mcp-client-transport-unification.md` §11](../plans/2026-09-14-common-mcp-client-transport-unification.md) — plan
  section that mandated this runbook.
- [`docs/followups/2026-09-14-akosha-hnsw-on-duckdb.md`](../followups/2026-09-14-akosha-hnsw-on-duckdb.md) — HNSW
  root cause for the original ``feed_never_populated`` symptom.
- PromQL alert rules in [`mahavishnu/config/prometheus/health_aggregator_alerts.yml`](../../config/prometheus/health_aggregator_alerts.yml)
  — wire ``runbook_url`` annotations to this page.

Co-Authored-By: Claude Code <noreply@anthropic.com>
