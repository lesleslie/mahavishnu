______________________________________________________________________

## name: mahavishnu title: Mahavishnu id: 01KXB2MJHQZ5K7VD9P0XCRWA1G description: Route a coding task through Mahavishnu worker pools for observability and cross-server delegation. Use this when the user wants the work to appear in ecosystem observability (Dhara, Akosha) or run on a specific pool. owner: mahavishnu-core status: active category: workflow last_reviewed: 2026-07-20

# Mahavishnu Orchestration (auto-trigger)

When user asks Claude to route work through Mahavishnu (e.g., "use mahavishnu
for this", "route through the orchestrator", or simply by invoking
`mcp__mahavishnu__pool_route_execute` directly), route `<task>` through the
Mahavishnu worker pool manager rather than running it locally.

## Behavior

1. **Parse the task** from the invocation argument. If no task follows the
   command, ask the user what to route.

1. **Pick the entry point based on the task:**

   - **Quick work** (single command, single file, \<5 min) →
     `mcp__mahavishnu__pool_route_execute(prompt="<task>")`
   - **Long-running or multi-step** →
     `mcp__mahavishnu__dispatch_to_pool(prompt="<task>", async_callback=True)`
   - **Durable orchestration across repos** →
     `mcp__mahavishnu__trigger_workflow(adapter="prefect", task_type="...")`

1. **Provide a clear dispatch prompt.** Refine the user's raw task into
   a prompt that includes:

   - Goal
   - Target repos or paths
   - Constraints (tests to run, files to skip, etc.)
   - Expected output

1. **Surface the result** to the user, including the workflow_id when
   applicable.

1. **Fall back gracefully.** If `mcp__mahavishnu__pool_health` returns
   unhealthy, tell the user Mahavishnu is unavailable and ask whether to
   proceed locally (with no observability) or wait.

## What this skill is NOT

- This is **not** a permission to bypass the orchestrator's review. If
  the task is high-stakes (cross-repo refactor, version bump, publish),
  the verification gate (Phase 1 of the integration plan) still runs.
- This is **not** a replacement for CLAUDE.md's Tool Preferences. It is
  a shortcut for users who want to *force* Mahavishnu on a specific task.

## Examples

```
mahavishnu: run the test suite
mahavishnu: refactor the auth module to use Pydantic v2
mahavishnu: deploy this branch to staging
mahavishnu: audit this repo for security issues
```

## When to use this skill vs. just letting Claude pick

Use the Mahavishnu dispatch tools when:

- The user explicitly wants the work routed through Mahavishnu
- The user wants the work to appear in ecosystem observability
- The work should be auditable / replayable

Let Claude pick tools normally when:

- The task is trivial (\<5 lines, conversation-local)
- The task is exploratory (read-only discovery)
- The user did not indicate a preference for observability
