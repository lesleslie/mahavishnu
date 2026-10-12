---
status: active
role: implementation
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-12
superseded_by: null
blocks_on:
  - docs/plans/2026-10-12-dhara-lock-delete.md
topic: crackerjack-async-durability
title: "C-WIRE Task 6: C-ASYNC-DURABILITY — AsyncTaskManager DharaLock consumer"
---

# C-WIRE Task 6: C-ASYNC-DURABILITY — AsyncTaskManager substrate-agnostic lock consumer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the brittle `asyncio.create_task(self._cleanup_loop())` pattern in `crackerjack/mcp/task_manager.py:37` with substrate-agnostic lock coordination so `task_id → status` is durable across `crackerjack` process restarts, surface the persisted state via a `result_store` MCP tool, and define a `reap_zombies` cron task. This closes C-WIRE Task 6 (`2026-08-03-crackerjack-c-wire-plan.md`).

**Architecture:** Use the canonical `mahavishnu.core._lock_sentinel.Lock` sentinel (in-process dict-backed; per the dhara-lock-delete plan, the substrate-agnostic home) as the coordination primitive. The sentinel exposes `try_acquire(lock_key, owner_token, permanent=True, metadata={"task_id": ..., "status": ...})` + `get(lock_key)` — the exact surface the HypothesisLock use case at `mahavishnu/core/precommitment.py` consumes. The `task_manager.py` rewrite uses the sentinel for the `task_id → status` map; the sentinel is a "register an immutable record keyed by `lock_id`" pattern (per the `_lock_sentinel.py` docstring), not a critical-section lock, which fits the AsyncTaskManager use case exactly.

**Tech Stack:** Python 3.14, asyncio, FastMCP, pytest, `mahavishnu.core._lock_sentinel` (intra-repo dependency — crackerjack imports from mahavishnu via the existing `crackerjack -> mahavishnu` dependency edge; verify the `pyproject.toml` edge first).

## Global Constraints

- `from __future__ import annotations` first non-comment line of every new module.
- Ruff line length 100; per-file ignores in `pyproject.toml` apply unchanged.
- mypy strict; `X | None` (not `Optional[X]`), `list[str]` (not `List[str]`), `pathlib.Path`.
- Function args ≤ 10 (excluding `self`/`cls`/`*args`/`**kwargs`).
- Branches ≤ 15; returns ≤ 6; statements ≤ 55.
- No `assert` in production code (`crackerjack/**`). Use `crackerjack.core.errors` exception hierarchy.
- In `except` blocks, use `logger.exception(...)`, never `logger.error(..., exc_info=True)`.
- Remove unused imports and dead code immediately (Ruff F401 / UP).

## Phase 1 — Pre-flight

- [ ] Verify `crackerjack/pyproject.toml` declares a `mahavishnu >= X.Y.Z` dependency. If not, add it (use the version pin from `mahavishnu/pyproject.toml`).
- [ ] Verify `dhara-lock-delete` plan has landed: `rg -n 'DharaLock' crackerjack/ --type py` should return 0 hits (after the delete plan executes). If still active, BLOCK on that plan.
- [ ] Verify `mahavishnu.core._lock_sentinel.Lock` is importable from crackerjack: `python -c "from mahavishnu.core._lock_sentinel import Lock; print(Lock)"` should succeed in the crackerjack venv.

## Phase 2 — Replace the cleanup loop

- [ ] In `crackerjack/mcp/task_manager.py:37`, replace `self._cleanup_task = asyncio.create_task(self._cleanup_loop())` with a substrate-agnostic initialization that uses the sentinel for `task_id → status` persistence.
- [ ] Define a new `crackerjack/mcp/persistence.py` module that:
  - imports `from mahavishnu.core._lock_sentinel import Lock, LockHandle, LockTimeoutError` (intra-repo dep)
  - exposes `AsyncTaskStore` class with `try_register(task_id, status, permanent=True, metadata=...)` and `get(task_id)` methods
  - holds a module-level `Lock()` instance
  - logs `crackerjack_async_task_registered` (info) and `crackerjack_async_task_lookup_miss` (debug)
- [ ] Refactor `crackerjack/mcp/task_manager.py` to use `AsyncTaskStore` instead of the dict-based `self._tasks` field. Each `register_task` call persists via `try_register` (with `permanent=True`); each `update_task_status` call re-registers with the new status (sentinel semantics: permanent locks are immutable; re-registering with a new status requires `try_release` first, then `try_register`).

## Phase 3 — MCP `result_store` tool

- [ ] In `crackerjack/mcp/tools/async_task_tools.py` (new file), define `result_store(task_id)` FastMCP tool that:
  - Looks up the persisted AsyncTaskStore entry
  - Returns `{"task_id": ..., "status": ..., "registered_at": ..., "metadata": ...}` or `None` if absent
  - Logs `crackerjack_async_task_result_query`
  - Requires no auth gate (read-only)
- [ ] Register the tool in `crackerjack/mcp/tools/profiles.py:REGISTRATION_MAP` under a new `async_task` tool group.
- [ ] Add `crackerjack:read` permission to the tool's required scopes (per `2026-08-03-crackerjack-c-wire-plan.md` Task 4 channel-permission canonicalization).

## Phase 4 — `reap_zombies` cron

- [ ] In `crackerjack/mcp/task_manager.py`, add a `_reap_zombies()` async method that:
  - Scans `AsyncTaskStore.list_keys(prefix="async_task:")` (or equivalent; sentinel exposes `list_keys` per protocol)
  - For any entry with `metadata["registered_at"]` older than 7 days and `metadata["status"]` in `{"pending", "running"}` (zombie states), logs `crackerjack_async_task_zombie_reaped` and removes the entry
- [ ] Add a `crackerjack.async_task.reap_zombies_interval_seconds` setting to `crackerjack/config/settings.py` (default 3600 = 1 hour).
- [ ] Start the reap task in the same lifespan hook that starts the existing cleanup loop.

## Phase 5 — Tests

- [ ] `tests/unit/mcp/test_async_task_persistence.py`:
  - `test_register_persists_via_sentinel` — `AsyncTaskStore.try_register("task-1", "running")` then `get("task-1")` returns the entry
  - `test_register_is_idempotent_via_sentinel_semantics` — second `try_register` for the same task_id raises `LockPermanentError`
  - `test_status_update_requires_release_then_register` — update path: `try_release` then `try_register` with new status
- [ ] `tests/integration/mcp/test_async_task_result_store.py`:
  - `test_result_store_returns_persisted_entry` — register via `AsyncTaskStore`, call `result_store` MCP tool, verify return value
  - `test_result_store_returns_none_for_unknown_task` — call `result_store` with unknown task_id, verify `None`
- [ ] `tests/unit/mcp/test_reap_zombies.py`:
  - `test_reap_zombies_removes_old_pending_entries` — register entry with `registered_at` 8 days ago, run `_reap_zombies()`, verify removal
  - `test_reap_zombies_preserves_recent_entries` — register entry with `registered_at` 1 hour ago, run `_reap_zombies()`, verify preservation

## Phase 6 — Verification

- [ ] `crackerjack run -v` clean
- [ ] Live MCP smoke test: start crackerjack, call `async_task register` + `result_store` + `async_task reaper.status`, verify the persistence is durable across a process restart (kill+restart, query, verify the entry still exists)

## Phase 7 — Commit

- [ ] Single commit on `main` (crackerjack repo) with message: `feat(crackerjack): C-ASYNC-DURABILITY — AsyncTaskManager sentinel consumer (C-WIRE Task 6)`
- [ ] Per `feedback-mcp-common-version-bump-is-user.md`: if `mahavishnu` version bump is needed, the user does it. Do NOT bump the `mahavishnu` version in `crackerjack/pyproject.toml`.
- [ ] Do NOT push. Per `feedback-bodai-push-is-user-controlled.md`, push is the user's call.

## Rollback signal

If Phase 6 verification fails, rollback is `git revert <commit-hash>`. The sentinel semantics (permanent keys, immutable) are strictly safer than the old `asyncio.create_task` pattern, so a regression is unlikely.

## Observability added

- `crackerjack_async_task_registered` (info) — emitted on every successful `try_register`
- `crackerjack_async_task_lookup_miss` (debug) — emitted on `get` returning `None`
- `crackerjack_async_task_zombie_reaped` (warning) — emitted when `_reap_zombies` removes a stale entry
- `crackerjack_async_task_result_query` (info) — emitted on every `result_store` MCP tool call

## Cross-references

- `docs/plans/2026-08-03-crackerjack-c-wire-plan.md` Task 6 (active) — the parent plan this closes
- `docs/plans/2026-10-12-dhara-lock-delete.md` (active) — the precursor plan that retires `DharaLock` so the sentinel is the canonical home
- `mahavishnu/core/_lock_sentinel.py` — the canonical lock primitive (intra-repo dep)
- `dhara/lock/protocol.py:DharaLock` — the retired Protocol (post-delete plan execution)
- `feedback-substrate-compat-shim-rot.md` — the memory rule that motivates using the substrate-agnostic sentinel rather than re-introducing a `Dhara`-named primitive
