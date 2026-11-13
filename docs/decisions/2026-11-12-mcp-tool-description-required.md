---
status: active
role: canonical
kind: decision
date: 2026-11-12
last_reviewed: 2026-11-12
superseded_by: null
topic: mcp-tool-descriptions
title: "Every MCP tool must publish a non-empty description"
---

# Every MCP Tool Must Publish a Non-Empty Description

## Context

On 2026-11-12 the operator pasted qwen-code's `/mcp` panel, which
reported "invalid tools" against five Bodai servers: crackerjack 34,
session-buddy 13, mahavishnu 2, akosha 2, oneiric 2 — 53 in total.

The cause was not a schema problem. qwen-code 0.26.1 counts a tool as
invalid when its name or description is empty:

```js
invalidToolCount: serverTools.filter(x => !x.name || !x.description).length
```

FastMCP derives a tool's `description` from the docstring of the
function it registers. A function without a docstring is published
with `description: null`. All 53 tools matched that rule exactly — the
counts reproduced tool for tool — so the diagnosis was not a guess.

Two distinct causes sat behind the 53:

1. **The shared factories in `mcp-common`.**
   `agents_tools.build_register_agents_tools` registers `list_agents`
   and `get_agent` through nested functions inside a `register(app)`
   closure. `skills_tools.build_register_skills_tools` does the same
   for `list_skills` and `get_skill`. None of those nested functions
   carried a docstring, so all five servers published their agent
   tools with `description: null` — 10 tools from one missing docstring
   pair, plus 2 more from the skill factory.
2. **Locally defined tools.** 30 crackerjack tools and 11 session-buddy
   tools had no docstring on their registered function.

## Decision rule

**A registered MCP tool function must have a docstring.** FastMCP
publishes it as the tool's `description`, and a tool with no
description cannot be chosen by a model reading the tool list.

This applies to:

- the nested functions inside `mcp_common`'s `register(app)` closures,
  which are invisible at the call site and therefore invisible in a
  review of the caller;
- every `@mcp.tool(...)` / `@mcp_app.tool(...)` function in a server's
  own tools package;
- any future tool, including one registered by a factory.

**How it is enforced.** Each server repo carries a static guard that
parses its own tools package and fails on a tool function without a
docstring. The fleet-wide check is `scripts/check_mcp_tool_surface.py`
in mahavishnu, which also covers duplicate bare names, registry drift
and parameter-signature drift across the five servers;
`tests/unit/test_mcp_tool_surface.py` runs the same analysis over a
checked-in snapshot of the fleet's `tools/list` so CI catches the drift
when the servers are down.

**Why a static check rather than a live one.** The live check is the
authoritative one, but a guard that fails when a server is merely
down trains people to ignore it. The static check is CI-safe and
offline; the live check is what proves the servers agree with it.

**A shared-library change needs a release.** `mcp_common` is installed
into each consumer's virtualenv as a copy, not an editable install, so
a docstring added to `mcp-common` does not reach the running servers
until it is released and the consumers reinstall. Editing the installed
copy in place works but is undone by the next `uv sync`.

## Status

Active. The 53 descriptions were added on 2026-11-12: 4 docstrings in
`mcp-common` (`agents_tools.py`, `skills_tools.py`), 30 in crackerjack,
11 in session-buddy. The `mcp-common` half needs a release before the
ten `<server>_list_agents` / `<server>_get_agent` tools pick it up in
the running fleet.
