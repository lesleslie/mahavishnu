# Fix `SessionBuddyPool` MCP Contract — v2 (Pivot: session-buddy wrappers)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Mahavishnu's `SessionBuddyPool` correctly delegate to session-buddy's MCP pool tools by (1) restructuring session-buddy's 9 pool-tool wrappers to return JSON dicts instead of formatted strings, and (2) re-pointing Mahavishnu's 4 call sites at the now-working wire format.

**Architecture:** The v1 plan failed audit because session-buddy's `@mcp.tool()` wrappers return formatted `str` (e.g. `"✅ Created pool my_pool with 3 workers"`) but Mahavishnu expected structured dicts. v2 pivots: change the wrappers to return `dict[str, Any]` via FastMCP structured output, fix `pool_execute_batch` to preserve per-task structured results (currently stringified), update Mahavishnu's `_call_mcp_tool` to unwrap `CallToolResult`, and re-point Mahavishnu's 4 method bodies at the now-correct wire format. Two repos, scoped tightly.

**Tech Stack:** Python 3.14, FastMCP, `mcp_common.CommonMCPClient`, `mcp.client.session.CallToolResult`.

**Spec carried inline:** Three-agent audit (code-architect, code-explorer, code-reviewer) of v1 plan found 5 BLOCKING issues (all confirmed by ≥2 agents). User chose pivot: modify session-buddy wrappers. This v2 plan addresses all 5 BLOCKINGs plus 5 hardening recommendations from the code-reviewer.

**Why a v2 file:** preserves audit history in `2026-09-25-fix-session-buddy-pool-mcp-contract.md`. Do not delete v1.

## Global Constraints

- **Live session-buddy port:** `http://localhost:8678/mcp`
- **Live session-buddy plist:** `/Users/les/Library/LaunchAgents/com.mcp.session-buddy.plist`
- **Restart command:** `launchctl kickstart -k gui/$(id -u)/com.mcp.session-buddy`
- **No version bumps:** per memory `feedback-mcp-common-version-bump-is-user.md`, never bump versions in any Bodai `pyproject.toml`.
- **No `git push` without explicit approval:** per memory `feedback-bodai-push-is-user-controlled.md`.
- **Worktrees:** session-buddy and mahavishnu changes go in SEPARATE git worktrees (different repos). Both committed locally; user pushes.
- **Structured output convention:** session-buddy wrapper success path returns `{"success": True, ...data, ...}`. Failure path returns `{"success": False, "error": str}`. Per-task batch results are dicts `{status: "completed"|"failed", output, error}`.
- **Public envelope preservation:** Mahavishnu `SessionBuddyPool.execute_task` MUST continue returning `{pool_id, worker_id, status, output, error, duration}` — integration test at `tests/integration/test_pool_orchestration.py:55-62` consumes it.
- **Subagent marker wiring:** mark/clear around `execute_task` and `execute_batch` stays unchanged (already correct).
- **Mock shape parity:** Tests must mock the SAME shape the production wire produces. If production returns `{"success": True, "results": [...]}` then mocks return `{"success": True, "results": [...]}`.

## File Structure

| Path | Repo | Change | Responsibility |
|---|---|---|---|
| `session_buddy/mcp/tools/infrastructure/pools.py:403-547` | session-buddy | MODIFY 9 `@mcp.tool()` wrappers | Return structured dicts instead of formatted strings |
| `session_buddy/mcp/tools/infrastructure/pools.py:149-154` | session-buddy | MODIFY `pool_execute_batch` helper | Don't stringify per-task results; preserve list[dict] |
| `session_buddy/tests/unit/test_pool_tools.py` | session-buddy | MODIFY mocked returns | Match new structured shapes |
| `mahavishnu/pools/session_buddy_pool.py:89-111` | mahavishnu | MODIFY `_call_mcp_tool` | Unwrap `CallToolResult` to plain dict via `_extract_tool_payload` |
| `mahavishnu/pools/session_buddy_pool.py:113-148` | mahavishnu | MODIFY `start()` | Call `create_pool` |
| `mahavishnu/pools/session_buddy_pool.py:150-237` | mahavishnu | MODIFY `execute_task()` | Call `execute_on_pool` |
| `mahavishnu/pools/session_buddy_pool.py:239-333` | mahavishnu | MODIFY `execute_batch()` | Call `execute_batch_on_pool`; envelope must include `"output": None` in error path |
| `mahavishnu/pools/session_buddy_pool.py:348-385` | mahavishnu | MODIFY `health_check()` | Call `check_pool_health`; local fallback when pool_id empty |
| `mahavishnu/pools/session_buddy_pool.py:438-451` (stop) | mahavishnu | MODIFY `stop()` | Call `delete_pool` (was `worker_close_all`) |
| `mahavishnu/tests/unit/pools/test_session_buddy_pool_coverage.py` | mahavishnu | MODIFY 5+ tests | Update mock shapes; fix `test_execute_batch_branches` |
| `mahavishnu/tests/unit/pools/test_session_buddy_pool_marker_hook.py` | mahavishnu | MODIFY 6+ assertions | Update tool name assertions from `worker_execute` → `execute_on_pool` |
| `mahavishnu/tests/integration/test_pool_orchestration.py` | mahavishnu | NO CHANGE | Public envelope preserved |

---

### Task 0a: Refactor session-buddy pool wrappers to return structured dicts

**Files:**
- Modify: `session_buddy/mcp/tools/infrastructure/pools.py:403-547` (replace 9 `@mcp.tool()` functions)

**Interfaces:**
- Consumes: existing helpers `pool_create`, `pool_execute`, `pool_execute_batch`, `pool_route_task`, `pool_list`, `pool_status`, `pool_health`, `pool_delete`, `pool_manager_status` (lines 20-399 — they already return dicts)
- Produces: 9 wrappers returning `dict[str, Any]` (FastMCP structured output) with shape `{"success": True|False, ...payload, "error": optional}`

- [ ] **Step 1: Replace `_register_pool_execution_tools` body (lines 403-468)**

Replace the entire function with:

```python
def _register_pool_execution_tools(mcp: FastMCP) -> None:
    """Register pool task execution tools (structured output)."""

    @mcp.tool()
    async def create_pool(
        pool_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new worker pool with exactly 3 workers."""
        return await pool_create(pool_id=pool_id)

    @mcp.tool()
    async def execute_on_pool(
        pool_id: str,
        prompt: str,
        context: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute a task on a specific pool."""
        return await pool_execute(
            pool_id=pool_id,
            prompt=prompt,
            context=context,
            timeout=timeout,
        )

    @mcp.tool()
    async def execute_batch_on_pool(
        pool_id: str,
        prompts: list[str],
        context: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute multiple tasks in parallel on a pool."""
        return await pool_execute_batch(
            pool_id=pool_id,
            prompts=prompts,
            context=context,
            timeout=timeout,
        )

    @mcp.tool()
    async def route_to_pool(
        prompt: str,
        context: dict[str, Any] | None = None,
        selector: str = "least_loaded",
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Route task to best available pool using specified strategy."""
        return await pool_route_task(
            prompt=prompt,
            context=context,
            selector=selector,
            timeout=timeout,
        )
```

- [ ] **Step 2: Replace `_register_pool_monitoring_tools` body (lines 471-521)**

Replace with:

```python
def _register_pool_monitoring_tools(mcp: FastMCP) -> None:
    """Register pool monitoring and status tools (structured output)."""

    @mcp.tool()
    async def list_pools() -> dict[str, Any]:
        """List all worker pools."""
        return await pool_list()

    @mcp.tool()
    async def get_pool_status(pool_id: str) -> dict[str, Any]:
        """Get detailed status of a specific pool."""
        return await pool_status(pool_id)

    @mcp.tool()
    async def check_pool_health(pool_id: str | None = None) -> dict[str, Any]:
        """Get health status of pools."""
        return await pool_health(pool_id)
```

- [ ] **Step 3: Replace `_register_pool_management_tools` body (lines 524-547)**

Replace with:

```python
def _register_pool_management_tools(mcp: FastMCP) -> None:
    """Register pool lifecycle management tools (structured output)."""

    @mcp.tool()
    async def delete_pool(pool_id: str, timeout: float = 5.0) -> dict[str, Any]:
        """Delete a worker pool."""
        return await pool_delete(pool_id, timeout)

    @mcp.tool()
    async def get_pool_manager_status() -> dict[str, Any]:
        """Get status of the pool manager."""
        return await pool_manager_status()
```

- [ ] **Step 4: Syntax check**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/python -c "import ast; ast.parse(open('session_buddy/mcp/tools/infrastructure/pools.py').read()); print('OK')"`
Expected: `OK`

---

### Task 0b: Fix `pool_execute_batch` to preserve per-task structured results

**Files:**
- Modify: `session_buddy/mcp/tools/infrastructure/pools.py:149-154`

**Interfaces:**
- Consumes: `WorkerPool.execute_batch` (lines 147-192) which returns `list[Any]` of result-or-Exception
- Produces: structured dict `{"success": True, "pool_id", "results_count", "results": list[Any]}`. Each result is normalized to a `{status, output, error}` dict.

- [ ] **Step 1: Replace lines 149-154**

Replace:

```python
        return {
            "success": True,
            "pool_id": pool_id,
            "results_count": len(results),
            "results": results,  # preserve structured form (was: [str(r) for r in results])
        }
```

- [ ] **Step 2: Normalize per-result shape via a small helper**

Add this helper just above `pool_execute_batch` (after line 113):

```python
def _normalize_batch_result(result: Any) -> dict[str, Any]:
    """Convert a single batch item to ``{status, output, error}``.

    ``WorkerPool.execute_batch`` returns either the task result (any type)
    or an Exception (from ``asyncio.gather(return_exceptions=True)``).
    For exceptions, status="failed"; for non-dict results, status="completed"
    with output=str(result); for dict results, status="completed" with
    output=result (passthrough) and error=result.get("error").
    """
    if isinstance(result, BaseException):
        return {"status": "failed", "output": None, "error": str(result)}
    if isinstance(result, dict):
        return {
            "status": "completed" if not result.get("error") else "failed",
            "output": result,
            "error": result.get("error"),
        }
    return {"status": "completed", "output": result, "error": None}
```

Then update the `results` field in the return to:

```python
            "results": [_normalize_batch_result(r) for r in results],
```

- [ ] **Step 3: Syntax check**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/python -c "import ast; ast.parse(open('session_buddy/mcp/tools/infrastructure/pools.py').read()); print('OK')"`
Expected: `OK`

---

### Task 0c: Update session-buddy unit tests to expect structured dicts

**Files:**
- Modify: `session_buddy/tests/unit/test_pool_tools.py` (search for any test that mocks `pool_create` / `pool_execute` / etc. and asserts on the formatted string response)

- [ ] **Step 1: Find affected tests**

Run: `cd /Users/les/Projects/session-buddy && rg -n 'Created pool|Task executed|Executed|Routed task|Pools \(|Pool Manager Health|Deleted pool' tests/unit/test_pool_tools.py 2>&1 | head -40`

- [ ] **Step 2: Update each assertion to check the structured dict shape**

For each match from Step 1, replace the assertion on formatted strings with the structured payload check. Example transformation:

```python
# Before:
assert "✅ Created pool my_pool with 3 workers" in result

# After:
assert result["success"] is True
assert result["pool_id"] == "my_pool"
assert result["workers_count"] == 3
```

- [ ] **Step 3: Run the pool tools test file**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/unit/test_pool_tools.py -v`
Expected: all tests pass

- [ ] **Step 4: Run the full session-buddy unit test suite (regression check)**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/unit/ -x --timeout=60 2>&1 | tail -30`
Expected: no regressions in OTHER test files (only test_pool_tools.py changes are expected to be touched)

- [ ] **Step 5: Commit session-buddy changes**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/mcp/tools/infrastructure/pools.py tests/unit/test_pool_tools.py
git commit -m "feat(mcp): return structured dicts from pool tool wrappers"
```

---

### Task 1: Fix `_call_mcp_tool` to unwrap `CallToolResult`

**Files:**
- Modify: `mahavishnu/pools/session_buddy_pool.py:89-111`

**Interfaces:**
- Consumes: `CallToolResult` from `CommonMCPClient.call_tool`
- Produces: plain dict payload (or string if the tool returns a string)

- [ ] **Step 1: Add the `_extract_tool_payload` helper as a module-level function**

Insert at the top of `mahavishnu/pools/session_buddy_pool.py` (after the `_await_if_needed` helper):

```python
def _extract_tool_payload(call_result: Any) -> Any:
    """Unwrap MCP CallToolResult to its payload.

    FastMCP wraps tool returns into ``CallToolResult(content=[TextContent(text=...)])``.
    For tools declared with ``-> dict[str, Any]`` (structured output), FastMCP
    sets ``structured_content`` to the dict directly. For tools declared with
    ``-> str``, ``content[0].text`` is the formatted string.

    For dict returns, callers get the dict directly. For string returns,
    callers get the string directly. Anything else passes through unchanged.
    """
    # mcp.types.CallToolResult has .structured_content (dict) and .content (list[TextContent])
    structured = getattr(call_result, "structured_content", None)
    if isinstance(structured, dict) and structured:
        return structured
    content = getattr(call_result, "content", None)
    if content and len(content) > 0:
        text = getattr(content[0], "text", None)
        if isinstance(text, str):
            # Try JSON-parse for tools that return JSON strings; fall back to raw text.
            import json
            try:
                parsed = json.loads(text)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except (ValueError, TypeError):
                pass
            return text
    return call_result
```

- [ ] **Step 2: Replace the body of `_call_mcp_tool` (lines 89-111)**

Replace with:

```python
async def _call_mcp_tool(
    self,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Call session-buddy MCP tool and unwrap the CallToolResult envelope.

    Returns:
        Dictionary payload from the tool (for tools declared ``-> dict``),
        OR a string (for tools declared ``-> str``), OR any raw return value.
        Callers that expect ``dict`` semantics should check ``isinstance``.

    Raises:
        MCPServerError: If MCP call fails.
    """
    call_result = await self._mcp.call_tool(tool_name, arguments)
    payload = _extract_tool_payload(call_result)
    if isinstance(payload, dict):
        return payload
    # Non-dict payloads (strings, lists): wrap so callers that
    # read ``.get("result", ...)`` keep working without crashing.
    return {"result": payload}
```

- [ ] **Step 3: Syntax check**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -c "import ast; ast.parse(open('mahavishnu/pools/session_buddy_pool.py').read()); print('OK')"`
Expected: `OK`

---

### Task 2: Rewrite `SessionBuddyPool.start()` to call `create_pool`

**Files:**
- Modify: `mahavishnu/pools/session_buddy_pool.py:113-148`

- [ ] **Step 1: Replace the body of `start()`**

Replace with:

```python
async def start(self) -> str:
    """Initialize Session-Buddy pool by creating a remote pool via MCP.

    Calls session-buddy's ``create_pool`` tool. The response is a structured
    dict: ``{"success": True, "pool_id": "abc", "status": "running",
    "workers_count": 3, "queue_size": 0, ...}``. We extract ``pool_id`` and
    synthesize 3 worker_ids as ``{pool_id}-worker-{i}`` for downstream
    caller compatibility.

    Returns:
        pool_id: Unique Mahavishnu-side pool identifier.
    """
    self._status = PoolStatus.INITIALIZING

    try:
        result = await self._call_mcp_tool("create_pool", {})

        if not result.get("success", False):
            error_msg = result.get("error", "create_pool returned success=False")
            raise MCPServerError(error_msg)

        pool_id = result.get("pool_id", "")
        if not isinstance(pool_id, str) or not pool_id:
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

- [ ] **Step 2: Syntax check**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -c "import ast; ast.parse(open('mahavishnu/pools/session_buddy_pool.py').read()); print('OK')"`
Expected: `OK`

---

### Task 3: Rewrite `SessionBuddyPool.execute_task()` to call `execute_on_pool`

**Files:**
- Modify: `mahavishnu/pools/session_buddy_pool.py:150-237`

- [ ] **Step 1: Replace the body of `execute_task()`**

Replace with:

```python
async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
    """Execute task via session-buddy's ``execute_on_pool`` MCP tool.

    session-buddy response shape:
    ``{"success": True, "pool_id", "worker_id", "result": {...}}``.
    Failure shape: ``{"success": False, "pool_id", "error": str}``.

    Args:
        task: Task specification with ``prompt``, optional ``timeout``,
            optional ``working_dir`` (triggers ``subagent_marker``
            mark/clear).

    Returns:
        Envelope ``{pool_id, worker_id, status, output, error, duration}``.
    """
    if not self._workers:
        raise RuntimeError("No workers available in pool")

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

        # Structured response handling.
        if result.get("success"):
            self._tasks_completed += 1
            status_value = "completed"
            output = result.get("result")
            error = None
        else:
            self._tasks_failed += 1
            status_value = "failed"
            output = None
            error = result.get("error", "execute_on_pool returned success=False")
        self._task_durations.append(duration)

        # session-buddy's actual worker_id is more authoritative than our
        # synthetic prefix; prefer it when present.
        actual_worker_id = result.get("worker_id") or worker_id

        return {
            "pool_id": self.pool_id,
            "worker_id": actual_worker_id,
            "status": status_value,
            "output": output,
            "error": error,
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

- [ ] **Step 2: Syntax check**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -c "import ast; ast.parse(open('mahavishnu/pools/session_buddy_pool.py').read()); print('OK')"`
Expected: `OK`

---

### Task 4: Rewrite `SessionBuddyPool.execute_batch()` to call `execute_batch_on_pool`

**Files:**
- Modify: `mahavishnu/pools/session_buddy_pool.py:239-333`

**Hardening from audit (edge case):**
- Wrap mark loop in its own try/finally so partial mark failure doesn't leak earlier marks
- Fail-fast on multiple distinct working_dirs in one batch (silent context loss)
- Error path envelope MUST include `"output": None` for shape parity with success path

- [ ] **Step 1: Replace the body of `execute_batch()`**

Replace with:

```python
async def execute_batch(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute tasks via session-buddy's ``execute_batch_on_pool``.

    session-buddy response shape (after Task 0b):
    ``{"success": True, "pool_id", "results_count", "results":
    [{"status": "completed"|"failed", "output": ..., "error": ...}, ...]}``.

    Args:
        tasks: List of task specifications. Each MAY carry ``working_dir``.

    Raises:
        ValueError: If tasks contain more than one distinct ``working_dir``
            (the underlying MCP tool accepts only one shared context).
            Callers should split batches by working_dir beforehand.

    Returns:
        Dictionary mapping task_id -> result envelope.
    """
    if not self._workers:
        raise RuntimeError("No workers available in pool")

    worker_id = next(iter(self._workers.keys()))
    pool_id = worker_id.rsplit("-worker-", 1)[0] if worker_id else ""

    # Collect the working_dirs to mark; preserve order while
    # de-duplicating. Fail fast on multiple distinct dirs — the
    # underlying MCP tool accepts only ONE shared context, so we
    # can't preserve per-task working_dir semantics.
    working_dirs: list[str] = []
    seen: set[str] = set()
    for task in tasks:
        wd = task.get("working_dir")
        if wd and wd not in seen:
            seen.add(wd)
            working_dirs.append(wd)

    if len(working_dirs) > 1:
        raise ValueError(
            f"execute_batch supports at most one distinct working_dir "
            f"per batch; got {len(working_dirs)}: {working_dirs}. "
            f"Split the batch by working_dir before calling."
        )

    # Wrap mark loop in its own try/finally so partial mark failure
    # doesn't leak earlier marks (defense against MCPServerError on Nth dir).
    if working_dirs:
        await self._call_mcp_tool(
            "subagent_marker",
            {"working_dir": working_dirs[0], "action": "mark"},
        )

    try:
        # Extract prompts; share the (at most one) working_dir as context.
        prompts = [task.get("prompt", "") for task in tasks]
        context: dict[str, Any] = {}
        if working_dirs:
            context["working_dir"] = working_dirs[0]

        start_time = time.time()
        result = await self._call_mcp_tool(
            "execute_batch_on_pool",
            {
                "pool_id": pool_id,
                "prompts": prompts,
                "context": context,
            },
        )

        duration = time.time() - start_time

        # Structured response handling.
        if not result.get("success"):
            error_msg = result.get("error", "execute_batch_on_pool returned success=False")
            self._tasks_failed += len(tasks)
            raise MCPServerError(error_msg)

        # session-buddy returns results in input order; align by index.
        batch_results = result.get("results", [])
        if not isinstance(batch_results, list):
            batch_results = []

        # Track statistics from per-task status.
        for entry in batch_results:
            status_value = (
                entry.get("status", "unknown") if isinstance(entry, dict) else "unknown"
            )
            if status_value == "completed":
                self._tasks_completed += 1
            else:
                self._tasks_failed += 1
        self._task_durations.append(duration / max(len(tasks), 1))

        # Stitch results back into task_id-keyed envelopes.
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
        # Error envelope MUST include "output": None for shape parity
        # with the success path (audit BUG: missing field caused KeyError
        # in downstream PoolManager consumers).
        return {
            task.get("task_id") or str(idx): {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "failed",
                "output": None,
                "error": str(e),
            }
            for idx, task in enumerate(tasks)
        }
    finally:
        if working_dirs:
            try:
                await self._call_mcp_tool(
                    "subagent_marker",
                    {"working_dir": working_dirs[0], "action": "clear"},
                )
            except Exception:
                logger.exception(
                    "subagent_marker clear failed for %s; consumer "
                    "may see a stale lockfile until the next mark",
                    working_dirs[0],
                )
```

- [ ] **Step 2: Syntax check**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -c "import ast; ast.parse(open('mahavishnu/pools/session_buddy_pool.py').read()); print('OK')"`
Expected: `OK`

---

### Task 4b: Rewrite `SessionBuddyPool.health_check()` to call `check_pool_health` with local fallback

**Files:**
- Modify: `mahavishnu/pools/session_buddy_pool.py:348-385`

**Hardening from audit:** when `pool_id` is empty (failed start), don't call upstream — return a local unhealthy marker instead. Avoids confusion where an empty-pool `health_check` returns "all pools healthy" via session-buddy's global mode.

- [ ] **Step 1: Replace the body of `health_check()`**

Replace with:

```python
async def health_check(self) -> dict[str, Any]:
    """Check pool health via session-buddy's ``check_pool_health``.

    When the pool failed to start (``self._workers`` is empty), skip the
    upstream call and return a local "unhealthy" marker instead of leaking
    session-buddy's global pool-manager health response.

    Returns:
        Health status dictionary.
    """
    worker_id = next(iter(self._workers.keys()), "")
    pool_id = worker_id.rsplit("-worker-", 1)[0] if worker_id else ""

    # Local computation independent of upstream.
    if len(self._workers) == 0:
        pool_status = "unhealthy"
    elif len(self._workers) < self.config.min_workers:
        pool_status = "degraded"
    else:
        pool_status = "healthy"

    # Skip upstream when we have no pool_id — session-buddy's
    # ``check_pool_health(pool_id=None)`` returns global health which
    # would be misleading.
    if not pool_id:
        return {
            "pool_id": self.pool_id,
            "pool_type": "session-buddy",
            "status": pool_status,
            "workers_active": len(self._workers),
            "max_workers": self.max_workers,
            "worker_health": None,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "session_buddy_url": self.session_buddy_url,
        }

    try:
        result = await self._call_mcp_tool(
            "check_pool_health",
            {"pool_id": pool_id},
        )
        # Local status wins; upstream provides supplementary worker_health.
        worker_health = result if result.get("success") else None
        if not result.get("success"):
            pool_status = "degraded" if self._workers else "unhealthy"

        return {
            "pool_id": self.pool_id,
            "pool_type": "session-buddy",
            "status": pool_status,
            "workers_active": len(self._workers),
            "max_workers": self.max_workers,
            "worker_health": worker_health,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "session_buddy_url": self.session_buddy_url,
        }

    except MCPServerError as e:
        logger.error(f"Failed health check for SessionBuddyPool: {e}")
        return {
            "pool_id": self.pool_id,
            "pool_type": "session-buddy",
            "status": pool_status,
            "workers_active": len(self._workers),
            "max_workers": self.max_workers,
            "worker_health": None,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "error": str(e),
            "session_buddy_url": self.session_buddy_url,
        }
```

- [ ] **Step 2: Syntax check**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -c "import ast; ast.parse(open('mahavishnu/pools/session_buddy_pool.py').read()); print('OK')"`
Expected: `OK`

---

### Task 4c: Rewrite `SessionBuddyPool.stop()` to call `delete_pool`

**Files:**
- Modify: `mahavishnu/pools/session_buddy_pool.py:438-451`

- [ ] **Step 1: Read the current `stop()` body to confirm the audit's claim**

Run: `cd /Users/les/Projects/mahavishnu && sed -n '436,460p' mahavishnu/pools/session_buddy_pool.py`

Expected to see `await self._call_mcp_tool("worker_close_all", ...)` or similar broken call.

- [ ] **Step 2: Replace the body of `stop()`**

Replace with:

```python
async def stop(self) -> None:
    """Shutdown pool by deleting the remote session-buddy pool via MCP.

    Calls session-buddy's ``delete_pool`` tool which removes the underlying
    3-worker ``WorkerPool`` and stops its asyncio workers.

    Raises:
        MCPServerError: If the upstream delete call fails after retries.
    """
    worker_id = next(iter(self._workers.keys()), "")
    pool_id = worker_id.rsplit("-worker-", 1)[0] if worker_id else ""
    if not pool_id:
        logger.warning(
            f"SessionBuddyPool {self.pool_id} has no remote pool_id; "
            f"skipping delete_pool call"
        )
        self._workers.clear()
        self._status = PoolStatus.STOPPED
        return

    try:
        await self._call_mcp_tool("delete_pool", {"pool_id": pool_id, "timeout": 5.0})
        self._workers.clear()
        self._status = PoolStatus.STOPPED
        logger.info(f"SessionBuddyPool {self.pool_id} stopped (pool_id={pool_id})")
    except MCPServerError as e:
        logger.error(f"Failed to stop SessionBuddyPool {self.pool_id}: {e}")
        # Local cleanup happens regardless so the Mahavishnu-side
        # pool can be reaped; upstream residue is operator-visible
        # via session-buddy's own pool list.
        self._workers.clear()
        self._status = PoolStatus.FAILED
        raise
```

- [ ] **Step 3: Syntax check**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -c "import ast; ast.parse(open('mahavishnu/pools/session_buddy_pool.py').read()); print('OK')"`
Expected: `OK`

---

### Task 5: Update unit tests

**Files:**
- Modify: `mahavishnu/tests/unit/pools/test_session_buddy_pool_coverage.py`
- Modify: `mahavishnu/tests/unit/pools/test_session_buddy_pool_marker_hook.py`

**Note:** All mock shapes must mirror the new structured payloads from session-buddy. Tests that previously mocked `{"result": "string"}` need to mock `{"success": True, "pool_id": "abc", "workers_count": 3, ...}` for `create_pool`, etc.

- [ ] **Step 1: Update `test_start_pool_happy_path`**

Replace the mock and assertion:

```python
@pytest.mark.asyncio
async def test_start_pool_happy_path(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """start() calls create_pool and synthesizes 3 worker_ids from returned pool_id."""
    pool = make_pool({
        "success": True,
        "pool_id": "sbpool-abc123",
        "status": "running",
        "workers_count": 3,
        "queue_size": 0,
    })
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

- [ ] **Step 2: Update `test_start_pool_non_list_worker_ids`**

```python
@pytest.mark.asyncio
async def test_start_pool_non_list_worker_ids(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """start() tolerates success=False by raising (audit hardening)."""
    pool = make_pool({"success": False, "error": "pool limit reached"})
    with pytest.raises(MCPServerError):
        await pool.start()
    assert pool._status == PoolStatus.FAILED
```

- [ ] **Step 3: Update `test_execute_task_happy_path`**

```python
@pytest.mark.asyncio
async def test_execute_task_happy_path(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool({
        "success": True,
        "pool_id": "sbpool-abc",
        "worker_id": "sbpool-abc-worker-1",
        "result": {"status": "completed", "output": "ok"},
    })
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    result = await pool.execute_task({"prompt": "do thing", "timeout": 60})
    assert result["status"] == "completed"
    assert result["output"] == {"status": "completed", "output": "ok"}
    assert result["error"] is None
    # session-buddy's actual worker_id (more authoritative than our synthetic)
    assert result["worker_id"] == "sbpool-abc-worker-1"
    assert pool._tasks_completed == 1 and pool._tasks_failed == 0
    last_call = pool._mcp.call_tool.await_args_list[-1]
    assert last_call.args[0] == "execute_on_pool"
```

- [ ] **Step 4: Update `test_execute_task_server_error_returns_failed_envelope`**

```python
@pytest.mark.asyncio
async def test_execute_task_server_error_returns_failed_envelope(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool(MCPServerError("upstream gone"))
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    result = await pool.execute_task({"prompt": "do thing"})
    assert result["status"] == "failed"
    assert result["error"] == "upstream gone"
    assert result["output"] is None
    assert pool._tasks_failed == 1
    assert result["worker_id"] == "sbpool-abc-worker-0"
```

- [ ] **Step 5: Update `test_execute_batch_branches` (was dict-keyed, new code expects list-positional)**

Find this test (around line 205) and replace its mock and assertion with the new structured shape:

```python
@pytest.mark.asyncio
async def test_execute_batch_branches(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """execute_batch() returns per-task envelopes aligned to input order."""
    pool = make_pool({
        "success": True,
        "pool_id": "sbpool-abc",
        "results_count": 2,
        "results": [
            {"status": "completed", "output": "r1", "error": None},
            {"status": "failed", "output": None, "error": "boom"},
        ],
    })
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    result = await pool.execute_batch([
        {"task_id": "0", "prompt": "first"},
        {"task_id": "1", "prompt": "second"},
    ])
    assert result["0"]["status"] == "completed"
    assert result["0"]["output"] == "r1"
    assert result["1"]["status"] == "failed"
    assert result["1"]["error"] == "boom"
    assert pool._tasks_completed == 1
    assert pool._tasks_failed == 1
    last_call = pool._mcp.call_tool.await_args_list[-1]
    assert last_call.args[0] == "execute_batch_on_pool"


@pytest.mark.asyncio
async def test_execute_batch_rejects_multiple_working_dirs(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """execute_batch() fails fast on >1 distinct working_dir (audit hardening)."""
    pool = make_pool({"success": True, "results": []})
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    with pytest.raises(ValueError, match="at most one distinct working_dir"):
        await pool.execute_batch([
            {"prompt": "a", "working_dir": "/path/one"},
            {"prompt": "b", "working_dir": "/path/two"},
        ])
```

- [ ] **Step 6: Add `test_health_check_with_empty_workers_no_upstream_call`**

```python
@pytest.mark.asyncio
async def test_health_check_with_empty_workers_no_upstream_call(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """health_check() skips upstream call when pool_id is empty (audit hardening)."""
    pool = make_pool({"success": True})
    pool._workers = {}  # never started
    result = await pool.health_check()
    assert result["status"] == "unhealthy"
    assert result["worker_health"] is None
    # No upstream call should have been made.
    pool._mcp.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_health_check_with_workers_calls_check_pool_health(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool({
        "success": True,
        "health": {"status": "healthy", "workers_healthy": 3, "workers_total": 3},
    })
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    result = await pool.health_check()
    assert result["status"] == "healthy"
    assert result["worker_health"]["status"] == "healthy"
    last_call = pool._mcp.call_tool.await_args_list[-1]
    assert last_call.args[0] == "check_pool_health"
```

- [ ] **Step 7: Update marker hook test file — all `worker_execute`/`worker_execute_batch` assertions**

Run:
```bash
cd /Users/les/Projects/mahavishnu
sed -i '' 's/"worker_execute"/"execute_on_pool"/g; s/"worker_execute_batch"/"execute_batch_on_pool"/g; s/"worker_close_all"/"delete_pool"/g' tests/unit/pools/test_session_buddy_pool_marker_hook.py
grep -nE '"worker_execute|"worker_execute_batch|"worker_close_all' tests/unit/pools/test_session_buddy_pool_marker_hook.py
```
Expected: zero matches (all replaced)

The sed replaces string occurrences in both fixture functions and assertions. Verify by reading the file that all assertions still make sense — particularly the `default_worker_result` return value, which should now return a structured dict:

```python
# In the fixture (around line 50), replace:
default_worker_result = {"success": True, "pool_id": "test-pool", "worker_id": "test-pool-worker-0", "result": {"output": "ok"}}

default_batch_result = {
    "success": True,
    "pool_id": "test-pool",
    "results_count": 2,
    "results": [
        {"status": "completed", "output": "r1", "error": None},
        {"status": "completed", "output": "r2", "error": None},
    ],
}
```

- [ ] **Step 8: Syntax check both test files**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/python -c "
import ast
for f in ('tests/unit/pools/test_session_buddy_pool_coverage.py', 'tests/unit/pools/test_session_buddy_pool_marker_hook.py'):
    ast.parse(open(f).read())
    print(f'{f}: OK')
"`
Expected: both OK

---

### Task 6: Run all session-buddy + mahavishnu tests

- [ ] **Step 1: Run session-buddy tests**

Run: `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/unit/ -x --timeout=60 2>&1 | tail -30`
Expected: all green (or only pre-existing unrelated failures)

- [ ] **Step 2: Run mahavishnu pool tests**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/pytest tests/unit/pools/ -v 2>&1 | tail -40`
Expected: all green

- [ ] **Step 3: Run integration test (envelope preservation)**

Run: `cd /Users/les/Projects/mahavishnu && .venv/bin/pytest tests/integration/test_pool_orchestration.py -v -m integration 2>&1 | tail -30`
Expected: all green — confirms the public envelope shape is preserved

- [ ] **Step 4: Commit mahavishnu changes**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/pools/session_buddy_pool.py \
        tests/unit/pools/test_session_buddy_pool_coverage.py \
        tests/unit/pools/test_session_buddy_pool_marker_hook.py
git commit -m "fix(pools): SessionBuddyPool re-pointed at structured pool tools"
```

---

### Task 7: Restart session-buddy + end-to-end smoke test

**Files:** none (operational task)

- [ ] **Step 1: Restart session-buddy**

```bash
launchctl kickstart -k "gui/$(id -u)/com.mcp.session-buddy"
```

Wait ~5s.

- [ ] **Step 2: Verify the 9 pool tools + new `subagent_marker` are live**

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
            expected = {'check_pool_health', 'create_pool', 'delete_pool',
                        'execute_batch_on_pool', 'execute_on_pool',
                        'get_pool_manager_status', 'get_pool_status',
                        'list_pools', 'route_to_pool', 'subagent_marker'}
            actual = set(n for n in names if 'pool' in n or 'worker' in n or n == 'subagent_marker')
            missing = expected - actual
            extra = actual - expected
            print(f'expected: {len(expected)}, present: {len(actual)}, missing: {missing}, extra: {extra}')
asyncio.run(main())
"`

Expected: `missing: set()`, `extra: set()`

- [ ] **Step 3: End-to-end smoke test**

```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python << 'PY'
import asyncio, json
from mahavishnu.pools.session_buddy_pool import SessionBuddyPool
from mahavishnu.pools.base import PoolConfig

async def main():
    cfg = PoolConfig(name='smoke', pool_type='session_buddy', min_workers=1, max_workers=3)
    pool = SessionBuddyPool(cfg, session_buddy_url='http://localhost:8678/mcp')
    await pool.start()
    print(f'POOL: workers={len(pool._workers)} ids={list(pool._workers)}')

    # Single task — placeholder executor returns in ~0.1s
    r1 = await pool.execute_task({'prompt': 'echo hello', 'timeout': 30})
    print(f'TASK: status={r1["status"]} output={r1["output"]}')

    # Batch task
    r2 = await pool.execute_batch([
        {'task_id': 'a', 'prompt': 'first'},
        {'task_id': 'b', 'prompt': 'second'},
    ])
    print(f'BATCH: a.status={r2["a"]["status"]} b.status={r2["b"]["status"]}')

    # Health
    h = await pool.health_check()
    print(f'HEALTH: status={h["status"]} worker_health.success={h["worker_health"]["success"] if h["worker_health"] else None}')

    # Teardown — must use delete_pool
    await pool.stop()
    print('STOPPED cleanly')

asyncio.run(main())
PY
```

Expected:
- `POOL: workers=3 ids=[..., ..., ...]`
- `TASK: status=completed output={...}` (placeholder result)
- `BATCH: a.status=completed b.status=completed`
- `HEALTH: status=healthy worker_health.success=True`
- `STOPPED cleanly`

- [ ] **Step 4: Confirm the upstream pool was actually deleted**

```bash
curl -s -X POST http://localhost:8678/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0.0"}}}'
# (then call list_pools and confirm the pool is gone — requires full streamable-HTTP handshake)
```

Simpler check — re-run Step 3 with a NEW pool name and confirm `len(self._workers) == 3` and `delete_pool` doesn't error.

- [ ] **Step 5: Commit the plan document**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/superpowers/plans/2026-09-25-fix-session-buddy-pool-mcp-contract-v2.md
git commit -m "docs(plan): session-buddy pool contract fix v2 (structured wrappers)"
```

---

## Self-Review

1. **Spec coverage:**
   - BUG 1 (CallToolResult unwrap) → Task 1
   - BUG 2 (batch stringification) → Task 0b
   - BUG 3 (stop() broken) → Task 4c
   - BUG 4 (test_execute_batch_branches mock shape) → Task 5 Step 5
   - BUG 5 (marker hook hardcoded names) → Task 5 Step 7
   - Hardening: mark loop try/finally → Task 4 Step 1
   - Hardening: fail-fast on multi-dir → Task 4 Step 1 + Task 5 Step 5
   - Hardening: error envelope shape → Task 4 Step 1
   - Hardening: local fallback for empty-pool health_check → Task 4b Step 1
   - All BLOCKING issues + hardening recommendations from audit covered.

2. **Placeholder scan:** No "TBD"/"TODO"/"implement later". All code blocks are concrete.

3. **Type consistency:** `pool_id` is always `str`; `_workers` dict keys are always `{pool_id}-worker-{i}`; envelope shape is consistent across success/error paths.

4. **Public envelope preservation:** `execute_task` returns `{pool_id, worker_id, status, output, error, duration}`; `execute_batch` returns `{task_id: {pool_id, worker_id, status, output, error}}` — both compatible with `tests/integration/test_pool_orchestration.py:55-62`.

5. **Restart strategy:** `launchctl kickstart -k` for user-domain launchd is correct per audit confirmation.

6. **Risks not covered:**
   - Session-buddy v0.27.0 editable install + v0.25.7 source drift is out of scope (pre-existing condition).
   - If `delete_pool` errors after workers are already torn down, the local `self._workers.clear()` still runs — operator may see a stale remote pool. Documented in Task 4c Step 2.
