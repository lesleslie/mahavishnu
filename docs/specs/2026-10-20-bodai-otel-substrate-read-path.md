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
| `_compute_signal` | `akosha/processing/fitness_analyzer.py:121` | aggregates **in Python**: `error_count / len(traces)` |
| MCP surface | `akosha/mcp/tools/fitness_tools.py:42` | `@app.tool(name="run_fitness_analysis")`, registered inside `register_fitness_tools(app)` — there is no module-level `mcp` object |

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

The query surface runs **in akosha**, because akosha is where the receiver already holds a `HotStore`. It is not a new service and opens no new database — see §4.1 for why one
connection, not two.

### 4.1 One connection, not two

The query surface takes the receiver's `HotStore` as a dependency. It must not construct its own.

Two same-process connections to one DuckDB file do work — verified on **both** builds this fleet carries (akosha's 1.5.6 and oneiric's 2.0.0-dev): the second opens, reads, writes, and sees the first's committed rows. So this is not a correctness constraint, it is a **simplicity** one. Two connections means two pools, two transaction boundaries, and a class of bug where the query tool reads a snapshot the receiver has not yet checkpointed.

**What one connection does and does not buy.** The receiver's `self._lock` is an `asyncio.Lock` held around *atomic mutation blocks* — `_ensure_operational_tables`, `_dlq_insert`, the advisory lock's acquire/renew/release. It does **not** serialise every `SELECT` against every `DELETE`, and DuckDB serialises writes internally on its own. An earlier draft of this section claimed the lock "serialises the reads, which is what the tests assume"; that overstated it, and it would have been load-bearing if anyone had sized ingestion latency against it.

The real consequence is the opposite one, and it belongs in the open questions rather than in a reassurance: a paginated `search_spans` issues N sequential queries against the same connection the receiver's batch INSERTs use, and a slow read **can** delay ingestion. §7 Q8 carries it. Nothing in this spec bounds page size, time range, or query timeout — that gap is recorded, not closed.

### 4.2 The §5.6 aggregate, corrected

Parent spec §5.6 is **stale against v7**. The logic is sound — `PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY …)`, `IS NOT DISTINCT FROM`, and the BIGINT-nanos comparison all execute on **akosha's own DuckDB 1.5.6**, which is the version this read path will run (§6.4) — but three things changed:

| §5.6 (parent spec) | v7 substrate | Why it matters |
|---|---|---|
| `FROM spans` | `FROM spans_substrate` | The v7 table name. No `spans` table exists anywhere in the fleet — the v7 plan's dropped PR-A6.5 recorded that the legacy ingester never wrote one. |
| `timestamp > now() - :window_seconds * INTERVAL '1 second'` | `received_at_unix_nano > :cutoff_unix_nano` | `received_at_unix_nano` is BIGINT epoch **nanos**, server-populated. There is no `timestamp` column on `spans_substrate` and no interval arithmetic against nanos. |
| (implied) producer clock | server receive clock | §8.2's cardinal rule: retention filters on `received_at_unix_nano`, never producer `start_time_unix_nano`. A read path filtering on a producer-shaped clock silently reintroduces the clock-skew bug the v5 review closed — reads would disagree with what retention actually kept. |

The corrected query:

```sql
SELECT
    COUNT(*)                                                            AS span_count,
    COALESCE(SUM(CASE WHEN outcome = 'error' THEN 1 ELSE 0 END), 0)     AS failure_count,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms)           AS latency_p99_ms
FROM spans_substrate
WHERE selector IS NOT DISTINCT FROM $selector
  AND task_class IS NOT DISTINCT FROM $task_class
  AND outcome IN ('success', 'error')
  AND received_at_unix_nano > $cutoff_unix_nano
```

**Bind with `$name`, not `:name`.** DuckDB's client rejects PEP-249 / SQLAlchemy
`bindparam` syntax outright — `WHERE selector = :selector` raises
`ParserException: syntax error at or near ":"`. Only `$name` and positional `?`
parse. `?` is used for the ad-hoc checks in the tests below; `$name` in the
tool body, because this query has five parameters and counting `?` is how
transposition bugs happen.

**Bind `cutoff_unix_nano` as an `int`.** It is BIGINT epoch nanos, and a float
loses precision at this magnitude: `1.7e18` round-trips to a value that no
longer equals `1700000000000000000`, so the boundary row silently drops out of
the window. Verified: bound as `int` → the row matches; bound as `float` → 0
rows. There is also no interval form — `received_at_unix_nano > now() -
INTERVAL '1 hour'` raises `BinderException: Cannot compare values of type
BIGINT and type TIMESTAMP WITH TIME ZONE`.

**`COALESCE` is required, not defensive.** `SUM(CASE …)` over zero matching rows
returns NULL, not 0. Without the wrapper, an empty window produces
`failure_count=None` and fails `SpanSummary.failure_count: int` validation — so
the empty-window contract in §5.8 would be unreachable by construction.

`IS NOT DISTINCT FROM` rather than `=`: `selector` is TEXT and nullable (§9's mapping has no semconv source for it — it is supplied by the decision-adapter producer), and a `=` against NULL yields NULL, silently dropping the row and under-reporting `span_count`.

`latency_ms` is REAL and nullable, and the NULLs change what the numbers mean.

**1. `PERCENTILE_CONT` excludes NULLs; the p99 is unbiased.** An earlier draft of
this spec claimed the opposite — that NULLs sort last and so pull p99 toward the
top of the distribution. **That claim was wrong, and is corrected here.** Verified
on 100 rows of which 95 had NULL latency:

```
p99 over all rows            = 4.96
p99 over latency IS NOT NULL = 4.96     -- identical
```

`PERCENTILE_CONT` excludes NULLs from its ordering set, per ordered-set
aggregate semantics. The hazard is real but belongs to a *different function*:
`PERCENTILE_DISC(0.99)` and `quantile(x, 0.99)` return `5.0` on that same data,
including the NULLs. Use `PERCENTILE_CONT`, and `latency_p99_ms` is `None` only
when the entire window lacks latency.

**2. The failure-rate denominator excludes them too, and that is a semantic
change to preserve deliberately.** `span_count` and `failure_count` are
unfiltered by latency, so the ratio covers all matching rows — but the p99
covers only latency-bearing ones. The two figures are computed over
**different populations**, and the rewired analyzer must not read p99 as if it
shared `span_count`'s denominator.

Today's analyzer computes `error_count / len(traces)` over everything the
endpoint returned, which is the same all-rows population §4.2 keeps. Filtering
the denominator to `latency_ms IS NOT NULL` would silently redefine the fitness
number the tool reports, and nothing downstream knows that definition changed.
Recorded here so a later reader does not "fix" it.

**Index support: stated accurately, because the first version of this claim was
wrong.** An earlier draft said `idx_spans_selector_task_class_outcome`
"(selector, task_class, outcome, received_at_unix_nano DESC)" is "an exact match
for the WHERE clause … the range predicate is index-ordered rather than a
post-filter … the plan's primary read index and it exists for this query." On
akosha's DuckDB 1.5.6 that is not what the planner does:

```
duckdb_indexes().expressions
  -> [selector, task_class, outcome, received_at_unix_nano]   # DESC is NOT stored

EXPLAIN of the §4.2 aggregate
  -> SEQ_SCAN  (Filters: selector IS NOT DISTINCT FROM ...,
                            task_class IS NOT DISTINCT FROM ...)
```

DuckDB normalises the stored index expression to ASC, and the predicates are
pushed down as **filters on a sequential scan**, not as index bounds. The
column *ordering* is as v7's DDL declares, but it carries no performance
implication on this version, and even a primary-key point lookup plans as a
`SEQ_SCAN`.

So: the indexes exist and are correctly shaped for this query, and the query is
fast anyway at the row counts measured in §5.3 — but "index-ordered, no sort
step" is not true, and this spec does not claim it. Whether that holds on
2.0.0-dev is untested and is not asserted either.

### 4.3 `search_spans` filters

All filters bind as parameters. None is interpolated.

| Filter | Column | Notes |
|---|---|---|
| `service_name` | `service_name` | backed by `idx_spans_service_name_recent` |
| `service_namespace` | `service_namespace` | allowlist-aware; see §5.4 |
| `outcome` | `outcome` | nullable. Populated values are `success` and `error`; see §4.2 — those two are the only values the aggregate filters on. A span whose producer set neither is stored NULL, searchable, and invisible to `spans_summary`. |
| `since` / `until` | `received_at_unix_nano` | BIGINT nanos, inclusive lower / exclusive upper |
| `trace_id` | `trace_id` | exact match |

Ordering is `received_at_unix_nano DESC, span_id DESC` — **`span_id` is part of the ORDER BY, not merely a cursor component.** A cursor over `(received_at_unix_nano, span_id)` against an `ORDER BY` on `received_at_unix_nano` alone is ambiguous for any page boundary that falls among rows sharing a receive time, and shared receive times are the normal case, not an edge case: `received_at_unix_nano` is stamped per batch, so every span in one export carries the same value. Ordering on the pair makes the cursor total, because `span_id` is the primary key and therefore unique.

`OFFSET` is never used, but the first draft of this section attributed its failure
to the wrong cause and said so wrongly. Measured, at page size 3:

| mutation during paging | OFFSET | keyset |
|---|---|---|
| retention sweep of the 4 **oldest** rows | no duplicates, **no gaps** | clean |
| INSERT at the head (steady-state ingestion) | **duplicate returned twice** | clean |
| DELETE of a not-yet-consumed row | **gap — row never seen** | clean |

A retention sweep deletes the oldest rows, which were already past the last
page, so it produces **neither** artifact. The real causes are **inserts above
the cursor** — which is this substrate's normal condition, since the receiver is
ingesting while you read — and **deletes at or above the cursor**. Both are
demonstrable, and an offset cursor cannot be repaired after the fact, which is
the whole reason for keyset.

The tiebreaker is load-bearing, and not merely as a uniqueness argument. With six
rows sharing one `received_at_unix_nano`:

```
keyset on (received_at_unix_nano, span_id)  -> all 6 returned, complete
keyset on received_at_unix_nano alone       -> 3 of 6 returned, 3 silently lost
```

The keyset predicate must therefore be the tuple `(received_at_unix_nano,
span_id) < (?, ?)`, and the `DESC` on `span_id` must match the `ORDER BY` or the
cursor re-emits rows on a tie.

Index support for the ordering is **not** claimed — see §4.2's index paragraph,
which corrects an earlier over-statement. The planner uses a sequential scan on
akosha's DuckDB.

### 4.4 Result shape

Pydantic models — the dependency akosha already has. Not ORM-backed row classes; see §6.1.

```python
class SpanSummary(BaseModel):
    span_count: int
    failure_count: int
    latency_p99_ms: float | None

class SpanHit(BaseModel):
    span_id: str
    trace_id: str | None   # DDL: `trace_id TEXT`, nullable — v7:134
    parent_span_id: str | None
    service_name: str
    service_namespace: str    # DDL: `service_namespace TEXT NOT NULL` — v7:137
    span_name: str
    start_time_unix_nano: int
    received_at_unix_nano: int
    duration_ms: float | None
    outcome: str | None
    attributes: dict[str, Any]
```

`attributes` is returned **as stored**, and is **not** re-sanitized on read. Masking happens once, on ingest, and re-applying it on read would double-mask anything already masked (`"***"` is not itself a sensitive key, but a re-mask pass over a mutated attribute set is a second policy implementation to keep in sync, and the read path must not be one).

What that means in practice needs stating precisely, because it is weaker than "the column is sanitized":

- The masker lives in **akosha** — `akosha/observability/tracing.py:383`, built on oneiric's `data.sanitize` kit over a canonical `_PII_MASK_FIELDS` tuple.
- v7 masks in `OTLPReceiver._iter_spans`, which is the akosha receiver's ingest path.
- **Every producer that routes through that receiver is sanitized. A producer that does not is not.**

Sanitization is therefore a property of *the ingest path*, not of the table. §5.5's migration procedure — change an OTLP exporter endpoint — routes a producer into akosha's receiver and so into the masker, which is the desired default. But a producer writing to `spans_substrate` through any other route bypasses it, and this spec has no mechanism to detect that.

§7 Q5 carries the open question: whether the read path should assert a redaction guarantee it cannot currently enforce, or whether the guarantee belongs to the ingest contract and the read path should simply not restate it. The conservative default, and the one this spec takes, is to **document** the guarantee's scope rather than to assert it unconditionally.

## 5. Behaviour

### 5.1 The receiver is the only writer; this spec adds no writer

`spans_substrate` rows arrive only through `insert_spans_substrate`. The read path never inserts.

**v7 already ships four readers against this table**, and this spec is the fifth — not the first, and not the second:

| Reader | Cadence | What it runs |
|---|---|---|
| Heartbeat watcher (v7 Task 8) | every 60s, via the receiver's lifespan task | `SELECT 1 … WHERE service_name = ? AND received_at_unix_nano > ? LIMIT 1` |
| Retention sweep (v7 §8.2) | every 6h when `archival_target` is set | `COPY (SELECT * …)` — a full read of everything past the cutoff |
| Retention sweep | same cycle | `DELETE FROM spans_substrate WHERE received_at_unix_nano < ?` |
| Row-count alert (v7 §8.2) | per scrape | `COUNT(*)` against a `max_rows` ceiling |
| `cardinality-report` (v7 Task 6) | operator-invoked | `SELECT COUNT(*)` **grouped by `service_name`**, not a bare count |

Two consequences. The heartbeat watcher runs **on the same connection this spec shares** (§4.1), so the two must coexist — it is a 60-second `LIMIT 1` probe against paginated reads. And the sweep's `COPY` is the heaviest reader on the table; a slow `spans_summary` and a sweep's `COPY` compete for the same file, which is DuckDB's serialised write path.

An earlier draft of this section claimed `cardinality-report` was "the only other reader." That was wrong by three, and understated `cardinality-report` itself, which aggregates rather than counting.

### 5.2 Empty result vs. error

`search_spans` with filters matching nothing returns an empty list with `exit 0`. It does not raise. Distinguishing "no spans in this window" from "the query failed" is the caller's job; conflating them turns a quiet service into a page.

### 5.3 Performance budget — now measured, and re-scoped

The first draft of this section carried `< 200ms p99` at 100k spans and admitted
it was a guess. It is now measured, in-memory, on this machine, synthetic rows,
no concurrent writer — which is **not** a production benchmark and is labelled as
such:

| table size | matched rows | p50 | **p99** | against a 200ms budget |
|---|---|---|---|---|
| 100k / 100 pairs | 857 | 8.7 ms | **14.6 ms** | holds, ~14× inside |
| 100k, all in one pair (worst selectivity) | 88,572 | 18.7 ms | **28.0 ms** | holds |
| 1M / 100 pairs | 8,571 | 37.3 ms | **114.2 ms** | marginal |
| **10M / 100 pairs** | 85,714 | 77.2 ms | **334.6 ms** | **fails** |

v7 §8.2 sets `spans_substrate_max_rows` to exactly **10,000,000**. The budget
holds at the 100k the first draft named and **fails at v7's own configured
ceiling**, and these numbers use a ~7-byte `attributes` payload where real spans
carry real JSON — so real cost is higher.

Two consequences. §3's "no materialized projection" non-goal now has a measured
trigger rather than a guessed one. And the budget should be restated as
row-count-scaled, not a single number — a flat 200ms that holds at 100k tells an
operator nothing about what happens when the table is at its cap. §7 Q10 carries
it.

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

### 5.7 Where the `(selector, task_class)` pair set comes from

**This is the mechanism of the whole rewiring, and it is not yet decided.**

Today the pair set is an emergent property of the HTTP fan-out: enumerate registered component endpoints, ask each for its traces, group what comes back. Rewiring removes the enumeration, and nothing replaces it. Three candidates, with different failure modes:

| Source | Failure mode |
|---|---|
| `SELECT DISTINCT selector, task_class FROM spans_substrate` | **The analyzer's input set is derived from the data it analyses.** A service that migrated but emitted nothing this window disappears from the report entirely — and "idle" and "broken" become indistinguishable. This is precisely the false-negative §5.6 exists to avoid, reintroduced at the enumeration layer. |
| The v7 `otel.receiver.known_mcp_servers` roster | Enumerates producers, not `(selector, task_class)` pairs. Needs a declared mapping from producer to the pairs it emits, which does not exist today. |
| A static configured list | Predictable and explicit, but goes stale silently as new selectors appear. Staleness is visible, though — an unknown pair produces no rows, and a configured pair producing no rows is a distinguishable condition. |

§7 Q1 carried this as the first open question, ahead of the coverage question it is nested inside, because it is the question whose wrong answer produces a **healthy-looking wrong number** rather than a missing feature. R-6 must not be implemented until it is answered.

**Resolved 2026-10-21 — see
`docs/decisions/2026-10-21-fitness-analyzer-pair-inventory.md`.** The answer is
**none of the three rows above on its own**: a *declared* inventory for R-6's
first cut, union'd with *observed* pairs in the long-term design, with the
difference carried as report output. `SELECT DISTINCT` is rejected outright — it
re-derives the inventory from the data and so reintroduces, at the substrate
layer, exactly the "inventory is a function of your own traffic" property the
rewrite exists to remove. The static list alone is adopted for R-6 but cannot
see drift, which is why the union, not the list, is the long-term shape.

One finding materially reframes the stakes. The fan-out is **already dead**:
`FitnessAnalyzer()` is constructed with no arguments
(`akosha/mcp/tools/__init__.py:170`), `add_component` has zero call sites
fleet-wide, and `fitness_analyzer.py:162` short-circuits on the empty endpoint
list. So §5.6's "silent-signal-regression of a working signal" is not the risk —
there is no working signal. The risk is its mirror: shipping a path that returns
zeros and looks healthy. That makes the distinction the decision turns on
*sharper*, not less important: with an empty substrate, a data-derived
inventory yields no pairs at all while a declared one yields declared pairs with
zero rows — the same dashboard, opposite readings.

### 5.8 The empty-window contract for `spans_summary`

§5.2's empty contract covers `search_spans` only. `spans_summary` needs its own, and it is not the same shape:

- Zero rows matching the WHERE clause returns `span_count=0`, `failure_count=0`, `latency_p99_ms=None`, exit 0.
- That is indistinguishable from a healthy quiet window unless the caller inspects `latency_p99_ms is None` — which is non-None whenever *any* row in the window carries a latency, because `PERCENTILE_CONT` ignores NULLs (§4.2).

Because §5.6's analyzer drives its failure rate from these numbers, the tool **must** distinguish "nothing to report" from "everything fine". The result model carries `latency_p99_ms: float | None` for exactly this reason; the consumer is responsible for treating `None` as *no data*, not as *zero latency*. Documenting that here because it is a contract, not an implementation detail.

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

### 6.2 No decision — an open gap, recorded not closed

The read tools log query parameters. A `service_name` or `selector` is operator-supplied and reaches a log line, and akosha's existing sanitizer operates on record-shaped payloads, not on query strings — so `data.sanitize` does not cover this case and no decision is made here.

This entry exists so the gap is visible. It is not a decision, and it must not be implemented as one by anyone skimming the heading. If the tools come to log full query payloads, `data.sanitize` over an allowlist is the right primitive and its field list should be reused rather than duplicated — but that is a future decision with its own review.

### 6.3 Read path lands in akosha

Named by parent-spec §5.6, and where the receiver already holds the connection. A separate read service would need either a shared DuckDB file across processes (single-writer contention with the receiver) or its own copy (a second source of truth). Neither is acceptable.

### 6.4 The fleet carries two DuckDB builds, and this spec runs on the older one

```
/Users/les/Projects/akosha/.venv   duckdb 1.5.6          <- the read path runs HERE
/Users/les/Projects/oneiric/.venv  duckdb 2.0.0.dev2610192346
```

`akosha/uv.lock:1246` pins 1.5.6; `akosha/pyproject.toml:16` declares `duckdb>=0.10.0` with no upper bound, so its resolution does not inherit oneiric's pin. **The `duckdb` library is resolved by the importing process, not by the repo that owns the DDL.** oneiric owns `spans_substrate`; akosha opens it.

Every "verified on DuckDB X" claim in a oneiric-hosted spec is therefore ambiguous, and an earlier draft of this document made exactly that error — it verified the §4.2 aggregate against oneiric's 2.0.0-dev while the query ships in akosha. Claims here are re-verified on **akosha's 1.5.6**, and §4.2's query, `IS NOT DISTINCT FROM`, and the BIGINT-nanos comparison all execute there.

This is not a read-path concern alone. It has one concrete consequence already found in the v7 plan: `DELETE ... .rowcount` returns the affected count on 2.0.0-dev but **returns `-1` on 1.5.6**, which is the version the retention sweep actually runs. That is recorded in the v7 plan, not fixed here. §7 Q7 carries the alignment question.

## 7. Open questions for review

### Resolved

**Q1 — §5.7 pair inventory: where does the `(selector, task_class)` pair set
come from? — RESOLVED 2026-10-21.** Answered by
`docs/decisions/2026-10-21-fitness-analyzer-pair-inventory.md`: a declared
inventory for R-6's first cut, union'd with observed pairs in the long-term
design, with the difference carried as report output so that
declared-but-silent and undeclared-but-observed are both visible. Neither
`SELECT DISTINCT` nor a bare static list survives on its own.

*Numbering note (2026-10-21):* §5.7 referred to this as "§7 Q1", but the
question was never listed here — the list began at the coverage-narrowing
question. It is recorded now as a resolved entry rather than renumbering the
list, so the existing `Q4` / `Q10` cross-references stay valid.

### Open

1. **§5.6 coverage narrowing.** Is repointing one producer in this spec sufficient, or does the rewiring need to wait for every producer in the roster? The narrow reading says one is enough to prove the path; the cautious reading says the analyzer loses real signal until all are migrated.
2. **Does `search_spans` need a `trace_id`-shaped browse mode** (all spans of one trace), or is exact `trace_id` filtering enough? The former is a natural second tool and is deliberately out of scope here.
3. **Is `spans_summary`'s budget (§5.3) achievable**, and does anyone want it measured before the plan is written? It is currently a guess with a number attached.
4. **Should `selector`/`task_class` filters be required rather than optional?** Optional filters on an indexed composite can still full-scan when the `(selector, task_class)` prefix is absent.
5. **The redaction guarantee (new — from review).** §4.4 no longer asserts attributes are masked, because the sanitizer's only call sites today are `akosha/tests/unit/test_action_kit_adoption.py` — nothing in production invokes it, and `class OTLPReceiver` does not exist yet. v7 Task 5 adds that call site, after which the guarantee becomes real for the akosha receiver. Question: does the read path document a producer-side requirement, or does it stay silent and leave the guarantee entirely to the ingest contract?
6. **Authorization (new — from review).** `search_spans` returns any span from any producer, including unbounded `attributes` JSON, to any MCP client. No authn, no authz, no per-caller scoping. §5.4 declines to re-apply the namespace allowlist as a read filter, which removes the one filter that would have limited cross-namespace visibility. Is akosha's MCP surface assumed to sit behind an authenticated boundary, or does this need one?
7. **DuckDB alignment (new — from §6.4).** akosha resolves 1.5.6 while oneiric resolves 2.0.0-dev, and the shared substrate code runs on whichever the importing process resolves. Should akosha's pin be aligned with oneiric's, or should every substrate-touching claim be verified twice? The first option is a lockfile change to another repo's dependency, so it is not this spec's call to make.
8. **Resource limits (new — from review).** Every filter is optional; nothing bounds max time range, page size, rows returned, or query timeout. A caller who omits all filters gets the whole retention window. Related to Q4 but distinct: Q4 asks which filters to require, this asks for a ceiling.
9. **Budget shape (new — from §5.3).** A flat <200ms p99 holds at 100k rows and fails at v7's 10M `spans_substrate_max_rows` cap. Should the budget be restated as row-count-scaled, and should `spans_summary` refuse or warn above some matched-row count rather than simply getting slower?
10. **Table-existence (new — from review).** §5.5 says the read path "returns empty" before any producer migrates. But the DDL is created by the receiver's `_ensure_operational_tables`, so before the receiver has started at least once the table may not exist and the tools would error rather than return empty. Should R-1 depend on the receiver having run?

## 8. PR boundaries

| PR | Ships | Repo | Blocked by |
|---|---|---|---|
| R-1 | query surface + Pydantic models, no tools registered | akosha | — |
| R-2 | `search_spans` MCP tool | akosha | R-1 |
| R-3 | `spans_summary` MCP tool (the corrected §5.6 aggregate) | akosha | R-1 |
| R-4 | migration runbook | mahavishnu | — |
| R-5 | one producer repointed | mahavishnu | R-4 |
| R-6 | `fitness_analyzer` rewiring | akosha | **R-5** |

R-1 through R-3 are independently testable and independently rejectable.

**R-6 (the rewiring) is blocked by R-5, not by R-3.** §5.6 establishes why: rewiring before any real producer emits makes the analyzer derive its inputs from a table containing only synthetic-canary rows, which is the silent-signal-regression case. The dependency lives in this table because this table is what a builder reads — §5.6's prose is not a substitute for it. R-4 (the runbook) is extracted from the old R-5 precisely because it is a prerequisite of R-6, not an afterthought of the last PR.

## 9. References

- v7 substrate spec: `docs/specs/2026-10-19-bodai-substrate-otel-v7.md` — §5.1 DDL, §8.2 cardinal rule, §9 attribute mapping, §11.3 metric contract
- v7 implementation plan: `docs/plans/2026-10-19-bodai-substrate-otel-v7-implementation.md`
- parent spec: `docs/specs/2026-10-19-bodai-event-sourced-otel-architecture.md` §5.6, §5.7
- ADR 017 — oneiric owns the persistence substrate
- `akosha/storage/hot_store.py:76` — `HotStore(DuckdbHotStore)`, `database_path=` kwarg
- `akosha/processing/fitness_analyzer.py:106,121,232` — the HTTP fan-out being replaced
- `akosha/mcp/tools/fitness_tools.py:42` — the existing MCP surface
- `akosha/observability/tracing.py:383` — the `data.sanitize`-backed attribute masker
