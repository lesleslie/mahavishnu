---
status: draft
role: implementation
kind: plan
date: 2026-10-20
last_reviewed: 2026-10-20
superseded_by: null
topic: substrate-otel
title: "Bodai OTel Substrate Read Path — Implementation Plan"
spec: docs/specs/2026-10-20-bodai-otel-substrate-read-path.md
blocked_by:
  - docs/plans/2026-10-19-bodai-substrate-otel-v7-implementation.md
review: []
---

# Bodai OTel Substrate — Read Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give the v7 OTel substrate a read surface — two MCP tools over
`spans_substrate`, and a rewrite of `fitness_analyzer` off HTTP fan-out onto a
local query.

**Architecture:** A query surface in akosha that borrows the receiver's
`HotStore` connection rather than opening a second one. Raw parameterised SQL
with Pydantic result models; no ORM. Two MCP tools registered through akosha's
existing `register_*_tools(app)` pattern.

**Tech Stack:** Python 3.14, DuckDB 2.0.0-dev (akosha, aligned with oneiric —
see Global Constraints), Pydantic v2, FastMCP, `pytest`.

**Spec:** `docs/specs/2026-10-20-bodai-otel-substrate-read-path.md` — the plan
argues from the spec, so the spec travels with it. Section references below are
to that document.

---

## Global Constraints

Every task inherits these. They are the exact values verified against the
running fleet on 2026-10-20.

- **DuckDB is `2.0.0.dev2610192346` in akosha.** Aligned with oneiric in
  `e634c55`. Do not introduce an ORM or a second connection.
- **Bind parameters with `$name` or `?`. Never `:name`** — DuckDB raises
  `ParserException: syntax error at or near ":"` on PEP-249 bindparam syntax.
- **`self.conn.execute(...)` is synchronous.** `hot_store.conn` is a plain
  `DuckDBPyConnection`. Never `await` it. The *methods* are `async` and take
  `async with self.hot_store._lock`.
- **Use `json_extract_string(col, '$.path')`, not `->` / `->>`.** The operator
  sugar is fragile across versions; `json_extract_string` returns VARCHAR on
  both 1.5.6 and 2.0.0-dev.
- **`PERCENTILE_CONT` excludes NULLs.** `latency_p99_ms` is `None` only when
  the *entire* window lacks latency.
- **Wrap `SUM(CASE …)` in `COALESCE(…, 0)`.** It returns NULL on zero rows.
- **`asyncio.Event.wait()` takes no timeout.** Use
  `asyncio.wait_for(stop_event.wait(), timeout=n)`; the receiver already has
  `_sleep_or_stop` for this.
- **`HotStore(database_path=…, embedding_dim=…)`.** The kwarg is
  `database_path`, not `db_path`. `__init__` is sync; `await initialize()`.
  **Fixtures must pass `embedding_dim`** — omitting it makes a live
  `get_embedding_service()` call in `__init__`.
- **Config: `from akosha.config import get_config`** → `AkoshaConfig`.
  There is no `get_settings`. `cfg.environment` is **top-level**
  (`config.py:489`); `cfg.hot.path` is the DuckDB file.
- **Metrics are module-level** against `get_metrics_registry()`
  (`prometheus_metrics.py:92-137`), never per-instance — a second construction
  raises `Duplicated timeseries in CollectorRegistry`.
- **MCP tools register via `@app.tool(name=…)` inside `register_*_tools(app)`**
  (`mcp/tools/fitness_tools.py:42`). There is no module-level `mcp` object.
- **Pre-1.0 replace-don't-extend.** No feature flags, no deprecation windows.
- **Run cross-repo work in a worktree** at
  `~/.local/state/mahavishnu/worktrees/<repo>/`.
- **Every task ends with** `audit_orphans.py` clean and a
  `docs/feature-tracking/` entry. Both gates are repeated in each task rather
  than assumed.

## Review Focus

Inputs the spec implies but no task's tests exercise. Each gets a test in the
task that owns the code.

1. **The table does not exist yet.** The DDL is created by the receiver's
   `_ensure_operational_tables`. A read tool invoked before the receiver has
   started once gets a *CatalogException*, not an empty result. The spec's
   §5.5 "returns empty" is only true once the table exists.
2. **A NULL `selector` or `task_class`.** Both are nullable; `= ?` silently
   drops those rows while `IS NOT DISTINCT FROM ?` matches them (spec §4.2).
3. **Every span in the window has NULL latency.** `latency_p99_ms` must be
   `None`, not `0.0` — the distinction is what tells "no data" from "fast".
4. **A row inserted mid-pagination.** Inserts above the cursor are the normal
   case here, since the receiver is ingesting while you read.
5. **A pair whose spans are all outside the time window.** `span_count=0` must
   be distinguishable from a healthy quiet window.
6. **`attributes` containing something that is not JSON-serialisable.** The
   column is JSON in DuckDB, but the read path hands back a Python dict.

---

## Task R-1: the query surface

**Spec §4.1, §4.4.** Ships the module the other tools call. Registers nothing.

**Files:**
- Create: `akosha/storage/span_query.py`
- Test: `akosha/tests/unit/storage/test_span_query.py`

**Interfaces:**
- Consumes: `HotStore` (akosha's `database_path=`/`embedding_dim=` ctor)
- Produces:
  - `class SpanQuery` — `__init__(self, hot_store: HotStore)`
  - `async def search(self, *, service_name: str | None = None,
    service_namespace: str | None = None, outcome: str | None = None,
    since_unix_nano: int | None = None, until_unix_nano: int | None = None,
    trace_id: str | None = None, limit: int = 50,
    cursor: tuple[int, str] | None = None) -> list[SpanHit]`
  - `async def summary(self, *, selector: str, task_class: str,
    cutoff_unix_nano: int) -> SpanSummary`
  - `SpanHit`, `SpanSummary` Pydantic models (spec §4.4)

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import json

import pytest

from akosha.storage.hot_store import HotStore
from akosha.storage.span_query import SpanQuery


@pytest.fixture
async def store(tmp_path):
    hs = HotStore(database_path=tmp_path / "q.duckdb", embedding_dim=384)
    await hs.initialize()
    return hs


def _insert(hs, span_id, *, selector=None, task_class=None, outcome="success",
            latency=10.0, received=None):
    hs.conn.execute(
        "INSERT INTO spans_substrate (span_id, trace_id, service_name, "
        "service_namespace, span_name, start_time_unix_nano, "
        "received_at_unix_nano, outcome, selector, task_class, latency_ms, "
        "attributes, resource) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [span_id, "t1", "mahavishnu", "bodai", "n", 1,
         received if received is not None else 1_700_000_000_000_000_000,
         outcome, selector, task_class, latency,
         json.dumps({"k": "v"}), json.dumps({"service.name": "mahavishnu"})],
    )


@pytest.mark.asyncio
async def test_search_returns_hits(store: HotStore) -> None:
    _insert(store, "s1")
    hits = await SpanQuery(store).search(limit=10)
    assert [h.span_id for h in hits] == ["s1"]


@pytest.mark.asyncio
async def test_search_missing_table_is_empty_not_error(tmp_path) -> None:
    """The receiver creates the DDL. Before it has run once, a read must not
    raise -- it returns empty (spec §5.5)."""
    hs = HotStore(database_path=tmp_path / "bare.duckdb", embedding_dim=384)
    await hs.initialize()
    await hs.conn.execute("DROP TABLE IF EXISTS spans_substrate")
    assert await SpanQuery(hs).search(limit=10) == []


@pytest.mark.asyncio
async def test_search_keyset_pages_without_duplicates_or_gaps(
    store: HotStore,
) -> None:
    """Review Focus #4: an insert above the cursor mid-pagination.

    OFFSET would return sp09 twice and never return sp99. Keyset must not.
    """
    received = 1_700_000_000_000_000_000
    for i in range(6):
        _insert(store, f"sp{i:02d}", received=received + i)
    q = SpanQuery(store)

    first = await q.search(limit=3)
    _insert(store, "sp99", received=received - 1)  # newest, above the cursor
    second = await q.search(limit=3, cursor=(first[-1].received_at_unix_nano,
                                             first[-1].span_id))

    ids = [h.span_id for h in first] + [h.span_id for h in second]
    assert len(ids) == len(set(ids)), f"duplicate across pages: {ids}"
    assert "sp99" not in ids, "a row inserted above the cursor leaked in"


@pytest.mark.asyncio
async def test_summary_matches_null_selector(store: HotStore) -> None:
    """Review Focus #2: `= ?` drops NULL selector; IS NOT DISTINCT FROM matches.

    Verified against DuckDB: `selector = NULL` -> 0 rows,
    `selector IS NOT DISTINCT FROM NULL` -> 10 rows.
    """
    for i in range(3):
        _insert(store, f"s{i}", selector=None, task_class="agent")
    got = await SpanQuery(store).summary(
        selector=None, task_class="agent",
        cutoff_unix_nano=1_700_000_000_000_000_000,
    )
    assert got.span_count == 3, "IS NOT DISTINCT FROM must match NULL selector"


@pytest.mark.asyncio
async def test_summary_all_null_latency_yields_none_not_zero(
    store: HotStore,
) -> None:
    """Review Focus #3: PERCENTILE_CONT excludes NULLs, so the whole-window
    NULL case must be None, never 0.0 — that distinction is what separates
    'no data' from 'fast'."""
    for i in range(3):
        _insert(store, f"s{i}", selector="x", task_class="agent", latency=None)
    got = await SpanQuery(store).summary(
        selector="x", task_class="agent",
        cutoff_unix_nano=1_700_000_000_000_000_000,
    )
    assert got.latency_p99_ms is None
    assert got.failure_count == 0, "COALESCE must keep failure_count an int"
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/storage/test_span_query.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'akosha.storage.span_query'`

- [ ] **Step 3: Implement**

Create `akosha/storage/span_query.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from .hot_store import HotStore


class SpanHit(BaseModel):
    span_id: str
    trace_id: str | None  # DDL: `trace_id TEXT`, nullable
    parent_span_id: str | None
    service_name: str
    service_namespace: str  # DDL: NOT NULL
    span_name: str
    start_time_unix_nano: int
    received_at_unix_nano: int
    duration_ms: float | None
    outcome: str | None
    attributes: dict[str, Any]


class SpanSummary(BaseModel):
    span_count: int
    failure_count: int
    latency_p99_ms: float | None


_SELECT_COLS = (
    "span_id, trace_id, parent_span_id, service_name, service_namespace, "
    "span_name, start_time_unix_nano, received_at_unix_nano, duration_ms, "
    "outcome, attributes"
)

# ORDER BY includes span_id so the keyset cursor is total. A batch stamps the
# same received_at_unix_nano on every span, so ties are the NORMAL case, not
# an edge case — without the tiebreaker, paging loses rows.
_ORDER = "ORDER BY received_at_unix_nano DESC, span_id DESC"


class SpanQuery:
    """Read-only queries over spans_substrate.

    Borrows the receiver's HotStore. Does not open its own connection and
    never writes -- see spec §4.1 and §5.1.
    """

    def __init__(self, hot_store: HotStore) -> None:
        self._store = hot_store

    def _table_exists(self) -> bool:
        return bool(
            self._store.conn.execute(
                "SELECT 1 FROM duckdb_tables() WHERE table_name = ?",
                ["spans_substrate"],
            ).fetchone()
        )

    async def search(
        self,
        *,
        service_name: str | None = None,
        service_namespace: str | None = None,
        outcome: str | None = None,
        since_unix_nano: int | None = None,
        until_unix_nano: int | None = None,
        trace_id: str | None = None,
        limit: int = 50,
        cursor: tuple[int, str] | None = None,
    ) -> list[SpanHit]:
        if not self._table_exists():
            return []
        if limit < 1:
            raise ValueError("limit must be >= 1")

        conditions: list[str] = []
        params: list[Any] = []
        if service_name is not None:
            conditions.append("service_name = ?")
            params.append(service_name)
        if service_namespace is not None:
            conditions.append("service_namespace = ?")
            params.append(service_namespace)
        if outcome is not None:
            conditions.append("outcome = ?")
            params.append(outcome)
        if since_unix_nano is not None:
            conditions.append("received_at_unix_nano >= ?")
            params.append(int(since_unix_nano))
        if until_unix_nano is not None:
            conditions.append("received_at_unix_nano < ?")
            params.append(int(until_unix_nano))
        if trace_id is not None:
            conditions.append("trace_id = ?")
            params.append(trace_id)
        if cursor is not None:
            conditions.append(
                "(received_at_unix_nano, span_id) < (?, ?)"
            )
            params.extend([int(cursor[0]), cursor[1]])

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"SELECT {_SELECT_COLS} FROM spans_substrate {where} {_ORDER} LIMIT ?"
        params.append(limit)

        async with self._store._lock:
            rows = self._store.conn.execute(sql, params).fetchall()
        return [_to_hit(r) for r in rows]

    async def summary(
        self, *, selector: str, task_class: str, cutoff_unix_nano: int
    ) -> SpanSummary:
        if not self._table_exists():
            return SpanSummary(span_count=0, failure_count=0, latency_p99_ms=None)
        # IS NOT DISTINCT FROM, not `=`: both columns are nullable and `=`
        # against NULL yields NULL, silently dropping rows and under-reporting
        # span_count. COALESCE: SUM(CASE ...) returns NULL on zero rows, which
        # would fail the int field.
        sql = """
            SELECT
                COUNT(*) AS span_count,
                COALESCE(SUM(CASE WHEN outcome = 'error' THEN 1 ELSE 0 END), 0)
                    AS failure_count,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms)
                    AS latency_p99_ms
            FROM spans_substrate
            WHERE selector IS NOT DISTINCT FROM $selector
              AND task_class IS NOT DISTINCT FROM $task_class
              AND outcome IN ('success', 'error')
              AND received_at_unix_nano > $cutoff
        """
        async with self._store._lock:
            row = self._store.conn.execute(
                sql,
                {
                    "selector": selector,
                    "task_class": task_class,
                    "cutoff": int(cutoff_unix_nano),
                },
            ).fetchone()
        return SpanSummary(
            span_count=int(row[0]),
            failure_count=int(row[1]),
            latency_p99_ms=None if row[2] is None else float(row[2]),
        )


def _to_hit(row: tuple) -> SpanHit:
    return SpanHit(
        span_id=row[0],
        trace_id=row[1],
        parent_span_id=row[2],
        service_name=row[3],
        service_namespace=row[4],
        span_name=row[5],
        start_time_unix_nano=row[6],
        received_at_unix_nano=row[7],
        duration_ms=row[8],
        outcome=row[9],
        attributes=row[10] or {},
    )
```

**`attributes` comes back already-sanitized** — masked on ingest by the
receiver's `data.sanitize`-backed sanitizer (`akosha/observability/tracing.py:383`).
Do **not** re-sanitize here: a second policy implementation is a second thing to
drift, and masking twice is not idempotent. Note the guarantee's scope — it
holds for producers routed through the akosha receiver, which is the only
writer (§5.1), but nothing here *enforces* it for a future non-akosha writer.

- [ ] **Step 4: Run and confirm pass**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/storage/test_span_query.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 5: Gate**

```bash
/Users/les/Projects/mahavishnu/.venv/bin/python \
  /Users/les/Projects/mahavishnu/scripts/audit_orphans.py
```

`SpanQuery` has test callers only until R-2. If the audit flags it, note in the
commit message that R-2 is the consumer — do not suppress.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/akosha
git add akosha/storage/span_query.py tests/unit/storage/test_span_query.py
git commit -m "feat(akosha): SpanQuery read surface over spans_substrate (R-1)

Read-only queries on the receiver's HotStore. No new connection, no ORM,
no writes. Establishes the shapes R-2 and R-3 register as MCP tools."
```

#### Integration Contract (R-1)
- **Triggered from**: nothing yet — R-2/R-3 are the consumers.
- **Returns to / updates**: `akosha/storage/span_query.py` (new), `SpanHit`/`SpanSummary`.
- **Demonstrable by**: `pytest tests/unit/storage/test_span_query.py -v` — 5 passing, including the missing-table, NULL-selector, all-NULL-latency and mid-pagination cases.
- **Rollback signal**: `test_search_keyset_pages_without_duplicates_or_gaps` sees a repeated `span_id` → the ORDER BY lost its `span_id` tiebreaker.
- **Observability added**: none (a library).

---

## Task R-2: `search_spans` MCP tool

**Spec §4.3.** Registers the browse surface. No aggregate.

**Files:**
- Modify: `akosha/mcp/tools/otel_span_tools.py` (new module, `register_otel_span_tools`)
- Modify: `akosha/mcp/server.py` — call the registrar alongside the existing `register_*_tools`
- Test: `akosha/tests/unit/mcp/test_search_spans_tool.py`

**Interfaces:**
- Consumes: `SpanQuery.search` (R-1)
- Produces: `search_spans` MCP tool

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest
from fastmcp import FastMCP

from akosha.mcp.tools.otel_span_tools import register_otel_span_tools


@pytest.fixture
def app() -> FastMCP:
    mcp = FastMCP("test")
    register_otel_span_tools(mcp)
    return mcp


@pytest.mark.asyncio
async def test_tool_is_registered(app: FastMCP) -> None:
    names = [t.name for t in await app.get_tools()]
    assert "search_spans" in names


@pytest.mark.asyncio
async def test_empty_result_is_success_not_error(app: FastMCP) -> None:
    """§5.2: no matches is exit 0 with an empty list. Conflating 'quiet' with
    'broken' turns a healthy service into a page."""
    result = await app._call_tool("search_spans", {})
    assert isinstance(result, list)
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/mcp/test_search_spans_tool.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `akosha/mcp/tools/otel_span_tools.py`:

```python
from __future__ import annotations

from typing import Any

from akosha.mcp.server import get_shared_hot_store
from akosha.storage.hot_store import HotStore
from akosha.storage.span_query import SpanQuery

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500


def register_otel_span_tools(app: Any) -> None:
    """Register the spans_substrate read tools.

    Pattern matches fitness_tools.py:42 — `@app.tool(name=...)` inside a
    `register_*_tools(app)` function. There is no module-level `mcp`.
    """

    @app.tool(name="search_spans")
    async def search_spans(
        service_name: str | None = None,
        service_namespace: str | None = None,
        outcome: str | None = None,
        since_unix_nano: int | None = None,
        until_unix_nano: int | None = None,
        trace_id: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search stored spans. Returns [] when nothing matches."""
        from akosha.config import get_config

        page = max(1, min(int(limit), MAX_PAGE_SIZE))
        parsed = _parse_cursor(cursor)
        # aksha already publishes the shared store: set_shared_hot_store at
        # server.py:282, get_shared_hot_store at :292, set by the lifespan.
        # Use it -- do NOT open a second connection (spec §4.1).
        store = get_shared_hot_store()
        if store is None:
            # Receiver has not started, so the DDL has not run either.
            return []
        hits = await SpanQuery(store).search(
            service_name=service_name,
            service_namespace=service_namespace,
            outcome=outcome,
            since_unix_nano=since_unix_nano,
            until_unix_nano=until_unix_nano,
            trace_id=trace_id,
            limit=page,
            cursor=parsed,
        )
        return [h.model_dump() for h in hits]
```

`cursor` crosses the MCP boundary as a string; encode it as
`"<received_at_unix_nano>:<span_id>"`. Cap `limit` — an unbounded page is the
egress risk spec §7 Q8 raises, and bounding it here is cheaper than answering
that question first.

**On authorization:** spec §7 Q6 records that this tool returns any producer's
spans to any MCP client with no authz. Do **not** add an allowlist filter as a
silent response to that — §5.4 already explains why the read path must not
re-apply the namespace allowlist. If a boundary is needed, it belongs at the
MCP server, and that is a separate decision.

- [ ] **Step 4: Run and confirm pass**
- [ ] **Step 5: Gate** (orphan audit)
- [ ] **Step 6: Commit**

#### Integration Contract (R-2)
- **Triggered from**: any MCP client of akosha.
- **Returns to / updates**: `akosha/mcp/tools/otel_span_tools.py` (new), `akosha/mcp/server.py`.
- **Demonstrable by**: `pytest tests/unit/mcp/test_search_spans_tool.py -v`; a live `search_spans` over the canary's rows returns one hit.
- **Rollback signal**: `test_empty_result_is_success_not_error` raises → §5.2's empty contract was inverted into an error.
- **Observability added**: none in this PR. §5.3's budget is unverified in production until a latency histogram exists (spec §7 Q7) — open, not closed.

---

## Task R-3: `spans_summary` MCP tool

**Spec §4.2.** The corrected §5.6 aggregate.

**Files:**
- Modify: `akosha/mcp/tools/otel_span_tools.py`
- Test: `akosha/tests/unit/mcp/test_spans_summary_tool.py`

- [ ] **Step 1: Write the failing test**

Cover Review Focus #3 and #5: an all-NULL-latency window, and a pair whose
spans are all outside the cutoff. Both must be distinguishable from a healthy
quiet window — `latency_p99_ms is None` is the signal.

- [ ] **Step 2: Run and confirm failure** (tool absent)
- [ ] **Step 3: Implement** — `spans_summary` delegating to `SpanQuery.summary`, passing `selector` and `task_class` through unchanged (including `None`).
- [ ] **Step 4: Run and confirm pass**
- [ ] **Step 5: Gate**
- [ ] **Step 6: Commit**

#### Integration Contract (R-3)
- **Triggered from**: MCP clients; R-6's rewired analyzer.
- **Returns to / updates**: `otel_span_tools.py`.
- **Demonstrable by**: `pytest tests/unit/mcp/test_spans_summary_tool.py -v`.
- **Rollback signal**: `span_count=0` and `latency_p99_ms=0.0` on an empty window → COALESCE / NULL handling regressed.
- **Observability added**: none yet; see R-2.

---

## Task R-4: migration runbook

**Spec §5.5.** Precedes R-5, and R-5 precedes R-6.

**Files:**
- Create: `docs/decisions/2026-10-20-otel-producer-migration.md`
- Modify: `mahavishnu/docs/ingestion/DATA_INGESTION.md` — add the substrate path

- [ ] **Step 1: Write the runbook**

It must state, concretely:

- A producer repoints by changing its OTLP exporter endpoint to
  `http://localhost:4317` (gRPC) or `:4318` (HTTP) and restarting. **No flag.**
  The v7 plan deleted `otel.receiver.trace_ingester_poller` rather than
  flipping it, because a settings key mapping to deleted code is a
  documentation lie.
- **No dual-write.** Spans written to both paths dedup invisibly at
  `ON CONFLICT`, so a rollback leaves no trace.
- Until a producer repoints, the read path returns empty. That is correct, not
  broken.
- Which service to verify with, and what "working" looks like.

- [ ] **Step 2: Review it against §5.6**

The runbook must not imply the analyzer is safe before R-5. Cross-reference the
coverage-narrowing consequence.

- [ ] **Step 3: Gate, commit**

#### Integration Contract (R-4)
- **Triggered from**: any repo about to repoint a producer.
- **Returns to / updates**: `docs/decisions/`, `DATA_INGESTION.md`.
- **Demonstrable by**: an operator follows it without asking a question.
- **Rollback signal**: none — documentation only.
- **Observability added**: none.

---

## Task R-5: repoint one real producer

**Spec §5.5, §5.6.** Mahavishnu first — it already emits OTLP.

**Files:**
- Modify: `mahavishnu/config/otel-collector-config.yaml` or the exporter's own config — the endpoint it *exports to*
- Test: a live check that spans land

- [ ] **Step 1: Establish the baseline**

Record what `search_spans` returns before the change. If it is already
non-empty, the producer has an unexpected path — stop and reconcile, do not
proceed on the assumption that it is only the canary.

- [ ] **Step 2: Repoint and restart**

- [ ] **Step 3: Verify spans arrive**

`search_spans` returns rows from this producer. **This is the first non-canary
writer in the substrate's life** — confirm with the operator-facing name, not
just a row count.

- [ ] **Step 4: Gate, commit**

#### Integration Contract (R-5)
- **Triggered from**: R-4's runbook.
- **Returns to / updates**: mahavishnu's exporter config.
- **Demonstrable by**: `search_spans` returns mahavishnu spans; `spans_summary` over a populated pair.
- **Rollback signal**: no rows within one heartbeat window after restart → the exporter is not reaching the receiver; revert the endpoint.
- **Observability added**: first real ingest volume in `telemetry_receiver_batch_inserted_total`.

---

## Task R-6: rewire `fitness_analyzer`

**Spec §5.6, §5.7.** **Blocked by R-5, not R-3.** Merging this before any real
producer emits makes the analyzer derive its inputs from a table holding only
synthetic-canary rows — the silent-signal-regression the spec names as the
reason for the ordering.

**Files:**
- Modify: `akosha/processing/fitness_analyzer.py:106` (`_collect_traces`), `:121` (`_compute_signal`)
- Test: `akosha/tests/unit/test_fitness_analyzer_rewired.py`

- [x] **Step 1: Answer §5.7 before writing code** — **DONE 2026-10-21**

The pair set comes from `SELECT DISTINCT selector, task_class` over the window,
from the v7 `known_mcp_servers` roster plus a producer→pairs mapping, or from a
static configured list. **`SELECT DISTINCT` has the failure mode spec §5.7
names**: a producer that migrated but emitted nothing disappears from the report
entirely, which is the false negative this whole change risks.

**Answered** in `docs/decisions/2026-10-21-fitness-analyzer-pair-inventory.md`:
a **declared inventory** for R-6's first cut (curated per producer, never the
15×5 cross product), union'd with observed pairs in the long-term design so that
both declared-but-silent and undeclared-but-observed are visible. The axes are
already canonical — `TaskCategory` (`core/model_routing.py:94-112`) and the five
pool-selector values — so the inventory is one new table, not an invention.

Note for the implementer: the fan-out being rewired is **already dead**
(`FitnessAnalyzer()` constructed with no args, `add_component` has zero call
sites, `fitness_analyzer.py:162` short-circuits on the empty list). The risk in
Step 2 is therefore not silent regression of a working signal but a new path
that reports zeros and looks healthy — which is what Step 2's test must catch.

- [ ] **Step 2: Write the failing test**

A test that pins *the distinction* §5.7 cares about: a configured pair with no
spans in the window must be **distinguishable** from a pair that is not
configured at all. If the implementation cannot tell them apart, the analyzer
reports healthy silence.

- [ ] **Step 3: Replace the fan-out**

`_collect_traces` no longer does `asyncio.gather` over
`_fetch_traces_from_component`. `_analyze_and_persist` calls
`SpanQuery.summary` once per pair.

**Preserve the failure-rate denominator.** Today's definition is
`error_count / len(traces)` over everything returned (`fitness_analyzer.py:134-135`),
which is the all-rows population `SpanSummary.span_count` also covers. Filtering
to `latency_ms IS NOT NULL` would silently redefine the reported fitness number
and nothing downstream knows the definition changed. p99 is a *different*
population — see spec §4.2.

- [ ] **Step 4: Keep the tool's shape**

`run_fitness_analysis` returns `self._signals` keyed by task_class→selector.
The MCP surface at `fitness_tools.py:42` must keep working unchanged — this is
an internal swap, not a contract change.

- [ ] **Step 5: Run, gate, commit**

#### Integration Contract (R-6)
- **Triggered from**: R-5 (a real producer exists); R-3 (the aggregate exists).
- **Returns to / updates**: `akosha/processing/fitness_analyzer.py`.
- **Demonstrable by**: `pytest tests/unit/test_fitness_analyzer_rewired.py -v`; `run_fitness_analysis` returns signals for a pair with spans.
- **Rollback signal**: the "configured pair, no spans" test cannot distinguish silence from absence → revert to the fan-out rather than ship a false negative.
- **Observability added**: none. This removes a failure mode (per-component endpoint health) rather than adding one; the replacement signal is v7's P0-A.

---

## Execution order

```
R-1 ──┬─▶ R-2
      └─▶ R-3 ──┐
R-4 ─────▶ R-5 ─┴─▶ R-6
```

R-2 and R-3 are independent of each other and of R-4/R-5. R-4 is
documentation and can land any time after R-1.

## Pre-plan verification

```bash
cd /Users/les/Projects/akosha
# R-1's substrate assumptions still hold after the DuckDB alignment
./.venv/bin/python -c "import duckdb; assert duckdb.__version__.startswith('2.0.0')"
./.venv/bin/python -m pytest tests/unit/storage -q
# Confirm the only other reader is still the one the spec enumerates
grep -rn "FROM spans_substrate" akosha/ --include="*.py" | grep -v span_query
```