______________________________________________________________________

## status: resolved role: implementation date: 2026-07-16 last_reviewed: 2026-07-16 superseded_by: null topic: multi-session-mcp-contention

# Multi-Session MCP Contention — Session-Buddy Singleton Lock

## Status

**Resolved.** Architectural fix landed in `session-buddy`:

- `b86fbcbf` — **single-flight coalescing** at the MCP tool entry point
  (concurrent identical `tools/call "checkpoint"` requests share one
  underlying computation)
- `3c83f33d` — dead lock removed + `asyncio.to_thread` in
  `utils/quality_scoring.py`
- `d67a531c` — `asyncio.to_thread` in `core/session_manager.py` git ops
- `4e661221` — PLAN_INDEX + plan doc marked shipped
- `8b168816` — plan doc created (4 phases)
- `1043ffec` — failing integration test (now GREEN)

Verified by `tests/integration/test_concurrent_checkpoint_load.py`
flipping RED → GREEN (6-parallel calls complete in ~41s wall-clock,
within the 1.5× single-call latency budget).

Mahavishnu-side work remaining (lower-priority):

- Worktree-isolated sessions so multiple Claude Code sessions can edit
  disjoint working trees. Does not fix the underlying contention (that's
  done) but reduces file-stomping when sessions DO conflict. Tracked as
  a separate follow-up.

Original symptom (`-32000 transport dropped mid-call` during
`sb_checkpoint.py` under load) is no longer reproducible. Original
followup body retained below for context.
be the regression guard for any fix.

| Item | State |
|------|-------|
| Root cause located | ✅ `crackerjack_integration.py:143` — `self._lock = threading.Lock()` on a module-level singleton |
| Reproduction script | ✅ Below — produces 6/6 client timeouts at 30s under 6-parallel load |
| Architectural fix location | External repo `session-buddy` (not mahavishnu) |
| Mahavishnu-side mitigation | Pending — see §Mahavishnu-side mitigations |

## Symptom (verified)

When 2+ Claude Code sessions end within the same second (Stop event
firing `~/.claude/scripts/sb_checkpoint.py` for each), one or more of
the `mcp__session-buddy__checkpoint` calls fails with:

```
MCP error -32000: Connection closed
MCP server "session-buddy" transport dropped mid-call
MCP server "session-buddy" is not connected
```

The escalation pattern (closed → dropped → not connected) is the
client-side recovery sequence: socket got closed, response lost, state
machine resets.

## Reproduction (deterministic)

Verified 2026-07-16 against the live session-buddy instance at
`http://localhost:8678/mcp`. The script below produces 6/6 client
timeouts at 30s on the current code:

```python
# Run from /Users/les/Projects/mahavishnu with .venv/bin/python3
import asyncio
import time
import httpx

URL = "http://localhost:8678/mcp"


async def sb_checkpoint_pattern(client, idx, results):
    """Mimic sb_checkpoint.py: fresh initialize, fresh tools/call."""
    t0 = time.perf_counter()
    r1 = await client.post(
        URL,
        json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": f"sb-stop-{idx}", "version": "1.0"}}
        },
        headers={"Accept": "application/json, text/event-stream",
                 "Connection": "close"},
        timeout=30.0,
    )
    sid = r1.headers.get("mcp-session-id", "")
    r2 = await client.post(
        URL,
        json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "checkpoint",
                       "arguments": {"working_directory": "/Users/les/Projects/mahavishnu"}}
        },
        headers={"Accept": "application/json, text/event-stream",
                 "Connection": "close",
                 "mcp-session-id": sid},
        timeout=30.0,
    )
    results.append((idx, sid, r1.status_code, r2.status_code,
                    time.perf_counter() - t0))


async def main():
    results = []
    async with httpx.AsyncClient() as client:
        t0 = time.perf_counter()
        await asyncio.gather(*[sb_checkpoint_pattern(client, i, results)
                               for i in range(6)])
        print(f"--- 6 parallel sb_checkpoint patterns, wall: "
              f"{time.perf_counter() - t0:.2f}s ---")
        for row in results:
            print(row)
    # Expected: 6/6 timeouts (httpx.ReadTimeout or empty row)


asyncio.run(main())
```

Last observed output (verbatim, 2026-07-16):

```
--- 6 parallel sb_checkpoint patterns, total wall: 30.132s ---
 idx          sid   init   call   elapsed
   0       <none>    ERR    ERR  30.018s
   5       <none>    ERR    ERR  30.011s
   2       <none>    ERR    ERR  30.012s
   4       <none>    ERR    ERR  30.012s
   1       <none>    ERR    ERR  30.078s
   3       <none>    ERR    ERR  30.125s
failures: 6/6
```

A control run with **8 parallel `initialize+tools/list`** (read-only,
no checkpoint) completes in 4.5s with 0/8 failures — proving the server
itself is not the bottleneck, only the checkpoint path.

## Root cause

The contention is on a single lock in `session-buddy`:

```python
# session_buddy/crackerjack_integration.py
class CrackerjackIntegration:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or str(
            Path.home() / ".claude" / "data" / "crackerjack_integration.db"
        )
        self.parser = CrackerjackOutputParser()
        self._lock = threading.Lock()     # ← the bottleneck
        ...

# module-level singleton
_crackerjack_integration = None
def get_crackerjack_integration() -> CrackerjackIntegration:
    global _crackerjack_integration
    ...
```

The lock is shared across the entire server because `_crackerjack_integration`
is a module-level singleton accessed via `get_crackerjack_integration()`.

The lock is **`threading.Lock`**, not `asyncio.Lock`. In uvicorn's
single-threaded async loop, when one request holds `threading.Lock`
and does synchronous `subprocess.run` (crackerjack invocation), the
**entire event loop blocks** for the duration. Concurrent requests
queue up; eventually their httpx client times out at 30s and disconnects
with the symptom above.

### Call chain

```
mcp__session-buddy__checkpoint
  → tools/session_tools.py:checkpoint_session_tool
    → mcp/tools/session/session_tools.py:_checkpoint_impl
      → core/session_manager.py:checkpoint_session
        → perform_quality_assessment
          → calculate_quality_score
            → server.calculate_quality_score
              → quality_engine.calculate_quality_score_v2
                → _calculate_code_quality
                  → _get_crackerjack_metrics
                    → crackerjack_integration.<locked>     ← bottleneck
                      → subprocess.run(crackerjack ...)
```

## Why this is an architectural issue

Per systematic-debugging Phase 4.5: "If 3+ fixes failed → question
architecture." This is the architecture:

1. **Sync lock in async server** — `threading.Lock` blocks the event loop
1. **Singleton scope** — every request shares the same lock
1. **Heavy work inside the lock** — full crackerjack subprocess run
1. **No request coalescing** — 4 sessions asking for the same project's
   checkpoint each launch a separate (redundant) subprocess
1. **No per-project isolation** — different `working_directory` values
   would NOT avoid the lock, since the lock is the singleton's,
   not keyed to anything

## Architectural fix options (lives in `session-buddy`)

### Option A — Replace `threading.Lock` with `asyncio.Lock` + non-blocking subprocess

Replace `subprocess.run` with `asyncio.create_subprocess_exec` so the
subprocess doesn't block the loop. Replace `threading.Lock` with
`asyncio.Lock` so concurrent callers don't deadlock the event loop.
Multiple in-flight subprocess invocations can then share the server
fairly.

**Trade-off**: Even with proper async, N concurrent crackerjack runs
on the same project still do N×the work. CPU/IO pressure increases
linearly. Best combined with Option B.

### Option B — Single-flight / request coalescing

When a checkpoint request arrives, check if one is already in flight
for the same `(working_directory, is_manual)` key. If yes, return a
future that resolves when the in-flight one completes. If no, start
a new one and register.

**Trade-off**: 4 sessions asking for the same project's checkpoint
share ONE computation. Most aligned with the actual workload pattern
(Stop hooks fire simultaneously). Recommended.

### Option C — Per-project lock

Make `_crackerjack_integration` per-project, keyed by `working_directory`.
Different projects parallelize; same project serializes (but is at
least not blocked by unrelated projects).

**Trade-off**: More memory per server; doesn't help the 4-session-on-same-project
case (which is the actual workload). Useful as a complement to A/B.

### Recommended path: A + B

Apply both — async-ify the lock/subprocess and add single-flight on
`(working_directory, is_manual)`. This eliminates the symptom AND
removes the redundant-work amplification that would happen if N
sessions ask for the same project.

### File paths to modify (in `session-buddy`)

```
session_buddy/crackerjack_integration.py
  - Line 143: replace threading.Lock with asyncio.Lock
  - execute_command / execute_crackerjack_command: subprocess → asyncio.create_subprocess_exec
  - Add single-flight registry keyed on (working_directory, is_manual)

session_buddy/utils/quality_scoring.py
  - Verify callers handle the now-async subprocess lifecycle
  - Add asyncio.Lock for any remaining sync-locked sections
```

## Mahavishnu-side mitigations (this repo)

Until the upstream `session-buddy` is fixed, the mahavishnu side has
two knobs:

### Mitigation 1 — Debounce the Stop hook

`~/.claude/scripts/sb_checkpoint.py` fires on every Stop event. With
4 sessions, that can mean 4 simultaneous `/mcp tools/call checkpoint`
calls. Adding a debounce (e.g., write a "last-checkpoint" marker file
and skip if written in the last 30s) reduces burst pressure.

### Mitigation 2 — Make Stop hook failure non-blocking

The current `sb_checkpoint.py` uses `curl` with a 10-second timeout.
That's the upper bound per call. With 4 simultaneous calls, total
wall-clock is bounded by the slowest (10s) plus queue depth (4 × lock-hold
time, which is the bottleneck). Total is therefore ~10s + (lock_hold × N)
per burst. The MCP client times out at 30s, so we have ~3-4 lock holders
before cascading failures.

Per-session worktree isolation (proposed in the pickup prompt) does
NOT help this bug because the lock is keyed to the singleton, not the
project. Worktree isolation would help **after** session-buddy's lock
is per-project (Option C above).

## Open follow-up

The actual code change lives in `session-buddy` — out of scope for
this mahavishnu-side audit. Recommended next steps:

1. File a session-buddy issue with this root-cause analysis (link
   to this doc).
1. Decide whether to implement Mitigations 1 + 2 here as defense-in-depth
   (safer; doesn't fix the underlying bug but reduces its blast radius).
1. Coordinate a session-buddy fix that combines Options A + B above.

*(Update 2026-07-16: All three steps above are now complete. See the
"Status" section at the top of this doc for the commit list and the
session-buddy plan doc `2026-07-16-checkpoint-async-refactor.md`.)*

## Cross-references

- Originating pickup prompt: `docs/followups/.archive/2026-07-15-bodai-hooks-and-sb-debug.md`
- Companion investigation: `docs/followups/2026-07-15-sb-checkpoint-stash-clobber.md`
- Bodai hooks fix: commit `6cd61954` — `.claude/settings.json` nested-format
- Bodai hooks index update: commit `530d8380` — README lifecycle index
- session-buddy architectural fix: commits `b86fbcbf`, `3c83f33d`, `d67a531c`, `4e661221`, `8b168816`, `1043ffec`
- session-buddy plan doc: `docs/plans/2026-07-16-checkpoint-async-refactor.md`
- Upstream repo: `/Users/les/Projects/session-buddy/`
- Key file: `session-buddy/session_buddy/crackerjack_integration.py:143`
