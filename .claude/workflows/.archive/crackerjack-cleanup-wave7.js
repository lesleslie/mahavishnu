// Multi-agent workflow: execute the 7 user actions from the wave-6 verify phase
// Repo: /Users/les/Projects/crackerjack
//
// These actions were explicitly recommended by the wave-6 verify report as
// the next concrete moves. They are:
//   1. Delete crackerjack/cli/handlers.py (dead file, 0% cover, 177 stmts)
//   2. Delete 15-18 *.bak / *.bak2 / *.backup orphan files
//   3. Add .gitignore lines for *.bak, *.bak2, *.backup
//   4. Move LSPAwareHookExecutor import out of TYPE_CHECKING (fixes 5 XPASSes)
//   5. Fix _apply_style_fix_for_rule in planning_agent.py (unlocks 12 XFAILs)
//   6. Fix _create_backup in autofix_coordinator.py to pass default=str to json.dumps
//   7. Add click.testing.CliRunner tests for crackerjack/cli/coverage_cli.py
//
// Strategy: 5 parallel agents (cleanup + 3 source fixes + CliRunner tests),
// then 1 verify agent to confirm the suite is healthier and coverage is up.

export const meta = {
  name: 'crackerjack-cleanup-wave7',
  description: 'Wave 7: execute the 7 cleanup actions recommended by wave-6 verify (deletions, gitignore, 3 source fixes, CliRunner tests)',
  phases: [
    { title: 'Setup' },
    { title: 'Execute actions' },
    { title: 'Verify health' },
  ],
}

const REPO = '/Users/les/Projects/crackerjack'

// ---------- Phase 1: setup ----------
phase('Setup')
const setup = await agent(
  `In ${REPO}:

1. Run \`git status --short\` and report the working-tree state.
2. Run \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | tail -5\` to get the current pass/fail summary.
3. Capture the current XPASSes and XFAILs:
   \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | grep -E "^(XPASS|XFAIL)" | sort -u > /tmp/wave6_xpass_xfail.txt; wc -l /tmp/wave6_xpass_xfail.txt\`
4. Verify which *.bak / *.backup / *.bak2 files actually exist in the tree (some may have been deleted already): \`find crackerjack tests -name "*.bak" -o -name "*.backup" -o -name "*.bak2" 2>/dev/null | sort\`
5. Return a 5-line summary: git status (clean/dirty), current test pass count, current XFAIL+XPASS count, list of *.bak files found, and any concerns.

Do not modify anything. Do not commit.`,
  { label: 'setup', phase: 'Setup' }
)

// ---------- Phase 2: 5 parallel action agents ----------
phase('Execute actions')

const ACTIONS = [
  {
    name: 'cleanup',
    task: `In ${REPO}, perform the file-system cleanup actions from the wave-6 verify report.

## Actions

### 1. Delete the dead file

Delete \`crackerjack/cli/handlers.py\` (374-line file, 0% cover, fully shadowed by the \`crackerjack/cli/handlers/\` package — confirmed by wave-4 source investigation). The package is at 92% cover and is the canonical implementation. Use \`git rm\` if tracked, plain \`rm\` if untracked.

### 2. Delete the *.bak / *.bak2 / *.backup orphans

Delete every file matching \`*.bak\`, \`*.bak2\`, or \`*.backup\` under \`crackerjack/\` and \`tests/\`. Use \`find crackerjack tests -name "*.bak" -o -name "*.bak2" -o -name "*.backup" -delete\` after first printing the list to confirm.

Expected files (from wave-5 source-cleanup investigation):
- crackerjack/services/ai_fix_progress.py.bak
- crackerjack/services/metrics_old.py.bak
- crackerjack/config/profile_loader.py.bak
- crackerjack/core/autofix_coordinator.py.bak
- crackerjack/agents/coordinator.py.bak, coordinator.py.bak2
- crackerjack/agents/planning_agent.py.bak
- crackerjack/agents/proactive_agent.py.bak
- crackerjack/agents/formatting_agent.py.backup
- crackerjack/agents/type_error_specialist.py.backup
- crackerjack/mahavishnu/mcp/tools/git_analytics.py.bak
- crackerjack/cli/handlers/__init__.py.bak
- crackerjack/cli/handlers/advanced/__init__.py.bak
- crackerjack/cli/handlers/lifecycle/__init__.py.bak
- crackerjack/cli/handlers/provider_selection/__init__.py.bak
- crackerjack/cli/handlers/config_handlers/__init__.py.bak
- crackerjack/cli/handlers/semantic/__init__.py.bak
- crackerjack/cli/handlers/cache_commands/__init__.py.bak

### 3. Update .gitignore

Append three lines to \`.gitignore\` (PUT COMMENTS ON THEIR OWN LINE — \`#\` mid-line is a literal character, not a comment):
\`\`\`
# Backup files from refactor checkpoints
*.bak
*.bak2
*.backup
\`\`\`

Verify the new .gitignore has no inline \`#\` mid-line (i.e., \`*.bak   # comment\` would be a bug). If the project already has a similar block, just append the missing patterns.

## Verification

1. \`git status --short | head -30\` — confirm the deletions are visible.
2. \`find crackerjack tests -name "*.bak" -o -name "*.bak2" -o -name "*.backup" 2>/dev/null | wc -l\` — should be 0.
3. \`head -20 .gitignore\` — confirm the new lines are present and well-formatted.
4. \`grep -n '#' .gitignore | head -20\` — check no inline \`#\` was introduced (whole-line comments only).
5. \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | tail -3\` — confirm the test suite still imports and the count is roughly the same.

## Return

- Files deleted (count and list).
- .gitignore diff.
- Whether the suite still passes imports.
- Any concerns.

Do NOT commit. Do NOT push. Do NOT modify anything other than the listed files.`,
  },
  {
    name: 'fix_lspaware_xpass',
    task: `In ${REPO}, fix the 5 XPASS root cause identified by the wave-6 verify report.

## The bug

\`crackerjack/managers/hook_manager.py\` imports \`LSPAwareHookExecutor\` inside a \`TYPE_CHECKING\` block (a type-checker-only import) but uses it at runtime. This causes 5 tests in \`tests/unit/managers/test_hook_manager*.py\` to be marked \`@pytest.mark.xfail\` against a known bug. They were xfail because the production code raises \`NameError: name 'LSPAwareHookExecutor' is not defined\` at runtime when the type-checker-only branch is taken; in some environments, the import is resolved differently and the tests pass unexpectedly (hence XPASS).

## Action

1. Read \`crackerjack/managers/hook_manager.py\` and find the \`TYPE_CHECKING\` block.
2. Move the \`LSPAwareHookExecutor\` import out of the \`TYPE_CHECKING\` block to a top-level import (or to a runtime-only import under a regular \`if not TYPE_CHECKING:\` guard, depending on the actual structure).
3. If there is a circular-import reason the import was inside \`TYPE_CHECKING\`, document the change in a comment.

## Verification

1. \`uv run pytest tests/unit/managers/test_hook_manager.py tests/unit/managers/test_hook_manager_extended.py -q 2>&1 | tail -10\` — should now show 0 XPASSes, all tests passing or xfail'd for unrelated reasons.
2. \`uv run coverage run --source=crackerjack.managers.hook_manager -m pytest tests/unit/managers/ -q && uv run coverage report --include='crackerjack/managers/hook_manager*'\` — measure the coverage delta.
3. \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | grep -E "^(XPASS|XFAIL)" | sort -u | head\` — should show fewer XPASSes than before.

## Return

- The diff of the change.
- Number of XPASSes before and after.
- Coverage % before and after for \`hook_manager.py\`.
- Any new failures (regression check).

Do NOT commit. Do NOT push. Do NOT modify anything other than \`hook_manager.py\`.`,
  },
  {
    name: 'fix_planning_xfail',
    task: `In ${REPO}, fix the 12 XFAIL root cause identified by the wave-6 verify report.

## The bug

\`crackerjack/agents/planning_agent.py\` has a method \`_apply_style_fix_for_rule\` that eagerly invokes the fix helper and then tries to call the stored \`ChangeSpec\` as a function. This causes 12 tests in \`tests/unit/agents/test_planning_agent_fixes.py\` to be marked \`@pytest.mark.xfail\`. The fix is in the production source.

## Action

1. Read \`crackerjack/agents/planning_agent.py\` and find \`_apply_style_fix_for_rule\`.
2. Identify the root cause: where the code calls a \`ChangeSpec\` as a function when it should be applying the change via its \`.apply(content)\` method (or equivalent), or where the eager invocation order is wrong.
3. Fix the bug. The fix should be a small, targeted change (1-5 lines).
4. The \`planning_agent.py\` file has 1770 stmts, 763 miss. A correct fix should reduce miss significantly.

## Verification

1. \`uv run pytest tests/unit/agents/test_planning_agent_fixes.py -v 2>&1 | tail -30\` — observe the 12 XFAIL tests; after the fix, the SUCCESS-rate should improve and the XFAIL count should drop.
2. \`uv run coverage run --source=crackerjack.agents.planning_agent -m pytest tests/unit/agents/test_planning_agent_fixes.py -q && uv run coverage report --include='crackerjack/agents/planning_agent*'\` — measure the coverage delta.
3. \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | grep -E "^XFAIL" | wc -l\` — should be down from 15 (or wherever the count is) to 3 or so.
4. \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | tail -3\` — overall suite health.

## Return

- The diff of the change (1-5 lines).
- XFAIL count before and after.
- Coverage % before and after for \`planning_agent.py\`.
- Number of tests promoted from xfail to pass.
- Any new failures (regression check).

Do NOT commit. Do NOT push. Do NOT modify anything other than \`planning_agent.py\`. If the root cause is more complex than 5 lines or requires a design decision, stop and report instead of writing speculative code.`,
  },
  {
    name: 'fix_backup_xfail',
    task: `In ${REPO}, fix the 1 XFAIL root cause identified by the wave-6 verify report.

## The bug

\`crackerjack/core/autofix_coordinator.py\` has a method \`_create_backup\` that calls \`json.dumps\` without \`default=str\`. When the data structure contains a non-JSON-serializable value (e.g., a Path, a datetime, a custom object), \`json.dumps\` raises \`TypeError\`. Adding \`default=str\` makes the serializer fall back to string representation for unknown types.

## Action

1. Read \`crackerjack/core/autofix_coordinator.py\` and find \`_create_backup\` (or any method that calls \`json.dumps\`).
2. Add \`default=str\` to the \`json.dumps\` call.
3. If there are other \`json.dumps\` calls in the same file that could have the same issue, fix them too — but only if the fix is obviously the same pattern.

## Verification

1. \`uv run pytest tests/unit/core/test_autofix_coordinator.py -v 2>&1 | tail -20\` — find the XFAIL test that mentions \`_create_backup\` and confirm it now passes.
2. \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | grep -E "^(XPASS|XFAIL)" | sort -u | head\` — should show the XFAIL count down by 1.
3. \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | tail -3\` — overall suite health.

## Return

- The diff (should be 1-2 lines).
- XFAIL count before and after.
- The test that was promoted.
- Any new failures (regression check).

Do NOT commit. Do NOT push. Do NOT modify anything other than \`autofix_coordinator.py\`.`,
  },
  {
    name: 'test_coverage_cli',
    task: `In ${REPO}, add CliRunner-based tests for the new \`crackerjack/cli/coverage_cli.py\` module.

## Context

\`coverage_cli.py\` is a freshly-added file from the wave-6 fan-out, currently at 0% cover. It's a Click-based CLI for the coverage subsystem. To prevent it from going stale, write CliRunner-based tests.

## Action

1. Read \`crackerjack/cli/coverage_cli.py\` and identify the Click commands and their options.
2. Find the existing CliRunner test pattern in the project: \`grep -lr "click.testing.CliRunner" tests/ | head -5\`. Match the style of any pre-existing CliRunner tests.
3. Create \`tests/cli/test_coverage_cli.py\` (basename MUST be unique — verify with \`find tests -name 'test_coverage_cli*'\` before creating).
4. Write CliRunner-based tests covering: each command's happy path, --help, missing required args, --json output mode if present, error fallback.
5. Use \`@pytest.mark.unit\` marker.
6. Mock any I/O at the boundary (subprocess, file system).

## Verification

1. \`uv run pytest tests/cli/test_coverage_cli.py -v 2>&1 | tail -20\` — all new tests pass.
2. \`uv run coverage run --source=crackerjack.cli.coverage_cli -m pytest tests/cli/test_coverage_cli.py -q && uv run coverage report --include='crackerjack/cli/coverage_cli*'\` — measure the lift (was 0%, should be 60%+).
3. \`find tests -name 'test_coverage_cli*' 2>&1 | head\` — confirm no basename collision.

## Return

- Path of the new test file.
- Number of tests added.
- Coverage % before vs after for \`coverage_cli.py\`.
- Any source bugs observed.
- Confirmation that the basename is unique.

Do NOT commit. Do NOT push. Do NOT run the full suite. Stay in \`tests/cli/\`.`,
  },
]

const actionResults = await parallel(
  ACTIONS.map((a) => () =>
    agent(a.task, { label: a.name, phase: 'Execute actions', agentType: 'python-pro' })
  )
)

// ---------- Phase 3: verify ----------
phase('Verify health')
const verify = await agent(
  `In ${REPO}, after the wave-7 action agents have run:

1. \`git status --short | head -40\` — confirm the deletions are staged/unstaged.
2. \`find crackerjack tests -name "*.bak" -o -name "*.bak2" -o -name "*.backup" 2>/dev/null | wc -l\` — should be 0.
3. \`ls crackerjack/cli/handlers.py 2>&1\` — should report "No such file or directory".
4. \`grep -E "^\\*.bak" .gitignore\` — should list the patterns.
5. \`uv run coverage run --source=crackerjack -m pytest -q -m "not slow" --no-header\`
6. \`uv run coverage report --skip-empty > /tmp/crackerjack_wave7_final.txt\`
7. Compare /tmp/crackerjack_wave6_final.txt and /tmp/crackerjack_wave7_final.txt:
   - TOTAL % before and after.
   - Per-package deltas for the touched packages.
   - Top 10 files by absolute coverage-point gain.
8. \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | tail -3\` — overall suite health.
9. \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | grep -cE "^XFAIL"\` — XFAIL count.
10. \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | grep -cE "^XPASS"\` — XPASS count.
11. \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | grep -cE "^FAILED"\` — hard failure count.

Return a markdown report with:
- ## Summary (total before/after/delta)
- ## Cleanup actions performed
  - Files deleted (count)
  - .gitignore changes
- ## Source fixes applied
  - Each fix: file:line, before/after for the related XFAIL or XPASS
- ## CliRunner tests added (count and coverage lift)
- ## Suite health (pass/fail/xfail/xpass)
- ## Overall test stability (any new failures introduced)
- ## Recommended commit message (the 7 user actions in one commit)
- ## Recommended next actions (if any)

Do not commit. Do not push.`,
  { label: 'verify', phase: 'Verify health' }
)

return { setup, actionResults, verify }
