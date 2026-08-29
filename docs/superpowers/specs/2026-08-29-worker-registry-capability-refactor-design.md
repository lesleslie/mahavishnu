# Worker Registry Capability Refactor + Engine Composition Layer

**Status:** Draft for multi-agent review
**Date:** 2026-08-29
**Author:** Claude (brainstorming session)
**Scope:** Stages 1, 2, 3 from brainstorming — registry fix, capability-driven selection, engine composition

---

## Context

The Mahavishnu worker subsystem has two interlocking defects and one architectural gap:

**Defect 1 (Stage 1, immediate):** The `tmux_adapter.create_session` function re-quotes worker launch commands that are already pre-quoted shell strings. The result is every `terminal-*` worker except `terminal-shell` and the bare-argv variants spawns into a non-functional zsh pane. Today: `pool_spawn(worker_type="terminal-claude")` returns success but the tmux pane contains `zsh: command not found: sh -lc 'claude ...'`.

**Defect 2 (Stage 2):** The worker registry (`mahavishnu/workers/registry.py`) is a flat `dict[str, WorkerConfig]` with 16 hand-curated entries. Selection is by string key. There is no capability matching, no auto-selection, and adding a new CLI requires editing Python.

**Gap (Stage 3):** The 5 engines (Prefect, LlamaIndex, Agno, Hatchet, Worker) are ortho­gonal subsystems. Today an operator picks one engine per task. There is no composition layer that runs "ingest with LlamaIndex + review with Agno + execute with Worker + persist with Prefect" as a unified workflow. This is the user's stated vision: engines working together, each doing what it does best.

All three are addressed in one spec because they share a foundation (the capability schema) and the user has explicitly said no backward-compat shims are needed.

---

## Goals

1. **Fix the worker bootstrap bug** so all 16 `terminal-*` worker types actually spawn a working tmux pane. (Stage 1)
2. **Replace the static registry** with a capability-driven registry where workers and engines share one capability vocabulary. (Stage 2)
3. **Add a composition layer** that resolves a task's required capabilities into a DAG of engines and runs it via Prefect. (Stage 3)
4. **Eliminate the dual-registry** (`WORKER_REGISTRY` + `app.adapters`) — both engines and workers live in one unified `CapabilityRegistry`.
5. **Keep the MCP-first design intact** — the new shape fits as an 18th profile-gated tool group.

## Non-Goals

- **UI / dashboard changes.** The CLI and MCP tools are the only surfaces touched.
- **Cross-cluster / cross-region orchestration.** Single Mahavishnu instance only.
- **Engine refactors.** Existing engines (Prefect, LlamaIndex, Agno, Hatchet, Worker) are not rewritten — they expose `provides: list[Capability]` in addition to their existing `AdapterCapabilities`.
- **LLM model registry unification.** This spec covers engines and workers. Model selection (MiniMax vs Claude vs Ollama) remains in the existing `TaskRouter` and is referenced via `CapabilityKind.MODEL` if a task requires a specific model.
- **Backward compat.** Old tools (`pool_spawn`, `pool_execute`, `pool_route_execute`, `dispatch_to_pool`, `trigger_workflow`, `worker_spawn`, `worker_execute`, `worker_close`, `worker_health`) are deleted. No shims, no aliases, no deprecation window.

---

## Design

### Section 1: Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  MCP client (Claude Code, CLI, slash command)                   │
│  Tool: execute_capability(spec, prompt, ...)                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Mahavishnu Conductor (NEW: mahavishnu/core/conductor.py)        │
│  - Capability resolution (interface-style)                       │
│  - Binding plan generation (DAG of engines)                      │
│  - Envelope transport (typed, persisted to Dhara)               │
└────────────────────────────┬────────────────────────────────────┘
                             │  Binding plan (ExecutionDAG)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Prefect DAG runtime (existing adapter, extended)                │
│  - Durable state, retries, scheduling                            │
│  - One Prefect task per binding-plan node                        │
└────────────────────────────┬────────────────────────────────────┘
                             │  task_type → engine
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Capability-aware engines (all 5 existing adapters)              │
│  Each declares provides: list[Capability]                       │
│  LlamaIndex (RAG) │ Agno (multi-agent) │ Worker pool (terminal)  │
│  Prefect (durable) │ Hatchet (durable alternative)              │
└─────────────────────────────────────────────────────────────────┘
```

**Architectural invariants:**

- **Conductor lives in Mahavishnu**, not in any individual engine. It is the layer that knows about all engines.
- **Prefect is the DAG runtime underneath the conductor**, the way an OS scheduler is underneath a workload orchestrator. Mahavishnu emits a Prefect flow definition; Prefect handles durability/retry/scheduling.
- **Engines don't call each other.** They read/write typed envelopes persisted to Dhara. The conductor routes envelopes between engines.
- **All selection is capability-driven.** No engine_id or worker_type strings in user-facing specs.

### Section 2: Capability Schema

```python
# mahavishnu/core/capabilities.py (NEW)
from __future__ import annotations
from enum import StrEnum
from typing import Any, Literal
from pydantic import BaseModel, Field


class CapabilityKind(StrEnum):
    """Top-level capability dimensions. String-addressed as `kind:name`."""
    ENGINE = "engine"
    MODEL = "model"
    WORKER = "worker"
    ADAPTER = "adapter"


class CapabilityState(StrEnum):
    """Lifecycle state of a capability implementation."""
    STATELESS = "stateless"
    EPHEMERAL = "ephemeral"
    DURABLE = "durable"


class TypeSchema(BaseModel):
    """Typed I/O contract for a capability."""
    fields: dict[str, Any] = Field(default_factory=dict)

    def matches(self, other: "TypeSchema") -> bool:
        """Returns True if `other`'s fields are a subset of self's (structural subtyping)."""


class CostHint(BaseModel):
    """Best-effort cost/latency profile for routing decisions."""
    latency_p50_ms: int | None = None
    latency_p99_ms: int | None = None
    tokens_per_call: int | None = None
    has_side_effects: bool = False


class HealthRef(BaseModel):
    """Point-in-time health check for a capability implementation."""
    last_check_at: str | None = None
    last_status: Literal["healthy", "degraded", "unreachable"] | None = None
    check_url: str | None = None


class Capability(BaseModel):
    """A single capability that can be required or provided."""
    id: str
    kind: CapabilityKind
    description: str
    io_in: TypeSchema
    io_out: TypeSchema
    state: CapabilityState
    idempotency_key: str | None = None
    cost_hint: CostHint = Field(default_factory=CostHint)
    health: HealthRef = Field(default_factory=HealthRef)
    tags: list[str] = Field(default_factory=list)
    undo: str | None = None  # CapabilityId of compensating action


class EngineRegistration(BaseModel):
    """An engine's capability surface."""
    engine_id: str
    provides: list[Capability]
    consumes: list[Capability]
    affinity: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class CapabilityEnvelope(BaseModel):
    """Typed, serializable record handed between engines."""
    envelope_id: str
    capability_id: str
    engine_id: str
    io_out: dict[str, Any]
    produced_at: str
    trace_id: str
    parent_envelope_ids: list[str] = Field(default_factory=list)
```

**Why interface-style (not flat flags, not hierarchical):**
- Flat flags conflate identity with capability (`provides_rag: bool` AND `provides_durable_flow: bool` on the same engine).
- Hierarchical taxonomy (`engine.durable`, `engine.agent`) fights cross-engine composition.
- Typed I/O contracts (`io_in`, `io_out`) enable structural subtyping: "what engine produces X?" auto-matches "what engine consumes X?" without hard-coded wiring.

**Why `kind:name` string addressing:**
- Mirrors Vercel AI SDK's `providerId:modelId` shape — proven multi-vendor abstraction.
- One namespace for engines, models, workers, adapters.
- Operators request `engine:prefect` or `model:minimax-m3` or `worker:claude-tui` in the same syntax.

### Section 3: Components

| Component | File | Responsibility |
|---|---|---|
| **Capability registry** | `mahavishnu/core/capabilities.py` (NEW) | `Capability`, `EngineRegistration`, `CapabilityEnvelope`, `CapabilityKind`. YAML-loaded at boot. |
| **Conductor** | `mahavishnu/core/conductor.py` (NEW) | Resolves `CapabilitySpec → ExecutionDAG`. Emits Prefect flow. Routes envelopes. |
| **Resolver** | `mahavishnu/core/conductor.py` | Pure function: `resolve(spec, registry) → list[Candidate]`. |
| **Binding planner** | `mahavishnu/core/conductor.py` | Pure function: `plan(candidates, spec) → ExecutionDAG`. Greedy fill; capability_adapters for gaps. |
| **Envelope transport** | `mahavishnu/core/envelopes.py` (NEW) | Read/write envelopes to Dhara. Trace ID propagation. |
| **Engine adapters** | `mahavishnu/engines/*_adapter_impl.py` (MODIFIED) | Each declares `provides: list[Capability]`. `execute()` accepts `CapabilitySpec`. |
| **Worker registry** | `mahavishnu/workers/registry.py` (REPLACED) | YAML-driven (`settings/workers.yaml`). Each worker is `WorkerRegistration` with `provides`. |
| **Prefect DAG runner** | `mahavishnu/engines/prefect_adapter_impl.py` (EXTENDED) | Emits Prefect flow from `ExecutionDAG`. One task per node. |
| **MCP tool group** | `mahavishnu/mcp/tools/capability_tools.py` (NEW) | 18th profile-gated group: `execute_capability`, `list_capabilities`, `explain_routing`. |
| **Tool cleanup** | `mahavishnu/mcp/tools/pool_tools.py`, `worker_tools.py`, `workflow_tools.py` | Old `pool_*`, `worker_*`, `trigger_workflow` tools deleted. |

**Selector strategies (AutoGen-style pluggable):**
- `least_loaded`, `round_robin`, `random` — current `route_task` behavior.
- `affinity`, `peer_affinity` — ADR-014.
- `capability_score` (NEW): weighted match on tags + cost + health.
- `llm_select` (NEW): LLM-mediated; falls back to `capability_score` on low confidence.

**Deterministic selector is always in the loop.** Even when `llm_select` is chosen, `capability_score` runs as fallback (AutoGen pitfall warning).

### Section 4: Data Flow

1. **Operator** calls `execute_capability(spec={"requires": ["rag.retrieve", "exec.terminal"]}, prompt="...")`.
2. **Conductor.resolve(spec, registry)** scores every engine that provides each required capability:
   - LlamaIndex provides `rag.retrieve` (score 0.92).
   - Worker pool provides `exec.terminal` (score 0.88, picks `worker-claude-tui` via capability submatch).
3. **Conductor.plan(candidates, spec)** emits `ExecutionDAG`:
   - `n1=llamaindex.rag.retrieve`
   - `n2=worker-claude-tui.exec.terminal`
   - Edge: `n1.io_out.{retrieved_chunks} → n2.io_in.{context}` (structural subtyping match).
4. **Conductor.emit_flow(DAG)** emits a Prefect flow definition. Each DAG node becomes a `@task`; the envelope handoff becomes the task's return value.
5. **Prefect runs the flow** (durable, retried, scheduled):
   - `n1` runs → envelope `envelope_001` written to `Dhara://envelopes/trace_xyz/envelope_001`.
   - `n2` reads envelope_001, runs, writes `envelope_002`.
6. **Prefect returns final state**; conductor returns `{trace_id, envelopes, status}`.

### Section 5: Error Handling

| Failure mode | Behavior |
|---|---|
| No engine matches a required capability | Raise `UnresolvableCapabilityError`. Response: `{unmatched: [...], partial_binding: [...]}`. |
| Multiple candidates tied | Deterministic score → tie-break by `(least_loaded, affinity, lowest_cost)`. Weights in `binding_policy.yaml`. |
| Engine fails mid-DAG | Prefect retries with `idempotency_key` gate: re-run iff capability declares key (e.g. `rag.retrieve`); skip iff side effects. Failed envelope stays in Dhara. |
| Engine disappears mid-DAG | Conductor rebinds the failed node against remaining candidates. Replays downstream from cached envelopes. |
| Prefect itself crashes | Prefect's durable execution handles this. No Mahavishnu-side code. |
| Envelope write fails | Transient → exponential backoff. Persistent → node FAILED, DAG halts. |
| LLM selector low confidence | Fall back to `capability_score`. |

**Compensating actions:** declared per capability via `Capability.undo: Optional[CapabilityId]`. If `exec.terminal` ran `git push`, the compensating capability `exec.git-rollback` is automatically invoked on downstream failure.

### Section 6: Testing

| Layer | Tool | Coverage |
|---|---|---|
| Unit — capability schema | pytest | Pydantic validation; `TypeSchema.matches()` structural subtyping. |
| Unit — resolver | pytest + hypothesis | `resolve()` correctness; tie-break deterministic; score weights honored. |
| Unit — binding planner | pytest | `plan()` produces valid DAGs: no cycles, all edge endpoints exist. |
| Contract — engine adapters | pytest | Each engine's `execute()` produces envelopes matching declared `io_out`. |
| Integration — end-to-end DAG | pytest + docker-compose (Prefect) | `execute_capability({"requires": ["rag.retrieve", "exec.terminal"]})` runs full DAG. |
| Failure injection | pytest | Crash mid-DAG → resume from envelope. Idempotency-key gate. |
| Selector strategies | pytest | All 5 strategies return expected candidates for fixed inputs. |
| MCP tool surface | pytest | `execute_capability`, `list_capabilities`, `explain_routing` schema validation. |

**Coverage targets:** new code ≥89%; conductor ≥95% (high criticality). Existing engine adapters maintained at current levels.

---

## Migration Plan

Three stages, each independently shippable but designed to compose. No stage requires the next to function — Stage 1 ships as a hotfix, Stage 2 ships the new capability schema with the worker registry replaced, Stage 3 adds the engine composition layer.

### Stage 1 — Worker bootstrap fix (immediate hotfix)

**Scope:** Fix `tmux_adapter.create_session` so `tmux new-session` exec's the launch command directly. Single-file change.

**Files:**
- `mahavishnu/workers/contract/tmux_adapter.py:152` — drop send-keys; pass command to `tmux new-session`.

**Exit criteria:** All 16 `terminal-*` worker types spawn functional tmux panes. Smoke test: `pool_spawn --worker-type terminal-claude` produces a pane with `claude --output-format stream-json ...` running, not a `zsh: command not found` error.

**Reversibility:** Trivial. Revert the one-file change.

### Stage 2 — Capability-driven registry

**Scope:** Replace static registry with capability-driven registry. Workers and engines share one capability vocabulary.

**Files (new):**
- `mahavishnu/core/capabilities.py` — schema definitions.
- `mahavishnu/workers/registry.py` (replaced) — yaml-driven loader.

**Files (modified):**
- `settings/workers.yaml` (new) — worker registrations.
- `mahavishnu/core/bootstrap.py` — load workers via yaml.
- All `mahavishnu/engines/*_adapter_impl.py` — declare `provides: list[Capability]`.

**Files (deleted):**
- `mahavishnu/workers/registry.py:WORKER_REGISTRY` (literal registry).
- `mahavishnu/terminal/config.py` adapter references.

**Exit criteria:** Same `pool_spawn --worker-type terminal-claude` works. New: `pool_spawn --worker-type <yaml-only-name>` works. Each worker's `provides` are discoverable via `list_capabilities(domain="worker")`.

**Reversibility:** Medium. Registry change is gated by version-pinned yaml + git history.

### Stage 3 — Engine composition layer

**Scope:** Conductor resolves `CapabilitySpec → ExecutionDAG`, emits Prefect flow, routes envelopes via Dhara.

**Files (new):**
- `mahavishnu/core/conductor.py` — resolver + planner + emit_flow.
- `mahavishnu/core/envelopes.py` — Dhara-backed transport.
- `mahavishnu/mcp/tools/capability_tools.py` — `execute_capability`, `list_capabilities`, `explain_routing`.

**Files (modified):**
- `mahavishnu/engines/prefect_adapter_impl.py` — accept `ExecutionDAG` as flow definition.
- All engine adapters — `execute()` accepts `CapabilitySpec`.
- `mahavishnu/mcp/tools/profiles.py` — register 18th group `_register_capability_tools`.

**Files (deleted):**
- `mahavishnu/mcp/tools/pool_tools.py:pool_spawn`, `pool_execute`, `pool_route_execute`, `dispatch_to_pool`, `workflow_result`.
- `mahavishnu/mcp/tools/worker_tools.py:worker_spawn`, `worker_execute`, `worker_close`, `worker_health`, `worker_list`.
- `mahavishnu/mcp/tools/workflow_tools.py:trigger_workflow` (the engine-picker variant).
- `mahavishnu/pools/manager.py` if redundant after new dispatcher.

**Exit criteria:** `execute_capability({"requires": ["rag.retrieve", "exec.terminal"]})` runs full DAG via Prefect with envelopes persisted to Dhara. Failure-injection tests pass. All 5 selector strategies covered by unit tests.

**Reversibility:** Hard. Stage 3 deletes MCP tools that production code may call. Coordinate with active deployments.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Prefect upgrade breaks flow emission | Medium | Pin Prefect version; contract test against Prefect's flow API. |
| Envelope schema drift between engines | High | Contract test per engine: `execute()` output must match declared `io_out`. CI guard fails on drift. |
| Capability descriptor rot | High | Pin via `evaluate_all_capabilities()` health check (already exists at `mahavishnu/workers/capabilities/_report.py:78`). |
| LLM selector hallucinating matches | Medium | Always pair `llm_select` with `capability_score` fallback. Log selector decisions for review. |
| Envelope write to Dhara becomes bottleneck | Medium | Dhara writes are async + batched; conductor fans out envelopes, doesn't serialize. |
| Single-source-of-truth failure (yaml corruption) | Low | Bootstrap loads yaml from settings dir; Oneiric caches last-good config. |
| Stage 3 deletes live MCP tools that production code calls | High | Notify deployments; provide one-PR-at-a-time staging. No backward compat = no soft rollout. |

---

## Open Questions

1. **Envelope persistence policy** — Should envelopes be retained indefinitely in Dhara, or TTL'd? Compliance may require TTL on certain content types. *Owner: conductor design.*
2. **Cross-DAG traceability** — When two DAGs share a capability, can they share envelopes? *Decision: no for now; one DAG = one trace_id.*
3. **Affinity semantics** — When two engines tie on capability_score, does `affinity: {repo_role: backend}` count more than `cost_hint`? *Tunable via binding_policy.yaml.*
4. **Prefect as default conductor backend** — what if Prefect itself goes down? Hatchet as fallback? *Defer to a follow-up spec if needed.*

---

## Acceptance Criteria

The spec is complete when:

1. All three stages have independent exit criteria met.
2. `pytest tests/` passes with ≥89% coverage on new code, ≥95% on `mahavishnu/core/conductor.py`.
3. `crackerjack run` passes with no new issues.
4. The 16 original `terminal-*` worker types all spawn functional tmux panes.
5. `execute_capability({"requires": ["rag.retrieve", "exec.terminal"]})` runs end-to-end via Prefect with envelopes persisted to Dhara.
6. `list_capabilities` returns all registered capabilities across engines and workers.
7. `explain_routing` returns a binding plan for a sample spec without executing.
