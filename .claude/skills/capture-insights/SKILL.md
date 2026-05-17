______________________________________________________________________

## name: capture-insights description: Use when capturing durable lessons from conversations.

# Capture Insights

## Overview

Use this skill to turn durable lessons into searchable insight entries.

## When to Use

- Explaining a technical concept or pattern
- Capturing a lesson learned or debugging discovery
- Recording a design decision or best practice
- Building reusable knowledge for future sessions

## Required Format

```markdown
★ Insight ─────────────────────────────────────
[Educational insight here]
─────────────────────────────────────────────────
```

## Rules

- Keep the header and footer exact.
- Write why something works, not just what happened.
- Avoid temporary status updates or throwaway notes.
- Let Session-Buddy capture and index the insight automatically.

## Quick Reference

- Store: `mcp__session-buddy__extract_and_store_memory_tool`
- Search: `mcp__session-buddy__search_by_concept`
- Stats: `mcp__session-buddy__reflection_stats`

## Notes

- Use this for durable learning, not for routine progress messages.
- Prefer concise, high-signal insights that will still matter later.
