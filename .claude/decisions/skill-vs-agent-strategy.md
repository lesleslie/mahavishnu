---
status: active
role: canonical
date: 2026-07-16
last_reviewed: 2026-07-16
topic: skill-vs-agent
---

## Context

Both skills and agents extend Claude's capabilities, but they solve different problems.
Choosing the wrong one creates duplication, confused invocation patterns, or missed automation.

## Decision rule

Use this flowchart when deciding whether to write a skill, an agent, or neither:

```
Is this a repeatable, trigger-driven procedure?
  YES → Is it Bodai-specific or stack-specific?
          YES → Write a local skill in ~/.claude/skills/
          NO  → Is there an installed plugin skill that covers it?
                  YES → Use the plugin skill
                  NO  → Write a local skill or install a plugin
  NO  → Does it require deep domain expertise or persona?
          YES → Does mycelium-core or an existing agent cover it?
                  YES → Use that agent
                  NO  → Write a new curated agent (apply agent-curation-strategy.md)
          NO  → Handle inline; no skill or agent needed
```

## When to write a skill

- **Trigger-driven**: fires automatically when a pattern matches (e.g., "after fixing a bug", "before merging")
- **Procedural**: teaches Claude HOW to do something, not WHO to be
- **Repeatable**: the same sequence of steps applies across many contexts
- **Ecosystem-aware**: benefits from knowing Bodai component topology, MCP tool names, or session state

Examples already written: `learn-from-errors`, `deployment-readiness-gate`, `auto-coordinate`,
`run-quality-checks`, `bodai-radar`.

## When to write an agent

- **Domain persona**: requires a specialist identity with deep, stable expertise
- **Explicit invocation**: the user or orchestrator consciously chooses the specialist
- **Complex judgment**: multi-step analysis, trade-off reasoning, architecture decisions
- **Ecosystem-specific**: references Bodai MCP tools by name in the description (triggers
  ecosystem-aware routing)

Examples: `mahavishnu-specialist`, `pytest-hypothesis-specialist`, `postgresql-specialist`.

## Overlap: when both exist

Some capabilities have a skill AND an agent (e.g., `run-quality-checks` skill +
`pytest-hypothesis-specialist` agent). This is intentional:

- **Skill** handles the automated gate (fires after every code change, runs crackerjack)
- **Agent** handles the deep conversation (test design, hypothesis strategies, coverage philosophy)

Do not collapse them into one. The skill automates; the agent advises.

## Anti-patterns to avoid

| Anti-pattern | Problem | Fix |
|---|---|---|
| Agent with a trigger description ("fires after X") | Agents don't auto-trigger; this will be ignored | Convert to a skill |
| Skill with "you are a specialist in X" persona | Skills teach procedures, not personas; this won't invoke correctly | Convert to an agent |
| Skill that duplicates a superpowers skill | Token waste in skill list; confuses triggering | Use the superpowers version |
| Agent that duplicates mycelium-core | Description token waste (counts against 15k limit) | Archive the local copy |

## Token implications

- **Skills**: only the name appears at session start — count doesn't matter
- **Agents**: description loaded every session — subject to 15k aggregate limit
  See `agent-curation-strategy.md` for curation rules

## Status  <!-- legacy status: Active — see YAML frontmatter -->

Established 2026-06-22 alongside `agent-curation-strategy.md`.
