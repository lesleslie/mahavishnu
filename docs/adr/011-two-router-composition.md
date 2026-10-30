---
status: complete
role: canonical
kind: decision
date: 2026-07-16
last_reviewed: 2026-10-29
superseded_by: null
blocks_on: []
decision_date: 2026-04-26
topic: routing-composition
---

# ADR 011: Two-Router Composition

**Status:** accepted

<!-- legacy status: **Status:** accepted — see YAML frontmatter -->

**Date:** 2026-04-26
**Amended:** 2026-10-29 — MiniMax M2.7/M2.7-highspeed retired from the fallback
chain (upstream retires the M2.x line on 2026-11-18); the latency-sensitive
bucket corrected to `MiniMax-M3.1-Flash`.
**Context:** Bodai I0 boundary hardening

## Decision

Mahavishnu uses two independent routers that compose at task dispatch time:

| Router | File | Concern | Input | Output |
|--------|------|---------|-------|--------|
| **Task Router** | `mahavishnu/core/task_router.py` | Engine selection | `TaskType` enum | Adapter preference order (Prefect, Agno, LlamaIndex) |
| **Model Router** | `mahavishnu/core/model_routing.py` (Phase 3b atomic migration from `mahavishnu/workers/task_router.py`) | Model selection | `TaskCategory` enum | Model ID per provider (llama_server, MiniMax, ZAI compatibility) |

## How They Compose

1. The caller (UnifiedOrchestrator, CLI, or pool) classifies a task as a `TaskType` (e.g., `AI_TASK`, `WORKFLOW`, `RAG_QUERY`).
1. The Task Router resolves the adapter preference order for that `TaskType`.
1. The selected adapter's worker classifies the task prompt as a `TaskCategory` (e.g., `CODE_GENERATION`, `REASONING`).
1. The Model Router maps the `TaskCategory` to a model ID for the worker's provider.

Neither router imports the other. The composition is implicit: the Task Router selects the engine, and the engine's worker selects the model.

## TaskType → Adapter Mapping

| TaskType | First Choice | Fallback |
|----------|-------------|----------|
| `WORKFLOW` | Prefect | Agno → LlamaIndex |
| `AI_TASK` | Agno | Prefect → LlamaIndex |
| `RAG_QUERY` | LlamaIndex | Agno → Prefect |
| `BATCH_TASK` | Prefect | Agno → LlamaIndex |
| `INTERACTIVE_TASK` | Agno | Prefect → LlamaIndex |

## TaskCategory → Model Mapping (MiniMax provider)

The MiniMax routing below mirrors `settings/models.yaml` (provider chain: minimax → llama_server). M3 is the primary for the correctness-sensitive categories — minimax's API does not expose a distinct M3-highspeed variant (verified 2026-09-16; that name returns error 2013). The latency-sensitive bucket moved to M3.1-Flash on 2026-10-19. M2.7/M2.7-highspeed are retired (MiniMax closes them to new users 2026-10-19 and retires them 2026-11-18), so the fallback entries now point at M3 / M3.1-Flash.

| TaskCategory | Cloud Model (MiniMax) | Local Model |
|-------------|-------------|-------------|
| `CODE_GENERATION`, `CODE_REVIEW`, `DEBUGGING`, `REFACTORING`, `TESTING`, `REASONING`, `ANALYSIS`, `DOCUMENTATION`, `VISION`, `ML_INFERENCE` | `MiniMax-M3` | qwen3.5 (llama_server) |
| `SWARM`, `QUICK`, `AGENT_LOOP`, `CREATIVE`, `GENERAL` | `MiniMax-M3.1-Flash` | qwen3.5 (llama_server) |
| `FALLBACK` (any category, when M3 unavailable) | `MiniMax-M3` (identical to the primary — no separate M2.x tier remains; the last resort is the local `llama_server` provider) | qwen3.5 (llama_server) |
| `FALLBACK_HIGHSPEED` (high-volume, when M3 unavailable) | `MiniMax-M3.1-Flash` | qwen3.5 (llama_server) |

## Key Constraints

- TaskType is coarse-grained (5 values). TaskCategory is fine-grained (14 values).
- TaskType is set by the caller. TaskCategory is inferred from the prompt text by regex.
- The Task Router operates at the Mahavishnu orchestration layer. The Model Router operates inside worker implementations.
- Adding a new engine (e.g., Temporal) requires updating the Task Router only. Adding a new model requires updating the Model Router only.
