# Oneiric EventEnvelope Wire Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-07-14
**Status:** draft, planning
**Owner:** Mahavishnu core
**Scope:** Phase 1 wire standardization plus the originally reported checker fixes.
**Purpose:** Standardize Mahavishnu’s cross-process EventBridge and optional Redis event records on Oneiric’s `EventEnvelope`, preserve the existing in-process Pydantic event contract, clear the reported pyscn and ty findings, and produce an end-to-end wire proof plus truthful feature state.

## 1. Outcome

When this plan ships:

1. The active EventBridge lifecycle path uses Oneiric envelopes with one canonical identity/timestamp pair and the concrete WebSocket server is wired through `set_eventbridge_publisher`.
2. The optional `RedisEventTransport` writes one canonical `{"wire_format": "oneiric-v1", "envelope": ...}` record by default and a legacy rollback record on operator opt-in.
3. The Bodai subscriber decodes the canonical record, decodes a legacy record only when `MAHAVISHNU_BODAI_ACCEPT_LEGACY_WIRE` is enabled, and the public entry point pyscn cyclomatic complexity is at most 10.
4. `mahavishnu metrics bodai` renders canonical source and timestamp data and shows that the queue was populated.
5. `pyscn` and `ty` no longer report the original failures.

**Concrete success signal:** `uv run pytest --no-cov tests/integration/test_event_wire_e2e.py -v` exits 0 and the test proves the canonical record before any consumer, the subscriber acks exactly once, and the CLI renders the canonical source.

## 2. Goals

1. Convert at one explicit boundary: `mahavishnu.core.events.canonical`.
2. Move the active lifecycle publisher to the canonical Oneiric protocol.
3. Repair the real EventBridge wiring by calling the concrete server setter.
4. Provide canonical and legacy modes for the optional Redis transport.
5. Refactor the Bodai subscriber to ten single-responsibility helpers and at most pyscn cyclomatic complexity 10.
6. Centralize Bodai metrics CLI header narrowing.
7. Remove the redundant Agno MCP transport cast and the unused `Literal` import.
8. Record truthful `built`/`wired` state and dated Phase 1 follow-ups.

## 3. Non-Goals

1. Replacing every in-process `EventPublisherProtocol` reference.
2. Removing `mahavishnu/core/events/envelope.py`.
3. Promoting Mahavishnu’s schema registry and compatibility policy into Oneiric.
4. Changing Oneiric’s runtime dispatcher API.
5. Migrating Oneiric shell `SessionStartEvent` / `SessionEndEvent` models.
6. Cross-repository changes in Akosha, Crackerjack, or Session-Buddy.
7. Adding `fakeredis` as a dev dependency.
8. Claiming OTLP collector delivery or p99 latency from unit tests.
9. Modifying `MessageBus.set_event_publisher`; it remains on the Pydantic protocol in Phase 1.

## 4. Current Findings

| Finding | Evidence | Implication |
|---|---|---|
| `pyscn` reports `subscribe_to_bodai_events` complexity 31, above ceiling 10 | `uv run pyscn check mahavishnu/core/events/bodai_subscriber.py` | Refactor the subscriber into single-responsibility helpers. |
| `ty` reports the Oneiric/Pydantic publisher mismatch | `mahavishnu/core/events/mahavishnu_publisher.py:35,91` | Move lifecycle publishers to `OneiricEventPublisherProtocol`. |
| `ty` reports resolver/concrete server setter mismatch | `mahavishnu/core/events/eventbridge_resolver.py:30,62` vs `mahavishnu/websocket/server.py:666` | Call `set_eventbridge_publisher`. |
| `ty` reports redundant Agno cast and unused `Literal` | `mahavishnu/engines/agno_adapter_impl.py:27,321` | Remove the cast and `Literal`. |
| `ty` reports headers narrowing in `metrics_cli.py:933` | `mahavishnu/metrics_cli.py:902-965` | Centralize `_headers_of(event)`. |
| `RedisEventTransport` writes flat Mahavishnu fields and a JSON blob | `mahavishnu/core/events/transport.py:205-226` | Switch to canonical two-field record. |
| `EventBusConsumer` decodes Pydantic only | `mahavishnu/core/events/transport.py:280,289` | Decode canonical first, legacy only when enabled. |
| `msgspec` is not declared in `pyproject.toml` | `pyproject.toml:20-89` | Add it as a direct dependency. |
| Targeted pytest commands enforce repository coverage | `pyproject.toml:327-331` `--cov-fail-under=80` | Use `--no-cov` for local gates; route full coverage to Crackerjack. |
| `mahavishnu.metrics_cli` renders source/count/timestamp, not topics | `mahavishnu/metrics_cli.py:975-1098` | End-to-end test must assert only the rendered fields. |
| `_BridgeSpy`/`RecordingQueueAdapter` and Oneiric decode helpers do not exist yet | `tests/unit/test_eventbridge_resolver.py` etc. | Plan creates them inline. |

## 5. Implementation Phases

### Phase 1: Wire Standardization

**Goal:** Replace cross-process envelopes with Oneiric, fix checker findings, and prove one end-to-end wire cycle.

**Tasks:** see Tasks 0–9 below.

**Exit criteria:** all Task 9 quality gates pass and `docs/feature-tracking/oneiric-event-envelope-wire-standardization.md` exists.

#### Integration Contract — Phase 1

- **Triggered from:** WebSocket workflow lifecycle broadcasts in `mahavishnu/websocket/server.py`; optional `RedisEventTransport.publish` from in-process producers; the `bodai-activity-subscriber` SessionStart hook.
- **Returns to / updates:** Oneiric envelopes flow on the EventBridge and Redis wire paths; the existing Pydantic in-process contract is preserved; the local Bodai queue and `mahavishnu metrics bodai` render canonical source/timestamp data.
- **Demonstrable by:** `uv run pytest --no-cov tests/integration/test_event_wire_e2e.py -v` passes and the test observes the canonical record before any consumer.
- **Rollback signal:** spec §6.4 signals are wired to metrics/logs/tests in Task 9.
- **Observability added:** four counters and four structured log names defined in Task 3.

## 6. Required Code Changes

- **New:**
  - `mahavishnu/core/events/canonical.py`
  - `mahavishnu/core/events/observability.py`
  - `tests/unit/test_event_canonical.py`
  - `tests/unit/test_event_wire_observability.py`
  - `tests/unit/test_event_conversion_error.py`
  - `tests/integration/test_event_wire_e2e.py`
  - `docs/feature-tracking/oneiric-event-envelope-wire-standardization.md`
- **Modify:**
  - `pyproject.toml` — add `msgspec>=0.21.1,<0.22` to project dependencies.
  - `mahavishnu/core/errors.py` — add `EventEnvelopeConversionError`.
  - `mahavishnu/core/events/__init__.py` — re-export the canonical surface.
  - `mahavishnu/core/events/eventbridge_resolver.py` — protocol and call use `set_eventbridge_publisher`.
  - `mahavishnu/core/events/eventbridge_adapter.py` — typed against the canonical protocol.
  - `mahavishnu/core/events/mahavishnu_publisher.py` — use the canonical factory and the canonical protocol.
  - `mahavishnu/core/events/transport.py` — canonical and legacy write modes; canonical-first decoder.
  - `mahavishnu/core/events/bodai_subscriber.py` — canonical decoder and ten single-responsibility helpers.
  - `mahavishnu/websocket/server.py` — typed EventBridge publisher slot.
  - `mahavishnu/mcp/tools/eventbridge_tools.py` — comment only.
  - `mahavishnu/engines/agno_adapter_impl.py` — remove literal cast and `Literal` import (resolved via the four-branch equality pattern).
  - `mahavishnu/metrics_cli.py` — centralize `_headers_of` and use it everywhere.

## 7. Validation Matrix

| Tool/command | Expected outcome | Evidence location |
|---|---|---|
| `uv run pyscn check mahavishnu/core/events/bodai_subscriber.py` | no complexity failure | terminal |
| `uv run ty check mahavishnu/core/events/mahavishnu_publisher.py mahavishnu/core/events/eventbridge_resolver.py mahavishnu/engines/agno_adapter_impl.py mahavishnu/metrics_cli.py` | no diagnostics | terminal |
| `uv run pytest --no-cov tests/integration/test_event_wire_e2e.py -v` | pass; canonical record asserted | terminal |
| `uv run pytest --no-cov tests/unit/test_bodai_subscriber.py -v` | pass; acknowledgement matrix covered | terminal |
| `python scripts/audit_orphans.py` | no newly introduced zero-caller symbols | terminal |
| `uv run crackerjack run` (routed through `mcp__mahavishnu__pool_route_execute`) | exits 0 or isolates pre-existing failures | Crackerjack output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Pydantic reverse conversion rejects Oneiric values the canonical factory accepted | medium | Constrain factory inputs to Pydantic-compatible shapes; add structured tests for each reject reason. |
| `RedisEventTransport` becomes orphan after standard adopts the canonical path | high | Document adoption state in Task 9 with a dated wire-or-retire review. |
| Subscriber refactor changes acknowledgement behavior | medium | Pin the full matrix in Task 7 with separate failing tests. |
| Coverage gate blocks every local pytest command | high | Use `--no-cov` everywhere except Crackerjack. |

## 9. Decision Rule

Phase 1 is done when: `pyscn` and `ty` report no original findings; `tests/integration/test_event_wire_e2e.py` proves the canonical record end to end; the feature-tracking entry states `built` only and the optional Redis transport’s wired/adopted state is honestly absent.

## 10. Task Briefs (see `.superpowers/sdd/task-N-brief.md`)

| Task | Brief | Status |
|---|---|---|
| 0 | `.superpowers/sdd/task-0-brief.md` | done (evidence only) |
| 1 | `.superpowers/sdd/task-1-brief.md` | done (spec ✅, quality ✅) |
| 2 | `.superpowers/sdd/task-2-brief.md` | done after fix (ty clean) |
| 3 | `.superpowers/sdd/task-3-brief.md` | done (spec ✅, quality ✅) |
| 4 | `.superpowers/sdd/task-4-brief.md` | pending |
| 5 | `.superpowers/sdd/task-5-brief.md` | pending |
| 6 | `.superpowers/sdd/task-6-brief.md` | pending |
| 7 | `.superpowers/sdd/task-7-brief.md` | pending |
| 8 | `.superpowers/sdd/task-8-brief.md` | pending |
| 9 | `.superpowers/sdd/task-9-brief.md` | pending |

## 11. Explicit Follow-ups Outside Phase 1

- Decide by 2026-08-14 whether to wire `RedisEventTransport` into startup or retire the optional adapter.
- Add publish/decode latency histograms only through a separate observability design.
- Verify OTLP collector delivery in a configured deployment.
- Add a real Redis consumer-group test or an approved fakeredis dependency after proving Streams semantics.
- Retire legacy decoding only after seven zero-use days in an enabled deployment and operator review.
- Hold the Phase 3 envelope-retirement architecture review no later than 2026-09-14.
- Leave the unrelated cast at `agno_adapter_impl.py:1332` unchanged unless ty independently reports it.

## 12. Global Constraints (apply to every task)

- Python target is 3.13.
- Source line length is at most 100 characters.
- Every function in `mahavishnu/core/events/bodai_subscriber.py` must have pyscn cyclomatic complexity at most 10.
- New source files begin with `from __future__ import annotations` after any module docstring.
- Imports remain sorted stdlib → third-party → first-party.
- Canonical payload and metadata are shallow-copied and never recursively normalized.
- Reserved header values are supplied once through named parameters; `extra_headers` cannot contain reserved keys.
- Canonical paths never call Mahavishnu `EventEnvelope.from_dict()` or `from_json()`.
- Conversion and encoding failures happen before enqueue or pub/sub publication.
- New structured logs use `oneiric.core.logging.get_logger`; do not add stdlib logging to new modules.
- Async orchestration code performs blocking queue-file writes through `asyncio.to_thread`.
- Preserve the subscriber acknowledgement matrix from the specification exactly.
- Do not modify `MessageBus.set_event_publisher`; it remains on the Pydantic protocol in Phase 1.
- Do not claim `RedisEventTransport` is adopted production wiring; it remains injectable and not constructed by the active startup path.
- Do not claim OTLP collector delivery or latency rollback thresholds from unit tests.
- Use `uv run pytest --no-cov` for all local pytest invocations.
- Pre-commit checkpoint: `git status --short`; refuse any `git add` that pulls in `uv.lock`, `docs/plans/drafts/...`, or other user-owned files not listed in this plan.
- Comma-separated `Co-Authored-By: Claude <noreply@anthropic.com>` on every authorized commit.
