---
status: active
role: implementation
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-12
superseded_by: null
blocks_on: []
topic: conductor-emit-node-dispatch
title: "Per-Engine emit_node Dispatch Tables for Conductor"
---

# Per-Engine `emit_node` Dispatch Tables for Conductor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `NotImplementedError` in `mahavishnu/core/conductor.py:emit_node` with a per-engine dispatch table covering all five supported `OrchestratorAdapter` engines (Prefect, LlamaIndex, Agno, Hatchet, pydantic_ai). Each dispatch writes a `CapabilityEnvelope` to MCP-backed Dhara storage and returns the `EnvelopeId` so the conductor's flow body can chain nodes with envelopes persisted (the Stage 3a exit criteria on the worker-registry plan, and the per-engine dispatch gap flagged by the v3 reviewer of that plan).

**Architecture:** Two new modules and one extension. The new `mahavishnu/core/conductor_types.py` defines `NodeSpec` (the input contract handed to engines) and `NodeHandle` (the dispatch result — envelope id plus engine status). The new `mahavishnu/engines/emit_node_dispatch.py` holds the five per-engine `async def emit_<engine>_node(...)` implementations, each invoked through a single dispatch table. The existing `mahavishnu/core/conductor.py` is extended: `emit_node` is rewritten from `raise NotImplementedError(...)` to `_EMIT_NODE_DISPATCH[node.engine_id](spec, ...)`. The dispatch key is the `EngineId` declared by the engine adapter (matches the `engine_id` field on `EngineRegistration`, `DAGNode`, and `Candidate`).

**Tech Stack:** Python 3.14 (`X | None`, `list[str]`, msgspec), FastMCP, Pydantic v2 (`frozen=True, extra="forbid"`), the existing `mahavishnu.core.envelopes.CapabilityEnvelope`/`write_envelope` for envelope persistence, the existing `mahavishnu.core.capabilities.EngineId`/`DAGNode` types for the input/output contract, the `OrchestratorAdapter` interface (`async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]`) shared by all five engines, pytest with `@pytest.mark.unit` and `@pytest.mark.integration` markers.

## Why this plan exists

Two plans in `docs/plans/` both flag the same gap:

| Plan | Status | What's blocked |
|---|---|---|
| `docs/plans/2026-08-23-phase3-streaming-tar-plan.md` (active, PARTIAL ~90%) | `emit_node` dispatch tables are explicitly out of scope |
| `docs/plans/2026-08-29-worker-registry-capability-refactor.md` (active, PARTIAL ~85%) | Stage 3a exit criteria require a full DAG run via Prefect with envelopes persisted to Dhara — blocked because `emit_node` raises `NotImplementedError` |

The v3 reviewer note in the worker-registry plan (`Phase 3 — Stage 3a exit criteria`, reviewer #13) is unambiguous: "Per-engine dispatch (`emit_node` raises `NotImplementedError` because the dispatch tables for Prefect/LlamaIndex/Agno/Hatchet/pydantic_ai land outside this plan's scope). Stage 3a exit criteria in the spec say 'runs full DAG via Prefect with envelopes persisted to Dhara'; v3 delivers a **plan-only** Stage 3a. Either land per-engine dispatch in a follow-up plan, or amend the spec's Stage 3a exit criteria."

This plan is the "land per-engine dispatch" path.

## Goals

1. `mahavishnu/core/conductor.py:emit_node` returns an `EnvelopeId` (not a `NotImplementedError`) for the five supported engines.
2. Each per-engine dispatch writes a redacted `CapabilityEnvelope` to Dhara via `mahavishnu.core.envelopes.write_envelope` and returns its `EnvelopeId`.
3. The dispatch is strict-typed (msgspec `Struct` for `NodeSpec`/`NodeHandle`; Pydantic re-use where the conductor already does Pydantic).
4. One unit test per engine + one fallback test for unsupported engine types.
5. `tests/integration/conductor/test_end_to_end_dag.py` can now run a 2-node DAG with a Prefect node + a LlamaIndex node and assert both produced envelopes.

## Non-Goals

1. Changing the conductor's `resolve`/`plan`/`select_candidates`/`emit_flow` surface — they are stable.
2. Adding a new engine — `pydantic_ai` is covered because it's already registered through the `ai` dependency group, but no new engine ships in this plan.
3. Replacing the `MCPAdapter.call_tool("get", ...)` / `mcp.put(...)` envelope transport with anything else — `write_envelope` is reused as-is.
4. Persisting the dispatch result to a real Dhara instance in unit tests — a `FakeMCPClient` is sufficient for the per-engine unit tests; only the existing integration test reaches the real adapter registry.
5. Pool-routing / observability wiring of `emit_node` — the conductor's existing OTel spans in `emit_flow` cover the flow body; `emit_node` is a leaf that returns an id.

## Current Findings

- `mahavishnu/core/conductor.py:152-165` — `emit_node` is a single async function that raises `NotImplementedError("per-engine dispatch lands in Phase 4 — see plan §Open Questions")`. The signature is `async def emit_node(node: DAGNode, *, trace_id: TraceId, mcp: MCPAdapter) -> EnvelopeId`.
- `mahavishnu/core/capabilities.py:31` — `EngineId` is an `Annotated` `str` with the regex `^[a-z][a-z0-9_-]{1,63}$`. `EngineRegistration.engine_id` carries this id; `DAGNode.engine_id` is the same.
- `mahavishnu/core/mcp_adapter.py:82-90` — `MCPClient.put(key, value, ttl=None)` persists bytes via `call_tool("put", arguments)`.
- `mahavishnu/core/envelopes.py:44-48` — `write_envelope(env, *, mcp)` builds the envelope address and calls `mcp.put(addr.to_key(), scrubbed.model_dump_json().encode())`.
- Five engines, all implementing `OrchestratorAdapter`:
  - `mahavishnu/engines/prefect_adapter_impl.py:500 class PrefectAdapter`, `execute` at line 850 — accepts `task: dict[str, Any], repos: list[str]`.
  - `mahavishnu/engines/llamaindex_adapter_impl.py:257 class LlamaIndexAdapter`, `execute` at line 1105 — same signature.
  - `mahavishnu/engines/agno_adapter_impl.py:434 class AgnoAdapter`, `execute` at line 1340 — same signature.
  - `mahavishnu/engines/hatchet_adapter_impl.py:30 class HatchetAdapterImpl`, `execute` at line 122 — same signature.
  - `mahavishnu/adapters/ai/pydantic_ai_adapter.py:226 class PydanticAIAdapter[OutputT: BaseModel]`, `execute` at line 500 — same signature. Loaded lazily via the `ai` PEP 735 dependency group (per CLAUDE.md "Optional Dependency Groups (PEP 735)").
- `mahavishnu/engines/__init__.py:109` — engine registry tuple: `("pydantic_ai", "mahavishnu.adapters.ai.pydantic_ai_adapter", "PydanticAIAdapter", {})`.
- `mahavishnu/mcp/tools/capability_tools.py:357-411` — `execute_capability` MCP tool currently returns `status='planned'` without ever calling `emit_node`; the Phase 4 follow-up is to flip `status='planned'` to `status='queued'` only after `emit_node` returns. This plan does NOT change `execute_capability` directly (Phase 5 below only adjusts the description).
- `tests/integration/conductor/test_end_to_end_dag.py` exists and runs the resolve → plan path; the docstring explicitly says "stops at plan() — exactly the surface the conductor ships with today".
- Coverage floor: `mahavishnu/core/conductor.py` was scoped at 95% in the worker-registry plan (reviewer #13 noted the 95% floor is unreachable while `emit_node` raises); the orchestrator-synthesis plan blocks Stage 3b on `crackerjack run` passing at this floor.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-001
    title: "emit_node dispatches by EngineId and returns an EnvelopeId for the 5 supported engines"
  - id: REQ-002
    title: "Each per-engine dispatch persists a CapabilityEnvelope to Dhara via write_envelope"
  - id: REQ-003
    title: "emit_node raises NotImplementedError ONLY for engine_ids outside the dispatch table"
  - id: REQ-004
    title: "NodeSpec and NodeHandle are msgspec.Struct with strict typing"
  - id: REQ-005
    title: "Per-engine dispatcher unit tests cover all 5 engines + the fallback path"
```

## 5. Implementation Phases

### Phase 1 — Design: `NodeSpec` and `NodeHandle` types

**Goal:** Define the two msgspec structs in a new module so the dispatch table can be strictly typed without leaking engine-specific dictionaries across the conductor.

**Tasks:**

- [ ] **Step 1.1**: Create `mahavishnu/core/conductor_types.py` with `from __future__ import annotations` as the first non-comment line.
- [ ] **Step 1.2**: Define `NodeSpec` as `msgspec.Struct(frozen=True, kw_only=True, eq=False)` with fields:
  - `node_id: str` — copied from `DAGNode.node_id`.
  - `engine_id: EngineId` — copied from `DAGNode.engine_id`.
  - `capability_id: CapabilityId` — copied from `DAGNode.capability_id`.
  - `trace_id: TraceId` — propagated from the flow-level `TraceId`.
  - `prompt: str` — the original `CapabilitySpec.prompt`.
  - `parent_envelope_ids: tuple[EnvelopeId, ...]` — empty for root nodes; populated from upstream `DAGEdge`s in `emit_flow` (Phase 4 hook).
  - `repos: tuple[str, ...]` — for engines that operate on a repo list (Prefect/LlamaIndex/Agno/Hatchet); pydantic_ai may pass `()`.
  - `timeout_seconds: int = 300` — matches `CapabilitySpec.timeout_seconds`.
- [ ] **Step 1.3**: Define `NodeHandle` as `msgspec.Struct(frozen=True, kw_only=True, eq=False)` with fields:
  - `envelope_id: EnvelopeId` — the id of the persisted `CapabilityEnvelope`.
  - `engine_id: EngineId` — echoes the dispatch target.
  - `status: str` — `"completed" | "failed" | "timeout"` mirroring the engine's `execute()` return value.
  - `flow_run_id: str | None = None` — only populated when the engine surfaces one (Prefect `flow_run.id`, Hatchet `run_id`).
  - `error: str | None = None` — populated when `status == "failed"`.
- [ ] **Step 1.4**: Add `__all__ = ["NodeHandle", "NodeSpec"]`.
- [ ] **Step 1.5**: Run `crackerjack run` and confirm the new module compiles clean.

#### Integration Contract ← REQUIRED for this deliverable
- **Triggered from**: import by `mahavishnu/core/conductor.py:emit_node` (Phase 2) and `mahavishnu/engines/emit_node_dispatch.py` (Phase 3).
- **Returns to / updates**: a new module at `mahavishnu/core/conductor_types.py`. No persisted state.
- **Demonstrable by**: `python -c "from mahavishnu.core.conductor_types import NodeSpec, NodeHandle; print(NodeSpec, NodeHandle)"` exits 0 and prints both classes.
- **Rollback signal**: import error in any of the five engine adapters or `crackerjack run` fails type-check on `conductor.py`.
- **Observability added**: none — type-only module.

### Phase 2 — Dispatch table in `mahavishnu/core/conductor.py`

**Goal:** Replace the `NotImplementedError` body with a dispatch lookup keyed by `EngineId`.

**Tasks:**

- [ ] **Step 2.1**: Add imports in `mahavishnu/core/conductor.py` for `NodeSpec`, `NodeHandle`, and the per-engine dispatch module (created in Phase 3).
- [ ] **Step 2.2**: Define a module-level `dict[EngineId, Callable[..., Awaitable[NodeHandle]]]` typed alias `_EmitNodeFn = Callable[[NodeSpec, MCPClient], Awaitable[NodeHandle]]`. Declare `_EMIT_NODE_DISPATCH: dict[EngineId, _EmitNodeFn] = {}` (the dict is populated at import time by `mahavishnu/engines/emit_node_dispatch.py:register()`; the import itself triggers registration via `from ... import _populate`).
- [ ] **Step 2.3**: Rewrite `emit_node`:
  - Build the `NodeSpec` from the `DAGNode` and the kwargs (`trace_id`, `mcp`). For Phase 2 we have no upstream wiring yet, so `parent_envelope_ids=()` and `repos=()`. `prompt` is pulled from a new `_current_prompt: ContextVar[str | None]` set by `emit_flow` before it submits each node (Phase 4 hook). If the contextvar is unset, fall back to `""` and log a one-time warning via `oneiric.logging.get_logger(__name__).warning(...)`.
  - Look up `_EMIT_NODE_DISPATCH.get(node.engine_id)`.
  - If the lookup misses, raise `NotImplementedError(f"per-engine emit_node dispatch not registered for engine_id={node.engine_id!r}")`. The error message is intentionally distinctive so production alerts can grep for it.
  - If found, `await dispatch(spec, mcp)` and return `result.envelope_id`.
- [ ] **Step 2.4**: Update `__all__` to include nothing new (the function name `emit_node` is already exported).
- [ ] **Step 2.5**: Run `pytest tests/unit/core/ -v` — existing tests (none directly test `emit_node` yet, but resolve/plan/select_candidates coverage must hold) must stay green.
- [ ] **Step 2.6**: Run `crackerjack run` to confirm the band-aid doesn't regress the 95% coverage floor on this file (it will drop for now — Phase 5 raises it back).

#### Integration Contract ← REQUIRED for this deliverable
- **Triggered from**: imported by `mahavishnu/mcp/tools/capability_tools.py` via `from mahavishnu.core.conductor import emit_node` (no direct call yet — the MCP tool still returns `planned`; Phase 5 flips the status to `queued` and calls `emit_node`).
- **Returns to / updates**: rewrites `mahavishnu/core/conductor.py:emit_node` from `raise NotImplementedError(...)` to a dict lookup. Persists nothing itself — the engine dispatchers persist the envelope (Phase 3).
- **Demonstrable by**: `python -c "from mahavishnu.core.conductor import emit_node; import inspect; print(inspect.getsource(emit_node))"` shows the new dispatch body, no `raise NotImplementedError`.
- **Rollback signal**: `pytest tests/unit/core/test_conductor_dispatch.py::test_unsupported_engine_raises` fails OR `pytest -k "emit_node"` shows the old error path.
- **Observability added**: a single `oneiric.logging` warning when `_current_prompt` is unset (Phase 4 hook); the lookup-miss `NotImplementedError` is the operator signal.

### Phase 3 — Per-engine dispatch implementations

**Goal:** Implement `emit_prefect_node`, `emit_llamaindex_node`, `emit_agno_node`, `emit_hatchet_node`, `emit_pydanticai_node`. Each one calls the engine's `execute()`, wraps the result in a `NodeHandle`, and persists a `CapabilityEnvelope` to Dhara.

**Tasks:**

- [ ] **Step 3.1**: Create `mahavishnu/engines/emit_node_dispatch.py` with `from __future__ import annotations`. Re-export the five engines under type-only imports (`if TYPE_CHECKING: from mahavishnu.engines.prefect_adapter_impl import PrefectAdapter`, etc.) to keep `pydantic_ai`'s lazy import intact (the `ai` PEP 735 dependency group is optional per CLAUDE.md).
- [ ] **Step 3.2**: Define `_build_envelope(spec: NodeSpec, handle_status: str, io_out: dict[str, str], *, parent_envelope_ids: tuple[EnvelopeId, ...]) -> CapabilityEnvelope` that constructs a `CapabilityEnvelope` with:
  - `envelope_id=EnvelopeId(uuid.uuid4())` (UUID4 per the worker-registry plan ID patterns).
  - `capability_id=spec.capability_id`.
  - `engine_id=spec.engine_id`.
  - `io_out=io_out` (string-only after redaction per `CapabilityEnvelope` model — engines return dicts; the dispatcher coerces each value via `str(v)` if it isn't already a string).
  - `produced_at=datetime.now(UTC)`.
  - `trace_id=spec.trace_id`.
  - `parent_envelope_ids=parent_envelope_ids`.
- [ ] **Step 3.3**: Implement `async def emit_prefect_node(spec: NodeSpec, mcp: MCPAdapter) -> NodeHandle`:
  - Lazily instantiate `PrefectAdapter` from a `_adapter_registry: dict[EngineId, OrchestratorAdapter]` keyed on `EngineId`. The registry is populated by `register()` (see Step 3.7); tests inject a `MagicMock` via the registry.
  - Build the task dict: `{"type": "code_sweep", "id": spec.node_id, "prompt": spec.prompt, "trace_id": str(spec.trace_id), "parent_envelope_ids": [str(p) for p in spec.parent_envelope_ids]}`. `repos` is forwarded verbatim from `spec.repos`.
  - `response = await adapter.execute(task=task, repos=list(spec.repos))`.
  - Build `io_out` from `response.get("results", [])` flattened to a single dict keyed by `f"result_{i}"` (one entry per repo result).
  - `flow_run_id = response.get("flow_run_id")`.
  - Persist via `write_envelope(envelope, mcp=mcp)` and return `NodeHandle(envelope_id=envelope.envelope_id, engine_id=spec.engine_id, status=response.get("status", "failed"), flow_run_id=flow_run_id, error=response.get("error"))`.
  - On exception, return `NodeHandle(envelope_id=EnvelopeId(uuid.uuid4()), engine_id=spec.engine_id, status="failed", error=str(exc))` AFTER writing a `status="failed"` envelope (so the failure is observable via Dhara list).
- [ ] **Step 3.4**: Implement `emit_llamaindex_node`, `emit_agno_node`, `emit_hatchet_node` with the same shape:
  - LlamaIndex — `task_type` defaults to `"ingest"` (matches the engine's existing behavior in `llamaindex_adapter_impl.py:1121`). The dispatcher does NOT special-case `query`; that's a follow-up when `CapabilitySpec` exposes an `io_in` hint. For now, `task = {"type": "ingest", "id": spec.node_id, "params": {"prompt": spec.prompt, "trace_id": str(spec.trace_id)}}`.
  - Agno — `task = {"type": "agent_run", "id": spec.node_id, "prompt": spec.prompt}` (Agno's `execute()` reads `task.get("type")` and falls back to `"default"`).
  - Hatchet — `task = {"prompt": spec.prompt, "workflow_name": spec.capability_id.removeprefix("engine:") or "agent-loop", "timeout": spec.timeout_seconds}` (the engine's `execute()` reads `task.get("workflow_name")` at `hatchet_adapter_impl.py:137`).
- [ ] **Step 3.5**: Implement `emit_pydanticai_node`:
  - Lazy-import `from mahavishnu.adapters.ai.pydantic_ai_adapter import PydanticAIAdapter` inside the function body (NOT at module top) per the `ai` PEP 735 group guidance. If `ImportError` is raised, return `NodeHandle(envelope_id=EnvelopeId(uuid.uuid4()), engine_id=spec.engine_id, status="failed", error="pydantic-ai dependency group not installed; run `uv sync --group ai`")` after writing the failed envelope.
  - `task = {"prompt": spec.prompt, "context": {"trace_id": str(spec.trace_id), "parent_envelope_ids": [str(p) for p in spec.parent_envelope_ids]}}`.
- [ ] **Step 3.6**: Define the dispatch table:
  ```python
  _EMIT_TABLE: dict[EngineId, _EmitNodeFn] = {
      "prefect": emit_prefect_node,
      "llamaindex": emit_llamaindex_node,
      "agno": emit_agno_node,
      "hatchet": emit_hatchet_node,
      "pydantic_ai": emit_pydanticai_node,
  }
  ```
- [ ] **Step 3.7**: Define `register(adapters: dict[EngineId, OrchestratorAdapter]) -> None` that REPLACES the registry used by the five dispatch functions (test seam — production wires real adapters in `mahavishnu/core/app.py:_wire_adapters()`; tests pass mocks). The dispatch functions read from a module-level `_REGISTRY: dict[EngineId, OrchestratorAdapter]` that `register()` populates.
- [ ] **Step 3.8**: Update `mahavishnu/core/app.py:_wire_adapters()` (or whatever the current wiring site is — verify before editing) to call `emit_node_dispatch.register(...)` with the live adapters before the first `emit_node` call lands. If the wiring site doesn't exist yet, log a `WARNING: emit_node dispatch is registered with no live adapters — DAG runs will fail until _wire_adapters is called`.

#### Integration Contract ← REQUIRED for this deliverable
- **Triggered from**: `mahavishnu/core/conductor.py:emit_node` (Phase 2) on every node dispatch.
- **Returns to / updates**: persists a `CapabilityEnvelope` to Dhara via `mahavishnu.core.envelopes.write_envelope` (the address is `envelopes/<trace_id>/<envelope_id>`) and returns the `NodeHandle` to the caller.
- **Demonstrable by**: `python -c "from mahavishnu.engines.emit_node_dispatch import _EMIT_TABLE; print(sorted(_EMIT_TABLE.keys()))"` prints `['agno', 'hatchet', 'llamaindex', 'pydantic_ai', 'prefect']`.
- **Rollback signal**: per-engine error rate >5% in `node.dispatch.failure_total` (added by the worker-registry plan's Stage 3a observability line — if it's not yet wired, use a manual grep for `"per-engine emit_node dispatch"` in MCP logs).
- **Observability added**: each dispatch writes a `CapabilityEnvelope` with `engine_id`, `capability_id`, and `produced_at`. `status="failed"` envelopes are queryable via the `list_envelopes` MCP tool; the existing `mahavishnu.metrics.envelopes` counter (if any — otherwise this is the trigger to add it in the integration tests).

### Phase 4 — Tests: per-engine dispatch

**Goal:** Cover all five engines plus the unsupported-engine fallback.

**Tasks:**

- [ ] **Step 4.1**: Create `tests/unit/core/test_conductor_dispatch.py` with `from __future__ import annotations` as the first non-comment line.
- [ ] **Step 4.2**: Define a `_FakeMCPClient` fixture that implements `put(key, value, ttl=None)` (records to an in-memory `dict[str, bytes]`) and `call_tool(name, arguments)` for `get`/`list_keys` so `envelopes.write_envelope` works without a live MCP server.
- [ ] **Step 4.3**: Define an `_adapter_factory` fixture that returns a `dict[EngineId, MagicMock]` with five mocks — each mock's `.execute = AsyncMock(return_value={"status": "completed", "flow_run_id": "test-123", "results": []})`.
- [ ] **Step 4.4**: Implement `test_emit_prefect_node_returns_handle` (and four siblings for llamaindex, agno, hatchet, pydantic_ai). Each test:
  1. Registers the mocks via `emit_node_dispatch.register(adapters)`.
  2. Builds a `NodeSpec` with `engine_id=<one-of-the-five>`, `prompt="hello"`, `repos=("/tmp/r",)`.
  3. Calls `await emit_node(spec=spec, trace_id=TraceId("0"*32), mcp=fake_mcp)` (or the equivalent direct call to the dispatcher — match the Phase 2 signature).
  4. Asserts the returned `NodeHandle.envelope_id` is a valid `EnvelopeId` and `status == "completed"`.
  5. Asserts `fake_mcp.store` has one key matching `envelopes/<trace_id>/<envelope_id>` and that the value parses as `CapabilityEnvelope`.
- [ ] **Step 4.5**: Implement `test_emit_node_unsupported_engine_raises` — pass a `DAGNode(engine_id="unknown-engine", ...)` and assert `pytest.raises(NotImplementedError, match="per-engine emit_node dispatch not registered for engine_id='unknown-engine'")`.
- [ ] **Step 4.6**: Implement `test_emit_pydantic_ai_node_handles_missing_dep_group` — temporarily patch `mahavishnu.adapters.ai.pydantic_ai_adapter.PydanticAIAdapter` to raise `ImportError`, dispatch a `NodeSpec(engine_id="pydantic_ai", ...)`, and assert the returned `NodeHandle.status == "failed"` with `error` containing the `uv sync --group ai` instruction. Confirm a `failed` envelope is still persisted (so observability is preserved even when the engine is unreachable).
- [ ] **Step 4.7**: Run `pytest tests/unit/core/test_conductor_dispatch.py -v` — all six tests green.
- [ ] **Step 4.8**: Run `pytest tests/unit/core/ -v` — confirm the new file doesn't regress resolve/plan/select_candidates coverage.

#### Integration Contract ← REQUIRED for this deliverable
- **Triggered from**: `pytest tests/unit/core/test_conductor_dispatch.py -v` (developer local + CI).
- **Returns to / updates**: a new test module at `tests/unit/core/test_conductor_dispatch.py`. No persisted state — uses `_FakeMCPClient`.
- **Demonstrable by**: `pytest tests/unit/core/test_conductor_dispatch.py -v --tb=short` shows 6 passed, 0 failed.
- **Rollback signal**: any test in the new module fails for ≥1 commit after merge.
- **Observability added**: test run output is the signal — CI gates the merge.

### Phase 5 — Integration: flip `execute_capability` to call `emit_node`

**Goal:** Make `mahavishnu/mcp/tools/capability_tools.py:execute_capability` actually dispatch the planned DAG (returning `status='queued'` instead of `status='planned'`).

**Tasks:**

- [ ] **Step 5.1**: Read `mahavishnu/mcp/tools/capability_tools.py:357-411` and confirm the current `execute_capability` returns without calling `emit_node`.
- [ ] **Step 5.2**: After `dag = plan(spec, candidates, trace_id=tid)`, iterate `for node in dag.nodes:` and `await emit_node(node=node, trace_id=tid, mcp=mcp_adapter)`. Capture the returned `EnvelopeId` into a list. The `MCPAdapter` instance is fetched from the existing wiring (likely `_settings_getter()` already exposes a connection helper — verify before editing; if none exists, instantiate `MCPAdapter(base_url=settings.mcp_url, timeout=10.0)`).
- [ ] **Step 5.3**: Update the return shape:
  - `status="queued"` on success (was `"planned"`).
  - `envelope_ids: list[str]` — one per node, in DAG order.
  - `nodes`, `edges`, `trace_id`, `error` unchanged.
- [ ] **Step 5.4**: Update the tool description (`@server.tool(description=...)`) from `"Plan and queue an ExecutionDAG (emits the envelopes — dispatch is Phase 4)."` to `"Plan an ExecutionDAG, dispatch each node via its engine, and persist envelopes."`.
- [ ] **Step 5.5**: Extend `tests/integration/conductor/test_end_to_end_dag.py` with a new test `test_execute_capability_runs_two_node_dag`:
  1. Build a `CapabilitySpec` requiring `["engine:durable-flow", "engine:rag-query"]` (or whatever `EngineId`s the test settings register).
  2. Mock all five engines via `emit_node_dispatch.register({...})` with `AsyncMock`s.
  3. Call `execute_capability_for_test(requires=...)` from `_helpers.py`.
  4. Assert `result.status == "queued"`, `len(result.envelope_ids) == 2`, and both engines' mocks had `.execute.assert_awaited_once()`.
- [ ] **Step 5.6**: Run `pytest tests/integration/conductor/ -v` — both old and new tests green.
- [ ] **Step 5.7**: Run `crackerjack run` — the 95% coverage floor on `mahavishnu/core/conductor.py` is now reachable; confirm the gate passes.

#### Integration Contract ← REQUIRED for this deliverable
- **Triggered from**: the `execute_capability` MCP tool, called by any client (operator via CLI, agent via tool-use, integration tests via the shim).
- **Returns to / updates**: persists one `CapabilityEnvelope` per DAG node to Dhara via `write_envelope` (Phase 3 path) AND flips the MCP tool return `status` from `"planned"` to `"queued"`. The tool's documented schema gains `envelope_ids: list[str]`.
- **Demonstrable by**: `pytest tests/integration/conductor/test_end_to_end_dag.py::test_execute_capability_runs_two_node_dag -v` passes.
- **Rollback signal**: `execute_capability` error rate >2% over a 1-hour window (the 1% drop from baseline is the manual signal — wire a real metric in a follow-up).
- **Observability added**: each `execute_capability` call now produces one `CapabilityEnvelope` per node, queryable via `envelopes.list_envelopes(trace_id=tid)`.

## 6. Required Code Changes

- [ ] Create: `mahavishnu/core/conductor_types.py` — NodeSpec, NodeHandle (msgspec.Struct).
- [ ] Modify: `mahavishnu/core/conductor.py` — replace `emit_node` body with dispatch lookup.
- [ ] Create: `mahavishnu/engines/emit_node_dispatch.py` — five engine dispatchers + `_EMIT_TABLE` + `register()`.
- [ ] Modify: `mahavishnu/core/app.py` — wire real adapters into `emit_node_dispatch.register()` at startup (verify the wiring site before editing).
- [ ] Modify: `mahavishnu/mcp/tools/capability_tools.py:357-411` — call `emit_node` after `plan()`, flip `status="planned"` → `"queued"`, surface `envelope_ids`.
- [ ] Create: `tests/unit/core/test_conductor_dispatch.py` — six tests (five engines + unsupported fallback).
- [ ] Modify: `tests/integration/conductor/test_end_to_end_dag.py` — add `test_execute_capability_runs_two_node_dag`.
- [ ] Modify: `docs/plans/PLAN_INDEX.md` — add the new plan row (per `.claude/decisions/plan-index-sync-script.md`).

## 7. Validation Matrix

| Tool / Command | Expected outcome | Evidence location |
|---|---|---|
| `python -c "from mahavishnu.core.conductor_types import NodeSpec, NodeHandle"` | exits 0, prints both classes | shell |
| `python -c "from mahavishnu.engines.emit_node_dispatch import _EMIT_TABLE; print(sorted(_EMIT_TABLE.keys()))"` | prints `['agno', 'hatchet', 'llamaindex', 'pydantic_ai', 'prefect']` | shell |
| `pytest tests/unit/core/test_conductor_dispatch.py -v` | 6 passed | CI / local |
| `pytest tests/integration/conductor/ -v` | all tests passed (old + new 2-node) | CI / local |
| `pytest --cov=mahavishnu/core/conductor.py --cov-report=term` | coverage ≥95% on the conductor module | CI / local |
| `crackerjack run` | passes clean (no new ERROR/WARNING; ty ratchet unchanged) | CI |
| `mcp__mahavishnu__execute_capability` (operator smoke) | returns `status="queued"` with `envelope_ids` populated | operator log |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The `pydantic_ai` dependency group is not installed in CI; the test that exercises the success path fails on a missing import | Medium | The test suite already skips optional groups via `@pytest.mark.ai`; mirror that marker on `test_emit_pydantic_ai_node_returns_handle` |
| The 95% coverage floor on `conductor.py` is unreachable if `_current_prompt` (Phase 4 hook) ends up untested | Low | Phase 5 adds a `test_emit_node_without_prompt_warns` that covers the warning branch; the Phase 2 signature stays minimal until Phase 4 ships |
| Engine `execute()` signatures diverge from the `task` shape the dispatcher builds (e.g. Agno rejects unknown keys) | Medium | Each dispatcher's task dict mirrors the shape used by the engine's existing `_process_single_repo` / `_invoke_client_method` callers; if a key is rejected, the engine returns `status="failed"` with the error — observable via Dhara list |
| The real-adapter wiring site in `app.py` doesn't exist yet, so production `register()` is never called | High | Phase 3 Step 3.8 emits a `WARNING` if no adapters are registered; the rollout is blocked until the wiring site is confirmed |
| Adding `parent_envelope_ids` and `flow_run_id` to `NodeHandle` complicates the `CapabilityEnvelope` schema (extra fields, not extra columns) | Low | Both fields live on `NodeHandle` only; `CapabilityEnvelope` already has `parent_envelope_ids` (capabilities.py:161) — no schema change |

## 9. Decision Rule

The plan is "done enough" when **all** of these hold:

1. `conductor.emit_node(node)` returns a `NodeHandle` for `EngineId in {"prefect", "llamaindex", "agno", "hatchet", "pydantic_ai"}`.
2. `conductor.emit_node(node)` raises `NotImplementedError` ONLY for engine_ids outside that set.
3. `pytest tests/unit/core/test_conductor_dispatch.py` shows 6 passed.
4. `pytest tests/integration/conductor/` shows the old tests + the new 2-node DAG test all passed.
5. `mahavishnu/core/conductor.py` coverage ≥95% per `crackerjack run`.
6. `mcp__mahavishnu__execute_capability` returns `status="queued"` with `envelope_ids` populated when called against a mocked registry.

If scope pressure forces a cut, drop **Phase 5** (the MCP tool flip) — the unit + integration tests still pass and `emit_node` is wired, but the MCP surface keeps `status="planned"`. Do NOT drop **Phase 3** (the per-engine dispatchers); without it, `emit_node` is just a dict lookup that returns nothing.

## Cross-references

- `docs/plans/2026-08-23-phase3-streaming-tar-plan.md` (active) — Phase C/D exit criteria reference the per-engine dispatch tables; this plan closes the gap the streaming-tar plan explicitly deferred.
- `docs/plans/2026-08-29-worker-registry-capability-refactor.md` (active) — Stage 3a exit criteria ("runs full DAG via Prefect with envelopes persisted to Dhara") are now reachable; reviewer #13's flag is closed.
- `mahavishnu/core/conductor.py` — the file modified in Phase 2.
- `mahavishnu/core/capabilities.py` — `EngineId`, `CapabilityId`, `DAGNode`, `CapabilityEnvelope`, `EnvelopeId`, `TraceId`, `TypeSchema`, `CostHint`, `CapabilitySpec`.
- `mahavishnu/core/envelopes.py` — `write_envelope` / `read_envelope` / `list_envelopes` reused as-is.
- `mahavishnu/core/mcp_adapter.py` — `MCPClient.put` is the transport.
- `mahavishnu/engines/{prefect,llamaindex,agno,hatchet}_adapter_impl.py` + `mahavishnu/adapters/ai/pydantic_ai_adapter.py` — the five adapter `execute()` signatures (all `(task: dict[str, Any], repos: list[str]) -> dict[str, Any]`).
- `mahavishnu/mcp/tools/capability_tools.py` — the MCP tool surface flipped in Phase 5.
- `tests/integration/conductor/test_end_to_end_dag.py` — extended in Phase 5 Step 5.5.

## Conventions

- `from __future__ import annotations` as the first non-comment line of every new module.
- Imports sorted within each section (stdlib → third-party → first-party; `force-sort-within-sections = true`, `known-first-party = ["mahavishnu"]`).
- Modern syntax: `X | None`, `list[str]`, `pathlib.Path`.
- No `assert` in production code (`mahavishnu/**`). Use `mahavishnu/core/errors.py`.
- Use the Oneiric logger (`oneiric.logging`) — not stdlib `logging`, not `print()`.
- Commit author: `git -c user.email="les@wedgwoodwebworks.com"` (per `git-author-email-correct-domain.md`).
- Commit trailer: `Co-Authored-By: Claude <noreply@anthropic.com>` (per CLAUDE.md + global instructions).
- Never `git push` for bodai repos — user owns publish (per `feedback-bodai-push-is-user-controlled.md`).
- Merge direct to `main` pre-1.0 (per `bodai-pre-1.0-merge-policy.md`).
- Quality gate: `crackerjack run` must pass.