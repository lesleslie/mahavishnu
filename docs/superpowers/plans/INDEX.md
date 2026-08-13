# Bodai Plans Index

This index catalogs all plans under `docs/superpowers/plans/` for the Mahavishnu repo and the wider Bodai ecosystem. Plans are implementation roadmaps for specific features or refactors. Use this index to find existing plans before starting new work.

**Conventions:**
- Filename format: `YYYY-MM-DD-<topic>.md`
- Each plan has a goal, architecture summary, file structure, and bite-sized tasks
- Plans are committed to git and reviewed by multi-agent review before execution

---

## Active Plans (most recent first)

### 2026-08-12

- **[bodai-conformance](./2026-08-12-bodai-conformance.md)** — CI-enforced conformance check that prevents 5 cross-repo drift patterns (documented-but-not-wired, removed-but-referenced, version-stamp-drift, MCP-tool-hallucination, cross-component-port-drift) across the 6 Bodai components. 25 tasks across 3 phases. Phase 1: crackerjack primitives + version_guard for mahavishnu. Phase 2: 4 more rules + adoption in 5 sibling repos. Phase 3: watchdog + permanent cross-layer regression test. Related spec: [`2026-08-12-bodai-ecosystem-consistency-design`](../specs/2026-08-12-bodai-ecosystem-consistency-design.md). Status: approved spec, plan committed with R2-1..7 inline fixes; awaiting execution direction.

### 2026-08-10

- [auto-checkpoint-safety-and-trigger](./2026-08-10-auto-checkpoint-safety-and-trigger.md)
- [auto-checkpoint-implementation-summary](./2026-08-10-auto-checkpoint-implementation-summary.md)
- [m-workflow-outcome](./2026-08-10-m-workflow-outcome.md)
- [m-webhook-durable](./2026-08-10-m-webhook-durable.md)

## Older Plans (chronological)

- 2026-06-22: `adapter-runtime-observability`, `anti-ai-flavor-style-sop`, `bodai-crow-http-server`, `completion-report-schema-v1`, `confidence-ceiling-gate`, and 14 more files
- 2026-06-19: `track1-terminal-gap`, `track2-openhands`, `track3-toad-tui`, `track4-turbovec`, `wave2b-a2a-worker`
- 2026-06-01: `dhara-crackerjack-critical-bug-fixes`
- 2026-05-25: `dhara-serverless-implementation-plan`
- 2026-05-23: `unified-iterm2-applescript-plan`
- 2026-05-22: `terminal-grid-plan`
- 2026-05-16: `llm-routing-plan1-mcp-common`, `llm-routing-plan2-downstream-migration`
- 2026-05-14: `doc-sync-and-channel-phase2`
- 2026-05-08: `hatchet-adapter`
- 2026-05-07: `bodai-phase1-harden-control-plane`, `bodai-phase3-cross-repo-coordination`
- 2026-05-01: `runpod-flash-pool`
- 2026-04-27: `bodai-auth-standardization`
- 2026-04-26: `agent-skill-modernization`, `code-indexing-integration`, `config-consolidation`, `pattern-learning-scaffolding`, `splashstand-oneiric-migration`
- 2026-04-14: `akosha-skills`, `bodai-radar`, `session-archaeologist`

---

## How to Add a Plan

When creating a new plan:

1. **Use the writing-plans skill** for structure (Goal, Architecture, Tech Stack, File Structure, Tasks).
2. **Filename:** `YYYY-MM-DD-<topic>.md` (kebab-case topic).
3. **Save to:** `docs/superpowers/plans/`.
4. **Commit to git** with a clear message.
5. **Add a row to the "Active Plans" section** above with a one-line summary.
6. **Reference the related spec** if any (specs live in `docs/superpowers/specs/`).

## How to Find an Existing Plan

- Search by topic: `grep -rli "<keyword>" docs/superpowers/plans/`
- Search by date: `ls docs/superpowers/plans/ | grep "^YYYY-MM"`
- Search by status: look in the "Active Plans" section above for in-progress work
- For Bodai ecosystem cross-component plans, search for `bodai-` or specific component names (akosha, dhara, session-buddy, etc.)
