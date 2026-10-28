---
status: draft
role: implementation
kind: plan
date: 2026-10-27
last_reviewed: 2026-10-27
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
- **Observability added:** `oneiric` counter
  `metrics_substrate_rows_inserted_total` and
  `metrics_substrate_insert_failed_total`.

### Phase 2: akosha — MetricsService servicer, ingestion, exposure

**Goal:** akosha accepts OTLP metrics on `:4317` and exposes them on
`:8682/metrics`.

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

**Exit criteria:** an OTLP metrics export to `:4317` is accepted, appears in
`curl http://localhost:8682/metrics`, and is queryable through Prometheus.

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
  `mahavishnu/core/observability.py` — **replace, don't extend**. The
  interim field was added by commit `0b0886ea` and never released, so
  removing it costs nothing.
- Remove the `otlp_metrics_endpoint` override from
  `~/.config/mahavishnu/local.yaml`.
- The metric exporter reverts to `observability.otlp_endpoint` (`:4317`),
  which is now a receiver that implements `MetricsService`.
- Update the `docs/feature-tracking/` and `docs/runbooks/` notes that
  reference the Alloy metric path.

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
- **Rollback signal:** `opentelemetry.exporter.otlp.proto.grpc.exporter`
  logging `Failed to export metrics` with any status code. Rollback = re-add
  the field and point it at `http://127.0.0.1:14317` (Alloy's receiver
  accepts metrics even though it does not expose them).
- **Observability added:** the drift counters
  (`mahavishnu_observability_drift_detected_total`) and the liveness
  instruments (`..._changepoint_evaluations_total`,
  `..._changepoint_detector_active`) become queryable on `:8682`.

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

## 6. Required Code Changes

**oneiric** (`/Users/les/Projects/oneiric`)
- [ ] `oneiric/adapters/vector/duckdb_hot_store.py` — `metrics_substrate`
      DDL, `insert_metrics_substrate`, `metrics_substrate_table`
- [ ] oneiric lifespan hook — idempotent `metrics_substrate` creation
- [ ] oneiric tests — `test_metrics_substrate.py`

**akosha** (`/Users/les/Projects/akosha`)
- [ ] `akosha/observability/otlp_receiver.py` — `_MetricsServiceServicer`,
      `add_MetricsServiceServicer_to_server`, `_handle_metrics_batch`
- [ ] `akosha/observability/prometheus_metrics.py` — OTLP → `prometheus_client`
      bridge, receiver counters
- [ ] akosha tests — `test_otlp_metrics_receiver.py`

**mahavishnu** (`/Users/les/Projects/mahavishnu`)
- [ ] `mahavishnu/core/config.py` — remove `otlp_metrics_endpoint` (REQ-M04)
- [ ] `mahavishnu/core/observability.py` — metric exporter reverts to
      `otlp_endpoint` (REQ-M04); keep the liveness instruments (REQ-M05)
- [ ] `docs/runbooks/MAHAVISHNU_DRIFT_DETECTION.md` — the stage-1 gate
      query (REQ-M05)
- [ ] `docs/feature-tracking/2026-09-10-observability-changepoint.md` —
      gate now queryable (REQ-M05)

**operator (outside the repos)**
- [ ] `~/.config/mahavishnu/local.yaml` — drop the
      `otlp_metrics_endpoint` override once Phase 3 lands
- [ ] `/usr/local/etc/grafana-alloy/config.alloy` — *no change*; the metric
      path is retired, not completed (NG1)

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `pytest` (oneiric) — `test_metrics_substrate.py` | passes; rows round-trip | oneiric CI |
| `pytest` (akosha) — `test_otlp_metrics_receiver.py` | passes; export accepted, series exposed | akosha CI |
| `pytest` (mahavishnu) — `test_change_point_tick_loop.py` | 11 passed | mahavishnu CI |
| `pytest` (mahavishnu) — `test_observability.py` | no **new** failures vs. the 2026-10-27 baseline (2 pre-existing) | mahavishnu CI |
| `curl -s localhost:8682/metrics \| grep mahavishnu_observability` | drift + liveness series present | terminal |
| `curl -s 'localhost:9090/api/v1/query?query=mahavishnu_observability_changepoint_evaluations_total'` | a number | terminal |
| `grep -c "Failed to export metrics" ~/.local/state/mcp/logs/mahavishnu.err` | no new lines after the change | mahavishnu stderr log |
| `curl -s localhost:9200/_cat/indices` | unchanged (OpenSearch is not in this path) | terminal |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Metric-name collision between producers in the shared `prometheus_client` registry | medium | namespace by `service.name`; document the label set; reject (count as `rejected_data_points`) rather than silently overwrite |
| Unbounded label cardinality in received data points | medium | cap distinct label values per metric; drop the excess into the DLQ count, matching the trace path's discipline |
| Cumulative-sum semantics: a restart resets the counter, Prometheus sees a counter reset | medium | document the reset; `changepoint_evaluations_total` is a counter, so a reset shows as a decrease — the gate uses `rate()`/`increase()`, which handle it |
| Oneiric's `DuckdbHotStore` is shared with other consumers | low | the metrics table is additive; `spans_substrate` DDL and the retention sweep are untouched (NG4) |
| The Alloy path is left half-wired (receiver accepts, nothing exposes) | low | intentional (NG1); Alloy's metric receiver keeps accepting, so any producer still pointed there is unaffected — and Phase 3 points mahavishnu back at the substrate |
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
