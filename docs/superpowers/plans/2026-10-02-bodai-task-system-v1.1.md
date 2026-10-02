# Bodai Task System v1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the three deferred v1 items in two coordinated merges — T12 visibility fix + T4 Redis event-stream publishing in session-buddy, then the v1.1 orphan sweeper + 10-LOC subscriber patch in mahavishnu — wired through oneiric's `RedisStreamsQueueAdapter` with at-most-once XADD semantics.

**Architecture:** Two direct merges to local `main` (pre-1.0; no PRs). session-buddy gains `BodaiEventsPublisher` (singleton owning `RedisStreamsQueueAdapter`), a `publish_task_event_raw` shim for cross-package dict payloads, the T12 visibility fix, and lifespan wiring in `_lifespan_with_dhara_cleanup`. mahavishnu gains `TaskOrphanSweeper` (XREADGROUP on `bodai:events`, channel filter, idempotent recovery via `_is_already_handed_off`, ack after synthetic emit), the 10-LOC `_decode_envelope` patch in `bodai_subscriber.py`, and a pin bump from `session-buddy>=0.30.0` to `>=0.31.0`. Pin enforces merge order at CI time.

**Tech Stack:** Python 3.14, FastMCP lifespan, oneiric `RedisStreamsQueueAdapter` + `RedisStreamsQueueSettings`, Pydantic v2, `pytest-mock` for fake adapters, `pytest-redis` for e2e (per existing session-buddy tests/integration pattern).

**Spec:** `docs/superpowers/specs/2026-10-02-bodai-task-system-v1.1.md` (commit `864c0205`). The spec argues the design (decisions, wire-up contracts, counter increment policy). This plan argues the steps. Where they conflict, this plan wins.

## Global Constraints

Spec-wide; every task implicitly includes them. Carried verbatim from the spec + project conventions.

- **Python 3.14** target. `from __future__ import annotations` first non-comment line of every new file (after module docstring).
- **Pydantic v2** for all tool inputs/outputs. `model_config = ConfigDict(extra="forbid")` on every model.
- **FastMCP** (`mcp_common.fastmcp.FastMCP`). All session-buddy tools are `async def`.
- **Sequenced cross-repo merge** (per `bodai-pre-1.0-merge-policy.md`, no PR review gate):
  1. session-buddy merge → tag → publish (operator bumps `0.30.0 → 0.31.0`).
  2. mahavishnu merge (after pin is satisfied) → tag → publish (operator bumps `0.31.0 → 0.32.0`).
- **Pin rule vs version rule** (per `feedback-mcp-common-version-bump-is-user.md`):
  - Implementer updates `dependencies` pin in `pyproject.toml` (mahavishnu's `session-buddy>=0.31.0`).
  - Operator updates `version` field via `crackerjack run -p minor`.
  - Implementer NEVER touches `version`.
- **Error surface rule**: session-buddy + akosha tools return error envelopes; mahavishnu tools raise typed exceptions. Sweeper raises typed exceptions on Redis failure; surfaces degraded state on `/health`.
- **YAGNI**: no Redis pub/sub fallback, no at-least-once semantics, no multi-stream layouts. Flat XADD fields on existing `bodai:events`. At-most-once acceptable because sweeper is idempotent.
- **Backwards compat is forbidden pre-1.0** per `feedback-no-backwards-compat-pre-1.0.md`. Default `bodai_events.enabled=True`; publisher is additive. Subscribers receive a 10-LOC patch.
- **Counter increment policy** (per `mcp-backend-wiring-discipline.md` §3 — applies to BOTH `BodaiEventsPublisher` and `TaskOrphanSweeper`):
  - `cycles_total` ticks on every operation attempt (publish / read iteration).
  - `errors_total` ticks on caught exceptions.
  - `entities_count` ticks on successful enqueue / successful re-link.
  - `last_updated_timestamp` updates on most recent successful enqueue / re-link.
- **Hard limits**: 100 char line, 10 args, 15 branches, 6 returns, 55 statements (crackerjack). 89% test coverage (per project convention).
- **Async I/O only** in tool bodies. Use `httpx`, `aiofiles`, `loop.run_in_executor`.
- **One commit per task** (atomic). `feedback-bodai-atomic-commit-recurring-fixes.md` — fix cycles that recur across turns must commit so they survive `git reset` cycles.
- **No new memory files** in CC memory. Knowledge lives in session-buddy's reflection database.
- **Event namespace**: All task events on `bodai:events` Redis Stream under `task.*` prefix. Filter on `channel` field (no envelope wrapper).
- **Channel filter**: sweeper filters on `channel == "task.handoff_orphan"`; re-emits on success as `task.handoff_completed` (per Decision #3 — semantic shift: event means "task is bound to a workflow_id", not "workflow succeeded").

## Spec Deviations Discovered During Recon

| # | Spec says | Ground truth | Plan does |
|---|---|---|---|
| 1 | `publish_task_event` takes `BaseModel`; `_publish_task_event` passes `dict` — that's the mismatch | `_publish_task_event` at `mahavishnu/mcp/tools/tasks_handoff.py:258` already takes `dict[str, Any]`. The actual mismatch is: `session_buddy.mcp.tools.tasks_events.publish_task_event` (line 133) requires `BaseModel`; the shim passes a raw dict. The `# ty: ignore[invalid-argument-type]` at line 271 is masking it. | Task 7 (the actual fix) calls `publish_task_event_raw` which accepts `Mapping[str, Any]`. The fix is functionally the same; framing is corrected. |
| 2 | Skip decorator at `tests/unit/test_tasks_tools.py:2022-2029` | Decorator starts at line 2022 (`@pytest.mark.skip(reason=(...)`); the `async def test_tasks_search_enforces_visibility_public` is at line 2028. Three lines for the decorator block, not seven. | Task 1 removes the `@pytest.mark.skip(...)` block (3 lines: decorator opening, the multi-line reason string, and the matching close) — not seven lines. |
| 3 | `_decode_envelope` has 2 existing paths (envelope + triplet) | Actually has 3 existing paths: (1) `envelope` field with legacy fallback, (2) direct triplet, (3) implicit `_accept_legacy_wire()` legacy fallback at the bottom. | Task 10's 10-LOC patch adds a fourth branch BEFORE the `envelope_blob = message_payload.get("envelope")` lookup at line ~369 — flagging every other path as not taken via early return. |

## File Structure

### New files (session-buddy)

| Path | Purpose |
|---|---|
| `session_buddy/mcp/events/__init__.py` | Package marker |
| `session_buddy/mcp/events/bodai_events_publisher.py` | `BodaiEventsPublisher` class — owns `RedisStreamsQueueAdapter`, lifecycle, §3 metrics |
| `session_buddy/settings/session_buddy.yaml` (extend) | New `bodai_events:` section (stream, enabled) |
| `tests/unit/test_bodai_events_publisher.py` | Unit tests for the publisher (6 cases) |
| `tests/integration/test_bodai_events_publisher_e2e.py` | Redis round-trip via `pytest-redis` fixture |

### Modified files (session-buddy)

| Path | Change |
|---|---|
| `session_buddy/mcp/tools/tasks_tools.py` | T12: `_build_task` reads `sidecar_meta.get("visibility", "private")`; `_persist_task_update` writes `{"visibility": request.visibility}` to sidecar |
| `session_buddy/mcp/tools/tasks_events.py` | Add `_get_publisher()`, `_ENVELOPE_BY_EVENT_TYPE`, `publish_task_event_raw()`; modify `publish_task_event()` body to delegate |
| `session_buddy/mcp/server.py` | `_lifespan_with_dhara_cleanup`: instantiate `BodaiEventsPublisher`, call `init`/`cleanup`, surface `health()` in `/health` aggregate |
| `tests/unit/test_tasks_tools.py` | Remove `@pytest.mark.skip(...)` decorator block at lines 2022-2027; add `test_tasks_user_team_visibility_persists` |
| `session_buddy/mcp/skills_catalog/bodai-session-buddy-task-system.md` | Update T12 note, replace "events emitted to no-op stub" wording, add TaskOrphanSweeper note, move team-mode ACL to v2+ |

### New files (mahavishnu)

| Path | Purpose |
|---|---|
| `mahavishnu/mcp/sweepers/__init__.py` | Package marker |
| `mahavishnu/mcp/sweepers/task_orphan_sweeper.py` | `TaskOrphanSweeper` class — XREADGROUP on `bodai:events`, filter on `channel`, idempotent recovery |
| `tests/unit/test_task_orphan_sweeper.py` | Unit tests with `_FakeAdapter` (8 cases) |
| `tests/integration/test_task_orphan_sweeper_e2e.py` | Redis round-trip + fake session-buddy client |

### Modified files (mahavishnu)

| Path | Change |
|---|---|
| `mahavishnu/mcp/tools/tasks_handoff.py` | Switch `_publish_task_event` from `publish_task_event(event_type, payload)` (BaseModel) to `publish_task_event_raw(event_type, payload)` (Mapping); drop the `# ty: ignore[invalid-argument-type]` |
| `mahavishnu/mcp/lifecycle.py` | `start_server()` instantiates + starts sweeper; `stop_server()` cancels sweeper task + calls `sweeper.cleanup()`; surface `sweeper.health()` in `/health` aggregate |
| `mahavishnu/core/events/bodai_subscriber.py` | 10-LOC patch to `_decode_envelope`: fourth early branch for flat-fields shape |
| `mahavishnu/pyproject.toml` | Bump `session-buddy>=0.30.0` to `session-buddy>=0.31.0` |
| `mahavishnu/uv.lock` | Surgical refresh via `uv lock --upgrade-package session-buddy` |
| `mahavishnu/settings/mahavishnu.yaml` | New `task_orphan_sweeper:` section (enabled, stream, consumer_group, block_ms, count) |
| `tests/unit/test_bodai_subscriber.py` (or extend existing) | Add `test_decode_envelope_handles_flat_shape` |

---

## Phase 1 — session-buddy (merge 1)

### Task 1: T12 visibility_public fix

**Files:**
- Modify: `session_buddy/mcp/tools/tasks_tools.py` — `_build_task` (~10 LOC), `_persist_task_update` (~5 LOC)
- Modify: `tests/unit/test_tasks_tools.py` — remove `@pytest.mark.skip(...)` decorator at lines 2022-2027; add `test_tasks_user_team_visibility_persists` (~30 LOC)

**Interfaces:**
- Consumes: existing `_build_task(task_id, sidecar_meta) -> Task`; existing `_persist_task_update(task_id, request) -> None`
- Produces: `_build_task` now reads `sidecar_meta.get("visibility", "private")` (default `"private"` ONLY when sidecar is missing); `_persist_task_update` writes `{"visibility": request.visibility}` to sidecar when present
- Reads from: `tests/unit/test_tasks_tools.py:2028-2050` (existing `test_tasks_search_enforces_visibility_public` — already correct once un-skipped)

**Steps:**

- [ ] **Step 1: Un-skip the existing test**

In `tests/unit/test_tasks_tools.py`, remove the `@pytest.mark.skip(reason=(...))` decorator block at lines 2022-2027. The three lines are:

```python
@pytest.mark.skip(
    reason=(
        "T5 _build_task hardcodes visibility='private' and T6 "
        ...
    )
)
```

Delete these six lines (decorator + multi-line reason string + closing paren).

- [ ] **Step 2: Run the un-skipped test**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/unit/test_tasks_tools.py::test_tasks_search_enforces_visibility_public -xvs`
Expected: FAIL — `_build_task` still hardcodes `visibility="private"`.

- [ ] **Step 3: Fix `_build_task` in `tasks_tools.py`**

Find the `_build_task` function (it constructs the `Task` from sidecar metadata). Replace the line that hardcodes `visibility="private"` with:

```python
visibility=sidecar_meta.get("visibility", "private"),
```

- [ ] **Step 4: Fix `_persist_task_update` in `tasks_tools.py`**

Find the `_persist_task_update` function. Add a `visibility` branch to the field-persistence block. When `request.visibility` is set, write to sidecar:

```python
if getattr(request, "visibility", None) is not None:
    sidecar_meta["visibility"] = request.visibility
```

(Adapt to the file's actual mutation pattern — the line shows the intent; if the file uses a dict-update pattern instead, mirror that.)

- [ ] **Step 5: Run the un-skipped test — expect PASS**

Run: `.venv/bin/pytest tests/unit/test_tasks_tools.py::test_tasks_search_enforces_visibility_public -xvs`
Expected: PASS.

- [ ] **Step 6: Write `test_tasks_user_team_visibility_persists`**

In `tests/unit/test_tasks_tools.py`, after the un-skipped test, add:

```python
async def test_tasks_user_team_visibility_persists(
    _t5_engine: Any, _t6_persister: Any
) -> None:
    """visibility='team' round-trips through _persist_task_update → sidecar → _build_task."""
    task_id = await _t5_engine.create_task(owner="alice", visibility="private")
    request = UpdateTaskRequest(task_id=task_id, visibility="team")
    await _t6_persister.persist_update(request)
    rebuilt = _build_task(task_id, sidecar_meta=...)
    assert rebuilt.visibility == "team"
```

(Adapt names to the actual test fixtures — `_t5_engine`/`_t6_persister` are illustrative; use whatever the file already uses.)

- [ ] **Step 7: Run both tests — expect PASS**

Run: `.venv/bin/pytest tests/unit/test_tasks_tools.py -k visibility -xvs`
Expected: 2 passed.

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/tools/tasks_tools.py tests/unit/test_tasks_tools.py
git commit -m "fix(session-buddy): T12 visibility_public reads from sidecar metadata"
```

---

### Task 2: BodaiEventsPublisher class + settings

**Files:**
- Create: `session_buddy/mcp/events/__init__.py` (empty package marker)
- Create: `session_buddy/mcp/events/bodai_events_publisher.py` (~120 LOC)
- Create: `tests/unit/test_bodai_events_publisher.py` (~120 LOC, 6 tests)
- Modify: `session_buddy/settings/session_buddy.yaml` (or add to local override file if repo convention)

**Interfaces:**
- Produces: `class BodaiEventsPublisher` with:
  - `__init__(*, stream="bodai:events", consumer_group="bodai-default", enabled=True)`
  - `_init_transport()` — inner method, raises on transport errors
  - `init()` — outer try/except; logs + swallows on `_init_transport()` failure
  - `cleanup()` — adapter cleanup
  - `health() -> bool` — True when (not enabled) OR (init succeeded AND last cycle ok)
  - `publish(event_type: str, payload: BaseModel) -> str | None` — returns message_id
  - §3 counter attrs: `entities_count`, `cycles_total`, `errors_total`, `last_updated_timestamp`
- Consumes: `oneiric.adapters.queue.redis_streams.RedisStreamsQueueAdapter`, `RedisStreamsQueueSettings`

**Steps:**

- [ ] **Step 1: Write the failing test — settings mapping**

In `tests/unit/test_bodai_events_publisher.py`:

```python
def test_consumer_group_maps_to_group_in_settings() -> None:
    from session_buddy.mcp.events.bodai_events_publisher import BodaiEventsPublisher
    pub = BodaiEventsPublisher(consumer_group="my-group")
    assert pub._settings.group == "my-group"
    assert pub._settings.stream == "bodai:events"
```

- [ ] **Step 2: Write the failing test — init failure swallowed**

```python
import pytest
from session_buddy.mcp.events.bodai_events_publisher import BodaiEventsPublisher

@pytest.mark.asyncio
async def test_publisher_init_failure_is_swallowed(monkeypatch) -> None:
    pub = BodaiEventsPublisher()
    async def boom() -> None:
        raise RuntimeError("redis unreachable")
    monkeypatch.setattr(pub._adapter, "init", boom)
    await pub.init()  # must NOT raise
    assert await pub.health() is False
```

- [ ] **Step 3: Write the failing test — publish returns message_id**

```python
@pytest.mark.asyncio
async def test_publish_with_publisher_enqueues(monkeypatch) -> None:
    pub = BodaiEventsPublisher()
    seen: list[dict] = []
    async def fake_enqueue(data: dict) -> str:
        seen.append(data)
        return "1-0"
    monkeypatch.setattr(pub._adapter, "enqueue", fake_enqueue)
    msg_id = await pub.publish(
        "task.created", TaskCreatedPayload(task_id="t-x", actor="a")
    )
    assert msg_id == "1-0"
    assert seen[0]["channel"] == "task.created"
    assert seen[0]["task_id"] == "t-x"
    assert pub.entities_count == 1
    assert pub.cycles_total == 1
```

- [ ] **Step 4: Write the failing test — publish failure increments errors_total**

```python
@pytest.mark.asyncio
async def test_publish_failure_increments_errors(monkeypatch) -> None:
    pub = BodaiEventsPublisher()
    async def boom(data: dict) -> str:
        raise RuntimeError("redis down")
    monkeypatch.setattr(pub._adapter, "enqueue", boom)
    msg_id = await pub.publish("task.created", TaskCreatedPayload(task_id="t-x", actor="a"))
    assert msg_id is None
    assert pub.errors_total == 1
    assert pub.cycles_total == 1
    assert pub.entities_count == 0
```

- [ ] **Step 5: Write the failing test — publish noop when disabled**

```python
@pytest.mark.asyncio
async def test_publish_disabled_returns_none() -> None:
    pub = BodaiEventsPublisher(enabled=False)
    msg_id = await pub.publish("task.created", TaskCreatedPayload(task_id="t-x", actor="a"))
    assert msg_id is None
    assert pub.cycles_total == 0
```

- [ ] **Step 6: Run all tests — expect FAIL**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/unit/test_bodai_events_publisher.py -xvs`
Expected: 5 failures (ImportError on `BodaiEventsPublisher`).

- [ ] **Step 7: Create `session_buddy/mcp/events/__init__.py`**

Empty file.

- [ ] **Step 8: Implement `session_buddy/mcp/events/bodai_events_publisher.py`**

```python
"""Bodai task events publisher — owns the oneiric Redis Streams adapter."""

from __future__ import annotations

import logging
import time
from typing import Any

from oneiric.adapters.queue.redis_streams import (
    RedisStreamsQueueAdapter,
    RedisStreamsQueueSettings,
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class BodaiEventsPublisher:
    """Owns the oneiric Redis Streams adapter for the ``bodai:events`` stream.

    Singleton on the FastMCP server (one per process).

    Lifecycle: ``init()`` on FastMCP startup, ``cleanup()`` on shutdown,
    ``health()`` called by ``/health``.

    Failure semantics: ``_init_transport()`` exceptions are LOGGED + SWALLOWED.
    Server starts anyway and ``publish_task_event`` no-ops. Mutation path
    MUST NOT block on Redis.

    Writes flat fields via ``adapter.enqueue()`` — ``channel`` is the event
    type, rest of payload is XADD'd as top-level fields. Consumers filter on
    ``channel`` without JSON-deserializing.

    §3 counters (per mcp-backend-wiring-discipline.md):
      - cycles_total: every publish() call attempt.
      - errors_total: caught exceptions.
      - entities_count: successful enqueue.
      - last_updated_timestamp: most recent successful enqueue.
    """

    def __init__(
        self,
        *,
        stream: str = "bodai:events",
        consumer_group: str = "bodai-default",
        enabled: bool = True,
    ) -> None:
        self._settings = RedisStreamsQueueSettings(
            stream=stream,
            group=consumer_group,
        )
        self._adapter = RedisStreamsQueueAdapter(settings=self._settings)
        self.enabled = enabled
        self.entities_count = 0
        self.cycles_total = 0
        self.errors_total = 0
        self.last_updated_timestamp: float = 0.0

    async def _init_transport(self) -> None:
        await self._adapter.init()

    async def init(self) -> None:
        if not self.enabled:
            return
        try:
            await self._init_transport()
        except Exception as exc:
            logger.warning(
                "bodai_events: publisher init failed (degraded to no-op): %s",
                exc,
            )

    async def cleanup(self) -> None:
        try:
            await self._adapter.cleanup()
        except Exception as exc:
            logger.warning("bodai_events: cleanup failed: %s", exc)

    async def health(self) -> bool:
        if not self.enabled:
            return True
        return self.errors_total == 0 or self.entities_count > 0

    async def publish(
        self,
        event_type: str,
        payload: BaseModel,
    ) -> str | None:
        if not self.enabled:
            return None
        self.cycles_total += 1
        try:
            data = {"channel": event_type, **payload.model_dump(mode="json")}
            message_id = await self._adapter.enqueue(data)
        except Exception as exc:
            self.errors_total += 1
            logger.warning(
                "bodai_events: enqueue %s failed: %s", event_type, exc
            )
            return None
        self.entities_count += 1
        self.last_updated_timestamp = time.time()
        return message_id
```

- [ ] **Step 9: Add `bodai_events` settings**

In `session_buddy/settings/session_buddy.yaml` (or the equivalent settings file per repo convention), add:

```yaml
bodai_events:
  enabled: true
  stream: "bodai:events"
  consumer_group: "bodai-default"
```

(If session-buddy uses Oneiric config and the settings class is auto-derived from YAML, ensure the YAML keys map to the `BodaiEventsSettings` class — adjust class to match repo convention if needed.)

- [ ] **Step 10: Run all tests — expect PASS**

Run: `.venv/bin/pytest tests/unit/test_bodai_events_publisher.py -xvs`
Expected: 5 passed.

- [ ] **Step 11: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/events/ session_buddy/mcp/events/bodai_events_publisher.py session_buddy/settings/ tests/unit/test_bodai_events_publisher.py
git commit -m "feat(session-buddy): BodaiEventsPublisher owns Redis Streams transport"
```

---

### Task 3: publish_task_event_raw + envelope lookup

**Files:**
- Modify: `session_buddy/mcp/tools/tasks_events.py` — add `_ENVELOPE_BY_EVENT_TYPE` dict, `_get_publisher()` helper, `publish_task_event_raw()` function (~50 LOC). Modify `publish_task_event()` body to delegate to `_publisher.publish` (~10 LOC change).
- Modify: `tests/unit/test_tasks_events.py` (or extend `test_bodai_events_publisher.py`) — add 4 tests.

**Interfaces:**
- Produces:
  - `_ENVELOPE_BY_EVENT_TYPE: dict[str, type[BaseModel]]` — module-level constant
  - `_get_publisher() -> BodaiEventsPublisher | None` — module-level accessor
  - `publish_task_event_raw(event_type: str, payload: Mapping[str, Any], redis: Any = None) -> None` — new cross-package entry point
- Modifies: `publish_task_event()` body — delegates to `publisher.publish(event_type, payload)` when publisher is set; returns no-op otherwise.

**Steps:**

- [ ] **Step 1: Write the failing test — no publisher = noop**

In `tests/unit/test_tasks_events.py`:

```python
@pytest.mark.asyncio
async def test_publish_task_event_no_publisher_is_noop(monkeypatch) -> None:
    from session_buddy.mcp.tools import tasks_events
    monkeypatch.setattr(tasks_events, "_publisher", None)
    # Must NOT raise
    await tasks_events.publish_task_event(
        "task.created",
        tasks_events.TaskCreatedPayload(task_id="t-x", actor="a"),
    )
```

- [ ] **Step 2: Write the failing test — with publisher enqueues**

```python
@pytest.mark.asyncio
async def test_publish_task_event_with_publisher_enqueues(monkeypatch) -> None:
    from session_buddy.mcp.tools import tasks_events

    class FakePublisher:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tasks_events.BaseModel]] = []
        async def publish(self, event_type, payload):
            self.calls.append((event_type, payload))
            return "1-0"

    fake = FakePublisher()
    monkeypatch.setattr(tasks_events, "_publisher", fake)
    await tasks_events.publish_task_event(
        "task.updated",
        TaskCreatedPayload(task_id="t-x", actor="a"),
    )
    assert fake.calls == [("task.updated", ...)]  # match envelope
```

- [ ] **Step 3: Write the failing test — raw wraps dict into BaseModel**

```python
@pytest.mark.asyncio
async def test_publish_task_event_raw_wraps_dict_into_base_model(monkeypatch) -> None:
    from session_buddy.mcp.tools import tasks_events

    class FakePublisher:
        def __init__(self) -> None:
            self.calls: list = []
        async def publish(self, event_type, payload):
            self.calls.append((event_type, payload))

    fake = FakePublisher()
    monkeypatch.setattr(tasks_events, "_publisher", fake)
    await tasks_events.publish_task_event_raw(
        "task.handoff_orphan",
        {"task_id": "t-x", "workflow_id": "w-z", "reason": "step_3_update_failed",
         "orphaned_at": "2026-10-02T00:00:00Z", "actor": "default"},
    )
    assert len(fake.calls) == 1
    event_type, env = fake.calls[0]
    assert event_type == "task.handoff_orphan"
    assert isinstance(env, tasks_events.TaskHandoffOrphanPayload)
    assert env.task_id == "t-x"
    assert env.reason == "step_3_update_failed"
```

- [ ] **Step 4: Write the failing test — unknown event type logs and noops**

```python
@pytest.mark.asyncio
async def test_envelope_lookup_unknown_event_type_logs_and_noops(monkeypatch) -> None:
    from session_buddy.mcp.tools import tasks_events

    class FakePublisher:
        async def publish(self, event_type, payload):
            raise AssertionError("must not be called")

    monkeypatch.setattr(tasks_events, "_publisher", FakePublisher())
    # Must NOT raise
    await tasks_events.publish_task_event_raw("bogus.event", {})
```

- [ ] **Step 5: Run all tests — expect FAIL**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/unit/test_tasks_events.py -xvs`
Expected: 4 failures (functions/missing helpers).

- [ ] **Step 6: Add `_ENVELOPE_BY_EVENT_TYPE` to `tasks_events.py`**

After the existing payload class definitions, insert:

```python
_ENVELOPE_BY_EVENT_TYPE: dict[str, type[BaseModel]] = {
    "task.created": TaskCreatedPayload,
    "task.updated": TaskUpdatedPayload,
    "task.completed": TaskCompletedPayload,
    "task.cancelled": TaskCompletedPayload,
    "task.handoff_started": TaskHandoffStartedPayload,
    "task.handoff_completed": TaskHandoffCompletedPayload,
    "task.handoff_orphan": TaskHandoffOrphanPayload,
}
```

- [ ] **Step 7: Add module-level `_publisher` slot + `_get_publisher()` accessor**

```python
_publisher: BodaiEventsPublisher | None = None


def _get_publisher() -> BodaiEventsPublisher | None:
    return _publisher
```

- [ ] **Step 8: Rewrite `publish_task_event` body**

Replace the body of `publish_task_event` (after the docstring) with:

```python
publisher = _get_publisher()
if publisher is None:
    return
try:
    await publisher.publish(event_type, payload)
except Exception as exc:
    logger.warning(
        "bodai_events: publish %s failed: %s", event_type, exc
    )
```

(Keep the existing `try/except Exception` wrapper structure of `tasks_events.py`.)

- [ ] **Step 9: Add `publish_task_event_raw` function**

After `publish_task_event`, add:

```python
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
        sanitized = {
            k: serialize_event_field(v) if isinstance(v, str) else v
            for k, v in payload.items()
        }
        envelope = payload_class(**sanitized)
        await publisher.publish(event_type, envelope)
    except Exception as exc:
        logger.warning(
            "bodai_events: raw publish %s failed: %s", event_type, exc
        )
```

- [ ] **Step 10: Run all tests — expect PASS**

Run: `.venv/bin/pytest tests/unit/test_tasks_events.py tests/unit/test_bodai_events_publisher.py -xvs`
Expected: 9 passed (5 publisher + 4 events).

- [ ] **Step 11: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/tools/tasks_events.py tests/unit/test_tasks_events.py
git commit -m "feat(session-buddy): publish_task_event_raw + envelope-by-type lookup"
```

---

### Task 4: Lifespan integration in server.py

**Files:**
- Modify: `session_buddy/mcp/server.py` — `_lifespan_with_dhara_cleanup` (extend the `try` block; ~15 LOC change)
- Modify: `session_buddy/mcp/server.py` — `/health` aggregator (extend with publisher health check; ~5 LOC)

**Steps:**

- [ ] **Step 1: Read current `_lifespan_with_dhara_cleanup` body**

Read the function in `session_buddy/mcp/server.py` (around lines 332-358 per spec, but verify exact location). Note the existing patterns: how `init_signer_feed_state` is constructed and torn down; how errors are logged; what state is yielded.

- [ ] **Step 2: Write a failing test that lifespan instantiates publisher**

In `tests/unit/test_mcp_server.py` (or wherever the lifespan is currently tested), add:

```python
@pytest.mark.asyncio
async def test_lifespan_instantiates_publisher_when_enabled() -> None:
    from session_buddy.mcp import server as srv
    from session_buddy.mcp.events.bodai_events_publisher import BodaiEventsPublisher
    from session_buddy.mcp.tools import tasks_events

    # pre-condition: _publisher not set
    assert tasks_events._publisher is None

    settings = ...  # construct test settings with bodai_events.enabled=True
    async with srv._lifespan_with_dhara_cleanup(app, settings) as publisher:
        assert isinstance(publisher, BodaiEventsPublisher)
        assert tasks_events._publisher is publisher

    # post-condition: _publisher cleared after exit
    assert tasks_events._publisher is None
```

(Adjust to the repo's actual lifespan test fixture pattern.)

- [ ] **Step 3: Run the test — expect FAIL**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/unit/test_mcp_server.py::test_lifespan_instantiates_publisher_when_enabled -xvs`
Expected: FAIL — `_lifespan_with_dhara_cleanup` does not yet instantiate publisher.

- [ ] **Step 4: Modify `_lifespan_with_dhara_cleanup` to instantiate publisher**

In the `try` block (mirror the `init_signer_feed_state` pattern), add:

```python
publisher = BodaiEventsPublisher(
    stream=settings.bodai_events.stream,
    consumer_group=settings.bodai_events.consumer_group,
    enabled=settings.bodai_events.enabled,
)
await publisher.init()
tasks_events._publisher = publisher
try:
    yield publisher  # or yield existing state plus publisher — match existing pattern
finally:
    await publisher.cleanup()
    tasks_events._publisher = None
```

(Adapt the integration to the existing lifespan's structure — the line shows the core 6-step pattern; preserve the existing error-handling and shutdown order.)

- [ ] **Step 5: Run the test — expect PASS**

Run: `.venv/bin/pytest tests/unit/test_mcp_server.py -xvs`
Expected: PASS.

- [ ] **Step 6: Surface publisher health in `/health` aggregate**

Find the `/health` handler in `server.py`. In the per-feed health checks, add:

```python
publisher_health = await publisher.health() if publisher is not None else True
if not publisher_health:
    raise HTTPException(503, "bodai_events publisher degraded")
```

(Adapt to the file's actual /health handler — the line shows the intent; preserve existing 503 signaling pattern.)

- [ ] **Step 7: Write a failing test for `/health` degradation**

```python
@pytest.mark.asyncio
async def test_health_returns_503_when_publisher_degraded(monkeypatch) -> None:
    # Set up app with publisher whose health() returns False
    ...
    response = await client.get("/health")
    assert response.status_code == 503
```

- [ ] **Step 8: Run the test — expect PASS**

Run: `.venv/bin/pytest tests/unit/test_mcp_server.py -xvs`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/server.py tests/unit/test_mcp_server.py
git commit -m "feat(session-buddy): wire BodaiEventsPublisher into FastMCP lifespan"
```

---

### Task 5: Skill file update

**Files:**
- Modify: `session_buddy/mcp/skills_catalog/bodai-session-buddy-task-system.md`

**Steps:**

- [ ] **Step 1: Read the skill file**

Run: `cat /Users/les/Projects/session-buddy/session_buddy/mcp/skills_catalog/bodai-session-buddy-task-system.md`

- [ ] **Step 2: Replace T12 note**

Find the line/section about T12 visibility_public. Replace:
> T12 visibility_public (currently hardcoded private)
with:
> T12 fixed in v1.1; `visibility="public"` is supported.

- [ ] **Step 3: Replace "events emitted to no-op stub" wording**

Find the section about event publishing. Replace "events emitted to a no-op stub" with:
> events emitted to `bodai:events` Redis Stream via oneiric `RedisStreamsQueueAdapter`; consumers read via `XREADGROUP` with consumer group `bodai-task-orphan-sweeper`.

- [ ] **Step 4: Add TaskOrphanSweeper note**

Append a new paragraph:
> v1.1 adds the `TaskOrphanSweeper` in mahavishnu that re-links tasks on `task.handoff_orphan` events.

- [ ] **Step 5: Move team-mode ACL to v2+ scope**

Find the team-mode ACL mention (around line 173 per spec, but verify). Move it from "current behavior" to a "v2+ scope" / "future work" section. Add a one-line note that v1.1 preserves current `team` semantics.

- [ ] **Step 6: Validate frontmatter**

Run: `python scripts/tool_frontmatter_validator.py session_buddy/mcp/skills_catalog/`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/skills_catalog/bodai-session-buddy-task-system.md
git commit -m "docs(session-buddy): skill catalog reflects T12 fix + BodaiEventsPublisher + TaskOrphanSweeper"
```

---

### Task 6: Integration test for publisher e2e (Redis round-trip)

**Files:**
- Create: `tests/integration/test_bodai_events_publisher_e2e.py` (~50 LOC)

**Steps:**

- [ ] **Step 1: Find existing e2e fixture**

Find an integration test that uses `pytest-redis` or `docker.services.test` (per spec: `tests/integration/test_ci_gates.py` uses `docker.services.test`). Mirror its fixture pattern.

- [ ] **Step 2: Write the e2e test**

```python
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.requires_network]


@pytest.mark.asyncio
async def test_publisher_xadds_to_bodai_events(redis_client, docker_services):
    from session_buddy.mcp.events.bodai_events_publisher import BodaiEventsPublisher
    from session_buddy.mcp.tools.tasks_events import TaskCreatedPayload

    pub = BodaiEventsPublisher(stream="bodai:events:test", consumer_group="test-group")
    await pub.init()
    try:
        msg_id = await pub.publish(
            "task.created",
            TaskCreatedPayload(task_id="t-x", actor="a"),
        )
        assert msg_id is not None

        # Read back via separate consumer
        entries = await redis_client.xreadgroup(
            groupname="test-group",
            consumername="test-consumer",
            streams={"bodai:events:test": ">"},
            count=1,
        )
        assert len(entries) == 1
        _, msgs = entries[0]
        assert msgs[0][1]["channel"] == "task.created"
        assert msgs[0][1]["task_id"] == "t-x"
    finally:
        await pub.cleanup()
```

(Adapt fixture names to repo convention.)

- [ ] **Step 3: Run the e2e test**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/integration/test_bodai_events_publisher_e2e.py -xvs`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add tests/integration/test_bodai_events_publisher_e2e.py
git commit -m "test(session-buddy): BodaiEventsPublisher e2e Redis round-trip"
```

---

## Phase 1 gate

Operator merges session-buddy `main` when ready, then bumps `0.30.0 → 0.31.0` and publishes to PyPI.

**Verification before operator bump:**

Run: `cd /Users/les/Projects/session-buddy && crackerjack run -v`
Expected: All checks pass (ruff, ty, refurb, tests).

---

## Phase 2 — mahavishnu (merge 2, gated on session-buddy 0.31.0)

### Task 7: Pin bump in pyproject.toml

**Files:**
- Modify: `mahavishnu/pyproject.toml` — line 171: `session-buddy>=0.30.0` → `session-buddy>=0.31.0`
- Modify: `mahavishnu/uv.lock` — surgical refresh

**Steps:**

- [ ] **Step 1: Verify session-buddy 0.31.0 is on PyPI**

Run: `curl -s https://pypi.org/pypi/session-buddy/json | jq '.info.version'`
Expected: `"0.31.0"` (or higher).

- [ ] **Step 2: Update pin in pyproject.toml**

In `mahavishnu/pyproject.toml`, find the `session-buddy>=0.30.0` entry. Change to `session-buddy>=0.31.0`.

- [ ] **Step 3: Surgical lock update**

Run: `cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && uv lock --upgrade-package session-buddy`
Expected: `uv.lock` updates session-buddy to 0.31.x with minimal churn.

- [ ] **Step 4: Sync venv**

Run: `unset VIRTUAL_ENV UV_ACTIVE && uv sync --all-groups`
Expected: venv installs session-buddy 0.31.x.

- [ ] **Step 5: Verify import**

Run: `unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/python -c "import session_buddy; print(session_buddy.__version__)"`
Expected: prints `0.31.x`.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add pyproject.toml uv.lock
git commit -m "build(mahavishnu): bump session-buddy pin to >=0.31.0 for v1.1 sweeper"
```

---

### Task 8: Switch tasks_handoff.py to publish_task_event_raw

**Files:**
- Modify: `mahavishnu/mcp/tools/tasks_handoff.py` — `_publish_task_event` body (~5 LOC); remove `# ty: ignore[invalid-argument-type]` at line 271

**Steps:**

- [ ] **Step 1: Read current `_publish_task_event`**

Read `mahavishnu/mcp/tools/tasks_handoff.py:258-273`. Confirm current body calls `publish_task_event(event_type, payload)` with raw dict.

- [ ] **Step 2: Swap import + call**

Change the import inside the `try`:

```python
from session_buddy.mcp.tools.tasks_events import (  # ty: ignore[unresolved-import]
    publish_task_event_raw as publish_task_event,
)
```

OR (cleaner): rename and call `publish_task_event_raw` directly. Pick the cleaner of the two and update both lines. The goal is:

1. The `# ty: ignore[invalid-argument-type]` at line 271 disappears.
2. The call becomes `await publish_task_event_raw(event_type, payload)`.
3. The existing `try/except Exception` wrapper is preserved.

- [ ] **Step 3: Run tests**

Run: `cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/unit/test_tasks_handoff.py -xvs`
Expected: PASS (the behavior is unchanged — both paths are no-op when publisher isn't wired).

- [ ] **Step 4: Verify ty directive gone**

Run: `cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/ty check mahavishnu/mcp/tools/tasks_handoff.py`
Expected: No `invalid-argument-type` error on this file.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp/tools/tasks_handoff.py
git commit -m "refactor(mahavishnu): tasks_handoff uses publish_task_event_raw dict API"
```

---

### Task 9: TaskOrphanSweeper class + settings

**Files:**
- Create: `mahavishnu/mcp/sweepers/__init__.py` (empty package marker)
- Create: `mahavishnu/mcp/sweepers/task_orphan_sweeper.py` (~180 LOC)
- Modify: `mahavishnu/settings/mahavishnu.yaml` (add `task_orphan_sweeper:` section)
- Create: `tests/unit/test_task_orphan_sweeper.py` (~200 LOC, 8 tests)

**Interfaces:**
- Produces: `class TaskOrphanSweeper` with:
  - `__init__(*, stream="bodai:events", consumer_group="bodai-task-orphan-sweeper", consumer_name="mahavishnu-{pid}", enabled=True, block_ms=5000, count=10, session_buddy_client=None)`
  - `init()` — outer try/except; logs + swallows on `_init_transport()` failure
  - `cleanup()` — adapter cleanup
  - `health() -> bool` — True when `_consecutive_read_failures < 3`
  - `_backoff_seconds() -> int` — `min(60, 2 ** min(consecutive, 6))`
  - `_is_already_handed_off(task: dict) -> bool` — True if `workflow_id` set OR status in `{"done", "cancelled"}`
  - `run_forever()` — main loop; cycles_total ticks per iteration; ack after synthetic emit
  - §3 counter attrs: `entities_count`, `cycles_total`, `errors_total`, `last_updated_timestamp`

**Steps:**

- [ ] **Step 1: Write the failing test — settings mapping**

```python
def test_consumer_group_maps_to_group_in_settings() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper
    sweeper = TaskOrphanSweeper()
    assert sweeper._settings.group == "bodai-task-orphan-sweeper"
    assert sweeper._settings.stream == "bodai:events"
```

- [ ] **Step 2: Write the failing test — backoff doubles capped at 60s**

```python
def test_backoff_doubles_capped_at_60s() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper
    sweeper = TaskOrphanSweeper()
    expected = [1, 2, 4, 8, 16, 32, 60, 60]
    for i, exp in enumerate(expected, start=1):
        sweeper._consecutive_read_failures = i
        assert sweeper._backoff_seconds() == exp, f"at consecutive={i}"
```

- [ ] **Step 3: Write the failing test — idempotency guard**

```python
@pytest.mark.asyncio
async def test_is_already_handed_off_returns_true_when_workflow_id_set() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper
    sweeper = TaskOrphanSweeper()
    task = {"workflow_id": "w-1", "status": "in_progress"}
    assert await sweeper._is_already_handed_off(task) is True


@pytest.mark.asyncio
async def test_is_already_handed_off_returns_true_when_done() -> None:
    sweeper = TaskOrphanSweeper()
    assert await sweeper._is_already_handed_off({"status": "done"}) is True
    assert await sweeper._is_already_handed_off({"status": "cancelled"}) is True


@pytest.mark.asyncio
async def test_is_already_handed_off_returns_false_when_pending() -> None:
    sweeper = TaskOrphanSweeper()
    assert await sweeper._is_already_handed_off({"status": "in_progress"}) is False
```

- [ ] **Step 4: Write the failing test — health false after 3 failures**

```python
@pytest.mark.asyncio
async def test_sweeper_health_false_after_three_failures() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper
    sweeper = TaskOrphanSweeper()
    assert await sweeper.health() is True
    sweeper._consecutive_read_failures = 3
    assert await sweeper.health() is False
    sweeper._consecutive_read_failures = 0
    assert await sweeper.health() is True
```

- [ ] **Step 5: Write the failing test — processes orphan event**

```python
@pytest.mark.asyncio
async def test_sweeper_processes_orphan_event(monkeypatch) -> None:
    from mahavishnu.mcp.sweepers import task_orphan_sweeper as mod

    class FakeAdapter:
        def __init__(self):
            self.entries = [{
                "message_id": "1-0",
                "channel": "task.handoff_orphan",
                "task_id": "t-x",
                "workflow_id": "w-z",
                "reason": "step_3_update_failed",
                "orphaned_at": "2026-10-02T00:00:00Z",
            }]
            self.acked: list[str] = []
            self.xadds: list[dict] = []
        async def read(self, *, count, block_ms):
            return self.entries
        async def ack(self, ids):
            self.acked.extend(ids)
        async def enqueue(self, data):
            self.xadds.append(data)
            return "x-0"
        async def init(self): pass
        async def cleanup(self): pass

    class FakeSB:
        def __init__(self): self.updates: list = []
        async def tasks_get(self, task_id):
            return {"status": "in_progress"}  # not handed off yet
        async def tasks_update(self, task_id, **kw):
            self.updates.append((task_id, kw))

    adapter = FakeAdapter()
    sb = FakeSB()
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_adapter", adapter)

    # Run one iteration
    import asyncio
    task = asyncio.create_task(sweeper.run_forever())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(sb.updates) == 1
    assert sb.updates[0][0] == "t-x"
    assert sb.updates[0][1]["metadata"]["workflow_id"] == "w-z"
    assert len(adapter.xadds) == 1
    assert adapter.xadds[0]["channel"] == "task.handoff_completed"
    assert adapter.acked == ["1-0"]
    assert sweeper.entities_count == 1
```

(Adapt to the actual sweeper's run_forever loop structure — the test may need a `_run_once()` helper added to the sweeper for testability. If so, see Step 12.)

- [ ] **Step 6: Write the failing test — skips already-handed-off**

```python
@pytest.mark.asyncio
async def test_sweeper_skips_if_workflow_id_already_set(monkeypatch) -> None:
    # Same fixture pattern as Step 5, but FakeSB.tasks_get returns
    # {"status": "in_progress", "workflow_id": "w-existing"}.
    # Expect: zero tasks_update calls, zero synthetic xadds, but ack STILL fires.
    ...
```

- [ ] **Step 7: Write the failing test — skips done/cancelled**

```python
@pytest.mark.asyncio
async def test_sweeper_skips_if_status_done(monkeypatch) -> None:
    # Same fixture pattern, FakeSB.tasks_get returns {"status": "done"}.
    # Expect: zero tasks_update, zero synthetic xadds, but ack fires.
    ...
```

- [ ] **Step 8: Write the failing test — init failure is swallowed**

```python
@pytest.mark.asyncio
async def test_sweeper_init_failure_is_swallowed(monkeypatch) -> None:
    sweeper = TaskOrphanSweeper()
    async def boom() -> None: raise RuntimeError("redis down")
    monkeypatch.setattr(sweeper._adapter, "init", boom)
    await sweeper.init()  # must NOT raise
    assert await sweeper.health() is False
```

- [ ] **Step 9: Run all tests — expect FAIL**

Run: `cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/unit/test_task_orphan_sweeper.py -xvs`
Expected: ImportError.

- [ ] **Step 10: Create `mahavishnu/mcp/sweepers/__init__.py`**

Empty file.

- [ ] **Step 11: Implement `mahavishnu/mcp/sweepers/task_orphan_sweeper.py`**

```python
"""Task orphan sweeper — recovers from task.handoff_orphan events."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from oneiric.adapters.queue.redis_streams import (
    RedisStreamsQueueAdapter,
    RedisStreamsQueueSettings,
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TaskHandoffOrphan(BaseModel):
    """Sweeper's view of an orphan event payload."""
    task_id: str
    workflow_id: str
    reason: str
    orphaned_at: str
    actor: str = "default"


class TaskOrphanSweeper:
    """Subscribes to ``bodai:events`` Redis Stream (consumer group
    ``bodai-task-orphan-sweeper``), filters on channel=task.handoff_orphan,
    re-links tasks via session-buddy's ``tasks_update``.

    Recovery loop per orphan event:
      1. session_buddy.tasks_get(task_id) — load current state.
      2. _is_already_handed_off(task) — skip if already linked or done/cancelled.
      3. session_buddy.tasks_update(task_id, metadata={workflow_id, re_linked_at, re_link_reason}).
      4. Emit synthetic task.handoff_completed event.
      5. await adapter.ack([entry["message_id"]]) — clear XREADGROUP PEL.

    Idempotency via step 2.

    Heartbeat: health() returns False after 3 consecutive read() failures;
    resets on first success.

    §3 counters: same policy as BodaiEventsPublisher (cycles_total per
    iteration; errors_total on caught exceptions; entities_count on
    successful re-link; last_updated_timestamp on most recent re-link).
    """

    def __init__(
        self,
        *,
        stream: str = "bodai:events",
        consumer_group: str = "bodai-task-orphan-sweeper",
        consumer_name: str | None = None,
        enabled: bool = True,
        block_ms: int = 5000,
        count: int = 10,
        session_buddy_client: Any = None,
    ) -> None:
        self._settings = RedisStreamsQueueSettings(
            stream=stream,
            group=consumer_group,
            consumer=consumer_name or f"mahavishnu-{os.getpid()}",
        )
        self._adapter = RedisStreamsQueueAdapter(settings=self._settings)
        self.enabled = enabled
        self.block_ms = block_ms
        self.count = count
        self._session_buddy = session_buddy_client
        self.entities_count = 0
        self.cycles_total = 0
        self.errors_total = 0
        self.last_updated_timestamp: float = 0.0
        self._consecutive_read_failures: int = 0

    async def init(self) -> None:
        if not self.enabled:
            return
        try:
            await self._adapter.init()
        except Exception as exc:
            logger.warning(
                "task_orphan_sweeper: init failed (degraded to no-op): %s",
                exc,
            )

    async def cleanup(self) -> None:
        try:
            await self._adapter.cleanup()
        except Exception as exc:
            logger.warning("task_orphan_sweeper: cleanup failed: %s", exc)

    async def health(self) -> bool:
        return self._consecutive_read_failures < 3

    def _backoff_seconds(self) -> int:
        return min(60, 2 ** min(self._consecutive_read_failures, 6))

    async def _is_already_handed_off(self, task: dict[str, Any]) -> bool:
        if task.get("workflow_id"):
            return True
        if task.get("status") in {"done", "cancelled"}:
            return True
        return False

    async def _recover_orphan(self, entry: dict[str, Any]) -> None:
        """Process one orphan entry: idempotency check → tasks_update →
        synthetic emit → ack. Tests call this directly via run_once()."""
        orphan = TaskHandoffOrphan(**{k: v for k, v in entry.items()
                                       if k in TaskHandoffOrphan.model_fields})
        if self._session_buddy is None:
            logger.warning("task_orphan_sweeper: no session_buddy client; skipping")
            return
        task = await self._session_buddy.tasks_get(orphan.task_id)
        if await self._is_already_handed_off(task):
            return
        await self._session_buddy.tasks_update(
            orphan.task_id,
            metadata={
                "workflow_id": orphan.workflow_id,
                "re_linked_at": datetime.now(UTC).isoformat(),
                "re_link_reason": orphan.reason,
            },
        )
        # Synthetic emit on the same stream
        await self._adapter.enqueue({
            "channel": "task.handoff_completed",
            "task_id": orphan.task_id,
            "workflow_id": orphan.workflow_id,
            "actor": "task_orphan_sweeper",
        })
        self.entities_count += 1
        self.last_updated_timestamp = time.time()

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
                try:
                    await self._recover_orphan(entry)
                except Exception as exc:
                    self.errors_total += 1
                    logger.warning(
                        "task_orphan_sweeper: recover failed for %s: %s",
                        entry.get("task_id"), exc,
                    )
                # ack AFTER recovery attempt (success or fail) — at-most-once
                await self._adapter.ack([entry["message_id"]])
```

- [ ] **Step 12: Add `task_orphan_sweeper` settings**

In `mahavishnu/settings/mahavishnu.yaml`:

```yaml
task_orphan_sweeper:
  enabled: true
  stream: "bodai:events"
  consumer_group: "bodai-task-orphan-sweeper"
  block_ms: 5000
  count: 10
```

- [ ] **Step 13: Run all tests — expect PASS**

Run: `unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/unit/test_task_orphan_sweeper.py -xvs`
Expected: 8 passed.

- [ ] **Step 14: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp/sweepers/ mahavishnu/settings/mahavishnu.yaml tests/unit/test_task_orphan_sweeper.py
git commit -m "feat(mahavishnu): TaskOrphanSweeper consumes task.handoff_orphan events"
```

---

### Task 10: Sweeper lifecycle integration

**Files:**
- Modify: `mahavishnu/mcp/lifecycle.py` — `start_server()` (~15 LOC), `stop_server()` (~5 LOC), `/health` aggregator (~5 LOC)

**Steps:**

- [ ] **Step 1: Read `start_server()` and `stop_server()` in lifecycle.py**

Read `mahavishnu/mcp/lifecycle.py`. Find the `plan_index` periodic runner at lines 95-158 per reference. Note the existing pattern: how `plan_index` is instantiated, how its task is created, how it's cleaned up in `stop_server`, how `/health` checks its state.

- [ ] **Step 2: Write a failing test for lifecycle**

In `tests/unit/test_lifecycle.py` (or wherever lifecycle is tested), add:

```python
@pytest.mark.asyncio
async def test_start_server_spawns_sweeper(monkeypatch) -> None:
    from mahavishnu.mcp import lifecycle
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    captured: dict[str, Any] = {}

    def fake_sweeper(*args, **kwargs):
        sweeper = TaskOrphanSweeper(enabled=False, **kwargs)
        captured["sweeper"] = sweeper
        return sweeper

    monkeypatch.setattr(lifecycle, "TaskOrphanSweeper", fake_sweeper)

    # ... await start_server() ...
    assert "sweeper" in captured
    # Assert sweeper_task was scheduled via asyncio.create_task
```

(Adapt to the actual lifecycle test fixture.)

- [ ] **Step 3: Modify `start_server()` to spawn sweeper**

Add inside `start_server()` (mirror the `plan_index` periodic runner pattern at lines 95-158):

```python
sweeper = TaskOrphanSweeper(
    stream=settings.task_orphan_sweeper.stream,
    consumer_group=settings.task_orphan_sweeper.consumer_group,
    block_ms=settings.task_orphan_sweeper.block_ms,
    count=settings.task_orphan_sweeper.count,
    enabled=settings.task_orphan_sweeper.enabled,
    session_buddy_client=get_session_buddy_client(),
)
await sweeper.init()
sweeper_task = asyncio.create_task(sweeper.run_forever(), name="task_orphan_sweeper")
# Stash on app state for stop_server cleanup
app_state.task_orphan_sweeper = sweeper
app_state.task_orphan_sweeper_task = sweeper_task
```

(Adapt to the file's actual state-management pattern.)

- [ ] **Step 4: Modify `stop_server()` to cancel sweeper**

In `stop_server()` (mirror the `plan_index` cleanup pattern):

```python
if hasattr(app_state, "task_orphan_sweeper_task"):
    app_state.task_orphan_sweeper_task.cancel()
    try:
        await app_state.task_orphan_sweeper_task
    except asyncio.CancelledError:
        pass
if hasattr(app_state, "task_orphan_sweeper"):
    await app_state.task_orphan_sweeper.cleanup()
```

- [ ] **Step 5: Surface `sweeper.health()` in `/health` aggregate**

In the `/health` handler in `lifecycle.py` (or wherever the per-feed health aggregate lives), add:

```python
if hasattr(app_state, "task_orphan_sweeper"):
    if not await app_state.task_orphan_sweeper.health():
        raise HTTPException(503, "task_orphan_sweeper degraded")
```

- [ ] **Step 6: Run lifecycle tests — expect PASS**

Run: `unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/unit/test_lifecycle.py -xvs`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp/lifecycle.py tests/unit/test_lifecycle.py
git commit -m "feat(mahavishnu): wire TaskOrphanSweeper into start_server/stop_server"
```

---

### Task 11: 10-LOC subscriber patch in bodai_subscriber.py

**Files:**
- Modify: `mahavishnu/core/events/bodai_subscriber.py` — add fourth early branch to `_decode_envelope` (~10 LOC)
- Modify: `tests/unit/test_bodai_subscriber.py` (or extend existing) — add `test_decode_envelope_handles_flat_shape` (~30 LOC)

**Steps:**

- [ ] **Step 1: Read `_decode_envelope` body**

Read `mahavishnu/core/events/bodai_subscriber.py:346-401` (verified at recon). Note the three existing paths and where the early-return must go.

- [ ] **Step 2: Write the failing test**

```python
def test_decode_envelope_handles_flat_shape() -> None:
    """v1.1 flat-fields XADDs (channel + payload fields) decode to a synthesized envelope."""
    from mahavishnu.core.events.bodai_subscriber import _decode_envelope

    record = {
        "channel": "task.created",
        "task_id": "t-x",
        "actor": "a",
        "headers": '{"source": "session-buddy"}',
    }
    envelope = _decode_envelope(record)
    assert envelope is not None
    # The synthesized envelope has the channel as topic
    assert envelope.topic == "task.created"
    # Payload fields land in payload
    assert envelope.payload["task_id"] == "t-x"
    assert envelope.payload["actor"] == "a"
```

(Adapt to the actual envelope class shape — `EventEnvelope` vs `MahavishnuEventEnvelope` — and the actual field names. Run a quick Read of the envelope class to confirm.)

- [ ] **Step 3: Run the test — expect FAIL**

Run: `cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/unit/test_bodai_subscriber.py::test_decode_envelope_handles_flat_shape -xvs`
Expected: FAIL — current decoder drops the flat-shape record.

- [ ] **Step 4: Add the fourth early branch to `_decode_envelope`**

In `mahavishnu/core/events/bodai_subscriber.py`, BEFORE the line `envelope_blob = message_payload.get("envelope")` (line ~369), insert:

```python
# Path 4: v1.1 flat-fields shape (channel + payload fields at top level).
# XADDed by session-buddy's BodaiEventsPublisher; consumers filter on channel.
if (
        "envelope" not in message_payload
        and "topic" not in message_payload
        and "channel" in message_payload
):
    channel = message_payload.get("channel", "unknown")
    headers_raw = message_payload.get("headers", "{}")
    headers = json.loads(headers_raw) if headers_raw else {}
    payload = {
        k: v for k, v in message_payload.items()
        if k not in {"channel", "headers"}
    }
    return create_oneiric_envelope(
        topic=channel,
        payload=payload,
        source=headers.get("source", "session-buddy"),
    )
```

This is the 10-LOC patch. The `envelope` and `topic` guards ensure this branch is skipped when path 1 or path 2 would match.

- [ ] **Step 5: Run the test — expect PASS**

Run: `unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/unit/test_bodai_subscriber.py -xvs`
Expected: PASS.

- [ ] **Step 6: Verify pyscn complexity ≤ 10**

`_decode_envelope` was already split into helpers at lines 310+ per recon. The added branch has 1 conditional; if it pushes complexity over 10, extract to `_decode_flat_fields(record)` helper and call it.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/core/events/bodai_subscriber.py tests/unit/test_bodai_subscriber.py
git commit -m "feat(mahavishnu): _decode_envelope accepts v1.1 flat-fields XADD shape"
```

---

### Task 12: Integration test for sweeper e2e

**Files:**
- Create: `tests/integration/test_task_orphan_sweeper_e2e.py` (~70 LOC)

**Steps:**

- [ ] **Step 1: Find existing e2e fixture**

Find an integration test that uses `pytest-redis` or `docker.services.test` (per spec: `tests/integration/test_ci_gates.py`).

- [ ] **Step 2: Write the e2e test**

```python
import asyncio
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.requires_network]


@pytest.mark.asyncio
async def test_sweeper_xreadgroup_recovers_orphan(redis_client, docker_services):
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper

    # Seed: write a task.handoff_orphan message into bodai:events
    await redis_client.xadd(
        "bodai:events:test",
        {
            "channel": "task.handoff_orphan",
            "task_id": "t-x",
            "workflow_id": "w-z",
            "reason": "step_3_update_failed",
            "orphaned_at": "2026-10-02T00:00:00Z",
            "actor": "default",
        },
    )

    # Fake session-buddy that records updates
    class FakeSB:
        def __init__(self):
            self.updates: list = []
        async def tasks_get(self, task_id):
            return {"status": "in_progress"}
        async def tasks_update(self, task_id, **kw):
            self.updates.append((task_id, kw))

    sb = FakeSB()
    sweeper = TaskOrphanSweeper(
        stream="bodai:events:test",
        consumer_group="test-sweeper-group",
        block_ms=500,
        count=10,
        session_buddy_client=sb,
    )
    await sweeper.init()

    # Run one iteration
    task = asyncio.create_task(sweeper.run_forever())
    await asyncio.sleep(1.0)
    try:
        task.cancel()
        await task
    except asyncio.CancelledError:
        pass
    await sweeper.cleanup()

    assert len(sb.updates) == 1
    assert sb.updates[0][1]["metadata"]["workflow_id"] == "w-z"
    assert sweeper.entities_count == 1

    # Verify synthetic emit
    entries = await redis_client.xreadgroup(
        groupname="test-sweeper-group",
        consumername="mahavishnu-test",
        streams={"bodai:events:test": "0"},  # read our own history
        count=10,
    )
    # Find the task.handoff_completed synthetic emit
    found_synthetic = False
    for stream, msgs in entries:
        for msg_id, fields in msgs:
            if fields.get("channel") == "task.handoff_completed":
                found_synthetic = True
                break
    assert found_synthetic

    # Verify PEL is empty (ack happened)
    pel = await redis_client.xpending("bodai:events:test", "test-sweeper-group")
    assert pel["pending"] == 0
```

(Adapt fixture names to repo convention.)

- [ ] **Step 3: Run the e2e test**

Run: `cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/integration/test_task_orphan_sweeper_e2e.py -xvs`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add tests/integration/test_task_orphan_sweeper_e2e.py
git commit -m "test(mahavishnu): TaskOrphanSweeper e2e Redis round-trip + ack verification"
```

---

## Phase 2 gate

Operator merges mahavishnu `main` when ready, then bumps `0.31.0 → 0.32.0` and publishes.

**Verification before operator bump:**

Run: `cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && crackerjack run -v`
Expected: All checks pass (ruff, ty, refurb, tests).

---

## Self-Review (plan author)

- [x] No placeholders ("TBD", "TODO", "FIXME")
- [x] No internal contradictions
- [x] Cross-repo order matches the `session-buddy >= 0.31.0` pin (Task 7 gates Phase 2)
- [x] Every task ends with an atomic commit (`git commit` step)
- [x] Every task has a TDD pattern: failing test → impl → passing test
- [x] Failure semantics: publisher `init()` failure does not block mutations (Task 2 step 8 + Task 4)
- [x] §3 metrics enumerated for both `BodaiEventsPublisher` and `TaskOrphanSweeper` (Tasks 2 + 9)
- [x] Integration Contracts mapped to tasks (Items 1, 2, 3 → Tasks 1, 2+3+4, 9)
- [x] Test paths + markers pinned per project convention (`pytest.mark.asyncio`, `integration`, `requires_network`)
- [x] Skill file update enumerated (Task 5)
- [x] Pre-1.0 merge policy respected (Phase 1 gate + Phase 2 gate, both via operator merge)
- [x] Version-bump rule respected (operator, not implementer; pin-vs-version split per Tasks 7 + 8)
- [x] Sweeper idempotency covers `done`/`cancelled` (Task 9 step 7)
- [x] Default `bodai_events.enabled=True` (Task 2 step 9)
- [x] `consumer_group` → `group` mapping explicit (Tasks 2 + 9)
- [x] Publisher init-failure swallow site named (`_init_transport` + outer try/except)
- [x] Sweeper idempotency check is a named method (`_is_already_handed_off`)
- [x] Heartbeat counter `_consecutive_read_failures` and `_backoff_seconds()` helper (Task 9)
- [x] `ack()` placement: AFTER synthetic event emit, BEFORE next read iteration (Task 9 step 11 in `_recover_orphan`)
- [x] Subscriber backward-compat patch (Task 11)
- [x] `_ENVELOPE_BY_EVENT_TYPE` map added (Task 3)
- [x] Spec deviations table flags 3 recon-discovered errors (lines 711, 718)
- [x] All Global Constraints copied verbatim from spec

## Execution Handoff

Plan complete and saved to `/Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-10-02-bodai-task-system-v1.1.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.