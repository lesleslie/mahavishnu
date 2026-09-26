---
status: active
role: canonical
kind: plan
date: 2026-09-26
last_reviewed: 2026-09-26
superseded_by: null
topic: mcp-launcher-standardization
---

# MCP Launcher Standardization Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans` or `superpowers:subagent-driven-development`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the 4+ bespoke MCP server startup patterns across Bodai's 5 Core components (vishnu/ak/sb/cj/oneiric + mcp-common supporting lib) into one canonical `mcp_common.server.launcher.launch()` helper, then migrate the 20 Bodai-managed standalone MCP servers via a tracker + cookbook pattern.

**Architecture:** New `mcp_common.server.launcher` module with one async `launch()` function. The launcher stays **fully generic** — no oneiric coupling — by accepting a `build_server: Callable[..., FastMCP]` closure that each component implements. The launcher handles: loading `~/.config/secrets.env` into `os.environ`, optionally warming the `settings` health feed with one-shot init (`entities_count > 0` is required for `/health=200` per mcp-common's `HealthFeedState.is_healthy()` decision tree), running FastMCP with `transport="http"` + `uvicorn_config={"timeout_graceful_shutdown": 30}`. Each component's `build_server` closure handles its own auth loading, processor wiring, and feed population per its own conventions.

**Tech Stack:** Python 3.14+, **FastMCP >=4.0.3** (fleet-standard per `BODAI_REPO_REGISTRY.md`), `mcp-common` 0.27.0 (this plan introduces 0.28.0 — bump is **user-owned**, not implementer-owned, per `feedback-mcp-common-version-bump-is-user.md`), Oneiric >=0.21 (for `LayerSettings`/`WorkflowBridge`), `httpx2` (transitive), `uv` for venv management.

**Spec:** This document; cross-references `BODAI_REPO_REGISTRY.md`, `settings/ecosystem.yaml`, `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md`.

**Reference investigation:** 2026-09-26 session + multi-agent plan review (architecture-council + feature-dev:code-explorer, 2026-09-26 03:39Z). Findings captured in §4 below.

## 1. Outcome

A new `mcp_common.server.launcher.launch()` helper is the single source of truth for Bodai MCP server startup. All 5 Core components use it; the 20 Bodai-managed standalone MCP servers have a tracker + cookbook pattern for migration. The wire-up contract (HTTP transport, uvicorn grace timeout, secrets loading, selective health-feed warming for `settings` only) is enforced by the library rather than by per-component reviewer vigilance. By end of Phase 4b, the `oneiric.cli.mcp.mcp_start` vendored bug is also fixed at source so anyone running `oneiric mcp start` directly works.

## 2. Goals

1. **Single canonical launcher.** All 5 Core components start via `launch(build_server=...)` or a 5-line per-component wrapper that calls it.
2. **Launcher is generic.** No oneiric coupling in mcp-common. Component-specific auth loading, processor wiring, and feed population happens inside each component's `build_server` closure.
3. **Dormant bugs fixed at source.** `oneiric.cli.mcp.mcp_start` wires `WorkflowTaskProcessor` and passes `transport="http"` so `oneiric mcp start` works directly.
4. **Wire-up contract enforced.** HTTP transport, uvicorn `timeout_graceful_shutdown=30`, secrets loading, and selective `settings`-only health-feed warming are guaranteed by the launcher.
5. **Honest `/health=200`.** Per `mcp_common.health.feed.is_healthy()`, feeds start at WARMING_UP unless their one-shot init legitimately populates them. Only `settings` (read of settings.yaml) is pre-warmed. `context` and `progress` populate via tool calls.
6. **Audit-completed.** All 21 entries in BODAI_REPO_REGISTRY's standalone MCP table have a written per-repo action item: migrate-now / defer-to-cookbook / out-of-scope.
7. **Backward compat preserved.** Each Core component's public CLI surface + launchd plist `ProgramArguments` keep working. Verified per Backward Compatibility Test Matrix (§7).

## 3. Non-Goals

1. **Unifying per-component CLI surface.** Each repo's `mcp start` argparse shape stays as-is.
2. **Replacing launchd plists.** `launch_with_healthcheck.sh` and the 12 plists are system-level supervision; they stay.
3. **Touching per-component MCP server source.** Only the launch scripts change.
4. **Migrating non-Bodai projects.** `swiftui-ipc-client`, `ARCHIVED/*`, `sites`, `SCRATCH/*`, `mdinject` (desktop app per user 2026-09-26 — not Core) — out of scope.
5. **Building a CLI dispatcher.** Each component keeps its own `mcp` Typer subcommand; launcher is programmatic, not CLI.
6. **Mahavishnu's other startup paths.** Mahavishnu has 4 startup-shaped paths (MCP server, pool worker, cloud worker, task router); plan targets only #1 (MCP). Pool/worker/task-router startup is out of scope.
7. **Bumping mcp-common version.** Per `feedback-mcp-common-version-bump-is-user.md`, the user runs `crackerjack run -p minor` to bump + tag + publish. Plan documents the version bump as a user-owned step, NOT implementer-owned.

## 4. Current Findings (verified by code-explorer + architecture-council reviews, 2026-09-26 03:39Z)

Five bespoke startup shapes (corrected citations):

| Component | Entry point | Pattern |
|---|---|---|
| **vishnu (mahavishnu)** | `scripts/launch_mcp_with_secrets.py:1-90` | `os.execvp` after parsing `~/.config/secrets.env` |
| **oneiric** (vendored CLI) | `oneiric/oneiric/cli/mcp.py:209-336` | Broken — no `WorkflowTaskProcessor` (line 273-277), stdio transport (line 327) |
| **oneiric** (new wrapper) | `scripts/launch_mcp.py` (90 LOC) | Manual `Resolver+LifecycleManager+WorkflowBridge`; pre-warm all 3 feeds; `run_async(transport="http")` |
| **ak (akosha)** | `akosha/akosha/cli.py:368-440` (`_start_server`) | Mode dispatch, `app.run(transport="streamable-http", uvicorn_config={"timeout_graceful_shutdown": 30})` |
| **cj (crackerjack)** | `crackerjack/crackerjack/mcp/server_core.py:480-509` (`_run_mcp_server`) | `mcp_app.run_http_async(host=, port=, uvicorn_config={"timeout_graceful_shutdown": 30})` |
| **sb (session-buddy)** | `python -m session_buddy server start --force` | Subcommand `server` (Typer app `add_typer` in `session_buddy/cli/base.py:317-324`), distinct from `mcp` |

**Uvicorn `timeout_graceful_shutdown=30` sites (4, not 2 — code-explorer catch):**
- `mahavishnu/mcp/lifecycle.py:34`
- `mahavishnu/mcp/crow_server.py:152` (comment-only, but same pattern)
- `akosha/akosha/cli.py:439`
- `crackerjack/crackerjack/mcp/server_core.py:499`
- `session-buddy/session_buddy/server_optimized.py:979`

**Dormant bugs in `oneiric/oneiric/cli/mcp.py` (confirmed by code-explorer):**
- Line 273-277: `build_mcp_server(config=..., auth_config=..., providers=...)` — NO `processor=` kwarg → `RuntimeError: schedule_task requires a processor; none supplied.` at startup.
- Line 327: `await server.run_async(host=host, port=resolved_port)` — NO `transport="http"` → `TypeError: TransportMixin.run_stdio_async() got an unexpected keyword argument 'host'`.
- `oneiric/oneiric/mcp/server.py:61-69` (`_resolve_processor` docstring) explicitly says: *"The current resolver is a pass-through; future production loaders will build a processor from a WorkflowBridge when processor is not supplied."* — confirms this is a known TODO.

**HealthFeedState semantics (code-explorer critical catch):**
- `mcp_common/health/feed.py:202-211`: `is_healthy()` returns `(False, WARMING_UP, [WARMING_UP_EMPTY_FEED])` when `entities_count == 0 AND cycles_total >= 1 AND ingester_running`.
- Only `StatusValue.HEALTHY` (which requires `entities_count > 0`) maps to `/health=200`.
- `mcp_common/health/aggregator.py:94-95`: takes worst-case across all feeds. So pre-warming without `entities_count > 0` keeps `/health` at WARMING_UP/503.
- **Resolution**: only `settings` is a legitimate one-shot init (read of settings.yaml). `context` and `progress` start UNHEALTHY and populate via tool calls.

**Audit count discrepancy (code-explorer catch):**
- `settings/ecosystem.yaml`: **20** entries with `mcp: 3rd-party`, **1** with `mcp: native` (bodai meta).
- `BODAI_REPO_REGISTRY.md` standalone MCP table: **21 entries** (includes `splashstand` which is `mcp: native` in ecosystem.yaml, NOT `mcp: 3rd-party`).
- Resolution: use **20** as the standalone-MCP-server count (ecosystem.yaml is authoritative for "what's wired"); note splashstand as a special case.

**Naming conflict (code-explorer catch):** `mcp_common/server/` already exists (`MCPServerCLIFactory`, `MCPServerSettings`). Adding `mcp_common/mcp/` creates a confusing namespace overlap. **Fix: put `launcher.py` inside the existing `mcp_common/server/` package** — the launcher IS a server launcher, co-located with `MCPServerCLIFactory`.

**Core components (user clarification, 2026-09-26 03:41Z):**
> "vishnu, ak, sb, cj, and oneiric are the core components with mcp-common as a supporting lib"

mdinject is **not** a core component — it's a desktop app. Moved from "migrate-now" to "out-of-scope".

**Repo census (corrected):**
- **Core 5** (migrate-now): vishnu (mahavishnu), ak (akosha), sb (session-buddy), cj (crackerjack), oneiric
- **Foundation**: mcp-common (the launcher lives here)
- **Defer-to-cookbook** (20): archive-org-mcp, cmux-mcp, css-mcp, excalidraw-mcp, graphics-mcp, langsmith-mcp, mailgun-mcp, medium-mcp, neo4j-mcp, opera-cloud-mcp, penpot-api-mcp, porkbun-dns-mcp, porkbun-domain-mcp, raindropio-mcp, scapy-mcp, spline-mcp, splashstand, synxis-crs-mcp, synxis-pms-mcp, unifi-mcp
- **Out-of-scope**: bodai (meta), dhara (no MCP server as of 2026-09-26), fastblocks + jinja2-* (libraries — adopt when they get MCP servers), flowscape (desktop), mdinject (desktop), swiftui-ipc-client (Swift only)

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-001
    title: "Canonical launcher in mcp-common.server.launcher exposes async launch() with HTTP transport + uvicorn grace timeout"
  - id: REQ-002
    title: "Launcher loads ~/.config/secrets.env into os.environ before running"
  - id: REQ-003
    title: "Launcher's launch() signature takes build_server: Callable[..., FastMCP] (variadic) so oneiric's 6-kwarg build_mcp_server works without unpacking"
  - id: REQ-004
    title: "Launcher optionally warms ONLY the 'settings' HealthFeedState feed (with entities_count > 0) when settings.yaml is read; 'context' and 'progress' start unhealthy and populate via tool calls"
  - id: REQ-005
    title: "Launcher's /health body includes 'launcher': 'mcp_common.server.launcher@<version>' for incident triage"
  - id: REQ-006
    title: "Launcher's helpers (load_secrets, warm_settings_feed, run_with_uvicorn_config) are independently unit-tested (TDD)"
  - id: REQ-007
    title: "Launcher passes transport='http' and uvicorn_config={'timeout_graceful_shutdown': 30} to run_async / run_http_async"
  - id: REQ-008
    title: "Launcher module lives at mcp_common/server/launcher.py (NOT mcp_common/mcp/) to avoid namespace overlap with MCPServerCLIFactory"
  - id: REQ-009
    title: "oneiric.cli.mcp.mcp_start wires WorkflowTaskProcessor from settings (dormant bug fixed)"
  - id: REQ-010
    title: "oneiric.cli.mcp.mcp_start passes transport='http' to run_async (dormant bug fixed)"
  - id: REQ-011
    title: "Migration cookbook exists at docs/mcp/launcher-cookbook.md with 4 worked examples (oneiric, vishnu, ak, cj)"
  - id: REQ-012
    title: "Per-server tracker exists at docs/mcp/server-migration-tracker.md with one row per of the 20 standalone MCP servers"
  - id: REQ-013
    title: "Backwards Compatibility Test Matrix enumerates per Core component: public CLI commands + launchd plist ProgramArguments + smoke test command. Phase 4 blocked until matrix is green"
  - id: REQ-014
    title: "Signal-handling smoke test: kill -TERM the running server, verify exit code 0 within timeout_graceful_shutdown window"
  - id: REQ-015
    title: "Audit: per-repo table in tracker covers all 20 standalone MCP servers + the 5 Core components + splashstand special case"
  - id: REQ-016
    title: "Phase 2 commits are split into 2.5a (wrapper-only), 2.5b (vendored transport='http'), 2.5c (vendored processor) to bound the akosha vendored-path regression window"
```

## 5. Implementation Phases

### Phase 1: Implement `mcp_common.server.launcher`

**Goal:** Add the canonical launcher to `mcp-common`. Foundation deliverable. Phase 4 unblocks after this lands.

#### Integration Contract ← Phase 1
- **Triggered from**: any component's `scripts/launch_mcp*.py` after Phase 4 migration; `mcp-common>=0.28.0` import.
- **Returns to / updates**: `os.environ` (secrets injected); a running FastMCP server process; `/health` endpoint exposed at `<host>:<port>/health`.
- **Demonstrable by**: `curl -fsS http://127.0.0.1:8680/health` returns HTTP 200 with body containing `"launcher": "mcp_common.server.launcher@0.1.0"`. Each test in `tests/server/test_launcher.py` passes (`pytest tests/server/test_launcher.py -v`).
- **Rollback signal**: `/health` returns 503 after `--timeout` window; `pytest tests/server/test_launcher.py -v` fails in CI.
- **Observability added**: `/health` body includes `"launcher": "mcp_common.server.launcher@<version>"` so an incident responder can grep which launcher version was running.

**Files (Phase 1):**
- Create: `mcp-common/mcp_common/server/launcher.py` (the helper, ~150 LOC after tests)
- Create: `mcp-common/tests/server/test_launcher.py` (TDD)
- Create: `mcp-common/docs/mcp/launcher-cookbook.md` (migration guide for downstream repos)
- Modify: `mcp-common/mcp_common/server/__init__.py` (re-export `launch`)
- Modify: `mcp-common/mcp_common/__init__.py` (top-level re-export of `launch` from `mcp_common.server`)
- Modify: `mcp-common/CHANGELOG.md` (add 0.28.0 entry — **DO NOT bump `pyproject.toml` version**; user does via `crackerjack run -p minor` per `feedback-mcp-common-version-bump-is-user.md`)

**Tasks (TDD, one step per action — 2-5 minutes each):**

- [ ] **Task 1.1: TDD `load_secrets()`**
  - Test: `tests/server/test_launcher.py::test_load_secrets_parses_export_quoted`, `test_load_secrets_handles_missing_file`, `test_load_secrets_uppercases_keys`, `test_load_secrets_strips_inline_comments_outside_quotes`.
  - Implementation: port `mahavishnu/scripts/launch_mcp_with_secrets.py:42-95` regex/parsing into `mcp_common.server.launcher.load_secrets()`. Reuse the `_LINE_RE` and `_strip_comment` helpers (move to module-level). ~30 LOC.
  - Verify: tests pass.

- [ ] **Task 1.2: TDD `warm_settings_feed()`**
  - Test: `test_warm_settings_sets_entities_count_to_one`, `test_warm_settings_sets_cycles_total_to_one`, `test_warm_settings_returns_healthy_status`, `test_no_warm_means_unhealthy`. CRITICAL: must assert `entities_count > 0` (not just `cycles_total >= 1`) per `mcp_common/health/feed.py:202-211` semantics.
  - Implementation: read settings.yaml once (or accept pre-loaded dict), construct `HealthFeedState(name="settings", ingester_running=True)`, call `record_success(state, entities_count=1)`. Returns the feed state. ~20 LOC.
  - Verify: tests pass.

- [ ] **Task 1.3: TDD `run_with_uvicorn_config()`**
  - Test: `test_run_forwards_transport_http`, `test_run_includes_grace_timeout_default_30`, `test_run_accepts_custom_grace_timeout`. (Note: not using asyncio.run in tests; using `unittest.mock.AsyncMock` for `server.run_async`.)
  - Implementation: thin wrapper. Signature: `async def run_with_uvicorn_config(server, host, port, *, timeout_graceful_shutdown=30)`. Calls `await server.run_async(transport="http", host=host, port=port, uvicorn_config={"timeout_graceful_shutdown": timeout_graceful_shutdown})`. ~20 LOC.
  - Verify: tests pass.

- [ ] **Task 1.4: TDD signal-handling smoke (REQ-014)**
  - Test: `test_run_catches_sigterm_and_exits_zero_within_grace_window` (integration test; spawns the launcher against a trivial FastMCP app, sends SIGTERM, asserts exit code 0 within `timeout_graceful_shutdown` + 5s).
  - Implementation: manual smoke (no code change in launcher); document in cookbook.
  - Verify: test passes against a real FastMCP app.

- [ ] **Task 1.5: Compose `launch()` (top-level entry point — REQ-001..005, REQ-007)**
  - Test: `test_launch_loads_secrets_then_calls_build_server`, `test_launch_passes_warm_settings_feed_when_settings_path_provided`, `test_launch_skips_warm_when_settings_path_is_none`, `test_launch_invokes_run_with_uvicorn_config_default_30`. CRITICAL: signature must use `build_server: Callable[..., Any]` (variadic) per REQ-003 so oneiric's 6-kwarg `build_mcp_server` works without unpacking.
  - Implementation: orchestrate `load_secrets`, optional `warm_settings_feed`, then call `server = await asyncio.to_thread(build_server)` (or however the closure is structured — it's variadic so call with no positional args, OR `**kwargs` if we ever need to pass extras). Then `await run_with_uvicorn_config(server, host, port)`.
  - Signature:
    ```python
    async def launch(
        *,
        build_server: Callable[..., Any],
        component_name: str,
        secrets_path: Path | None = None,
        settings_path: Path | None = None,
        host: str = "127.0.0.1",
        port: int = 8680,
        timeout_graceful_shutdown: int = 30,
    ) -> None:
    ```
  - Verify: tests pass.

- [ ] **Task 1.6: Re-export from `mcp_common.server` and `mcp_common`**
  - `mcp_common/server/__init__.py`: `from .launcher import launch`.
  - `mcp_common/__init__.py`: `from .server.launcher import launch`.
  - Verify: `from mcp_common import launch` works in a fresh Python.

- [ ] **Task 1.7: Write the migration cookbook (REQ-011)**
  - Path: `mcp-common/docs/mcp/launcher-cookbook.md`. Four worked examples:
    1. **oneiric** (has settings.yaml auth + workflow processor): closure calls `build_mcp_server(config=..., auth_config=..., providers=..., processor=_build_processor(), health_feeds=_warm_feeds())`
    2. **vishnu** (has secrets.env + 173-tool profile gating): closure returns `mahavishnu.mcp.server.build_mahavishnu_mcp_app()` with secrets already in os.environ.
    3. **ak** (has mode dispatch + streamable-http): closure calls `akosha.mcp.create_app(mode=mode_instance)`; launcher handles `transport="http"`.
    4. **cj** (no auth — `enabled=False`, no settings.yaml): closure calls `crackerjack.mcp.server_core.create_mcp_server(mcp_config)` with `auth_config=None`.
  - Each example shows: before/after of the launch script, with diff and a "demonstrable by" command.

- [ ] **Task 1.8: Update CHANGELOG (do NOT bump version)**
  - `mcp-common/CHANGELOG.md`: add entry under `[Unreleased]` (user bumps to 0.28.0):
    ```
    Added: `mcp_common.server.launcher` — canonical async launcher for Bodai MCP
    servers. Loads `~/.config/secrets.env`, optionally warms the `settings`
    health feed (one-shot init), runs FastMCP with `transport="http"` +
    `uvicorn_config={"timeout_graceful_shutdown": 30}`. Generic —
    no oneiric coupling. See docs/mcp/launcher-cookbook.md for migration
    patterns.
    ```
  - **DO NOT modify `pyproject.toml` version.** Per `feedback-mcp-common-version-bump-is-user.md`, user bumps via `crackerjack run -p minor`.

- [ ] **Task 1.9: Validate against a real component (smoke test)**
  - In a tmpdir: write a 5-line script calling `launch(build_server=...)` with a trivial FastMCP app, run `curl /health` and assert HTTP 200. Assert `/health` body contains `"launcher": "mcp_common.server.launcher@0.1.0"`.
  - Verify: smoke test passes.

- [ ] **Task 1.10: Commit (no version bump, no tag)**
  ```bash
  git add mcp-common/mcp_common/server/launcher.py \
          mcp-common/mcp_common/server/__init__.py \
          mcp-common/mcp_common/__init__.py \
          mcp-common/tests/server/test_launcher.py \
          mcp-common/docs/mcp/launcher-cookbook.md \
          mcp-common/CHANGELOG.md
  git commit -m "feat(mcp-common): add canonical MCP server launcher (REQ-001..008)"
  ```
  **DO NOT tag or bump version.** User does that via `crackerjack run -p minor` after reviewing this commit.

### Phase 2: Migrate oneiric + fix vendored CLI bug (split into 3 commits)

**Goal:** oneiric adopts the launcher (proof). The vendored CLI bug is fixed at source so anyone running `oneiric mcp start` works directly. **Three separate commits** to bound the akosha vendored-path regression window.

#### Integration Contract ← Phase 2
- **Triggered from**: `~/Library/LaunchAgents/com.mcp.oneiric.plist:18-37` (ProgramArguments).
- **Returns to / updates**: running oneiric MCP server on port 8681; `~/.oneiric/settings.yaml` (settings path consumed); `/health` 200; `oneiric/cli/mcp.py:mcp_start` no longer crashes.
- **Demonstrable by**: `curl -fsS http://127.0.0.1:8681/health` returns HTTP 200 with `"launcher": "mcp_common.server.launcher@0.1.0"`. `oneiric mcp start --foreground` boots cleanly without the wrapper, logs "WorkflowTaskProcessor wired".
- **Rollback signal**: `/health` returns 503 after timeout > 120s; `oneiric mcp start` exits with non-zero within 30s.
- **Observability added**: oneiric's `/health` body now includes `"launcher": "mcp_common.server.launcher@0.1.0"`.

**Tasks:**

- [ ] **Task 2.1: Wrapper-only migration (commit 2.5a)**
  - `oneiric/scripts/launch_mcp.py`: rewrite to ~25 LOC calling `launch(build_server=lambda: _build_server(), component_name="oneiric", secrets_path=Path("~/.config/secrets.env"), settings_path=Path("~/.oneiric/settings.yaml"), host="127.0.0.1", port=8681)`.
  - `_build_server()` constructs `WorkflowTaskProcessor(WorkflowBridge(Resolver(), LifecycleManager(Resolver()), LayerSettings()))` and calls `build_mcp_server(config=..., auth_config=..., providers=..., processor=..., health_feeds=warm_settings_feed(...))` (warm only `settings`, leave `context`/`progress` for tool calls).
  - Verify: smoke test (run wrapper, `curl /health`, see HTTP 200); `/health` body contains `"launcher"`.
  - Live-akosha smoke: `curl -fsS http://127.0.0.1:8682/health` returns 200 (akosha still uses vendored oneiric — must not regress).

- [ ] **Task 2.2: Fix `oneiric/cli/mcp.py:mcp_start` `transport="http"` (commit 2.5b)**
  - Line 327: change `await server.run_async(host=host, port=resolved_port)` to `await server.run_async(transport="http", host=host, port=resolved_port)`.
  - Verify: `oneiric mcp start --foreground` boots without the wrapper.
  - Live-akosha smoke: still 200 (ak uses vendored oneiric — confirm vendored path now also passes `transport="http"`).

- [ ] **Task 2.3: Fix `oneiric/cli/mcp.py:mcp_start` processor wiring (commit 2.5c)**
  - Add `_build_processor_from_settings(settings_path)` helper that constructs `LayerSettings + Resolver + LifecycleManager + WorkflowBridge + WorkflowTaskProcessor` (mirror Phase 1 Task 1.5's pattern, but in oneiric vendored CLI).
  - Pass `processor=_build_processor_from_settings(...)` to `build_mcp_server(...)` at line 273-277.
  - Verify: `oneiric mcp start --foreground` no longer crashes with `RuntimeError: schedule_task requires a processor`.
  - Live-akosha smoke: still 200.

- [ ] **Task 2.4: Add tests for `oneiric/cli/mcp.py` mcp_start path**
  - `tests/cli/test_mcp_start.py`: `test_mcp_start_loads_auth_from_settings`, `test_mcp_start_passes_transport_http`, `test_mcp_start_wires_processor_when_settings_present`.
  - Verify: pytest passes.

- [ ] **Task 2.5: Three separate commits (per commit granularity rule from architecture review)**
  ```bash
  # 2.5a: wrapper-only migration
  git add oneiric/scripts/launch_mcp.py
  git commit -m "feat(oneiric): migrate launcher wrapper to mcp_common.server.launcher (REQ-001..005)"
  # Validate 24-48h before next commit; live-akosha smoke must remain 200.

  # 2.5b: vendored CLI transport fix (after validation period)
  git add oneiric/oneiric/cli/mcp.py
  git commit -m "fix(oneiric): pass transport='http' to vendored CLI's run_async (REQ-010)"

  # 2.5c: vendored CLI processor wiring (after 2.5b validates)
  git add oneiric/oneiric/cli/mcp.py oneiric/tests/cli/test_mcp_start.py
  git commit -m "fix(oneiric): wire WorkflowTaskProcessor in vendored CLI mcp_start (REQ-009)"
  ```

### Phase 3: Audit all repos + tracker

**Goal:** Produce a per-repo action item table covering Core 5, mcp-common, and the 20 standalone MCP servers.

#### Integration Contract ← Phase 3
- **Triggered from**: this plan (reads `BODAI_REPO_REGISTRY.md` + `settings/ecosystem.yaml`).
- **Returns to / updates**: `docs/mcp/server-migration-tracker.md` in mahavishnu (new file) — a table with one row per audited repo.
- **Demonstrable by**: the tracker exists, has rows for all 5 Core + mcp-common + 20 standalone MCP servers + splashstand special case, each row has: `repo`, `current_entry_point`, `migration_status` (`todo` / `in-progress` / `done` / `out-of-scope`), `migrated_at_commit` (when applicable), `notes`.
- **Rollback signal**: N/A (audit, not deployment).
- **Observability added**: future incidents can grep the tracker to find per-repo migration status.

**Tasks:**

- [ ] **Task 3.1: Write audit script (`scripts/audit_mcp_launchers.py` in mahavishnu)**
  - One-shot detection: for each repo in `BODAI_REPO_REGISTRY.md` standalone MCP table, detect MCP server presence (look for `mcp.py`, `mcp/`, `*-mcp` pattern, plist at `~/Library/LaunchAgents/com.mcp.*.plist`).
  - Output: a markdown table the tracker consumes.
  - Verify: script runs in <5s; output has correct row count.

- [ ] **Task 3.2: Create tracker `docs/mcp/server-migration-tracker.md`**
  - Initial population:
    - **Core 5 (migrate in Phase 4a/4b)**: vishnu (Phase 4a), cj (Phase 4a), ak (Phase 4b), sb (Phase 4b discovery subtask first), oneiric (Phase 2 proof done)
    - **mcp-common (foundation, Phase 1)**: launcher module
    - **Defer-to-cookbook (20)**: archive-org, cmux, css, excalidraw, graphics, langsmith, mailgun, medium, neo4j, opera-cloud, penpot-api, porkbun-{dns,domain}, raindropio, scapy, spline, synxis-{crs,pms}, unifi
    - **Special**: splashstand (`mcp: native` in ecosystem.yaml — needs separate investigation per the architecture review's note that some servers have non-FastMCP transport)
    - **Out-of-scope**: bodai (meta), dhara (no MCP server), fastblocks + jinja2-* (libraries), flowscape (desktop), mdinject (desktop), swiftui-ipc-client (Swift)

- [ ] **Task 3.3: Commit tracker + audit script**
  ```bash
  git add scripts/audit_mcp_launchers.py docs/mcp/server-migration-tracker.md
  git commit -m "chore(audit): per-repo MCP launcher action items (REQ-012, REQ-015)"
  ```
  Tracker lives in `mahavishnu/docs/mcp/` (not mcp-common) — mahavishnu is the planning/coordination hub per the Bodai hierarchy.

### Phase 4a: Migrate vishnu + crackerjack (known shapes)

**Goal:** Two known-shape Core components migrated. Each task thin (~15-LOC wrapper change).

#### Integration Contract ← Phase 4a
- **Triggered from**: each component's launchd plist after migration.
- **Returns to / updates**: each component's `scripts/launch_mcp*.py` (or equivalent) collapses to <15 LOC; `/health` includes `"launcher": "mcp_common.server.launcher@0.1.0"`.
- **Demonstrable by**: per component, `curl /health` returns 200 with launcher field present.
- **Rollback signal**: per component, `curl /health` returns 503 OR launchd list shows repeated keepalive restarts.
- **Observability added**: `"launcher"` field in every component's `/health`.

**Tasks:**

- [ ] **Task 4a.1: Migrate vishnu** — replace `mahavishnu/scripts/launch_mcp_with_secrets.py` body with launcher call; delete the regex parsing (now in launcher). Smoke test: `curl /health` on port 8680.

- [ ] **Task 4a.2: Migrate crackerjack** — refactor `crackerjack/mcp/server_core.py:_run_mcp_server` to delegate to launcher. Smoke test: `curl /health` on port 8676.

- [ ] **Task 4a.3: Commit each as separate PR per repo**
  ```bash
  git -C mahavishnu add scripts/launch_mcp_with_secrets.py
  git -C mahavishnu commit -m "feat(mahavishnu): migrate MCP startup to mcp-common launcher (REQ-013)"

  git -C crackerjack add crackerjack/mcp/server_core.py
  git -C crackerjack commit -m "feat(crackerjack): migrate MCP startup to mcp-common launcher (REQ-013)"
  ```

### Phase 4b: Migrate akosha + session-buddy (atypical — discovery needed)

**Goal:** Two atypical Core components migrated. Each gets a discovery subtask FIRST (size estimate before commit granularity).

#### Integration Contract ← Phase 4b
- Same as 4a, but **the Backward Compatibility Test Matrix (REQ-013) must be green for ak and sb before Phase 4b commits land.**

**Tasks:**

- [ ] **Task 4b.1: Discovery subtask for ak (akosha)**
  - Investigate `akosha/cli.py:_start_server` mode dispatch. Determine whether `launch(build_server=...)` closure handles mode selection or whether mode needs to be a launcher kwarg.
  - **Discovery deliverable**: 1-page note (`akosha/.claude/decisions/2026-XX-XX-launcher-mode-dispatch.md`) describing the closure shape + any kwargs the launcher must accept. Block migration until note is committed.

- [ ] **Task 4b.2: Backward Compatibility Test Matrix (REQ-013)**
  - Per Core component: enumerate (a) public CLI commands + args, (b) launchd plist `ProgramArguments`, (c) smoke test command.
  - Save as `mahavishnu/docs/mcp/launcher-backcompat-matrix.md`. Block Phase 4a/4b completion until matrix is green.

- [ ] **Task 4b.3: Migrate ak (akosha)**
  - Apply discovery findings. Migrate `_start_server` to use launcher.
  - Smoke test: `curl /health` on port 8682; also `akosha mcp start --foreground` public CLI smoke.

- [ ] **Task 4b.4: Discovery subtask for sb (session-buddy)**
  - Investigate `python -m session_buddy server start --force` plob subcommand. Determine whether `session_buddy server start --force` is equivalent to `launch(build_server=session_buddy.create_app(...))` or whether the `server` subcommand does additional lifecycle work (signal handling, pid file management, --force semantics).
  - **Discovery deliverable**: 1-page note (`session-buddy/.claude/decisions/2026-XX-XX-launcher-server-subcommand.md`). Block migration.

- [ ] **Task 4b.5: Migrate sb (session-buddy)**
  - Apply discovery findings. Either: (a) replace `session_buddy server start` body with launcher call, preserving `--force` semantics; or (b) keep plob subcommand as-is if it does non-launcher work (signal handlers, etc.).
  - Smoke test: `curl /health` on port 8678; also `python -m session_buddy server start --foreground` smoke.

- [ ] **Task 4b.6: Commit each repo separately**
  - One commit per repo. Block on backcompat matrix being green.

### Phase 5a: Server migration tracker (non-cuttable)

- [ ] **Task 5a.1: Initialize `mahavishnu/docs/mcp/server-migration-tracker.md`**
  - Already created in Phase 3 Task 3.2. Phase 5a maintains it.
  - Each per-server commit in Phase 5b updates one row.

- [ ] **Task 5a.2: Wire tracker into CI**
  - `crackerjack run` (or `pytest -m mcp-server-audit`) re-runs `audit_mcp_launchers.py` and fails if any Core component shows `migration_status: todo` (other rows OK).

### Phase 5b: Per-MCP-server migrations (cuttable)

- [ ] **Task 5b.1: Per-server cookbook-driven commits**
  - For each of the 20 standalone MCP servers: one PR per server, each modifying only `scripts/launch_mcp*.py` (or equivalent) per the cookbook.
  - Update tracker row on merge.
  - **Not all at once.** Stagger by risk profile (cookbook-validated servers first; atypical transports get discovery subtasks).

- [ ] **Task 5b.2: Per-server pattern (cookbook example)**
  ```python
  # one example: css-mcp/scripts/launch_mcp.py
  from pathlib import Path
  from mcp_common.server import launch
  from css_mcp.server import build_app  # whatever the component exposes

  async def main():
    await launch(
      build_server=build_app,
      component_name="css-mcp",
      secrets_path=Path("~/.config/secrets.env"),
      host="127.0.0.1", port=3050,
    )

  if __name__ == "__main__":
    import asyncio; asyncio.run(main())
  ```

## 6. Required Code Changes

```
mcp-common/
├── mcp_common/
│   ├── __init__.py                      [MODIFY] re-export launch from server
│   └── server/
│       ├── __init__.py                  [MODIFY] re-export launch from launcher
│       └── launcher.py                  [CREATE] ~150 LOC after tests
├── tests/server/
│   └── test_launcher.py                 [CREATE] TDD tests
├── docs/mcp/
│   └── launcher-cookbook.md             [CREATE] migration guide (REQ-011)
└── CHANGELOG.md                         [MODIFY] add [Unreleased] entry

oneiric/
├── scripts/
│   └── launch_mcp.py                    [MODIFY] collapse to ~25 LOC using launcher (REQ-001..005)
├── oneiric/cli/
│   └── mcp.py                           [MODIFY] fix processor wiring + transport (REQ-009, REQ-010)
└── tests/cli/
    └── test_mcp_start.py                [CREATE] tests for the vendored fixes

vishnu (mahavishnu)/
└── scripts/
    └── launch_mcp_with_secrets.py       [MODIFY] collapse to launcher call (REQ-013)

cj (crackerjack)/
└── crackerjack/mcp/
    └── server_core.py                   [MODIFY] _run_mcp_server → launcher (REQ-013)

ak (akosha)/
└── akosha/
    └── cli.py                           [MODIFY] _start_server → launcher (REQ-013, after discovery subtask)

sb (session-buddy)/
└── session_buddy/                       [INVESTIGATE first, then MODIFY (REQ-013)]

mahavishnu/
├── scripts/
│   └── audit_mcp_launchers.py           [CREATE] one-shot detection script
├── docs/mcp/
│   ├── server-migration-tracker.md      [CREATE] per-repo status (REQ-012, REQ-015)
│   └── launcher-backcompat-matrix.md    [CREATE] Backward Compatibility Test Matrix (REQ-013)
```

## 7. Validation Matrix

| Tool/command | Expected outcome | Evidence |
|---|---|---|
| `pytest mcp-common/tests/server/test_launcher.py -v` | all tests pass | CI run |
| `python -c "from mcp_common import launch"` | imports cleanly | CI run |
| `curl -fsS http://127.0.0.1:8681/health` (oneiric, post-Phase 2) | HTTP 200, body contains `"launcher": "mcp_common.server.launcher@0.1.0"` | smoke-test log |
| `curl -fsS http://127.0.0.1:8681/health` body | `checks.settings.healthy == true` AND `checks.context.healthy == true` AND `checks.progress.healthy == true` | smoke test (after Claude Code calls tools/list) |
| `curl -fsS http://127.0.0.1:8681/health` body pre-tool-call | `checks.context.healthy == false` (data-feed not yet populated) | smoke test |
| `oneiric mcp start --foreground` (post-Phase 2c) | boots cleanly, logs "WorkflowTaskProcessor wired" | manual smoke |
| `kill -TERM <pid>` of any migrated server | exits 0 within `timeout_graceful_shutdown` + 5s | signal-handling smoke (REQ-014) |
| Live-akosha smoke after each Phase 2 commit | `curl /health` on 8682 still returns 200 | ak vendored-path regression check |
| `python scripts/audit_mcp_launchers.py` (post-Phase 3) | emits table with rows for all 5 Core + mcp-common + 20 standalone MCP + splashstand | `docs/mcp/server-migration-tracker.md` |
| `crackerjack run` (after mcp-common commit) | passes; mcp-common is a transitive dep | CI run |
| Backward Compatibility Test Matrix (post-Phase 4a/4b) | per-component CLI + plist + smoke test green | `mahavishnu/docs/mcp/launcher-backcompat-matrix.md` |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Pre-warm of `context`/`progress` returns WARMING_UP → `/health=503` (code-explorer's catch) | Resolved | Only `settings` is pre-warmed; `context`/`progress` populate via tool calls. Claude Code calls `tools/list` immediately after MCP initialize, populating feeds within seconds. |
| `launch()` signature incompatible with oneiric's 6-kwarg `build_mcp_server` (code-explorer) | Resolved | REQ-003: signature uses `Callable[..., Any]` (variadic). |
| Plan violates user version-bump policy (code-explorer) | Resolved | Task 1.10 explicitly excludes bump + tag. User does via `crackerjack run -p minor`. |
| Naming clash `mcp_common/mcp/` vs existing `mcp_common/server/` (code-explorer) | Resolved | REQ-008: launcher lives at `mcp_common/server/launcher.py`. |
| Phase 2 single commit regresses akosha vendored path | Medium | Task 2.5 split into 2.5a/b/c with 24-48h validation + live-akosha smoke between commits. |
| Phase 4a and 4b assumed to be uniform | Medium | Split into 4a (vishnu + cj known shapes) and 4b (ak + sb discovery). Discovery subtasks per atypical component. |
| Phase 5's 21 plan files is bureaucratic | Medium | Replace with single tracker file (Phase 5a). |
| Feed warming lies about "data flowing" | Medium | Q6 fix: only `settings` is pre-warmed; `context`/`progress` start unhealthy. |
| Backward compat breaks a public CLI | Medium | REQ-013: Backward Compatibility Test Matrix gates Phase 4 completion. |
| launchd KeepAlive cascade after FastMCP upgrade | Low | Signal-handling smoke (REQ-014) catches SIGTERM exit-code regression. |
| FastMCP version drift breaks `run_async` signature | Low | Pin to `>=4.0.3,<5` in launcher docs (no `pyproject.toml` edit since launcher lives in mcp-common). |
| MCP tool picker shows empty window between launcher start and tool registration | Low | Out of scope for this plan (architecture review noted but separate concern). |
| Mahavishnu WorkerManager / pool / task-router overlap | Low | §3 Non-Goals explicitly excludes those startup paths. |
| Audit script lives in mahavishnu but should arguably live in mcp-common | Low | Architecture review noted; we keep it in mahavishnu (planning hub) per tracker decision in Phase 3 Task 3.3. |
| 21 `build_server` closures become 21 places to update when launcher signature changes | Medium | Document `Callable[..., Any]` (variadic) — new optional kwargs are forward-compatible. Cookbook shows the contract. |
| Dhara "out-of-scope" but might regain MCP server | Low | Tracker notes "dhara: out-of-scope as of 2026-09-26; revisit if MCP server is reintroduced." |

## 9. Decision Rule

This plan is **done enough** when:
1. `mcp-common` has `server/launcher.py` with tests passing (`mcp-common` v0.28.0, **user-bumped**).
2. **All 5 Core components** show `"launcher": "mcp_common.server.launcher@0.1.0"` in their `/health` bodies (Phases 2 + 4a + 4b complete).
3. The tracker `docs/mcp/server-migration-tracker.md` exists with all 26 rows (5 Core + mcp-common + 20 standalone).
4. The Backward Compatibility Test Matrix is green for all 5 Core components.
5. The vendored `oneiric.cli.mcp.mcp_start` bug is fixed at source (Phase 2c merged).

If scope pressure forces a cut: **Phase 5b (per-server migrations for the 20 standalone MCP servers) is the most cuttable** — the tracker + cookbook alone are sufficient for downstream maintainers to migrate on their own cadence. Phases 1-4b are non-cuttable; they're the foundation. If `mcp-common>=0.28.0` release coordination fails: Phase 1 ships behind a feature flag (`launch` importable but undocumented); Phase 4 per-repo migrations use `try: from mcp_common.server.launcher import launch` with a fallback to the bespoke launcher.

---

**Plan written by:** writing-plans skill + mahavishnu plan template
**Date:** 2026-09-26 (revised post-multi-agent review 03:45Z)
**Estimated scope:** ~30 tasks across 5 phases (1+5+3+3+2+4+1+2=21 numbered + Phase 5b open-ended). Phase 1 alone is ~10 tasks (TDD); Phase 2 is 5 tasks in 3 commits; Phase 3 is 3 tasks; Phase 4a is 3 tasks (thin); Phase 4b is 6 tasks (4 thin + 2 discovery); Phase 5a is 2 tasks; Phase 5b is open-ended.

**Reviewers' contributions applied:**
- **architecture-council**: Phase 2 split into 2.5a/b/c, Phase 4 split into 4a/b, Phase 5 split into 5a/b, settings-only pre-warm, signal-handling smoke, Backward Compat Test Matrix, "drop load_auth_from_settings from helper surface", version policy preserved, mahavishnu 4-startup-paths excluded explicitly.
- **code-explorer**: signature uses `Callable[..., Any]`, pre-warm must seed `entities_count > 0` (not just cycles_total), launcher lives at `mcp_common/server/` not `mcp_common/mcp/`, 4 uvicorn sites not 2, FastMCP pin to 4.0.3, 20 standalone (not 21) per ecosystem.yaml.
- **user (mdinject correction)**: mdinject moved from migrate-now to out-of-scope.

**See also:**
- [[feedback-oneiric-cli-mcp-loader-gap]] — the bug this plan fixes at source
- [[feedback-oneiric-mcp-health-feed-warmup]] — the 503-cycle-0 pattern this plan fixes
- [[feedback-macos-reboot-launchd-keepalive-cascade]] — the ops incident that surfaced the fragmentation
- [[feedback-mcp-common-version-bump-is-user]] — version bumps are user-owned, not implementer-owned
