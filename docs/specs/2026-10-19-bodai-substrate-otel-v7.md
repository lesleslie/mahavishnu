---
status: draft
role: canonical
kind: plan
date: 2026-10-19
last_reviewed: 2026-10-20
superseded_by: null
blocks_on: []
topic: substrate-otel
title: "Bodai OTel Substrate — v7"
parent_spec: docs/specs/2026-10-19-bodai-event-sourced-otel-architecture.md
supersedes: docs/specs/.archive/2026-10-19-bodai-substrate-otel-v6.md
review:
  - 2026-10-19 v3: critical-audit-specialist (5 P0, 3 P1, 4 P2)
  - 2026-10-19 v3: observability-incident-lead (2 P0, 3 P1, 1 P2)
  - 2026-10-19 v4: critical-audit-specialist (2 P0, 3 P1, 1 P2)
  - 2026-10-19 v4: observability-incident-lead (2 P0, 5 P1, 1 P2)
  - 2026-10-19 v5: critical-audit-specialist (1 P0, 2 P1, 2 P2 + disputed jitter)
  - 2026-10-19 v5: observability-incident-lead (3 P0, 2 P1, 1 P2)
  - 2026-10-19 v5: oneiric-specialist (3 P0, 0 P1, 0 P2 — DuckDB 1.5.6 verification)
  - 2026-10-19 v6: akosha-specialist (3 P1, 4 P2, 1 P3 — akosha-codebase wiring)
  - 2026-10-19 v7: pending (post-draft 1-agent pass)
  - 2026-10-20 v7-rebaseline: DuckDB 2.0.0-dev re-verification (0 drift, 3 exception-type corrections, 1 new finding — see §5.1a)
---

# Bodai OTel Substrate — v7

**Status:** Draft v7; supersedes v6 (`.archive/2026-10-19-bodai-substrate-otel-v6.md`), v5, v4, v3, v2, and v1.
**Date:** 2026-10-19
**Stage:** Sub-spec A; companion to `2026-10-19-bodai-event-sourced-otel-architecture.md` (sub-spec B).
**Repos in scope:** `oneiric` (substrate), `akosha` (receiver, DLQ, heartbeat watcher, canary, retention sweep), `mcp-common` (bridge release).

---

## 1. Why this exists

v1 had a substrate-architecture mistake (substrate DDL in akosha; ADR 017 violated). v2 fixed the architecture root but the 5-agent v2 review found ~12 P0s that weren't about architecture — they were about *implementation completeness* (DLQ silent-failure paths, heartbeat source, yoyo conventions, dep placement, cross-spec scope, port collision consumer enumeration, etc.). v3 fixed those.

The 2-agent v3 final review (critical-audit-specialist proper + observability-incident-lead random) found **7 P0 + 6 P1 + 5 P2** that v3 hadn't addressed. v4 closed the 7 P0s and 3 concrete-bug P1s (Prometheus metric misuse, PR-A6 namespace constant, feature-flag naming consistency).

The 2-agent v4 review (same ensemble) found **4 P0 + 8 P1 + 2 P2** — note that v4 *introduced* 4 of these via its own §8.2/§11.3 additions. v5 closed the 4 P0s and 4 P1s whose fix is mechanical spec-completion.

The 3-agent v5 review (critical-audit proper + observability-incident-lead random + **oneiric-specialist proper, with live DuckDB 1.5.6 verification**) found **7 P0 + 5 P1 + 3 P2**. v6 closes all 7 P0s (4 of which the oneiric-reviewer caught by running the DDL live against DuckDB 1.5.6 — partial-index `WHERE` clauses, ALTER ADD CONSTRAINT, COPY filename parameterization, ALTER ADD COLUMN with `NOT NULL DEFAULT` were all bugs the spec author never verified at runtime). v6 also closes the 2 P1s that are mechanical fixes (phase="copy" dead-code documentation, §11.4 comment vs §13.6 placement), plus 1 P2 (typo). 3 P1s and 1 P2 remain deferred to writing-plans.

v6 is **architecturally stable** (the substrate-in-oneiric + receiver-in-akosha split is unchanged from v5). What changes from v5: every DDL string is verified against DuckDB 1.5.6 (4 verified audit entries in §5.1a); the sweep body uses `result.rowcount` (verified cursor contract) and inline-paths the COPY target (with regex-validated `archival_target`); §11.3 canary now has liveness — try/except with backoff + `bridge_failed_total`; §11.1.7 typo fixed.

The 4th-round review (akosha-specialist) found **3 P1 + 4 P2 + 1 P3** — every one of which is a spec-vs-akosha-codebase alignment bug no other lens (DB execution, runbook, contract-gaps) could catch. The akosha-reviewer did a direct read of `akosha/cli.py`, `akosha/storage/path_resolver.py`, `akosha/mcp/server.py:282-305`, `server.py:397-420`, and `server.py:951-1101` — and surfaced four structural issues: (1) `ARCHIVAL_TARGET_RE` regex excludes every default akosha storage path; (2) `set_shared_otel_receiver` is referenced as if it exists but is NEW code from PR-A0b; (3) the §6 lifespan snippet uses Starlette shape but akosha's actual is `@asynccontextmanager`; (4) `HealthFeedState("name")` notation is wrong — kwarg-only dataclass. v7 closes all 3 P1s and all 4 P2s.

### 1.1 DuckDB re-baseline (2026-10-20)

The v6 DDL verification footer cited `duckdb==1.5.6`, "per `mahavishnu/uv.lock`". **That attribution was wrong, and so was the version.** The substrate's DuckDB comes from *oneiric* (ADR 017), and `oneiric/uv.lock:1270` pins `duckdb==2.0.0.dev2610192346`. The v6 footer was a false attestation: it named a version nobody verified against, citing a lockfile that does not govern the substrate.

Re-verified empirically against `2.0.0.dev2610192346` via `scripts/verify_otel_ddl.py` (12 assertions, all §5.1a claims):

- **Zero design drift.** All four v6 negative claims still hold, so every DDL decision v6 made — inline `UNIQUE CONSTRAINT`, no index `WHERE`, inline `received_at_unix_nano`, inline `COPY` target — remains necessary. Nothing in §5.1 changed shape.
- **Three exception-type corrections.** `ALTER ADD CONSTRAINT` and `ALTER ADD COLUMN NOT NULL DEFAULT` now raise `DependencyException` (not `NotImplementedException`/`Parser Error`); `COPY … TO ?` raises `InvalidInputException` (not `INTERNAL Error`). The *conclusions* are unchanged; only the cited diagnostic text was wrong. Implementation must not string-match on these.
- **One new finding (§5.1a).** DuckDB does not store the declared constraint name `uq_span_identity`; it normalises to `spans_substrate_trace_id_span_id_key`. The name is a declaration label for readers. **Nothing may look the constraint up by name.**

The re-baseline decision is *oneiric's* to own: this spec now targets whatever `oneiric/uv.lock` pins, and the footer names that version by reading the lock rather than by hardcoding it.

## 2. Scope

In scope (the 8 items, refined from v1/v2):

1. **`spans_substrate` table in oneiric** — `DuckdbHotStore.initialize()` adds the table alongside `conversations`; substrate contract pins both DDL and table-name class attribute.
2. **Akkosha's `OTLPReceiver`** — gRPC `:4317` + HTTP `:4318` lifecycles; lifespan-ordered after `HotStore.initialize()`.
3. **yoyo migrations in akosha** managing only **two** tiny tables: `_akosha_otel_receiver_state` (version-stamp) and `_dlq_rows` (per-row quarantine). Sibling `.rollback.sql` per migration.
4. **Per-row validation** before batch INSERT. Bad rows quarantined; per-row metric emitted. **`_dlq_insert` itself is wrapped in try/except** (the DLQ has its own failure mode).
5. **Partial-batch INSERT semantics** — `ON CONFLICT (trace_id, span_id) DO NOTHING RETURNING span_id` (the dedup constraint spans both axes; cross-producer trace_id collisions are caught).
6. **OTel attribute normalization** (dotted → underscore) — OTel exporter handles this; **server-side normalizer in OTLPReceiver** re-checks (older SDK / non-standard producers fall back through the normalizer).
7. **`service.namespace` migration** (`mcp-ecosystem` → dual-label → `bodai`) with explicit consumer-file-path enumeration + per-repo owners + CI gate.
8. **Heartbeat-watcher known-server roster** — separate `known_mcp_servers` field; empty roster is itself a P0 condition.

## 3. Non-goals

- Not changing oneiric's vector substrate beyond `initialize()` additions.
- Not making `run_fitness_analysis` read the new substrate.
- Not introducing gRPC receivers in oneiric (HTTP-only at `:4318`).
- Not adopting SaaS.
- Not adding claud/qwen collector pipeline mirroring in v3. **Reclassified as non-goal for v3.**
- Not a Crackerjack or bifrost-mcp change.

---

## 4. Architecture

```
                    ┌───────────────────────────────────────────┐
   producers        │  oneiric.adapters.vector.duckdb_hot_store │
   (every `*-mcp`)──▶│  initialize()                             │
   gRPC + HTTP       │  ├── conversations  (existing)            │
                    │  └── spans_substrate (NEW, added here)    │
                    └───────────────────────────────────────────┘
                                       │   ▲
                                       │   │ read-side query (substrate-managed)
                                       ▼   │
                    ┌───────────────────────────────────────────┐
                    │  akosha/observability/otlp_receiver.py    │
                    │  ├── per-row pre_validate (try/except)   │
                    │  ├── _dlq_insert (try/except, recovery)   │
                    │  ├── INSERT ... ON CONFLICT               │
                    │  │     (trace_id, span_id) DO NOTHING     │
                    │  │     RETURNING span_id                  │
                    │  ├── Prometheus counters emitted          │
                    │  │     (on the :8682 /metrics route)      │
                    └───────────────────────────────────────────┘
                                       │
                                       ▼
                    ┌───────────────────────────────────────────┐
                    │  akosha/observability/heartbeat_watcher.py│
                    │  reads known_mcp_servers│
                    │  for per-service name roster              │
                    │  emits P0-A after 2 consecutive 60s absences│
                    └───────────────────────────────────────────┘
```

The substrate lives in oneiric. Akkosha's receiver writes through the substrate abstraction. Lifecycle order: `HotStore.initialize()` → `OTLPReceiver.start()` → MCP tool registration.

---

## 5. Substrate placement — oneiric

### 5.1 `spans_substrate` DDL

Added to `oneiric/adapters/vector/duckdb_hot_store.py:130-185` (the `initialize()` method that today creates `conversations`). Substrate-managed; every Bodai component inherits the access path via the substrate.

```sql
-- spans_substrate DDL. Re-verified against the DuckDB that oneiric's
-- uv.lock pins (2.0.0.dev2610192346 as of 2026-10-20) via
-- scripts/verify_otel_ddl.py. Audit trail in §5.1a below.

CREATE TABLE IF NOT EXISTS spans_substrate (
    span_id                 TEXT PRIMARY KEY,
    trace_id                TEXT,
    parent_span_id          TEXT,
    service_name            TEXT         NOT NULL,
    service_namespace       TEXT         NOT NULL,
    deployment_environment  TEXT,
    telemetry_source        TEXT,
    telemetry_source_type   TEXT,
    span_name               TEXT         NOT NULL,
    start_time_unix_nano    BIGINT       NOT NULL,
    end_time_unix_nano      BIGINT,
    received_at_unix_nano   BIGINT       NOT NULL DEFAULT (CAST(epoch_ms(now()) * 1e6 AS BIGINT)),  -- v6: inline; ALTER ADD COLUMN with NOT NULL DEFAULT is unsupported by DuckDB (2.0.0-dev: DependencyException)
    duration_ms             REAL,
    outcome                 TEXT,                              -- success | error | unset
    selector                TEXT,                              -- routing-decision side
    task_class              TEXT,                              -- routing-decision side
    latency_ms              REAL,
    gen_ai_provider_name    TEXT,
    gen_ai_request_model    TEXT,
    gen_ai_response_model   TEXT,
    gen_ai_usage_input_tokens INTEGER,
    gen_ai_usage_output_tokens INTEGER,
    gen_ai_usage_cost       NUMERIC(10, 6),
    status_code             TEXT,                              -- OTel StatusCode enum
    status_message          TEXT,
    attributes              JSON         NOT NULL,
    events                  JSON,
    resource                JSON         NOT NULL,
    has_gen_ai_attrs        BOOLEAN      NOT NULL DEFAULT FALSE,
    has_dispatch_attrs      BOOLEAN      NOT NULL DEFAULT FALSE,
    inserted_at             TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- v6: composite uniqueness INLINE in CREATE TABLE (DuckDB ALTER TABLE
    -- ADD CONSTRAINT UNIQUE is unsupported — 2.0.0-dev: DependencyException;
    -- UNIQUE INDEX is insufficient because ON CONFLICT (trace_id, span_id)
    -- only fires on PRIMARY KEY or UNIQUE CONSTRAINT targets — UNIQUE INDEX
    -- leaves it as Binder Error. v3/v4/v5 had this wrong in different ways.).
    -- NB: DuckDB does NOT store the declared name `uq_span_identity`; it
    -- normalises to `spans_substrate_trace_id_span_id_key`. This label is for
    -- readers — never look the constraint up by name (§5.1a).
    --
    -- DEFECT FOUND 2026-10-23 (PR-A3 implementation): this constraint is
    -- UNREACHABLE, and the DDL is shipped as-is anyway. `span_id` above is
    -- PRIMARY KEY — strictly NARROWER than this UNIQUE over the pair. Every
    -- row colliding on (trace_id, span_id) has therefore already collided on
    -- span_id, so the PK always fires first and this constraint can never be
    -- the one that rejects anything.
    --
    -- Consequence: the spec's prescribed `ON CONFLICT (trace_id, span_id)`
    -- names only this constraint, so a span_id collision falls through to
    -- the PK and raises ConstraintException on the hot ingest path — in
    -- exactly the case the composite key exists to handle (two producers
    -- reusing a span_id under different trace_ids, e.g. a producer that
    -- restarted its trace).
    --
    -- Fix applied in PR-A3: use UNTARGETED `ON CONFLICT DO NOTHING`, which
    -- honours every constraint. The DDL is deliberately left unchanged —
    -- dropping the PK would weaken span_id lookups for the read path, and the
    -- untargeted clause already achieves the stated intent. NOT NULL
    -- violations are unaffected and still raise, so the table constraint
    -- remains a backstop for rows validation misses.
    --
    -- Docs: docs/decisions/2026-10-23-otel-substrate-spec-corrections.md §2
    CONSTRAINT uq_span_identity UNIQUE (trace_id, span_id)
);

-- Hot-path projection indexes. v6: all four indexes order by
-- `received_at_unix_nano DESC` (the server-side receive-time column; see
-- §8.2 cardinal rule). DuckDB does NOT support `WHERE` clauses on
-- CREATE INDEX (NotImplementedException on both 1.5.6 and 2.0.0-dev); the
-- `outcome IN ('success','error')`
-- predicate that v5 had here is gone — push the predicate into the read-side
-- SELECT (the sub-spec B §5.6 FSM projection already qualifies with
-- `WHERE outcome IN (...)`). Performance impact is negligible (the
-- cardinality of `outcome` is 3 — the read-side filter is cheap).
CREATE INDEX IF NOT EXISTS idx_spans_selector_task_class_outcome
    ON spans_substrate(selector, task_class, outcome, received_at_unix_nano DESC);
CREATE INDEX IF NOT EXISTS idx_spans_service_name_recent
    ON spans_substrate(service_name, received_at_unix_nano DESC);
CREATE INDEX IF NOT EXISTS idx_spans_source_type_recent
    ON spans_substrate(telemetry_source_type, received_at_unix_nano DESC);
CREATE INDEX IF NOT EXISTS idx_spans_received_at_recent
    ON spans_substrate(received_at_unix_nano DESC);
```

The DDL ships in `PR-0a` (oneiric) — bumps oneiric's minor version. Same PR exposes `spans_substrate_table` and `table_exists()`:

```python
# oneiric/adapters/vector/duckdb_hot_store.py (additions to DuckdbHotStore class)
class DuckdbHotStore:
    spans_substrate_table: str = "spans_substrate"
    conversations_table:   str = "conversations"

    async def initialize(self) -> None:
        # existing conversations DDL stays
        # NEW: spans_substrate DDL (above — re-verified 2026-10-20 against
        # the duckdb build oneiric/uv.lock pins; see §5.1a)
        # UNIQUE CONSTRAINT uq_span_identity is INLINE in CREATE TABLE;
        # no separate ALTER step required. DuckDB stores it as
        # spans_substrate_trace_id_span_id_key.
        ...

    async def table_exists(self, name: str) -> bool:
        """Used by OTLPReceiver.start() to fail-loud if substrate is missing."""
        row = await self._conn.execute(
            "SELECT 1 FROM duckdb_tables WHERE table_name = ?", [name]
        ).fetchone()
        return row is not None
```

### 5.1a DDL verification trail (re-baselined 2026-10-20)

**Every claim below is asserted by `scripts/verify_otel_ddl.py`, run against the DuckDB that `oneiric/uv.lock` pins. Re-run it after any `oneiric` dependency change and update this section from the output — do not hand-edit the version string to match a new pin.**

```bash
# Run from the substrate's own venv so `duckdb` resolves to oneiric's build.
/Users/les/Projects/oneiric/.venv/bin/python scripts/verify_otel_ddl.py
```

**Current result:** `duckdb==2.0.0.dev2610192346`, **12 passed, 0 drift, 0 failed** (2026-10-20).

**Run it against BOTH builds the fleet carries (added 2026-10-20).** The substrate DDL is
owned by oneiric, but the `duckdb` *library* is resolved by whichever process opens the
file — and the receiver runs in akosha, whose lock pins **1.5.6**, not 2.0.0-dev:

```
/Users/les/Projects/oneiric/.venv/bin/python scripts/verify_otel_ddl.py   # 2.0.0-dev
/Users/les/Projects/akosha/.venv/bin/python  scripts/verify_otel_ddl.py  # 1.5.6
```

This is not pedantry: on 1.5.6, `DELETE ... .rowcount` returns **-1** where 2.0.0-dev returns
the affected count. §8.2's sweep reads `deleted = result.rowcount`, which is why the v7 plan
now counts before/after instead. "Whichever DuckDB oneiric pins" is the wrong question —
the right one is "whichever DuckDB the consuming process resolves."

The script distinguishes two failure modes, which matters: a **FAIL** means a positive claim broke (the DDL no longer does what §5.1 says it does), while **DRIFT** means a negative claim stopped holding (a statement the spec relies on being *unsupported* has become supported, so the design that works around it needs revisiting). Zero of both means §5.1 is correct for this version.

The v6 footer attributed the pin to `mahavishnu/uv.lock`. That was wrong — ADR 017 makes *oneiric* the substrate, so oneiric's lock governs. Corrected here.

**Audit pins:**
- `CREATE TABLE … (…, received_at_unix_nano BIGINT NOT NULL DEFAULT (CAST(epoch_ms(now()) * 1e6 AS BIGINT)))` resolves, and the DEFAULT actually fires at INSERT ✓
- `CONSTRAINT uq_span_identity UNIQUE (trace_id, span_id)` (inline in CREATE TABLE) is present as a `UNIQUE` constraint over those two columns ✓ — **asserted on `(constraint_type, constraint_column_names)`, never on the name**: DuckDB normalises the declared `uq_span_identity` to `spans_substrate_trace_id_span_id_key` (§1.1). Any code that queries `duckdb_constraints()` by `uq_span_identity` will find nothing.
- All four `CREATE INDEX … ON spans_substrate(…, received_at_unix_nano DESC)` resolve ✓
- No `WHERE` clause on any `CREATE INDEX` — still unsupported, `NotImplementedException` ✓
- `INSERT INTO spans_substrate (…) ON CONFLICT (trace_id, span_id) DO NOTHING` resolves against the inline CONSTRAINT, and a replayed `(trace_id, span_id)` is a genuine no-op (row count unchanged) ✓ — **AMENDED 2026-10-23 (PR-A3).** This pin is true but tests the wrong thing. It replays a *composite* collision, which the inline CONSTRAINT does catch, so it passes while the span_id-only collision the composite key exists to survive raises `ConstraintException` (see the DEFECT note in §5.1). The shipped statement is UNTARGETED `ON CONFLICT DO NOTHING`, which honours the PK and the composite constraint alike; verified on the pinned 2.0.0.dev build that it no-ops a span_id-only collision and still raises on NOT NULL.
- `result.rowcount` (DuckDB Python cursor contract) returns the affected-row count for DML ✓ — **version-sensitive**: this returned `-1` on 1.5.6. The §8.2 sweep body's rowcount check is only correct because oneiric currently pins 2.0.0-dev. If oneiric ever downgrades, the sweep must not trust `rowcount`.
- `COPY (SELECT … FROM spans_substrate WHERE received_at_unix_nano < ?)` to an inline path writes a real file ✓; `TO ?` (parameterized) is still rejected — now `InvalidInputException`, previously `INTERNAL Error: Unsupported parameter type for filename`. §8.2 swap-inlines the target path with strict-path validation (see §8.2 v6 change).
```

### 5.2 Substrate-access path

Akkosha's `HotStore` extends `oneiric.adapters.vector.duckdb_hot_store.DuckdbHotStore`. The receiver calls:

```python
# akosha/storage/hot_store.py
class HotStore(DuckdbHotStore):
    async def insert_spans_substrate(
        self, rows: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Returns (inserted_count, deduped_count)."""
        # INSERT INTO spans_substrate (...) VALUES (...) ...
        # ON CONFLICT (trace_id, span_id) DO NOTHING RETURNING span_id
        ...
```

No `akosha/migrations/versions/...` writes against `spans_substrate`. ADR 017's canonical-home claim holds.

**AMENDED 2026-10-23 (PR-A3 implementation).** The sketch above shows the
writers *declared on akosha's subclass*. They are shipped on
`DuckdbHotStore` in oneiric instead, and akosha's `HotStore` inherits
them unchanged — so the receiver's call sites are unaffected.

Two reasons. `akosha/storage/hot_store.py` is capped at 500 LOC by
`tests/unit/test_hot_store_subclass.py`, precisely so it stays a thin
subclass; declaring the writers there pushed it to 580, and the right
response to a guard like that is to fix the layering rather than raise the
ceiling. And ADR 017 puts `spans_substrate` ownership in oneiric, so the
write path to it is substrate access rather than akosha domain logic —
and placing the writers beside the DDL and indexes they target stops a
column added in one repo and named in another from silently diverging.

`insert_dlq_rows` moved for the same reason.

### 5.3 Substrate asymmetry — explicit

Two tables in this design are **`akosha-local`, not substrate-managed**:

| Table | Why akosha-local |
|---|---|
| `_akosha_otel_receiver_state` | Component-internal metadata; only Akosha reads/writes; not a substrate concept. |
| `_dlq_rows` | Per-row quarantine; substrate-managed data already rejected the row; DLQ is component-local dead-letter storage. |

Documented as deliberate asymmetry. ADR 017's "substrate is the single source of truth for telemetry data" holds for `spans_substrate` and `conversations` only.

---

## 6. `OTLPReceiver` — implementation interface

The receiver lives at `akosha/observability/otlp_receiver.py`. Function signatures, error types, and constants are pinned here so the engineer can start typing without further design:

```python
# CORRECTED 2026-10-23 (PR-A3 implementation). The claim below that
# LifecycleError lives in `mcp_common.errors` is FALSE: there is no such
# module. mcp_common's submodules are auth, config, health, profiles,
# traces, … and none is `errors`. The real class is in oneiric, and
# subclasses RuntimeError. No `mcp-common>=0.40` pin is needed.
#
# See docs/decisions/2026-10-23-otel-substrate-spec-corrections.md
from oneiric.core.lifecycle import LifecycleError

class ReceiverError(Exception):                       ...
class BatchRejected(ReceiverError):                  ...    # whole-batch abort
class RowValidationError(ReceiverError):             ...    # per-row quarantine
class DLQWriteError(ReceiverError):                  ...    # the DLQ itself failed
class PreValidateException(ReceiverError):           ...    # validator itself raised

@dataclass
class BatchResult:
    ok:        int   # inserted_count
    deduped:   int   # RETURNING < supplied, exclusive of ok
    rejected:  int   # per-row validation failed; in DLQ
    dlq_failed: int  # DLQ itself failed; rows logged to stderr
    errored:   int   # whole-batch abort
```

**As implemented (PR-A3), the exception hierarchy above is simplified.**
`RowValidationError` is a frozen dataclass returned by `pre_validate`, not
an exception — it doubles as a metric-label dedup key, which an exception
would not survive. There are no `BatchRejected` / `DLQWriteError` /
`PreValidateException` classes: a DLQ failure is caught and counted rather
than re-raised (§15), and a validator failure is a return value. The class
count above describes intent, not the shipped surface.

```python
class OTLPReceiver:
    MAX_BATCH_SIZE: int          = 512
    MAX_RETRIES:    int          = 3
    BACKOFF_BASE_SECONDS: float  = 1.0
    BACKOFF_MAX_SECONDS:   float = 8.0
    QUEUE_MAX_DEPTH:    int      = 2048
    PROMETHEUS_PORT:     int      = 9464
    # v7 addition (2026-10-21): bind ports were literals in start()'s docstring,
    # leaving no seam. §13.1 requires them to be operator-settable — the substrate
    # owns canonical :4317/:4318 and Alloy moves to :14317/:14318, and any later
    # port change must not be a source edit in a receiver with live producers.
    GRPC_PORT:         int      = 4317
    HTTP_PORT:         int      = 4318

    async def start(self) -> None:
        """Lifespan-invoked. Asserts HotStore.spans_substrate_table exists
        (LifecycleError if absent), binds GRPC_PORT (gRPC) + HTTP_PORT (HTTP),
        starts PROMETHEUS_PORT, increments receiver_started_total."""

    async def stop(self) -> None:
        """Drains in-flight batches, closes listeners."""

    async def _handle_batch(self, batch: ExportTraceServiceRequest) -> ExportTraceServiceResponse:
        """Per §6.1 below."""
```

**Lifespan order — PR-A3 initial state** (this is what lands in PR-A3 — the canary_metrics_task is NOT yet wired because that lives in PR-A4):

The snippet mirrors akosha's actual lifespan at `akosha/mcp/server.py:397-420`: a FastMCP-blessed `@asynccontextmanager` coroutine yielding a `dict[str, Any]` context, parameter named `server`. v6 used Starlette's bare-yield shape (no `@asynccontextmanager`, parameter `app`), which would not compile against the existing lifespan decoration. v7 corrects this.

```python
# akosha/mcp/server.py — PR-A3 lifespan snippet (matches the existing shape)
@asynccontextmanager
async def lifespan(server: Any) -> AsyncGenerator[dict[str, Any], None]:
    # 0. v7: pin stop_event at lifespan scope. Passed to retention_sweep
    #    and canary_metrics_bridge so the same event shuts down both tasks
    #    cleanly via stop_event.set() rather than relying on Task.cancel()
    #    alone (matches server.py:951 lifespan teardown pattern).
    stop_event = asyncio.Event()
    hot_store = HotStore(...)
    await hot_store.initialize()                              # 1. substrate tables exist
    receiver = OTLPReceiver(hot_store=hot_store)
    await receiver.start()                                    # 2. bind listeners, fail-loud if substrate missing
    # 3. publish singletons. PR-A0b introduces `set_shared_otel_receiver`
    #    as a 1:1 mirror of `set_shared_hot_store` at server.py:282-294 —
    #    new code, not in main as of v7. PR-A0b also extends
    #    `clear_shared_services()` to clear the new `_shared_otel_receiver`
    #    module global alongside the existing two; otherwise test isolation
    #    regresses and shutdown leaks the prior singleton. Regression test in
    #    PR-A0b: `create_app()` twice → `get_shared_otel_receiver() is None`.
    set_shared_hot_store(hot_store); set_shared_otel_receiver(receiver)
    # 4. tools see active receiver
    await _apply_tool_profile(server, ...)
    # PR-A3: two new lifespan tasks alongside the receiver. Both run in
    # parallel with the MCP server; cancellation order is reverse on shutdown
    # so a canary cannot write into a stopped substrate.
    # NB: `run_canary_emitter` ships as a stub at PR-A3 — emits no-op until PR-A4
    # swaps the body. The stub exists so PR-A3's lifespan compiles and §6 lifespan
    # task ordering is correct; between PR-A3 and PR-A4, canary writes succeed
    # silently (no-op), and the `sweep_retention_late` alert correctly does NOT fire
    # because sweep_first_started_unix_nano == 0 (operator runbook §11.1.6 step 4).
    canary_task = asyncio.create_task(
        receiver.run_canary_emitter(), name="receiver_canary_stub_at_PR_A3"
    )
    retention_task = asyncio.create_task(
        receiver.run_retention_sweep(stop_event), name="spans_retention_sweep"
    )
    yield {"server": server, "hot_store": hot_store, "receiver": receiver}
    # 5. reverse-order shutdown. v7: stop_event.set() BEFORE the gather
    #    so the `await stop_event.wait(...)` inside the bridge body wakes
    #    BEFORE Task.cancel() propagates, eliminating the cancel-vs-wait race.
    stop_event.set()
    retention_task.cancel(); canary_task.cancel()
    await asyncio.gather(canary_task, retention_task, return_exceptions=True)
    await receiver.stop()
```

**Lifespan order — post-PR-A4 final state** (PR-A4 adds the bridge task to the lifespan):

```python
# PR-A4 diff against the PR-A3 lifespan: only the canary_metrics_task addition
# (between canary_task and the yield).
canary_task = asyncio.create_task(
    receiver.run_canary_emitter(), name="receiver_canary"   # PR-A4 swaps the stub body
)
retention_task = asyncio.create_task(
    receiver.run_retention_sweep(stop_event), name="spans_retention_sweep"
)
canary_metrics_task = asyncio.create_task(
    _canary_metrics_bridge(stop_event, receiver), name="canary_metrics_bridge"
)  # PR-A4; bridge contract per §11.3. NB: stop_event is now an explicit
   # positional arg, fixing the v6 "undefined stop_event" free-variable bug.
yield {"server": server, "hot_store": hot_store, "receiver": receiver}
stop_event.set()
canary_metrics_task.cancel()
retention_task.cancel()
canary_task.cancel()
await asyncio.gather(canary_metrics_task, retention_task, canary_task,
                    return_exceptions=True)
await receiver.stop()
```

**`run_canary_emitter` contract**:

```python
# PR-A3: stub (no-op). PR-A4: real impl that emits a canary span per the §11.3 spec.
# The stub is required so the PR-A3 lifespan compiles cleanly against the §6
# snippet above; swapping the body at PR-A4 is a one-file diff.
async def run_canary_emitter(self, stop_event: asyncio.Event) -> None:
    # v7 — `stop_event` is now an explicit positional arg (was free variable
    # in v6). Stub body: real impl in PR-A4 reads CANARY_EMIT_INTERVAL_SECONDS = 30.
    return
```

A `LifecycleError("spans_substrate_missing")` (from `mcp_common.errors`) fires if `receiver.start()` is called before the substrate table exists. **Fail-loud, never silent boot.**

### 6.1 Per-row validation + DLQ

Each row is validated before INSERT. A bad row goes to `_dlq_rows`:

```python
def pre_validate(self, span: dict) -> RowValidationError | None:
    if not span.get("service_name"):
        return RowValidationError(field="service_name", reason="not_null")
    if span.get("status_code") not in {"STATUS_CODE_UNSET", "STATUS_CODE_OK", "STATUS_CODE_ERROR"}:
        return RowValidationError(field="status_code", reason="enum")
    # ... etc.
```

**`pre_validate` itself is wrapped in try/except** (synthetic error on validator raise):

```python
for span in batch.spans:
    try:
        err = self.pre_validate(span)
    except Exception as exc:
        err = RowValidationError(reason="validator_threw", detail=repr(exc))
        self._metric_row_rejected.inc(reason="validator_threw")
    if err:
        dlq.append((err, span)); rejected += 1
    else:
        clean.append(span)
```

### 6.2 DLQ error recovery (NEW: the DLQ is wrapped)

The DLQ itself can fail (`_dlq_rows` missing post-PR-A2 rollback, DuckDB locked, disk full). **`_dlq_insert` is wrapped**:

```python
try:
    await self._dlq_insert(dlq)
except Exception as exc:
    dlq_failed = len(dlq)
    for err, span in dlq:
        logger.error("dlq_write_failed", reason=err.reason, span_id=span.get("span_id"))
    # v4 — `.inc(amount=N)` is the prometheus_client convention.
    # v3 had `.inc(reason="exception", n=dlq_failed)` which silently
    # passes `n=` as an unlabeled kwarg (raises TypeError on recent
    # prometheus_client) or increments by 1 — operators can't tell
    # "1 batch with 50 rejected rows" from "50 batches with 1 row each."
    self._metric_dlq_insert_failed.labels(reason="exception").inc(amount=dlq_failed)
    # The still-clean rows continue to the batch INSERT — never lose a good row.
```

Per-batch metrics, full enum:

```python
# single counter, multi-label
# `inc(amount=N)` is the convention: count is the increment, NOT a label.
batch_inserted{outcome="ok|dedup|partial|err|validation_failed|dlq_write_failed"}
```

| Label | When |
|---|---|
| `ok` | All rows inserted, `RETURNING` == supplied |
| `dedup` | All rows matched existing `(trace_id, span_id)` |
| `partial` | Mixed: some new, some dup |
| `err` | Whole-batch abort; OTLP `partial_success` returned |
| `validation_failed` | At least one row quarantined to DLQ successfully |
| `dlq_write_failed` | At least one row's DLQ write itself failed; logged to stderr + metric |

Plus `batch_size` histogram (log scale), `receiver_started_total` counter, `row_rejected{reason,field}` per-quarantine event, `dlq_insert_failed{reason}` per-DLQ-failure event.

### 6.3 yoyo migrations — sibling `.rollback.sql`

**`akosha/migrations/versions/0001.akosha-otel-receiver-state.sql`:**

```sql
-- depends: -

CREATE TABLE IF NOT EXISTS _akosha_otel_receiver_state (
    component     TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    last_applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

**`akosha/migrations/versions/0001.akosha-otel-receiver-state.rollback.sql`:**

```sql
DROP TABLE IF EXISTS _akosha_otel_receiver_state;
```

**`akosha/migrations/versions/0002.dlq-rows.sql`:**

```sql
-- depends: -

CREATE TABLE IF NOT EXISTS _dlq_rows (
    rejected_at  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reason       TEXT        NOT NULL,
    field        TEXT,
    row_json     JSON        NOT NULL,
    trace_id     TEXT,
    span_id      TEXT
);
CREATE INDEX IF NOT EXISTS idx_dlq_rows_recent ON _dlq_rows(rejected_at DESC);
```

**`akosha/migrations/versions/0002.dlq-rows.rollback.sql`:**

```sql
DROP TABLE IF EXISTS _dlq_rows;
```

yoyo file naming: `<id>.<name>.sql` + optional sibling `<id>.<name>.rollback.sql`. PR-A2 introduces both files in one commit. **Inline `-- rollback:` comments are NOT a thing in yoyo**; the rollback sibling is.

### 6.4 TOML — opentelemetry-proto moves to `[project.dependencies]`

```toml
# akosha/pyproject.toml
[project.dependencies]
# (existing entries ...)
"opentelemetry-proto" = ">=1.27"   # NEW — hard runtime dep; the substrate is the whole point
"opentelemetry-exporter-otlp-proto-grpc" = ">=1.27"  # NEW (used by OTLPReceiver)
# ... existing OTel packages at akosha/pyproject.toml:22-27
```

`opentelemetry-proto` is **runtime-required**. The previous PEP 735 group approach was wrong — PEP 735 groups never auto-install, so `LifecycleError("opentelemetry-proto-missing")` from §12 would fire on every fresh `uv sync`. Removing the install-discipline complexity entirely.

`[dependency-groups].otel-receiver` is removed in v3.

### 6.5 `tracing.py` namespace hygiene

`akosha/observability/tracing.py:62-68` currently hardcodes:

```python
"service.namespace": "akosha"
```

Update to source from the same `OTelSettings.service_namespace` the bridge release introduces. v3 only described the `settings.service_namespace` read but did not specify how `setup_telemetry()` gets the OTelSettings object — `setup_telemetry()` takes `(service_name: str, environment: str)` and has no `settings` parameter. v4 makes the contract explicit:

**Signature change required** (callers in `akosha/mcp/server.py` and any lifespan path):

```python
# akosha/observability/tracing.py — current
def setup_telemetry(service_name: str, environment: str) -> None: ...

# v4 — signature change
def setup_telemetry(
    service_name: str,
    environment: str,
    *,
    settings: OTelSettings | None = None,       # NEW — optional; default reads mcp-common OTelSettings
) -> None:
    namespace = (settings or OTelSettings()).service_namespace
    resource = Resource.create({
        "service.name": service_name,
        "service.namespace": namespace,
        "deployment.environment": environment,
    })
    ...
```

The call site at `akosha/mcp/server.py:466` (and any other callers) is updated to pass the live `OTelSettings`:

```python
setup_telemetry(service_name="akosha", environment=settings.deployment.environment, settings=settings)
```

PR-A0b (or whichever PR ships the bridge release) extends `setup_telemetry()`'s signature; existing call sites keep compiling because the new parameter is keyword-only with `None` default.

After this refresh, Akosha's outgoing spans carry the same namespace other `*-mcp` servers use, which means the §13.2 validator's "allowlisted for the fleet" set does NOT need an `akosha`-specific carve-out.

---

## 7. Receiver internals

Concrete signatures the engineer types against:

```python
# akosha/storage/hot_store.py (or co-located with the receiver if cleaner)
class HotStore(DuckdbHotStore):
    async def insert_spans_substrate(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Returns (inserted_count, deduped_count).

        Atomic batch INSERT. Implements:
          INSERT INTO spans_substrate (...) VALUES (...)
          ON CONFLICT (trace_id, span_id) DO NOTHING
          RETURNING span_id;

        Returns (inserted_count, deduped_count) where:
          inserted_count = rows where (trace_id, span_id) was new
          deduped_count  = rows where (trace_id, span_id) already existed
        """
```

Prometheus counters, on the **:8682 `/metrics` route** (v8 — the
`:9464` listener is not a thing; see the note below):
- `akosha_otlp_spans_received_total` (counter — spans accepted off the wire, before validation)
- `akosha_otlp_spans_inserted_total` (counter — rows written to `spans_substrate`)
- `akosha_otlp_spans_deduped_total` (counter — spans skipped because the span_id was already present)
- `akosha_otlp_spans_rejected_total{field}` (counter — quarantined to `_dlq_rows`, labelled by the field that failed)
- `akosha_otlp_dlq_inserts_total` (counter — rows written to `_dlq_rows`)
- `akosha_otlp_dlq_insert_failed_total` (counter — DLQ writes that raised; the evidence was lost)
- `akosha_otlp_http_body_undecodable_total` (counter — bodies that failed protobuf decode)
- `akosha_otlp_sweep_first_started_unix_nano` / `akosha_otlp_sweep_last_completed_unix_nano` (gauges)
- `akosha_otlp_sweep_duration_seconds` (histogram)
- `akosha_otlp_retention_sweep_failed_total{table}` (counter — labelled by table)
- `akosha_otlp_dlq_rows_deleted_total` (counter)
- `akosha_otlp_resource_rejected_total` / `akosha_otlp_resource_drift_alert_total` / `akosha_otlp_resource_drift_values` (PR-A6)
- `akosha_otlp_heartbeat_*` (PR-A5)

**Why not `:9464`.** `OTLPReceiver.PROMETHEUS_PORT = 9464` is a
class attribute that was never bound, and 9464 is Grafana Alloy's
`otelcol.exporter.prometheus` default endpoint — binding it would
collide the moment that exporter is given an `endpoint`. The receiver
has no business owning a second port when a metrics route is already
served for it on `:8682`. The constant is retained only as a
description of the original intent; it is dead code.

The gRPC servicer class is `opentelemetry.proto.collector.trace.v1.TraceServiceServicer` (the canonical OTel collector trace service). Subclass to override `Export`; route to `_handle_batch`.

### 7.1 Validation chain (full enumeration, no `...etc.`)

```python
REQUIRED_FIELDS = {
    "service_name",
    "service_namespace",   # v4 — was missing in v3; required because the
                            # substrate's `service_namespace TEXT NOT NULL`
                            # column is silent-corruption bait for
                            # pre_validate if this is not enforced
                            # (every selector-level projection groups by
                            # (selector, task_class, outcome, namespace)).
    "span_name",
    "start_time_unix_nano",
}
ENUM_FIELDS = {
    "status_code": {"STATUS_CODE_UNSET", "STATUS_CODE_OK", "STATUS_CODE_ERROR"},
}

def pre_validate(self, span: dict) -> RowValidationError | None:
    for f in REQUIRED_FIELDS:
        if not span.get(f):
            return RowValidationError(field=f, reason="not_null")
    for f, allowed in ENUM_FIELDS.items():
        v = span.get(f)
        if v is not None and v not in allowed:
            return RowValidationError(field=f, reason="enum")
    return None
```

That's the complete chain. Future fields added in this list (NOT to extend `...etc.` — that was v2's error).

---

## 8. Partial-batch INSERT semantics

**Idempotent retry:**

```sql
INSERT INTO spans_substrate (trace_id, span_id, ...) VALUES (?, ?, ...)
ON CONFLICT (trace_id, span_id) DO NOTHING
RETURNING span_id;
```

The dedup constraint spans **both** `trace_id` and `span_id`. v2's `ON CONFLICT (span_id)` alone was wrong — cross-producer `(same span_id, different trace_id)` pairs would silently drop spans (OTel scope violation). v3's composite UNIQUE INDEX `uq_span_identity (trace_id, span_id)` is added by PR-0a.

Per-batch outcome semantics:
- `dedup`: rowcount == 0, all matched existing identity → no retry needed.
- `partial`: rowcount < supplied, mixed → no retry needed.
- `err`: integrity error or similar (NOT NULL violation caught by per-row validation, so this only fires on `attributes` JSON malformedness) → retry per §6 retry constants → if still failing after `MAX_RETRIES`, drop to DLQ with `reason="max_retries_exceeded"`.

### 8.1 `_dlq_rows` retention

Avoid `SELECT * FROM _dlq_rows` performance degradation: PR-A4's lifespan wires a periodic retention sweep (24h retention; runs every 6h via the same lifespan task that the existing Akosha heat-mitigation uses, per `akosha/mcp/server.py` lifespan pattern):

```python
# PR-A4 — lifespan task
async def _dlq_retention_sweep():
    while not stop_event.is_set():
        await stop_event.wait(6 * 3600)
        await self._conn.execute(
            "DELETE FROM _dlq_rows WHERE rejected_at < now() - INTERVAL '24 hours'"
        )
```

### 8.2 `spans_substrate` retention & rollover (v4 addition; v5 hardening)

`spans_substrate` was unbounded in v3. At fleet-scale ingestion rates the DuckDB file grows ~30GB/month; without intervention it is a guaranteed disk-full pager at the 6-month mark. v4 ships a default retention policy + sweep mechanism + cold archival:

| Setting | Default | Pinned at | Operator-overridable? |
|---|---|---|---|
| `spans_substrate.retention_days` | `30` | PR-A3 ships default | yes (settings key) |
| `spans_substrate.retention_sweep_interval_hours` | `6` | PR-A3 | yes |
| `spans_substrate.archival_target` | `null` (no cold sink) | PR-A3 | yes (S3 URL OR filesystem path; format inferred from extension — `.parquet`/`.csv`/`.json` required; **v6 — `COPY ... TO ?` is rejected by DuckDB (2.0.0-dev: `InvalidInputException`); the sweep inlines the validated path instead. v7 — regex widened to cover the four storage roots akosha's `path_resolver.py:90-220` actually defaults to (XDG/macOS/Docker/log); reject else.**) |
| `spans_substrate.receiver_grpc_port` | `4317` | PR-A3 ships default | yes (settings key) — **v7 addition.** Canonical OTLP gRPC port; the substrate owns it (§13.1). Grafana Alloy moves to `:14317`. |
| `spans_substrate.receiver_http_port` | `4318` | PR-A3 ships default | yes (settings key) — **v7 addition.** Canonical OTLP HTTP port; the substrate owns it (§13.1). Grafana Alloy moves to `:14318`. |

**`archival_target` validation regex (v7 — widened to match akosha's `path_resolver.py` defaults):**

```python
# v7: covers the four real storage roots + S3 URLs. Compiled once at settings-load.
ARCHIVAL_TARGET_RE = re.compile(
    r"^(?:"
    r"s3://[a-z0-9][a-z0-9.\-]{1,62}/.*"
    r"|"
    r"(?:/var/log/akosha/|/var/lib/akosha/|/data/akosha/|/srv/akosha/"
    r"|/opt/akosha/|/Users/[A-Za-z0-9_.\- ]+/Library/Application Support/akosha/"
    r"|/Users/[A-Za-z0-9_.\- ]+/\.local/share/akosha/"
    r"|/home/[A-Za-z0-9_.\- ]+/\.local/share/akosha/"
    r")[\w./\-]*\.(?:parquet|csv|json)"
    r")$"
)
```

(empty `archival_target` → skipped; only non-empty values are validated.)

Coverage verified against `akosha/storage/path_resolver.py:90-220`:

| Path | Origin | regex match |
|---|---|---|
| `~/.local/share/akosha/archives/spans.parquet` | XDG_LINUX (`path_resolver.py:136`) | ✓ |
| `~/Library/Application Support/akosha/archives/spans.parquet` | XDG_MACOS (`path_resolver.py:129`) | ✓ |
| `/data/akosha/archives/spans.parquet` | DOCKER_DEFAULT (`path_resolver.py:90`) | ✓ |
| `/tmp/akosha/test/archives/spans.parquet` | TEST_ENV (`path_resolver.py:102`) | ✓ |
| `s3://cold-bucket/akosha-archive/spans.parquet` | S3 (Bifrost/tiered cold) | ✓ |

Operators outside these roots (e.g., `/home/custom/akosha/archives/...`) get the regex-rejected and operator-visible fail-loud at settings-load — the migration target is `akosha_config.warm_path`, not an arbitrary filesystem location.

**Cardinal rule (v5 pinning; closes v4 P0-3):** retention filters on **`received_at_unix_nano`** (server-populated, clock-trustworthy), not `start_time_unix_nano` (producer clock, drift-prone). v4 set up the column but missed this — the sweep body now uses the trustworthy column. `start_time_unix_nano` remains a metadata column for cross-correlation; it is NOT a retention driver. Decision logged in §15 ("retention driver: `received_at_unix_nano`, not `start_time_unix_nano`").

**Sweep mechanism (v5 hardened)** (PR-A3, lifespan task paralleling §8.1):

```python
# PR-A3 — lifespan task. v6: result.rowcount (DuckDB cursor contract);
# COPY path inlined with regex-validated archival_target; "never ran"
# disambiguation via sweep_first_started_unix_nano; promQL §11.3 bridge
# guarantee extended to this task too (try/except + retry counter).

# Path validation regex — compiled once. v7 widens to cover akosha's
# four storage roots (path_resolver.py:90-220); see §8.2 v7 docs.
ARCHIVAL_TARGET_RE = re.compile(
    r"^(?:"
    r"s3://[a-z0-9][a-z0-9.\-]{1,62}/.*"
    r"|"
    r"(?:/var/log/akosha/|/var/lib/akosha/|/data/akosha/|/srv/akosha/"
    r"|/opt/akosha/|/Users/[A-Za-z0-9_.\- ]+/Library/Application Support/akosha/"
    r"|/Users/[A-Za-z0-9_.\- ]+/\.local/share/akosha/"
    r"|/home/[A-Za-z0-9_.\- ]+/\.local/share/akosha/"
    r")[\w./\-]*\.(?:parquet|csv|json)"
    r")$"
)

# Idempotent — set once on the very first sweep iteration; never reset.
# Used by §11.1.6 runbook step 1 to disambiguate "sweep hasn't run on this
# pod yet" (==0) from "frozen on archival" (>0 with sweep_last_completed=0).
_sweep_first_started_unix_nano: int = 0

async def _spans_substrate_retention_sweep(stop_event: asyncio.Event):
    # v7 — stop_event is an explicit positional arg (was free variable in v6).
    # Set by the lifespan function (§6) before the gather teardown so all
    # sweep tasks receive the same shutdown signal.
    global _sweep_first_started_unix_nano
    while not stop_event.is_set():
        await stop_event.wait(settings.spans_substrate.retention_sweep_interval_hours * 3600)
        # Random jitter (interruptible: asyncio.sleep is cancelled by Task.cancel();
        # verification in §15 v6 decisions log).
        await asyncio.sleep(random.uniform(0, 60))
        sweep_started_unix_nano = time.time_ns()
        # Idempotent: only set on the very first sweep iteration across the
        # process lifetime. Subsequent iterations preserve the original timestamp
        # so operators can grep this gauge to confirm "this pod has swept at
        # least once."
        if _sweep_first_started_unix_nano == 0:
            _sweep_first_started_unix_nano = sweep_started_unix_nano
            self._metric_sweep_first_started_unix_nano.set(sweep_started_unix_nano)
        cutoff_ns = sweep_started_unix_nano - int(settings.spans_substrate.retention_days) * 86_400 * 1_000_000_000
        deleted_count = 0
        archival_succeeded = True
        try:
            if settings.spans_substrate.archival_target:
                # v6: COPY path is INLINE (not parameterized) — DuckDB rejects
                # `COPY … TO ?` (2.0.0-dev: InvalidInputException). Path is
                # regex-validated at settings-load; sweeping an unverified
                # path is unreachable.
                archival_path = settings.spans_substrate.archival_target
                assert ARCHIVAL_TARGET_RE.match(archival_path), \
                    f"archival_target {archival_path!r} failed validation; check §8.2 regex"
                copy_sql = (
                    f"COPY (SELECT * FROM spans_substrate "
                    f"WHERE received_at_unix_nano < {cutoff_ns}) "
                    f"TO '{archival_path}'"
                )
                try:
                    await self._conn.execute(copy_sql)
                    self._metric_archival_last_success_unix_nano.set(sweep_started_unix_nano)
                except Exception as exc:
                    archival_succeeded = False
                    self._metric_archival_failed.labels(reason=type(exc).__name__).inc()
                    logger.exception("archival_target_write_failed",
                                     target=archival_path)
            if archival_succeeded:
                # v6: result.rowcount (DuckDB Python cursor contract for DML).
                # v5 used result.fetchone()[0] which raises TypeError on DML
                # cursors (None[0]) — every sweep iteration permanently
                # incremented retention_sweep_failed{phase="delete"} as a
                # false alarm that eroded operator trust in the new alerts.
                result = await self._conn.execute(
                    "DELETE FROM spans_substrate WHERE received_at_unix_nano < ?",
                    [cutoff_ns],
                )
                deleted_count = result.rowcount
        except Exception as exc:
            # v6: ONE except labels — phase semantics are dead-code-only;
            # archival_target failures already increment archival_failed; COPY
            # errors are swallowed inside the inner try. The outer except
            # therefore catches only DELETE-phase failures (or rowcount failures
            # on the DML itself). phase="copy" never increments; documented in §15.
            self._metric_retention_sweep_failed.labels(
                phase="delete"  # v6: only ever fires for DELETE-phase failures
            ).inc()
            logger.exception("spans_retention_sweep_failed",
                             cutoff_unix_nano=cutoff_ns, deleted_count=deleted_count)
        finally:
            # v6: do NOT collapse "frozen on archival" into "never ran".
            # sweep_last_completed_unix_nano == 0 means the sweep's most recent
            # cycle did not complete cleanly; sweep_first_started_unix_nano == 0
            # means the sweep has never run. Operators disambiguate via runbook §11.1.6.
            self._metric_sweep_last_completed_unix_nano.set(
                sweep_started_unix_nano if archival_succeeded else 0
            )
            self._metric_sweep_duration_seconds.observe(
                (time.time_ns() - sweep_started_unix_nano) / 1e9
            )
        logger.info("spans_retention_sweep_complete",
                    cutoff_unix_nano=cutoff_ns,
                    deleted=deleted_count,
                    archival_succeeded=archival_succeeded)
```

**Sweep observability** (PR-A3 — these are the gauge/histogram/counter the spec was missing in v4):

- `telemetry.receiver.sweep_last_completed_unix_nano` (gauge; updated at end of every sweep; **0 means last cycle did not complete cleanly** — pair with `sweep_first_started_unix_nano` for runbook disambiguation)
- `telemetry.receiver.sweep_first_started_unix_nano` (gauge; **set once on the very first sweep, never reset** — v6 addition; **0 means "sweep has never run on this pod"**)
- `telemetry.receiver.sweep_duration_seconds` (histogram; sweep wall-clock)
- `telemetry.receiver.retention_sweep_failed{phase,reason}` (counter; **v6 — `phase` label is now `delete` only; `copy` failures route to `archival_failed` instead.** Both labels are still in the contract for back-compat readers, but `phase="copy"` never increments)
- `telemetry.receiver.archival_failed{reason}` (counter; only when `archival_target` is set)
- `telemetry.receiver.archival_last_success_unix_nano` (gauge; COPY success only)

**Alerts**:

```
ALERT sweep_retention_late
  for 12h
  expr: time() - telemetry_receiver_sweep_last_completed_unix_nano > 12 * 3600
  AND telemetry_receiver_sweep_first_started_unix_nano > 0
  annotations:
    summary: "spans_substrate retention sweep hasn't completed cleanly in 12h (and has run at least once)"
    runbook_url: "docs/specs/2026-10-19-bodai-substrate-otel-v6.md#82-spans_substrate-retention--rollover-v4-addition-v5-hardening"

ALERT archival_stale
  for 24h
  expr: time() - telemetry_receiver_archival_last_success_unix_nano > 24 * 3600
  annotations:
    summary: "archival_target hasn't succeeded in 24h"
    runbook_url: "docs/specs/2026-10-19-bodai-substrate-otel-v6.md#82-spans_substrate-retention--rollover-v4-addition-v5-hardening"
```

(The `phase="copy"` label is permanently dead — the inner COPY try/except routes to `archival_failed` instead, so the outer `retention_sweep_failed{phase}` can only ever be `delete`. Keep the `phase` label dimension for log/alert shape, document the asymmetry in §15.)

**Partitioning** (deferred; out of scope for v4). When `spans_substrate` exceeds ~10M rows, the receiving PR adds range partitioning on `start_time_unix_nano` (DuckDB supports `CREATE TABLE … PARTITIONED BY (…))`). The retention sweep above keeps index paths clean until that scale; the partition step is its own ADR.

**`received_at_unix_nano` clock-skew guard** (v4 addition; v5 completes the index migration):

Producer `start_time_unix_nano` is unreliable (paused-laptop drift, NTP outages; silently corrupts every index that orders by it). Every INSERT into `spans_substrate` carries a server-populated `received_at_unix_nano BIGINT NOT NULL DEFAULT (CAST(epoch_ms(now()) * 1e6 AS BIGINT))`. **Cardinal rule: every ordering column in v5 is `received_at_unix_nano`** — the cardinal-rule gap in v4 was that the original three hot-path indexes still ordered by `start_time_unix_nano`; v5 drops and recreates them on the trustworthy column. Cross-spec rewrite (§17) flips parent §5.6 projection SQL to use it.

DDL updates to §5.1 (v6): **all DDL is INLINE in the §5.1 CREATE TABLE.** v5 attempted to ADD COLUMN via ALTER TABLE; v6's DuckDB verification (per §5.1a audit trail) confirmed `ALTER TABLE … ADD COLUMN … NOT NULL DEFAULT (…)` is unsupported (1.5.6: `Parser Error: Adding columns with constraints not yet supported`; 2.0.0-dev: `DependencyException` — same conclusion, different diagnostic). The column is now part of the initial substrate DDL; the v5 DROP+CREATE index migration collapsed to "create the indexes inline, no DROP step needed." Fresh deployments (PR-0a's path) get the canonical schema; legacy deployments (a substrate pre-v6 with rows that lack `received_at_unix_nano`) need a one-off script — deferred to writing-plans.

**Cardinality alarm** (runbook §11.1.6, mentioned for context):

```
ALERT spans_substrate_row_count_high
  for 1h
  expr: COUNT(*) FROM spans_substrate > 0.9 * $spans_substrate_max_rows
  annotations:
    summary: "spans_substrate > 90% of `max_substrate_rows` setting"
    runbook_url: "docs/specs/2026-10-19-bodai-substrate-otel-v6.md#82-spans_substrate-retention--rollover-v4-addition-v5-hardening"
```

`spans_substrate_max_rows` defaults to `10_000_000`; sweeps in §8.2 keep us below unless ingestion rate climbs. §11.1.6 runbook: "check `spans_substrate` row count vs `sweep_last_completed_unix_nano` — if row count growing AND sweep is current, lower `retention_days` or raise `archival_target`. If sweep is stale, see §11.1.7."

---

## 9. OTel attribute normalization

The substrate receives **post-normalized** keys (`task.class` → `task_class`; the OTel Python exporter does this automatically when the SemConv environment is configured). Mapping (canonical Python-attr-form):

| Source (semconv) | Substrate form |
|---|---|
| `task.class` | `task_class` |
| `gen_ai.operation.name` | `gen_ai_operation_name` |
| `gen_ai.provider.name` | `gen_ai_provider_name` |
| `gen_ai.request.model` | `gen_ai_request_model` |
| `gen_ai.response.model` | `gen_ai_response_model` |
| `gen_ai.usage.input_tokens` | `gen_ai_usage_input_tokens` |
| `gen_ai.usage.output_tokens` | `gen_ai_usage_output_tokens` |
| `gen_ai.usage.cost` | `gen_ai_usage_cost` |
| `service.namespace` | `service_namespace` |
| `deployment.environment` | `deployment_environment` |
| `telemetry.source` | `telemetry_source` |
| `telemetry.source.type` | `telemetry_source_type` |
| `mcp.tool.name` | `mcp_tool_name` |

### 9.1 Server-side normalizer (v3 addition)

Older OTel SDKs and non-standard producers may emit dotted-attribute keys. The receiver re-checks at INSERT time:

```python
def normalize_attributes(self, span: dict) -> dict:
    """Map semconv dotted keys → underscore form, fallback to identity.

    v3 had `out.get(dotted_to_underscore(k), v)` — a read that discards
    its result. The function returned `{}` for every input. v4 assigns
    so the normalizer actually runs.
    """
    out = {}
    for k, v in span.get("attributes", {}).items():
        out[dotted_to_underscore(k)] = v      # v4 — assignment, not .get()
    return out
```

**Required unit test** (`tests/unit/test_normalize_attributes.py`):

```python
def test_normalize_attributes_assigns():
    span = {"attributes": {"task.class": "code_generation",
                           "gen_ai.usage.input_tokens": 42,
                           "weird.unknown.key": "kept-as-identity"}}
    out = receiver.normalize_attributes(span)
    assert out == {"task_class": "code_generation",
                   "gen_ai_usage_input_tokens": 42,
                   "weird_unknown_key": "kept-as-identity"}
```

(Pin via the `feedback-line-number-pin-tests.md` rule — assert against the dict, not against specific attribute-shape assumptions; `weird.unknown.key` is identity-mapped per `dotted_to_underscore`, change the test if `dotted_to_underscore` semantics change.)

This is a one-line dict comprehension in `_handle_batch`; doesn't change the column contract; explicitly defends against SDK version drift or non-conformant producers.

---

## 10. `service.namespace` migration

Two-release bridge: `mcp-ecosystem` → dual-label → `bodai`.

### 10.1 Enumerated downstream consumers (PR-A7 gate)

A `git grep` sweep across these paths must return zero for `service.namespace=mcp-ecosystem` before PR-A7 merges:

| Consumer type | File path pattern | Owner |
|---|---|---|
| Grafana dashboards | `mahavishnu/config/grafana/dashboards/*.json` (corrected 2026-10-21: the `dashboards/bodai/` subdirectory does not exist — the four dashboards sit directly in `dashboards/`, so a sweep over that path is vacuous) | platform-team |
| Mahavishnu alert rules | `mahavishnu/config/alerts/*.yaml` | platform-team |
| Akosha queries | `akosha/processing/fitness_analyzer.py:106-199` (after v3 §6.5 refresh) | akosha-team |
| mcp-common settings overrides | `mcp-common/**/settings*.py`, per-`*mcp` server settings.yaml | per-component owner |

### 10.2 CI gate

PR-A7 cannot merge until **a pre-merge CI step** lands `git grep "service.namespace=mcp-ecosystem"` returning zero across the listed paths. Step goes in `mahavishnu/.github/...` or equivalent (PR-A7 PR description cites the exact step).

### 10.3 Bridge + flip release

**Bridge** (`PR-A1`, mcp-common): emits `service.namespace` from OTelSettings (default `mcp-ecosystem`) plus `namespace.legacy_alias=bodai`.

**Flip** (`PR-A7`, mcp-common): default flip to `bodai` + drop `legacy_alias`. **Gated on §10.1 sweep + §10.2 CI gate.**

### 10.4 Bridge release merge-gate test

PR-A7's required-to-pass integration test (`tests/integration/test_service_namespace_bridge.py`):

```python
def test_dual_label_emitted_during_bridge():
    """During bridge release, every span must carry both:
       service.namespace='mcp-ecosystem' AND namespace.legacy_alias='bodai'.
    """
    ...

def test_consumer_sweep_returns_zero_pre_merge():
    """The git grep sweep returns zero — runs as part of PR-A7's CI gate."""
    ...
```

---

## 11. Heartbeat-watcher hooks

`akosha/observability/heartbeat_watcher.py`:

- **Source of truth for known servers:** a **separate, boot-populated** feed distinct from the per-cycle feed. The two are distinct feeds with distinct semantics. v7 notation correction: `HealthFeedState` is a kwarg-only dataclass at `mcp_common.health.feed` (server.py:951-1101), NOT a positional constructor — `known_mcp_servers` and `receiver_canary` are NOT valid Python. The feed name is the dict key in `/health`'s aggregate view; the dataclass is constructed per-feed with kwargs. The roster itself is a separate module-level list:

```python
# akosha/observability/heartbeat_watcher.py (PR-A5 ships)
# v7: known_mcp_servers is a list[str] at module scope, populated at
# lifespan startup. The heartbeat watcher reads the list to detect absences.
KNOWN_MCP_SERVERS: list[str] = []   # populated by lifespan from §13.6 settings

# Per-feed /health aggregate — every feed is a kwarg-only HealthFeedState
# constructed by its owner; the dict key is the feed name (separate
# module-level convention, NOT a positional arg):
{
    "known_mcp_servers": HealthFeedState(
        entities_count=len(KNOWN_MCP_SERVERS),
        last_updated_timestamp=boot_unix_time,
        cycles_total=1,
        errors_total=0,
        last_error_at=None,
        ingester_running=True,
    ),
    "mcp_tool_call": <populated per-cycle by mcp_call_loop>,
    "receiver_canary": <populated per-cycle by canary_metrics_bridge; v7 added>,
}
```

| Feed name (dict key in `/health`) | Source | Used for |
|---|---|---|
| `known_mcp_servers` | Static `KNOWN_MCP_SERVERS: list[str]` at module scope, populated at lifespan startup from `akosha/settings/akosha.yaml` (`servers = ["mahavishnu", "akosha", "session-buddy", "oneiric", "crackerjack", "bifrost-mcp"]`) | P0-A roster |
| `mcp_tool_call` | Per-cycle observation (`entities_count`, `last_updated_timestamp`, `cycles_total`) | `/health` aggregate |
| `receiver_canary` | Per-cycle observation from the canary emitter (`last_canary_success_unix_nano`, `canary_writes_*_total`) — **v8: updated in place by the emitter; there is no bridge task** | P0-C alert |

The two are distinct. The heartbeat watcher reads `known_mcp_servers` for the per-service roster.

- **Window:** 60s (cites parent spec §7.4).
- **Threshold:** 2 consecutive windows (120s) of absence = P0-A.
- **Empty roster = P0:** if `known_mcp_servers` is empty (misconfiguration, never populated), heartbeat watcher emits P0-A itself. Catches "registry wipe" and "substrate lift removed all entries" cases.

### 11.1 Query-empty vs query-threw

- `query_empty` (zero rows for an expected `service.name`) — counts toward P0-A.
- `query_threw` (timeout/error in `SELECT`) — emits `telemetry.heartbeat_watcher.query_failed{code}`; **suppresses** P0-A until query returns; this case is tracked separately.

```bash
# P0-A runbook (3am actionable, more concrete than v2)
# 1. Confirm Akosha reachable
curl -fsS http://localhost:8682/health | jq '.checks'

# 2. Inspect the roster the watcher is checking. There is no
#    `akosha admin heartbeat registry ls` command -- the roster is a
#    settings key, and the watcher reports against it:
#      akosha_otlp_heartbeat_service_absent_total{...}   a producer went quiet
#      akosha_otlp_heartbeat_p0_a_total{...}             P0-A fired
#      akosha_otlp_heartbeat_empty_roster_total          the roster itself is empty
curl -fsS http://localhost:8682/metrics | grep "^akosha_otlp_heartbeat_"

# 3. Verify spans_substrate (receiver is the substrate's write path)
tail -n 200 ~/.local/state/mcp/logs/akosha.err | grep -i "lifecycle\|spans_substrate"

# 4. Read the receiver's own state. There is no `akosha hot-store exec` --
#    the substrate is in-memory and has no CLI surface. The receiver's
#    state is on the metrics route:
curl -fsS http://localhost:8682/metrics \
  | grep -E "^akosha_otlp_(spans_received|spans_inserted|spans_rejected)_total"

# 5. Verify spans_substrate is present and populated, via the read path:
#    mcp__akosha__search_spans {limit: 5}   -- the rows
#    mcp__akosha__spans_summary {}          -- the counts
```

### 11.2 P0-B query-failure threshold

`query_failed` persists for `>120s` (2x the 60s heartbeat window) → emits P0-B-class alert:

```
ALERT telemetry_heartbeat_query_failed_persistent
  for 2m
  annotations:
    summary: "Heartbeat watcher substrate unreachable for 2m"
    runbook_url: "..."
```

### 11.2a The alert rules (v10, 2026-10-28)

The watcher emits three counters, and until 2026-10-28 **no rule consumed any of
them**. The detector shipped; the alerting loop did not. The fleet's producers
went silent for four hours and the counters climbed past 292 per service while
Prometheus watched them do nothing — the condition was found by reading
`/metrics` by hand.

All three rules now live in
`mahavishnu/config/prometheus/health_aggregator_alerts.yml`, group
`bodai-otel-heartbeat`, beside the `bodai-otel-canary` group that covers the
other half of the same question:

| Rule | Counter | `for` | Fires when |
|---|---|---|---|
| `OtelHeartbeatProducerSilent` | `akosha_otlp_heartbeat_p0_a_total{service}` | 30s | a rostered producer missed two consecutive 60s windows |
| `OtelHeartbeatQueryFailedPersistent` | `akosha_otlp_heartbeat_query_failed_total{code}` | 2m | the substrate could not be read for two windows |
| `OtelHeartbeatRosterEmpty` | `akosha_otlp_heartbeat_empty_roster_total` | 30s | the roster is empty, so nothing is being watched |

**The producer is `exported_service`, never `service`.** The scrape config
labels the TARGET — akosha's receiver, at `127.0.0.1:8682` — with
`service: akosha`, and Prometheus renames the counter's own `service` label to
`exported_service`. So every one of these series carries
`service="akosha"` and `exported_service="<the producer>"`. An annotation
reading `{{ $labels.service }}` would announce "akosha" for every producer in
the fleet: an alert that fires correctly and points at the wrong service is
worse than one that does not fire, because it looks like it works.

`config/prometheus/tests/heartbeat_rules.test.yml` pins that with a
`promtool test rules` unit test — the expected alert carries the producer's
identity and names it in the summary — and `tests/unit/test_prometheus_alert_rules.py`
runs `promtool check rules` and `promtool test rules` so neither file can rot
unnoticed. Prometheus reloads rule files on SIGHUP; this host's Prometheus is
reloaded that way.

**The operator procedure is `docs/runbooks/OTEL_HEARTBEAT.md`.** This spec
says what the watcher does; the runbook says what to do at 3am. The three
alerts' `runbook_url` annotations point at it, anchored to the scenario that
matches each rule. The runbook covers the triage decision matrix (canary vs
heartbeat), the seven root causes of a silent producer in the order they
actually occur, and the traps — the cumulative counters, the
`exported_service` label, the launchd wrapper's PID, and the boot-timeout
loop. `tests/unit/test_prometheus_alert_rules.py` resolves each annotation's
anchor against the runbook's actual headings, so the link cannot rot into a
404 unnoticed.

### 11.1.5 Retention sweep failure (v8 — rewritten 2026-10-27)

`akosha_otlp_retention_sweep_failed_total{table}` > 0, OR the
`sweep_retention_late` alert firing (the alert is gated by
`akosha_otlp_sweep_first_started_unix_nano > 0`, so a sweep that has not
come due yet cannot page anyone). Disambiguate which state you are in
before taking action:

```bash
# 1. Distinguish "has not come due yet" from "the last cycle failed":
curl -fsS http://localhost:8682/metrics \
  | grep -E "^akosha_otlp_sweep_(first_started|last_completed)_unix_nano"
# both 0                        => the sweep has not come due yet. It runs one
#                                  full interval AFTER start, not at t=0.
#                                  (Unless an operator asked for one — see
#                                  step 4 — which makes it run early.)
# first_started > 0, last_completed = 0 => the last cycle FAILED
# first_started > 0, last_completed > 0 => the last cycle completed cleanly;
#                                  check the row-count trend instead (§11.1.6)

# 2. Which table failed — the counter is labelled by table:
curl -fsS http://localhost:8682/metrics | grep "^akosha_otlp_retention_sweep_failed_total"
# {table="spans_substrate"} or {table="_dlq_rows"}
```

**The metrics endpoint is `:8682/metrics`, not `:9464`.** The receiver
has no port of its own: `OTLPReceiver.PROMETHEUS_PORT = 9464` is dead
code, and 9464 is Grafana Alloy's `otelcol.exporter.prometheus` default
endpoint, so binding it would collide the moment that exporter is given
an `endpoint`. The receiver's metrics ride the MCP server's own
`/metrics` route.

3. If the failure is DuckDB IO:
   Two Akosha pods racing the sweep is the multi-pod failure mode; this
   host runs one pod, so a single-pod failure is a real IO error, not a
   race. A failing pod clears at the next 6h window.

4. **There is no CLI manual-run command — there is an MCP tool.** The
   sweep is a lifespan task, and the substrate is IN-MEMORY inside the
   running akosha process, so the operation has to be triggered on the
   server that owns the data (§11.4a). Recovery is: fix the cause, then
   either wait for the next interval or ask for a sweep now:

   ```
   mcp__akosha__force_retention_sweep()
     -> {"requested": true, "already_pending": false,
         "interval_s": 21600,
         "watch": "akosha_otlp_sweep_last_completed_unix_nano"}
   ```

   The call queues the request and returns; the sweep runs on the loop's
   next turn. Confirm it landed on
   `akosha_otlp_sweep_last_completed_unix_nano`.

   Restarting akosha does **not** force a sweep; it restarts the interval
   clock, so the next sweep is a full interval away again.

5. To see what the sweep is about to remove, ask the substrate rather
   than the shell. The retention cutoff is
   `now - spans_substrate.retention_days`, and it filters on
   `received_at_unix_nano` (the receiver's clock — §15's cardinal rule):
   - `mcp__akosha__spans_summary` with `cutoff_unix_nano` set to the
     cutoff boundary returns the count of rows that fall OUTSIDE the
     retention window.
   - `mcp__akosha__search_spans` with `since_unix_nano` set to the same
     boundary returns those rows.

### 11.1.6 Cardinality alarm (v8 — rewritten 2026-10-27)

`spans_substrate_row_count_high` alert firing:

```bash
# 1. The sweep's own state (§11.1.5's two-gauge disambiguation):
curl -fsS http://localhost:8682/metrics \
  | grep -E "^akosha_otlp_sweep_(first_started|last_completed)_unix_nano"

# 2. Ingest rate — the substrate's own counters:
curl -fsS http://localhost:8682/metrics \
  | grep -E "^akosha_otlp_spans_(received|inserted)_total"

# 3. Distinct namespace values the validator has seen — the cardinality
#    signal it actually tracks:
curl -fsS http://localhost:8682/metrics | grep "^akosha_otlp_resource_drift_values"

# 4. Row counts per (selector, task_class) pair, via the substrate read
#    path rather than a shell:
#    mcp__akosha__spans_summary {selector: ..., task_class: ..., cutoff_unix_nano: 0}
```

2. If the sweep is alive (last_completed > 0) AND the row count is
   climbing: lower the retention horizon in `akosha/settings/akosha.yaml`
   (or the deployment's local override):

   ```yaml
   spans_substrate:
     retention_days: 14
   ```

   The receiver reads the value on the next sweep cycle, so **no restart
   is needed**. There is no `config set` command — see §11.4a.

3. If the sweep is stale (last_completed older than 12h) AND
   first_started > 0: see §11.1.5.

4. If first_started == 0: the sweep has not come due yet. It runs one
   full interval after start, not at t=0 — wait one interval.

### 11.1.7 Cold archival — NOT SHIPPED (v8)

§8.2 permits `archival_target: null` (no cold sink), and that is what
ships. The retention sweep **deletes** expired rows; it does not COPY
them anywhere first. So there is no `archival_failed` counter and no
`archival_last_success_unix_nano` gauge.

**Do not write a PromQL rule on `archival_failed`.** The series does not
exist, and a rule on a missing series never fires — so the alert would
be silently dead, which is worse than no alert, because it reads as
"archived fine". That silence is the specific failure this section
exists to prevent.

If a cold sink is required, that is a separate change with its own
review: an operator-configured egress path for span rows. Until it
exists, the sweep deletes rather than stalling on a write it cannot make.

### 11.3 Synthetic canary span (v4 addition; ops P0)

The heartbeat watcher verifies the substrate is **queryable** (P0-A / P0-B). It does not verify the **receiver writes succeed end-to-end**. A broken `_handle_batch` (serializer bug, class-not-found, DLQ permission error after a §6.2 try/except swallowed the error) lets `/health` return green indefinitely while every producer's spans silently drop. No "observability of the observability."

v4 adds a synthetic canary: the receiver (or, more cheaply, the lifespan) emits a deterministic marker span every 30s and tracks the time of the last successful end-to-end write into the substrate.

**Canary spec** (PR-A3 ships the lifespan task; PR-A4 wires the metric + alert):

- `service_name = "_receiver_canary"`
- `span_name = "_canary_substrate_write"`
- `service.namespace = "bodai"` (v8 — the fleet default, so the receiver's own validator accepts the marker; see the v8 note below)
- `start_time_unix_nano = time.time_ns()`
- `attributes = {"_canary": true, "_canary_version": "1"}`
- Attempted every `CANARY_EMIT_INTERVAL_SECONDS = 30` (default)
- INSERT goes through the same `_handle_batch` → `insert_spans_substrate` path the production spans use — **defends against partial-deploy code paths** (a code change that breaks the live INSERT but leaves `_dlq_insert` working would otherwise pass silently). **v8: the FULL path, not just the INSERT** — protobuf decode and `_proto_to_dict` included, because the serializer is where the `ArrayValue` defect lived.

**State tracking** (mirrors the §11 heartbeat-watcher pattern; new `receiver_canary`):

```python
# akosha/observability/canary_watcher.py (PR-A4)
@dataclass
class CanaryState:
    last_canary_success_unix_nano: int | None = None   # server-side receive time
    last_canary_failure_unix_nano: int | None = None
    canary_writes_attempted_total:   int = 0
    canary_writes_succeeded_total:   int = 0   # v6: pinned to "BatchResult(ok=1, deduped=0)" — see below
    canary_writes_failed_total:      int = 0
    canary_writes_rejected_total:    int = 0   # v6: UNIQUE CONSTRAINT rejected (no exception)
    # v8: no `bridge_failed_total` — there is no bridge. See the v8 note below.
```

**"Succeeded" definition (v6 — pinned to remove ambiguity for multi-pod deployments):**

A canary write is **succeeded** iff `_handle_batch` returns `BatchResult(ok=1, deduped=0)` — i.e. exactly one row INSERTed (no exception, no UNIQUE-CONSTRAINT rejection). With multiple Akosha pods racing the canary emit, only one pod per cycle meets this bar; the others' INSERTs return `BatchResult(ok=0, deduped=N-1)` (or hit the §6.2 DLQ for bad rows), and they increment `canary_writes_rejected_total` instead of `canary_writes_succeeded_total`. Without this pin, a multi-pod deployment either silently double-counts successes (option a) or silently under-counts them (option b) — both are misleading. Decided: **option b is the contract**, with explicit `canary_writes_rejected_total` as the positive signal that the loser-pod's constraint-rejection registered.

**v8 — the canary's namespace is `bodai`, and it goes through the FULL path.**

Two pins the v6 text above did not make:

1. **The namespace is `bodai`** (the fleet default), not a canary-specific one. The receiver's own resource validator runs on the canary, so a namespace outside the allowlist would reject the marker *before it reached the INSERT* — and a canary that fails on a namespace the fleet legitimately uses is a false alarm, not a signal. The marker is identifiable by its `service_name` (`_receiver_canary`), not by its namespace. If `bodai` ever leaves the allowlist, the canary failing is the CORRECT signal: the whole fleet is being rejected.
2. **The marker is a real `ExportTraceServiceRequest`, not a dict.** It crosses protobuf decode → `_extract_spans` → `_proto_to_dict` → `pre_validate` → `insert_spans_substrate` — the same path a producer's span takes. A canary that shortcut into the INSERT would have missed exactly the bug class it exists to catch: the `ArrayValue` serializer defect lived in `_proto_to_dict`, and a canary that skipped it would have stayed green through that entire outage.

**v8 — NO bridge task. The emitter updates the metrics directly.**

v6 described a `_canary_metrics_bridge` task that copied `CanaryState` into Prometheus gauges every 10s, with its own `bridge_failed_total` and a P0-D alert for "the bridge died". That task is **not shipped**, and the reason is worth recording: a bridge that dies freezes the gauge, so the bridge needs its own liveness alert — and the P0-C staleness alert would then have two ways to fire for one underlying failure (stale gauge, dead bridge).

Updating the metrics in place, at the moment the write outcome is known, removes that gap. The only way `canary_last_success_unix_nano` goes stale is the emitter task dying — and the P0-C staleness alert catches exactly that. So there is no `bridge_failed_total` and no P0-D alert; the P0-C alert covers both "the write path is broken" and "the emitter died", which is the correct granularity: from the outside they are the same symptom and the same action.

**Prometheus surface** (PR-A4 contract — every name written by `canary_watcher.py`, on the `:8682` `/metrics` route):

- `akosha_otlp_canary_last_success_unix_nano` (gauge; `last_canary_success_unix_nano` — the RECEIVER's clock at the moment the write landed, not the producer's and not the span's start time)
- `akosha_otlp_canary_writes_attempted_total` (counter; monotonically incremented)
- `akosha_otlp_canary_writes_succeeded_total` (counter; **ok=1 ∧ deduped=0 ∧ rejected=0 only**)
- `akosha_otlp_canary_writes_failed_total{reason}` (counter; `reason` = the exception class name, or `unexpected_result` when the write returned without inserting)
- `akosha_otlp_canary_writes_rejected_total` (counter; **incremented on `ok=0, deduped>0`** — its own counter, not a label on the failure counter, because a constraint rejection is not an exception)
- `akosha_otlp_canary_rows_deleted_total` (counter; canary rows removed by the sweep)

**v8 — canary rows are swept at 24h, not at the substrate's `retention_days`.**

At one row per 30 seconds that is 86,400 rows a day. On the substrate's 30-day horizon the canary alone would accumulate into millions of rows inside an **IN-MEMORY** DuckDB with a 1GB limit — the canary would fill the table it is measuring. A canary row is liveness evidence, not history: the same reasoning §8.1 applies to `_dlq_rows`. The sweep runs a second DELETE against `spans_substrate` with a 24h cutoff and `service_name = '_receiver_canary'`, labelled `spans_substrate_canary` in `akosha_otlp_retention_sweep_failed_total` so the two sweeps on one table stay distinguishable in an alert.

**P0-C alert** (v8 — corrected again for the shipped metric names and the
absence of a bridge; v4 used `time_ns()` which is non-standard PromQL, and
the LHS referenced a Python dataclass field, which evaluates `null` and
never fires):

```yaml
# config/prometheus/health_aggregator_alerts.yml — group bodai-otel-canary
- alert: OtelReceiverCanaryStale
  expr: |
    (time() * 1e9 - akosha_otlp_canary_last_success_unix_nano > 60e9)
    and on(instance) (up{job="bodai-ecosystem", instance=~".*:8682"} == 1)
  for: 30s
  annotations:
    summary: "Akosha's OTLP receiver is not writing spans (canary stale 60s+)"
```

**Thresholds, pinned (v8).** The canary writes every 30s. The expression
fires at **60s** of staleness — two missed emits, which is what §14's
"2 missed emits surface P0-C" requires — and the `for: 30s` adds one more
interval of confirmation so a single slow cycle does not page. Total
detection is ~90s. (The v6 text said `for: 90s` over a `> 90e9`
threshold, which is 180s of detection and does not match §14.)

**The first emit is immediate (v9).** The gauge starts at 0, so a canary
that waited out its first interval would leave it there for 30 seconds on
every boot — and with `for: 30s` on the rule, long enough for the
expression to fire on a receiver that is starting up perfectly normally.
The emitter therefore writes its first canary at startup and then every
30s after. This is the same reasoning the receiver already applies to
`cycles_total`: the startup IS the first cycle.

**The `up` guard matters.** If akosha is DOWN the gauge goes absent and
the expression would not fire anyway — but "down" and "up but not
writing" are different incidents with different fixes, and they deserve
different alerts. The guard keeps the canary alert about the canary.

**No P0-D bridge alert** — there is no bridge (see above). The P0-C
staleness alert covers both "the write path is broken" and "the emitter
task died", which is the right granularity: from the outside they are
the same symptom and the same action.

```
ALERT receiver_canary_stale   [superseded by the v8 form above]
  for 90s
  expr: time() * 1e9 - telemetry_receiver_canary_last_success_unix_nano > 90e9
  annotations:
    summary: "Receiver has not written a successful canary span in 90s"
    runbook_url: "docs/specs/2026-10-19-bodai-substrate-otel-v6.md#113-synthetic-canary-span-v4-addition-v5-hardened-v6-canary-bridge-liveness"
```

**The v6 P0-D bridge alert is withdrawn.** There is no bridge (see
above), so `bridge_failed_total` does not exist and a rule on it would
never fire — a silently dead alert, which is worse than no alert. The
P0-C staleness rule covers the case the P0-D rule was for.

PromQL notes:
- `time()` returns Unix seconds; `time() * 1e9` is Unix nanoseconds. v4 had `time_ns()`, which PromQL doesn't define; the alert would have been syntactically invalid in strict parsers and surfaced a parse error.
- The LHS is the Prometheus gauge name (every Prometheus alert MUST address scraped metric names; referencing Python `CanaryState.last_canary_success_unix_nano` would evaluate `null > 90e9`, never firing). v8 removed the bridge, so the gauge is set by the emitter at write time rather than copied at scrape time — the value is the same, but it is now fresh by construction instead of fresh by polling.

P0-C catches:
- `INSERT` path regressions (the §6.2 try/except would have hidden a silently-failing batch).
- `start()` succeeded but `_handle_batch` doesn't (e.g., a span class renamed without aliasing, JSON serializer accidentally returns `None` for `attributes`).
- **Serializer regressions** — this is the class the canary's full-path design exists for. The `ArrayValue` defect (2026-10-23) broke `_proto_to_dict` for array-valued attributes; 223 Export RPCs failed and every producer's batch was dropped while `/health` stayed green. A canary that shortcut into the INSERT would not have noticed.
- DLQ-flood scenarios where good rows stop landing.
- Cold-start of substrate (the first canary might be slow; the P0 only fires after 60s of staleness plus 30s of confirmation).
- The emitter task itself died — the gauge freezes, and that is the same symptom and the same action as a broken write path.

**Duplicate-suppression**: the canary uses a deterministic `trace_id` (derived from the constant `"_canary"`) and a `span_id` derived from the cycle's timestamp, so duplicate canaries don't bloat the table. Worst-case noise: 1 row per 30s = 86,400 rows/day per canary producer — which is why the canary rows are swept at 24h (above). With multiple Akosha pods, only one INSERT survives per `(trace_id, span_id)` due to the §5.1 UNIQUE CONSTRAINT — pods that lag emit a duplicate that the constraint quietly rejects, and that is counted in `akosha_otlp_canary_writes_rejected_total`, not as a failure. Loser pods show up in the rejection counter and in `canary_last_success_unix_nano` staleness; not as DLQ noise.

### 11.4a Operator interface for the substrate (v9 — rewritten 2026-10-27)

**v7 required a new `akosha admin otel retention {…}` Typer subtree and a
top-level `akosha migrations {up,down,…}` group. Neither ships.** The
reasons are worth stating, because v7 asserted the opposite and an
operator reading v7 would still reach for commands that do not exist:

1. **There is no migration framework.** §15 chose inline
   `CREATE TABLE IF NOT EXISTS` at the point of first use. The substrate
   DDL lives in oneiric's `DuckdbHotStore.initialize()`; the receiver's
   two operational tables follow the same rule. A `migrations` CLI would
   be a Typer group wrapped around a framework the Bodai fleet does not
   have. The v7 proposal even named yoyo — which v6 had already dropped
   for this exact reason.

2. **A CLI is the wrong surface for a self-driving subsystem.** The
   retention sweep is a lifespan task that runs on its own interval. What
   an operator normally needs is to *see* what it is doing and to change
   the horizon it operates on. Both are already available: the first on
   the metrics route, the second in the settings file.

3. **v9 adds the one operation that genuinely needed a trigger.** v8's
   table marked "force a sweep now" as *Not available*, and that was
   honest — but it left a 6-hour worst-case wait on the one operation
   where waiting hurts: the substrate is an IN-MEMORY DuckDB with a 1GB
   limit, and an operator watching the row count climb has no way to
   reclaim space now.

   **The trigger is an MCP tool, not a CLI.** This is not a preference:
   the substrate lives in the running akosha process's memory
   (`HotStore(database_path=":memory:")`) and the receiver is a
   process-local singleton published by `set_shared_otel_receiver`. A CLI
   subprocess is a *different process* — it has neither the rows nor the
   receiver, so `akosha admin otel retention manual-run` could not have
   worked even if it had shipped. The operation has to run on the server
   that owns the data.

The operator interface is therefore:

| Need | Interface |
|---|---|
| Is the receiver alive, and what has it ingested? | `curl -fsS http://localhost:8682/metrics` — the `akosha_otlp_*` families |
| Is the sweep healthy? | `akosha_otlp_sweep_first_started_unix_nano` / `akosha_otlp_sweep_last_completed_unix_nano` / `akosha_otlp_retention_sweep_failed_total{table}` |
| Why was a span rejected? | `akosha_otlp_spans_rejected_total{field=…}` — labelled by the field that failed |
| Which producers are reporting? | `akosha_otlp_heartbeat_*` (PR-A5) |
| What is in the substrate? | `mcp__akosha__search_spans`, `mcp__akosha__spans_summary` |
| Change the retention horizon? | `spans_substrate.retention_days` in `akosha/settings/akosha.yaml` |
| Force a sweep now? | `mcp__akosha__force_retention_sweep` — returns `{"requested": true, "already_pending": false, "interval_s": …, "watch": "akosha_otlp_sweep_last_completed_unix_nano"}` |

**The trigger SIGNALS; it never deletes.** The sweep loop owns the single
DuckDB connection to the substrate. A caller that ran the sweep itself
would put a second `DELETE` against that connection, and two coroutines
deleting on one DuckDB handle is a race, not a feature. So the tool sets
an event and returns; the loop — the sole writer — wakes and sweeps. The
call returns *before* the sweep lands: the operator confirms it with
`akosha_otlp_sweep_last_completed_unix_nano`, which the response names.

One pending request is one sweep. A second call while one is queued
reports `already_pending: true` rather than queueing a second DELETE over
the same rows. A requested sweep does NOT reset the interval clock: the
next automatic sweep still runs a full interval after the requested one.

Operator runbook: `akosha/docs/ops/OTEL_RETENTION.md`.

### 11.4 `known_mcp_servers` config home (v4; was undefined in v3)

The §11 table at line 574 mentions a `servers = ["mahavishnu", "akosha", "session-buddy", "oneiric", "crackerjack", "bifrost-mcp:grpc"]` config but never says where the config lives. v4 pins it under `akosha/settings/akosha.yaml`:

```yaml
# akosha/settings/akosha.yaml — additions in PR-A5
otel:
  receiver:
    trace_ingester_poller:   true        # PR-A8 flips to false (rollback path)
    known_mcp_servers:                    # NEW — static roster for P0-A detection
      - "mahavishnu"
      - "akosha"
      - "session-buddy"
      - "oneiric"
      - "crackerjack"
      - "bifrost-mcp"                     # entry not the gRPC suffix; suffix belongs to Bifrost's own URL
  # NOTE: this section only pins the §11.4 PR-A5 roster keys. The §8.2 retention
  # settings (`otel.spans_substrate.{retention_days, retention_sweep_interval_hours,
  # archival_target}`) live at the §13.6 / §11.4 canonical location (sibling of
  # `otel.receiver`, NOT nested under it). v5's "bound under otel.receiver" inline
  # comment was misleading; v6 fixes it. The §8.2 sweep body reads `settings.spans_substrate.*`
  # which oneiric's layered config resolves via dot-notation at the §13.6 path.
```

The empty-roster case (no entries → the §11 P0-A `Empty roster = P0` check fires on every heartbeat) is itself a P0; PR-A5 ships a `test_empty_known_servers_roster_emits_p0` regression test.

(Note: cross-component `services:` lists for orchestration now share this single YAML, instead of being scattered across `mahavishnu/settings/mahavishnu.yaml` and each `*-mcp` repo's settings.yaml. PR-A5's CLAUDE.md note for operators.)

---

### 11.4b The producer side — what "reporting" means (v10, 2026-10-28)

**The roster is a declaration of expectation, and until v10 nothing met it.**
The §11 watcher read the substrate for spans whose `service_name` matched a
roster entry. On 2026-10-28 the substrate held **no such spans at all** —
`akosha_otlp_spans_received_total` equalled `inserted_total` and every row
was the receiver's own canary. P0-A had fired for every rostered service,
continuously, since PR-A5 shipped. It was telling the truth.

Three things were wrong, and all three had to be fixed for the roster to
mean anything.

**1. Nothing installed a tracer provider.** The launchd plists set no
`OTEL_EXPORTER_OTLP_*` variable, and launchd services do not inherit the
shell environment — so no service had an exporter, every span it created
stayed in the process, and the receiver heard only from itself. The fix
lives in **one place**: `mcp_common/server/launcher.py::launch` calls
`mcp_common/server/producer_telemetry.py::configure_producer_tracing`
before it builds the server. Every core service already starts through
that launcher, and the `component_name` it passes there is **the same
string the roster watches**:

| Service | `component_name` | Roster entry |
|---|---|---|
| mahavishnu | `"mahavishnu"` | `mahavishnu` |
| akosha | `"akosha"` | `akosha` |
| session-buddy | `"session-buddy"` | `session-buddy` |
| oneiric | `"oneiric"` | `oneiric` |
| crackerjack | `"crackerjack"` | `crackerjack` |

**2. Request-driven spans cannot serve as a heartbeat.** An MCP server
emits a span when somebody calls a tool. The watcher's window is 60s and
its threshold is two consecutive absences, so an **idle** fleet trips
P0-A by construction — the alert would be a guaranteed false positive
rather than a detector. (Measured: mahavishnu was demonstrably alive and
reporting `resolver.decision` spans, and the watcher still read it as
absent, because those spans were 195s old.)

The fix is a **producer-side liveness span**: `_service_liveness`, emitted
every 30s by `run_liveness_emitter`. It mirrors the §11.3 canary one
layer up — the canary proves the *write* path, the liveness span proves
the *export* path. Silence then means "the telemetry pipeline is broken",
which is what the watcher is for. It is emitted **immediately** at
startup rather than one interval later, so a producer that came up late
is distinguishable from one that is broken.

**3. Two producers pointed at the wrong place.** Both were invisible to
the receiver and neither produced a metric, which is what made them hard
to find:

- **The endpoint.** The OTLP/HTTP exporter treats an explicit endpoint as
  the COMPLETE URL, signal path included. Session-Buddy handed it
  `http://127.0.0.1:4318`, so every batch posted to the port's root
  instead of `/v1/traces` and came back `404 Not Found`. A rejected
  request and a request that was never made look identical from the
  sender's side. The shared helper resolves the endpoint the way the
  exporter expects.
- **The namespace.** The §13.2 allowlist is a fixed set of **NAMESPACES**
  (`bodai`, `cli-tools`). `session-buddy` and `akosha-mcp` are service
  **NAMES**; a span carrying either as its namespace would have been
  quarantined as namespace drift even with the endpoint right. Every core
  service reports under `bodai`.

**The rules, for anything added to the roster later:**

1. The service must start through `mcp_common.server.launcher.launch` with
   a `component_name` equal to its roster entry.
2. Its launchd plist must set `OTEL_EXPORTER_OTLP_ENDPOINT` (and
   `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`). The launcher is
   **opt-in**: with no endpoint in the environment it installs nothing, so
   the standalone MCP servers that share the launcher are unaffected.
3. Its `service.namespace` must be `bodai`.
4. The provider must carry the exporter. `setup_telemetry` used to build
   the `TracerProvider` twice — once for the span processors, once for
   the sampler — and the second replaced the first, so the exporter was
   attached to a provider nobody used and akosha exported nothing at all.

---

## 12. `opentelemetry-proto` install discipline

`opentelemetry-proto` is **runtime-required** (the substrate's whole point). PR-A2 + PR-A3 move it from `[dependency-groups]` (PEP 735, opt-in) to `[project.dependencies]` (always-installed) per §6.4. **There is no separate install command.** Production deployments pick up the dep automatically with `uv sync`.

The `LifecycleError("opentelemetry-proto-missing")` path from v2 §12 is removed in v3 — the dep is always available; the error class never fires.

**Verified at PR-A3 (2026-10-23).** `opentelemetry-proto` was already
present in akosha's venv at 1.45.1, pulled in transitively by
`opentelemetry-exporter-otlp`. No install was needed; §6.4's declaration
into `[project.dependencies]` still matters, because the receiver imports
the package directly and a direct import behind a transitive dependency
breaks the moment the exporter's own dependency set moves.

---

## 13. Stage-A PR execution order

**11 PRs total** across 3 repos. Dependency graph is sequential; PR-A3 onward builds on the substrate managed by PR-0a.

| PR | Repo | Purpose | Depends on |
|---|---|---|---|
| **PR-0a** | oneiric | Add `spans_substrate` DDL + `spans_substrate_table` class attribute + `table_exists()` to `DuckdbHotStore`. Bump oneiric minor. | — |
| **PR-0b** | akosha | Update `pyproject.toml` to declare `opentelemetry-proto` as `[project.dependencies]`. **Add `set_shared_otel_receiver()` hook + extend `clear_shared_services()`** to clear the new `_shared_otel_receiver` module global alongside `_shared_hot_store` and `_shared_kg_builder`. PR-0b PR description enumerates 3 edits: (a) `set_shared_otel_receiver(receiver)` + `get_shared_otel_receiver()`; (b) module-level `_shared_otel_receiver: OTLPReceiver \| None = None`; (c) extend `clear_shared_services()` body to also nil out `_shared_otel_receiver`. Regression test: `create_app()` twice → `get_shared_otel_receiver()` is `None` between calls. | PR-0a |
| **PR-A1** | mcp-common | Bridge release — emit `namespace.legacy_alias=bodai` alongside current `service.namespace`. | — |
| **PR-A2** | akosha | yoyo migrations `0001.akosha-otel-receiver-state.sql` + `0001.…rollback.sql` + `0002.dlq-rows.sql` + `0002.…rollback.sql`. | PR-0a, PR-0b |
| **PR-A3** | akosha | `OTLPReceiver` lifespan wiring (HotStore.init → receiver.start → set_shared_otel_receiver → tool register). **Move the real port owner — Grafana Alloy — from `:4317`/`:4318` to `:14317`/`:14318`, and repoint the 3 `~/.zshrc` OTLP endpoint exports (§13.1, corrected 2026-10-21)**. Add `GRPC_PORT`/`HTTP_PORT` settings keys. Drop substrate mid-test and confirm `LifecycleError`. **SHIPPED 2026-10-23** (akosha `e897bbd`, `7a3f182`; oneiric `ddc40ed`, `c0c4556`) with four deviations, all recorded in `docs/decisions/2026-10-23-otel-substrate-spec-corrections.md`: (a) validation + DLQ ship **here**, not in PR-A4 — the port cutover is also in this row, and a receiver that binds `:4317` without ingesting would make the cutover strictly worse than not cutting over; (b) the three `~/.zshrc` exports need **no change**; (c) Alloy's trace pipeline is **deleted**, not just disconnected, because it blocks Alloy's startup outright; (d) the ingest writers live in oneiric, not akosha's subclass. | PR-A2 |
| **PR-A4** | akosha | Per-row validation + DLQ try/except wrapping + `_dlq_rows` retention sweep. | PR-A3 |
| **PR-A5** | akosha | `heartbeat_watcher.py` reading `known_mcp_servers`. query-empty vs query-threw distinction. Empty-roster P0. | PR-A3 |
| **PR-A6** | akosha | Receiver resource-attribute validator (allowlist-based, rate-based thresholds). | PR-A4 |
| **PR-A6.5** | akosha | Existing `spans` table disposition (drop or migrate to `spans_substrate`). | PR-A4 |
| **PR-A7** | mcp-common | Flip release — `service.namespace` defaults to `bodai`. **Gated on §10.1 sweep + §10.2 CI gate**. | PR-A1 + bridge-recursive-validation |
| **PR-A8** | akosha | Retire `OtelTraceIngester` poller. `otel.receiver.trace_ingester_poller: bool` (in `akosha/settings/akosha.yaml`, see §11.4 + §13.6) gates the import + lifespan start. PR-A8 flips the flag to `false`; rollback is a flag flip + restart, never a code revert. **v7 — PR-A8 must explicitly retire the pre-existing `AKOSHA_SKIP_OTEL_INGESTER` env var (`akosha/mcp/server.py:627`); remove the `if not _env_truthy("AKOSHA_SKIP_OTEL_INGESTER"):` block, replace with the settings-key read path. Runbooks (`§11.1.5`/6/7) and `akosha/CLAUDE.md` operator note updated accordingly. Without this edit, operators with launchd plists setting `AKOSHA_SKIP_OTEL_INGESTER=1` get the dead OTelPoller silently re-enabled post-PR-A8.** | PR-A5, PR-A6, PR-A6.5 |

After PR-A8 ships:

**PR-B** — rewrite sub-spec B against this substrate. Independent brainstorm + agent review + writing-plans cycle.

### 13.1 Port collision fix (full enumeration)

**Corrected 2026-10-21.** The port owner is **Grafana Alloy**, not
`mahavishnu/config/otel-collector-config.yaml`. Verified: no `otelcol` process
is running, nothing listens on that config's ports, and the 2026-09-28 relay it
descended from (`/tmp/otel_relay.py`) is gone. Alloy holds both ports as a
Homebrew service (`sh.brew.grafana-alloy.plist`, config at
`/usr/local/etc/grafana-alloy/config.alloy`). Rationale and rollback in
`docs/decisions/2026-10-21-otel-substrate-port-ownership.md`.

Two facts drive the design:

- **Alloy's trace pipeline is a dead end.** `config.alloy:58-67` routes traces
  to `otelcol.exporter.debug`, which logs them and never persists or forwards
  them. Only metrics survive, via the Prometheus exporter on `:12345`.
- **Alloy is the designated ingress.** `~/.zshrc:183-196` exports **three**
  OTLP endpoints at it — `CODEX_OTEL_EXPORTER_OTLP_ENDPOINT` (:188),
  `QWEN_TELEMETRY_EXPORTER_OTLP_ENDPOINT` (:191), and the generic
  `OTEL_EXPORTER_OTLP_ENDPOINT` (:193). Claude Code has **no** endpoint export
  of its own; it reaches `:4318` via the generic variable. The two
  `CLAUDE_CODE_*` lines are `CLAUDE_CODE_ENABLE_TELEMETRY=1` (a toggle) and
  `CLAUDE_CODE_PROMETHEUS_PORT=9465` (a Prometheus **scrape** port — nothing
  listens on 9465; do not repoint it at an OTLP receiver). Six established
  connections from four producers at survey time (a point-in-time census, not
  a stable set): `akosha mcp start`, two `claude` sessions, two `bifrost-http`
  connections, and `scripts/launch_mcp.py` (gRPC).

**Decision: the canonical OTLP ports belong to the substrate. Alloy keeps a
non-canonical pair for metrics.** The substrate is the storage, not a relay
hop — routing spans through a collector that never persists them would preserve
the existing data loss under a new name.

```
producers ──> :4317 gRPC / :4318 HTTP ──> Akosha OTLPReceiver
                                                │
                                                └──> spans_substrate (DuckDB)

:14317 / :14318 ──> Alloy  (metrics ──> :12345 ──> Grafana)
```

`:4319`-`:4322` (claude/qwen) are **not** Alloy's — they exist only in the
dead `config/otel-collector-config.yaml`, nothing listens on them, and they are
untouched by this decision.

**Conflicts with new `OTLPReceiver`:**

| New receiver port | Existing holder | Resolution |
|---|---|---|
| `:4317` (gRPC) | Alloy `otelcol.receiver.otlp.cli_tools` | Alloy moves to `:14317`; Akosha gets `:4317` |
| `:4318` (HTTP) | Alloy `otelcol.receiver.otlp.cli_tools` | Alloy moves to `:14318`; Akosha gets `:4318` |

**Migration:**

```alloy
// /usr/local/etc/grafana-alloy/config.alloy — refactor at PR-A3
otelcol.receiver.otlp "cli_tools" {
    http { endpoint = "127.0.0.1:14318" }   // was :4318
    grpc { endpoint = "127.0.0.1:14317" }   // was :4317

    output {
        metrics = [otelcol.processor.memory_limiter.cli_tools.input]
        traces  = [otelcol.processor.batch.cli_tools_traces.input]
    }
}
// otlp/claude (:4319/:4320) and otlp/qwen (:4321/:4322) are NOT in this file.
// They exist only in the dead mahavishnu collector config, nothing listens on
// them, and they are out of scope — see below.
```

**Executed 2026-10-23 — with one addition the sketch above omits.**
Alloy's `otelcol.processor.batch "cli_tools_traces"` and
`otelcol.exporter.debug "cli_tools_traces"` are **removed entirely**, not
merely orphaned.

`otelcol.exporter.debug` sits at "experimental" stability, below Alloy's
minimum "generally-available" level, so the config could not load at all:

```
Error: otelcol.exporter.debug is at stability level "experimental",
       below the minimum allowed stability level "generally-available"
Error: could not perform the initial load successfully
```

That defect predates PR-A3 and was **masked**: Alloy had been running
under the old config since April, and moving the ports forced a config
reload that surfaced it. Leaving the trace pipeline in place would have
left Alloy unable to start — and its metrics pipeline down with it.

Deleting the pipeline is also the correct outcome independently of the
startup bug: the debug exporter discards traces by design, which is the
entire reason this substrate exists. Alloy is metrics-only after this
change. Backup:
`/usr/local/etc/grafana-alloy/config.alloy.bak-pre-akosha-cutover`.

**Producer repointing** (required at PR-A3, in lockstep with the Alloy move):

| Item | Change |
|---|---|
| `~/.zshrc:188,191,193` | 3 OTLP endpoint exports repointed to the substrate (`:4318` stays canonical). **Not** `CLAUDE_CODE_PROMETHEUS_PORT` (:186) — a scrape port, not an endpoint |
| `akosha` | `AKOSHA_OTLP_ENDPOINT` → substrate receiver, not a collector |
| `mahavishnu` | `MAHAVISHNU_OBSERVABILITY__OTLP_ENDPOINT=http://127.0.0.1:4318` — the HTTP port. An `http://` URL must not target `:4317`, which is gRPC |
| `settings/local.yaml:4-19` | delete the dead 2026-09-28 relay comment block |

**CORRECTED 2026-10-23 (PR-A3 execution).** The `~/.zshrc` row is a
**no-op**, not a change. All three exports already target
`http://127.0.0.1:4318`, which after the move IS the substrate receiver:

```
188:export CODEX_OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
191:export QWEN_TELEMETRY_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
193:export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
```

Repointing them to `:14318` would route traces into Alloy's discarding
pipeline — strictly worse than leaving them alone. They were never
wrong; they were aimed at a port a debug exporter happened to occupy.
Only the occupier moves.

That is the payoff of resolving port **ownership** rather than port
**numbers**: no coordinated producer rollout, and no window in which
spans are lost. Verify the exports are unchanged rather than editing them.

**Receiver ports must be configurable.** §Appendix D declares
`PROMETHEUS_PORT = 9464` as a class attribute, but the gRPC/HTTP ports appear
only as literals inside `start()`'s docstring — there is no seam. PR-A3 must add

**Implemented.** `GRPC_PORT` / `HTTP_PORT` are class attributes, and the
lifespan resolves them from a real `SpansSubstrateConfig` field
(`spans_substrate.receiver_grpc_port` / `receiver_http_port`) rather than
from a defensive `settings.get()`. `get_config` strips any key
`AkoshaConfig` does not declare, **silently** — an undeclared key is
dropped with nothing in the logs, so the receiver binds the canonical
ports while the operator believes otherwise. A settings key with no
matching model field is a lie that reads like a setting.

**HTTP listener.** An earlier draft of §6 sketched
`TraceServiceResource` from `opentelemetry.exporter.otlp.proto.http`.
That package ships **no servicer and no ASGI app** — it is a client-side
exporter, and the receiver is the server. Shipped instead: a Starlette app
built in the receiver, parsing `ExportTraceServiceRequest` off the raw
protobuf body at `POST /v1/traces`, served by uvicorn as a task so the
lifespan's reverse-order teardown still owns shutdown.
`GRPC_PORT` / `HTTP_PORT` class attributes and settings keys alongside
`PROMETHEUS_PORT`, so the port assignment above is a setting rather than a code
edit in a receiver that four producers are pointed at.

**Consumers that reference the OTLP ports:**

| Consumer | File pattern |
|---|---|
| `~/.zshrc` producer exports | lines 188, 191, 193 (3 OTLP endpoints) |
| Alloy receiver config | `/usr/local/etc/grafana-alloy/config.alloy` |
| Bifrost gateway | operator-owned; **endpoint source unverified** — see risk below |
| Mahavishnu's dead collector config | `mahavishnu/config/otel-collector-config.yaml` — **not running**; do not repoint |
| Grafana dashboards | **none** — `config/grafana/dashboards/*.json` reference no OTLP port; the `dashboards/bodai/` path in the pre-v7 draft never existed |

**Migration gate** (PR-A3 CI step): `git grep -nE ':(4317|4318)'` over
`config/grafana/dashboards/` returns zero hits, and the sweep over consumers
above shows only the three `~/.zshrc` lines and the Alloy config — each of which
must be updated in the same change. Plus a liveness assertion: the CI step fails
if Alloy is still bound to `:4317`/`:4318` after the move.

**Risk — `bifrost-http` endpoint is not inspectable, and bifrost is
intermittent.** Its `~/.config/bifrost/config.json` has no otlp/telemetry key,
its process environment carries no `OTEL_*` variable, and its binary contains
no `localhost:4318` literal — yet it held two established connections to
`:4318` at survey time. The endpoint source is outside the files we can read.
Those connections were gone on re-check ~50 min later and the process itself
had exited, consistent with an interval-flushing batch exporter. PR-A3 must
therefore **observe bifrost across at least one flush interval** after cutover:
if its spans appear in `spans_substrate`, it followed the SDK default and the
swap is correct; if reporting stops with no local signal, treat as a cutover
failure and roll back. A single point-in-time `lsof` sweep is not a valid
producer census — it missed bifrost entirely on the second pass. Do not assume
either outcome.

**Rollback:** reverts `config.alloy` to `:4317`/`:4318` (`brew services restart
grafana-alloy`), restores the `~/.zshrc` exports, and stops the receiver. Rows
already written to `spans_substrate` stay readable — the port number is not part
of the storage path.

**claude/qwen receivers** (`:4319`/`:4320`/`:4321`/`:4322`) — **reclassified as out-of-scope for v7**. These are not Alloy's: they are declared only in the dead `config/otel-collector-config.yaml`, and nothing listens on them. Sub-spec B or a later spec decides whether to revive them on the substrate or delete them. See §3.

### 13.2 Resource-attribute validator (PR-A6)

Sets the allowlisted namespaces:

```python
# akosha/observability/resource_validator.py
ALLOWED_NAMESPACES_BRIDGE = {"mcp-ecosystem", "bodai"}             # during bridge
ALLOWED_NAMESPACES_POST_FLIP = {"bodai"}                          # post-flip
# PR-A6 ships with `ALLOWED_NAMESPACES = ALLOWED_NAMESPACES_BRIDGE` (the bridge
# release is active at PR-A6's merge time — mcp-ecosystem producers MUST be
# permitted, otherwise every span gets flagged as namespace drift during the
# bridge window).
# PR-A7's flip swaps the binding in a single-line edit:
#     ALLOWED_NAMESPACES = ALLOWED_NAMESPACES_POST_FLIP
# Both the §10.2 git-grep CI sweep and the dual-label test (§10.4
# `test_dual_label_emitted_during_bridge`) gate the flip — neither alone
# is sufficient; both must pass.
```

**Drift detection — rate-based, not count-based:**

```python
ROLLING_WINDOW_SECONDS  = 300   # 5 min
SPIKE_THRESHOLD          = 3     # >3 in rolling window = P1 spike
SUSTAINED_THRESHOLD_HR   = 0.5   # >0.5/hour over 24h = P2 sustained
```

Two alert tracks:
- **P1 spike**: >3 drifts from a single producer in any rolling 5-minute window. Alerts once per window.
- **P2 sustained**: >0.5/hour drift rate over 24h. Alerts daily.

(Replaces v2's count-per-hour threshold; v2 was misclassified by startup bursts and slow drift.)

### 13.5 Existing akosha `spans` table disposition (PR-A6.5)

Parent spec §5.5 ALTERed a `spans` table. v3's substrate uses `spans_substrate`. If `spans` exists in akosha's HotStore today, it is **migrated with explicit column mapping** (v3 had a bare `INSERT INTO ... SELECT ...` which fails because the v3 substrate column names do not match the v1 `spans` schema):

```sql
-- PR-A6.5 migration step. Adjust schema inspection PR:
-- 1. The PR must hand-inspect the live `spans` schema first
--    (DESCRIBE spans) and edit this mapping if the live schema differs.
--    v3 column names below assume the parent-spec §5.5 schema:
--      spans:  span_id, trace_id, parent_id, service_name, name,
--              start_time, end_time, duration_ms, attributes, events,
--              status, embedding, timestamp
--      spans_substrate (v3):
--              span_id, trace_id, parent_span_id, service_name,
--              span_name, start_time_unix_nano, end_time_unix_nano,
--              duration_ms, attributes, events, status_code,
--              status_message, ...

INSERT INTO spans_substrate (
    span_id, trace_id, parent_span_id, service_name, service_namespace,
    deployment_environment, span_name,
    start_time_unix_nano, end_time_unix_nano, duration_ms,
    outcome, status_code, status_message,
    attributes, events, has_gen_ai_attrs, has_dispatch_attrs
)
SELECT
    span_id, trace_id, parent_id, service_name,
    COALESCE(service_namespace, 'mcp-ecosystem') AS service_namespace,  -- backfill
    COALESCE(deployment_environment, 'unknown') AS deployment_environment,
    name AS span_name,
    CAST(start_time AS BIGINT) * 1000000 AS start_time_unix_nano,  -- ms -> ns
    CAST(end_time   AS BIGINT) * 1000000 AS end_time_unix_nano,
    duration_ms,
    CASE status WHEN 'ok' THEN 'success' WHEN 'error' THEN 'error' ELSE 'unset' END
        AS outcome,
    CASE status WHEN 'ok' THEN 'STATUS_CODE_OK'
                WHEN 'error' THEN 'STATUS_CODE_ERROR'
                ELSE 'STATUS_CODE_UNSET' END
        AS status_code,
    NULL AS status_message,
    attributes, events,
    FALSE AS has_gen_ai_attrs,
    FALSE AS has_dispatch_attrs
FROM spans
WHERE span_id NOT IN (SELECT span_id FROM spans_substrate);  -- idempotent

DROP TABLE IF EXISTS spans;  -- IF EXISTS guards against the "spans missing" case
```

**PR-A6.5 merge-gate test** (lives in `tests/integration/test_old_spans_table_migration.py`):

1. If `spans` exists, run the migration; assert row counts before/after on `spans_substrate` match.
2. If `spans` does not exist (the common case per the v3 agent read), assert the migration is a no-op and `DROP TABLE IF EXISTS spans` does not raise.
3. Both branches must pass; the test must exercise both via a parameterized fixture (empty-DB + populated-DB).

### 13.6 PR-A8 feature flag for rollback

`akosha/settings/akosha.yaml` adds (per §11.4 inline; §13.6 cites the same block):

```yaml
otel:
  receiver:
    trace_ingester_poller: true                # PR-A8 flips to false
    known_mcp_servers:                         # (also §11.4)
      - "mahavishnu"
      - "akosha"
      - "session-buddy"
      - "oneiric"
      - "crackerjack"
      - "bifrost-mcp"
  hotstore:
    spans_substrate_drop_old_table: false      # PR-A6.5 flips to true
  # v5 — operators pin the retention/archival settings §8.2 reads.
  spans_substrate:
    retention_days: 30
    retention_sweep_interval_hours: 6
    archival_target: null                       # S3 URL or filesystem path; see §8.2 for format
```

`akosha/observability/otlp_receiver.py` reads `otel.receiver.trace_ingester_poller` at lifespan via oneiric's layered config (`OTelSettings.trace_ingester_poller`); PR-A8 sets it to `false` to retire the poller. **Rollback** is a flag flip + restart; **never** a code revert. Consistent with `feedback-no-backwards-compat-pre-1.0.md`.

**Naming convention** (v4 normalization): all feature flags in v4 follow the `domain.subdomain.setting: bool` YAML convention; flat env-var-style names (v3's `feature_flag_otel_trace_ingester_poller`) are **replaced** — no env-var shim, no backwards-compat layer. The settings block is canonical; env-var overrides flow through oneiric's layered config loader, not as ad-hoc names.

---

## 14. PR integration tests required (every PR)

| PR | Required test(s) |
|---|---|
| PR-0a | `test_oneiric_substrate_table_create.py` (assert `spans_substrate` exists post-`initialize()`) |
| PR-0b | (no new test; existing oneiric compat covers) |
| PR-A1 | `test_namespace_bridge_dual_label.py` (assert `namespace.legacy_alias=bodai` emitted alongside `service.namespace=mcp-ecosystem`) |
| PR-A2 | `test_yoyo_migrations_e2e.py` (fresh `up`, idempotent re-`up`, sibling `.rollback.sql` `down`, idempotent re-`down`) |
| PR-A3 | `test_otlp_receiver_e2e.py` (full lifecycle, OTLP/gRPC + OTLP/HTTP); `test_substrate_lifespan_order.py` (`await conn.execute("DROP TABLE spans_substrate")` + close; assert `LifecycleError("spans_substrate_missing")`); **`test_spans_substrate_retention_sweep.py`** (v5: assert sweep deletes rows with `received_at_unix_nano < cutoff`; COPY to `archival_target` when set; cutoff-age metric emits; on COPY failure DELETE is skipped and `archival_failed` counter increments) |
| PR-A4 | `test_otlp_receiver_dlq.py` (bad row → DLQ; DLQ-write failure → DLQ-recovery metric + good rows still land in INSERT); **`test_canary_watcher_e2e.py`** (v5: 3 consecutive 30s emits produce 3 rows; `telemetry_receiver_canary_last_success_unix_nano` advances within 90s window via the §11.3 bridge; `canary_writes_failed_total` increments on `_handle_batch` regression; 2 missed emits surface P0-C condition; bridged-gauge identity test — assert `/metrics` exposes `canary_last_success_unix_nano`) |
| PR-A5 | `test_heartbeat_watcher_e2e.py` (seed 0 rows (expect `query_empty`); close DB (expect `query_threw` + P0-A suppressed); seed 2 consecutive absences (expect P0-A); empty roster → P0) |
| PR-A6 | `test_resource_validator.py` (rate-based spike threshold; allowlist honored; startup-burst rejection; sustained-pressure path) |
| PR-A6.5 | `test_old_spans_table_migration.py` (idempotent; `spans` empty → DROP no-ops) |
| PR-A7 | `test_service_namespace_bridge.py` (`test_dual_label_emitted_during_bridge` + `test_consumer_sweep_returns_zero_pre_merge`) |
| PR-A8 | `test_poller_retirement.py` (assert the lifespan does not construct `OtelTraceIngester` when the flag is off; the retired `AKOSHA_SKIP_OTEL_INGESTER` env var is read nowhere; the `OtelTraceIngester` class is still importable so rollback stays a flag flip) |

All `@pytest.mark.slow`; the fast feedback lane (`pytest -m "not slow"`) skips them. **`crackerjack run -v -f` is the merge gate.**

> **PR-A8 row corrected 2026-10-24.** The row previously read "assert
> `OtelTraceIngester` import gone", which contradicted §13.6, §13's
> PR-A8 row and §15's decisions log — all three of which say the flag
> *gates the import + lifespan start* and rollback is a flag flip, never a
> code revert. The class is retained behind the flag precisely so that
> rollback stays a config change; asserting the class is gone would have
> made the flag a lie. The row now asserts what §13.6 actually specifies.

---

## 15. Decisions log

| Decision | Choice | Rationale |
|---|---|---|
| Substrate home | **`oneiric/adapters/vector/duckdb_hot_store.py`** | ADR 017 names this as canonical; one PR vs many; substrate-managed access |
| DLQ is akosha-local, not substrate | §5.3 explicit | `_dlq_rows` is dead-letter for rejected substrate data, not telemetry itself |
| Migration framework | **none — inline `CREATE TABLE IF NOT EXISTS` at point of first use** | **v7 corrected.** v6 chose yoyo (raw SQL + sibling `.rollback.sql`). There is no yoyo in the Bodai fleet — not in akosha, not in oneiric, not in mahavishnu, which uses Alembic (`migrations/versions/V*.sql`). Building a yoyo runner would have introduced a third framework into a repo that has none, for a substrate ADR 017 assigns to oneiric. `CREATE TABLE IF NOT EXISTS` in `DuckdbHotStore.initialize()` is idempotent and runs on every substrate boot, so it covers fresh and pre-existing substrate files with nothing to sequence. The receiver's two operational tables (`_dlq_rows`, `_akosha_otel_receiver_state`) follow the same rule. Reversibility is a `git revert`; there is no partial-apply state to roll back. |
| `opentelemetry-proto` placement | `[project.dependencies]` (hard runtime dep) | Runtime-required; PEP 735 groups never auto-install and would fire `LifecycleError` |
| `ON CONFLICT (trace_id, span_id)` | **superseded 2026-10-23 → untargeted `ON CONFLICT DO NOTHING`** | cross-producer dedup correctness. The targeted form could not deliver it: §5.1's PK on `span_id` is narrower than the composite UNIQUE, so the PK always fires first and the targeted clause handles an unreachable constraint — a span_id-only collision raised on the hot path. Untargeted honours both, and leaves NOT NULL violations raising, preserving the table constraint as a backstop |
| `received_at_unix_nano` source | **receiver's `time.time_ns()`**, never the producer's | §15's "cardinal rule", now confirmed in code. Retention sweeps on this column; a producer clock offset either deletes spans before anything reads them or keeps them past retention. A queue-replayed batch is the same failure with no skew at all |
| Missing required fields | **no `"unknown"` sentinel**; absence propagates to the DLQ | A sentinel satisfies `REQUIRED_FIELDS` on every row, which makes `pre_validate` unreachable, leaves `_dlq_rows` permanently empty, and writes rows no read-path filter can match |
| Service identity source | **`ResourceSpans` attributes**, threaded into the per-span mapping | A protobuf `Span` has no `resource` field. A span-level lookup finds nothing, falls through to a default, and silently attributes every span to a service named `"unknown"` |
| Ingest writers' home | **`oneiric.DuckdbHotStore`**, inherited by akosha's `HotStore` | akosha's module is capped at 500 LOC to stay a thin subclass; ADR 017 puts `spans_substrate` ownership in oneiric; and writers beside the DDL they target cannot drift from it |
| DLQ error recovery | DLQ failure does NOT abort the batch; good rows still INSERT; metric emitted | Single failure mode shouldn't zero throughput |
| Heartbeat known-server roster | separate `known_mcp_servers` field, boot-populated | The per-cycle feed can't carry a roster; empty roster is its own P0 |
| Resource-attribute validator | rate-based (rolling 5m spike + 24h sustained) | v2's count/hour was misclassified by startup bursts and slow drift |
| PR-A8 rollback | `otel.receiver.trace_ingester_poller: bool` (settings YAML nested key) | Rollback is flag-flip + restart, never code revert; consistent with no-backcompat rule. v3 used a flat `feature_flag_otel_trace_ingester_poller` env-var style; v4 normalizes to nested-YAML per `akosha/settings/akosha.yaml` convention (no env-var shim). |
| Bifrost gateway UI value | `http://localhost:4318/v1/traces` | Substrate receiver's HTTP port |
| claude/qwen collector pipelines | out-of-scope for v3 (reclassified) | Sub-spec B or later spec decides whether to mirror through Akosha |
| Existing akosha `spans` table | PR-A6.5 migrates then drops (idempotent) | Don't leave orphan tables |
| **v5** Retention driver | `received_at_unix_nano`, not `start_time_unix_nano` | v4 set up the column but missed this — clock-skew producer values would otherwise be deleted/preserved incorrectly. Cardinal rule. |
| **v5** Archival-failure semantics | COPY failure → set `archival_succeeded=False`, skip DELETE | v4's DELETE-after-failed-COPY silently destroys data. Cold-sink errors (NFS, S3 IAM, ENOSPC) all gate on this. |
| **v5** Sweep task lifecycle | Try/except + observability (gauge + histogram + counter) | v4's happy-path sweep body silently halts on first error. The sweep itself is the only thing keeping §8.2 from running away; its liveness is operationally critical. |
| **v5** Canary Prometheus bridge | `CanaryState` → named gauge `telemetry.receiver.canary_last_success_unix_nano` | v4's P0-C alert referenced a Python field; PromQL can't read Python state. The bridge is the wire. |
| **v5** Canary alert expression | `time() * 1e9 - telemetry_receiver_canary_last_success_unix_nano > 90e9` | v4's `time_ns()` is non-standard PromQL; v5 uses `time() * 1e9` and pins the gauge name explicitly. |
| **v5** Index ordering | All four ordering indexes on `received_at_unix_nano DESC` | v4 only added the new index, leaving the original three on the unreliable column. v5 drops+recreates. |
| **v5** Sweep collision avoidance | Random 0-60s jitter + multi-pod advisory lock (deferred to writing-plans) | DuckDB file-lock + same-wall-clock sweep = silent pod death. |
| **v5** Naming convention | `domain.subdomain.setting: bool` (nested YAML only) | v3's flat `feature_flag_` prefix is fully replaced. One canonical form across §11.4, §13.6, Appendix C. |
| **v5** `phase="copy"` retention_sweep_failed label | **permanently dead** — COPY failures route to `archival_failed` (separate counter) instead of `retention_sweep_failed{phase="copy"}` | v5's inner COPY try/except swallows COPY errors before the outer except can route them. The outer except therefore only ever increments `phase="delete"`. Both labels remain in the contract for shape stability; `phase="copy"` never increments. |
| **v6** DDL verification footer | Every CREATE statement in §5.1 verified by re-running `scripts/verify_otel_ddl.py` against whatever `oneiric/uv.lock` pins; §5.1a carries the version, date, and result counts | v5 had 4 P0 DuckDB-execution issues (partial index WHERE, ALTER ADD CONSTRAINT, COPY filename param, ALTER ADD COLUMN with NOT NULL DEFAULT) that oneiric-specialist's live-repl verification caught. The audit footer makes verification a spec discipline, not a one-off. **v7 corrected it:** the v6 footer cited `duckdb==1.5.6` "per `mahavishnu/uv.lock`" — the wrong version *and* the wrong lockfile (ADR 017 puts the substrate in oneiric). A footer naming an unverified version is worse than none, because it reads as verification having happened. |
| **v7** Two PRs carry no implementation task | **PR-A2 (yoyo migrations) and PR-A6.5 (legacy `spans` migration) are dropped** | Both rest on premises the codebase contradicts, found by verifying against source rather than reading the spec. (1) There is no yoyo in the fleet — the migration-framework row above records what replaced it. (2) There is no `spans` table anywhere: `mahavishnu/ingesters/otel_ingester.py` flattens traces into `conversations`-shaped records through the inherited `DuckdbHotStore.insert()`. A repo-wide grep for `CREATE TABLE.*spans` returns only this spec. The PR table rows below and the §11.4a `akosha migrations` subcommand references are therefore **superseded** — the implementation plan records the reasoning in its Deferred items table. Nothing else depends on either PR landing. |
| **v6** UNIQUE CONSTRAINT inline in CREATE TABLE | Not via ALTER ADD CONSTRAINT | DuckDB `ALTER TABLE … ADD CONSTRAINT UNIQUE (…)` is unsupported (1.5.6: `NotImplementedException`; 2.0.0-dev: `DependencyException`). Inline `CONSTRAINT uq_span_identity UNIQUE (trace_id, span_id)` is the only path; it's required for `ON CONFLICT (trace_id, span_id)` to resolve. **Do not match on the exception type** — it is not stable across versions. |
| **v7** Constraint *name* is a declaration label | Query `duckdb_constraints()` by `(constraint_type, constraint_column_names)`, never by `uq_span_identity` | DuckDB normalises the declared name to `spans_substrate_trace_id_span_id_key`. The v6 DDL reads as if `uq_span_identity` were a stable handle; any code that looks the constraint up by that string finds nothing and silently concludes the dedup guarantee is absent. |
| **v6** Partial index — no WHERE clause | DuckDB doesn't support `WHERE` on CREATE INDEX (NotImplementedException on both 1.5.6 and 2.0.0-dev) | v5 had a `WHERE outcome IN ('success','error')` predicate that raised at first run. v6 drops the predicate; the read-side SELECT (sub-spec B §5.6) qualifies the outcome filter. |
| **v6** `received_at_unix_nano` inline | Not via ALTER ADD COLUMN with NOT NULL DEFAULT | DuckDB `ALTER TABLE ADD COLUMN NOT NULL DEFAULT (…)` is unsupported (1.5.6: `Parser Error: Adding columns with constraints not yet supported`; 2.0.0-dev: `DependencyException`). Inline the column in CREATE TABLE; the constraint then backfills any existing rows at INSERT time only. |
| **v6** COPY filename path | Inline-string (with regex validation at settings-load) | DuckDB `COPY (SELECT …) TO ?` is unsupported (1.5.6: `INTERNAL Error: Unsupported parameter type for filename`; 2.0.0-dev: `InvalidInputException`). Inline the validated path; ARCHIVAL_TARGET_RE ensures only safe paths reach the sweep body. |
| **v6** Sweep DML row count | `result.rowcount` (DuckDB Python cursor contract) | v5 used `result.fetchone()[0]` which raises `TypeError` on DML cursors (None[0]). Every sweep iteration permanently incremented `retention_sweep_failed{phase="delete"}` as a false alarm. **Version-sensitive (v7):** verified as returning the affected count on 2.0.0-dev, but it returned `-1` on 1.5.6. Correct only because oneiric currently pins 2.0.0-dev; a oneiric downgrade silently breaks the sweep's count. |
| **v6** Sweep liveness ambiguity | `sweep_first_started_unix_nano` (set once, never reset) | v5 collapsed "sweep has never run on this pod" and "sweep is frozen on archival" into the same `sweep_last_completed_unix_nano == 0` signal. Operators couldn't disambiguate. v6 adds a separate gauge for the "never started" state, with the `sweep_retention_late` alert gated by `sweep_first_started_unix_nano > 0`. |
| **v6** Canary "succeeded" definition | `BatchResult(ok=1, deduped=0)` exactly | Multi-pod races had undefined behavior — v5 let implementers pick between double-counting successes and under-counting them. v6 pins option (b): succeed iff exactly one row INSERTed, with losers tracked via `canary_writes_rejected_total` (its own counter, not a `canary_writes_failed_total` label). |
| **v6** Canary bridge liveness | Try/except + retry-with-backoff + `bridge_failed_total` counter + P0-D alert | v5 had a `while not stop_event.is_set(): await stop_event.wait(10)` body with no exception handling — any uncaught exception killed the bridge forever until process restart. v6 wraps the body, increments a counter on failure, adds a `receiver_canary_bridge_dead` P0-D alert, and clears the counter on success. |
| **v6** Canary stub at PR-A3 | `OTLPReceiver.run_canary_emitter()` ships as a no-op at PR-A3; PR-A4 swaps the body | §6 lifespan snippet was a forward-reference that called `run_canary_emitter` before PR-A3 had any impl. v6 splits the lifespan into PR-A3-stub and post-PR-A4-final states; the stub avoids NameError and the §6 snippet compiles against PR-A3 reality. |
| **v6** `asyncio.sleep` jitter is cancelable | `Task.cancel()` interrupts `asyncio.sleep(N)` at the next await point | The v5 reviewer's P1 #3 claimed "jitter blocks graceful shutdown for up to 60s" — technically wrong. `asyncio.gather(…, return_exceptions=True)` propagates cancellation cleanly. The jitter is interruptible; no change needed beyond a comment. |
| **v7** `ARCHIVAL_TARGET_RE` regex widened | Match XDG/macOS/Docker/log roots via the `path_resolver.py:90-220` defaults | v6 regex only matched `/var/...` and S3; every default akosha installation failed validation. Operator got an `AssertionError` at sweep runtime, not a fail-fast at config-load. v7 covers the four real storage roots. |
| **v7** `set_shared_otel_receiver` is NEW code from PR-A0b | Not a mirror of `set_shared_hot_store` that exists today | The spec repeatedly referenced `set_shared_otel_receiver` as a mirror of `set_shared_hot_store`; v6 comment implied it already shipped. It doesn't — PR-A0b introduces it. PR-A0b's deliverable also extends `clear_shared_services()` to nil the new module global. |
| **v7** `clear_shared_services` extension | 3 globals in `akosha/mcp/server.py` after PR-A0b (`_shared_hot_store`, `_shared_kg_builder`, `_shared_otel_receiver`) | Without the explicit nill-out, test isolation regresses: `create_app()` twice leaks the prior singleton. |
| **v7** §6 lifespan is FastMCP `@asynccontextmanager`, not Starlette | `async def lifespan(server): yield {"server": server, ...}` (`akosha/mcp/server.py:397-420`) | v6 used `async def lifespan(app): yield` (bare `yield`, parameter `app`) — wrong shape for the existing `@asynccontextmanager` decoration. Implementer copy-paste would break FastMCP's `_lifespan_proxy`. |
| **v7** `stop_event` is an explicit positional arg | Declared at lifespan scope, passed to retention_sweep + canary_metrics_bridge | v6 referenced `stop_event` as a free variable in the bridge body; spec never pinned where it came from. |
| **v7** `HealthFeedState("name")` is not valid Python | `HealthFeedState(entities_count=…, last_updated_timestamp=…, …)` (kwarg-only dataclass at `mcp_common.health.feed`) + a module-level `_known_mcp_servers_roster: list[str]` for the roster itself | The pos-arg notation crossed §11, §11.4, §13.6, §15 (four sites). Implementers copy-pasting hit a TypeError. Spec replaces with the kwarg shape + a separate roster list. |
| **v7** PR-A8 retires `AKOSHA_SKIP_OTEL_INGESTER` env var | Remove the `if not _env_truthy("AKOSHA_SKIP_OTEL_INGESTER"):` block at `akosha/mcp/server.py:627` | v6's §15 "no env-var shim" decision was incorrect for this var — operators with launchd plists setting `=1` get the poller silently re-enabled post-PR-A8. Pre-1.0 no-backcompat rule applied retroactively. |
| **v7** CLI Typer hierarchy | **superseded 2026-10-27 → no CLI ships; the operator interface is the metrics route + the MCP tools + the settings file** | v7 required new `admin`/`otel`/`retention` and `migrations` top-level sub-apps on `akosha.cli.app`, because v6 referenced commands (`akosha admin otel retention manual-run`, `akosha migrations up`) that don't exist. Two reasons that requirement is dropped: (1) there is no migration framework in the fleet — the migration-framework row above records what replaced it, and a `migrations` CLI would wrap a framework that does not exist; (2) the sweep is a self-driving lifespan task, so the operator needs to SEE it (metrics route) and change its horizon (settings file), not drive it from a shell. §11.4a now carries the operator-interface table. **v9 (2026-10-27) adds the one operation that did need a trigger — `mcp__akosha__force_retention_sweep` — and the reason it is an MCP tool rather than a CLI is architectural, not a preference: the substrate is IN-MEMORY inside the running akosha process and the receiver is a process-local singleton, so a CLI subprocess could not have reached either.** |
| **v10** Producer reporting lives in mcp-common's launcher | `mcp_common.server.launcher.launch` installs the tracer provider and starts the liveness emitter; `component_name` is the service identity | Every core service already starts through that launcher and already passes a `component_name` equal to its roster entry, so this is ONE seam for the whole fleet rather than five copies — and no second naming scheme to keep in step with the roster. The alternative (a per-service exporter setup) would have left the roster and the producers free to drift apart again, which is exactly how the roster came to name five services that had never reported a span. |
| **v10** A liveness span, not a request span, is the heartbeat | `_service_liveness`, emitted every 30s by the producer | An MCP server emits a span when somebody calls a tool, so request-driven spans cannot distinguish an idle service from a dead one — a 60s window with a two-cycle threshold fires on a healthy idle fleet by construction. Measured: mahavishnu was alive and reporting spans that were 195s old, and the watcher still read it as absent. The liveness span mirrors the §11.3 canary one layer up: the canary proves the write path, the liveness span proves the export path. |
| **v10** The producer exporter is opt-in | `configure_producer_tracing` installs nothing unless `OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`) is set | The launcher is shared with the standalone MCP servers outside the Bodai core set. Making the wiring unconditional would have every one of them start exporting to the substrate without an operator asking for it. The plist is the opt-in, and the plist is where the destination lives. |
| **v10** An explicit exporter endpoint is the COMPLETE URL | The shared helper normalises a base URL by appending `/v1/traces` | The OTLP/HTTP exporter treats an explicit endpoint as the full URL including the signal path, while the generic environment variable gets the path appended. Session-Buddy handed it the base URL, and every batch came back `404 Not Found` — with no metric anywhere, because a rejected request and a request that was never made look the same from the sender's side. |
| **v7** Spec vs codebase alignment priority | After v6, run multi-agent ensemble with at least one domain-specialist lens against the actual codebase (`akosha-specialist`, `mcp-integration-expert`, `crackerjack-specialist`) | The 4-round review (v3→v4→v5→v6→v7) found 9 P0s that all three codebase-illiterate lenses missed — every one surfaced by direct read of `akosha/cli.py`, `akosha/storage/path_resolver.py`, or `akosha/mcp/server.py`. Specialist lenses for component integration are now a hard requirement, not optional. |

## 16. References

- Parent spec: `docs/specs/2026-10-19-bodai-event-sourced-otel-architecture.md` (sub-spec B; pending rewrite against this substrate — see §17 for scope)
- v1 spec (archived): `docs/specs/.archive/2026-10-19-bodai-akosha-otel-substrate.md`
- v2 spec (archived): `docs/specs/.archive/2026-10-19-bodai-substrate-otel-v2.md`
- ADR 017 (cited inline in `oneiric/adapters/vector/duckdb_hot_store.py:23` docstring)
- Oneiric substrate DDL anchor: `oneiric/adapters/vector/duckdb_hot_store.py:130-185`
- Akkosha lifespan pattern: `akosha/mcp/server.py:516-661`
- Akkosha existing health-feed construction: `akosha/mcp/server.py:1094-1101`
- Existing `OtelTraceIngester` (PR-A8 retirement target): `akosha/ingestion/otel_ingester.py`
- Akkosha fitness analyzer (preserved, MCP-poll): `akosha/processing/fitness_analyzer.py` + `akosha/mcp/tools/fitness_tools.py`
- Pre-1.0 no-backcompat rule: `feedback-no-backwards-compat-pre-1.0.md`
- **PR-A3 port-move source (corrected 2026-10-21):** Grafana Alloy, `/usr/local/etc/grafana-alloy/config.alloy` (Homebrew service `sh.brew.grafana-alloy.plist`). NOT `mahavishnu/config/otel-collector-config.yaml`, which is not running — see §13.1 and `docs/decisions/2026-10-21-otel-substrate-port-ownership.md`.
- Producer exports to repoint at PR-A3: `~/.zshrc:183-195`
- Dead 2026-09-28 relay (must be corrected or deleted at PR-A3): `mahavishnu/settings/local.yaml:4-19`
- yoyo-migrations docs: <https://ollycope.com/software/yoyo/latest/>
- OTLP protocol: <https://opentelemetry.io/docs/specs/otlp/>
- OpenTelemetry GenAI semantic conventions: <https://github.com/open-telemetry/semantic-conventions-genai>

## 17. Cross-spec rewrite scope (sub-spec B / PR-B deliverable)

This section enumerates **exactly what the parent spec needs to change** so PR-B (sub-spec B's rewrite) isn't undersized. Each row is a specific edit against `docs/specs/2026-10-19-bodai-event-sourced-otel-architecture.md` (the parent spec).

| Parent spec section | What's wrong | Rewrite to |
|---|---|---|
| §4.1 Topology diagram | References `HotStore.spans` | `HotStore.spans_substrate` |
| §5.2 `OTelSettings` resource defaults | Underspecified | Cite v3 §6.4 / §6.5; same conventions, different substrate |
| §5.5 migration SQL | ALTERs `spans` (table doesn't exist); references columns that don't exist | Drop the ALTER entirely; substrate DDL is in oneiric per v3 §5.1 |
| §5.6 projection SQL | `WHERE timestamp > now() - ...` (column doesn't exist); `parent_id` (column doesn't exist); reads from `spans` (table doesn't exist) | `WHERE received_at_unix_nano > :cutoff_unix_nano`; `parent_span_id`. **Corrected 2026-10-20 — this row previously said `start_time_unix_nano`, which contradicts this spec's own §8.2 cardinal rule.** `start_time_unix_nano` is producer-supplied and drift-prone (§8.2: "silently corrupts every index that orders by it"), and a read filtered on it would disagree with what the retention sweep actually kept. `received_at_unix_nano` is BIGINT epoch nanos, so there is no interval arithmetic: bind a precomputed cutoff integer. The read path in `docs/specs/2026-10-20-bodai-otel-substrate-read-path.md` §4.2 already implements this; PR-B inherits that query rather than re-deriving it.an_id` |
| §6.1 receiver section | Claims `set_shared_otel_receiver` already exists | Rename to reflect v3's actual location (akosha/observability/otlp_receiver.py) |
| §7.2 P0-A | References `mcp_tool_call` as the roster source | Cite v3 §11 (separate `known_mcp_servers` field) |
| §7.4 PR-A7 / default-flip | Lacks consumer-sweep gate | Cite v3 §10.1 + §10.2 (enumerated consumers + CI gate) |
| §8 References | Cites `akosha/observability/fitness_analyzer.py` in wrong path | Path: `akosha/processing/fitness_analyzer.py` + `akosha/mcp/tools/fitness_tools.py` |
| (Section 5.1) | Where undefined | Add: 7 gen_ai_* columns land in substrate (parent §5.5 spec'd them — v3 §5.1 has them) |

PR-B owns these edits. **The parent spec's projection SQL won't execute against v3's substrate as currently written** — implementers reading PR-B between now and PR-B merge will see broken behavior.

---

## Appendix A — yoyo vs alternatives (unchanged from v1)

| Aspect | yoyo | alembic | oneiric substrate |
|---|---|---|---|
| Dependencies | 1 small package | SQLAlchemy + alembic | n/a |
| Migration format | Raw SQL + sibling .rollback.sql | Python + autogenerate | n/a |
| Reversibility | First-class (`.rollback.sql` sibling) | First-class | n/a |
| HotStore grade | Compatible (raw SQL → DuckDB) | Compatible (uses SA models) | n/a |
| Convention | `<id>.<name>.sql` + `<id>.<name>.rollback.sql` | Python module | n/a |

## Appendix B — Receiver code shape (refined)

```python
# akosha/observability/otlp_receiver.py
from __future__ import annotations
import asyncio, logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from akosha.storage.hot_store import HotStore

logger = logging.getLogger(__name__)


class ReceiverError(Exception): ...
class BatchRejected(ReceiverError): ...
class RowValidationError(ReceiverError):
    def __init__(self, field: str | None = None, reason: str = "unspecified", detail: str | None = None):
        self.field = field
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}:{field}:{detail}")

class DLQWriteError(ReceiverError): ...


@dataclass
class BatchResult:
    ok: int = 0
    deduped: int = 0
    rejected: int = 0
    dlq_failed: int = 0
    errored: int = 0


class OTLPReceiver:
    MAX_BATCH_SIZE         = 512
    MAX_RETRIES            = 3
    BACKOFF_BASE_SECONDS   = 1.0
    BACKOFF_MAX_SECONDS    = 8.0
    QUEUE_MAX_DEPTH         = 2048
    PROMETHEUS_PORT         = 9464
    GRPC_PORT               = 4317   # v7 addition — see §13.1
    HTTP_PORT               = 4318   # v7 addition — see §13.1

    REQUIRED_FIELDS = frozenset({
    "service_name",
    "service_namespace",   # v4 — see §7.1 inline note
    "span_name",
    "start_time_unix_nano",
})
    ENUM_FIELDS = {"status_code": {"STATUS_CODE_UNSET", "STATUS_CODE_OK", "STATUS_CODE_ERROR"}}

    def __init__(self, hot_store: HotStore) -> None:
        self._hot_store = hot_store
        self._stop = asyncio.Event()
        self._sem = asyncio.Semaphore(4)

    async def start(self) -> None:
        if not await self._hot_store.table_exists("spans_substrate"):
            raise LifecycleError("spans_substrate_missing")
        # bind :4317 (gRPC), :4318 (HTTP), start :9464 (Prometheus); increment receiver_started_total

    async def stop(self) -> None: ...

    def pre_validate(self, span: dict) -> RowValidationError | None:
        for f in self.REQUIRED_FIELDS:
            if not span.get(f):
                return RowValidationError(field=f, reason="not_null")
        for f, allowed in self.ENUM_FIELDS.items():
            v = span.get(f)
            if v is not None and v not in allowed:
                return RowValidationError(field=f, reason="enum")
        return None

    def normalize_attributes(self, span: dict) -> dict:
        # one-line dict comprehension: dotted → underscore
        ...

    async def _handle_batch(self, batch) -> "ExportTraceServiceResponse":
        result = BatchResult()
        clean, dlq = [], []
        for span in batch.spans:
            try:
                err = self.pre_validate(span)
            except Exception as exc:
                err = RowValidationError(reason="validator_threw", detail=repr(exc))
                self._metric_row_rejected.inc(reason="validator_threw")
            if err:
                dlq.append((err, span))
                result.rejected += 1
            else:
                clean.append(span)

        # DLQ write — wrapped; failure does not abort
        if dlq:
            try:
                await self._dlq_insert(dlq)
            except Exception as exc:
                result.dlq_failed = len(dlq)
                for err, span in dlq:
                    logger.error("dlq_write_failed", reason=err.reason, span_id=span.get("span_id"))
                self._metric_dlq_insert_failed.labels(reason="exception").inc(amount=result.dlq_failed)

        # Batch INSERT with retry
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                inserted, deduped = await self._hot_store.insert_spans_substrate(clean)
                result.ok, result.deduped = inserted, deduped
                break
            except IntegrityError as exc:
                if attempt == self.MAX_RETRIES:
                    result.errored = len(clean)
                    self._metric_batch_inserted.labels(outcome="err").inc(amount=result.errored)
                    return self._partial_success_response(batch, result)
                await asyncio.sleep(min(self.BACKOFF_BASE_SECONDS * (2 ** attempt), self.BACKOFF_MAX_SECONDS))

        # Emit batch outcome metric — v4: every inc() uses `.labels(...).inc(amount=N)`;
        # prometheus_client treats `n=` or `N=` as unrecognized kwargs, so v3's
        # `.inc(outcome="ok", n=result.ok)` silently incremented by 1 (or raised
        # TypeError on a strict client). Operators page on the actual row count,
        # not the batch count.
        if result.ok == len(clean):
            self._metric_batch_inserted.labels(outcome="ok").inc(amount=result.ok)
        elif result.ok == 0:
            self._metric_batch_inserted.labels(outcome="dedup").inc(amount=result.deduped)
        else:
            self._metric_batch_inserted.labels(outcome="partial").inc(amount=result.ok + result.deduped)
        if result.rejected:
            self._metric_batch_inserted.labels(outcome="validation_failed").inc(amount=result.rejected)
        if result.dlq_failed:
            self._metric_batch_inserted.labels(outcome="dlq_write_failed").inc(amount=result.dlq_failed)

        return self._success_response(batch, result)
```

## Appendix C — Receiver shutdown sequence (operator procedure)

**v8 — rewritten 2026-10-27.** The v7 procedure assumed a migration
framework and a `hot-store` CLI. Neither exists: §15 chose inline
`CREATE TABLE IF NOT EXISTS` at the point of first use, and akosha's CLI
ships only `shell`, `start`, `version`, `info`, `modes` and the `mcp`
group.

**The substrate is in-memory.** `hot.backend` is `duckdb-memory` with
`path: ":memory:"`, so `spans_substrate` lives in the akosha process.
Stopping the process DOES drop every row — there is nothing to preserve
across a restart, and no `down` to run. The table is recreated on the
next boot by oneiric's `DuckdbHotStore.initialize()`.

So the procedure is short:

1. Stop akosha's MCP server (the lifespan shutdown drains the receiver).
2. The substrate is gone with the process. To inspect what was in it
   before stopping, use the read path:
   - `mcp__akosha__search_spans` — the rows
   - `mcp__akosha__spans_summary` — the counts per pair
3. The receiver's two operational tables (`_dlq_rows`,
   `_akosha_otel_receiver_state`) are created by the receiver's
   `_ensure_operational_tables` call and are likewise in-memory. There
   is nothing to drop, and no `migrations down` to run.
4. The substrate DDL itself (`spans_substrate`) is substrate-managed and
   has no `down`. If it is ever missing, the receiver's `start()` fails
   loud with `LifecycleError("spans_substrate_missing")` — no silent boot
   is possible.
5. Restart akosha. The receiver recreates what it needs and re-binds
   `:4317`/`:4318`.

**PR-A8 has no `down`.** PR-A8 flips `otel.receiver.trace_ingester_poller`
in `akosha/settings/akosha.yaml` to `false`. Rollback is
`trace_ingester_poller: true` + restart.

## Appendix D — `OBSERVABILITY__OTLP_ENDPOINT` env var change

Documented previously (and dead as of 2026-10-21 — see correction below):
```bash
MAHAVISHNU_OBSERVABILITY__OTLP_ENDPOINT=http://localhost:14317
```

This was intended to map to the relocated `otlpclaude`/`otlpqwen` analogue or the off-Akosha collector.

**Corrected 2026-10-21.** The `:14317` target named above does not
exist — the 2026-09-28 relay at `/tmp/otel_relay.py` is gone and nothing
listens on `:14317`/`:14318`. The env var is also unset in the current
shell, so this is a documented-but-dead configuration rather than a live
one. Two consequences:

1. **The env-var change IS part of PR-A3.** With §13.1 as corrected, the
   substrate takes the canonical ports, so Mahavishnu's exporter points at
   `http://127.0.0.1:4318` — the HTTP port, not `:4317`, which is gRPC.
   This is a required step of the same cutover as the Alloy move, not the
   out-of-scope producer-side concern the pre-v7 draft assumed. The
   producer-side *sampling* question remains out of scope (see the
   deferred PR-B prerequisite).
2. **`settings/local.yaml:4-19` must be corrected or deleted at PR-A3.** It
   still documents the dead relay topology and will otherwise send the next
   operator down a path that no longer exists.
