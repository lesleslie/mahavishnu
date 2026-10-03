# Bodai Task System — v1.1 (deferred items)

> **Spec addendum to**: `2026-09-29-task-system-design.md` (the original v1 spec).
> All T1–T18 design decisions stand. This doc fills in three items the
> v1 spec explicitly deferred — T12 visibility_public follow-up, T4
> Redis event-stream publishing, and the v1.1 orphan sweeper.

**Goal:** Close out the three deferred items from the v1 release so the
task-system emits real events, recovers from dispatch-edge orphans, and
enforces the public/private visibility read boundary. Note: per

> [Decision #3](#decisions-resolved-from-brainstorming-2026-10-02) the
> `task.handoff_completed` event semantic shifts in v1.1 — it now fires
> when a task is *bound to a workflow_id*, not strictly when the workflow
> reports success. Read [Decisions Resolved](#decisions-resolved) row 3
> before consuming or filtering on it.

**Architecture:** Three repo-local edits, no new MCP server. session-buddy
gains the Redis publisher wiring + T12 visibility persistence fix;
mahavishnu gains the v1.1 orphan sweeper that consumes the stream the
publisher writes to (plus a 10-LOC subscriber patch to keep the existing
`/mahavishnu:status` slash command observing v1.1 events). oneiric's
`RedisStreamsQueueAdapter` is the shared transport — both repos already
depend on oneiric; no new dependency.

**Tech Stack:** Python 3.14, oneiric `RedisStreamsQueueAdapter` (transport),
FastMCP, Pydantic v2, `pytest-mock` for the fake publisher fixture.
**Glossary:**

- `oneiric.adapters.queue.redis_streams.RedisStreamsQueueAdapter` — the
  XADD / XREADGROUP transport; lifecycle via `init()`/`cleanup()`;
  per-call `enqueue(data)` and `read(...)`; per-message `ack(message_ids)`
  to clear XREADGROUP's PEL.
- `fastmcp.lifespan` — the async startup/shutdown hook pattern. In
  session-buddy it's overridden at
  `session_buddy/mcp/server.py:_lifespan_with_dhara_cleanup`; in
  mahavishnu wiring happens in `mahavishnu/mcp/lifecycle.py:start_server()`
  (mirroring the `plan_index` periodic runner pattern at lines 95-158).
- `RedisStreamsQueueSettings` — the oneiric `BaseSettings` with `stream`,
  `group` (named `consumer_group` in this spec for readability), and
  `pubsub_channel_prefix` (default `bodai:events:`, irrelevant for v1.1
  since task channels do not match).

**Spec:** This doc *is* the spec for v1.1. For v1 design decisions (T1-T17,
authz, skill frontmatter, two-call handoff flow, error surface rule,
rejected-alternatives table, etc.) see `2026-09-29-task-system-design.md`.

## Global Constraints (carry-overs from v1 + v1.1 addenda)

- **Sequenced merge to main, not PRs** per pre-1.0 merge policy
  (`bodai-pre-1.0-merge-policy.md`). Cross-repo order is enforced by
  the pin rule, not by a PR review gate.
  - **session-buddy merge first** (`T12` + `T4` + `BodaiEventsPublisher`).
  - **mahavishnu merge second**, gated by `session-buddy >= 0.31.0` pin
    in mahavishnu's `pyproject.toml`. The mahavishnu merge updates
    that pin from `>=0.30.0` to `>=0.31.0` (implementer does the pin;
    operator does the version field — see below).
- **Pin rule vs version rule** (per `feedback-mcp-common-version-bump-is-user.md`):
  - **Implementer** updates `dependencies` pins in `pyproject.toml`
    (the `session-buddy >= 0.31.0` constraint on mahavishnu's
    `[dependencies]` / `[dependency-groups].eco`).
  - **Operator (user)** updates the `version` field in `pyproject.toml`
    via `crackerjack run -p minor`. The implementer NEVER touches
    `version`. After merge, the operator runs `crackerjack run -p minor`
    to bump + publish.
- **Feature-flag fallback**: unchanged from v1 — `_publish_task_event`
  still no-ops when the publisher adapter is not wired (import-time
  guard). Sweeper degrades to a `/health` warning + no-op consume when
  Redis is unreachable.
- **Error surface rule**: session-buddy + akosha tools return error
  envelopes; mahavishnu tools raise typed exceptions. The sweeper (in
  mahavishnu) raises typed exceptions on Redis failure and surfaces
  degraded state on `/health`.
- **YAGNI**: no Redis pub/sub fallback, no at-least-once delivery
  semantics, no multi-stream layouts. Flat XADD fields on the existing
  `bodai:events` stream. At-most-once is acceptable because the sweeper
  is idempotent on re-link.
- **Backwards compat is forbidden pre-1.0** per
  `feedback-no-backwards-compat-pre-1.0.md`. Default
  `bodai_events.enabled=True`; the publisher is additive. Existing
  subscribers that don't handle the new shape get a 10-LOC patch (see
  [Cross-repo wire-up patches](#cross-repo-wire-up-patches)).
- **No new memory file**: knowledge lives in session-buddy's existing
  reflection database; not in CC memory.

## Decisions resolved (from brainstorming 2026-10-02)

| # | Question | Decision |
|---|---|---|
| 1 | Who bumps versions? | **User (operator)** — implementer does NOT touch `version` |
| 2 | Envelope shape on `bodai:events` | **Flat XADD fields, no envelope wrapper.** Drop `oneiric-v1` envelope. Existing subscribers get a 10-LOC patch (see below). |
| 3 | Re-emit event for sweeper re-link | **Reuse `task.handoff_completed`** (accept semantic shift) |
| 4 | `bodai_events.enabled` default | **`True`** (additive) |
| 5 | Cross-repo merge model | **Direct merge to local main**, sequenced by pin rule (no PRs) |
| 6 (post-trio) | Subscriber backward-compat | **Add 10-LOC patch** to `mahavishnu/core/events/bodai_subscriber.py:_decode_envelope` to accept flat-fields shape |
| 7 (post-trio) | `ack()` in sweeper | **Yes** — `await adapter.adapter.clear([message_id])` after successful recovery |
| 8 (post-trio) | Sweeper settings `block_ms`/`count` | **YAML-tunable** (matches other settings) |

______________________________________________________________________

## Item 1 — T12 visibility_public fix (bounded, session-buddy)

> T12 is a one-line visibility_public fix; no class skeleton or new module
> required. Items 2-3 below are larger in scope; the difference is not
> an oversight, it's the work each item actually requires.

### Bug

`tasks_tools._build_task` (T5) hardcodes `visibility="private"`, and
`tasks_tools._persist_task_update` (T6) does not write the `visibility`
field to the sidecar metadata. Net effect: a caller running
`tasks_update(visibility="public")` sees `task.visibility` updated in
the immediate return, but the next `_build_task` call still returns
`"private"` because the sidecar metadata dict lacks the field.

### Fix

1. `_build_task` in `session_buddy/mcp/tools/tasks_tools.py`: read
   visibility from `sidecar_meta.get("visibility", "private")` instead
   of hardcoding. Default `"private"` only when sidecar metadata is
   missing (not when it explicitly says `"private"`).
1. `_persist_task_update` in the same file: when the request includes
   `visibility`, write `{"visibility": request.visibility}` into the
   sidecar metadata dict.

### Tests

- Un-skip `test_tasks_search_enforces_visibility_public` (remove the
  `@pytest.mark.skip(...)` decorator at
  `tests/unit/test_tasks_tools.py:2022-2029`). The test is already
  complete and just needs the persistence + read path corrected to pass.
- Add unit test `test_tasks_user_team_visibility_persists` confirming
  `visibility="team"` round-trips through `_persist_task_update` →
  sidecar → `_build_task`. **Scope confirmed with user:** preserve
  current behavior for `team`; the security filter at
  `tasks_security.py:71` stays unchanged.

### Integration Contract (per `wire-up-contract.md`)

| Field | Value |
|---|---|
| **Triggered from** | `tasks_update(visibility=...)` mutation in `tasks_tools.py:tasks_update` |
| **Returns to / updates** | `sidecar_meta["visibility"]` field in session-buddy's reflection DB |
| **Demonstrable by** | `tests/unit/test_tasks_tools.py::test_tasks_search_enforces_visibility_public` + new `test_tasks_user_team_visibility_persists` |
| **Rollback signal** | log: `logger.warning("tasks_tools: visibility_public fall-back engaged: %s", exc)` if `_build_task` errors reading sidecar; existing test passes when visibility_default = "private" hardcoded |
| **Observability added** | Existing `task.updated` event includes `visibility` in the diff (v1 envelope change is automatic); no new OTel spans. |

______________________________________________________________________

## Item 2 — T4 (Bodai task #4) — Redis event-stream publishing (architectural, session-buddy)

### Status quo (v1)

`session_buddy/mcp/tools/tasks_events.py:publish_task_event` is a typed
no-op stub (`return` at line 160). The envelope schemas
(`TaskCreatedPayload`, `TaskUpdatedPayload`, `TaskCompletedPayload`,
`TaskHandoffStartedPayload`, `TaskHandoffCompletedPayload`,
`TaskHandoffOrphanPayload`) are already defined in the same module.
Both session-buddy's `tasks_tools.py` mutation tools and mahavishnu's
`tasks_handoff.py` route through this stub.

### Wire-up

**New module** `session_buddy/mcp/events/bodai_events_publisher.py`:

```python
class BodaiEventsPublisher:
    """Owns the oneiric Redis Streams adapter for the ``bodai:events``
    stream. Singleton on the FastMCP server (one per process).

    Lifecycle: ``_init_transport()`` on FastMCP startup (before the
    first request), ``cleanup()`` on shutdown, ``health()`` called by
    ``/health``.

    Failure semantics: ``_init_transport()`` exceptions are LOGGED +
    SWALLOWED — the server starts anyway and ``publish_task_event``
    no-ops. The mutation path (tasks_create, etc.) MUST NOT block on
    Redis. The publisher is enabled only by default
    (``bodai_events.enabled = True``) per
    ``feedback-no-backwards-compat-pre-1.0``.

    The publisher writes flat fields via ``adapter.enqueue()`` —
    ``channel`` is the event type (``task.created``, ``task.updated``,
    ``task.completed``, ``task.cancelled``, ``task.handoff_started``,
    ``task.handoff_completed``, ``task.handoff_orphan``); the rest of
    the payload is XADD'd as top-level fields (no envelope wrapper).
    Consumers (the v1.1 sweeper in mahavishnu) filter on the
    ``channel`` field without JSON-deserializing.

    Counter increment policy (§3 metrics per
    ``mcp-backend-wiring-discipline.md``):
      - ``cycles_total`` ticks on every ``publish()`` call attempt.
      - ``errors_total`` ticks on caught exceptions.
      - ``entities_count`` ticks on successful enqueue.
      - ``last_updated_timestamp`` updates on the most recent
        successful enqueue.
    """

    def __init__(
        self,
        *,
        stream: str = "bodai:events",
        consumer_group: str = "bodai-default",
        enabled: bool = True,
    ) -> None:
        # API-level name `consumer_group` maps to oneiric's `group`
        # field on RedisStreamsQueueSettings.
        self._settings = RedisStreamsQueueSettings(
            stream=stream,
            group=consumer_group,
        )
        self._adapter = RedisStreamsQueueAdapter(settings=self._settings)
        self.enabled = enabled
        # §3 counters (per mcp-backend-wiring-discipline §3)
        self.entities_count = 0
        self.cycles_total = 0
        self.errors_total = 0
        self.last_updated_timestamp: float = 0.0

    async def _init_transport(self) -> None:
        # If ``enabled`` is False, no-op.
        await self._adapter.init()

    async def init(self) -> None:
        # Outer try/except: log + no-op on any init failure. Mutation
        # path MUST NOT block on Redis.
        if not self.enabled:
            return
        try:
            await self._init_transport()
        except Exception as exc:
            logger.warning(
                "bodai_events: publisher init failed (degraded to no-op): %s",
                exc,
            )

    async def cleanup(self) -> None: ...

    async def health(self) -> bool:
        # True when (not enabled) OR (init succeeded AND last cycle ok).
        # ...

    async def publish(
        self,
        event_type: str,
        payload: BaseModel,
    ) -> str | None:
        # Returns the redis stream message id, or None if disabled /
        # not initialized / Redis error.
        if not self.enabled:
            return None
        self.cycles_total += 1
        try:
            data = {"channel": event_type, **payload.model_dump(mode="json")}
            message_id = await self._adapter.enqueue(data)
        except Exception as exc:
            self.errors_total += 1
            logger.warning(
                "bodai_events: enqueue %s failed: %s", event_type, exc,
            )
            return None
        self.entities_count += 1
        self.last_updated_timestamp = time.time()
        return message_id
```

**Settings** (config layer — `oneiric`-compatible):

```yaml
# session_buddy/settings/session-buddy.yaml (or local override)
bodai_events:
  enabled: true
  stream: "bodai:events"
  consumer_group: "bodai-default"
```

**Modify** `session_buddy/mcp/tools/tasks_events.py`:

- Keep the typed envelopes as-is.
- Add a module-level `_get_publisher() -> BodaiEventsPublisher | None`
  helper that returns the singleton (set by FastMCP server lifespan).
- `publish_task_event()` body: if `_get_publisher()` is `None`,
  return no-op (existing behavior, import-time safe). Else,
  `await publisher.publish(event_type, payload)` inside the existing
  try/except wrapper.
- **Add a new function** `publish_task_event_raw(event_type: str, payload: Mapping[str, Any])`
  for cross-package callers (mahavishnu's `tasks_handoff.py`) that
  already use `dict` payloads. Wraps `dict → BaseModel` via the
  appropriate envelope class (one of the existing payload classes)
  before publishing. Lookup table (see below). Resolves the
  typed-payload mismatch surfaced in the trio review.

```python
# Module-level entry — mapping event_type → BaseModel class.
# Add to session_buddy/mcp/tools/tasks_events.py.
_ENVELOPE_BY_EVENT_TYPE: dict[str, type[BaseModel]] = {
    "task.created": TaskCreatedPayload,
    "task.updated": TaskUpdatedPayload,
    "task.completed": TaskCompletedPayload,
    "task.cancelled": TaskCompletedPayload,  # reuses per v1 spec
    "task.handoff_started": TaskHandoffStartedPayload,
    "task.handoff_completed": TaskHandoffCompletedPayload,
    "task.handoff_orphan": TaskHandoffOrphanPayload,
}

async def publish_task_event_raw(
    event_type: str,
    payload: Mapping[str, Any],
    redis: Any = None,
) -> None:
    """Publish a task.* event with raw dict payload (cross-package API)."""
    payload_class = _ENVELOPE_BY_EVENT_TYPE.get(event_type)
    if payload_class is None:
        logger.warning("bodai_events: unknown event_type %r", event_type)
        return
    publisher = _get_publisher()
    if publisher is None:
        return
    try:
        # serialize_event_field on every string value (per v1 spec)
        sanitized = {
            k: serialize_event_field(v) if isinstance(v, str) else v
            for k, v in payload.items()
        }
        envelope = payload_class(**sanitized)
        await publisher.publish(event_type, envelope)
    except Exception as exc:  # noqa: BLE001 - publisher is best-effort
        logger.warning(
            "bodai_events: raw publish %s failed: %s", event_type, exc,
        )
```

**Modify** `session_buddy/mcp/server.py` (`_lifespan_with_dhara_cleanup`,
the documented FastMCP lifespan pattern):

- Inside the `try` block (mirror the existing `init_signer_feed_state`
  pattern at lines 332-358):
  ```python
  publisher = BodaiEventsPublisher(
      stream=settings.bodai_events.stream,
      consumer_group=settings.bodai_events.consumer_group,
      enabled=settings.bodai_events.enabled,
  )
  await publisher.init()  # already swallows internally
  tasks_events._publisher = publisher  # module-level singleton
  yield publisher
  await publisher.cleanup()
  ```
- Surface `publisher.health()` in the `/health` aggregate
  (returns 503 on degraded per `mcp-backend-wiring-discipline.md` §1).

**Modify** `mahavishnu/mcp/tools/tasks_handoff.py:_publish_task_event`:

- Switch from `publish_task_event(event_type, payload)` (BaseModel
  required) to `publish_task_event_raw(event_type, payload)` (dict
  accepted). Body is otherwise unchanged.

### Failure semantics (unchanged)

Publisher failure is best-effort, never blocks mutation. The existing
`try/except Exception` in `tasks_handoff.py:_publish_task_event` and
analogous sites in `tasks_tools.py` stays. The mutation path
(`tasks_create`, `tasks_update`, etc.) never raises on Redis errors.

### Tests

- **Unit** (no Redis required):

  - `test_publish_task_event_no_publisher_is_noop` — no publisher = no
    raise, return `None`.
  - `test_publish_task_event_with_publisher_enqueues` — stub publisher
    gets one `await publisher.publish(event_type, payload)` call with
    the right envelope; assert the message id surfaces back.
  - `test_publish_task_event_raw_wraps_dict_into_base_model` —
    `publish_task_event_raw("task.handoff_orphan", {"task_id": "...", "workflow_id": "...", "reason": "step_3_update_failed", "orphaned_at": iso_now, "actor": "default"})` constructs a
    `TaskHandoffOrphanPayload` and forwards to the publisher.
  - `test_envelope_lookup_unknown_event_type_logs_and_noops` —
    `publish_task_event_raw("bogus", {})` logs warning + does not raise.
  - `test_publisher_init_failure_is_swallowed` — `BodaiEventsPublisher.init()`
    raising `RedisError` is logged + caught; `publisher.health()`
    returns `False`; `publisher.publish()` no-ops.
  - `test_consumer_group_maps_to_group_in_settings` — constructor
    produces a `RedisStreamsQueueSettings` whose `group` field equals
    the API-level `consumer_group` arg.

- **Integration** (Redis required, gated by `@pytest.mark.requires_network`

  - `@pytest.mark.integration`):

  * `tests/integration/test_bodai_events_publisher_e2e.py`:
    - Spins up a real Redis via `pytest-redis` fixture (or
      `docker.services.test` per `tests/integration/test_ci_gates.py`).
    - Asserts `BodaiEventsPublisher.publish("task.created", payload)`
      actually writes to `bodai:events` and the message id matches
      an `xreadgroup` from a separate consumer.

### Integration Contract

| Field | Value |
|---|---|
| **Triggered from** | `tasks_create`/`tasks_update`/`tasks_complete` mutations in `tasks_tools.py` + `tasks_handoff_to_workflow` step transitions in mahavishnu |
| **Returns to / updates** | `bodai:events` Redis Stream (XADD with `channel=event_type` + flat payload fields) |
| **Demonstrable by** | `tests/integration/test_bodai_events_publisher_e2e.py` — Redis round-trip; unit tests with fake publisher |
| **Rollback signal** | `logger.warning("bodai_events: init failed (degraded to no-op): %s", exc)` + `/health` returns 503 from `BodaiEventsPublisher.health() == False` |
| **Observability added** | `BodaiEventsPublisher.entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total` (§3 metrics); OTel span `bodai_events.publish` with attributes `event_type`, `task_id`, `outcome=success\|failure\|disabled` |

______________________________________________________________________

## Item 3 — v1.1 orphan sweeper (architectural, in mahavishnu)

### Decision

Per brainstorming session 2026-10-02: **sweeper lives in mahavishnu**
(Option B). Rationale: mahavishnu owns the dispatch edge
(`tasks_handoff_to_workflow`); the orphan is a dispatch-edge failure
mode; mahavishnu should clean up after itself.

### Behavior

**New module** `mahavishnu/mcp/sweepers/task_orphan_sweeper.py`:

```python
class TaskOrphanSweeper:
    """Subscribes to ``bodai:events`` Redis Stream (consumer group
    ``bodai-task-orphan-sweeper``), filters on channel=task.handoff_orphan,
    re-links tasks via session-buddy's ``tasks_update``.

    One instance per mahavishnu process. Started by ``start_server()``
    in ``mahavishnu/mcp/lifecycle.py`` (mirrors the ``plan_index``
    periodic runner at lines 95-158). Skipped if
    ``settings.task_orphan_sweeper.enabled == False``.

    Recovery loop (per orphan event):
      1. ``session_buddy.tasks_get(task_id)`` — load current state.
      2. ``_is_already_handed_off(task)`` — skip if already linked
         OR status is ``done``/``cancelled`` (no point re-linking
         a finished task).
      3. Else, ``session_buddy.tasks_update(task_id, metadata={
           "workflow_id": event.workflow_id,
           "re_linked_at": datetime.now(UTC).isoformat(),
           "re_link_reason": event.reason,
         })``.
      4. Emit a synthetic ``task.handoff_completed`` event on
         ``bodai:events`` for the re-link (per Decision #3 — we
         reuse the existing event type, accepting the semantic
         shift: this event now means "task is bound to a
         workflow_id", not strictly "workflow has reported success").
      5. ``await adapter.ack([entry["message_id"]])`` — clear the
         XREADGROUP PEL entry. Acks happen AFTER synthetic emit so
         a crash between steps 4 and 5 leads to reprocessing
         (idempotent — step 2 short-circuits).

    Idempotency: step 2 ensures no double-write.

    Heartbeat: ``health()`` returns ``False`` after 3 consecutive
    ``read()`` failures; resets to ``True`` on first success. The
    ``_consecutive_read_failures`` counter ticks on every caught
    exception in ``run_forever``; resets on success. Exponential
    backoff between retries (1s, 2s, 4s, … capped at 60s) via
    ``_backoff_seconds()``.

    Channel filter: subscribe to ``bodai:events``, filter on
    ``channel == "task.handoff_orphan"`` client-side. This is the
    sweeper's exclusive channel — no other consumer in this process
    competes on the same filter.

    Counter increment policy (§3 metrics): same as
    ``BodaiEventsPublisher`` — see Item 2 class docstring.
    """

    def __init__(
        self,
        *,
        stream: str = "bodai:events",
        consumer_group: str = "bodai-task-orphan-sweeper",
        consumer_name: str = "mahavishnu-{pid}",
        enabled: bool = True,
        block_ms: int = 5000,
        count: int = 10,
        session_buddy_client: Any = None,
    ) -> None:
        # Same consumer_group → group translation as BodaiEventsPublisher.
        self._settings = RedisStreamsQueueSettings(
            stream=stream,
            group=consumer_group,
            consumer=consumer_name,
        )
        self._adapter = RedisStreamsQueueAdapter(settings=self._settings)
        self.enabled = enabled
        self.block_ms = block_ms
        self.count = count
        # §3 counters
        self.entities_count = 0
        self.cycles_total = 0
        self.errors_total = 0
        self.last_updated_timestamp: float = 0.0
        # Heartbeat state
        self._consecutive_read_failures: int = 0

    async def init(self) -> None:
        # Same swallow-on-init-failure as BodaiEventsPublisher.
        ...

    async def cleanup(self) -> None: ...

    async def health(self) -> bool:
        return self._consecutive_read_failures < 3

    def _backoff_seconds(self) -> int:
        # 1s, 2s, 4s, … capped at 60s.
        return min(60, 2 ** min(self._consecutive_read_failures, 6))

    async def _is_already_handed_off(self, task: dict[str, Any]) -> bool:
        """True if the task is already linked to a workflow_id OR
        the task is finished. Centralizes the idempotency guard."""
        if task.get("workflow_id"):
            return True
        if task.get("status") in {"done", "cancelled"}:
            return True
        return False

    async def run_forever(self) -> None:
        while True:
            self.cycles_total += 1
            try:
                entries = await self._adapter.read(
                    count=self.count, block_ms=self.block_ms,
                )
                self._consecutive_read_failures = 0
            except Exception as exc:
                self.errors_total += 1
                self._consecutive_read_failures += 1
                logger.warning(
                    "task_orphan_sweeper: read failed (consecutive=%d): %s",
                    self._consecutive_read_failures, exc,
                )
                await asyncio.sleep(self._backoff_seconds())
                continue

            for entry in entries:
                if entry.get("channel") != "task.handoff_orphan":
                    continue
                # ... parse, recover via session_buddy, emit synthetic,
                # ack [entry["message_id"]] ...
                self.entities_count += 1
                self.last_updated_timestamp = time.time()
```

**Settings** (config layer — `oneiric`-compatible):

```yaml
# mahavishnu/settings/mahavishnu.yaml (or local override)
task_orphan_sweeper:
  enabled: true
  stream: "bodai:events"
  consumer_group: "bodai-task-orphan-sweeper"
  block_ms: 5000
  count: 10
```

**Modify** `mahavishnu/mcp/lifecycle.py:start_server()` (mirrors
`plan_index` periodic runner at lines 95-158):

```python
async def start_server() -> None:
    # ... existing code ...
    sweeper = TaskOrphanSweeper(
        stream=settings.task_orphan_sweeper.stream,
        consumer_group=settings.task_orphan_sweeper.consumer_group,
        block_ms=settings.task_orphan_sweeper.block_ms,
        count=settings.task_orphan_sweeper.count,
        enabled=settings.task_orphan_sweeper.enabled,
        session_buddy_client=get_session_buddy_client(),
    )
    await sweeper.init()  # already swallows internally
    sweeper_task = asyncio.create_task(sweeper.run_forever())
    # Stash sweeper_task for cleanup in stop_server()
    # Surface sweeper.health() in /health aggregate (503 on degraded).
```

**Modify** `mahavishnu/mcp/lifecycle.py:stop_server()`:

- `sweeper_task.cancel()` + `await sweeper.cleanup()` on shutdown.

### Tests

- **Unit** (no Redis required, uses `_FakeAdapter` pattern from
  `tests/unit/test_event_transport.py:35-66`):

  - `test_sweeper_processes_orphan_event` — fake adapter with one
    `task.handoff_orphan` message → one `tasks_update` call with the
    right metadata dict.
  - `test_sweeper_skips_if_workflow_id_already_set` — orphan event
    whose task already has `workflow_id` → zero `tasks_update` calls.
  - `test_sweeper_skips_if_status_done_or_cancelled` — orphan event
    for a `done` task → zero `tasks_update` calls.
  - `test_sweeper_emits_synthetic_handoff_completed` — successful
    re-link → one XADD to `bodai:events` with channel
    `task.handoff_completed` and the right payload.
  - `test_sweeper_acks_after_synthetic_emit` — successful re-link →
    one `adapter.ack([entry["message_id"]])` call AFTER the synthetic
    emit, not before.
  - `test_sweeper_health_false_after_three_failures` — three
    consecutive `read()` exceptions → `health() == False`; one success
    → `health() == True`.
  - `test_sweeper_init_failure_is_swallowed` — `TaskOrphanSweeper.init()`
    raising `RedisError` is logged + caught; `health()` returns `False`;
    `run_forever()` exits cleanly.
  - `test_backoff_doubles_capped_at_60s` — assert `_backoff_seconds()`
    sequence is `1, 2, 4, 8, 16, 32, 60, 60, ...`.

- **Integration** (Redis required, `@pytest.mark.requires_network` +
  `@pytest.mark.integration`):

  - `tests/integration/test_task_orphan_sweeper_e2e.py`:
    - Spins up Redis + session-buddy fake.
    - Publishes an orphan event → asserts the sweeper picks it up and
      re-links within the configured poll cadence; asserts PEL is
      empty after ack.

### Integration Contract

| Field | Value |
|---|---|
| **Triggered from** | `task.handoff_orphan` events on `bodai:events` Redis Stream (channel filter) |
| **Returns to / updates** | session-buddy's `task.metadata["workflow_id"]` field via `tasks_update` |
| **Demonstrable by** | `tests/integration/test_task_orphan_sweeper_e2e.py` (full loop); unit tests with fake adapter + fake session-buddy |
| **Rollback signal** | `logger.warning("task_orphan_sweeper: init failed (degraded to no-op): %s", exc)` + `/health` returns 503 |
| **Observability added** | `TaskOrphanSweeper.entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total` (§3 metrics); OTel span `task_orphan_sweeper.recover` with attributes `task_id`, `workflow_id`, `outcome=success\|skipped\|failed` |

______________________________________________________________________

## Cross-repo wire-up patches

### `mahavishnu/core/events/bodai_subscriber.py:_decode_envelope` — 10-LOC patch

The existing `bodai_subscriber.py:_decode_envelope` (line 346-401) only
decodes two shapes:

- `envelope=<JSON>` (the `oneiric-v1` envelope used by
  `mahavishnu/core/events/transport.py`)
- `topic/payload/headers` triplet

v1.1 flat-fields XADDs match neither — the subscriber would silently
drop v1.1 task events. Add a third branch:

```python
# Inside _decode_envelope, BEFORE the existing path 1 / path 2 logic:
# Path 3: v1.1 flat-fields shape (channel + payload fields at top level).
if "envelope" not in record and "topic" not in record:
    channel = record.get("channel", "unknown")
    headers = json.loads(record.get("headers", "{}")) if record.get("headers") else {}
    payload = {
        k: v for k, v in record.items()
        if k not in {"channel", "headers"}
    }
    return create_oneiric_envelope(
        topic=channel,
        payload=payload,
        source=headers.get("source", "session-buddy"),
    )
```

This patch is in **mahavishnu**, not in this spec's "Item 3 (sweeper)" —
it's a sibling change. The mahavishnu merge includes both the sweeper
(Item 3) and this patch.

______________________________________________________________________

## Direct-merge-to-main sequencing (replaces PR strategy)

| Order | Repo | Scope | Trigger |
|---|---|---|---|
| 1st | session-buddy | T12 fix + T4 publisher wiring + `BodaiEventsPublisher` + `publish_task_event_raw` + tests | Operator merges `main` when ready |
| 2nd | session-buddy tag | Operator bumps `0.30.0 → 0.31.0` + publishes to PyPI | After merge; per `feedback-mcp-common-version-bump-is-user` |
| 3rd | mahavishnu | `TaskOrphanSweeper` + `bodai_subscriber.py` 10-LOC patch + sweeper tests | After `session-buddy >= 0.31.0` is on PyPI; implementer updates the pin from `>=0.30.0` to `>=0.31.0` in `pyproject.toml` |
| 4th | mahavishnu tag | Operator bumps `0.31.0 → 0.32.0` + publishes | After merge |

`session-buddy`'s pin in mahavishnu's `pyproject.toml` enforces the order at
CI time. No PRs (per `bodai-pre-1.0-merge-policy.md`). The implementer
updates the `dependencies` pin; the operator does the `version` field.

______________________________________________________________________

## Wire-Up Discipline (per `wire-up-contract.md` + `mcp-backend-wiring-discipline.md`)

- **Publisher** (`BodaiEventsPublisher`): §3 metrics + `/health` aggregated → 503 on unhealthy.
- **Sweeper** (`TaskOrphanSweeper`): §3 metrics + `/health` aggregated → 503 on unhealthy.
- **Skill file** (update on ship):
  `/Users/les/Projects/session-buddy/session_buddy/mcp/skills_catalog/bodai-session-buddy-task-system.md` **(session-buddy repo)**:
  - Replace "T12 visibility_public (currently hardcoded private)" note with
    "T12 fixed in v1.1; `visibility="public"` is supported."
  - Replace "events emitted to a no-op stub" wording with "events
    emitted to `bodai:events` Redis Stream via oneiric
    `RedisStreamsQueueAdapter`; consumers read via
    `XREADGROUP` with consumer group `bodai-task-orphan-sweeper`."
  - Add a note: "v1.1 adds the `TaskOrphanSweeper` in mahavishnu that
    re-links tasks on `task.handoff_orphan` events."
  - Move "team-mode ACL" from line 173 to v2+ scope.

______________________________________________________________________

## Non-Goals (v1.1 explicitly does NOT ship)

- **Atomic handoff** (rollback dispatch on step-3 update failure).
- **At-least-once event delivery semantics**.
- **Multiple Redis Streams layouts**.
- **Redis pub/sub fallback** — single transport: XADD on `bodai:events`.
- **Akosha reindex integration** (akosha will pick up `task.*` events
  on its next reindex cycle automatically).
- **Version bumps in any `pyproject.toml`** — operator does this.

______________________________________________________________________

## Self-review checklist (run by author)

- [x] No placeholders ("TBD", "TODO", "FIXME")
- [x] No internal contradictions
- [x] Cross-repo order matches the `session-buddy >= 0.31.0` pin
- [x] Failure semantics: publisher `init()` failure does not block mutations
- [x] §3 metrics enumerated for both feeds (with increment policy docstring)
- [x] Integration Contracts have all 5 fields per `wire-up-contract.md`
- [x] Test paths + markers pinned per project convention
- [x] Skill file updates enumerated (cross-repo path annotated)
- [x] Pre-1.0 merge policy respected (direct merge, no PRs)
- [x] Version-bump rule respected (operator, not implementer; pin vs version split)
- [x] Sweeper idempotency covers `done`/`cancelled` states (not just `workflow_id`)
- [x] Default `bodai_events.enabled=True` (no backwards compat pre-1.0)
- [x] `consumer_group` → `group` mapping explicit in constructors
- [x] Publisher init-failure swallow site named (`_init_transport` + try/except)
- [x] Sweeper idempotency check is a named method (`_is_already_handed_off`)
- [x] Heartbeat counter `_consecutive_read_failures` and `_backoff_seconds()` helper in skeleton
- [x] `ack()` placement: AFTER synthetic event emit, BEFORE next read iteration
- [x] Subscriber backward-compat patch in cross-repo wire-up patches section (per Decision #6)
- [x] Goal section cross-references Decision #3 about semantic shift on `task.handoff_completed`
- [x] `event_type → payload_class` map (`_ENVELOPE_BY_EVENT_TYPE`) added
- [x] Tech Stack glossary added for `RedisStreamsQueueAdapter`, `fastmcp.lifespan`, `RedisStreamsQueueSettings`
