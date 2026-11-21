"""A quoted verdict template is not the reviewer's verdict.

``parse_verdict`` reads a reply only when **exactly one** block could
be the reviewer's answer. The prompt asks the reviewer to put its
verdict last, and its own docstring records what that invites: an
analysis that quotes a line of code can carry a literal verdict block,
and a parser that simply took the last one would take the quote as the
verdict.

That is not hypothetical. The source that builds the dispatcher's
verdict hardcodes the decision word ``block``, so a reviewer that
quotes that source back — which is what a reviewer does when it
verifies a claim about that source — hands the parser a block that
nobody wrote, with an uninterpolated template fragment as its note.
Three rounds of a real plan's review reported exactly that:
``block - {failure}`` and ``block - {DISPATCH_FAILED_PREFIX}{detail}``.

The prompt is the other source: it spells the decision word as the
alternatives joined by ``|``, because the reviewer has to be shown the
format. A reviewer that quotes the prompt back produces a decision word
that is not one of the three.

Both are recognisable from the block's own shape, which is what makes
the fix structural rather than a request for care: a reviewer's note
is prose and its decision word is one word. Those two shapes are the
only ones the parser skips, because they are the only two a genuine
verdict cannot have — a rule that skips anything else can hide the
reviewer's own answer and promote a quote to be the only candidate.

Everything else is either the answer or a reason to refuse. A reply
carrying two possible answers is refused rather than parsed, and so is
a reply whose **last** block names a decision the pipeline does not
know.
"""

from __future__ import annotations

from mahavishnu.core.merge_review_dispatcher import (
    DISPATCH_FAILED_PERMANENT_PREFIX,
    DISPATCH_FAILED_PREFIX,
    _isolation_failure,
)
from mahavishnu.core.merge_to_main import (
    MAX_NOTE_LENGTH,
    _is_retryable,
    parse_verdict,
)

#: The dispatcher's own template, copied out of
#: ``merge_review_dispatcher.py``. The decision word is fixed at
#: ``block``, so a parser that takes this as a verdict reports a block
#: that the reviewer never wrote.
TEMPLATE_QUOTE = "<verdict>decision: block note: {failure}</verdict>"

#: The other template in the same function.
TEMPLATE_QUOTE_2 = (
    "<verdict>decision: block note: {DISPATCH_FAILED_PREFIX}{detail}</verdict>"
)

#: The prompt's contract, quoted back.
CONTRACT_QUOTE = "<verdict>decision: pass|needs_adjustment|block note: ...</verdict>"


def test_a_quoted_template_after_the_verdict_does_not_win() -> None:
    """The reviewer's own verdict survives a quote that follows it."""
    reply = (
        "The diff looks correct to me.\n"
        "<verdict>decision: pass note: nothing to change</verdict>\n"
        "For reference, the dispatcher builds it like this:\n"
        f"{TEMPLATE_QUOTE}\n"
    )

    verdict = parse_verdict(reply)

    assert verdict["decision"] == "pass"
    assert "nothing to change" in verdict["note"]


def test_a_quoted_template_alone_is_not_a_verdict() -> None:
    """A reply that is only a quote is malformed, not a block."""
    verdict = parse_verdict(f"Here is the template:\n{TEMPLATE_QUOTE}\n")

    assert verdict["decision"] == "block"
    assert verdict["note"].startswith("malformed:")
    assert "only quoted verdict templates" in verdict["note"]


def test_the_second_template_is_also_recognised() -> None:
    """The other template in the same function is a quote too."""
    verdict = parse_verdict(f"the code says:\n{TEMPLATE_QUOTE_2}\n")

    assert verdict["decision"] == "block"
    assert "only quoted verdict templates" in verdict["note"]


def test_the_contracts_own_quote_is_not_a_verdict() -> None:
    """Quoting the prompt's contract is a quote, not an unknown decision."""
    verdict = parse_verdict(f"I was told to reply like this:\n{CONTRACT_QUOTE}\n")

    assert verdict["decision"] == "block"
    assert verdict["note"].startswith("malformed:")
    assert "unknown decision" not in verdict["note"]


def test_the_reviewers_verdict_behind_a_contract_quote_still_counts() -> None:
    """A contract quote after the verdict does not hide the verdict."""
    reply = (
        "Looks good.\n"
        "<verdict>decision: needs_adjustment note: one thing to fix</verdict>\n"
        f"{CONTRACT_QUOTE}\n"
    )

    verdict = parse_verdict(reply)

    assert verdict["decision"] == "needs_adjustment"
    assert "one thing to fix" in verdict["note"]


def test_a_plain_verdict_is_unchanged() -> None:
    """The ordinary path still parses the reviewer's own verdict."""
    verdict = parse_verdict(
        "<verdict>decision: block note: the diff breaks the contract</verdict>"
    )

    assert verdict["decision"] == "block"
    assert "the diff breaks the contract" in verdict["note"]


def test_an_unknown_decision_is_still_fail_loud() -> None:
    """A non-quote with an unknown decision word still fails loud.

    The quote rules are narrow on purpose: a block that names no known
    decision and is not recognisably a quote is still an error, not a
    reason to go looking for an earlier block.
    """
    verdict = parse_verdict(
        "<verdict>decision: looks_fine note: everything reads well</verdict>"
    )

    assert verdict["decision"] == "block"
    assert "unknown decision" in verdict["note"]


def test_a_note_that_mentions_a_placeholder_is_still_a_note() -> None:
    """A placeholder inside prose is prose, and stays the note."""
    verdict = parse_verdict(
        "<verdict>decision: block note: the note field is literally "
        "{failure} in the source</verdict>"
    )

    assert verdict["decision"] == "block"
    assert "{failure}" in verdict["note"]


def test_the_note_is_still_capped() -> None:
    """The sanitizer still caps the note it keeps.

    The cap is on the content, and a truncated note keeps a trailing
    ``...`` so a cut note is not mistaken for a whole one -- so the
    result is the cap plus those three characters.
    """
    verdict = parse_verdict(
        f"<verdict>decision: pass note: {'x' * (MAX_NOTE_LENGTH + 100)}</verdict>"
    )

    assert verdict["decision"] == "pass"
    assert len(verdict["note"]) <= MAX_NOTE_LENGTH + 3
    assert verdict["note"].endswith("...")


def test_the_dispatchers_own_failure_is_read_as_a_block_with_its_reason() -> None:
    """The dispatcher's failure report is a block that names the failure.

    The pool-failure branch synthesises a verdict of its own, and its
    note is the pool's error text verbatim -- which can be a template
    fragment. A parser that skipped placeholder-shaped notes as quotes
    would skip this genuine failure report and lose the reason with it.
    The prefix is what tells them apart: the note says the DISPATCH
    failed, so the operator sees a failure and not a reviewer's opinion.
    """
    reply = (
        f"<verdict>decision: block note: {DISPATCH_FAILED_PREFIX}"
        "the worker died</verdict>"
    )

    verdict = parse_verdict(reply)

    assert verdict["decision"] == "block"
    # The reason survives, and the prefix keeps it retryable: a
    # dispatch that failed says nothing about the code.
    assert "the worker died" in verdict["note"]
    assert verdict["note"].startswith(DISPATCH_FAILED_PREFIX)


def test_the_isolation_template_carries_the_prefix_too() -> None:
    """Every synthesised failure verdict carries the prefix.

    The isolation-failure template's note is prose, so a reviewer who
    quoted it would have it read as their own verdict. With the prefix
    on it, a quote is recognisable as a quote.

    It carries the **permanent** sibling of the prefix: this pool
    cannot honour the isolation the review asked for, so a second
    dispatch would abort the same way. The isolation abort was
    fail-closed and not retried before the prefix existed, and it
    stays that way.
    """
    template = _isolation_failure("python-pro")

    assert template.startswith(
        f"<verdict>decision: block note: {DISPATCH_FAILED_PERMANENT_PREFIX}"
    )


def test_a_reviewer_who_quotes_the_isolation_template_is_refused() -> None:
    """Quoting the isolation template cannot become the verdict.

    The template's note is prose, so nothing in the block says it is a
    quotation -- which is exactly why the parser does not try to tell.
    The reply carries two blocks that could each be the reviewer's own,
    so it is refused and the reviewer is asked again.
    """
    reply = (
        "The isolation check looks right.\n"
        "<verdict>decision: pass note: nothing to change</verdict>\n"
        f"{_isolation_failure('python-pro')}\n"
    )

    verdict = parse_verdict(reply)

    assert verdict["decision"] == "block"
    assert "more than one verdict block" in verdict["note"]
    assert "nothing to change" not in verdict["note"]


def test_a_permanent_failure_is_read_as_a_block_with_its_reason() -> None:
    """A permanent dispatch failure says so, and keeps its reason.

    The permanent prefix is the same contract as the transient one: the
    note says the DISPATCH failed, so the block is a failure report
    rather than a reviewer's opinion. The reason survives, because that
    is the whole point of synthesising the failure here rather than
    letting the parser report a bare "malformed".
    """
    reply = (
        "<verdict>decision: block note: "
        f"{DISPATCH_FAILED_PERMANENT_PREFIX}the pool refused the task shape"
        "</verdict>"
    )

    verdict = parse_verdict(reply)

    assert verdict["decision"] == "block"
    assert verdict["note"].startswith(DISPATCH_FAILED_PERMANENT_PREFIX)
    assert "the pool refused the task shape" in verdict["note"]


def test_a_transient_failure_is_retried_and_a_permanent_one_is_not() -> None:
    """Only the failure that might change is worth another attempt.

    A server that could not be reached is worth one more try; a pool
    that refused the task's shape will refuse it again, so spending a
    second full dispatch on it teaches nothing.
    """
    transient = f"{DISPATCH_FAILED_PREFIX}the server could not be reached"
    permanent = f"{DISPATCH_FAILED_PERMANENT_PREFIX}the pool refused the shape"

    assert _is_retryable(transient) is True
    assert _is_retryable(permanent) is False


def test_two_candidate_verdicts_are_ambiguous() -> None:
    """A reply with two candidate verdicts is refused, not guessed at.

    Which of two blocks the reviewer wrote cannot be told from the
    reply, so the parser refuses to pick. Picking one could open the
    ensemble gate on a verdict nobody wrote.
    """
    reply = (
        "<verdict>decision: needs_adjustment note: one thing to fix</verdict>\n"
        "<verdict>decision: pass note: nothing to change</verdict>\n"
    )

    verdict = parse_verdict(reply)

    assert verdict["decision"] == "block"
    assert "more than one verdict block" in verdict["note"]
    # Fail-loud, and worth one more attempt: the reviewer can answer
    # unambiguously next time.
    assert _is_retryable(verdict["note"]) is True


def test_a_quoted_block_with_a_prose_note_does_not_win() -> None:
    """The fail-open this branch closes: a quote read as the verdict.

    A quoted source line whose decision word is a single valid word
    and whose note is prose is indistinguishable from a verdict the
    reviewer wrote. Taking the last one read the quote — a ``pass``
    nobody wrote — and a quoted pass can open the ensemble gate.
    """
    reply = (
        "<verdict>decision: needs_adjustment note: the cap breaks a test"
        "</verdict>\n"
        "the fixture says:\n"
        "<verdict>decision: pass note: nothing to change</verdict>\n"
    )

    verdict = parse_verdict(reply)

    assert verdict["decision"] == "block"
    assert "more than one verdict block" in verdict["note"]
    assert "nothing to change" not in verdict["note"]


def test_a_standalone_quote_does_not_win_over_an_embedded_verdict() -> None:
    """The mirror of the embedded quote: a standalone quote must not win.

    A reviewer that writes its verdict inside a sentence and quotes a
    verdict block on its own line produces two candidates, and the
    standalone one is not necessarily the reviewer's — the quote is the
    shape a review takes when it explains something. Refusing the
    reply is the only answer that cannot read a quoted ``pass`` as the
    reviewer's own.

    A tie-break on position would get this one wrong in the other
    direction: preferring the block that stands on its own line reads
    the QUOTE as the answer, which is the same fail-open as preferring
    the last one.
    """
    reply = (
        "the source says:\n"
        "<verdict>decision: pass note: nothing to change</verdict>\n"
        "and my verdict is <verdict>decision: needs_adjustment note: the "
        "cap breaks a test</verdict>\n"
    )

    verdict = parse_verdict(reply)

    assert verdict["decision"] == "block"
    assert "more than one verdict block" in verdict["note"]
    assert "nothing to change" not in verdict["note"]


def test_an_unknown_decision_earlier_does_not_poison_the_answer() -> None:
    """A quote the parser cannot read does not fail the review.

    The reviewer whose last block is fine has answered, whatever it
    quoted earlier -- and a quoted source line often carries a decision
    word that is not one of the three. The unknown word decides nothing
    and poisons nothing; it is reported only when it is all the reply
    has.
    """
    reply = (
        "<verdict>decision: {decision} note: the source builds it like this"
        "</verdict>\n"
        "<verdict>decision: needs_adjustment note: the cap breaks a test"
        "</verdict>"
    )

    verdict = parse_verdict(reply)

    assert verdict["decision"] == "needs_adjustment"
    assert "the cap breaks a test" in verdict["note"]


def test_a_block_inside_a_quoted_literal_is_refused_not_read() -> None:
    """The shape the real incident took: a string literal in the source.

    The reply-builder line a review quotes is a Python string, so the
    characters around the block are quote marks. That shape is USUALLY
    a quotation — but it is not a sound one to act on: a reviewer that
    wraps its own verdict in quote marks would be hidden by it, and what
    a rule hides, a rule can promote to be the only candidate. So the
    reply is refused instead, and the reviewer is asked again.
    """
    reply = (
        "the reply builder reads\n"
        '    return "<verdict>decision: pass note: " + '
        'body[:REPLY_LENGTH] + "</verdict>"\n'
        "which is fine.\n"
        "<verdict>decision: needs_adjustment "
        "note: the capture still cuts the reply</verdict>"
    )

    verdict = parse_verdict(reply)

    assert verdict["decision"] == "block"
    assert "more than one verdict block" in verdict["note"]
    assert "the capture still cuts the reply" not in verdict["note"]
