---
status: active
role: canonical
date: 2026-11-05
last_reviewed: 2026-11-05
topic: convergence-control-plane
---

# Decision: Absorb External Agent-Skill Patterns; Do Not Install the Packs

## Context

Four widely-adopted Claude Code skill collections were assessed against this
repository's existing catalogue (424 plugin skills, 39 user skills, 8 project
skills, 166 plugin agents, 62 user agents, 48 project agents):

| Collection | Repo | Size | Licence | Stars |
|---|---|---|---|---|
| Matt Pocock's Skills | `mattpocock/skills` | 39 skills | MIT | 315,299 |
| Trail of Bits Skills | `trailofbits/skills` | ~95 skills / 40 plugins | CC-BY-SA-4.0 | 8,029 |
| Elephant-Goldfish Model | `google/elephant-goldfish-model` | 7 skills | Apache-2.0 | 12,463 |
| Hallmark | `nutlope/hallmark` | 1 skill | MIT | 48,800 |
| Agent Skills | `addyosmani/agent-skills` | 25 skills | MIT | 113,524 |

The question was whether installing any of them would add capability to the
Bodai ecosystem or merely duplicate what this repository already enforces.

## Decision rule

The findings were **not** installed wholesale. Their durable patterns were
absorbed into repository-native gates — code and policy this repository owns,
that survive an upstream release and can be enforced.

Two rules decided each candidate:

1. **Absorb a pattern when this repo lacks the capability** it provides.
2. **Refuse a pattern when this repo already enforces it**, especially when
   this repo's version is stronger because it is specific to this codebase.

A pattern that is "the same idea, better executed here" is duplication, not
value. A pattern that closes a *known* gap — one this repo's own memory
records as a recurring failure — is value.

## Why not install

- **Meta-skill conflict.** `addyosmani/agent-skills` ships `using-agent-skills`,
  which asserts "These behaviors apply at all times, across all skills. They
  are non-negotiable" and "Check for an applicable skill before starting
  work." `superpowers:using-superpowers` already holds that role and is the
  single global skill-selection authority here. Two competing global routers
  make selection nondeterministic.
- **Plugin subagents land at the lowest priority.** Plugin `agents/` is
  priority 5, below project (3) and user (4) scope. Their `code-reviewer`,
  `security-auditor`, `test-engineer` and `web-performance-auditor` personas
  would mostly be shadowed by agents this repo already defines.
- **Catalogue dilution.** Adding 25 descriptions to a catalogue of ~471
  skills degrades routing precision for every existing skill.
- **Genericity is the opposite of what this repo needs.** Where a pattern
  conflicts with a local convention, the local convention is right:
  `mattpocock/skills` `setup-pre-commit` contradicts this repo's documented
  decision that there is no pre-commit hook, and
  `setup-matt-pocock-skills` would scaffold `CONTEXT.md` and ADR directories
  that collide with the existing `docs/decisions/` and `docs/adr/` stores.

## Licence asymmetry

`trailofbits/skills` is **CC-BY-SA-4.0**; the other four are MIT or
Apache-2.0. Share-alike is a real constraint on a repository whose own code
is permissively licensed: copying upstream wording would attach the same
licence to the copy.

**Rule adopted:** for CC-BY-SA-4.0 sources, absorb the *idea*, never the
*text*. The wording in `.claude/skills/security-finding-gate/SKILL.md` is
original to this repository; the upstream skill is cited in the file's
Provenance section.

## Patterns absorbed, and where they landed

| Pattern | Source | Lands in | Status |
|---|---|---|---|
| Doc/implementation drift detection with drift categories | `google/elephant-goldfish-model` (`egm-drift-report`) | `scripts/audit_doc_drift.py` | shipped |
| Fresh-reader acceptance bar for design documents | `google/elephant-goldfish-model` | `docs/plans/2026-11-05-external-skill-pattern-port.md` § 5 Phase 4 | pending |
| Evidence required to dismiss a security finding | `trailofbits/skills` (`fp-check`) | `.claude/skills/security-finding-gate/SKILL.md` | shipped |
| True/false-positive counts in security output | `trailofbits/skills` (`fp-check`) | `.claude/skills/security-finding-gate/SKILL.md` | shipped |
| Two-axis review (Standards + Spec) in parallel sub-agents | `mattpocock/skills` (`code-review`) | Phase 3 | pending |
| `CONSTRAINTS.md` artefact and cheap-first check ordering | `addyosmani/agent-skills` (`constraint-driven-development`) | Phase 5 | pending |
| Change-size heuristic and complexity ceiling | `addyosmani/agent-skills` (`code-review-and-quality`, `code-simplification`) | Phase 5 | pending |
| Mandatory vs advisory deprecation tiers | `addyosmani/agent-skills` (`deprecation-and-migration`) | Phase 5 | pending |
| No fabricated metrics in generated output | `nutlope/hallmark` | Phase 4 | pending |
| Variant analysis across a codebase | `trailofbits/skills` (`variant-analysis`) | Phase 5 | pending |
| Fail-open vs fail-secure default detection | `trailofbits/skills` (`insecure-defaults`) | Phase 5 | pending |

## Consequences

- The doc-drift gate is a **ratchet**, not a wall. Pre-existing drift is
  recorded in `docs/audit-inventory/doc-drift-baseline.json` (79 entries at
  the time of writing) and does not fail the build; new drift does.
- The drift detector is **deterministic** where it can be, and hands the
  rest to a human. Behavioural drift ("Logic Shortcuts", "Architectural
  Divergence") is emitted as a semantic-review worklist rather than guessed
  at, because a guessed verdict is worse than no verdict.
- The security finding gate changes what a reviewer is *allowed to assert*,
  not what tooling is permitted to do. It is instruction, deliberately
  scoped to finding triage, with no mutating surface.

## Rejected outright

- `mattpocock/skills` `setup-pre-commit` — contradicts the no-pre-commit
  decision.
- `mattpocock/skills` `setup-matt-pocock-skills` — collides with the
  established `docs/decisions/` and `docs/adr/` stores.
- `trailofbits/skills` `agentic-actions-auditor` — this repository has no
  GitHub Actions workflows in any core repo, so there is nothing to audit.
- `trailofbits/skills` blockchain scanners, C/Rust fuzzers, DWARF and
  Burp Suite tooling — irrelevant to a Python control-plane fleet.
- Wholesale installs of all five collections.

## References

- `docs/plans/2026-11-05-external-skill-pattern-port.md` — the plan this
  decision implements.
- `docs/feature-tracking/2026-11-05-external-skill-pattern-port.md` —
  feature lifecycle state.
- `docs/decisions/wire-up-contract.md` — the wiring policy.
