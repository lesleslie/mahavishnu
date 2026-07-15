# Feature: loop-until-dry

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

`mcp__mahavishnu__clone_detect_ecosystem(detect_until_dry=True, ..., max_iterations=5)` (line 29 in `clone_tools.py`) and `mcp__mahavishnu__get_cross_project_patterns(detect_until_dry=True, ..., max_iterations=5)`. Default is `detect_until_dry=False`; opt-in only.

## Integration point

New `mahavishnu/core/loop_helpers.py` exporting `detect_until_dry(scan_fn, k_empty_rounds, max_iterations, dedup_key)`. Wraps `PatternDetector.analyze_tasks` and the underlying scanner for the two MCP tools. The helper is testable independently of the stubbed scan functions.

## End-to-end check

`pytest tests/unit/test_loop_helpers.py::test_detect_until_dry_stops_after_k_empty -v` — a mock scanner that returns `[1]` first round, `[]` twice — wrapper returns after 3 iterations with `stopped_reason == "converged"`.

Plus integration: `mahavishnu mcp call clone_detect_ecosystem detect_until_dry=true max_iterations=3` returns a response with `run_metadata.iterations == 3` and `stopped_reason == "max_iterations"` on a synthetic non-converging scan.

## Blocker

None — implementation pending Phase 2 of `docs/plans/2026-07-11-ultracode-integration-wiring.md`.

## Next action

Execute Phase 2, Tasks 2.1–2.4 of the source plan. Owner: mahavishnu core. Target: end of week 2026-07-25.

## Related

- Plan: `docs/plans/2026-07-11-ultracode-integration-wiring.md` (Phase 2)
- Parking lot: `docs/feature-tracking/2026-07-11-ultracode-tier2-parking-lot.md` (entry 2.4 — adapter race — is conceptually adjacent)
- `mahavishnu/core/pattern_detection.py::PatternDetector.analyze_tasks` (the wrapped implementation)

## Session-Buddy

- Reflection ID: <to be filled>
- Saved at: <ISO timestamp>
