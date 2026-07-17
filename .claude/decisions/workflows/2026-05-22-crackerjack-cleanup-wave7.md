# 2026-05-22-crackerjack-cleanup-wave7 — workflow decision

## Status

Active

## Context

Wave-7 of the crackerjack coverage fan-out (cleanup wave). Executed the 7 user actions recommended by the wave-6 verify report: deleted dead handlers.py, removed 15-18 orphan .bak/.bak2/.backup files, added .gitignore lines, fixed the LSPAwareHookExecutor TYPE_CHECKING import (5 XPASSes), fixed _apply_style_fix_for_rule (12 XFAILs), fixed _create_backup json.dumps default, and added CliRunner tests for coverage_cli.py.

## Decision rule

Re-run this workflow as the actionable follow-up to a wave-6 verify report: it executes the concrete cleanup moves that wave-6 surfaced rather than chasing more coverage. Expect ~20-min wall-clock; uses 5 parallel python-pro agents (1 cleanup + 3 source fixes + 1 CliRunner test agent), followed by 1 verify agent.

## Status history

- 2026-05-22 — Created.
