---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: convergence-control-plane
---

# Completion Report Schema v1 — Design

**Status:** Draft (brainstormed 2026-06-22)  <!-- legacy status: Draft (brainstormed 2026-06-22) — see YAML frontmatter -->
**Phase:** 1 (Foundational)
**Source:** Synthesis of three articles —

1. *Rebuilt Hermes / MAOS* (levelup.gitconnected, 2026) — agent self-validation failure mode
1. *The Method That Replaces Spec-Driven Development — IDSD* (Medium, 2026) — ICE framework, "the agent fills the gaps"
1. *Building a Production Agent Harness* — completion_report JSON contract, 19 quality gates, mechanical confidence ceilings

______________________________________________________________________

## Overview

This spec defines `IterationReport` and `WorkflowReport` — the typed contract that Claude-emitter workers in Mahavishnu publish to the EventBus after each reasoning iteration and at workflow completion. The reports carry the structural information that quality gates (`precommitment-hypothesis-lock`, `confidence-ceiling-gate`), persistent state (Dhara), intelligence (Akosha), and memory (Session-Buddy) consume to evaluate, debug, and learn from agent runs.

Reports are **events, not return values**: a worker publishes an `EventEnvelope` whose `payload` is the report. Consumers subscribe; producers are decoupled. The schema is the contract.

The v1 schema captures only what downstream Phase 1 specs need. Token counts, cost, tool-call breakdown, and other operational metadata are deliberately deferred to v1.1+ to avoid scope creep and premature standardization.

______________________________________________________________________

## Goals

- **G1.** Provide a stable, versioned JSON Schema for iteration and workflow outcomes that downstream specs (precommitment lock, confidence ceiling, three-layer self-heal) can depend on without coordinating per-feature.
- **G2.** Eliminate the "agent grades its own homework" failure mode by making report fields *machine-checkable*, not just *self-reported*. Confidence is self-reported but subject to mechanical caps; status enums are fixed; open_questions is enumerated.
- **G3.** Reuse Mahavishnu's existing `EventEnvelope` so reports flow through the existing EventBus and reach existing subscribers (Dhara, Akosha, Crackerjack) without bespoke transport.
- **G4.** Coexist with existing single-shot worker return values. Adoption is incremental: opt-in v1.0, default for new iterative workers in v1.1, required in v2.0.

## Non-Goals

- **N1.** Persisting PII-redacted reports. v1 stores what the worker emits. Redaction is v2 work.
- **N2.** Token / cost / tool-call breakdown in v1. Deferred to v1.1+ when a consumer demonstrates need.
- **N3.** Defining the report content for non-Claude-emitter workers (e.g. container workers running deterministic code). Those workers continue using their existing return path.
- **N4.** Replacing `get_workflow_status` in v1. The legacy field is preserved; reports are additive.

______________________________________________________________________

## Architecture & Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ WORKER (Claude-emitter, iterative)                              │
│                                                                 │
│  for iteration_index in range(iteration_budget):                │
│    response = claude.run(prompt)                                │
│    report = IterationReport(                                    │
│      iteration_index=iteration_index,                           │
│      iteration_budget=iteration_budget,                         │
│      started_at=now(),                                          │
│      ...                                                        │
│      completed_at=now(),                                        │
│    )                                                            │
│    envelope = EventEnvelope(                                    │
│      event_type="workflow.iteration.completed",                  │
│      source=worker_id,                                          │
│      correlation_id=workflow_id,                                │
│      payload=report,                                            │
│    )                                                            │
│    event_bus.publish(envelope)   # raises on validation failure │
│    if not gates_pass(envelope): break                           │
│                                                                 │
│  workflow_report = WorkflowReport(...)                          │
│  event_bus.publish(EventEnvelope(                               │
│    event_type="workflow.completed",                              │
│    payload=workflow_report))                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │ EventBus → multiple consumers              │
        │                                             │
        │  ┌─────────────────┐   ┌─────────────────┐  │
        │  │ Dhara           │   │ Crackerjack     │  │
        │  │ (persister)     │   │ (gates)         │  │
        │  └─────────────────┘   └─────────────────┘  │
        │  ┌─────────────────┐   ┌─────────────────┐  │
        │  │ Akosha          │   │ session-buddy   │  │
        │  │ (anomaly/stats) │   │ (memory)        │  │
        │  └─────────────────┘   └─────────────────┘  │
        └─────────────────────────────────────────────┘
```

**Architectural properties:**

1. **Reports are events, not return values.** The worker doesn't return a report to its caller — it publishes to the EventBus. Decouples producer from gates from storage.
1. **The worker is the sole producer of `workflow.iteration.completed` and `workflow.completed`.** Orchestrator, gates, storage are all consumers.
1. **Two event types** share one envelope pattern; their payloads (`IterationReport` vs `WorkflowReport`) differ.
1. **Validation happens at publish**, not at consume. A worker that produces an invalid report cannot advance its iteration loop. This mirrors the source article's "the agent cannot bypass the reply gate" principle.

______________________________________________________________________

## Schema Definition

JSON Schema is the canonical source. Pydantic models are generated from JSON Schema via `datamodel-code-generator`. Both live in version control; the JSON Schema is the source of truth.

### `IterationReport` (per Claude turn)

Published as `EventEnvelope.payload` with `event_type = "workflow.iteration.completed"`.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `schema_version` | string | yes | const `"1.0.0"` |
| `report_kind` | string | yes | const `"iteration"` |
| `workflow_id` | string (uuid) | yes | — |
| `iteration_index` | integer | yes | ≥ 0 |
| `iteration_budget` | integer | yes | ≥ 1 |
| `started_at` | string (date-time) | yes | ISO 8601, UTC |
| `completed_at` | string (date-time) | yes | ISO 8601, UTC |
| `duration_ms` | integer | yes | ≥ 0 |
| `status` | string (enum) | yes | `IN_PROGRESS` | `BLOCKED` | `COMPLETE` |
| `confidence` | integer | yes | 0–100. Subject to mechanical ceiling by `confidence-ceiling-gate` (separate spec). |
| `open_questions` | array<string> | yes | may be empty |
| `unchecked_sources` | array<source> | yes | see below; may be empty |
| `contradiction_register` | array<string> | yes | may be empty |
| `assumption_register` | array<string> | yes | may be empty |
| `adjacent_problems` | array<problem> | yes | see below; may be empty |
| `draft_response` | string | no | free-form prose, optional |

**Source object (`unchecked_sources[*]`):**

| Field | Type | Required | Constraints |
|---|---|---|---|
| `name` | string | yes | — |
| `access_status` | string (enum) | yes | `accessible` | `permission_denied` | `not_found` | `rate_limited` | `skipped_inferred` |

**Problem object (`adjacent_problems[*]`):**

| Field | Type | Required | Constraints |
|---|---|---|---|
| `summary` | string | yes | — |
| `status` | string (enum) | yes | `open` | `investigating` | `resolved` | `wont_fix` |
| `blocker` | string | no | — |

### `WorkflowReport` (per workflow completion)

Published as `EventEnvelope.payload` with `event_type = "workflow.completed"`.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `schema_version` | string | yes | const `"1.0.0"` |
| `report_kind` | string | yes | const `"workflow"` |
| `workflow_id` | string (uuid) | yes | — |
| `worker_id` | string | yes | — |
| `pool_id` | string | yes | — |
| `task_type` | string | yes | — |
| `started_at` | string (date-time) | yes | ISO 8601, UTC |
| `completed_at` | string (date-time) | yes | ISO 8601, UTC |
| `duration_ms` | integer | yes | ≥ 0 |
| `exit_reason` | string (enum) | yes | `complete` | `blocked` | `stalled` | `degrading` | `timeout` | `budget_exhausted` | `force_continued` |
| `iteration_count` | integer | yes | ≥ 0 |
| `final_status` | string (enum) | yes | `IN_PROGRESS` | `BLOCKED` | `COMPLETE` |
| `confidence_trajectory` | array<integer> | no | per-iteration confidence, ordered; useful for diagnosing drift |

### Strictness policy

**Both reports use `additionalProperties: false` in v1.** This is intentional: it forces schema evolution to be explicit (MAJOR bump) rather than accidental. v1.1 may relax this to `true` once token/cost/tool-call extension fields are standardized. Consumers wanting forward-compat with v1.1+ should not rely on `additionalProperties: false` to reject unknown keys — they should check `schema_version` first.

______________________________________________________________________

## Event Envelope Integration

Reports are published inside the existing `EventEnvelope` (per `docs/specs/event-envelope-spec.md`).

| Envelope field | Value for iteration reports | Value for workflow reports |
|---|---|---|
| `event_type` | `"workflow.iteration.completed"` | `"workflow.completed"` |
| `source` | `worker_id` | `worker_id` |
| `correlation_id` | `workflow_id` | `workflow_id` |
| `payload` | `IterationReport` (this spec) | `WorkflowReport` (this spec) |
| `metadata.report_kind` | `"iteration"` | `"workflow"` |

The `event_type` is the discriminator; consumers subscribe by event type. The `metadata.report_kind` field provides a redundant check for consumers that need to filter reports across event types.

______________________________________________________________________

## Validation

**Where validation happens:** at publish, inside `event_bus.publish_iteration_report(report)` and `event_bus.publish_workflow_report(report)`. Validation runs before the envelope is dispatched.

**Validation failure is a hard error.** The worker:

1. Catches `MahavishnuReportValidationError` from publish.
1. Logs the failure with the full offending payload (sanitized of secrets by existing logger).
1. Increments a `mahavishnu_report_validation_failure_total` counter (Prometheus).
1. Emits an anomaly event to Akosha.
1. **Does NOT advance to the next iteration.** The worker loop terminates with `exit_reason = "blocked"` and the iteration's `open_questions` augmented with a validation diagnostic.

This mirrors the source article's principle: *"Whatever Claude believes about its work, validation re-runs the real operation. ... The agent's self-report is never the ground truth — the harness re-checks against the wire."*

**Dhara stores only validated reports.** The persister subscriber runs *after* validation; an invalid report never reaches storage.

______________________________________________________________________

## Versioning Policy

Follows `event-envelope-spec.md`:

- **MAJOR bump** = breaking change (removed required field, tightened enum, narrowed type). Consumers must explicitly migrate.
- **MINOR bump** = additive optional field or new enum value at end. Backward compatible.
- **PATCH bump** = doc/description-only change. No code impact.

The `schema_version` field inside the payload is the version discriminator. Consumers must check this *before* parsing the rest of the payload; mismatch routes to:

- **Unknown future version** → consumer's policy (default: log + skip + alert via Akosha).
- **Older known version** → consumer may either parse (forward compat) or reject (strict mode).

______________________________________________________________________

## Adoption & Migration

| Version | Adoption policy |
|---|---|
| **v1.0** | Schema defined, helpers shipped. Workers opt in by calling `event_bus.publish_iteration_report(...)`. Existing single-shot workers unchanged. |
| **v1.1** | All *new* iterative workers (created after v1.1 ships) MUST emit reports. Existing iterative workers log a deprecation warning once per process. Token / cost / tool-call extension fields added (if needed). |
| **v2.0** | Every iterative worker MUST emit reports. Legacy `worker.result` returns for iterative workers are deprecated; CLI flag `--allow-legacy-iterative-workers` to suppress enforcement for one release. |

**Migration aid:** `mahavishnu migrate --check-reports` CLI command audits the codebase for new workers created since the cutoff that don't emit reports. Exits non-zero if violations found; suitable for CI gating after v2.0.

______________________________________________________________________

## Storage & Retrieval

**Storage:**

- **Dhara persister subscriber** at `mahavishnu/core/events/subscribers/report_persister.py` auto-stores validated reports.
- Tables:
  - `iteration_reports` — primary key `(workflow_id, iteration_index)`; columns mirror the schema with `payload` JSON column for the raw report.
  - `workflow_reports` — primary key `workflow_id`; same shape.
- Retention: 90 days default, configurable via `mahavishnu.report.retention_days`.
- **No PII scrubbing in v1.** Operators are responsible for not putting secrets in `draft_response`. Documented in the worker authoring guide.

**Retrieval — new MCP tools:**

| Tool | Returns |
|---|---|
| `mcp__mahavishnu__get_iteration_history(workflow_id)` | Ordered list of `IterationReport` for the workflow. |
| `mcp__mahavishnu__get_workflow_status(workflow_id, include_reports=False)` | Existing fields plus `latest_iteration_report` and `workflow_report` when present. `include_reports=True` returns the full ordered iteration history. |

**Existing consumers (free upgrades):**

- **Dhara**: schema-versioned column added; no breaking changes for existing tables.
- **Akosha**: anomaly detector gains a hook for `mahavishnu_report_validation_failure_total` metric; pattern detector can mine `confidence_trajectory` for drift.
- **Session-Buddy**: stores workflow reports as conversation context (operator-controlled opt-in).
- **Crackerjack**: precommitment and confidence-ceiling gates consume iteration reports (separate specs).

______________________________________________________________________

## Error Handling

| Failure | Detection | Response |
|---|---|---|
| Worker publishes malformed report | JSON Schema validation at publish | `MahavishnuReportValidationError`; iteration loop terminates with `blocked`; Akosha anomaly recorded. |
| Consumer doesn't know report version | `schema_version` mismatch on consume | Default: log + skip + alert via Akosha. Configurable per consumer (`strict=true` rejects). |
| Dhara write fails | Persister subscriber catches storage error | Worker continues; metric incremented; report not lost in EventBus (replay possible). |
| Clock skew between `started_at` and `completed_at` | `duration_ms` derived from wall clock; if negative, log warning but accept | Worker may pass a duration derived from monotonic clock instead; out of v1 scope. |
| Worker emits duplicate `(workflow_id, iteration_index)` | Persister detects primary key collision | Reject duplicate, log, alert. Idempotency rule: same iteration index published twice = bug. |

**New exception class:**

```python
# mahavishnu/core/errors.py (additive)
class MahavishnuReportValidationError(MahavishnuError):
    """Raised when a worker publishes a report that fails JSON Schema validation.

    Carries the offending payload (sanitized) and the validation error path
    for diagnostic context.
    """
```

______________________________________________________________________

## Testing Strategy

Aligned with Bodai's existing L0–L4 framework (per the Production Harness article's pattern, adapted to Bodai's conventions in `pyproject.toml`).

| Layer | Scope | Examples |
|---|---|---|
| **L0 (pure boundary)** | JSON Schema validation; Pydantic round-trip; no IO | Valid report accepted; invalid report rejected with correct error path; boundary confidence values 0/100; empty arrays allowed; `additionalProperties` rejected. |
| **L1 (file isolation)** | Real filesystem, real threading, no mocks for `pathlib` | Concurrent publish race; serializability of payload to disk. |
| **L2 (service isolation)** | Real subprocess; mocked EventBus; mocked Dhara | Worker loop blocks iteration on validation failure; metric increments; anomaly event emitted. |
| **L3 (sandbox)** | Real EventBus; mocked downstream consumers | Subscribe by event_type; cross-version compatibility: v1.0 producer + v1.0 consumer, v1.0 producer + v1.1 consumer (forward compat), v1.1 producer + v1.0 consumer (backward compat rejection). |
| **L4 (integration matrix)** | End-to-end; real Dhara; real Akosha | Full worker → EventBus → persister → retrieval path; CLI `migrate --check-reports` on a sample repo. |
| **L4g (production replay)** | After first production incident | Test reproducing the incident's payload + actor + state, kept permanently. |

**Coverage target:** `tests/unit/test_completion_report.py` ≥ 95% line coverage. Hard limits: function args ≤ 10, branches ≤ 15, statements ≤ 55 — enforced by Ruff config in `pyproject.toml`. Pydantic models with many fields use nested model composition to stay within limits.

**Fixtures:** Reusable valid/invalid report generators in `tests/fixtures/reports.py`. Generated via property-based testing (Hypothesis) to cover edge cases (empty arrays, max enum values, boundary integers).

______________________________________________________________________

## Implementation Module Paths

| Component | Path |
|---|---|
| JSON Schema (canonical) | `mahavishnu/core/schemas/completion_report/v1.json` |
| Pydantic model (generated) | `mahavishnu/core/completion_report.py` |
| Generation script | `scripts/generate_completion_report_model.py` |
| EventBus helpers | `mahavishnu/core/events/report_publishers.py` |
| Validation at publish | `mahavishnu/core/events/report_validation.py` |
| Persister subscriber | `mahavishnu/core/events/subscribers/report_persister.py` |
| MCP retrieval tools | `mahavishnu/mcp/tools/report_query_tools.py` |
| Migration CLI command | `mahavishnu/cli/report_migration_cli.py` |
| Tests | `tests/unit/test_completion_report.py`, `tests/integration/test_report_eventbus.py` |
| Test fixtures | `tests/fixtures/reports.py` |
| Exception class | `mahavishnu/core/errors.py` (additive: `MahavishnuReportValidationError`) |

______________________________________________________________________

## Trade-offs & Alternatives Considered

| Choice | Why this | Why not the alternative |
|---|---|---|
| JSON Schema canonical, Pydantic generated | Single source of truth, interop-ready, Python-idiomatic | Pydantic-only — locks non-Python consumers out. JSON-Schema-only — unidiomatic for FastMCP workers. |
| `additionalProperties: false` in v1 | Forces explicit schema evolution; consumers can trust fields | `true` — invites drift and surprise. We can relax in v1.1 if extension use is well-governed. |
| Reports as events, not return values | Decouples producer from consumers; reuses EventBus | Return values — tight coupling; no persistence without consumer code. |
| Deferred metadata (tokens, cost, tool calls) to v1.1+ | Avoid scope creep; add when consumer need emerges | All-in v1 — settles debates prematurely; some fields may never be used. |
| Coexist adoption in v1.0/v1.1; required in v2.0 | Ship value immediately; migrate incrementally | Required in v1.0 — breaks every existing worker; high churn. |
| `schema_version` as payload field, not envelope `version` | Schema and envelope can evolve independently | Reuse envelope `version` — couples schema and envelope semantics. |

______________________________________________________________________

## Open Questions / Future Work

- **OQ1.** Should `draft_response` be a structured field (e.g. `{markdown, plain_text, attachments}`) rather than free-form string? Deferred to v1.1+; for v1, free-form string matches the article.
- **OQ2.** When v1.1 adds token/cost/tool-call fields, do they belong in the core schema or in a `metrics` sub-object? Lean toward `metrics` sub-object for namespace isolation. To be decided before v1.1.
- **OQ3.** PII redaction: hook into the persister subscriber so the worker doesn't have to remember. Deferred to v2; tracked separately.
- **OQ4.** Schema documentation generation: do we ship a published HTML doc via `Redoc` or similar? Likely yes, before v1.0 GA. Not blocking v1.0-alpha.

______________________________________________________________________

## Success Criteria

- **SC1.** All v1.0 design decisions (above) implemented and merged behind no feature flag.
- **SC2.** One new iterative worker (e.g. `mahavishnu/workers/iterative_researcher.py`) ships in v1.0 demonstrating full report emission.
- **SC3.** `mcp__mahavishnu__get_iteration_history` and updated `get_workflow_status` shipped.
- **SC4.** Test coverage ≥ 95% on the report module; L0–L3 tests green.
- **SC5.** Crackerjack precommitment-hypothesis-lock and confidence-ceiling-gate specs (separate docs) can reference this spec's schema as their input contract.
