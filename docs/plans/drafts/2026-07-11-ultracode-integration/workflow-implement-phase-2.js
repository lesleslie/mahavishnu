// Workflow: Implement Phase 2 of the integration plan.
// Phase 2 = Opt-In Loop-Until-Dry for Pattern Detection.
// Source plan: docs/plans/2026-07-11-ultracode-integration-wiring.md

export const meta = {
  name: 'implement-phase-2-loop-until-dry',
  description: 'Implement the opt-in loop-until-dry helper for pattern detection',
  phases: [
    { title: 'T2.1 — loop_helpers.py' },
    { title: 'T2.2/T2.3 parallel wiring' },
    { title: 'T2.4 tests + T2.5 export' },
    { title: 'Synthesis review' },
  ],
};

const T21_SCHEMA = {
  type: 'object',
  required: ['files_created', 'files_modified', 'tests_passing', 'summary', 'blockers'],
  properties: {
    files_created: { type: 'array', items: { type: 'string' } },
    files_modified: { type: 'array', items: { type: 'string' } },
    tests_passing: { type: 'boolean' },
    summary: { type: 'string' },
    blockers: { type: 'array', items: { type: 'string' } },
  },
};
const T22_SCHEMA = T21_SCHEMA;
const T23_SCHEMA = T21_SCHEMA;
const T24_SCHEMA = T21_SCHEMA;
const T25_SCHEMA = T21_SCHEMA;
const REVIEW_SCHEMA = {
  type: 'object',
  required: ['verdict', 'issues', 'summary'],
  properties: {
    verdict: { type: 'string', enum: ['approve', 'approve-with-minor', 'needs-revision', 'blocking'] },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
          file: { type: 'string' },
          summary: { type: 'string' },
          fix: { type: 'string' },
        },
      },
    },
    summary: { type: 'string' },
  },
};

// ===== Phase A: T2.1 — Create loop_helpers.py =====
phase('T2.1 — loop_helpers.py');
const t21 = await agent(
  `Implement Task 2.1 of the Mahavishnu integration plan.

**Plan:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — §5 Phase 2, Task 2.1.

**Existing files to read for context:**
- /Users/les/Projects/mahavishnu/mahavishnu/core/pattern_detection.py (PatternDetector is real, working — loop-until-dry wraps it)
- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/clone_tools.py (clone_detect_ecosystem — T2.2 will modify)

**What to create:** /Users/les/Projects/mahavishnu/mahavishnu/core/loop_helpers.py

**Required contents:**

1. \`async def detect_until_dry(scan_fn: Callable, *, k_empty_rounds: int = 2, max_iterations: int = 5, dedup_key: Callable = lambda r: r["id"], per_iteration_timeout_seconds: float = 60.0) -> tuple[list, dict]\`

   Returns \`(all_findings, run_metadata)\` where:
   - \`all_findings\`: list of unique findings across iterations (deduped by dedup_key)
   - \`run_metadata\`: dict with keys:
     - \`iterations: int\` — number of scan iterations completed
     - \`empty_rounds: int\` — number of consecutive empty rounds at end
     - \`stopped_reason: Literal["converged", "max_iterations", "error"]\`
     - \`error: str | None\` — populated when stopped_reason == "error"
     - \`exception: BaseException | None\` — populated when stopped_reason == "error"

   **Behavior:**
   - Loop up to max_iterations times.
   - Stop when k_empty_rounds consecutive rounds return no new findings → stopped_reason="converged".
   - Stop when max_iterations hit → stopped_reason="max_iterations".
   - If scan_fn raises OR dedup_key raises (e.g., KeyError on missing "id") → capture exception and partial findings, set stopped_reason="error", do NOT propagate.
   - Per-iteration timeout via asyncio.wait_for or asyncio.timeout.

2. Helper: \`_dedupe_by_key(items: list, dedup_key: Callable) -> list\` — returns the items in first-seen order, deduped by dedup_key(item).

3. Module docstring explaining the pattern, the dedup-key contract, and the stopped_reason semantics.

**Style requirements (CLAUDE.md Crackerjack-Compliant Code):**
- from __future__ import annotations first
- Imports sorted stdlib → third-party → first-party
- X | None syntax, list[str] etc.
- Use oneiric.core.logging logger
- logger.exception in except blocks
- Type all parameters and return values

Do NOT write tests in this task — T2.4 handles tests. Do NOT modify clone_tools.py or other tools — T2.2 handles those.`,
  { label: 'T2.1', schema: T21_SCHEMA }
);

log(`T2.1 complete: ${t21.summary}`);

// ===== Phase B: T2.2 + T2.3 parallel =====
phase('T2.2/T2.3 parallel wiring');
const [t22, t23] = await parallel([
  () => agent(
    `Implement Task 2.2 of the Mahavishnu integration plan.

**Plan:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — §5 Phase 2, Task 2.2.

**Files to read first:**
- /Users/les/Projects/mahavishnu/mahavishnu/core/loop_helpers.py (T2.1 output)
- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/clone_tools.py:29-58 (clone_detect_ecosystem)

**What to modify:** /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/clone_tools.py

**Required changes:**

1. In the CloneTools class, update clone_detect_ecosystem to accept new optional parameters:
   - \`detect_until_dry: bool = False\`
   - \`k_empty_rounds: int = 2\`
   - \`max_iterations: int = 5\`

2. When detect_until_dry=True, wrap the (currently stubbed) scan function with detect_until_dry from loop_helpers. The wrapper is testable independently of the stub.

3. Add run_metadata to the response dict: \`{"run_metadata": {"iterations": int, "empty_rounds": int, "stopped_reason": str}}\`

4. Update the @mcp.tool() decorator on register_clone_tools's wrapper accordingly.

**Style:** Same as T1.3.`,
    { label: 'T2.2', schema: T22_SCHEMA }
  ),
  () => agent(
    `Implement Task 2.3 of the Mahavishnu integration plan.

**Plan:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — §5 Phase 2, Task 2.3.

**Step 1:** Find the symbol. Run \`grep -rn "def get_cross_project_patterns" mahavishnu/\` to locate it. Expected in mahavishnu/mcp/tools/*.py or mahavishnu/core/pattern_detection.py. Confirm path with the implementer.

**Step 2:** Read the located file and the T2.1 output (loop_helpers.py).

**What to modify:** the file containing get_cross_project_patterns.

**Required changes:** same as T2.2 — accept detect_until_dry, k_empty_rounds, max_iterations parameters; wrap scan with detect_until_dry when enabled; surface run_metadata in the response.

**Style:** Same as T1.3.`,
    { label: 'T2.3', schema: T23_SCHEMA }
  ),
]);

log(`T2.2: ${t22.summary}`);
log(`T2.3: ${t23.summary}`);

// ===== Phase C: T2.4 tests + T2.5 export =====
phase('T2.4 tests + T2.5 export');
const [t24, t25] = await parallel([
  () => agent(
    `Implement Task 2.4 of the Mahavishnu integration plan — tests.

**Plan:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — §5 Phase 2, Task 2.4 and Exit Criteria.

**Files to read first:**
- /Users/les/Projects/mahavishnu/mahavishnu/core/loop_helpers.py (T2.1)
- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/clone_tools.py (T2.2)

**What to create:** /Users/les/Projects/mahavishnu/tests/unit/test_loop_helpers.py

**Required tests (mirror the plan's Exit Criteria):**
- \`test_detect_until_dry_stops_after_k_empty\` — a mock scanner that returns [1] first round, [] twice — wrapper returns after 3 iterations with stopped_reason == "converged".
- \`test_detect_until_dry_respects_max_iterations\` — a non-converging scanner (always returns new items); wrapper returns after max_iterations with stopped_reason == "max_iterations".
- \`test_detect_until_dry_dedupes_via_dedup_key\` — scanner returns [{id: 1, x: ...}, {id: 1, x: ...}, {id: 2, ...}] across iterations; only 2 unique findings in the result.
- \`test_detect_until_dry_captures_scan_fn_exception\` — scanner raises on iteration 2; wrapper returns partial findings with stopped_reason == "error" and exception populated.
- \`test_detect_until_dry_captures_dedup_key_exception\` — finding without "id" → KeyError in dedup_key; same error path.
- \`test_detect_until_dry_per_iteration_timeout\` — scanner that sleeps 5s with timeout=1s; raises asyncio.TimeoutError → stopped_reason == "error".

**Run:** \`uv run pytest tests/unit/test_loop_helpers.py -v --no-cov\`. All tests must pass.

**Style:** Same as Phase 1 tests.`,
    { label: 'T2.4', schema: T24_SCHEMA }
  ),
  () => agent(
    `Implement Task 2.5 of the Mahavishnu integration plan — export.

**Plan:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — §5 Phase 2, Task 2.5.

**File to read:** /Users/les/Projects/mahavishnu/mahavishnu/core/__init__.py

**What to modify:** Add \`from mahavishnu.core.loop_helpers import detect_until_dry\` (or similar) and re-export as \`loop_helpers\` module-level attribute, OR add to \`__all__\` if it uses that pattern.

Verify the import works: \`uv run python -c "from mahavishnu.core import detect_until_dry; print(detect_until_dry)\"`

Report what you verified or added.`,
    { label: 'T2.5', schema: T25_SCHEMA }
  ),
]);

log(`T2.4: ${t24.summary}`);
log(`T2.5: ${t25.summary}`);

// ===== Phase D: Synthesis review =====
phase('Synthesis review');
const review = await agent(
  `Review the Phase 2 implementation of the Mahavishnu integration plan.

**Plan:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — §5 Phase 2.

**Files to inspect:**
- /Users/les/Projects/mahavishnu/mahavishnu/core/loop_helpers.py
- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/clone_tools.py (T2.2 changes)
- The file containing get_cross_project_patterns (T2.3 changes)
- /Users/les/Projects/mahavishnu/tests/unit/test_loop_helpers.py
- /Users/les/Projects/mahavishnu/mahavishnu/core/__init__.py

**Review dimensions:**

1. **Correctness**: Does detect_until_dry honor k_empty_rounds / max_iterations correctly? Are the error paths (scan_fn raises, dedup_key raises, per-iteration timeout) all encoded as stopped_reason="error"?

2. **Integration**: Are the detect_until_dry parameters (off-by-default) added to clone_detect_ecosystem AND get_cross_project_patterns? Is run_metadata surfaced in both responses?

3. **Tests**: Do all six test_loop_helpers.py tests pass?

4. **Style**: Crackerjack conventions followed? Imports sorted? X | None used?

5. **Export**: Is detect_until_dry importable from mahavishnu.core?

Verdict: approve | approve-with-minor | needs-revision | blocking

Report each finding with severity, file path, summary, fix.`,
  { label: 'review', schema: REVIEW_SCHEMA }
);

log(`Review verdict: ${review.verdict}`);

return { t21, t22, t23, t24, t25, review };