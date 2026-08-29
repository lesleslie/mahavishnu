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
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from pydantic import BaseModel, ConfigDict, Field

# ─── ID newtypes (pattern-enforced via Pydantic Field) ───────────────────────
# Replaces plain `str` IDs that were untyped and unenforced.

CapabilityId = Annotated[str, Field(pattern=r"^[a-z]+:[a-z0-9._-]+$")]
"""Format: `kind:name` (e.g. `engine:prefect`, `worker:claude-tui`)."""

EngineId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")]
EnvelopeId = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
TraceId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


# ─── Enums ──────────────────────────────────────────────────────────────────

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
    INTERACTIVE = "interactive"  # Added per architecture-council H4 — interactive tmux workers


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"


class SelectorStrategy(StrEnum):
    """Pluggable selector strategies. See Section 3."""
    LEAST_LOADED = "least_loaded"
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    AFFINITY = "affinity"
    PEER_AFFINITY = "peer_affinity"
    CAPABILITY_SCORE = "capability_score"
    LLM_SELECT = "llm_select"


# ─── Core schemas ───────────────────────────────────────────────────────────

class TypeSchema(BaseModel):
    """Typed I/O contract for a capability.

    `fields` MUST be a valid JSON Schema dict (validated at registration
    via `jsonschema.Draft202012Validator.check_schema()`). Runtime envelope
    writes validate payload against `fields` via `TypeAdapter(fields).validate_python(value)`.
    """
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, Any] = Field(default_factory=dict)

    def matches(self, other: "TypeSchema") -> bool:
        """Structural subtyping: True if `other.fields` validates against self.fields."""


class CostHint(BaseModel):
    """Best-effort cost/latency profile for routing decisions."""
    model_config = ConfigDict(extra="forbid")
    latency_p50_ms: int | None = None
    latency_p99_ms: int | None = None
    tokens_per_call: int | None = None
    has_side_effects: bool = False


class HealthRef(BaseModel):
    """Point-in-time health check for a capability implementation."""
    model_config = ConfigDict(extra="forbid")
    last_check_at: datetime | None = None  # Was `str` — switched to AwareDatetime per python-pro H2
    last_status: HealthStatus | None = None
    check_url: str | None = None


class Capability(BaseModel):
    """A single capability that can be required or provided."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: CapabilityId
    kind: CapabilityKind
    description: str
    io_in: TypeSchema
    io_out: TypeSchema
    state: CapabilityState
    idempotency_key: str | None = None
    cost_hint: CostHint = Field(default_factory=CostHint)
    health: HealthRef = Field(default_factory=HealthRef)
    tags: list[str] = Field(default_factory=list)
    undo: CapabilityId | None = None  # Was `str | None` — typed per python-pro M2
    deprecated_after: datetime | None = None  # Per orchestration L3 — capability rotation


class EngineRegistration(BaseModel):
    """An engine's capability surface."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    engine_id: EngineId
    provides: list[Capability]
    consumes: list[CapabilityId] = Field(default_factory=list)  # Was `list[Capability]` — typed IDs prevent cyclic refs
    affinity: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class CapabilityEnvelope(BaseModel):
    """Typed, serializable record handed between engines.

    `io_out` is validated at write against the producing capability's `io_out: TypeSchema`.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")
    envelope_id: EnvelopeId
    capability_id: CapabilityId
    engine_id: EngineId
    io_out: dict[str, Any]  # Validated against Capability.io_out at write time
    produced_at: datetime
    trace_id: TraceId
    parent_envelope_ids: list[EnvelopeId] = Field(default_factory=list)


class EnvelopeAddress(BaseModel):
    """Typed Dhara storage address. Replaces magic-string path `envelopes/{trace_id}/{envelope_id}`."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    trace_id: TraceId
    envelope_id: EnvelopeId

    def to_key(self) -> str:
        return f"envelopes/{self.trace_id}/{self.envelope_id}"

    @classmethod
    def from_key(cls, key: str) -> "EnvelopeAddress":
        prefix = "envelopes/"
        if not key.startswith(prefix):
            raise ValueError(f"Invalid envelope key: {key!r}")
        parts = key[len(prefix):].split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid envelope key: {key!r}")
        return cls(trace_id=parts[0], envelope_id=parts[1])


# ─── DAG + resolver types (previously referenced but undefined) ────────────

class Candidate(BaseModel):
    """Resolver output: one engine candidate for a required capability."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    engine_id: EngineId
    capability_id: CapabilityId
    score: float = Field(ge=0.0, le=1.0)
    reason: str


class DAGNode(BaseModel):
    """One node in an ExecutionDAG — a single engine invocation."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str
    engine_id: EngineId
    capability_id: CapabilityId
    inputs: TypeSchema
    outputs: TypeSchema


class DAGEdge(BaseModel):
    """Dependency edge: `from_node.outputs[field_path]` → `to_node.inputs`."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    from_node: str
    to_node: str
    field_path: str


class ExecutionDAG(BaseModel):
    """Compiled binding plan: nodes + edges + trace_id. Immutable post-`plan()`."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    nodes: tuple[DAGNode, ...]
    edges: tuple[DAGEdge, ...]
    trace_id: TraceId


class CapabilitySpec(BaseModel):
    """User-facing spec passed to `execute_capability`. Runtime tool-input model.

    Distinct from `Capability` (which is the registration-time declaration). The spec
    is what the caller wants; the capability is what an engine provides.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")
    requires: list[CapabilityId]
    prompt: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    repos: list[str] = Field(default_factory=list)
    timeout: int = 300
    selector: SelectorStrategy = SelectorStrategy.CAPABILITY_SCORE
    trace_id: TraceId | None = None
    idempotency_key: str | None = None
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

**Scope:** Fix the broken worker launch path traced through two cooperating sites. `WorkerManager` constructs the argv; `tmux_adapter.create_session` passes it to tmux. Both must change together.

**Call chain (per `mahavishnu-specialist` review C1 + `feature-dev:code-architect` review H1):**

1. `WorkerManager.create_worker()` reads `WorkerConfig.command` (a pre-quoted shell string like `sh -lc 'claude --output-format stream-json --permission-mode acceptEdits'`) and constructs `command=[WorkerConfig.command]` — a one-element argv containing the entire pre-quoted string.
2. `tmux_adapter.create_session()` (`mahavishnu/workers/contract/tmux_adapter.py:112`) does `quoted = shlex.join(command)` on that list, producing doubly-quoted output like `'sh -lc '"'"'claude ...'"'"''`.
3. The doubly-quoted text is `send-keys`'d into a fresh zsh pane via `tmux send-keys -t pane -- '<quoted>' Enter` (line 152).
4. zsh parses the entire doubly-quoted string as one literal token and rejects it with `command not found`.

**Fix:** Pass the command string directly to `tmux new-session`'s positional command argument (after `--`), not via `send-keys`. The exact diff:

```python
# mahavishnu/workers/contract/tmux_adapter.py — replace the create_session body
quoted = shlex.join(command)  # DELETE this line
proc = subprocess.run(
    ["tmux", "-S", socket, "new-session", "-d",
     "-s", session, "-n", window_name,
     "-P", "-F", "#{session_name}:#{window_id}:#{pane_id}",
     "--"] + list(command),  # ADD `--` then the argv
    check=False, capture_output=True, text=True,
)
# DELETE the send-keys block (current lines 152)
```

WorkerManager's argv construction stays as-is. tmux's `--` separates tmux options from the command, so the shell-quoted string passes through to the pane's initial process intact.

**Files (multi-file fix):**
- `mahavishnu/workers/contract/tmux_adapter.py` — apply the diff above; delete lines 144-152 (send-keys + chmod tail).
- `tests/unit/workers/contract/test_tmux_adapter.py:46,62,85` — three unit tests assert the old `send-keys` invocation. Update to assert the new `new-session -- <command>` shape.

**Exit criteria:** All 16 `terminal-*` worker types spawn functional tmux panes. Smoke test: `pool_spawn --worker-type terminal-claude` produces a pane with `claude --output-format stream-json --permission-mode acceptEdits` running, not `zsh: command not found`.

**Reversibility:** Trivial. Revert the two-file change.

### Stage 2 — Capability-driven registry

**Scope:** Replace static registry with capability-driven registry. Workers and engines share one capability vocabulary.

**Files (new):**
- `mahavishnu/core/capabilities.py` — schema definitions (Capability, CapabilitySpec, ExecutionDAG, etc.).
- `WorkerRegistryConfig` Pydantic model added to `MahavishnuSettings` in `mahavishnu/core/config.py` — typed surface for the `workers:` config block.

**Files (modified):**
- `settings/mahavishnu.yaml` — add `workers:` block under existing config (per `oneiric-specialist` review C1: do **NOT** create a separate `settings/workers.yaml` — that bypasses `_settings_build_values` ordering and silently breaks `MAHAVISHNU_WORKERS__FOO` env-var overrides).
- `mahavishnu/core/bootstrap.py` — load worker registry via existing `oneiric.core.config.load_settings()` (not a new bootstrap path; `oneiric` already supports XDG layering at `~/.config/mahavishnu/workers.yaml`).
- All `mahavishnu/engines/*_adapter_impl.py` — declare `provides: list[Capability]`.

**Files (deleted):**
- `mahavishnu/workers/registry.py:WORKER_REGISTRY` (literal registry, replaced by Oneiric-loaded `WorkerRegistryConfig`).
- `mahavishnu/terminal/config.py` adapter references.

**Exit criteria:** Same `pool_spawn --worker-type terminal-claude` works. New: `pool_spawn --worker-type <yaml-only-name>` works. Each worker's `provides` are discoverable via `list_capabilities(domain="worker")`.

**Reversibility:** Medium. Registry change is gated by version-pinned yaml + git history.

### Stage 3 — Engine composition layer

**Scope:** Conductor + composition layer + envelope transport. Per the "no alias shims, no hard cutover" decision, this stage splits into additive (3a, ships new tools alongside existing ones) and deletive (3b, removes old tools after one release cycle of dual maintenance). No silent deletions; every removed tool has a documented migration path.

#### Stage 3a — Additive composition (no deletions)

**Scope:** Add `execute_capability`, `list_capabilities`, `explain_routing`, plus conductor + envelope transport. Existing tools untouched.

**Files (new):**
- `mahavishnu/core/conductor.py` — resolver + planner + emit_flow.
- `mahavishnu/core/envelopes.py` — Dhara-backed transport via `EnvelopeAddress.to_key()`.
- `mahavishnu/mcp/tools/capability_tools.py` — `execute_capability`, `list_capabilities`, `explain_routing`.
- `mahavishnu/mcp/tools/get_capability_result_tool.py` — async read-back (`get_capability_result(trace_id=...)`) per `mcp-integration-expert` H1; replaces deleted `workflow_result`.

**Files (modified):**
- `mahavishnu/engines/prefect_adapter_impl.py` — accept `ExecutionDAG` as flow definition.
- All engine adapters — `execute()` accepts `CapabilitySpec`.
- `mahavishnu/mcp/tools/profiles.py` — register 18th group `_register_capability_tools` in `STANDARD_REGISTRATIONS` (per `mcp-integration-expert` M1: capability dispatch is daily-dev primitive, not FULL-only).

**Pre-conditions for shipping 3a:**
- All slash-command skills migrated: `.claude/skills/mahavishnu/SKILL.md`, `.claude/skills/mahavishnu-status/SKILL.md` (per `mcp-integration-expert` C1).
- Orchestrator subagent `.claude/agents/mahavishnu-orchestrator.md` `tools:` frontmatter updated.
- `/vishnu` skill description updated.
- All `tests/unit/test_*pool*` and `test_*worker*` updated to use new tools.
- CLI subcommands `_main_cli.py:1402,1469,1781` migrated to call `execute_capability` underneath (CLI surface preserved).

**Exit criteria:** New tools work alongside existing tools. `execute_capability({"requires": ["rag.retrieve", "exec.terminal"]})` runs full DAG via Prefect with envelopes persisted to Dhara. Old `pool_*`, `worker_*`, `trigger_workflow` tools still work.

**Reversibility:** Easy. New tools can be hidden via `MAHAVISHNU_TOOL_PROFILE=standard` (or removed entirely) without breaking old paths.

#### Stage 3b — Deletive cleanup

**Scope:** Remove old MCP tools after one release cycle of dual maintenance. This is the only step that deletes anything.

**Pre-conditions (must all be true before 3b ships):**
- 3a has been in production for ≥1 release cycle.
- Slash commands / orchestrator subagent / `/vishnu` skill verified using new tools.
- `MAHAVISHNU_LEGACY_TOOLS=true` env var honored by old tools for one final release (logs warning on every call).
- Run `python scripts/audit_orphans.py` — zero callers of deleted tools.

**Files (deleted):**
- `mahavishnu/mcp/tools/pool_tools.py:pool_spawn`, `pool_execute`, `pool_route_execute`, `dispatch_to_pool`, `workflow_result`.
- `mahavishnu/mcp/tools/worker_tools.py:worker_spawn`, `worker_execute`, `worker_close`, `worker_health`, `worker_list`.
- `mahavishnu/mcp/server_core.py:272` — `trigger_workflow` (registered inline here, NOT in `workflow_tools.py` per `mcp-integration-expert` C2).
- `mahavishnu/pools/manager.py` if redundant after new dispatcher.

**Files (preserved — operator-observability subset):**
- `pool_list`, `pool_health`, `pool_monitor`, `pool_scale`, `pool_close`, `pool_close_all`, `pool_search_memory` — operator surfaces not duplicated by `execute_capability`.

**Exit criteria:** All pool/worker dispatch tools except the observability subset are deleted. `trigger_workflow` is gone. `MAHAVISHNU_LEGACY_TOOLS=true` no longer recognized.

**Reversibility:** Hard. Stage 3b is the only irreversible step in the entire refactor. Coordinate with active deployments.

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
