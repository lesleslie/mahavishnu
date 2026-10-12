---
status: active
role: implementation
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-12
superseded_by: null
blocks_on: []
supersedes_part_of: docs/plans/2026-08-29-orchestrator-research-synthesis.md
topic: pool-tools-debt-shepherd-registry
title: "Carve-out: pool_tools.py budget_enforce extract + shepherd worker_registry entry"
---

# Carve-out: pool_tools.py budget_enforce extract + shepherd worker_registry entry

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unblock `2026-08-29-worker-registry-capability-refactor.md` Stage 3b (delete legacy `pool_tools.py` + `worker_tools.py`) by extracting the `budget_enforce` orchestrator from `pool_tools.py:720-790` into a new `budget_tools.py` MCP tool module, and add the missing `shepherd` entry to `settings/mahavishnu.yaml:459-588` (the `worker_registry:` block). This is a 2-task carve-out that resolves the dependency without activating the still-`draft` synthesis plan (per the cluster-4 coupling analysis, 2026-10-12).

**Architecture:** The 2 tasks are independent. Task 1 extracts an in-process MCP tool definition; Task 2 adds a config-only YAML entry. Both are mechanically reversible.

**Tech Stack:** Python 3.14, FastMCP, msgspec, Pydantic, `pyyaml` (already a dep), `crackerjack run -v` gate per project convention.

## Global Constraints

- `from __future__ import annotations` first non-comment line of every new module.
- Ruff line length 100; per-file ignores in `pyproject.toml` apply unchanged.
- mypy strict; `X | None` (not `Optional[X]`), `list[str]` (not `List[str]``), `pathlib.Path`.
- Function args ≤ 10 (excluding `self`/`cls`/`*args`/`**kwargs`).
- Branches ≤ 15; returns ≤ 6; statements ≤ 55.
- No `assert` in production code. Use `mahavishnu/core/errors.py` exception hierarchy.
- In `except` blocks, use `logger.exception(...)`, never `logger.error(..., exc_info=True)`.
- No `Co-Authored-By` trailer in commit message (per `feedback-no-claude-code-coauthor-attribution.md`).
- Use `user.email="les@wedgwoodwebworks.com"` for any commits.

## Task 1 — Extract `budget_enforce` to `budget_tools.py`

### Phase 1.1 — Inventory the surface
- [ ] Read `mahavishnu/mcp/tools/pool_tools.py:720-790` to confirm the `budget_enforce` function signature, its dependencies (BudgetSpec, BudgetRecord, BudgetStateMachine from `mahavishnu.core.budget`), and any MCP-tool registration glue
- [ ] `rg -n "budget_enforce" mahavishnu/ --type py` to find all call sites — expected: `pool_tools.py:733` only, plus any tests
- [ ] `rg -n "from .budget import\|from .budget_tools" mahavishnu/mcp/tools/` to confirm no existing import path conflicts

### Phase 1.2 — Create `mahavishnu/mcp/tools/budget_tools.py`
- [ ] Create the file with `from __future__ import annotations`
- [ ] Import the budget primitives: `from mahavishnu.core.budget import BudgetSpec, BudgetRecord, BudgetStateMachine` (verify these names against `mahavishnu/core/budget.py`)
- [ ] Move the `budget_enforce` function body (with docstring, type hints, and error handling) verbatim from `pool_tools.py:733`
- [ ] Define `async def budget_enforce_tool(...)` wrapper that handles the FastMCP tool surface (path normalization, JSON-encoding for the response, structured logging)
- [ ] Export: `__all__ = ["budget_enforce_tool"]`

### Phase 1.3 — Register the new tool
- [ ] In `mahavishnu/mcp/tools/profiles.py:REGISTRATION_MAP` (or equivalent), add a new entry: `("budget_enforce", "_register_budget_tools", ["budget", "enforcement"])`
- [ ] In `mahavishnu/mcp/tools/profiles.py:_register_budget_tools` (new function), call `mcp.tool()(budget_enforce_tool)` to register the new tool

### Phase 1.4 — Remove the old surface from `pool_tools.py`
- [ ] Delete `pool_tools.py:720-790` (the `budget_enforce` function body)
- [ ] Delete any imports in `pool_tools.py` that are no longer used after the removal (verify with `rg -n "from .budget import" pool_tools.py` should return 0 hits)
- [ ] Verify `crackerjack run -v` (or at minimum `ruff check` + `mypy --strict` on the touched files) is clean

### Phase 1.5 — Tests
- [ ] `tests/unit/mcp/tools/test_budget_tools.py` (new file)
  - `test_budget_enforce_tool_returns_envelope_id` — call the tool with a sample BudgetSpec, assert the response includes the envelope_id
  - `test_budget_enforce_tool_handles_invalid_spec` — call with a malformed BudgetSpec, assert the tool returns an error envelope (not a Python exception)
  - `test_budget_enforce_tool_persists_via_envelopes` — verify the `CapabilityEnvelope` is written to `~/.mahavishnu/envelopes/` (or wherever the envelope substrate lives)
- [ ] Run `pytest tests/unit/mcp/tools/test_budget_tools.py -v --no-cov` and confirm 3/3 pass

## Task 2 — Add `shepherd` entry to `worker_registry:`

### Phase 2.1 — Inventory existing entries
- [ ] Read `settings/mahavishnu.yaml:459-588` (the `worker_registry:` block) to confirm the schema of an existing entry (e.g. pick the last entry as a template)
- [ ] Verify the schema fields against `mahavishnu/core/capabilities.py:WorkerEntry` (or equivalent Pydantic model)

### Phase 2.2 — Verify the `shepherd` adapter is registered in code
- [ ] `rg -n "shepherd_backend" mahavishnu/workers/` to confirm `mahavishnu/workers/shepherd_backend.py` exists and is dispatchable
- [ ] `rg -n "shepherd" mahavishnu/workers/manager.py` to confirm `WorkerManager` has a `worker_type="shepherd"` dispatch path
- [ ] `rg -n "shepherd" mahavishnu/pyproject.toml` to confirm the `shepherd` PEP 735 dep group exists

### Phase 2.3 — Add the YAML entry
- [ ] Add a `shepherd:` entry to `worker_registry:` mirroring the existing 16 entries. Required fields (verify against `WorkerEntry` Pydantic model):
  - `domain: worker`
  - `key: shepherd`
  - `provider: mahavishnu`
  - `version: 0.1.0`
  - `factory_path: mahavishnu.workers.shepherd_backend:ShepherdWorker`
  - `config: {}` (no special config; shepherd uses defaults)
  - `dependencies: []`
  - `capabilities: ["isolated_execution", "session_durable", "tmux_backend"]` (verify against `shepherd_backend.py` actual capability set)
  - `metadata: {}`
- [ ] Validate the YAML syntactically: `.venv/bin/python -c "import yaml; yaml.safe_load(open('settings/mahavishnu.yaml'))"` must succeed
- [ ] Verify the entry is recognized: `.venv/bin/python -c "from mahavishnu.core.capabilities import load_capabilities_from_settings; cs = load_capabilities_from_settings(); print([e.key for e in cs if e.key == 'shepherd'])"` must output `['shepherd']`

### Phase 2.4 — Tests
- [ ] `tests/unit/core/test_capabilities_loader_shepherd.py` (new file)
  - `test_shepherd_entry_loads_from_settings` — load `settings/mahavishnu.yaml`, assert a `shepherd` WorkerEntry is present
  - `test_shepherd_entry_has_required_capabilities` — assert `capabilities` is non-empty
  - `test_shepherd_entry_factory_path_resolves` — import the factory path, assert it's a callable class

## Phase 3 — Verification gate

- [ ] `crackerjack run -v` clean
- [ ] Live smoke test: start the MCP server, call `budget_enforce` via the new tool, verify the envelope was persisted
- [ ] `rg -n "budget_enforce" mahavishnu/mcp/tools/pool_tools.py` should return 0 hits
- [ ] `rg -n "shepherd" settings/mahavishnu.yaml` should return at least 1 hit (the new entry)

## Phase 4 — Unblock check

After Task 1 + Task 2 land, the `2026-08-29-worker-registry-capability-refactor.md` Stage 3b prerequisites are satisfied:
- `budget_enforce` is no longer in `pool_tools.py:720-790` (Task 1 ✓)
- `shepherd` is registered in `worker_registry:` (Task 2 ✓)
- Plan A Stage 3b can proceed to delete `pool_tools.py` + `worker_tools.py` without losing functionality

After this plan lands, the next concrete action is to update Plan A's `blocks_on` to `[]` and execute Stage 3b. That work belongs in a follow-up worktree + crackerjack gate; it is out of scope for this carve-out.

## Phase 5 — Commit

- [ ] Single commit on `main` (mahavishnu repo) with message: `feat(mahavishnu): pool_tools budget_enforce extract + shepherd worker_registry entry (Stage 3b unblocker)`
- [ ] Use `git -c user.email="les@wedgwoodwebworks.com" commit ...` (per `git-author-email-correct-domain.md`)
- [ ] Do NOT add `Co-Authored-By` trailer (per `feedback-no-claude-code-coauthor-attribution.md`)
- [ ] Do NOT push (per `feedback-bodai-push-is-user-controlled.md`)

## Rollback signal

If Phase 3 verification fails:
- Revert the commit (`git revert <commit-hash>`)
- The old `budget_enforce` is restored in `pool_tools.py:720-790`
- The new `shepherd` YAML entry is removed
- Plan A Stage 3b is blocked again — the user decides whether to retry or activate the synthesis plan

## Observability added

- `mahavishnu_budget_enforce_invoked` (info) — emitted on every successful `budget_enforce_tool` call
- `mahavishnu_budget_envelope_persisted` (info) — emitted when the envelope is written
- `mahavishnu_budget_enforce_failed` (warning) — emitted on a malformed-spec error path

## Cross-references

- `docs/plans/2026-08-29-worker-registry-capability-refactor.md` (active) — Stage 3b unblocks after this lands
- `docs/plans/2026-08-29-orchestrator-research-synthesis.md` (draft) — this plan carves out Phases 3 + 4
- `mahavishnu/mcp/tools/pool_tools.py:720-790` — the budget_enforce source to extract
- `mahavishnu/core/budget.py` — the BudgetSpec/BudgetRecord/BudgetStateMachine primitives
- `mahavishnu/workers/shepherd_backend.py` — the shepherd worker backend to register
- `settings/mahavishnu.yaml:459-588` — the worker_registry block to extend
- `feedback-bodai-push-is-user-controlled.md` — push policy
- `feedback-no-claude-code-coauthor-attribution.md` — commit message policy
- `git-author-email-correct-domain.md` — author email policy
