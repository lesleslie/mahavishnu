---
status: active
role: canonical
kind: decision
date: 2026-10-09
last_reviewed: 2026-10-09
superseded_by: null
topic: slash-commands-multi-call-only
---

# Slash Commands Are for Multi-Call Workflows Only

## Context

Slash commands (`/<x>`) and MCP tools (`mcp__x__y`) are two independent
surfaces in Claude Code and every other MCP-capable harness. MCP tools
are the cross-harness portable API — they work in Claude Code, Cursor,
Windsurf, Cline, and any future MCP client without modification. Slash
commands are Claude Code-specific (and partially portable to a few
harnesses that have their own slash-command systems, but with divergent
syntax). The Bodai ecosystem's stated goal is harness-agnostic operation
(see `2026-08-24-bodai-mcp-routing-pattern.md`); the cross-harness
surface is the MCP tool.

A 1:1 slash command — a file whose entire body says "use this MCP tool" —
adds zero capability on top of the MCP tool it wraps. It does add:

- **Staleness risk.** The MCP tool evolves (new params, renamed fields);
  the markdown file drifts unless someone hand-syncs the description.
- **Discoverability tax.** A user asking for the capability can invoke
  the MCP tool directly via a natural-language prompt — Claude picks
  the right `mcp__x__y` from its tool description. The slash command
  hides the same capability behind a separate, hand-named route that
  has to be remembered.
- **Cross-harness inconsistency.** The slash command disappears in
  Cursor; the MCP tool stays. Two parallel surfaces for the same
  capability, one portable, one not.
- **The "is it user-driven or model-driven?" confusion.** A slash
  command is a user invocation; an MCP tool is a model invocation.
  When the two paths exist, neither has clear ownership.

The third surface — **skills** — already covers the auto-triggered
guidance role: tell Claude *when* to use the tools. The system prompt
already lists `mahavishnu-status` and `bodai-status` as skills, not
slash commands. The architecture is consistent at the skill layer; the
slash-command layer is the inconsistency.

## Decision rule

A slash command file in `~/.claude/commands/`, `<repo>/.claude/commands/`,
or `<repo>/commands/` is **justified only when** it orchestrates ≥2
distinct tool calls in a deterministic sequence the user wants to drive.

**Forbidden:** any slash command that wraps a single MCP tool call —
regardless of whether the file's frontmatter advertises one or more
tools. A wrapper around one tool is always a single-tool wrapper, no
matter how many sibling tool names appear in `allowed-tools:`
documentation noise.

**Required pattern for 1:1 wrappers:** remove the file. The MCP tool
itself is the capability. Users invoke via natural-language prompt;
Claude dispatches via the tool's description.

**Required pattern for genuine orchestrations:** keep the file, but
ensure the orchestration is real — at least two distinct tool invocations
or a multi-step bash sequence, not a single `mcp__x__y` call with
surrounding prose.

**Discovery surface:** when a user wants a tool to be discoverable,
write a skill (auto-triggered context, cross-harness where supported),
not a slash command. Skills are the cross-harness layer that complements
MCP tools; slash commands are a Claude Code-specific UX convenience.

## Status of the existing fleet (audit 2026-10-09)

Fifteen 1:1 wrappers exist today. All slated for deletion:

| File | Wrapped MCP tool | Repo |
|---|---|---|
| `~/.claude/commands/checkpoint.md` | `mcp__session-buddy__checkpoint` | (user-level) |
| `~/.claude/commands/start.md` | `mcp__session-buddy__start` | (user-level) |
| `~/.claude/commands/end.md` | `mcp__session-buddy__end` | (user-level) |
| `akosha/commands/akosha-search.md` | `mcp__akosha__search_all_systems` | akosha |
| `akosha/commands/akosha-analyze.md` | `mcp__akosha__analyze_imports` | akosha |
| `dhara/commands/dhara-get.md` | `mcp__dhara__*` (1 tool) | dhara |
| `dhara/commands/dhara-put.md` | `mcp__dhara__*` (1 tool) | dhara |
| `session-buddy/commands/session-buddy-checkpoint.md` | `mcp__session-buddy__checkpoint` | session-buddy |
| `session-buddy/commands/session-buddy-end.md` | `mcp__session-buddy__end` | session-buddy |
| `session-buddy/commands/session-buddy-start.md` | `mcp__session-buddy__start` | session-buddy |
| `crackerjack/commands/crackerjack-init.md` | `mcp__crackerjack__init_crackerjack` | crackerjack |
| `crackerjack/commands/crackerjack-run.md` | `mcp__crackerjack__execute_crackerjack` | crackerjack |
| `crackerjack/commands/crackerjack-status.md` | `mcp__crackerjack__get_comprehensive_status` | crackerjack |
| `mailgun-mcp/commands/mailgun-send.md` | `mcp__mailgun__send_message` | mailgun-mcp |
| `porkbun-domain-mcp/commands/porkbun-domain-pricing.md` | `mcp__porkbun-domain__get_pricing` | porkbun-domain-mcp |

The remaining slash command files in the fleet (≈30 per-MCP-server
orchestrations in css-mcp, excalidraw-mcp, graphics-mcp, langsmith-mcp,
mailgun-mcp, neo4j-mcp, opera-cloud-mcp, penpot-api-mcp, porkbun-dns-mcp,
raindropio-mcp, spline-mcp, synxis-crs-mcp, synxis-pms-mcp, unifi-mcp
plus the multi-call mahavishnu workflows in
`mahavishnu/.claude/commands/{bodai-status,merge-to-main,run}.md`,
`mahavishnu/commands/mahavishnu-status.md`, the verbose toggles, and
the full `workflows/` tree) all bundle ≥2 distinct tool calls and
remain.

## Future additions

When adding a new slash command:

1. **First question:** does this need to be user-invoked? If no, write
   a skill instead.
2. **Second question:** does this orchestrate ≥2 tool calls? If no,
   it's a 1:1 wrapper — write nothing, the MCP tool is the API.
3. **Third question (only after the first two pass):** does this need
   to be Claude Code-specific, or could it be a skill (cross-harness)?
   If cross-harness suffices, write a skill.
4. **Only if all three pass:** write a slash command, with the
   orchestration clearly documented in the body.

## Cross-references

- **Spec (cross-harness surface rationale):** this decision
  operationalizes the harness-agnostic goal stated in
  `2026-08-24-bodai-mcp-routing-pattern.md`.
- **Memory (auto-triggered layer):** the system prompt's existing
  skill listings for `mahavishnu-status` and `bodai-status` are the
  cross-harness complement to MCP tools. Slash commands are deliberately
  not in that layer.
- **Sibling decision (worktree convention):** the trunk-based
  workflow at `2026-10-03-trunk-based-agent-review.md` is the route
  for removing the 1:1 wrappers above; this decision establishes the
  *what*, the workflow establishes the *how*.
