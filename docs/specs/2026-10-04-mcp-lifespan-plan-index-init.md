---
status: draft
role: implementation
topic: mcp
date: 2026-10-04
last_reviewed: 2026-10-04
superseded_by: null
blocks_on: []
title: "MCP Server Lifespan Refactor — Move Post-Start Init Out of lifecycle.start_server"

---

# MCP Server Lifespan Refactor — Move Post-Start Init Out of `lifecycle.start_server`

## **Goal:** Eliminate the `lifecycle.start_server` circular dependency on the MCP server's own HTTP endpoint by moving all post-listener init (`init_signer_feed_state`, `plan_index` rebuild, `TaskOrphanSweeper` spawn) into a FastMCP lifespan handler. The lifespan runs *after* uvicorn has bound the listener but *before* the server starts accepting requests, breaking the dep. Side effects: (1) the three `/health` feeds stop reporting permanent `warming_up`; (2) the 5 pre-existing `TestLifecycle` / `TestServerLifecycle` failures in `tests/unit/test_mcp_server_core.py` and `tests/unit/test_mcp_server.py` (which trace to the same root cause) start passing; (3) the C1 wrapper refactor (removing `_RunAsyncAdapter`) becomes safe to ship. **Architecture:** FastMCP's `http_app()` already supports a custom Starlette lifespan via `lifespan=...`; we thread a `lifespan_post_start_init(app)` async-context-manager through `run_http_async` → `http_app(lifespan=...)`. `lifecycle.start_server` shrinks to "build lifespan, call `run_http_async`". **Tech Stack:** Python 3.14, FastMCP 4.0.10 (already pinned), Starlette lifespan API, mcp_common >= 0.30.2, pytest-asyncio (auto mode).

## Context

The 4-day-old mahavishnu MCP server wedged on 2026-10-03 — sending an `/mcp` `initialize` request caused the server to hang, with even `/health` (the lightweight endpoint) timing out until the hung connection was reaped. The wedge forced a process restart, which the launchd wrapper's `ThrottleInterval: 30` then kept looping because the new process hit the same hang.

### Why the server hung

`mahavishnu/mcp/lifecycle.py:start_server` runs, in order, **before** `server.server.run_http_async(...)`:

1. `init_signer_feed_state()` — pure data init (no HTTP), fine
2. `plan_index` rebuild — `MCPKvClient(base_url=mcp_url, config=MCPKvConfig(enabled=True))` then `await runner.force_run()`. `MCPKvClient` is an HTTP client that talks to the MCP server's own KV endpoints. **The server isn't bound until step 3.**
3. `TaskOrphanSweeper` init — Redis stream, fine
4. `await server.server.run_http_async(host, port, uvicorn_config)` — binds the listener, server starts

Step 2 blocks trying to connect to a port that's listening on nothing. The launchd wrapper's `--timeout 180` kills the process before the connection times out. Then launchd's `ThrottleInterval: 30` restarts it; the new process hits the same hang; infinite loop.

### Why this bug was latent

The previous `scripts/launch_mcp.py` had a `_RunAsyncAdapter` shim that bypassed `lifecycle.start_server` entirely — it called `server.server.run_http_async(...)` directly on the inner FastMCP. That bypass was added on 2026-09-26 (see `.claude/decisions/2026-09-26-mcp-launcher-migration.md` Trap #1) because `lifecycle.start_server` hardcoded `uvicorn_config={"timeout_graceful_shutdown": 30}` and ignored launcher-passed kwargs.

The bypass was deliberate. But it also meant **the broken code path in `lifecycle.start_server` was never exercised in production** for the entire ~3-week life of the migration. Unit tests in `tests/unit/test_mcp_lifecycle.py` use `monkeypatch` to mock `PROFILE_REGISTRATIONS`, `_register_profile_tools_helper`, `TaskOrphanSweeper`, and the plan_index setup — so they too never saw the dep. The 5 pre-existing test failures in `tests/unit/test_mcp_server_core.py::TestLifecycle` and `tests/unit/test_mcp_server.py::TestServerLifecycle` (verified failing on `main` via `git stash` round-trip on 2026-10-03) trace to the same root cause: those tests mock `run_http_async` but don't mock the plan_index init, so `MCPKvClient` makes a real HTTP call to the not-yet-bound server.

The decision doc justified the bypass as "monkey-patching `start()` to accept `uvicorn_config` — rejected because it requires touching `lifecycle.start_server` for a behavior that the launcher now owns." This rejection was correct in spirit but missed that `lifecycle.start_server` had grown a hidden dep on the server being up. The bypass papered over a real bug, not just a config wire-up.

## Goals & Non-Goals

### Goals

1. **No circular dep.** All init that requires the HTTP server to be up runs *after* uvicorn has bound the listener. Init that doesn't require it stays in `__init__` (no need to move it).
2. **Feeds warm.** `/health` reports `ok: true` (not `warming_up`) for `skills_signer`, `plan_index`, and `task_orphan_sweeper` on a freshly-booted server. Per `mcp-backend-wiring-discipline.md`'s 4-signal contract: `feed.entities_count > 0` AND `cycles_total >= 1` AND `ingester_running` AND `feed.last_updated_timestamp` populated.
3. **C1 wrapper refactor unblocked.** Removing `scripts/launch_mcp.py:_RunAsyncAdapter` and threading `uvicorn_config` through `FastMCPServer.start(host, port, uvicorn_config=...)` becomes safe. The 7 new C1 tests in `tests/unit/test_mcp_lifecycle.py` and `tests/unit/test_mcp_server_core.py` (added 2026-10-03, currently red on `main`) start passing.
4. **Pre-existing 5 test failures fixed.** `TestLifecycle::test_start_invokes_run_http_async`, `TestLifecycle::test_start_uses_default_host_and_port`, `TestServerLifecycle::test_server_start`, and the two `TestFastMCPServerInit::test_init_with_tracing_*` failures (the last two are tangential — the tracing-middleware tests fail because `MahavishnuApp` heavy init is triggered by the `server` fixture even when tracing is off; the lifespan refactor won't fix those, but we should confirm).
5. **Launch still fits in 180s.** The launchd wrapper's `--timeout 180` must continue to pass — the post-init work adds a few hundred ms (one `force_run` cycle + Redis subscribe), not minutes.
6. **Wedge remains a non-issue.** A fresh process is the wedge workaround per the 2026-10-03 investigation. The lifespan refactor doesn't change the wedge surface — but by removing the bug that hid behind the bypass, future wedge investigations have a cleaner baseline.

### Non-Goals (v1)

- **Not a C1 wrapper change.** The C1 refactor (remove `_RunAsyncAdapter`, thread `uvicorn_config` through `start()`) is the next change after this lands — not part of this spec. This spec's acceptance criterion is that C1 *becomes possible*, not that it ships here.
- **Not a oneiric / akosha / crackerjack migration.** Those repos use FastMCP-shaped servers without `lifecycle.start_server` and don't have this bug. `crackerjack` and `oneiric` already use the launcher directly; no follow-up work needed.
- **Not a decision-doc rewrite.** The 2026-09-26 launcher-migration decision doc becomes partly-stale (Trap #1 explains a bypass that no longer needs to exist after C1). Marking it `superseded_by` is a follow-up commit, not part of this spec.
- **Not a `mahavishnu mcp start` CLI rewrite.** The CLI path (`mahavishnu/_main_cli.py:755`) calls `server.start(host, port)` without `uvicorn_config`. It works unchanged because the new `start()` keeps the historical default-`None` shape. Out of scope.
- **Not a FastMCP upgrade.** The 4.0.10 lifespan API is sufficient; no need to chase 4.0.11+.

## Architecture

```
              ┌────────────────────────────────────────┐
              │  scripts/launch_mcp.py (unchanged)    │
              │  build_server() → FastMCPServer(...)   │
              │  mcp_common.server.launcher.launch()   │
              │      run_async(transport="http",       │
              │                  host=, port=,         │
              │                  uvicorn_config=)      │
              └────────────────────┬───────────────────┘
                                   │ routes to FastMCPServer.run_async
                                   ▼
              ┌────────────────────────────────────────┐
              │  FastMCPServer.run_async (NEW)         │
              │  1. build lifespan_post_start_init()   │
              │  2. await self.server.run_http_async(  │
              │       host=, port=,                    │
              │       uvicorn_config=uvicorn_config)   │
              └────────────────────┬───────────────────┘
                                   │ start_server_helper now just calls
                                   ▼
              ┌────────────────────────────────────────┐
              │  lifecycle.start_server (SIMPLIFIED)   │
              │  1. register profile tools              │
              │  2. await run_http_async(              │
              │       host, port, uvicorn_config)      │
              │  (post-init moves to lifespan)         │
              └────────────────────┬───────────────────┘
                                   │ lifespan registered via
                                   ▼
              ┌────────────────────────────────────────┐
              │  FastMCP lifespan_post_start_init      │
              │  ── startup (after uvicorn binds) ──   │
              │  init_signer_feed_state()              │
              │  build MCPKvClient + PlanIndexStore    │
              │  await runner.force_run()              │
              │  runner.start() (schedules periodic)   │
              │  sweeper = TaskOrphanSweeper(...)      │
              │  await sweeper.init()                  │
              │  sweeper_task = create_task(           │
              │      sweeper.run_forever(),            │
              │      name="task_orphan_sweeper")       │
              │  ── yield (server runs here) ──        │
              │  ── shutdown (on SIGTERM) ──           │
              │  sweeper_task.cancel()                 │
              │  await sweeper_task (CancelledError)   │
              │  runner.stop()                         │
              │  reset_signer_feed_state()             │
              └────────────────────────────────────────┘
```

The key invariant: **all init that requires the server to be up runs after uvicorn's `Server.startup` event fires and before `Server.shutdown`.** FastMCP's `http_app(lifespan=...)` parameter accepts a Starlette lifespan that fires exactly in that window. We register our lifespan on the ASGI app; FastMCP composes it with its own internal lifespan (which sets up the `StreamableHTTPSessionManager`).

## Component Changes

### 1. `mahavishnu/mcp/lifecycle.py` — simplify + extract lifespan

**Current state** (the broken function, lines 28-184): 156 lines doing tool profile, defensive init, signer feed, plan_index rebuild, sweeper spawn, then `run_http_async`.

**Target state**: split into two pieces. **Implementation note (2026-10-04)**: the `plan_index` rebuild inside the lifespan is scheduled as a background task (`asyncio.create_task`) rather than being awaited, because uvicorn's accept loop hasn't started yet when the lifespan runs — awaited HTTP calls from the plan_index `MCPKvClient` to its own server sit in the OS TCP backlog and time out at 180s. The background task runs after the lifespan yields, when the event loop is free to process both the server's request handling and the client's response handling concurrently. The `/health` endpoint briefly reports `plan_index: warming_up` (until the background task completes) — for this codebase that means "forever, due to a pre-existing doc-frontmatter validation bug," which is a separate issue.

```python
# New: extracted lifespan function (new file or top of lifecycle.py)
from contextlib import asynccontextmanager
from fastmcp import FastMCP
from starlette.applications import Starlette


def build_post_start_lifespan(server: FastMCPServer) -> Callable[..., AsyncContextManager]:
    """Return a Starlette lifespan that runs all post-listener init.

    FastMCP's http_app(lifespan=...) expects an async context manager factory.
    This factory receives the ASGI app, so it can stash references on
    ``app.state`` if needed (we don't, but the contract is there).
    """
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        # ── startup (after uvicorn binds, before accepting) ──
        # signer feed (pure data, fast)
        from .signer_feed import init_signer_feed_state
        try:
            init_signer_feed_state()
        except Exception as exc:
            logger.error("Failed to initialize skills_signer feed state: %s", exc)

        # plan_index rebuild (needs MCP server's own KV endpoints — NOW UP)
        try:
            from pathlib import Path
            from ..core.bootstrap import resolve_mcp_url
            from ..core.state_backends.mcp_kv import MCPKvClient, MCPKvConfig
            from ..plan_index.cron import PeriodicTaskRunner
            from ..plan_index.store import PlanIndexStore

            mcp_url = resolve_mcp_url(server.app.config)
            kv_backend = MCPKvClient(
                base_url=mcp_url, config=MCPKvConfig(enabled=True)
            )
            server._plan_index_mcp_kv = kv_backend
            store = PlanIndexStore(kv_backend)
            repo_root = Path.cwd() if Path("docs/plans").is_dir() else None
            runner = PeriodicTaskRunner(store=store, repo_root=repo_root)
            outcome = await runner.force_run()
            runner.start()
            server._plan_index_runner = runner
            logger.info(
                "plan_index cycle complete: success=%d errors=%d entities=%d",
                outcome.success, outcome.errors, outcome.entities_count,
            )
        except Exception as exc:
            logger.error("Failed to start plan_index subsystem: %s", exc)

        # sweeper (Redis stream, no HTTP dep)
        sweeper_task: asyncio.Task | None = None
        try:
            from .sweepers.task_orphan_sweeper import TaskOrphanSweeper
            sweeper = TaskOrphanSweeper(
                session_buddy_client=get_session_buddy_client()
            )
            await sweeper.init()
            sweeper_task = asyncio.create_task(
                sweeper.run_forever(), name="task_orphan_sweeper"
            )
            server._task_orphan_sweeper = sweeper
            server._task_orphan_sweeper_task = sweeper_task
            logger.info("task_orphan_sweeper started (stream=bodai:events)")
        except Exception as exc:
            logger.error("Failed to start task_orphan_sweeper: %s", exc)

        # ── yield: server runs here ──
        yield

        # ── shutdown (on SIGTERM) ──
        if sweeper_task is not None:
            sweeper_task.cancel()
            try:
                await sweeper_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Error cancelling task_orphan_sweeper: %s", exc)

        # stop plan_index runner (guarded)
        runner = getattr(server, "_plan_index_runner", None)
        if runner is not None:
            try:
                runner.stop()
            except Exception as exc:
                logger.warning("Error stopping plan_index runner: %s", exc)

        # reset signer feed state
        from .signer_feed import reset_signer_feed_state
        try:
            reset_signer_feed_state()
        except Exception as exc:
            logger.warning("Error resetting signer_feed_state: %s", exc)

    return lifespan


# Shrunk: lifecycle.start_server now just runs the server
async def start_server(
    server: Any,
    host: str = "127.0.0.1",
    port: int = 3000,
    *,
    uvicorn_config: dict[str, Any] | None = None,
) -> None:
    """Start the MCP server.

    Post-listener init (signer feed, plan_index rebuild, sweeper spawn)
    moved to the FastMCP lifespan returned by ``build_post_start_lifespan``.
    C1: uvicorn_config kwarg threads through to ``run_http_async`` so the
    launcher's ``timeout_graceful_shutdown=30`` wins end-to-end.
    """
    # 1. Tool profile (no server dep — stays in start_server)
    server._active_profile = get_active_profile()
    methods_to_call = PROFILE_REGISTRATIONS[server._active_profile]
    methods_set = set(methods_to_call)
    await _register_profile_tools_helper(server, methods_set)
    server._update_registered_tool_metrics()

    # 2. Defensive init for the `mahavishnu mcp start` path (no server dep)
    # ... unchanged pool_manager / memory_aggregator blocks ...

    # 3. Register the post-start lifespan on the FastMCP app BEFORE run_http_async
    #    This is the key change: lifespan runs after uvicorn binds.
    server.server.add_lifespan(build_post_start_lifespan(server))

    # 4. Run the server (blocks until shutdown)
    effective_uvicorn_config = (
        uvicorn_config if uvicorn_config is not None
        else {"timeout_graceful_shutdown": 30}
    )
    await server.server.run_http_async(
        host=host, port=port, uvicorn_config=effective_uvicorn_config,
    )
```

**API question to resolve during implementation:** does FastMCP 4.0.10 expose `server.add_lifespan(callable)` directly, or do we need to use `http_app(lifespan=...)` and run that manually? The implementer should:
- Check `fastmcp.server.server.FastMCP` for `add_lifespan` / `lifespan` / `http_app` methods
- Check `fastmcp.server.http.create_streamable_http_app` to see how the existing lifespan is composed
- If `add_lifespan` doesn't exist, fall back to: build the app via `server.server.http_app(lifespan=...)` ourselves and run it via `uvicorn.Server` directly (bypassing `run_http_async`)

The investigation during the failed C1 attempt (saved to `feedback-mahavishnu-c1-plan-index-circular-dep.md`) only confirmed the symptom, not the API. This spec is a target shape; the implementer fills in the exact API call.

### 2. `mahavishnu/mcp/server_core.py` — keep `start()` + `run_async()` (from C1)

The C1 work is preserved (with `uvicorn_config` threading) but the tests stay red on `main` until this spec lands. The relevant signatures from the C1 attempt:

```python
async def start(self, host="127.0.0.1", port=3000, *, uvicorn_config=None) -> None:
    await _start_server_helper(self, host=host, port=port, uvicorn_config=uvicorn_config)

async def run_async(self, *, transport, host, port, uvicorn_config) -> None:
    if transport != "http":
        raise ValueError(f"FastMCPServer only supports transport='http', got {transport!r}")
    await self.start(host=host, port=port, uvicorn_config=uvicorn_config)
```

When this spec lands, both call through to `lifecycle.start_server`, which now uses the lifespan. C1 wrapper refactor (the next change after this spec) is then safe.

### 3. `scripts/launch_mcp.py` — no change

Stays as-is (still has `_RunAsyncAdapter` from 2026-09-26). C1 wrapper change is the *next* PR after this spec; not this one.

### 4. Tests — `tests/unit/test_mcp_lifecycle.py` + `tests/unit/test_mcp_server_core.py`

Two layers of test updates:

**A. Add new tests for the lifespan path:**
- `test_post_start_lifespan_init_signer_feed` — patch the lifespan, run it, assert `init_signer_feed_state` was called
- `test_post_start_lifespan_swallows_plan_index_failure` — patch `MCPKvClient` to raise, run lifespan, assert the runner was not stored on `server`
- `test_post_start_lifespan_spawns_sweeper_task` — run lifespan, assert `server._task_orphan_sweeper_task` is an `asyncio.Task` (matches existing pattern in `test_start_server_spawns_task_orphan_sweeper`)
- `test_post_start_lifespan_teardown_cancels_sweeper` — run lifespan's teardown half, assert sweeper task is cancelled
- `test_start_server_no_longer_init_signer_feed_directly` — assertion of the OPPOSITE: confirms signer feed init moved to lifespan (regression guard against re-merging the two paths)
- `test_start_server_no_longer_build_plan_index_runner` — same idea for plan_index

**B. Update the 3 pre-existing `TestLifecycle` / `TestServerLifecycle` tests:**

Current state (failing on `main`):
```python
async def test_start_invokes_run_http_async(self, server):
    server.server.run_http_async = AsyncMock()
    await server.start(host="127.0.0.1", port=4001)
    server.server.run_http_async.assert_awaited_once_with(
        host="127.0.0.1", port=4001, uvicorn_config={"timeout_graceful_shutdown": 30},
    )
```

Failure mode: `server.start()` calls `lifecycle.start_server` which makes a real `MCPKvClient` HTTP call because the test doesn't mock the plan_index subsystem. The HTTP call hangs/times-out.

After this spec: `lifecycle.start_server` no longer touches plan_index (it moved to lifespan). The test should pass as-written without changes — verify in the implementation PR.

The 2 `TestFastMCPServerInit::test_init_with_tracing_*` failures are unrelated (heavy `MahavishnuApp` init in the `server` fixture). They should be retried after the spec lands; if they still fail, they're a separate issue and not a blocker for this spec.

**C. The 7 C1 tests already added (currently red):**
- `test_mcp_lifecycle.py::test_start_server_honors_passed_uvicorn_config` (RED — needs `uvicorn_config` kwarg which exists in C1 source)
- `test_mcp_lifecycle.py::test_start_server_none_uvicorn_config_uses_default` (RED)
- `test_mcp_server_core.py::TestC1RunAsyncContract::*` (3 tests, RED)
- `test_mcp_server_core.py::TestC1StartForwardsUvicornConfig::*` (2 tests, RED)

After this spec lands (and source changes are in place), these 7 should go green automatically. Verify in the implementation PR.

### 5. Decision doc — out of scope, follow-up commit

`.claude/decisions/2026-09-26-mcp-launcher-migration.md` Trap #1 explains the `_RunAsyncAdapter` bypass. After C1 lands, that bypass goes away. Add `superseded_by: 2026-10-04-c1-launcher-cleanup` (or the actual merge SHA) to the decision frontmatter, and add a one-paragraph "Status" block pointing at the new code. Out of scope for this spec — do it in the C1 PR.

## Migration Path

1. **PR 1 (this spec):** Lifespan refactor. Source changes in `lifecycle.py`. New tests. Pre-existing 5 failures should reduce to 2 (the tracing-middleware pair). 7 C1 tests still red.
2. **PR 2 (C1 wrapper):** Remove `_RunAsyncAdapter`, thread `uvicorn_config` through `start()`. 7 C1 tests go green. Decision doc marked superseded.
3. **PR 3 (cleanup):** If any of the 2 tracing-middleware failures are still failing, address them as a separate small change. Out of scope for this spec.

## Acceptance Criteria

The implementation PR is done when:

- [ ] All 11 `test_mcp_lifecycle.py` tests pass (4 existing + 6 new lifespan tests + 1 cleanup)
- [ ] All 5 `TestC1RunAsyncContract` + `TestC1StartForwardsUvicornConfig` tests in `test_mcp_server_core.py` go green
- [ ] `TestLifecycle::test_start_invokes_run_http_async` and `test_start_uses_default_host_and_port` go green without modification (the lifespan refactor makes the underlying `run_http_async` call reachable)
- [ ] `TestServerLifecycle::test_server_start` goes green without modification
- [ ] Of the 5 pre-existing failures, 3 (the `TestLifecycle` / `TestServerLifecycle` trio) go green. The 2 `test_init_with_tracing_*` failures are explicitly out of scope.
- [ ] Live server: `curl -fsS http://127.0.0.1:8680/health | jq -e '.checks.skills_signer.ok, .checks.plan_index.ok, .checks.task_orphan_sweeper.ok'` returns `true, true, true` (currently: `true, true, true` but with `status: "warming_up"`; after: `status: "ok"`)
- [ ] Live server starts in < 180s (current ~150s on warm venv, plan_index force_run should add < 5s)
- [ ] No new warnings on `/health` from the post-init flow (lifespan swallows exceptions per the existing `try/except` pattern)
- [ ] `mahavishnu mcp start --help` still parses (CLI path unchanged)
- [ ] `crackerjack run -v` shows no new ruff / ty / bandit failures on changed files
- [ ] Decision doc note added in PR description: "this unblocks C1 (PR 2) and supersedes the bypass in the 2026-09-26 launcher-migration decision"

## Risks

- **FastMCP lifespan API surface** — `add_lifespan` may not exist on FastMCP 4.0.10. If it doesn't, the implementer needs to call `server.server.http_app(lifespan=...)` directly and run uvicorn manually. The investigation effort is bounded (~30 min in the FastMCP source) but it could push the design away from the "minimal `lifecycle.start_server`" shape shown above. The spec is target-shaped; the implementer fills in the actual API.
- **Lifespan exception semantics** — if the lifespan's startup phase raises, uvicorn fails to start. The existing code uses `try/except` + `logger.error` per subsystem to swallow init failures. The lifespan must do the same. If `init_signer_feed_state()` raises an unhandled exception, the server won't start at all. This is a tightening of the current contract — but the current contract is already "fail-soft per subsystem" so the change is one of placement, not semantics.
- **Launch-time budget** — the lifespan startup runs *after* uvicorn binds but *before* it accepts requests. If `plan_index.force_run` is slow on cold boot, the launchd `--timeout 180` could fire. The existing `force_run` already runs in the current `start_server` (where it blocks) and the wrapper tolerates 180s; the lifespan path adds maybe 1-2s overhead. Acceptable.
- **Sweeper teardown race** — the lifespan's teardown cancels the sweeper task. If a request is mid-flight using the sweeper, it could race. The existing `stop_server` (which `lifecycle.stop_server` does the same thing) already has this risk; no new exposure.
- **Test fixture flakiness** — the lifespan tests use `asyncio` and may be order-sensitive. The `test_post_start_lifespan_spawns_sweeper_task` test needs to cancel the task it created (mirror the existing pattern in `test_start_server_spawns_task_orphan_sweeper`).
- **Two `test_init_with_tracing_*` failures may persist** — these are unrelated to the lifespan refactor. If they still fail after PR 1, they're a separate small fix. Document explicitly in the PR description so reviewers know.

## Estimated Size

- `mahavishnu/mcp/lifecycle.py`: net -30 LOC (extracted lifespan function adds ~80, but `start_server` shrinks by ~110)
- New tests: ~150 LOC (6 new lifespan tests)
- Test updates: ~10 LOC (no changes expected to existing 3 tests; the lifespan refactor makes them pass)
- Total diff: ~200 LOC. Implementable in one PR by a single agent.

## Related Work

- `feedback-mahavishnu-c1-plan-index-circular-dep.md` — memory file with full diagnostic of the bug. Read first.
- `.claude/decisions/2026-09-26-mcp-launcher-migration.md` Trap #1 — explains the bypass that hid the bug. Becomes stale after C1 lands.
- `docs/specs/2026-09-29-task-system-design.md` — example of the spec format used in this repo.
- `mahavishnu/mcp/backend-wiring-discipline.md` — the 4-signal contract this spec satisfies.
- `feedback-oneiric-mcp-health-feed-warmup.md` — adjacent memory: oneiric has a similar "feed warm at startup" pattern that works because oneiric doesn't have the lifecycle dep.
