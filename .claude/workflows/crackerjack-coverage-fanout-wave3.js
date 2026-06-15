// Multi-agent workflow: increase test coverage in crackerjack — WAVE 3
// Repo: /Users/les/Projects/crackerjack
// Post-wave-2 state: ~66% (21,824 / 70,258 stmts missed)
// Strategy: 10 parallel agents on the remaining zero-coverage tier + 1 regression-fixer
// for the 102 leftover failures from waves 1+2. Also includes a "git_analytics
// audit" agent to confirm the renamed test file actually runs at scale.

export const meta = {
  name: 'crackerjack-coverage-fanout-wave3',
  description: 'Wave 3: cover the next tier of zero-coverage crackerjack files and clean up wave 1+2 regressions',
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

1. Read /tmp/crackerjack_wave2_final.txt (post-wave-2 coverage report) and /tmp/wave2_failures.txt (current failures) so you understand state.
2. Confirm the test suite still imports cleanly: \`uv run pytest --collect-only -q 2>&1 | tail -5\`
3. Confirm there are no collection errors (the wave-2 git_analytics file was renamed to test_mcp_git_analytics.py to fix a module-name collision).
4. Re-run coverage on JUST the git_analytics source to confirm the rename worked:
   \`uv run coverage run --source=crackerjack.mahavishnu.mcp.tools.git_analytics -m pytest tests/unit/mahavishnu/mcp/tools/test_mcp_git_analytics.py -q && uv run coverage report --include='crackerjack/mahavishnu/mcp/tools/git_analytics*'\`
   Report the actual % (the agent claimed 0% -> 90% but pytest couldn't collect the file). If it's still near 0%, flag it as a CRITICAL issue.
5. Return a 5-line summary: current TOTAL %, number of test failures, any new collection errors, git_analytics confirmed covered %, and the top 5 zero-coverage files by stmt count.

Do not modify source files. Do not commit.`,
  { label: 'setup', phase: 'Setup' }
)

// ---------- Phase 2: fan out ----------
phase('Write tests')

// Tier-3 zero-coverage targets. All under 200 stmts each — these are
// "small but real" modules. 10 in parallel. None share a package so no
// write conflicts. Plus 1 regression-fixer and 1 git_analytics-audit.
const PACKAGES = [
  {
    pkg: 'crackerjack.cli.handlers',
    stmts: 177,
    files: ['crackerjack/cli/handlers.py'],
    hint: 'CLI command handlers. Likely Typer/Click-based. Mock the runtime. Cover: each subcommand happy path, --help, error fallback, missing-required-arg. Parametrize heavily.',
  },
  {
    pkg: 'crackerjack.mcp.task_manager',
    stmts: 163,
    files: ['crackerjack/mcp/task_manager.py'],
    hint: 'MCP task manager — task CRUD over a backend. Mock the network/persistence layer. Cover: create, list, get, update, delete, conflict on duplicate, malformed input.',
  },
  {
    pkg: 'crackerjack.adapters.treesitter.treesitter',
    stmts: 157,
    files: ['crackerjack/adapters/treesitter/treesitter.py'],
    hint: 'tree-sitter binding wrapper. May be import-only because the binary is not installed — check first. If tree-sitter is available, test parse / language detection / error on malformed input. If unavailable, document and skip with a clear reason.',
  },
  {
    pkg: 'crackerjack.agents.qwen_code_bridge',
    stmts: 153,
    files: ['crackerjack/agents/qwen_code_bridge.py'],
    hint: 'Thin wrapper around qwen API. Mock the HTTP layer (httpx or requests). Cover: happy response, error responses (4xx/5xx), timeout, retry, malformed JSON. Do NOT actually call the qwen API.',
  },
  {
    pkg: 'crackerjack.cli.profile_handlers',
    stmts: 151,
    files: ['crackerjack/cli/profile_handlers.py'],
    hint: 'CLI profile-management handlers. Mock the profile storage layer (YAML/JSON file). Cover: list, add, remove, switch, invalid profile name, missing profile file.',
  },
  {
    pkg: 'crackerjack.services.intelligent_commit',
    stmts: 140,
    files: ['crackerjack/services/intelligent_commit.py'],
    hint: 'Intelligent commit-message generator. Likely LLM-backed. Mock the LLM client. Cover: short diff -> short message, large diff -> chunked, LLM timeout, LLM refusal (parses to fallback), no diff (errors cleanly).',
  },
  {
    pkg: 'crackerjack.skills.metrics',
    stmts: 142,
    files: ['crackerjack/skills/metrics.py'],
    hint: 'Skill metrics aggregator. Pure functions over skill execution records. Cover: aggregation windows, per-skill counters, empty inputs, malformed metric records.',
  },
  {
    pkg: 'crackerjack.services.coverage_badge_service',
    stmts: 99,
    files: ['crackerjack/services/coverage_badge_service.py'],
    hint: 'Coverage badge generator (the SVG you put in README). Pure functions. Cover: 0% (red), 50% (yellow), 100% (green), custom thresholds, malformed input. Use snapshot tests for SVG output.',
  },
  {
    pkg: 'crackerjack.data.repository',
    stmts: 110,
    files: ['crackerjack/data/repository.py'],
    hint: 'Data access layer. Use a temp SQLite fixture (pytest-asyncio + aiosqlite). Cover: CRUD on the model(s), transaction rollback, schema migration helper, connection error.',
  },
  {
    pkg: 'crackerjack.agents.refactoring_agent',
    stmts: 700,
    files: ['crackerjack/agents/refactoring_agent.py'],
    hint: 'Largest partial-coverage refactoring agent. 79% covered. Lift to 88%+. Avoid duplicating existing tests. Cover the remaining 21% — likely message-classifier branches and a few subcommand routers.',
  },
  {
    pkg: 'crackerjack.regressions',
    stmts: 0,  // not a stmt-count target
    files: [],
    hint: 'NOT a coverage target — this is the REGRESSION FIXER. Read /tmp/wave2_failures.txt (102 unique failures from waves 1+2) and /tmp/regressions.txt (31 wave-1 regressions, partially addressed). For each, run the failing test, read the traceback, and either (a) update the test if the new test coverage is correct, or (b) update the new test in the wave-1/2 fan-out if the regression was caused by an over-eager test. Do NOT modify the crackerjack source under test. Do NOT add new tests — only fix existing ones. Return a list of fixes with file:line for each.',
    special: true,
  },
  {
    pkg: 'crackerjack.mahavishnu.mcp.tools.git_analytics.audit',
    stmts: 0,
    files: ['tests/unit/mahavishnu/mcp/tools/test_mcp_git_analytics.py', 'crackerjack/mahavishnu/mcp/tools/git_analytics.py'],
    hint: 'AUDIT only — no new test writing. The file was renamed from test_git_analytics.py to test_mcp_git_analytics.py in wave 3 setup to fix a module-name collision. Verify the rename was clean: (1) no stale .pyc files reference the old name; (2) pytest collects all 267 tests in the new location; (3) coverage on crackerjack/mahavishnu/mcp/tools/git_analytics.py is >= 80% (the agent claimed 90%). Report any discrepancy. Do not commit, do not push.',
    special: true,
  },
]

const TEST_DIRECTIVE = (p) => p.special
  ? `You are auditing/fixing an existing artifact in the crackerjack project at ${REPO}.

Target: ${p.pkg}
Files involved:
${p.files.map(f => '- ' + f).join('\n') || '(none — read /tmp/wave2_failures.txt and /tmp/regressions.txt for the work list)'}

Task: ${p.hint}

## Rules

- Read /Users/les/Projects/mahavishnu/CLAUDE.md "Crackerjack-Compliant Code" before making changes.
- For test fixes: do not introduce new dependencies. Keep the test style consistent with surrounding tests.
- For audit: report findings clearly. Do not modify source. Do not commit.

## Workflow

1. Read the relevant files and reports.
2. Make minimal targeted changes (or audit-only observations).
3. Run the affected tests and confirm they pass (or, for audit, confirm the stated claim).
4. Return a summary with: files touched, tests fixed/verified, observed behavior, and any remaining concerns.

Do NOT commit. Do NOT push.`
  : `You are writing pytest tests for the package \`${p.pkg}\` in the crackerjack project at ${REPO}.

Source file(s) to cover:
${p.files.map(f => '- ' + f).join('\n')}

The package has ~${p.stmts} statements and is at 0% (or near-0%) coverage.

Context: ${p.hint}

## Rules

- Read /Users/les/Projects/mahavishnu/CLAUDE.md "Crackerjack-Compliant Code" before writing any code. Asserts are fine in tests; other style rules (imports, X | None, from __future__ import annotations, pathlib) apply.
- Use existing pytest markers: unit, integration, slow, property. Mark tests >2s as @pytest.mark.slow.
- Test files go under tests/<mirror path>/test_<module>.py. CRITICAL: the test file basename MUST be unique across the entire tests/ tree — pytest cannot disambiguate two files with the same basename (e.g. test_git_analytics.py in tests/models/ AND tests/unit/.../tools/ would collide). If you are tempted to use a basename that already exists somewhere else, rename to something distinct (e.g. test_mcp_<thing>.py or test_<pkg>_<module>.py).
- Match the style of neighboring tests in the same package. Use existing conftest.py fixtures.
- For async code, asyncio_mode=auto (no @pytest.mark.asyncio).
- Do not introduce new dependencies. Mock external I/O (subprocess, httpx, network, fs) at the boundary.

## Workflow

1. Read the source file(s) AND any existing tests for them. Check for test file basename collisions (see rule above).
2. Identify the public API and obvious edge cases (None, empty, error, boundary).
3. Write the test file. Aim for 60%+ on the package. Don't chase 100%.
4. Run \`uv run pytest tests/<your-test-path> -v\` — all new tests must pass. If a pre-existing test in the same dir now fails, that's a REGRESSION — fix your new test, do not skip the old one.
5. Measure the lift: \`uv run coverage run --source=crackerjack.<pkg-dotted> -m pytest tests/<your-test-path> -q && uv run coverage report --include='crackerjack/<pkg-path>*'\`
6. If you found source bugs, document them in your final report. Do NOT fix the source.

## Return a summary with

- Path of each new (or modified) test file. CONFIRM the basename is unique (no collisions).
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
2. \`uv run coverage report --skip-empty > /tmp/crackerjack_wave3_final.txt\`
3. Compare /tmp/crackerjack_wave2_final.txt and /tmp/crackerjack_wave3_final.txt:
   - Report new TOTAL line.
   - For each package in the wave 3 fan-out, report before/after/delta.
   - List top 20 files by absolute coverage-point gain.
4. \`uv run pytest -q -m "not slow" --no-header\` and diff with /tmp/wave2_failures.txt to identify NEW fixes and any new regressions.
5. Verify that \`crackerjack/mahavishnu/mcp/tools/git_analytics.py\` is now >= 80% covered (this was the wave-2 file that hit a collection error).

Return a markdown report with:
- ## Summary (total before/after/delta)
- ## Per-package results (table: package | before | after | delta | new tests)
- ## Top gainers (top 20)
- ## Regression analysis (fixed | added | net)
- ## Suite health (pass/fail/xfail)
- ## git_analytics audit (confirm collected + covered)
- ## Remaining gaps (top 10 zero-coverage files for wave 4)

Do not commit. Do not push.`,
  { label: 'verify', phase: 'Verify lift' }
)

return { setup, writeResults, final }
