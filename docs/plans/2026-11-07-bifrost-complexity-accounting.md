---
status: complete
role: implementation
kind: plan
date: 2026-11-07
last_reviewed: 2026-11-08
superseded_by: null
topic: bifrost-complexity-accounting
title: "Complexity-router accounting — price the classifier, watch the session binding"
requirements:
  - id: REQ-BIFROST-046
    title: "The complexity router's cost is measurable from the gateway's own request log"
    description: "An operator can read, over a stated window, how many requests the router classified, how many of those classifications were served from the session tier store rather than a decision-model call, and how many tokens the decision-model calls consumed. The measurement reads only the gateway's request log and requires no new runtime instrumentation."
  - id: REQ-BIFROST-047
    title: "Each classified request is attributed to the outcome it actually had"
    description: "Every classified request is attributed to exactly one outcome — the rule's intent carried out, the tier's instruction overruled, or the classification paid for and not acted on — determined from the routing engine's own log rather than inferred from counts. A request the attribution cannot be read from is reported as unclassified, never guessed."
  - id: REQ-BIFROST-048
    title: "The accounting is reachable from the operator's command line"
    description: "The report runs as a `mahavishnu bifrost` subcommand, prints a human-readable summary by default and JSON on request, and can exit non-zero when the risk it reports is present, so it can be used as a monitor rather than only read by hand."
---

# Complexity-router accounting — price the classifier, watch the session binding

> **Status: complete** (verified 2026-11-08). Shipped in `7ab4257a`; the
> §9 rule holds. Re-verified live: `mahavishnu bifrost complexity-report
> --hours 24` runs against the live store and reports the classifier's
> spend and the session binding's overruns.

## 1. Outcome

`mahavishnu bifrost complexity-report` prints, for a stated window, what
Bifrost's complexity router cost, what traffic the cheap model actually
served, and how often the session binding overruled the router's tier.

It is the instrument that makes the decision recorded in
`docs/decisions/2026-11-07-bifrost-complexity-router.md` — *keep the router,
price it as observability, watch the risk* — a watched property rather than
an intention.

## 2. Goals

1. Make the classifier's token cost legible per window, so the cost side of
   the trade is a number rather than an estimate.
2. Attribute every classified request to the outcome it actually had, so the
   "saving" and the "risk" are not inferred from the tier alone.
3. Give the operator a command that can be run by hand and wired into a
   monitor.

## 3. Non-Goals

1. **Not** a counterfactual saving measurement. The gateway does not record
   what the other model would have produced, so the report gives the traffic
   that moved, not the tokens saved.
2. **Not** a change to the router's configuration. The rule, the classifier,
   and the session mode stay exactly as they are; this plan only measures.
3. **Not** a replacement for `mahavishnu bifrost verify-gate`, which
   answers a different question (does a worker route through Bifrost at all).

## 4. Current Findings

Measured 2026-11-07 against `~/.config/bifrost/logs.db`, the gateway's own
request log:

1. **The classifier costs tokens.** A decision-model call carries about
   3,500 input tokens, and the input scales with the turn being classified.
   Session mode holds the number of calls at roughly 5% of classified
   requests; without it every request would pay.
2. **The session binding overrides the tier.** Bifrost's
   `session-affinity` engine binds `(session id, requested model)` to the
   provider and model the session was first served, and it runs *after* the
   routing rules. Its own log says so:
   `Session stays on minimax-anthropic/MiniMax-M3.1-Flash for MiniMax-M3;
   routing proposed minimax-anthropic/MiniMax-M3`.
3. **The "SIMPLE discount" is a session-wide downgrade.** The binding
   persists for the session, so one SIMPLE turn rebinds that session's model
   class to the cheap model and every later request in the class is served by
   it — including MEDIUM and COMPLEX turns, where the rules explicitly
   propose keeping the caller's model. Measured: one session's first SIMPLE
   turn was followed by 266 MEDIUM requests that asked for `MiniMax-M3` and
   were served `MiniMax-M3.1-Flash`.

   This is a larger effect than the decision record's rule 3 assumed, and
   it is the reason the attribution has to be per request rather than per
   tier.

## 4.5 Requirements

See the frontmatter. `scripts/audit_requirements.py` validates that each
declared ID is referenced from code — `# req: REQ-BIFROST-046` in
`mahavishnu/bifrost/complexity_report.py`, and
`@pytest.mark.req([...])` in
`tests/unit/test_bifrost_complexity_report.py`.

## 5. Implementation Phases

### Phase 1: the accounting module and the operator command

**Goal:** A windowed, attributable, operator-reachable report.

**Tasks:**

1. `mahavishnu/bifrost/complexity_report.py` — read the log store
   read-only, classify each request, price the decision-model calls.
2. `mahavishnu bifrost complexity-report` — the operator surface.
3. `tests/unit/test_bifrost_complexity_report.py` — pin the attribution,
   the pricing, the malformed-row guard, and the CLI contract.

**Exit criteria:** the command runs against the live store and prints
numbers; the tests pass; the report's own numbers reconcile with a direct
SQL query over the same window.

#### Integration Contract

- **Triggered from:** an operator running
  `mahavishnu bifrost complexity-report [--hours N] [--json]
  [--fail-on-hazard] [--db PATH]`, or a monitor invoking the same command
  with `--fail-on-hazard`.
- **Returns to / updates:** nothing is written. The module opens
  `~/.config/bifrost/logs.db` read-only (`file:...?mode=ro`) and writes
  no state anywhere.
- **Demonstrable by:** `mahavishnu bifrost complexity-report --hours 24`
  prints the tier distribution, the classifier's token cost, the
  cheap-model request count, and the count of requests where the session
  binding overruled the tier. `pytest tests/unit/test_bifrost_complexity_report.py`
  passes.
- **Rollback signal:** the command exits non-zero with `log store missing`,
  or the report shows `classifier tokens` growing faster than the tiered
  request count — which would mean the session tier store stopped
  holding and every request is paying for a classification.
- **Observability added:** the report *is* the observability. It is the
  standing measurement for the decision record's cost side, and
  `--fail-on-hazard` is the alert channel for the risk side.

## 6. Required Code Changes

- [x] `mahavishnu/bifrost/complexity_report.py` — new: the accounting
      module (`REQ-BIFROST-046`, `REQ-BIFROST-047`).
- [x] `mahavishnu/cli/bifrost_cli.py` — new `complexity-report` command
      (`REQ-BIFROST-048`).
- [x] `tests/unit/test_bifrost_complexity_report.py` — new: 9 tests.
- [x] `docs/decisions/2026-11-07-bifrost-complexity-router.md` — the
      measured-behaviour section corrected for the session-wide effect, and
      the status updated to point at the report.
- [x] `config/bifrost/README.md` — the command documented.
- [x] `docs/CLI_REFERENCE.md` — the command listed.

## 7. Validation Matrix

| tool/command | expected outcome | evidence location |
|---|---|---|
| `pytest tests/unit/test_bifrost_complexity_report.py` | 9 passed | test output |
| `mahavishnu bifrost complexity-report --hours 24` | a priced report | operator terminal |
| `sqlite3 ~/.config/bifrost/logs.db "<count query>"` | reconciles with the report's counts | the same window |
| `crackerjack run -v -f` | passes | gate output |
| `python scripts/audit_requirements.py` | no orphans, no phantoms | script output |

## 8. Risks

| risk | likelihood | mitigation |
|---|---|---|
| The report's attribution depends on a log line Bifrost could change | medium | the affinity line is parsed from `routing_engine_logs`; a shape change shows up as rows moving to `unclassified`, which is reported rather than silently mis-attributed |
| A malformed `routing_metadata` breaks the cost query | high | the query filters on `json_valid(routing_metadata)`; a test pins it |
| The report reads the user's real log store during tests | low | the store path is resolved at call time and every test passes an explicit `db_path` or redirects the module constant |
| The report is read once and goes stale | high | it is a command, not a document; the decision record points at it rather than restating the numbers |

## 9. Decision Rule

The report is the instrument; the decision it informs is recorded in the
decision record. This plan is done when the command runs against the live
store, its numbers reconcile with a direct SQL query over the same window,
and the decision record's cost and risk claims are sourced from it rather
than from a one-off snapshot.
