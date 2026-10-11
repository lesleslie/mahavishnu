// Multi-agent workflow: increase test coverage in crackerjack — WAVE 2
// Repo: /Users/les/Projects/crackerjack
// Post-wave-1 state: 67% (23,029 / 70,258 stmts missed)
// Strategy: 12 parallel test-writers targeting the next-highest-leverage
// packages, plus 1 dedicated regression-fixer (wave 1 introduced 31).

export const meta = {
  name: 'crackerjack-coverage-fanout-wave2',
  description: 'Wave 2: lift coverage on the next tier of crackerjack packages and fix wave-1 regressions',
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

1. Read /tmp/crackerjack_final.txt (post-wave-1 coverage report) and /tmp/regressions.txt (wave-1 regressions) so you understand the current state.
2. Run \`uv run pytest --collect-only -q\` to confirm the suite still imports. Report any collection errors.
3. Confirm .coverage is fresh (\`ls -la .coverage\`).
4. Return a 3-line summary of: current TOTAL %, number of regressions, and a yes/no on whether the suite imports cleanly.

Do not modify source files. Do not commit.`,
  { label: 'setup', phase: 'Setup' }
)

// ---------- Phase 2: fan out ----------
// Targets ranked by (total_coverage_points × lift_potential). Agents run
// concurrently. None share a package, so no write conflicts.
//
// 1 agent is dedicated to fixing the 31 wave-1 regressions, because they
// are not coverage work and would otherwise leak noise into the delta
// report. The other 11 are pure coverage lifts.
phase('Write tests')

const PACKAGES = [
  {
    pkg: 'crackerjack.mahavishnu.mcp.tools.git_analytics',
    stmts: 1035,
    files: ['crackerjack/mahavishnu/mcp/tools/git_analytics.py'],
    hint: 'Biggest single zero-coverage file (1035 stmts, 384 branches). Likely git-statistics aggregator. Mock subprocess/CLI output. Cover: empty repo, multi-author, merge commits, edge cases on missing HEAD.',
  },
  {
    pkg: 'crackerjack.core.phase_coordinator',
    stmts: 954,
    files: ['crackerjack/core/phase_coordinator.py'],
    hint: '49% covered. Lift to 75%+. Core orchestration. Look at existing tests/test_phase_coordinator.py and tests/unit/core/test_phase_coordinator_additional.py to see what is already covered; do NOT duplicate. Target the remaining ~50%.',
  },
  {
    pkg: 'crackerjack.executors.hook_executor',
    stmts: 885,
    files: ['crackerjack/executors/hook_executor.py'],
    hint: '55% covered. Lift to 75%+. Subprocess-based hook runner. Mock subprocess at boundary. Cover: timeouts, exit-code handling, parallel execution, error paths. See existing tests in tests/test_hook_executor.py and tests/executors/.',
  },
  {
    pkg: 'crackerjack.parsers.json_parsers',
    stmts: 635,
    files: ['crackerjack/parsers/json_parsers.py'],
    hint: '18% covered. Pure-function JSON schema parsers. Easy to lift: feed representative JSON inputs and assert parsed structures. Cover happy + malformed + schema-mismatch.',
  },
  {
    pkg: 'crackerjack.parsers.regex_parsers',
    stmts: 634,
    files: ['crackerjack/parsers/regex_parsers.py'],
    hint: '33% covered. Regex-driven parsers. Use hypothesis property-based tests where appropriate. Cover each parser\'s happy path and its no-match fallback.',
  },
  {
    pkg: 'crackerjack.agents.helpers.ast_transform.surgeons.libcst_surgeon',
    stmts: 849,
    files: ['crackerjack/agents/helpers/ast_transform/surgeons/libcst_surgeon.py'],
    hint: '65% covered. Lift to 80%+. LibCST-based AST surgery. Use small Python code samples + libcst CST round-trip. Cover: node insertion, replacement, deletion, syntax error inputs.',
  },
  {
    pkg: 'crackerjack.executors.async_hook_executor',
    stmts: 423,
    files: ['crackerjack/executors/async_hook_executor.py'],
    hint: '29% covered. Async hook runner — likely asyncio.gather over subprocesses. Mock asyncio.create_subprocess_exec. Cover concurrency, cancellation, error handling. Mark slow tests with @pytest.mark.slow.',
  },
  {
    pkg: 'crackerjack.managers.publish_manager',
    stmts: 501,
    files: ['crackerjack/managers/publish_manager.py'],
    hint: '11% covered. Publish-to-PyPI workflow. Mock the upload + twine subprocess, and the HTTP/git calls. Cover: version validation, dry-run, conflict detection, rollback.',
  },
  {
    pkg: 'crackerjack.services.config_cleanup',
    stmts: 484,
    files: ['crackerjack/services/config_cleanup.py'],
    hint: '35% covered. Config-file cleanup service. Use tmp_path + real config fixtures. Cover: drift detection, repair, backup-before-write, idempotence.',
  },
  {
    pkg: 'crackerjack.agents.documentation_agent',
    stmts: 418,
    files: ['crackerjack/agents/documentation_agent.py'],
    hint: '28% covered. Doc-generation agent. Mock file I/O and LLM calls. Cover: docstring extraction, format conversion, error fallback.',
  },
  {
    pkg: 'crackerjack.agents.coordinator',
    stmts: 515,
    files: ['crackerjack/agents/coordinator.py'],
    hint: '39% covered. Agent coordinator. Note: tests/test_agents/test_coordinator.py has 3 regressions from wave 1 — investigate whether your new tests re-trigger or fix those as a side effect. Mock sub-agents.',
  },
  {
    pkg: 'crackerjack.executors.hook_lock_manager',
    stmts: 388,
    files: ['crackerjack/executors/hook_lock_manager.py'],
    hint: '16% covered. File-locking manager. Use tmp_path. Cover: lock acquisition, blocking, timeout, stale-lock cleanup, cross-process semantics (mock the lock file).',
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
- Test files go under tests/<mirror path>/test_<module>.py. If a test file already exists for this module, EXTEND it (or add new files in the same dir) — do NOT delete or rewrite pre-existing tests.
- Match the style of neighboring tests in the same package. Use existing conftest.py fixtures.
- For async code, asyncio_mode=auto (no @pytest.mark.asyncio).
- Do not introduce new dependencies. Mock external I/O (subprocess, httpx, network, fs) at the boundary.
- IMPORTANT: do not break any pre-existing test. If you need to refactor a fixture, do it in a non-disruptive way (additive only).

## Workflow

1. Read the source file(s) AND any existing tests for them. Identify the public API and obvious edge cases (None, empty, error, boundary).
2. Write the test file. Aim for 60%+ on the package (or lift by 25+ pp if already partially covered). Don't chase 100%.
3. Run \`uv run pytest tests/<your-test-path> -v\` — all new tests must pass. If a pre-existing test in the same dir now fails, that's a REGRESSION — fix your new test, do not skip the old one.
4. Measure the lift: \`uv run coverage run --source=crackerjack.<pkg-dotted> -m pytest tests/<your-test-path> -q && uv run coverage report --include='crackerjack/<pkg-path>*'\`
5. If you found source bugs, document them in your final report. Do NOT fix the source.

## Return a summary with

- Path of each new (or modified) test file.
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
2. \`uv run coverage report --skip-empty > /tmp/crackerjack_wave2_final.txt\`
3. Compare /tmp/crackerjack_final.txt and /tmp/crackerjack_wave2_final.txt:
   - Report new TOTAL line.
   - For each package in the wave 2 fan-out, report before/after/delta.
   - List top 20 files by absolute coverage-point gain.
4. \`uv run pytest -q -m "not slow" --no-header\` and compare with the wave-1 post-state to identify any NEW regressions (or fixed tests).
5. Diff the regression list: how many wave-1 regressions are now fixed, how many new ones appeared.

Return a markdown report with:
- ## Summary (total before/after/delta)
- ## Per-package results (table: package | before | after | delta | new tests)
- ## Top gainers (top 20)
- ## Regression analysis (fixed | added | net)
- ## Suite health (pass/fail/xfail)
- ## Remaining gaps (top 10 zero-coverage files for wave 3)

Do not commit. Do not push.`,
  { label: 'verify', phase: 'Verify lift' }
)

return { setup, writeResults, final }
