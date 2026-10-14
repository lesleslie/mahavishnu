// Workflow: Implement Phase 1 of the integration plan.
// Phase 1 = Diverse-Refuter Adversarial Verification Gate.
// Source plan: docs/plans/2026-07-11-ultracode-integration-wiring.md
//
// Task graph:
//   T1.1 (verification.py with all Pydantic models)         [foundation]
//     ├── T1.2 (VerificationStore)                          [parallel]
//     ├── T1.3 (modify clone_tools.py:60-96)                [parallel]
//     └── T1.4 (modify self_improvement_tools.py:463-511)   [parallel]
//   T1.5 (get_verification_result MCP tool)                  [after T1.3]
//   T1.6 (tests + audit_orphans verification)               [after all]

export const meta = {
  name: 'implement-phase-1-verification-gate',
  description: 'Implement the adversarial verification gate from the integration plan',
  phases: [
    { title: 'T1.1 — verification.py' },
    { title: 'T1.2/T1.3/T1.4 parallel' },
    { title: 'T1.5 — get_verification_result + T1.6 tests' },
    { title: 'Synthesis review' },
  ],
};

const T11_SCHEMA = {
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

const T12_SCHEMA = T11_SCHEMA;
const T13_SCHEMA = T11_SCHEMA;
const T14_SCHEMA = T11_SCHEMA;
const T15_SCHEMA = T11_SCHEMA;
const T16_SCHEMA = T11_SCHEMA;
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

// ===== Phase 1: T1.1 — Create verification.py =====
phase('T1.1 — verification.py');
const t11 = await agent(
  `Implement Task 1.1 of the Mahavishnu integration plan.

**Plan to read first:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — read §5 Phase 1 (Diverse-Refuter Adversarial Verification Gate) in full. Specifically Tasks 1.1 and 1.2.

**Existing files to read for context:**
- /Users/les/Projects/mahavishnu/mahavishnu/core/errors.py (around line 662 for RateLimitError precedent — you do NOT need to add a new exception; reuse the existing pattern if relevant)
- /Users/les/Projects/mahishnu/mahavishnu/models/pattern.py (Pydantic BaseModel + Field validators precedent)
- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/clone_tools.py (call sites for verification — clone_refactor_group at lines 60-96)

**What to create:** /Users/les/Projects/mahavishnu/mahavishnu/core/verification.py

**Required contents (per the plan's Tier 1+2 fixes):**

1. Three StrEnums (per type-design review):
   - \`class RefuterErrorKind(StrEnum)\`: TIMEOUT, MALFORMED_RESPONSE, LLM_ERROR, RATE_LIMITED, INTERNAL
   - \`class RefuterVerdictValue(StrEnum)\`: APPROVE, REJECT, ABSTAIN
   - \`class Consensus(StrEnum)\`: APPROVE, REJECT, SPLIT, UNAVAILABLE

2. Pydantic models (frozen, per type-design review — use model_config = ConfigDict(frozen=True)):
   - \`class RefuterStrategy\`: name, prompt_template, temperature (Field ge=0.0 le=2.0), model_hint (str | None), timeout_seconds (Field default=30.0 gt=0)
   - \`class RefuterVerdict\`: strategy_name (str, NOT the whole strategy — prevents prompt_template leak), verdict (RefuterVerdictValue), rationale, concerns (list[str]), latency_seconds, error (RefuterErrorKind | None). Add a \`model_validator(mode="after")\` enforcing: \`error is not None ⟺ verdict == RefuterVerdictValue.ABSTAIN\`
   - \`class Proposal\`: proposal_id, proposal_type (e.g. "clone_refactor"), subject, details (dict[str, Any]). Used as typed input to verify_proposal — replaces bare dict (violates no-Any rule).
   - \`class VerificationResult\`: proposal_id, verdicts (list[RefuterVerdict]), consensus (Consensus), concerns_aggregated (list[str]), persisted (bool), persist_error (str | None)

3. \`DEFAULT_STRATEGIES: tuple[RefuterStrategy, ...]\` — three diverse refuters:
   - "checklist" (temperature 0.2)
   - "devils_advocate" (temperature 0.7)
   - "scope_audit" (temperature 0.3)

4. \`async def verify_proposal(proposal: Proposal, strategies: list[RefuterStrategy] = DEFAULT_STRATEGIES) -> VerificationResult\`

   Failure-mode handling (mandatory):
   - Per-refuter timeout (use the strategy's timeout_seconds). On timeout: verdict=ABSTAIN, error=TIMEOUT, rationale populated.
   - Refuter LLM call failure: verdict=ABSTAIN, error=LLM_ERROR or RATE_LIMITED.
   - Malformed JSON: verdict=ABSTAIN, error=MALFORMED_RESPONSE.
   - ALL refuters fail: consensus=UNAVAILABLE (NOT SPLIT). concerns_aggregated includes "verification infrastructure unavailable".
   - Empty proposal: short-circuit consensus=APPROVE with concern "empty proposal".
   - verify_proposal NEVER raises. All failures are encoded in the result.

5. \`class VerificationStore\`:
   - \`async def persist(result: VerificationResult) -> VerificationResult\` — writes to \`verification/{proposal_id}/\` in Dhara. On Dhara failure: log WARNING, set persisted=False, persist_error=<summary>, dead-letter to \`~/.mahavishnu/verification-dead-letter/{proposal_id}.json\`. Returns the result with persisted/persist_error updated.
   - \`async def get(proposal_id: str) -> VerificationResult | None\`

**Style requirements (per CLAUDE.md Crackerjack-Compliant Code):**
- \`from __future__ import annotations\` as first non-comment line.
- Imports sorted: stdlib → third-party → first-party (\`mahavishnu\`).
- \`X | None\` not \`Optional[X]\`.
- \`list[str]\` not \`List[str]\`.
- No \`Any\` in tool inputs (use the \`Proposal\` model).
- \`logger.exception(...) not logger.error(..., exc_info=True)\` in except blocks.
- Use the Oneiric logger (\`from oneiric.logging import get_logger\`) — not stdlib logging.

**Final step:** Confirm the file is created. Report what you did. Do NOT write tests in this task — T1.6 handles tests. Do NOT modify clone_tools.py or self_improvement_tools.py — T1.3 and T1.4 handle those.`,
  { label: 'T1.1', schema: T11_SCHEMA }
);

log(`T1.1 complete: ${t11.summary}`);

// ===== Phase 2: Parallel T1.2, T1.3, T1.4 =====
phase('T1.2/T1.3/T1.4 parallel');
const [t12, t13, t14] = await parallel([
  () => agent(
    `Implement Task 1.2 of the Mahavishnu integration plan.

**Plan:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — §5 Phase 1, Task 1.2.

**Existing file (T1.1 output):** /Users/les/Projects/mahavishnu/mahavishnu/core/verification.py — read it first; the VerificationStore you create uses VerificationResult.

**What to create:** VerificationStore is ALREADY defined in verification.py (T1.1 task). For T1.2, **no new file is needed**.

**What to verify in T1.2:**
- Confirm VerificationStore.persist writes to Dhara at \`verification/{proposal_id}/\`.
- Confirm dead-letter path is \`~/.mahavishnu/verification-dead-letter/{proposal_id}.json\`.
- Confirm the persisted field propagates correctly through the VerificationResult returned to the caller.
- Confirm a Dhara stub test (in tests/unit/test_verification.py) covers the persisted=False path.

**Action:** Read verification.py. If VerificationStore is missing the dead-letter logic OR the persisted field propagation, add it. Report what you verified or changed.`,
    { label: 'T1.2', schema: T12_SCHEMA }
  ),
  () => agent(
    `Implement Task 1.3 of the Mahavishnu integration plan.

**Plan:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — §5 Phase 1, Task 1.3.

**Files to read first:**
- /Users/les/Projects/mahavishnu/mahavishnu/core/verification.py (the new module — T1.1 output)
- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/clone_tools.py (the file you'll modify; specifically the \`clone_refactor_group\` method at lines 60-96)

**What to modify:** /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/clone_tools.py

**Required changes:**
1. In the CloneTools class, instantiate a VerificationStore (or accept one via dependency injection).
2. In \`clone_refactor_group\`, BEFORE returning the job-id:
   - Construct a \`Proposal\` (proposal_id, proposal_type="clone_refactor", subject=cluster_id, details={...}).
   - Call \`verify_proposal(proposal)\` and \`store.persist(result)\`.
   - Add the persisted VerificationResult as \`"verification"\` field in the returned dict.
   - If \`verification_enabled=True\` in settings AND \`consensus == Consensus.REJECT\`, set \`decision: "blocked_by_verification"\` instead of \`"propose_approve"\`.
3. Add a new method \`get_verification_result(proposal_id: str) -> dict\` that calls \`store.get(proposal_id)\`.

**Style requirements:** Same as T1.1 — see CLAUDE.md Crackerjack-Compliant Code section.

**DO NOT modify self_improvement_tools.py — that's T1.4.**

Report what you modified.`,
    { label: 'T1.3', schema: T13_SCHEMA }
  ),
  () => agent(
    `Implement Task 1.4 of the Mahavishnu integration plan.

**Plan:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — §5 Phase 1, Task 1.4.

**Files to read first:**
- /Users/les/Projects/mahavishnu/mahavishnu/core/verification.py (the new module — T1.1 output)
- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/self_improvement_tools.py (the file you'll modify; specifically \`self_improvement_generate\` at lines 463-511)

**What to modify:** /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/self_improvement_tools.py

**Required changes:**
1. Instantiate a VerificationStore in the SelfImprovementTools class.
2. In \`self_improvement_generate\`, AFTER the threshold check (count >= 3) and BEFORE generating the job-id:
   - Construct a \`Proposal\` (proposal_id derived from fingerprint, proposal_type="self_improvement", subject=pattern_description or fingerprint, details={...}).
   - Call \`verify_proposal(proposal)\` and \`store.persist(result)\`.
   - Add the persisted VerificationResult as \`"verification"\` field in the returned dict.
   - Same blocking-mode logic as T1.3 (gated on \`verification_enabled\` setting and \`consensus == Consensus.REJECT\`).

**Style requirements:** Same as T1.1.

**DO NOT modify clone_tools.py — that's T1.3.**

Report what you modified.`,
    { label: 'T1.4', schema: T14_SCHEMA }
  ),
]);

log(`T1.2: ${t12.summary}`);
log(`T1.3: ${t13.summary}`);
log(`T1.4: ${t14.summary}`);

// ===== Phase 3: T1.5 (get_verification_result MCP tool) + T1.6 (tests) =====
phase('T1.5 + T1.6');
const [t15, t16] = await parallel([
  () => agent(
    `Implement Task 1.5 of the Mahavishnu integration plan.

**Plan:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — §5 Phase 1, Task 1.5.

**Note:** T1.3 should already have added \`get_verification_result\` as a method on CloneTools. Read /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/clone_tools.py to confirm.

**What to do:** Confirm the method exists. If T1.3 didn't add it (T1.3 may have only added it inside CloneTools — we ALSO need it registered as an MCP tool in register_clone_tools), add the @mcp.tool() decorator wrapping the method in register_clone_tools.

**Final state:** the MCP tool \`mcp__mahavishnu__get_verification_result(proposal_id: str)\` is callable from a Claude Code session.

Report what you verified or added.`,
    { label: 'T1.5', schema: T15_SCHEMA }
  ),
  () => agent(
    `Implement Task 1.6 of the Mahavishnu integration plan.

**Plan:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — §5 Phase 1, Tasks 1.6 and the Phase 1 Exit Criteria section.

**Files to read first:**
- /Users/les/Projects/mahavishnu/mahavishnu/core/verification.py (T1.1 output)
- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/clone_tools.py (T1.3 output)
- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/self_improvement_tools.py (T1.4 output)

**What to create:**
1. /Users/les/Projects/mahavishnu/tests/unit/test_verification.py with the following tests:
   - \`test_three_refuters_disagree_on_bad_proposal\` — feeds a known-bad proposal through \`verify_proposal\` and confirms at least one refuter returns \`verdict == ABSTAIN\` or \`REJECT\` (the test mock will return a structured response).
   - \`test_consensus_approve_when_all_pass\` — all three refuters approve; consensus is APPROVE.
   - \`test_consensus_unavailable_when_all_refuters_fail\` — all three refuters raise (simulated outage); consensus is UNAVAILABLE (NOT SPLIT).
   - \`test_model_validator_enforces_error_abstain_biconditional\` — verify the Pydantic validator rejects \`RefuterVerdict(verdict="APPROVE", error=RefuterErrorKind.TIMEOUT)\`.
   - \`test_persisted_false_on_dhara_write_failure\` — Dhara stub raises; result carries persisted=False, persist_error, dead-letter file written.

2. /Users/les/Projects/mahavishnu/tests/unit/test_clone_tools.py — add \`test_clone_refactor_group_runs_verification\` that asserts the \`verification\` field is present in the returned dict and Dhara has a \`verification/{proposal_id}/\` record.

3. /Users/les/Projects/mahavishnu/tests/unit/test_self_improvement_tools.py — add \`test_self_improvement_generate_runs_verification_after_threshold\` (only when count >= 3, otherwise no verification).

4. Run \`python scripts/audit_orphans.py\` and verify zero new orphans for Phase 1 symbols (RefuterStrategy, RefuterVerdict, VerificationResult, Proposal, verify_proposal, VerificationStore).

5. Run \`pytest tests/unit/test_verification.py -v\` and confirm all tests pass.

**Style requirements:** Same as T1.1.

Report test results and the audit_orphans outcome.`,
    { label: 'T1.6', schema: T16_SCHEMA }
  ),
]);

log(`T1.5: ${t15.summary}`);
log(`T1.6: ${t16.summary}`);

// ===== Phase 4: Synthesis review =====
phase('Synthesis review');
const review = await agent(
  `Review the Phase 1 implementation of the Mahavishnu integration plan.

**Plan:** /Users/les/Projects/mahavishnu/docs/plans/2026-07-11-ultracode-integration-wiring.md — §5 Phase 1.

**Files to inspect:**
- /Users/les/Projects/mahavishnu/mahavishnu/core/verification.py
- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/clone_tools.py
- /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/self_improvement_tools.py
- /Users/les/Projects/mahavishnu/tests/unit/test_verification.py
- /Users/les/Projects/mahavishnu/tests/unit/test_clone_tools.py
- /Users/les/Projects/mahavishnu/tests/unit/test_self_improvement_tools.py

**Review dimensions (return findings as structured output):**

1. **Type safety**: Are StrEnums used for cross-boundary values? Are Pydantic models used for validated results? Does the model_validator actually enforce the error-ABSTAIN invariant? Any \`Any\` leaking through?

2. **Failure modes**: Does Consensus.UNAVAILABLE get emitted when all refuters fail (NOT just SPLIT)? Does VerificationResult.persisted propagate to callers? Is there a dead-letter path?

3. **Integration**: Does clone_refactor_group actually call verify_proposal? Does self_improvement_generate? Does get_verification_result work as an MCP tool?

4. **Tests**: Do all five tests in test_verification.py pass? Do the integration tests pass? Are audit_orphans results clean?

5. **Style**: Crackerjack-Compliant Code conventions followed? Imports sorted? \`X | None\` not \`Optional[X]\`?

**Verdict options:**
- \`approve\`: ready to ship
- \`approve-with-minor\`: ship but file follow-ups
- \`needs-revision\`: blocks before merging
- \`blocking\`: critical issues

Report each finding with severity, file path, summary, and suggested fix.`,
  { label: 'review', schema: REVIEW_SCHEMA }
);

log(`Review verdict: ${review.verdict}`);

return { t11, t12, t13, t14, t15, t16, review };