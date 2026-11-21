---
status: active
role: implementation
kind: plan
date: 2026-11-21
last_reviewed: 2026-11-21
superseded_by:
blocks_on:
  - docs/specs/2026-11-20-fleet-session-start-status-banners-design.md
topic: fleet-session-status
title: "Fleet SessionStart Status Banners — Implementation Plan"
requirements:
  - id: REQ-FLEETHOOK-001
    title: "Session-Buddy announces itself in every repository at session start"
    implementation_repo: session-buddy
  - id: REQ-FLEETHOOK-002
    title: "The Mahavishnu banner names active pools and their worker counts"
    implementation_repo: mahavishnu
  - id: REQ-FLEETHOOK-003
    title: "mahavishnu_ecosystem_status reports real per-service health"
    implementation_repo: mahavishnu
  - id: REQ-FLEETHOOK-004
    title: "Bodai records the hook surface and rejects registry drift"
    implementation_repo: bodai
  - id: REQ-FLEETHOOK-005
    title: "Session-Buddy lifecycle hooks call the right tools and surface errors"
    implementation_repo: session-buddy
  - id: REQ-FLEETHOOK-006
    title: "Session-Buddy memory-health tools resolve their service and return metrics"
    implementation_repo: session-buddy
  - id: REQ-FLEETHOOK-007
    title: "No banner hook can block session startup"
---

# Fleet SessionStart Status Banners — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code session starts with a truthful Session-Buddy line in every repository, and a Mahavishnu session adds a truthful fleet line with component health and pool counts without blocking the first prompt.

**Architecture:** Two banner hooks, one shared style. Session-Buddy owns a user-global `SessionStart` command hook that probes its own `/health` directly and emits one `systemMessage` line. Mahavishnu keeps its existing pool-bootstrap hook; that hook now adds a banner sibling key after probing the fleet directly from a `services:` config block, enriching the result with `mahavishnu_ecosystem_status` and pool counts on the same MCP session. The public YAML key stays `services`, while the Python model uses a non-colliding internal field with an alias so the config shape matches the spec without colliding with Oneiric.

**Tech Stack:** Python 3.14 in the repos, stdlib-only for the user-global Session-Buddy banner, FastMCP over streamable HTTP for Mahavishnu tool calls, PyYAML for the registry/config loader, pytest for the new regression tests, Claude Code hook envelopes (`SessionStart`, `command`, `systemMessage`).

**Spec:** `docs/specs/2026-11-20-fleet-session-start-status-banners-design.md`

## Global Constraints

- Banner hooks are **synchronous** `SessionStart` **command** hooks. `async: true` hides `systemMessage` from the user; `mcp_tool` hooks are skipped at initial launch.
- stdout must contain **exactly one JSON object** and nothing else. All diagnostics go to stderr.
- The Session-Buddy banner registration uses the explicit five-source matcher `startup|resume|clear|compact|fork`.
- The Session-Buddy banner script is stdlib-only and pinned to an absolute interpreter path; no `uv run` on the session-start path.
- The fleet config uses a public `services:` YAML block, but the Python model may map it through a non-colliding internal field.
- Every probe is bounded; a hung component must not block session start.
- Banner text is a narrow projection only: no raw errors, hostnames, absolute paths, connection strings, or unbounded stack traces.
- New source files carry `from __future__ import annotations`. No `assert` in production, no `print()` in library code, and line length stays at 88.

## Review Focus

1. A component is down when the session starts; the banner must say `UNREACHABLE` and still exit 0. *(Tasks 4, 5)*
2. A component answers 503 with JSON; the banner must say `DEGRADED`, not `UNREACHABLE`. *(Tasks 3, 5)*
3. A component omits `version`; the banner must omit the version entirely, not print `vNone`. *(Tasks 3, 4, 5)*
4. A probe hangs rather than refusing the connection; the deadline must cut it off and the hook must still exit 0 within budget. *(Tasks 4, 5)*
5. The hook fires on `resume`, `clear`, and `fork`, not just `startup`, and the banner must still appear on a second session with the same text. *(Tasks 4, 5)*

## 1. Outcome

A person opening a Claude Code session sees, without asking:

- a Session-Buddy line in every repository, with its own health state;
- a Mahavishnu fleet line in the Mahavishnu repository, with component health and pool counts;
- both hooks exit cleanly and do not delay the first prompt;
- the hook surface is recorded in Bodai, and registry drift fails loudly.

Success is measured by: the banners appear in a real interactive session, the values come from live probes rather than hard-coded text, and a deliberately stopped component flips its line to `UNREACHABLE` or `DEGRADED` as appropriate.

## 2. Goals

1. Repair the Session-Buddy hook scripts so they call the real tools and surface errors instead of silently swallowing them.
2. Ship a Session-Buddy session-start banner that runs in every repository.
3. Teach Mahavishnu how to build a truthful fleet banner from the `services:` config, `mahavishnu_ecosystem_status`, and pool health.
4. Keep the fleet banner on the existing pool-bootstrap hook and the Session-Buddy banner on one registration surface.
5. Record the live hook surface in Bodai and make registry drift fail fast.

## 3. Non-Goals

- Not a monitoring dashboard. This is a point-in-time startup banner, not a replacement for Grafana or `bodai-radar`.
- Not a new daemon or polling loop.
- Not a `SessionEnd` banner.
- Not a push to any remote.
- Not a second fleet-health implementation.
- Not a second Session-Buddy banner registration surface.
- Not a broad refactor of unrelated hook helper libraries.

## 4. Current Findings

- The Session-Buddy hook scripts in `~/.claude/scripts/` call unprefixed tool names and swallow MCP errors, so they can appear successful while doing nothing.
- `session_buddy/core/memory_health.py` still needs the live analyzer path / connection fix so the reflection-health tools report the actual store, not a dead fallback.
- `mahavishnu/core/ecosystem_status.py` currently reports an empty `services` map because the service-config source is missing and the probes run sequentially.
- `mahavishnu_pool_health` already has the raw pool data, but the banner needs a stable summary shape and a version bump once the response grows.
- No hook anywhere emits `systemMessage` yet, so the banner channel is still greenfield.

## 4.5 Requirements

The authoritative requirement IDs live in the frontmatter above. This table is a human-readable mirror for the same seven IDs and the tasks that fulfil them.

| ID | Title | Implemented in | Task |
|---|---|---|---|
| REQ-FLEETHOOK-001 | Session-Buddy announces itself in every repository at session start | session-buddy | Task 4 |
| REQ-FLEETHOOK-002 | The Mahavishnu banner names active pools and their worker counts | mahavishnu | Tasks 3, 5 |
| REQ-FLEETHOOK-003 | `mahavishnu_ecosystem_status` reports real per-service health | mahavishnu | Task 3 |
| REQ-FLEETHOOK-004 | Bodai records the hook surface and rejects registry drift | bodai | Task 6 |
| REQ-FLEETHOOK-005 | Session-Buddy lifecycle hooks call the right tools and surface errors | session-buddy | Task 2 |
| REQ-FLEETHOOK-006 | Session-Buddy memory-health tools resolve their service and return metrics | session-buddy | Task 1 |
| REQ-FLEETHOOK-007 | No banner hook can block session startup | mahavishnu, session-buddy | Tasks 1, 2, 4, 5 |

## 5. Implementation Phases

### Phase 1: Session-Buddy prerequisite fixes

**Goal:** Repair the Session-Buddy surfaces the banner work depends on.
**Tasks:** 1, 2
**Exit criteria:** the memory-health tools return the live store's metrics, and the lifecycle hook scripts call the prefixed tools and surface their errors instead of swallowing them.

#### Integration Contract

- **Triggered from**: `session_buddy_get_reflection_health`, `session_buddy_get_error_hotspots`, `session_buddy_get_cleanup_recommendations`, and the `~/.claude/settings.local.json` hook registrations for `session_buddy_start`, `session_buddy_checkpoint`, `session_buddy_end`, `session_buddy_pre_compact_sync`, `session_buddy_store_reflection`, and `session_buddy__code_ingest_file_impl`.
- **Returns to / updates**: the live reflection store, the memory-health analyzer registration, and the hook scripts under `session-buddy/.claude/hooks/`.
- **Demonstrable by**: `session_buddy_get_reflection_health` returns `success=true` with non-zero reflection metrics, and a stubbed hook run writes the MCP error text to stderr instead of hiding it.
- **Rollback signal**: the metrics payload drops back to zero or the hook scripts again report success after an `Unknown tool` response.
- **Observability added**: stderr carries the actual MCP error text, and the memory-health tools expose the real `total_reflections` / failure kind instead of a dead fallback.

### Phase 2: Fleet health data

**Goal:** `services:` config, `ecosystem_status`, and pool health all report truthfully.
**Tasks:** 3
**Exit criteria:** `mahavishnu_ecosystem_status` returns a non-empty `services` map, and `mahavishnu_pool_health` returns pool names, counts, and a stable status shape.

#### Integration Contract

- **Triggered from**: `mcp__mahavishnu__mahavishnu_ecosystem_status`, `mcp__mahavishnu__mahavishnu_pool_health`, and the `mahavishnu ecosystem status` / `mahavishnu pool health` CLI surfaces.
- **Returns to / updates**: `settings/mahavishnu.yaml`, `MahavishnuSettings`, `EcosystemStatusService`, and the `mahavishnu_pool_health` tool response.
- **Demonstrable by**: a direct `tools/call` to `mahavishnu_ecosystem_status` returns per-service health entries, and `mahavishnu_pool_health` includes pool names and worker counts.
- **Rollback signal**: `services` becomes `{}` again or pool counts disappear from the tool response.
- **Observability added**: `ServiceStatus.reachable` and `ServiceStatus.error` make the report distinguish a timeout, a refused connection, and an unrecognised response.

### Phase 3: Session-start banners

**Goal:** A Session-Buddy session and a Mahavishnu session both emit a truthful, single-line banner on startup.
**Tasks:** 4, 5
**Exit criteria:** the Session-Buddy line appears in every repository, and the Mahavishnu line appears in Mahavishnu with pool counts and component health, including when the backing services are degraded or down.

#### Integration Contract

- **Triggered from**: Claude Code `SessionStart` via `~/.claude/settings.local.json` for Session-Buddy and `mahavishnu/.claude/settings.json` for the fleet banner.
- **Returns to / updates**: the banner hook envelopes — a top-level `systemMessage` sibling and the existing `hookSpecificOutput` payload.
- **Demonstrable by**: a fresh interactive session in a non-Bodai repo shows the Session-Buddy line; a fresh interactive session in `~/Projects/mahavishnu` shows the fleet line and pool summary.
- **Rollback signal**: the banner is silent, duplicates, or exceeds the startup budget.
- **Observability added**: the hook logs one bounded probe result per service to stderr so a slow or failed probe is diagnosable without re-running the session.

### Phase 4: Registry and drift test

**Goal:** Bodai records the hook surface and rejects drift.
**Tasks:** 6
**Exit criteria:** `bodai/config/ecosystem.yaml` lists the hook surface, and a two-way pytest compares that registry to the live trees in `~/Projects/*` and `~/.claude`.

#### Integration Contract

- **Triggered from**: `pytest tests/test_hook_surface_sync.py` in Bodai.
- **Returns to / updates**: `bodai/config/ecosystem.yaml` and `bodai/tests/test_hook_surface_sync.py`.
- **Demonstrable by**: the new pytest passes on a consistent tree and fails if a hook or registration is removed.
- **Rollback signal**: a registry entry goes stale or a hook file moves without the registry changing.
- **Observability added**: the failure message names the missing hook and the path it came from.

## 6. Required Code Changes

- `session_buddy/core/memory_health.py` — fix `get_memory_health_analyzer` to use the live registration / live store path.
- `session_buddy/di/__init__.py` — register `MemoryHealthAnalyzer` so the singleton path is used in production.
- `session_buddy/tests/unit/test_memory_health.py` — assert the production `KeyError` contract and the live-store metric shape.
- `session_buddy/tests/unit/mcp/tools/monitoring/test_memory_health_tools.py` — prove the tools return non-zero metrics.
- `session-buddy/.claude/hooks/sb_*.py` and `pre_compact_sync.py` — move the lifecycle scripts into the repo and fix tool names / stderr handling.
- `~/.claude/settings.local.json` — repoint the five lifecycle hook registrations.
- `session-buddy/plugins/session-buddy/scripts/session_start_status.py` — the canonical Session-Buddy banner script.
- `~/.claude/settings.local.json` — add the Session-Buddy banner registration (single surface only).
- `settings/mahavishnu.yaml` — add the public `services:` block.
- `mahavishnu/core/config.py` — add the internal config field and alias mapping for `services`.
- `mahavishnu/core/ecosystem_status.py` — add `version`, `reachable`, `error`, concurrent probes, and the shared config builder.
- `mahavishnu/mcp/tools/ecosystem_tools.py` — pass the service-config source through to `EcosystemStatusService`.
- `mahavishnu/mcp/server_core.py` — pass the service-config source through to `EcosystemStatusService`.
- `mahavishnu/ecosystem_cli.py` — pass the service-config source through to `EcosystemStatusService`.
- `mahavishnu/tui/app.py` — read the same service-config source instead of hand-building a partial dict.
- `mahavishnu/mcp/tools/pool_tools.py` — extend `mahavishnu_pool_health` with the banner-ready pool summary.
- `mahavishnu/mcp/tool_versions.py` — bump `mahavishnu_pool_health` for the new response shape.
- `mahavishnu/.claude/hooks/mahavishnu-pool-bootstrap.py` — add the fleet banner sibling key to the existing hook.
- `mahavishnu/.claude/settings.json` — widen the existing matcher to the five-source form.
- `bodai/config/ecosystem.yaml` — add the hook registry and the missing `oneiric` component entry.
- `bodai/tests/test_hook_surface_sync.py` — the new two-way registry drift test.

## 7. Validation Matrix

| Command | Expected outcome |
|---|---|
| `cd ~/Projects/session-buddy && .venv/bin/pytest tests/unit/test_memory_health.py tests/unit/mcp/tools/monitoring/test_memory_health_tools.py -v` | PASS |
| `cd ~/Projects/session-buddy && .venv/bin/pytest tests/unit/ -k "sb_hooks or session_start_status" -v` | PASS |
| `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/ -k "ecosystem_status or pool_health or pool_bootstrap" -v` | PASS |
| `cd ~/Projects/bodai && .venv/bin/pytest tests/test_hook_surface_sync.py -v` | PASS |
| `cd ~/Projects/mahavishnu && .venv/bin/python scripts/audit_requirements.py` | the `REQ-FLEETHOOK-001..007` markers are reported as implemented |
| a fresh interactive session in `~/Projects/session-buddy` | the Session-Buddy banner line appears |
| a fresh interactive session in `~/Projects/mahavishnu` | the fleet banner appears |
| a second fresh interactive session in `~/Projects/mahavishnu` | the same fleet banner appears again |
| a fresh interactive session in `~/Projects/mahavishnu` with Session-Buddy stopped | the Session-Buddy line reads `UNREACHABLE` |
| a fresh interactive session in `~/Projects/mahavishnu` with one component degraded or stopped | the affected line reads `DEGRADED` or `UNREACHABLE` as appropriate |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The Session-Buddy banner duplicates if a second registration surface is added later | Medium | Keep the banner on the single user-global registration surface only, and make the drift test assert the exact command string |
| The `services:` YAML block collides with a model field name | Medium | Keep the public YAML key as `services`, but map it through a different internal field name and alias it explicitly |
| A slow probe blocks the first prompt | Low | Use hard timeouts and daemon-threaded probe wrappers so the hook can always exit 0 on time |
| The registry falls out of sync with the live hooks | Medium | The drift test is two-way and compares the full command string, not just the script basename |
| The fleet banner can no longer read component health when Mahavishnu is down | Medium | Keep direct component probes as the primary source and use `mahavishnu_ecosystem_status` as enrichment when reachable |

## 9. Decision Rule

This plan is done when all seven `REQ-FLEETHOOK-001..007` markers are present and `scripts/audit_requirements.py` reports them as implemented; a fresh interactive session in `~/Projects/session-buddy` prints the Session-Buddy banner; a fresh interactive session in `~/Projects/mahavishnu` prints the fleet banner; a second Mahavishnu session prints it again; the same Mahavishnu session with Session-Buddy stopped still prints the Session-Buddy line as `UNREACHABLE`; and `bodai/tests/test_hook_surface_sync.py` fails when a registry entry is removed.

If scope must be cut, cut in this order: Task 6's two-way registry test loses its extra exclusion checks before it loses existence; Task 2 may keep the hook scripts but defer non-essential cleanup; Tasks 3 and 5 must keep the config alias and the banner wiring even if the surrounding diagnostics are trimmed.
