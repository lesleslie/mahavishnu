---
status: draft
role: canonical
date: 2026-10-19
last_reviewed: 2026-10-19
superseded_by: null
blocks_on: []
topic: event-sourced-otel
---

# Bodai Event-Sourced OTel Architecture

**Status:** Draft, awaiting user review (post-brainstorm, pre-writing-plans)
**Date:** 2026-10-19
**Stage:** 1 of 2 (this spec covers stage 1 only; stage 2 listed in §9 as non-binding preview)
**Repos in scope:** `mcp-common`, `oneiric`, `akosha`, `mahavishnu`, `session-buddy`
**Operator-config scope:** Bifrost gateway (port 8471) — no code change; UI values listed in Appendix C
**Out of scope:** `bifrost-mcp` (not done; doesn't do what earlier conversation assumed)

---

## 1. Context

Bodai's telemetry story today is asymmetric. The producer side is partially wired: 4 of 6 Bodai components initialize OTel SDKs (`mahavishnu`, `akosha`, `session-buddy`, `oneiric`); 2 don't (`crackerjack` has zero OTel imports; `bifrost-mcp` is out of scope). The backend side is mostly empty: the local Grafana Alloy collector on `:4317`/`:4318` has a working **metrics** pipeline (Prometheus exporter at `:12345/metrics`) and a **trace** pipeline that ends at a `debug` exporter writing spans to stdout. No Tempo, no Loki, no Akosha-side hot-store ingestion sits behind traces today.

The fix is not "more instrumentation." It is **(a) a substrate-default producer** so the producer side actually unifies, and **(b) an event-sourced log in Akosha** with **a closed feedback loop** for routing signals.

This spec defines the design for the stage-1 delivery.

---

## 2. Goals

- Make every current and future `*-mcp` server a producer of OTel traces and metrics by default, with no per-component code change required.
- Codify resource-attribute conventions so spans from any Bodai component carry a stable identity (service.name, service.namespace, telemetry.source, telemetry.source.type, deployment.environment).
- Land an event-sourced log in Akosha HotStore; treat OTel spans as immutable append-only events; projections read from the log.
- Close the selector-fitness loop in v1: a routing-decision span informs no FSM in stage 1; outcome spans feed a circuit-breaker FSM whose recommendation informs the Mahavishnu router.
- Coexist with Akosha's existing `run_fitness_analysis`, partitioned by input scope (system-level view vs. selector-level view). No replacement; no drift.
- Emit OpenTelemetry GenAI semantic-convention spans from any producer that calls an LLM (the Bifrost gateway is the first).
- Provide operational dashboards, alertable conditions, and crash recovery posture that keep the system routing in every failure mode.

## 3. Non-Goals

- Replace `run_fitness_analysis` with FSMs. Coexist with explicit partitioning rules (§4.7).
- Touch `bifrost-mcp` (out of scope per user direction).
- Close a feedback loop inside the OTel collector ([OTel Collector architecture](https://opentelemetry.io/docs/collector/architecture/), [OTel routing connector docs](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/connector/routingconnector/README.md)). The collector is never on the read path (§5.2).
- Ship non-selector FSMs in stage 1 (model-effectiveness, drift, cost, quality-judge). Stage 2 (§9).
- Adopt a SaaS backend in stage 1. Tempo + Grafana-stack mirrors as stage-2 only.
- Build a SaaS-only intelligence alternative. Akosha HotStore is the canonical event log for projections.
- Re-design the Crackerjack OTel story as a primary deliverable. Crackerjack gains producer capability from the substrate default and is smoke-tested.

---

## 4. Architecture Overview

Three layers, with the loop closing **inside Akosha's log boundary** — never inside the OTel collector.

```
producers (every `*-mcp` server, substrate default-on)
  └─ OTel SDK ─gRPC→ :4317 / :4318 (Akkosha's OTLP receiver; substrate default)
                  Akkosha OTLP receiver
                    └─ write → HotStore.spans
                                  ▲
                                  │ (read projection)
                                  │
                          SelectorFitnessFSM (Akosha, separate process)
                                  │
                                  └─→ Redis hot tier (TTL 30s)
                                          │
                                          ▼ (read)
                                  Mahavishnu TaskRouter
                                          │
                                          └─→ emit routing.decision span (via SDK → back to top)

Alloy (sibling collector, :12345 metrics, optional local debug mirror)
       │ not on the read path; never re-routes traces back to itself.
```

### 4.1 Why this topology

| Aspect | Before | After (stage 1) |
|---|---|---|
| Producer activation | Per-component opt-in via env vars | Substrate default-on (`*-mcp` inherits) |
| Resource attributes | Inconsistent across components | Codified substrate contract (§4.2) |
| Backend for traces | Stdout-only via Alloy debug exporter | Akosha HotStore (canonical event log) |
| Backend for metrics | Alloy Prometheus exporter (works today) | Unchanged |
| Routing intelligence | Manual team orchestration + YAML rule table | YAML + FSM recommendations |
| Health feed | `run_fitness_analysis` (system-wide spans) | Unchanged |
| GenAI semconv spans | None emitted anywhere | Future producer (Bifrost gateway is the first) |

### 4.2 Resource-attribute convention (codified)

Every span resource carries:

| Attribute | Source | Example values |
|---|---|---|
| `service.name` | substrate | `mahavishnu`, `akosha`, `session-buddy`, `oneiric`, `crackerjack` |
| `service.namespace` | substrate default `bodai` | `bodai` |
| `service.version` | optional, from settings | `0.30.0` |
| `deployment.environment` | env | `development`, `staging`, `production` |
| `telemetry.source` | alias of `service.name` | (vendor back-compat) |
| `telemetry.source.type` | substrate, per server | `mcp_server`, `bodai_component`, `llm_gateway` |
| `telemetry.sdk.name` | auto-injected | `opentelemetry` |
| `telemetry.sdk.language` | auto-injected | `python` |

### 4.3 The structural anti-loop rule

The OTel collector has a documented feedback-loop anti-pattern: traces flowing from an exporter back into a receiver that re-emits the same trace, with the routing connector as the canonical offender. **This architecture forbids the loop by construction.**

- The **write path** is producer → SDK → Akosha OTLP receiver → HotStore.
- The **read path** is HotStore → projection (a separate process run by Akosha's FSM host) → FSM → Redis.
- The **router** reads Redis (not OTel, not the collector) and emits a new span tree, which closes the loop by hitting the write path again.
- **The OTel collector is never on the read path.** If a future refactor adds a loop here, that refactor must be reverted.

### 4.4 Bifrost gateway operator-config

The Bifrost gateway (port 8471, separate process; not in any Bodai repo) is the first producer of `gen_ai.*` spans. It uses **OTLP/HTTP** (not the gRPC substrate default), because the gateway's admin UI exposes HTTP exporter settings first.

| Resource attribute | Value |
|---|---|
| `service.name` | `bifrost-gateway` |
| `service.namespace` | `bodai` |
| `telemetry.source.type` | `llm_gateway` |
| `deployment.environment` | per environment |

OTLP exporter endpoint: `http://localhost:4318/v1/traces` (Akkosha HTTP receiver, see §5.1 for the dual-port binding). Insecure (loopback) on. Format: `OTel GenAI Extension (Recommended)`. No auth headers (loopback). Export timeout 5s.

**Dual protocol, single canonical receiver:** Akosha's OTLP receiver binds **both** `:4317` (gRPC, substrate-default for `*-mcp` servers) and `:4318` (HTTP, used by the Bifrost gateway). Bodai `*-mcp` producers ship gRPC by substrate default; the Bifrost gateway ships HTTP because its admin UI is HTTP-first. Both streams land in the same `HotStore.spans` table. There is no per-message protocol branching downstream.

These Bifrost UI values are an operator action; no Bodai-repo code change.

---

## 5. Component Contract

### 5.1 Stage-1 file changes (across 5 repos)

| Repo | Files new | Files modified | New LOC | Why |
|---|---|---|---|---|
| `mcp-common` | 1 (`mcp_common/server/telemetry.py`, default-on flip) + tests | 1 (`factory.py` bootstrap) | ~120 | Substrate default-on flip; OTelSettings model |
| `oneiric` | 0 | 2 (`adapters/monitoring/otlp.py`, `core/substrate_settings.py`) | ~50 | Settings default, namespace convention |
| `akosha` | 6 (`fsm/types.py`, `fsm/base.py`, `fsm/registry.py`, `fsm/projections.py`, `fsm/selector_fitness.py`, `mcp/tools/selectors.py`, `migrations/2026_10_19_add_genai_and_dispatch_event_columns.py`) | 2 (`hotstore/schema.py`, `observability/tracing.py`) | ~750 | FSM substrate, first FSM, HotStore migration, MCP tool |
| `mahavishnu` | 2 (Redis recommendation reader in `pools/`, `DecisionSpanEmitter` in `pools/manager.py`) | 2 (`core/model_routing.py`, `pools/manager.py`) | ~200 | Router augmentation |
| `session-buddy` | 0 | 1 (`settings/session-buddy.yaml`) + integration test | ~50 | Explicit substrate-default verification |
| **Total** | **9 files new** | **6 files modified** | **~1170 LOC** | |

Bifrost gateway: **no code change**; see §4.4.

### 5.2 Substrate contract — `mcp-common`

```python
# mcp_common/server/telemetry.py (new defaults)
class OTelSettings(BaseModel):
    enabled: bool = True  # was: opt-in via env var
    endpoint: str | None = None  # None → autodetect :4317 (Akkosha gRPC receiver)
    protocol: Literal["grpc", "http/protobuf"] = "grpc"
    insecure: bool = True  # loopback default
    headers: dict[str, str] = Field(default_factory=dict)
    resource: dict[str, str] = Field(
        default_factory=lambda: {
            "service.namespace": "bodai",
            "telemetry.source.type": "mcp_server",
        }
    )

class FastMCPOpenTelemetryMiddleware:
    def __init__(self, service_name, otel_settings: OTelSettings | None = None, ...):
        self._settings = otel_settings or OTelSettings()
        # init gates on _settings.enabled (was: env-var presence)
```

The substrate middleware also injects a synthetic `telemetry.heartbeat` span every 60s while the FastMCP server is up. Heartbeat is substrate-internal; the regression detector (§7.2, P0-A) uses it.

### 5.3 `oneiric/adapters/monitoring/otlp.py` (settings defaults)

Existing adapter; only the settings model gains new fields with sensible defaults:

```python
class OTLPObservabilitySettings(BaseModel):
    enabled: bool = True
    endpoint: str | None = None  # see autodetect contract
    protocol: Literal["grpc", "http/protobuf"] = "grpc"
    insecure: bool = True
    service_name: str = "oneiric-app"
    service_namespace: str = "bodai"  # was: implicit blank
    telemetry_source_type: Literal["mcp_server", "bodai_component", "llm_gateway"] = "mcp_server"
    environment: str = "development"
    enable_traces: bool = True
    enable_metrics: bool = True
```

### 5.4 Akkosha FSM substrate (Pydantic types)

```python
# akosha/fsm/types.py
from enum import Enum
from pydantic import BaseModel, Field

class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
    DEGRADED = "degraded"

class FSMInput(BaseModel):
    selector: str
    task_class: str
    window_seconds: int = 60
    span_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    latency_p99_ms: float | None = None
    gen_ai_tokens_used: int | None = None
    observed_at: str

class CircuitObservation(BaseModel):
    state: CircuitState
    entered_at: str
    failure_rate: float = Field(ge=0.0, le=1.0)
    sample_size: int = Field(ge=0)
    threshold: float
    consecutive_failures: int = 0

class FSMRecommendation(BaseModel):
    selector: str
    task_class: str
    state: CircuitState
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    evidence_hash: str          # sha256(canonical_json(FSMInput.dict())) — pin-to-input
    emitted_at: str
    ttl_seconds: int = 30

class FSMContract(BaseModel):
    name: str
    selector: str
    task_class: str
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    minimum_sample_size: int = Field(default=10, ge=1)
    half_open_probe_fraction: float = Field(default=0.1, ge=0.0, le=1.0)
```

Substrate (`akosha/fsm/base.py`): `CircuitBreakerFSM`, a generic state-machine shell. Future FSMs are config + a `process(input: FSMInput) -> FSMRecommendation` implementation.

### 5.5 HotStore schema migration

`akosha/migrations/2026_10_19_add_genai_and_dispatch_event_columns.py` — idempotent, with rollback support.

```sql
ALTER TABLE spans ADD COLUMN gen_ai_provider            TEXT;
ALTER TABLE spans ADD COLUMN gen_ai_model               TEXT;
ALTER TABLE spans ADD COLUMN gen_ai_tokens_in           INTEGER;
ALTER TABLE spans ADD COLUMN gen_ai_tokens_out          INTEGER;
ALTER TABLE spans ADD COLUMN gen_ai_cost_usd_estimate   NUMERIC(10, 6);
ALTER TABLE spans ADD COLUMN gen_ai_cache_hit           BOOLEAN;
ALTER TABLE spans ADD COLUMN dispatch_event_payload     JSON;
ALTER TABLE spans ADD COLUMN dispatch_event_emitted_at  TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_spans_selector_task_class_outcome
    ON spans(selector, task_class, outcome, timestamp);
CREATE INDEX IF NOT EXISTS idx_spans_source_type
    ON spans(telemetry_source_type, timestamp);
```

`gen_ai.*` columns fill in as producers (Bifrost gateway first) emit `gen_ai.*` spans. `dispatch_event_*` columns reserved — stage 1 leaves them nullable; stage 1.5 (Mahavishnu's DecisionSpanEmitter) fills them.

### 5.6 The FSM selection filter

`akosha/fsm/projections.py` — the read-side projection materializes `FSMInput` for one `(selector, task_class)` pair from `HotStore.spans`. The SQL the projection runs:

```sql
SELECT
  COUNT(*)                                     AS span_count,
  SUM(CASE WHEN outcome = 'error' THEN 1 ELSE 0 END) AS failure_count,
  PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms) AS latency_p99_ms
FROM spans
WHERE selector = :selector
  AND task_class = :task_class
  AND outcome IN ('success', 'error')
  AND timestamp > now() - :window_seconds * INTERVAL '1 second';
```

### 5.7 Partition rule (codified, FSM-registration-validated)

- `run_fitness_analysis` reads **every** span (system-level view). Unchanged.
- Each FSM's projection reads **only** spans matching its `(selector, task_class)` selection. Two FSMs never share the same `(selector, task_class)` tuple.
- "Overlap" = identical `(selector, task_class)` tuple. Different FSMs on the same selector but different task_class are fine; same selector and same task_class is forbidden at registration.
- If two FSMs ever need the same slice (e.g. future drift + model_effectiveness on the same `(selector, task_class)`), the slice becomes a **shared projection** (one reader, multiple FSMs consuming the materialized FSMInput). The partition rule preserves the projection-input layer, not the FSM stage.
- Rule enforced at registration by `FSMRegistry.register(...)` (§7.7).

---

## 6. Data Flow

### 6.1 Worked example: a code-generation dispatch

The full sequence, with time offsets and concrete events:

| t (ms) | Component | Action |
|---|---|---|
| 0 | Operator | `mcp__mahavishnu__pool_route_execute(prompt=...)` enters `pool_manager.route_task(...)`. |
| 1 | TaskRouter (Mahavishnu) | Redis GET `akosha:fsm:selector_fitness:mahavishnu_pool:code_generation` → `FSMRecommendation{state:CLOSED,confidence:0.92,ttl_remaining:24s}`. |
| 2 | DecisionSpanEmitter (NEW) | Emits `routing.decision` span with `task.class=code_generation`, `selector=mahavishnu_pool`, `selected_reason=fsm_recommendation`, `fitness.snapshot_hash=0x7a3f...`. |
| 3 | Worker | Calls Claude/Anthropic. |
| 180 | Worker | Emits `gen_ai.chat` span tree: parent + `gen_ai.user.message` / `gen_ai.choice` / `gen_ai.system.message` events; attributes `gen_ai.provider.name=anthropic`, `gen_ai.request.model=claude-opus-5`, `gen_ai.usage.input_tokens=512`, `gen_ai.usage.output_tokens=2048`, `gen_ai.usage.cost=0.0827`. |
| 185 | OTel SDK | Batched gRPC export. `OTEL_EXPORTER_OTLP_ENDPOINT` resolves to Akosha's `:4317` (substrate autodetect). |
| 190 | Akosha OTLP receiver | Validates resource attributes; inserts row; computes embedding. |
| 1200 | SelectorFitnessFSM | Projection tick. Reads 14 outcome spans since last tick: failure_rate=1.0. |
| 1210 | FSM | CLOSED → OPEN. Emits `FSMRecommendation{state:OPEN,reason="14/14 failures in 1s",confidence:0.99}`. Redis SET TTL 30. |
| 1400 | Next TaskRouter call | Reads REDIS → OPEN. Router avoids `mahavishnu_pool`. Emits `routing.decision` with `selected_reason="fsm_recommendation_avoid"`. |
| 30000 | Redis TTL expires | Subsequent Router calls fall back to YAML rule (emits `selected_reason="yaml_default"`). |
| 300000 (5 min) | FSM half-open timer | Probes `mahavishnu_pool` at `half_open_probe_fraction=0.1`. Outcomes observed. Spans > failures → HALF_OPEN → CLOSED. |

The FSM observation is **not** stored as a span — it's a read-side projection over the immutable event log.

### 6.2 Boundary behaviors

| Boundary | Failure | Observable | Recovery |
|---|---|---|---|
| Producer → OTLP exporter | Collector unreachable | SDK queues, drops oldest if queue full, emits `telemetry.exporter.errors` metric | Auto-retry |
| Akosha OTLP receiver | Schema not migrated | LifecycleError at startup; receiver never accepts | Migration is startup-blocking (§7.6) |
| Akosha OTLP receiver | HotStore write fail | Receiver returns OTLP server-error; SDK retries with backoff | Operator disk/fs check |
| FSM projection | HotStore read > threshold (default 500 ms) | FSM emits `DEGRADED` | Window resumes |
| FSM host | `sample_size < minimum_sample_size` | FSM emits `CLOSED, confidence=low` | Subsequent ticks widen window |
| Redis hot tier | Cold | FSM emits `DEGRADED`; TaskRouter falls back to YAML | Redis reconnect |
| TaskRouter | Redis unreachable | Uses YAML rule; emits `selected_reason="yaml_default"` | Trivial |
| TaskRouter | FSM `DEGRADED` | Uses YAML; emits `selected_reason="yaml_fallback_degraded"` | FSM recovers |
| FSM state machine | Threshold breach sustained | Holds OPEN (no flapping); half-open probe after configurable window | Per Resilience4j pattern |
| Substrate middleware | Server has `otel.enabled: false` | Server still boots; heartbeat absent but logs `telemetry-disabled-at-instance` | Explicit operator action |
| Substrate middleware | Endpoint set but unreachable | SDK retries with backoff | Endpoint recovers |

### 6.3 GenAI semconv attribute contract

Stage 1's `SelectorFitnessFSM` does **not** parse `gen_ai.*` — its input is `outcome`, `latency_p99_ms`. Stage 2's `model_effectiveness` FSM parses:

```
span.name = "<gen_ai.operation.name>"   # chat | embeddings | tool_use | agent_run
attributes:
  gen_ai.operation.name
  gen_ai.provider.name
  gen_ai.request.model
  gen_ai.response.model
  gen_ai.usage.input_tokens
  gen_ai.usage.output_tokens
  gen_ai.usage.cost                       # USD estimate
  gen_ai.request.temperature              # optional
  gen_ai.request.max_tokens               # optional
events:
  gen_ai.user.message
  gen_ai.choice
  gen_ai.system.message
  gen_ai.tool.message
```

Pinned to a specific release tag of [open-telemetry/semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai) (Development stability as of mid-2026).

---

## 7. Error Handling and Operational Posture

### 7.1 Severity taxonomy

| Severity | Definition | Routing impact | Operator action |
|---|---|---|---|
| P0 | Routing integrity: HotStore write fail persistent, FSM stuck, substrate regression, migration fail-loud | Suspicious / lost | Page within 5 min |
| P1 | Routing degraded but functional: collector unreachable >5 min, Redis cold >5 min, FSM DEGRADED >10 min | YAML fallback engaged | Ticket within 1 business day |
| P2 | Single-FSM transient: confidence drop, half-open spikes, span drops | None | Dashboard review |
| WARN | Expected transient: SDK retry, single-batch drop | None | Log only |

### 7.2 P0-A — Substrate regression detector

**Detection:** Heartbeat span (`telemetry.heartbeat`) auto-injected every 60s by `mcp-common` middleware. Akosha's health-feed cycles every 60s query against `HotStore.spans` for recent `telemetry.heartbeat` rows grouped by `service.name`. Each known-running `*-mcp` server should appear in the rollup every window; absence for two consecutive windows = P0.

**Concrete detector location:** `akosha/observability/heartbeat_watcher.py` (new), running inside Akosha's existing health-feed scheduler. Emits a per-`service.name` series of `{ts, last_heartbeat_at}` and a single P0 alert when a known `service.name` (`akosha` health-feed registry) goes silent. The known-server list is the same one that currently powers `HealthFeedState("mcp_tool_call")`.

**Runbook:**
1. Identify the silent server (alert includes `service.name`).
2. Verify `mcp-common` version on that server includes the heartbeat injection.
3. Confirm `otel.enabled` is not flipped to `false` in settings.
4. Remove opt-out; restart; verify heartbeat resumes.
5. If still silent, escalate to mcp-common owner.

### 7.3 P0-B — HotStore write failure

**Detection:** 3+ consecutive `hotstore_write_failed` ERROR from the receiver; SDK emits `telemetry.exporter.errors` metric.

**Runbook:** disk / fs-quota / lock-contention checks. Restart Akosha (startup-migration re-runs if schema is intact).

### 7.4 P1 — FSM stuck

**Detection:** No FSM tick has emitted a Redis recommendation in >2× the expected tick interval, AND HotStore has matching new spans.

**Runbook:** Read host logs; check HotStore reachability from FSM host; reconcile FSMContract config in `akosha_fsm_registry` with in-memory contract.

### 7.5 P1 — Redis cold

**Detection:** `akosha:fsm:selector_fitness:*` reads return `KeyError`. TaskRouter logs `fsm_recommendation_absent` >5/min. Akosha FSM host logs `redis_unreachable`.

**Runbook:** `redis-cli ping`. Check substrate health (`oneiric.health`). Retry with backoff. Routing continues on YAML.

### 7.6 Migration fail-loud

Every persistent store in this architecture gets a startup preflight:

```python
# akosha/hotstore/schema.py
class HotStoreSchema:
    REQUIRED_VERSION = "2026-10-19"  # bumped per release

    def preflight(self) -> None:
        actual = self.current_version()
        if actual < REQUIRED_VERSION:
            raise LifecycleError(
                f"hotstore_schema_outdated: have {actual}, need {REQUIRED_VERSION}. "
                f"Run akosha migrations up before starting the receiver."
            )
```

### 7.7 FSM registration guard (partition-rule enforcement)

```python
class FSMRegistry:
    def register(self, contract: FSMContract, projection_params: tuple) -> None:
        existing = self._filter_by_overlap(projection_params)
        if existing:
            raise LifecycleError(
                f"fsm_projection_overlap: {contract.name} overlaps with "
                f"{[c.name for c in existing]} on input slice {projection_params}. "
                f"Either narrow the new FSM's scope, or route through a shared projection."
            )
```

### 7.8 Crash recovery posture

| Failure | Routing outcome | Recovery |
|---|---|---|
| Mahavishnu restart (everything else up) | YAML fallback for ≤30s | Trivial |
| Akosha restart | Routing on YAML; rebuilds as new spans emit | Trivial |
| Redis restart | TaskRouter falls back to YAML; FSM writes fail with backoff | Reconnects; re-emits |
| HotStore write failure | Receiver returns error; SDK retries; FSM runs against partial window | Operator disk check |
| Both Mahavishnu and Akosha restart | Substrate autoload continues; routing lost intelligence | Coincidence; P0 |
| Whole host down (OTLP receiver unreachable) | Producers queue per SDK; routing on YAML | Trivial; emissivity resumes |

### 7.9 Operational dashboards

Panels to ship alongside the runtime (concrete JSON / Grafana provisioning is a stage-1 PR deliverable):

- **Intelligence health** — emitting-components count vs. expected; heartbeat chart. Alert P0-A.
- **Telemetry pipeline drops** — `telemetry.exporter.errors` per service; `hotstore_write_failed` per minute. Alert P0-B.
- **FSM state map** — state distribution per FSM over time; per-selector current state.
- **Hot tier latency** — Redis read p50/p95/p99 from TaskRouter.
- **HotStore ingestion rate** — rows/s; embedding-compute p95; spans-dropped counter.
- **Substrate vs. component detection** — heartbeat presence/absence grid.

---

## 8. Testing Strategy

### 8.1 The load-bearing integration test

`mcp-common/tests/integration/test_substrate_load_bearing_claim.py` — proves the substrate change unifies the fleet:

```python
async def test_every_mcp_server_is_a_producer_without_per_component_settings():
    server = build_minimal_fastmcp_server()  # uses mcp-common bootstrap
    await server.handle_tool_call("echo", {"msg": "hi"})
    span = await test_collector.wait_for_span("mcp.tools.call.echo", timeout=2.0)
    assert span.resource.attributes["service.namespace"] == "bodai"
    assert span.resource.attributes["telemetry.source.type"] == "mcp_server"
```

Companion in Akosha: `tests/integration/test_session_buddy_substrate_default.py` — boot the real session-buddy server in a subprocess; verify spans arrive. **Both pass = the substrate's contract holds.**

### 8.2 Heartbeat regression test

`mcp-common/tests/integration/test_heartbeat_injection.py` — proves heartbeat auto-emits; opt-out suppresses it.

### 8.3 FSM state-machine tests (Hypothesis)

Property-based: for any `(failure_rate, sample_size, threshold)`, the FSM produces a stable state on identical input distribution (no flapping). Plus 8-10 example tests for explicit transition paths.

### 8.4 Partition-rule enforcement

`akosha/tests/unit/fsm/test_registry.py` — overlapping input slices raise `LifecycleError` at registration; `_input_scope` invariant verified.

### 8.5 End-to-end dispatch test

`akosha/tests/integration/fsm/test_dispatch_e2e.py` — synthesize 14 failing outcomes, let FSM tick, observe router read recommendation and emit `routing.decision` with `selected_reason="fsm_recommendation_avoid"`. Wait for TTL; assert YAML fallback engages.

### 8.6 Boundary tests

Table-driven `tests/integration/test_boundaries.py` — one test per failure mode in §6.2.

### 8.7 GenAI semconv conformance

`tests/integration/test_genai_semconv_conformance.py` — JSON-schema-like assertion against the pinned GenAI semconv release.

### 8.8 Test pyramid

| Layer | Count | Max runtime each | Coverage target |
|---|---|---|---|
| Unit | ~50 | 5 s | 100% on FSM substrate, registry, OTel receiver schema validator |
| Integration | ~25 | 30 s | ≥89% project floor |
| E2E | ~5 | 2 min | Smoke-level |
| Smoke | ~3 | 30 s | One server per smoke |

### 8.9 CI / merge gating

- `pytest -m "not slow"` on every PR.
- `pytest -m "slow"` nightly.
- `test_substrate_load_bearing_claim.py` is required-to-pass at merge.
- `crackerjack run -v -f` (per project CLAUDE.md) gates merge.

### 8.10 Out of scope

- Load testing (≥1000 spans/s sustained) — stage 2.
- Multi-region failover — out of architecture scope.
- Stage-2 FSMs (model_effectiveness, drift, cost) — designed in stage 1 contracts; **tested in stage 2**.
- Tempo / SaaS mirror — stage 2.

---

## 9. Stage-2 Preview (Non-Binding)

The following are stage-2 candidates, not in this spec's scope. Each is a small additive PR once stage-1 has landed.

- **`model_effectiveness` FSM** — reads `routing.decision` + `outcome` + `gen_ai.*` attributes; emits per-`(provider, model, task_class)` recommendations.
- **`drift` FSM** — reuses Mahavishnu's existing CUSUM/Page-Hinkley codebase; emits anomaly events.
- **`cost` FSM** — parses `gen_ai.usage.cost`; per-tenant / per-project attribution.
- **Tempo mirror** — Akosha OTLP receiver forwards a copy to `otelcol.exporter.otlp` pointing at `localhost:4317` (Allyo's `tempo` listener). Akosha remains canonical.
- **SaaS variant** — opt-in, per-environment, behind `telemetry.source.type=gateway`.

---

## 10. Decisions Log

| Decision | Choice | Alternatives | Rationale |
|---|---|---|---|
| Substrate defaults to opt-out, not opt-in | `mcp-common` middleware default-on; per-component settings disable knob | Opt-in per server (status quo); per-server env-var opt-out | Every `*-mcp` server becomes a producer without per-component code change; the load-bearing guarantee |
| FSM runtime lives in Akosha, not Mahavishnu | Akosha hosts event log + FSM substrate | Mahavishnu background coroutines; new `bodai-intelligence-mcp`; no FSM substrate | Seer/actor separation preserved; projection reads from local log; loop closes inside Akosha's boundary |
| Stage 1 closes selector-fitness loop with one minimal FSM (O3) | Closed loop in v1; ~150 LOC `SelectorFitnessFSM` | Producer-only stage 1 (defer); full FSM library in stage 1 | Validates the architecture with one shipped artifact; future FSMs are pure additions |
| Coexist with `run_fitness_analysis`, partition by input scope | `run_fitness_analysis` = every span; FSMs = their own slice | Replace; merge; ignore | Avoids `/health` regression; gives the rule a home; convergence is a stage-2 decision |
| Bifrost gateway in stage 1, but as operator-config | Spec lists UI values; no code change | Out of scope until later | Bifrost gateway is the first `gen_ai.*` emitter; cheap to include; explicit UI values prevent drift |
| Bifrost-mcp out of scope | Not in any stage of this spec | Include for tracing; instrument both | Per user direction: not done, doesn't do what earlier conversation assumed |
| Akkosha is the canonical event log (replaces "Alloy then Akosha") | Producers point at Akosha `:4317`/`:4318`; Alloy stays as sibling | Producers → Alloy → Akosha | Skip the middleman; structural anti-loop rule is trivially satisfied |
| Migration fail-loud at startup | `LifecycleError("hotstore_schema_outdated")` | Warn-and-continue | Silent-degraded schema permanently dims FSM projections; P0 invariant |
| FSM registration validates partition rule | `FSMRegistry.register(...)` raises on overlap | Runtime check; documentation only | Conformance at the most consequential seam; FSM authors can't violate the discipline |
| Five repos in stage 1 (mcp-common, oneiric, akosha, mahavishnu, session-buddy) | All five receive changes | Three repos, ship others later | session-buddy is the substrate-leverage proof; crackerjack gains for free, smoke-tested |
| Topology A from brainstorm (intelligence at storage layer) + event-sourced projections | Akosha HotStore = append-only event log; FSMs = projections | Topology B (separate intelligence service); Topology C (inline in Mahavishnu) | Storage-layer intelligence matches Akosha's "Seer" role; FSMs in Akosha are the analyst substrate; loop closes inside Akosha's log boundary |

---

## 11. Open Questions / Stage-2 Hooks

- **Tempo mirror visibility** — does Akosha forward a copy, or do producers dual-export? Spec commits to "Alkosha forwards" but doesn't pin the implementation.
- **Drift FSM code reuse** — Mahavishnu already has CUSUM/Page-Hinkley in `mahavishnu/core/observability.py`. Stage-2 FSM author chooses: re-instantiate in Akosha or consume from Mahavishnu's exposed metrics.
- **Resource attribute auditing** — spec mandates contract; doesn't pin the assertion mechanism. Stage-1 PR adds a `telemetry.contract_validator` middleware that emits WARN for unknown attributes; stage-2 promotes to P1-alert.
- **GenAI semconv pin** — pinned to a specific commit of `open-telemetry/semantic-conventions-genai`. TBD at stage-1 implementation; the spec only requires the pin.

---

## 12. References

- GenAI conventions repo: <https://github.com/open-telemetry/semantic-conventions-genai>
- GenAI conventions blog (May 2026): <https://opentelemetry.io/blog/2026/genai-observability/>
- OTel Collector routing-connector README: <https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/connector/routingconnector/README.md>
- OTel Collector architecture (the collector is a telemetry data plane, not a feedback loop): <https://opentelemetry.io/docs/collector/architecture/>
- Circuit breaker reference (Resilience4j): <https://resilience4j.readme.io/docs/circuitbreaker>
- Circuit breaker reference (Microsoft Azure pattern catalog): <https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker>
- OpenTelemetry Python SDK docs (target-pinned, fetched fresh at PR write time)
- Existing Oneiric OTLP adapter: `oneiric/adapters/monitoring/otlp.py`
- Existing mcp-common middleware: `mcp-common/server/telemetry.py`
- Existing Akosha OTLP ingester: `akosha/ingestion/otel_ingester.py`
- Existing Akosha fitness analyzer: `akosha/observability/fitness_analyzer.py`
- Existing Mahavishnu OTel wiring: `mahavishnu/core/observability.py`
- Project CLAUDE.md (gating, conventions): `/Users/les/Projects/mahavishnu/CLAUDE.md`

---

## Appendix A — HotStore schema (current vs. stage-1)

```sql
-- current
CREATE TABLE spans (
    span_id        TEXT PRIMARY KEY,
    trace_id       TEXT,
    parent_id      TEXT,
    service_name   TEXT,
    name           TEXT,
    start_time     TIMESTAMP,
    end_time       TIMESTAMP,
    duration_ms    REAL,
    attributes     JSON,
    events         JSON,
    status         TEXT,
    embedding      BLOB,
    timestamp      TIMESTAMP
);

-- after migration (additive)
ALTER TABLE spans ADD COLUMN ...   -- see §5.5
CREATE INDEX ... ON spans(...);    -- see §5.5
```

The migration is **additive**: existing columns unchanged; new columns are nullable with safe defaults.

## Appendix B — Worked example details

See §6.1. The example assumes `task_class=code_generation` and a synthetic burst of 14 failing outcomes; the FSM transitions CLOSED → OPEN in one tick; the router defers to the FSM recommendation on the next dispatch; Redis TTL ages out after 30s and YAML fallback engages. The example is end-to-end reproducible in `akosha/tests/integration/fsm/test_dispatch_e2e.py`.

## Appendix C — Bifrost gateway admin-UI config

```
Service Name:                   bifrost-gateway
Protocol:                       HTTP
OTLP Collector URL:             http://localhost:4318/v1/traces
Insecure (Skip TLS):            ON
Enable Trace Export:            ON
Format:                         OTel GenAI Extension (Recommended)
Export Timeout (seconds):       5
```

For metrics, set the same endpoints' `/v1/metrics` route on the Metrics tab. Headers: leave empty (loopback). Per-environment `deployment.environment` is set at the gateway's environment-vars layer (not via this UI).
