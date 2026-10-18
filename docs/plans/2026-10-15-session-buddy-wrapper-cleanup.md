---
status: active
role: implementation
date: 2026-10-15
last_reviewed: 2026-10-15
superseded_by: null
blocks_on: []
topic: session-buddy-cleanup
title: "Session-Buddy Wrapper Cleanup — Delete _lifespan_with_dhara_cleanup"

---

# Session-Buddy Wrapper Cleanup — Delete _lifespan_with_dhara_cleanup

**Date:** 2026-10-15
**Status:** `active`
**Purpose:** Clean up the duplicate BodaiEventsPublisher install path that the 2026-10-04 lifespan-publisher-inline plan identified. The publisher install landed in `session_buddy/server_optimized.py:275` (via the v1.1 plan's Task 4), but `_lifespan_with_dhara_cleanup` at `session_buddy/mcp/server.py:313` was NOT deleted. The wrapper remains a duplicate install path with no callers in CLI startup (the CLI never imports `session_buddy.mcp.server`, so the module-load side-effect at `server.py:~458` never runs).

## Scope (Session-Buddy Repo)

This work lives in the **session-buddy repo**, not mahavishnu. Listed here for cross-repo tracking per the 2026-10-15 plan audit.

### Files to modify

| Path | Change |
|---|---|
| `session_buddy/mcp/server.py` | **Hard-delete** `_init_publisher` (lines ~278-289), `_teardown_publisher` (lines ~294-306), `_lifespan_with_dhara_cleanup` (lines ~313-449, including CAUTION I-10 comment), `_original_lifespan = mcp._lifespan` (line ~455), `mcp._lifespan = _lifespan_with_dhara_cleanup` (lines ~464-465 and surrounding comment). |
| `session_buddy/mcp/server.py` | Slim imports: remove `asynccontextmanager` if unused elsewhere; remove `suppress` from `contextlib` if unused elsewhere; remove the TYPE_CHECKING import of `BodaiEventsPublisher` (now in `server_optimized.py`). KEEP `from ..server_optimized import mcp` (still used by `_apply_tool_profile` to register tools on the live mcp instance). |
| `tests/unit/mcp/test_server_lifespan.py` | Refactor 3 tests to drive `session_buddy.server_optimized.session_lifecycle` directly instead of the deleted wrapper (per original §3 of `2026-10-04-session-buddy-lifespan-publisher-inline.md`). |

### Verification

1. `/health` smoke test: `curl http://127.0.0.1:8678/health` returns HTTP 200 with `bodai_events.ingester_running=True`.
2. Cascade-restart loop healed: launchd wrapper stops killing server every 60s.
3. No regression: `mcp__session-buddy__*` tools work end-to-end (smoke via `mcp__session-buddy__health_check_service`).
4. Tests: `pytest tests/unit/mcp/test_server_lifespan.py` and `pytest tests/unit/test_bodai_events_publisher.py` both pass.

## Provenance

This plan is the operational successor to:

- [`2026-10-04-session-buddy-lifespan-publisher-inline.md`](.archive/2026-10-04-session-buddy-lifespan-publisher-inline.md) — which described the inline approach (now mostly landed via v1.1 Task 4 in `server_optimized.py:275`)
- [`2026-10-02-bodai-task-system-v1.1.md`](../specs/2026-10-02-bodai-task-system-v1.1.md) — whose Task 4 (`_lifespan_with_dhara_cleanup` publisher install) was replaced by the cleaner `server_optimized.py:275` approach

The 2026-10-15 plan audit Cluster 3 resolution noted: "Pick one canonical installation site before declaring done." This is the final cleanup step.

## Resolution Status

- [x] Publisher install in `session_lifecycle` (landed in `session_optimized.py:275` via v1.1 Task 4)
- [ ] **Delete `_lifespan_with_dhara_cleanup` wrapper** (this plan)
- [ ] Slim `server.py` imports (this plan)
- [ ] Refactor `test_server_lifespan.py` to drive `session_lifecycle` directly (this plan)
- [ ] Verify `/health` returns 200 + cascade-restart loop healed (this plan)
