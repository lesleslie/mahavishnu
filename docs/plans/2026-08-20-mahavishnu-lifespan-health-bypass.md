---
status: active
role: canonical
date: 2026-08-20
last_reviewed: 2026-08-20
superseded_by: null
topic: mcp-lifespan-startup-ordering
---

# Mahavishnu MCP `/health` Lifespan Bypass

## 1. Outcome

The `mahavishnu mcp start` command must serve `/health` (HTTP 200 with
`version`) within **5 seconds** of process start, regardless of how long
the underlying adapter initialization (OpenSearch, LlamaIndex, Agno,
session-buddy poller, repo loader, …) takes.

This unblocks the launchd `launch_with_healthcheck.sh` wrapper (60s
timeout) and prevents the crash-loop observed in
`~/.local/state/mcp/logs/mahavishnu.err` on 2026-08-20 (10+ consecutive
"did not respond within 60s, killing PID N" entries).

Success metric: `time curl -sf http://127.0.0.1:8680/health` returns
`< 1.0s` on a cold start with all adapters enabled.

## 2. Goals

1. `/health` (liveness) responds immediately when Uvicorn binds — it
   must not depend on `MahavishnuApp._initialize_runtime_services()`
   having completed.
2. `/ready` (readiness) continues to reflect adapter initialization
   status — returns 503 with reason until `_initialize_runtime_services()`
   finishes, then 200.
3. Existing behavior preserved: when `/health` and `/ready` are both 200,
   the application is functionally identical to today.
4. The launchd wrapper's 60s `--timeout` becomes a comfortable margin
   instead of a race.

## 3. Non-Goals

- Reworking the launchd wrapper timeout (defense-in-depth bump to 180s
  for mahavishnu can be a separate follow-up; out of scope here).
- Speculative async refactors of every adapter init step — we only need
  to defer the *registration* of the heavy init, not redesign each
  subsystem.
- Changes to `/health` response body (version, status fields).
- Migrating to `/ready` from launchd (launchd doesn't speak readiness;
  it only knows live-or-dead). Wrapper stays on `/health`.

## 4. Current Findings

`mahavishnu/core/app.py` lines 209–212:

```python
self.observability = self._init_observability()
self._health_endpoint = self._init_health_endpoint()              # constructs HealthEndpoint object
self._initialize_runtime_services()                               # HEAVY: OpenSearch + 8 repos + adapters
```

`_initialize_runtime_services()` is dispatched to
`bootstrap.initialize_runtime_services(app)` (`mahavishnu/core/bootstrap.py:298`).
That function calls, in order, among others:

- `QualityControl(app.config)`
- `SessionBuddy(app.config)`
- `_init_coordination_memory` (Dhara client)
- `_init_repository_messenger`
- `app._init_pool_manager()` (when pools enabled)
- `OpenSearchIntegration(app.config)` — **observed taking 4.7s for a
  single GET against `localhost:9200`** in
  `~/.local/state/mcp/logs/mahavinshu.err` (2026-08-20 trace)
- `MonitoringService(app)`
- Plus Agno/LlamaIndex adapter imports (already lazy per
  `mahavishnu/core/bootstrap.py:198–203`)

The HTTP `/health` route is only registered when
`FastMCPServer.start()` runs (`mahavishnu/mcp/server_core.py:1355`), and
that happens *after* `MahavishnuApp.__init__` returns — i.e. after
the heavy init has finished.

Observed crash pattern (from `mahavishnu.err`):

```
launch_with_healthcheck: http://127.0.0.1:8680/health did not respond within 60s, killing PID N
```

repeated 10+ times across PIDs 2289 → 3098 → 5362 → 7282 → 9247 →
11341 → 13256 → 16142 → 18208 → 20014 before the current PID 22060
managed to bind in time. The success of 22060 was timing-dependent,
not deterministic.

The `/ready` endpoint schema already exists
(`mahavishnu/core/health.py:97`) — it's just not wired into the
application's startup signaling.

**Related finding (2026-08-20 cross-server smoke test):** During the
`discover_tools` verification that surfaced this plan, Session-Buddy
was identified as the lone Bodai core MCP server lacking the
canonical `discover_tools` meta-tool and shipping a one-off `ping`
tool instead of the mcp-common `get_liveness` primitive. That gap
is the subject of the companion plan
[`2026-08-20-bodai-mcp-surface-standardization.md`](./2026-08-20-bodai-mcp-surface-standardization.md),
not this one.

## 5. Implementation Phases

### Phase 1: Decouple `/health` from runtime init

**Goal:** `/health` route is registered on the FastMCP/ASGI app BEFORE
`__init__` calls `_initialize_runtime_services()`, and its handler
doesn't read any `app.*` attributes that the heavy init creates.

**Tasks:**

1. In `mahavishnu/core/app.py`, move `_init_health_endpoint()` so it
   runs AFTER `_initialize_runtime_services()`. The endpoint object
   doesn't need runtime services to be constructed — only its handler
   needs them, and the handler will be rewritten to read from a
   "ready" flag.
2. Refactor `HealthEndpoint` so its `/health` handler returns
   `{status: ok, service: mahavishnu, version: ...}` without touching
   `app.opensearch_integration`, `app.pool_manager`, `app.session_buddy`,
   etc. All those checks move to `/ready`.
3. Add a `_ready_flag` attribute on `MahavishnuApp` that defaults to
   `False` and is flipped to `True` at the END of
   `_initialize_runtime_services()`. `/ready` returns 200 only when
   the flag is `True`; otherwise returns 503 with `{status: warming_up,
   reason: runtime_init_pending}`.
4. Verify the FastMCP/Uvicorn binding order: the `/health` route must
   be on the ASGI app by the time `uvicorn` calls `lifespan.startup`
   — which means the route registration must happen during
   `FastMCPServer.__init__`, not during `MahavishnuApp.__init__`.

**Exit criteria:**
- `time curl -sf http://127.0.0.1:8680/health` returns < 1s on a fresh
  boot with all adapters enabled.
- `curl -sf http://127.0.0.1:8680/ready` returns 503 with the warming-up
  reason while init is running, then 200 after init finishes.
- No crash-loop in `~/.local/state/mcp/logs/mahavishnu.err` over 5
  consecutive restarts (a hand-driven `kill -TERM <pid>` followed by
  launchd restart cycle).

#### Integration Contract
- **Triggered from**: `mahavishnu mcp start` (`scripts/launch_mcp_with_secrets.py`)
  → `mahavishnu/cli.py:mcp:start` → `run_server()` →
  `FastMCPServer.start()` → Uvicorn lifespan.
- **Returns to / updates**: `~/.local/state/mcp/logs/mahavishnu.err`
  (new info-level log line `Health endpoint bound before runtime init —
  /health responding immediately`). `MahavishnuApp._ready_flag` flips
  `False` → `True` at end of `_initialize_runtime_services()`.
- **Demonstrable by**:
  ```bash
  pkill -f 'mahavishnu mcp start' || true
  sleep 2  # let launchd restart
  time curl -sf http://127.0.0.1:8680/health
  # expected: {"status":"ok","service":"mahavishnu","version":"0.12.1"} in < 1.0s
  curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8680/ready
  # expected: 503 immediately, 200 within 30s
  ```
- **Rollback signal**: if any test in `tests/unit/test_core/test_app.py`
  fails after the refactor (especially `test_app_lifespan.py` if it
  exists, or any test that asserts `_initialize_runtime_services` runs
  before Uvicorn binds), revert via `git revert`.
- **Observability added**: structured log line at INFO when the
  `/health` route is registered (with elapsed time since process start);
  second structured log line at INFO when `_ready_flag` flips to True
  (with elapsed time). Both lines should appear in `mahavishnu.err`.

### Phase 2: Defense-in-depth: bump wrapper timeout for mahavishnu only

**Goal:** Even with Phase 1, give the wrapper headroom for pathological
cold starts (e.g. OpenSearch unreachable, repos on cold filesystem cache).

**Tasks:**

1. Identify the launchd plist for mahavishnu
   (`~/Library/LaunchAgents/*mahavishnu*`).
2. Change `--timeout 60` to `--timeout 180` for mahavishnu only.
3. `launchctl unload` and `launchctl load` to apply.

**Exit criteria:** plist shows `--timeout 180`. Wrapper logs in
`mahavishnu.err` show no kill events over 24h of normal operation.

#### Integration Contract
- **Triggered from**: manual `launchctl unload/load` of the mahavishnu
  plist.
- **Returns to / updates**: `~/Library/LaunchAgents/*mahavishnu*.plist`
  argument array.
- **Demonstrable by**: `grep timeout ~/Library/LaunchAgents/*mahavishnu*`
  shows `180`.
- **Rollback signal**: `--timeout` revert to `60` if Phase 1 alone is
  sufficient and the longer window masks a regression.
- **Observability added**: none (config change).

### Phase 3: Add a regression test

**Goal:** Prevent the bug from recurring. A test that boots the FastMCP
server with simulated slow init (monkeypatch `_initialize_runtime_services`
to sleep 30s) and asserts `/health` responds within 1s while `/ready`
correctly reports warming-up.

**Tasks:**

1. New test file: `tests/integration/test_lifespan_health_bypass.py`
   (or extend an existing lifespan test).
2. Monkeypatch `_initialize_runtime_services` to `asyncio.sleep(30)`.
3. Boot the server in a background task, poll `/health` with a 1s
   deadline, assert 200. Poll `/ready` with the same deadline, assert 503.
4. After 30s, poll `/ready` again, assert 200.

**Exit criteria:** new test passes locally; CI is green.

#### Integration Contract
- **Triggered from**: `pytest tests/integration/test_lifespan_health_bypass.py`.
- **Returns to / updates**: adds a new test file under `tests/`.
- **Demonstrable by**: `pytest -k test_lifespan_health_bypass -v` passes.
- **Rollback signal**: test is flaky in CI (rare, but the long sleep
  may interact with slow CI runners — keep sleep duration configurable).
- **Observability added**: test emits timing data via `pytest -v` so
  regressions in /health response time are visible.

> **Phase 4 moved.** The cross-server `discover_tools` smoke test
> that surfaced this plan also surfaced a Session-Buddy
> standardization gap. That work was promoted during plan review on
> 2026-08-20 to its own plan:
> [`2026-08-20-bodai-mcp-surface-standardization.md`](./2026-08-20-bodai-mcp-surface-standardization.md).
> Phases 1-3 here are Mahavishnu-internal and ship on the
> `worktree-mhv-lifespan-health-bypass` branch; the standardization
> plan ships separately in mcp-common + session-buddy.

## 6. Required Code Changes

- [ ] `mahavishnu/core/app.py` — reorder init so `/health` route binds
      first; add `_ready_flag` attribute; flip flag at end of
      `_initialize_runtime_services()`.
- [ ] `mahavishnu/core/health.py` — refactor `/health` handler to not
      read adapter state; route the new flag-based logic in `/ready`.
- [ ] `mahavishnu/mcp/server_core.py` — ensure `/health` and `/ready`
      routes are registered during `FastMCPServer.__init__` (before any
      `app` reference is needed).
- [ ] `tests/integration/test_lifespan_health_bypass.py` — new
      regression test.
- [ ] `~/Library/LaunchAgents/*mahavishnu*.plist` — `--timeout 180`.

## 7. Validation Matrix

| Check | Expected | Evidence |
|---|---|---|
| `time curl -sf http://127.0.0.1:8680/health` after cold start | < 1.0s | terminal timing output |
| `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8680/ready` immediately after Uvicorn binds | 503 | curl exit code + body |
| Same after 30s | 200 | curl exit code + body |
| `pytest tests/integration/test_lifespan_health_bypass.py` | PASS | pytest output |
| `crackerjack run` (full quality gate) | PASS | crackerjack report |
| `git grep -n '_initialize_runtime_services' mahavishnu/` | shows reorder | grep output |
| Session-Buddy standardization gate: `pytest mcp-common/tests/test_baseline_surface.py` passes (see companion plan) | PASS | companion plan link |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Existing tests assume `/health` requires full runtime init | Medium | Run full test suite early in Phase 1; identify and adjust |
| Tool registration depends on adapter init completing | Medium | Audit `FastMCPServer.register_*` methods; confirm they only register decorators (lazy) |
| `/ready` clients exist that need 200 even during init (e.g. dhara health poller) | Low | Grep callers of `/ready` before flipping semantics |
| Order-of-init side effect in `_initialize_runtime_services` that assumes `/health` is not yet reachable | Low | The init is called from `__init__` (synchronous), so `/health` cannot be polled during init today; behavior change is bounded |
| Wrapper timeout bump masks a real regression in Phase 1 | Low | Phase 3 test catches regression; bump is 60→180, still finite |

## 9. Decision Rule

Phase 1 is the **load-bearing** deliverable. Phase 2 is a one-line
defense-in-depth bump. Phase 3 is a regression test.

Ship Phase 1 alone if Phase 2/3 block. Don't ship without Phase 1.

**Companion plan:** Session-Buddy standardization work was promoted
from the original Phase 4 to
[`2026-08-20-bodai-mcp-surface-standardization.md`](./2026-08-20-bodai-mcp-surface-standardization.md)
on 2026-08-20. It is non-blocking on this plan and ships
independently in mcp-common + session-buddy.

---

## Appendix A: Why not just bump the wrapper timeout?

Two reasons:
1. The wrapper has no way to distinguish "process is starting up" from
   "process is hung." A longer timeout means *longer hangs* before
   crash-loop recovery, which delays operator visibility.
2. The startup is genuinely fragile (OpenSearch PUT 400 in the log
   suggests a real config bug). Adding headroom doesn't fix the
   fragility — it just hides it for 3x longer.

The architectural fix (Phase 1) makes the timeout largely moot.

## Appendix B: Why not move all of `_initialize_runtime_services` into the lifespan?

That would still keep `/health` blocked until the heavy init finishes,
because ASGI lifespan startup runs *before* Uvicorn starts accepting
requests. The only way to unblock `/health` is to register the route on
the ASGI app *before* running the heavy init, which means the heavy
init can't run synchronously inside `MahavishnuApp.__init__`. The
cleanest path is the flag-based `/ready` pattern described in Phase 1.
