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
                    │  ├── /metrics on :9464                    │
                    │  └── Prometheus counters emitted          │
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
- `INSERT INTO spans_substrate (…) ON CONFLICT (trace_id, span_id) DO NOTHING` resolves against the inline CONSTRAINT, and a replayed `(trace_id, span_id)` is a genuine no-op (row count unchanged) ✓
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
# LifecycleError is imported from mcp-common — substrate-bound starts raise
# it when boot preconditions fail. Confirmed exported at PR-0b commit time
# (mcp-common source: it is defined in `mcp_common.errors` and re-exported
# from `mcp_common.__init__`). If you rebase against a mcp-common tag
# older than the bridge release that introduced the import path, pin
# `mcp-common>=0.40` in your PR description.
from mcp_common.errors import LifecycleError

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

```python
class OTLPReceiver:
    MAX_BATCH_SIZE: int          = 512
    MAX_RETRIES:    int          = 3
    BACKOFF_BASE_SECONDS: float  = 1.0
    BACKOFF_MAX_SECONDS:   float = 8.0
    QUEUE_MAX_DEPTH:    int      = 2048
    PROMETHEUS_PORT:     int      = 9464

    async def start(self) -> None:
        """Lifespan-invoked. Asserts HotStore.spans_substrate_table exists
        (LifecycleError if absent), binds :4317 (gRPC) + :4318 (HTTP),
        starts :9464 (Prometheus), increments receiver_started_total."""

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

Prometheus listener bound to `:9464`:
- `telemetry.receiver.batch_inserted{outcome}` (counter — `.inc(amount=N)` per batch per outcome; `n` is NOT a label, it is the increment; v3 had this wrong)
- `telemetry.receiver.batch_size` (histogram, log scale)
- `telemetry.receiver.receiver_started_total` (counter)
- `telemetry.receiver.row_rejected{reason,field}` (counter — labeled)
- `telemetry.receiver.dlq_insert_failed{reason}` (counter — labeled; `.inc(amount=N)` where N is the count of rows whose DLQ write failed)

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
| Grafana dashboards | `mahavishnu/config/grafana/dashboards/bodai/*.json` | platform-team |
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
| `receiver_canary` | Per-cycle observation from `_canary_metrics_bridge` (`last_canary_success_unix_nano`, `bridge_failed_total`) | P0-C alert + P0-D alert |

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

# 2. Inspect known_mcp_servers
akosha admin heartbeat registry ls

# 3. Verify spans_substrate (receiver is the substrate's write path)
tail -n 200 ~/.akosha/logs/observability/otlp_receiver.log | grep -i "lifecycle\|spans_substrate"

# 4. Read receiver state
akosha hot-store exec "SELECT * FROM _akosha_otel_receiver_state"

# 5. Verify spans_substrate present
akosha hot-store inspect --table spans_substrate
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

### 11.1.5 Retention sweep failure (v6)

`retention_sweep_failed{phase="delete",reason}` counter > 0 OR `sweep_retention_late` alert firing (v6 — alert is gated by `sweep_first_started_unix_nano > 0` so a never-run sweep doesn't page). Disambiguate which state you're in before action:

```bash
# 1. Distinguish "never ran on this pod" from "frozen on archival":
curl -fsS http://localhost:9464/metrics | grep -E "telemetry_receiver_sweep_(first_started|last_completed)_unix_nano"
# Both 0           => sweep has never run (likely operator just deployed)
# first_started > 0, last_completed = 0 => sweep has run but failed (most recent cycle)
# first_started > 0, last_completed > 0 => sweep is healthy; check row count trend instead (see §11.1.6)

# 2. If sweep has run, identify which phase:
curl -fsS http://localhost:9464/metrics | grep retention_sweep_failed
# v6: phase="copy" never increments (COPY failures route to archival_failed instead);
# phase="delete" fires on DuckDB IO errors inside the DELETE branch.

# 3. If phase="delete" / DuckDB IO:
#     Most common: two Akosha pods race the sweep; one holds the file lock, the other fails.
#     Failing pods should clear at the next 6h window. If alerts persist >12h, restart
#     one pod at a time.

# 4. Manual recovery (v6 — DO NOT use the bare SQL command; use the CLI subcommand):
akosha admin otel retention manual-run --retention-days 30 --dry-run
# (prints the SQL it would execute + the predicted deleted-row count, prompts confirm)
akosha admin otel retention manual-run --retention-days 30 --apply --confirm "delete rows older than 30 days"
# (typed-phrase confirmation; the regex-validated archival_target path is computed
# internally so a fat-fingered shell arithmetic can't drop hot data)
```

### 11.1.6 Cardinality alarm (v6)

`spans_substrate_row_count_high` alert firing:

```bash
# 1. Use v6's two-gauge disambiguation (§11.1.5)
curl -fsS http://localhost:9464/metrics | grep -E "telemetry_receiver_sweep_(first_started|last_completed)_unix_nano"
# AND row count trend (the substrate's row count, sampled over time):
akosha admin otel retention cardinality-report

# 2. If sweep is alive (last_completed > 0, recent) AND row count climbing:
#     Lower retention_days OR raise archival_target via:
akosha admin otel retention config set --retention-days 14 --reload
# (CLI is dry-run by default; --apply required for mutation; receiver reads
#  the new value on next sweep cycle without process restart)

# 3. If sweep is stale (last_completed > 12h old) AND first_started > 0:
#     See §11.1.5 step 3 (DuckDB IO / multi-pod race) or §11.1.7 (archival).

# 4. If first_started == 0: sweep has never run (boot just completed; wait 1 cycle).
```

### 11.1.7 Archival-loss prevention: COPY-failure skips DELETE (v6)

If `archival_failed{reason}` > 0:

```bash
# 1. Diagnose the COPY failure
tail -n 200 ~/.akosha/logs/observability/otlp_receiver.log | grep archival_target_write_failed | tail -10
# Common causes:
#   NFS:                     mount dropped → remount; sweep retries next cycle
#   S3 IAM:                  aws iam get-access-key-last-used; rotate to active key
#   S3 bucket:               aws s3 ls $ARCHIVAL_TARGET (validate bucket exists)
#   Local filesystem full:   df -h $ARCHIVAL_DIR; archive target needs more space
#   Path not matching §8.2 ARCHIVAL_TARGET_RE: settings change refused at
#                                       config-load time; fix the YAML to a valid path

# 2. After fix, force one sweep cycle manually OR wait for next 6h:
akosha admin otel retention sweep-once
# (Sweep uses the same _spans_substrate_retention_sweep body; safe to invoke
#  manually — the lifespan task will also resume on the next interval.)

# 3. Verify recovery: archival_last_success_unix_nano advances within 6h.
curl -fsS http://localhost:9464/metrics | grep archival_last_success_unix_nano
```

### 11.3 Synthetic canary span (v4 addition; ops P0)

The heartbeat watcher verifies the substrate is **queryable** (P0-A / P0-B). It does not verify the **receiver writes succeed end-to-end**. A broken `_handle_batch` (serializer bug, class-not-found, DLQ permission error after a §6.2 try/except swallowed the error) lets `/health` return green indefinitely while every producer's spans silently drop. No "observability of the observability."

v4 adds a synthetic canary: the receiver (or, more cheaply, the lifespan) emits a deterministic marker span every 30s and tracks the time of the last successful end-to-end write into the substrate.

**Canary spec** (PR-A3 ships the lifespan task; PR-A4 wires the metric + alert):

- `service_name = "_receiver_canary"`
- `span_name = "_canary_substrate_write"`
- `start_time_unix_nano = time.time_ns()`
- `attributes = {"_canary": true, "_canary_version": "1"}`
- Attempted every `CANARY_EMIT_INTERVAL_SECONDS = 30` (default)
- INSERT goes through the same `_handle_batch` → `insert_spans_substrate` path the production spans use — **defends against partial-deploy code paths** (a code change that breaks the live INSERT but leaves `_dlq_insert` working would otherwise pass silently).

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
    bridge_failed_total:             int = 0   # v6: bridge body raised (liveness)
```

**"Succeeded" definition (v6 — pinned to remove ambiguity for multi-pod deployments):**

A canary write is **succeeded** iff `_handle_batch` returns `BatchResult(ok=1, deduped=0)` — i.e. exactly one row INSERTed (no exception, no UNIQUE-CONSTRAINT rejection). With multiple Akosha pods racing the canary emit, only one pod per cycle meets this bar; the others' INSERTs return `BatchResult(ok=0, deduped=N-1)` (or hit the §6.2 DLQ for bad rows), and they increment `canary_writes_failed_total{reason="duplicate_constraint"}` instead of `canary_writes_succeeded_total`. Without this pin, a multi-pod deployment either silently double-counts successes (option a) or silently under-counts them (option b) — both are misleading. Decided: **option b is the contract**, with explicit `canary_writes_rejected_total` as the positive signal that the loser-pod's constraint-rejection registered.

**PromQL bridge (v6 — wires the dataclass state to a Prometheus gauge surface AND has liveness)**:

```python
# PR-A4 — lifespan task; bridges CanaryState -> /metrics on :9464.
# v7: explicit `stop_event` positional arg (was free variable in v6).
# v6: wraps the loop body in try/except; transient failure does NOT kill the task.
# Bridge alive invariant: retrying the same logic on the next iteration is acceptable;
# killing the bridge silently keeps canary_last_success_unix_nano frozen.
async def _canary_metrics_bridge(
    stop_event: asyncio.Event,
    receiver: "OTLPReceiver",
):
    backoff = 1.0
    while not stop_event.is_set():
        await stop_event.wait(10)
        try:
            state = receiver.canary_state   # CanaryState
            last_success = state.last_canary_success_unix_nano or 0
            receiver._metric_canary_last_success_unix_nano.set(last_success)
            # Note: write-side counters incremented by _canary_writer at INSERT time
            # (BatchResult.ok / BatchResult.dlq_failed / BatchResult.errored branches)
            # — bridge is observation only; never increments counters itself.
        except Exception as exc:
            receiver._metric_bridge_failed_total.inc()
            logger.exception("canary_metrics_bridge_failed",
                             retry_after_seconds=backoff)
            await stop_event.wait(backoff)   # backoff up to 60s on consecutive failures
            backoff = min(backoff * 2, 60)
            continue
        backoff = 1.0   # reset on success
```

Or the cleaner Prometheus approach: a custom `Collector` registered against the `prometheus_client.REGISTRY` whose `collect()` reads `CanaryState` and yields the metrics on demand. PR-A4 picks one and pins it; either way, **`canary_writes_rejected_total{reason="duplicate_constraint"}` is its own counter, not a label on `canary_writes_failed_total`** (constraint rejection is not an exception — distinct metric cardinality).

**Prometheus surface** (PR-A4 contract — every name written by `canary_watcher.py`):

- `telemetry.receiver.canary_last_success_unix_nano` (gauge; `last_canary_success_unix_nano`)
- `telemetry.receiver.canary_writes_attempted_total` (counter; monotonically incremented)
- `telemetry.receiver.canary_writes_succeeded_total` (counter; **v6: ok=1 ∧ deduped=0 only**)
- `telemetry.receiver.canary_writes_failed_total{reason}` (counter; `reason` = exception class name; v6 no longer increments on `duplicate_constraint`)
- `telemetry.receiver.canary_writes_rejected_total` (counter; **v6; incremented on `BatchResult(ok=0, deduped>0)`**)
- `telemetry.receiver.bridge_failed_total` (counter; **v6; incremented on bridge-body exception; P0-D alert**)

**P0-C alert** (corrected — v4 used `time_ns()` which is non-standard PromQL, and the LHS referenced a Python dataclass field; v5 fixes both; v6 keeps the fix):

```
ALERT receiver_canary_stale
  for 90s
  expr: time() * 1e9 - telemetry_receiver_canary_last_success_unix_nano > 90e9
  annotations:
    summary: "Receiver has not written a successful canary span in 90s"
    runbook_url: "docs/specs/2026-10-19-bodai-substrate-otel-v6.md#113-synthetic-canary-span-v4-addition-v5-hardened-v6-canary-bridge-liveness"

ALERT receiver_canary_bridge_dead
  for 5m
  expr: increase(telemetry_receiver_bridge_failed_total[5m]) > 0
    AND increase(telemetry_receiver_canary_writes_attempted_total[5m]) > 0
  annotations:
    summary: "Canary metrics bridge has failed in the last 5 minutes while canary writes are still being attempted"
    runbook_url: "docs/specs/2026-10-19-bodai-substrate-otel-v6.md#113-synthetic-canary-span-v4-addition-v5-hardened-v6-canary-bridge-liveness"
```

PromQL notes:
- `time()` returns Unix seconds; `time() * 1e9` is Unix nanoseconds. v4 had `time_ns()`, which PromQL doesn't define; the alert would have been syntactically invalid in strict parsers and surfaced a parse error.
- The LHS is now the Prometheus gauge name (every Prometheus alert MUST address scraped metric names; referencing Python `CanaryState.last_canary_success_unix_nano` would evaluate `null > 90e9`, never firing). With the v5 bridge, the gauge is populated at every Prometheus scrape.

P0-C catches:
- `INSERT` path regressions (the §6.2 try/except would have hidden a silently-failing batch).
- `start()` succeeded but `_handle_batch` doesn't (e.g., a span class renamed without aliasing, JSON serializer accidentally returns `None` for `attributes`).
- DLQ-flood scenarios where good rows stop landing.
- Cold-start of substrate (the first canary might be slow; the P0 only fires after 90s).
- The bridge itself is dead (Prometheus scrapes `:9464/metrics` and gets no `canary_last_success_unix_nano` — alerts on a stale gauge vs. no gauge at all is the difference between "broken canary writes" and "broken wiring"; both are P0-C).

**Duplicate-suppression**: `INSERT INTO spans_substrate (…attributes JSON…) ON CONFLICT (trace_id, span_id) DO NOTHING` — the canary uses a deterministic `trace_id = "_canary"` and `span_id = "_canary_<unix_time_ns>"` so duplicate canaries don't bloat the table. Worst-case noise: 1 row per 30s = 86,400 rows/day per canary producer. With multiple Akosha pods, only one INSERT survives per `(trace_id, span_id)` due to the §5.1 UNIQUE CONSTRAINT — pods that lag emit a duplicate that the constraint quietly rejects. Failed pods show up only as `canary_writes_failed_total` and `canary_last_success_unix_nano` staleness; not as DLQ noise.

### 11.4a `akosha admin otel …` CLI subtree (v7 — required by §11.1.5/6/7 runbooks)

The retention/canary/heartbeat runbooks reference `akosha admin otel retention {…}` and `akosha migrations {up,down,…}` subcommands. **Verified against `akosha/cli.py:226-501`** — none of these Typer sub-groups exist today. PR-A2 + PR-A3 must ship the new Typer hierarchy; the v7 declarations:

```python
# akosha/cli.py — PR-A3 additions
admin_app = typer.Typer(help="operator/admin subcommands")
otel_app = typer.Typer(help="OpenTelemetry substrate commands")
retention_app = typer.Typer(help="spans_substrate retention sweep")

@retention_app.command("manual-run")
def retention_manual_run(
    retention_days: int = typer.Option(..., help="days of history to keep"),
    dry_run: bool = typer.Option(True, help="print SQL + row-count preview; do not execute"),
    apply: bool = typer.Option(False, help="actually execute (requires --confirm)"),
    confirm: str = typer.Option("", help="typed-phrase confirmation"),
) -> None:
    """Run the retention sweep manually. Default is --dry-run; --apply is required
    for mutation. The --confirm phrase must be one of the spec's blessed
    strings (e.g., 'delete rows older than 30 days'). The CLI computes the
    cutoff_ns internally so a fat-fingered shell arithmetic can't drop hot data."""
    ...

@retention_app.command("sweep-once")
def retention_sweep_once() -> None:
    """Run one sweep cycle now (same body as the lifespan task; bypasses
    the wait interval)."""
    ...

@retention_app.command("config set")
def retention_config_set(
    retention_days: int | None = typer.Option(None, help="override retention_days"),
    reload: bool = typer.Option(False, help="re-read settings after change"),
) -> None:
    """Operator-facing settings override (dry-run by default; --apply required)."""
    ...

@retention_app.command("cardinality-report")
def retention_cardinality_report() -> None:
    """Print row count, retention horizon, and per-service-name row breakdown."""
    ...

otel_app.add_typer(retention_app, name="retention")
admin_app.add_typer(otel_app, name="otel")
app.add_typer(admin_app, name="admin")

# akosha/cli.py — PR-A2 additions (separate top-level Typer group, not nested)
migrations_app = typer.Typer(help="yoyo SQL migrations")

@migrations_app.command("up")
def migrations_up(revision: str = typer.Option("head", help="target revision")) -> None:
    """yoyo `up` to <revision> (default: head)."""
    ...

@migrations_app.command("down")
def migrations_down(revision: str = typer.Option("-1", help="relative target")) -> None:
    """yoyo `down` to <revision>."""
    ...

@migrations_app.command("status")
def migrations_status() -> None:
    """Print applied vs pending migrations."""
    ...

@migrations_app.command("list")
def migrations_list() -> None:
    """Enumerate available migration files."""
    ...

app.add_typer(migrations_app, name="migrations")

# The existing `cli/commands/migrate.py` (Click `data-migrate` group, pre-existing
# data-migration tool) stays under its original Typer registration name to avoid
# namespace collision with the new SQL `migrations` group.
```

The `migrations` and `admin` Typer groups land in PR-A2 + PR-A3 PR descriptions as enumerated deliverables. Without them, `§11.1.5` step 4 (`akosha admin otel retention manual-run`) and `Appendix C` (`akosha migrations down 0002.dlq-rows`) reference commands that won't exist post-deploy — operators will hit "command not found" at 3am.

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

## 12. `opentelemetry-proto` install discipline

`opentelemetry-proto` is **runtime-required** (the substrate's whole point). PR-A2 + PR-A3 move it from `[dependency-groups]` (PEP 735, opt-in) to `[project.dependencies]` (always-installed) per §6.4. **There is no separate install command.** Production deployments pick up the dep automatically with `uv sync`.

The `LifecycleError("opentelemetry-proto-missing")` path from v2 §12 is removed in v3 — the dep is always available; the error class never fires.

---

## 13. Stage-A PR execution order

**11 PRs total** across 3 repos. Dependency graph is sequential; PR-A3 onward builds on the substrate managed by PR-0a.

| PR | Repo | Purpose | Depends on |
|---|---|---|---|
| **PR-0a** | oneiric | Add `spans_substrate` DDL + `spans_substrate_table` class attribute + `table_exists()` to `DuckdbHotStore`. Bump oneiric minor. | — |
| **PR-0b** | akosha | Update `pyproject.toml` to declare `opentelemetry-proto` as `[project.dependencies]`. **Add `set_shared_otel_receiver()` hook + extend `clear_shared_services()`** to clear the new `_shared_otel_receiver` module global alongside `_shared_hot_store` and `_shared_kg_builder`. PR-0b PR description enumerates 3 edits: (a) `set_shared_otel_receiver(receiver)` + `get_shared_otel_receiver()`; (b) module-level `_shared_otel_receiver: OTLPReceiver \| None = None`; (c) extend `clear_shared_services()` body to also nil out `_shared_otel_receiver`. Regression test: `create_app()` twice → `get_shared_otel_receiver()` is `None` between calls. | PR-0a |
| **PR-A1** | mcp-common | Bridge release — emit `namespace.legacy_alias=bodai` alongside current `service.namespace`. | — |
| **PR-A2** | akosha | yoyo migrations `0001.akosha-otel-receiver-state.sql` + `0001.…rollback.sql` + `0002.dlq-rows.sql` + `0002.…rollback.sql`. | PR-0a, PR-0b |
| **PR-A3** | akosha | `OTLPReceiver` lifespan wiring (HotStore.init → receiver.start → set_shared_otel_receiver → tool register). **Move existing Alloy collector from `:4318` to `:14318` (§13.1)**. Drop substrate mid-test and confirm `LifecycleError`. | PR-A2 |
| **PR-A4** | akosha | Per-row validation + DLQ try/except wrapping + `_dlq_rows` retention sweep. | PR-A3 |
| **PR-A5** | akosha | `heartbeat_watcher.py` reading `known_mcp_servers`. query-empty vs query-threw distinction. Empty-roster P0. | PR-A3 |
| **PR-A6** | akosha | Receiver resource-attribute validator (allowlist-based, rate-based thresholds). | PR-A4 |
| **PR-A6.5** | akosha | Existing `spans` table disposition (drop or migrate to `spans_substrate`). | PR-A4 |
| **PR-A7** | mcp-common | Flip release — `service.namespace` defaults to `bodai`. **Gated on §10.1 sweep + §10.2 CI gate**. | PR-A1 + bridge-recursive-validation |
| **PR-A8** | akosha | Retire `OtelTraceIngester` poller. `otel.receiver.trace_ingester_poller: bool` (in `akosha/settings/akosha.yaml`, see §11.4 + §13.6) gates the import + lifespan start. PR-A8 flips the flag to `false`; rollback is a flag flip + restart, never a code revert. **v7 — PR-A8 must explicitly retire the pre-existing `AKOSHA_SKIP_OTEL_INGESTER` env var (`akosha/mcp/server.py:627`); remove the `if not _env_truthy("AKOSHA_SKIP_OTEL_INGESTER"):` block, replace with the settings-key read path. Runbooks (`§11.1.5`/6/7) and `akosha/CLAUDE.md` operator note updated accordingly. Without this edit, operators with launchd plists setting `AKOSHA_SKIP_OTEL_INGESTER=1` get the dead OTelPoller silently re-enabled post-PR-A8.** | PR-A5, PR-A6, PR-A6.5 |

After PR-A8 ships:

**PR-B** — rewrite sub-spec B against this substrate. Independent brainstorm + agent review + writing-plans cycle.

### 13.1 Port collision fix (full enumeration)

Existing collector (`mahavishnu/config/otel-collector-config.yaml`) currently binds:
- `:4317` gRPC (OTLP)
- `:4318` HTTP (OTLP)
- `:4319` gRPC (`otlp/claude`)
- `:4320` HTTP (`otlp/claude`)
- `:4321` gRPC (`otlp/qwen`)
- `:4322` HTTP (`otlp/qwen`)
- `:9411` zipkin
- `:14250` jaeger
- `:8888` pprof

**Conflicts with new `OTLPReceiver`:**

| New receiver port | Existing collector binding | Resolution |
|---|---|---|
| `:4317` (gRPC) | existing `:4317` | Existing must move; Akosha gets it |
| `:4318` (HTTP) | existing `:4318` | Existing moves to `:14318`; Akosha gets `:4318` |

**Migration:**

```yaml
# mahavishnu/config/otel-collector-config.yaml — refactor at PR-A3
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:14317     # was :4317
      http:
        endpoint: 0.0.0.0:14318    # was :4318
  otlp/claude: ...                  # unchanged
  otlp/qwen: ...                    # unchanged
  zipkin: ...                       # unchanged
  jaeger: ...                       # unchanged
  pprof: ...                        # unchanged
```

`MAHAVISHNU_OBSERVABILITY__OTLP_ENDPOINT=http://localhost:14317` precedent holds.

**Consumers that hardcoded `:4318`:**

| Consumer | File pattern |
|---|---|
| Grafana metric-mirror probe | `mahavishnu/config/grafana/dashboards/bodai/*.json` |
| Alloy relay templates | `mahavishnu/config/otel-collector-config.yaml` and any `*-alloy.yaml` |
| Bifrost gateway UI | operator sets at runtime per sub-spec B §4.4 |

**Migration gate** (PR-A3 CI step): `git grep ':4318'` over `dashboards/bodai/` returns zero hits pointing at the substrate receiver; mirrored sweep over consumers.

**claude/qwen receivers** (`:4319`/`:4320`/`:4321`/`:4322`) — **reclassified as out-of-scope for v3**. Sub-spec B or a later spec will decide whether to mirror them through Akosha or leave them as Alloy-only. See §3.

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
| PR-A8 | `test_poller_retirement.py` (assert `OtelTraceIngester` import gone; lifespan no longer references it; feature-flag-off path tested) |

All `@pytest.mark.slow`; the fast feedback lane (`pytest -m "not slow"`) skips them. **`crackerjack run -v -f` is the merge gate.**

---

## 15. Decisions log

| Decision | Choice | Rationale |
|---|---|---|
| Substrate home | **`oneiric/adapters/vector/duckdb_hot_store.py`** | ADR 017 names this as canonical; one PR vs many; substrate-managed access |
| DLQ is akosha-local, not substrate | §5.3 explicit | `_dlq_rows` is dead-letter for rejected substrate data, not telemetry itself |
| Migration framework | **none — inline `CREATE TABLE IF NOT EXISTS` at point of first use** | **v7 corrected.** v6 chose yoyo (raw SQL + sibling `.rollback.sql`). There is no yoyo in the Bodai fleet — not in akosha, not in oneiric, not in mahavishnu, which uses Alembic (`migrations/versions/V*.sql`). Building a yoyo runner would have introduced a third framework into a repo that has none, for a substrate ADR 017 assigns to oneiric. `CREATE TABLE IF NOT EXISTS` in `DuckdbHotStore.initialize()` is idempotent and runs on every substrate boot, so it covers fresh and pre-existing substrate files with nothing to sequence. The receiver's two operational tables (`_dlq_rows`, `_akosha_otel_receiver_state`) follow the same rule. Reversibility is a `git revert`; there is no partial-apply state to roll back. |
| `opentelemetry-proto` placement | `[project.dependencies]` (hard runtime dep) | Runtime-required; PEP 735 groups never auto-install and would fire `LifecycleError` |
| `ON CONFLICT (trace_id, span_id)` | composite uniqueness | cross-producer dedup correctness |
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
| **v7** CLI Typer hierarchy | New `admin`/`otel`/`retention` and `migrations` top-level sub-apps on `akosha.cli.app` | v6 referenced commands (`akosha admin otel retention manual-run`, `akosha migrations up`) that don't exist today. PR-A2 + PR-A3 must ship them; v7 §11.4a enumerates the surface. |
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
- Existing collector config (PR-A3 port-move source): `mahavishnu/config/otel-collector-config.yaml`
- Precedent relay env var: `mahavishnu/settings/local.yaml:17` (`MAHAVISHNU_OBSERVABILITY__OTLP_ENDPOINT=http://localhost:14317`)
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

If a hot down is needed (rare; usually avoided):

1. Stop Akosha's MCP server (lifespan shutdown drains the receiver).
2. Verify no more spans land: `akosha hot-store inspect --table spans_substrate --since=now-1m --count`.
3. yoyo `down` calls (siblings):
   ```bash
   akosha migrations down 0002.dlq-rows   # drops _dlq_rows
   akosha migrations down 0001.akosha-otel-receiver-state  # drops _akosha_otel_receiver_state
   ```
4. The substrate DDL (`spans_substrate` in `DuckdbHotStore.initialize()`) has no `down` — substrate-managed. To remove the table, run a one-off `akosha hot-store exec "DROP TABLE spans_substrate"`. The receiver's `start()` will fail-loud (the `table_exists()` check) on next boot — no silent boot possible.
5. Restart Akosha. The receiver's `start()` will raise `LifecycleError("spans_substrate_missing")` if invoked without the table.

**PR-A8 has no `down`.** PR-A8 flips `otel.receiver.trace_ingester_poller` in `akosha/settings/akosha.yaml` to `false`. Rollback is `trace_ingester_poller: true` + restart.

## Appendix D — `OBSERVABILITY__OTLP_ENDPOINT` env var change

Today (pre-v3):
```bash
MAHAVISHNU_OBSERVABILITY__OTLP_ENDPOINT=http://localhost:14317
```

This already maps to the relocated `otlpclaude`/`otlpqwen` analogue or the off-Akosha collector. **No env-var change is part of v3.** The Mahavishnu exporter continues to point at `:14317`. PR-A3 adds Akosha's receiver on `:4317` (substrate receiver); Mahavishnu's `OTLP_EXPORTER_OTLP_ENDPOINT` could be re-pointed at `:4317` post-sub-spec-B-rewrite, but is **out of scope for v3** (it's a producer-side concern, not substrate).
