# Removed Scripts — `required_scripts:` policy

One-line summary: documents why 5 scripts referenced from tool command frontmatter stay removed, and which 1 is being implemented.

## Background

Six scripts were previously referenced in `required_scripts:` blocks across 8 files under `.claude/commands/tools/`. None had ever been committed. Five are staying removed; one is being implemented.

## Scripts that stay removed

| Script | Reason |
|--------|--------|
| `scripts/dependency_report.py` | Defer. A thin wrapper around `pip-audit` / `osv-scanner` would suffice if needed. |
| `scripts/release_checklist.py` | Defer. The LLM produces release checklists adequately at runtime. |
| `scripts/privacy_matrix.py` | Permanently removed. Would imply regulatory authority a script cannot have. |
| `scripts/support_health.py` | Permanently removed. No ticketing data source available to query. |
| `scripts/telemetry_audit.py` | Defer. Needs a stable SLO contract first; scope is larger than it looks. |

## Script being added

| Script | Scope | Consumers |
|--------|-------|-----------|
| `scripts/test_matrix.py` | Test coverage matrix generator | `.claude/commands/tools/development/testing/quality-validation.md`, `.claude/commands/tools/development/testing/test-harness.md` |

The `required_scripts:` reference has been added back to those two tool commands now that the script is committed.

## Decision rule

Do not add speculative `required_scripts:` entries to tool command frontmatter. Either:

1. Implement the script (committed to `scripts/`, runnable today), or
2. Leave the reference out.

A `required_scripts:` entry pointing at a non-existent file is a bug, not a TODO.
