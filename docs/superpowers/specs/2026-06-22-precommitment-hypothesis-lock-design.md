# Precommitment Hypothesis Lock v1.1 — Design

**Status:** Draft (brainstormed 2026-06-22)
**Phase:** 1 (Foundational; extends Spec #1)
**Source:** Synthesis of three articles — `Rebuilt Hermes / MAOS`, `IDSD`, `Building a Production Agent Harness`. The precommitment pattern is the most distinctive technique in the Production Harness article: a hypothesis slate frozen at iteration 0 prevents LLM reasoning loops from converging on early-evidence-supported hypotheses and retrospectively framing subsequent evidence to confirm them.

**Depends on:** `completion-report-schema-v1` (the report contract this gate consumes).

______________________________________________________________________

## Overview

This spec extends Spec #1's `IterationReport` schema with a `precommitment_slate` field that is **required at iteration 0 and forbidden at iterations > 0**, and defines a gate function `validate_precommitment()` that enforces those rules plus structural validity of the slate itself.

The slate carries **at least 6 candidate hypotheses** and **at least 4 evaluation criteria** for choosing among them. Once written, it is **immutable** — the timestamp `frozen_at` records when it was locked, and downstream consumers (including a future adversarial-review spec) read it from iteration 0's persisted report.

This spec does **not** include the adversarial reviewer; that is a separate concern. The gate is structural enforcement at publish; review is a downstream consumption pattern.

______________________________________________________________________

## Goals

- **G1.** Force every iterative Claude worker to enumerate a hypothesis space and evaluation criteria *before* running a single reasoning iteration, eliminating post-hoc rationalization.
- **G2.** Make the slate immutable from the moment it's written. Downstream consumers (persister, future adversarial reviewer) can trust that iteration 0's slate is the one the worker started with.
- **G3.** Compose with Spec #1's report contract. The slate lives on IterationReport at iteration 0; other iterations are unaffected.
- **G4.** Reuse Spec #1's error-handling pattern (`raise → loop terminates with blocked → Akosha anomaly`).

## Non-Goals

- **N1.** Defining the adversarial reviewer (a separate Claude invocation that compares the final conclusion against the initial slate). Deferred to a future spec; possibly folded into three-layer-self-heal.
- **N2.** Defining how hypotheses are *generated*. The worker produces them via Claude; the gate only validates that the slate is well-formed.
- **N3.** Multi-slate workflows (one slate per sub-investigation within a single workflow). v1.1 supports one slate per workflow.
- **N4.** Slate versioning. The slate is v1.1; bumps require a new schema file.

______________________________________________________________________

## Architecture & Data Flow

```
Worker loop, iteration_index = 0:
  ┌─────────────────────────────────────────────────────────────────┐
  │  1. Build slate (≥6 hypotheses, ≥4 criteria, frozen_at = now()) │
  │  2. Build IterationReport with precommitment_slate populated   │
  │  3. validate_precommitment(report)    ← gate (this spec)       │
  │     ↓ MahavishnuPrecommitmentViolation on violation             │
  │  4. validate_iteration_report(report) ← Spec #1                 │
  │  5. publish_iteration_report(report, source, correlation_id)    │
  │  6. Run Claude (the actual iteration)                           │
  └─────────────────────────────────────────────────────────────────┘

Worker loop, iteration_index > 0:
  1. Build IterationReport WITHOUT precommitment_slate
  2. validate_precommitment(report)    ← rejects if slate present
  3. validate_iteration_report + publish_iteration_report
  4. Run Claude, continue
```

**Key properties:**

1. **Single check at iteration 0, single check at iteration >0.** The gate is O(1) at every iteration; cost is slate validation, not new infrastructure.
1. **Immutability is structural, not procedural.** The gate enforces that no later iteration includes the slate field. Combined with Spec #1's persister (which writes each iteration to Dhara), this means the slate at iteration 0 is physically never updated.
1. **Composition with Spec #1.** The gate runs *between* `validate_iteration_report` (Spec #1) and `publish_iteration_report` (Spec #1). Failure propagates the same way as Spec #1's validation failures.

______________________________________________________________________

## Schema Definition (v1.1)

This spec introduces a **new sub-schema** for the slate and **extends** Spec #1's IterationReport with an optional field. The extension bumps Spec #1 from v1.0 to v1.1 per its own versioning policy (additive optional field = MINOR bump).

### New file: `mahavishnu/core/schemas/completion_report/precommitment_slate.v1.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://mahavishnu.local/schemas/precommitment_slate/v1.json",
  "title": "Precommitment Slate v1",
  "type": "object",
  "required": ["hypotheses", "evaluation_criteria", "frozen_at"],
  "properties": {
    "hypotheses": {
      "type": "array",
      "minItems": 6,
      "items": {"type": "string", "minLength": 1},
      "uniqueItems": true,
      "description": "Candidate explanations for the problem. Min 6, non-empty, distinct."
    },
    "evaluation_criteria": {
      "type": "array",
      "minItems": 4,
      "items": {"type": "string", "minLength": 1},
      "uniqueItems": true,
      "description": "Criteria for choosing among hypotheses. Min 4, non-empty, distinct."
    },
    "frozen_at": {
      "type": "string",
      "format": "date-time",
      "description": "UTC timestamp when the slate was locked. Immutable after creation."
    }
  },
  "additionalProperties": false
}
```

### Modified: `mahavishnu/core/schemas/completion_report/v1.json`

Add one new property to `iteration_report.properties`. **No other v1.0 fields change.** The `additionalProperties: false` policy is preserved; the slate is opt-in per-iteration (required at iter 0, forbidden at iter >0, enforced by the gate, not by the schema's required array).

```jsonc
{
  "iteration_report": {
    "type": "object",
    "required": [
      // unchanged from v1.0 — does NOT include precommitment_slate,
      // because the field is forbidden at iteration_index > 0.
      "schema_version", "report_kind", "workflow_id",
      "iteration_index", "iteration_budget",
      "started_at", "completed_at", "duration_ms",
      "status", "confidence",
      "open_questions", "unchecked_sources",
      "contradiction_register", "assumption_register", "adjacent_problems"
    ],
    "properties": {
      // ... all v1.0 properties unchanged ...
      "precommitment_slate": {
        "$ref": "precommitment_slate.v1.json",
        "description": "Required at iteration_index=0; forbidden at iteration_index>0. Enforced by validate_precommitment(), not by JSON Schema's required array (the field is structurally absent in non-initial iterations)."
      }
    },
    "additionalProperties": false
  }
}
```

### v1.1 schema_version discriminator

The `schema_version` field inside IterationReport's payload is bumped from `"1.0.0"` to `"1.1.0"` for reports that include the slate. Workers that don't yet emit slates continue emitting `"1.0.0"`. Consumers handle both versions:

- v1.0 consumer reading v1.1 report with `precommitment_slate` field — **accepts with warning** (relaxation of strict mode; see OQ1 resolution below).
- v1.1 consumer reading v1.0 report — accepts (slate is optional in the v1.1 schema).

______________________________________________________________________

## OQ1 Resolution: Cross-Version Reader Behavior

**Decision: v1.0 consumers are relaxed to accept-and-warn on unknown fields.**

This is a breaking change to Spec #1's strict `additionalProperties: false` policy. Justification:

1. Without this relaxation, a v1.0 worker that hasn't upgraded to v1.1 cannot read v1.1 reports. The whole point of additive evolution is that consumers don't need to coordinate.
1. The relaxation is **accept-and-warn**, not **accept-silently**. Akosha records unknown fields as warnings; operators can audit drift.
1. The strict policy still applies for *forward* evolution: a v1.1 worker emitting a v1.2 field would be rejected by v1.1's strict validation, surfacing the upgrade clearly.

Implementation: in `mahavishnu/core/events/report_validation.py`, when the validator encounters an unknown field, log a warning and accept. The strict rejection is reserved for malformed *known* fields.

Spec #1's spec file is **not amended**. This decision is recorded here as a v1.1 implementation detail that supersedes v1.0's "strict unknown-field rejection" policy for forward-compat purposes.

______________________________________________________________________

## Gate Function

```python
# mahavishnu/core/events/precommitment_gate.py

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from mahavishnu.core.errors import MahavishnuPrecommitmentViolation

SLATE_SCHEMA_PATH = (
    Path(__file__).parents[1]
    / "schemas"
    / "completion_report"
    / "precommitment_slate.v1.json"
)


@lru_cache(maxsize=1)
def _slate_validator() -> Draft202012Validator:
    schema = json.loads(SLATE_SCHEMA_PATH.read_text())
    return Draft202012Validator(schema)


def validate_precommitment(report: dict) -> None:
    """Validate precommitment slate rules for an IterationReport.

    Rules:
    - iteration_index == 0 → precommitment_slate MUST be present and valid.
    - iteration_index > 0  → precommitment_slate MUST NOT be present.

    Raises:
        MahavishnuPrecommitmentViolation: if any rule is violated.
    """
    iteration_index = report.get("iteration_index")
    slate = report.get("precommitment_slate")

    if iteration_index == 0:
        if slate is None:
            raise MahavishnuPrecommitmentViolation(
                "iteration_index=0 requires precommitment_slate field"
            )
        errors = list(_slate_validator().iter_errors(slate))
        if errors:
            raise MahavishnuPrecommitmentViolation(
                f"precommitment_slate failed validation: {errors}"
            )
        return

    if slate is not None:
        raise MahavishnuPrecommitmentViolation(
            f"iteration_index={iteration_index} must not include precommitment_slate"
        )
```

### New exception

In `mahavishnu/core/errors.py`, add (after `MahavishnuReportValidationError`):

```python
class MahavishnuPrecommitmentViolation(MahavishnuError):
    """Raised when an IterationReport violates precommitment slate rules.

    Three failure modes:
    - iteration_index=0 lacks precommitment_slate
    - iteration_index=0 has malformed precommitment_slate
    - iteration_index>0 has precommitment_slate (forbidden after iteration 0)
    """
```

### Integration with Spec #1's publisher

In `mahavishnu/core/events/report_publishers.py`, modify `publish_iteration_report`:

```python
async def publish_iteration_report(report: dict, *, source: str, correlation_id: str) -> None:
    validate_precommitment(report)             # ← NEW (this spec)
    validate_iteration_report(report)          # Spec #1
    envelope = EventEnvelope(
        event_type="workflow.iteration.completed",
        source=source,
        correlation_id=correlation_id,
        payload=report,
        metadata={"report_kind": "iteration", "schema_version": report["schema_version"]},
    )
    await event_bus.publish(envelope)
```

Failure path is identical to Spec #1: `MahavishnuPrecommitmentViolation` propagates, worker loop terminates with `exit_reason="blocked"`, Akosha anomaly recorded.

______________________________________________________________________

## Adoption & Migration

| Version | Adoption policy |
|---|---|
| **v1.1** | Slate schema + gate shipped. Opt-in via `params.enable_precommitment=true`. Workers that don't enable continue to publish IterationReport without the slate field; gate allows that (the slate is optional at iteration_index > 0 anyway, and absent at iter 0 is a violation). |
| **v1.2** | New iterative workers MUST enable precommitment; existing iterative workers log a deprecation warning once per process. CLI `migrate --check-reports` (Spec #1) extended to flag workers that don't enable precommitment. |
| **v2.0** | Every iterative worker MUST emit precommitment at iteration 0. `publish_iteration_report()` always runs `validate_precommitment`; the `enable_precommitment` parameter is removed. |

**Migration aid:** Extend Spec #1's `mahavishnu migrate --check-reports` CLI to also check for `enable_precommitment=True` in worker entrypoints.

______________________________________________________________________

## Storage & Retrieval

No schema change to Spec #1's `iteration_reports` table. The `payload` column already stores the full JSON report; v1.1 reports include `precommitment_slate` and v1.0 reports do not. Retrieval tools work unchanged.

A future query helper (out of scope for v1.1) may add `get_precommitment_slate(workflow_id) -> dict | None` that reads iteration 0's slate directly. Not needed for the gate or any in-scope consumer.

______________________________________________________________________

## Error Handling

| Failure | Detection | Response |
|---|---|---|
| Iteration 0 lacks slate | `validate_precommitment` at iter 0 | `MahavishnuPrecommitmentViolation`; worker loop terminates with `exit_reason="blocked"`; Akosha anomaly. |
| Iteration 0 has malformed slate | `validate_precommitment` at iter 0 | Same. Error includes `jsonschema` error paths. |
| Iteration >0 has slate | `validate_precommitment` at iter >0 | Same. |
| Slate validator unavailable (file missing) | `SLATE_SCHEMA_PATH.read_text()` raises `FileNotFoundError` | Worker fails loudly on startup; gate never runs. Treat as deployment error. |
| Duplicate slate across iterations (race condition) | Out of v1.1 scope; rely on Spec #1's persister primary key `(workflow_id, iteration_index)` to detect. | Duplicate publish raises existing persister error. |

______________________________________________________________________

## Testing Strategy

Aligned with Bodai's L0–L4 framework.

| Layer | Tests |
|---|---|
| **L0 (pure boundary)** | Slate schema validation: ≥6 hypotheses, ≥4 criteria, distinct non-empty strings, frozen_at ISO 8601. IterationReport v1.1 accepts slate at iter 0, rejects at iter >0, rejects malformed slate. v1.0 consumer reads v1.1 report with unknown field: accepts with warning. |
| **L1 (file isolation)** | Slate JSON file round-trip. IterationReport JSON serialization with optional slate field. |
| **L2 (service isolation)** | Publisher raises `MahavishnuPrecommitmentViolation` on missing slate at iter 0; raises on present slate at iter >0; raises on malformed slate. Worker loop terminates with `exit_reason="blocked"`. Akosha anomaly emitted. |
| **L3 (sandbox)** | Real EventBus + Spec #1 persister. Iteration 0 with slate is persisted; subsequent iterations without slate are persisted. Persister schema-version discriminator routes correctly. |
| **L4 (integration matrix)** | Cross-version: v1.0 worker + v1.1 consumer (forward compat — slate is opaque optional field); v1.1 worker + v1.0 consumer (accept-with-warning); v1.1 worker + v1.1 consumer (full contract). |

**Coverage target:** `tests/unit/test_precommitment_gate.py` and `tests/integration/test_precommitment_integration.py` ≥ 95% line coverage.

**Fixtures:** `tests/fixtures/slates.py` with reusable valid/invalid slate generators.

______________________________________________________________________

## Implementation Module Paths

| Component | Path |
|---|---|
| Slate JSON Schema (new) | `mahavishnu/core/schemas/completion_report/precommitment_slate.v1.json` |
| IterationReport schema (modified, v1.0 → v1.1) | `mahavishnu/core/schemas/completion_report/v1.json` |
| Gate function | `mahavishnu/core/events/precommitment_gate.py` |
| Exception class | `mahavishnu/core/errors.py` (additive: `MahavishnuPrecommitmentViolation`) |
| Publisher integration | `mahavishnu/core/events/report_publishers.py` (one-line addition in `publish_iteration_report`) |
| Validation relaxation (accept-warn-unknown) | `mahavishnu/core/events/report_validation.py` (modify `_format_errors` behavior) |
| Migration CLI extension | `mahavishnu/cli/report_migration_cli.py` (extend `check-reports` to also flag precommitment absence) |
| L0 tests | `tests/unit/test_precommitment_gate.py` |
| L1 tests | `tests/unit/test_precommitment_gate.py` (file round-trip portion) |
| L2 tests | `tests/integration/test_precommitment_publisher.py` |
| L3 tests | `tests/integration/test_precommitment_persister.py` |
| L4 tests | `tests/integration/test_precommitment_cross_version.py` |
| Test fixtures | `tests/fixtures/slates.py` |

______________________________________________________________________

## Trade-offs & Alternatives Considered

| Choice | Why this | Why not the alternative |
|---|---|---|
| Slate on IterationReport iteration 0 (per first design decision) | Reuses Spec #1's envelope + persister + retrieval; no new event type | Separate `workflow.precommitment.locked` event — adds a second envelope to subscribe to; doubles subscription surface for downstream consumers. |
| Required at iter 0, forbidden at iter >0 (enforced by gate) | Mirrors the article's "frozen in iteration 0" pattern; structural enforcement > procedural | Optional everywhere — workers can omit; loses the forcing function. |
| Accept-and-warn on unknown fields in v1.0 consumers | Forward compat without coordination overhead | Strict rejection everywhere — every reader must coordinate with every writer's evolution. |
| Gate runs at publish (not at consume) | Same pattern as Spec #1; failure blocks iteration; Akosha anomaly immediately | Gate at consume — bad reports reach storage; harder to debug. |
| 6 hypotheses + 4 criteria (article defaults) | Article-faithful; meaningful minimum that prevents shallow enumeration | Lower minimums (e.g. 3+2) — easier to game; loses forcing function. Higher minimums (e.g. 10+6) — narrow problems struggle to enumerate. |
| Slate scope: this spec only; adversarial review deferred | Focused spec; review is its own design conversation | Bundle review into this spec — 30+ page document; harder to review. |

______________________________________________________________________

## Open Questions / Future Work

- **OQ1 (resolved).** Cross-version reader behavior: accept-and-warn. Recorded above.
- **OQ2.** Should the slate include an `iteration_index` field inside it for self-description? Currently the slate is implicitly iteration 0 (the gate enforces it). Adding it would be redundant; skipping for v1.1.
- **OQ3.** When v1.1 reports are read by an Akosha consumer that doesn't know about precommitment, does the unknown field trigger an anomaly? Decision: yes, but downgraded to `info` level (not `warning`). Operator-tunable.
- **OQ4.** Future v1.2+ may add `precommitment_extends` for sub-investigations within a workflow. Deferred; v1.1 supports one slate per workflow.

______________________________________________________________________

## Success Criteria

- **SC1.** Slate JSON Schema file created; IterationReport JSON Schema updated to v1.1 with `precommitment_slate` field.
- **SC2.** `validate_precommitment()` function implemented; tested against all rule violations (missing at iter 0, malformed, present at iter >0).
- **SC3.** `publish_iteration_report()` integrates the gate; failure propagates as `MahavishnuPrecommitmentViolation`.
- **SC4.** Spec #1's `report_validation.py` relaxed to accept-warn-unknown-fields; tests confirm behavior.
- **SC5.** L0–L3 tests green; ≥ 95% line coverage on the new module.
- **SC6.** Spec #3 (`confidence-ceiling-gate`) can reference `validate_precommitment` and the slate field as the input contract for confidence arithmetic (slate presence at iter 0 is a precondition for `confidence-ceiling-gate`'s invocation).
