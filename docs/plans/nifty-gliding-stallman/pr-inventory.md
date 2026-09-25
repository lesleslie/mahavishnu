# Phase 0 Pre-flight Inventory

**Plan**: `/Users/les/.claude/plans/nifty-gliding-stallman.md` (v3)
**Locked**: 2026-09-25 (Demo Track, Phase 0)
**Branch**: local `main` (Bodai pre-1.0 merge-to-main policy)

---

## Q1 — Duplicate-class sweep (`WorkerResult`, `WorkerConfig`, `TaskResult`)

```text
mahavishnu/adapters/ai/pydantic_ai_adapter.py:268:        >>> class TaskResult(BaseModel):     (docstring example — NOT a real class)
mahavishnu/core/config.py:1552:class WorkerConfig(BaseModel):            (Pydantic config schema — distinct purpose)
mahavishnu/workers/base.py:15:class WorkerResult:                       (the live definition, KEEP)
mahavishnu/workers/registry.py:63:class WorkerConfig:                    (registry dataclass, KEEP — distinct from core/config.py)
```

**Status**: NO action items.
- `TaskResult(BaseModel)` in `pydantic_ai_adapter.py:268` is inside a `>>>` docstring example — false positive.
- `core/config.py:1552 WorkerConfig(BaseModel)` is a Pydantic **config schema** (different from registry.py's **registry dataclass**). Naming collision only; no behavior overlap. OUT OF SCOPE per size/efficiency audit.
- `workers/base.py:15 WorkerResult` is the live one. `workers/registry.py:63 WorkerConfig` is the live one. Phase 5b already verifies the canonicalization of `WorkerStatus` — no parallel action for `WorkerResult`/`WorkerConfig` needed.

---

## Q2 — `_exec_guard.py` callers

```text
mahavishnu/workers/apple_container.py        (DEAD — Phase 4.5b deletes)
mahavishnu/workers/e2b_sandbox.py           (DEAD — Phase 4.5b deletes)
mahavishnu/workers/shepherd_backend.py      (KEEP per user decision)
tests/unit/workers/test_shepherd_backend.py (live test, KEEP)
```

**Decision (locked)**: `_exec_guard.py` is KEEP. After Phase 4.5b deletes `apple_container.py` and `e2b_sandbox.py`, only `shepherd_backend.py` remains as a caller. `_exec_guard.py` lives.

---

## Q3 — 18 test file pre-flight (Phase 4.5b deletion list)

```text
tests/unit/workers/test_a2a_worker.py                  5996 bytes — exists
tests/unit/workers/test_apple_container.py             9727 bytes — exists
tests/unit/workers/test_crow_worker.py                1427 bytes — exists
tests/unit/workers/test_e2b_sandbox.py                8140 bytes — exists
tests/unit/workers/test_acp_emission.py              11813 bytes — exists
tests/unit/workers/test_terminal_claude_completion.py 1908 bytes — exists
tests/unit/test_application_worker.py                32837 bytes — exists
tests/unit/test_pycharm_worker.py                      4970 bytes — exists
tests/unit/test_ollama_worker.py                     61034 bytes — exists
tests/unit/test_openclaw_gateway.py                  26706 bytes — exists
tests/unit/test_generic_shell_worker.py              33808 bytes — exists
tests/unit/test_workers.py                           39384 bytes — exists
tests/unit/test_workers_base.py                       7856 bytes — exists
tests/unit/test_workers_protocol.py                  10250 bytes — exists
tests/unit/test_worker_manager.py                     33925 bytes — exists
tests/unit/test_worker_manager_timeout.py              3969 bytes — exists
tests/unit/test_error_codes.py                        5122 bytes — exists
tests/unit/test_cloud_worker.py                      19533 bytes — exists
```

**All 18 test files exist on disk.** Phase 4.5b's `git rm` batch can proceed.

---

## Q4 — `_main_cli.py` dead-class imports

```text
$ git grep -nE "AppleContainerWorker|ApplicationWorker|CrowWorker|E2BSandboxWorker|GenericShellWorker|HTTPOpenClawGatewayClient|OllamaConfig|OllamaWorker|OpenClawGatewayClient|OpenClawGatewayConfig|OpenClawGatewayWorker|OpenClawTaskRequest|ProgressSnapshot|TerminalWorkerProtocol|is_terminal_worker|A2AWorker|A2AAgentConfig" mahavishnu/_main_cli.py
(no matches)
```

**Correction to v3 plan**: Agent C's inventory cited line numbers (73, 74, 76, 1421, 1438, 1563, 1564, 1570, 1571) for `_main_cli.py`. **Those references are stale.** The current `_main_cli.py` has zero dead-class imports. Phase 4.5b's `_main_cli.py` audit subtask is **dropped** — no work to do there.

---

## Q5 — `StateManager` in `workers/task_router.py`

```text
$ git grep -nE "StateManager" mahavishnu/workers/task_router.py
(no matches)
```

**Decision (locked)**: `StateManager` lives at `mahavishnu/core/task_router.py:565` (per the v3 plan's note). Phase 3b's atomic migration is collision-free.

> **Historical note (2026-09-25)**: `mahavishnu/workers/task_router.py` no longer
> exists — Phase 3b's atomic migration removed it and the file's contents
> moved verbatim to `mahavishnu/core/model_routing.py`. The pre-flight grep
> above is preserved as a record of the original Phase-0 verification; the
> grep would now return "no such file or directory" rather than "(no matches)".

---

## Q6 — `cloud_worker.py` task_router import line

```text
mahavishnu/workers/cloud_worker.py:25: from .task_router import (
```

**Decision (locked)**: Phase 3b must update this line to `from ..core.model_routing import (` — runtime import path.

---

## Q7 — `pool_route_execute` reference enumeration

```text
docs/BUDGET_ENFORCEMENT.md:4,204                        (description — keep but verify wording post-implementation)
docs/POOL_ARCHITECTURE.md:435,456                        (current architecture doc — update if needed)
docs/POOL_MIGRATION.md:465                              (current migration doc — update if needed)
docs/SHEPHERD_BACKEND.md:52,145                         (current operational doc — references the live tool)
docs/WORKFLOW_DIAGRAMS.md:470                           (diagram — keep)
docs/adr/014-honcho-peer-model-routing-precedence.md:36,42,78,86,99,134  (ADR — keep, references the tool)
docs/adr/018-gateway-pattern-evaluation.md:146,269      (ADR — keep)
docs/architecture/MEMORY_ARCHITECTURE.md:58,220,1077,1124,1143,1171   (architecture — references the tool as live)
docs/archive/completion-reports/POOL_IMPLEMENTATION_COMPLETE.md:35   (archive — leave)
docs/archive/guides/MIGRATION_GUIDE_1.md:386           (archive — leave)
docs/archive/implementation-plans/UX_FEEDBACK_IMPLEMENTATION_SUMMARY.md:65  (archive — leave)
docs/archive/migration/POOL_MIGRATION.md:465          (archive — leave)
docs/archive/reports/POOL_ARCHITECTURE.md:474,495      (archive — leave)
docs/archive/sprints-and-fixes/POOL_IMPLEMENTATION_PROGRESS.md:65,218  (archive — leave)
```

**Decision (locked)**: Archive documents (`docs/archive/**`) — leave alone per v3's "Optional polish" decision. Current docs (`docs/adr/`, `docs/architecture/`, `docs/POOL_ARCHITECTURE.md`, `docs/POOL_MIGRATION.md`, `docs/SHEPHERD_BACKEND.md`, `docs/BUDGET_ENFORCEMENT.md`, `docs/WORKFLOW_DIAGRAMS.md`) **already describe the tool as live** — Phase 2m's implementation matches, so no doc edits needed in Demo Track.

---

## Q8 — `pools_enabled` config-gate

```text
mahavishnu/mcp/lifecycle.py:52:        server.app.config, "pools_enabled", True
```

**Decision (locked)**: Phase 1m MUST preserve the `pools_enabled` config-gate as the FIRST check in `init_pool_manager`, before the `try/except`. This keeps the opt-out path unchanged.

---

## Phase 0 Lock Decision

- Q1: PASS (false positive + naming collision out of scope)
- Q2: KEEP `_exec_guard.py`
- Q3: All 18 test files exist → Phase 4.5b deletion batch is safe
- Q4: NO `_main_cli.py` audit needed in Phase 4.5b (correction to v3)
- Q5: StateManager conflict-free
- Q6: cloud_worker.py:25 update required
- Q7: No doc edits required in Demo Track (current docs already align)
- Q8: `pools_enabled` opt-out preserved

**PHASE 0 LOCKED — Demo Track Phase 1m, Phase 2m, and Phase 7 may proceed.**

---

## Memory (for plan execution)

- `feedback-bodai-push-is-user-controlled.md` — never `git push` without explicit approval.
- `feedback-mcp-common-version-bump-is-user.md` — never bump version directly.
- `bodai-pre-1.0-merge-policy.md` — merge directly to main, no PRs.
- `git-author-email-correct-domain.md` — use `les@wedgwoodwebworks.com`.
- `mahavishnu-worktree-precommit-blocks-workers.md` — bypass via `git -c core.hooksPath=/dev/null commit`.
- `feedback-memories-must-be-dual-stored.md` — REQ-016 cross-cutting rule dual-store after Phase 1m merges.
