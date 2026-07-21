---
status: active
role: canonical
date: 2026-07-16
last_reviewed: 2026-07-16
topic: agent-curation
---

The Claude Code agent catalog has a **15,000-token hard limit** on aggregated agent descriptions
loaded into context at session start. Exceeding it produces a warning and degrades context budget.

The Bodai ecosystem uses two complementary agent sources:

- **`mycelium-core` plugin** (120 agents): broad generalist coverage — languages, frameworks, cloud, data
- **`~/.claude/agents/` + `mahavishnu/.claude/agents/`**: curated Bodai-specific and stack-specific agents

## Decision rule

Before adding an agent to the curated catalog, apply this test in order:

1. **Does `mycelium-core` already cover it?**
   Check `/tmp/mycelium_agents.txt` or run:
   `find ~/.claude/plugins/cache/mycelium -name "*.md" -path "*/agents/*" | xargs -I{} basename {} .md | sed 's/^[0-9]*-[a-z]*-//'`
   If yes → **do not add**; the mycelium version will be available automatically.

1. **Is it Bodai-stack relevant?**
   Bodai primary stack: Python 3.13, FastMCP, Oneiric, Starlette, FastBlocks, HTMX, HTMY,
   Jinja2, PostgreSQL, Redis, Rust/PyO3, pytest/Hypothesis, Rich/Textual.
   Bodai components: Mahavishnu, Akosha, Dhara, Session-Buddy, Crackerjack, Oneiric.
   If the agent serves none of these directly → **archive or skip**.

1. **Does it serve non-Bodai repos that Bodai maintains?**
   Accepted exceptions: `pwa-specialist`, `pycharm-plugin-creator`, `vitest-specialist`,
   `web-components-specialist`, `css-architect`, `accessibility-auditor`.
   If a new agent fits this category, document it here.

## Archive pattern

**Do NOT archive to a subdirectory inside `~/.claude/agents/` or `mahavishnu/.claude/agents/`.**
Claude Code scans agent directories recursively — any `.md` file in a subdirectory (including
`.archive/`) is loaded as an agent, defeating the purpose of archiving.

Agents that fail the test above are moved to `~/.claude/.archive/agents-removed/` (outside the
scan path). The mahavishnu project repo simply deletes them from `.claude/agents/` (the files
are preserved in the global archive if recovery is needed).

Archived agents can be restored with:

```
mv ~/.claude/.archive/agents-removed/<batch>/<name>.md ~/.claude/agents/
cp ~/.claude/agents/<name>.md mahavishnu/.claude/agents/
```

## Current counts (2026-06-22)

| Location | Active | Archived |
|----------|--------|----------|
| `~/.claude/agents/` | 52 | 49 (in `~/.claude/.archive/agents-removed/`) |
| `mahavishnu/.claude/agents/` | 52 | 0 (deleted from repo) |
| `mycelium-core` plugin | 120 | — |
| `understand-anything` plugin | 9 | — |

Total unique agents in catalog: ~207. Token budget: comfortably under 15k.

## Status <!-- legacy status: Active — see YAML frontmatter -->

Established 2026-06-21 after hitting the 15k limit following `understand-anything` install.
Archive pattern corrected 2026-06-22: subdirectory archives inside agents/ don't work.
