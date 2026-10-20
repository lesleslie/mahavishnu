---
status: draft
role: canonical
kind: plan
date: 2026-10-20
last_reviewed: 2026-10-20
superseded_by: null
blocks_on:
  - docs/specs/2026-10-19-bodai-substrate-otel-v7.md
topic: substrate-otel
title: "Bodai OTel Substrate — Read Path"
parent_spec: docs/specs/2026-10-19-bodai-event-sourced-otel-architecture.md
depends_on:
  - docs/plans/2026-10-19-bodai-substrate-otel-v7-implementation.md
review: []
---

# Bodai OTel Substrate — Read Path

**Status:** Draft. Sub-spec A′; companion to the v7 substrate spec.
**Repos in scope:** `akosha` (query surface, MCP tools, fitness projection), `mahavishnu` (one producer repointed), `oneiric` (substrate access only — read-only).
**Blocked on:** the v7 implementation plan. The receiver must be ingesting before anything can query it.

---

## 1. Why this exists

The v7 spec delivers a **write path**: producers emit OTLP, `akosha`'s `OTLPReceiver` validates and batches into `oneiric`'s `spans_substrate`, with retention, archival, a heartbeat watcher, and a synthetic canary.

It delivers no read path. No task builds a query surface. No task repoints a producer at the new receiver. The substrate could be fully built, all twelve tasks merged, every test green — and the only writer would be the synthetic canary.

This spec closes that. It adds the query surface, and it rewires the one consumer that already exists.

### 1.1 The consumer is not a query today

This is the finding that shapes the scope. The parent spec's §5.6 describes a read-side projection at `akosha/fsm/projections.py` running SQL against a `spans` table. **That file does not exist, and that SQL has never run.**

What exists today:

| Component | Location | What it actually does |
|---|---|---|
| `run_fitness_analysis` | `akosha/processing/fitness_analyzer.py:232` | calls `_analyze_and_persist`, returns an in-memory `self._signals` dict |
| `_collect_traces` | `akosha/processing/fitness_analyzer.py:106` | `asyncio.gather` over `_fetch_traces_from_component(name, url, task_class)` — **HTTP fan-out to each component** |
| `_compute_signal` | `akosha/processing/fitness_analyzer.py:120` | aggregates **in Python**: `error_count / len(traces)` |
| MCP surface | `akosha/mcp/tools/fitness_tools.py:43` | `@mcp.tool` wrapper over the above |

So the read path is not "a query surface bolted onto a new table." It is **replacing an N-way HTTP poll with one local SQL query.** That is the better story and the smaller change — but it is a real architectural substitution with real consequences, and §7 states them.

## 2. Scope

Five items:

1. A parameterized query surface over `spans_substrate`, on the connection the receiver already holds.
2. A `search_spans` MCP tool (filters: service, namespace, outcome, time range; paginated).
3. A `spans_summary` MCP tool carrying the §5.6 aggregate, corrected for v7 columns (§4.2).
4. Rewiring `fitness_analyzer` from HTTP fan-out to the local aggregate.
5. Repointing one real producer, and a migration runbook so each consumer repo opts in on its own PR.

## 3. Non-goals

- **No ORM.** See §6.1 — this is a load-bearing decision with a hard blocker behind it.
- **No schema changes.** `spans_substrate` is owned by oneiric under ADR 017. This spec reads it; it does not alter it, and any new index is a v7 amendment.
- **No materialized projection table.** §5.6's phrasing ("materializes `FSMInput`") implies one. The aggregate is fast enough to run per call against the existing composite index; materializing introduces invalidation that §5.7's partition rule does not solve. Revisit only if p99 on `spans_summary` exceeds the budget in §5.3.
- **No cross-repo span search.** Mahavishnu's `search_otel_traces` keeps its current implementation. Repointing it is out of scope; akosha is the substrate's read surface.
- **Not the full §5.6 FSM framework.** Only the aggregate moves. The partition rule, registration-time overlap detection, and shared-projection machinery stay as designed and remain unimplemented.

## 4. Architecture

```
producer ──OTLP :4317/:4318──▶ OTLPReceiver ──▶ spans_substrate (oneiric)
                                       │              ▲
                                       │ same conn    │
                                       ▼              │
                              query surface (NEW) ─────┘
                                       │
                        ┌──────────────┴──────────────┐
                        ▼                             ▼
                 search_spans                  spans_summary ──▶ fitness_analyzer
                (MCP, paginated)                (MCP, aggregate)
```

The query surface runs **in akosha**, because akosha is where the receiver already holds a `HotStore`. It is not a new service and opens no new database (§6.1).

### 4.1 One connection, not two

The query surface takes the receiver's `HotStore` as a dependency. It must not construct its own.

Two same-process connections to one DuckDB file do work — verified on 2.0.0-dev: the second opens, reads, writes, and sees the first's committed rows. So this is not a correctness constraint, it is a **simplicity** one. Two connections means two pools, two transaction boundaries, and a class of bug where the query tool reads a snapshot the receiver has not yet checkpointed. One `HotStore` means the receiver's `self._lock` also serialises the reads, which is what the tests assume.

### 4.2 The §5.6 aggregate, corrected

Parent spec §5.6 is **stale against v7**. The logic is sound — `PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY …)` executes verbatim on DuckDB 2.0.0-dev, verified — but three things changed:

| §5.6 (parent spec) | v7 substrate | Why it matters |
|---|---|---|
| `FROM spans` | `FROM spans_substrate` | The v7 table name. No `spans` table exists anywhere in the fleet — the v7 plan's dropped PR-A6.5 recorded that the legacy ingester never wrote one. |
| `timestamp > now() - :window_seconds * INTERVAL '1 second'` | `received_at_unix_nano > :cutoff_unix_nano` | `received_at_unix_nano` is BIGINT epoch **nanos**, server-populated. There is no `timestamp` column on `spans_substrate` and no interval arithmetic against nanos. |
| (implied) producer clock | server receive clock | §8.2's cardinal rule: retention filters on `received_at_unix_nano`, never producer `start_time_unix_nano`. A read path filtering on a producer-shaped clock silently reintroduces the clock-skew bug the v5 review closed — reads would disagree with what retention actually kept. |

The corrected query:

```sql
SELECT
    COUNT(*)                                          AS span_count,
    SUM(CASE WHEN outcome = 'error' THEN 1 ELSE 0 END) AS failure_count,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms) AS latency_p99_ms
FROM spans_substrate
WHERE selector IS NOT DISTINCT FROM :selector
  AND task_class IS NOT DISTINCT FROM :task_class
  AND outcome IN ('success', 'error')
  AND received_at_unix_nano > :cutoff_unix_nano
```

`IS NOT DISTINCT FROM` rather than `=`: `selector` is TEXT and nullable (§9's mapping has no semconv source for it — it is supplied by the decision-adapter producer), and a `=` against NULL yields NULL, silently dropping the row and under-reporting `span_count`.

`latency_ms` is REAL and nullable. A NULL latency sorts last in `ORDER BY`, so `PERCENTILE_CONT` interpolates toward the end of the distribution. §5.3 records this as known; it is not silently corrected.

**Index support.** `idx_spans_selector_task_class_outcome` is `(selector, task_class, outcome, received_at_unix_nano DESC)` — an exact match for the WHERE clause, with the timestamp as the fourth key so the range predicate is index-ordered rather than a post-filter. This is the plan's primary read index and it exists for this query.

### 4.3 `search_spans` filters

All filters bind as parameters. None is interpolated.

| Filter | Column | Notes |
|---|---|---|
| `service_name` | `service_name` | backed by `idx_spans_service_name_recent` |
| `service_namespace` | `service_namespace` | allowlist-aware; see §5.4 |
| `outcome` | `outcome` | `success` / `error` / `unset` |
| `since` / `until` | `received_at_unix_nano` | BIGINT nanos, inclusive lower / exclusive upper |
| `trace_id` | `trace_id` | exact match |

Ordering is `received_at_unix_nano DESC`, which is the trailing key of every index on the table — so no sort step. Pagination is keyset on `(received_at_unix_nano, span_id)`, never `OFFSET`: `LIMIT`/`OFFSET` re-scans the skipped rows, and the sweep deletes old rows underneath a paged read, so `OFFSET` returns **duplicates and gaps across pages**. `span_id` is the tiebreaker because it is the primary key and therefore unique.

### 4.4 Result shape

Pydantic models — the dependency akosha already has. Not ORM-backed row classes; see §6.1.

```python
class SpanSummary(BaseModel):
    span_count: int
    failure_count: int
    latency_p99_ms: float | None

class SpanHit(BaseModel):
    span_id: str
    trace_id: str
    parent_span_id: str | None
    service_name: str
    service_namespace: str | None
    span_name: str
    start_time_unix_nano: int
    received_at_unix_nano: int
    duration_ms: float | None
    outcome: str | None
    attributes: dict[str, Any]
```

`attributes` is the **already-sanitized** JSON column. The read path must not re-sanitize and must not re-render masked values: `attributes` was masked on the way in by akosha's `data.sanitize`-backed sanitizer (`akosha/observability/tracing.py:383`), and a read path that returned unmasked values would undo that at exactly the point a human is most likely to look.

## 5. Behaviour

### 5.1 The receiver is the only writer; this spec adds no writer

`spans_substrate` rows arrive only through `insert_spans_substrate`. The read path never inserts. The one-off `SELECT COUNT(*)` in v7's `cardinality-report` remains the only other reader, and it stays.

### 5.2 Empty result vs. error

`search_spans` with filters matching nothing returns an empty list with `exit 0`. It does not raise. Distinguishing "no spans in this window" from "the query failed" is the caller's job; conflating them turns a quiet service into a page.

### 5.3 Performance budget

`spans_summary` over a 24h window on one `(selector, task_class)` pair: **< 200ms p99**, measured against a table seeded to 100k spans. Exceeding this is the trigger for revisiting the §3 materialization non-goal. The number is a budget, not an observation — nobody has measured it yet, and this spec does not claim anyone has.

### 5.4 Namespace allowlist is a receiver concern, not a read concern

`ResourceValidator` (v7 Task 9) rate-limits off-allowlist namespaces **at ingest**, and `_metric_namespace_drift` counts them. The read path does **not** re-apply the allowlist as a filter — doing so would make `search_spans` silently incomplete relative to `spans_summary`, with no way for an operator to see the spans that were dropped. Off-allowlist spans are returned like any other; the drift metric is the signal that they exist.

### 5.5 Producer migration is per-repo, never a flag

Each producer repo repoints in its own PR, by changing its OTLP exporter endpoint. There is no substrate-side feature flag and no dual-write: the v7 substrate already retired one flag for exactly this reason (a settings key mapping to deleted code is a documentation lie), and dual-writing spans produces rows that dedup invisibly at `ON CONFLICT`, so a rollback leaves no trace.

The read path is available before any producer migrates. It returns empty. That is correct, not broken, and the runbook says so.

### 5.6 `fitness_analyzer` rewiring

`_collect_traces` stops doing HTTP fan-out; `_analyze_and_persist` calls the local aggregate once per `(selector, task_class)` pair instead of once per `(task_class)` per component.

Consequences, stated plainly:

- **Latency.** N HTTP round-trips collapse to N local queries. The analyzer gets faster and stops depending on each component's endpoint being up.
- **Coverage narrows.** Today the analyzer sees whatever each component's endpoint returns, including spans that never reached the substrate. After rewiring it sees only what producers actually sent to the receiver. A producer that has not migrated contributes nothing — previously it contributed via its own endpoint. **This is the real regression risk**, and it is why §2 item 5 (repoint a real producer) must land before or with §5.6, not after.
- **Failure mode changes.** A dead component endpoint currently shows up as a degraded fitness signal. Afterwards it shows up as *absent spans*, which surfaces through the v7 heartbeat watcher's P0-A instead. The two are not equivalent — P0-A is per-producer and roster-driven; the endpoint check was per-call.

## 6. Decisions log

### 6.1 No ORM — no SQLModel, no SQLAlchemy

`sqlmodel` 0.0.48 is present in the akosha venv, but transitively, as a FastAPI/SQLAlchemy dependency. **No repo declares it** except session-buddy and crackerjack.

SQLModel is a Pydantic layer over SQLAlchemy, and SQLAlchemy needs a dialect. Verified on this fleet:

```
duckdb_engine     -> not installed in any venv (akosha, oneiric, mahavishnu,
                     session-buddy, crackerjack)
duckdb.sqlalchemy -> ModuleNotFoundError on duckdb 2.0.0-dev
```

SQLModel therefore **cannot open the substrate today**. Wiring it means adding `duckdb-engine` → SQLAlchemy 2.x → into akosha.

Beyond the blocker, it is the wrong shape here. The read query is an aggregate returning a 3-tuple, not entity CRUD — there is no row to map to a model. SQLAlchemy's expression language for `PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY …)` is worse than the SQL already specified in §4.2. And a second, ORM-owned connection into `spans_substrate` is exactly the invariant §4.1 declines to break.

Two hypotheses were tested and **discarded**, recorded so they are not re-litigated: DuckDB does *not* forbid a second same-process connection (it opens, reads, writes), and that connection *does* see the first's committed rows. The objection is design, not feasibility.

If typed models are the real pull, define Pydantic models directly — §4.4 does, and Pydantic is already a hard dependency.

### 6.2 Reuse oneiric's `data.sanitize` for the read path's own logging

The read tools log query parameters. A `service_name` or `selector` is operator-supplied and reaches a log line. akosha's existing sanitizer covers record-shaped payloads, not query strings, so this spec does **not** claim the kit solves it — it records the gap. If the tools ever log full query payloads, `data.sanitize` is the right primitive and its field list should be reused rather than duplicated.

### 6.3 Read path lands in akosha

Named by parent-spec §5.6, and where the receiver already holds the connection. A separate read service would need either a shared DuckDB file across processes (single-writer contention with the receiver) or its own copy (a second source of truth). Neither is acceptable.

## 7. Open questions for review

1. **§5.6 coverage narrowing.** Is repointing one producer in this spec sufficient, or does the rewiring need to wait for every producer in the roster? The narrow reading says one is enough to prove the path; the cautious reading says the analyzer loses real signal until all are migrated.
2. **Does `search_spans` need a `trace_id`-shaped browse mode** (all spans of one trace), or is exact `trace_id` filtering enough? The former is a natural second tool and is deliberately out of scope here.
3. **Is `spans_summary`'s budget (§5.3) achievable**, and does anyone want it measured before the plan is written? It is currently a guess with a number attached.
4. **Should `selector`/`task_class` filters be required rather than optional?** Optional filters on an indexed composite can still full-scan when the `(selector, task_class)` prefix is absent.

## 8. PR boundaries

| PR | Ships | Repo |
|---|---|---|
| R-1 | query surface + Pydantic models, no tools registered | akosha |
| R-2 | `search_spans` MCP tool | akosha |
| R-3 | `spans_summary` MCP tool (the corrected §5.6 aggregate) | akosha |
| R-4 | `fitness_analyzer` rewiring | akosha |
| R-5 | one producer repointed + migration runbook | mahavishnu |

R-1 through R-3 are independently testable and independently rejectable. R-4 depends on R-3. R-5 is the first PR where a non-canary writer exists.

## 9. References

- v7 substrate spec: `docs/specs/2026-10-19-bodai-substrate-otel-v7.md` — §5.1 DDL, §8.2 cardinal rule, §9 attribute mapping, §11.3 metric contract
- v7 implementation plan: `docs/plans/2026-10-19-bodai-substrate-otel-v7-implementation.md`
- parent spec: `docs/specs/2026-10-19-bodai-event-sourced-otel-architecture.md` §5.6, §5.7
- ADR 017 — oneiric owns the persistence substrate
- `akosha/storage/hot_store.py:76` — `HotStore(DuckdbHotStore)`, `database_path=` kwarg
- `akosha/processing/fitness_analyzer.py:106,120,232` — the HTTP fan-out being replaced
- `akosha/mcp/tools/fitness_tools.py:43` — the existing MCP surface
- `akosha/observability/tracing.py:383` — the `data.sanitize`-backed attribute masker