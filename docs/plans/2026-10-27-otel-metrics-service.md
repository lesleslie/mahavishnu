---
status: active
role: implementation
kind: plan
date: 2026-10-27
last_reviewed: 2026-11-06
superseded_by: null
blocks_on: []
topic: substrate-otel
title: "OTLP MetricsService in the Bodai Substrate — Implementation Plan"
requirements:
  - id: REQ-M01
    title: "akosha's OTLP receiver implements the gRPC MetricsService"
    description: "add_MetricsServiceServicer_to_server is registered beside the trace servicer on the same :4317 port."
  - id: REQ-M02
    title: "Received metrics are exposed in Prometheus text on :8682/metrics"
    description: "Converted data points become prometheus_client instruments on the shared registry, so the existing /metrics route renders them and Prometheus already scrapes that target."
  - id: REQ-M03
    title: "Received metrics are persisted to a durable metrics_substrate"
    description: "A metrics_substrate table beside spans_substrate, with insert primitives in oneiric's DuckdbHotStore and idempotent DDL on the lifespan path."
  - id: REQ-M04
    title: "Producers can target the substrate endpoint for metrics"
    description: "mahavishnu's metric export returns to observability.otlp_endpoint and the interim otlp_metrics_endpoint split is removed."
  - id: REQ-M05
    title: "Drift counters and detector liveness are queryable"
    description: "changepoint_evaluations_total and changepoint_detector_active reach the substrate, so the stage-1 gate can read a real zero instead of a missing series."
  - id: REQ-M06
    title: "Malformed metric payloads are rejected without aborting the receiver"
    description: "Schema failures are counted in rejected_data_points and DLQ'd; the batch continues."
  - id: REQ-M07
    title: "Every in-process metric exporter reaches the substrate without error"
    description: "Both mahavishnu's own exporter and oneiric's OTLPObservabilityAdapter, which sends traces and metrics to ONE endpoint and therefore requires a receiver that implements both services."
---

# OTLP MetricsService in the Bodai Substrate — Implementation Plan

## 1. Outcome

akosha's OTLP receiver serves the gRPC **MetricsService** alongside the
**TraceService** on the same `:4317` endpoint, so any OTLP producer can send
metrics to the substrate — and those metrics are queryable in Grafana through
the scrape path that **already exists** (`:8682` → Prometheus `:9090` →
Grafana), with no new collector, no new scrape target, and no second
telemetry pipeline.

Success is demonstrable by one `curl` and one PromQL query:

```bash
curl -s http://localhost:8682/metrics | grep mahavishnu_observability
# -> mahavishnu_observability_drift_detected_total ... (the producer's own
#    instruments, as received over OTLP)
```

## 2. Goals

1. **G1** — akosha's receiver implements the OTLP/gRPC MetricsService, so a
   producer's metric export is accepted instead of answered with
   `UNIMPLEMENTED / Method not found!`.
2. **G2** — received metrics are exposed in Prometheus text format on
   akosha's existing `:8682/metrics` route, which Prometheus already scrapes
   and Grafana already queries.
3. **G3** — received metrics are persisted durably in a `metrics_substrate`
   store, symmetric with `spans_substrate`, so the §7 stage-1 gate has a
   historical source and not only a live gauge.
4. **G4** — mahavishnu's metric export returns to the trace endpoint, and the
   interim `observability.otlp_metrics_endpoint` split is **removed**, not
   kept (replace, don't extend — `feedback-no-backwards-compat-pre-1.0.md`).
5. **G5** — the change-point drift counters and the new liveness instruments
   (`changepoint_evaluations_total`, `changepoint_detector_active`) are
   queryable, so the stage-1 gate can read a real zero instead of "missing".
6. **G6** — **both** in-process metric exporters reach the substrate without
   error: mahavishnu's own, and oneiric's `OTLPObservabilityAdapter`
   (Finding 10). This is the requirement that makes the single-endpoint
   design non-negotiable — a split-endpoint fix that only covers mahavishnu
   leaves the second exporter failing.

## 3. Non-Goals

1. **NG1** — Not completing the Alloy half of the pipeline. The
   `otelcol.exporter.prometheus.cli_tools` dead end is *retired*, not fixed:
   with the substrate serving metrics, Alloy's metric path has no consumer.
2. **NG2** — Not enabling Prometheus's remote-write receiver
   (`--web.enable-remote-write-receiver`). That is the Alloy route's cost and
   this plan does not pay it.
3. **NG3** — Not turning akosha into a general-purpose OTel Collector. One
   receiver, two services, the same validation and DLQ discipline the trace
   path already has.
4. **NG4** — Not changing the trace path, the `spans_substrate` schema, or
   the retention sweep.
5. **NG5** — Not adding a second telemetry store. `metrics_substrate` is a
   table in the same DuckDB substrate, not a new database.
6. **NG6** — Not splitting oneiric's `OTLPObservabilityAdapter` endpoint. It
   sends traces and metrics to **one** endpoint
   (`oneiric/adapters/monitoring/otlp.py:140-153`), so a receiver that
   implements both services satisfies it as-is. Splitting oneiric's endpoint
   would be a second mechanism solving the same problem.

   **NG6 was wrong on one point, corrected 2026-11-06.** "No oneiric code
   change is needed" does not hold, for a reason that has nothing to do with
   the endpoint: `OTLPObservabilitySettings.insecure` defaults to `False`
   and is passed **explicitly** to the exporter, which overrides the
   exporter's own scheme detection and forces a TLS channel. akosha's `:4317`
   is plaintext, so the handshake fails and **zero points arrive**.
   Measured: `OTLPMetricExporter(endpoint="http://127.0.0.1:4317",
   insecure=False)` → `_insecure = False` (TLS); with `insecure` unset →
   `_insecure = True` (plaintext). The fix is oneiric's default becoming
   `bool | None = None` — the scheme decides, an explicit value still
   overrides — which matches what mahavishnu's exporter already does. The
   *endpoint* stays single; only the transport default changes.

   **The transport default is not the only guard (2026-11-07).** Letting
   the scheme decide is the SDK's *own* default, but on its own it lets
   **any** host receive telemetry in the clear. The old `insecure=False`
   blocked plaintext egress to a remote host only as a side effect of
   being broken, so removing the breakage removed that side effect too.
   oneiric now validates the endpoint before constructing an exporter:

   - plaintext to a **loopback** host is allowed (the substrate case);
   - plaintext to a **non-loopback** host requires an explicit
     `allow_insecure=True` — one way in, not two, so the guard stays
     greppable and there is never a question of which knob was flipped;
   - the cloud metadata addresses (`169.254.169.254` and friends) are
     rejected **always**, over TLS as well as plaintext — a telemetry
     exporter has no business talking to a metadata service;
   - **RFC1918 is deliberately not blocked**: an internal OTLP collector
     on `10.x` is a legitimate destination here, unlike an LLM gateway.

   The validator mirrors the exporter's transport resolution exactly,
   **per protocol**, because a guard that disagrees with the exporter
   would either block a config the exporter would have handled
   securely or wave through a plaintext one:

   - **`grpc`** — the `https` pin, then the explicit `insecure`, then
     `OTEL_EXPORTER_OTLP_INSECURE`, then `scheme == "http"`.
   - **`http/protobuf`** — the **scheme alone**. The HTTP exporters
     accept no `insecure` kwarg and never read
     `OTEL_EXPORTER_OTLP_INSECURE`, so `http://` is plaintext whatever
     the setting says. An explicitly set `insecure` on that protocol is
     a **hard error**, not a silent ignore: a security knob that
     silently does nothing is the exact failure this guard exists to
     prevent, and `insecure=False` is the most dangerous form of it —
     the operator believes they forced TLS while the exporter sends
     plaintext.

   A scheme-less `host:port` endpoint is TLS to the gRPC exporter, so
   the guard must treat it as TLS too.

   The metadata endpoints are blocked by **CIDR**, not by a literal
   string set: `169.254.0.0/16`, `100.100.100.200/32`, `fd00:ec2::254/128`
   and `fe80::/10`, with the host canonicalised first
   (`ipaddress.ip_address`, then a `socket.inet_aton` fallback, so the
   decimal `2852039166` and the hex `0xa9fea9fe` are both recognised as
   `169.254.169.254`) and the name normalised (trailing dot stripped,
   lowercased). A literal set is a denylist with escape hatches.

   The model also sets `hide_input_in_errors=True`: Pydantic echoes the
   whole model into **every** validation error, and this model's
   `headers` routinely carries vendor API keys. The endpoint error
   itself reports only the scheme, the sanitised host and the port —
   never the raw endpoint, which can carry `user:pass@` userinfo.

### Interim state (until Phase 2 lands)

The `UNIMPLEMENTED` flood continues, but it is **one** exporter, not two:
mahavishnu's own now targets `:14317` (commit `0b0886ea`) and succeeds, so
the remaining 60-second error stream is oneiric's monitoring adapter against
the trace-only `:4317`. Two interim options, neither of which this plan
requires:

- **Accept it.** The flood is one line per minute in a log file, and no
  metric is lost that was ever delivered.
- **Silence it in oneiric** by giving `OTLPObservabilitySettings` a separate
  metrics endpoint, mirroring the mahavishnu change. This is a oneiric
  change and buys nothing durable — it is a second endpoint-split mechanism
  to maintain, and the substrate's MetricsService makes it unnecessary.

Prefer the first. A durable fix in the substrate is worth more than a
temporary one in a producer.

## 4. Current Findings

Citations are file:line against the working tree on 2026-10-27.

1. **The receiver implements one service.** `akosha/observability/otlp_receiver.py:224`
   registers `add_TraceServiceServicer_to_server` and nothing else. There is
   no `MetricsServiceServicer` anywhere in akosha, so gRPC correctly answers
   `UNIMPLEMENTED` for the metric method. This is not a misconfiguration —
   the method was never implemented.

2. **Producers sent metrics to the trace receiver anyway.** mahavishnu used
   one setting (`observability.otlp_endpoint`) for both signals
   (`mahavishnu/core/observability.py:201` traces, `:222` metrics), so the
   metric export inherited a receiver that cannot accept it. The symptom was
   one `UNIMPLEMENTED` error per minute, forever, and **no metric series ever
   reached any backend**.

3. **The substrate deliberately split the two paths** (PR-A3, 2026-10-23):
   traces → akosha `:4317` → DuckDB `spans_substrate`; metrics → Alloy
   `:14317` → `otelcol.exporter.prometheus`. The rationale is in
   `/usr/local/etc/grafana-alloy/config.alloy` (Alloy had been squatting on
   `:4317` and terminating traces in `otelcol.exporter.debug`).

4. **The Alloy metric path is a dead end, not a detour.** Measured on this
   host: Alloy's OTLP receiver accepts the points (counter 1652 → 1891 for a
   synthetic probe pushed straight to `:14317`) and exposes **nothing** — the
   `otelcol.exporter.prometheus.cli_tools` block has `forward_to = []` and, in
   Alloy v1.21, **no `endpoint` argument at all** (it is a converter, not a
   server). Compiling candidate configs with `alloy validate` shows the only
   valid sink is `prometheus.remote_write`, which requires Prometheus's
   `--web.enable-remote-write-receiver` (not currently set). The Alloy route
   therefore costs **two** shared-infra changes; this plan costs **zero**.

5. **akosha already has the exposure surface.**
   `akosha/mcp/server.py:1759` serves `/metrics` on the main HTTP port from a
   shared `CollectorRegistry` (`akosha/observability/prometheus_metrics.py:96`),
   and Prometheus already scrapes `127.0.0.1:8682/metrics`
   (`monitoring/file_sd/verified_metrics_targets.yml`, live target confirmed
   `health=up`). Grafana's Prometheus datasource points at
   `http://localhost:9090` and health-checks OK.

6. **The substrate's storage primitives live in oneiric.**
   `akosha/storage/hot_store.py:76` defines `class HotStore(DuckdbHotStore)`,
   and `insert_spans_substrate` / `table_exists` / `spans_substrate_table`
   are inherited from `oneiric.adapters.vector.duckdb_hot_store.DuckdbHotStore`.
   A metrics substrate follows the same shape — **this is a three-repo change
   surface: oneiric, akosha, mahavishnu.**

7. **The protos are already available.** In akosha's venv,
   `opentelemetry.proto.collector.metrics.v1.metrics_service_pb2` and
   `..._grpc` import cleanly and the servicer exposes `Export`; the data
   model is `opentelemetry.proto.metrics.v1.metrics_pb2` (note: the data
   model is **not** under `collector.metrics.v1` — `metrics_pb2` is not
   importable from there).

8. **mahavishnu's own `:8680/metrics` does not carry the OTel instruments.**
   It exposes a separate, hand-rolled set (`mahavishnu_workflows_total`,
   `mahavishnu_workflow_queue_depth`, …). The OTel instruments
   (`mahavishnu.workflows.executed` → `mahavishnu_workflows_executed_total`)
   are distinct series and are absent from every backend today.

9. **The interim split is already shipped** as `mahavishnu` commit `0b0886ea`
   (`observability.otlp_metrics_endpoint`, default `None` → falls back to the
   trace endpoint). It stops the error and routes metrics to Alloy's
   receiver, where they are accepted and discarded. G4 retires it.

10. **There are TWO metric exporters in the mahavishnu process, not one.**
    Instrumenting `OTLPMetricExporter.__init__` while constructing
    `MahavishnuApp()` **and** `FastMCPServer(app)` shows exactly one
    construction — mahavishnu's own, to `http://127.0.0.1:14317`
    (`mahavishnu/core/observability.py:236`). But the running process holds
    **two** OTLP connections (`:14317` and `:4317`) and logs **two**
    independent 60-second error streams to `localhost:4317`. An exhaustive
    sweep of site-packages finds exactly one other gRPC metric-exporter
    construction: **`oneiric/adapters/monitoring/otlp.py`** — oneiric's
    `OTLPObservabilityAdapter`. It is the only file in the venv that both
    imports `opentelemetry.exporter.otlp.proto.grpc.metric_exporter` and
    mentions `4317`.

    It is **lazily** resolved (not at app or server construction), which is
    why the flood starts when it does rather than at boot. Its
    `_create_metric_exporter` uses `self._settings.endpoint`
    (`oneiric/adapters/monitoring/otlp.py:140-153`) — the **same** endpoint
    as its span exporter. One endpoint, both signals.

    This is the decisive design fact: oneiric's adapter can only work
    against a receiver that implements **both** services. A MetricsService
    on `:4317` therefore satisfies it, and a split-endpoint fix in
    mahavishnu alone cannot.

    **Correction 2026-11-06.** The clause "with **no oneiric code
    change**" was wrong — see NG6 above. The single-endpoint conclusion
    holds; the no-change conclusion did not, because oneiric's `insecure`
    default forced TLS against the plaintext receiver. With that default
    corrected, the adapter needs no other change.

11. **The one-shot `set_meter_provider` rule makes the two exporters
    independent.** OTel allows the global meter provider to be set once;
    a later `set_meter_provider` is a silent no-op. oneiric's adapter
    calls it too (`oneiric/adapters/monitoring/otlp.py:init`), so its
    `PeriodicExportingMetricReader` — and therefore its exporter — keeps
    running and keeps failing even though its instruments are never
    recorded. A "fix" that only repoints the global provider would not
    stop the flood.

## 4.5 Requirements

The canonical requirement table lives in this file's **YAML frontmatter**
(`requirements:`) — that is where `scripts/audit_requirements.py` reads it
from. It is not duplicated here, so there is one source of truth.

| ID | Title | Delivered by |
|---|---|---|
| REQ-M01 | akosha's OTLP receiver implements the gRPC MetricsService | Phase 2 |
| REQ-M02 | Received metrics are exposed in Prometheus text on `:8682/metrics` | Phase 2 |
| REQ-M03 | Received metrics are persisted to a durable `metrics_substrate` | Phase 1 |
| REQ-M04 | Producers can target the substrate endpoint for metrics | Phase 3 |
| REQ-M05 | Drift counters and detector liveness are queryable | Phases 3–4 |
| REQ-M06 | Malformed metric payloads are rejected without aborting the receiver | Phase 2 |
| REQ-M07 | Every in-process metric exporter reaches the substrate without error | Phase 2 |

Traceability: each ID is marked in code with `# req: REQ-Mnn` (or
`# Implements: REQ-Mnn` in a docstring, or `@pytest.mark.req(["REQ-Mnn"])` on
the test) in the phase that delivers it.

## 5. Implementation Phases

### Phase 1: oneiric — metrics substrate storage primitives

**Goal:** the durable store for received metrics, beside `spans_substrate`.

**Tasks:**
- Add a `metrics_substrate` table to
  `oneiric/adapters/vector/duckdb_hot_store.py`: idempotent `CREATE TABLE
  IF NOT EXISTS` + indexes, mirroring the `spans_substrate` DDL.
  Columns: `ts`, `service_name`, `service_namespace`, `scope_name`,
  `metric_name`, `unit`, `description`, `data_type` (`sum`/`gauge`/
  `histogram`/`exponential_histogram`/`summary`), `value_sum`,
  `value_count`, `value_min`, `value_max`, `value_sum_of_squares`,
  `attributes_json`, `resource_json`, `is_monotonic`.
- Add `insert_metrics_substrate(rows)` and `metrics_substrate_table` to the
  same class, with the same dedup/insert-error discipline as
  `insert_spans_substrate`.
- Idempotent table creation is invoked from the same lifespan path that
  creates `spans_substrate` — a metrics producer must not be able to wedge
  the receiver on a missing table.

**Exit criteria:** `insert_metrics_substrate` round-trips a row into a
DuckDB file and the table survives a reopen; the table is created
idempotently.

**Delivered 2026-11-06** — oneiric `f869951` on branch
`feat/metrics-substrate` (not pushed). Four deviations from the plan
text, recorded here so Phase 2 builds against reality:

1. **`buckets_json` column added.** The plan's column list carries a
   histogram's summary statistics but not its bucket boundaries, and the
   statistics do not determine the boundaries — a stored histogram would
   not be reconstructible. The column is nullable and unused by every
   type but `histogram`/`exponential_histogram`.
2. **Counter names carry the `oneiric_` prefix.** The plan named them
   `metrics_substrate_rows_inserted_total`; oneiric's other 25
   instruments are all prefixed, and these share a registry with the
   substrate's metrics in Phase 2, where an unprefixed name could
   collide.
3. **The test file is `tests/adapters/test_duckdb_hot_store_metrics.py`**,
   not `test_metrics_substrate.py` — it sits beside its sibling
   `test_duckdb_hot_store_spans.py`, and this repo names substrate tests
   after the module under test.
4. **Identity is `(service_name, service_namespace, scope_name,
   metric_name, ts, attributes)` with canonicalized attribute JSON**, and
   the insert counts come from the statement's `RETURNING` rows rather
   than from a pre-insert existence probe. Both are forced by DuckDB
   behaviour verified on the pinned 2.1.0-dev build: a JSON column inside
   a UNIQUE constraint is compared **as text** (`{"a":1,"b":2}` and
   `{"b":2,"a":1}` are two rows), and `executemany` reports no per-row
   outcome while a single multi-row `VALUES` statement can.

   **Phase 2 consequence:** the akosha receiver must let the substrate
   canonicalize the attributes. It must not pre-serialize them in a
   different key order and expect the identity to hold.

Evidence: 25 new tests plus the 24 existing span-substrate tests pass;
`ruff check`, `ruff format --check`, and `ty check` are clean on the
changed files; the full oneiric suite reaches 93.87% coverage against
its 78.75% floor. The 18 failures in that run are pre-existing and
unrelated (auth, MCP registration signatures, health-envelope shape,
UUID7/ULID, version stamps, and a Bifrost env-var leak).

#### Integration Contract ← REQUIRED

- **Triggered from:** `akosha.storage.hot_store.HotStore` inherits the
  primitives; the table is created by the same oneiric lifespan hook that
  creates `spans_substrate` (akosha
  `akosha/mcp/server.py:634` reads `get_config().spans_substrate`).
- **Returns to / updates:** the `metrics_substrate` table in the substrate
  DuckDB file — the same file that holds `spans_substrate`.
- **Demonstrable by:** `pytest tests/.../test_metrics_substrate.py` in the
  oneiric repo — insert two rows, read them back, assert the schema.
- **Rollback signal:** `oneiric` logs `metrics_substrate_create_failed` at
  ERROR; the trace path is unaffected and keeps working, so the rollback is
  "stop sending metrics" rather than "revert a shared store".
- **Observability added:** `oneiric` counters
  `oneiric_metrics_substrate_rows_inserted_total` and
  `oneiric_metrics_substrate_insert_failed_total` (the `oneiric_` prefix
  matches every other instrument in the repo — these share a registry
  with the substrate's metrics once Phase 2 lands).

### Phase 2: akosha — MetricsService servicer, ingestion, exposure

**Goal:** akosha accepts OTLP metrics on `:4317` and exposes them on
`:8682/metrics`.

**Prerequisite — the oneiric publish gate (added 2026-11-06).** Phase 2's
persistence step calls `HotStore.insert_metrics_substrate()`, which is
inherited from oneiric's `DuckdbHotStore`. That primitive exists only on
oneiric's **local, unpushed** `main` (commit `f869951`); the published
`oneiric` 0.34.0 that akosha's `oneiric>=0.33` pin resolves to has **no**
`insert_metrics_substrate` and **no** `metrics_substrate_table`. The
implementation therefore develops against a local editable oneiric, and
**cannot ship until oneiric publishes a release carrying Phase 1**. The
version bump and the publish are operator actions — they are not part of
this plan and were not performed.

Two consequences the Phase 2 review made explicit:

- **The gap must be loud, not silent.** Against published oneiric 0.34.0
  the receiver binds, accepts exports, exposes the series on
  `:8682/metrics`, and stores **nothing** — while answering
  `rejected_data_points=0`. A Prometheus series with no durable row behind
  it reads as "working but quiet". The receiver now probes substrate
  readiness at bind time, exposes
  `akosha_otlp_metrics_substrate_ready` (1/0), labels the insert failure
  with a reason, and reports it to the producer in
  `partial_success.error_message`.
- **The Phase 2 exit criterion is strengthened.** "Appears in
  `curl http://localhost:8682/metrics`" is not sufficient on its own — the
  exposure path does not touch the substrate, so it passes even when
  persistence is entirely broken. The criterion now also requires a
  **non-empty `metrics_substrate` row count** for the same export, and a
  real OTLP export to `:4317` must be answered by the MetricsService
  rather than `UNIMPLEMENTED`.

**A second, independent cross-repo prerequisite — the transport default.**
oneiric's `OTLPObservabilityAdapter` passed `insecure=False` explicitly,
which forced TLS against akosha's plaintext `:4317` and delivered **zero**
points. Fixed on the oneiric side by making the endpoint scheme decide
(NG6 above). Until oneiric publishes that fix too, REQ-M07 is not met
even with a published Phase 1.

**Decisions taken in Phase 2 that the plan did not specify:**
- **`ts` is epoch nanoseconds**, from the data point's `time_unix_nano`.
  Phase 1 stores `ts` as a raw `BIGINT` and constrains nothing, but
  `spans_substrate` keeps nanosecond timestamps (`start_time_unix_nano`)
  in the *same* DuckDB file. Two time units in one substrate would be a
  silent trap for every future reader.
- **The exposed Prometheus series are namespaced by the resource's
  `service.name`.** REQ-M07's two producers are indistinguishable at the
  wire level, and the shared `CollectorRegistry` has no other way to keep
  mahavishnu's and oneiric's instruments from colliding.
- **The substrate's `resource` column is not part of the point's
  identity** — the UNIQUE constraint covers
  `(service_name, service_namespace, scope_name, metric_name, ts,
  attributes)`. Two producers that share a service identity but differ in
  their resource attributes are the same point.

**Delivered 2026-11-07 — akosha `ab76a77` on local `main`** (base
`f7353ca`, not pushed). Nine files, +4,253/-17: `akosha/observability/
otlp_receiver.py` (+989), the new `akosha/observability/otlp_prometheus_bridge.py`
(1,013), the new `akosha/storage/metrics_query.py` (49), `akosha/observability/
otlp_metrics.py` (+155), `akosha/mcp/server.py` (+83), the new
`tests/unit/observability/test_otlp_metrics_receiver.py` (1,298, 36 tests),
the new `tests/unit/test_metrics_health_feed.py` (247, 4 tests), the new
`tests/integration/test_otlp_metrics_receiver_e2e.py` (323, 3 tests over a
real `grpc.aio` wire with a real OTel SDK exporter), and
`tests/unit/observability/test_retention_sweep.py` (+111, 2 tests).

**The trace path is byte-identical to before.** An AST comparison of
`_handle_batch`, `pre_validate`, `_extract_spans`, `_dlq_insert`,
`_unrenderable_row`, `_count_by_field`, `_proto_to_dict`, `_attr_key` and
`_attr_value` against HEAD shows every body unchanged, and no function was
removed. The metric path is deliberately *parallel* to the span path rather
than a branch of it: sharing the code would couple the two paths' futures,
so a change to the span batch would silently change the metric batch.

**Ensemble review (spec §4.4: domain specialist + code-quality specialist
+ random generalist) — three lenses, all `needs_adjustment`, sixteen
defects found and fixed.** The ones that mattered most were the ones that
produced a *plausible wrong number* rather than an obvious failure:

| Defect | Symptom |
|---|---|
| A broken substrate answered **success** | `rejected_data_points=0` for data that was thrown away, while the plan's own acceptance check still passed |
| A cumulative histogram **clamped a producer restart to zero** | that interval lost for ever, while the counter path re-baselined correctly — the two halves disagreed about the same restart |
| An attribute key-set change **froze the metric** | stuck at a stale value for ever; the family now mints a sibling instrument |
| A replayed delta point was **deduped in the substrate but double-counted on Prometheus** | the two halves disagreed about what a replay is |
| `target_info` rendered `deployment_environment=""` | the label map was keyed by *label*, so an absent attribute overwrote a present one |

**`/health` gained a `metrics_feed`.** The metric path had no feed of its
own, which was the gap: a receiver that accepts exports, exposes them on
`/metrics` and stores **nothing** left `/health` reporting green. The
feed's `entities_count` is the **durable** row count, not the exposed
series, because the exposure is a separate path that keeps working when
the substrate is broken. A receiver that has simply not been exported to
yet reports **warming_up**, not degraded — a degraded feed is a 503, and
the launchd wrapper polls `/health` with `curl -fsS`, so a feed that
flapped to degraded on every cold start would make the wrapper kill the
server it was supposed to start. An unusable substrate is an **ongoing**
error, not a past one: the readiness flag is re-read each probe so the
feed cannot decay out of the halflife back to healthy.

Seventeen deviations from the plan text, recorded so Phase 3 and the
operator build against reality:

1. **`service.namespace` is NOT required for a metric point.** oneiric's
   `OTLPObservabilityAdapter` builds its resource with `service.name`,
   `deployment.environment` and optionally `service.version` — **and no
   namespace at all**. Requiring one would quarantine every metric oneiric
   sends, breaking REQ-M07's second producer while reporting "accepted,
   zero points stored". The namespace is stored as `""` — "not declared", a
   different fact from "unknown" — to satisfy the substrate's NOT NULL.
   **For the same reason the span path's namespace allowlist is NOT applied
   to metrics:** it would reject oneiric's empty namespace outright.
2. **`ts` is epoch nanoseconds**, from the point's `time_unix_nano`
   (falling back to `start_time_unix_nano`). A point with no timestamp is
   rejected (`ts`/`not_positive`) rather than stored at `ts=0`, where it
   would collide with every other `ts=0` point.
3. **`attributes` and `resource` are passed as dicts**, never pre-serialized
   — the substrate canonicalizes them itself, and DuckDB compares a JSON
   column in a UNIQUE constraint as text.
4. **The bridge lives in a new module**, `otlp_prometheus_bridge.py`, rather
   than in `prometheus_metrics.py` as §6's checklist says.
   `prometheus_metrics.py` is akosha's own application metrics and has no
   OTLP/protobuf knowledge; `otlp_metrics.py` is the receiver's *static*
   counter module. The dynamic-instrument machinery (temporality, bucket
   writes, cardinality) got its own module.
5. **The service-name prefix is skipped when the metric name already starts
   with the service name.** A naive `<service>_<metric>` would render
   mahavishnu's instruments as `mahavishnu_mahavishnu_observability_…`, and
   this plan's own acceptance check (`grep mahavishnu_observability`) would
   find nothing.
6. **Exposure drops are counted separately** — `akosha_otlp_metrics_exposure_dropped_total{reason}` —
   and not in `rejected_data_points`. The risk table said "drop the excess
   into the DLQ count", but the point *is* in the substrate, so counting it
   as rejected would tell a producer its data was thrown away when it was
   not. The cardinality cap is **100 distinct label-value combinations per
   metric family** (the plan asked for a cap but named no number).
7. **No bind-time assertion that `metrics_substrate` exists — but the
   readiness is still checked, and the check does not raise.** The trace
   receiver asserts `spans_substrate_table` and raises
   `LifecycleError("spans_substrate_missing")`; the metrics receiver does
   **not** raise, because failing the receiver's boot would take the
   *trace* path down with it — and a metrics dependency gap must never be
   able to stop trace ingestion. Instead the receiver probes readiness at
   bind time, logs at ERROR, and exposes
   `akosha_otlp_metrics_substrate_ready` (1/0) on `:8682/metrics`; an
   unusable substrate is distinguishable from a normal write failure on
   `akosha_otlp_metrics_insert_failed_total{reason}`, and it is reported
   to the producer through `partial_success.error_message`.

   **Correction 2026-11-06.** The original justification here — "the table
   is created by oneiric's `DuckdbHotStore.initialize()`, which akosha's
   `HotStore.initialize()` calls, so it is always there" — was **false
   against the locked dependency**. akosha's `uv.lock` pins *published*
   `oneiric==0.34.0`, whose `initialize()` has no metrics DDL and whose
   wheel contains neither `insert_metrics_substrate` nor
   `metrics_substrate_table`. In that configuration the table is never
   created, the insert raises, and — because the insert was wrapped in a
   blanket `except Exception` that only counted a failure — the export
   still answered `rejected_data_points=0, error_message=""`. The producer
   was told "accepted" for data that was thrown away, and because the
   Prometheus exposure path does not touch the substrate, the plan's own
   acceptance check (`curl :8682/metrics | grep mahavishnu_observability`)
   still **passed** while REQ-M03 was entirely unmet. Measured: 12 of the
   23 new tests fail in that shape.
8. **`value_sum_of_squares` is always NULL.** OTLP does not carry it and it
   cannot be derived from bucket boundaries without guessing where inside
   each bucket the observations fell. NULL says "not known"; a fabricated
   number would poison every variance computed over the column.
9. **Scope version and scope attributes have no column** in Phase 1's
   schema, so they ride in the substrate's `resource` JSON under
   `otel.scope` (`resource` is explicitly not part of the point's identity).
   Summary **quantiles are dropped entirely** — `prometheus_client`'s
   `Summary` has no quantile support, and `buckets_json` is reserved for
   the two histogram types.
10. **Histogram buckets are written through `prometheus_client`'s bucket
    values (private API)** — there is no public API for importing
    pre-aggregated bucket counts, and `observe()` would corrupt the sum.
    Cumulative values are converted to deltas per series, with a backwards
    jump treated as a producer restart (the counter-reset convention).
11. **Exponential histograms with negative buckets are stored but not
    exposed** — a Prometheus histogram's bounds would have to start below
    zero, and `prometheus_client` then omits the `_count` and `_sum`
    samples. Positive-only exponential histograms are exposed with bounds
    derived from `scale`/`offset`.
12. **The counters are `akosha_otlp_metrics_*`**, following the receiver's
    existing `akosha_otlp_spans_*` convention, rather than the plan's
    shorthand `otlp_metrics_*`. `akosha_otlp_metrics_insert_failed_total`
    gained a `reason` label (`substrate_unavailable` vs `write_failed`),
    which changes the metric's identity — pre-1.0, replace-not-extend.
    New: `akosha_otlp_metrics_batches_total`,
    `akosha_otlp_metrics_substrate_ready` (1/0),
    `akosha_otlp_metrics_rows_deleted_total`.
13. **`/health` gained a `metrics_feed`**, which the plan did not ask for.
    The plan's exit criterion could be satisfied by a live Prometheus
    series alone, which says nothing about whether anything is being
    *stored*. The feed reports the durable row count, so the two are
    distinguishable. See above.
14. **`metrics_substrate` is swept on the `spans_substrate` retention
    setting**, filtered on `inserted_at` — Phase 1 gave the table that
    column and no epoch-nanos one, and the schema lives in oneiric, which
    the receiver cannot change. `inserted_at` is stamped by the
    *database's* clock, so a skewed producer clock still cannot delete
    fresh rows — the same reasoning as the DLQ sweep's `rejected_at`.
15. **The substrate count lives in a new `akosha/storage/metrics_query.py`**,
    not in `hot_store.py` as §6's checklist says, because
    `akosha/storage/hot_store.py` has a hard 500-LOC CI cap and is "the
    code-graph overlay", not a query surface. It borrows the store's lock
    the way `SpanQuery` does — no second connection.
16. **Phase 3's documentation task has no targets.** It asked to "update the
    `docs/feature-tracking/` and `docs/runbooks/` notes that reference the
    Alloy metric path". Neither directory contains such a note — a grep of
    both for `Alloy|alloy|14317|4317` returns nothing. The documents that
    *do* describe the split are dated specs and decision records, which are
    records of what was true at the time and were deliberately left alone.
    The real documentation work is Phase 4's (the stage-1 gate query and the
    feature-tracking state), and it is still open.
17. **Removing the config field is order-independent, and the env var
    behaves differently from the YAML key.** mahavishnu's settings loader
    calls `_filter_subconfig_keys` *before* `MahavishnuSettings(**merged)`,
    which drops any key a sub-config does not declare. A leftover
    `otlp_metrics_endpoint` under `observability:` in `local.yaml` is
    therefore **silently dropped**, not fatal — so the code change could
    land first without a breakage window. The `MAHAVISHNU_OBSERVABILITY__*`
    overlay merges *after* that filter, so
    `MAHAVISHNU_OBSERVABILITY__OTLP_METRICS_ENDPOINT` now raises and
    every CLI command fails loudly, naming the removed key. (On the
    `get_settings()` path the exception is pydantic's `ValidationError`;
    on the app-startup path `bootstrap.load_config()` wraps it as
    `ConfigurationError("Failed to load configuration: …")` — same
    loudness, different type.) That asymmetry is correct — a stale env
    var should stop the process, a stale YAML key should not — but the
    plan did not describe it, and an operator who still exports the
    variable will hit it on the next restart. **The field shipped in
    v0.37.0 and v0.38.0** (see Phase 3's task list), so this is a real
    upgrade break for anyone who set the variable, not a hypothetical.

**Known gap — `/v1/metrics` on the HTTP listener is NOT implemented.** gRPC
is the required path and it is served; the HTTP listener still exposes only
`/v1/traces`. oneiric's adapter chooses its exporter by *config*
(`OTLPObservabilitySettings.protocol`, default `"grpc"` — there is no
automatic runtime fallback), so the default configuration works, but an
operator who sets `protocol: "http/protobuf"` would get 404s. This is the
remaining half of REQ-M07 for that configuration.

**Tasks:**
- Add `_MetricsServiceServicer` next to `_TraceServiceServicer`
  (`akosha/observability/otlp_receiver.py:692`), returning
  `ExportMetricsServiceResponse(partial_success=ExportMetricsPartialSuccess(
  rejected_data_points=N))` — the same "counts ride on partial_success"
  convention the trace servicer uses.
- Register it beside the trace servicer at
  `akosha/observability/otlp_receiver.py:224`
  (`add_MetricsServiceServicer_to_server`).
- Implement `_handle_metrics_batch(request)`: walk
  `resource_metrics → scope_metrics → metrics → data points`, honouring
  `sum` (monotonic / non-monotonic), `gauge`, `histogram`,
  `exponential_histogram` and `summary`; carry `resource.attributes` and
  `data_point.attributes` through.
- Validate before persisting, with the DLQ discipline the trace path has:
  a payload that fails validation goes to the DLQ, and the batch continues.
  A payload that fails **schema** validation is counted in
  `rejected_data_points` rather than aborting the request.
- Bridge to Prometheus: convert received data points into
  `prometheus_client` instruments on the shared registry
  (`akosha/observability/prometheus_metrics.py:96`) so they are rendered by
  the existing `/metrics` route (`akosha/mcp/server.py:1759`). Cumulative
  sums become `Counter`/`Gauge`; histograms become `Histogram` with the
  producer's bucket boundaries.
- Persist to `metrics_substrate` via Phase 1's primitives.
- **Accept metrics from BOTH in-process producers** (REQ-M07): mahavishnu's
  own exporter and oneiric's `OTLPObservabilityAdapter`. They are
  indistinguishable at the wire level — both speak OTLP MetricsService to
  `:4317` — so the receiver must not assume a single producer, and must
  namespace the exposed series by the resource's `service.name` so
  mahavishnu's and oneiric's instruments cannot collide.

**Exit criteria (strengthened 2026-11-07):** an OTLP metrics export to
`:4317` is accepted — the MetricsService answers it rather than
`UNIMPLEMENTED` — it appears in `curl http://localhost:8682/metrics`, and
it is **queryable through Prometheus**. It must ALSO leave a **non-empty
`metrics_substrate`** behind, and be **queryable through Prometheus**.

The "also" clause is not decoration. The exposure path does not touch the
substrate, so the first two clauses pass while REQ-M03 is entirely unmet:
the review reproduced a receiver that bound happily, accepted exports,
exposed the series, stored nothing, and answered
`rejected_data_points=0`. "Appears on `/metrics`" is evidence about the
exposure path alone; a durable row is evidence about the substrate.

#### Integration Contract ← REQUIRED

- **Triggered from:** the gRPC server started by
  `OTLPReceiver.start()` (`akosha/observability/otlp_receiver.py:223-228`),
  on the same `127.0.0.1:4317` port as the trace service.
- **Returns to / updates:** (a) the `metrics_substrate` table (Phase 1) and
  (b) the shared `CollectorRegistry` rendered at
  `http://localhost:8682/metrics`.
- **Demonstrable by:**
  `curl -s http://localhost:8682/metrics | grep <producer_metric_name>` after
  one OTLP metrics export; and
  `pytest tests/unit/observability/test_otlp_metrics_receiver.py`.
- **Rollback signal:** `akosha` logs `otlp_metrics_export_rejected` with a
  non-zero `rejected_data_points`, or the producer's export starts returning
  `UNIMPLEMENTED` again after a redeploy. Rollback = remove the
  `add_MetricsServiceServicer_to_server` line; the trace service is
  untouched and keeps running.
- **Observability added:** `akosha` counters
  `otlp_metrics_received_total`, `otlp_metrics_rejected_total`,
  `otlp_metrics_points_exported_total`, and a `otel_scope_info` /
  `target_info` conversion for each received resource.

### Phase 3: mahavishnu — retire the interim split, point metrics at the substrate

**Goal:** mahavishnu's metrics go to `:4317` again, with the interim
Alloy detour removed.

**Tasks:**
- Remove `observability.otlp_metrics_endpoint` from
  `mahavishnu/core/config.py` and the corresponding branch in
  `mahavishnu/core/observability.py` — **replace, don't extend**.
  **Correction 2026-11-07 (the plan originally said the field "was added
  by commit `0b0886ea` and never released, so removing it costs nothing").
  That was wrong.** `git merge-base --is-ancestor 0b0886ea v0.37.0` and
  `... v0.38.0` both succeed, and this repo's version *is* 0.38.0 — the
  field shipped in two releases. An operator on 0.37 or 0.38 who set
  `MAHAVISHNU_OBSERVABILITY__OTLP_METRICS_ENDPOINT` will hit a hard
  `ValidationError` on their next start, not a silent no-op. The
  *YAML* path is harmless (the loader drops unknown sub-keys before
  validation), but the env var stops the process.
- Remove the `otlp_metrics_endpoint` override from
  `~/.config/mahavishnu/local.yaml`.
- The metric exporter reverts to `observability.otlp_endpoint` (`:4317`),
  which is now a receiver that implements `MetricsService`.
- Update the `docs/feature-tracking/` and `docs/runbooks/` notes that
  reference the Alloy metric path.
- **Deployment order (stated 2026-11-07, previously unstated):** akosha
  must be running a build with `MetricsService` **before** mahavishnu
  restarts with metrics export enabled. A mahavishnu pointed at a
  trace-only receiver gets `UNIMPLEMENTED` once a minute — and this
  operator has metrics enabled in three places (`~/.zshenv`, the launchd
  plist, and `~/.config/mahavishnu/local.yaml`), so the next restart
  turns the failure on whether or not akosha has been upgraded.

**Exit criteria:** mahavishnu's OTLP metrics export is accepted by
akosha; the `UNIMPLEMENTED` error is absent; the series are visible on
`:8682/metrics` and in Grafana.

#### Integration Contract ← REQUIRED

- **Triggered from:** `ObservabilityManager._init_otel_components`
  (`mahavishnu/core/observability.py:218-230`), which builds the
  `PeriodicExportingMetricReader` and its `OTLPMetricExporter`.
- **Returns to / updates:** the `observability.otlp_endpoint` setting
  (`:4317`) for both signals, and the exported series land in akosha's
  registry and `metrics_substrate`.
- **Demonstrable by:** `mahavishnu` stderr contains no
  `Failed to export metrics` line over a 5-minute window, and
  `curl -s http://localhost:8682/metrics | grep mahavishnu_observability`
  returns the drift and liveness series.
- **Rollback signal (corrected 2026-11-07):** TWO clauses, because the
  original one was reachable only in a failure mode this fleet does not
  actually hit.
  1. `opentelemetry.exporter.otlp.proto.grpc.exporter` logging
     `Failed to export metrics` **with `StatusCode.UNIMPLEMENTED`** — that
     specifically means "the receiver is trace-only", i.e. roll *forward*
     by upgrading akosha, not back. `UNAVAILABLE` and `DEADLINE_EXCEEDED`
     produce the same line shape and mean different things; "any status
     code" was too loose to be a trigger.
  2. `opentelemetry.sdk.metrics._internal.export` logging `Metric
     collection timed out`. **This is the clause that actually fires.**
     `MetricReader.collect()` raises `MetricsTimeoutError` *before* it
     calls the exporter, so the export is never attempted and the "Failed
     to export metrics" line never appears — the original signal was
     silent exactly while metrics were being dropped. The live log shows
     both shapes.
  - **Rollback = revert the commit.** The plan previously said "re-add
    the field and point it at `http://127.0.0.1:14317`", on the grounds
    that "Alloy's receiver accepts metrics even though it does not expose
    them". **That is false for the gRPC path**, and the fleet's own log
    says so: 50 lines of `Failed to export metrics to 127.0.0.1:14317,
    error code: StatusCode.DEADLINE_EXCEEDED`. The export does not get
    accepted — it hangs until the deadline. The documented rollback would
    have swapped `UNIMPLEMENTED` for `DEADLINE_EXCEEDED` and left the
    operator with no working path at all.
- **Observability added:** the drift counters
  (`mahavishnu_observability_drift_detected_total`) and the liveness
  instruments (`..._changepoint_evaluations_total`,
  `..._changepoint_detector_active`) become queryable on `:8682`.

**Delivered 2026-11-07 — mahavishnu `feat/phase3-metrics-revert-split`**
(base `6637d4c6`, not pushed). Six files — the five below plus this plan
file: `mahavishnu/core/config.py` (the
interim `otlp_metrics_endpoint` field removed; the `metrics_enabled` and
`otel_metrics_enabled` descriptions rewritten), `mahavishnu/core/
observability.py` (the metric exporter targets `observability.otlp_endpoint`),
`tests/unit/test_config.py` and `tests/unit/test_observability_signal_gating.py`
(comments that described the split as current fact), and the new
`tests/unit/test_observability_metrics_endpoint.py` (5 tests).

**The field's removal is order-independent, and the reason is not
obvious.** mahavishnu's settings loader calls `_filter_subconfig_keys`
*before* `MahavishnuSettings(**merged)`, which drops any key a sub-config
does not declare. A leftover `otlp_metrics_endpoint` under `observability:`
in `local.yaml` is therefore **silently dropped**, not fatal — the code
change could land first, with no breakage window, contrary to what the
plan's ordering implied. The env var is the opposite:
`MAHAVISHNU_OBSERVABILITY__OTLP_METRICS_ENDPOINT` merges *after* that
filter and now raises `ValidationError`, stopping every CLI command and
naming the removed key. Both behaviours were verified by running them, not
inferred.

**Nine in-repo places described the split as current fact.** The plan's task
list named only the config field and the `observability.py` branch. An audit
of the whole repo found the same claim in **two other fields of those same
two files** — `ObservabilityConfig.metrics_enabled` and the top-level
`MahavishnuSettings.otel_metrics_enabled`, the latter ~1,400 lines away
from the field being removed — plus a runtime log string ("akosha's
receiver serves TraceService only") that would have kept telling operators
the split was live, and four comments/assertion messages across two test
files. Editing only the named field would have left the fleet documenting a
topology that no longer existed.

**Consolidating the two paths destroys one diagnostic, and the plan did
not say so.** Before, "metrics failing while traces succeed" proved the
two paths had diverged — a config problem. After, both signals share one
endpoint, so a substrate outage fails both at once and the logs can no
longer distinguish "one broken path" from "the whole substrate is down".
That is an accepted consequence of consolidation, but it is the reason the
rollback signal above names two clauses: a single symptom no longer
identifies which half broke.

**Ensemble review (spec §4.4: domain specialist + code-quality specialist
+ random generalist) — three lenses, all `needs_adjustment`, fifteen
defects found and fixed.** The *production* change was judged correct by
all three: the field is gone, the exporter targets `otlp_endpoint`, no
leftover reference survives anywhere in the tree, and the load-bearing
external fact (akosha's receiver serving MetricsService on :4317) was
independently confirmed against akosha's source by two of the lenses.
What the review found was that the change's own **evidence layer** did not
support it:

| Defect | Symptom |
|---|---|
| The endpoint test passed while **nothing was exported** | `_init_otel_components` catches every exception and falls back to mocks, and the exporters are built BEFORE the fallible work that follows — so a test asserting only on exporter construction stays green while the manager silently exports nothing. Reproduced independently by the reviewer |
| The plan's **documented rollback did not work** | it pointed operators at Alloy's `:14317`, which the fleet's own log shows returning `DEADLINE_EXCEEDED` 50 times. The rollback would have swapped one broken path for another |
| The plan's **rollback signal was unreachable** | `MetricReader.collect()` raises `MetricsTimeoutError` *before* calling the exporter, so "Failed to export metrics" never appears exactly while metrics are being dropped |
| The plan said the field **"was never released"** | it shipped in v0.37.0 and v0.38.0; the current version IS 0.38.0. "Removing it costs nothing" was false for anyone who set the env var |
| A config description claimed oneiric's schema was `extra="forbid"` | it is `extra="allow"`; the claim was contradicted by the operator's own `local.yaml`, updated in the same window |
| Both rewritten descriptions implied the nested flag **alone** gated export | it is an OR with the top-level flag, which is the one the operator actually sets — so `observability.metrics_enabled: false` cannot turn export off |
| `docs/CONFIGURATION.md` said the default was `True` | the code default is `False` |
| The two "endpoint" tests **passed against the pre-change commit** | the interim field's `None` value fell back to `otlp_endpoint` anyway, so they were not regression tests for the property they name |

Two of the three lenses independently reported the false `extra="forbid"`
claim, the wrong default in `docs/CONFIGURATION.md`, and the
mis-described fixture docstring. Three independent reports of the same
defect is what makes those fixes trustworthy rather than one reviewer's
reading.

**The plan's Phase 3 documentation task had no targets** (deviation 16).
The documentation that actually needed changing was the config field's own
description and the runtime log line — neither of which the plan named.

**Live verification 2026-11-07 — the exit criteria are met.** The running
akosha receiver (restarted by launchd onto `ab76a77`) serves MetricsService
on :4317. A real `ExportMetricsServiceRequest` over gRPC was answered
`rejected_data_points=0`, `error_message=''` — no UNIMPLEMENTED — and
mahavishnu's own exporter, built from the Phase 3 code against the real
operator config, reported `otlp_endpoint=http://localhost:4317` and
flushed a counter that appeared as
`mahavishnu_phase3_probe_total{probe="phase3"} 1.0` on `:8682/metrics`,
alongside `target_info{service_name="mahavishnu",
service_namespace="bodai"}`.

**The durable side was checked separately, because the exposure path and
the substrate path are independent.** `/health`'s `metrics_feed` reported
`entities_count=475`, `substrate_ready=true`, `errors_total=0` — 475 rows
actually in `metrics_substrate`, counted by `count_metrics_points` over the
durable table rather than over the Prometheus registry. The three batches
include oneiric's own `OTLPObservabilityAdapter` export, so REQ-M07's
second producer is landing live.

**A caveat on what was proven, and where.** The exporter was exercised as a
short-lived process running the Phase 3 code, not by restarting the
long-running mahavishnu MCP server — that server still runs the
pre-Phase-3 code and therefore still exports to :14317, and it will keep
doing so until the change lands and the server restarts. The receiver side
and the exporter's endpoint resolution are both proven; the long-running
process's own restart is a deployment action, not a code one.

**Known issue found during Phase 3 — forking from a multi-threaded
mahavishnu can crash the child.** Three review dispatches through
`pool_route_execute` each timed out at 600 s with no output, and macOS
crash reports showed why: a child of the mahavishnu MCP server died with
`EXC_BAD_INSTRUCTION` and *"BUG IN CLIENT OF LIBDISPATCH: trying to lock
recursively"*. The chain is `pool_route_execute` → `_repo_has_git` →
`asyncio.create_subprocess_exec("git", ...)` → CPython's `fork_exec`.
CPython 3.14.10 on this build has `_HAVE_POSIX_SPAWN_CLOSEFROM = False`, so
with the default `close_fds=True` it cannot use `posix_spawn` and must
`fork()`. `fork()` in a multi-threaded process copies every other thread
into the child; a gRPC thread that was inside `ares_init_sysconfig_macos`
→ `dns_configuration_copy` → libdispatch's `os_log` held a libdispatch
lock at fork time, so the child inherited it locked and died on its first
libdispatch call. This is a fleet-wide hazard, not a one-off: the same
fork-unsafe pattern appears at every `asyncio.create_subprocess_exec` and
`subprocess.Popen` call site in a process that also runs gRPC. It is
**outside this plan's scope** and is recorded here because it was
discovered while verifying Phase 3 and it silently breaks any
pool-dispatched work on this machine.

### Phase 4: verification and gate enablement

**Goal:** prove the end-to-end path and turn the §7 stage-1 gate from a
documented hope into a query.

**Tasks:**
- End-to-end check: trigger a drift, confirm the counter moves on
  `:8682/metrics` and in Prometheus (`:9090/api/v1/query`).
- Write the gate query in the drift runbook
  (`docs/runbooks/MAHAVISHNU_DRIFT_DETECTION.md`): "no drift" is
  `changepoint_evaluations_total` rising **and** `drift_detected_total`
  absent — not "drift_detected_total absent" alone.
- Retire the interim `~/.config/mahavishnu/local.yaml` override and the
  Alloy metric path note.
- Update `docs/feature-tracking/2026-09-10-observability-changepoint.md` to
  record that the gate now has a queryable source.

**Exit criteria:** the gate query returns a number, and a deliberately
injected drift moves it.

#### Integration Contract ← REQUIRED

- **Triggered from:** the change-point tick loop
  (`ObservabilityManager.start_change_point_tick_loop`), which records
  `changepoint_evaluations_total` on every evaluation.
- **Returns to / updates:** the drift-detection runbook's stage-1 gate
  section, and the feature-tracking doc's state.
- **Demonstrable by:** the gate query returns a value from Prometheus, and
  `pytest tests/unit/observability/test_change_point_tick_loop.py` passes
  (11 tests, including the two liveness regressions added 2026-10-27).
- **Rollback signal:** the gate query errors or returns no series for
  10 minutes while the server is healthy — the metrics path regressed.
- **Observability added:** the gate's own two instruments,
  `mahavishnu_observability_changepoint_evaluations_total` and
  `mahavishnu_observability_changepoint_detector_active`.

**Delivered 2026-11-07.** The gate query is written, the feature-tracking
doc records that the gate has a queryable source, and both branches of the
gate were verified against live Prometheus.

**The gate query** (`docs/runbooks/MAHAVISHNU_DRIFT_DETECTION.md`,
"Stage-1 gate"):

```promql
rate(mahavishnu_observability_changepoint_evaluations_total[10m]) > 0
and on() absent(mahavishnu_observability_drift_detected_total)
```

with the liveness half detached so "no drift" and "detector never wired"
can be told apart — the two differ only in whether the drift counter is
absent, which is ambiguous on its own. The `on()` is load-bearing:
`absent()` yields an unlabelled vector and PromQL's `and` matches on the
full label set by default, so without it the gate returns empty even when
there is genuinely no drift.

**Verification, against live Prometheus.** With no drift the gate returned
`0.0257` (a number). After a deliberately injected drift it went empty
while the liveness half kept returning a number and
`mahavishnu_observability_drift_detected_total` read `2`. The drift was
injected by adding a 3-worker pool to the tick loop's metric source: the
CUSUM fired at score `16.5` against a threshold of `14.0`
(`severity=minor`, `direction=up`), and the independent 3-sigma
reference detector fired alongside it (`z=7.617`).
`mahavishnu_observability_changepoint_evaluations_total` read `44` and
`changepoint_detector_active` read `44` at that point.

**The gate was not merely undocumented — it was unreachable, and two
defects had to be fixed before it could be enabled.** Phase 4's task
list named no code changes, and this plan's §6 listed none for Phase 4
either; the two defects are pre-existing (both from `a886942b`, the
2026-10-24 tier-1 round-3 review), not regressions from Phases 1–3.

- **The detector was blind, not calm.** The tick loop's metric source
  returned a snapshot keyed by **pool id**, but the loop reads
  `snapshot.get(target_metric)`, where `target_metric` is a metric
  *name* ("pool_queue_depth" by default) and never a pool id. Every
  tick therefore evaluated a constant `0.0`, so the CUSUM accumulator
  could never cross its threshold and `drift_detected_total` could
  never move. A gate built on "drift_detected_total absent" over a
  blind detector is vacuously green forever — it would have reported
  "no drift" through every real drift. The `metric_source` contract is
  `{metric_name: value}`, so the closure now publishes the aggregate
  pool depth under the configured metric name.
- **`changepoint_detector_active` contradicted its own HELP text.** It
  documented itself as "1 while the tick loop is running, 0 when it is
  not" but added 1 on *every* tick, so it grew with the tick count
  (44 after 44 ticks) and an operator querying `== 1` matched nothing.
  It now adds 1 on the first tick and 0 thereafter, which keeps the
  series present — so it still goes stale when the process dies — while
  reporting the documented value.

**Feeding the detector real data required a second change, or the fix
would have been a regression.** `pool_queue_depth` is a raw count, and
the CUSUM accumulates `observation - target_mean - slack`. With the
default `target_mean: 0.0`, any non-zero pool depth accumulates
`≈4.75` per tick and fires within three ticks of baseline traffic — a
false-positive storm. `settings/mahavishnu.yaml` now sets
`target_mean_auto: true`, which derives the in-control mean from the
sampler's rolling baseline and is deployment-agnostic (no operator
needs to know their own baseline). The detector is deferred until that
window holds 30 samples (R3-M2), but the evaluation counter ticks
throughout, so the gate stays queryable from the first tick while
detection warms up.

**Two operator-facing items were retired; one was refused.**
`~/.config/mahavishnu/local.yaml`'s interim `otlp_metrics_endpoint`
override is gone (2026-11-07). The Alloy metric path note — the
`~/.zshenv` comment claiming "akosha's receiver implements TraceService
only, so metric exports to :4317 fail with UNIMPLEMENTED once a
minute" — is **stale and still present**: the permission classifier
denied the edit as an unauthorized persistent-profile change, and the
comment is now false in both halves (the receiver implements
MetricsService, and the export succeeds). It needs the operator's
decision. `/usr/local/etc/grafana-alloy/config.alloy` is unchanged by
design (NG1).

**Deployment note — the live service was NOT restarted.** The
verification ran as a short-lived process using the real production
entry point (`MahavishnuApp.start_change_point_tick_loop`), the same
technique Phase 3 used, because restarting the service was denied as a
production deploy. The long-running Mahavishnu MCP server (PID 21173,
started 11:26) still runs **pre-Phase-3** code and still exports
metrics to Alloy's `:14317`, which returns `DEADLINE_EXCEEDED`. It must
be restarted to pick up Phase 3 and these fixes; until then its own
drift metrics do not reach the substrate. The drift and gate numbers
above came from the verification process, which shares the substrate
with the live server.

## 6. Required Code Changes

**oneiric** (`/Users/les/Projects/oneiric`)
- [x] `oneiric/adapters/vector/duckdb_hot_store.py` — `metrics_substrate`
      DDL, `insert_metrics_substrate`, `metrics_substrate_table`
- [x] oneiric lifespan hook — idempotent `metrics_substrate` creation
- [x] oneiric tests — `tests/adapters/test_duckdb_hot_store_metrics.py`
      (named for the module under test, beside its span sibling)
- [x] **one change** to `oneiric/adapters/monitoring/otlp.py` (added
      2026-11-06 by the Phase 2 review) — the adapter's single endpoint
      works against a receiver that implements both services, but its
      `insecure` default forced TLS against a plaintext receiver, so
      **zero points arrived**. `insecure: bool | None = Field(default=None)`
      lets the endpoint scheme decide (`http://` → plaintext,
      `https://` → TLS) and an explicit value still overrides. The
      *endpoint* stays single; only the transport default changes. (NG6,
      REQ-M07)

**akosha** (`/Users/les/Projects/akosha`)
- [x] `akosha/observability/otlp_receiver.py` — `_MetricsServiceServicer`,
      `add_MetricsServiceServicer_to_server`, `_handle_metrics_batch` —
      landed in `ab76a77`
- [x] `akosha/observability/otlp_prometheus_bridge.py` — OTLP →
      `prometheus_client` bridge — and `akosha/observability/otlp_metrics.py`
      — receiver counters — landed in `ab76a77`. The plan named
      `prometheus_metrics.py` for both; that module already existed as the
      shared-registry owner (`get_metrics_registry()`), so the bridge got
      its own module.
- [x] akosha tests — `test_otlp_metrics_receiver.py`,
      `test_metrics_health_feed.py`, `test_otlp_metrics_receiver_e2e.py` —
      landed in `ab76a77`

**mahavishnu** (`/Users/les/Projects/mahavishnu`)
- [x] `mahavishnu/core/config.py` — remove `otlp_metrics_endpoint` (REQ-M04)
- [x] `mahavishnu/core/observability.py` — metric exporter reverts to
      `otlp_endpoint` (REQ-M04); keep the liveness instruments (REQ-M05)
- [x] `tests/unit/test_observability_metrics_endpoint.py` — pins the
      removal (field gone, env var fatal, YAML key dropped) and the
      endpoint (metrics and traces share one), including the check that
      the manager did **not** fall back to mocks
- [x] `docs/runbooks/MAHAVISHNU_DRIFT_DETECTION.md` — the stage-1 gate
      query (REQ-M05) — **Phase 4**
- [x] `docs/feature-tracking/2026-09-10-observability-changepoint.md` —
      gate now queryable (REQ-M05) — **Phase 4**
- [x] `mahavishnu/core/app.py` — the tick loop's metric source publishes
      the aggregate pool depth under the configured metric NAME. It
      returned a pool-id-keyed snapshot, so the loop read a constant
      `0.0` and the detector could never fire — **Phase 4** (REQ-M05)
- [x] `mahavishnu/core/observability.py` — `changepoint_detector_active`
      reports the value its HELP text promises (1 while ticking) instead
      of counting ticks — **Phase 4** (REQ-M05)
- [x] `settings/mahavishnu.yaml` — `changepoint.target_mean_auto: true`,
      so feeding the detector real data does not fire on baseline —
      **Phase 4** (REQ-M005)
- [x] `tests/unit/observability/test_change_point_tick_loop.py` — pins
      the metric-source namespace (and a renamed target metric) and the
      active gauge's value — **Phase 4**

**operator (outside the repos)**
- [x] `~/.config/mahavishnu/local.yaml` — drop the
      `otlp_metrics_endpoint` override once Phase 3 lands
- [x] `/usr/local/etc/grafana-alloy/config.alloy` — *no change*; the metric
      path is retired, not completed (NG1)
- [ ] `~/.zshenv` — the stale OTLP note ("akosha's receiver implements
      TraceService only, so metric exports to :4317 fail with
      UNIMPLEMENTED once a minute"). Now false in both halves. The
      permission classifier denied the edit as an unauthorized
      persistent-profile change — **needs the operator's decision**

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `pytest` (oneiric) — `test_metrics_substrate.py` | passes; rows round-trip | oneiric CI |
| `pytest` (akosha) — `test_otlp_metrics_receiver.py` | passes; export accepted, series exposed | akosha CI |
| `pytest` (mahavishnu) — `test_change_point_tick_loop.py` | 11 passed | mahavishnu CI |
| `pytest` (mahavishnu) — `test_observability_metrics_endpoint.py` | 6 passed; 3 of them fail against the pre-change commit | mahavishnu CI |
| `pytest` (mahavishnu) — `test_observability.py` | no **new** failures vs. the 2026-10-27 baseline (2 pre-existing) | mahavishnu CI |
| `curl -s localhost:8682/metrics \| grep mahavishnu_observability` | drift + liveness series present | terminal |
| `curl -s 'localhost:9090/api/v1/query?query=mahavishnu_observability_changepoint_evaluations_total'` | a number | **verified 2026-11-07**: `44` |
| `curl -s --get 'localhost:9090/api/v1/query' --data-urlencode 'query=rate(mahavishnu_observability_changepoint_evaluations_total[10m]) > 0 and on() absent(mahavishnu_observability_drift_detected_total)'` | a number while no drift; empty once drift fires | **verified 2026-11-07**: `0.0257` with no drift, empty after the injected drift |
| `grep -c "Failed to export metrics" ~/.local/state/mcp/logs/mahavishnu.err` | **not usable as written** (corrected 2026-11-07): the log is append-only and already holds 3,062 matching lines, so the count is 3,062 forever. Count lines *after a recorded marker* — note the current count before the restart, then diff — and add the `opentelemetry.sdk.metrics._internal.export` clause, which is the one that fires when collection times out | mahavishnu stderr log |
| `curl -s localhost:9200/_cat/indices` | unchanged (OpenSearch is not in this path) | terminal |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Metric-name collision between producers in the shared `prometheus_client` registry | medium | there are **two** producers (Finding 10): mahavishnu's exporter and oneiric's monitoring adapter. Namespace by the resource's `service.name`; document the label set; reject (count as `rejected_data_points`) rather than silently overwrite |
| Unbounded label cardinality in received data points | medium | cap distinct label values per metric; drop the excess into the DLQ count, matching the trace path's discipline |
| Cumulative-sum semantics: a restart resets the counter, Prometheus sees a counter reset | medium | document the reset; `changepoint_evaluations_total` is a counter, so a reset shows as a decrease — the gate uses `rate()`/`increase()`, which handle it |
| Oneiric's `DuckdbHotStore` is shared with other consumers | low | the metrics table is additive; `spans_substrate` DDL and the retention sweep are untouched (NG4) |
| The Alloy path is left half-wired (receiver accepts, nothing exposes) | **medium, corrected 2026-11-07** | intentional (NG1), but the plan's claim that "Alloy's metric receiver keeps accepting, so any producer still pointed there is unaffected" is **false for the gRPC path**: the fleet's log holds 50 × `Failed to export metrics to 127.0.0.1:14317, error code: StatusCode.DEADLINE_EXCEEDED`. Alloy accepts nothing and exposes nothing on that path — it hangs. Phase 3 points mahavishnu back at the substrate, which is the only working path |
| A producer's histogram bucket boundaries differ between exports | low | accept the producer's boundaries on first sight; log and ignore later divergences rather than resetting the histogram |

## 9. Decision Rule

This plan is **done enough** when all of the following hold:

1. An OTLP metrics export to `127.0.0.1:4317` is accepted by akosha and the
   series appear in `curl -s localhost:8682/metrics`.
2. Prometheus has scraped them (visible in
   `curl -s 'localhost:9090/api/v1/query?query=<name>'`) and Grafana's
   Prometheus datasource renders them.
3. mahavishnu's stderr has had no `Failed to export metrics` line for 10
   minutes, and `observability.otlp_metrics_endpoint` no longer exists in
   the codebase.
4. The §7 stage-1 gate query returns a number, and a deliberately injected
   drift moves `drift_detected_total` off zero.

If scope pressure forces a cut, cut in this order: **G3 (durable storage) →
G1's histogram/summary types → G5 (gate docs)**. G1's `sum` + `gauge` types
and G2's exposure are the load-bearing parts — without them the metrics are
accepted and then vanish, which is strictly worse than the current honest
`UNIMPLEMENTED`.
