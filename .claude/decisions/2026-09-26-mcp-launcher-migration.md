---
status: active
role: design-note
kind: migration-design
date: 2026-09-26
last_reviewed: 2026-09-26
superseded_by: null
topic: mcp-launcher-migration
phase: 4a-task-4a.1
component: vishnu (mahavishnu)
---

# Vishnu (Mahavishnu) MCP Launcher Migration — Phase 4a Design Note

> **Read-only design sketch** for the implementer. The implementer owns the
> actual code change. This note enumerates: current state, target state, the
> factory function I found (the cookbook's `build_mahavishnu_mcp_app()` does
> **not** exist — see §1), the bridge the closure needs (the launcher
> duck-types on `run_async(transport="http", ...)` but `FastMCPServer` exposes
> `start()`/`run_http_async()` — see §4), and acceptance gates.

**Plan**: `docs/plans/2026-09-26-mcp-launcher-standardization.md` §5 Phase 4a
Task 4a.1 (REQ-013).

**Cookbook**: `docs/mcp/launcher-cookbook.md` Example 2 (secrets-only — no
settings warm).

## 1. Current state (what exists today)

### Entry-point chain

```
launchd plist (com.mcp.mahavishnu.plist)
   └── ~/Library/LaunchAgents/com.mcp.mahavishnu.plist:36-42
       ProgramArguments: [.../launch_with_healthcheck.sh <url> --timeout 180 --
                         .../scripts/launch_mcp_with_secrets.py]
            └── launch_with_healthcheck.sh (109 LOC, polls /health for 180s)
                └── mahavishnu/scripts/launch_mcp_with_secrets.py (93 LOC)
                    1. Read ~/.config/secrets.env (inline regex parser, lines 38-78)
                    2. os.environ.setdefault each parsed key
                    3. os.execvp → <repo>/.venv/bin/python -m mahavishnu mcp start
                        └── mahavishnu/_main_cli.py:719-761 (@mcp_app.command("start"))
                            - maha_app = MahavishnuApp()         (heavy init)
                            - server = FastMCPServer(maha_app)  (sync constructor)
                            - server.start(host, port)          (async → lifecycle.start_server)
                                └── await server.server.run_http_async(host=, port=,
                                        uvicorn_config={"timeout_graceful_shutdown": 30})
                            - /health registered in FastMCPServer.__init__ via
                              mahavishnu.mcp.bootstrap.register_health_endpoint
                              (lines 69-70 + bootstrap.py:264)
```

### What each piece does (1-2 lines)

| Layer | Path | What it does |
|---|---|---|
| **launchd plist** | `~/Library/LaunchAgents/com.mcp.mahavishnu.plist` | Supervises the process; `KeepAlive.Crashed=true` restart policy; sets `MCP_PORT=8680`, `LANG`, `LOG_LEVEL`, `PATH` env vars; `WorkingDirectory=/Users/les/Projects/mahavishnu` |
| **launch_with_healthcheck.sh** | `~/.local/state/mcp/scripts/launch_with_healthcheck.sh` | Wraps the inner script with a 180s `/health` poll loop so launchd's `KeepAlive` doesn't restart the process during MahavishnuApp's heavy init (3+ minute Akosha round-trips per `mahavishnu.mcp.bootstrap.register_health_endpoint:268-291`) |
| **launch_mcp_with_secrets.py** | `mahavishnu/scripts/launch_mcp_with_secrets.py` | Parses `~/.config/secrets.env` (because launchd doesn't source `.zshrc`) and `os.execvp`s to `mahavishnu mcp start` |
| **`mahavishnu mcp start`** | `mahavishnu/_main_cli.py:719-761` | Builds `MahavishnuApp()`, `FastMCPServer(maha_app)`, calls `server.start(host, port)` |
| **`FastMCPServer.start`** | `mahavishnu/mcp/server_core.py:1283-1285` | Delegates to `lifecycle.start_server(self, host, port)` |
| **`start_server` (lifecycle)** | `mahavishnu/mcp/lifecycle.py:14-144` | Applies tool profile, warms `skills_signer` + `plan_index` feeds, calls `server.server.run_http_async(host=, port=, uvicorn_config={"timeout_graceful_shutdown": 30})` |
| **`register_health_endpoint`** | `mahavishnu/mcp/bootstrap.py:264-327` | Registers `/health`, `/healthz`, `/metrics` custom routes on the FastMCP app |

### LOC tally (today)

| File | LOC |
|---|---|
| `mahavishnu/scripts/launch_mcp_with_secrets.py` | **93 LOC** (full file; 38 LOC of that is the inline regex parser `_LINE_RE` + `_strip_comment` + `load_secrets`) |
| `mahavishnu/mcp/server_core.py` (the `FastMCPServer` class + `run_server`) | 1335 LOC total file; `FastMCPServer` class body is 1283-1335 (~52 LOC); `run_server` (lines 1332-1335) is 4 LOC |
| **Total entry-point LOC**: `launch_mcp_with_secrets.py` + `FastMCPServer` class + `start_server` lifecycle helper + `register_health_endpoint` helper | **93 + 52 + 144 + 64 ≈ 353 LOC** (this is the surface Phase 4a touches; the rest of `server_core.py` is the 27 inline tool definitions which are out of scope) |

### Critical fact: actual factory function name

The cookbook Example 2 (line 294) imports
`from mahavishnu.mcp.server import build_mahavishnu_mcp_app`. **That name does
not exist.** The actual surface is:

- **Class**: `FastMCPServer` in
  `mahavishnu.mcp.server_core` (`mahavishnu/mcp/server_core.py:50`).
- **Sync constructor**: `def __init__(self, app=None, config=None)` — line 53.
- **Convenience wrapper**: `async def run_server(config=None)` — line 1332 —
  constructs `FastMCPServer(config)` then calls `server.start()` with no
  host/port (uses defaults 127.0.0.1:3000, which is **wrong** for production —
  the CLI passes the actual host/port from Typer options).

The Phase 4a implementer must **build a fresh `build_server` closure** that
constructs `FastMCPServer(MahavishnuApp())` and returns an object with the
launcher's duck-typed `run_async(transport="http", host=, port=,
uvicorn_config=)` method (see §4 trap #1).

## 2. Target state (after migration, ~30 LOC total)

### New wrapper: `mahavishnu/scripts/launch_mcp.py` (~20 LOC including the
`run_async` adapter — slightly fatter than the cookbook's 10 LOC because of
the bridge):

```python
#!/usr/bin/env python3
"""Launch wrapper for the Mahavishnu MCP server (mcp-common launcher edition).

Phase 4a Task 4a.1 migration. Replaces launch_mcp_with_secrets.py:
- secrets parsing lives at mcp_common.server.launcher.load_secrets (REQ-002)
- secrets_path = ~/.config/secrets.env (same as before)
- os.execvp hop is GONE — the launcher's launch() calls FastMCP's run_async
  in-process; launchd sees a single long-running Python process.

Bridge: the launcher duck-types on `run_async(transport="http", host=, port=,
uvicorn_config=)`. FastMCPServer exposes `start(host, port)` and the inner
FastMCP exposes `run_http_async(...)` — neither matches. The _RunAsyncAdapter
below wraps FastMCPServer so the launcher can drive it. See
.claude/decisions/2026-09-26-mcp-launcher-migration.md §4 trap #1.
"""
from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

from mcp_common.server import launch


class _RunAsyncAdapter:
    """Adapt FastMCPServer to the launcher's duck-typed run_async(transport=, ...) contract."""

    def __init__(self, mhv_server) -> None:
        self._server = mhv_server

    async def run_async(self, *, transport, host, port, uvicorn_config):
        # FastMCPServer.start() runs the full lifecycle (tool profile, feed warm,
        # run_http_async). It honors its own uvicorn_config but ignores the
        # launcher-passed one. We call the inner FastMCP directly so the
        # launcher's timeout_graceful_shutdown (REQ-007) actually wins.
        await self._server.server.run_http_async(
            host=host, port=port, uvicorn_config=uvicorn_config,
        )


def build_server():
    """Closure: returns the configured Mahavishnu MCP server. build_server() takes no args."""
    from mahavishnu.core.app import MahavishnuApp
    from mahavishnu.mcp.server_core import FastMCPServer

    maha_app = MahavishnuApp()
    mhv_server = FastMCPServer(maha_app)
    return _RunAsyncAdapter(mhv_server)


def main() -> int:
    # REQ-014 — explicit SIGTERM handler so the wrapper exits 0 (not -15) on
    # cooperative shutdown. See launcher-cookbook.md "Failure modes" row for
    # why this is load-bearing for incident-response scripts.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    asyncio.run(
        launch(
            build_server=build_server,
            component_name="mahavishnu",
            secrets_path=Path("~/.config/secrets.env"),
            # No settings_path — mahavishnu uses settings/mahavishnu.yaml but
            # the launcher-warmed `settings` feed is for the generic
            # HealthFeedState ("entities_count > 0"). Mahavishnu's /health
            # reports skills_signer + plan_index, not `settings`, so warming
            # a `settings` feed here would be a no-op for the visible body.
            host="127.0.0.1",
            port=8680,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### What gets DELETED

- **The 38-LOC inline regex parser** (`_LINE_RE` line 38, `_strip_comment`
  lines 41-51, `load_secrets()` lines 54-78) — covered by
  `mcp_common.server.launcher.load_secrets()` per Task 1.1.
- **The `os.execvp` indirection** (line 88) — the launcher's secrets
  injection replaces it. The new wrapper keeps the same Python process and
  calls `launch()` directly.

### What STAYS unchanged

- The plist's `ProgramArguments` shape: update **one path** (the script
  filename) but keep the `launch_with_healthcheck.sh http://127.0.0.1:8680/health
  --timeout 180 -- <wrapper>` structure. The healthcheck wrapper is still
  needed because MahavishnuApp + FastMCPServer init takes >60s during cold
  boot (per `mahavishnu.mcp.bootstrap:268-291`).
- The FastMCP factory: `FastMCPServer(MahavishnuApp())` is what we build
  inside the closure. The factory itself is unchanged.
- `mahavishnu/_main_cli.py` (`mahavishnu mcp start` Typer subcommand) —
  untouched. The CLI path remains useful for foreground dev runs.
- `~/.config/secrets.env` — unchanged. Same path, same format (the launcher
  parses the same `export KEY='value'` lines via the moved regex).
- `register_health_endpoint` (`mahavishnu/mcp/bootstrap.py:264`) — but
  **patched to emit `"launcher": "mcp_common.server.launcher@<version>"`**
  per REQ-005. See §4 trap #2.

### What gets PATCHED (new requirement discovered during investigation)

- `mahavishnu/mcp/bootstrap.py:264` (`register_health_endpoint`) — the
  existing body emits `{"status": "ok|degraded", "service": "mahavishnu",
  "version": <version>, "checks": {...}}` but **does NOT include the
  `launcher` field**. The launcher is generic — it doesn't write to `/health`
  (REQ-005 is a consumer-side contract per `launcher-cookbook.md:34-39`).
  Patch:

  ```python
  body = {
      "status": "ok" if all_ok else "degraded",
      "service": "mahavishnu",
      "version": version,
      "launcher": f"mcp_common.server.launcher@{mcp_common.__version__}",  # NEW per REQ-005
      "checks": checks,
  }
  ```

  The patch is one line. It belongs in the same commit as the wrapper (the
  smoke test asserts both the wrapper runs and the field is present).

## 3. Migration steps (numbered, for the implementer agent)

### A. Verify the API

1. Confirm `mahavishnu/mcp/server_core.py:50` exposes `FastMCPServer` with
   sync `__init__(self, app=None, config=None)`. **Verified 2026-09-26** —
   yes (line 53).
2. Confirm the launcher duck-types on `run_async(transport="http", host=,
   port=, uvicorn_config=)`. **Verified** in
   `mcp-common/mcp_common/server/launcher.py:186-191`.
3. Confirm `FastMCPServer` does NOT expose `run_async(...)` directly —
   instead exposes `start(host, port)` (line 1283) which calls
   `lifecycle.start_server` which calls `run_http_async(host, port,
   uvicorn_config={"timeout_graceful_shutdown": 30})`. **Verified 2026-09-26**.
4. **The bridge needed**: a small `_RunAsyncAdapter` class in the wrapper
   that wraps `FastMCPServer` and exposes `run_async(transport=, host=,
   port=, uvicorn_config=)`. The adapter calls the inner FastMCP's
   `run_http_async(...)` directly with the launcher's `uvicorn_config` so
   REQ-007 (timeout_graceful_shutdown=30) actually wins. See §4 trap #1 for
   why the lifecycle helper's hardcoded uvicorn_config is a footgun.

### B. Write new `mahavishnu/scripts/launch_mcp.py`

Use the code block in §2 above. **Replace the file at
`mahavishnu/scripts/launch_mcp_with_secrets.py`** (recommendation: `git mv`
then edit; don't keep both files — they're 93 LOC of pure dead weight after
migration). The new file is ~30 LOC including the adapter class.

### C. Update launchd plist

In `~/Library/LaunchAgents/com.mcp.mahavishnu.plist:36-42`, change the last
`ProgramArguments` entry from:

```
<string>/Users/les/Projects/mahavishnu/scripts/launch_mcp_with_secrets.py</string>
```

to:

```
<string>/Users/les/Projects/mahavishnu/scripts/launch_mcp.py</string>
```

Everything else in the plist stays the same (the `launch_with_healthcheck.sh`
wrapper, `--timeout 180`, the `--` separator, the `EnvironmentVariables`).

### D. Patch `register_health_endpoint` for REQ-005

In `mahavishnu/mcp/bootstrap.py:311-316`, add the `launcher` field to the
`/health` response body:

```python
import mcp_common  # top-of-file alongside existing imports

body = {
    "status": "ok" if all_ok else "degraded",
    "service": "mahavishnu",
    "version": version,
    "launcher": f"mcp_common.server.launcher@{mcp_common.__version__}",  # REQ-005
    "checks": checks,
}
```

### E. Smoke test

```bash
launchctl unload ~/Library/LaunchAgents/com.mcp.mahavishnu.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.mcp.mahavishnu.plist
sleep 5
curl -fsS http://127.0.0.1:8680/health | jq '.checks, .launcher'
```

Assert:
- HTTP 200
- `"launcher": "mcp_common.server.launcher@<version>"` field present
- `checks.skills_signer.ok == true` (or `status == "warming_up"` during cold boot)
- `checks.plan_index.ok == true` (or `status == "warming_up"`)

### F. Backward Compatibility Test Matrix row

Append a per-component row to
`mahavishnu/docs/mcp/launcher-backcompat-matrix.md` (Task 4b.2 deliverable —
does not exist yet; cross-link from your PR description). Row schema:

| Component | Public CLI | Plist ProgramArguments | Smoke test | Status |
|---|---|---|---|---|
| vishnu | `mahavishnu mcp start --host 127.0.0.1 --port 8680` | `[launch_with_healthcheck.sh, http://127.0.0.1:8680/health, --timeout, 180, --, .../scripts/launch_mcp.py]` | `curl -fsS http://127.0.0.1:8680/health \| jq .launcher` | green |

The CLI row is preserved because `_main_cli.py` is untouched — the `mahavishnu
mcp start` Typer command still works as a foreground dev runner.

## 4. Risks and unknowns

### Trap #1: `FastMCPServer.start()` ignores the launcher's `uvicorn_config`

`mahavishnu/mcp/lifecycle.py:137-144` hardcodes
`uvicorn_config={"timeout_graceful_shutdown": 30}` when calling
`server.server.run_http_async(...)`. If the closure calls
`server.start(host=, port=)` (the public method), the launcher's
`timeout_graceful_shutdown` setting is silently overridden (start() ignores
kwargs except `host` and `port`). The adapter in §2 bypasses the lifecycle
helper and calls `server.server.run_http_async(host, port, uvicorn_config)`
directly with the launcher-passed config, so REQ-007 holds.

**Alternative considered**: monkey-patching `start()` to accept
`uvicorn_config` — rejected because it requires touching
`lifecycle.start_server` for a behavior that the launcher now owns.

### Trap #2: `register_health_endpoint` does not emit the `launcher` field

Per REQ-005 (consumer contract, not launcher contract — see
`launcher-cookbook.md:34-39`), every component's `/health` route must include
`"launcher": "mcp_common.server.launcher@<version>"`. Mahavishnu's existing
`register_health_endpoint` (`mahavishnu/mcp/bootstrap.py:264-327`) emits
`{status, service, version, checks}` but no `launcher` field. The smoke test
in §3.E asserts the field is present — without the one-line patch in §3.D,
the assertion fails. The patch is in scope for Phase 4a (it's a single line
that closes the wire-up contract for this component).

### Trap #3: the cookbook's Example 2 imports `build_mahavishnu_mcp_app` which
does not exist

`launcher-cookbook.md:294` has:
`from mahavishnu.mcp.server import build_mahavishnu_mcp_app`. There is no
`build_mahavishnu_mcp_app` in this codebase. The actual surface is
`FastMCPServer` in `mahavishnu.mcp.server_core`. The implementer must NOT
trust the cookbook verbatim — use the import path above (`from
mahavishnu.mcp.server_core import FastMCPServer`) and adapt the closure body
to the `_RunAsyncAdapter` shape in §2.

### Trap #4: maha_app init blocks >60s on cold boot

`MahavishnuApp()` triggers Akosha round-trips + OpenSearch init that
real-warmly takes 3+ minutes per the comment at
`mahavishnu/mcp/bootstrap.py:285-286`. The `launch_with_healthcheck.sh`
180s timeout was added specifically to absorb this. **Do NOT delete the
shell wrapper** — the new plist entry keeps the
`launch_with_healthcheck.sh -- ...` shape. The `launcher-cookbook.md` smoke
test sleeps only `sleep 3` after `launchctl load`, which assumes a
pre-warmed state; on a cold boot, wait at least `sleep 180` before the
`curl`.

### Other paths out of scope (reiterating §3 Non-Goals of the plan)

Mahavishnu has 4 startup-shaped paths:

1. **MCP server** — the path this note migrates. In scope.
2. **Pool worker** — `mahavishnu/pools/mahavishnu_pool.py`, `session_buddy_pool.py`, `runpod_pool.py`. Not a FastMCP server; out of scope.
3. **Cloud worker** — `mahavishnu/workers/cloud_worker.py` (OpenAI-compatible HTTP client). Not a FastMCP server; out of scope.
4. **Task router** — `mahavishnu/core/model_routing.py` (Phase 3b atomic migration from `mahavishnu/workers/task_router.py`). Pure routing config; not a server; out of scope.

Per the plan §3 Non-Goals item 6, only path #1 (MCP server) is in scope. The
implementer must NOT touch pool/worker/task-router startup code.

## 5. Acceptance gates for the implementer

Five-gate pattern matching Phase 1 commit:

1. **Gate 1 — dep install**: `python -c "from mcp_common.server import launch"` exits 0 (mcp-common >= 0.28.0 required; user bumps, per `feedback-mcp-common-version-bump-is-user.md`).
2. **Gate 2 — wrapper imports cleanly**: `python -c "import importlib.util; assert importlib.util.spec_from_file_location('launch_mcp', 'mahavishnu/scripts/launch_mcp.py') is not None"` exits 0 (no syntax errors).
3. **Gate 3 — main() is async-compatible**: `python -c "import ast; tree = ast.parse(open('mahavishnu/scripts/launch_mcp.py').read()); assert any(isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(tree)) or any(isinstance(n.value, ast.Call) and getattr(n.value.func, 'id', '') == 'asyncio' for n in ast.walk(tree))"` exits 0 (confirms `asyncio.run` bridge exists).
4. **Gate 4 — /health contract**: After `launchctl unload && launchctl load && sleep 5`, `curl -fsS http://127.0.0.1:8680/health | jq -e '.launcher'` exits 0 (the new field is present; REQ-005).
5. **Gate 5 — ruff clean**: `ruff check scripts/launch_mcp.py mahavishnu/mcp/bootstrap.py` exits 0.

## 6. Commit sketch (NOT to be made by this design-note writer)

```bash
# Inside mahavishnu repo:
cd /Users/les/Projects/mahavishnu

git -c user.email=les@wedgwoodwebworks.com -c user.name=les \
    mv scripts/launch_mcp_with_secrets.py scripts/launch_mcp.py
# (then edit scripts/launch_mcp.py to the §2 body)

git -c user.email=les@wedgwoodwebworks.com -c user.name=les \
    add scripts/launch_mcp.py mahavishnu/mcp/bootstrap.py

git -c user.email=les@wedgwoodwebworks.com -c user.name=les \
    commit -m "feat(mahavishnu): migrate MCP startup to mcp-common launcher (REQ-013)

- Collapse scripts/launch_mcp_with_secrets.py (93 LOC) to launch_mcp.py (~30 LOC)
  using mcp_common.server.launcher.launch() per plan
  docs/plans/2026-09-26-mcp-launcher-standardization.md §5 Phase 4a Task 4a.1.
- Bridge FastMCPServer (sync __init__, no run_async method) to the launcher's
  duck-typed run_async(transport='http', ...) contract via _RunAsyncAdapter
  (calls inner FastMCP run_http_async with launcher-passed uvicorn_config so
  REQ-007 timeout_graceful_shutdown=30 holds).
- Patch register_health_endpoint to emit 'launcher' field per REQ-005.
- Plist path update is operator-side (~/Library/LaunchAgents/com.mcp.mahavishnu.plist)
  and documented in .claude/decisions/2026-09-26-mcp-launcher-migration.md §3.C."
```

Plist path update (operator-side, not in the commit):

```bash
# After the commit lands:
launchctl unload ~/Library/LaunchAgents/com.mcp.mahavishnu.plist 2>/dev/null
# Edit the plist: change the trailing string entry from launch_mcp_with_secrets.py
# to launch_mcp.py (sed -i '' 's|launch_mcp_with_secrets.py|launch_mcp.py|'
# ~/Library/LaunchAgents/com.mcp.mahavishnu.plist).
launchctl load ~/Library/LaunchAgents/com.mcp.mahavishnu.plist
sleep 5
curl -fsS http://127.0.0.1:8680/health | jq .launcher
# expect: "mcp_common.server.launcher@<version>"
```

## Files touched by the implementer

| Path | Change | LOC delta |
|---|---|---|
| `mahavishnu/scripts/launch_mcp_with_secrets.py` | **DELETE** | -93 |
| `mahavishnu/scripts/launch_mcp.py` | **CREATE** (use §2 body) | +30 |
| `mahavishnu/mcp/bootstrap.py` | **MODIFY** line 311 (add `launcher` field) | +2 (one import + one line) |
| `~/Library/LaunchAgents/com.mcp.mahavishnu.plist` | **MODIFY** line 41 (rename script) | 0 |
| `mahavishnu/docs/mcp/launcher-backcompat-matrix.md` | **APPEND ROW** (Task 4b.2 deliverable; cross-link from PR) | +1 row |

**Net LOC delta**: -93 + 30 + 2 = **-61 LOC** (≈63% reduction in launcher
surface area).

## Cross-references

- Plan: `docs/plans/2026-09-26-mcp-launcher-standardization.md` §5 Phase 4a
  Task 4a.1 (line 334); §3 Non-Goals item 6 (line 46) — pool/worker/task-router
  explicitly excluded.
- Plan: §4.5 Requirements — REQ-001, REQ-002, REQ-003, REQ-007, REQ-013,
  REQ-014.
- Cookbook: `docs/mcp/launcher-cookbook.md` Example 2 (lines 234-329);
  "Failure modes" rows at 552-561 (especially the SIGTERM returncode=-15
  handler note).
- Launcher source: `mcp-common/mcp_common/server/launcher.py:199-264`
  (`launch()` signature; `run_with_uvicorn_config()` at line 162 duck-types
  on `run_async(transport="http", host=, port=, uvicorn_config=)`).
- Factory surface (verified): `mahavishnu/mcp/server_core.py:50-53`
  (`FastMCPServer.__init__`); line 1283-1285 (`FastMCPServer.start`);
  line 1332-1335 (`async def run_server`).
- Health route (patch target): `mahavishnu/mcp/bootstrap.py:264-327`
  (`register_health_endpoint`); current body is lines 311-316, missing the
  `launcher` field.
- Lifecycle (out of scope to modify): `mahavishnu/mcp/lifecycle.py:14-144`
  (`start_server`).
- CLI (out of scope to modify): `mahavishnu/_main_cli.py:719-761`
  (`@mcp_app.command("start")`).
- Launchd plist: `~/Library/LaunchAgents/com.mcp.mahavishnu.plist`
  (ProgramArguments lines 36-42).
