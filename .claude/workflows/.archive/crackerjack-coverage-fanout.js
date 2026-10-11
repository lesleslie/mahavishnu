// Multi-agent workflow: increase test coverage in crackerjack
// Repo: /Users/les/Projects/crackerjack (Python 3.13+)
// Baseline: 6% total coverage, 70,148 stmts, 64,549 missed.
// Strategy: fan out one test-writing agent per high-leverage package in parallel.

export const meta = {
  name: 'crackerjack-coverage-fanout',
  description: 'Fan out agents to write pytest tests for zero-coverage crackerjack modules',
  phases: [
    { title: 'Capture baseline' },
    { title: 'Write tests' },
    { title: 'Verify lift' },
  ],
}

const REPO = '/Users/les/Projects/crackerjack'

// ---------- Phase 1: capture baseline ----------
phase('Capture baseline')
const baseline = await agent(
  `In ${REPO}:

1. Run \`uv run pytest --collect-only -q\` to confirm the suite is importable. Stop and report if there are collection errors.
2. Run \`uv run coverage run --source=crackerjack -m pytest -q -m "not slow" --no-header\` to gather fresh coverage (existing .coverage is stale).
3. Run \`uv run coverage report --skip-empty > /tmp/crackerjack_baseline.txt\`.
4. Return:
   - The TOTAL line.
   - The top 30 zero-coverage files by statement count.
   - Any collection errors.

Do not modify source files. Do not commit.`,
  { label: 'baseline', phase: 'Capture baseline' }
)

// ---------- Phase 2: fan out test-writing agents ----------
phase('Write tests')

// Highest-leverage targets: zero-or-near-zero coverage with many stmts.
const PACKAGES = [
  { pkg: 'crackerjack.services.secure_subprocess',         stmts: 241, hint: 'Wraps subprocess with safety checks. Mock subprocess.run/Popen, test deny-list and env stripping.' },
  { pkg: 'crackerjack.services.secure_status_formatter',   stmts: 220, hint: 'Status formatter — likely pure functions. Test empty/long/unicode/injection inputs.' },
  { pkg: 'crackerjack.services.safe_code_modifier',        stmts: 216, hint: 'AST-based source edits. Use tmp_path. Test idempotence, syntax errors, no-op cases.' },
  { pkg: 'crackerjack.services.thread_safe_status_collector', stmts: 195, hint: 'Concurrent aggregator. Mark slow. Cover thread-safety invariants with concurrent.futures.' },
  { pkg: 'crackerjack.shell.adapter',                       stmts: 176, hint: 'Shell session adapter. Mock the transport. Test lifecycle, exec, errors, timeouts.' },
  { pkg: 'crackerjack.skills.agent_skills',                 stmts: 186, hint: 'Skill registry/dispatch. Test registration, dispatch, missing-skill errors.' },
  { pkg: 'crackerjack.services.refurb_fixer',               stmts: 781, hint: '7% covered — large file. Skip already-tested paths, focus on the remaining 93%.' },
  { pkg: 'crackerjack.services.swarm_client',               stmts: 258, hint: '23% covered. Network client — mock httpx/aiohttp. Test retry, circuit-breaker, timeout, malformed.' },
  { pkg: 'crackerjack.services.vector_store',               stmts: 228, hint: '12% covered. Use a fake/in-memory backend. Test CRUD, similarity, empty store.' },
  { pkg: 'crackerjack.websocket.server',                    stmts: 130, hint: 'WebSocket server. FastAPI TestClient or websockets test helpers. Test connect, broadcast, auth, shutdown.' },
]

const TEST_DIRECTIVE = (p) => `You are writing pytest tests for the package \`${p.pkg}\` in the crackerjack project at ${REPO}.

The package has ~${p.stmts} statements and is at 0% (or near-0%) coverage.

Context: ${p.hint}

## Rules

- Read /Users/les/Projects/mahavishnu/CLAUDE.md "Crackerjack-Compliant Code" before writing any code. Asserts are fine in tests; other style rules (imports, X | None, from __future__ import annotations, pathlib) apply.
- Use existing pytest markers: unit, integration, slow, property. Mark tests >2s as @pytest.mark.slow.
- Test files go under tests/<mirror path>/test_<module>.py. Match the style of neighboring tests in the same package.
- Use existing conftest.py fixtures. Do not introduce new dependencies. Mock external I/O (subprocess, httpx, network, fs) at the boundary.
- For async, asyncio_mode=auto — no @pytest.mark.asyncio.

## Workflow

1. Read the source file(s) and any existing tests.
2. Identify public API and obvious edge cases (None, empty, error, boundary).
3. Write the test file. Aim for 60%+ on the package. Don't chase 100%.
4. Run \`uv run pytest tests/<your-test-path> -v\` — all new tests must pass. If a test fails because of a real source bug, REPORT it; do not silently skip.
5. Measure the lift: \`uv run coverage run --source=crackerjack.<pkg-dotted> -m pytest tests/<your-test-path> -q && uv run coverage report --include='crackerjack/<pkg-path>*'\`

## Return a summary with

- Path of each new test file.
- Number of tests added.
- Coverage % before vs after for this package.
- Any source bugs observed.
- Any xfail/skip with reason.

Do NOT commit. Do NOT push. Do NOT run the full suite. Stay in your package.`

const writeResults = await parallel(
  PACKAGES.map((p) => () =>
    agent(TEST_DIRECTIVE(p), { label: `test:${p.pkg}`, phase: 'Write tests', agentType: 'python-pro' })
  )
)

// ---------- Phase 3: verify lift ----------
phase('Verify lift')
const final = await agent(
  `In ${REPO}:

1. \`uv run coverage run --source=crackerjack -m pytest -q -m "not slow" --no-header\`
2. \`uv run coverage report --skip-empty > /tmp/crackerjack_final.txt\`
3. Diff /tmp/crackerjack_baseline.txt and /tmp/crackerjack_final.txt:
   - Report new TOTAL line.
   - Per-package before/after/delta.
   - Top 20 files by absolute coverage-point gain.
4. \`uv run pytest -q -m "not slow" --no-header\` — report pass/fail and any new failures vs the pre-fanout run.

Return a markdown report with:
- ## Summary (total before/after/delta)
- ## Per-package results (table)
- ## Top gainers (top 20)
- ## Suite health (pass/fail/regressions)
- ## Remaining gaps (top 10 zero-coverage files for the next wave)

Do not commit. Do not push.`,
  { label: 'verify', phase: 'Verify lift' }
)

return { baseline, writeResults, final }
