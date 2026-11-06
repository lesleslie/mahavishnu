---
status: active
role: implementation
kind: plan
date: 2026-11-05
last_reviewed: 2026-11-05
superseded_by: null
blocks_on: []
topic: convergence-control-plane
title: "Port — External Agent-Skill Patterns into Repo-Native Gates"
---

# Port — External Agent-Skill Patterns into Repo-Native Gates

**Date:** 2026-11-05
**Last reviewed:** 2026-11-05
**Owner:** maintainer
**Scope:** `.claude/agents/`, `.claude/skills/`, `scripts/`, `docs/`, `tests/`
**Purpose:** Absorb the durable patterns from four external agent-skill
collections into this repo's own gates — as code and policy we control —
rather than installing packs we did not write.

---

## 1. Outcome

Two repo-native gates exist, are exercised by CI, and are referenced by the
agents and workflows that need them:

1. **Doc-drift gate** — a deterministic script that compares design
   documents (`docs/specs/`, `docs/plans/`) against the implementation and
   reports references that no longer resolve, with severity derived from the
   document's lifecycle status.
2. **Security finding gate** — a skill that forces every security finding
   through a documented verification path and forbids pattern-similarity
   dismissal.

Success signal: `python scripts/audit_doc_drift.py --json` exits non-zero on
a seeded drift fixture and exits 0 on the live tree; the gate appears in
`tests/integration/test_ci_gates.py`; the finding gate is referenced by at
least one project agent and one workflow.

## 2. Goals

1. Detect **documented-but-not-implemented** drift mechanically, closing the
   gap named by the `docs-audit-documented-not-wired` failure mode.
2. Make **false-positive dismissal** in security review require recorded
   evidence, closing the gap named by
   `resolve-symbol-binding-not-shape` and
   `feedback-mcp-test-must-assert-aggregator-verdict`.
3. Keep every absorbed pattern **attributable** to its upstream source in a
   single decision record.
4. Preserve the repo's own conventions: `docs/plans/TEMPLATE.md` integration
   contracts, `scripts/audit_requirements.py` traceability, and
   `scripts/audit_orphans.py` orphan detection.

## 3. Non-Goals

1. **No wholesale plugin installs.** The four upstream collections were
   assessed in a prior review; 21 of 25 Addy Osmani skills, ~80 of ~95 Trail
   of Bits skills, 8 of 8 Matt Pocock `in-progress` skills, and Hallmark
   itself were judged redundant with existing coverage.
2. **No upstream text copying from CC-BY-SA-4.0 sources.** Trail of Bits is
   share-alike; where their method is absorbed, this repo writes its own
   wording and cites the source in `docs/decisions/`.
3. **No change to `superpowers` behaviour.** `using-superpowers` remains the
   single global skill-selection authority; no second meta-skill is added.
4. **No LLM-based semantic drift judgement in Phase 1.** The script reports
   what it can prove and lists the rest as a review worklist.
5. **No new CI provider.** The repo has no `.github/workflows`; gates run
   through the existing pytest integration surface, not a new pipeline.

## 4. Current Findings

- `scripts/audit_orphans.py` detects *code* with no callers
  (`scripts/audit_orphans.py:1-12`). Nothing detects *documents* whose
  claims have no implementation.
- `scripts/audit_requirements.py` validates `REQ-NNN` traceability between
  plan frontmatter and code markers (`# req:`, `# Implements:`,
  `@pytest.mark.req([...])`).
- `tests/integration/test_ci_gates.py:1-95` is the established entry point
  for audit gates: each gate is invoked as a `subprocess` against the live
  tree and asserted to produce a known exit-code envelope.
- `.claude/agents/security-auditor.md` exists only under
  `.claude/agents/.archive/` and its body is a stub pointing at a
  `../../AGENTS.md#security--compliance#auditing` anchor that does not
  exist in the current 70-line `AGENTS.md` (its only matching heading is
  `## Security & Configuration Tips` at line 66).
- The live project security agents are `.claude/agents/api-security-specialist.md`
  and the user-level `authentication-specialist`. Neither requires evidence
  before a finding is dismissed.
- `docs/specs/` holds 16 design documents; `docs/plans/` holds the plan
  store. Both use the `document-frontmatter-v1` schema with a `status` key
  in `{draft, active, partial, shipped, complete}`.

### Upstream sources absorbed from

| Source | Repo | License | Absorbed for |
|---|---|---|---|
| Google | `google/elephant-goldfish-model` | Apache-2.0 | drift categories; fresh-reader bar |
| Trail of Bits | `trailofbits/skills` | CC-BY-SA-4.0 | finding-verification method (rewritten locally) |
| Matt Pocock | `mattpocock/skills` | MIT | two-axis review (Phase 3) |
| Addy Osmani | `addyosmani/agent-skills` | MIT | constraints/change-size/deprecation (Phase 5) |
| Nutlope | `nutlope/hallmark` | MIT | fabricated-metric rule (Phase 4) |

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-DRIFT-001
    title: "Doc-drift script reports unresolved file references in design docs"
  - id: REQ-DRIFT-002
    title: "Doc-drift script reports unresolved symbol references in design docs"
  - id: REQ-DRIFT-003
    title: "Doc-drift severity is derived from document lifecycle status"
  - id: REQ-DRIFT-004
    title: "Doc-drift script emits JSON and markdown output"
  - id: REQ-DRIFT-005
    title: "Doc-drift gate is exercised by the CI gate integration test"
  - id: REQ-DRIFT-006
    title: "Docs needing semantic review are listed as an explicit worklist"
  - id: REQ-FIND-001
    title: "Security finding dismissal requires recorded evidence"
  - id: REQ-FIND-002
    title: "Security finding output reports true-positive and false-positive counts"
  - id: REQ-FIND-003
    title: "Security finding gate is referenced by a project agent and a workflow"
```

## 5. Implementation Phases

### Phase 1: Deterministic doc-drift detector

**Goal:** a script that resolves the code references inside design documents
and reports the ones that no longer exist.

**Tasks:**
1. `scripts/audit_doc_drift.py` — extract backticked references from
   markdown (excluding fenced code blocks), classify them as path,
   path+symbol, or dotted-module, and resolve each against the tree.
2. Severity mapping from the document's frontmatter `status`:
   `draft` → expected (not drift); `active` / `partial` → warn;
   `shipped` / `complete` → error.
3. `--json` and `--out` output modes; non-zero exit on error-severity drift.
4. Normative-claim extraction (`must` / `shall` / `will` / `should`) whose
   symbols resolve, emitted as the semantic-review worklist.
5. Unit tests over a temp fixture tree.

**Exit criteria:** script passes its unit tests; live tree exits 0.

#### Integration Contract — `scripts/audit_doc_drift.py`
- **Triggered from**: `tests/integration/test_ci_gates.py::TestCIGates::test_audit_doc_drift_gate` (subprocess, live tree), and manually via `python scripts/audit_doc_drift.py --json`.
- **Returns to / updates**: writes `reports/doc_drift.md` when `--out` is passed; otherwise stdout only. No persistent state.
- **Demonstrable by**: `python scripts/audit_doc_drift.py --json` exits 0 on the live tree and exits 1 with `missing_path` entries on the seeded fixture in `tests/unit/test_audit_doc_drift.py`.
- **Rollback signal**: non-zero exit from `test_audit_doc_drift_gate` in the pytest run.
- **Observability added**: structured JSON report with `documents_scanned`, `references_checked`, `errors`, `warnings`, `semantic_review` counters — emitted on every run.

### Phase 2: Security finding gate

**Goal:** a project skill that makes false-positive dismissal in security
review an evidence-bearing act.

**Tasks:**
1. `.claude/skills/security-finding-gate/SKILL.md` — claim articulation,
   verification-path selection, mandatory evidence set, TP/FP count output.
2. Reference the skill from `.claude/agents/api-security-specialist.md`.
3. Reference the skill from the review workflow that owns security passes.
4. Unit test asserting the skill exists, is well-formed, and is referenced.

**Exit criteria:** skill is discoverable in the skill catalog, the
references resolve, and the test passes.

#### Integration Contract — `.claude/skills/security-finding-gate/SKILL.md`
- **Triggered from**: `.claude/agents/api-security-specialist.md` (§ How I work) and the review workflow's security phase; independently loadable by any agent whose task matches the skill description.
- **Returns to / updates**: the reviewer's written finding list — no persistent state.
- **Demonstrable by**: `pytest tests/unit/test_security_finding_gate.py` asserts the skill file, its frontmatter, and both inbound references exist.
- **Rollback signal**: the security-phase reviewer omitting TP/FP counts — detected by the same test asserting the skill body contains the count requirement.
- **Observability added**: none (read-only review guidance); the count requirement makes the reviewer's output self-reporting.

### Phase 3: Two-axis code review

**Goal:** review a diff against repository standards *and* against the
originating specification, as two parallel fresh-context reviewers, reported
side by side without merging or re-ranking.

**Tasks:** add the two-axis method to the code-review surface; pin a
comparison point via `git diff <fixed>...HEAD`; skip the Spec axis when no
spec exists.

**Exit criteria:** a review produces separate `## Standards` and `## Spec`
sections.

#### Integration Contract
- **Triggered from:** the code-review skill/agent invoked on a diff.
- **Returns to / updates:** the reviewer's report.
- **Demonstrable by:** a test asserting the review surface names both axes.
- **Rollback signal:** reviewer output missing an axis.
- **Observability added:** none.

### Phase 4: Fresh-reader bar and design rules

**Goal:** make design documents independently buildable, and stop
fabricated content in generated UI.

**Tasks:** add the fresh-reader acceptance bar to the plan and spec
templates; add the fabricated-metric rule and a pre-emit critique gate to
`frontend-design`.

**Exit criteria:** the templates contain the bar; the design skill contains
the rule.

#### Integration Contract
- **Triggered from:** `docs/plans/TEMPLATE.md` and `docs/specs/` template use; `frontend-design` skill load.
- **Returns to / updates:** the templates and the skill body.
- **Demonstrable by:** a test asserting both strings are present.
- **Rollback signal:** template regression test failure.
- **Observability added:** none.

### Phase 5: Remaining absorbed patterns

**Goal:** fold the remaining absorbed heuristics into existing surfaces —
`CONSTRAINTS.md` artefact and cheap-first check ordering, ~100-line change
size, the complexity-ceiling heuristic, mandatory-vs-advisory deprecation
tiers, variant analysis, and fail-open-vs-fail-secure defaults.

**Tasks:** extend `quality-strategist`, `crackerjack-compliant-code`, the
code-review surface, `docs/decisions/`, `security-auditor` /
`api-security-specialist`, and `authentication-specialist`.

**Exit criteria:** each pattern present in its target surface with a
one-line test.

#### Integration Contract
- **Triggered from:** the respective agent/skill loads.
- **Returns to / updates:** those agent and skill bodies.
- **Demonstrable by:** one test per pattern asserting its presence.
- **Rollback signal:** test failure.
- **Observability added:** none.

## 6. Required Code Changes

- [ ] `scripts/audit_doc_drift.py` (new)
- [ ] `tests/unit/test_audit_doc_drift.py` (new)
- [ ] `tests/integration/test_ci_gates.py` (extend)
- [ ] `.claude/skills/security-finding-gate/SKILL.md` (new)
- [ ] `.claude/agents/api-security-specialist.md` (edit)
- [ ] `tests/unit/test_security_finding_gate.py` (new)
- [ ] `docs/decisions/2026-11-05-external-skill-pattern-port.md` (new)
- [ ] `docs/feature-tracking/2026-11-05-external-skill-pattern-port.md` (new)
- [ ] `docs/plans/PLAN_INDEX.md` (regenerated)

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `python scripts/audit_doc_drift.py --json` | exit 0, zero error-severity drift | stdout JSON |
| `pytest tests/unit/test_audit_doc_drift.py` | pass | pytest output |
| `pytest tests/integration/test_ci_gates.py` | pass | pytest output |
| `pytest tests/unit/test_security_finding_gate.py` | pass | pytest output |
| `python scripts/audit_requirements.py --json` | new REQ ids resolve, no orphans/phantoms | stdout JSON |
| `python scripts/audit_orphans.py` | no new orphans | stdout |
| `python scripts/audit_doc_frontmatter.py` | new docs valid | stdout |
| `crackerjack run -v -f` | merge gate green | crackerjack output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Drift script false-positives on legitimate forward references | high | lifecycle-aware severity; `draft` docs treated as expected; fenced code excluded; placeholders skipped |
| Drift script flags prose words that look like paths | medium | strict candidate regex; require a known code extension or a `/` separator |
| New skill competes with `superpowers` for selection | low | no meta-skill added; the gate skill is scoped to security findings only |
| Absorbing share-alike text into an MIT repo | medium | ToB method is rewritten locally, not copied; decision record cites the source |
| Scope creep beyond the two gates | medium | Phases 3-5 explicitly deferred; only Phase 1-2 land in this pass |

## 9. Decision Rule

This plan is done when: Phase 1 and Phase 2 both satisfy their Integration
Contracts end-to-end, `scripts/audit_requirements.py` reports no orphan or
phantom requirement ids, `scripts/audit_orphans.py` reports no new orphans,
and `docs/decisions/2026-11-05-external-skill-pattern-port.md` records the
provenance of every absorbed pattern. Phases 3-5 may be cut without
invalidating this plan — they are separate improvements, not prerequisites.

## References

- `docs/decisions/wire-up-contract.md` — the policy this plan implements.
- `docs/plans/TEMPLATE.md` — plan template with the required Integration
  Contract block.
- `docs/feature-tracking/TEMPLATE.md` — `{built, wired, adopted}` tracker.
- `docs/schemas/document-frontmatter-v1.md` — frontmatter contract.
- `scripts/audit_orphans.py`, `scripts/audit_requirements.py` — sibling gates.
- `tests/integration/test_ci_gates.py` — the gate entry point.
- Upstream: `google/elephant-goldfish-model` (Apache-2.0),
  `trailofbits/skills` (CC-BY-SA-4.0), `mattpocock/skills` (MIT),
  `addyosmani/agent-skills` (MIT), `nutlope/hallmark` (MIT).
