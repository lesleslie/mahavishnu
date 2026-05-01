---
name: learn-from-errors
description: >
  Proactive error learning skill. Use automatically after fixing a bug, resolving an error,
  or debugging an issue. Queries Session-Buddy for similar past errors, records the fix for
  future reference, enriches the knowledge graph with error-solution links, and checks
  Crackerjack for recurring patterns. NOT user-invoked — Claude activates this autonomously
  after completing a fix.
---

# Learn From Errors

## Overview

## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| session-buddy | 8678 | full | mcp__session-buddy__search_conversations, mcp__session-buddy__store_reflection, mcp__session-buddy__search_entities | 30s |
| crackerjack | 8676 | grep | mcp__crackerjack__smart_error_analysis | 120s |

Every error fixed is a learning opportunity. This skill teaches Claude to check whether an error has been seen before, record the fix for future sessions, and detect recurring patterns that may indicate systemic issues.

**Core principle:** Fix once, learn forever. Every debugging session should make the next one faster.

## Activation

**Reactive** — triggers automatically when Claude has just:
- Fixed a failing test
- Resolved a runtime error, exception, or traceback
- Applied a fix suggested by Crackerjack, Ruff, Mypy, or another quality tool
- Debugged an issue the user reported

**Not a slash command.** Claude uses this autonomously after completing a fix.

## Quick Reference

```
# 1. Check if this error has been seen before
query_similar_errors(error_message, limit=5)

# 2. If found → inform user. If not → record the fix
record_fix_success(error_message, action_taken, code_changes, error_type)

# 3. Enrich the knowledge graph
create_entity(name="error:<hash>", entity_type="error_pattern", observations=[...])
create_entity(name="fix:<hash>", entity_type="solution", observations=[...])
create_relation(from="error:<hash>", to="fix:<hash>", relation_type="fixed_by")

# 4. Check for recurring patterns
crackerjack_patterns(days=30)
```

## Implementation

### Step 1: Query for Similar Past Errors

**Always do this first — read before write.**

```
Call mcp__session-buddy__query_similar_errors with:
  - error_message: the error text, stack trace, or description (first 500 chars is sufficient)
  - limit: 5
```

**If similar errors found:**
- Tell the user: "This error pattern was seen before. Here's what worked last time: [excerpt]"
- Assess whether the past fix still applies to the current situation
- If the past fix is still applicable, apply it and skip to Step 4
- If the past fix is NOT applicable (different context), proceed to Step 2 with both the old and new fix recorded

**If no similar errors found:**
- Proceed to Step 2

### Step 2: Record the Fix

```
Call mcp__session-buddy__record_fix_success with:
  - error_message: the error text (same as Step 1)
  - action_taken: what you did to fix it (1-2 sentences)
  - code_changes: which files/functions were changed (optional, null is fine)
  - error_type: one of "import_error", "type_error", "runtime_error",
                "test_failure", "build_error", "configuration_error", "unknown"
```

**Error type classification guide:**

| Error Type | When to Use | Examples |
|---|---|---|
| `import_error` | Missing/wrong imports | `ModuleNotFoundError`, circular imports |
| `type_error` | Type mismatches, NoneType | `AttributeError: 'NoneType'`, type hints |
| `runtime_error` | Exceptions during execution | `KeyError`, `ValueError`, timeout |
| `test_failure` | Test assertion failures | `AssertionError`, expected vs actual |
| `build_error` | Compilation, packaging | `pip install` failures, missing dependencies |
| `configuration_error` | Wrong config, missing env vars | `ConfigError`, missing settings |
| `unknown` | Default fallback | Anything that doesn't fit above |

### Step 3: Enrich the Knowledge Graph

Create two linked entities — one for the error pattern, one for the solution.

**Create error entity:**
```
Call mcp__session-buddy__create_entity with:
  - name: "error:<short_descriptive_name>"  (e.g., "error:none adapters access")
  - entity_type: "error_pattern"
  - observations: [
      "Error: <error message or summary>",
      "Context: <what was being done when the error occurred>",
      "File: <file path if applicable>"
    ]
```

**Create solution entity:**
```
Call mcp__session-buddy__create_entity with:
  - name: "fix:<short_descriptive_name>"  (e.g., "fix:null guard before adapters")
  - entity_type: "solution"
  - observations: [
      "Fix: <what was done to resolve the error>",
      "Approach: <strategy used — guard clause, retry, refactor, etc.>",
      "Files changed: <list of files modified>"
    ]
```

**Link them:**
```
Call mcp__session-buddy__create_relation with:
  - from_entity: "error:<name>"
  - to_entity: "fix:<name>"
  - relation_type: "fixed_by"
```

### Step 4: Check for Recurring Patterns

```
Call mcp__session-buddy__crackerjack_patterns with:
  - days: 30
  - working_directory: <current project directory>
```

**If recurring patterns found:**
- Tell the user: "Crackerjack detected [N] recurring failure patterns in the last 30 days. This error may be part of a systemic issue."
- Include the top pattern description and frequency
- Suggest investigating the root cause if frequency > 3

**If no patterns found:**
- Silent — no need to mention this to the user

## Entity Naming Convention

Use short, descriptive names with colons as separators:

| Entity Type | Format | Example |
|---|---|---|
| Error pattern | `error:<descriptive name>` | `error:none adapters access` |
| Solution | `fix:<descriptive name>` | `fix:null guard before adapters` |

Keep names under 50 characters. Use lowercase with spaces. The name doesn't need to be globally unique — Session-Buddy handles deduplication via content hashing.

## Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| **Recording before querying** | Duplicate error entries | Always `query_similar_errors` first |
| **Vague error_message** | No matches found on similar errors | Include the actual error text, not a summary |
| **Missing error_type** | Poor search results later | Always classify the error type |
| **Creating entities for trivial fixes** | Knowledge graph bloat | Only create entities for non-trivial errors (not typos, import ordering) |
| **Verbose entity observations** | Hard to search later | Keep each observation to 1-2 sentences |

## When NOT to Activate

- **Trivial fixes:** Typo corrections, import ordering, formatting changes
- **Already recorded:** If `query_similar_errors` found an exact match and the same fix applies
- **User declines:** If the user says "don't worry about it" or "skip the learning step"
- **Flaky tests:** If the test failure was intermittent and the "fix" was just re-running

## Related Skills

- `run-quality-checks` — Quality gates that may trigger this skill
- `capture-insights` — Broader insight capture (use this for architectural insights, not error fixes)
- `code-knowledge-builder` — Proactive code knowledge graph enrichment (complementary)

## MCP Tools Used

| Tool | Purpose |
|---|---|
| `mcp__session-buddy__query_similar_errors` | Check if error seen before |
| `mcp__session-buddy__record_fix_success` | Store error-to-fix mapping |
| `mcp__session-buddy__create_entity` | Create error/solution entities |
| `mcp__session-buddy__create_relation` | Link error to solution |
| `mcp__session-buddy__crackerjack_patterns` | Check for recurring patterns |
