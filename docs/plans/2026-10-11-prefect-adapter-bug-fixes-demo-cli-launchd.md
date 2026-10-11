# Plan: Fix 3 Prefect adapter bugs + `mahavishnu demo prefect` + `mahavishnu launchd prefect`

## Context

Earlier in this session, we ran the Prefect engine against a live `prefect server` and found 3 real adapter bugs in `mahavishnu/engines/prefect_adapter_impl.py`. The user wants:

- **Fix the bugs** with regression tests pinning each.
- **Build `mahavishnu demo prefect`** as a first-class CLI sub-command, plus 7 stub commands for the other engines/terminals. Mirrors the precedent set by commit `55630b45` (Oct 9, since reverted in an untraceable merge — wire-up must be revert-resistant).
- **Wire Prefect into launchd** via `~/Library/LaunchAgents/com.mcp.mahavishnu.prefect.plist` (user-decided Label), with the **full** key set from `com.mcp.mahavishnu.plist` precedent (memory note `feedback-macos-reboot-launchd-keepalive-cascade.md` warns against the exact `KeepAlive.Crashed=true` cascade shape).
- **User decisions captured** (this turn): Launchd Label = `com.mcp.mahavishnu.prefect`; CLI = `mahavishnu launchd prefect` (single file, no nested `setup/` package); PREFECT_API_URL canonical form = **with `/api` suffix** (existing `_api_key_env` line 785 must be updated to match); demo scope = ship 7 stubs as discovery surface with `--why-stub` flag.

**Critical findings from 3-agent multi-review** (this turn): the draft plan as written would have shipped 6 new bugs (wrong Prefect import path, wrong return type unwrap, env-leak Bug C fix, missing launchd keys, malformed wrapper argv, stale tests). All corrections are listed below; **the plan as originally drafted will not work** — read this version carefully.

## Staged rollout

| Phase | Ships | Reversible? |
|---|---|---|
| **A** — bug fixes + 3 pinning tests + dual-store memory | Independently | Yes (single adapter commit) |
| **B** — `mahavishnu/cli/demo_cli.py` (tmux + prefect + 7 stubs) + wire-up + CLI tests | Builds on A | Yes (single CLI commit) |
| **C** — `mahavishnu/cli/launchd_cli.py` + plist template + launchd e2e tests | Builds on A | Yes (no install until opt-in) |
| **D** — stub real implementations | Deferred | Per-substrate PR |

If launchd misbehaves in C, A and B still ship cleanly.

## Critical files

**Modify**
- `mahavishnu/engines/prefect_adapter_impl.py` — 3 bug fixes (lines ~389, ~760-795, ~853)
- `tests/unit/engines/test_prefect_adapter.py` — update 3 broken existing mocks at lines 415, 446, 480
- `mahavishnu/_main_cli.py` — wire `demo_app` + `launchd_app` (Pattern A, near `_main_cli.py:1508-1524`)

**Create**
- `mahavishnu/cli/demo_cli.py` — module-level Typer `demo_app` with `tmux` (rebuilt from `55630b45`), `prefect` (new, full impl), 7 stubs (`agno`, `llamaindex`, `hatchet`, `pydantic_ai`, `crow`, `goose`, `mock`)
- `mahavishnu/cli/launchd_cli.py` — module-level Typer `launchd_app` with `prefect` sub-command (install/uninstall/status)
- `config/launchd/com.mcp.mahavishnu.prefect.plist` — in-repo template (mirrors `~/Library/LaunchAgents/com.mcp.mahavishnu.plist` **full** key set)
- `tests/unit/engines/test_prefect_adapter_impl.py` — 3 pinning tests
- `tests/unit/cli/test_demo_cli.py` — 5 tmux + 5 prefect tests
- `tests/unit/cli/test_launchd_cli.py` — install/uninstall/status unit tests (mock `launchctl`)
- `tests/integration/test_prefect_launchd_e2e.py` — gated by `requires_prefect`
- `tests/unit/cli/test_cli_wireup_invariants.py` — meta-test asserting `demo_app` and `launchd_app` are registered in `_main_cli`
- `.claude/decisions/2026-10-11-prefect-demo-cli-launchd.md` — 5 recurring rules
- `docs/plans/2026-10-11-prefect-adapter-bug-fixes-demo-cli-launchd.md` — archive after execution

**Cleanup** (gitignored per `crackerjack` canonical patterns, but find+delete for working tree hygiene):
- `mahavishnu/cli/__pycache__/demo_cli.cpython-314.pyc` (stale)
- `tests/integration/__pycache__/test_tmux_adapter_e2e.cpython-314-pytest-9.1.1.pyc` (stale)

## Approach

### Phase A — Fix the 3 adapter bugs

**Bug A** (`prefect_adapter_impl.py:853` in `PrefectAdapter.execute`):

Replace:
```python
state = await _invoke_client_method(
    client, "wait_for_flow_run", flow_run_id, timeout=self.config.timeout_seconds,
)
is_completed = await _maybe_await(state.is_completed())
results = await _maybe_await(state.result()) if is_completed else []
```
with:
```python
# Module-level import at top of file:
from prefect.flow_runs import wait_for_flow_run as _wait_for_flow_run

# In execute(), AFTER `flow_run_id = flow_run.id`:
flow_run = await _wait_for_flow_run(
    flow_run_id, timeout=self.config.timeout_seconds
)
state = flow_run.state  # Optional[State], not the awaited value itself
is_completed = await _maybe_await(state.is_completed()) if state else False
results = await _maybe_await(state.result()) if is_completed else []
```
The function signature from `prefect/flow_runs.py`: `async def wait_for_flow_run(flow_run_id, timeout=10800, poll_interval=None, client=None, log_states=False) -> FlowRun`. **It returns `FlowRun`, not `State`** — call `.state` on the result.

**Bug B** (`prefect_adapter_impl.py:389` in `_flow_run_to_response`):

Add helper and use it for both fields:
```python
def _coerce_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if hasattr(value, "total_seconds"):  # datetime.timedelta
        return float(value.total_seconds())
    if isinstance(value, (int, float)):
        return float(value)
    return None  # strings fail closed, not silently coerced
```
Apply at lines 389 (`total_run_time`) and 389-region (`estimated_run_time`). 
**Side benefit**: clear the misleading `_map_prefect_exception(... PREFECT_API_ERROR)` mapping when Pydantic ValidationError fires — add a specific branch in `_map_prefect_exception` so future Pydantic-mismatch bugs surface as `PREFECT_VALIDATION_ERROR`, not `PREFECT_API_ERROR`.

**Bug C + pre-existing teardown bug** (`prefect_adapter_impl.py:760-795`):

Two changes in `_get_client_context` + `_api_key_env`:

1. Remove the `if self.config.api_key:` guard at line 760. **URL is independent of auth** — always swap `PREFECT_API_URL` inside the env-swap block.
2. **Canonical form**: write `PREFECT_API_URL` with the `/api` suffix (e.g. `http://127.0.0.1:4200/api`). Update both `_api_key_env` line 785 *and* the new always-on swap to use this suffix consistently.
3. **Fix the silent-corrupt teardown**: replace
   ```python
   if saved_api_url is not None:
       os.environ["PREFECT_API_URL"] = saved_api_url
   elif "PREFECT_API_URL" in os.environ:
       del os.environ["PREFECT_API_URL"]   # already correct, but the original code had a missing-body branch
   ```
   The current code has the right intent but the prior fix left a stale pass. Verify on read and reconcile if not del.

Env-mutation stays scoped to `_get_client_context` (a scoped `@contextmanager`) — never mutates `os.environ` at `__init__`/`shutdown`. **Reason: process-global state across test instances** (code-review #4).

**Update 3 existing tests** (`tests/unit/engines/test_prefect_adapter.py:415,446,480`): they mock `mock_prefect_client.wait_for_flow_run = AsyncMock(return_value=mock_state)`. After the fix, the adapter never calls the client method — update to patch `mahavishnu.engines.prefect_adapter_impl._wait_for_flow_run` and return a `FlowRun`-shaped mock with `.state`.

**Pinning tests** (`tests/unit/engines/test_prefect_adapter_impl.py`, new):

| Test | Pins |
|---|---|
| `test_wait_for_flow_run_import_path_is_prefect_flow_runs` | Import must be `from prefect.flow_runs import wait_for_flow_run`, **not** `from prefect import wait_for_flow_run`. Attr-lookup probe. |
| `test_wait_for_flow_run_unwraps_flow_run_not_state` | Mock `_wait_for_flow_run` to return a `FlowRun`-shaped object with `.state.is_completed()`; assert adapter reads `flow_run.state`, not direct. |
| `test_coerce_seconds_with_timedelta_and_float_and_string` | Helper: `timedelta(seconds=2.5) → 2.5`, `1.234 → 1.234`, `None → None`, `"1.5" → None` (fail-closed). Three values × three asserts, no longer just type-hint compat. |
| `test_api_key_env_swaps_url_unconditionally` | Even with `api_key=None`, instantiate adapter, assert `PREFECT_API_URL` set inside `_get_client_context` (use `httpx_mock` to probe env during the call, not after). |
| `test_api_key_env_with_api_suffix_consistency` | Assert `_api_key_env` writes `http://localhost:4200/api` (suffix form), matches new init-time swap. |

### Phase B — `mahavishnu/cli/demo_cli.py` (new)

**Module-level Typer** (Pattern A, per `b7c60e57` executions / `2601a20a` acp / `16513427` jot):

```python
"""mahavishnu demo <engine|adapter> — first-class demo commands.

Re-creates the precedent set by commit 55630b45 (Oct 9, since reverted).
Wire-up: 'mahavishnu demo <x>'. See plan dazzling-waddling-ullman
(/Users/les/.claude/plans/) for the full design.
"""
from __future__ import annotations
import asyncio
import shutil
import typer

demo_app = typer.Typer(help="...", invoke_without_command=True)
```

**Three command types**:
1. `@demo_app.command("tmux")` — rebuild `55630b45` source (precondition check + 50ms spawn + ACK + optional reap).
2. `@demo_app.command("prefect")` — full impl using **`get_settings().prefect`** (not bare `PrefectConfig`, since only the former honors `MAHAVISHNU_PREFECT__*` env vars). Threads `work_pool` into `client.create_flow_run(flow=..., work_pool_name=settings.prefect.work_pool)`. Uses **`prefect.flow_runs.wait_for_flow_run`** for completion. Precondition probe with explicit `timeout=5.0`.
3. `@demo_app.command("<engine>")` × 7 stubs — each 5 lines: docstring, `--why-stub` typer option that prints implementation cost, `typer.echo("not implemented — see plan dazzling-waddling-ullman")`, `raise typer.Exit(0)`. Stub bodies are 5 + `--why-stub` option.

**Reuses** (no invention): `from mahavishnu.core.config import get_settings`; `from mahavishnu.engines.prefect_adapter_impl import PrefectAdapter, process_repositories_flow`; `from prefect.flow_runs import wait_for_flow_run` (correct path).

**Tests** (`tests/unit/cli/test_demo_cli.py`): mirror 5-test pattern from `55630b45` for `tmux`; parallel 5 for `prefect` (precondition / default / `--keep` / `--repos` / `--flow`); one meta-test asserting the module exposes `demo_app` and at least one registered command.

### Phase C — `mahavishnu/cli/launchd_cli.py` + plist template

**Single-file CLI** (no nested package, per `rollback_cli.py` precedent):

```python
launchd_app = typer.Typer(help="Launchd-based always-on substrate management.")
launchd_prefect_app = typer.Typer(help="Prefect server under launchd.")

@launchd_prefect_app.command("install")
def install(): ...
@launchd_prefect_app.command("uninstall")
def uninstall(): ...
@launchd_prefect_app.command("status")
def status(): ...

launchd_app.add_typer(launchd_prefect_app, name="prefect")
```

The 3 commands:
- `install` — interpolate `~/.local/state/mcp/scripts/launch_with_healthcheck.sh` (verify the script exists; if not, instruct user to run `mahavishnu mcp install --healthcheck`), write plist to `~/Library/LaunchAgents/com.mcp.mahavishnu.prefect.plist`, run `launchctl load -w`, print `launchctl list | grep com.mcp.mahavishnu.prefect`.
- `uninstall` — `launchctl bootout gui/$UID/com.mcp.mahavishnu.prefect`, remove plist, clean empty log files.
- `status` — `launchctl list | grep com.mcp.mahavishnu.prefect` + httpx probe of `http://127.0.0.1:4200/api/health` with `timeout=5.0`.

**Plist template** (`config/launchd/com.mcp.mahavishnu.prefect.plist`) — mirror `~/Library/LaunchAgents/com.mcp.mahavishnu.plist` **full** key set (the architecture reviewer caught the original plan missing three keys):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>com.mcp.mahavishnu.prefect</string>
    <key>ProgramArguments</key>
    <array>
      <string>/Users/les/.local/state/mcp/scripts/launch_with_healthcheck.sh</string>
      <string>http://127.0.0.1:4200/api/health</string>
      <string>--timeout</string><string>30</string>
      <string>--</string>
      <string>/Users/les/Projects/mahavishnu/.venv/bin/prefect</string>
      <string>server</string><string>start</string>
      <string>--host</string><string>127.0.0.1</string>
      <string>--port</string><string>4200</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PREFECT_API_URL</key><string>http://127.0.0.1:4200/api</string>
      <key>PREFECT_HOME</key><string>/Users/les/.local/state/prefect</string>
      <key>MAHAVISHNU_PREFECT__API_URL</key><string>http://127.0.0.1:4200/api</string>
      <key>MAHAVISHNU_PREFECT__WORK_POOL</key><string>default</string>
      <key>PATH</key><string>/Users/les/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>EnvironmentFile</key><string>/Users/les/.config/secrets.env</string>
    <key>KeepAlive</key>
    <dict>
      <key>Crashed</key><true/>
      <key>SuccessfulExit</key><false/>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>ThrottleInterval</key><integer>30</integer>
    <key>LimitLoadToSessionType</key><array><string>Aqua</string></array>
    <key>WorkingDirectory</key><string>/Users/les/Projects/mahavishnu</string>
    <key>StandardOutPath</key><string>/Users/les/.local/state/mcp/logs/com.mcp.mahavishnu.prefect.log</string>
    <key>StandardErrorPath</key><string>/Users/les/.local/state/mcp/logs/com.mcp.mahavishnu.prefect.err</string>
  </dict>
</plist>
```

`MAHAVISHNU_AUTOSTART_PREFECT=1` in `~/.config/secrets.env` is the kill switch — `mahavishnu launchd prefect --install` reads it before writing. Default unset → install still works, just informational.

**Verify `launch_with_healthcheck.sh` signature** before installing: signature is `[health-url] [--timeout SECONDS] -- <command> [args...]`. If absent, the install command prints the missing-dependency message instead of writing the plist.

### Phase A/B/C wire-up — `_main_cli.py`

Three greppable markers (the architecture reviewer's "anti-revert marker" suggestion):

```python
# === DEMO SUB-COMMANDS (mahavishnu demo <engine|adapter>) ===
# First added in commit 55630b45 (Oct 9 2026), reverted in an untraceable merge.
# Anti-revert grep:   git grep -n 'DEMO SUB-COMMANDS' mahavishnu/_main_cli.py
# Module docstring:   mahavishnu/cli/demo_cli.py also references this block.
from .cli.demo_cli import demo_app
app.add_typer(demo_app, name="demo")
```
and
```python
# === LAUNCHD SUB-COMMANDS (mahavishnu launchd <service>) ===
# Mirror rollback_cli.py single-file precedent.
from .cli.launchd_cli import launchd_app
app.add_typer(launchd_app, name="launchd")
```

Place next to the existing `jot_app`/`board_app` wiring block. **Mirror the markers** in the docstrings of `mahavishnu/cli/demo_cli.py` and `mahavishnu/cli/launchd_cli.py` so a refactor sees the wire-up from either side.

**Meta-test** (`tests/unit/cli/test_cli_wireup_invariants.py`):
```python
def test_demo_subcommands_wired():
    from mahavishnu._main_cli import app
    assert "demo" in {grp.name for grp in app.registered_groups}

def test_launchd_subcommands_wired():
    from mahavishnu._main_cli import app
    assert "launchd" in {grp.name for grp in app.registered_groups}
```

### Tests (across all phases)

| File | Tests | Gating |
|---|---|---|
| `tests/unit/engines/test_prefect_adapter_impl.py` (new) | 5 bug-fix pinning tests | unit, runs in 1s |
| `tests/unit/engines/test_prefect_adapter.py` (existing) | 3 updated mocks | unit |
| `tests/unit/cli/test_demo_cli.py` (new) | 10 demo CLI tests (5 tmux + 5 prefect) + 1 stub-cmd test | unit |
| `tests/unit/cli/test_launchd_cli.py` (new) | 3 launchd CLI tests (mock `shutil.which`, mock `subprocess.run`) + 1 plist-content test asserting the full key set | unit |
| `tests/unit/cli/test_cli_wireup_invariants.py` (new) | 2 meta-tests asserting `demo` and `launchd` registered in `app.registered_groups` | unit |
| `tests/integration/test_prefect_launchd_e2e.py` (new) | 3 tests: install → wait → uninstall | gated by `requires_prefect` (skip if `PREFECT_API_URL` unset) |

**Marker registration in `pyproject.toml`**: add `"requires_prefect: ..."` at line 484-486 (between `requires_auth:` and `req:`, in the `requires_*` group — NOT between `prefect:` and `requires_network:` as in the draft, which is wrong category).

### Decision capture

`.claude/decisions/2026-10-11-prefect-demo-cli-launchd.md` with 5 rules:

1. **Prefect SDK 3.x adapter fixes** — link to `prefect.flow_runs.wait_for_flow_run`, `.state` unwrap, `_coerce_seconds` helper for SDK `timedelta`. Applies to every 3.x line.
2. **Bug C is `_api_key_env`-scoped, not `__init__`** — env mutations in `_get_client_context`, restored on context exit.
3. **launchd plists copy the full key set** — never cherry-pick; carry `ThrottleInterval`, `RunAtLoad`, `LimitLoadToSessionType`, `KeepAlive.Crashed=true`+`SuccessfulExit=false`. Test against `~/Library/LaunchAgents/com.mcp.mahavishnu.plist`.
4. **Use `get_settings()`, not bare `BaseModel`** — `MAHAVISHNU_PREFECT__*` and similar env prefixes only fire through `MahavishnuSettings` (a `BaseSettings`); bare `PrefectConfig()` ignores them.
5. **Revert-resistant CLI wire-up** — three markers (CLI docstring + `_main_cli.py` comment block + meta-test) all must move together. One absent → CI fails loudly.

### Dual-store memory captures

Per memory `feedback-memories-must-be-dual-stored.md`: cross-cutting rules go to BOTH:

- CC memory: `/Users/les/.claude/projects/-Users-les-Projects-mahavishnu/memory/prefect-3-8-sdk-shape.md` (alias to existing `prefect-adapter-bugs-2026-10-11.md` if a name conflict-free save is possible; otherwise fresh file).
- Session-Buddy: `mcp__session-buddy__store_reflection(content=..., tags=["project", "prefect", "sdk-shape", "bugs-2026-10-11"])`.

### Plan archival

After merge: `cp /Users/les/.claude/plans/dazzling-waddling-ullman.md → docs/plans/2026-10-11-prefect-adapter-bug-fixes-demo-cli-launchd.md` and commit on `main` (per `feedback-keep-plan-files-tracked.md` — git-ignore nothing here).

## Verification

End-to-end checks before exit:

1. **Pin tests green**:
   ```
   pytest tests/unit/engines/test_prefect_adapter_impl.py tests/unit/engines/test_prefect_adapter.py -v
   pytest tests/unit/cli/test_demo_cli.py tests/unit/cli/test_launchd_cli.py tests/unit/cli/test_cli_wireup_invariants.py -v
   ```
2. **Integration gated tests skip cleanly without server**:
   ```
   PREFECT_API_URL= pytest tests/integration/test_prefect_launchd_e2e.py -v
   ```
3. **Live demo works against running server** (the env-var fix from Bug C must be live):
   ```
   PREFECT_API_URL=http://localhost:4200/api python -m mahavishnu.cli demo prefect --repos /Users/les/Projects/mahavishnu
   ```
   Expects: server probe → flow registered → flow run → state printed → View URL.
4. **launchd round-trip**:
   ```
   mahavishnu launchd prefect --install     # opt-in
   launchctl list | grep com.mcp.mahavishnu.prefect   # expect <PID> running
   curl -sS http://127.0.0.1:4200/api/health         # expect true
   mahavishnu launchd prefect --status               # expect loaded + healthy
   mahavishnu launchd prefect --uninstall           # expect gone
   ```
5. **Wire-up invariants**:
   ```
   pytest tests/unit/cli/test_cli_wireup_invariants.py -v
   ```
6. **Quality gate** (CRITICAL — never `-p`):
   ```
   crackerjack run -v
   python scripts/audit_orphans.py    # 7 stubs must register, not appear as orphans
   ```
7. **Memory stores** verified:
   ```
   ls /Users/les/.claude/projects/-Users-les-Projects-mahavishnu/memory/prefect-*
   mcp__session-buddy__quick_search("prefect 3.x SDK shape")
   ```
8. **Plan archived**:
   ```
   ls docs/plans/2026-10-11-prefect-adapter-bug-fixes-demo-cli-launchd.md
   ```

## Out of scope (deferred)

- Real implementations of the 7 stub demo commands (Phase D, per-substrate PRs).
- `mahavishnu launchd <service>` framework for other engines — same pattern once any other service becomes always-on.
- Auto-start `launchctl load -w` on machine boot — the install is opt-in per memory `feedback-macos-reboot-launchd-keepalive-cascade.md`.
- Prefect Cloud mode (`workspace` + `api_key`); plist's `EnvironmentFile` plumbing supports it, but the demo prints a "not implemented — set MAHAVISHNU_PREFECT__WORKSPACE to enable" hint if detected.
