---
name: workflow-status
description: Use ONLY when the user explicitly types `/mahavishnu:workflow-status` or selects this Skill from the picker to poll the status of a Mahavishnu-launched durable workflow. Do not auto-trigger. Routes through `mcp__mahavishnu__get_workflow_status` and explains the difference between durable Prefect flows, Agno agent loops, and LlamaIndex RAG pipelines so the user can pick the right polling cadence.
allowed-tools: mcp__mahavishnu__get_workflow_status, mcp__mahavishnu__list_workflows, mcp__mahavishnu__trigger_workflow, Read, Bash(echo:*)
---

# workflow-status

## When to use

This Skill is the right entry point when the user wants to check the
status of a Mahavishnu-launched durable workflow — typically one
launched via `trigger_workflow(adapter=...)` and now awaiting
completion, failure, or operator attention. Common cases:

- "What's the status of workflow `wf_abc123`?"
- "Did my Prefect flow finish? Show me the result."
- "Why is my Agno loop still running?"
- "How many repos have completed the cross-repo review?"

The Skill uses `mcp__mahavishnu__get_workflow_status(workflow_id)` as the
primary entry point. When the user does not have a specific workflow_id
but wants a fleet overview, the Skill falls back to
`mcp__mahavishnu__list_workflows(status=..., limit=...)` and presents
the recent-N table.

## What the tool does

`mcp__mahavishnu__get_workflow_status(workflow_id, user_id=None)`
returns the persisted state for one durable workflow. The shape covers
the four lifecycle stages:

- **queued** — workflow accepted, awaiting a worker pickup. This is
  the early-window case where the Skill should poll once more before
  reporting stuck.
- **running** — at least one repo started executing. The response
  carries `repos_processed`, `progress`, and `errors_count` so the
  Skill can summarize mid-flight state without additional calls.
- **completed** — all repos finished. The Skill renders the result
  summary and the per-repo breakdown.
- **failed** / **cancelled** — terminal failure modes. The Skill
  surfaces the `errors` array verbatim so the user can decide whether
  to retry, escalate, or cancel siblings.

## Adapter semantics — why the cadence differs

The choice of adapter at dispatch time changes the polling cadence:

- **Prefect flows (`adapter="prefect"`)** — durable Prefect flows with
  retries, scheduling, and observability. Long-running (minutes to
  hours). Poll every 30s for the first 5 minutes, then back off to
  every 2 minutes up to 30 minutes, then every 5 minutes.
- **Agno agent loops (`adapter="agno"`)** — multi-step reasoning
  loops. Typically shorter than Prefect flows (seconds to minutes)
  but the loop may iterate many times. Poll every 5s for the first
  30s, then every 15s.
- **LlamaIndex RAG (`adapter="llamaindex"`)** — document ingestion
  and semantic search pipelines. Variable; depends on corpus size.
  Poll every 10s for the first minute, then every 30s.

When the user does not specify the adapter, the Skill inspects the
returned `task.adapter` field and applies the matching cadence.

## When NOT to use

- For a synchronous single-task dispatch that has already returned,
  use `mcp__mahavishnu__pool_route_execute` directly — there is no
  workflow_id to poll.
- For ad-hoc health checks, use `mcp__mahavishnu__get_health`.
- For workflow cancellation, use `mcp__mahavishnu__cancel_workflow`
  (this Skill does not cancel; it only polls).

## Failure modes and how to handle them

- **`status: "not_found"`** — the workflow_id does not exist in the
  state manager. Surface the response, suggest verifying the
  workflow_id with the dispatch log, and propose listing recent
  workflows so the user can pick the correct id.
- **`status: "forbidden"`** — the caller lacks
  `Permission.VIEW_WORKFLOW_STATUS`. Surface the gate and propose
  the user re-authenticate or escalate to an admin.
- **`status: "failed"`** — surface the `errors` array and the
  `failed_repos` count. Suggest `mcp__mahavishnu__cancel_workflow`
  for sibling cancellation if the workflow is still partially
  running, or `trigger_workflow` with adjusted `params` for retry.
- **Mid-flight timeout (no terminal status after expected cadence)** —
  increase the poll interval, surface the elapsed wall time, and
  propose `cancel_workflow` if the user wants to bail.

## Inputs the Skill expects

- `workflow_id` (string, required) — the id returned by
  `trigger_workflow`. The Skill validates the id shape before calling
  to avoid a wasted round-trip.
- Optional `user_id` for permission-scoped queries — passed verbatim.
- Optional user signal about polling cadence preference ("check
  every 5s", "give it a few minutes") — the Skill honors explicit
  overrides.

## Outputs the Skill returns

A concise status report: lifecycle stage, elapsed wall time, repo
progress, error count, and a recommendation for the next action
(poll again, cancel, retry, or mark complete). Long error arrays are
truncated to the top three entries with a count summary.
