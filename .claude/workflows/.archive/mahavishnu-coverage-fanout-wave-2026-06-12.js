// Multi-agent workflow: increase test coverage in mahavishnu
// Repo: /Users/les/Projects/mahavishnu (Python 3.13+)
// Strategy: fan out one test-writing agent per high-leverage module in parallel.
// Each agent uses its own .cov_<module>.qual so parallel pytest runs don't race.
//
// Wave: 2026-06-12
// Targets: 8 modules totaling 7,302 source lines that currently have no test file
// or have a very low test:source ratio.

export const meta = {
  name: 'mahavishnu-coverage-fanout-wave-2026-06-12',
  description: 'Fan out 8 agents to add comprehensive test coverage for 8 high-value Mahavishnu modules',
  phases: [
    { title: 'Write tests (fan-out)' },
    { title: 'Verify coverage' },
  ],
}

const REPO = '/Users/les/Projects/mahavishnu'

// Highest-leverage targets: substantial modules with no test file or very low ratio.
const TARGETS = [
  {
    src: 'mahavishnu/core/embeddings.py',
    test: 'tests/unit/test_embeddings_coverage.py',
    cov_data: '.cov_embeddings.qual',
    size: 1296,
    brief: 'EmbeddingService with FastEmbed/Ollama/OpenAI providers, circuit breaker, query sanitization, rate limiting, budget tracking, FastEmbed cache.',
  },
  {
    src: 'mahavishnu/core/resilience.py',
    test: 'tests/unit/test_resilience_coverage.py',
    cov_data: '.cov_resilience.qual',
    size: 1073,
    brief: 'Circuit breaker, retry policy with backoff, dead-letter handling, prometheus metrics integration (with noop shim).',
  },
  {
    src: 'mahavishnu/pools/manager.py',
    test: 'tests/unit/test_pool_manager_coverage.py',
    cov_data: '.cov_pools_manager.qual',
    size: 944,
    brief: 'Multi-pool orchestration: spawn, execute_on_pool, route_task with strategies (least_loaded, round_robin, random, affinity), health checks.',
  },
  {
    src: 'mahavishnu/core/task_router.py',
    test: 'tests/unit/test_task_router_coverage.py',
    cov_data: '.cov_task_router.qual',
    size: 907,
    brief: 'Task classification + model selection. IMPORTANT: existing guard test tests/unit/test_task_router.py::TestYAMLRoutingSync pins YAML routing to in-code routing — DO NOT modify it. Only ADD a new test file.',
  },
  {
    src: 'mahavishnu/core/adapter_persistence.py',
    test: 'tests/unit/test_adapter_persistence_coverage.py',
    cov_data: '.cov_adapter_persistence.qual',
    size: 859,
    brief: 'Adapter persistence layer: save/load adapter configurations, versioning, repository association.',
  },
  {
    src: 'mahavishnu/core/goal_team_metrics.py',
    test: 'tests/unit/test_goal_team_metrics_coverage.py',
    cov_data: '.cov_goal_team_metrics.qual',
    size: 844,
    brief: 'Goal/team metrics aggregation, calculation, formatting for CLI/MCP output.',
  },
  {
    src: 'mahavishnu/core/coordination/memory.py',
    test: 'tests/unit/test_coordination_memory_coverage.py',
    cov_data: '.cov_coordination_memory.qual',
    size: 736,
    brief: 'Coordination memory: agent state, task ownership, lock primitives for cross-process coordination.',
  },
  {
    src: 'mahavishnu/engines/agno_tools/file_tools.py',
    test: 'tests/unit/test_agno_file_tools_coverage.py',
    cov_data: '.cov_agno_file_tools.qual',
    size: 645,
    brief: 'Agno file operation tools: read, write, list, search within sandboxed paths with permission checks.',
  },
]

const SYSTEM_PROMPT = `
You are writing tests for ONE specific Python module in the Mahavishnu project. The module currently has NO test file (or very low coverage). Your job: bring it to >=80% line+branch coverage.

## Mahavishnu test conventions (from /Users/les/Projects/mahavishnu/CLAUDE.md)

- Use \`from __future__ import annotations\` as the first non-comment line of every test file.
- Use pytest. asyncio_mode is "auto" — do NOT use @pytest.mark.asyncio on async tests.
- Use \`pytest.raises\` for exception testing (no bare assert in test logic).
- Mark slow tests with \`@pytest.mark.slow\`.
- Mark unit tests with \`@pytest.mark.unit\`.
- Imports sorted within each section (stdlib -> third-party -> first-party). known-first-party = ["mahavishnu"].
- Modern syntax: \`X | None\` (not Optional[X]), \`list[str]\` (not List[str]), pathlib.Path for filesystem paths.
- All I/O should be mocked. For HTTP, use \`respx\` or \`unittest.mock\`. For async, use \`AsyncMock\`.
- Python 3.13 target.
- Do not modify pyproject.toml or any existing test files. Only ADD a new test file at the path specified.

## Your workflow

1. Read the entire target module (use the path given below).
2. Enumerate public surface: classes, public functions, public methods, top-level constants/enums.
3. Plan test cases:
   - Happy path for each public function/method
   - Edge cases (empty input, None, boundary values, large inputs)
   - Error paths (each exception type the module raises)
   - Branch coverage (both sides of every if/else, every except clause, both arms of and/or short-circuits)
   - Async behavior if applicable (mock the awaits)
4. Write the test file at the path given below.
5. Run: \`cd /Users/les/Projects/mahavishnu && uv run pytest <TEST_PATH> --cov=<SRC_MODULE> --cov-branch --cov-data-file=<COV_DATA> --no-header -q\`
6. Read the coverage report. If <80%, add more tests targeting the missing lines/branches. Iterate.
7. Stop when coverage >=80% OR you've made 3 honest attempts to cover remaining lines (some may be unreachable — e.g. pragma: no cover, platform-specific code that's mocked away).

## Output

Return a JSON object with:
- final_coverage_pct (number, e.g. 87.4)
- tests_added (integer)
- test_file_lines (integer)
- uncovered_lines: array of {line, reason} for lines you couldn't cover and why
- any_module_modifications: array of strings — must be empty (we only add tests, not change source)
- existing_test_failures: array of {test_path, test_name, error_short} — anything that was already broken before this wave (do NOT fix; just report)

## Verification discipline

Do NOT trust your own "I wrote the tests" claim. Run the actual pytest command. Read the terminal output. Report the number you actually saw. If you can't get to 80% in 3 iterations, report what you got and explain.
`

// ---------- Phase 1: Fan out test writing ----------
phase('Write tests (fan-out)')

const writeResults = await parallel(
  TARGETS.map((t) => () => {
    const mod_dotted = t.src.replace(/\.py$/, '').replace(/\//g, '.')
    const prompt = `${SYSTEM_PROMPT}

## Your specific target

- **Source module**: \`${t.src}\` (${t.size} lines)
- **Test file to create**: \`${t.test}\`
- **Coverage data file** (use this to avoid colliding with parallel agents): \`${t.cov_data}\`
- **What this module does**: ${t.brief}

## Concrete commands

Read module + plan tests:
\`\`\`bash
cd ${REPO}
ls -la ${t.src}
wc -l ${t.src}
\`\`\`

Write the test file with the Write tool, absolute path \`${REPO}/${t.test}\`.

Run coverage check:
\`\`\`bash
cd ${REPO}
uv run pytest ${t.test} \\
  --cov=${mod_dotted} \\
  --cov-branch \\
  --cov-data-file=${t.cov_data} \\
  --no-header -q 2>&1 | tail -40
\`\`\`

If coverage <80%, identify missing lines:
\`\`\`bash
cd ${REPO}
uv run pytest ${t.test} \\
  --cov=${mod_dotted} \\
  --cov-branch \\
  --cov-data-file=${t.cov_data} \\
  --cov-report=term-missing:skip-covered \\
  --no-header -q 2>&1 | tail -80
\`\`\`

Then add tests for those lines and re-run.

## Reminder

- Do NOT modify any other files.
- Do NOT run \`uv pip install\`. Dependencies are already installed.
- Do NOT touch .cov_qual (the shared one). Use your own \`${t.cov_data}\`.
- Do NOT add \`@pytest.mark.asyncio\` — asyncio_mode is auto.
- For task_router.py: do NOT modify the existing tests/unit/test_task_router.py.

Return JSON only. Be honest about coverage numbers.`
    return agent(prompt, {
      label: `tests:${t.src.split('/').pop()}`,
      phase: 'Write tests (fan-out)',
      agentType: 'python-pro',
      schema: {
        type: 'object',
        properties: {
          final_coverage_pct: { type: 'number' },
          tests_added: { type: 'integer' },
          test_file_lines: { type: 'integer' },
          uncovered_lines: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                line: { type: 'integer' },
                reason: { type: 'string' },
              },
              required: ['line', 'reason'],
            },
          },
          any_module_modifications: { type: 'array', items: { type: 'string' } },
          existing_test_failures: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                test_path: { type: 'string' },
                test_name: { type: 'string' },
                error_short: { type: 'string' },
              },
              required: ['test_path', 'test_name', 'error_short'],
            },
          },
        },
        required: [
          'final_coverage_pct',
          'tests_added',
          'test_file_lines',
          'uncovered_lines',
          'any_module_modifications',
          'existing_test_failures',
        ],
      },
    })
  })
)

log(`Write phase complete: ${writeResults.filter(Boolean).length}/${TARGETS.length} agents returned data`)

// ---------- Phase 2: Verify ----------
phase('Verify coverage')

const VERIFIER_PROMPT = (t) => {
  const mod_dotted = t.src.replace(/\.py$/, '').replace(/\//g, '.')
  return `You are verifying the test file another agent claimed to write for ${t.src}.

## Steps

1. Confirm the file exists and has reasonable content:
\`\`\`bash
ls -la ${REPO}/${t.test}
wc -l ${REPO}/${t.test}
grep -c "^def test_" ${REPO}/${t.test} || true
grep -c "^    def test_" ${REPO}/${t.test} || true
\`\`\`

2. Read the test file (it should have at least 5 test functions, with proper imports and fixtures).

3. Run the test file to confirm it passes:
\`\`\`bash
cd ${REPO}
uv run pytest ${t.test} --cov-data-file=${t.cov_data} --no-header -q 2>&1 | tail -15
\`\`\`

4. Re-run the coverage measurement (THIS IS THE GROUND TRUTH):
\`\`\`bash
cd ${REPO}
uv run pytest ${t.test} \\
  --cov=${mod_dotted} \\
  --cov-branch \\
  --cov-data-file=${t.cov_data} \\
  --no-header -q 2>&1 | tail -10
\`\`\`

5. Use term-missing to get exact uncovered lines if <80%:
\`\`\`bash
cd ${REPO}
uv run pytest ${t.test} \\
  --cov=${mod_dotted} \\
  --cov-branch \\
  --cov-data-file=${t.cov_data} \\
  --cov-report=term:skip-covered \\
  --no-header -q 2>&1 | tail -30
\`\`\`

Return a JSON object:
{
  file_exists: boolean,
  test_count: integer (count of \`def test_\` functions in the file),
  tests_pass: boolean,
  coverage_pct_actual: number (the number you saw in the terminal, not what the writer claimed),
  uncovered_critical_lines: array of integer (line numbers that are uncovered),
  discrepancy: string | null (e.g. "writer claimed 87% but actual is 62%"),
  verdict: "ok" | "needs_more_tests" | "broken" | "not_real"
}

Verdict rules:
- "ok" if file_exists AND tests_pass AND coverage_pct_actual >= 80
- "needs_more_tests" if file_exists AND tests_pass AND coverage < 80
- "broken" if file_exists AND not tests_pass
- "not_real" if not file_exists`
}

const verifyResults = await parallel(
  TARGETS.map((t, i) => () => {
    const writer = writeResults[i]
    if (!writer) {
      return {
        verdict: 'not_real',
        file_exists: false,
        test_count: 0,
        tests_pass: false,
        coverage_pct_actual: 0,
        uncovered_critical_lines: [],
        discrepancy: 'agent failed to return',
      }
    }
    return agent(VERIFIER_PROMPT(t), {
      label: `verify:${t.src.split('/').pop()}`,
      phase: 'Verify coverage',
      agentType: 'python-pro',
      schema: {
        type: 'object',
        properties: {
          file_exists: { type: 'boolean' },
          test_count: { type: 'integer' },
          tests_pass: { type: 'boolean' },
          coverage_pct_actual: { type: 'number' },
          uncovered_critical_lines: { type: 'array', items: { type: 'integer' } },
          discrepancy: { type: ['string', 'null'] },
          verdict: { enum: ['ok', 'needs_more_tests', 'broken', 'not_real'] },
        },
        required: ['file_exists', 'test_count', 'tests_pass', 'coverage_pct_actual', 'verdict'],
      },
    })
  })
)

log(`Verify phase complete: ${verifyResults.filter(v => v && v.verdict === 'ok').length}/${TARGETS.length} pass at >=80%`)

// ---------- Final report ----------
const summary = TARGETS.map((t, i) => {
  const w = writeResults[i]
  const v = verifyResults[i]
  return {
    module: t.src,
    test: t.test,
    size: t.size,
    writer_claimed_coverage: w?.final_coverage_pct,
    writer_claimed_tests: w?.tests_added,
    writer_claimed_lines: w?.test_file_lines,
    verifier_actual_coverage: v?.coverage_pct_actual,
    verifier_test_count: v?.test_count,
    verdict: v?.verdict,
    discrepancy: v?.discrepancy ?? null,
  }
})

const verdictCounts = summary.reduce((acc, s) => {
  const k = s.verdict || 'unknown'
  acc[k] = (acc[k] || 0) + 1
  return acc
}, {})

const totalSourceLines = TARGETS.reduce((s, t) => s + t.size, 0)
const okCount = verdictCounts.ok || 0
const avgCoverage = summary
  .filter(s => typeof s.verifier_actual_coverage === 'number')
  .reduce((s, x) => s + x.verifier_actual_coverage, 0) / Math.max(1, summary.filter(s => typeof s.verifier_actual_coverage === 'number').length)

return {
  wave: 'mahavishnu-coverage-fanout-wave-2026-06-12',
  targets: TARGETS.length,
  total_source_lines: totalSourceLines,
  verdict_counts: verdictCounts,
  avg_actual_coverage: Math.round(avgCoverage * 10) / 10,
  summary,
  needs_attention: summary.filter(s => s.verdict !== 'ok'),
}
