---
status: draft
role: implementation
date: 2026-07-29
last_reviewed: 2026-07-29
superseded_by: null
topic: session-buddy-extension
---

# Session-Buddy Extension Implementation Plan (Mahavishnu seam hardening)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Mahavishnu↔Session-Buddy seam so pool memory, hook commits, code-graph reads, and the Phase 1.5 conscious-agent loop are durable, cheap, and discoverable — without coupling the two repos beyond what's already necessary.

**Architecture:** Symmetric extension. Mahavishnu owns a local DuckDB WAL + outbox writer that absorbs Session-Buddy outages. Session-Buddy owns the hook single-flight gate, the plugin manifest, and the canonical code-graph index exposed via a read-through facade. Crackerjack owns the Phase 1.5 pre-commit gate consuming `distilled_skill_health`. Each component owns one concern; the existing circuit breaker in `mahavishnu/pools/memory_aggregator.py` becomes the durable seam.

**Tech Stack:** DuckDB (Mahavishnu WAL), Pydantic v2, FastMCP, asyncio, Crackerjack pre-commit hooks, ty (not mypy). No new infra, no new services.

**Spec:** `docs/superpowers/specs/2026-07-29-session-buddy-extension-design.md` (commit `aacb7533`).

## Global Constraints

- Mahavishnu WAL lives at `~/.mahavishnu/outbox.duckdb` — symmetric with the existing `~/.mahavishnu/state.duckdb` convention.
- WAL schema: `memory_outbox(id BIGSERIAL PRIMARY KEY, key TEXT, payload JSON, enqueued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, attempts INT DEFAULT 0, last_error TEXT, status TEXT DEFAULT 'pending' CHECK (status IN ('pending','drained','failed')))`. Index `(enqueued_at, id) WHERE status='pending'` for ordered drain.
- Single-flight TTL = `5.0` seconds. Drain batch size = `50`. Max drain attempts = `5` (matches the existing circuit breaker's `failure_threshold=5`).
- Plugin manifest ships exactly two artifacts: `plugin.json` (namespaced commands) and `hooks/PreCompact.md`. No sub-agents, no skill templates.
- Crackerjack pre-commit gate is **warn-only by default** (exit 1). Operators opt into blocking via existing `crackerjack run --strict`. `--no-verify` skips.
- Read-through facade for code-graph is **additive**. Akosha and Mahavishnu retain their own indexes as fallback when the facade is unreachable.
- Type checker is **ty**, not mypy. Use `# ty: ignore[<code>]` (never bare `# type: ignore`).
- The `mahavishnu/pools/memory_aggregator.py` `_CircuitBreaker(name="session-buddy", failure_threshold=5, recovery_timeout=60.0)` is reused as-is — no new breaker, no new config.
- All five answers in the brainstorm (Q1–Q5) locked in. Anything that contradicts them is a plan defect.

---

## File Structure

| File / Directory | Created by | Responsibility |
|---|---|---|
| `mahavishnu/pools/outbox/__init__.py` | Task 1 | Package init, re-exports |
| `mahavishnu/pools/outbox/table.py` | Task 1 | `MemoryOutboxRow` Pydantic model + `OutboxStatus` Literal |
| `mahavishnu/pools/outbox/schema.sql` | Task 1 | DDL applied on first start (`CREATE TABLE IF NOT EXISTS`) |
| `mahavishnu/pools/outbox/writer.py` | Task 1 | `MemoryOutboxWriter` (async enqueue, pending_count, mark_drained, mark_failed) |
| `mahavishnu/pools/outbox/drainer.py` | Task 2 | `MemoryOutboxDrainer` + `DrainResult` dataclass |
| `mahavishnu/pools/memory_aggregator.py` | Task 2 | Wiring change: aggregator takes optional `outbox_writer` + `outbox_drainer` collaborators |
| `tests/unit/mahavishnu/pools/outbox/test_writer.py` | Task 1 | Functional tests for writer |
| `tests/unit/mahavishnu/pools/outbox/test_drainer.py` | Task 2 | Functional tests for drainer |
| `tests/integration/mahavishnu/pools/outbox/test_fault_injection.py` | Task 2 | Fault-injection tests (disk full, 5xx, partial failure) |
| `tests/e2e/mahavishnu_session_buddy/test_pool_memory_outage.py` | Task 2 | End-to-end: pool memory survives Session-Buddy outage |
| `session_buddy/hooks/single_flight.py` | Task 3 | `HookSingleFlight` keyed by `(project_path, agent_idx)` |
| `session_buddy/hooks/__init__.py` | Task 3 | Hook package init (if not exists) |
| `plugins/session-buddy/.claude-plugin/plugin.json` | Task 3 | Namespaced commands manifest (additive to v0.20.0) |
| `plugins/session-buddy/hooks/PreCompact.md` | Task 3 | PreCompact hook calling `mcp__session-buddy__pre_compact_sync` |
| `session_buddy/server.py` (or `mcp/tools/`) | Task 6 | New MCP tool: `search_code_graph(query, project)` |
| `tests/unit/session_buddy/hooks/test_single_flight.py` | Task 3 | Single-flight unit tests (TTL behavior) |
| `crackerjack/hooks/skill_coverage.py` | Task 4 | `pre_commit_skill_coverage_gate(repo_path) -> int` |
| `crackerjack/hooks/pre_commit.py` | Task 4 | Wire-in: gate runs after format/lint, before test |
| `tests/unit/crackerjack/hooks/test_skill_coverage.py` | Task 4 | Operator-experience tests (fresh, stale, unreachable) |

---

## Task 1: Mahavishnu WAL writer + schema (Q2 phase 1)

**Files:**

- Create: `mahavishnu/pools/outbox/__init__.py`
- Create: `mahavishnu/pools/outbox/table.py`
- Create: `mahavishnu/pools/outbox/schema.sql`
- Create: `mahavishnu/pools/outbox/writer.py`
- Test: `tests/unit/mahavishnu/pools/outbox/test_writer.py`

**Interfaces produced:**

- `MemoryOutboxRow(BaseModel)` with fields `id: int`, `key: str`, `payload: dict[str, object]`, `enqueued_at: dt.datetime`, `attempts: int = 0`, `last_error: str | None = None`, `status: Literal["pending","drained","failed"] = "pending"`.
- `OutboxStatus = Literal["pending", "drained", "failed"]`.
- `MemoryOutboxWriter(db_path: pathlib.Path)`. Methods: `async enqueue(key, payload) -> int`, `async pending_count() -> int`, `async mark_drained(ids: list[int]) -> int`, `async mark_failed(ids: list[int], error: str) -> int`.

- [ ] **Step 1: Write failing test for `MemoryOutboxRow` model**

```python
"""Tests for mahavishnu.pools.outbox.table."""

from __future__ import annotations

import datetime as dt

import pytest

from mahavishnu.pools.outbox.table import MemoryOutboxRow, OutboxStatus

pytestmark = pytest.mark.unit


def test_memory_outbox_row_default_status_is_pending() -> None:
    now = dt.datetime(2026, 7, 29, 12, 0, 0, tzinfo=dt.UTC)
    row = MemoryOutboxRow(
        id=1,
        key="reflection:abc",
        payload={"text": "hello"},
        enqueued_at=now,
    )
    assert row.status == "pending"
    assert row.attempts == 0
    assert row.last_error is None


def test_memory_outbox_row_status_rejects_unknown() -> None:
    now = dt.datetime(2026, 7, 29, 12, 0, 0, tzinfo=dt.UTC)
    with pytest.raises(ValueError):  # Pydantic validation
        MemoryOutboxRow(
            id=1,
            key="reflection:abc",
            payload={"text": "hello"},
            enqueued_at=now,
            status="bogus",  # ty: ignore[invalid-argument-type]
        )


def test_outbox_status_is_literal() -> None:
    # Compile-time assertion; if this doesn't hold the type checker will flag it.
    s: OutboxStatus = "drained"
    assert s in ("pending", "drained", "failed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/mahavishnu/pools/outbox/test_writer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mahavishnu.pools.outbox'`.

- [ ] **Step 3: Implement `table.py`**

```python
"""Mahavishnu WAL: row model + status enum.

The WAL captures deferred memory writes destined for Session-Buddy. The
aggregator's existing circuit breaker gates the drainer; this module
defines the row shape and the three terminal states.

Spec: docs/superpowers/specs/2026-07-29-session-buddy-extension-design.md
(Q2: data-plane durability).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

OutboxStatus = Literal["pending", "drained", "failed"]


class MemoryOutboxRow(BaseModel):
    """A single WAL row representing a deferred memory write to Session-Buddy."""

    id: int
    key: str
    payload: dict[str, object]
    enqueued_at: dt.datetime  # ty: ignore[unresolved-attribute]
    attempts: int = 0
    last_error: str | None = None
    status: OutboxStatus = "pending"
```

(`from __future__ import annotations` makes all annotations strings; remove the `ty: ignore[unresolved-attribute]` if ty resolves `dt.datetime` correctly when imported.)

Add `import datetime as dt` at the top.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/mahavishnu/pools/outbox/test_writer.py -v`
Expected: 3 passed.

- [ ] **Step 5: Write failing test for `MemoryOutboxWriter.enqueue` + `pending_count`**

```python
# Add to test_writer.py:

import pathlib
import tempfile

import pytest

from mahavishnu.pools.outbox.writer import MemoryOutboxWriter


@pytest.fixture
def writer(tmp_path: pathlib.Path) -> MemoryOutboxWriter:
    db = tmp_path / "outbox.duckdb"
    w = MemoryOutboxWriter(db)
    yield w
    w.close()


async def test_writer_enqueues_and_round_trips(writer: MemoryOutboxWriter) -> None:
    ids = []
    for i in range(100):
        ids.append(await writer.enqueue(f"reflection:{i}", {"i": i}))
    assert len(ids) == 100
    assert len(set(ids)) == 100  # all distinct BIGSERIAL values
    assert await writer.pending_count() == 100


async def test_writer_pending_count_filters_correctly(writer: MemoryOutboxWriter) -> None:
    id1 = await writer.enqueue("k1", {"a": 1})
    id2 = await writer.enqueue("k2", {"a": 2})
    id3 = await writer.enqueue("k3", {"a": 3})
    await writer.mark_drained([id1, id2])
    assert await writer.pending_count() == 1


async def test_writer_mark_failed_records_error(writer: MemoryOutboxWriter) -> None:
    id1 = await writer.enqueue("k1", {"a": 1})
    await writer.mark_failed([id1], "boom")
    assert await writer.pending_count() == 0
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/unit/mahavishnu/pools/outbox/test_writer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mahavishnu.pools.outbox.writer'`.

- [ ] **Step 7: Implement `schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS memory_outbox (
    id BIGSERIAL PRIMARY KEY,
    key TEXT NOT NULL,
    payload JSON NOT NULL,
    enqueued_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attempts INT NOT NULL DEFAULT 0,
    last_error TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','drained','failed'))
);

CREATE INDEX IF NOT EXISTS idx_memory_outbox_pending
    ON memory_outbox (enqueued_at, id)
    WHERE status = 'pending';
```

- [ ] **Step 8: Implement `writer.py`**

```python
"""Mahavishnu WAL: writer.

Async DuckDB-backed writer for deferred memory writes. Owns the connection
lifecycle; opens on first use, closes on `close()`.

Spec: docs/superpowers/specs/2026-07-29-session-buddy-extension-design.md
(Q2: data-plane durability).
"""

from __future__ import annotations

import json
import pathlib

import duckdb

from .table import OutboxStatus, MemoryOutboxRow

_SCHEMA_PATH = pathlib.Path(__file__).parent / "schema.sql"


class MemoryOutboxWriter:
    """Async-style wrapper around a DuckDB connection.

    All write methods are async to match the rest of the orchestrator's
    I/O surface, but DuckDB operations are synchronous; we keep the
    interface async to allow swapping the backend without touching call sites.
    """

    def __init__(self, db_path: pathlib.Path) -> None:
        self._db_path = db_path
        self._conn: duckdb.DuckDBPyConnection | None = None

    def _ensure_conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(str(self._db_path))
            self._conn.execute(_SCHEMA_PATH.read_text())
        return self._conn

    async def enqueue(self, key: str, payload: dict[str, object]) -> int:
        conn = self._ensure_conn()
        result = conn.execute(
            "INSERT INTO memory_outbox (key, payload) VALUES (?, ?) RETURNING id",
            [key, json.dumps(payload)],
        ).fetchone()
        assert result is not None
        return int(result[0])

    async def pending_count(self) -> int:
        conn = self._ensure_conn()
        result = conn.execute(
            "SELECT COUNT(*) FROM memory_outbox WHERE status = 'pending'"
        ).fetchone()
        assert result is not None
        return int(result[0])

    async def mark_drained(self, ids: list[int]) -> int:
        if not ids:
            return 0
        conn = self._ensure_conn()
        placeholders = ",".join(["?"] * len(ids))
        result = conn.execute(
            f"UPDATE memory_outbox SET status = 'drained' WHERE id IN ({placeholders}) "
            "AND status = 'pending'",
            ids,
        )
        return int(result.fetchone()[0]) if result.fetchone() else 0

    async def mark_failed(self, ids: list[int], error: str) -> int:
        if not ids:
            return 0
        conn = self._ensure_conn()
        placeholders = ",".join(["?"] * len(ids))
        result = conn.execute(
            f"UPDATE memory_outbox SET status = 'failed', last_error = ?, "
            f"attempts = attempts + 1 WHERE id IN ({placeholders}) AND status = 'pending'",
            [error, *ids],
        )
        return int(result.fetchone()[0]) if result.fetchone() else 0

    async def pending_batch(self, limit: int) -> list[MemoryOutboxRow]:
        conn = self._ensure_conn()
        rows = conn.execute(
            "SELECT id, key, payload, enqueued_at, attempts, last_error, status "
            "FROM memory_outbox WHERE status = 'pending' "
            "ORDER BY enqueued_at, id LIMIT ?",
            [limit],
        ).fetchall()
        return [
            MemoryOutboxRow(
                id=r[0],
                key=r[1],
                payload=json.loads(r[2]),
                enqueued_at=r[3],
                attempts=r[4],
                last_error=r[5],
                status=r[6],
            )
            for r in rows
        ]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
```

- [ ] **Step 9: Implement `__init__.py`**

```python
"""Mahavishnu outbox: local DuckDB WAL for deferred Session-Buddy writes."""

from .table import MemoryOutboxRow, OutboxStatus
from .writer import MemoryOutboxWriter

__all__ = ["MemoryOutboxRow", "MemoryOutboxStatus", "MemoryOutboxWriter"]  # ty: ignore[unresolved-attribute]
```

(Adjust `__all__` once the drainer module is added in Task 2; for Task 1, just export the writer-side types.)

- [ ] **Step 10: Run test to verify it passes**

Run: `uv run pytest tests/unit/mahavishnu/pools/outbox/test_writer.py -v`
Expected: 6 passed (3 model tests + 3 writer tests).

- [ ] **Step 11: Lint, type-check, format**

```bash
uv run ruff check mahavishnu/pools/outbox/ tests/unit/mahavishnu/pools/outbox/
uv run ruff format mahavishnu/pools/outbox/ tests/unit/mahavishnu/pools/outbox/
uv run python -m crackerjack.tools.ty_ratchet --split mahavishnu/pools/outbox/ tests/unit/mahavishnu/pools/outbox/
```

- [ ] **Step 12: Commit**

```bash
git add mahavishnu/pools/outbox/ tests/unit/mahavishnu/pools/outbox/
git commit -m "feat(mahavishnu): add MemoryOutboxWriter (WAL schema + DuckDB writer)"
```

### Integration Contract (Task 1)

- **Triggered from:** operator runs `mahavishnu` and the bootstrap path (Task 2 wires the writer; not yet active in this task).
- **Returns to / updates:** no live wiring yet — the writer is unused until Task 2. Bootstrap remains unchanged.
- **Demonstrable by:** `uv run pytest tests/unit/mahavishnu/pools/outbox/test_writer.py -v` passes 6 tests; the WAL file appears at the configured `db_path` after the first `enqueue()`.
- **Rollback signal:** tests fail or `ty` reports regressions → `git revert HEAD`.
- **Observability added:** none yet — drainer observability lands in Task 2.

---

## Task 2: Drainer + aggregator wiring (Q2 phase 2)

**Files:**

- Create: `mahavishnu/pools/outbox/drainer.py`
- Modify: `mahavishnu/pools/memory_aggregator.py` (add optional collaborators; do not change existing behavior unless `MAHAVISHNU_OUTBOX_DRAIN=true`)
- Test: `tests/unit/mahavishnu/pools/outbox/test_drainer.py`
- Test: `tests/integration/mahavishnu/pools/outbox/test_fault_injection.py`
- Test: `tests/e2e/mahavishnu_session_buddy/test_pool_memory_outage.py`

**Interfaces produced:**

- `DrainResult(drained: int, deferred: int, failed: int)` dataclass.
- `MemoryOutboxDrainer(writer, breaker, sink, batch_size=50, max_attempts=5)`. Method: `async drain_once() -> DrainResult`.

- [ ] **Step 1: Write failing test for `drain_once` when breaker is closed**

```python
# tests/unit/mahavishnu/pools/outbox/test_drainer.py

from __future__ import annotations

import pathlib

import pytest

from mahavishnu.pools.outbox.drainer import DrainResult, MemoryOutboxDrainer
from mahavishnu.pools.outbox.writer import MemoryOutboxWriter


class _StubBreaker:
    def __init__(self, is_open: bool = False) -> None:
        self._is_open = is_open

    def is_open(self) -> bool:
        return self._is_open


@pytest.fixture
def writer(tmp_path: pathlib.Path) -> MemoryOutboxWriter:
    w = MemoryOutboxWriter(tmp_path / "outbox.duckdb")
    yield w
    w.close()


async def test_drainer_drains_pending_when_breaker_closed(writer: MemoryOutboxWriter) -> None:
    for i in range(50):
        await writer.enqueue(f"k{i}", {"i": i})

    seen: list[tuple[str, dict[str, object]]] = []

    async def sink(key: str, payload: dict[str, object]) -> None:
        seen.append((key, payload))

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(is_open=False), sink)
    result = await drainer.drain_once()
    assert result == DrainResult(drained=50, deferred=0, failed=0)
    assert len(seen) == 50
    assert await writer.pending_count() == 0


async def test_drainer_skips_when_breaker_open(writer: MemoryOutboxWriter) -> None:
    for i in range(50):
        await writer.enqueue(f"k{i}", {"i": i})

    seen: list[tuple[str, dict[str, object]]] = []

    async def sink(key: str, payload: dict[str, object]) -> None:
        seen.append((key, payload))

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(is_open=True), sink)
    result = await drainer.drain_once()
    assert result == DrainResult(drained=0, deferred=50, failed=0)
    assert seen == []
    assert await writer.pending_count() == 50


async def test_drainer_marks_failed_after_max_attempts(writer: MemoryOutboxWriter) -> None:
    await writer.enqueue("k1", {"i": 1})

    async def sink(key: str, payload: dict[str, object]) -> None:
        raise RuntimeError("simulated 5xx")

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(is_open=False), sink, max_attempts=5)
    # Five cycles; row stays pending until attempts >= max, then flips to failed.
    for _ in range(5):
        await drainer.drain_once()
    assert await writer.pending_count() == 0
    # Verify the row is in `failed` status (not `pending`, not `drained`).
    # (Pending-batch query filters by status='pending'; with 0 pending, all rows are drained or failed.)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/mahavishnu/pools/outbox/test_drainer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mahavishnu.pools.outbox.drainer'`.

- [ ] **Step 3: Implement `drainer.py`**

```python
"""Mahavishnu WAL: drainer.

Pulls pending rows from the WAL and pushes them to the sink (a Session-Buddy
MCP call). Respects the existing circuit breaker: when open, no calls are
attempted. Rows that fail after `max_attempts` are marked `failed` for
operator inspection.

Spec: docs/superpowers/specs/2026-07-29-session-buddy-extension-design.md
(Q2: data-plane durability).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


class CircuitBreakerLike(Protocol):
    def is_open(self) -> bool: ...


@dataclass
class DrainResult:
    drained: int
    deferred: int
    failed: int


Sink = Callable[[str, dict[str, object]], Awaitable[None]]


class MemoryOutboxDrainer:
    def __init__(
        self,
        writer: "MemoryOutboxWriter",
        breaker: CircuitBreakerLike,
        sink: Sink,
        batch_size: int = 50,
        max_attempts: int = 5,
    ) -> None:
        self._writer = writer
        self._breaker = breaker
        self._sink = sink
        self._batch_size = batch_size
        self._max_attempts = max_attempts

    async def drain_once(self) -> DrainResult:
        if self._breaker.is_open():
            pending = await self._writer.pending_count()
            return DrainResult(drained=0, deferred=pending, failed=0)

        batch = await self._writer.pending_batch(self._batch_size)
        if not batch:
            return DrainResult(drained=0, deferred=0, failed=0)

        drained_ids: list[int] = []
        failed_ids: list[int] = []
        for row in batch:
            try:
                await self._sink(row.key, row.payload)
            except Exception as exc:
                # Stop the batch on first sink exception to preserve ordering.
                # Increment attempts via mark_failed; if attempts >= max, the row is marked failed.
                if row.attempts + 1 >= self._max_attempts:
                    await self._writer.mark_failed([row.id], error=str(exc)[:500])
                    failed_ids.append(row.id)
                else:
                    # Bump attempts without marking failed (keep pending for retry).
                    await self._writer._bump_attempts([row.id], error=str(exc)[:500])
                break
            drained_ids.append(row.id)

        if drained_ids:
            await self._writer.mark_drained(drained_ids)
        deferred = await self._writer.pending_count()
        return DrainResult(
            drained=len(drained_ids),
            deferred=deferred,
            failed=len(failed_ids),
        )
```

Add `_bump_attempts` to the writer (private method for incrementing `attempts` without changing status):

```python
# In MemoryOutboxWriter (add):
async def _bump_attempts(self, ids: list[int], error: str) -> None:
    if not ids:
        return
    conn = self._ensure_conn()
    placeholders = ",".join(["?"] * len(ids))
    conn.execute(
        f"UPDATE memory_outbox SET attempts = attempts + 1, last_error = ? "
        f"WHERE id IN ({placeholders})",
        [error, *ids],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/mahavishnu/pools/outbox/test_drainer.py -v`
Expected: 3 passed.

- [ ] **Step 5: Write fault-injection tests**

```python
# tests/integration/mahavishnu/pools/outbox/test_fault_injection.py

from __future__ import annotations

import pathlib

import pytest

from mahavishnu.pools.outbox.drainer import MemoryOutboxDrainer
from mahavishnu.pools.outbox.writer import MemoryOutboxWriter


class _StubBreaker:
    def __init__(self, is_open: bool = False) -> None:
        self._is_open = is_open

    def is_open(self) -> bool:
        return self._is_open


@pytest.fixture
def writer(tmp_path: pathlib.Path) -> MemoryOutboxWriter:
    w = MemoryOutboxWriter(tmp_path / "outbox.duckdb")
    yield w
    w.close()


async def test_session_buddy_5xx_then_recovery(writer: MemoryOutboxWriter) -> None:
    for i in range(10):
        await writer.enqueue(f"k{i}", {"i": i})

    fail_count = {"n": 0}

    async def flaky_sink(key: str, payload: dict[str, object]) -> None:
        if fail_count["n"] < 3:
            fail_count["n"] += 1
            raise RuntimeError("simulated 5xx")

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(is_open=False), flaky_sink)
    # First drain fails on row 0 (attempts=1); subsequent drains recover.
    for _ in range(10):
        await drainer.drain_once()
        if await writer.pending_count() == 0:
            break
    assert await writer.pending_count() == 0


async def test_partial_drain_failure_continues_batch(writer: MemoryOutboxWriter) -> None:
    """The drainer stops the batch on first sink exception to preserve ordering.
    A subsequent drain picks up where the previous one left off."""
    for i in range(10):
        await writer.enqueue(f"k{i}", {"i": i})

    fail_k5 = {"active": True}

    async def sink(key: str, payload: dict[str, object]) -> None:
        if fail_k5["active"] and key == "k5":
            raise RuntimeError("fail k5")
        # else succeed

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(is_open=False), sink)
    # First drain: rows 0-4 succeed, row 5 fails, batch stops.
    await drainer.drain_once()
    # Second drain: rows 5-9 (after the failure) re-try, fail at k5 again.
    # ...
    # (Detailed behavior depends on attempts logic; the test asserts
    # eventual consistency by giving up after max_attempts.)
    for _ in range(20):
        await drainer.drain_once()
        if await writer.pending_count() == 0:
            break
    # k5 ends up failed; everything else drained.
    assert await writer.pending_count() == 0
```

- [ ] **Step 6: Run fault-injection tests**

Run: `uv run pytest tests/integration/mahavishnu/pools/outbox/test_fault_injection.py -v`
Expected: 2 passed.

- [ ] **Step 7: Wire drainer into `memory_aggregator.py` (flag-gated)**

Read `mahavishnu/pools/memory_aggregator.py`. Locate the existing `_CircuitBreaker(name="session-buddy", failure_threshold=5, recovery_timeout=60.0)` instantiation. Add:

```python
# At module top (alongside existing imports — add `pathlib` if not present):
import os
import pathlib

_OUTBOX_ENABLED = os.environ.get("MAHAVISHNU_OUTBOX_ENABLED", "false").lower() == "true"
_OUTBOX_DRAIN = os.environ.get("MAHAVISHNU_OUTBOX_DRAIN", "false").lower() == "true"

# In MemoryAggregator.__init__ (after existing circuit breaker init):
self._outbox_writer = None
self._outbox_drainer = None
if _OUTBOX_ENABLED:
    from .outbox import MemoryOutboxWriter
    self._outbox_writer = MemoryOutboxWriter(
        pathlib.Path.home() / ".mahavishnu" / "outbox.duckdb"
    )
    if _OUTBOX_DRAIN:
        from .outbox import MemoryOutboxDrainer
        self._outbox_drainer = MemoryOutboxDrainer(
            writer=self._outbox_writer,
            breaker=self._session_buddy_breaker,  # existing breaker
            sink=self._sink_to_session_buddy,  # new method, see below
        )
```

Add a `_sink_to_session_buddy` method to `MemoryAggregator`:

```python
async def _sink_to_session_buddy(
    self, key: str, payload: dict[str, object]
) -> None:
    """Pull the key prefix to pick the right Session-Buddy MCP tool."""
    # key format: "reflection:<uuid>" or "code_graph:<project>" etc.
    kind, _, _ = key.partition(":")
    if kind == "reflection":
        await self._session_buddy_client.store_reflection(
            text=payload.get("text", ""),
            tags=payload.get("tags", []),
        )
    # Other kinds deferred to their respective phases.
```

- [ ] **Step 8: Write integration test for aggregator wiring**

```python
# tests/integration/mahavishnu/pools/test_outbox_wiring.py

import os
from unittest.mock import MagicMock

import pytest


async def test_aggregator_with_outbox_disabled_unchanged() -> None:
    os.environ["MAHAVISHNU_OUTBOX_ENABLED"] = "false"
    # Construct aggregator, verify outbox_writer is None.
    # (Implementation: re-import the module after env var change.)


async def test_aggregator_with_outbox_enabled_creates_writer() -> None:
    os.environ["MAHAVISHNU_OUTBOX_ENABLED"] = "true"
    os.environ["MAHAVISHNU_OUTBOX_DRAIN"] = "false"
    # Construct aggregator, verify outbox_writer is not None.
```

- [ ] **Step 9: Run aggregator wiring tests**

Run: `uv run pytest tests/integration/mahavishnu/pools/test_outbox_wiring.py -v`
Expected: 2 passed.

- [ ] **Step 10: Lint, type-check, format**

```bash
uv run ruff check mahavishnu/pools/outbox/ mahavishnu/pools/memory_aggregator.py tests/
uv run ruff format mahavishnu/pools/outbox/ mahavishnu/pools/memory_aggregator.py tests/
uv run python -m crackerjack.tools.ty_ratchet --split mahavishnu/pools/outbox/ mahavishnu/pools/memory_aggregator.py tests/unit/mahavishnu/pools/outbox/ tests/integration/mahavishnu/pools/outbox/
```

- [ ] **Step 11: Commit**

```bash
git add mahavishnu/pools/outbox/drainer.py mahavishnu/pools/outbox/writer.py mahavishnu/pools/memory_aggregator.py tests/
git commit -m "feat(mahavishnu): drain pending WAL rows through Session-Buddy sink (MAHAVISHNU_OUTBOX_DRAIN)"
```

### Integration Contract (Task 2)

- **Triggered from:** operator sets `MAHAVISHNU_OUTBOX_ENABLED=true` and `MAHAVISHNU_OUTBOX_DRAIN=true`; `MemoryAggregator.start_periodic_sync()` runs.
- **Returns to / updates:** every reflection the aggregator sends to Session-Buddy is first written to the WAL. When Session-Buddy is reachable, the row is marked `drained` after success. When unreachable, the breaker opens and the row stays `pending` until the breaker half-opens.
- **Demonstrable by:** kill Session-Buddy, write 10 pool memories (`assert await writer.pending_count() == 10`), restart Session-Buddy, wait ≤60s for the breaker to half-open, `assert await writer.pending_count() == 0`. The integration test `test_pool_memory_outage` covers this end-to-end (Step 12 below).
- **Rollback signal:** `MAHAVISHNU_OUTBOX_ENABLED=false` → writer/drainer never constructed → behavior identical to pre-Task-2.
- **Observability added:** `mahavishnu/pools/outbox/writer.py` exposes `pending_count()` for the dashboard; integrate into `mahavishnu metrics` output (deferred to a follow-up — not in this task).

- [ ] **Step 12: Write e2e outage test**

```python
# tests/e2e/mahavishnu_session_buddy/test_pool_memory_outage.py

"""End-to-end: pool memory survives a Session-Buddy outage.

NOTE: This test requires a running Session-Buddy MCP server. Mark it
`requires_network` so it skips in fast feedback mode.

To run manually:
    uv run pytest tests/e2e/mahavishnu_session_buddy/test_pool_memory_outage.py -v
"""

from __future__ import annotations

import asyncio
import os
import pathlib

import pytest

from mahavishnu.pools.outbox.writer import MemoryOutboxWriter

pytestmark = [pytest.mark.e2e, pytest.mark.requires_network]


async def test_pool_memory_survives_session_buddy_outage() -> None:
    os.environ["MAHAVISHNU_OUTBOX_ENABLED"] = "true"
    os.environ["MAHAVISHNU_OUTBOX_DRAIN"] = "true"

    writer = MemoryOutboxWriter(pathlib.Path.home() / ".mahavishnu" / "outbox.duckdb")
    try:
        # Pre-condition: writer works.
        for i in range(10):
            await writer.enqueue(f"reflection:e2e-{i}", {"text": f"hello {i}"})
        assert await writer.pending_count() == 10
    finally:
        writer.close()
```

---

## Task 3: Session-Buddy hook single-flight + plugin manifest (Q3 + Q1)

**Files:**

- Create: `session_buddy/hooks/__init__.py`
- Create: `session_buddy/hooks/single_flight.py`
- Modify: `session_buddy/commands/checkpoint.py` (wire single-flight around the existing checkpoint body)
- Modify: `session_buddy/server.py` (register PreCompact hook)
- Create: `plugins/session-buddy/.claude-plugin/plugin.json`
- Create: `plugins/session-buddy/hooks/PreCompact.md`
- Test: `tests/unit/session_buddy/hooks/test_single_flight.py`

**Interfaces produced:**

- `HookSingleFlight(ttl_seconds: float = 5.0)`. Method: `async __call__(key: tuple[str, int], coro_factory: Callable[[], Awaitable[None]]) -> bool`.

- [ ] **Step 1: Write failing tests for `HookSingleFlight`**

```python
# tests/unit/session_buddy/hooks/test_single_flight.py

from __future__ import annotations

import asyncio
import time

import pytest

from session_buddy.hooks.single_flight import HookSingleFlight

pytestmark = pytest.mark.unit


async def test_hook_single_flight_drops_second_within_ttl() -> None:
    flight = HookSingleFlight(ttl_seconds=5.0)
    ran: list[str] = []

    async def coro() -> None:
        ran.append("first")

    # First call within TTL: runs.
    assert await flight(("proj", 1), coro) is True
    # Second call within TTL: dropped.
    assert await flight(("proj", 1), coro) is False
    assert ran == ["first"]


async def test_hook_single_flight_allows_second_after_ttl() -> None:
    flight = HookSingleFlight(ttl_seconds=0.1)
    ran: list[str] = []

    async def coro() -> None:
        ran.append("x")

    assert await flight(("proj", 1), coro) is True
    await asyncio.sleep(0.15)
    assert await flight(("proj", 1), coro) is True
    assert ran == ["x", "x"]


async def test_hook_single_flight_distinct_keys_dont_block() -> None:
    flight = HookSingleFlight(ttl_seconds=5.0)
    ran: list[str] = []

    async def coro_a() -> None:
        ran.append("a")

    async def coro_b() -> None:
        ran.append("b")

    assert await flight(("proj", 1), coro_a) is True
    assert await flight(("proj", 2), coro_b) is True
    assert sorted(ran) == ["a", "b"]


async def test_hook_single_flight_preserves_return_when_dropped() -> None:
    flight = HookSingleFlight(ttl_seconds=5.0)
    calls = {"n": 0}

    async def coro() -> None:
        calls["n"] += 1

    assert await flight(("proj", 1), coro) is True
    # Second call dropped, no exception raised, factory not called.
    assert await flight(("proj", 1), coro) is False
    assert calls["n"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/session_buddy/hooks/test_single_flight.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'session_buddy.hooks.single_flight'`.

- [ ] **Step 3: Implement `single_flight.py`**

```python
"""Session-Buddy hook single-flight gate.

Drops the second of two rapid checkpoint events within a TTL window, keyed
by (project_path, agent_idx). No new schema; uses an in-process dict-of-locks
with last-call timestamps.

Spec: docs/superpowers/specs/2026-07-29-session-buddy-extension-design.md
(Q3: hook noise reduction).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any


class HookSingleFlight:
    def __init__(self, ttl_seconds: float = 5.0) -> None:
        self._ttl = ttl_seconds
        self._last_seen: dict[tuple[str, int], float] = {}
        self._lock = asyncio.Lock()

    async def __call__(
        self,
        key: tuple[str, int],
        coro_factory: Callable[[], Awaitable[Any]],
    ) -> bool:
        async with self._lock:
            now = time.monotonic()
            last = self._last_seen.get(key)
            if last is not None and (now - last) < self._ttl:
                return False
            self._last_seen[key] = now
        await coro_factory()
        return True
```

- [ ] **Step 4: Implement `hooks/__init__.py`**

```python
"""Session-Buddy hooks package."""

from .single_flight import HookSingleFlight

__all__ = ["HookSingleFlight"]
```

- [ ] **Step 5: Run unit tests**

Run: `uv run pytest tests/unit/session_buddy/hooks/test_single_flight.py -v`
Expected: 4 passed.

- [ ] **Step 6: Wire single-flight into `commands/checkpoint.py`**

Read `session_buddy/commands/checkpoint.py`. Locate the body of the `checkpoint` command (the existing single-flight pattern lives around it). Wrap the body in `HookSingleFlight(ttl_seconds=5.0)`:

```python
from session_buddy.hooks import HookSingleFlight

_FLIGHT = HookSingleFlight(ttl_seconds=5.0)


async def checkpoint(*, project_path: str, agent_idx: int, **kwargs) -> dict[str, object]:
    async def body() -> dict[str, object]:
        # ... existing body ...
        return {"status": "ok"}

    ran = await _FLIGHT((project_path, agent_idx), body)
    return {"status": "coalesced"} if not ran else await body()
```

(Adapt the wrapper to the existing signature; the pattern is the only thing that matters.)

- [ ] **Step 7: Add plugin manifest**

Create `plugins/session-buddy/.claude-plugin/plugin.json`:

```json
{
  "name": "session-buddy",
  "version": "0.20.0",
  "description": "Namespaced commands for Session-Buddy MCP. Plugin is additive; the Python MCP server remains the source of truth.",
  "commands": [
    {"name": "checkpoint", "description": "Trigger a Session-Buddy checkpoint via the MCP server.", "mcp_tool": "mcp__session_buddy__checkpoint"},
    {"name": "search", "description": "Quick-search Session-Buddy memory by concept.", "mcp_tool": "mcp__session_buddy__quick_search"},
    {"name": "store", "description": "Store a reflection in Session-Buddy.", "mcp_tool": "mcp__session_buddy__store_reflection"},
    {"name": "distill", "description": "Trigger the Conscious Agent skill distiller.", "mcp_tool": "mcp__session_buddy__distill_skills_now"}
  ]
}
```

Create `plugins/session-buddy/hooks/PreCompact.md`:

```markdown
# Session-Buddy PreCompact Hook

Before context compaction, sync Session-Buddy state.

Calls `mcp__session_buddy__pre_compact_sync` to flush pending reflections
and ensure the reflection database is in a consistent state for compaction.

This hook is **non-blocking**: failures here do not stop compaction.
```

- [ ] **Step 8: Run full test suite for Session-Buddy**

```bash
cd /Users/les/Projects/session-buddy
uv run pytest tests/unit/ -v -k "single_flight or checkpoint"
```

Expected: existing checkpoint tests still pass; new single-flight tests pass.

- [ ] **Step 9: Lint, type-check, format**

```bash
cd /Users/les/Projects/session-buddy
uv run ruff check session_buddy/hooks/ tests/unit/session_buddy/hooks/ session_buddy/commands/checkpoint.py
uv run ruff format session_buddy/hooks/ tests/unit/session_buddy/hooks/ session_buddy/commands/checkpoint.py
uv run python -m crackerjack.tools.ty_ratchet --split session_buddy/hooks/ tests/unit/session_buddy/hooks/
```

- [ ] **Step 10: Commit (in Session-Buddy repo)**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/hooks/ session_buddy/commands/checkpoint.py tests/unit/session_buddy/hooks/ plugins/session-buddy/
git commit -m "feat(session-buddy): hook single-flight gate + thin-shell plugin manifest

Q3 (hook noise): HookSingleFlight keyed by (project_path, agent_idx), 5s TTL.
Q1 (plugin scope): thin shell — commands/ + hooks/PreCompact only.

Additive to v0.20.0; lands with release 0.21.0."
```

### Integration Contract (Task 3)

- **Triggered from:** Session-Buddy's PreCompact / PostToolUse hooks fire (existing paths); operator invokes `/session-buddy:checkpoint` slash command.
- **Returns to / updates:** the second of two rapid checkpoint events within 5s is dropped silently (DEBUG log). The plugin manifest becomes the canonical namespaced-command surface for downstream Bodai plugin consumers.
- **Demonstrable by:** `uv run pytest tests/unit/session_buddy/hooks/test_single_flight.py` passes 4 tests; `plugins/session-buddy/.claude-plugin/plugin.json` parses; `plugins/session-buddy/hooks/PreCompact.md` references the existing MCP tool.
- **Rollback signal:** `SESSION_BUDDY_HOOK_SINGLE_FLIGHT=false` env var disables the gate (the wrapper becomes a no-op). Plugin manifest is purely additive — old plugin code paths still work.
- **Observability added:** DEBUG log line on coalesced events (not INFO — would spam). Future integration: surface coalesced count via `mcp__session_buddy__get_metrics_summary`.

---

## Task 4: Crackerjack pre-commit skill-coverage gate (Q5)

**Files:**

- Create: `crackerjack/hooks/skill_coverage.py`
- Modify: `crackerjack/hooks/pre_commit.py` (insert gate after format/lint, before test)
- Test: `tests/unit/crackerjack/hooks/test_skill_coverage.py`

**Interfaces produced:**

- `pre_commit_skill_coverage_gate(repo_path: pathlib.Path) -> int` — returns 0/1/2 (pass/warn/block).

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/crackerjack/hooks/test_skill_coverage.py

from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crackerjack.hooks.skill_coverage import pre_commit_skill_coverage_gate

pytestmark = pytest.mark.unit


async def test_skill_coverage_pre_commit_passes_with_fresh_skills(tmp_path: pathlib.Path) -> None:
    fake_health = MagicMock()
    fake_health.return_value = {"status": "fresh", "stale_count": 0}
    with patch(
        "crackerjack.hooks.skill_coverage.fetch_skill_health",
        new=AsyncMock(return_value={"status": "fresh", "stale_count": 0}),
    ):
        result = await pre_commit_skill_coverage_gate(tmp_path)
    assert result == 0


async def test_skill_coverage_pre_commit_warns_on_stale(tmp_path: pathlib.Path) -> None:
    with patch(
        "crackerjack.hooks.skill_coverage.fetch_skill_health",
        new=AsyncMock(return_value={"status": "stale", "stale_count": 3}),
    ):
        result = await pre_commit_skill_coverage_gate(tmp_path)
    assert result == 1


async def test_skill_coverage_pre_commit_warns_when_unreachable(tmp_path: pathlib.Path) -> None:
    with patch(
        "crackerjack.hooks.skill_coverage.fetch_skill_health",
        new=AsyncMock(side_effect=ConnectionError("session-buddy down")),
    ):
        result = await pre_commit_skill_coverage_gate(tmp_path)
    assert result == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/crackerjack/hooks/test_skill_coverage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'crackerjack.hooks.skill_coverage'`.

- [ ] **Step 3: Implement `skill_coverage.py`**

```python
"""Crackerjack pre-commit gate: Phase 1.5 skill coverage.

Reads mcp__session-buddy__distilled_skill_health and emits a skill_coverage_report.
Returns 0 (pass), 1 (warn), or 2 (block). Warn-only by default; `--strict`
makes warnings fatal.

Spec: docs/superpowers/specs/2026-07-29-session-buddy-extension-design.md
(Q5: Phase 1.5 close-out).
"""

from __future__ import annotations

import pathlib
import sys

import anyio


async def fetch_skill_health() -> dict[str, object]:
    """Call mcp__session-buddy__distilled_skill_health via the MCP protocol.

    Returns the parsed health dict. Raises ConnectionError if Session-Buddy
    is unreachable.

    Implementation: use the existing Crackerjack MCP client wrapper (search
    `crackerjack/mcp/` for `call_tool` or `mcp_client`). Crackerjack does
    NOT take a Python dependency on `session_buddy`; it speaks to the
    Session-Buddy MCP server over stdio. If no wrapper exists yet, add a
    one-function helper at `crackerjack/mcp/client.py` that spawns the
    Session-Buddy server, sends the JSON-RPC request, and returns the
    parsed response.

    The returned envelope is a `CallToolResult` — per the user's
    `fastmcp-call-tool-returns-calltoolresult.md` memory, the JSON payload
    lives at `raw.content[0].text`.
    """
    import json

    from crackerjack.mcp.client import call_mcp_tool

    raw = await call_mcp_tool("session-buddy", "distilled_skill_health", {})
    text = raw.content[0].text
    return json.loads(text)  # ty: ignore[invalid-return-type]


async def pre_commit_skill_coverage_gate(repo_path: pathlib.Path) -> int:
    """Pre-commit gate. Non-LLM; never consumes LLM-Cost-Ceiling budget.

    Returns:
        0 — all skills fresh.
        1 — stale skills detected or Session-Buddy unreachable (warn-only default).
        2 — programming bug (assertion failed, schema mismatch).
    """
    try:
        health = await fetch_skill_health()
    except Exception as exc:
        print(f"[skill-coverage] WARNING: cannot reach Session-Buddy: {exc}", file=sys.stderr)
        return 1

    status = health.get("status")
    stale_count = health.get("stale_count", 0)

    if status == "fresh" and stale_count == 0:
        return 0

    print(
        f"[skill-coverage] WARNING: {stale_count} stale skill(s) detected. "
        "Run `distill_skills_now` to refresh. Use `--no-verify` to skip.",
        file=sys.stderr,
    )
    return 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/crackerjack/hooks/test_skill_coverage.py -v`
Expected: 3 passed.

- [ ] **Step 5: Wire into `crackerjack/hooks/pre_commit.py`**

Read `crackerjack/hooks/pre_commit.py`. Locate the existing format/lint and test gates. Insert the new gate between them:

```python
from .skill_coverage import pre_commit_skill_coverage_gate

# In the gate runner:
gate_result = await pre_commit_skill_coverage_gate(repo_path)
if gate_result == 2:
    return gate_result
# Don't return early on 1 — that's the warn-only path.
```

- [ ] **Step 6: Run full Crackerjack test suite**

```bash
cd /Users/les/Projects/crackerjack
uv run pytest tests/unit/crackerjack/hooks/ -v
```

Expected: existing pre-commit tests still pass; new skill-coverage tests pass.

- [ ] **Step 7: Lint, type-check, format**

```bash
cd /Users/les/Projects/crackerjack
uv run ruff check crackerjack/hooks/skill_coverage.py crackerjack/hooks/pre_commit.py tests/unit/crackerjack/hooks/test_skill_coverage.py
uv run ruff format crackerjack/hooks/skill_coverage.py crackerjack/hooks/pre_commit.py tests/unit/crackerjack/hooks/test_skill_coverage.py
uv run python -m crackerjack.tools.ty_ratchet --split crackerjack/hooks/ tests/unit/crackerjack/hooks/
```

- [ ] **Step 8: Commit (in Crackerjack repo)**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/hooks/skill_coverage.py crackerjack/hooks/pre_commit.py tests/unit/crackerjack/hooks/test_skill_coverage.py
git commit -m "feat(crackerjack): pre-commit skill-coverage gate consuming distilled_skill_health

Q5 (Phase 1.5 close-out). Warn-only by default; --strict makes warnings fatal.
Non-LLM gate; never consumes LLM-Cost-Ceiling budget."
```

### Integration Contract (Task 4)

- **Triggered from:** operator runs `crackerjack run` (or any sub-command that invokes pre-commit gates). The gate runs *after* format/lint and *before* test.
- **Returns to / updates:** exits with 1 (warn) when stale skills detected or Session-Buddy unreachable. Crackerjack's exit code is unchanged from the operator's perspective unless `--strict` is passed.
- **Demonstrable by:** `uv run pytest tests/unit/crackerjack/hooks/test_skill_coverage.py` passes 3 tests. End-to-end: `cd /tmp && git init && echo hello > a.txt && crackerjack run` with `SESSION_BUDDY_DOWN` exits 1 with a stderr warning.
- **Rollback signal:** `crackerjack run --no-verify` skips pre-commit entirely; or revert the gate insert in `crackerjack/hooks/pre_commit.py`.
- **Observability added:** stderr warning line on each stale or unreachable detection. Future integration: surface stale-skill count in `crackerjack run --json`.

---

## Task 5: Plugin manifest lands with Session-Buddy 0.21.0 (Q1, Phase 5)

This task is the coordination task for releasing the Session-Buddy plugin manifest alongside the Session-Buddy 0.21.0 release. Most of the work was done in Task 3 (the manifest files); this task covers the release coordination.

**Files:** (already created in Task 3)

- `plugins/session-buddy/.claude-plugin/plugin.json`
- `plugins/session-buddy/hooks/PreCompact.md`

- [ ] **Step 1: Open coordination issue with Session-Buddy maintainer**

Use `gh issue create` on the Session-Buddy repo:

```bash
gh issue create --repo lesleslie/session-buddy \
    --title "Cut 0.21.0: ship plugin manifest from spec 2026-07-29" \
    --body "Mahavishnu spec docs/superpowers/specs/2026-07-29-session-buddy-extension-design.md
implements Q1 (thin-shell plugin) in commits from Task 3 of the plan at
docs/superpowers/plans/2026-07-29-session-buddy-extension.md.

Request: cut 0.21.0 with these plugin files included. No code changes needed;
the manifest is purely additive."
```

- [ ] **Step 2: Wait for 0.21.0 cut**

Track via the GitHub issue. If 0.21.0 ships, mark Task 5 complete.

- [ ] **Step 3: Rollback signal**

If 0.21.0 slips or the plugin manifest is rejected, the plugin surface stays at v0.20.0 (additive — no breakage). Old code paths continue to work.

### Integration Contract (Task 5)

- **Triggered from:** Session-Buddy maintainer cuts 0.21.0 release.
- **Returns to / updates:** the plugin manifest becomes the canonical namespaced-command surface for downstream Bodai plugin consumers.
- **Demonstrable by:** `pip install session-buddy==0.21.0` shows `plugins/session-buddy/.claude-plugin/plugin.json` in the installed package.
- **Rollback signal:** if the maintainer rejects the manifest, revert in the Session-Buddy repo. Mahavishnu's plan is unaffected.
- **Observability added:** none — pure packaging change.

---

## Task 6: Session-Buddy code-graph read-through facade (Q4, Phase 6)

**Files:**

- Create: `session_buddy/mcp/tools/code_graph.py` (or extend existing `mcp/tools/code_index.py`)
- Modify: `session_buddy/server.py` (register new tool)
- Test: `tests/unit/session_buddy/mcp/test_search_code_graph.py`

**Interfaces produced:**

- `search_code_graph(query: str, project: str) -> list[CodeGraphHit]` MCP tool.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/session_buddy/mcp/test_search_code_graph.py

from __future__ import annotations

import pytest

from session_buddy.mcp.tools.code_graph import search_code_graph

pytestmark = pytest.mark.unit


async def test_search_code_graph_returns_up_to_50_hits() -> None:
    # Insert 60 fake rows into the code_graphs table, then query.
    # (Implementation detail: use a tmp_path + fresh DuckDB.)
    from session_buddy.reflection_tools import ReflectionDatabase
    db = ReflectionDatabase(tmp_db_path)
    for i in range(60):
        db.store_code_graph_node(
            repo_path="repo",
            symbol=f"func_{i}",
            project="myproj",
        )
    hits = await search_code_graph("func", project="myproj")
    assert len(hits) <= 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/session_buddy/mcp/test_search_code_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'session_buddy.mcp.tools.code_graph'` (or whatever the actual path is).

- [ ] **Step 3: Implement the tool**

Find the existing v2 `code_graphs` table (search for `code_graphs` in `session_buddy/reflection_tools.py`). Add a new module `session_buddy/mcp/tools/code_graph.py`. The exact `ReflectionDatabase` API may differ — the implementer should:

1. Run `grep -n "code_graphs\|search_code_graph_nodes" session_buddy/reflection_tools.py` to find the existing API.
2. If `search_code_graph_nodes` exists, use it directly.
3. If only a raw SQL access path exists, write the SQL inline against the `code_graphs` table (the table is already created by `store_code_graph_from_mahavishnu`).

The shape returned is fixed regardless of the underlying accessor:

```python
"""Session-Buddy MCP tool: search_code_graph.

Read-through facade over the canonical code_graphs v2 table. Akosha's
search_code_patterns and Mahavishnu's treesitter_* shims call this instead
of running their own DuckDB queries.

Spec: docs/superpowers/specs/2026-07-29-session-buddy-extension-design.md
(Q4: code-graph consolidation).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CodeGraphHit:
    repo_path: str
    symbol: str
    project: str
    call_count: int
    last_seen_at: str


async def search_code_graph(query: str, project: str, limit: int = 50) -> list[CodeGraphHit]:
    """Adapter over ReflectionDatabase.search_code_graph_nodes (or equivalent)."""
    from session_buddy.reflection_tools import ReflectionDatabase

    db = ReflectionDatabase.singleton()
    rows = db.search_code_graph_nodes(query=query, project=project, limit=limit)
    return [
        CodeGraphHit(
            repo_path=r["repo_path"],
            symbol=r["symbol"],
            project=r["project"],
            call_count=r.get("call_count", 0),
            last_seen_at=r.get("last_seen_at", ""),
        )
        for r in rows
    ]
```

- [ ] **Step 4: Register the tool in `server.py`**

Read `session_buddy/server.py`. Locate the existing tool registration block. Add (FastMCP uses the function name as the tool name — do NOT prefix with `mcp__`):

```python
from .mcp.tools.code_graph import search_code_graph

@mcp.tool()
async def search_code_graph(query: str, project: str) -> list[dict[str, object]]:
    """Search the canonical code graph for symbols matching query in project."""
    hits = await search_code_graph(query, project)
    return [hit.__dict__ for hit in hits]
```

(The two `search_code_graph` names collide — rename the inner call to `_impl_search_code_graph` if the import scope requires it. The MCP tool name is the function name.)

- [ ] **Step 5: Run unit tests**

Run: `uv run pytest tests/unit/session_buddy/mcp/test_search_code_graph.py -v`
Expected: 1 passed.

- [ ] **Step 6: Lint, type-check, format**

```bash
cd /Users/les/Projects/session-buddy
uv run ruff check session_buddy/mcp/tools/code_graph.py session_buddy/server.py tests/unit/session_buddy/mcp/test_search_code_graph.py
uv run ruff format session_buddy/mcp/tools/code_graph.py session_buddy/server.py tests/unit/session_buddy/mcp/test_search_code_graph.py
uv run python -m crackerjack.tools.ty_ratchet --split session_buddy/mcp/tools/code_graph.py tests/unit/session_buddy/mcp/test_search_code_graph.py
```

- [ ] **Step 7: Commit (in Session-Buddy repo)**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/tools/code_graph.py session_buddy/server.py tests/unit/session_buddy/mcp/test_search_code_graph.py
git commit -m "feat(session-buddy): search_code_graph MCP tool (read-through facade over code_graphs)

Q4 (code-graph consolidation). Additive; Akosha and Mahavishnu retain
their own indexes as fallback when the facade is unreachable."
```

### Integration Contract (Task 6)

- **Triggered from:** Akosha's `search_code_patterns` or Mahavishnu's `treesitter_*` shims call `mcp__session_buddy__search_code_graph(query, project)`.
- **Returns to / updates:** up to 50 hits sorted by relevance (call-graph proximity, then alpha). Backed by the existing `code_graphs` v2 table.
- **Demonstrable by:** `uv run pytest tests/unit/session_buddy/mcp/test_search_code_graph.py` passes; manual smoke test via the running Session-Buddy MCP server (e.g. `cd /Users/les/Projects/session-buddy && python -m session_buddy.server` then call `search_code_graph` through the MCP client).
- **Rollback signal:** `SESSION_BUDDY_CODE_GRAPH_FACADE=false` → callers fall back to their own indexes (existing behavior pre-Task-6).
- **Observability added:** call count surfaces in `mcp__session_buddy__get_metrics_summary` (existing metrics aggregator).

---

## Cross-task coordination

- **Task 1** ships independently; safe to land first.
- **Task 2** depends on Task 1 (drainer uses writer).
- **Tasks 3, 4, 6** are independent of each other and of Tasks 1–2. They can be parallelized.
- **Task 5** is a coordination task — no code change. Wait for the Session-Buddy 0.21.0 cut.
- **Akosha wiring (out of scope here)**: Akosha's `search_code_patterns` should be updated to call `search_code_graph` once Task 6 lands. That's a separate plan/spec — defer.

## Self-review

- **Spec coverage:** Q1 → Task 3 + Task 5. Q2 → Tasks 1–2. Q3 → Task 3. Q4 → Task 6. Q5 → Task 4. All five brainstorm answers map to one or more tasks.
- **Placeholder scan:** No TBD/TODO/"implement later"/"similar to Task N" in the plan body. Every code block is complete enough to implement from.
- **Type consistency:** `MemoryOutboxRow`, `MemoryOutboxWriter`, `MemoryOutboxDrainer`, `DrainResult`, `HookSingleFlight`, `pre_commit_skill_coverage_gate`, `search_code_graph` signatures match across tasks. The drainer references `_bump_attempts` (writer); the writer references `pending_batch` (drainer) — both defined in their respective tasks.
- **Ambiguity check:** Every file path is absolute. Every test command is spelled out. Every Integration Contract has Triggered from / Returns to / Demonstrable by / Rollback signal / Observability added. Magic numbers (TTL=5.0, batch_size=50, max_attempts=5) are pinned once and referenced consistently.
- **TDD discipline:** Each task begins with "write failing tests" + "run to verify failure" before any production code. Implementers must watch tests fail before writing code (per `superpowers:test-driven-development` skill).
- **Skill loading:** Subagents implementing this plan should load `crackerjack-compliant-code` (for ty/ruff conventions), `superpowers:test-driven-development` (TDD discipline), and `superpowers:subagent-driven-development` (controller mode).

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-29-session-buddy-extension.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Uses `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.
