# Doc Status Sync and Session-Buddy Channel Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synchronize all plan documents to match actual codebase state (most "deferred" items are already implemented), then implement the one genuinely missing feature: Session-Buddy Channel Phase 2 Dhara time-series publishing.

**Architecture:** Two independent work tracks. Track A is pure documentation: PLAN_INDEX entries, stale checkboxes, and an ARCHITECTURE.md update — no code changes. Track B adds a `DharaChannelPublisher` (thin `httpx` wrapper) to `channel_tracking_tools.py` and wires it through the session-buddy MCP server startup.

**Tech Stack:** Track A — markdown edits only. Track B — `httpx` (already in session-buddy), `asyncio.create_task` for fire-and-forget, `pytest-asyncio`, `unittest.mock`.

______________________________________________________________________

## Why These Changes

Investigation revealed:

- `PoolManager._persist_pool_state` and `_persist_routing_decision` are already called at spawn, route, and close (deferred P2 items are done in code).
- `scripts/migrate_config_to_project.py` (241 lines, 8 tests) and all CLI config commands already exist (config consolidation is done).
- `HatchetAdapterImpl` exists at `mahavishnu/engines/hatchet_adapter_impl.py` (P10 is done in code).
- `TerminalWorkerProtocol` and the `TerminalAIWorker` shim are both merged (T1/T4 done).
- `docs/architecture/ARCHITECTURE.md` still says "Last Updated: 2026-05-02" and has zero Dhara mentions — it is the only doc that needs a real content addition.
- Session-Buddy `channel_tracking_tools.py` is purely in-memory — Dhara publishing is the one genuinely-unimplemented feature.

______________________________________________________________________

## File Map

### Track A — Documentation

| Action | Path | Change |
|--------|------|--------|
| Modify | `docs/plans/PLAN_INDEX.md` | Fix status of Remaining Work, Terminal Unification, Hatchet entries; update Current Implementation Priority block |
| Modify | `docs/superpowers/plans/2026-05-08-hatchet-adapter.md` | Tick all 8 task checkboxes |
| Modify | `docs/plans/2026-05-07-mahavishnu-master-backlog.md` | Mark P2 deferred PoolManager/RoutingDecisionBuffer/arch-doc items delivered |
| Modify | `docs/superpowers/plans/2026-04-26-config-consolidation.md` | Tick all checkboxes; add delivered header note |
| Modify | `docs/architecture/ARCHITECTURE.md` | Add Dhara Persistence Layer section; update Last Updated date |

### Track B — Session-Buddy Channel Phase 2

| Action | Path | Change |
|--------|------|--------|
| Modify | `session_buddy/mcp/tools/session/channel_tracking_tools.py` | Add `DharaChannelPublisher`; add optional `dhara_publisher` param to `register_channel_tracking_tools` |
| Modify | `session_buddy/mcp/server.py` | Read `SESSION_BUDDY_DHARA_URL` env var; pass `DharaChannelPublisher` to registration |
| Modify | `tests/unit/test_channel_tracking_tools.py` | Add 5 Phase 2 tests covering publish on start/heartbeat/end, skip when no publisher, error tolerance |

______________________________________________________________________

## Track A: Documentation Housekeeping

### Task 1: Fix PLAN_INDEX.md stale entries

**Files:**

- Modify: `docs/plans/PLAN_INDEX.md`

- [ ] **Step 1: Update Remaining Work Execution Order entry**

Find this block (around line 83):

```
### Remaining Work Execution Order

- Plan: [2026-05-11-remaining-work-execution-order.md](./2026-05-11-remaining-work-execution-order.md)
- Status: `active`, `implementation`
- Use for: the prioritized queue for the remaining convergence, terminal, and cleanup work after inventory reconciliation.
- Current implementation note: tracks only tasks still open as of 2026-05-11; completed and historical plans are omitted.
```

Replace with:

```
### Remaining Work Execution Order

- Plan: [2026-05-11-remaining-work-execution-order.md](./2026-05-11-remaining-work-execution-order.md)
- Status: `complete`, `historical`
- Use for: historical record of the post-convergence execution queue. All tasks (T1 TerminalWorkerProtocol, T4 TerminalAIWorker shim, C6a Crackerjack contracts, C6b complexity reduction, C7 docs cleanup) are complete as of 2026-05-13.
```

- [ ] **Step 2: Update Terminal Worker Unification entry**

Find this block (around line 98):

```
### Terminal Worker Unification

- Plan: [2026-05-10-terminal-worker-unification-plan.md](./2026-05-10-terminal-worker-unification-plan.md)
- Status: `active`, `implementation`
- Use for: collapsing provider-specific branching in terminal-based AI workers behind a shared provider-neutral protocol while preserving current defaults and optional non-default support until the shared contract is fully covered.
- Current implementation note: this is a separate refactor track from the MiniMax migration. T0, T2, and T3 are complete; the remaining work is shared-protocol extraction and legacy-branch retirement. It should consume the existing `generic_shell.py` path, reduce special cases in `terminal.py`, and keep `terminal-*` workers registry-driven rather than provider-default driven.
```

Replace with:

```
### Terminal Worker Unification

- Plan: [2026-05-10-terminal-worker-unification-plan.md](./2026-05-10-terminal-worker-unification-plan.md)
- Status: `complete`, `historical`
- Use for: historical record of the terminal worker unification. All phases T0–T4 complete as of 2026-05-13. `TerminalWorkerProtocol` lives in `workers/protocol.py`; `TerminalAIWorker` is a 65-line shim over `GenericShellWorker`.
```

- [ ] **Step 3: Update Hatchet Integration entry**

Find this block (around line 229):

```
### Hatchet Integration

- Backlog: [2026-05-07-mahavishnu-master-backlog.md](./2026-05-07-mahavishnu-master-backlog.md) — Priorities 7, 8, 10
- Status: `active`, `implementation` — P7 (rate-limiting pattern) and P8 (approval durable wait) are plan-only; P10 (HatchetAdapter) requires spec first
- Hatchet is an MIT-licensed durable task queue on Postgres (<20ms start, per-key rate limiting, WaitForEvent). P7 and P8 are pattern borrows (no SDK dependency). P10 adds `hatchet-sdk` and a full `OrchestratorAdapter` implementation gated on `adapters.hatchet: true`.
- Use for: P7/P8 implementation details are inline in the backlog. P10 spec file path: `docs/plans/2026-05-07-hatchet-adapter-spec.md` (to be written).
```

Replace with:

```
### Hatchet Integration

- Plan: [docs/superpowers/plans/2026-05-08-hatchet-adapter.md](../superpowers/plans/2026-05-08-hatchet-adapter.md)
- Backlog: [2026-05-07-mahavishnu-master-backlog.md](./2026-05-07-mahavishnu-master-backlog.md) — Priorities 7, 8, 10
- Status: `complete`, `historical`
- Use for: historical record. P7 (sliding-window rate limiter in `task_router.py`), P8 (durable approval persistence to Dhara), and P10 (`HatchetAdapterImpl` in `mahavishnu/engines/hatchet_adapter_impl.py` with `WaitForEvent` approval bridge) are all delivered as of 2026-05-08.
```

- [ ] **Step 4: Update Current Implementation Priority block**

Find the block starting with `## Current Implementation Priority` (around line 255). Replace the first paragraph and intro:

```
## Current Implementation Priority

*Last verified: 2026-05-14. All backlog priorities (P0–P10) and convergence phases (C0–C7) are complete. The remaining-work execution queue is also complete (T1/T4 merged 2026-05-13).*

**No active implementation queue.** Open work:
- Session-Buddy Channel Phase 2 (Dhara time-series publishing) — tracked in `docs/superpowers/plans/2026-05-14-doc-sync-and-channel-phase2.md`
- OpenWebUI P9 manual UI steps (tool registration in OpenWebUI Admin, model arena run) — no code changes required
- Bodai Agent Platform I4 optional extensions — gated on product justification document

**Historical priorities** (delivered by 2026-05-08, listed below for reference only):
```

- [ ] **Step 5: Verify the file is valid markdown**

```bash
grep -n "Status:" docs/plans/PLAN_INDEX.md | head -20
```

Expected: every status line shows either `complete`, `shipped`, `partial`, or `active` — no entry should show the old stale `active, implementation` for terminal/remaining-work/hatchet.

- [ ] **Step 6: Commit**

```bash
git -C /Users/les/Projects/mahavishnu add docs/plans/PLAN_INDEX.md
git -C /Users/les/Projects/mahavishnu commit -m "docs: update PLAN_INDEX — terminal, remaining-work, and hatchet entries now complete/historical"
```

______________________________________________________________________

### Task 2: Tick Hatchet adapter plan checkboxes

**Files:**

- Modify: `docs/superpowers/plans/2026-05-08-hatchet-adapter.md`

The code was shipped 2026-05-08 but none of the 8 tasks had their checkboxes ticked.

- [ ] **Step 1: Tick all checkboxes**

Run a global replace in `docs/superpowers/plans/2026-05-08-hatchet-adapter.md`:

```bash
sed -i '' 's/- \[ \] \*\*Step/- [x] **Step/g' /Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-05-08-hatchet-adapter.md
```

- [ ] **Step 2: Verify**

```bash
grep -c "- \[ \]" /Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-05-08-hatchet-adapter.md
```

Expected: `0`

```bash
grep -c "- \[x\]" /Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-05-08-hatchet-adapter.md
```

Expected: `40` (5 steps × 8 tasks)

- [ ] **Step 3: Commit**

```bash
git -C /Users/les/Projects/mahavishnu add docs/superpowers/plans/2026-05-08-hatchet-adapter.md
git -C /Users/les/Projects/mahavishnu commit -m "docs: tick all hatchet adapter plan checkboxes — delivered 2026-05-08"
```

______________________________________________________________________

### Task 3: Mark P2 deferred backlog items delivered

**Files:**

- Modify: `docs/plans/2026-05-07-mahavishnu-master-backlog.md`

The three P2 deferred items are actually implemented. `PoolManager._persist_pool_state` is called at spawn (line 242), route (line 370/466), and close (line 542). `ARCHITECTURE.md` will be updated in Task 5.

- [ ] **Step 1: Update the P2 deferred PoolManager task**

Find:

```
- [ ] Wire `PoolManager` to checkpoint pool health + active worker list to Dhara on change — deferred
```

Replace with:

```
- [x] Wire `PoolManager` to checkpoint pool health + active worker list to Dhara on change — `_persist_pool_state` called in `spawn_pool`, `route_task`, and `close_pool`; `_persist_routing_decision` called in `route_task` (verified 2026-05-14)
```

- [ ] **Step 2: Update the P2 deferred RoutingDecisionBuffer task**

Find:

```
- [ ] Wire `RoutingDecisionBuffer` to persist routing decisions to Dhara — deferred
```

Replace with:

```
- [x] Wire `RoutingDecisionBuffer` to persist routing decisions to Dhara — `PoolManager._persist_routing_decision` covers this at the routing site; `RoutingDecisionBuffer` itself remains in-memory (ring buffer for live queries only, not the persistence layer) (verified 2026-05-14)
```

- [ ] **Step 3: Update the P2 arch doc task**

Find:

```
- [ ] Update `docs/architecture/ARCHITECTURE.md` with Dhara persistence layer — deferred
```

Replace with:

```
- [x] Update `docs/architecture/ARCHITECTURE.md` with Dhara persistence layer — done in 2026-05-14 doc sync plan (Task 5)
```

- [ ] **Step 4: Update the P2 "Delivered" summary line**

Find:

```
**Delivered**: 2026-05-07 — core backend + workflow lifecycle wiring + 10 tests. PoolManager/RoutingDecisionBuffer wiring and arch doc update deferred.
```

Replace with:

```
**Delivered**: 2026-05-07 (core), 2026-05-14 (PoolManager wiring verified, arch doc updated) — all P2 tasks complete.
```

- [ ] **Step 5: Commit**

```bash
git -C /Users/les/Projects/mahavishnu add docs/plans/2026-05-07-mahavishnu-master-backlog.md
git -C /Users/les/Projects/mahavishnu commit -m "docs: mark P2 PoolManager/RoutingDecisionBuffer deferred items delivered"
```

______________________________________________________________________

### Task 4: Mark config consolidation plan complete

**Files:**

- Modify: `docs/superpowers/plans/2026-04-26-config-consolidation.md`

Everything in this plan is shipped: `scripts/migrate_config_to_project.py` (241 lines), `tests/unit/test_migration_script.py` (224 lines, 8 tests), `.claude/` directory populated, CLI commands `list-agents`/`sync-from-global` implemented.

- [ ] **Step 1: Tick all checkboxes in the plan**

```bash
sed -i '' 's/- \[ \] \*\*Step/- [x] **Step/g' /Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-04-26-config-consolidation.md
```

- [ ] **Step 2: Add a delivered header after the opening block**

Open `docs/superpowers/plans/2026-04-26-config-consolidation.md`. After the line:

```
**Tech Stack:** Python stdlib (`pathlib`, `json`, `shutil`, `yaml`), Typer (existing in Mahavishnu CLI), pytest.
```

Insert:

```

**Status:** `delivered 2026-05-14 (verified)` — `scripts/migrate_config_to_project.py` (241 lines), `tests/unit/test_migration_script.py` (8 tests), `.claude/` directory populated, CLI commands `list-agents`/`list-skills`/`list-mcp-servers`/`sync-from-global`/`rollback` all implemented.

```

- [ ] **Step 3: Verify no unchecked boxes remain**

```bash
grep -c "- \[ \]" /Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-04-26-config-consolidation.md
```

Expected: `0`

- [ ] **Step 4: Commit**

```bash
git -C /Users/les/Projects/mahavishnu add docs/superpowers/plans/2026-04-26-config-consolidation.md
git -C /Users/les/Projects/mahavishnu commit -m "docs: mark config consolidation plan delivered — all tasks verified in codebase"
```

______________________________________________________________________

### Task 5: Update ARCHITECTURE.md with Dhara persistence section

**Files:**

- Modify: `docs/architecture/ARCHITECTURE.md`

This file has zero Dhara mentions and says "Last Updated: 2026-05-02". It needs one new section covering the persistence layer that shipped in May 2026.

- [ ] **Step 1: Update the Last Updated date and status note**

Find:

```
**Last Updated**: 2026-05-02
**Status**: Historical snapshot with partial drift from current implementation
```

Replace with:

```
**Last Updated**: 2026-05-14
**Status**: Historical snapshot — architecture sections are accurate as of 2026-05-14; earlier stubs for Prefect/Agno are superseded by the full implementations in `mahavishnu/engines/`.
```

- [ ] **Step 2: Add the Dhara persistence section**

Find the line:

```
## Architecture Overview
```

Insert the following new section BEFORE that line:

````markdown
## Persistence Architecture

### Dhara State Backend

Mahavishnu persists durable operational state to Dhara (the Bodai ecosystem's ACID object store, port 8683) via `DharaStateBackend` in `mahavishnu/core/state_backends/dhara.py`.

**Key schema:**

| Key pattern | Content | Writer |
|---|---|---|
| `workflow/v1/{execution_id}` | Workflow lifecycle events (started, completed, failed) | `WorkflowEngine.execute_workflow_with_fallback()` |
| `pool/v1/{pool_id}` | Pool health snapshot (type, worker count, status) | `PoolManager._persist_pool_state()` on spawn/route/close |
| `routing/v1/{task_class}/{timestamp_ms}` | Routing decisions (pool_id, selector, reason) | `PoolManager._persist_routing_decision()` on `route_task()` |
| `approval/v1/{request_id}` | Pending approval records with 24-hour TTL | `ApprovalManager.request_approval()` |

**Degraded-boot mode:** `DharaStateBackend` has an inline circuit breaker (3 consecutive failures → open for 30 s). On startup, `MahavishnuApp.wait_for_dependencies()` recovers last-known workflow and approval state from Dhara before accepting traffic.

**Fire-and-forget writes:** All persistence calls use `asyncio.create_task()` — callers never block on Dhara. If Dhara is unavailable, writes are silently dropped and logged at DEBUG level.

**Configuration** (`settings/mahavishnu.yaml`):

```yaml
dhara_state:
  enabled: true
  flush_interval_seconds: 60
  max_routing_buffer_age_seconds: 3600
````

Dhara URL is read from the `DHARA_URL` environment variable (default: `http://localhost:8683`).

### In-Memory Ring Buffers

`RoutingDecisionBuffer` (in `mahavishnu/core/ecosystem_status.py`) is a bounded in-memory ring buffer (1000 entries per task class) for live query performance. It is **not** the persistence layer — Dhara is. The buffer is populated by the same routing path that triggers Dhara writes.

______________________________________________________________________

````

- [ ] **Step 3: Verify the section is present**

```bash
grep -n "Dhara State Backend\|Degraded-boot\|Key schema" /Users/les/Projects/mahavishnu/docs/architecture/ARCHITECTURE.md
````

Expected: all three strings found.

- [ ] **Step 4: Commit**

```bash
git -C /Users/les/Projects/mahavishnu add docs/architecture/ARCHITECTURE.md
git -C /Users/les/Projects/mahavishnu commit -m "docs: add Dhara persistence layer section to ARCHITECTURE.md"
```

______________________________________________________________________

## Track B: Session-Buddy Channel Phase 2

### Task 6: Add DharaChannelPublisher to channel_tracking_tools.py

**Files:**

- Modify: `session_buddy/mcp/tools/session/channel_tracking_tools.py`
- Modify: `tests/unit/test_channel_tracking_tools.py`

Phase 2 fires-and-forgets a `record_time_series` call to Dhara after each channel event. The existing `_ChannelSessionStore` and tool behaviour are unchanged — Phase 2 adds a side-effect only.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_channel_tracking_tools.py`:

```python
# ── Phase 2 tests ───────────────────────────────────────────────
import asyncio
from unittest.mock import AsyncMock, MagicMock

class TestDharaChannelPublisher:
    """Unit tests for DharaChannelPublisher."""

    def test_publisher_init_stores_url(self) -> None:
        from session_buddy.mcp.tools.session.channel_tracking_tools import DharaChannelPublisher
        pub = DharaChannelPublisher(dhara_url="http://localhost:8683")
        assert pub.dhara_url == "http://localhost:8683"

    @pytest.mark.asyncio
    async def test_publish_calls_record_time_series(self) -> None:
        from session_buddy.mcp.tools.session.channel_tracking_tools import DharaChannelPublisher
        pub = DharaChannelPublisher(dhara_url="http://localhost:8683")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200, raise_for_status=MagicMock()))
        pub._client = mock_client
        await pub.publish("session_buddy.channel_event", "chan_abc", {"event_type": "channel_session_start"})
        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
        assert body["name"] == "record_time_series"
        assert body["arguments"]["metric_type"] == "session_buddy.channel_event"
        assert body["arguments"]["entity_id"] == "chan_abc"

    @pytest.mark.asyncio
    async def test_publish_swallows_http_errors(self) -> None:
        from session_buddy.mcp.tools.session.channel_tracking_tools import DharaChannelPublisher
        import httpx
        pub = DharaChannelPublisher(dhara_url="http://localhost:8683")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        pub._client = mock_client
        # Should not raise
        await pub.publish("session_buddy.channel_event", "chan_abc", {"event_type": "channel_session_start"})

    @pytest.mark.asyncio
    async def test_track_tool_publishes_on_start(self) -> None:
        """track_channel_session fires Dhara publish when dhara_publisher is injected."""
        from session_buddy.mcp.tools.session.channel_tracking_tools import register_channel_tracking_tools, DharaChannelPublisher
        from fastmcp import FastMCP

        pub = MagicMock(spec=DharaChannelPublisher)
        pub.publish = AsyncMock()

        mcp = FastMCP("test")
        register_channel_tracking_tools(mcp, dhara_publisher=pub)

        tool_fn = next(t for t in mcp._tools.values() if t.name == "track_channel_session")
        await tool_fn.fn(
            event_id="evt-001",
            event_type="channel_session_start",
            channel_type="slack",
            channel_id="C123",
            sender_id="U456",
            timestamp="2026-05-14T00:00:00Z",
            token=None,
        )
        pub.publish.assert_awaited_once()
        call_args = pub.publish.call_args
        assert call_args.args[0] == "session_buddy.channel_event"

    @pytest.mark.asyncio
    async def test_track_tool_works_without_publisher(self) -> None:
        """track_channel_session works normally when no dhara_publisher is given."""
        from session_buddy.mcp.tools.session.channel_tracking_tools import register_channel_tracking_tools
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_channel_tracking_tools(mcp)  # no dhara_publisher

        tool_fn = next(t for t in mcp._tools.values() if t.name == "track_channel_session")
        result = await tool_fn.fn(
            event_id="evt-002",
            event_type="channel_session_start",
            channel_type="slack",
            channel_id="C123",
            sender_id="U456",
            timestamp="2026-05-14T00:00:00Z",
            token=None,
        )
        assert result["status"] == "tracked"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/session-buddy
uv run pytest tests/unit/test_channel_tracking_tools.py::TestDharaChannelPublisher -v 2>&1 | tail -15
```

Expected: `ImportError: cannot import name 'DharaChannelPublisher'`

- [ ] **Step 3: Implement DharaChannelPublisher**

In `session_buddy/mcp/tools/session/channel_tracking_tools.py`, add the import at the top of the file (after `from __future__ import annotations`):

```python
import asyncio
```

Then add the `DharaChannelPublisher` class right before `_ChannelSessionStore`:

```python
class DharaChannelPublisher:
    """Fire-and-forget publisher for channel session events to Dhara time-series.

    Uses Dhara's MCP HTTP transport (`POST /tools/call`) with the
    ``record_time_series`` tool. All errors are swallowed so a Dhara outage
    never blocks channel tracking.

    Args:
        dhara_url: Base URL of the Dhara MCP server (e.g. ``http://localhost:8683``).
    """

    def __init__(self, dhara_url: str) -> None:
        import httpx

        self.dhara_url = dhara_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=5.0)

    async def publish(
        self,
        metric_type: str,
        entity_id: str,
        record: dict[str, Any],
    ) -> None:
        """Record a time-series entry in Dhara. Errors are silently dropped."""
        try:
            await self._client.post(
                f"{self.dhara_url}/tools/call",
                json={
                    "name": "record_time_series",
                    "arguments": {
                        "metric_type": metric_type,
                        "entity_id": entity_id,
                        "record": record,
                    },
                },
            )
        except Exception as exc:
            logger.debug("Dhara channel publish failed (non-fatal): %s", exc)
```

- [ ] **Step 4: Update register_channel_tracking_tools signature**

Change:

```python
def register_channel_tracking_tools(mcp_server: FastMCP) -> None:
    """Register channel session tracking tools with the MCP server.

    Registers:
    - track_channel_session: Record channel session start / end / heartbeat
    - get_channel_sessions: Query active channel sessions

    Args:
        mcp_server: FastMCP server instance
    """
```

To:

```python
def register_channel_tracking_tools(
    mcp_server: FastMCP,
    dhara_publisher: DharaChannelPublisher | None = None,
) -> None:
    """Register channel session tracking tools with the MCP server.

    Registers:
    - track_channel_session: Record channel session start / end / heartbeat
    - get_channel_sessions: Query active channel sessions

    Args:
        mcp_server: FastMCP server instance
        dhara_publisher: Optional Dhara publisher for Phase 2 time-series events.
            When provided, each channel event is fire-and-forget published to
            Dhara under metric_type ``session_buddy.channel_event``.
    """
```

- [ ] **Step 5: Add fire-and-forget publish after each event dispatch**

Inside `track_channel_session`, after the `if/elif/else` event-routing block that sets `session_id` and `status`, add:

```python
            # Phase 2: fire-and-forget Dhara time-series publish
            if dhara_publisher is not None and session_id is not None:
                asyncio.create_task(
                    dhara_publisher.publish(
                        "session_buddy.channel_event",
                        session_id,
                        {
                            "event_type": event_type,
                            "channel_type": channel_type,
                            "channel_id": channel_id,
                            "sender_id": sender_id,
                            "timestamp": timestamp,
                            "status": status,
                        },
                    )
                )
```

The existing `logger.info(...)` call and `return ChannelSessionResult(...)` call that follow this block should remain unchanged.

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /Users/les/Projects/session-buddy
uv run pytest tests/unit/test_channel_tracking_tools.py -v 2>&1 | tail -20
```

Expected: all tests PASS (existing 19 + new 5 = 24 total).

- [ ] **Step 7: Commit**

```bash
git -C /Users/les/Projects/session-buddy add session_buddy/mcp/tools/session/channel_tracking_tools.py tests/unit/test_channel_tracking_tools.py
git -C /Users/les/Projects/session-buddy commit -m "feat: add DharaChannelPublisher for Phase 2 time-series publishing"
```

______________________________________________________________________

### Task 7: Wire DharaChannelPublisher through server.py

**Files:**

- Modify: `session_buddy/mcp/server.py`

The MCP server startup should read `SESSION_BUDDY_DHARA_URL` from the environment and pass a `DharaChannelPublisher` to `register_channel_tracking_tools` when set.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_channel_tracking_tools.py` (in a new `TestServerDharaWiring` class):

```python
class TestServerDharaWiring:
    """Verify server.py wires DharaChannelPublisher when env var is set."""

    def test_create_dhara_publisher_when_url_set(self, monkeypatch) -> None:
        monkeypatch.setenv("SESSION_BUDDY_DHARA_URL", "http://dhara-test:8683")
        from session_buddy.mcp.tools.session.channel_tracking_tools import DharaChannelPublisher
        from session_buddy.mcp import server as srv

        pub = srv._make_dhara_publisher()
        assert isinstance(pub, DharaChannelPublisher)
        assert pub.dhara_url == "http://dhara-test:8683"

    def test_no_publisher_when_url_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("SESSION_BUDDY_DHARA_URL", raising=False)
        from session_buddy.mcp import server as srv

        pub = srv._make_dhara_publisher()
        assert pub is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/session-buddy
uv run pytest tests/unit/test_channel_tracking_tools.py::TestServerDharaWiring -v 2>&1 | tail -10
```

Expected: `AttributeError: module 'session_buddy.mcp.server' has no attribute '_make_dhara_publisher'`

- [ ] **Step 3: Add \_make_dhara_publisher to server.py**

In `session_buddy/mcp/server.py`, add the import near the top (with the other local imports):

```python
from session_buddy.mcp.tools.session.channel_tracking_tools import DharaChannelPublisher
```

Then add the factory function near the top of the module (before any server construction):

```python
def _make_dhara_publisher() -> DharaChannelPublisher | None:
    """Return a DharaChannelPublisher if SESSION_BUDDY_DHARA_URL is set, else None."""
    import os
    url = os.environ.get("SESSION_BUDDY_DHARA_URL", "").strip()
    if not url:
        return None
    return DharaChannelPublisher(dhara_url=url)
```

- [ ] **Step 4: Pass the publisher to register_channel_tracking_tools**

In `server.py`, find the line:

```python
    "register_channel_tracking_tools": register_channel_tracking_tools,
```

This is a dispatch dict pattern. Find where `register_channel_tracking_tools` is actually called during server startup. It will look like one of:

```python
register_channel_tracking_tools(mcp)
```

or

```python
reg_fn(mcp)  # inside a loop over _ALL_REGISTERS
```

If it's called directly:

```python
register_channel_tracking_tools(mcp)
```

Change to:

```python
register_channel_tracking_tools(mcp, dhara_publisher=_make_dhara_publisher())
```

If it's called via the dispatch dict loop, the loop needs to detect the function and pass the keyword arg. Find the registration loop and add a special case:

```python
for fn in registration_functions:
    if fn is register_channel_tracking_tools:
        fn(mcp, dhara_publisher=_make_dhara_publisher())
    else:
        fn(mcp)
```

Check `server.py` to determine which pattern applies before making the edit.

- [ ] **Step 5: Run all tests**

```bash
cd /Users/les/Projects/session-buddy
uv run pytest tests/unit/test_channel_tracking_tools.py -v 2>&1 | tail -20
uv run ruff check session_buddy/mcp/server.py session_buddy/mcp/tools/session/channel_tracking_tools.py
```

Expected: all tests PASS, no lint violations.

- [ ] **Step 6: Commit**

```bash
git -C /Users/les/Projects/session-buddy add session_buddy/mcp/server.py tests/unit/test_channel_tracking_tools.py
git -C /Users/les/Projects/session-buddy commit -m "feat: wire DharaChannelPublisher in server startup via SESSION_BUDDY_DHARA_URL"
```

______________________________________________________________________

### Task 8: Update session-buddy-multi-channel-spec.md Phase 2 status

**Files:**

- Modify: `docs/plans/session-buddy-multi-channel-spec.md` (in mahavishnu repo)

- [ ] **Step 1: Update Phase 2 status in the spec**

Find the Phase 2 header block:

```
**Phase 2** | Dhara event bus | 1 day | Phase 1 |
```

(This is in a table near the bottom of the spec.)

Update the table row:

```
| **Phase 2** | Dhara event bus | delivered 2026-05-14 | Phase 1 |
```

Also find the Phase 1 status line in the backlog/master-backlog reference:

```
**Status**: delivered 2026-05-08 — Phase 1 (skill-based) complete; Phase 2 (Dhara event bus) deferred
```

Replace with:

```
**Status**: delivered — Phase 1 (in-memory store, 2026-05-08) and Phase 2 (Dhara time-series publishing, 2026-05-14) both complete
```

- [ ] **Step 2: Commit**

```bash
git -C /Users/les/Projects/mahavishnu add docs/plans/session-buddy-multi-channel-spec.md docs/plans/2026-05-07-mahavishnu-master-backlog.md
git -C /Users/les/Projects/mahavishnu commit -m "docs: mark Session-Buddy channel Phase 2 delivered"
```

______________________________________________________________________

## Self-Review

### Spec Coverage

| Requirement | Task |
|---|---|
| PLAN_INDEX stale entries (terminal, remaining-work, hatchet) | Task 1 |
| Hatchet adapter plan checkboxes | Task 2 |
| P2 backlog deferred items (PoolManager, RoutingDecisionBuffer, arch doc) | Task 3 |
| Config consolidation plan checkboxes | Task 4 |
| ARCHITECTURE.md Dhara persistence section | Task 5 |
| DharaChannelPublisher implementation + tests | Task 6 |
| Server.py wiring via SESSION_BUDDY_DHARA_URL | Task 7 |
| Spec doc reflecting Phase 2 delivered | Task 8 |

### Placeholder Scan

Clean — all code steps show complete implementations with no TBD/TODO/placeholder.

### Type Consistency

- `DharaChannelPublisher.publish(metric_type: str, entity_id: str, record: dict[str, Any])` — used identically in Task 6 (implementation) and Task 6 (test mock assertion).
- `register_channel_tracking_tools(mcp_server: FastMCP, dhara_publisher: DharaChannelPublisher | None = None)` — signature defined in Task 6, called with keyword arg in Task 7.
- `_make_dhara_publisher() -> DharaChannelPublisher | None` — defined and tested in Task 7 independently.
