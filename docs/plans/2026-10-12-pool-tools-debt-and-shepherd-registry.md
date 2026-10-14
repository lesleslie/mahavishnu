---
status: complete
role: implementation
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-13
superseded_by: null
blocks_on: []
topic: pool-tools-budget-extract
title: "Extract budget_enforce from pool_tools.py to budget_tools.py (Stage 3b unblocker)"
---

# Extract `budget_enforce` from `pool_tools.py` to `budget_tools.py`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unblock `2026-08-29-worker-registry-capability-refactor.md` Stage 3b (delete legacy `pool_tools.py` + `worker_tools.py`) by extracting the `budget_enforce` orchestrator from `pool_tools.py:733-800` into a new `budget_tools.py` MCP tool module. The original draft of this plan also proposed adding a `shepherd` entry to `worker_registry:`, but that registration is a **category error** — `WorkerEntry` (mahavishnu/core/config.py:1698-1734) is a terminal-worker schema, and `ShepherdBackendWorker` is an OS-level syscall-jail backend that `WorkerManager._create_isolated_worker` (manager.py:85-99) already special-cases via constructor kwargs, not via the registry. The shepherd-registration half of the original plan is dropped; only the `budget_enforce` extract remains.

**Architecture:** The extraction is a single-task move. The `budget_enforce` function is a closure inside `register_pool_tools(mcp, pool_manager, ...)` that captures `budget_store` and `pool_manager` from the enclosing scope. The new `budget_tools.py` will host the same logic at module scope with explicit dependency injection via the registrar signature (`register_budget_tools(mcp_app, *, budget_store, pool_manager)`). The function is registered through the crackerjack-style nested group registrar pattern.

**Tech Stack:** Python 3.14, FastMCP, Pydantic v2 (`frozen=True, extra="forbid"`), `crackerjack run -v` gate per project convention.

## Global Constraints

- `from __future__ import annotations` first non-comment line of every new module.
- Ruff line length 100; per-file ignores in `pyproject.toml` apply unchanged.
- mypy strict; `X | None` (not `Optional[X]`), `list[str]` (not `List[str]`), `pathlib.Path`.
- Function args ≤ 10 (excluding `self`/`cls`/`*args`/`**kwargs`).
- Branches ≤ 15; returns ≤ 6; statements ≤ 55.
- No `assert` in production code. Use `mahavishnu/core/errors.py` exception hierarchy.
- In `except` blocks, use `logger.exception(...)`, never `logger.error(..., exc_info=True)`.
- No `Co-Authored-By` trailer in commit message (per `feedback-no-claude-code-coauthor-attribution.md`).
- Use `user.email="les@wedgwoodwebworks.com"` for any commits.

## Why the shepherd registration was dropped

The original draft proposed adding a `shepherd:` entry to `worker_registry:` mirroring the 16 existing `terminal-*` entries. Three structural reasons this is wrong:

1. **`WorkerEntry` schema mismatch** — `WorkerEntry` (mahavishnu/core/config.py:1697-1733) has fields `worker_type`, `command_argv`, `completion_markers`, `provides`, `runtime_kind`, etc. None of `domain`/`key`/`provider`/`factory_path`/`config`/`dependencies`/`capabilities`/`metadata`. `model_config = ConfigDict(extra="forbid")` means a stray field is rejected.
2. **Shepherd is OS-jail, not terminal** — `ShepherdBackendWorker` (shepherd_backend.py) is an OS-level syscall-jail backend with constructor kwargs `writable_root=`, `workspace_cwd=`, `placement=`, `default_timeout=`, `session_buddy_client=` — none of which are `WorkerEntry` fields. The `command_argv` + `completion_markers` shape (the only existing schema) is for interactive shells.
3. **Already handled at manager level** — `_create_isolated_worker` (manager.py:85-99) already special-cases `worker_type == "shepherd"` with explicit kwargs from the caller. The registry is bypassed entirely for shepherd.

The shepherd-backend story does not need a `worker_registry:` entry; the manager hard-codes the dispatch. If a registry-based shepherd registration ever lands, it will need a new `WorkerEntry` schema field (e.g. `factory_kwargs: dict[str, Any]`) AND a registry-driven loader, which is a separate cross-cutting schema change — out of scope for a "Stage 3b unblocker."

## Task 1 — Extract `budget_enforce` to `budget_tools.py`

### Phase 1.1 — Inventory the surface

- [ ] Read `mahavishnu/mcp/tools/pool_tools.py:733-800` to confirm the `budget_enforce` function signature, its dependencies (`BudgetSpec`, `BudgetRecord`, `BudgetStateMachine` from `mahavishnu.core.budget`), the `budget_store` and `pool_manager` captured from the enclosing scope, and any MCP-tool registration glue (line 732 is the `@mcp.tool()` decorator; the function body starts at 733)
- [ ] `rg -n "^async def budget_enforce" mahavishnu/ --type py` to find the function definition only (the loose `budget_enforce` pattern also matches docstring references in `mahavishnu/core/budget.py:7` and `mahavishnu/core/app.py:483`, and in tests — neither are call sites) — expected: `pool_tools.py:733` only
- [ ] `rg -n "from mahavishnu.core.budget import" mahavishnu/mcp/tools/` to confirm the current import path

#### Integration Contract ← REQUIRED
- **Triggered from**: developer / agent reading the current code before extracting.
- **Returns to / updates**: nothing persisted; a documented snapshot of the line range, captured closure, and import path.
- **Demonstrable by**: `sed -n '732,800p' mahavishnu/mcp/tools/pool_tools.py` shows the function body; `rg "budget_enforce" mahavishnu/` returns exactly one hit (the definition).
- **Rollback signal**: not applicable — Phase 1.1 is read-only.
- **Observability added**: none.

### Phase 1.2 — Create `mahavishnu/mcp/tools/budget_tools.py`

- [ ] Create the file with `from __future__ import annotations` as the first non-comment line
- [ ] Move imports verbatim from `pool_tools.py:1-30` (only the lines actually used by `budget_enforce`):
  - `from mahavishnu.core.budget import BudgetSpec, BudgetRecord, BudgetStateMachine` (verify the actual names against `mahavishnu/core/budget.py`)
  - Oneiric logger: `from oneiric.logging import get_logger` (per CLAUDE.md convention)
  - `from mahavishnu.core.errors import MahavishnuError, ErrorCode` (if used in the original)
- [ ] Move the `budget_enforce` function body verbatim from `pool_tools.py:732-800`, keeping the function body identical to the original. The new `register_budget_tools` accepts `budget_store` and `pool_manager` as **explicit registrar parameters** (not module-level globals) — the lambda in `REGISTRATION_MAP` (Phase 1.3) injects them via the `ServerContext`.
- [ ] Define `register_budget_tools(mcp_app, *, budget_store, pool_manager) -> None` — the crackerjack-style nested group registrar. Inside, decorate `async def budget_enforce_tool(...) -> str` with `@mcp_app.tool(name="mahavishnu_budget_enforce")` and have the body call into the underlying `budget_enforce` (the same logic). Return JSON-string envelope consistent with the other tools in the project (see `crackerjack/mcp/tools/execution_tools.py` for the JSON-string convention).
- [ ] Add `__all__ = ["register_budget_tools", "budget_enforce_tool"]`

#### Integration Contract ← REQUIRED
- **Triggered from**: Phase 1.3 (the registration in `profiles.py`).
- **Returns to / updates**: a new file at `mahavishnu/mcp/tools/budget_tools.py` containing the extracted function and the registrar.
- **Demonstrable by**: `python -c "from mahavishnu.mcp.tools.budget_tools import register_budget_tools, budget_enforce_tool; print(register_budget_tools, budget_enforce_tool)"` exits 0 and prints both callables.
- **Rollback signal**: import error in `mahavishnu/mcp/tools/profiles.py` after Phase 1.3; `crackerjack run` fails type-check.
- **Observability added**: `mahavishnu_budget_enforce_invoked` (info) emitted on every successful call (preserved from the original closure).

### Phase 1.3 — Register the new tool in `profiles.py`

- [ ] In `mahavishnu/mcp/tools/profiles.py:REGISTRATION_MAP` (verified at line 188 — it is `dict[str, Callable]` keyed by string registrar-name → lambda; e.g., `"_register_pool_tools": lambda s: _register_pool_tools(s._mhv_server)`), add a new entry matching the **lambda trampoline pattern** the existing entries use:
  ```python
  REGISTRATION_MAP["_register_budget_tools"] = lambda s: _register_budget_tools(
      s._mhv_server, budget_store=s._budget_store, pool_manager=s._pool_manager,
  )
  ```
  The lambda receives a `ServerContext` (or equivalent) and calls the registrar with the dependencies explicit. **Do not** propose a 3-tuple `(key, name, tags)` — that shape doesn't match this map; using it will cause a `TypeError` on first registration.
- [ ] Per the project's wiring discipline, the new registrar is called from the existing wiring site (likely `mahavishnu/core/app.py:_register_tools()` or the equivalent in `server_core.py`); **do not** add a parallel `_OPTIONAL_TOOL_BLOCKS` dict. The crackerjack W2a migration memory rule explicitly notes that the dual-track drift pattern was retired; this is the same convention in mahavishnu.
- [ ] The wiring site must populate `s._budget_store` and `s._pool_manager` on the `ServerContext` before the lambda is invoked. Verify the args are available at that site (look for the existing call to `_register_pool_tools` for the pattern).
- [ ] The new registrar `_register_budget_tools` is added to `STANDARD_REGISTRATIONS` and `FULL_REGISTRATIONS` lists in `mahavishnu/mcp/tools/profiles.py` (the same lists that already contain `_register_pool_tools`).

#### Integration Contract ← REQUIRED
- **Triggered from**: `mahavishnu mcp start` (or the equivalent in `server_core.py`).
- **Returns to / updates**: `mahavishnu_budget_enforce` tool becomes callable through the MCP server; `mcp__mahavishnu__budget_enforce` is now exposed.
- **Demonstrable by**: `mahavishnu mcp start` + `mcp__mahavishnu__budget_enforce(...)` (or the equivalent) returns a JSON envelope.
- **Rollback signal**: server fails to start with a `TypeError` from the lambda (catches the case where the `ServerContext` doesn't expose the deps); `REGISTRATION_MAP` has a key without a matching registrar; `crackerjack run` flags a profile-gate violation.
- **Observability added**: `mahavishnu_budget_enforce_registered` (info) emitted at server startup when the registrar is invoked.

### Phase 1.4 — Remove the old surface from `pool_tools.py`

- [ ] Delete `pool_tools.py:732-800` (the `budget_enforce` function body)
- [ ] Delete the now-unused imports in `pool_tools.py` (verify with `rg -n "from mahavishnu.core.budget" pool_tools.py` should return 0 hits)
- [ ] Delete the now-unused `budget_store` and `pool_manager` capture from the enclosing `register_pool_tools` function (if they were only used by `budget_enforce`)
- [ ] Verify `crackerjack run -v` is clean (or at minimum `ruff check` + `mypy --strict` on the touched files)

#### Integration Contract ← REQUIRED
- **Triggered from**: `crackerjack run` gate.
- **Returns to / updates**: `pool_tools.py` no longer contains `budget_enforce`; the only owner is `budget_tools.py`.
- **Demonstrable by**: `rg -n "budget_enforce" mahavishnu/mcp/tools/pool_tools.py` returns 0 hits; `rg -n "budget_enforce" mahavishnu/` returns exactly 1 hit (`budget_tools.py`).
- **Rollback signal**: `rg "budget_enforce" pool_tools.py` returns hits after this phase; `crackerjack run` flags an unused import.
- **Observability added**: none (pure deletion).

### Phase 1.5 — Tests

- [ ] `tests/unit/mcp/tools/test_budget_tools.py` (new file):
  - `test_budget_enforce_tool_returns_envelope_id` — call `register_budget_tools` with a `_FakeBudgetStore` and a `_FakePoolManager`, then call `budget_enforce_tool(...)` and assert the response is a JSON-string envelope containing the envelope_id
  - `test_budget_enforce_tool_handles_invalid_spec` — call with a malformed `BudgetSpec` (e.g. empty `workflow_id`) and assert the tool returns an error envelope, not a Python exception
  - `test_budget_enforce_tool_persists_via_envelopes` — verify the `CapabilityEnvelope` is written to the substrate (the existing persistence mechanism for the M-* plans via `mcp.put` + `EnvelopeAddress`)
- [ ] Run `pytest tests/unit/mcp/tools/test_budget_tools.py -v --no-cov` and confirm 3/3 pass
- [ ] Per the project's MCP wiring discipline (`docs/decisions/mcp-backend-wiring-discipline.md`), also add `tests/integration/test_budget_enforce_e2e.py`: spin up the server, wait for warmup, call `mcp__mahavishnu__budget_enforce`, assert non-empty response.

#### Integration Contract ← REQUIRED
- **Triggered from**: `pytest tests/unit/mcp/tools/test_budget_tools.py -v` (developer local + CI).
- **Returns to / updates**: 3 unit tests + 1 e2e integration test for the new tool.
- **Demonstrable by**: `pytest tests/unit/mcp/tools/test_budget_tools.py tests/integration/test_budget_enforce_e2e.py -v --tb=short` shows 4 passed, 0 failed.
- **Rollback signal**: any test fails for ≥1 commit after merge.
- **Observability added**: e2e smoke test result is the CI gate signal.

## Phase 2 — Verification gate

- [ ] `crackerjack run -v` clean
- [ ] Live smoke test: start the MCP server, call `mcp__mahavishnu__budget_enforce` via the new tool, verify the envelope was persisted
- [ ] `rg -n "budget_enforce" mahavishnu/mcp/tools/pool_tools.py` returns 0 hits
- [ ] `rg -n "from mahavishnu.core.budget" mahavishnu/mcp/tools/pool_tools.py` returns 0 hits

## Phase 3 — Unblock check

After Task 1 lands, the `2026-08-29-worker-registry-capability-refactor.md` Stage 3b prerequisites are satisfied for the `pool_tools.py` side:

- `budget_enforce` is no longer in `pool_tools.py:732-800` (Task 1 ✓)
- The MCP-tool surface that depends on `budget_enforce` now lives in `budget_tools.py` (Task 1 ✓)
- Stage 3b can proceed to delete `pool_tools.py` + `worker_tools.py` (the worker-registry plan author should verify the other Stage 3b prerequisites before that delete lands — out of scope for this carve-out)

After this plan lands, the next concrete action is to update the worker-registry plan's `blocks_on` to `[]` and execute Stage 3b. That work belongs in a follow-up worktree + crackerjack gate; it is out of scope for this carve-out.

## Phase 4 — Commit

- [ ] Single commit on `main` (mahavishnu repo) with message: `feat(mahavishnu): pool_tools budget_enforce extract (Stage 3b unblocker)`
- [ ] Use `git -c user.email="les@wedgwoodwebworks.com" commit ...` (per `git-author-email-correct-domain.md`)
- [ ] Do NOT add `Co-Authored-By` trailer (per `feedback-no-claude-code-coauthor-attribution.md`)
- [ ] Do NOT push (per `feedback-bodai-push-is-user-controlled.md`)

## Rollback signal

If Phase 2 verification fails:
- Revert the commit (`git revert <commit-hash>`)
- The old `budget_enforce` is restored in `pool_tools.py:732-800`
- The new `budget_tools.py` is removed
- Stage 3b is blocked again — the user decides whether to retry or activate the synthesis plan

## Observability added

- `mahavishnu_budget_enforce_invoked` (info) — emitted on every successful `budget_enforce_tool` call (preserved from the original)
- `mahavishnu_budget_envelope_persisted` (info) — emitted when the envelope is written
- `mahavishnu_budget_enforce_failed` (warning) — emitted on a malformed-spec error path
- `mahavishnu_budget_enforce_registered` (info) — emitted at server startup when the registrar runs

## Cross-references

- `docs/plans/2026-08-29-worker-registry-capability-refactor.md` (active) — Stage 3b unblocks after this lands (for the `pool_tools.py` side; the worker-registry plan's other Stage 3b prerequisites are separate)
- `mahavishnu/mcp/tools/pool_tools.py:732-800` — the `budget_enforce` source to extract
- `mahavishnu/core/budget.py` — the `BudgetSpec`/`BudgetRecord`/`BudgetStateMachine` primitives
- `mahavishnu/workers/shepherd_backend.py` — referenced for **why the shepherd registration was dropped**; the dispatch lives in `WorkerManager._create_isolated_worker` (manager.py:85-99), not in the registry
- `mahavishnu/core/config.py:1698-1734` — the actual `WorkerEntry` Pydantic schema (terminal-style fields only; shepherd is OS-jail and doesn't fit)
- `crackerjack/mcp/tools/execution_tools.py:10` — the crackerjack-style nested group registrar pattern this plan mirrors
- `feedback-bodai-push-is-user-controlled.md` — push policy
- `feedback-no-claude-code-coauthor-attribution.md` — commit message policy
- `git-author-email-correct-domain.md` — author email policy
