---
status: active
role: canonical
kind: decision
date: 2026-11-08
last_reviewed: 2026-11-08
superseded_by: null
topic: mcp-tool-naming
title: "MCP tool names carry a component prefix across the Bodai fleet"
---

# MCP Tool Names Carry a Component Prefix

## Context

A live audit of the five Bodai core MCP servers (2026-11-07) found 496 tools
with 464 distinct names: **15 names appear on more than one server**, 47
tools in total. Plan: `docs/plans/2026-11-07-mcp-tool-disambiguation.md`.

The audit also established three things that constrain the answer:

1. **The names are already unique where uniqueness matters.** The
   `mcp__<server>__<tool>` prefix is Claude Code's *config-entry* namespace,
   derived from the MCP entry name — not from the tool name. `KNOWN_TOOLS`
   (`mahavishnu/core/skill_mcp_validator.py`) holds 103 entries, all
   namespaced; agent frontmatter holds 23 references, all namespaced. So a
   sweep rename buys no functional disambiguation.
2. **Some duplicates are correct.** Seven names (`get_liveness`,
   `get_readiness`, `health_check_all`, `health_check_service`,
   `wait_for_dependency`, `wait_for_all_dependencies`, `discover_tools`)
   come from *one* mcp-common library fanned out across servers. Each
   server should answer "how am I?" with an identically-shaped tool.
3. **Some duplicates are genuinely different functions sharing a name** —
   `detect_anomalies` (system metrics vs skill usage), `find_path`
   (knowledge-graph shortest path vs DuckPGQ), `search_code` (regex over
   files vs semantic over session memory).

Separately, the Claude Code TUI's `/<component>` picker prefix-matches on the
tool's **registered name**, so a server whose tools are bare never surfaces
under its component — the gap recorded for akosha.

## Decision rule

**Every Bodai-maintained MCP server prefixes its tool names with the
component name.**

1. **Component-specific tools carry `<component>_<tool>`.** `akosha_search`,
   `session_buddy_search`, `crackerjack_search`. Mahavishnu, session-buddy
   and crackerjack already follow this for their agent/skill/catalog tools;
   akosha does not, and converges as part of the fleet-wide sweep
   (Phase 5 of the plan).

2. **Tools that come from a shared library stay unprefixed.** The
   mcp-common baseline set (`get_liveness`, `get_readiness`,
   `health_check_all`, `health_check_service`, `wait_for_dependency`,
   `wait_for_all_dependencies`, `discover_tools`) is one implementation
   mounted by several servers. Prefixing them per server would register the
   same function under four names and break the guard's allowlist. These
   are the documented exception.

3. **Two tools that share a name MUST mean the same thing, or be renamed.**
   If the same name means different things on two servers, at least one is
   renamed to its component-scoped form. This is the rule that catches
   `detect_anomalies`, `find_path` and `search_code`.

4. **Same name ⇒ same parameter contract.** The parameter names, requiredness
   and defaults must match across every server exposing the name. Where they
   cannot (different auth models, different data models), the divergence is
   documented rather than silently papered over.

5. **The `mcp__<server>__<tool>` config-entry namespace is not a substitute
   and must not be relied on.** It is derived from the MCP *entry* name, so
   any aggregator that prefixes tool names renames every tool at once and
   breaks `KNOWN_TOOLS`, the agent frontmatter and the skill catalog
   simultaneously. Keep one config entry per server.

## Status

Active. Phase 3 of `docs/plans/2026-11-07-mcp-tool-disambiguation.md` renames
the three coincidental collisions; Phase 5 sweeps the remaining unprefixed
tools. The fleet guard (Phase 4) enforces rules 2, 3 and 4 in CI.

## Related

- `docs/plans/2026-11-07-mcp-tool-disambiguation.md` — the plan and the
  audit behind this decision.
- `docs/decisions/tool-description-rubric.md` — the 6-criterion rubric every
  tool description must satisfy.
- `docs/decisions/mcp-backend-wiring-discipline.md` — sibling decision on the
  wire-up side of the same surface.
- `docs/decisions/2026-10-29-learning-pipeline-tools-authz-block.md` — the
  prior decision that `require_mcp_auth` binds on a **caller-asserted**
  `user_id` tool argument rather than the transport's credential. Relevant
  here because it explains why `user_id` on mahavishnu's tools must stay
  (it is the identity the gate reads) even though it is not a real
  authentication, and why the trace tools' `system_id` / `task_class` are
  query filters rather than authorization boundaries.
