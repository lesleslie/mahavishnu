---
status: active
role: canonical
kind: decision
date: 2026-11-15
last_reviewed: 2026-11-15
superseded_by:
blocks_on: []
topic: merge-review
title: "A capture of a live pane keeps the newest bytes"
---

# A capture of a live pane keeps the newest bytes

## Context

The stage-2 review does not receive the reviewer's answer directly. It
launches a one-shot `claude -p --output-format stream-json` session in
a tmux pane, polls that pane until the CLI's completion marker appears,
and parses the verdict out of **what the capture returned**. The capture
is therefore load-bearing for the merge: a reply that arrives truncated
carries no readable verdict, and an unreadable verdict is a fail-loud
`block`.

Two things about the capture were wrong, and they had to be fixed
together.

**The capture read only the visible pane.** `TmuxTerminalAdapter`
passed `since_offset=0`, which is `tmux capture-pane -S -0` — the
current screenful and nothing else. The pane is 24 rows of 80 columns,
so a reply past about 1,920 characters wraps off the top of the screen
and its opening falls out of the capture. Measured on a real pane:
`-S -0` returned 1,744 bytes of a reply whose verdict block was in the
part that had scrolled away, and the verdict did not parse. A review
that ran perfectly well gated the merge as a block, with nothing in the
verdict to say the reply had been cut.

**The shared capture truncated by keeping the OLDEST bytes.**
`capture_pane` bounded its output with `encoded[:max_bytes]` — the
head of the pane. That is backwards for a capture of a *live* pane: the
answer is written **last**, so the head is the part that does not
matter. This was invisible while the capture read one screenful, because
one screenful never reached 64 KB. It becomes load-bearing the moment
the capture is widened: a review's scrollback crosses 64 KB at roughly
600 tool calls (measured: 118 KB of scrollback from 600 events), and
the head-truncation would then delete the result line outright —
replacing "the reply is cut" with "the reply is gone".

**The prompt stated a budget that was not real.** It told the reviewer
it had "about three minutes of wall clock" and that "the dispatch that
runs you is cut off after that -- not by a timeout you can see, but by
the transport the reply travels over". The three minutes was never
measured and is not what the code does. What *is* measured: a call
held open through this client's MCP transport for 420 s came back with
its payload intact, and reviews in this repo have run to 855 s and
1168 s and delivered a verdict. The `REVIEW_DISPATCH_TIMEOUT` comment
asserted the opposite — that the transport cut the reviewer off and
that "the budget the reviewer actually has is minutes, not an hour" —
so the prompt and the constant it reads contradicted each other, which
is how a reviewer caught it.

The two now agree, and both say only what was measured: the constant
is the **server-side** ceiling (how long the pool lets the worker run),
the prompt states that ceiling and tells the reviewer not to plan on
spending it, and the practical advice — read only the files the
verdict needs — is what actually keeps a review inside its budget.
Neither claims a mechanism nobody confirmed: the client's httpx read
timeout is 300 s on a quiet stream, and the server's dispatch
heartbeat *is* a no-op for a client that sends no progress token (this
one does not), so those two facts do not fit together neatly — which is
a reason to state the measurement rather than a mechanism.

A budget stated three times too short makes a reviewer rush, and a
reviewer that rushes writes a long reply to compensate — which is
what pushes it past the capture bound. The prompt also quoted a
600-character note length while the sanitizer caps a note at 500, and
it quoted a 1,500-character reply budget "because the pool captures
the last screenful" — a justification that stopped being true the
moment the capture started reading the scrollback, and a number that
has to keep fitting a capture smaller than this repo's.

## Decision rule

- **A capture of a live pane keeps the newest bytes.** `capture_pane`
  bounds its output from the end (`encoded[-max_bytes:]`). The answer
  is written last; the answer is what the capture is for.
- **The terminal adapter reads the pane's scrollback, not its visible
  screenful** — `CAPTURE_SCROLLBACK_LINES` (2,000 lines, which is
  tmux's default history limit, so in practice the whole session). The
  bound still applies, so the work per poll stays bounded.
- **The adapter honours the terminal adapter contract's `lines`
  argument** (`None` means all of it), which it previously accepted and
  ignored. The mock adapter already behaved this way. The bound is
  applied in the adapter, not left to tmux: `-S -N` starts N rows above
  the *top* of the visible pane, so it returns N rows of scrollback
  **plus** the pane's own rows (measured: `-S -10` on a 24-row pane
  returned 33 rows).
- **The prompt states the dispatch's ceiling and tells the reviewer not
  to plan on spending it.** The ceiling is read from
  `REVIEW_DISPATCH_TIMEOUT` so the number cannot drift, and the note
  length it quotes is read from `MAX_NOTE_LENGTH`, the cap that is
  actually enforced. Neither states a mechanism that cuts a reviewer
  off: the transport's limits were asserted but never measured, and
  the constant's own comment asserted the opposite of the prompt.
- **The prompt's reply budget stays smaller than what the capture can
  hold** (`REVIEW_REPLY_BUDGET_CHARS`, 1,500). The capture reads the
  scrollback, so the reply could be far longer — but the budget is the
  advice that actually keeps a review inside its budget, and it has to
  survive a capture smaller than the one this repo runs: the visible
  pane is 24 rows of 80 columns, and a reply past about that used to
  arrive with its opening cut off. So the prompt states the number,
  says the read is bounded, and puts the verdict block last — without
  advertising how much room the capture actually has, which would
  invite a reviewer to overrun a budget during the window between the
  change landing and the server picking it up.
- **The verdict block stays the last thing the reviewer writes.** The
  capture is bounded at the end, so the one part of the reply that must
  never be the part that is lost is the block itself.
- **The reply is taken from the *last* `"result"` event in the
  capture.** The capture reads the scrollback, so a session that ran
  more than one turn carries more than one result event; the reply is
  written last, so the last event is the one that answers this
  dispatch.

## What still blocks a verdict (2026-11-16)

The capture, the extraction, the verdict parser and the prompt are fixed
and measured, and the fork crash that was killing the MCP server's own
children is fixed too (see
`2026-11-16-no-grpc-in-forking-processes.md`). A review still does not
produce a readable verdict, for a reason outside this file's scope.

**The reviewer's CLI session ends mid-turn and never emits a result
event.** The captured stream carries
`"terminal_reason":"aborted_streaming"`, `"is_error":true` and
`"subtype":"error_during_execution"` after 30 turns, and no
`"type":"result"` line anywhere. The capture then holds a session with
no reply in it, so the review reads as a malformed verdict — which is a
fail-loud block, not a review that had no opinion. The CLI's own
diagnostic is terse: `[ede_diagnostic] result_type=user last_content_type=n/a stop_reason=tool_use`, from an API call that had
run for 161 s. A short review-shaped dispatch — a prompt that asks the
model to read one file and answer — completes in 250 s and produces a
clean result event, so the abort is not the pool, the capture or the
transport: it is the model session's own stream, ending mid-turn.

Two candidate causes were checked rather than assumed, and both are
ruled out:

- **The fork crash.** With the OTLP exporters no longer loading
  grpcio, the crash reports stopped dead (27 before a review run, 27
  after) and the server logged no fork warnings at all. The reviews
  still failed the same way.
- **The harness's permission check.** The pane's "system" events are
  `thinking_tokens` — 496 of them in one pane — and not hook
  notifications, so the reviewer was not starved by hook latency. The
  permission denials it did hit (a `cd` before a version-control
  command, a file redirect) cost it a turn each, not its reply.

So the open question is upstream of this repo: an Anthropic-compatible
stream through the Bifrost gateway ends mid-turn, and the reviewer
never gets to answer. Until that is settled, a merge whose review
cannot be read is blocked by the environment — and the prompt's budget
and the capture's window are the only things this side still controls.

## Status

Accepted, 2026-11-15. Updated 2026-11-16: the capture reads the
scrollback and keeps the newest bytes; the reply is taken from the last
`"result"` event; the verdict parser reads the **last** verdict block
rather than the first, because the prompt permits analysis before the
block and an analysis that quotes a line of code carries a literal
`<verdict>...</verdict>` in it; the prompt states the ceiling and the
practical advice without claiming a mechanism; the review dispatch
carries its own budget to the transport; and the three consumers of the capture
are consistent with the change — the one-shot review path (a fresh
session per task, so its scrollback holds exactly one run), the
interactive path (where `_output_since`'s `pane.startswith(before)`
slicing now actually works, because `before` is the scrollback the
later capture extends), and the CLI and MCP capture surfaces (where
`lines` now bounds the read).

Updated 2026-11-21: the clause above — "the verdict parser reads the
**last** verdict block rather than the first" — is **superseded** by
`2026-11-21-verdict-parser-single-candidate.md`. The parser no longer
decides by position: it reads a reply only when exactly one block
could be the reviewer's answer, and refuses the reply when two could
be. Three rounds of one plan's review showed that a position-based
rule reads a quoted block as the verdict, and that the ensemble gate
proceeds on two passes out of three — so a quoted `pass` could open a
gate on a verdict nobody wrote. Everything else in this record stands:
the capture keeps the newest bytes, the reply is taken from the last
`"result"` event, and the prompt still asks for the verdict block
last.

Covered by `tests/unit/terminal/test_tmux_adapter_capture.py`,
`tests/unit/workers/contract/test_tmux_adapter.py`,
`tests/unit/test_merge_review_dispatcher.py`, and
`tests/integration/test_review_capture_window.py` — the last one
drives a real tmux pane whose reply overflows the visible screen and
fails with `malformed: <verdict> block not found in agent response`
against the old capture.
