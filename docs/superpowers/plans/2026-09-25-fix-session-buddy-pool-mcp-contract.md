# Fix `SessionBuddyPool` MCP Contract Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite Mahavishnu's `SessionBuddyPool.start/execute_task/execute_batch/health_check` to call session-buddy's existing pool tools (`create_pool`, `execute_on_pool`, `execute_batch_on_pool`, `check_pool_health`) so the delegation path actually works end-to-end.

**Architecture:** The `SessionBuddyPool` class is a substrate wrapper that delegates worker execution to a remote session-buddy MCP server. The current code calls four tools (`worker_spawn`, `worker_execute`, `worker_execute_batch`, `worker_health`) that **do not exist** on session-buddy — they were an aspirational contract. Session-buddy already exposes pool tools under different names; this plan re-points Mahavishnu at those names. The public return envelope (`{pool_id, worker_id, status, output, error, duration}`) is preserved exactly so downstream `PoolManager` callers don't change.

**Tech Stack:** Python 3.14, FastMCP, `mcp_common.CommonMCPClient` (streamable-HTTP transport).

**Spec (carried inline):** Demo conversation 2026-09-25; the live session-buddy exposes 49 tools, none of which are the `worker_*` tools mahavishnu calls. The 9 pool tools (`create_pool`, `execute_on_pool`, `execute_batch_on_pool`, `route_to_pool`, `list_pools`, `get_pool_status`, `check_pool_health`, `delete_pool`, `get_pool_manager_status`) register successfully in-process but the running daemon (PID 10812, started 2026-09-20) loaded an older version where they didn't exist. Restart is required for them to appear on the live MCP.

## Global Constraints

- **Live session-buddy port:** `http://localhost:8678/mcp` (per `settings/mahavishnu.yaml`)
- **Live session-buddy plist:** `/Users/les/Library/LaunchAgents/com.mcp.session-buddy.plist`
- **Restart command:** `launchctl kickstart -k gui/$(id -u)/com.mcp.session-buddy` (process is in user domain; `-k` kills + restarts so a fresh Python interpreter reloads the pool tools)
- **Session-buddy version drift:** installed editable metadata is `0.27.0`, repo `__init__.py` reports `0.25.7`. Don't change version metadata — out of scope.
- **Worker-id synthesis:** each Mahavishnu `SessionBuddyPool` represents one session-buddy `WorkerPool` of exactly 3 workers. Worker IDs are derived deterministically: `{f"{pool_id}-worker-{i}": f"worker_{i}" for i in range(3)}`.
- **Public return envelope:** `execute_task` MUST return `{"pool_id", "worker_id", "status", "output", "error", "duration"}` — `PoolManager.execute_on_pool` (consumed by `tests/integration/test_pool_orchestration.py:58`) reads `worker_id` and `status`.
- **`subagent_marker` wiring:** unchanged. The mark/clear calls around `execute_task` and `execute_batch` in `session_buddy_pool.py:172-176, 222-237, 268-272, 321-333` are correct and stay.
- **No version bumps:** per memory `feedback-mcp-common-version-bump-is-user.md`, never bump versions in any Bodai `pyproject.toml` — user does via `crackerjack run -p minor`.
- **No push without approval:** per memory `feedback-bodai-push-is-user-controlled.md`, never `git push` for bodai without explicit approval.

## File Structure

| Path | Change | Responsibility |
|---|---|---|
| `mahavishnu/pools/session_buddy_pool.py` | MODIFY methods: `start` (lines 113-148), `execute_task` (150-237), `execute_batch` (239-333), `health_check` (348-385) | Re-point the four MCP calls at existing session-buddy pool tools |
| `tests/unit/pools/test_session_buddy_pool_coverage.py` | MODIFY mocked tool names in ~6 tests | Update `call_tool.await_args.args[0]` assertions + `make_pool` mock fixtures |
| `tests/integration/test_pool_orchestration.py` | NO CHANGE | Public envelope contract is preserved — these tests must still pass unmodified |

---

### Task 1: Rewrite `SessionBuddyPool.start()` to call `create_pool`

**Files:**
- Modify: `mahavishnu/pools/session_buddy_pool.py:113-148`

**Interfaces:**
- Consumes: `self.config: PoolConfig`, `self.max_workers: int` (always 3)
- Produces: `self._workers: dict[str, str]` keyed by `{pool_id}-worker-{i}`, value `f"worker_{i}"`. `self.pool_id` is unchanged (Mahavishnu-internal UUID).

- [ ] **Step 1: Replace the body of `start()` (lines 113-148)**

Replace with:

```python
async def start(self) -> str:
    """Initialize Session-Buddy pool by creating a remote pool via MCP.

    Calls session-buddy's ``create_pool`` tool which returns a single
    ``pool_id`` representing a 3-worker ``WorkerPool`` on the session-buddy
    side. We synthesize per-worker IDs as ``{pool_id}-worker-{i}`` so the
    ``_workers`` dict shape is unchanged for callers.

    Returns:
        pool_id: Unique Mahavishnu-side pool identifier.
    """
    self._status = PoolStatus.INITIALIZING

    try:
        # Session-buddy creates one WorkerPool of 3 workers per call.
        # We don't pass pool_id — session-buddy auto-generates one and
        # returns it; that becomes the per-worker ID prefix below.
        result = await self._call_mcp_tool("create_pool", {})

        pool_id = result.get("result")
        if not isinstance(pool_id, str) or not pool_id:
            # Tolerate unexpected shapes by treating as zero workers (the
            # pool is RUNNING but degraded — execute_task will raise).
            pool_id = ""

        self._workers = {
            f"{pool_id}-worker-{i}": f"worker_{i}"
            for i in range(self.max_workers)
        } if pool_id else {}
        self._status = PoolStatus.RUNNING

        logger.info(
            f"SessionBuddyPool {self.pool_id} started with "
            f"{len(self._workers)} workers (pool_id={pool_id!r} via "
            f"{self.session_buddy_url})"
        )

    except MCPServerError as e:
        logger.error(f"Failed to start SessionBuddyPool: {e}")
        self._status = PoolStatus.FAILED
        raise

    return self.pool_id
```

- [ ] **Step 2: Read the file to confirm replacement is syntactically clean**

Run: `python -c "import ast; ast.parse(open('mahavishnu/pools/session_buddy_pool.py').read()); print('OK')"`
Expected: `OK`

---

### Task 2: Rewrite `SessionBuddyPool.execute_task()` to call `execute_on_pool`

**Files:**
- Modify: `mahavishnu/pools/session_buddy_pool.py:150-237`

**Interfaces:**
- Consumes: `task: dict` with keys `prompt`, `timeout`, optional `working_dir`
- Produces: `{"pool_id", "worker_id", "status", "output", "error", "duration"}` — envelope unchanged from current contract

- [ ] **Step 1: Replace the body of `execute_task()` (lines 150-237)**

Replace with:

```python
async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
    """Execute task via session-buddy's ``execute_on_pool`` MCP tool.

    The session-buddy pool's internal 3-worker queue picks a free worker;
    Mahavishnu-side ``worker_id`` in the response is the synthetic
    ``{pool_id}-worker-0`` (deterministic — caller doesn't care which of
    the 3 internal workers handled the task).

    Args:
        task: Task specification with ``prompt``, optional ``timeout``,
            optional ``working_dir`` (triggers ``subagent_marker``
            mark/clear for the checkpoint subsystem).

    Returns:
        Envelope ``{pool_id, worker_id, status, output, error, duration}``.
    """
    if not self._workers:
        raise RuntimeError("No workers available in pool")

    # Use the first synthetic worker_id; the response will echo a
    # canonical worker_id from session-buddy once it picks one, but
    # our envelope just needs *some* id to satisfy PoolManager callers.
    worker_id = next(iter(self._workers.keys()))
    pool_id = worker_id.rsplit("-worker-", 1)[0] if worker_id else ""
    working_dir = task.get("working_dir")

    if working_dir:
        await self._call_mcp_tool(
            "subagent_marker",
            {"working_dir": working_dir, "action": "mark"},
        )

    start_time = time.time()
    try:
        result = await self._call_mcp_tool(
            "execute_on_pool",
            {
                "pool_id": pool_id,
                "prompt": task.get("prompt", ""),
                "timeout": task.get("timeout", 300),
            },
        )

        duration = time.time() - start_time
        tool_result = result.get("result", {})

        status_value = tool_result.get("status", "unknown")
        if status_value == "completed":
            self._tasks_completed += 1
        else:
            self._tasks_failed += 1
        self._task_durations.append(duration)

        return {
            "pool_id": self.pool_id,
            "worker_id": worker_id,
            "status": status_value,
            "output": tool_result.get("output"),
            "error": tool_result.get("error"),
            "duration": duration,
        }

    except MCPServerError as e:
        logger.error(f"Failed to execute task on SessionBuddyPool: {e}")
        self._tasks_failed += 1
        return {
            "pool_id": self.pool_id,
            "worker_id": worker_id,
            "status": "failed",
            "output": None,
            "error": str(e),
            "duration": time.time() - start_time,
        }
    finally:
        if working_dir:
            try:
                await self._call_mcp_tool(
                    "subagent_marker",
                    {"working_dir": working_dir, "action": "clear"},
                )
            except Exception:
                logger.exception(
                    "subagent_marker clear failed for %s; consumer "
                    "may see a stale lockfile until the next mark",
                    working_dir,
                )
```

- [ ] **Step 2: Read the file to confirm replacement is syntactically clean**

Run: `python -c "import ast; ast.parse(open('mahavishnu/pools/session_buddy_pool.py').read()); print('OK')"`
Expected: `OK`

---

### Task 3: Rewrite `SessionBuddyPool.execute_batch()` to call `execute_batch_on_pool`

**Files:**
- Modify: `mahavishnu/pools/session_buddy_pool.py:239-333`

**Interfaces:**
- Consumes: `tasks: list[dict]` — each task has `prompt`, optional `working_dir`, optional `timeout`. May carry extra fields the new tool ignores.
- Produces: `dict[task_id, {pool_id, status, output, error}]` — envelope unchanged.

- [ ] **Step 1: Replace the body of `execute_batch()` (lines 239-333)**

Replace with:

```python
async def execute_batch(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute tasks via session-buddy's ``execute_batch_on_pool``.

    session-buddy's ``execute_batch_on_pool`` takes ``prompts: list[str]``
    plus optional shared ``context``. We extract ``prompt`` from each
    task dict and forward ``{working_dir}`` as shared context (single
    working_dir per batch — multiple distinct dirs in one batch are not
    currently supported; callers should split beforehand).

    Args:
        tasks: List of task specifications. Each MAY carry ``working_dir``;
            tasks with one are wrapped with ``subagent_marker`` mark/clear
            so the checkpoint subsystem's consumer side sees the producer
            half of the lockfile contract for that working tree.

    Returns:
        Dictionary mapping task_id -> result envelope.
    """
    if not self._workers:
        raise RuntimeError("No workers available in pool")

    worker_id = next(iter(self._workers.keys()))
    pool_id = worker_id.rsplit("-worker-", 1)[0] if worker_id else ""

    # Collect the working_dirs to mark; preserve order while
    # de-duplicating so a batch with the same working_dir across
    # tasks marks once and clears once.
    working_dirs: list[str] = []
    seen: set[str] = set()
    for task in tasks:
        wd = task.get("working_dir")
        if wd and wd not in seen:
            seen.add(wd)
            working_dirs.append(wd)

    for wd in working_dirs:
        await self._call_mcp_tool(
            "subagent_marker",
            {"working_dir": wd, "action": "mark"},
        )

    # Extract prompts; share the first working_dir (if any) as context.
    prompts = [task.get("prompt", "") for task in tasks]
    context: dict[str, Any] = {}
    if working_dirs:
        context["working_dir"] = working_dirs[0]

    start_time = time.time()
    try:
        result = await self._call_mcp_tool(
            "execute_batch_on_pool",
            {
                "pool_id": pool_id,
                "prompts": prompts,
                "context": context,
            },
        )

        duration = time.time() - start_time
        # session-buddy returns results in input order; align by index.
        batch_results = result.get("result", [])
        if not isinstance(batch_results, list):
            batch_results = []

        # Track statistics
        for entry in batch_results:
            status_value = (
                entry.get("status", "unknown")
                if isinstance(entry, dict) else "unknown"
            )
            if status_value == "completed":
                self._tasks_completed += 1
            else:
                self._tasks_failed += 1
        self._task_durations.append(duration / max(len(tasks), 1))

        # Stitch results back into task_id-keyed envelopes (preserves
        # the old wire format that PoolManager callers depend on).
        task_results: dict[str, Any] = {}
        for idx, task in enumerate(tasks):
            entry = batch_results[idx] if idx < len(batch_results) else {}
            entry = entry if isinstance(entry, dict) else {}
            task_id = task.get("task_id") or str(idx)
            task_results[task_id] = {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": entry.get("status", "unknown"),
                "output": entry.get("output"),
                "error": entry.get("error"),
            }

        logger.info(
            f"SessionBuddyPool {self.pool_id} executed {len(tasks)} tasks "
            f"in {duration:.2f}s"
        )

        return task_results

    except MCPServerError as e:
        logger.error(f"Failed to execute batch on SessionBuddyPool: {e}")
        self._tasks_failed += len(tasks)
        return {
            task.get("task_id") or str(idx): {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "failed",
                "error": str(e),
            }
            for idx, task in enumerate(tasks)
        }
    finally:
        for wd in working_dirs:
            try:
                await self._call_mcp_tool(
                    "subagent_marker",
                    {"working_dir": wd, "action": "clear"},
                )
            except Exception:
                logger.exception(
                    "subagent_marker clear failed for %s; consumer "
                    "may see a stale lockfile until the next mark",
                    wd,
                )
```

- [ ] **Step 2: Read the file to confirm replacement is syntactically clean**

Run: `python -c "import ast; ast.parse(open('mahavishnu/pools/session_buddy_pool.py').read()); print('OK')"`
Expected: `OK`

---

### Task 4: Rewrite `SessionBuddyPool.health_check()` to call `check_pool_health`

**Files:**
- Modify: `mahavishnu/pools/session_buddy_pool.py:348-385` (the `health_check` method body)

**Interfaces:**
- Consumes: `self._workers` (may be empty if pool failed to spawn)
- Produces: `{"pool_id", "pool_type", "status", "workers_active", "max_workers", "worker_health", "tasks_completed", "tasks_failed", "session_buddy_url"}`

- [ ] **Step 1: Replace the body of `health_check()` (lines 348-385)**

Replace with:

```python
async def health_check(self) -> dict[str, Any]:
    """Check pool health via session-buddy's ``check_pool_health``.

    Returns:
        Health status dictionary.
    """
    worker_id = next(iter(self._workers.keys()), "")
    pool_id = worker_id.rsplit("-worker-", 1)[0] if worker_id else ""

    try:
        result = await self._call_mcp_tool(
            "check_pool_health",
            {"pool_id": pool_id} if pool_id else {},
        )
        health_result = result.get("result", {})

        pool_status = "healthy"
        if len(self._workers) < self.config.min_workers:
            pool_status = "degraded"
        elif len(self._workers) == 0:
            pool_status = "unhealthy"

        return {
            "pool_id": self.pool_id,
            "pool_type": "session-buddy",
            "status": pool_status,
            "workers_active": len(self._workers),
            "max_workers": self.max_workers,
            "worker_health": health_result,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "session_buddy_url": self.session_buddy_url,
        }

    except MCPServerError as e:
        logger.error(f"Failed health check for SessionBuddyPool: {e}")
        return {
            "pool_id": self.pool_id,
            "pool_type": "session-buddy",
            "status": "unknown",
            "workers_active": len(self._workers),
            "max_workers": self.max_workers,
            "worker_health": None,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "error": str(e),
            "session_buddy_url": self.session_buddy_url,
        }
```

- [ ] **Step 2: Read the file to confirm replacement is syntactically clean**

Run: `python -c "import ast; ast.parse(open('mahavishnu/pools/session_buddy_pool.py').read()); print('OK')"`
Expected: `OK`

---

### Task 5: Update unit test mocked tool names

**Files:**
- Modify: `tests/unit/pools/test_session_buddy_pool_coverage.py`

**Interfaces:**
- Consumes: existing test fixtures (mock `call_tool`, `make_pool`)
- Produces: tests that assert the new tool names (`create_pool`, `execute_on_pool`, `execute_batch_on_pool`, `check_pool_health`)

- [ ] **Step 1: Update `test_start_pool_happy_path` (line ~140)**

Change the asserted tool name from `"worker_spawn"` to `"create_pool"`:

```python
@pytest.mark.asyncio
async def test_start_pool_happy_path(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """start() calls create_pool and synthesizes 3 worker_ids from returned pool_id."""
    pool = make_pool({"result": "sbpool-abc123"})
    await pool.start()
    assert len(pool._workers) == 3
    # call_tool invoked with create_pool
    pool._mcp.call_tool.assert_awaited()
    assert pool._mcp.call_tool.await_args.args[0] == "create_pool"
    # Worker IDs are derived as {pool_id}-worker-{i}
    assert set(pool._workers.keys()) == {
        "sbpool-abc123-worker-0",
        "sbpool-abc123-worker-1",
        "sbpool-abc123-worker-2",
    }
```

- [ ] **Step 2: Update `test_start_pool_non_list_worker_ids` (line ~147)**

Update the mock to return a non-string `result` (since create_pool returns a string, an unexpected non-string means 0 workers):

```python
@pytest.mark.asyncio
async def test_start_pool_non_list_worker_ids(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """start() tolerates a non-string 'result' by treating it as zero workers."""
    pool = make_pool({"result": 42})  # not a string
    await pool.start()
    assert pool._workers == {} and pool._status == PoolStatus.RUNNING
```

- [ ] **Step 3: Update `test_execute_task_happy_path` (line ~170)**

The mock result shape must match session-buddy's `execute_on_pool` response. Update the mock and add the worker_id assertion:

```python
@pytest.mark.asyncio
async def test_execute_task_happy_path(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool({"result": {"status": "completed", "output": "ok", "error": None}})
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    result = await pool.execute_task({"prompt": "do thing", "timeout": 60})
    assert result["status"] == "completed" and result["output"] == "ok"
    assert result["error"] is None
    assert result["worker_id"] == "sbpool-abc-worker-0"
    assert pool._tasks_completed == 1 and pool._tasks_failed == 0
    # Verify execute_on_pool was the tool invoked
    last_call = pool._mcp.call_tool.await_args_list[-1]
    assert last_call.args[0] == "execute_on_pool"
```

- [ ] **Step 4: Update `test_execute_task_server_error_returns_failed_envelope` (line ~191)**

The error path is unchanged in shape — just verify the tool name assertion if missing:

```python
@pytest.mark.asyncio
async def test_execute_task_server_error_returns_failed_envelope(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool(MCPServerError("upstream gone"))
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    result = await pool.execute_task({"prompt": "do thing"})
    assert result["status"] == "failed" and result["error"] == "upstream gone"
    assert pool._tasks_failed == 1
    assert result["worker_id"] == "sbpool-abc-worker-0"
```

- [ ] **Step 5: Add new tests for `execute_batch` and `health_check` (insert after existing tests)**

Add these two tests covering the new tool names:

```python
@pytest.mark.asyncio
async def test_execute_batch_happy_path(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """execute_batch() calls execute_batch_on_pool and returns task_id-keyed envelopes."""
    pool = make_pool({
        "result": [
            {"status": "completed", "output": "r1"},
            {"status": "completed", "output": "r2"},
        ]
    })
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    result = await pool.execute_batch([
        {"task_id": "t1", "prompt": "do one"},
        {"task_id": "t2", "prompt": "do two"},
    ])
    assert "t1" in result and "t2" in result
    assert result["t1"]["status"] == "completed" and result["t1"]["output"] == "r1"
    assert result["t2"]["status"] == "completed" and result["t2"]["output"] == "r2"
    # Verify execute_batch_on_pool was the tool invoked
    last_call = pool._mcp.call_tool.await_args_list[-1]
    assert last_call.args[0] == "execute_batch_on_pool"


@pytest.mark.asyncio
async def test_health_check_calls_check_pool_health(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool({"result": {"healthy": True}})
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    result = await pool.health_check()
    assert result["status"] == "healthy"
    assert result["worker_health"] == {"healthy": True}
    last_call = pool._mcp.call_tool.await_args_list[-1]
    assert last_call.args[0] == "check_pool_health"
```

---

### Task 6: Run unit tests + verify all pass

**Files:**
- Read: `tests/unit/pools/test_session_buddy_pool_coverage.py`, `tests/unit/pools/test_session_buddy_pool_marker_hook.py`

- [ ] **Step 1: Run the coverage test file**

Run: `.venv/bin/pytest tests/unit/pools/test_session_buddy_pool_coverage.py -v`
Expected: all tests pass

- [ ] **Step 2: Run the marker hook test file (regression check)**

Run: `.venv/bin/pytest tests/unit/pools/test_session_buddy_pool_marker_hook.py -v`
Expected: all tests pass (subagent_marker wiring unchanged)

- [ ] **Step 3: Run the integration test file (public envelope contract)**

Run: `.venv/bin/pytest tests/integration/test_pool_orchestration.py -v -m integration`
Expected: all tests pass — confirms the `{pool_id, worker_id, status, output}` envelope shape is preserved

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/pools/session_buddy_pool.py tests/unit/pools/test_session_buddy_pool_coverage.py
git commit -m "fix(pools): re-point SessionBuddyPool at existing session-buddy pool tools"
```

---

### Task 7: Restart session-buddy daemon + verify pool tools are live

**Files:** none (operational task)

- [ ] **Step 1: Restart session-buddy via launchctl**

```bash
launchctl kickstart -k "gui/$(id -u)/com.mcp.session-buddy"
```

Wait ~5 seconds for the new process to bind 8678.

- [ ] **Step 2: Verify the live server exposes the 9 pool tools**

Run: `.venv/bin/python -c "
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with streamable_http_client('http://localhost:8678/mcp') as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.list_tools()
            names = sorted([t.name for t in res.tools])
            pool = [n for n in names if 'pool' in n.lower() or 'worker' in n.lower()]
            print('pool/worker tools:', pool)

asyncio.run(main())
"`

Expected: `['check_pool_health', 'create_pool', 'delete_pool', 'execute_batch_on_pool', 'execute_on_pool', 'get_pool_manager_status', 'get_pool_status', 'list_pools', 'route_to_pool']`

- [ ] **Step 3: End-to-end smoke test — spawn + execute + health**

Run: `.venv/bin/python << 'PY'
import asyncio, json
from mahavishnu.pools.session_buddy_pool import SessionBuddyPool
from mahavishnu.pools.base import PoolConfig

async def main():
    cfg = PoolConfig(name='smoke-test', pool_type='session_buddy',
                      min_workers=1, max_workers=3)
    pool = SessionBuddyPool(cfg, session_buddy_url='http://localhost:8678/mcp')
    pool_id = await pool.start()
    print(f'POOL_ID={pool_id}  workers={len(pool._workers)}')

    # Execute a single task
    result = await pool.execute_task({'prompt': 'echo hello', 'timeout': 30})
    print(f'EXECUTE: {json.dumps(result, default=str)}')

    # Batch execute
    batch = await pool.execute_batch([
        {'task_id': 'a', 'prompt': 'first'},
        {'task_id': 'b', 'prompt': 'second'},
    ])
    print(f'BATCH: {json.dumps(batch, default=str)}')

    # Health check
    health = await pool.health_check()
    print(f'HEALTH: {json.dumps(health, default=str)[:300]}')

asyncio.run(main())
PY`

Expected: 
- `POOL_ID=<uuid>  workers=3`
- `EXECUTE: {... "status": "completed" ...}` (placeholder executor returns within 0.1s)
- `BATCH: {"a": {...}, "b": {...}}`
- `HEALTH: {"status": "healthy", "workers_active": 3, ...}`

- [ ] **Step 4: Commit the plan document (no code change)**

```bash
git add docs/superpowers/plans/2026-09-25-fix-session-buddy-pool-mcp-contract.md
git commit -m "docs(plan): session-buddy pool MCP contract fix"
```

(Plan document lives in mahavishnu even though the fix spans both repos — it's the change log for this work.)

---

## Self-Review

1. **Spec coverage:** Demo conversation required (a) re-pointing 4 tool calls, (b) preserving the public return envelope, (c) restart + verify. Covered by Tasks 1-7.
2. **Placeholder scan:** No "TBD"/"TODO"/"add appropriate" placeholders. All code blocks are concrete.
3. **Type consistency:** `worker_id` is always a string. `pool_id` derivation `worker_id.rsplit("-worker-", 1)[0]` is consistent across all 4 methods.
4. **Envelope preservation:** All return shapes match `tests/integration/test_pool_orchestration.py:55-62` requirements (`pool_id`, `worker_id`, `status`, `output`).
5. **Restart command correctness:** `launchctl kickstart -k` for user-domain launchd requires `gui/$(id -u)/` prefix — confirmed via `launchctl list` showing `10809` (not `-` PID), which means it's in the user gui domain.
6. **Risks not covered:**
   - Session-buddy v0.27.0 editable install + v0.25.7 source drift is out of scope — flagged in global constraints but not addressed (it's a pre-existing condition).
   - If live session-buddy restart fails to expose pool tools, the integration test in Task 7 Step 3 will fail and we need to investigate why — that's the smoke test catching the regression.
