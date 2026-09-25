---
name: cloud-worker-retirement-decision
status: complete
date: 2026-09-25
last_reviewed: 2026-09-25
owner: mahavishnu
role: decision
plan: .claude/plans/nifty-gliding-stallman.md v3 §10 follow-up #3
triggered_by: User direction post §10 follow-up batch ship
related: docs/decisions/2026-09-24-legacy-worker-deprecation.md; docs/feature-tracking/2026-09-06-orphan-sweep.md; docs/feature-tracking/2026-09-25-pool-worker-mcp-audit.md; commit 24ff5f2d (Phase 3b atomic migration)
progress: "Decision recorded: KEEP. No code changes required. Docstring in cloud_worker.py is already accurate (references core.model_routing, not the deleted task_router)."
---

# CloudWorker Retirement Decision (Plan §10 #3)

## State — complete

- [x] Audit callers complete (no internal callers in `mahavishnu/` or `tests/`)
- [x] Decision recorded: **KEEP**
- [x] Docstring accuracy verified (already references post-Phase-3b `core.model_routing`)
- [x] No code changes required

## Audit findings

CloudWorker lives at `mahavishnu/workers/cloud_worker.py` and is exported via
`mahavishnu/workers/__init__.py:32` as `CloudWorker, CloudWorkerConfig`. After
Phase 3b's atomic migration of routing primitives to `core/model_routing.py`
(commit `24ff5f2d`), the worker is a thin wrapper around:

- `mcp_common.llm.FallbackChain` — three-tier provider dispatch
  (MiniMax → llama-server → Ollama)
- `core/model_routing.py::classify_task()` + `TaskCategory` enum +
  `DEFAULT_MINIMAX_ROUTING` / `DEFAULT_OLLAMA_ROUTING` /
  `DEFAULT_LLAMA_SERVER_ROUTING`

### Callers in `mahavishnu/` (verified 2026-09-25)

```
$ git grep -nE "from mahavishnu\.workers\.cloud_worker|import.*cloud_worker|CloudWorker|CloudWorkerConfig" mahavishnu/ tests/
mahavishnu/core/model_routing.py:4:   # doc comment: "so that both OllamaWorker and CloudWorker can share the same routing."
mahavishnu/core/model_routing.py:249: # doc comment: "final fallback in CloudWorkerConfig.model."
mahavishnu/workers/__init__.py:32:    # export statement
mahavishnu/workers/__init__.py:56:    # __all__ listing
```

**Zero production or test imports** of CloudWorker outside the file itself
and its package export.

### Doc references (live)

- `docs/VISUAL_GUIDE.md` — architecture diagram
- `docs/feature-tracking/2026-09-06-orphan-sweep.md` — wiring tracker
- `docs/plans/2026-09-12-finish-partial-implementations.md` — partial-implementations tracker
- `docs/plans/PLAN_INDEX.md` — plan registry

Plus 3 archived (`docs/superpowers/...`).

## Decision: **KEEP**

The cost of retiring CloudWorker exceeds the benefit, on five counts:

1. **External API surface**: exported via `workers/__init__.py` — external
   consumers (downstream Bodai repos, Akosha/Crackerjack MCP integrations,
   in-house tooling that imports `from mahavishnu.workers import CloudWorker`)
   may depend on the symbol. Removing the export breaks them silently with
   no compile-time signal at the package boundary.

2. **Documentation contract**: `CLAUDE.md` documents CloudWorker as "the
   OpenAI-compatible cloud worker with MiniMax primary defaults." Retiring
   requires CLAUDE.md update plus the 4 live doc references above.

3. **It's not broken**: the code works today. Phase 3b moved routing
   primitives, but the worker still serves as the wrapper that turns
   `core.model_routing.TaskCategory` into a `mcp_common.llm.LLMSettings` +
   `FallbackChain` call.

4. **Retirement cost > benefit** (concrete list):
   - Find external callers (out-of-repo audit needed — unverifiable
     from this codebase)
   - Update 4 live doc references + `CLAUDE.md`
   - Risk breaking external integrations with no compile-time error
   - Risk losing the wrapper contract — every consumer would need to
     reimplement the `TaskCategory → LLMSettings → FallbackChain` glue

5. **The wrapper has value**: it provides the integration point between
   `core.model_routing.TaskCategory` enum values and
   `mcp_common.llm.LLMSettings` + `FallbackChain` calls. The wrapper
   centralizes retry, circuit-breaking, and fail-closed auth in one place.
   Removing it means every consumer has to write that glue code themselves.

## Docstring verification

The `cloud_worker.py` module docstring (lines 1-7) is already accurate
post-Phase-3b:

```python
"""Cloud AI worker — three-tier FallbackChain (MiniMax → llama-server → Ollama).

Delegates all LLM dispatch to mcp_common.llm.FallbackChain, which handles
per-provider retry, circuit breaking, and fail-closed auth checks.
Intelligent task classification via classify_task() feeds the task_type
field so each provider selects the right model from its routing table.
"""
```

Imports at lines 26-34 confirm the docstring's claim — they pull
`classify_task`, `routing_to_task_map`, `DEFAULT_*_ROUTING` from
`..core.model_routing`, not from the deleted `..workers.task_router`.
No docstring update needed.

## Open work (not pursued)

- **Out-of-repo caller audit**: before any future retirement, audit
  downstream Bodai repos (Akosha, Crackerjack, Session-Buddy,
  bodai-crow) for `from mahavishnu.workers import CloudWorker` usage.
  Not blocking; revisit if user signals retirement interest.
- **Deprecation shim**: not added. Adding `DeprecationWarning` on a
  public symbol with no internal callers is premature — external impact
  unverifiable, and no consumer has asked for the migration.
- **`workers/cloud_worker.py` thin-wrapper doc update**: not needed;
  the existing docstring is accurate.

## References

- `commit 24ff5f2d` — Phase 3b atomic migration of routing primitives
  to `core/model_routing.py`
- `docs/feature-tracking/2026-09-06-orphan-sweep.md` — CloudWorker wired
  status (line 37)
- `commit ca1cad18` — §10 audit batch, lists this as parked open work
- `CLAUDE.md:726` — documents CloudWorker in the workers section
- `mahavishnu/workers/__init__.py:32` — public export
