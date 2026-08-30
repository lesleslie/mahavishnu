# Fix: `dispatch_to_pool(async_callback=True)` → `workflow_result(not_found)`

**Outcome #1 of** `docs/plans/2026-08-29-orchestrator-research-synthesis.md`
**Filed**: 2026-08-29
**Status**: Diagnosed, fix designed, awaiting worker-registry-2026-08-28 merge to main

## Bug repro (this session, verified)

```python
mcp__mahavishnu__dispatch_to_pool(prompt="outcome-1-bug-reproduction: ...", async_callback=True)
# → {"workflow_id": "10633f68-279a-4bcc-8c7b-634d870f71c8", "status": "queued", ...}

mcp__mahavishnu__workflow_result(workflow_id="10633f68-279a-4bcc-8c7b-634d870f71c8")
# → {"workflow_id": "10633f68-279a-4bcc-8c7b-634d870f71c8", "status": "not_found"}
```

Round-trip broken. Caller was told the workflow was queued but cannot retrieve its status.

## Root cause

The bug lives in the worker-registry refactor branch (`refactor/worker-registry-capability-2026-08-29`,
currently 38 commits ahead of `main`). It is NOT in `main` yet. The implementation is in
`mahavishnu/mcp/tools/pool_tools.py` in that worktree (the file on `main` is the 177-line stub).

### Write side: silent no-op when Dhara unavailable

**`mahavishnu/mcp/tools/pool_tools.py` (worker-registry worktree), lines 181–194**

```python
dhara = getattr(pool_manager, "_dhara_state", None)

async def _persist_state(state_value: str, payload: dict[str, Any]) -> None:
    if dhara is None:
        return                                          # ← bug: silent no-op
    await dhara.put(
        f"workflow-results/{workflow_id}/",
        {"workflow_id": workflow_id, "status": state_value, ...},
    )
```

The `if dhara is None: return` branch was **documented as a "non-fatal failure mode"** in the
docstring at lines 158–171. The author's intent was graceful degradation: if Dhara is down,
async dispatch still returns a `workflow_id`. But the *caller* then has no way to read back
the result — `workflow_result` returns `not_found`. Graceful degradation broke the contract.

### Why Dhara is unavailable in this environment

**`mahavishnu/core/bootstrap.py` (worker-registry worktree), lines 389–409**

```python
def _init_dhara_state(app: Any) -> Any:
    if not (app.config.dhara_state.enabled and app.dhara_url):
        return None                                   # ← returns None when not configured
    ...
```

Bootstrap wires `app._dhara_state = _init_dhara_state(app)`. When `dhara_state.enabled=False`
or `dhara_url` is unset, `app._dhara_state` is `None`, which propagates to
`PoolManager._dhara_state = None` (via `bootstrap.py:578`), which makes `_persist_state`
silent-no-op, which makes `workflow_result` return `not_found`.

### Read side: only consults Dhara

**`mahavishnu/mcp/tools/pool_tools.py` (worker-registry worktree), lines 953–960**

```python
dhara = getattr(pool_manager, "_dhara_state", None)
if dhara is None:
    return {"workflow_id": workflow_id, "status": "not_found"}     # ← same root
record = await dhara.get(f"workflow-results/{workflow_id}/")
if not record:
    return {"workflow_id": workflow_id, "status": "not_found"}
```

`workflow_result` only checks Dhara. Even if we fix the write side to fall back to dead-letter,
the read side won't find the result unless we also teach `workflow_result` to consult the
dead-letter file.

## Fix design

**Two coordinated changes**, both in the same file (`pool_tools.py`):

### Change 1 — `_persist_state` (write side): fall through to dead-letter when Dhara unavailable

```python
dhara = getattr(pool_manager, "_dhara_state", None)

async def _persist_state(state_value: str, payload: dict[str, Any]) -> None:
    """Persist workflow state to Dhara, with dead-letter fallback."""
    if dhara is not None:
        try:
            await dhara.put(
                f"workflow-results/{workflow_id}/",
                {
                    "workflow_id": workflow_id,
                    "status": state_value,
                    "updated_at": datetime.now(UTC).isoformat(),
                    **payload,
                },
            )
            return
        except Exception as exc:
            logger.exception(
                "dispatch_to_pool: dhara.put failed for workflow_id=%s "
                "state=%s; falling back to dead-letter",
                workflow_id, state_value,
            )
            # Fall through to dead-letter
    _dead_letter_append(workflow_id, state_value, payload)
```

The existing dead-letter pattern at lines 235–282 already handles Dhara-side failures. This fix
makes the *unavailable* case use the same recovery path. The `if dhara is None: return` branch
is deleted entirely — silent data loss is no longer a tolerated mode.

### Change 2 — `workflow_result` (read side): check dead-letter as fallback

```python
dhara = getattr(pool_manager, "_dhara_state", None)
record = None
if dhara is not None:
    record = await dhara.get(f"workflow-results/{workflow_id}/")

# Dead-letter fallback: recover workflows that ran while Dhara was
# unavailable or when the Dhara write itself failed.
if not record:
    safe_wid = workflow_id.replace("/", "_").replace("..", "_")[:200]
    dead_letter_path = (
        Path.home() / ".mahavishnu" / "async-dead-letter" / f"{safe_wid}.json"
    )
    if dead_letter_path.exists():
        try:
            loaded = json.loads(dead_letter_path.read_text())
        except (json.JSONDecodeError, OSError):
            loaded = None
        if isinstance(loaded, dict):
            states = loaded.get("states", [])
            # Find the latest terminal state (completed/failed) for the result.
            for entry in reversed(states):
                if isinstance(entry, dict) and entry.get("status") in ("completed", "failed"):
                    payload_inner = entry.get("payload", {})
                    record = {
                        "status": entry["status"],
                        "result": payload_inner.get("result"),
                        "error": payload_inner.get("error"),
                        "rate_limited": bool(payload_inner.get("rate_limited", False)),
                        "retry_after_seconds": payload_inner.get("retry_after_seconds"),
                    }
                    break

if not record:
    return {"workflow_id": workflow_id, "status": "not_found"}
```

### Change 3 — extract `_dead_letter_append` helper

The current dead-letter write logic at lines 235–282 is inline. Extract it as a helper so both
the new `_persist_state` fallback (Change 1) and the existing Dhara-write-failure path
(lines 230–282) share the same recovery mechanism. Pseudocode:

```python
def _dead_letter_append(workflow_id: str, status: str, payload: dict[str, Any]) -> None:
    """Append a workflow state record to the local dead-letter file.

    Best-effort; logs at exception severity on failure but never raises
    (preserves the fire-and-forget contract). The dead-letter file is at
    ``~/.mahavishnu/async-dead-letter/{safewid}.json`` and accumulates
    states across calls so the read side can find the latest terminal
    state when Dhara is unavailable.
    """
    dead_letter_dir = Path.home() / ".mahavishnu" / "async-dead-letter"
    try:
        dead_letter_dir.mkdir(parents=True, exist_ok=True)
        safe_wid = workflow_id.replace("/", "_").replace("..", "_")[:200]
        dead_letter_path = dead_letter_dir / f"{safe_wid}.json"
        existing_states: list[dict[str, Any]] = []
        if dead_letter_path.exists():
            try:
                loaded = json.loads(dead_letter_path.read_text())
                if isinstance(loaded, dict):
                    existing_states = list(loaded.get("states", []))
            except (json.JSONDecodeError, OSError):
                pass
        existing_states.append({
            "status": status,
            "updated_at": datetime.now(UTC).isoformat(),
            "payload": payload,
        })
        dead_letter_path.write_text(json.dumps(
            {"workflow_id": workflow_id, "states": existing_states},
            default=str,
        ))
    except Exception:
        logger.exception(
            "dispatch_to_pool: dead-letter write FAILED "
            "workflow_id=%s status=%s",
            workflow_id, status,
        )
```

## Why this approach (vs alternatives)

| Alternative | Why not |
|---|---|
| Make Dhara **required** (raise on `dhara is None`) | Breaking change for environments without Dhara. The fire-and-forget contract returns a `workflow_id` before persist runs — even raising wouldn't prevent that, but it would invalidate existing smoke tests. |
| Fix bootstrap to *always* configure Dhara | Doesn't help when `dhara_state.enabled` is intentionally `False` (e.g., local dev). |
| Wire Dhara in `PoolManager` after construction | `bootstrap.py:578` already passes `dhara_state=getattr(app, "_dhara_state", None)`. The wiring is correct; the assumption "Dhara is optional" is the bug. |
| In-memory dict fallback | Doesn't survive restart. Dead-letter file gives operators a recoverable record. |
| Skip the fix entirely | Outcome #1's purpose is to ship this fix. Outcome #2–5 depend on it. |
| Migrate callers to `get_capability_result(trace_id)` | **Verified unavailable in current MCP server** — see Coordination Notes. Tools exist in source but aren't exposed; the running server only has the deprecated tools. |

The dead-letter fallback is the path of least resistance: existing infrastructure
(`~/.mahavishnu/async-dead-letter/`), existing JSON shape, just extends it from
"Dhara-write-failed" to "Dhara-unavailable."

## Regression test

When the code lands on `main`, add to `tests/unit/mcp/tools/test_pool_tools.py`:

```python
import json
from pathlib import Path

import pytest

from mahavishnu.mcp.tools.pool_tools import _dead_letter_append


@pytest.fixture
def tmp_dead_letter_dir(tmp_path, monkeypatch):
    """Redirect dead-letter writes to tmp_path."""
    monkeypatch.setattr(
        "mahavishnu.mcp.tools.pool_tools.Path",
        lambda *args: tmp_path.joinpath(*args),
    )
    return tmp_path


async def test_dispatch_to_pool_async_persists_via_dead_letter_when_dhara_unavailable(
    tmp_dead_letter_dir,
):
    """Regression: dispatch_to_pool must persist via dead-letter when Dhara is None.

    Pre-fix: workflow_result(workflow_id) returned {"status": "not_found"} even
    when the workflow completed, because _persist_state silently no-op'd.
    Post-fix: dead-letter captures the state and workflow_result recovers it.
    """
    workflow_id = "test-uuid-1234"

    # Simulate the dispatch: persist running state, then terminal state
    _dead_letter_append(workflow_id, "running", {"caller_kind": "unknown"})
    _dead_letter_append(
        workflow_id,
        "completed",
        {"caller_kind": "unknown", "result": {"echo": "ok"}},
    )

    # Dead-letter file exists
    safe_wid = workflow_id.replace("/", "_").replace("..", "_")[:200]
    dead_letter_path = tmp_dead_letter_dir / ".mahavishnu" / "async-dead-letter" / f"{safe_wid}.json"
    assert dead_letter_path.exists()
    payload = json.loads(dead_letter_path.read_text())
    assert payload["workflow_id"] == workflow_id
    assert len(payload["states"]) == 2
    assert payload["states"][-1]["status"] == "completed"
    assert payload["states"][-1]["payload"]["result"] == {"echo": "ok"}


async def test_workflow_result_recovers_from_dead_letter(monkeypatch, tmp_path):
    """workflow_result must find records in dead-letter when Dhara returns nothing."""
    # Pre-seed the dead-letter file
    workflow_id = "test-uuid-deadletter"
    safe_wid = workflow_id.replace("/", "_").replace("..", "_")[:200]
    dead_letter_dir = tmp_path / ".mahavishnu" / "async-dead-letter"
    dead_letter_dir.mkdir(parents=True, exist_ok=True)
    (dead_letter_dir / f"{safe_wid}.json").write_text(json.dumps({
        "workflow_id": workflow_id,
        "states": [
            {"status": "running", "updated_at": "2026-08-29T00:00:00Z", "payload": {}},
            {
                "status": "completed",
                "updated_at": "2026-08-29T00:00:01Z",
                "payload": {"result": {"answer": 42}},
            },
        ],
    }))

    # Patch Path.home() to tmp_path
    monkeypatch.setattr(
        "mahavishnu.mcp.tools.pool_tools.Path.home",
        classmethod(lambda cls: tmp_path),
    )

    # Invoke workflow_result against a pool_manager with no Dhara
    # Asserts: result.status == "completed", result.result == {"answer": 42}
    # (specific call shape depends on MCP tool introspection; left abstract here)
    ...
```

## Coordination notes

The bug lives in `pool_tools.py` of the worker-registry refactor (`2026-08-28-oneiric-cli-rename-spec`
worktree). This file is NOT in `main` yet — it's behind a 38-commit refactor that's mid-flight.

Per the handoff: "Worker-registry / capability refactor plan: finishing in another session;
assume it lands mid-run and unblocks you."

I attempted to apply the fix via `Edit` on the worker-registry worktree's path, but the
worktree-isolation guard (per `mahavishnu-worktree-isolation-guard-is-bash-classifier.md`)
denied it with "Edit the worktree copy of this file instead of the shared-checkout path."

### Plan Phase 0 task #4 says "switch callers to `get_capability_result(trace_id)`"

The v2 plan's Phase 0 task #4 reads:

> **Check whether the failure traces to the deprecated `dispatch_to_pool` path.**
> Worker-registry Task 3b.3 deletes `dispatch_to_pool`, `pool_route_execute`, and
> `workflow_result` after one release cycle of dual maintenance. Worker-registry Task
> 3a.4 ships `get_capability_result(trace_id: TraceId)` as the replacement. If the
> failing `workflow_result(workflow_id)` callsite can switch to `get_capability_result(trace_id)`,
> the right fix is **switching the caller, not patching the old tool** — patching
> produces dead code that Task 3b.3 will remove.

I verified the migration path is **NOT yet available** in this environment:

```python
mcp__mahavishnu__execute_capability(requires=["code_generation"],
                                    prompt="...",
                                    trace_id="outcome-1-test-trace")
# → Error: No such tool available: mcp__mahavishnu__execute_capability

mcp__mahavishnu__get_capability_result(trace_id="outcome-1-test-trace")
# → Error: No such tool available: mcp__mahavishnu__get_capability_result
```

The replacement tools exist in `mahavishnu/mcp/tools/capability_tools.py` and
`mahavishnu/mcp/tools/get_capability_result_tool.py` (verified by `grep`), but the
running MCP server (PID 46863, started 2026-08-28T23:31:00) does NOT expose them.
The MCP tool list available to this session includes `dispatch_to_pool` and
`workflow_result` but NOT `execute_capability` or `get_capability_result`.

So the migration path is "in transit": the new tools exist in source but the running
server is on a pre-migration build. Patching the old tools is the only path that
restores functionality *now*. When the worker-registry refactor finishes and the
MCP server is restarted on the new build, the migration becomes the canonical path.

### Recommended sequencing

1. **Right now** — apply the fix to `pool_tools.py` (this design) on whichever branch
   lands first. Either:
   - Wait for worker-registry to land on `main`, then apply the three changes on
     `main` as a follow-up commit.
   - Cherry-pick the dead-letter helper into the worker-registry worktree directly
     (coordinate with that session; the helper is small).
1. **Long term** — when the new MCP server build ships, complete the migration to
   `execute_capability` + `get_capability_result(trace_id)` per plan Phase 0 task #4.
   The dead-letter fallback remains as a recovery layer for the new path too.

Either way, the design above is complete and reviewable. The follow-on session can apply it
mechanically: extract `_dead_letter_append`, swap the silent no-op for the fall-through,
add the read-side dead-letter check. ~30 lines net change.

## Status update for the plan doc

```diff
- Outcome #1: Status pending (waiting on worker-registry)
+ Outcome #1: Bug diagnosed. Root cause: `_dhara_state is None` causes silent
+ no-op in `_persist_state` (write side) and `workflow_result` returns
+ `not_found` (read side). Fix designed: dead-letter fallback on write side
+ + read-side dead-letter check. Awaiting worker-registry-2026-08-28 merge
+ to main so the changes can land. See
+ `docs/fixes/2026-08-29-dispatch-to-pool-dead-letter-fallback.md` for the
+ complete patch design.

+ Secondary finding: Plan Phase 0 task #4 recommends migrating to
+ `execute_capability` + `get_capability_result(trace_id)`. Verified the
+ new tools are NOT exposed in the running MCP server (only the deprecated
+ `dispatch_to_pool`/`workflow_result` are). Migration is "in transit":
+ the new tools exist in source but the MCP server is on a pre-migration
+ build. The dead-letter fallback fix restores the old tools to working
+ state during the dual-maintenance window.
```
