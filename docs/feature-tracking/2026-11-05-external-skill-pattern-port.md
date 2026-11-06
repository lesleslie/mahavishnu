---
name: external-skill-pattern-port
status: wired
date: 2026-11-05
last_reviewed: 2026-11-05
owner: maintainer
role: canonical
---

# Feature: external-skill-pattern-port

**Owner:** maintainer
**Created:** 2026-11-05
**Last updated:** 2026-11-05
**Repo(s):** /Users/les/Projects/mahavishnu

## State — pick one

- [ ] **built** (code merged, no callers wired)
- [x] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

## Wiring checklist

- [x] Entry point registered (CLI command / MCP tool / FastAPI route / handler)
- [x] Trigger path identified (who calls this, and from where)
- [x] Returns / state updates land in expected destination
- [x] End-to-end smoke check documented (one command that proves it works)
- [x] Observability hook in place (log/metric/trace)
- [x] Rollback signal defined

## Built (yes/no)

yes — `scripts/audit_doc_drift.py`,
`.claude/skills/security-finding-gate/SKILL.md` and their tests are
merged.

## Wired (yes/no)

yes — the drift gate is invoked by
`tests/integration/test_ci_gates.py::TestCIGates::test_audit_doc_drift_gate`
against the live tree, and the security finding gate is referenced by
`.claude/agents/api-security-specialist.md` and
`.claude/commands/workflows/multi-stage-code-review.md`.

## Trigger path

- Drift gate: `tests/integration/test_ci_gates.py::TestCIGates::test_audit_doc_drift_gate`
  invokes `scripts/audit_doc_drift.py --baseline docs/audit-inventory/doc-drift-baseline.json --json`
  as a subprocess with `cwd=REPO_ROOT`. Operators run the same command directly.
- Security finding gate: any agent whose task matches the skill description
  loads `.claude/skills/security-finding-gate/SKILL.md`; the
  `api-security-specialist` agent and the `multi-stage-code-review` workflow
  name it explicitly.

## Integration point

- Drift gate → writes `docs/audit-inventory/doc-drift-baseline.json` (the
  ratchet baseline) and, on demand, a markdown report via `--out`.
- Security finding gate → the reviewer's written finding list. No persistent
  state; the counts requirement makes the reviewer's output self-reporting.

## End-to-end check

```
python scripts/audit_doc_drift.py --baseline docs/audit-inventory/doc-drift-baseline.json --json
```

Exits 0 with `errors: 0` against the current tree (79 baseline entries
tolerated, 1118 references checked). Removing the `--baseline` flag makes it
exit 1 and report the 57 genuine drift findings, which is what proves the
gate is live rather than silently inert.

## Blocker

None for Phases 1 and 2. Phases 3-5 of the plan are not started: the
two-axis code-review method, the fresh-reader design bar, the fabricated-
metric rule, and the remaining security patterns (variant analysis,
fail-open defaults) are recorded in the plan but not yet implemented.

The 57 pre-existing drift findings are baselined rather than fixed. Until
they are cleared, the gate blocks only *new* drift.

## Next action

Implement Phase 3 (two-axis Standards/Spec review) — owner: maintainer,
target 2026-11-12.

## Related

- Plan: `docs/plans/2026-11-05-external-skill-pattern-port.md`
- Decision: `docs/decisions/2026-11-05-external-skill-pattern-port.md`
- Integration contract: `docs/plans/2026-11-05-external-skill-pattern-port.md`
  § 5, Phase 1 and Phase 2
- Audit evidence: `docs/audit-inventory/doc-drift-baseline.json`

## How to save to Session-Buddy

After completing this file, persist a one-line summary to Session-Buddy
for cross-session retrieval by calling the Session-Buddy MCP tool
`store_reflection` with the following shape (replace the `<…>` values
from the fields above):

```python
mcp__session-buddy__store_reflection(
    content=(
        "Feature external-skill-pattern-port: state=wired, "
        "built=yes, wired=yes, "
        "blocker=none for Phases 1-2; Phases 3-5 not started and 57 "
        "pre-existing drift findings are baselined rather than fixed, "
        "next=implement Phase 3 two-axis Standards/Spec review by 2026-11-12"
    ),
    tags=["feature-tracking", "external-skill-pattern-port", "wire-up-state"],
)
```

That call returns a reflection ID; paste that ID into the section below
so the long-form record and the searchable reflection stay linked.

## Session-Buddy

- Reflection ID: `01a1aec6f3f17440868af32b6a8d1801`
- Saved at: 2026-11-06T02:54:08Z
