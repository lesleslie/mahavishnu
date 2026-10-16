---
date: 2026-10-04
status: complete
role: superseded
topic: session-buddy-lifespan-publisher-inline
last_reviewed: 2026-10-15
superseded_by: docs/plans/2026-10-15-session-buddy-wrapper-cleanup.md
---

# Plan: Inline BodaiEventsPublisher install into session_lifecycle; delete _lifespan_with_dhara_cleanup

## Context

The session-buddy MCP server is in a launchd-cascade-restart loop. The wrapper script polls `/health`, gets HTTP 503, and kills the server every 60s — producing brief ECONNREFUSED gaps that cause `/mcp` reconnect failures.

The root cause of the 503: `bodai_events` feed reports `ingester_running=False` because **`tasks_events._publisher is None`**. The publisher should be installed by the lifespan during startup, but it isn't, because:

1. `server_optimized.py:287` constructs `mcp = FastMCP("session-buddy", lifespan=session_lifecycle)` — this is the *only* mcp instance the CLI ever starts.
2. `session_buddy/mcp/server.py` defines `_lifespan_with_dhara_cleanup` (which installs the publisher) and at module-load sets `mcp._lifespan = _lifespan_with_dhara_cleanup`.
3. The CLI startup chain (`cli_with_modes → run_server → mcp_common.launch`) **never imports `session_buddy.mcp.server`**, so the module-load side-effect never runs. The bare `session_lifecycle` runs in production → no publisher install → 503 → cascade.

Verified by direct test: `BodaiEventsPublisher.init()` succeeds locally (`_init_ok=True`, `health()=True`), so the Redis substrate is healthy — the only problem is the lifespan never installs the publisher.

User has additionally flagged that **Dhara is no longer a core Bodai component**, so the wrapper named `_lifespan_with_dhara_cleanup` is itself obsolete — its only purpose was Dhara teardown, with the publisher install tacked on later. The right fix is to delete the wrapper and put the publisher install directly in `session_lifecycle`, where it always runs.

**Outcome**: `/health` returns 200; launchd wrapper polls succeed; no more cascade-restart loop; `/mcp` stays continuously reachable.

## Approach

Inline all of `_lifespan_with_dhara_cleanup`'s non-Dhara logic into `session_lifecycle` (the actual lifespan), then delete the wrapper and its module-load side-effect. Dhara registration (still wanted for `register_channel_tracking_tools`) and Dhara publisher `aclose` move into `session_lifecycle`'s post-yield block, where they belong alongside each other.

Per Bodai-wide rule `feedback-no-backwards-compat-pre-1.0.md`: no deprecation aliases, no shims. Hard-delete.

## Changes

### 1. `session_buddy/server_optimized.py` — add publisher + auto-loop to `session_lifecycle`; add Dhara teardown

**In `session_lifecycle`** (currently line ~218-275), add **before** `yield`:

- **Publisher install** (moved from `_lifespan_with_dhara_cleanup:432-434`):
  ```python
  # BodaiEventsPublisher install — moved from mcp/server.py wrapper.
  # The lifespan that production actually runs must install this; relying
  # on a module-load side-effect in mcp/server.py broke the CLI startup
  # path (CLI never imports that module).
  from session_buddy.mcp.events.bodai_events_publisher import BodaiEventsPublisher
  from session_buddy.mcp.tools import tasks_events

  publisher = BodaiEventsPublisher(
      stream=settings.bodai_events.stream,
      consumer_group=settings.bodai_events.consumer_group,
      enabled=settings.bodai_events.enabled,
  )
  await publisher.init()  # swallows transport errors per design
  tasks_events._publisher = publisher
  ```
  Call `get_settings()` once at the top of `session_lifecycle` so we have `settings.bodai_events`. (Currently `session_lifecycle` doesn't read settings — but it needs them now.)

- **AutoCheckpointLoop** (moved from wrapper's loop_enabled block at line ~322-352). Lift the same `mode_cfg = get_mode().get_config(); loop_enabled = getattr(mode_cfg, "enable_auto_checkpoint", True)` gate plus the `AutoCheckpointLoop(...)` construction and `await auto_loop.start()` so the loop runs when mode allows.

**Post-yield block** (currently has `_register_component_to_dhara` task + delayed session init + end_session):

- Add **publisher cleanup** (moved from `_teardown_publisher:294-306`):
  ```python
  if tasks_events._publisher is not None:
      with suppress(Exception):
          await tasks_events._publisher.cleanup()
      tasks_events._publisher = None
  ```
- Add **Dhara publisher aclose** (moved from wrapper line ~444-446):
  ```python
  if _dhara_publisher is not None:
      with suppress(Exception):
          await _dhara_publisher.aclose()
  ```
  Import `_dhara_publisher` from `session_buddy.mcp.tools.profiles`.
- Add **auto_loop.stop()** (moved from wrapper line ~441):
  ```python
  if auto_loop is not None:
      with suppress(Exception):
          await auto_loop.stop()
  ```
  (No change in semantics; auto_loop cleanup just needs to land before the post-yield work so the loop isn't ticking while we tear down the publisher.)

Keep the existing post-yield Dhara registration task (`_register_component_to_dhara`) and `lifecycle_manager.end_session()` cleanup — those are independent.

### 2. `session_buddy/mcp/server.py` — delete wrapper and module-load side-effect

Hard-delete these definitions:
- `_init_publisher` (lines ~278-289)
- `_teardown_publisher` (lines ~294-306)
- `_lifespan_with_dhara_cleanup` (lines ~313-449, including the CAUTION I-10 comment)
- `_original_lifespan = mcp._lifespan` (line ~455)
- `mcp._lifespan = _lifespan_with_dhara_cleanup` (lines ~464-465 and the surrounding comment)

Remove imports that become unused:
- `asynccontextmanager` (still used by `_apply_tool_profile` callers? verify before deleting)
- `suppress` from `contextlib` (still used? verify)
- The TYPE_CHECKING import of `BodaiEventsPublisher` (now in `server_optimized.py`)
- `from ..server_optimized import mcp` — **KEEP** (used by `_apply_tool_profile` to register tools on the live mcp instance)
- `from session_buddy.checkpoint.pending import load_pending as _load_pending` — verify if still used after wrapper delete
- `from session_buddy.core.session_manager import validate_orchestrator_working_dir` — verify if still used after wrapper delete

(`session_buddy/mcp/server.py` will slim down to just the tool-profile dispatch and the mcp re-export. That's fine — the file's purpose is "MCP Server module — imports and exports the mcp instance" per the file docstring.)

### 3. `tests/unit/mcp/test_server_lifespan.py` — drive `session_lifecycle` directly

Two tests currently drive `mcp_server._lifespan_with_dhara_cleanup`:
- `test_lifespan_instantiates_publisher_when_enabled` (~line 257)
- `test_lifespan_clears_publisher_on_exit_when_disabled` (~line 327)

And a third test that patches `_original_lifespan`:
- `test_lifespan_skips_orchestrator_for_invalid_cwd` (~line 66)

After the refactor:

- **`test_lifespan_instantiates_publisher_when_enabled`**: drive `session_buddy.server_optimized.session_lifecycle` directly. The `_noop_lifespan` / `_original_lifespan` patches go away (they were a wrapper-internal detail). Keep the `_fake_init_transport` patch and `settings_stub` fixtures. Assert `tasks_events._publisher is publisher` while inside, `is None` after exit.

- **`test_lifespan_clears_publisher_on_exit_when_disabled`**: same — drive `session_lifecycle` directly with `enabled=False`.

- **`test_lifespan_skips_orchestrator_for_invalid_cwd`**: drive `session_lifecycle` directly with `auto_checkpoint_interval=60`. The `enable_auto_checkpoint=True` mode patch stays. The `_noop_lifespan` / `_original_lifespan` patches go away.

The lifespan's `get_settings()` invocation currently isn't mocked at module level — needs `monkeypatch.setattr("session_buddy.settings.get_settings", lambda: settings_stub)`. The `settings_stub` fixture already exists; just point the mock at the new callsite.

The lifespan's `get_mode()` invocation (for `loop_enabled`) needs `monkeypatch.setattr("session_buddy.modes.get_mode", lambda: _FakeMode())` — same pattern as today.

The lifespan calls `lifecycle_manager.drain_pending_markers()` as an `asyncio.create_task` — that runs in the background and will hit `_clean_pending_dir` (which the fixture already provides).

The lifespan reads `os.getcwd()` to decide whether to call `lifecycle_manager.end_session()` on shutdown — tests need to either (a) run from a git repo or (b) patch `is_git_repository`. Since the existing tests don't patch this and they pass, the cwd must already be a git repo in the test environment. Leave it.

### 4. Verification

After implementation:

1. **Direct test of the lifespan** — write a one-off Python script that imports `session_buddy.server_optimized.session_lifecycle`, runs it with a stub `app`, asserts `tasks_events._publisher` is set inside and cleared after. Confirms the publisher install moved correctly.
2. **`/health` smoke test** — `curl http://127.0.0.1:8678/health` while the live server (or a fresh CLI launch) is running; expect HTTP 200 with `bodai_events.ingester_running=True` reflected indirectly via `aggregate` status `healthy`.
3. **Stop the cascade** — `launchctl unload ~/Library/LaunchAgents/com.mcp.session-buddy.plist`, restart via `python -m session_buddy server start --force`, watch the wrapper log for ~3 minutes; no `killing PID` lines should appear.
4. **Unit tests** — `pytest tests/unit/mcp/test_server_lifespan.py` and `pytest tests/unit/test_bodai_events_publisher.py` both pass.
5. **No regression in /mcp** — `mcp__session-buddy__*` tools work end-to-end (smoke via `mcp__session-buddy__health_check_service`).

## Files modified

- `session_buddy/server_optimized.py` — extend `session_lifecycle`, leave `mcp` construction unchanged
- `session_buddy/mcp/server.py` — delete wrapper, slim imports, keep tool profile dispatch
- `tests/unit/mcp/test_server_lifespan.py` — drive `session_lifecycle` directly instead of the deleted wrapper

## Files NOT modified

- `session_buddy/mcp/events/bodai_events_publisher.py` — no change; the publisher's design already swallows init errors and reports degraded via `_init_ok`
- `session_buddy/mcp/tools/profiles.py` — `_dhara_publisher` global stays; still used by `register_channel_tracking_tools`
- `session_buddy/mcp/tools/tasks_events.py` — `_publisher` slot stays; just gets populated by the new lifespan code
- `launch_with_healthcheck.sh` — no change; with `/health` returning 200, the wrapper stops killing the server

## Key files referenced (read-only)

- `session_buddy/mcp/events/bodai_events_publisher.py:55-77` — `BodaiEventsPublisher.__init__` accepts `(stream, consumer_group, enabled)`
- `session_buddy/mcp/events/bodai_events_publisher.py:80-89` — `init()` swallows exceptions per design (`_init_ok` stays False on failure, lifespan still completes)
- `session_buddy/settings.py` — `get_settings()` returns object with `.bodai_events.{stream,consumer_group,enabled}`
- `session_buddy/modes.py` — `get_mode().get_config().enable_auto_checkpoint` gates the auto-loop
- `session_buddy/server_optimized.py:287` — `mcp = FastMCP("session-buddy", ..., lifespan=session_lifecycle)` is the live instance; don't change the construction site, only the lifespan body
