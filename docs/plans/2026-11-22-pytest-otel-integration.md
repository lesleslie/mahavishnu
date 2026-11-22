---
status: draft
role: implementation
date: 2026-11-22
last_reviewed: 2026-11-22
topic: pytest-observability
title: "Pytest runs emit OpenTelemetry spans into the Bodai substrate"
---

# Pytest runs emit OpenTelemetry spans into the Bodai substrate

> **DRAFT — research capture, not an approved plan.** This document records
> what a design session established (2026-11-22). It has not been through
> the design-doc approval gate, and it deliberately declares no
> `requirements:` in its frontmatter: `scripts/audit_requirements.py`
> exits 1 on declared-but-unimplemented requirements
> (`audit_requirements.py:573`), and nothing is implemented yet. Requirement
> IDs get declared in the frontmatter when this plan is promoted from
> `draft` to `active` and the implementation markers exist alongside them.
>
> **Resume point:** §9 lists the open decisions. §8 has the phase sketch.

## 1. Outcome

A pytest run in any fleet repo emits OpenTelemetry spans that land in the
Bodai substrate (`spans_substrate`) and can be queried through Akosha's MCP
tools — so a test run is observable and analysable with the same machinery
as production telemetry. The same span stream also serves as the assertion
surface that proves our instrumentation emits the attributes we claim.

Success signal: `akosha_search_spans` returns spans whose
`service.name` identifies the test run, and a test asserts on a span
produced by code under test without a hand-rolled exporter fixture.

## 2. Goals

1. Emit a span per test (and per test phase / fixture) from a pytest run,
   into the Bodai substrate, queryable via Akosha.
2. Provide a reusable in-memory span fixture so telemetry contracts
   (attribute names, values, span names) are asserted in-repo.
3. Remove the six duplicated hand-rolled `InMemorySpanExporter` fixtures
   that currently exist in mahavishnu alone.
4. Ship the plugin where it reaches the whole fleet without leaking into
   production installs.

## 3. Non-Goals

1. A Grafana trace dashboard. Live Grafana has two datasources
   (`DuckDB Learning (PostgreSQL)`, `prometheus`) and no trace datasource;
   provisioning Tempo/Loki is a separate infrastructure decision.
2. Replacing `crackerjack run` as the merge gate.
3. Making the OTel *collector* part of this. The collector configs in the
   tree are legacy and not on the production path (§4.1).
4. Python-version-based mitigation of the fork hazard (§4.4).

## 4. Current Findings

### 4.1 The live span path is producer → Akosha, not through a collector

| Stage | Detail |
|---|---|
| Producer wiring | `mcp_common/server/producer_telemetry.py::configure_producer_tracing` (line 150), installed by `mcp_common/server/launcher.py:272` **before** the server is built |
| Default transport | `http/protobuf` (`mcp_common/server/producer_telemetry.py:110`; `mahavishnu/core/observability.py:49`) |
| Destination | `observability.otlp_endpoint`, default `http://localhost:4318` (`mahavishnu/core/config.py:1590`) → `mahavishnu/core/observability.py:301` |
| Receiver | Akosha's in-process OTLP receiver, `akosha/akosha/observability/otlp_receiver.py:99`, gRPC `:4317` / HTTP `:4318` |
| Storage | DuckDB `spans_substrate`, 30-day retention (`akosha/akosha/storage/hot_store.py`) |
| Query surface | `akosha_search_spans` / `akosha_spans_summary` (`akosha/akosha/mcp/tools/otel_span_tools.py:78,133`) |

`mahavishnu/config/otel-collector-config.yaml` (10 pipelines, exports to
Jaeger + debug) is **legacy and not on the production path**. Its
`resource` processor upserts `service.namespace=mahavishnu`, but it never
sees our spans, so a test producer must carry `service.namespace` itself.

**Akosha validates every span** (`akosha/akosha/observability/otlp_receiver.py:119-125`):

```text
REQUIRED_FIELDS = {service_name, service_namespace, span_name, start_time_unix_nano}
```

and `service_namespace` must be in `ALLOWED_NAMESPACES = {"bodai", "cli-tools"}`
(`akosha/akosha/observability/resource_validator.py:104,108`). A span missing
`service.namespace` is quarantined to `_dlq_rows` — accepted, stored nowhere,
counted in `akosha_otlp_spans_rejected_total`.

### 4.2 Constraint 1 — the global TracerProvider is write-once per process

`opentelemetry/trace/__init__.py:515` gates the global provider with
`Once()`. A second `trace.set_tracer_provider()` logs *"Overriding of
current TracerProvider is not allowed"* and does nothing.

The codebase already knows this: `mahavishnu/core/observability.py:270-272`
splits the export path out precisely so a test does not have to touch the
global, because doing so *"is order-dependent under `pytest -n auto`"*.

Only one correct reset exists in the fleet —
`mcp-common/tests/unit/test_producer_telemetry.py:54-70`, which swaps **both**
`trace._TRACER_PROVIDER` and `trace._TRACER_PROVIDER_SET_ONCE` (a fresh
`Once()`) and restores both in a `finally`. mahavishnu's
`tests/integration/test_tool_call_telemetry_e2e.py` instead pokes
`trace._TRACER_PROVIDER_SET_ONCE._done = False`, which is weaker.

`mcp-common/server/producer_telemetry.py:204-224` shows the production-side
discipline: if a real provider is already installed, it declines to replace
it and returns `ProducerTracingResult(None, True)` — the caller does not own
the provider.

### 4.3 Constraint 2 — the suite runs under xdist

`pyproject.toml` `addopts` contains `-n auto`. Each xdist worker is a
separate process with its own global provider, and "session" scope means
*once per worker*. With N workers, a session-scoped span object is created
N times.

Worker creation goes through `subprocess.Popen`, not `os.forkpty`:

```python
# execnet/gateway_io.py:34
self.popen = p = execmodel.subprocess.Popen(args, stdout=PIPE, stdin=PIPE)
```

`close_fds` defaults to `True`, so this is the same fork path as the MCP
server's `git diff` children (see §4.4).

### 4.4 Constraint 3 — no gRPC in a forking process (Python 3.15 does not fix this)

`docs/decisions/2026-11-16-no-grpc-in-forking-processes.md` (active,
canonical): macOS CPython cannot use `posix_spawn` for `subprocess` with
the default `close_fds=True`, so it forks; a live grpcio/c-ares thread at
fork time kills the child with SIGILL. That decision cost 43 crash reports
(`BUG IN CLIENT OF LIBDISPATCH: trying to lock recursively`).

**Measured on this host, 2026-11-22** — Python 3.15.2 is installed at
`/usr/local/bin/python3.15` and does **not** change the behaviour:

```text
3.14.10:  _USE_POSIX_SPAWN: True   _HAVE_POSIX_SPAWN_CLOSEFROM: False
3.15.2:   _USE_POSIX_SPAWN: True   _HAVE_POSIX_SPAWN_CLOSEFROM: False
os.POSIX_SPAWN_CLOSEFROM: ABSENT   os.POSIX_SPAWN_CLOEXEC_DEFAULT: ABSENT
```

The 3.15 `_execute_child` gate is unchanged:

```python
and (not close_fds or _HAVE_POSIX_SPAWN_CLOSEFROM)
```

With `close_fds=True` and `_HAVE_POSIX_SPAWN_CLOSEFROM=False`, the condition
is false → `fork_exec()` is used. `_USE_VFORK` is absent on macOS in both
versions (CPython's vfork path is Linux-only). The upstream work is still
open: CPython gh-113117 and gh-109154.

**Consequence for this plan: the version is irrelevant.** HTTP transport is
already a dependency (`opentelemetry-exporter-otlp-proto-http>=1.45.1`,
`pyproject.toml:111`) and already the fleet default. Choosing it costs
nothing and removes the hazard *structurally*.

**Gap to close:** the decision doc does not mention xdist at all. xdist is a
fork site the rule already covers but never names. It needs an amendment
(§10).

### 4.5 Off-the-shelf pytest plugins — all rejected

Checked against PyPI on 2026-11-22.

| Plugin | Version | Why rejected |
|---|---|---|
| `pytest-opentelemetry` | 2.0.0 | **Hard-depends on `opentelemetry-exporter-otlp-proto-grpc`** → grpcio in the test process → re-arms §4.4 under xdist. Also cannot set `service.namespace=bodai` or know the `task.class`/`task_class` dual-write vocabulary. |
| `pytest-otel` | 2.6.0 | Depends on the `opentelemetry-exporter-otlp` meta-package (also grpc). Exact-pins `pytest==9.2.0`, `opentelemetry-api==1.45.2`, `opentelemetry-sdk==1.45.2` — a fleet-wide pin-conflict source. |
| `pytest-ot` | 0.0.7 | Stale 0.0.x. |

`opentelemetry-instrumentation-pytest` is listed in the OTel ecosystem
registry but is **not on PyPI** — no such package to install.

### 4.6 The assertion vocabulary is span names + attribute keys, not tracer names

`mahavishnu.workflow` and `session_buddy.memory` are **not** tracer names.
The real surface:

- Tool-call enrichment (`mahavishnu/mahavishnu/mcp/tool_call_enricher.py:50`)
  sets exactly five attributes: `task.class` **and** `task_class` (both
  spellings, dual-written), `selector`, `outcome`, `duration_ms`.
  Akosha reads both spellings
  (`akosha/akosha/ingestion/otel_ingester.py:375`).
- Span names worth pinning: `workflow.{workflow_id}`,
  `repo.process.{basename}`, `mahavishnu.acp.session`,
  `mahavishnu.observability.drift_detected`,
  `mcp.{method}.{component}` (`mcp_common/server/telemetry.py:108`),
  `_service_liveness`, `merge.semantic.invocations`,
  `task_orphan_sweeper.recover`, `eval.run_suite`.
- Tracer scopes: `mcp_common.server.telemetry.<service>`,
  `mahavishnu.core.observability`, `mahavishnu.acp.session`,
  `oneiric.core`.

### 4.7 Fleet state of test-time OTel

No pytest OTel plugin exists anywhere in the fleet. What exists:

| Piece | Location |
|---|---|
| pytest guard | `session_buddy/mcp/telemetry.py:104` — `if endpoint is None and "pytest" in sys.modules: return False` |
| provider reset (the correct one) | `mcp-common/tests/unit/test_producer_telemetry.py:54-70` |
| hand-rolled exporters | 6 files in mahavishnu: `tests/unit/acp/test_observability_validation.py`, `tests/integration/test_eval_cardinality.py`, `tests/integration/test_tool_call_telemetry_e2e.py`, `tests/unit/test_check_merge_driver.py`, `tests/unit/test_task_orphan_sweeper.py`, `tests/unit/pools/test_pi_observability.py` |
| autouse global provider | `akosha/tests/conftest.py:14` — installs one with **no exporter**, autouse ⇒ every akosha test runs under it |
| crackerjack | **zero OTel code** |

The session-buddy guard matters: the fleet convention is already "don't emit
spans under pytest unless explicitly asked". A pytest integration does not
fight producers for the global provider — it invites them.

### 4.8 The provider must be installed before test modules are imported

Most instrumentation grabs its tracer at **import** time
(`mod._tracer` in `task_orphan_sweeper.py:81`,
`trace.get_tracer(__name__)` at module scope in `core/observability.py:328`).
An OTel `Tracer` binds to its provider at creation, so a *function-scoped*
fixture that swaps the global provider **after import cannot capture spans**
emitted through an already-captured module-level tracer. That is exactly why
`tests/unit/test_task_orphan_sweeper.py:388` has to monkeypatch `mod._tracer`.

Consequence for the design: the provider is installed **once, at session
scope, before collection** (`pytest_configure`), not in a fixture. Since the
provider can no longer be swapped per test, use one session-scoped
`InMemorySpanExporter` and `exporter.clear()` between tests.

### 4.9 Plugin home — measured reach across the fleet

37 repos in `settings/ecosystem.yaml`, 35 on disk:

| candidate | runtime dep | dev-only dep | absent | **available in a test env** |
|---|---|---|---|---|
| **crackerjack** | 2 | 33 | 0 | **35/37** |
| oneiric | 29 | 0 | 6 | 29/37 |
| mcp-common | 27 | 0 | 8 | 27/37 |

mcp-common is the narrowest — `flowscape` uses oneiric + crackerjack but not
mcp-common, and 8 repos have no mcp-common at all.

**crackerjack wins on four compounding grounds:**

1. Widest reach (35/37, zero absent).
2. **Dev-only in 33 of 35** — a `pytest11` entry point in a dev-only
   package can never be auto-loaded in a production venv. oneiric and
   mcp-common are *runtime* deps in 29 and 27 repos, so their entry points
   would be advertised in production installs.
3. crackerjack **is** the quality gate and already invokes pytest — the
   plugin and its caller live in the same package, so `crackerjack run` can
   toggle telemetry as a run flag rather than inventing a second opt-in.
4. crackerjack has **zero OTel code** — no competing convention, and it
   closes the fleet's one real gap.

The plugin *shell* (entry point, fixtures, hooks) belongs in crackerjack. The
observability primitives it builds on stay where they are and get imported:
`configure_producer_tracing` (mcp-common), `observed_span` (oneiric).

## 5. Approaches considered

**Approach A — adopt `pytest-opentelemetry`.** Rejected: grpc hard-depend
(§4.5), plus it cannot express the ecosystem's namespace allowlist or
attribute vocabulary.

**Approach B — hand-rolled `pytest11` plugin in crackerjack. Recommended.**
Zero new dependencies. Owns the hook set, so xdist semantics and
`service.namespace` are ours to get right. Uses the HTTP exporter only, so
the fork hazard is structurally impossible.

**Approach C — conftest fixtures only, no plugin.** Cheapest; covers only
goal 2. Subsumed by B, which is a superset. Kept as the fallback if B's
scope proves too large for one sitting.

## 6. Proposed design (draft — not yet approved)

### 6.1 Transport and processor

- **HTTP transport only.** `opentelemetry-exporter-otlp-proto-http` only. No
  gRPC option exposed at all — that makes the fork hazard structurally
  impossible rather than configuration-dependent.
- **`SimpleSpanProcessor`, not `BatchSpanProcessor`.** Batch starts a
  background thread (macOS `getaddrinfo` also goes through libdispatch's
  `dispatch_once` — the same trap class), and Batch drops spans on
  short-lived process exit because the interval never fires. A test run is
  exactly that shape. Simple is synchronous, deterministic, and needs no
  flush.

### 6.2 Lifecycle

- `pytest_configure`: install the provider (if none exists) **before test
  modules are imported** (§4.8). Session scope.
- `pytest_addoption`: `--otel-test-spans` (default off — inert by default,
  so a `pytest11` entry point never changes behaviour unasked) and
  `--otel-test-spans-endpoint`.
- Per-test spans: one span per test, `SimpleSpanProcessor` export,
  attributes carry the test nodeid, outcome, and duration.
- `service.namespace="bodai"` (allowlist), `service.name="<repo>-tests"`,
  `deployment.environment="test"` — the distinction from production spans
  is `service.name`, because the namespace cannot vary.

### 6.3 Fixtures

- `span_exporter` — session-scoped `InMemorySpanExporter`, `clear()`ed
  between tests.
- `reset_tracer_provider` — adopt mcp-common's pattern verbatim
  (`mcp-common/tests/unit/test_producer_telemetry.py:54-70`).

### 6.4 Known problems to solve in implementation

1. **akosha's autouse conftest fixture** (`akosha/tests/conftest.py:14`)
   installs a provider with no exporter. The plugin must detect an existing
   provider and defer to it, or akosha's tests need adjusting.
2. **xdist session duplication** — N workers produce N session-scoped
   objects. Each test should be its own trace root (no shared session
   span), so traces do not collide.
3. **Substrate pollution** — test spans land in `spans_substrate` beside
   production spans, distinguished only by `service.name`. Needs an
   explicit decision (§9).
4. **Akosha's own span search** must be able to filter them out. Whether
   `service.name` is enough is an open question.

## 7. Risks

| Risk | Mitigation |
|---|---|
| SIGILL crash class returns | HTTP transport only; no gRPC import path at all |
| Spans dropped on exit | `SimpleSpanProcessor`; synchronous export |
| Order-dependent tests under xdist | Session-scoped install before import; `clear()` between tests |
| Substrate pollution | `service.name` suffix; pending §9 decision |
| Fleet-wide pin churn | No new dependencies; no version pins |

## 8. Phase sketch

> Integration Contract blocks are drafted at the phase level. Each phase
> block gets its own contract when this plan is promoted to `active`.

### Phase 1 — fixtures only (no export)

Generalize the in-memory exporter into a shared, xdist-safe fixture and
repoint the six duplicated call sites.

#### Integration Contract

- **Triggered from**: pytest session start — `pytest_configure` in the
  plugin's `conftest.py` / plugin module.
- **Returns to / updates**: the process-global `opentelemetry.trace`
  provider; one session-scoped `InMemorySpanExporter` per worker process.
- **Demonstrable by**: the six existing hand-rolled fixtures are replaced by
  the shared one; their assertions still pass.
- **Rollback signal**: any test that asserts on spans starts failing with
  an empty exporter — the failure mode is a loud empty result, not a silent
  pass.
- **Observability added**: none to the substrate (in-memory only).

### Phase 2 — test-run span export

Add the opt-in exporter, the per-test span, and the `service.namespace`
handling.

#### Integration Contract

- **Triggered from**: `pytest --otel-test-spans`, or `crackerjack run` with
  the equivalent flag.
- **Returns to / updates**: Akosha's `spans_substrate` via OTLP/HTTP
  `:4318/v1/traces`.
- **Demonstrable by**: `akosha_search_spans` returns the run's spans with
  `service.namespace=bodai` and the test `service.name`.
- **Rollback signal**: `akosha_otlp_spans_rejected_total` climbing, or
  `_dlq_rows` growing — a namespace or required-field mismatch.
- **Observability added**: per-test spans in the substrate.

### Phase 3 — span contract tests

Pin the attribute vocabulary (§4.6) with assertions so telemetry cannot
drift silently.

## 9. Open decisions (resume here)

1. **Substrate pollution.** Test spans in `spans_substrate` beside
   production spans — accept and filter on `service.name`, or give tests a
   separate destination? There is no Grafana trace datasource, so the
   current payoff is MCP queries only.
2. **xdist trace shape.** One trace per test (no session span) is the
   recommendation, because a session span is duplicated per worker.
3. **Scope of phase 1.** Six call sites in mahavishnu alone; session-buddy
   and oneiric have their own patterns. Fleet-wide or mahavishnu-first?
4. **Plugin inertness.** Confirm the `pytest11` entry point must be a
   complete no-op unless `--otel-test-spans` is passed.
5. **Whether `crackerjack run` should default it on** in CI.

## 10. Follow-ups

1. **Amend `docs/decisions/2026-11-16-no-grpc-in-forking-processes.md`** to
   name xdist as a fork site. It is covered by the rule but never
   mentioned, and execnet reaches it via `subprocess.Popen` (§4.3).
2. **Record the Python 3.15 measurement** in that decision doc, so the
   question is not re-researched: §4.4 has the commands and the output.
3. **Note the `monitoring/otel.py` module-scope gRPC import.**
   `mahavishnu/monitoring/otel.py:15` imports the gRPC exporter at module
   scope, against the decision's lazy-import rule. It is *not* a live
   violation — `pyproject.toml:6` sets `packages = ["mahavishnu"]`, so the
   module never ships and its only importer is the demo
   `monitoring/example_integration.py`. Still worth a comment or a delete.
