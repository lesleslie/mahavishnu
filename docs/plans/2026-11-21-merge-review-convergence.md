---
status: active
role: canonical
kind: plan
date: 2026-11-21
last_reviewed: 2026-11-21
superseded_by:
blocks_on: []
topic: merge-review
title: "Merge Review Convergence — stop paying for reviews the code does not need"
requirements:
  - id: REQ-MERGEREV-006
    title: A quoted verdict template in the reply is not read as the reviewer's verdict
---

# Merge Review Convergence — stop paying for reviews the code does not need

## 1. Outcome

A merge that has already been reviewed does not pay for the review
again, and a review that fails to ARRIVE costs a retry rather than a
verdict.

Concretely: the operator sees the merge pipeline skip stage 2 when the
tree under review has not changed since the last passing review, sees a
re-review after findings are addressed check those findings instead of
re-reading the whole diff, and sees a dispatch that times out or is
rate-limited retried instead of blocking the merge.

**How we will know.** The session-buddy branch `fix/mermaid-jsdom-guard-test`
took **eight** ensemble review rounds to land, on 2026-11-21. Rounds 6
and 7 found **no correctness defect** — the findings were a missing
index row, a wrong docstring, a doc that overstated its guarantee, and
a race that a fresh reviewer caught. The evidence this plan is done:
a branch whose tree has not moved is reviewed **once**, and a dispatch
that fails to return is **retried**, not turned into a verdict.

## 2. Goals

1. A dispatch that reaches a worker but does not finish — a timeout, a
   rate limit, a dropped connection — is retried, not converted into a
   `block` verdict on the code.
2. The ensemble review is skipped when the tree under review and the
   merge base are both unchanged since the last **passing** review.
3. A re-review after findings are addressed checks **those findings**,
   not the whole diff.
4. A running reviewer can be told to produce its verdict before the
   dispatch ceiling, so a slow reviewer does not cost the full budget.

## 3. Non-Goals

1. **Not changing the three-reviewer shape.** The ensemble stays
   `python-pro` + `critical-audit-specialist` + one random draw from
   `AGENT_POOL`. This plan makes the reviews cheaper; it does not make
   them fewer or shallower.
2. **Not making the review optional by default.** `--review none`
   already exists as an explicit operator opt-out and stays that way.
   This plan removes the need for that escape hatch on routine
   re-runs; it does not widen it.
3. **Not changing the gate.** Stage 3 (`crackerjack run -v`) is the
   merge gate and stays it. Nothing here weakens it.
4. **Not touching the reviewer's verdict format.** The verdict block —
   the decision word, then the note — is the contract every parser
   depends on. Its exact shape is **not reproduced anywhere in this
   plan**, on purpose: see §4.6 for why writing it out here makes the
   plan poison its own review.
5. **Not generalising to other dispatch paths.** The changes are scoped
   to the merge-review dispatch.

## 4. Current Findings

All line references are `mahavishnu/core/` at `0.40.1`.

### 4.1 A dispatch that fails to arrive is a verdict on the code

`merge_review_dispatcher.py` defines
`DISPATCH_FAILED_PREFIX = "the dispatch failed: "`. Two places produce a
verdict about a FAILED dispatch:

- **line 803** — no pool envelope came back. This one **does** add the
  prefix.

- **line 806-812** — a pool envelope came back carrying a failure. This
  one does **not**:

  ```python
  failure = _pool_failure_message(reply)
  if failure is not None:
      # Builds a BLOCK verdict whose note is `failure` — and, unlike the
      # branch above, it carries NO DISPATCH_FAILED_PREFIX.
      return ...
  ```

`_is_retryable` (`merge_to_main.py`, before this branch)
decides whether a note is worth another attempt, and it checks exactly
two things:

```python
_RETRYABLE_NOTE_PREFIXES: tuple[str, ...] = ("malformed",)

return note.startswith(_RETRYABLE_NOTE_PREFIXES) or note.startswith(
    DISPATCH_FAILED_PREFIX
)
```

A note of `"worker execute() exceeded timeout of 3600.0s (3607.0s)"`
starts with neither. So the retry loop at `merge_to_main.py`
breaks on the first attempt and the timeout becomes a **block**.

This was measured twice on the same branch, 2026-11-21:

| Round | Reviewer | Verdict | Elapsed |
|---|---|---|---|
| 1 | `critical-audit-specialist` | `block - the pool reported status 'rate_limited'` | **0.4s** |
| 4 | `documentation-review-specialist` | `block - worker execute() exceeded timeout of 3600.0s` | **3607.0s** |

Round 1 burned **0.4 seconds** of review to produce a block, and round 4
burned the **entire budget** to produce one. Neither examined a line of
code. Both were transient pool conditions reported as judgements on the
branch.

### 4.2 The review always runs, whatever the tree

`run_pipeline` (`merge_to_main.py`) runs stage 2 whenever
`review_mode != "none"`. There is no state check. The
`.review-state.json` file IS written — `make_review_state`
(`merge_to_main.py`) records `stages_completed`, `current_stage`
and `pre_rebase_base_sha` — but `run_pipeline` never reads it to decide
where to start. It is read by the sibling-worktree checker
(`merge_to_main.py`) and by the consolidation-gate hold-back marker.

The module docstring's "idempotent and resumeable" therefore describes
the cross-session MARKER, not an actual stage skip. Every invocation
re-reviews from scratch — including the invocation after a stage-3 gate
failure, where the code has not changed at all.

### 4.3 The variance is one random slot

`merge_to_main.py`:

```python
AGENT_POOL: list[str] = [
    "performance-review-specialist",
    "test-coverage-review-specialist",
    "critical-audit-specialist",
    "documentation-review-specialist",
    "qa-strategist",
    "observability-incident-lead",
    "architecture-council",
]

_CODE_QUALITY_AGENT: str = "critical-audit-specialist"
```

Two of the three slots are fixed. The third is `random.choice` from
seven agents. Measured on the same branch and the same diff:

| Round | Third reviewer | Elapsed |
|---|---|---|
| 5 | `architecture-council` | 399.4s |
| 6 | `qa-strategist` | 378.5s |
| 7 | `qa-strategist` | **3277.2s** |

That is a **8.7× spread** on the same work. The review's cost is
dominated by which agent the dice land on, not by the size of the diff.

### 4.4 There is no way to steer a running reviewer

The worker command (`workers/registry.py:223`) is:

```sh
claude -p --verbose --output-format stream-json --permission-mode acceptEdits "$MAHAVISHNU_PROMPT"
```

`-p` is **print mode**: the CLI reads the prompt from argv, runs one
turn, and exits. It does not consume stdin as a conversational turn, so
`tmux send-keys` (`workers/contract/tmux_adapter.py:301`) — exposed to
operators as `mahavishnu_send_input`
(`mcp/tools/worker_contract_tools.py:268`) — types bytes into a pane
nobody reads. The registry comment says this outright: *"`-p` removes
the TUI from the contract entirely."*

The CLI does support the channel that would work:
`--input-format <format>`, documented as *"only works with --print"* —
the SDK's streaming-input mode, where `{"type":"user", ...}` messages
written to stdin while the agent is running arrive as new turns.
**Mahavishnu never uses it**: `--input-format` appears nowhere in the
repo.

The prompt already tells the reviewer about the budget
(`merge_review_dispatcher.py`): *"You have a wall-clock budget and
the dispatch's ceiling is 60 minutes, but do not plan on spending it."*
It is a passive statement. The reviewer can run `date`; nobody asks it
to.

### 4.5 The review prompt is already bounded

`collect_diff_context` (`merge_review_dispatcher.py`) emits a
truncated diffstat and a truncated file list, and
`build_review_prompt` (`:168`) tells the reviewer to *"read only the
files you need to judge, not every changed file."* So the prompt does
not grow with the diff, and a slow reviewer is not a slow PROMPT.

### 4.6 A quoted verdict template is read as a verdict

`parse_verdict` (`merge_to_main.py`) takes the **last** verdict
block in the reply, because the prompt asks the reviewer to put its
verdict last. Its own docstring records the failure this invites: *"an
analysis that quotes a line of code can carry a literal verdict block in
it... the parser took the quote as the verdict: the reviewer had said
`decision: pass`, and the merge read a note that was a fragment of
Python."*

That failure is not hypothetical, and it is not rare. It is what
happened to **this plan's own review**, across three rounds:

- The plan quoted the dispatcher's verdict-building source, so a
  reviewer verifying the plan's claim **quoted that line back**. The
  quote carries a literal verdict block whose decision word is `block`
  and whose note is an uninterpolated `{failure}` — and the parser
  read it as the reviewer's verdict. The merge reported
  `python-pro: block - {failure}`: a block, with a template fragment as
  its reason, from a reviewer that never said `block`.
- Another round reported `block - {DISPATCH_FAILED_PREFIX}{detail}` —
  the same shape, from the other template in the same function.
- A third reported `malformed: unknown decision`, from a reviewer that
  quoted this plan's own description of the verdict contract.

**The plan was the source of the poison.** A reviewer is asked to
verify the plan's line references, so it reads the code the plan points
at — and the code it reads contains the verdict template. The plan
quoting that template made quoting it a natural thing for the reviewer
to do, and the parser had no way to tell a quote from an answer.

Two fixes, and both are needed:

1. **The parser must not read a quote as a verdict.** A candidate
   block whose note is a bare template placeholder — a note that is
   nothing but `{name}` tokens — is not something a reviewer wrote; it
   is a template. Such a block is skipped, and the parser keeps looking
   for the reviewer's own block. The same applies to the **contract**
   quote: the prompt itself spells the decision word as the
   alternatives joined by `|`, so a reviewer that quotes the prompt
   back produces a decision word that is not one of the three — that is
   a quote, not an answer.

   **Those two are the only shapes the parser acts on**, and they share
   one property: a genuine verdict cannot have either. A reviewer's
   note is prose and its decision word is one word. Everything else
   that looks like a verdict is either the answer or a reason to
   refuse — which is the second fix, and the reason for the rule
   below.

2. **The prompt must say that quoting the template is not a verdict.**
   Cheap, and it removes the reason for the quote in the first place.

**And the case the shapes do not cover.** A quoted block whose decision
word is a single valid word and whose note is prose is
indistinguishable from a verdict the reviewer wrote — it survives every
shape rule. The parser cannot tell them apart, so it does not guess:
a reply carrying **more than one** candidate is refused as malformed,
which the retry path turns into another attempt. Without this rule a
quoted `pass` could open the ensemble gate on a verdict nobody wrote —
two passes are enough to proceed, and a reviewer that said
`needs_adjustment` would be overruled by its own quotation.

**And no tie-break, and no rule about the surroundings.** The obvious
refinement — prefer the candidate that stands on its own line, since a
quotation is usually embedded in a line of code — is the same fail-open
wearing a different hat. A quotation of a verdict block also stands on
its own line, and a reviewer that writes its verdict *inside a
sentence* and quotes a block beneath it would have the quote read as
the answer. Position cannot separate those two replies: they are the
same text with the roles reversed.

The same reasoning rules out the OTHER way of telling them apart —
by what surrounds the block. A block inside a quoted literal is
usually a quotation, but a reviewer that wraps its own verdict in
quote marks would be hidden by that rule, and **what a rule hides, a
rule can promote to be the only candidate**. That is how a quoted
`pass` opens the gate, and it is why the parser has no rule about
surroundings at all. The same argument retired the
dispatch-failure prefix as a *skip*: a reviewer's own note could
begin with the same words, and the prefix now tells the operator and
the retry path what the block is instead of hiding it.

**Two consequences that follow from the same principle.**

*Untrusted text is defanged before it is spliced into a verdict
block.* The pool's error text is not ours: it can carry a literal
verdict block, and splicing it raw would give the reply a **second**
candidate — which the parser refuses, dropping the very reason the
failure report exists to carry. So the delimiters are defanged before
the text is spliced.

*A block whose decision word is unknown decides nothing, and poisons
nothing.* A reviewer whose last block is fine has answered, whatever
it quoted earlier — so an unknown decision word earlier in the reply
does not fail the reply. But it is never skipped in favour of an
earlier block either: when the **last** block names a decision the
pipeline does not know, that block is reported, because reporting an
earlier quote as the verdict would hide the reviewer's own answer.

**The rule is now a decision record**, because it reverses one:
`docs/decisions/2026-11-21-verdict-parser-single-candidate.md`. The
clause it supersedes — "the verdict parser reads the last verdict
block rather than the first" — was in
`docs/decisions/2026-11-15-review-capture-window.md`, and a rule
reversal belongs in the durable record, not only in a plan.

**And a rule for this plan's own text:** no document under review may
reproduce the verdict block's shape. That includes the plan, the
decision docs, and the review prompts. The shape is described in prose,
never in a fenced block, and never with the placeholder names the
source uses. **The review prompt is the one place the shape must
still appear** — the reviewer cannot comply with a format it has never
been shown — so the prompt is the reason fix 1 has to exist, not an
exception to fix 1.

### 4.7 The note is cut mid-sentence

`MAX_NOTE_LENGTH` (`merge_to_main.py`) was 500, and the note is
where the finding that justifies the verdict goes — the prompt says so
explicitly. But the reply budget the same prompt declares
(`REVIEW_REPLY_BUDGET_CHARS`, 1,500) covers the **whole** reply: the
verdict block, the note inside it, and whatever analysis precedes it.
So the note had a third of the budget its own finding was supposed to
fit in, and the prompt's own arithmetic was incoherent: it told the
reviewer the note was capped at 500 **and** that the rest of the
budget was "room for the finding that justifies it" — a room the
finding did not get to use, because the finding lives in the note.

The cost was not theoretical. A reviewer's architectural finding — a
real one, about the review state never being written — arrived as its
first 500 characters and a cut, and the operator had to guess the rest.
A finding that cannot be read is a finding that cannot be acted on.

**The fix is to raise the cap, and it is safe to raise it.** The
sanitizer runs first and is unchanged: control characters are
stripped, credential-shaped substrings are masked, whitespace is
collapsed. The cap bounds log volume and nothing else, so a longer
note carries no more injection or secret-leak risk than a short one.
`MAX_NOTE_LENGTH` is now 1,200 — most of the reply budget, leaving
room for the analysis and the block — and the number the reviewer is
told is read from the constant, so the prompt and the cap cannot
drift apart.

## 4.8 Requirements

> **Declared incrementally, one commit at a time.** The
> `requirements:` frontmatter key is authoritative and
> `scripts/audit_requirements.py` exits **1** on an orphan (a
> declaration with no marker in code). So an ID is declared in the same
> commit that adds its `# req:` marker, and not before — the IDs below
> are RESERVED until their commit lands. `REQ-MERGEREV-006` is declared
> now, because that commit carries its marker.
>
> **The frontmatter block is added INCREMENTALLY, one commit at a
> time.** A commit declares exactly the IDs whose `# req:` markers it
> adds — so a phase that lands in two commits declares in two steps,
> and an ID is never declared before its marker exists. Declaring all
> five in the first commit would orphan `REQ-MERGEREV-002` through
> `REQ-MERGEREV-005` — declared, but with no marker — and the audit
> would exit 1 from Phase 1 onwards, which is the opposite of what the
> audit is for:
>
> | Commit | Declares | Marker added in the same commit |
> |---|---|---|
> | Phase 1, tasks 5-6 — **landed** | `REQ-MERGEREV-006` | `# req: REQ-MERGEREV-006` |
> | Phase 1, tasks 1-4 | `REQ-MERGEREV-001` | `# req: REQ-MERGEREV-001` |
> | Phase 2 | `REQ-MERGEREV-002`, `REQ-MERGEREV-003` | one marker per ID |
> | Phase 3 | `REQ-MERGEREV-004` | `# req: REQ-MERGEREV-004` |
> | Phase 4 | `REQ-MERGEREV-005` | `# req: REQ-MERGEREV-005` |

| ID | Title | Phase |
|---|---|---|
| `REQ-MERGEREV-001` | A dispatch that reaches a worker but does not finish is retried, not converted into a block verdict | 1 |
| `REQ-MERGEREV-006` | A quoted verdict template in the reply is not read as the reviewer's verdict | 1 |
| `REQ-MERGEREV-002` | The review state records the tree hash and base SHA that were reviewed | 2 |
| `REQ-MERGEREV-003` | The ensemble review is skipped when the reviewed tree and the merge base are unchanged since the last passing review | 2 |
| `REQ-MERGEREV-004` | A re-review after findings are addressed checks those findings rather than the whole diff | 3 |
| `REQ-MERGEREV-005` | A running reviewer can be told to produce its verdict before the dispatch ceiling | 4 |

## 5. Implementation Phases

### Phase 1: A failed dispatch is a retry, not a verdict

**Goal:** a pool failure reaches the reviewer as a retryable note, so
the merge is not blocked by a condition that has nothing to do with the
code.

**Tasks:**

01. **LANDED.** Add the retryable marker to the pool-failure branch at
    `merge_review_dispatcher.py`, so its note carries the same
    prefix the no-envelope branch uses. The **note text stays
    informative** — the operator still sees *why* the review failed.
    The prefix also does a second job: it says the reply is the
    DISPATCHER's failure report and not a reviewer's answer, so the
    operator sees a failure rather than a reviewer's opinion. It
    **classifies; it does not skip** — the block is read as the
    `block` it is, with the failure in its note, because a rule that
    skips a block can hide a reviewer's own verdict (§4.6). The
    isolation-failure branch (`:696-717`) carries the **permanent**
    sibling of the prefix, so a fail-closed isolation abort is not
    retried, which is what it was before the prefix existed.
02. **LANDED.** Extend `_is_retryable` (`merge_to_main.py`) so the
    two dispatch failures are told apart: a transient one
    (`the dispatch failed: `) is retried, a permanent one
    (`the dispatch failed permanently: `) is not. A pool that refused
    the task's shape will refuse it again, and the isolation a review
    asked for cannot appear on the second attempt; spending a whole
    review cycle to learn the same thing is waste, not diligence. The
    two prefixes differ by more than a word — the permanent one has
    `permanently` where the transient one has a colon — so they are
    distinguishable by prefix alone.
03. Confirm the second attempt still blocks. The retry budget is one
    extra attempt, and a second failure must still block — the gate is
    not weakened, it is made honest about what it is deciding.
04. Decide whether the retry re-draws the generalist. **Recommendation:
    keep the same agent**, so a retry measures the same reviewer rather
    than a different one; a different draw would make the variance
    larger, not smaller.
05. **LANDED. Make `parse_verdict` skip a quoted template (§4.6).** A
    candidate block is a quote, not an answer, when its **note is a bare
    template placeholder** — a note that is nothing but `{name}` tokens
    — or when its **decision word is not one of the three** because it
    is the prompt's alternatives joined by `|`. Those are the only two
    shapes a genuine verdict cannot have, so skipping them cannot hide
    one; everything else is either the answer or a reason to refuse
    (task 7). The decision word in a quoted template is fixed
    (`block`), so a quote reads as a block today: a reviewer that never
    said `block` gates the merge as a block. **The shape is the tell** —
    a reviewer's note is prose and its decision word is one word.
06. **LANDED. Tell the reviewer in the prompt that quoting the template
    is not a verdict** (§4.6, second fix). One sentence in
    `build_review_prompt`, and it removes the reason for the quote.
07. **LANDED.** A reply that carries **more than one** candidate block is
    ambiguous: a quoted block with a single-word decision and a prose
    note is indistinguishable from a verdict the reviewer wrote, and
    reviewers of this repo quote source lines verbatim. Picking one of
    two candidates could open the ensemble gate on a verdict nobody
    wrote, so the parser refuses — a fail-loud `malformed` note, which
    the retry path gives the reviewer another chance to answer
    unambiguously. There is **no tie-break** and **no rule about the
    block's surroundings**: preferring the block that stands on its own
    line is the same fail-open with the roles reversed (a reviewer whose
    verdict is inside a sentence, quoting a block beneath it, would have
    the quote read as the answer), and a rule about the surroundings —
    "a block inside a quoted literal is a quotation" — can hide a
    genuine verdict, and what a rule hides, a rule can promote to be the
    only candidate.
08. **LANDED.** The transport-error path (`merge_review_dispatcher.py`
    and `:959-967`) returned bare prose, which the parser reads as a
    reply with no verdict in it — so the exception was **lost** and the
    operator was shown "malformed". It now carries the dispatch-failure
    prefix, so the reason travels with the failure.
09. **LANDED.** The retry of an **unreadable** reply carries a
    **hint**, keyed by what went wrong. An ambiguous reply gets the
    reviewer asked for the verdict block alone — no analysis, and no
    quotation of the block's shape; a reply naming a decision the
    pipeline does not know gets the three words it accepts. A retry
    that repeats the same prompt gets the same reply, and the merge
    then blocks for a reason nobody could act on.
10. **LANDED.** Untrusted text is **defanged** before it is spliced
    into a verdict block. The pool's error text can carry a literal
    verdict block, and splicing it raw gives the reply a second
    candidate — which the parser refuses, dropping the reason the
    failure report exists to carry.
11. **LANDED.** A block whose decision word is unknown **decides
    nothing and poisons nothing**: a reviewer whose last block is fine
    has answered, whatever it quoted earlier. It is still never skipped
    in favour of an earlier block — when the **last** block names a
    decision the pipeline does not know, it is reported.

**Exit criteria:** a dispatch that returns `rate_limited` or a timeout
produces a retry, and a second failure produces the same block it
produces today. A dispatch failure that will fail again — the pool
refused the task's shape, or the isolation could not be provided — is
**not** retried. A reply whose only verdict-shaped content is a quoted
template — or a quote of the prompt's own contract — is **not** read as
a verdict: it is either the reviewer's own earlier verdict or a
malformed reply, and either way it is not a `block` that nobody said.
A reply carrying two candidate verdicts is refused rather than
guessed at, so no quoted `pass` can open the ensemble gate.

#### Integration Contract

- **Triggered from**: `merge_to_main.run_review` →
  `mahavishnu/core/merge_to_main.py` (the per-agent retry loop),
  reached from `run_pipeline` → `merge_to_main.py`.
- **Returns to / updates**: the verdict list returned by
  `run_review`'s per-reviewer closure (`merge_to_main.py`), consumed by
  `aggregate_verdicts` (`merge_to_main.py`).
- **Demonstrable by**:
  `pytest tests/unit/core/test_merge_to_main_gaps.py::TestDispatcher::test_the_retry_belongs_to_one_reviewer_not_to_the_dispatch`
  — a reviewer whose first reply cannot be read is dispatched twice and
  the other two reviewers once each;
  `pytest tests/unit/core/test_merge_to_main_gaps.py::TestDispatcher::test_dispatch_failure_returns_a_block_with_the_reason`
  — an unreachable pool blocks **and keeps the reason**;
  `pytest tests/unit/core/test_merge_to_main_verdict_quotes.py` — the
  quote shapes and the ambiguity rule; and
  `pytest tests/unit/test_merge_review_dispatcher.py::TestTheDispatchFailureKeepsItsReason`
  — a transport error is retried, a refused task shape is not.
- **Rollback signal**: the log line
  `[merge_to_main] reviewer '<agent>' returned an unreadable verdict (<note>); retrying` stops appearing while review failures persist —
  the retry path is bypassed.
- **Observability added**: the existing stderr line gains the failure
  reason, so the dev-log entry distinguishes "the reviewer disagreed"
  from "the reviewer never arrived".

### Phase 2: The review is bound to the tree it judged

**Goal:** a re-run of the pipeline on an unchanged tree does not pay
for the review again.

**Tasks:**

1. Extend `make_review_state` (`merge_to_main.py`) to record the
   **tree hash** reviewed (`git rev-parse <branch>^{tree}`) and the base
   SHA, alongside the existing `stages_completed` / `current_stage`.
   The tree hash, not the branch name: a review is a judgement about
   content, and the branch can be renamed without the content moving.
2. **Wire the write call site — this is the load-bearing step.**
   `write_review_state` (`merge_to_main.py`) has **no production
   caller**: the only callers are `tests/unit/core/test_merge_to_main.py`
   and `tests/unit/hooks/test_agent_merge_on_end.py`. `make_review_state`
   (`:109`) has **no caller at all**, not even a test. So the state file
   this phase reads is never written, and a "reuse" branch would find no
   state and re-review every time — the skip would be unreachable code
   behind a function nobody invokes. `run_pipeline` must call
   `write_review_state(worktree_root, make_review_state(...))` once
   stage 2 completes, carrying the tree hash, the base SHA, the
   verdict and the findings. **Extending a function nobody calls
   changes nothing**: the mechanism only exists once the write happens,
   and the tests must prove the file appears on disk after a run.
3. On a re-run, compare the current tree hash and base SHA against the
   recorded ones. **Skip stage 2 only when BOTH match** and the last
   recorded verdict was a pass. A `needs_adjustment` verdict is not a
   pass — the findings are still open.
4. Make the skip visible: a line saying the review was reused, with the
   tree hash it was bound to. A silent skip is indistinguishable from a
   broken pipeline.
5. Do **not** let the skip survive a base move. The base SHA is part of
   the key because the diff is `base...branch`: the same tree against a
   different base is a different review.

**Exit criteria:** two consecutive pipeline runs on an unchanged branch
perform one review, and the skip is invalidated by **each** of the
three conditions **separately**:

| # | Invalidation condition | Why it must invalidate |
|---|---|---|
| 1 | a tracked file changed | the tree hash moves, so the content judged is no longer the content under review |
| 2 | the base moved | the review is of `base...branch`; the same tree against a different base is a different review |
| 3 | the last recorded verdict was not a pass (`needs_adjustment` or `block`) | the findings are still open, so there is nothing to reuse |

Each condition is a **separate test**. "Changing any tracked file
invalidates the skip" is condition 1, not the whole of them; a test
that only covers condition 1 would leave a skip that fires on an
unresolved `needs_adjustment` — exactly the review that was supposed to
be re-run.

#### Integration Contract

- **Triggered from**: `merge_to_main.run_pipeline`
  (`merge_to_main.py`), at the point where it currently always
  enters stage 2.
- **Returns to / updates**:
  `docs/plans/PLAN_INDEX.md`-adjacent `.review-state.json` at the
  worktree root — written by `write_review_state`
  (`merge_to_main.py`), read by `read_review_state`
  (`merge_to_main.py`).
- **Demonstrable by**:
  `pytest tests/unit/core/test_merge_to_main.py -k review_state` — four
  cases, one per row of the exit-criteria table above: the **reuse**
  case (unchanged tree, unchanged base, last verdict a pass → one
  dispatch), and the three **invalidation** cases (tracked file changed
  → two dispatches; base moved → two dispatches; last verdict
  `needs_adjustment` → two dispatches). The three invalidation cases
  are what stop a needed review from being silently skipped.
- **Rollback signal**: the stderr line
  `[merge_to_main] reusing the review of tree <hash>` appears for a
  tree that has changed — the skip is keyed too loosely.
- **Observability added**: the dev-log entry gains the reviewed tree
  hash, so a merge record says WHICH content was reviewed.

### Phase 3: A re-review answers the findings it is answering

**Goal:** after findings are addressed, the next review checks those
findings rather than re-reading the whole diff.

**Tasks:**

1. Persist the findings of a `needs_adjustment` verdict — the note
   text, and the file/line references it carries — into
   `.review-state.json`.
2. When the next review runs and finds open findings in the state,
   build the prompt so it carries those findings as the PRIMARY
   question, with the full diff available as secondary context. The
   reviewer's job becomes *"are these addressed?"* rather than *"find
   everything wrong with this branch"*.
3. Keep the aggregate rule unchanged: any `block` still blocks, two
   passes still proceed. A focused review is not a weaker gate — it is
   the same gate asked a narrower question.
4. **Guard against a narrowed review becoming a blind one.** A focused
   re-review must still see the diff, and the prompt must say plainly
   that a reviewer who sees a NEW problem must still report it. The
   findings are the focus, not the boundary.
5. **Scope the re-review to the reviewers whose findings are open.** A
   focused re-review answers the findings of the reviewers that raised
   them, so it dispatches those reviewers rather than the full
   ensemble. This is what makes the saving measurable: the dispatch
   count drops from three to one for a single-reviewer re-review. A
   re-review whose findings came from the whole ensemble still
   dispatches the whole ensemble.
6. **Make the aggregate rule scale with the dispatch count — this
   pairs with task 5 and is not optional.** `aggregate_verdicts`
   (`merge_to_main.py`) proceeds on `pass_count >= 2`, a threshold
   written for a three-reviewer ensemble. A focused re-review that
   dispatches ONE reviewer can never reach two passes, so a focused
   re-review that every dispatched reviewer **passed** aggregates to
   `iterate` — and the merge blocks on a review that found nothing
   wrong. Scoping the dispatch without changing the aggregate makes
   Phase 3 strictly worse than doing nothing.
   The rule therefore becomes relative to the reviewers actually
   dispatched: any `block` still blocks; **all** dispatched reviewers
   passing proceeds; anything else iterates. On the full three-reviewer
   ensemble this is *not* the existing rule — two passes out of three
   still proceed there — so the full-review path keeps its own
   threshold and only the focused path uses the relative one. The
   focused review is a complete gate over its (smaller) scope, not a
   weaker one: every reviewer it dispatched must pass.

**Exit criteria:**

- **A new problem introduced by the fix is still caught.** Tested
  BEHAVIOURALLY, not on the prompt's shape: a fixture whose branch
  carries a defect **outside** the focused findings must still produce
  a verdict that reports it. Asserting that the prompt *carries* the
  findings is not this criterion — a prompt can carry the findings and
  still let a new defect through, and a shape assertion cannot tell
  those two cases apart.
- **The re-review costs measurably less.** The proxy is the
  **reviewer-dispatch count**, which is deterministic and testable: a
  re-review of one reviewer's findings dispatches **one** reviewer
  where a first review dispatches three. The dev-log entry records the
  dispatch count and the wall-clock of each review, so wall-clock is
  an **observation**, not the criterion — a wall-clock difference on
  its own is too noisy to gate on, because the same reviewer can run
  three times slower on a cold cache.
- **A focused re-review that passes actually proceeds.** A focused
  review of one reviewer's findings, where that reviewer returned
  `pass`, aggregates to **proceed** — not `iterate`. This is the
  criterion that catches the aggregate-threshold defect: with the
  existing `pass_count >= 2` rule, a one-reviewer focused review can
  never reach two passes, so it blocks the merge on a review that
  found nothing wrong. The focused review must be a complete gate over
  the reviewers it dispatched: all of them pass → proceed; any of them
  blocks → block; anything else → iterate.

#### Integration Contract

- **Triggered from**: `merge_review_dispatcher.build_review_prompt`
  (`merge_review_dispatcher.py`), called from
  `merge_to_main.py`.
- **Returns to / updates**: the prompt handed to
  `run_review` (`merge_to_main.py`), and the findings recorded in
  `.review-state.json` alongside the tree hash from Phase 2.
- **Demonstrable by**:
  `pytest tests/unit/core/test_merge_to_main.py -k focused_review` — two
  cases: one asserting the prompt carries the previous findings (the
  **shape**), and one asserting that a fixture reviewer still reports a
  defect **outside** those findings (the **behaviour**). The behavioural
  case is the criterion; the shape case is a cheap precondition.
- **Rollback signal**: the stderr line reporting a re-review no longer
  names the findings it is answering — the focus was dropped.
- **Observability added**: the dev-log entry records how many findings
  the re-review was scoped to.

### Phase 4: The reviewer can be steered before the ceiling

**Goal:** a reviewer that is going slowly is told to produce its verdict
before the dispatch ceiling, instead of being cut off by it.

**Tasks:**

1. Launch the review worker with `--input-format stream-json` and a
   **FIFO** as stdin, so the dispatch can write a user turn into the
   reviewer's input stream while it runs. The reviewer's stdin is
   currently the tmux pane's tty; a FIFO is what makes it writable
   from outside the pane.
2. At `REVIEW_DISPATCH_TIMEOUT` minus a margin (recommended: 18
   minutes, so the reviewer has time to finish inside the ceiling),
   write a steering message — a `{"type": "user", ...}` turn whose
   content asks the reviewer to stop reading and produce its verdict
   with what it has.
3. Write the steering turn into the FIFO **once**, and make the
   reviewer aware of the deadline in the ORIGINAL prompt too. The
   steering message is a backstop; the prompt is the primary channel,
   because a prompt the reviewer reads at the start costs nothing.
4. Extend `build_review_prompt` to say: *"run `date +%s` now and keep
   the result; if more than 40 minutes have passed by the time you
   finish reading, stop reading and write your verdict with what you
   have."* The reviewer can observe the clock itself — it already can
   run shell commands, and `date` needs no new plumbing.
5. Note the constraint: a reply cut off by the ceiling has **no
   verdict**, so the steering turn has to arrive early enough for the
   reviewer to finish writing one. A SIGINT-style interrupt is not a
   substitute — it produces the same unreadable reply the timeout does.

**Exit criteria:** a reviewer that would have overrun the ceiling
produces a readable verdict instead of a timeout, and a reviewer that
finishes early is unaffected.

#### Integration Contract

- **Triggered from**: `merge_review_dispatcher._default_dispatcher`
  (`merge_to_main.py`) → the pool dispatch, with the steering
  timer owned by `merge_review_dispatcher.py`
  (`timeout: float = REVIEW_DISPATCH_TIMEOUT`).
- **Returns to / updates**: the reviewer's stdin (the FIFO), and the
  captured pane the verdict is parsed from
  (`workers/contract/tmux_adapter.py:capture_pane`).
- **Demonstrable by**:
  `pytest tests/unit/test_merge_review_dispatcher.py -k steer` — a
  case asserting a steering turn is written to the FIFO before the
  deadline.
- **Rollback signal**: the steering write fails or the reviewer's reply
  arrives with no verdict where it previously had one — the steering
  is interfering with a reply that would have completed.
- **Observability added**: a stderr line naming the reviewer and the
  time the steering turn was written.

## 6. Required Code Changes

```text
mahavishnu/core/merge_review_dispatcher.py
  [x]     add the retryable marker to the pool-failure verdict
  [x]     the isolation-failure verdict carries the PERMANENT marker (fail-closed, not retried)
  [x]     the transport-error path carries the marker, so the reason is not lost
  [x]     the sync wrapper's transport error carries the marker too
  [x]     _dispatch_failure_prefix: a refused task shape is permanent, the rest transient
  [x]     build_review_prompt: say that quoting the verdict shape is not a verdict
  [ ]     build_review_prompt: carry open findings; state the clock contract
  [ ]     own the steering timer

mahavishnu/core/merge_to_main.py
  [x]     DISPATCH_FAILED_PREFIX lives here — it is a PARSER contract, not a dispatcher's
  [x]     DISPATCH_FAILED_PERMANENT_PREFIX: the failure that will fail again
  [x]     parse_verdict: skip a block whose note is a bare template placeholder
  [x]     parse_verdict: skip a block whose decision word is the contract quote
  [x]     parse_verdict: REFUSE a reply carrying more than one candidate — with NO tie-break
  [x]     parse_verdict: NO rule about the block's surroundings (a rule that hides can promote)
  [x]     parse_verdict: an unknown decision word decides nothing, and poisons nothing
  [x]     merge_review_dispatcher: defang the verdict delimiters in spliced untrusted text
  [x]     run_review: the retry hint covers BOTH unreadable replies
  [x]     run_review: the retry of an ambiguous reply carries a hint
  [x]     MAX_NOTE_LENGTH: 500 -> 1,200, so a finding is not cut mid-sentence
  [x]     _is_retryable: recognise the dispatch-failure note, and tell transient from permanent
  [ ]     make_review_state: record the reviewed tree hash and base SHA
  [ ]     make_review_state: also record the open findings and their reviewers
  [ ]     write_review_state: CALL IT — run_pipeline writes the state after stage 2
  [ ]     retry loop: keep the same agent across attempts
  [ ]     aggregate_verdicts: the threshold scales with the dispatch count
  [ ]     run_pipeline: skip stage 2 when the tree and base are unchanged
  [ ]     run_pipeline: dispatch only the reviewers whose findings are open

mahavishnu/workers/registry.py
  [ ]     worker command: add --input-format stream-json, stdin a FIFO

mahavishnu/workers/contract/tmux_adapter.py
  [ ] new   write a steering turn into the worker's input FIFO

tests/unit/core/test_merge_to_main.py
  [ ] retry-on-dispatch-failure, review-state round trip, focused re-review

tests/unit/core/test_merge_to_main_verdict_quotes.py
  [x] new   a quoted template and a quoted contract are not the reviewer's verdict
  [x] new   an ambiguous reply is refused, and the permanent failure is not retried

tests/unit/core/test_merge_to_main_gaps.py
  [x] new   a dispatch failure blocks AND keeps the reason

tests/unit/test_merge_review_dispatcher.py
  [x] new   a transport error is retried; a refused task shape is not
  [ ]       steering turn written before the deadline
```

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `pytest tests/unit/core/test_merge_to_main.py` | pass | CI log |
| `pytest tests/unit/test_merge_review_dispatcher.py` | pass | CI log |
| `python scripts/audit_requirements.py` | exit 0 — no orphans, no phantoms | CI log |
| `python scripts/audit_orphans.py` | no new orphans | CI log |
| `crackerjack run -v` | pass | dev-log entry |
| Two pipeline runs on an unchanged branch, last verdict a pass | **one** dispatch, second says "reusing the review of tree \<hash>" | stderr |
| Two pipeline runs with a **tracked file changed** between them | **two** dispatches — the skip is invalidated | stderr |
| Two pipeline runs with the **base moved** between them | **two** dispatches — the skip is invalidated | stderr |
| Two pipeline runs where the last verdict was **`needs_adjustment`** | **two** dispatches — the skip is invalidated | stderr |
| A focused re-review whose fixture carries a defect **outside** the focused findings | the verdict **reports the new defect** (behavioural, not prompt shape) | CI log |
| A focused re-review of **one** reviewer's findings | **one** dispatch, against the three of a first review | dev-log entry |
| A focused re-review of **one** reviewer whose verdict is `pass` | the merge **proceeds** — not `iterate` (the aggregate threshold scales with the dispatch count) | CI log |
| A focused re-review of one reviewer whose verdict is `block` | the merge **blocks** | CI log |
| A dispatch returning `rate_limited` | two dispatches, then the same block as today | stderr |
| A dispatch failing on the **transport** (the server unreachable) | the **reason** reaches the operator, and the review is retried once | stderr |
| A pool that **refused the task's shape** | **one** dispatch — the failure is permanent, and a second attempt would be refused the same way | stderr |
| An isolation abort (the pool could not provide a worktree) | **one** dispatch — fail-closed, and not retried | stderr |
| A reply whose only verdict-shaped content is a **quoted template** | **not** read as a verdict — the reviewer's own earlier verdict, or a malformed retryable note | CI log |
| A reply quoting the prompt's own contract (decision word = the alternatives joined by `|`) | **not** read as a verdict | CI log |
| A reply quoting a **verdict block inside a quoted literal** | refused as malformed and retried — a rule about the surroundings can hide the real verdict, so there is none | CI log |
| A reply carrying **two** candidate verdict blocks on their own lines | refused as malformed and retried — **no** quoted `pass` can open the ensemble gate | CI log |
| A reply whose verdict is **inside a sentence** and which quotes a block beneath it | refused as malformed and retried — the quote is not read as the answer | CI log |
| The retry of an **ambiguous** reply | carries a hint — the reviewer is asked for the block alone, so the second answer is the one that is read | CI log |
| The retry of a reply naming an **unknown decision** | carries a hint — the reviewer is told the three words the pipeline accepts | CI log |
| A pool error whose text carries a **verdict block** | the delimiters are defanged, so the reason survives and the reply has no second candidate | CI log |
| A reply whose **last** block is fine and whose **earlier** block names an unknown decision | the last block is read — an earlier quote does not poison the answer | CI log |
| A reviewer told to wrap up at T-18min | a verdict arrives before the ceiling | captured pane |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The tree-hash skip suppresses a review that was actually needed | low | The key includes the base SHA; any tracked change moves the tree hash; the skip is logged with the hash it was bound to |
| The review state is never written, so the skip never fires and the plan changes nothing | **was high** | Phase 2 task 2 makes the write call site explicit and load-bearing, with a test that the file appears on disk after a run; `make_review_state` and `write_review_state` are dead code today |
| The scoped re-review blocks every merge because the aggregate threshold still wants two passes | **was high** | Phase 3 task 6 makes the threshold scale with the dispatch count, and the exit criteria require a focused review that passed to *proceed* |
| A focused re-review misses a problem introduced by the fix | **medium** | The prompt keeps the full diff available and says plainly that a new problem must still be reported; Phase 3's exit criteria require catching one |
| The steering turn corrupts a reply that would have completed | low | The steering is written once, early; a reply that arrives with no verdict where one previously existed is the rollback signal, and the steering is the only new input |
| The retry doubles the cost of a genuinely broken review | low | The retry budget stays at one extra attempt; a second failure still blocks |
| The FIFO stdin changes worker behaviour for non-review dispatches | medium | Scope the change to the review dispatch's worker options; the shared registry command is only touched if the flag is proven safe there |
| The audit fails on the reserved requirement IDs | low | The frontmatter `requirements:` block is added **per phase** — each phase declares only the IDs whose `# req:` markers it adds in the same commit. Declaring all five up front orphans four of them and the audit exits 1 from Phase 1 |

## 9. Decision Rule

**This plan is done enough when all four of these hold:**

1. A dispatch that fails to return is retried, and a second failure
   still blocks. A quoted template — or a quote of the prompt's own
   contract — is not read as a verdict.
2. An unchanged tree is reviewed once, and the skip is visible in the
   log with the tree hash it was bound to.
3. A re-review after findings are addressed checks those findings, still
   catches a problem the fix introduced (behaviourally — a fixture
   defect outside the findings is still reported — not by asserting the
   prompt's shape), and costs measurably less, measured by the
   reviewer-dispatch count rather than by wall-clock.
4. A reviewer that would overrun the ceiling produces a verdict instead
   of a timeout.

**If scope pressure forces a cut, cut in this order:** Phase 1 first
(it is a small change that removes a whole class of false blocks),
then Phase 2 (the largest saving per line), then Phase 3, then
Phase 4 (the most invasive — it changes how the worker is launched).
**Do not cut Phase 1.** It is the smallest change in the plan and the
one that stops transient pool conditions from being reported as
judgements on code.

## 10. Review History

The first ensemble review of this plan raised three findings **against
the plan itself**. All three are addressed above, and they are listed
here so a later review does not re-raise them:

| Finding | Addressed in |
|---|---|
| Phase 2's tree-hash skip was tested only for *reuse*; its three invalidation conditions — tracked file changed, base moved, last verdict not a pass — had no test, so a needed review could be silently skipped | §5 Phase 2 — the exit-criteria table and the Integration Contract now name all four cases, three of them invalidations |
| Phase 3 asserted the prompt's **shape** rather than its behavioural criterion ("a new problem is still caught"), and "costs measurably less" had no proxy | §5 Phase 3 — the exit criteria now carry a behavioural test, and task 5 supplies the proxy: the reviewer-dispatch count |
| Declaring all five REQ IDs in Phase 1 orphans `REQ-MERGEREV-002` through `-005`, and `audit_requirements.py` exits 1 — contradicting the Validation Matrix | §4.8 — the declaration is now per phase, with the table of which commit declares which IDs |
| **Nothing writes `.review-state.json`** — `write_review_state` has no production caller and `make_review_state` is dead code, so Phase 2 and Phase 3 extend a path that never runs | §5 Phase 2 task 2 — the write call site is now an explicit, load-bearing task, with a test that the file appears on disk after a run |
| **Phase 3's scoped dispatch breaks the aggregate rule** — `aggregate_verdicts` proceeds on `pass_count >= 2`, so a one-reviewer focused re-review that passed aggregates to `iterate` and blocks the merge | §5 Phase 3 task 6 — the threshold scales with the dispatch count; the full ensemble keeps its own rule |
| **A reviewer quoting the dispatcher's verdict template was read as a `block`** — three rounds of this plan's review reported blocks whose notes were uninterpolated template fragments, from reviewers that never said `block`. The plan's own quoted source caused it | §4.6 — the parser skips a quoted template, the prompt says a quote is not a verdict, and this plan no longer reproduces the verdict block's shape anywhere |
| **The note was cut mid-sentence** — a 500-character cap against a 1,500-character reply budget, so a real architectural finding arrived as its first half and a cut | §4.7 — the cap is now 1,200, most of the reply budget, and the prompt's arithmetic finally agrees with itself |

Round 5, with the parser fix in the branch, produced the first real
verdicts this plan has had — which is the diagnosis confirming itself.
Its findings, and what each turned into:

| Finding | Answered |
|---|---|
| Raising the cap broke a test that hardcoded 500 | `tests/unit/test_merge_review_verdict_note.py` now asserts against the constant |
| The quote rule missed the **isolation** template — its note is prose, so a quote of it still read as a block | every synthesised failure verdict now carries `DISPATCH_FAILED_PREFIX`, so a quote of any of them is recognisable |
| The placeholder rule also swallowed the **dispatcher's own** failure verdict, losing the pool's error text | same marker: a note carrying it is the dispatcher's report, not the reviewer's answer, and its text is kept |
| `PLAN_INDEX` counts moved +3 for the store against +2 for the matrix | **both are the generator's output** — compared against a regenerated main they move +1 and +1. The mismatch was main's *committed* index being stale by two entries |
| The cap's comment claimed the cap "bounds log volume and nothing else" | reworded: the cap IS the log-volume bound; what it does not do is sanitise |

Round 6 reviewed the parser fix in the branch. Its findings were
mostly about the fix's own edges, and one of them was a fail-open:

| Finding | Answered |
|---|---|
| **A quoted block with a single-word decision and a prose note was still read as the verdict** — the shape rules do not cover it, and the parser takes the LAST block, so a quoted `pass` after the reviewer's own `needs_adjustment` opened the ensemble gate on a verdict nobody wrote | §4.6 — a reply with more than one candidate is refused as malformed and retried. (This row was first answered with a tie-break on position; the commit security review found that the tie-break was the same fail-open reversed, and it was removed — see the round below.) Phase 1 task 7 |
| The lazy import of `DISPATCH_FAILED_PREFIX` claimed a cycle that does not exist — the dispatcher imports `merge_to_main` only inside a function | the prefix moved to `merge_to_main.py` (it is a *parser* contract), the dispatcher aliases it, and both lazy imports are gone |
| `dispatch_failures[0]` picked the last-in-document failure, not the first | the parser reports the first failure in the reply — the thing that went wrong first |
| The isolation abort became **retryable**, which it was not before the prefix existed | it carries the permanent prefix: fail-closed, and not retried |
| The dispatcher's module docstring still described the OLD contract ("carries no parseable verdict") — the branch had changed it | rewritten to describe the prefix, and the two kinds of failure |
| The Phase 1 "Demonstrable by" commands selected **zero** tests (`-k retry`, `-k quoted_template` match no test id) | the real test ids, each of which exists and passes |
| A **deterministic** dispatch error (the pool refused the task's shape) cost a second full dispatch to learn the same thing | the permanent prefix: a shape refusal and an isolation abort are not retried |
| *(found while answering the above)* The transport-error path returned bare prose, so the **exception was lost** and the operator saw "malformed" | it carries the dispatch-failure prefix, so the reason travels with the failure |

The **commit security review**, run against the round-6 commit, then
found the fail-open that round 6's own fix had introduced — which is
the measure of the defect: the shape rules were never the problem, the
guessing was.

| Finding | Answered |
|---|---|
| **The tie-break was a fail-open.** Preferring the candidate that stands on its own line lets a QUOTE win when the reviewer's real verdict is inside a sentence: the reply is refused only if two candidates stand on their own lines, so a standalone quote beside an embedded verdict was read as the answer | §4.6 — the tie-break is gone. A reply with more than one candidate is refused, whatever the positions, because the two replies are the same text with the roles reversed |
| *(asked for by the same review)* A regression test for the asymmetric shape — quote on its own line, genuine verdict embedded in prose — asserting the reply is refused | `tests/unit/core/test_merge_to_main_verdict_quotes.py::test_a_standalone_quote_does_not_win_over_an_embedded_verdict` |

The fourth quote shape changed with it, and then changed back. It
became a block **inside a quoted literal** — the reply-builder line a
review quotes is a string in the source, so the characters around the
block are quote marks. And then the same review, run against the
commit that added it, pointed out that a rule about a block's
surroundings has the SAME failure direction as the tie-break: a
reviewer that wraps its own verdict in quote marks would be hidden by
it, and what a rule hides, a rule can promote to be the only
candidate. So the shape went, and with it the last rule that could
hide a genuine verdict.

**The rule the parser ended up with.** The only shapes it acts on are
the ones a genuine verdict cannot have — a note that is nothing but
template placeholders, and a decision word that is the prompt's
alternatives joined by a pipe. Everything else is either the answer or
a reason to refuse, and a reply with two possible answers is refused.
The dispatch-failure prefix stopped being a *skip* for the same
reason: it now tells the operator and the retry path what the block
is, instead of hiding it.

Round 8 reviewed the tightened parser, and its findings were about
the edges of the rule rather than the rule itself:

| Finding | Answered |
|---|---|
| A **durable decision record** still said "the verdict parser reads the last verdict block rather than the first" — the rule this plan reverses. CLAUDE.md makes `docs/decisions/` the record of how the build behaves | `docs/decisions/2026-11-21-verdict-parser-single-candidate.md` is the new record, and the capture-window record's Status now points at it as superseded |
| The **retry hint covered only one** of the two unreadable replies: a reply naming an unknown decision was retried with the bare prompt, so a reviewer that quoted a bad decision word reproduced it | the hints are keyed by what went wrong — the ambiguous reply and the unknown decision each get their own |
| An unknown-decision block **anywhere** in the reply poisoned it, where the parser before this branch read only the last block | an unknown decision word now decides nothing and poisons nothing; it is reported only when it is the **last** block, because that block is the reviewer's own answer |
| **Untrusted text was spliced into a verdict block raw** — the pool's reply, the pool's error, an exception repr. A verdict block in that text gave the reply a second candidate, so the parser refused it and the failure reason was dropped | the delimiters are defanged before the text is spliced |

Round 9 reviewed the branch with the decision record and the corrected
task list in it. Its findings were about the plan under-reporting what
had actually landed, plus one formatting slip:

| Finding | Answered |
|---|---|
| **Phase 1 task 01 still claimed the dispatch-failure prefix makes `parse_verdict` skip the block** — the mechanism this plan's own decision record names as fail-open #3. A task marked LANDED that documents a skip the code deliberately lacks invites a future reader to reinstate it | task 01 now says the prefix *classifies; it does not skip* — the block is read as the `block` it is, with the failure in its note (§4.6) |
| **The third refusal shape had no retry hint** — a reply carrying only quoted verdict templates is refused, but no hint matched it, so the retry re-sent the identical prompt and the merge blocked for a reason nobody could act on | `_QUOTED_ONLY_NOTE` joined the other two in `_RETRY_HINTS`; the hint table now covers every refusal the parser can issue |
| `ruff format` would reformat a test file | `tests/unit/test_merge_review_dispatcher.py` carried extra blank lines; it is reformatted, and every touched file passes `ruff format --check` |
| **Tasks 05 and 06 shipped but were not marked LANDED**, and task 05's wording still described the superseded design — the plan under-reported its own state | both are marked LANDED, and task 05's text now names the two shapes a genuine verdict cannot have, rather than the retired rule |
| **`parse_verdict`'s docstring contradicted its code** — it said an unknown decision is reported "only when it is all the reply has", while the code reports it whenever the *last* block is unknown | the docstring now states the rule the code implements: the last block being unreadable is what gets reported, because reporting an earlier quote would hide the reviewer's own answer |
| **Drop the unrelated edit to `docs/plans/2026-11-21-fleet-session-start-status-banners.md`** (`superseded_by: null` → `superseded_by:`) | **Kept, and here is why.** The edit is not a drive-by: it is what the `mdformat` hook *writes*. Restoring the file to `main`'s text and running the hook over it rewrites the line again — so dropping the commit would leave the merge gate modifying a file mid-run and the working tree dirty when the squash-merge happens. The YAML value is unchanged (`null` and an empty scalar are the same value); what changes is the frontmatter's spelling, and the gate insists on the spelling |

**Landed with this plan:** Phase 1 tasks 5, 6 and 7 — the parser skips
a quoted template, refuses an ambiguous reply, and the prompt says that
quoting the verdict's shape is not a verdict — plus the §4.7 note-cap
change and the permanent/transient split. These had to land *with* the
plan rather than after it: a branch whose review is blocked by the very
defect the plan describes cannot be reviewed, so the fix travels in the
branch that documents it.

Two further reviewers returned a **block that carried no review
opinion at all**: one pool dispatch failed with the literal placeholder
`{failure}` in the envelope's `error` field, and one reviewer produced
no parseable verdict block on either attempt. Both are the
condition §4.1 describes — a failed dispatch converted into a verdict
about the code — and both are what Phase 1 exists to fix. Neither says
anything about the plan's content.

The review path itself was measured directly to confirm that the
machinery is sound: a short reply, a reply dispatched with worktree
isolation, and a 40 KB reply all returned a parseable verdict through
`dispatch_review_async` → `parse_verdict`. The failures are specific
to particular reviewer agents and particular dispatches, not to the
capture or the parser.

## Related

- `docs/decisions/2026-10-03-trunk-based-agent-review.md` — the
  workflow this plan serves
- `docs/decisions/2026-11-15-parallel-ensemble-review.md` — the
  concurrent-dispatch and worktree-isolation decision this plan
  extends
- `docs/decisions/2026-11-15-review-capture-window.md` — the capture
  contract the verdict is parsed through
- `docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md` — §4.1
  (exit codes) and §4.4 (the ensemble rule)
