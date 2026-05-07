# Phase 1: Harden the Control Plane

**Date**: 2026-05-07
**Status**: COMPLETE — shipped 2026-05-07
**Scope**: Replace simulated integrations in `checkpoint.py` and `qc/checker.py` with real service-backed HTTP MCP calls

## Context

From the roadmap (`docs/proposals/2026-05-02-bodai-ecosystem-improvement-roadmap.md`), Phase 1 is the sole remaining open phase:

- Phase 2 (auth standardization): **COMPLETE** — `mcp_common.auth` live across all 6 services
- Phase 4 (code-aware automation): **COMPLETE** — call chain / impact analysis live in Session-Buddy

The two stubbed files are the only remaining gap:

| File | What is stubbed | Real target |
|---|---|---|
| `mahavishnu/session/checkpoint.py` | All 5 methods print then return hardcoded data | Session-Buddy MCP at `http://localhost:8678/mcp` |
| `mahavishnu/qc/checker.py` | All checks return hardcoded `passed` with `issues_found: 0` | Crackerjack MCP at `http://localhost:8676/mcp` |

## Existing Production Pattern

`mahavishnu/pools/session_buddy_pool.py:71` already establishes the canonical HTTP MCP client pattern:

```python
import httpx

self._client = httpx.AsyncClient(timeout=30.0)

async def _call_mcp_tool(self, tool_name: str, arguments: dict) -> dict:
    response = await self._client.post(
        f"{self.base_url}/mcp",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": tool_name, "arguments": arguments}},
    )
    response.raise_for_status()
    return response.json()
```

**Note**: Both services run FastMCP's `run_http_async` (streamable HTTP transport), which requires an `Accept: application/json, text/event-stream` header and a session handshake via `initialize` before `tools/call`. The pools module already handles this — copy that pattern exactly.

`ExternalServiceError` and `TimeoutError` already exist in `mahavishnu/core/errors.py`.

## Config Changes Needed

**Issue resolved**: `session_buddy_url` already exists as `config.session_buddy_url` (top-level `MahavishnuSettings`, line 398 in `config.py`). Do **not** add a duplicate to `SessionConfig`. `checkpoint.py` should read `config.session_buddy_url` directly.

`QualityControlConfig` has no URL field — add one:

```python
# QualityControlConfig (mahavishnu/core/config.py)
crackerjack_url: str = Field(
    default="http://localhost:8676/mcp",
    description="Crackerjack MCP server URL",
)
```

## What the Real MCP Tools Actually Do

### Session-Buddy (verified from source)

Session-Buddy does **not** expose a CRUD checkpoint API (`create/get/update/delete` with arbitrary state). Its checkpoint tools are session lifecycle tools:

| Tool name | What it does | Relevant to us? |
|---|---|---|
| `checkpoint` | Mid-session quality checkpoint + workflow analysis | Yes — use for workflow state snapshots |
| `store_conversation_checkpoint` | Store conversation from current session context; args: `checkpoint_type`, `quality_score` | Yes — use for durable record-keeping |
| `create_session_context` | Create reusable session context snapshot | Possibly |

**Implication**: The current `SessionBuddy` class in `checkpoint.py` models a CRUD checkpoint store that Session-Buddy doesn't provide. The rewrite must adapt to what Session-Buddy actually offers:

- `create_checkpoint` → call `store_conversation_checkpoint` with `checkpoint_type="workflow"` and pass `quality_score` if available; return `conversation_id` as the checkpoint ID
- `update_checkpoint` → Session-Buddy has no update-by-ID API; log the status locally and call `store_conversation_checkpoint` again on terminal states (`completed`, `failed`) so there is a durable record
- `get_checkpoint` → no direct lookup-by-ID in Session-Buddy; return `None` (callers already handle this)
- `restore_from_checkpoint` → no restore-by-ID in Session-Buddy; return `None` (callers already handle this)
- `cleanup_checkpoint` → no-op is safe; return `True`

This means the `SessionBuddy` class becomes a **write-forward sink** rather than a read/write store. Orchestration recovery (restore) must rely on Mahavishnu's own state rather than round-tripping through Session-Buddy.

### Crackerjack (verified from source)

Crackerjack exposes one primary quality execution tool:

| Tool name | What it does | Args | Return shape |
|---|---|---|---|
| `execute_crackerjack` | Runs the full crackerjack quality pipeline | `args: str`, `kwargs: str` (JSON) | JSON string with `QualityCheckResult` |

`QualityCheckResult` fields (from `crackerjack/api.py`):

```python
@dataclass
class QualityCheckResult:
    success: bool
    fast_hooks_passed: bool
    comprehensive_hooks_passed: bool
    errors: list[str]
    warnings: list[str]
    duration: float
```

**Score computation**: Crackerjack does not return a numeric score — it returns `success: bool`. Map to `qc/checker.py`'s score model as:

- `success=True` → `score = 100`, `passed = True`
- `success=False, errors=[]` → `score = self.min_score - 1` (just below threshold), `passed = False`
- `success=False, errors=[...]` → `score = max(0, 100 - len(errors) * 10)`, `passed = score >= self.min_score`

The `checks` list argument to `run_pre_checks`/`run_post_checks` does not map to separate Crackerjack tools — Crackerjack runs all hooks in one invocation. Pass the `checks` list as part of `kwargs` so Crackerjack can scope its run if it supports it; otherwise run the full suite and ignore the list.

## Workstream A: Replace `checkpoint.py`

**File**: `mahavishnu/session/checkpoint.py`

**Implementation steps:**

1. Add `httpx.AsyncClient` as `self._client` in `__init__`, URL from `config.session_buddy_url`
2. Add `async def _call_mcp(self, tool: str, args: dict) -> dict` — use the pool pattern (with session handshake)
3. Rewrite `create_checkpoint`:
   - Call `store_conversation_checkpoint` with `checkpoint_type="workflow"`
   - Extract `conversation_id` from response as the checkpoint ID
   - Wrap `httpx.TransportError | httpx.HTTPStatusError` → fall through to degraded mode
4. Rewrite `update_checkpoint`:
   - On terminal states (`completed`, `failed`): call `store_conversation_checkpoint` again with `checkpoint_type=f"workflow_{status}"`
   - On non-terminal states: log locally only (no Session-Buddy call needed)
5. Rewrite `get_checkpoint` → return `None` (Session-Buddy has no lookup-by-ID)
6. Rewrite `restore_from_checkpoint` → return `None` (no restore API available)
7. Rewrite `cleanup_checkpoint` → no-op, return `True`
8. Remove all `print()` statements — use `self.logger`

**Degraded-mode contract:**

```python
# create_checkpoint degraded: return local UUID (no Session-Buddy persistence)
# update_checkpoint degraded: log WARNING, return False
# get_checkpoint: always returns None (by design — no CRUD API)
# restore_from_checkpoint: always returns None (by design)
# cleanup_checkpoint: always returns True (no-op)
```

## Workstream B: Replace `qc/checker.py`

**File**: `mahavishnu/qc/checker.py`

**Implementation steps:**

1. Add `crackerjack_url` to `QualityControlConfig` in `config.py`
2. Add `httpx.AsyncClient` as `self._client` in `__init__`, URL from `config.qc.crackerjack_url`
3. Add `async def _call_mcp(self, tool: str, args: dict) -> dict`
4. Rewrite `run_pre_checks` and `run_post_checks`:
   - For each repo, call `execute_crackerjack` with `args=""` and `kwargs=json.dumps({"target_dir": repo})`
   - Parse `QualityCheckResult` from JSON response
   - Map `success`/`errors` to the existing result shape
5. Compute `score` from the real result (see formula above)
6. On `httpx.TransportError | httpx.HTTPStatusError`: return `passed=False` with `error` key
7. Keep the `enabled: False` short-circuit — intentional for dev/test bypass

## Workstream C: Health-Aware Guard

Add `is_healthy()` to both classes:

```python
async def is_healthy(self) -> bool:
    try:
        r = await self._client.get(
            self.base_url.replace("/mcp", "/health"), timeout=5.0
        )
        return r.status_code == 200
    except (httpx.HTTPError, httpx.TransportError):
        return False
```

Wire into Mahavishnu's pre-execution path to distinguish: safe → degraded → block.

## Error Contract

No new error classes needed:

| Situation | Handling |
|---|---|
| HTTP 4xx/5xx | `ExternalServiceError(service_name=...)` |
| Connection refused / timeout | Catch `httpx.TransportError | httpx.TimeoutException`, degrade gracefully |
| Service unavailable | Log `WARNING`, return degraded sentinel |

**Fix from v1**: Use `except (httpx.HTTPError, httpx.TransportError)` — not just `httpx.HTTPError` — to catch connection-refused and timeout errors.

## Test Coverage

1. Unit tests with `respx` for happy path, HTTP error, `ConnectError`, timeout
2. Integration smoke tests marked `@pytest.mark.integration` — skip if service unavailable
3. `enabled: False` path must continue to pass

Confirm `respx` is in dev dependencies before writing tests:

```bash
grep respx pyproject.toml
```

## Task Checklist

- [x] A1: Verify `config.session_buddy_url` (top-level) is accessible from `checkpoint.py.__init__`
- [x] A2: Rewrite `checkpoint.py` as a write-forward sink using `store_conversation_checkpoint`
- [x] A3: Add `is_healthy()` to `SessionBuddy`
- [x] A4: Unit tests for `checkpoint.py` (respx mocks)
- [x] B1: Add `crackerjack_url` to `QualityControlConfig` in `config.py`
- [x] B2: Rewrite `qc/checker.py` using `execute_crackerjack` with real score computation
- [x] B3: Add `is_healthy()` to `QualityControl`
- [x] B4: Unit tests for `qc/checker.py` (respx mocks)
- [x] C1: Wire `is_healthy()` into Mahavishnu pre-execution path
- [x] C2: `grep respx pyproject.toml` — add to dev deps if missing
- [x] C3: Run `crackerjack run` to validate no regressions

## Files to Modify

| File | Change |
|---|---|
| `mahavishnu/core/config.py` | Add `crackerjack_url` to `QualityControlConfig` only |
| `mahavishnu/session/checkpoint.py` | Rewrite as write-forward sink; add `httpx` client |
| `mahavishnu/qc/checker.py` | Rewrite using `execute_crackerjack`; add real score |
| `tests/unit/test_checkpoint.py` | New/expanded tests with respx |
| `tests/unit/test_qc_checker.py` | New/expanded tests with respx |

## Dependencies

- `httpx` — already in pyproject.toml
- `respx` — verify before writing tests

## Sequencing

A → B → C. All three land in one PR. Do not add `session_buddy_url` to `SessionConfig` — it already exists at the top level.
