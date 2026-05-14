# Terminal Worker Unification Plan

**Date:** 2026-05-10
**Status:** `completed`
**Owner:** Core Eng
**Scope:** Mahavishnu terminal workers, registry, adapter selection, CLI/help docs, and tests. This plan does not change provider-default migration scope.
**Purpose:** Reduce terminal-worker branching and normalize all terminal-based AI execution behind a provider-neutral interface so `terminal-*` workers share the same execution protocol and only differ by registry configuration and CLI launcher details.

## 1. Outcome

Mahavishnu should have one terminal-worker story:

1. Terminal workers are provider-neutral execution wrappers.
1. Worker behavior is driven by registry/configuration instead of per-provider branching.
1. `generic_shell.py` becomes the primary shared execution path for terminal-like workers.
1. `terminal.py` only retains behavior that truly cannot be expressed by the shared protocol.
1. Qwen, Claude, Codex, OpenClaw, and future terminal workers all conform to the same lifecycle, completion, and output contract.
1. Docs and tests describe terminal workers as CLI-local execution surfaces, not provider-default surfaces.

## 2. Source Surfaces

Initial implementation surfaces to review:

| Surface | Why it matters |
|---|---|
| `mahavishnu/workers/generic_shell.py` | Existing shared worker path that already handles configurable commands and completion detection. |
| `mahavishnu/workers/terminal.py` | Provider-specific branching currently remains here. |
| `mahavishnu/workers/registry.py` | Defines the terminal worker catalog and command templates. |
| `mahavishnu/core/adapters/worker.py` | Resolves worker types and is where fallback behavior should stay registry-driven. |
| `mahavishnu/pools/base.py` | Defaults and worker selection behavior may reference terminal worker names. |
| `mahavishnu/mcp/tools/*.py` | MCP wrappers expose worker spawn/execution behavior to operators. |
| `docs/README.md`, `docs/GETTING_STARTED.md`, `docs/MCP_TOOLS_REFERENCE.md`, `docs/MCP_TOOLS_SPECIFICATION.md` | Operator-facing descriptions that should stop implying provider-specific terminal workers. |

### T0 Inventory Snapshot

| Bucket | Current examples | Notes |
|---|---|---|
| Shared behavior | session launch, prompt delivery, output capture, completion detection, Session-Buddy result storage | Already partially implemented in `TerminalManager` and `GenericShellWorker` |
| Registry-driven behavior | worker command templates, timeout defaults, terminal-type lookup | Should remain declarative and avoid provider-name branching |
| Provider-specific behavior | `terminal.py` Qwen/Claude command selection, CLI flag differences, stream parsing quirks | Candidate for reduction or removal where a shared template can express the same behavior |
| Supported non-default compatibility | `terminal-qwen` and Qwen-labeled docs | Retain while shared coverage reaches the current callsites |

## 3. Non-Goals

1. Do not change MiniMax, Claude, or other cloud-provider defaults in this plan.
1. Do not delete `terminal-qwen` support until the shared protocol covers every current callsite.
1. Do not add a new cloud-provider-specific terminal worker class.
1. Do not force all terminal execution through the same CLI binary if a worker legitimately needs a different launcher.

## 4. Desired Design

| Concern | Target |
|---|---|
| Shared protocol | One terminal-worker interface for launch, prompt delivery, output capture, and completion detection. |
| Launcher strategy | Registry supplies commands and metadata; worker code should not special-case provider names when a template works. |
| Output parsing | Reuse the generic completion/output parsing path where possible. |
| Worker defaults | Keep `terminal-claude` as the current default until the protocol migration is complete. |
| Non-default support | Retain Qwen as a supported non-default worker until its path can be folded into the shared protocol. |

## 5. Phase Outline

| Phase | Name | Status | Deliverable |
|---|---|---:|---|
| T0 | Inventory and contract review | `completed` | list of current terminal-worker behaviors that are truly shared vs provider-specific |
| T1 | Shared protocol extraction | `completed` | terminal execution contract, completion markers, and launcher abstractions |
| T2 | Worker and registry consolidation | `completed` | reduced branching in `terminal.py` and normalized registry-backed worker creation |
| T3 | Docs and test cleanup | `completed` | operator docs, CLI help, and tests that describe the unified terminal model |
| T4 | Legacy branch retirement | `completed` | remove obsolete provider-specific terminal paths once coverage is complete |

## 6. Initial Acceptance Criteria

- Terminal workers are described as provider-neutral in active docs.
- Shared behavior lives in the generic terminal path whenever possible.
- Registry-driven worker selection no longer requires provider-name branching for normal execution.
- Any retained provider-specific code has an explicit reason and test coverage.

## 7. Validation

- `uv run pytest tests/unit -k "worker or terminal or registry"`
- `uv run ruff check mahavishnu tests`
- `git diff --check`

## 8. Progress Log

Use this log for terminal-unification updates that change the implementation shape.

| Date | Phase | Change | Validation |
|---|---|---|---|
| 2026-05-10 | T0 | Inventory captured for shared behavior, registry-driven behavior, provider-specific behavior, and supported non-default compatibility buckets | `git diff --check` |
| 2026-05-10 | T2 | `TerminalAIWorker` now resolves its launch command from the worker registry instead of hard-coding Qwen/Claude branches | `git diff --check` |
| 2026-05-10 | T2 | Terminal worker tests updated to assert registry-backed command templates; `test_terminal_worker.py` passes | `uv run pytest --no-cov tests/unit/test_terminal_worker.py`, `git diff --check` |
| 2026-05-10 | T2 | Terminal worker metadata now emits `worker_type` / `worker_name` instead of `ai_type` in Session-Buddy and progress payloads | `uv run pytest --no-cov tests/unit/test_terminal_worker.py`, `git diff --check` |
| 2026-05-10 | T2 | Internal terminal worker naming now uses `worker_key` plus a compatibility `ai_type` alias; error messaging is worker-type oriented | `uv run pytest --no-cov tests/unit/test_terminal_worker.py`, `git diff --check` |
| 2026-05-10 | T3 | Active CLI help and operator docs reworded so `terminal-qwen` is clearly supported but non-default in user-facing surfaces | `git diff --check` |
| 2026-05-10 | T2 | Removed the stored `self.ai_type` alias from `TerminalAIWorker`; worker identity now lives in `worker_key`/`worker_name` only | `uv run pytest --no-cov tests/unit/test_terminal_worker.py`, `git diff --check` |
| 2026-05-10 | T3 | Active docs/examples outside the terminal path reworded to describe Qwen as supported non-default compatibility or replace it with MiniMax | `git diff --check` |
| 2026-05-10 | T3 | README and top-level docs index now present `terminal-qwen` and Qwen support as supported non-default compatibility while keeping MiniMax current | `git diff --check` |
| 2026-05-11 | T2/T3 | Inventory reconciled against the codebase: terminal registry-driven execution and docs/help cleanup are complete; only shared protocol extraction and final legacy retirement remain | `git diff --check` |
