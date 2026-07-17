// Multi-agent workflow: increase test coverage in crackerjack — WAVE 4
// Repo: /Users/les/Projects/crackerjack
// Post-wave-3 state: 69% (19,595 / 70,258 stmts missed), 26 test failures
// Strategy: 10 parallel agents on the remaining zero-coverage tier +
// 1 memory-package deep dive + 1 regression fixer + 1 shadowing investigation.

export const meta = {
  name: 'crackerjack-coverage-fanout-wave4',
  description: 'Wave 4: cover the smallest remaining zero-coverage files, lift the memory package, fix the 26 remaining regressions, investigate the cli/handlers shadowing bug',
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

1. Read /tmp/crackerjack_wave3_final.txt and any wave-3 reports in /tmp/.
2. Confirm \`uv run pytest --collect-only -q 2>&1 | tail -5\` runs without collection errors.
3. Capture the current test failure list: \`uv run pytest -q -m "not slow" --no-header --tb=no 2>&1 | grep "^FAILED" | sort -u > /tmp/wave3_failures.txt; wc -l /tmp/wave3_failures.txt\`. Report the count.
4. Capture the top 20 zero-coverage files: \`uv run coverage report --skip-empty 2>&1 | awk 'NR>2 && NF>=4 {pct = substr($5, 1, length($5)-1); if (pct+0 == 0) print $1, $2}' | sort -k2 -nr | head -20\`.
5. Return a 5-line summary: TOTAL %, failing test count, any collection errors, top 5 zero-coverage files, and a yes/no on whether the suite imports.

Do not modify source files. Do not commit.`,
  { label: 'setup', phase: 'Setup' }
)

// ---------- Phase 2: fan out ----------
phase('Write tests')

const PACKAGES = [
  {
    pkg: 'crackerjack.memory.git_history_embedder',
    stmts: 111,
    files: ['crackerjack/memory/git_history_embedder.py'],
    hint: 'Git-history embedding service. Mock the embedding model + the storage backend. Cover: empty repo, single commit, branch history, embedding round-trip, error on missing HEAD.',
  },
  {
    pkg: 'crackerjack.mcp.tools.git_metrics_tools',
    stmts: 104,
    files: ['crackerjack/mcp/tools/git_metrics_tools.py'],
    hint: 'MCP tool exposing git metrics. Mock the underlying GitMetricsCollector. Cover: each tool handler, error fallback, empty results.',
  },
  {
    pkg: 'crackerjack.mcp.tools.mahavishnu_tools',
    stmts: 95,
    files: ['crackerjack/mcp/tools/mahavishnu_tools.py'],
    hint: 'MCP tools for Mahavishnu orchestration. Mock the pool manager + adapter registry. Cover: route_task, list_pools, get_pool_status, error paths.',
  },
  {
    pkg: 'crackerjack.agents.behavior_validator',
    stmts: 90,
    files: ['crackerjack/agents/behavior_validator.py'],
    hint: 'Agent behavior validator. Pure-function validation rules. Cover each rule: valid behavior, rule violations, edge cases (empty input, malformed behavior descriptor).',
  },
  {
    pkg: 'crackerjack.services.memory_aware_scanner',
    stmts: 82,
    files: ['crackerjack/services/memory_aware_scanner.py'],
    hint: 'Memory-aware scanner. Mock the embedding store. Cover: scan fresh files, scan duplicates, partial-match threshold, empty input.',
  },
  {
    pkg: 'crackerjack.memory.git_metrics_storage',
    stmts: 77,
    files: ['crackerjack/memory/git_metrics_storage.py'],
    hint: 'Storage layer for git metrics. Probably wraps SQLite/aiosqlite. Use a temp SQLite fixture. Cover: insert metrics, query by range, aggregate, schema migration, connection error.',
  },
  {
    pkg: 'crackerjack.services.pool_scaler',
    stmts: 71,
    files: ['crackerjack/services/pool_scaler.py'],
    hint: 'Worker pool auto-scaler. Mock the metrics source and the pool executor. Cover: scale up on high load, scale down on low load, no-op at boundaries, cooldown enforcement.',
  },
  {
    pkg: 'crackerjack.services.pool_client',
    stmts: 64,
    files: ['crackerjack/services/pool_client.py'],
    hint: 'Pool client (likely HTTP client to a remote pool). Mock httpx/aiohttp. Cover: success, retry, timeout, auth, malformed response.',
  },
  {
    pkg: 'crackerjack.mcp.client_runner',
    stmts: 60,
    files: ['crackerjack/mcp/client_runner.py'],
    hint: 'MCP client runner. Mock the MCP transport. Cover: connect, execute tool, disconnect, error handling.',
  },
  {
    pkg: 'crackerjack.memory.deep_dive',
    stmts: 0,
    files: [
      'crackerjack/memory/git_metrics_collector.py',
      'crackerjack/memory/vector_store.py',
      'crackerjack/memory/session_memory.py',
    ],
    hint: 'DEEP DIVE on the memory package (39.7% overall). Multiple submodules need lifts. Read the current coverage per file. Target each, prioritize ones with most remaining stmts. Do NOT duplicate the wave-1 vector_store tests. Aim for 30+ pp combined lift across the package.',
  },
  {
    pkg: 'crackerjack.regressions',
    stmts: 0,
    files: [],
    hint: 'NOT a coverage target. Wave 3 left 26 failures (down from 102). Read /tmp/wave3_failures.txt. For each, run the failing test, read the traceback, and either (a) update the test if the new test coverage is correct, or (b) update the wave-1/2/3 test that caused the regression. Do NOT modify the crackerjack source under test. Do NOT add new tests — only fix existing ones. Return a list of fixes with file:line for each.',
    special: true,
  },
  {
    pkg: 'crackerjack.cli.handlers.shadowing',
    stmts: 0,
    files: ['crackerjack/cli/handlers.py', 'crackerjack/cli/handlers/__init__.py'],
    hint: 'INVESTIGATE only — no new test writing. Wave 3 discovered that crackerjack/cli/handlers.py (374-line file) shadows crackerjack/cli/handlers/ (a package) at import time. The file is dead code; the real implementation lives in main_handlers.py. Investigate: (1) Is the .py file referenced anywhere (grep imports, setup.py, docs)? (2) Is it a leftover from a refactor? (3) Should it be deleted, or should it be the canonical implementation and the package deleted? Produce a written recommendation. Do NOT delete anything. Do NOT commit.',
    special: true,
  },
]

const TEST_DIRECTIVE = (p) => p.special
  ? `You are auditing/fixing an existing artifact in the crackerjack project at ${REPO}.

Target: ${p.pkg}
Files involved:
${p.files.map(f => '- ' + f).join('\n') || '(none — read /tmp/wave3_failures.txt for the work list)'}

Task: ${p.hint}

## Rules

- Read /Users/les/Projects/mahavishnu/CLAUDE.md "Crackerjack-Compliant Code" before making changes.
- For test fixes: do not introduce new dependencies. Keep the test style consistent with surrounding tests.
- For investigation: report findings clearly with evidence (grep results, file:line references). Do not modify source. Do not commit.

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
- CRITICAL: the test file basename MUST be unique across the entire tests/ tree. Pytest cannot disambiguate two files with the same basename (e.g. test_git_analytics.py in tests/models/ AND tests/unit/.../tools/ would collide). If tempted to use a basename that already exists elsewhere, rename to something distinct.
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
2. \`uv run coverage report --skip-empty > /tmp/crackerjack_wave4_final.txt\`
3. Compare /tmp/crackerjack_wave3_final.txt and /tmp/crackerjack_wave4_final.txt:
   - Report new TOTAL line.
   - For each package in the wave 4 fan-out, report before/after/delta.
   - List top 20 files by absolute coverage-point gain.
4. \`uv run pytest -q -m "not slow" --no-header\` and diff with /tmp/wave3_failures.txt to identify NEW fixes and any new regressions.
5. Note the cli/handlers shadowing investigation result.

Return a markdown report with:
- ## Summary (total before/after/delta)
- ## Per-package results (table)
- ## Top gainers (top 20)
- ## Regression analysis (fixed | added | net)
- ## Suite health (pass/fail/xfail)
- ## Shadowing investigation outcome (recommendation: delete .py file, delete package, or neither)
- ## Remaining gaps (top 10 zero-coverage files for wave 5)

Do not commit. Do not push.`,
  { label: 'verify', phase: 'Verify lift' }
)

return { setup, writeResults, final }
