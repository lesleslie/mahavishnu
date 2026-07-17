// Multi-agent workflow: increase test coverage in crackerjack — WAVE 6
// Repo: /Users/les/Projects/crackerjack
// Post-wave-5 state: 71% (17,912 / 70,258 stmts missed), 0 hard failures
// (1 flaky perf threshold documented). The verify phase for wave 5
// explicitly recommended a SMALL wave 6 on the listed low-coverage files
// and stated that beyond this, agent cost > value.
//
// Strategy: 4-5 small focused agents on the remaining low-coverage tier.
// No regression-fixer (the 1 flaky is a known timing issue, not a code
// bug). No source-cleanup agent (the user has the deletion recommendation
// from wave 5 and can act on it).

export const meta = {
  name: 'crackerjack-coverage-fanout-wave6',
  description: 'Wave 6 (likely final): focused coverage on the last low-coverage files; produce a stop-condition verdict',
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

1. Read /tmp/crackerjack_wave5_final.txt.
2. Confirm \`uv run pytest --collect-only -q 2>&1 | tail -3\` runs cleanly.
3. Capture current test failures: \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | grep "^FAILED" | sort -u > /tmp/wave5_failures.txt; wc -l /tmp/wave5_failures.txt\`.
4. Capture the top 10 low-coverage files (anything below 20%): \`uv run coverage report --skip-empty 2>&1 | awk 'NR>2 && NF>=4 {pct = substr($5, 1, length($5)-1); if (pct+0 > 0 && pct+0 < 20) print $1, $2, $5}' | sort -k3 -n | head -10\`.
5. Return a 4-line summary: TOTAL %, failing test count, top 5 low-coverage files, yes/no on suite imports.

Do not modify source files. Do not commit.`,
  { label: 'setup', phase: 'Setup' }
)

// ---------- Phase 2: fan out ----------
phase('Write tests')

const PACKAGES = [
  {
    pkg: 'crackerjack.mcp.tools.error_analyzer',
    stmts: 102,
    files: ['crackerjack/mcp/tools/error_analyzer.py'],
    hint: 'Error-analyzer MCP tool. Pure function analysis — likely classifies errors, suggests remediations. Cover: each error class, multi-error input, unknown error, JSON output shape.',
  },
  {
    pkg: 'crackerjack.cli.semantic_handlers',
    stmts: 118,
    files: ['crackerjack/cli/semantic_handlers.py'],
    hint: 'CLI handlers for semantic-search operations. Mock the semantic search backend. Cover: each subcommand, empty input, error fallback, output formatting.',
  },
  {
    pkg: 'crackerjack.mcp.tools.intelligence_tools',
    stmts: 90,
    files: ['crackerjack/mcp/tools/intelligence_tools.py'],
    hint: 'Intelligence-related MCP tools. Mock the intelligence backend (likely crackerjack.intelligence). Cover: each tool handler, error fallback, empty results.',
  },
  {
    pkg: 'crackerjack.cli.handlers.health',
    stmts: 139,
    files: ['crackerjack/cli/handlers/health.py'],
    hint: 'Health-check CLI handlers. Mock the system health checkers (psutil, network probes). Cover: each subcommand, healthy/unhealthy/partial states, JSON vs text output, --verbose flag.',
  },
]

const TEST_DIRECTIVE = (p) => `You are writing pytest tests for the package \`${p.pkg}\` in the crackerjack project at ${REPO}.

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
2. \`uv run coverage report --skip-empty > /tmp/crackerjack_wave6_final.txt\`
3. Compare /tmp/crackerjack_wave5_final.txt and /tmp/crackerjack_wave6_final.txt:
   - Report new TOTAL line.
   - For each package in the wave 6 fan-out, report before/after/delta.
   - List top 20 files by absolute coverage-point gain.
4. \`uv run pytest -q -m "not slow" --no-header\` and diff with /tmp/wave5_failures.txt.

Return a markdown report with:
- ## Summary (total before/after/delta)
- ## Per-package results (table)
- ## Top gainers (top 20)
- ## Regression analysis (fixed | added | net)
- ## Suite health (pass/fail/xfail)
- ## Final state assessment
  - Has the project reached the 80% target? If not, how far?
  - What is the remaining un-coverable surface (subprocess-bound, integration-only, etc.)?
  - Is wave 7 worth running? If yes, which specific files? If no, why not?
- ## Recommended user actions (deletion of \`crackerjack/cli/handlers.py\`, deletion of \`*.bak\` files, etc.)
- ## Cumulative wave-1-through-6 statistics (total tests added, total pp gain, total source bugs surfaced)

Do not commit. Do not push.`,
  { label: 'verify', phase: 'Verify lift' }
)

return { setup, writeResults, final }
