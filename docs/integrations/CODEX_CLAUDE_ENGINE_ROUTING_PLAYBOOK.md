# Codex + Claude Engine Routing Playbook

## Purpose

Use this playbook to make Codex and Claude Code reliably route work through Mahavishnu engines and multi-repo orchestration features, instead of only doing local single-repo actions.

## Key Point

Codex and Claude are **capable** of using Mahavishnu engines, but they typically need explicit routing instructions and tool access. Without that, they may default to local shell/code actions.

## Prerequisites

1. Mahavishnu MCP server reachable.
1. Repository catalog configured (`settings/repos.yaml` or `settings/ecosystem.yaml`).
1. Engine adapters configured/enabled in `settings/mahavishnu.yaml`.
1. Optional: PostgreSQL metrics configured via `MAHAVISHNU_PERSISTENCE__POSTGRES_URL` for historical engine usage.

## Routing Policy (Recommended)

Use these defaults in both Codex and Claude:

1. If task touches more than one repo: route through Mahavishnu.
1. If task requires async/concurrent execution: use pool routing/worker orchestration.
1. If task is single-file/single-repo and low-risk: local execution is fine.
1. Prefer `pool_route_execute` / `mahavishnu pool route` for generic execution.
1. Prefer `trigger_workflow` for structured orchestration workflows.
1. Prefer repository messaging tools for cross-repo handoffs.

## Codex Snippet (AGENTS.md)

Add to your Codex project/user instructions:

```md
## Mahavishnu Routing Defaults

- For multi-repo work, do not execute ad hoc local loops; route via Mahavishnu first.
- For async/concurrent tasks, use pool routing instead of sequential shell execution.
- Preferred order:
  1) `mahavishnu metrics engines` (observe engine usage/health when relevant)
  2) `mahavishnu pool route --prompt "<task>" --selector least_loaded`
  3) If workflow semantics are needed, use `trigger_workflow` via MCP.
- When task intent is unclear, pick adapter by workload:
  - `llamaindex`: retrieval/RAG-heavy
  - `prefect`: workflow/flow orchestration
  - `agno`: goal-driven multi-agent tasks
- For cross-repo updates, send status via repository messaging tools.
```

## Claude Code Snippet (CLAUDE.md)

Add a section like this:

```md
## Mahavishnu Orchestration Mode

When a request spans multiple repositories or needs concurrent execution:
1. Resolve target repos from configured catalog.
2. Route via Mahavishnu pool/workflow tools, not manual per-repo shell loops.
3. Use `least_loaded` as default routing selector unless user specifies otherwise.
4. Emit workflow/repository status updates for downstream repos.
5. Report engine choice and execution outcome in final response.
```

## Suggested CLI Workflows

### 1) Generic Multi-Repo Task

```bash
mahavishnu pool route --prompt "Run lint and tests for backend-tagged repos" --selector least_loaded
```

### 2) Explicit Engine-Oriented Sweep

```bash
mahavishnu sweep --tag backend --adapter prefect
```

### 3) Engine Usage Visibility

```bash
mahavishnu metrics engines --source auto --output table
```

## Operational Notes

1. If `metrics engines` shows zeros, that usually means no persisted history yet, or no live `/metrics` exposure from the running server.
1. For durable usage/success analytics, configure PostgreSQL metrics persistence and query with `--source postgres`.
1. Keep environment-specific secrets (DSNs, auth tokens) in environment variables, not checked-in docs/config.
