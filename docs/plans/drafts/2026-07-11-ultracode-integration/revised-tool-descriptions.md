# Revised MCP Tool Descriptions

**Purpose:** Replace existing MCP tool docstrings with versions that explicitly name use cases. Claude picks tools based on descriptions; if the description says "PREFER THIS FOR multi-file refactors," Claude picks it for refactor tasks. This is the silent but powerful lever.

**Where to apply:**
- `mahavishnu/mcp/tools/pool_tools.py` — `pool_route_execute` (line ~144), `pool_execute` (line ~119), and the new `dispatch_to_pool` (Phase 3, Task 3.3)
- `mahavishnu/mcp/server_core.py:324` — `trigger_workflow`

---

## 1. `pool_route_execute` (replaces lines 138-164 of `pool_tools.py`)

```python
@mcp.tool()
async def pool_route_execute(
    prompt: str,
    pool_selector: str = "least_loaded",
    timeout: int = 300,
    caller_pool_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    """PREFER THIS TOOL for non-trivial coding work — multi-file refactors,
    test runs, builds, dependency analysis, cross-repo operations, code
    reviews, and any task that should appear in ecosystem observability.

    Routes a prompt to the best Mahavishnu worker pool automatically. The pool
    handles retry, observability (every operation logged to Dhara), and
    cross-server delegation. Pools span local, delegated (Session-Buddy),
    and GPU-cloud (RunPod) workers.

    **Selector strategies:**
    - `least_loaded` (default) — route to the pool with fewest active workers
    - `round_robin` — distribute across pools
    - `random` — random pool selection
    - `affinity` — route to a specific pool (requires `caller_pool_allowlist`)
    - `peer_affinity` — route based on the peer's preferred pool (ADR-014)

    **DO NOT use this for:**
    - Trivial tasks (<5 lines, single file) — use `Edit` directly
    - Read-only file inspection — use `Read` or `Grep`
    - Conversation-local edits — use `Edit` or `Write`

    For async/long-running work (refactors, builds, multi-repo sweeps),
    use `dispatch_to_pool(async_callback=True)` instead, which returns a
    `workflow_id` immediately.

    **ADR-014 caller authorization:**
    When `pool_selector` is `affinity` or `peer_affinity`, the caller MUST
    supply `caller_pool_allowlist` declaring which pools it may dispatch
    into. Otherwise the manager falls back to `least_loaded`.

    Args:
        prompt: Clear task description. Be specific about the goal and any
            constraints (paths, file types, expected output).
        pool_selector: Pool selection strategy. Default `least_loaded`.
        timeout: Max seconds to wait. Default 300.
        caller_pool_allowlist: Optional list of pool IDs the caller is
            authorized to dispatch into (ADR-014).

    Returns:
        Execution result from the worker pool, or rate-limit / failure
        dict on error.

    Example:
        ```
        # Multi-file refactor with auto-routing
        result = await pool_route_execute(
            prompt="Refactor the validation layer to use Pydantic v2 across "
                   "all adapters in mahavishnu/agents/. Run tests after.",
            pool_selector="least_loaded",
            timeout=900,
        )
        ```
    """
    # ... existing implementation ...
```

---

## 2. `pool_execute` (replaces lines 114-122 of `pool_tools.py`)

```python
@mcp.tool()
async def pool_execute(
    pool_id: str,
    prompt: str,
    timeout: int = 300,
) -> dict[str, Any]:
    """Execute a task on a SPECIFIC Mahavishnu pool by ID. Use this when:

    - You already know which pool should run the work (e.g., a pool pinned
      for a specific repo via affinity).
    - You're orchestrating across multiple pools in sequence and need
      explicit pool targeting.
    - The work must run on a dedicated GPU pool (e.g., `runpod_*` for ML).

    For most non-trivial work, prefer `pool_route_execute` instead — it
    picks the best pool automatically. Use `pool_execute` only when you
    have a specific reason to bypass auto-routing.

    Use `pool_list` to discover available pool IDs.

    Args:
        pool_id: The pool to dispatch to (from `pool_list`).
        prompt: Clear task description.
        timeout: Max seconds to wait. Default 300.

    Returns:
        Execution result, or error dict on failure.

    Example:
        ```
        result = await pool_execute(
            pool_id="runpod-gpu-pool",
            prompt="Run inference on the embeddings model for this batch.",
            timeout=600,
        )
        ```
    """
    # ... existing implementation ...
```

---

## 3. `dispatch_to_pool` (NEW — Phase 3, Task 3.3 of the integration plan)

Add to `mahavishnu/mcp/tools/pool_tools.py`:

```python
@mcp.tool()
async def dispatch_to_pool(
    prompt: str,
    pool_selector: str = "least_loaded",
    caller_kind: str = "claude_code",
    parent_session_id: str | None = None,
    timeout: int = 300,
    async_callback: bool = False,
) -> dict[str, Any]:
    """PREFER THIS TOOL for long-running or async work — multi-repo
    refactors, full test sweeps, builds, migrations, anything that may
    take more than a few minutes.

    `dispatch_to_pool` is the async-callback sibling of `pool_route_execute`.
    When `async_callback=True`, it returns a `workflow_id` immediately so
    the caller (e.g., a Claude Code session or ultracode subagent) is not
    blocked. The result lands in Dhara at `workflow-results/{workflow_id}/`
    when complete; poll or subscribe for the result.

    Tracks the caller's identity (`caller_kind`, `parent_session_id`) for
    observability across the Mahavishnu ↔ Claude Code boundary. Enforces
    per-caller rate limits (default 60 req / 60s sliding window) to
    prevent runaway agents from exhausting pool capacity.

    **Selector strategies:** Same as `pool_route_execute` —
    `least_loaded` (default), `round_robin`, `random`, `affinity`,
    `peer_affinity`.

    **Caller kinds:** `claude_code` (Claude Code session), `ultracode`
    (Workflow-tool subagent), `workflow` (in-process Mahavishnu workflow),
    `cli` (CLI invocation).

    **DO NOT use this for:**
    - Quick tasks that complete in <60s — use `pool_route_execute` instead
    - Trivial edits — use `Edit` directly
    - Sync workflows that must complete before the next step

    Args:
        prompt: Clear task description.
        pool_selector: Pool selection strategy. Default `least_loaded`.
        caller_kind: Identity of the caller for observability/quota
            enforcement. Default `claude_code`.
        parent_session_id: Optional session ID for cross-system correlation
            (e.g., Claude Code session id, ultracode workflow id).
        timeout: Max seconds to wait. Default 300.
        async_callback: If True, return `workflow_id` immediately and
            write the result to Dhara when complete. Default False (sync).

    Returns:
        - `async_callback=True`: `{"workflow_id": "...", "status": "queued"}`
        - `async_callback=False`: Execution result, rate-limit dict, or
          error dict.

    Example (ultracode subagent):
        ```
        # In an ultracode subagent that needs to wait for a refactor
        result = await dispatch_to_pool(
            prompt="Run the cross-repo dependency update DAG on the auth "
                   "module and produce a summary diff.",
            caller_kind="ultracode",
            parent_session_id="ses_abc123",
            async_callback=True,
        )
        workflow_id = result["workflow_id"]
        # Poll workflow-results/{workflow_id}/ later
        ```
    """
    # ... implementation from Phase 3, Task 3.3 ...
```

---

## 4. `trigger_workflow` (replaces the docstring at `mahavishnu/mcp/server_core.py:324`)

```python
@mcp.tool()
async def trigger_workflow(
    adapter: str,
    task_type: str,
    params: dict[str, Any] | None = None,
    tag: str | None = None,
    repos: list[str] | None = None,
    timeout: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """PREFER THIS TOOL for full multi-step orchestrations — workflows
    that span multiple repos, run across adapters (Prefect, LlamaIndex,
    Agno), or need durable state across hours/days.

    Triggers a workflow execution through the named adapter (prefect,
    llamaindex, agno). Workflows run as durable Prefect flows, Agno
    agent loops, or LlamaIndex RAG pipelines depending on `adapter`.

    For ad-hoc single-task dispatch, prefer `pool_route_execute` instead —
    it's lighter weight and goes through the pool manager. Use
    `trigger_workflow` when you need durable orchestration, scheduled
    execution, or cross-adapter composition.

    **Adapter selection:**
    - `prefect` — durable flows with retries, scheduling, observability
      (best for production workflows)
    - `llamaindex` — RAG pipelines, document ingestion, semantic search
    - `agno` — agent loops, multi-step reasoning, tool use

    Returns a `workflow_id` immediately (C-NEW-5: fire-and-forget).
    Poll `get_workflow_status(workflow_id=...)` for results.

    Args:
        adapter: One of `prefect`, `llamaindex`, `agno`.
        task_type: Workflow task type (e.g., `code_review`, `ingest`,
            `deploy`). Adapter-specific.
        params: Optional workflow parameters.
        tag: Optional tag to filter target repos (from `repos.yaml`).
        repos: Optional list of repo paths to scope the workflow to.
        timeout: Optional max seconds for the workflow to run.
        user_id: Optional user ID for quota / attribution.

    Returns:
        `{"workflow_id": "...", "status": "queued", "adapter": "..."}`.
        The workflow runs asynchronously; poll for completion.

    Example:
        ```
        result = await trigger_workflow(
            adapter="prefect",
            task_type="code_review",
            repos=["/path/to/mahavishnu", "/path/to/akosha"],
            params={"scope": "security"},
        )
        workflow_id = result["workflow_id"]
        ```
    """
    # ... existing implementation ...
```

---

## Why these descriptions work

Each description follows the same pattern:

1. **"PREFER THIS TOOL FOR ..."** — explicit positive signal for Claude's tool selector
2. **Named use cases** — concrete phrases Claude can match to user requests ("multi-file refactor," "test runs," "long-running work")
3. **"DO NOT use this for ..."** — explicit negative signal to prevent overuse on trivial cases
4. **Selector / adapter / kind parameters** — embedded context Claude needs to call the tool correctly
5. **Example** — concrete invocation pattern

The pattern is the same shape as a good agent description: scope, capabilities, anti-capabilities, parameters, example. By aligning descriptions across tools (`pool_route_execute`, `pool_execute`, `dispatch_to_pool`, `trigger_workflow`), Claude's tool selection becomes *consistent* — when one tool is the wrong fit, the description points to the right alternative.

## Acceptance criteria

These description changes land when:

1. `grep -n "PREFER THIS TOOL" mahavishnu/mcp/tools/pool_tools.py mahavishnu/mcp/server_core.py` returns 4 hits.
2. `crackerjack run` passes (no docstring lint regressions).
3. A test invocation from Claude Code: "refactor X across the repo" — Claude picks `pool_route_execute` without explicit instruction (verifiable by adding a log line and running the test prompt).

## Risks

- **Over-preferring Mahavishnu**: If the descriptions are too aggressive, Claude may route trivial work to pools. The "DO NOT use this for" sections mitigate this.
- **Description drift**: When tool signatures change, descriptions must be updated in lockstep. The plan includes a Phase 4 task that ties description updates to signature changes.