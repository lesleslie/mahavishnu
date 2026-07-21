---
status: active
role: canonical
date: 2026-07-16
last_reviewed: 2026-07-16
topic: tool-preference
---

# Mahavishnu Tool Preference Policy

One-line summary: tool-selection steering lives in two canonical
locations only; docstrings narrate use cases rather than market the
tool to the LLM.

## Context

The architecture-council review of Mahavishnu's tool surface surfaced
a third, undocumented steering channel: `PREFER THIS TOOL FOR ...` /
`DO NOT use this for ...` marketing copy inside tool docstrings.
Docstring copy is loaded by the LLM at the same priority as the tool
signature, so it acts as steering — but it is not maintained alongside
the two intended channels and drifts the moment a tool signature or
profile changes.

Three concrete failure modes have been observed:

- **Drift.** Docstring "prefer this for" copy survives tool renames,
  capability changes, and profile moves. The LLM follows stale advice
  and routes to a tool that no longer fits the use case.
- **Over-routing.** Marketing copy that says "always prefer X" causes
  Claude to push trivial work through Mahavishnu even when the cost
  note in `CLAUDE.md` `## Tool Preferences` says otherwise. The audit
  trail records noise rather than meaningful orchestration.
- **Contradiction.** Two tools can both claim to be the right answer
  for the same task, and both claim to be forbidden for the same
  task. The LLM has to pick; the contradictions cannot be resolved
  from the docstrings alone and require reading CLAUDE.md, which the
  LLM should not need to do to disambiguate steering.

The fix is to declare the two canonical steering channels and forbid
docstrings from carrying steering content. This is an operational
rule, not an architectural decision — there is no change to the
system's shape, only to how future contributors should phrase tool
documentation.

## Decision rule

Tool-selection steering lives in two places only:

- `MAHAVISHNU_TOOL_PROFILE` (configured in
  `mahavishnu/mcp/tools/profiles.py`) — controls which tools are
  exposed to the LLM at all (`full`, `standard`, `minimal`).
- `CLAUDE.md` `## Tool Preferences` — controls which exposed tools
  the LLM should prefer for which kinds of work, and the cost /
  observability / degraded-mode posture.

Docstrings narrate the tool's purpose, inputs, outputs, and example
use cases. They do not contain "prefer this over X" or "do not use
this for Y" copy. If a docstring is the only place that knows a
steering fact, that fact is missing from one of the two canonical
sources and the docstring should be fixed by moving the fact, not
by promoting the docstring to steering.

When the canonical sources conflict with a docstring, the canonical
sources win. Reviewers should treat docstring steering copy as a
regression and ask the contributor to delete it or move the
underlying fact to `MAHAVISHNU_TOOL_PROFILE` / `## Tool Preferences`.

## Status <!-- legacy status: Active — see YAML frontmatter -->

Active. The rule applies to all new tool registrations and to any
existing tool touched after this date. Existing docstring marketing
copy is tracked as a follow-up and will be stripped in a dedicated
pass; contributors should not strip it ad hoc while editing
adjacent code (avoid drift-bundling — see `removed-scripts.md` for
the same posture on `required_scripts:` churn).
