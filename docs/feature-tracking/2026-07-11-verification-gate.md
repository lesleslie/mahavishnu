# Feature: verification-gate

**Owner:** mahavishnu core
**Created:** 2026-07-11
**Last updated:** 2026-07-11
**Repo(s):** /Users/les/Projects/mahavishnu

## State — pick one
- [ ] **built** (code merged, no callers wired)
- [ ] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

## Wiring checklist
- [ ] Entry point registered (CLI command / MCP tool / FastAPI route / handler)
- [ ] Trigger path identified (who calls this, and from where)
- [ ] Returns / state updates land in expected destination
- [ ] End-to-end smoke check documented (one command that proves it works)
- [ ] Observability hook in place (log/metric/trace)
- [ ] Rollback signal defined

## Built (yes/no)
no

## Wired (yes/no)
no

## Trigger path
`mcp__mahavishnu__clone_refactor_group(cluster_id=...)` (line 60 in `clone_tools.py`) and `mcp__mahavishnu__self_improvement_generate(fingerprint=...)` (line 463 in `self_improvement_tools.py`). Verification runs at entry to both methods, before the job-id is generated.

## Integration point
New `mahavishnu/core/verification.py` exporting `RefuterStrategy`, `RefuterVerdict`, `VerificationResult`, and `verify_proposal`. New Dhara prefix `verification/{proposal_id}/`. The MCP response dict gains a `verification` field with the serialized result.

## End-to-end check
`pytest tests/unit/test_verification.py::test_three_refuters_disagree_on_bad_proposal -v` — feeds a known-bad proposal through `verify_proposal` and confirms at least one refuter returns `verdict == "reject"`.

Plus integration: `mahavishnu mcp call clone_refactor_group cluster_id=test-cluster` returns a dict with `"verification": {"consensus": "...", "verdicts": [...]}`.

## Blocker
None — implementation pending Phase 1 of `docs/plans/2026-07-11-ultracode-integration-wiring.md`.

## Next action
Execute Phase 1, Tasks 1.1–1.6 of the source plan. Owner: mahavishnu core. Target: end of week 2026-07-18.

## Related
- Plan: `docs/plans/2026-07-11-ultracode-integration-wiring.md` (Phase 1)
- Parking lot: `docs/feature-tracking/2026-07-11-ultracode-tier2-parking-lot.md`
- ADR M-NEW-5: cross-repo extractions are PROPOSE_APPROVE
- ADR-014: caller-side authorization for pool selection

## Session-Buddy
- Reflection ID: <to be filled>
- Saved at: <ISO timestamp>