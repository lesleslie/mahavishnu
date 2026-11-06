---
name: security-finding-gate
description: >-
  Use when reporting, triaging, or dismissing a security finding — when a
  reviewer proposes a vulnerability, when a finding is being challenged as a
  false positive, or when a security report needs true/false-positive counts.
  Enforces a recorded-evidence standard for every verdict.
---

# Security Finding Gate

## Overview

A security review is only worth as much as the evidence behind each verdict.
A finding dismissed because it "looked unlikely" is a missed vulnerability; a
finding reported because it "matched a vulnerable pattern" is a false alarm
that costs the team credibility and time.

This skill makes both failure modes explicit and forces the evidence to be
recorded before a verdict is allowed.

The rule that carries the whole skill:

> **Pattern similarity alone is insufficient.** Callers and protections
> differ. Two call sites that look identical may have different guards, and
> two that look different may share the same flaw.

## Step 1 — Articulate the claim

Before any finding is confirmed or dismissed, write the claim down in full.
A finding that cannot be stated coherently is not a finding yet — ask for
clarification instead of guessing.

State, explicitly:

1. **What the attacker controls** — the untrusted input, and how it reaches
   the code under review.
2. **Where it enters** — the entry point (HTTP handler, CLI argument, queue
   message, file on disk, environment variable).
3. **What sensitive operation it reaches** — the sink, and what it would let
   the attacker do.
4. **What the bug class is** — injection, BOLA, broken function-level
   authorization, path traversal, insecure deserialization, race, and so on.
5. **The trust boundary being crossed** — and the privilege the attacker needs
   to cross it.
6. **What protections already exist** — validation, allowlists, sandboxing,
   privilege drops, framework defaults.

If step 1 cannot be completed, stop and ask. Do not report a half-formed
claim, and do not dismiss one.

## Step 2 — Choose a verification path

Pick the path deliberately and say which one you used.

| Path | Use when | Depth |
|---|---|---|
| **Standard** | One component, known bug class, straightforward source-to-sink flow | Trace the complete flow once, end to end |
| **Deep** | Ambiguity, multiple components, concurrency, unclear specification, an inconclusive standard review, or an explicit request for full verification | Trace every branch, model the concurrency, and challenge your own conclusion |

An inconclusive standard review is a reason to escalate to deep, not a reason
to stop. Partial analysis is not analysis.

## Step 3 — Verify independently and adversarially

Verify the *specific instance* you are looking at. Do not import a verdict
from a similar bug elsewhere in the codebase.

Then argue against yourself: try to prove the code is safe. If you cannot
produce the evidence in Step 4, the finding stands.

## Step 4 — Evidence required to dismiss a finding

A finding may be dismissed **only** when the dismissal is backed by recorded
evidence. Record as many of these as apply to the case:

- [ ] The coherent claim and its alleged trigger (Step 1, written out)
- [ ] End-to-end data flow from attacker-controlled input to the sensitive
      operation — or proof that no such flow exists
- [ ] Caller-imposed validation or constraints that break the flow
- [ ] Threat-model and privilege assumptions the flow depends on
- [ ] Architectural protections and sandboxing boundaries in the path
- [ ] Proof of attacker control, where the claim depends on it
- [ ] Adversarial review that tests the dismissal rationale itself — ask what
      would have to be true for the finding to be real, then check whether it
      is
- [ ] Bug-class-specific reasoning (for example, why a deserialization path
      is not reachable, or why the authz check is not bypassable)

Severity impressions, code-pattern matching, and "this looks fine" are not
evidence and never justify a dismissal.

## Step 5 — Report with counts

Every security review output must open with the counts:

```
X TRUE POSITIVES, Y FALSE POSITIVES
```

Then list each **confirmed** finding with a brief explanation of the
vulnerability, and each **rejected** finding with a brief justification for
the rejection and a pointer to the evidence that justified it.

A report that omits the counts, or that lists only the survivors, has not
been through this gate.

## Worked example

**Claim.** "The `/admin/users` handler is missing an ownership check — BOLA."

Step 1: attacker controls the `user_id` path segment; entry point is the
route; the sink is the delete of another tenant's user record; the bug class
is BOLA; the boundary crossed is tenant → admin; the existing protection is
the `require_admin` dependency.

Step 2: **Standard** path — one handler, known class, one source-to-sink flow.

Step 3: Adversarial check — *is* `require_admin` sufficient? It verifies the
caller's role, not the tenant boundary, so the flow survives.

Step 4: The dismissal attempt fails (no caller-imposed tenant check exists),
so the finding stands.

Step 5: `1 TRUE POSITIVES, 0 FALSE POSITIVES`.

## Related surfaces

- `.claude/agents/api-security-specialist.md` — OWASP API Top 10 review;
  applies this gate to every finding it produces.
- `.claude/commands/workflows/multi-stage-code-review.md` — the security
  phase runs this gate before findings are aggregated.
- `docs/security/SECURITY_CHECKLIST.md` — the checklist surface this gate
  complements.

## Provenance

The method was adapted from `trailofbits/skills` (`fp-check`,
`differential-review`), which is licensed CC-BY-SA-4.0. The wording here is
original to this repository; the upstream skill is cited rather than copied.
See `docs/decisions/2026-11-05-external-skill-pattern-port.md`.
