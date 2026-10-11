// Multi-agent workflow: coverage wave 2 for mahavishnu
// Repo: /Users/les/Projects/mahavishnu (Python 3.13+)
// Wave 1 (2026-06-12 part 1) covered 8 modules averaging 94.7%.
// Wave 2 picks the next 8 high-value targets. Verifier phase dropped
// to avoid the 429 rate-limit issue; coverage is measured directly
// after the wave completes (cheap, no agents).

export const meta = {
  name: 'mahavishnu-coverage-fanout-wave-2026-06-12-part2',
  description: 'Wave 2: 8 more modules, no verifier phase (measured directly post-wave)',
  phases: [
    { title: 'Write tests (fan-out)' },
  ],
}

const REPO = '/Users/les/Projects/mahavishnu'

const TARGETS = [
  {
    src: 'mahavishnu/ingesters/otel_ingester.py',
    test: 'tests/unit/test_otel_ingester_coverage.py',
    cov_data: '.cov_otel_ingester.qual',
    size: 1343,
    brief: 'OpenTelemetry trace ingestion: storage backends (DuckDB, PostgreSQL+pgvector), semantic search, batch ingestion, span filtering.',
  },
  {
    src: 'mahavishnu/websocket/server.py',
    test: 'tests/unit/test_websocket_server_coverage.py',
    cov_data: '.cov_websocket_server.qual',
    size: 1001,
    brief: 'WebSocket server: connection lifecycle, channel subscriptions, broadcast, rate limiting, authentication. NOTE: there is an existing test tests/unit/test_websocket_server.py and tests/unit/test_websocket_server_impl.py — do NOT modify them. Only ADD a new test file.',
  },
  {
    src: 'mahavishnu/core/repositories/tasks.py',
    test: 'tests/unit/test_repositories_tasks_coverage.py',
    cov_data: '.cov_repositories_tasks.qual',
    size: 723,
    brief: 'Task repository pattern: CRUD operations, query filters, pagination, status transitions, batch operations.',
  },
  {
    src: 'mahavishnu/workers/registry.py',
    test: 'tests/unit/test_workers_registry_coverage.py',
    cov_data: '.cov_workers_registry.qual',
    size: 591,
    brief: 'Worker registry: registration, lookup, capability matching, health tracking, deregistration.',
  },
  {
    src: 'mahavishnu/core/repositories/runs.py',
    test: 'tests/unit/test_repositories_runs_coverage.py',
    cov_data: '.cov_repositories_runs.qual',
    size: 544,
    brief: 'Run repository pattern: workflow run records, status history, retry tracking, query by status/agent.',
  },
  {
    src: 'mahavishnu/websocket/metrics.py',
    test: 'tests/unit/test_websocket_metrics_coverage.py',
    cov_data: '.cov_websocket_metrics.qual',
    size: 449,
    brief: 'WebSocket metrics: connection counts, message rates, broadcast latency, error rates, prometheus exposition.',
  },
  {
    src: 'mahavishnu/core/repositories/documents.py',
    test: 'tests/unit/test_repositories_documents_coverage.py',
    cov_data: '.cov_repositories_documents.qual',
    size: 400,
    brief: 'Document repository: storage, retrieval, search by metadata, vector storage integration.',
  },
  {
    src: 'mahavishnu/websocket/rate_limiter.py',
    test: 'tests/unit/test_websocket_rate_limiter_coverage.py',
    cov_data: '.cov_websocket_rate_limiter.qual',
    size: 355,
    brief: 'WebSocket rate limiter: token bucket, sliding window, per-client and per-channel limits, rejection handling.',
  },
]

const SYSTEM_PROMPT = `You are writing tests for ONE specific Python module in the Mahavishnu project. The module currently has NO test file (or very low coverage). Your job: bring it to >=80% line+branch coverage.

## Mahavishnu test conventions (from /Users/les/Projects/mahavishnu/CLAUDE.md)

- Use \`from __future__ import annotations\` as the first non-comment line of every test file.
- Use pytest. asyncio_mode is "auto" — do NOT use @pytest.mark.asyncio on async tests.
- Use \`pytest.raises\` for exception testing.
- Mark slow tests with \`@pytest.mark.slow\`. Mark unit tests with \`@pytest.mark.unit\`.
- Imports sorted within each section (stdlib -> third-party -> first-party). known-first-party = ["mahavishnu"].
- Modern syntax: \`X | None\` (not Optional[X]), \`list[str]\` (not List[str]), pathlib.Path for filesystem paths.
- All I/O should be mocked. For HTTP, use \`respx\` or \`unittest.mock\`. For async, use \`AsyncMock\`. For websockets, use \`starlette.testclient\` or mock the connection.
- Python 3.13 target.
- Do not modify pyproject.toml or any existing test files. Only ADD a new test file at the path specified.

## Workflow

1. Read the entire target module.
2. Enumerate public surface: classes, public functions, public methods, top-level constants/enums.
3. Plan tests: happy path, edge cases (empty, None, boundary, large), error paths, branch coverage, async mocks.
4. Write the test file at the path given.
5. Run: \`cd /Users/les/Projects/mahavishnu && COVERAGE_FILE=<COV_DATA> uv run pytest <TEST_PATH> --cov=<SRC_MODULE> --cov-branch --override-ini="addopts=" --no-header -q\`
6. If <80%, identify missing lines with --cov-report=term-missing:skip-covered and add tests.
7. Stop at >=80% OR after 3 honest attempts (some lines may be unreachable).

CRITICAL: This project uses pytest-xdist with -n auto in addopts. You MUST use --override-ini="addopts=" to disable parallel mode, OR the --cov-data-file flag will conflict. Use the COVERAGE_FILE env var.

## Output JSON

{
  "final_coverage_pct": number,
  "tests_added": integer,
  "test_file_lines": integer,
  "uncovered_lines": [{"line": int, "reason": str}],
  "any_module_modifications": [string],   // must be empty
  "existing_test_failures": [{"test_path": str, "test_name": str, "error_short": str}]
}

## Verification discipline

Do NOT trust your own claim. Run the actual pytest command. Read the terminal output. Report what you saw. If you can't reach 80% in 3 iterations, report the actual number and explain.`

phase('Write tests (fan-out)')

const writeResults = await parallel(
  TARGETS.map((t) => () => {
    const mod_dotted = t.src.replace(/\.py$/, '').replace(/\//g, '.')
    const prompt = `${SYSTEM_PROMPT}

## Your target

- **Source module**: \`${t.src}\` (${t.size} lines)
- **Test file to create**: \`${t.test}\`
- **Coverage data file**: \`${t.cov_data}\` (yours alone; don't touch .cov_qual)
- **Module description**: ${t.brief}

## Commands

Read source + plan:
\`\`\`bash
cd ${REPO} && wc -l ${t.src} && ls -la ${t.src}
\`\`\`

Write the test file with the Write tool, absolute path \`${REPO}/${t.test}\`.

Run coverage (NOTE the COVERAGE_FILE env var and --override-ini trick):
\`\`\`bash
cd ${REPO}
COVERAGE_FILE=${t.cov_data} uv run pytest ${t.test} \\
  --cov=${mod_dotted} \\
  --cov-branch \\
  --override-ini="addopts=" \\
  --no-header -q 2>&1 | tail -40
\`\`\`

If <80%, get missing lines:
\`\`\`bash
cd ${REPO}
COVERAGE_FILE=${t.cov_data} uv run pytest ${t.test} \\
  --cov=${mod_dotted} \\
  --cov-branch \\
  --override-ini="addopts=" \\
  --cov-report=term-missing:skip-covered \\
  --no-header -q 2>&1 | tail -80
\`\`\`

## Reminders

- Do NOT modify any other files.
- Do NOT run \`uv pip install\`.
- Do NOT add \`@pytest.mark.asyncio\`.
- For websocket/server.py: do NOT modify existing tests/unit/test_websocket_server.py or tests/unit/test_websocket_server_impl.py.

Return JSON only.`
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
          uncovered_lines: { type: 'array', items: { type: 'object', properties: { line: { type: 'integer' }, reason: { type: 'string' } }, required: ['line', 'reason'] } },
          any_module_modifications: { type: 'array', items: { type: 'string' } },
          existing_test_failures: { type: 'array', items: { type: 'object', properties: { test_path: { type: 'string' }, test_name: { type: 'string' }, error_short: { type: 'string' } }, required: ['test_path', 'test_name', 'error_short'] } },
        },
        required: ['final_coverage_pct', 'tests_added', 'test_file_lines', 'uncovered_lines', 'any_module_modifications', 'existing_test_failures'],
      },
    })
  })
)

log(`Write phase: ${writeResults.filter(Boolean).length}/${TARGETS.length} agents returned data`)

const summary = TARGETS.map((t, i) => {
  const w = writeResults[i]
  return {
    module: t.src,
    test: t.test,
    size: t.size,
    writer_claimed_coverage: w?.final_coverage_pct,
    writer_claimed_tests: w?.tests_added,
    writer_claimed_lines: w?.test_file_lines,
    agent_succeeded: !!w,
  }
})

const totalSourceLines = TARGETS.reduce((s, t) => s + t.size, 0)
const succeeded = summary.filter(s => s.agent_succeeded).length

return {
  wave: 'mahavishnu-coverage-fanout-wave-2026-06-12-part2',
  targets: TARGETS.length,
  total_source_lines: totalSourceLines,
  agents_succeeded: succeeded,
  agents_failed: TARGETS.length - succeeded,
  summary,
  note: 'Verifier phase dropped; coverage will be measured directly by Claude after wave completes.',
}
