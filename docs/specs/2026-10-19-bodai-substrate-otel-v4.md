---
status: in-review
role: sub-spec
date: 2026-10-19
last_reviewed: 2026-10-19
superseded_by: null
blocks_on: []
topic: substrate-otel
parent_spec: docs/specs/2026-10-19-bodai-event-sourced-otel-architecture.md
supersedes: docs/specs/.archive/2026-10-19-bodai-substrate-otel-v3.md
review:
  - 2026-10-19 v3: critical-audit-specialist (5 P0, 3 P1, 4 P2)
  - 2026-10-19 v3: observability-incident-lead (2 P0, 3 P1, 1 P2)
  - 2026-10-19 v4: pending (post-draft 2-agent pass)
---

# Bodai OTel Substrate — v4

# Bodai OTel Substrate — v3

**Status:** Draft v4; supersedes v3 (`.archive/2026-10-19-bodai-substrate-otel-v3.md`), v2, and v1.
**Date:** 2026-10-19
**Stage:** Sub-spec A; companion to `2026-10-19-bodai-event-sourced-otel-architecture.md` (sub-spec B).
**Repos in scope:** `oneiric` (substrate), `akosha` (receiver, DLQ, heartbeat watcher, canary), `mcp-common` (bridge release).

---

## 1. Why this exists

v1 had a substrate-architecture mistake (substrate DDL in akosha; ADR 017 violated). v2 fixed the architecture root but the 5-agent v2 review found ~12 P0s that weren't about architecture — they were about *implementation completeness* (DLQ silent-failure paths, heartbeat source, yoyo conventions, dep placement, cross-spec scope, port collision consumer enumeration, etc.). v3 fixed those.

The 2-agent v3 final review (critical-audit-specialist proper + observability-incident-lead random) found **7 P0 + 6 P1 + 5 P2** that v3 hadn't addressed. v4 closes the 7 P0s and 3 concrete-bug P1s (Prometheus metric misuse, PR-A6 namespace constant, feature-flag naming consistency). The remaining 3 P1s and 5 P2s are *policy / scope decisions* — they're deferred to the **writing-plans** phase, where they get crystallized into concrete PR descriptions rather than into spec edits.

v4 is **architecturally stable** (the substrate-in-oneiric + receiver-in-akosha split is unchanged from v3). What changes is rigor: every implementation surface has its failure paths, contracts, and merge-gate tests spelled out, plus the two new sections added in response to the operational review (retention / rollover in §8.2; synthetic canary span in §11.3).

## 2. Scope

In scope (the 8 items, refined from v1/v2):

1. **`spans_substrate` table in oneiric** — `DuckdbHotStore.initialize()` adds the table alongside `conversations`; substrate contract pins both DDL and table-name class attribute.
2. **Akkosha's `OTLPReceiver`** — gRPC `:4317` + HTTP `:4318` lifecycles; lifespan-ordered after `HotStore.initialize()`.
3. **yoyo migrations in akosha** managing only **two** tiny tables: `_akosha_otel_receiver_state` (version-stamp) and `_dlq_rows` (per-row quarantine). Sibling `.rollback.sql` per migration.
4. **Per-row validation** before batch INSERT. Bad rows quarantined; per-row metric emitted. **`_dlq_insert` itself is wrapped in try/except** (the DLQ has its own failure mode).
5. **Partial-batch INSERT semantics** — `ON CONFLICT (trace_id, span_id) DO NOTHING RETURNING span_id` (the dedup constraint spans both axes; cross-producer trace_id collisions are caught).
6. **OTel attribute normalization** (dotted → underscore) — OTel exporter handles this; **server-side normalizer in OTLPReceiver** re-checks (older SDK / non-standard producers fall back through the normalizer).
7. **`service.namespace` migration** (`mcp-ecosystem` → dual-label → `bodai`) with explicit consumer-file-path enumeration + per-repo owners + CI gate.
8. **Heartbeat-watcher known-server roster** — separate `HealthFeedState("known_mcp_servers")` field; empty roster is itself a P0 condition.

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
                    │  reads HealthFeedState("known_mcp_servers")│
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
    -- Composite uniqueness is enforced by a separate UNIQUE CONSTRAINT
    -- (NOT a UNIQUE INDEX — DuckDB `ON CONFLICT (col_list)` only honors
    -- PRIMARY KEY or UNIQUE CONSTRAINT targets. A UNIQUE INDEX leaves
    -- `ON CONFLICT (trace_id, span_id)` as `Binder Error: conflict target
    -- does not match any key`. v3 had this wrong; v4 corrects it.):
    --   ALTER TABLE spans_substrate
    --     ADD CONSTRAINT uq_span_identity UNIQUE (trace_id, span_id);
    -- (added by PR-0a alongside the table; dedup constraint spans both axes)
);

-- Hot-path projection indexes (consumer: sub-spec B §5.6 FSM projection)
CREATE INDEX IF NOT EXISTS idx_spans_selector_task_class_outcome
    ON spans_substrate(selector, task_class, outcome, start_time_unix_nano DESC)
    WHERE outcome IN ('success', 'error');
CREATE INDEX IF NOT EXISTS idx_spans_service_name_recent
    ON spans_substrate(service_name, start_time_unix_nano DESC);
CREATE INDEX IF NOT EXISTS idx_spans_source_type_recent
    ON spans_substrate(telemetry_source_type, start_time_unix_nano DESC);
```

The DDL ships in `PR-0a` (oneiric) — bumps oneiric's minor version. Same PR exposes `spans_substrate_table` and `table_exists()`:

```python
# oneiric/adapters/vector/duckdb_hot_store.py (additions to DuckdbHotStore class)
class DuckdbHotStore:
    spans_substrate_table: str = "spans_substrate"
    conversations_table:   str = "conversations"

    async def initialize(self) -> None:
        # existing conversations DDL stays
        # NEW: spans_substrate DDL (above)
        # NEW: UNIQUE CONSTRAINT uq_span_identity UNIQUE (trace_id, span_id)
        ...

    async def table_exists(self, name: str) -> bool:
        """Used by OTLPReceiver.start() to fail-loud if substrate is missing."""
        row = await self._conn.execute(
            "SELECT 1 FROM duckdb_tables WHERE table_name = ?", [name]
        ).fetchone()
        return row is not None
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

**Lifespan order** (pinned; reuse pattern at `akosha/mcp/server.py:516-661`):

```python
async def lifespan(app: ASGIApp):
    hot_store = HotStore(...)
    await hot_store.initialize()                              # 1. substrate tables exist
    receiver = OTLPReceiver(hot_store=hot_store)
    await receiver.start()                                    # 2. bind listeners, fail-loud if substrate missing
    set_shared_hot_store(hot_store); set_shared_otel_receiver(receiver)  # 3. publish singletons
    await _apply_tool_profile(); ... MCP tools register      # 4. tools see active receiver
    yield
    await receiver.stop()                                     # reverse order on shutdown
    # NB: set_shared_otel_receiver is NEW; mirrors set_shared_hot_store at server.py:282-294
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

### 8.2 `spans_substrate` retention & rollover (v4 addition; ops P0)

`spans_substrate` was unbounded in v3. At fleet-scale ingestion rates the DuckDB file grows ~30GB/month; without intervention it is a guaranteed disk-full pager at the 6-month mark. v4 ships a default retention policy + sweep mechanism + cold archival:

| Setting | Default | Pinned at | Operator-overridable? |
|---|---|---|---|
| `spans_substrate.retention_days` | `30` | PR-A3 ships default | yes (settings key) |
| `spans_substrate.retention_sweep_interval_hours` | `6` | PR-A3 | yes |
| `spans_substrate.archival_target` | `null` (no cold sink) | PR-A3 | yes (S3 sink or filesystem path) |

**Sweep mechanism** (PR-A3, lifespan task paralleling §8.1):

```python
# PR-A3 — lifespan task
async def _spans_substrate_retention_sweep():
    while not stop_event.is_set():
        await stop_event.wait(settings.spans_substrate.retention_sweep_interval_hours * 3600)
        cutoff_ns = time.time_ns() - int(settings.spans_substrate.retention_days) * 86_400 * 1_000_000_000
        # Archive before delete when archival_target is set
        if settings.spans_substrate.archival_target:
            await self._conn.execute(
                "COPY (SELECT * FROM spans_substrate "
                "WHERE start_time_unix_nano < ?) TO ?",
                [cutoff_ns, settings.spans_substrate.archival_target],
            )
        await self._conn.execute(
            "DELETE FROM spans_substrate WHERE start_time_unix_nano < ?",
            [cutoff_ns],
        )
        logger.info("spans_retention_sweep_complete",
                    cutoff_unix_nano=cutoff_ns,
                    deleted=deleted_count)
```

**Partitioning** (deferred; out of scope for v4). When `spans_substrate` exceeds ~10M rows, the receiving PR adds range partitioning on `start_time_unix_nano` (DuckDB supports `CREATE TABLE … PARTITIONED BY (…))`). The retention sweep above keeps index paths clean until that scale; the partition step is its own ADR.

**`received_at_unix_nano` clock-skew guard** (v4 addition; addresses ops P1 from the v3 review):

Producer `start_time_unix_nano` is unreliable (paused-laptop drift, NTP outages; silently corrupts every index that orders by it). Every INSERT into `spans_substrate` carries a server-populated `received_at_unix_nano BIGINT NOT NULL DEFAULT (CAST(epoch_ms(now()) * 1e6 AS BIGINT))`. Indexes order by `received_at_unix_nano`; the cross-spec rewrite (§17) flips parent §5.6 projection SQL to use it.

DDL additions to §5.1:

```sql
ALTER TABLE spans_substrate ADD COLUMN received_at_unix_nano BIGINT
    NOT NULL DEFAULT (CAST(epoch_ms(now()) * 1e6 AS BIGINT));
CREATE INDEX IF NOT EXISTS idx_spans_received_at_recent
    ON spans_substrate(received_at_unix_nano DESC);
```

(replaces the v3 indexes' exclusive reliance on `start_time_unix_nano` — clock-drift regions were getting mis-ordered results in the ops review's 3am scenario).

**Cardinality alarm** (runbook §11.1.6, mentioned for context):

```
ALERT spans_substrate_row_count_high
  for 1h
  expr: COUNT(*) FROM spans_substrate > 0.9 * $spans_substrate_max_rows
  annotations:
    summary: "spans_substrate > 90% of `max_substrate_rows` setting"
    runbook_url: "docs/specs/2026-10-19-bodai-substrate-otel-v4.md#82-spans_substrate-retention--rollover-v4-addition-ops-p0"
```

`spans_substrate_max_rows` defaults to `10_000_000`; sweeps in §8.2 keep us below unless ingestion rate climbs. The §11.1.6 runbook step is "check `spans_substrate` row count vs retention horizon — if growing, lower `retention_days` or raise `archival_target`."

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

- **Source of truth for known servers:** a **separate, boot-populated** `HealthFeedState("known_mcp_servers")` field, not the per-cycle feed. The two are distinct feeds with distinct semantics:

| Feed | Source | Used for |
|---|---|---|
| `HealthFeedState("known_mcp_servers")` | Static, populated at `akosha/mcp/server.py` lifespan startup from a config (`servers = ["mahavishnu", "akosha", "session-buddy", "oneiric", "crackerjack", "bifrost-mcp:grpc"]`) | P0-A roster |
| `HealthFeedState("mcp_tool_call")` | Per-cycle observation (`entities_count`, `last_updated_timestamp`, `cycles_total`) | `/health` aggregate |

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

**State tracking** (mirrors the §11 heartbeat-watcher pattern; new `HealthFeedState("receiver_canary")`):

```python
# akosha/observability/canary_watcher.py (PR-A4)
@dataclass
class CanaryState:
    last_canary_success_unix_nano: int | None = None   # server-side receive time
    last_canary_failure_unix_nano: int | None = None
    canary_writes_attempted_total: int = 0
    canary_writes_succeeded_total: int = 0
    canary_writes_failed_total:    int = 0
```

Sweeped every 60s; **P0-C alert if `last_canary_success_unix_nano` is older than 90s**:

```
ALERT receiver_canary_stale
  for 90s
  expr: time_ns() - last_canary_success_unix_nano > 90s
  annotations:
    summary: "Receiver has not written a successful canary span in 90s"
    runbook_url: "docs/specs/2026-10-19-bodai-substrate-otel-v4.md#113-synthetic-canary-span-v4-addition-ops-p0"
```

P0-C catches:
- `INSERT` path regressions (the §6.2 try/except would have hidden a silently-failing batch).
- `start()` succeeded but `_handle_batch` doesn't (e.g., a span class renamed without aliasing, JSON serializer accidentally returns `None` for `attributes`).
- DLQ-flood scenarios where good rows stop landing.
- Cold-start of substrate (the first canary might be slow; the P0 only fires after 90s).

**Duplicate-suppression**: `INSERT INTO spans_substrate (…attributes JSON…) ON CONFLICT (trace_id, span_id) DO NOTHING` — the canary uses a deterministic `trace_id = "_canary"` and `span_id = "_canary_<unix_time_ns>"` so duplicate canaries don't bloat the table. Worst-case noise: 1 row per 30s = 86,400 rows/day per canary producer. Acceptable.

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
| **PR-0b** | akosha | Update `pyproject.toml` to declare `opentelemetry-proto` as `[project.dependencies]`. Add `set_shared_otel_receiver()` hook. | PR-0a |
| **PR-A1** | mcp-common | Bridge release — emit `namespace.legacy_alias=bodai` alongside current `service.namespace`. | — |
| **PR-A2** | akosha | yoyo migrations `0001.akosha-otel-receiver-state.sql` + `0001.…rollback.sql` + `0002.dlq-rows.sql` + `0002.…rollback.sql`. | PR-0a, PR-0b |
| **PR-A3** | akosha | `OTLPReceiver` lifespan wiring (HotStore.init → receiver.start → set_shared_otel_receiver → tool register). **Move existing Alloy collector from `:4318` to `:14318` (§13.1)**. Drop substrate mid-test and confirm `LifecycleError`. | PR-A2 |
| **PR-A4** | akosha | Per-row validation + DLQ try/except wrapping + `_dlq_rows` retention sweep. | PR-A3 |
| **PR-A5** | akosha | `heartbeat_watcher.py` reading `HealthFeedState("known_mcp_servers")`. query-empty vs query-threw distinction. Empty-roster P0. | PR-A3 |
| **PR-A6** | akosha | Receiver resource-attribute validator (allowlist-based, rate-based thresholds). | PR-A4 |
| **PR-A6.5** | akosha | Existing `spans` table disposition (drop or migrate to `spans_substrate`). | PR-A4 |
| **PR-A7** | mcp-common | Flip release — `service.namespace` defaults to `bodai`. **Gated on §10.1 sweep + §10.2 CI gate**. | PR-A1 + bridge-recursive-validation |
| **PR-A8** | akosha | Retire `OtelTraceIngester` poller. `otel.receiver.trace_ingester_poller: bool` (in `akosha/settings/akosha.yaml`, see §11.4 + §13.6) gates the import + lifespan start. PR-A8 flips the flag to `false`; rollback is a flag flip + restart, never a code revert. | PR-A5, PR-A6, PR-A6.5 |

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
| PR-A3 | `test_otlp_receiver_e2e.py` (full lifecycle, OTLP/gRPC + OTLP/HTTP); `test_substrate_lifespan_order.py` (`await conn.execute("DROP TABLE spans_substrate")` + close; assert `LifecycleError("spans_substrate_missing")`) |
| PR-A4 | `test_otlp_receiver_dlq.py` (bad row → DLQ; DLQ-write failure → DLQ-recovery metric + good rows still land in INSERT) |
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
| Migration framework | yoyo (raw SQL + sibling .rollback.sql) | Lightest option; reversibility is first-class |
| `opentelemetry-proto` placement | `[project.dependencies]` (hard runtime dep) | Runtime-required; PEP 735 groups never auto-install and would fire `LifecycleError` |
| `ON CONFLICT (trace_id, span_id)` | composite uniqueness | cross-producer dedup correctness |
| DLQ error recovery | DLQ failure does NOT abort the batch; good rows still INSERT; metric emitted | Single failure mode shouldn't zero throughput |
| Heartbeat known-server roster | separate `HealthFeedState("known_mcp_servers")` field, boot-populated | The per-cycle feed can't carry a roster; empty roster is its own P0 |
| Resource-attribute validator | rate-based (rolling 5m spike + 24h sustained) | v2's count/hour was misclassified by startup bursts and slow drift |
| PR-A8 rollback | `otel.receiver.trace_ingester_poller: bool` (settings YAML nested key) | Rollback is flag-flip + restart, never code revert; consistent with no-backcompat rule. v3 used a flat `feature_flag_otel_trace_ingester_poller` env-var style; v4 normalizes to nested-YAML per `akosha/settings/akosha.yaml` convention (no env-var shim). |
| Bifrost gateway UI value | `http://localhost:4318/v1/traces` | Substrate receiver's HTTP port |
| claude/qwen collector pipelines | out-of-scope for v3 (reclassified) | Sub-spec B or later spec decides whether to mirror through Akosha |
| Existing akosha `spans` table | PR-A6.5 migrates then drops (idempotent) | Don't leave orphan tables |

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
| §5.6 projection SQL | `WHERE timestamp > now() - ...` (column doesn't exist); `parent_id` (column doesn't exist) | `WHERE start_time_unix_nano > now_ns - :window_seconds * 1e9`; `parent_span_id` |
| §6.1 receiver section | Claims `set_shared_otel_receiver` already exists | Rename to reflect v3's actual location (akosha/observability/otlp_receiver.py) |
| §7.2 P0-A | References `HealthFeedState("mcp_tool_call")` as the roster source | Cite v3 §11 (separate `known_mcp_servers` field) |
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

