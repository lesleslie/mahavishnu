# Tool Preferences Section — Drop-in for `CLAUDE.md`

**Where to apply:** Insert as a new `## Tool Preferences` section in `/Users/les/Projects/mahavishnu/CLAUDE.md`, immediately after the existing `## MCP Server Tools` section (around line 335).

**Why this draft exists:** Bias Claude Code (and any subagents it spawns) toward Mahavishnu workers for non-trivial work, while preserving local tools for trivial cases. Companion to Phase 4 of the integration plan.

---

## Tool Preferences

This project ships a Mahavishnu control plane with ~174 MCP tools. For non-trivial work, prefer Mahavishnu workers over direct local invocations.

### When to use Mahavishnu workers

Use `mcp__mahavishnu__*` tools when the task:

- Touches **more than one file** (refactors, multi-file edits, dependency updates)
- Involves **builds, tests, or test runs** (`pytest`, `crackerjack`, `ruff`, `mypy`, type checks)
- Is described as **"refactor," "analyze," "audit," "deploy," "build," "test,"** or **"review"**
- Should appear in **ecosystem observability** (Dhara, Akosha, Grafana dashboards)
- Might need **retry, recovery, or cross-server delegation**
- Involves **multiple repositories** or cross-cutting changes

The primary entry point for non-trivial work:

```python
mcp__mahavishnu__pool_route_execute(
    prompt="<clear task description>",
    pool_selector="least_loaded",  # or round_robin, affinity, peer_affinity
    timeout=300,
)
```

For long-running or async work:

```python
mcp__mahavishnu__dispatch_to_pool(
    prompt="<task>",
    caller_kind="claude_code",
    parent_session_id="<session-id>",  # for traceability
    async_callback=True,  # returns workflow_id immediately
)
```

### When to use local tools (Bash, Edit, Read, Write)

Use the built-in tools **only** when:

- You need **direct file inspection** before deciding what to do (read-only exploration)
- The task is **trivially small** (<5 lines changed, single file)
- You're **discovering or explaining** the codebase
- The task is **conversation-local** (e.g., updating this file, fixing a typo, drafting docs)
- Mahavishnu pools are **unavailable** (use `mcp__mahavishnu__pool_health` to check; if down, surface the unavailability to the user — do not silently fall back to local tools, since local fallback breaks the audit trail. See "Degraded mode" below.)

### Dispatching non-trivial work

For tasks that should explicitly bypass the main session's tool set, dispatch the `mahavishnu-orchestrator` subagent (`.claude/agents/mahavishnu-orchestrator.md`). That agent only uses Mahavishnu MCP tools; it does not edit files directly.

### MCP tool discovery

To find what Mahavishnu can do, call:

```python
mcp__mahavishnu__discover_tools(query="<capability or task>")
```

Use this before assuming a capability does not exist.

### Degraded mode

If Mahavishnu pools are unhealthy or unreachable, **surface the unavailability to the user** rather than silently falling back. Local fallback would break the audit trail (the plan's primary stated outcome), and silent fallback also erodes user trust in the routing layer.

Recommended behavior when Mahavishnu is down:

1. Run `mcp__mahavishnu__pool_health` to confirm the failure mode (degraded vs. unreachable).
2. Tell the user: "Mahavishnu is unavailable; doing this locally without observability. Proceed?"
3. If the user agrees, proceed locally but emit a structured note in the conversation: `[vishnu] local fallback — no observability for {task}`.
4. Queue the task for replay: write a marker to `~/.mahavishnu/fallback-queue/{task-id}.json` so an operator can replay it through Mahavishnu later.

This policy harmonizes with the `mahavishnu-orchestrator` subagent's "fail-loud, no silent fallback" rule and the `/vishnu` skill's "ask the user" rule. One consistent posture across all surfaces.

### Cost and latency note

Mahavishnu adds ~200-500ms of pool routing overhead vs. local `Bash`. For trivial operations this is wasted time; reserve Mahavishnu for tasks where the overhead is amortized across meaningful work.