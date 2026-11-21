---
status: active
role: canonical
kind: decision
date: 2026-11-21
last_reviewed: 2026-11-21
superseded_by:
blocks_on: []
topic: merge-review
title: "A reviewer's reply is read only when one block could be the answer"
---

# A reviewer's reply is read only when one block could be the answer

## Context

`parse_verdict` reads a model's free text: it finds the verdict block
in the reviewer's reply and decides the merge on what it says. The
reviewer's analysis sits in the same reply, and an analysis that
quotes a line of code carries a literal verdict block in it.

That is not hypothetical, and it is not rare. Three rounds of one
plan's review reported blocks whose notes were uninterpolated template
fragments, from reviewers that never said `block`. The plan quoting
the dispatcher's verdict-building source made quoting it a natural
thing for the reviewer to do — the plan was the source of the poison.

The failure is expensive because of the ensemble rule: `aggregate_verdicts`
proceeds on **two passes out of three**. A quoted `pass` does not
merely add noise; it can open the gate on a verdict nobody wrote, and
a reviewer that said `needs_adjustment` is overruled by its own
quotation.

Three fixes were tried, and each one was a fail-open wearing a
different hat. The rule that generalises them is the one this record
states.

## Decision rule

**A reply is read only when exactly one block could be the reviewer's
answer.** More than one candidate is refused — a fail-loud `malformed`
note, which the retry path turns into another attempt with a prompt
that says what to change.

The consequences are the whole rule:

- **A skip rule is safe only if the shape it keys on is one a genuine
  verdict cannot have.** Two are: a note that is nothing but template
  placeholders, and a decision word that is the prompt's alternatives
  joined by a pipe. A reviewer's note is prose and its decision word
  is one word. Those two are skipped; nothing else is.
- **No tie-break, and no rule about the block's surroundings.**
  Preferring the block that stands on its own line is the same
  fail-open with the roles reversed: a reviewer whose verdict is inside
  a sentence, quoting a block beneath it, would have the quote read as
  the answer. So would a rule that treats "a block inside a quoted
  literal" as a quotation. **What a rule hides, a rule can promote to
  be the only candidate** — that is how a quoted `pass` opens the gate.
- **A marker classifies; it does not skip.** The dispatch-failure
  prefixes (`the dispatch failed: ` and `the dispatch failed permanently: `) say what a synthesised failure report is, so the
  operator sees a failure and the retry path knows whether another
  attempt is worth making. They do not remove the block from
  consideration: a reviewer's own note could begin with the same
  words.
- **Untrusted text is defanged before it is spliced into a verdict
  block.** The pool's error text can carry a literal verdict block, and
  splicing it raw would give the reply a second candidate — which the
  parser refuses, dropping the very reason the failure report exists
  to carry.
- **A block whose decision word is unknown decides nothing, and
  poisons nothing.** A reviewer whose last block is fine has answered,
  whatever it quoted earlier. But an unknown decision word is never
  skipped in favour of an earlier block: when the **last** block names
  a decision the pipeline does not know, it is reported — reporting an
  earlier quote as the verdict would hide the reviewer's own answer.

## Status

Active — 2026-11-21. Implemented in
`mahavishnu/core/merge_to_main.py` (`parse_verdict`) and
`mahavishnu/core/merge_review_dispatcher.py`, covered by
`tests/unit/core/test_merge_to_main_verdict_quotes.py`,
`tests/unit/core/test_merge_to_main_gaps.py` and
`tests/unit/test_merge_review_dispatcher.py`. The plan is
`docs/plans/2026-11-21-merge-review-convergence.md`.

Three fail-opens were found and closed on the way, each by a review
rather than by the first draft:

1. The tie-break ("prefer the candidate on its own line") read a
   **quote** as the answer whenever the reviewer's real verdict was
   inside a sentence.
2. The rule about a quoted literal read a **verdict** as a quotation
   whenever the reviewer wrapped its own verdict in quote marks.
3. The dispatch-failure prefix, used as a skip, hid a reviewer's own
   verdict whenever its note began with the same words.

Each was the same mistake in a different direction: a rule that
classifies candidates can hide the real answer, and hiding it promotes
whatever is left.

This record supersedes the clause in
`2026-11-15-review-capture-window.md` that the verdict parser reads
the **last** verdict block rather than the first. The capture still
keeps the newest bytes, and the prompt still asks for the verdict
block last — but the parser no longer decides by position.
