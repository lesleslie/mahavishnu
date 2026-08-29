## name: mahavishnu description: Route a coding task through Mahavishnu worker pools for observability and cross-server delegation. Use this when the user wants the work to appear in ecosystem observability (Dhara, Akosha) or run on a specific pool.

# Mahavishnu Orchestration (auto-trigger)

When user asks Claude to route work through Mahavishnu (e.g., "use mahavishnu
for this", "route through the orchestrator", or simply by invoking
`mcp__mahavishnu__execute_capability` directly), route `<task>` through the
Mahavishnu capability resolver / planner rather than running it locally.

## Behavior

1. **Parse the task** from the invocation argument. If no task follows the
   command, ask the user what to route.

1. **Pick the entry point based on the task:**

   - **Capability-driven dispatch** (single, declarative entry point — preferred) →
     Use `mcp__mahavishnu__execute_capability(spec=CapabilitySpec(requires=["engine:rag-retrieve", "worker:ai-context"], prompt="..."))` for capability-driven dispatch.

1. **Provide a clear dispatch prompt.** Refine the user's raw task into
   a prompt that includes:

   - Goal
   - Target repos or paths
   - Constraints (tests to run, files to skip, etc.)
   - Expected output

1. **Surface the result** to the user, including the workflow_id when
   applicable.

1. **Fall back gracefully.** If `mcp__mahavishnu__pool_health` returns
   unhealthy (legacy pool surface) or the capability planner returns no
   candidates, tell the user Mahavishnu is unavailable and ask whether to
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
