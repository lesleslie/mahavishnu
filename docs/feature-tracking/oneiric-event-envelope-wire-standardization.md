# Feature: oneiric-event-envelope-wire-standardization

**Owner:** Mahavishnu core
**Created:** 2026-07-14
**Last updated:** 2026-07-15
**Repo(s):** /Users/les/Projects/mahavishnu

## State — pick one

- [x] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **built** (code merged, no callers wired)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

## Wiring checklist

- [x] Entry point registered (`RedisEventTransport.publish` publishes canonical records; `subscribe_to_bodai_events` decodes them)
- [x] Trigger path identified (Pydantic `EventEnvelope` produced via internal factories → `RedisEventTransport.publish` → `EventBusConsumer.replay_pending` and `_on_pubsub_message` → `subscribe_to_bodai_events` callback → queue file → `mahavishnu metrics bodai`)
- [x] Returns / state updates land in expected destination (canonical wire records on Redis stream; queue JSON at `queue_path`; metrics CLI renders canonical source/timestamp)
- [x] End-to-end smoke check documented (`tests/integration/test_event_wire_e2e.py::test_pydantic_event_round_trips_through_wire_and_metrics_cli`)
- [x] Observability hook in place (four recorders in `mahavishnu/core/events/observability.py`: `record_wire_converted`, `record_wire_conversion_failed`, `record_legacy_decoded`, `record_wire_decode_failed`)
- [x] Rollback signal defined (see Rollback signal map below)

## Built (yes/no)

yes — merged into `main` at commit `bcc7aff` (24 files, +3110/-464 lines).

## Wired (yes/no)

yes — `tests/integration/test_event_wire_e2e.py` exercises the full path:
Pydantic event → canonical Redis record (`{"wire_format": "oneiric-v1", "envelope": msgspec_json}`)
→ `subscribe_to_bodai_events` callback fires → queue file persisted →
`mahavishnu metrics bodai --queue-path ...` renders canonical source and timestamp data.

## Trigger path

Pydantic `EventEnvelope` instances built through `mahavishnu/core/events/contract.py::create_event_envelope`
flow through `RedisEventTransport.publish` (default `wire_format="oneiric-v1"`).
The `EventBusConsumer` and `subscribe_to_bodai_events` consume those records.
Active EventBridge producer path: `mahavishnu/websocket/server.py` calls `set_eventbridge_publisher(...)`
when `MAHAVISHNU_EVENTBRIDGE_BRIDGE` is set, EventBridge is enabled, and dry-run is disabled.

## Integration point

- Redis stream records: `{"wire_format": "oneiric-v1", "envelope": <msgspec_json>}` on `bodai:events`
- Pub/sub channels: `<channel_prefix><topic>` where topic is the Oneiric envelope topic (e.g. `bodai:events:workflow.completed`)
- Subscriber queue file: `queue_path` argument to `subscribe_to_bodai_events`, JSON of Pydantic envelopes
- Metrics CLI: `mahavishnu metrics bodai --queue-path <path>` renders source and timestamp from canonical records

## End-to-end check

```bash
uv run pytest --no-cov tests/integration/test_event_wire_e2e.py -x
```

Asserts: canonical record shape on the Redis stream, subscriber `xack` after queue persistence,
CLI renders canonical source and queue-derived identifiers.

## Rollback signal map

| Signal | Surface |
|---|---|
| canonical conversion/round-trip failure | `record_wire_conversion_failed` in `mahavishnu/core/events/observability.py` |
| subscriber decode failures increase | `record_wire_decode_failed(consumer="bodai_subscriber", reason=...)` |
| resolver fails to populate concrete server publisher | `tests/unit/test_eventbridge_resolver.py::test_resolver_populates_real_server` |
| ack-matrix regression | `tests/unit/test_bodai_subscriber.py` (eight acknowledgement-matrix tests) |
| events vanish from `mahavishnu metrics bodai` | `tests/integration/test_event_wire_e2e.py` |
| latency/error baseline regression | deferred — no histograms in Phase 1 |

## Operational follow-ups

- **Legacy read retirement**: requires seven consecutive zero-use days in an enabled deployment
  (`MAHAVISHNU_BODAI_ACCEPT_LEGACY_WIRE=true`) and operator review. Track
  `record_legacy_decoded` counter; if zero for 7 days in a deployment with legacy enabled,
  schedule retirement.
- **Optional Redis transport wire-or-retire decision** (due **2026-08-14**):
  `RedisEventTransport` has no production constructor outside of `RedisEventTransport.publish`
  callers. If no production caller is registered by 2026-08-14, retire the transport and keep only
  the canonical conversion helpers.
- **Phase 3 envelope-retirement architecture review** (due **2026-09-14**):
  Pydantic `EventEnvelope` is retained in-process while Oneiric envelopes cross the wire boundary.
  Decide whether to retire the Pydantic form, retain both indefinitely, or migrate internal call sites.

## Conditional adoption (state → adopted)

The EventBridge producer is wired but not adopted. Promotion to `adopted` requires:

1. Operator sets `MAHAVISHNU_EVENTBRIDGE_BRIDGE` to a concrete destination
1. `MAHAVISHNU_EVENTBRIDGE_ENABLED` is true
1. `MAHAVISHNU_EVENTBRIDGE_DRY_RUN` is false

When all three hold for ≥1 day without `record_wire_conversion_failed` anomalies,
mark the feature as `adopted`.

## Next action

Schedule two calendar-driven reminders via CronCreate:

- 2026-08-13: Redis transport wire-or-retire decision reminder
- 2026-09-13: Phase 3 envelope-retirement architecture review reminder

(Owner: Mahavishnu core; date: 2026-07-15)

## Related

- Plan: `docs/plans/2026-07-14-oneiric-event-envelope-wire-standardization.md` (untracked; see commit-decision follow-up)
- Spec: `docs/superpowers/specs/2026-07-14-oneiric-event-envelope-wire-standardization-design.md`
- Merge commit: `bcc7aff` on `main`
- Feature commit: `f103bcc` on branch `agent-bridge-phase1`
- Final review: `.superpowers/sdd/final-review.md`
- Bridge review package: `.superpowers/sdd/review-bridge-phase1-5973d93..aa2c580.diff`
- E2E proof: `tests/integration/test_event_wire_e2e.py`

## Session-Buddy

- Reflection ID: r_session_buddy_reflection_pending (see CronCreate-mirror in `.claude/scheduled_tasks.json`)
- Saved at: 2026-07-15 (this run)
- Reflection content: `Feature oneiric-event-envelope-wire-standardization: state=wired, built=yes, wired=yes, blocker=conditional adoption requires operator setup, next=calendar reminders on 2026-08-13 and 2026-09-13`

## Post-creation decisions (2026-07-15)

| Decision | Resolution |
|---|---|
| `.superpowers/sdd/preserve/` (two pre-merge backup files) | Gitignored. Files retained on disk for archaeology. `.gitignore` updated with `.superpowers/sdd/preserve/` plus the related scratch patterns (`.superpowers/sdd/*.diff`, `.superpowers/sdd/progress.md`). |
| Untracked plan file `docs/plans/2026-07-14-oneiric-event-envelope-wire-standardization.md` | Remains untracked. User declined commit at this time. The file is referenced from this record as the canonical plan. |
| Full `uv run crackerjack run` gate | Skipped. Targeted pytest gate (394 tests) is the source of truth for this delivery. Awaiting Mahavishnu pool availability for a future observability-backed full gate. |
| Calendar reminders for 2026-08-13 and 2026-09-13 | Document-only. No `CronCreate` job. Future-me or operator must surface these by date when the deadlines approach. The dates are pinned here and in the durable calendar items above. |
