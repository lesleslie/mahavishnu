---
status: complete
role: implementation
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-13
superseded_by: null
blocks_on: []
topic: crackerjack-async-durability
title: "C-WIRE Task 6: C-ASYNC-DURABILITY — AsyncTaskManager SQLite-backed persistence"
---

# C-WIRE Task 6: C-ASYNC-DURABILITY — AsyncTaskManager SQLite-Backed Persistence

> **For agentic workers:** REQUIRED SUB-KILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Wire `AsyncTaskManager` into the crackerjack MCP server startup (it is currently defined but only instantiated in tests, leaving the entire class orphaned); (2) replace the in-memory dict-based state in `crackerjack/mcp/task_manager.py` with SQLite-backed persistence so `task_id → status` survives `crackerjack` process restarts; (3) surface the persisted state via a `result_store` MCP tool; (4) define a `reap_zombies` cron task. Closes C-WIRE Task 6 (`2026-08-03-crackerjack-c-wire-plan.md`).

**Why the orphan must be wired first:** Verified 2026-10-12 via `rg -n "AsyncTaskManager()" /Users/les/Projects/crackerjack/ --type py`: the class is defined at `crackerjack/mcp/task_manager.py:26` but only instantiated in `tests/mcp/test_task_manager.py:61` (a test file). It is never wired into production. Without Phase 0, the `result_store` MCP tool would return an empty envelope on every call, the `reap_zombies` cron would find zero rows, and the "kill-restart-query" smoke test would always succeed vacuously (because nothing was inserted to begin with). The re-review (mcp-integration-expert + env-auditor) caught this in the second pass.

**Architecture:** Use stdlib `sqlite3` (no new dependencies) for persistent state at `~/.crackerjack/state/async_tasks.db`. Define `AsyncTaskStore` with `register(task_id, status, metadata) -> None`, `get(task_id) -> AsyncTaskRecord | None`, `list_keys(prefix: str) -> list[str]`, and `update_status(task_id, new_status) -> None`. Schema: one row per `task_id`; columns `task_id` (PRIMARY KEY), `status`, `registered_at` (ISO8601), `metadata_json` (JSON-encoded dict). The store is process-shared (single-writer via SQLite's built-in locking; the manager is async so all writes go through `loop.run_in_executor` or `aiosqlite` — verify which the project uses). The original draft proposed routing through `mahavishnu.core._lock_sentinel.Lock`, but the sentinel is explicitly an in-process dict (per its docstring at lines 7-32) and cannot satisfy the "durable across restart" goal. SQLite is the right primitive here.

**Why the sentinel was rejected:** `mahavishnu/core/_lock_sentinel.py` is a "register an immutable record keyed by `lock_id`" witness pattern, with only `try_acquire` and `get` exposed. The docstring explicitly defers `try_release`, `list_keys`, and cross-process persistence ("If a future caller needs them, extend the surface here… If cross-process persistence is required in the future, this sentinel would need a SQL/DuckDB backend; that's a larger refactor and out of scope here."). This plan is exactly that "larger refactor" — but at the AsyncTaskStore level, not the sentinel level. The sentinel stays as-is for the HypothesisLock use case (`mahavishnu/core/precommitment.py`); the AsyncTaskStore uses SQLite directly.

**Tech Stack:** Python 3.14, asyncio, stdlib `sqlite3`, FastMCP (crackerjack-style nested group registrar), pytest, Pydantic v2 for the `AsyncTaskRecord` model.

## Global Constraints

- `from __future__ import annotations` first non-comment line of every new module.
- Ruff line length 100; per-file ignores in `pyproject.toml` apply unchanged.
- mypy strict; `X | None` (not `Optional[X]`), `list[str]` (not `List[str]`), `pathlib.Path`.
- Function args ≤ 10 (excluding `self`/`cls`/`*args`/`**kwargs`).
- Branches ≤ 15; returns ≤ 6; statements ≤ 55.
- No `assert` in production code (`crackerjack/**`). Use `crackerjack.core.errors` exception hierarchy.
- In `except` blocks, use `logger.exception(...)`, never `logger.error(..., exc_info=True)`.
- Remove unused imports and dead code immediately (Ruff F401 / UP).
- No `Co-Authored-By` trailer in commit message (per `feedback-no-claude-code-coauthor-attribution.md`).
- Use `user.email="les@wedgwoodwebworks.com"` for any commits.

## Phase 0 — Wire `AsyncTaskManager` into the crackerjack MCP server startup

- [ ] Read `crackerjack/mcp/server_core.py` (or whichever file owns the server-lifecycle wiring) and confirm the current `create_mcp_server` flow does NOT construct an `AsyncTaskManager`. Capture the exact construction site.
- [ ] Add an `AsyncTaskManager` instance to the server lifecycle: construct it at server startup, hold it on the `ServerContext` (or equivalent), and call `await manager.start()` in the lifespan startup. Hold a reference so the `result_store` MCP tool can reach it.
- [ ] Verify the wiring with `rg -n "AsyncTaskManager()" /Users/les/Projects/crackerjack/crackerjack/mcp/ --type py` returns ≥1 hit (in production code, not just tests). The `tests/mcp/test_task_manager.py:61` hit must remain.
- [ ] Run the existing test suite to confirm the wiring doesn't break the unit tests that exercise the in-memory path. Add a new test `tests/integration/test_async_task_manager_wired.py` that asserts the manager is constructed in the server's lifespan context.

#### Integration Contract ← REQUIRED
- **Triggered from**: server startup (`crackerjack mcp start`).
- **Returns to / updates**: `AsyncTaskManager` is now a real, instantiated component in the server lifecycle. Subsequent phases (SQLite store, `result_store` tool, `reap_zombies` cron) have something to read from.
- **Demonstrable by**: `rg -n "AsyncTaskManager()" crackerjack/mcp/ --type py` returns ≥1 production hit; the new integration test passes.
- **Rollback signal**: server fails to start (the new wiring raises during lifespan); `crackerjack run` test suite fails.
- **Observability added**: `crackerjack_async_task_manager_constructed` (info) at server startup.

## Phase 1 — Pre-flight: Pydantic settings + storage path

- [ ] Add a new Pydantic class `AsyncTaskSettings` to `crackerjack/config/settings.py`:
  ```python
  class AsyncTaskSettings(OneiricMCPConfig):
      """AsyncTaskManager persistence settings (C-WIRE Task 6)."""
      storage_path: Path = Field(
          default_factory=lambda: Path("~/.crackerjack/state/async_tasks.db").expanduser(),
          description="SQLite database file for AsyncTaskStore",
      )
      reap_zombies_interval_seconds: int = Field(
          default=3600,
          ge=60,
          le=86400,
          description="How often to reap zombie tasks (60s-24h)",
      )
      zombie_age_seconds: int = Field(
          default=604800,  # 7 days
          ge=3600,
          le=2592000,
          description="Tasks with registered_at older than this AND status in {pending, running} are reaped",
      )
  ```
  Add `async_task: AsyncTaskSettings = Field(default_factory=AsyncTaskSettings)` to `CrackerjackSettings`. Mirror the same block to `settings/crackerjack.yaml` (no new env-var keys — the SQLite path lives in YAML so operators can change it without code).
- [ ] Verify the `settings/` YAML loader accepts the new `async_task:` block (the test in Phase 5 will catch a regression).
- [ ] Verify the existing `crackerjack/mcp/task_manager.py:37` is the only site in that file using `asyncio.create_task(self._cleanup_loop())`: `rg -n "_cleanup_loop" crackerjack/mcp/task_manager.py` should return exactly one hit (line 37). NOTE: `crackerjack/mcp/rate_limiter.py:286` also uses this pattern (with its own `_cleanup_loop` at line 315) — that file is out of scope for this plan.

#### Integration Contract ← REQUIRED
- **Triggered from**: developer / agent reading the existing code before extraction.
- **Returns to / updates**: a new Pydantic class `AsyncTaskSettings` in `crackerjack/config/settings.py`; a `async_task:` block in `settings/crackerjack.yaml`; nothing persisted yet.
- **Demonstrable by**: `python -c "from crackerjack.config.settings import AsyncTaskSettings; s = AsyncTaskSettings(); print(s.storage_path, s.reap_zombies_interval_seconds, s.zombie_age_seconds)"` exits 0 and prints sane defaults.
- **Rollback signal**: import error on `from crackerjack.config.settings import AsyncTaskSettings`; `crackerjack run` fails type-check.
- **Observability added**: none.

## Phase 2 — SQLite-backed `AsyncTaskStore`

- [ ] Create `crackerjack/mcp/persistence.py` with `from __future__ import annotations` as the first non-comment line.
- [ ] Define `AsyncTaskRecord` as a Pydantic v2 `BaseModel` with `model_config = ConfigDict(frozen=True, extra="forbid")`:
  - `task_id: str` (PRIMARY KEY in the SQL table; not a Pydantic newtype, since async task ids are operator-supplied UUIDs or short strings)
  - `status: str` (one of `"pending" | "running" | "completed" | "failed" | "timeout"`)
  - `registered_at: datetime` (UTC)
  - `metadata: dict[str, Any] = Field(default_factory=dict)`
- [ ] Define `AsyncTaskStore` with constructor `(self, db_path: Path) -> None`. On init, run the schema migration in `loop.run_in_executor`:
  ```sql
  CREATE TABLE IF NOT EXISTS async_tasks (
      task_id TEXT PRIMARY KEY,
      status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed', 'timeout')),
      registered_at TEXT NOT NULL,  -- ISO8601 UTC
      metadata_json TEXT NOT NULL DEFAULT '{}'
  );
  CREATE INDEX IF NOT EXISTS idx_async_tasks_status ON async_tasks(status);
  CREATE INDEX IF NOT EXISTS idx_async_tasks_registered_at ON async_tasks(registered_at);
  ```
- [ ] Implement `register(self, task_id, status, metadata=None) -> AsyncTaskRecord` — `INSERT OR REPLACE` (the SQLite UPSERT) so the same `task_id` can be re-registered with a new status without an explicit release step. Returns the new row.
- [ ] Implement `get(self, task_id) -> AsyncTaskRecord | None` — `SELECT … WHERE task_id = ?`.
- [ ] In `__init__`, call `self._db_path.parent.mkdir(parents=True, exist_ok=True)` to create `~/.crackerjack/state/` on first use (the existing `sql:` block in `settings/crackerjack.yaml:7` already uses this dir).
- [ ] Implement `list_keys(self, prefix: str = "") -> list[str]` — `SELECT task_id FROM async_tasks WHERE task_id LIKE ?` (prefix concatenated with `%`); returns sorted list.
- [ ] Implement `update_status(self, task_id, new_status) -> None` — `UPDATE async_tasks SET status = ? WHERE task_id = ?`; raises `KeyError` if no row matched.
- [ ] Implement `delete(self, task_id) -> bool` — `DELETE … WHERE task_id = ?`; returns True if a row was removed.
- [ ] All DB access goes through `loop.run_in_executor(None, …)` (or `aiosqlite` if the project already uses it — verify by reading `crackerjack/mcp/task_manager.py` and adjacent files). No synchronous sqlite3 calls inside async functions.
- [ ] Add `__all__ = ["AsyncTaskRecord", "AsyncTaskStore"]`.

#### Integration Contract ← REQUIRED
- **Triggered from**: `AsyncTaskManager.__init__` (Phase 3).
- **Returns to / updates**: a new file at `crackerjack/mcp/persistence.py` with the `AsyncTaskStore` and `AsyncTaskRecord`.
- **Demonstrable by**: `python -c "from crackerjack.mcp.persistence import AsyncTaskRecord, AsyncTaskStore; print(AsyncTaskRecord, AsyncTaskStore)"` exits 0; the unit test in Phase 5 demonstrates round-trip durability across `AsyncTaskStore` instances (close + reopen the same db_path, verify `get` still returns the record).
- **Rollback signal**: any unit test in Phase 5 fails.
- **Observability added**: `crackerjack_async_task_registered` (info) on `register`; `crackerjack_async_task_lookup_miss` (debug) on `get` returning `None`; `crackerjack_async_task_status_updated` (info) on `update_status`.

## Phase 3 — `AsyncTaskManager` rewrite

- [ ] In `crackerjack/mcp/task_manager.py`, replace the `asyncio.create_task(self._cleanup_loop())` start with a call to `AsyncTaskStore(settings.async_task.storage_path)` (instantiated at `__init__`, using the same `settings` object the manager already receives). The store is a `self._store: AsyncTaskStore` attribute.
- [ ] Rewrite `register_task(self, task_id, status, metadata=None) -> AsyncTaskRecord` to call `self._store.register(task_id, status, metadata)` and return the result. The existing `dict`-based `self._tasks` field is removed.
- [ ] Rewrite `update_task_status(self, task_id, new_status) -> None` to call `self._store.update_status(task_id, new_status)`. The "release then re-register" dance from the original draft is gone — SQLite `INSERT OR REPLACE` handles re-registration atomically, and `update_status` is the explicit "status changed" path.
- [ ] Rewrite `get_task(self, task_id) -> AsyncTaskRecord | None` to call `self._store.get(task_id)`.
- [ ] Wire the existing `start()` method to launch the `reap_zombies` cron (Phase 4) alongside the existing cleanup loop; the cleanup loop's dict-based iteration is replaced with `self._store.list_keys()` and `self._store.get(task_id)` reads.

#### Integration Contract ← REQUIRED
- **Triggered from**: `AsyncTaskManager.start()` (called by the existing wiring site at server startup).
- **Returns to / updates**: `crackerjack/mcp/task_manager.py` no longer uses `asyncio.create_task` for the cleanup loop body; the new `AsyncTaskStore` is the single source of truth.
- **Demonstrable by**: `python -c "from crackerjack.mcp.task_manager import AsyncTaskManager; m = AsyncTaskManager.__new__(AsyncTaskManager); print(hasattr(m, '_store'))"` after a successful start; the e2e test in Phase 5 demonstrates cross-restart durability.
- **Rollback signal**: import error; the cleanup loop fails to iterate; `crackerjack run` fails type-check.
- **Observability added**: `crackerjack_async_task_manager_started` (info) at start; `crackerjack_async_task_manager_stopped` (info) at stop.

## Phase 4 — `result_store` MCP tool (crackerjack-style nested registrar)

- [ ] Create `crackerjack/mcp/tools/async_task_tools.py` with `from __future__ import annotations` as the first non-comment line.
- [ ] Define `register_async_task_tools(mcp_app, *, task_manager) -> None` (crackerjack nested group registrar pattern, matching `crackerjack/mcp/tools/execution_tools.py:10`). Inside, define the single tool:
  ```python
  @mcp_app.tool(name="crackerjack_result_store")
  async def result_store(task_id: str) -> str:
      """Look up a persisted async task record by id.

      Returns a JSON envelope:
          {"found": true, "task": {...}} on hit
          {"found": false, "task_id": "..."} on miss
      """
      ...
  ```
  The return type is a Pydantic model serialized as JSON, not `None` (the original draft's `Optional[dict]` would serialize awkwardly per the MCP review). Wrap in `{"found": bool, "task": dict | None}` so consumers handle one shape.
- [ ] Wire `result_store` to call `task_manager.get_task(task_id)` and serialize the result. Log `crackerjack_async_task_result_query` on every call.
- [ ] Do **NOT** add a `crackerjack:read` permission scope to the tool — the project has no such convention (verified: no `:read` / `:write` / `permission` string in `crackerjack/mcp/`). The tool is read-only by signature and the server's auth layer (if any) governs access at the request level.
- [ ] Add `"async_task_tools"` to the `STANDARD_REGISTRATIONS` (and thus `FULL_REGISTRATIONS`) list in `crackerjack/mcp/tools/profiles.py`. The `MINIMAL` profile is intentionally excluded — operators running in MINIMAL don't need the result surface.
- [ ] Wire the registrar into the existing wiring site (the one that calls `register_execution_tools(mcp_app, …)` — find the exact call site by reading `crackerjack/mcp/server_core.py` or equivalent). Pass the same `task_manager` instance.

#### Integration Contract ← REQUIRED
- **Triggered from**: `crackerjack mcp start` (the wiring site invokes the registrar at startup).
- **Returns to / updates**: `crackerjack_result_store` becomes callable through the MCP server; exposed as `mcp__crackerjack__result_store`.
- **Demonstrable by**: `mcp__crackerjack__result_store(task_id="...")` returns a JSON envelope; the e2e test in Phase 5 demonstrates end-to-end discoverability.
- **Rollback signal**: server fails to start; `register_async_task_tools` is called but `task_manager` is None; `crackerjack run` profile-gate violation.
- **Observability added**: `crackerjack_async_task_result_query` (info) on every `result_store` call.

## Phase 5 — `reap_zombies` cron

- [ ] In `crackerjack/mcp/task_manager.py`, add an async method `async def _reap_zombies(self) -> None` that:
  1. Lists all keys via `self._store.list_keys()`.
  2. For each key, fetches the record; if `record.status in {"pending", "running"}` AND `now - record.registered_at > timedelta(seconds=self._settings.async_task.zombie_age_seconds)`, call `self._store.delete(task_id)` and log `crackerjack_async_task_zombie_reaped` at WARNING level.
- [ ] Start `_reap_zombies` in `AsyncTaskManager.start()` as a recurring task with `asyncio.create_task(self._reap_zombies_loop())`, where `_reap_zombies_loop` is `while True: await self._reap_zombies(); await asyncio.sleep(self._settings.async_task.reap_zombies_interval_seconds)`. Cancel the task in `stop()`.
- [ ] The existing `_cleanup_loop` continues to run (the original cleanup behavior is independent of reaping); the new `_reap_zombies` task is a sibling, not a replacement.

#### Integration Contract ← REQUIRED
- **Triggered from**: `AsyncTaskManager.start()` (lifecycle).
- **Returns to / updates**: a recurring `reap_zombies` task running every `reap_zombies_interval_seconds`; zombie entries (`status in {pending, running}` AND older than `zombie_age_seconds`) are deleted.
- **Demonstrable by**: the unit test `test_reap_zombies_removes_old_pending_entries` (Phase 6) registers a row with `registered_at = now - 8 days`, runs `_reap_zombies()` once, asserts the row is deleted.
- **Rollback signal**: `_reap_zombies` is never scheduled; the integration test in Phase 6 fails.
- **Observability added**: `crackerjack_async_task_zombie_reaped` (warning) per deleted entry; `crackerjack_async_task_reaper_status` (info) on each reaper tick (count of zombies found, count of reaped).

## Phase 6 — Tests

- [ ] `tests/unit/mcp/test_async_task_persistence.py` (unit tests for the store):
  - `test_register_persists_via_sqlite` — `AsyncTaskStore.register("task-1", "running")` then `get("task-1")` returns the entry. Uses a `tmp_path` fixture.
  - `test_register_upserts_with_new_status` — `register("task-1", "running")` then `register("task-1", "completed")`; assert `get` returns `status="completed"` (SQLite `INSERT OR REPLACE`). This replaces the original draft's awkward "release then re-register" pattern with the cleaner SQL-native upsert.
  - `test_status_update_via_explicit_path` — `register(...)` then `update_status(task_id, "failed")`; assert `get` returns the new status. Demonstrates the explicit-update path.
  - `test_get_returns_none_for_unknown_task` — `get("nonexistent")` returns `None`.
  - `test_list_keys_with_prefix` — register 3 tasks, `list_keys("async:")` returns 0 (none match) or however many do.
- [ ] `tests/unit/mcp/test_reap_zombies.py`:
  - `test_reap_zombies_removes_old_pending_entries` — register a row with `registered_at = now - 8 days`, run `_reap_zombies()` once, assert the row is gone.
  - `test_reap_zombies_preserves_recent_entries` — register a row with `registered_at = now - 1 hour`, run `_reap_zombies()`, assert the row remains.
  - `test_reap_zombies_preserves_completed_entries` — register a row with `status="completed"` and `registered_at = now - 8 days`, run `_reap_zombies()`, assert the row remains (zombies are only `pending` or `running`).
- [ ] `tests/integration/mcp/test_async_task_result_store.py`:
  - `test_result_store_returns_envelope_on_hit` — register a row via the live `AsyncTaskManager`, call `mcp__crackerjack__result_store(task_id=...)`, assert `{"found": true, "task": {...}}`.
  - `test_result_store_returns_envelope_on_miss` — call `result_store` with an unknown `task_id`, assert `{"found": false, "task_id": "..."}`.
- [ ] **Per `.claude/decisions/mcp-backend-wiring-discipline.md`**, add `tests/integration/test_async_task_result_store_e2e.py`: spin up the crackerjack MCP server, wait for warmup, call `mcp__crackerjack__result_store`, assert non-empty response. This is the per-tool e2e smoke test the discipline requires.
- [ ] **Cross-restart durability test** (per the original plan's goal): in `tests/integration/mcp/test_async_task_persistence.py`, register a task via `AsyncTaskStore` at one db_path, drop the in-memory store object, instantiate a new `AsyncTaskStore` at the same path, call `get(task_id)` and assert the record survives. This is the load-bearing assertion for the "durable across process restart" claim.
- [ ] Run `pytest tests/unit/mcp/test_async_task_persistence.py tests/unit/mcp/test_reap_zombies.py tests/integration/mcp/test_async_task_result_store.py tests/integration/test_async_task_result_store_e2e.py -v --tb=short` — all tests green.

#### Integration Contract ← REQUIRED
- **Triggered from**: `pytest <files>` (developer local + CI).
- **Returns to / updates**: 4 unit tests + 3 integration tests (including the e2e smoke per wiring discipline and the cross-restart durability assertion).
- **Demonstrable by**: `pytest … -v --tb=short` shows all tests passed.
- **Rollback signal**: any test fails for ≥1 commit after merge.
- **Observability added**: test output is the CI gate signal.

## Phase 7 — Verification

- [ ] `crackerjack run -v` clean
- [ ] Live MCP smoke test: start crackerjack, register a task via `AsyncTaskManager.register_task`, call `mcp__crackerjack__result_store(task_id=...)`, kill the crackerjack process, restart, call `result_store` again with the same `task_id`, verify the entry is still there.
- [ ] `rg -n "asyncio.create_task" crackerjack/mcp/task_manager.py` should return 0 hits (the brittle pattern is fully removed).
- [ ] `rg -n "self._tasks" crackerjack/mcp/task_manager.py` should return 0 hits (the dict-based state is gone).

#### Integration Contract ← REQUIRED
- **Triggered from**: developer / CI run.
- **Returns to / updates**: validated that the rewrite is durable, observable, and that the legacy code paths are fully removed.
- **Demonstrable by**: the kill-restart-query smoke test passes.
- **Rollback signal**: any Phase 6 test fails; the smoke test can't observe the entry after restart.
- **Observability added**: the kill-restart query is a one-time smoke; the per-call log lines are persistent.

## Phase 8 — Commit

- [ ] Single commit on `main` (crackerjack repo) with message: `feat(crackerjack): C-ASYNC-DURABILITY — AsyncTaskManager SQLite-backed persistence (C-WIRE Task 6)`
- [ ] Use `git -c user.email="les@wedgwoodwebworks.com" commit ...` (per `git-author-email-correct-domain.md`)
- [ ] Do NOT add `Co-Authored-By` trailer (per `feedback-no-claude-code-coauthor-attribution.md`)
- [ ] Do NOT push (per `feedback-bodai-push-is-user-controlled.md`)

## Rollback signal

If Phase 7 verification fails, rollback is `git revert <commit-hash>`. SQLite is strictly more durable than the old `asyncio.create_task` pattern, so a regression is unlikely; the failure mode is more likely a test that exercises a path the rewrite didn't cover.

## Observability added

- `crackerjack_async_task_registered` (info) — emitted on every successful `register`
- `crackerjack_async_task_lookup_miss` (debug) — emitted on `get` returning `None`
- `crackerjack_async_task_status_updated` (info) — emitted on `update_status`
- `crackerjack_async_task_zombie_reaped` (warning) — emitted when `_reap_zombies` removes a stale entry
- `crackerjack_async_task_reaper_status` (info) — emitted on each reaper tick (counts)
- `crackerjack_async_task_result_query` (info) — emitted on every `result_store` MCP tool call
- `crackerjack_async_task_manager_started` (info) — emitted at startup
- `crackerjack_async_task_manager_stopped` (info) — emitted at shutdown

## Cross-references

- `docs/plans/2026-08-03-crackerjack-c-wire-plan.md` Task 6 (active) — the parent plan this closes
- `mahavishnu/core/_lock_sentinel.py` — the substrate-agnostic lock primitive for in-process coordination (separate concern; not used by this plan)
- `feedback-substrate-compat-shim-rot.md` — the memory rule that motivates routing through SQLite rather than reintroducing a Dhara-named primitive
- `crackerjack/mcp/task_manager.py` — the file modified in Phases 1, 3, 5
- `crackerjack/config/settings.py` — the new `AsyncTaskSettings` class lives here
- `settings/crackerjack.yaml` — the `async_task:` YAML block
- `crackerjack/mcp/tools/execution_tools.py:10` — the nested group registrar pattern this plan mirrors
- `crackerjack/mcp/tools/profiles.py` — the `REGISTRATION_MAP` + profile lists this plan adds `async_task_tools` to
- `.claude/decisions/mcp-backend-wiring-discipline.md` — the per-tool e2e smoke test required by the project
- `feedback-bodai-push-is-user-controlled.md` — push policy
- `feedback-no-claude-code-coauthor-attribution.md` — commit message policy
- `git-author-email-correct-domain.md` — author email policy
