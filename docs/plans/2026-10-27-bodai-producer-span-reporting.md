---
status: active
role: canonical
kind: plan
date: 2026-10-27
last_reviewed: 2026-10-27
superseded_by: null
topic: otel-producer-reporting
title: "Producer Span Reporting — make the heartbeat roster mean something"
---

# Producer Span Reporting — make the heartbeat roster mean something

## 1. Outcome

Every service on `otel.receiver.known_mcp_servers` reports a span to
akosha's substrate within the heartbeat watcher's 60s window, and
`akosha_otlp_heartbeat_p0_a_total{service=...}` stops incrementing for
rostered services that are alive.

**Success signal:** `curl -fsS http://127.0.0.1:8682/metrics | grep
akosha_otlp_heartbeat_p0_a_total` stops rising, and
`search_spans` returns rows whose `service_name` is each roster entry.

## 2. Goals

1. Every rostered service installs a tracer provider that exports to the
   substrate receiver (`http://127.0.0.1:4318/v1/traces`).
2. Every rostered service emits a **periodic liveness span**, so silence
   means "the telemetry pipeline is broken" rather than "nobody called a
   tool".
3. One implementation of (1) and (2) for the whole fleet — not five copies.
4. The launchd boot timeout stops killing akosha before it becomes healthy.

## 3. Non-Goals

1. Changing the heartbeat watcher's detection semantics (two consecutive
   absences, `query_empty` ≠ `query_threw`). That code is correct.
2. Changing the roster. The roster names are the fleet's service
   identities and they are right.
3. Replacing the receiver canary. It proves the *write* path; the liveness
   span proves the *producer* path. Both are needed.
4. Shipping an OTLP metrics path to the substrate. The receiver
   implements TraceService only.

## 4. Current Findings

Measured on the live service, 2026-10-27.

**The substrate has no producer rows at all.**

```
akosha_otlp_spans_received_total  576.0
akosha_otlp_spans_inserted_total  576.0
akosha_otlp_heartbeat_p0_a_total{service="mahavishnu"}    292.0
akosha_otlp_heartbeat_p0_a_total{service="akosha"}        292.0
akosha_otlp_heartbeat_p0_a_total{service="session-buddy"} 292.0
akosha_otlp_heartbeat_p0_a_total{service="oneiric"}       292.0
akosha_otlp_heartbeat_p0_a_total{service="crackerjack"}   292.0
```

`search_spans` returns only `_receiver_canary` rows (plus two
`cli-tools` rows from a manual proof). Not one rostered service has ever
written a span.

### 4.1 Per-producer root causes

| Producer | Tracer provider at startup? | Endpoint | `service.name` | FastMCP middleware |
|---|---|---|---|---|
| akosha | yes, but exporter-less | `OTLP_ENDPOINT` unset → `None` | `akosha-mcp` (≠ roster `akosha`) | n/a (own `tracing.py`) |
| mahavishnu | no — `ObservabilityManager` is never constructed at startup | default `http://localhost:4317` | Resource `mahavishnu` ✓ | yes, but no provider → no-op tracer |
| session-buddy | no — `configure_otel_tracing()` returns `False` without `OTEL_EXPORTER_OTLP_ENDPOINT` | — | `session-buddy` ✓ | yes, but no provider → no-op tracer |
| crackerjack | no | — | — | never attached |
| oneiric | no | — | — | never attached |

Sources: `akosha/mcp/server.py:552`, `akosha/observability/tracing.py:40`,
`mahavishnu/mahavishnu/core/observability.py:180`,
`session_buddy/mcp/telemetry.py:72`, `crackerjack/mcp/server_core.py:187`,
`oneiric/mcp/server.py`.

### 4.2 The shared cause: no env, no provider

The launchd plists set no `OTEL_EXPORTER_OTLP_*` variable, and launchd
services do not inherit the shell environment. `~/.zshrc:193` sets

```sh
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

which is why a **CLI-spawned** script with an explicitly configured
`TracerProvider` exports successfully, while every launchd service is
silent. The launchd plists were checked: none of the five sets an OTLP
endpoint.

### 4.3 A second, independent akosha bug

`akosha/observability/tracing.py:74-105` builds the `TracerProvider`
**twice**:

```python
tracer_provider = TracerProvider(resource=resource)
if otlp_endpoint:
    tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
...
tracer_provider = TracerProvider(resource=resource, sampler=sampler)  # <- orphans the processor
trace.set_tracer_provider(tracer_provider)
```

The second assignment replaces the provider that carries the span
processor, so the exporter is attached to a provider that is never
registered. Even with `OTLP_ENDPOINT` set, akosha would export nothing.

### 4.4 The semantic gap: request-driven spans are not a heartbeat

Even with every exporter wired, a rostered MCP server emits spans only
when someone calls a tool. The watcher's window is 60s and its threshold
is two consecutive absences. An **idle** fleet therefore trips P0-A by
construction — the alert would be a guaranteed false positive, not a
detector.

The receiver already has the right shape for this: the canary
(`akosha/observability/canary_watcher.py`) emits a synthetic marker span
every 30s to prove the *write* path. What is missing is the producer-side
equivalent proving the *export* path.

### 4.5 The seam

Every one of the five services starts through
`mcp_common.server.launcher.launch(build_server=..., component_name=...)`:

| Service | `component_name` | Roster entry |
|---|---|---|
| akosha | `"akosha"` | `akosha` ✓ |
| mahavishnu | `"mahavishnu"` | `mahavishnu` ✓ |
| session-buddy | `"session-buddy"` | `session-buddy` ✓ |
| oneiric | `"oneiric"` | `oneiric` ✓ |
| crackerjack | `"crackerjack"` | `crackerjack` ✓ |

`component_name` matches the roster **1:1**. The launcher is the shared
seam, and `component_name` is already the canonical service identity.

### 4.6 Boot timeout

`~/Library/LaunchAgents/com.mcp.akosha.plist` passes `--timeout 120`.
The log shows 245 boot kills in the last 300k lines of `akosha.err`
("did not respond within 120s, killing PID …") against 496 successful
"Application startup complete". mahavishnu's plist already uses `300`
for the same reason — mahavishnu's boot is slow too.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-001
    title: "Shared producer tracing helper in mcp-common"
  - id: REQ-002
    title: "Periodic liveness span emitted by every rostered service"
  - id: REQ-003
    title: "Launchd plists set the substrate OTLP endpoint"
  - id: REQ-004
    title: "akosha's tracer provider carries its span processor"
  - id: REQ-005
    title: "akosha's service name matches the roster"
  - id: REQ-006
    title: "Boot timeout exceeds the measured time-to-healthy"
```

## 5. Implementation Phases

### Phase 1: mcp-common producer telemetry (REQ-001, REQ-002)

**Goal:** one implementation of exporter setup + liveness emission.

**Tasks:**
1. New module `mcp_common/server/producer_telemetry.py`:
   - `configure_producer_tracing(service_name, *, service_namespace="bodai",
     environment="production")` — installs a `TracerProvider` whose
     `Resource` carries `service.name` / `service.namespace` /
     `deployment.environment`, plus a `BatchSpanProcessor` over an OTLP
     HTTP exporter. Idempotent: does **not** override a provider another
     component already installed. Opt-in: does nothing unless
     `OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`)
     is set, so MCP servers outside the fleet are unaffected.
   - `run_liveness_emitter(service_name, stop_event, *, interval_seconds=30)`
     — emits a `_service_liveness` span per interval.
2. Wire both into `mcp_common/server/launcher.py::launch`:
   `configure_producer_tracing(component_name)` before `build_server()`,
   and the liveness emitter running for the life of the server.
3. Unit tests for: provider installation, no-override, opt-in gate,
   namespace on the Resource, liveness span emission.

**Exit criteria:** `mcp-common` tests green; a component launched through
`launch()` exports a span whose `service.name` is its `component_name`.

#### Integration Contract

- **Triggered from**: `mcp_common.server.launcher.launch()` — every Bodai
  MCP server's startup path.
- **Returns to / updates**: the process-global OTel `TracerProvider`
  (`opentelemetry.trace.set_tracer_provider`) and the substrate
  `spans_substrate` table via the receiver on `:4318`.
- **Demonstrable by**: `mcp_common` test asserting a launched component
  exports a span with the right `service.name`; live, `search_spans`
  returns a row for the component.
- **Rollback signal**: `akosha_otlp_spans_rejected_total` climbs after
  rollout, or the exporter's own error log appears. Rollback is removing
  the `OTEL_EXPORTER_OTLP_ENDPOINT` line from the plist — no code revert.
- **Observability added**: the `_service_liveness` span itself, plus the
  receiver's existing `akosha_otlp_spans_received_total` /
  `inserted_total` counters, which now have a non-canary source.

### Phase 2: akosha's own tracer provider (REQ-004, REQ-005)

**Goal:** akosha exports under the name the roster watches, and its
exporter is not orphaned.

**Tasks:**
1. Fix the double-`TracerProvider` construction in
   `akosha/observability/tracing.py` — build once, add the processors,
   then apply the sampler.
2. Reuse an already-installed global provider instead of replacing it, so
   the launcher's provider (installed first, with the substrate endpoint)
   wins and akosha's internal spans inherit `service.name=akosha`.
3. Update `akosha/mcp/server.py:552` to pass the roster name.

**Exit criteria:** akosha's own spans reach the substrate with
`service_name=akosha`.

#### Integration Contract

- **Triggered from**: `akosha/mcp/server.py` lifespan startup.
- **Returns to / updates**: the process-global tracer provider and the
  substrate table.
- **Demonstrable by**: `search_spans(service_name="akosha")` returns rows
  after a restart.
- **Rollback signal**: `akosha_otlp_spans_rejected_total{service="akosha"}`
  climbs. Rollback is the env line in the plist.
- **Observability added**: `akosha_otlp_spans_received_total` gains a
  self-sourced series.

### Phase 3: launchd configuration (REQ-003, REQ-006)

**Goal:** the services get the endpoint, and akosha survives its boot.

**Tasks:**
1. Add `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318` and
   `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` to the five service
   plists.
2. Measure akosha's real time-to-healthy during the restart and set
   `--timeout` from the measurement plus headroom (mahavishnu already
   uses 300).

**Exit criteria:** all five services report; no boot kills in the log.

#### Integration Contract

- **Triggered from**: `launchd` loading `~/Library/LaunchAgents/*.plist`.
- **Returns to / updates**: each service process's environment.
- **Demonstrable by**: `launchctl kickstart -k gui/$(id -u)/com.mcp.akosha`
  followed by a `/health` 200 and no new "did not respond within" line.
- **Rollback signal**: a service that will not come up healthy after the
  restart. Rollback is restoring the plist backup.
- **Observability added**: `akosha_otlp_heartbeat_p0_a_total` flatlines.

## 6. Required Code Changes

- [ ] `mcp-common/mcp_common/server/producer_telemetry.py` (new)
- [ ] `mcp-common/mcp_common/server/launcher.py`
- [ ] `mcp-common/tests/unit/test_producer_telemetry.py` (new)
- [ ] `akosha/akosha/observability/tracing.py`
- [ ] `akosha/akosha/mcp/server.py`
- [ ] `akosha/tests/unit/test_tracing.py`
- [ ] `~/Library/LaunchAgents/com.mcp.{akosha,mahavishnu,session-buddy,oneiric,crackerjack}.plist`

## 7. Validation Matrix

| Command | Expected | Evidence |
|---|---|---|
| `mcp-common/.venv/bin/pytest tests/unit/test_producer_telemetry.py` | pass | test output |
| `akosha/.venv/bin/pytest tests/unit/test_tracing.py` | pass | test output |
| `curl -fsS :8682/metrics \| grep heartbeat_p0_a` | flat over 5 min | metrics |
| `mcp__akosha__search_spans {service_name: "<each roster entry>"}` | ≥1 row each | tool output |
| `tail akosha.err \| grep 'did not respond within'` | no new lines | log |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Span volume: 5 services × 1 span/30s ≈ 86k rows/day | certain | the 30-day retention sweep already bounds it; the liveness span is ~1 row/30s/service |
| A service's own tracer provider overrides the launcher's | medium | the launcher installs first; `set_tracer_provider` does not override; akosha's `setup_telemetry` is changed to reuse rather than replace |
| `service.namespace` drift → DLQ quarantine | low | the helper pins `service.namespace=bodai`, which is on the receiver's allowlist |
| The liveness span is mistaken for a real trace | low | it is named `_service_liveness`; the canary uses the same `_`-prefix convention |
| Env-gated opt-in leaves a service unwired | low | the plist edit is the checklist item; verification queries each roster name individually |

## 9. Decision Rule

Done when `akosha_otlp_heartbeat_p0_a_total` is flat for five consecutive
minutes **and** `search_spans` returns a row for each of the five roster
names. If the liveness emitter proves too noisy, dropping it is a config
change, not a code revert — but the roster then has no liveness signal and
the watcher must be treated as request-driven only.
