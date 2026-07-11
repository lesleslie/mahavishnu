---
name: vishnu-status
title: Vishnu Status
id: 01KX99DC1JV6SSMB688RV193BK
description: 'Auto-trigger skill that surfaces Mahavishnu pool, verification, and dispatch status when the user asks "are workers running?", "what is the pool status?", or similar phrasings. Use this for visibility into Mahavishnu without leaving the current session.'
owner: mahavishnu-core
status: active
category: observability
last_reviewed: 2026-07-11
---

# Vishnu Status (auto-trigger)

Visibility surface for Mahavishnu worker activity. Fires when the user asks
"what is happening in Mahavishnu?" rather than "do something in Mahavishnu."

## When to use

This skill is **observation**, not **dispatch**. Trigger when the user wants
visibility, e.g.:

- "Are any workers running?"
- "What is the pool status?"
- "Show me Mahavishnu activity."
- "What is Mahavishnu doing right now?"
- "Is anything queued / pending / failed?"
- "Surface pool / worker / dispatch metrics."

The skill is *not* for requests like "dispatch this to Mahavishnu" or "run
the workers on X" — those route to `/vishnu` (or the `mahavishnu-orchestrator`
subagent for forced delegation).

## Behavior

When this skill fires, surface Mahavishnu status by invoking the
`/vishnu-status` slash command. The slash command runs:

```bash
mahavishnu pool list
mahavishnu metrics
# After Phases 1 & 3 land:
mahavishnu metrics verification
mahavishnu metrics dispatch
```

…and prints a compact, formatted status table to the conversation. The
user sees pool health, pending work, and any verification or dispatch
alerts without leaving the session or opening a second terminal.

If the Mahavishnu server is unreachable or no pools are registered, surface
that explicitly — do not invent status. The slash command body has the
canonical fallback wording.

## Distinction from `/vishnu`

| Surface              | Purpose                               | Effect                          |
|----------------------|---------------------------------------|---------------------------------|
| `/vishnu`            | Dispatch / *do work* through Mahavishnu | Routes a task to worker pools |
| `/vishnu-status`     | Observe / *show state* of Mahavishnu  | Surfaces pool, workflow, dispatch metrics |
| `mahavishnu-orchestrator` (subagent) | Forced delegation with tool isolation | Same as `/vishnu` but with strict `tools:` frontmatter |

If the user says "run X on Mahavishnu" → `/vishnu`.
If the user says "what's running on Mahavishnu" → this skill → `/vishnu-status`.

## Where to find more

- Slash command body: `.claude/commands/vishnu-status.md` (Phase 5 Task 5.1).
- Activity surfacing hook: `.claude/hooks/mahavishnu-activity-stream.py`
  (Phase 5 Task 5.4) — surfaces per-event summaries streamed from
  `ws://localhost:8690`.
- Plan: `docs/plans/2026-07-11-ultracode-integration-wiring.md` §Phase 5.
