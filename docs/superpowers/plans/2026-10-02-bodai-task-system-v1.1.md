# Bodai Task System v1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the three deferred v1 items in two coordinated merges — T12 visibility fix + T4 Redis event-stream publishing in session-buddy, then the v1.1 orphan sweeper + 10-LOC subscriber patch in mahavishnu — wired through oneiric's `RedisStreamsQueueAdapter` with at-most-once XADD semantics and OTel-observed outcomes.

**Architecture:** Two direct merges to local `main` (pre-1.0; no PRs). session-buddy gains `BodaiEventsPublisher` (singleton owning `RedisStreamsQueueAdapter`), a `publish_task_event_raw` shim for cross-package dict payloads, the T12 visibility fix, OTel span emission (`bodai_events.publish`), and lifespan wiring in `_lifespan_with_dhara_cleanup`. mahavishnu gains `TaskOrphanSweeper` (XREADGROUP on `bodai:events`, channel filter on `entry["payload"]["channel"]`, idempotent recovery via `_is_already_handed_off`, OTel span `task_orphan_sweeper.recover`, ack after synthetic emit), the 10-LOC `_decode_envelope` patch in `bodai_subscriber.py`, and a pin bump from `session-buddy>=0.30.0` to `>=0.31.0`. Pin enforces merge order at CI time.

**Tech Stack:** Python 3.14, FastMCP lifespan, oneiric `RedisStreamsQueueAdapter` + `RedisStreamsQueueSettings`, Pydantic v2, OTel (existing oneiric OTLP exporter), `pytest-mock` for fake adapters, `pytest-redis` for e2e (per existing session-buddy tests/integration pattern).

**Spec:** `docs/superpowers/specs/2026-10-02-bodai-task-system-v1.1.md` (commit `864c0205`). The spec argues the design (decisions, wire-up contracts, counter increment policy). This plan argues the steps. Where they conflict, this plan wins.

## Global Constraints

Spec-wide; every task implicitly includes them. Carried verbatim from the spec + project conventions.

- **Python 3.14** target. `from __future__ import annotations` first non-comment line of every new file (after module docstring).
- **Pydantic v2** for all tool inputs/outputs. `model_config = ConfigDict(extra="forbid")` on every model.
- **FastMCP** (`mcp_common.fastmcp.FastMCP`). All session-buddy tools are `async def`.
- **Sequenced cross-repo merge** (per `bodai-pre-1.0-merge-policy.md`, no PR review gate):
  1. session-buddy merge → tag → publish (operator bumps `0.30.0 → 0.31.0`).
  1. mahavishnu merge (after pin is satisfied) → tag → publish (operator bumps `0.31.0 → 0.32.0`).
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
- **OTel span policy** (per `mcp-backend-wiring-discipline.md` §4 — applies to BOTH `BodaiEventsPublisher` and `TaskOrphanSweeper`):
  - Publisher: span `bodai_events.publish` with attributes `event_type`, `task_id`, `outcome ∈ {success, failure, disabled}`.
  - Sweeper: span `task_orphan_sweeper.recover` with attributes `task_id`, `workflow_id`, `outcome ∈ {success, skipped, failed}`.
- **Adapter entry shape** (per `oneiric.adapters.queue.redis_streams.RedisStreamsQueueAdapter._format_entries`): each entry returned by `read()` is `{"message_id": message_id, "payload": <XADD-fields-dict>}`. **All consumers MUST read the XADD fields from `entry["payload"]`**, never from the entry root. The `message_id` lives at the entry root for `ack()` lookup.
- **Hard limits**: 100 char line, 10 args, 15 branches, 6 returns, 55 statements (crackerjack). 89% test coverage (per project convention).
- **Async I/O only** in tool bodies. Use `httpx`, `aiofiles`, `loop.run_in_executor`.
- **One commit per task** (atomic). `feedback-bodai-atomic-commit-recurring-fixes.md` — fix cycles that recur across turns must commit so they survive `git reset` cycles.
- **No new memory files** in CC memory. Knowledge lives in session-buddy's reflection database.
- **Event namespace**: All task events on `bodai:events` Redis Stream under `task.*` prefix. Filter on `channel` field (no envelope wrapper).
- **Channel filter**: sweeper filters on `entry["payload"]["channel"] == "task.handoff_orphan"`; re-emits on success as `task.handoff_completed` (per Decision #3 — semantic shift: event means "task is bound to a workflow_id", not "workflow succeeded").

## Spec Deviations Discovered During Recon

| # | Spec says | Ground truth | Plan resolves to |
|---|---|---|---|
| 1 | `publish_task_event` is a "typed no-op stub (`return` at line 160)" | Spec is correct: line 160 IS where the `return` statement terminates the body. Function definition starts at line 133. The `tasks_handoff.py:_publish_task_event` shim passes a raw `dict[str, Any]` (signature line 258). The actual mismatch is `session_buddy.mcp.tools.tasks_events.publish_task_event` requires `BaseModel` (signature line 143) while `_publish_task_event` passes a raw dict. `# ty: ignore[invalid-argument-type]` at line 271 masks the type error. | Task 8 calls `publish_task_event_raw(event_type, payload)` which accepts `Mapping[str, Any]`. Drop the ty ignore directive. |
| 2 | Skip decorator at `tests/unit/test_tasks_tools.py:2022-2029` | Spec is correct on bounds. The decorator is 8 lines (2022-2029 inclusive), not 3 or 6: `@pytest.mark.skip(` (2022), `reason=(` (2023), four string lines (2024-2027), `)` (2028), `)` (2029). | Task 1 removes all 8 lines. |
| 3 | `_decode_envelope` has 2 existing paths (envelope + triplet) | Plan identified 3 existing paths (envelope with legacy fallback at line 367, direct triplet, legacy fallback at the bottom). The 10-LOC patch adds a fourth early branch. | Task 11 inserts a fourth branch BEFORE line 367. |

## File Structure

### New files (session-buddy)

| Path | Purpose |
|---|---|
| `session_buddy/mcp/events/__init__.py` | Package marker |
| `session_buddy/mcp/events/bodai_events_publisher.py` | `BodaiEventsPublisher` class — owns `RedisStreamsQueueAdapter`, lifecycle, §3 counters, OTel spans |
| `tests/unit/test_bodai_events_publisher.py` | Unit tests for the publisher (6 cases incl. OTel span assertion) |
| `tests/integration/test_bodai_events_publisher_e2e.py` | Redis round-trip via `pytest-redis` fixture (or `docker.services.test`) |

### Modified files (session-buddy)

| Path | Change |
|---|---|
| `session_buddy/pyproject.toml` | Register `requires_network` marker in `[tool.pytest].markers` block (Task 6 step 1) |
| `session_buddy/mcp/tools/tasks_tools.py` | T12: `_build_task` reads `sidecar_meta.get("visibility", "private")`; `_persist_task_update` writes `visibility` to sidecar metadata |
| `session_buddy/mcp/tools/tasks_events.py` | Add `_ENVELOPE_BY_EVENT_TYPE` dict, `_get_publisher()` helper, `publish_task_event_raw()`; modify `publish_task_event()` body to delegate |
| `session_buddy/mcp/server.py` | `_lifespan_with_dhara_cleanup` (lines 279-329): instantiate `BodaiEventsPublisher`, call `init`/`cleanup`; surface `health()` in `/health` aggregate. Lifespan signature changes from `AsyncGenerator[None]` to `AsyncGenerator[BodaiEventsPublisher \| None]`. |
| `session_buddy/settings/session-buddy.yaml` (note: hyphen, not underscore) | New `bodai_events:` section (stream, consumer_group, enabled) |
| `tests/unit/test_tasks_tools.py` | Remove `@pytest.mark.skip(...)` decorator block at lines 2022-2029 (8 lines); add `test_tasks_user_team_visibility_persists` |
| `session_buddy/mcp/skills_catalog/bodai-session-buddy-task-system.md` | Update T12 note, replace "events emitted to no-op stub" wording, add TaskOrphanSweeper note, move team-mode ACL to v2+ |

### New files (mahavishnu)

| Path | Purpose |
|---|---|
| `mahavishnu/mcp/sweepers/__init__.py` | Package marker |
| `mahavishnu/mcp/sweepers/task_orphan_sweeper.py` | `TaskOrphanSweeper` class — XREADGROUP on `bodai:events`, filter on `entry["payload"]["channel"]`, idempotent recovery, OTel spans, `_run_once()` testability helper |
| `tests/unit/test_task_orphan_sweeper.py` | Unit tests with `_FakeAdapter` (extended with `init`/`cleanup`/`ack`) (8 cases incl. OTel span assertion) |
| `tests/integration/test_task_orphan_sweeper_e2e.py` | Redis round-trip + fake session-buddy client |

### Modified files (mahavishnu)

| Path | Change |
|---|---|
| `mahavishnu/mcp/tools/tasks_handoff.py` | Switch `_publish_task_event` from `publish_task_event(event_type, payload)` (BaseModel) to `publish_task_event_raw(event_type, payload)` (Mapping); remove `# ty: ignore[invalid-argument-type]` at line 271 |
| `mahavishnu/mcp/lifecycle.py` | `start_server(server, host=, port=)` (line 14, positional `server` required): instantiate + start sweeper; `stop_server(server)` (line 147, positional `server` required): cancel sweeper task + `sweeper.cleanup()`; surface `sweeper.health()` in `/health` aggregate |
| `mahavishnu/core/events/bodai_subscriber.py` | 10-LOC patch to `_decode_envelope` (lines 346-402): fourth early branch for flat-fields shape inserted BEFORE line 367 |
| `mahavishnu/pyproject.toml` | Bump `session-buddy>=0.30.0` (line 171) to `session-buddy>=0.31.0` |
| `mahavishnu/uv.lock` | Surgical refresh via `uv lock --upgrade-package session-buddy` |
| `mahavishnu/settings/mahavishnu.yaml` | New `task_orphan_sweeper:` section (enabled, stream, consumer_group, block_ms, count) |
| `tests/unit/test_bodai_subscriber.py` (or extend existing) | Add `test_decode_envelope_handles_flat_shape` |

______________________________________________________________________

## Phase 1 — session-buddy (merge 1)

### Task 1: T12 visibility_public fix

**Files:**

- Modify: `session_buddy/mcp/tools/tasks_tools.py` — `_build_task` (line 344, hardcoded visibility at 400), `_persist_task_update` (line 706, takes `task: Task` after `_apply_update_request`)
- Modify: `tests/unit/test_tasks_tools.py` — remove `@pytest.mark.skip(...)` decorator block at lines 2022-2029 (8 lines); add `test_tasks_user_team_visibility_persists`

**Interfaces:**

- Consumes: existing `_build_task(task_id, sidecar_meta) -> Task` (line 344); existing `_persist_task_update(reflection_id, task, sidecar_meta, diff_events, actor) -> None` (line 706). The function takes the already-mutated `task` (not a `request`); sidecar_meta is already a local parameter.
- Produces: `_build_task` reads `sidecar_meta.get("visibility", "private")` (default `"private"` ONLY when sidecar is missing); `_persist_task_update` writes `new_meta["visibility"] = task.visibility` after `new_meta = dict(sidecar_meta)` (mirroring the `priority`/`effort` pattern at lines 723-727).

**Steps:**

- [ ] **Step 1: Un-skip the existing test (8 lines)**

In `tests/unit/test_tasks_tools.py`, remove lines 2022-2029 (the `@pytest.mark.skip(reason=(...))` decorator block). Lines 2022-2029 inclusive:

```python
@pytest.mark.skip(
    reason=(
        "T5 _build_task hardcodes visibility='private' and T6 "
        "_persist_task_update does not write visibility to the sidecar; "
        "visibility_public needs the T5 fix to read visibility from "
        "sidecar metadata. Tracked as T12 follow-up."
    )
)
```

Delete all 8 lines (decorator + multi-line reason string + two closing parens).

- [ ] **Step 2: Run the un-skipped test**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/unit/test_tasks_tools.py::test_tasks_search_enforces_visibility_public -xvs`
Expected: FAIL — `_build_task` still hardcodes `visibility="private"`.

- [ ] **Step 3: Fix `_build_task` in `tasks_tools.py`**

At `tasks_tools.py:400`, replace the hardcoded `visibility="private"` with:

```python
visibility=sidecar_meta.get("visibility", "private"),
```

- [ ] **Step 4: Fix `_persist_task_update` in `tasks_tools.py`**

In `_persist_task_update` (line 706), the function already has `new_meta = dict(sidecar_meta)` and writes `priority`/`effort` keys. Add a visibility branch in the same block:

```python
if getattr(task, "visibility", None) is not None:
    new_meta["visibility"] = task.visibility
```

(Place immediately after the existing `priority`/`effort` writes — mirror the existing mutation pattern.)

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
    task = await _t5_engine.get_task(task_id)
    task.visibility = "team"
    await _t6_persister.persist_update(task_id, task=task)
    rebuilt = _build_task(task_id, sidecar_meta=...)
    assert rebuilt.visibility == "team"
```

(Adapt names to actual test fixtures — `_t5_engine`/`_t6_persister` are illustrative; use whatever the file already uses.)

- [ ] **Step 7: Run both tests — expect PASS**

Run: `.venv/bin/pytest tests/unit/test_tasks_tools.py -k visibility -xvs`
Expected: 2 passed.

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/tools/tasks_tools.py tests/unit/test_tasks_tools.py
git commit -m "fix(session-buddy): T12 visibility_public reads from sidecar metadata"
```

______________________________________________________________________

### Task 2: BodaiEventsPublisher class + settings + OTel span

**Files:**

- Create: `session_buddy/mcp/events/__init__.py` (empty package marker)
- Create: `session_buddy/mcp/events/bodai_events_publisher.py` (~140 LOC)
- Create: `tests/unit/test_bodai_events_publisher.py` (~140 LOC, 6 tests)
- Modify: `session_buddy/settings/session-buddy.yaml` (note: hyphen, not underscore) — add `bodai_events:` section

**Interfaces:**

- Produces: `class BodaiEventsPublisher` with:
  - `__init__(*, stream="bodai:events", consumer_group="bodai-default", enabled=True)`
  - `_init_transport()` — inner method, raises on transport errors
  - `init()` — outer try/except; logs + swallows on `_init_transport()` failure
  - `cleanup()` — adapter cleanup
  - `health() -> bool` — True when (not enabled) OR (init succeeded AND last cycle ok)
  - `publish(event_type: str, payload: BaseModel) -> str | None` — returns message_id; emits OTel span `bodai_events.publish` with attributes `event_type`, `task_id`, `outcome ∈ {success, failure, disabled}`
  - §3 counter attrs: `entities_count`, `cycles_total`, `errors_total`, `last_updated_timestamp`

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

- [ ] **Step 6: Write the failing test — OTel span emitted on success**

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

@pytest.mark.asyncio
async def test_publish_emits_otel_span_on_success(monkeypatch) -> None:
    provider = TracerProvider()
    tracer = provider.get_tracer("test")
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with patch.dict(os.environ, {"OTEL_PYTHON_TRACER_PROVIDER": "sdk"}):
        pub = BodaiEventsPublisher()
        async def fake_enqueue(data: dict) -> str: return "1-0"
        monkeypatch.setattr(pub._adapter, "enqueue", fake_enqueue)
        await pub.publish("task.created", TaskCreatedPayload(task_id="t-x", actor="a"))

    spans = exporter.get_finished_spans()
    assert any(s.name == "bodai_events.publish" for s in spans)
    span = next(s for s in spans if s.name == "bodai_events.publish")
    assert span.attributes["event_type"] == "task.created"
    assert span.attributes["task_id"] == "t-x"
    assert span.attributes["outcome"] == "success"
```

(Adapt to existing OTel testing pattern in the repo.)

- [ ] **Step 7: Run all tests — expect FAIL**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/unit/test_bodai_events_publisher.py -xvs`
Expected: 6 failures (ImportError on `BodaiEventsPublisher`).

- [ ] **Step 8: Create `session_buddy/mcp/events/__init__.py`**

Empty file.

- [ ] **Step 9: Implement `session_buddy/mcp/events/bodai_events_publisher.py`**

```python
"""Bodai task events publisher — owns the oneiric Redis Streams adapter."""

from __future__ import annotations

import logging
import time
from typing import Any

from opentelemetry import trace
from oneiric.adapters.queue.redis_streams import (
    RedisStreamsQueueAdapter,
    RedisStreamsQueueSettings,
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)


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
    ``channel`` (in entry["payload"]) without JSON-deserializing.

    §3 counters (per mcp-backend-wiring-discipline.md):
      - cycles_total: every publish() call attempt.
      - errors_total: caught exceptions.
      - entities_count: successful enqueue.
      - last_updated_timestamp: most recent successful enqueue.

    OTel span (per mcp-backend-wiring-discipline.md §4):
      - bodai_events.publish: attributes event_type, task_id, outcome ∈ {success, failure, disabled}.
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
        task_id = getattr(payload, "task_id", None) or "unknown"
        with _tracer.start_as_current_span("bodai_events.publish") as span:
            span.set_attribute("event_type", event_type)
            span.set_attribute("task_id", str(task_id))
            if not self.enabled:
                span.set_attribute("outcome", "disabled")
                return None
            self.cycles_total += 1
            try:
                data = {"channel": event_type, **payload.model_dump(mode="json")}
                message_id = await self._adapter.enqueue(data)
            except Exception as exc:
                self.errors_total += 1
                span.set_attribute("outcome", "failure")
                logger.warning(
                    "bodai_events: enqueue %s failed: %s", event_type, exc
                )
                return None
            span.set_attribute("outcome", "success")
            self.entities_count += 1
            self.last_updated_timestamp = time.time()
            return message_id
```

- [ ] **Step 10: Add `bodai_events` settings**

In `session_buddy/settings/session-buddy.yaml` (note: hyphen, NOT underscore — code reviewer confirmed the actual filename):

```yaml
bodai_events:
  enabled: true
  stream: "bodai:events"
  consumer_group: "bodai-default"
```

(If session-buddy uses Oneiric config and the settings class is auto-derived from YAML, ensure the YAML keys map to the `BodaiEventsSettings` class — adjust class to match repo convention if needed.)

- [ ] **Step 11: Run all tests — expect PASS**

Run: `.venv/bin/pytest tests/unit/test_bodai_events_publisher.py -xvs`
Expected: 6 passed.

- [ ] **Step 12: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/events/ session_buddy/mcp/events/bodai_events_publisher.py session_buddy/settings/session-buddy.yaml tests/unit/test_bodai_events_publisher.py
git commit -m "feat(session-buddy): BodaiEventsPublisher owns Redis Streams + OTel"
```

______________________________________________________________________

### Task 3: publish_task_event_raw + envelope lookup

**Files:**

- Modify: `session_buddy/mcp/tools/tasks_events.py` — add `_ENVELOPE_BY_EVENT_TYPE` dict, `_get_publisher()` helper, `publish_task_event_raw()` function (~50 LOC). Modify `publish_task_event()` body to delegate (~10 LOC).
- Modify: `tests/unit/test_tasks_events.py` (or extend `test_bodai_events_publisher.py`) — add 4 tests.

**Interfaces:**

- Produces:
  - `_ENVELOPE_BY_EVENT_TYPE: dict[str, type[BaseModel]]` — module-level constant
  - `_publisher: BodaiEventsPublisher | None` — module-level slot
  - `_get_publisher() -> BodaiEventsPublisher | None` — accessor
  - `publish_task_event_raw(event_type: str, payload: Mapping[str, Any], redis: Any = None) -> None` — new cross-package entry point

**Steps:**

- [ ] **Step 1: Write the failing test — no publisher = noop**

```python
@pytest.mark.asyncio
async def test_publish_task_event_no_publisher_is_noop(monkeypatch) -> None:
    from session_buddy.mcp.tools import tasks_events
    monkeypatch.setattr(tasks_events, "_publisher", None)
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
    assert fake.calls == [("task.updated", ...)]
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
    await tasks_events.publish_task_event_raw("bogus.event", {})
```

- [ ] **Step 5: Run all tests — expect FAIL**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/unit/test_tasks_events.py -xvs`
Expected: 4 failures.

- [ ] **Step 6: Verify `serialize_event_field` is importable**

Read `session_buddy/mcp/tools/tasks_events.py` and confirm `serialize_event_field` is defined or importable. If it's in the same module, no import needed. If it's elsewhere (e.g., a sibling module), add the explicit import statement (per reviewer finding #5):

```python
from session_buddy.mcp.tools.tasks_events import serialize_event_field  # or from .events if co-located
```

(Adjust to actual location during implementation — verify the symbol exists before importing.)

- [ ] **Step 7: Add `_ENVELOPE_BY_EVENT_TYPE` to `tasks_events.py`**

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

- [ ] **Step 8: Add module-level `_publisher` slot + `_get_publisher()` accessor**

```python
_publisher: BodaiEventsPublisher | None = None


def _get_publisher() -> BodaiEventsPublisher | None:
    return _publisher
```

- [ ] **Step 9: Rewrite `publish_task_event` body**

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

- [ ] **Step 10: Add `publish_task_event_raw` function**

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

- [ ] **Step 11: Run all tests — expect PASS**

Run: `.venv/bin/pytest tests/unit/test_tasks_events.py tests/unit/test_bodai_events_publisher.py -xvs`
Expected: 10 passed (6 publisher + 4 events).

- [ ] **Step 12: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/tools/tasks_events.py tests/unit/test_tasks_events.py
git commit -m "feat(session-buddy): publish_task_event_raw + envelope-by-type lookup"
```

______________________________________________________________________

### Task 4: Lifespan integration in server.py

**Files:**

- Modify: `session_buddy/mcp/server.py` — `_lifespan_with_dhara_cleanup` (lines 279-329, decorator at 278-279); `init_signer_feed_state` pattern at lines 343-357; bare `yield` at line 389. Surface `publisher.health()` in `/health` aggregator.

**Steps:**

- [ ] **Step 1: Read current `_lifespan_with_dhara_cleanup` body**

Read lines 278-390 of `session_buddy/mcp/server.py`. Note:

- Lifespan declared as `AsyncGenerator[None]`.

- Bare `yield` at line 389.

- `init_signer_feed_state` instantiation pattern at lines 343-357.

- [ ] **Step 2: Write a failing test that lifespan instantiates publisher**

In `tests/unit/test_mcp_server.py` (or wherever the lifespan is tested), add:

```python
@pytest.mark.asyncio
async def test_lifespan_instantiates_publisher_when_enabled() -> None:
    from session_buddy.mcp import server as srv
    from session_buddy.mcp.events.bodai_events_publisher import BodaiEventsPublisher
    from session_buddy.mcp.tools import tasks_events

    assert tasks_events._publisher is None
    settings = ...  # construct test settings with bodai_events.enabled=True
    async with srv._lifespan_with_dhara_cleanup(app, settings) as publisher:
        assert isinstance(publisher, BodaiEventsPublisher)
        assert tasks_events._publisher is publisher
    assert tasks_events._publisher is None
```

- [ ] **Step 3: Run the test — expect FAIL**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/unit/test_mcp_server.py::test_lifespan_instantiates_publisher_when_enabled -xvs`
Expected: FAIL.

- [ ] **Step 4: Modify `_lifespan_with_dhara_cleanup` signature + body**

Update the function signature from `AsyncGenerator[None]` to `AsyncGenerator[BodaiEventsPublisher | None, None]` (import BodaiEventsPublisher at module top if not already imported). Replace the bare `yield` at line 389 with:

```python
publisher = BodaiEventsPublisher(
    stream=settings.bodai_events.stream,
    consumer_group=settings.bodai_events.consumer_group,
    enabled=settings.bodai_events.enabled,
)
await publisher.init()
tasks_events._publisher = publisher
try:
    yield publisher
finally:
    await publisher.cleanup()
    tasks_events._publisher = None
```

(Insert this BEFORE the existing `try: yield` block, mirror the `init_signer_feed_state` pattern at lines 343-357. The existing `init_signer_feed_state` yield must remain unchanged unless you've added its teardown — preserve all existing behavior.)

- [ ] **Step 5: Run the test — expect PASS**

Run: `.venv/bin/pytest tests/unit/test_mcp_server.py -xvs`
Expected: PASS.

- [ ] **Step 6: Surface publisher health in `/health` aggregate**

Find the `/health` handler. In the per-feed health checks, add:

```python
publisher_health = await publisher.health() if publisher is not None else True
if not publisher_health:
    raise HTTPException(503, "bodai_events publisher degraded")
```

- [ ] **Step 7: Write a failing test for `/health` degradation**

```python
@pytest.mark.asyncio
async def test_health_returns_503_when_publisher_degraded() -> None:
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

______________________________________________________________________

### Task 5: Skill file update

**Files:**

- Modify: `session_buddy/mcp/skills_catalog/bodai-session-buddy-task-system.md`

**Steps:**

- [ ] **Step 1: Read the skill file**

Run: `cat /Users/les/Projects/session-buddy/session_buddy/mcp/skills_catalog/bodai-session-buddy-task-system.md`

- [ ] **Step 2: Replace T12 note**

Find the T12 line/section. Replace:

> T12 visibility_public (currently hardcoded private)
> with:
> T12 fixed in v1.1; `visibility="public"` is supported.

- [ ] **Step 3: Replace "events emitted to no-op stub" wording**

Find the section about event publishing. Replace "events emitted to a no-op stub" with:

> events emitted to `bodai:events` Redis Stream via oneiric `RedisStreamsQueueAdapter`; consumers read via `XREADGROUP` with consumer group `bodai-task-orphan-sweeper`.

- [ ] **Step 4: Add TaskOrphanSweeper note**

Append a new paragraph:

> v1.1 adds the `TaskOrphanSweeper` in mahavishnu that re-links tasks on `task.handoff_orphan` events.

- [ ] **Step 5: Move team-mode ACL to v2+ scope**

Find the team-mode ACL mention (around line 173 per spec). Move it from "current behavior" to a "v2+ scope" section. Add a one-line note that v1.1 preserves current `team` semantics.

- [ ] **Step 6: Validate frontmatter**

Run: `python scripts/tool_frontmatter_validator.py session_buddy/mcp/skills_catalog/`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/skills_catalog/bodai-session-buddy-task-system.md
git commit -m "docs(session-buddy): skill catalog reflects T12 fix + BodaiEventsPublisher + TaskOrphanSweeper"
```

______________________________________________________________________

### Task 6: Publisher e2e + register pytest marker

**Files:**

- Create: `tests/integration/test_bodai_events_publisher_e2e.py` (~50 LOC)
- Modify: `session_buddy/pyproject.toml` — add `requires_network` to `[tool.pytest].markers` (lines 127-153)

**Steps:**

- [ ] **Step 1: Register `requires_network` marker in session-buddy pyproject.toml**

In `session_buddy/pyproject.toml`, find the `markers = [...]` block (lines 127-153). Add:

```toml
    "requires_network: Test requires network access (Redis, etc.)",
```

- [ ] **Step 2: Find existing e2e fixture pattern**

Search session-buddy for existing Redis fixtures: `pytest-redis`, `docker.services.test`, or similar in `conftest.py`. Adapt the e2e test to use whatever convention the repo has. If neither exists, you must add a `conftest.py` fixture (or a session-scoped Redis instance) — this is a prerequisite.

- [ ] **Step 3: Write the e2e test**

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

- [ ] **Step 4: Run the e2e test**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/integration/test_bodai_events_publisher_e2e.py -xvs`
Expected: PASS (or skip if no Redis available; the test gating is via `requires_network`).

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/pyproject.toml tests/integration/test_bodai_events_publisher_e2e.py
git commit -m "test(session-buddy): BodaiEventsPublisher e2e Redis round-trip"
```

______________________________________________________________________

## Phase 1 gate

Operator merges session-buddy `main` when ready, then bumps `0.30.0 → 0.31.0` and publishes to PyPI.

**Verification before operator bump:**

Run: `cd /Users/les/Projects/session-buddy && crackerjack run -v`
Expected: All checks pass (ruff, ty, refurb, tests).

______________________________________________________________________

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

In `mahavishnu/pyproject.toml`, find the `session-buddy>=0.30.0` entry (line 171). Change to `session-buddy>=0.31.0`.

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

______________________________________________________________________

### Task 8: Switch tasks_handoff.py to publish_task_event_raw

**Files:**

- Modify: `mahavishnu/mcp/tools/tasks_handoff.py` — `_publish_task_event` body (lines 258-273); remove `# ty: ignore[invalid-argument-type]` at line 271

**Steps:**

- [ ] **Step 1: Read current `_publish_task_event`**

Read `mahavishnu/mcp/tools/tasks_handoff.py:258-273`. Confirm current body calls `publish_task_event(event_type, payload)` with raw dict.

- [ ] **Step 2: Swap import + call**

Change the import inside the `try`:

```python
from session_buddy.mcp.tools.tasks_events import (  # ty: ignore[unresolved-import]
    publish_task_event_raw,
)
```

The `publish_task_event_raw` symbol exists in session-buddy per Task 3. Update the call:

```python
await publish_task_event_raw(event_type, payload)
```

This eliminates the `# ty: ignore[invalid-argument-type]` on line 271 (the new function accepts `Mapping[str, Any]`).

- [ ] **Step 3: Run tests**

Run: `cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/unit/test_tasks_handoff.py -xvs`
Expected: PASS.

- [ ] **Step 4: Verify ty directive gone**

Run: `unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/ty check mahavishnu/mcp/tools/tasks_handoff.py`
Expected: No `invalid-argument-type` error on this file.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp/tools/tasks_handoff.py
git commit -m "refactor(mahavishnu): tasks_handoff uses publish_task_event_raw dict API"
```

______________________________________________________________________

### Task 9: TaskOrphanSweeper class + settings + OTel + adapter shape

**Files:**

- Create: `mahavishnu/mcp/sweepers/__init__.py` (empty package marker)
- Create: `mahavishnu/mcp/sweepers/task_orphan_sweeper.py` (~190 LOC)
- Modify: `mahavishnu/settings/mahavishnu.yaml` (add `task_orphan_sweeper:` section)
- Create: `tests/unit/test_task_orphan_sweeper.py` (~220 LOC, 8 tests + OTel span test)

**Interfaces:**

- Produces: `class TaskOrphanSweeper` with:
  - `__init__(*, stream="bodai:events", consumer_group="bodai-task-orphan-sweeper", consumer_name="mahavishnu-{pid}", enabled=True, block_ms=5000, count=10, session_buddy_client=None)`
  - `init()` — outer try/except; logs + swallows on `_init_transport()` failure
  - `cleanup()` — adapter cleanup
  - `health() -> bool` — True when `_consecutive_read_failures < 3`
  - `_backoff_seconds() -> int` — `min(60, 2 ** max(0, _consecutive_read_failures - 1))` (first failure waits 1s; doubles to 2, 4, 8, 16, 32, then caps at 60)
  - `_is_already_handed_off(task: dict) -> bool` — True if `workflow_id` set OR status in `{"done", "cancelled"}`
  - `_run_once()` — public testability helper; runs exactly one read iteration; returns list of (entry, recovered_bool) tuples. No sleep, no cancel.
  - `run_forever()` — main loop; calls `_run_once()` per iteration; cycles_total ticks per iteration; ack after synthetic emit
  - §3 counter attrs: `entities_count`, `cycles_total`, `errors_total`, `last_updated_timestamp`
  - OTel span `task_orphan_sweeper.recover` with attributes `task_id`, `workflow_id`, `outcome ∈ {success, skipped, failed}`

**Steps:**

- [ ] **Step 1: Write the failing test — settings mapping**

```python
def test_consumer_group_maps_to_group_in_settings() -> None:
    from mahavishnu.mcp.sweepers.task_orphan_sweeper import TaskOrphanSweeper
    sweeper = TaskOrphanSweeper()
    assert sweeper._settings.group == "bodai-task-orphan-sweeper"
    assert sweeper._settings.stream == "bodai:events"
```

- [ ] **Step 2: Write the failing test — backoff doubles capped at 60s, starting at 1s**

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

- [ ] **Step 5: Write the failing test — processes orphan event with adapter entry shape**

The `FakeAdapter` returns entries shaped like the real adapter: `[{"message_id": ..., "payload": {"channel": ..., ...}}]`.

```python
@pytest.mark.asyncio
async def test_sweeper_processes_orphan_event(monkeypatch) -> None:
    from mahavishnu.mcp.sweepers import task_orphan_sweeper as mod

    class FakeAdapter:
        def __init__(self):
            self.entries = [{
                "message_id": "1-0",
                "payload": {
                    "channel": "task.handoff_orphan",
                    "task_id": "t-x",
                    "workflow_id": "w-z",
                    "reason": "step_3_update_failed",
                    "orphaned_at": "2026-10-02T00:00:00Z",
                    "actor": "default",
                },
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
            return {"status": "in_progress"}
        async def tasks_update(self, task_id, **kw):
            self.updates.append((task_id, kw))

    adapter = FakeAdapter()
    sb = FakeSB()
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_adapter", adapter)

    await sweeper._run_once()

    assert len(sb.updates) == 1
    assert sb.updates[0][0] == "t-x"
    assert sb.updates[0][1]["metadata"]["workflow_id"] == "w-z"
    assert len(adapter.xadds) == 1
    assert adapter.xadds[0]["channel"] == "task.handoff_completed"
    assert adapter.acked == ["1-0"]
    assert sweeper.entities_count == 1
    assert sweeper.cycles_total >= 1
```

- [ ] **Step 6: Write the failing test — skips already-handed-off**

```python
@pytest.mark.asyncio
async def test_sweeper_skips_if_workflow_id_already_set(monkeypatch) -> None:
    # Same FakeAdapter pattern as Step 5, but FakeSB.tasks_get returns
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

- [ ] **Step 8: Write the failing test — OTel span on recovery**

```python
@pytest.mark.asyncio
async def test_sweeper_emits_otel_span_on_recovery(monkeypatch) -> None:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # ... set up FakeAdapter with one orphan entry, FakeSB returning in_progress ...
    sweeper = TaskOrphanSweeper(session_buddy_client=sb)
    monkeypatch.setattr(sweeper, "_adapter", adapter)
    await sweeper._run_once()

    spans = exporter.get_finished_spans()
    recover = [s for s in spans if s.name == "task_orphan_sweeper.recover"]
    assert len(recover) == 1
    assert recover[0].attributes["task_id"] == "t-x"
    assert recover[0].attributes["workflow_id"] == "w-z"
    assert recover[0].attributes["outcome"] == "success"
```

- [ ] **Step 9: Write the failing test — init failure is swallowed**

```python
@pytest.mark.asyncio
async def test_sweeper_init_failure_is_swallowed(monkeypatch) -> None:
    sweeper = TaskOrphanSweeper()
    async def boom() -> None: raise RuntimeError("redis down")
    monkeypatch.setattr(sweeper._adapter, "init", boom)
    await sweeper.init()
    assert await sweeper.health() is False
```

- [ ] **Step 10: Run all tests — expect FAIL**

Run: `cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/unit/test_task_orphan_sweeper.py -xvs`
Expected: ImportError.

- [ ] **Step 11: Create `mahavishnu/mcp/sweepers/__init__.py`**

Empty file.

- [ ] **Step 12: Implement `mahavishnu/mcp/sweepers/task_orphan_sweeper.py`**

```python
"""Task orphan sweeper — recovers from task.handoff_orphan events."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from oneiric.adapters.queue.redis_streams import (
    RedisStreamsQueueAdapter,
    RedisStreamsQueueSettings,
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)


class TaskHandoffOrphan(BaseModel):
    """Sweeper's view of an orphan event payload."""
    task_id: str
    workflow_id: str
    reason: str
    orphaned_at: str
    actor: str = "default"


class TaskOrphanSweeper:
    """Subscribes to ``bodai:events`` Redis Stream (consumer group
    ``bodai-task-orphan-sweeper``), filters on payload channel=task.handoff_orphan,
    re-links tasks via session-buddy's ``tasks_update``.

    Adapter entry shape (per oneiric RedisStreamsQueueAdapter._format_entries):
    each entry returned by read() is [ {"message_id": message_id, "payload": <XADD-fields-dict>} ].
    Channel filter reads entry["payload"]["channel"] — never from entry root.

    Recovery loop per orphan entry:
      1. _is_already_handed_off(task) check (uses session_buddy.tasks_get).
      2. If not handed off: session_buddy.tasks_update(task_id, metadata={...}).
      3. Emit synthetic task.handoff_completed event.
      4. ack([entry["message_id"]]) AFTER synthetic emit.

    Idempotency via step 2.

    Heartbeat: health() returns False after 3 consecutive read() failures.
    Backoff: 1s, 2s, 4s, 8s, 16s, 32s, capped at 60s.

    §3 counters: same policy as BodaiEventsPublisher.
    OTel span: task_orphan_sweeper.recover with task_id, workflow_id, outcome.
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
        """Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, capped at 60s."""
        return min(60, 2 ** max(0, self._consecutive_read_failures - 1))

    async def _is_already_handed_off(self, task: dict[str, Any]) -> bool:
        if task.get("workflow_id"):
            return True
        if task.get("status") in {"done", "cancelled"}:
            return True
        return False

    async def _recover_orphan(self, entry: dict[str, Any]) -> str:
        """Process one orphan entry: idempotency check → tasks_update →
        synthetic emit → ack.

        Returns the outcome string for the OTel span attribute.
        """
        # Adapter entry shape: {"message_id": ..., "payload": <XADD-fields-dict>}
        payload = entry.get("payload", {})
        orphan = TaskHandoffOrphan(**{k: v for k, v in payload.items()
                                       if k in TaskHandoffOrphan.model_fields})
        if self._session_buddy is None:
            logger.warning("task_orphan_sweeper: no session_buddy client; skipping")
            return "skipped"
        task = await self._session_buddy.tasks_get(orphan.task_id)
        if await self._is_already_handed_off(task):
            return "skipped"
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
        return "success"

    async def _run_once(self) -> list[tuple[dict[str, Any], str]]:
        """Run exactly one read iteration. Returns list of (entry, outcome).

        Public testability helper — test code calls this directly without
        needing to manage asyncio cancellation timing.
        """
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
            return []

        results: list[tuple[dict[str, Any], str]] = []
        for entry in entries:
            payload = entry.get("payload", {})
            if payload.get("channel") != "task.handoff_orphan":
                continue
            try:
                with _tracer.start_as_current_span("task_orphan_sweeper.recover") as span:
                    span.set_attribute("task_id", payload.get("task_id", "unknown"))
                    span.set_attribute("workflow_id", payload.get("workflow_id", "unknown"))
                    outcome = await self._recover_orphan(entry)
                    span.set_attribute("outcome", outcome)
                    results.append((entry, outcome))
            except Exception as exc:
                self.errors_total += 1
                with _tracer.start_as_current_span("task_orphan_sweeper.recover") as span:
                    span.set_attribute("task_id", payload.get("task_id", "unknown"))
                    span.set_attribute("workflow_id", payload.get("workflow_id", "unknown"))
                    span.set_attribute("outcome", "failed")
                logger.warning(
                    "task_orphan_sweeper: recover failed for %s: %s",
                    payload.get("task_id"), exc,
                )
            # ack AFTER recovery attempt (success or fail) — at-most-once
            await self._adapter.ack([entry["message_id"]])
        return results

    async def run_forever(self) -> None:
        while True:
            await self._run_once()
```

- [ ] **Step 13: Add `task_orphan_sweeper` settings**

In `mahavishnu/settings/mahavishnu.yaml`:

```yaml
task_orphan_sweeper:
  enabled: true
  stream: "bodai:events"
  consumer_group: "bodai-task-orphan-sweeper"
  block_ms: 5000
  count: 10
```

- [ ] **Step 14: Run all tests — expect PASS**

Run: `unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/unit/test_task_orphan_sweeper.py -xvs`
Expected: 9 passed (8 + OTel).

- [ ] **Step 15: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp/sweepers/ mahavishnu/settings/mahavishnu.yaml tests/unit/test_task_orphan_sweeper.py
git commit -m "feat(mahavishnu): TaskOrphanSweeper consumes task.handoff_orphan events"
```

______________________________________________________________________

### Task 10: Sweeper lifecycle integration

**Files:**

- Modify: `mahavishnu/mcp/lifecycle.py` — `start_server(server, host=, port=)` (line 14, positional `server` required); `stop_server(server)` (line 147, positional `server` required); `plan_index` periodic runner pattern at lines 95-158; `/health` aggregator.

**Steps:**

- [ ] **Step 1: Read `start_server()` and `stop_server()` in lifecycle.py**

Read `mahavishnu/mcp/lifecycle.py`. Note the signatures:

- `start_server(server: Any, host: str = "127.0.0.1", port: int = 3000) -> None` (line 14) — `server` is REQUIRED positional
- `stop_server(server: Any) -> None` (line 147) — `server` is REQUIRED positional

Verify `get_session_buddy_client()` is a module-level factory in `lifecycle.py` (grep for it; if absent, inline a stub that returns None — the sweeper handles `None` via the "no session_buddy client; skipping" log path).

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

    # ... await start_server(server) ...
    assert "sweeper" in captured
```

(Adapt to the actual lifecycle test fixture.)

- [ ] **Step 3: Modify `start_server()` to spawn sweeper**

Inside `start_server(server, host=, port=)` (mirror the `plan_index` periodic runner at lines 95-158), add:

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
server._task_orphan_sweeper = sweeper
server._task_orphan_sweeper_task = sweeper_task
```

(Adapt state-management to the file's actual pattern; stash on `server` since `server` is the only required positional.)

- [ ] **Step 4: Modify `stop_server(server)` to cancel sweeper**

In `stop_server(server)` (mirror the `plan_index` cleanup pattern):

```python
if hasattr(server, "_task_orphan_sweeper_task"):
    server._task_orphan_sweeper_task.cancel()
    try:
        await server._task_orphan_sweeper_task
    except asyncio.CancelledError:
        pass
if hasattr(server, "_task_orphan_sweeper"):
    await server._task_orphan_sweeper.cleanup()
```

- [ ] **Step 5: Surface `sweeper.health()` in `/health` aggregate**

In the `/health` handler, add:

```python
if hasattr(server, "_task_orphan_sweeper"):
    if not await server._task_orphan_sweeper.health():
        raise HTTPException(503, "task_orphan_sweeper degraded")
```

- [ ] **Step 6: Write a failing test for sweeper /health degradation**

```python
@pytest.mark.asyncio
async def test_health_returns_503_when_sweeper_degraded(monkeypatch) -> None:
    # Stash a sweeper whose health() returns False on the server
    # ...
    response = await client.get("/health")
    assert response.status_code == 503
```

- [ ] **Step 7: Run lifecycle tests — expect PASS**

Run: `unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/unit/test_lifecycle.py -xvs`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp/lifecycle.py tests/unit/test_lifecycle.py
git commit -m "feat(mahavishnu): wire TaskOrphanSweeper into start_server/stop_server"
```

______________________________________________________________________

### Task 11: 10-LOC subscriber patch in bodai_subscriber.py

**Files:**

- Modify: `mahavishnu/core/events/bodai_subscriber.py` — add fourth early branch to `_decode_envelope` (lines 346-402), inserted BEFORE line 367 (~10 LOC)
- Modify: `tests/unit/test_bodai_subscriber.py` (or extend existing) — add `test_decode_envelope_handles_flat_shape` (~30 LOC)

**Steps:**

- [ ] **Step 1: Read `_decode_envelope` body**

Read `mahavishnu/core/events/bodai_subscriber.py:346-402` (verified at recon). Note the three existing paths and where the early-return must go — the `envelope_blob = message_payload.get("envelope")` lookup is at line 367.

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
    assert envelope.topic == "task.created"
    assert envelope.payload["task_id"] == "t-x"
    assert envelope.payload["actor"] == "a"
```

(Adapt to the actual envelope class shape — `EventEnvelope` vs `MahavishnuEventEnvelope` — and the actual field names.)

- [ ] **Step 3: Run the test — expect FAIL**

Run: `cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/unit/test_bodai_subscriber.py::test_decode_envelope_handles_flat_shape -xvs`
Expected: FAIL.

- [ ] **Step 4: Add the fourth early branch to `_decode_envelope`**

In `mahavishnu/core/events/bodai_subscriber.py`, BEFORE line 367 (`envelope_blob = message_payload.get("envelope")`), insert:

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

______________________________________________________________________

### Task 12: Integration test for sweeper e2e

**Files:**

- Create: `tests/integration/test_task_orphan_sweeper_e2e.py` (~80 LOC)

**Steps:**

- [ ] **Step 1: Find existing e2e fixture**

Find an integration test that uses `pytest-redis` or `docker.services.test` in mahavishnu's `tests/integration/` (mahavishnu registers `requires_network` per the verified pyproject.toml line 482). Adapt to existing convention. If no Redis fixture exists, add a session-scoped fixture to `tests/integration/conftest.py` first.

- [ ] **Step 2: Write the e2e test**

```python
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

    # Run one iteration via _run_once (deterministic, no asyncio.sleep timing)
    await sweeper._run_once()
    await sweeper.cleanup()

    assert len(sb.updates) == 1
    assert sb.updates[0][1]["metadata"]["workflow_id"] == "w-z"
    assert sweeper.entities_count == 1
    assert sweeper.cycles_total >= 1

    # Verify synthetic emit
    entries = await redis_client.xreadgroup(
        groupname="test-sweeper-group",
        consumername="mahavishnu-test",
        streams={"bodai:events:test": "0"},
        count=10,
    )
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

- [ ] **Step 3: Run the e2e test**

Run: `cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && .venv/bin/pytest tests/integration/test_task_orphan_sweeper_e2e.py -xvs`
Expected: PASS (or skip if no Redis available).

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add tests/integration/test_task_orphan_sweeper_e2e.py
git commit -m "test(mahavishnu): TaskOrphanSweeper e2e Redis round-trip + ack verification"
```

______________________________________________________________________

## Phase 2 gate

Operator merges mahavishnu `main` when ready, then bumps `0.31.0 → 0.32.0` and publishes.

**Verification before operator bump:**

Run: `cd /Users/les/Projects/mahavishnu && unset VIRTUAL_ENV UV_ACTIVE && crackerjack run -v`
Expected: All checks pass (ruff, ty, refurb, tests).

______________________________________________________________________

## Self-Review (plan author, post-reviewer-folding)

- [x] No placeholders ("TBD", "TODO", "FIXME")
- [x] No internal contradictions
- [x] Cross-repo order matches the `session-buddy >= 0.31.0` pin (Task 7 gates Phase 2)
- [x] Every task ends with an atomic commit (`git commit` step)
- [x] Every task has a TDD pattern: failing test → impl → passing test
- [x] Failure semantics: publisher `init()` failure does not block mutations (Task 2 step 9 + Task 4)
- [x] §3 metrics enumerated for both `BodaiEventsPublisher` and `TaskOrphanSweeper` (Tasks 2 + 9)
- [x] **OTel spans added for both publisher and sweeper** (Tasks 2 + 9 — reviewer blocker fix)
- [x] **Sweeper reads channel from `entry["payload"]["channel"]`, not entry root** (Task 9 — reviewer blocker fix)
- [x] **Settings file path corrected: `session-buddy.yaml` (hyphen)** (Task 2 — reviewer blocker fix)
- [x] **`requires_network` marker registered in session-buddy pyproject.toml** (Task 6 — reviewer blocker fix)
- [x] Integration Contracts mapped to tasks (Items 1, 2, 3 → Tasks 1, 2+3+4, 9)
- [x] Test paths + markers pinned per project convention (`pytest.mark.asyncio`, `integration`, `requires_network`)
- [x] Skill file update enumerated (Task 5)
- [x] Pre-1.0 merge policy respected (Phase 1 gate + Phase 2 gate, both via operator merge)
- [x] Version-bump rule respected (operator, not implementer; pin-vs-version split per Tasks 7 + 8)
- [x] Sweeper idempotency covers `done`/`cancelled` (Task 9 step 7)
- [x] Default `bodai_events.enabled=True` (Task 2 step 10)
- [x] `consumer_group` → `group` mapping explicit (Tasks 2 + 9)
- [x] Publisher init-failure swallow site named (`_init_transport` + outer try/except)
- [x] Sweeper idempotency check is a named method (`_is_already_handed_off`)
- [x] Heartbeat counter `_consecutive_read_failures` and `_backoff_seconds()` helper (Task 9)
- [x] **Backoff sequence matches spec: 1s, 2s, 4s, 8s, 16s, 32s, capped at 60s** (Task 9 step 12 + step 2 — reviewer fix)
- [x] **Skip decorator removal is 8 lines (2022-2029), not 3 or 6** (Task 1 step 1 — reviewer fix)
- [x] **`start_server(server, host=, port=)` requires positional `server`** (Task 10 step 1 + step 3 — reviewer fix)
- [x] **`get_session_buddy_client()` verification step** (Task 10 step 1 — reviewer fix)
- [x] **Lifespan signature changes from `AsyncGenerator[None]` to `AsyncGenerator[BodaiEventsPublisher \| None]`** (Task 4 step 4 — reviewer fix)
- [x] **`init_signer_feed_state` at lines 343-357** (Task 4 — reviewer fix)
- [x] **`_decode_envelope` at lines 346-402; `envelope_blob` lookup at line 367** (Task 11 — reviewer fix)
- [x] **`_FakeAdapter` reuse claim corrected** (Task 9 step 5 — reviewer fix)
- [x] **e2e fixtures require pre-existing Redis fixture pattern** (Tasks 6 + 12 step 1 — reviewer fix)
- [x] **Spec deviations table corrected on 3 misclaim rows** (lines 50-58 — reviewer fix)
- [x] **`cycles_total` assertion added to sweeper tests** (Task 9 step 5 — reviewer fix)
- [x] **`/health` degradation test for sweeper added** (Task 10 step 6 — reviewer fix)
- [x] **`_run_once` testability helper added** (Task 9 — reviewer fix)
- [x] All Global Constraints copied verbatim from spec
- [x] **Adapter entry shape pinned: `{"message_id": ..., "payload": <XADD-fields-dict>}`** (Global Constraints + Task 9)

## Execution Handoff

Plan complete and saved to `/Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-10-02-bodai-task-system-v1.1.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
1. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.
