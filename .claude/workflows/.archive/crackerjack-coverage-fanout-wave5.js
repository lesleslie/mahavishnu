// Multi-agent workflow: increase test coverage in crackerjack — WAVE 5
// Repo: /Users/les/Projects/crackerjack
// Post-wave-4 state: 73% (18,904 / 70,258 stmts missed), 1 stable + 1 flaky failure
// Strategy: clean up the last 4 small zero-coverage files + 2 deep-dive agents
// on the largest remaining partial-coverage packages (mcp/tools and services/ai)
// + 1 regression-fixer for the 1 new failure + 1 source-cleanup investigator
// for the shadowed files (read-only — leave actual deletion to the user).

export const meta = {
  name: 'crackerjack-coverage-fanout-wave5',
  description: 'Wave 5: clean up the last small zero-coverage files, deep-dive mcp/tools and services/ai, fix the test_full_publish_success regression, investigate source cleanup',
  phases: [
    { title: 'Setup' },
    { title: 'Write tests' },
    { title: 'Verify lift' },
  ],
}

const REPO = '/Users/les/Projects/crackerjack'

// ---------- Phase 1: setup ----------
phase('Setup')
const setup = await agent(
  `In ${REPO}:

1. Read /tmp/crackerjack_wave4_final.txt and any wave-4 reports.
2. Capture the current test failure list: \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | grep "^FAILED" | sort -u > /tmp/wave4_failures.txt; wc -l /tmp/wave4_failures.txt\`.
3. Confirm \`uv run pytest --collect-only -q 2>&1 | tail -3\` runs without errors.
4. Capture the top 10 zero-coverage files: \`uv run coverage report --skip-empty 2>&1 | awk 'NR>2 && NF>=4 {pct = substr($5, 1, length($5)-1); if (pct+0 == 0) print $1, $2}' | sort -k2 -nr | head -10\`.
5. Note any *.bak or *.py.bak files in crackerjack/ that the wave-4 investigation flagged for cleanup (likely \`crackerjack/cli/handlers.py\` and \`crackerjack/cli/handlers/__init__.py.bak\`).
6. Return a 5-line summary: TOTAL %, failing test count, top 5 zero-coverage files, any *.bak files found, and yes/no on suite imports.

Do not modify source files. Do not commit.`,
  { label: 'setup', phase: 'Setup' }
)

// ---------- Phase 2: fan out ----------
phase('Write tests')

const PACKAGES = [
  {
    pkg: 'crackerjack.services.file_chunker',
    stmts: 50,
    files: ['crackerjack/services/file_chunker.py'],
    hint: 'File chunker (likely splits large files for embedding/indexing). Use tmp_path + small text fixtures. Cover: empty input, single-line, multi-line, very large input, edge cases on chunk boundaries.',
  },
  {
    pkg: 'crackerjack.mcp.tools.workspace_tools',
    stmts: 42,
    files: ['crackerjack/mcp/tools/workspace_tools.py'],
    hint: 'Workspace-related MCP tools. Mock any filesystem operations. Cover: each tool handler happy path, error fallback, empty input.',
  },
  {
    pkg: 'crackerjack.services.pool_router',
    stmts: 36,
    files: ['crackerjack/services/pool_router.py'],
    hint: 'Pool routing logic (selects which pool to use). Mock the pool manager. Cover: each routing strategy, tie-breaks, no-pools-available error, single-pool fast path.',
  },
  {
    pkg: 'crackerjack.managers.constants',
    stmts: 21,
    files: ['crackerjack/managers/constants.py'],
    hint: 'Constants module. May be a pure-constants file — test that the values are importable and have sensible types. If it has helper functions, test those. Otherwise, document and skip if trivial.',
  },
  {
    pkg: 'crackerjack.mcp.tools.deep_dive',
    stmts: 0,
    files: [
      'crackerjack/mcp/tools/',
    ],
    hint: 'DEEP DIVE on the mcp/tools package (46.12%, 2344 stmts). Largest remaining partial-coverage package. Read coverage report to find the worst-covered files in mcp/tools/. Likely candidates: execution_tools.py, monitoring_tools.py, semantic_tools.py, workflow_executor.py, git_analytics.py (already at 90%). Target each, prioritize ones with most remaining stmts. Aim for 60-70% combined lift across the package (~500+ stmts recovered).',
  },
  {
    pkg: 'crackerjack.services.ai.deep_dive',
    stmts: 0,
    files: [
      'crackerjack/services/ai/',
    ],
    hint: 'DEEP DIVE on the services/ai package (38.5%, 1161 stmts). Read coverage report to find the worst-covered files. Likely candidates: contextual_ai_assistant.py, predictive_analytics.py, pattern_cache.py. Mock any LLM/embedding calls. Aim for 60%+ combined lift (~250+ stmts recovered).',
  },
  {
    pkg: 'crackerjack.regressions',
    stmts: 0,
    files: [],
    hint: 'NOT a coverage target. Wave 4 left 1 stable failure: \`tests/unit/core/test_phase_coordinator_flows.py::TestExecutePublishingWorkflow::test_full_publish_success\`. The test expects \`_execute_publishing_workflow\` to commit+push successfully but the source has a "no changes to stage" bug. Read /tmp/wave4_failures.txt. For each failure, run the failing test, read the traceback, and either (a) xfail it with a clear reason if the source has a known bug, or (b) update the test if its expectations are wrong. Do NOT modify the crackerjack source under test. Do NOT add new tests — only fix existing ones.',
    special: true,
  },
  {
    pkg: 'crackerjack.source_cleanup',
    stmts: 0,
    files: ['crackerjack/cli/handlers.py', 'crackerjack/cli/handlers/'],
    hint: 'INVESTIGATE only — no deletions, no modifications. Wave 4 confirmed that \`crackerjack/cli/handlers.py\` (374-line file) shadows the \`crackerjack/cli/handlers/\` package at import time, and is dead code. Also flag any \`.py.bak\` / \`__init__.py.bak\` files in the repo. Your job: (1) Produce a final list of files safe to delete (no imports, no documentation references, no setup.py references). (2) For each, document the evidence (grep results, line counts, what the file would lose). (3) Do NOT delete anything. The user will decide. Return a cleanup recommendation report.',
    special: true,
  },
]

const TEST_DIRECTIVE = (p) => p.special
  ? `You are auditing/fixing an existing artifact in the crackerjack project at ${REPO}.

Target: ${p.pkg}
Files involved:
${p.files.map(f => '- ' + f).join('\n') || '(none — read /tmp/wave4_failures.txt for the work list)'}

Task: ${p.hint}

## Rules

- Read /Users/les/Projects/mahavishnu/CLAUDE.md "Crackerjack-Compliant Code" before making changes.
- For test fixes: do not introduce new dependencies. Keep the test style consistent with surrounding tests.
- For investigation: report findings clearly with evidence (grep results, file:line references). Do not modify source. Do not delete. Do not commit.

## Workflow

1. Read the relevant files and reports.
2. Make minimal targeted changes (or audit-only observations).
3. Run the affected tests and confirm they pass (or, for investigation, confirm the stated claim).
4. Return a summary with: files touched, tests fixed/verified, observed behavior, recommendations, and any remaining concerns.

Do NOT commit. Do NOT push.`
  : `You are writing pytest tests for the package \`${p.pkg}\` in the crackerjack project at ${REPO}.

Source file(s) to cover:
${p.files.map(f => '- ' + f).join('\n')}

The package has ~${p.stmts} statements.

Context: ${p.hint}

## Rules

- Read /Users/les/Projects/mahavishnu/CLAUDE.md "Crackerjack-Compliant Code" before writing any code. Asserts are fine in tests; other style rules (imports, X | None, from __future__ import annotations, pathlib) apply.
- Use existing pytest markers: unit, integration, slow, property. Mark tests >2s as @pytest.mark.slow.
- CRITICAL: the test file basename MUST be unique across the entire tests/ tree. Pytest cannot disambiguate two files with the same basename.
- Test files go under tests/<mirror path>/test_<module>.py. Match the style of neighboring tests in the same package.
- For async code, asyncio_mode=auto (no @pytest.mark.asyncio).
- Do not introduce new dependencies. Mock external I/O (subprocess, httpx, network, fs) at the boundary.

## Workflow

1. Read the source file(s) AND any existing tests for them. Check for test file basename collisions.
2. Identify the public API and obvious edge cases (None, empty, error, boundary).
3. Write the test file. Aim for 60%+ on the package (or lift by 25+ pp if partially covered). Don't chase 100%.
4. Run \`uv run pytest tests/<your-test-path> -v\` — all new tests must pass. If a pre-existing test fails, that's a REGRESSION — fix your new test, do not skip the old one.
5. Measure the lift: \`uv run coverage run --source=crackerjack.<pkg-dotted> -m pytest tests/<your-test-path> -q && uv run coverage report --include='crackerjack/<pkg-path>*'\`
6. If you found source bugs, document them. Do NOT fix the source.

## Return a summary with

- Path of each new (or modified) test file. CONFIRM the basename is unique.
- Number of tests added.
- Coverage % before vs after for this package.
- Any pre-existing test that you had to update (and why).
- Any source bugs observed.
- Any xfail/skip with reason.

Do NOT commit. Do NOT push. Do NOT run the full suite. Stay in your package.`

const writeResults = await parallel(
  PACKAGES.map((p) => () =>
    agent(TEST_DIRECTIVE(p), { label: `test:${p.pkg}`, phase: 'Write tests', agentType: 'python-pro' })
  )
)

// ---------- Phase 3: verify ----------
phase('Verify lift')
const final = await agent(
  `In ${REPO}:

1. \`uv run coverage run --source=crackerjack -m pytest -q -m "not slow" --no-header\`
2. \`uv run coverage report --skip-empty > /tmp/crackerjack_wave5_final.txt\`
3. Compare /tmp/crackerjack_wave4_final.txt and /tmp/crackerjack_wave5_final.txt:
   - Report new TOTAL line.
   - For each package in the wave 5 fan-out, report before/after/delta.
   - List top 20 files by absolute coverage-point gain.
4. \`uv run pytest -q -m "not slow" --no-header\` and diff with /tmp/wave4_failures.txt to identify NEW fixes and any new regressions.
5. Note the source-cleanup investigation result and the recommended files for deletion.

Return a markdown report with:
- ## Summary (total before/after/delta)
- ## Per-package results (table)
- ## Top gainers (top 20)
- ## Regression analysis (fixed | added | net)
- ## Suite health (pass/fail/xfail)
- ## Source cleanup recommendations (list of files safe to delete, with evidence)
- ## Remaining gaps (top 10 zero-coverage files for wave 6, or "exhausted" if all are tiny/trivial)
- ## Diminishing-returns assessment (is wave 6 worth the agent cost, or is coverage work done?)

Do not commit. Do not push.`,
  { label: 'verify', phase: 'Verify lift' }
)

return { setup, writeResults, final }
