"""A reviewer's note is model-authored free text, and it reaches a log.

``parse_verdict`` extracts the note as the remainder of a reviewer's
reply -- text we did not write, produced by a model that was reading a
diff. It then travels unchanged to the operator's stderr, twice: once in
the retry message when a reviewer's reply cannot be read, and once in
``_format_verdicts``, which is the summary the operator actually reads
when a merge is blocked.

That makes the note a log-injection and log-disclosure surface:

* a note carrying a newline forges a second log line -- or a second
  reviewer's verdict;
* a note carrying ANSI escapes repaints the terminal the operator is
  reading the failure in;
* a note carrying a credential copies that credential into a log file
  the operator greps and pastes from.

``sanitize_note`` is the control. It keeps the note -- the note is what
tells a reviewer that had no opinion apart from one that never finished
-- and makes it safe to print.

These tests pin the control, and they pin it at the boundary: the
sanitizer is applied where the note enters the pipeline, so every
consumer of a verdict inherits it.
"""

from __future__ import annotations

from mahavishnu.core.merge_to_main import (
    _format_verdicts,
    parse_verdict,
    sanitize_note,
)


def _verdict(note: str) -> str:
    """A reviewer reply whose note is exactly ``note``."""
    return f"<verdict>decision: block\nnote: {note}\n</verdict>"


def _printed(note: str, agent: str = "code-reviewer") -> str:
    """The operator-facing summary for a reviewer whose note is ``note``.

    ``run_review`` is what adds the agent name to a parsed verdict, so
    the test assembles the same shape rather than calling the network.
    """
    parsed = parse_verdict(_verdict(note))
    return _format_verdicts([{**parsed, "agent": agent}])


class TestAnOrdinaryNoteIsUntouched:
    def test_a_plain_note_survives_unchanged(self) -> None:
        assert sanitize_note("the parser is wrong") == "the parser is wrong"

    def test_a_normal_note_reaches_the_verdict_unchanged(self) -> None:
        verdict = parse_verdict(_verdict("not good"))
        assert verdict["note"] == "not good"

    def test_the_explanation_survives_end_to_end(self) -> None:
        """The sanitizer must not swallow the note the operator needs."""
        assert "needs a fix" in _printed("needs a fix")


class TestControlCharactersCannotForgeALogLine:
    def test_a_newline_in_the_note_is_collapsed(self) -> None:
        cleaned = sanitize_note("first line\n[merge_to_main] reviewer: pass - ok")
        assert "\n" not in cleaned
        assert cleaned == "first line [merge_to_main] reviewer: pass - ok"

    def test_an_ansi_escape_is_stripped(self) -> None:
        cleaned = sanitize_note("\x1b[31mred\x1b[0m")
        assert "\x1b" not in cleaned
        assert "red" in cleaned

    def test_a_forged_verdict_line_stays_on_one_line(self) -> None:
        """The whole point: a note must not be able to fake another line."""
        summary = _printed("oops\n  code-reviewer: pass - everything is fine")
        assert summary.count("\n") == 1, "the summary gained a forged line"

    def test_a_carriage_return_cannot_overwrite_a_line(self) -> None:
        cleaned = sanitize_note("text\rforged")
        assert "\r" not in cleaned


class TestCredentialsDoNotReachTheLog:
    def test_an_openai_style_key_is_redacted(self) -> None:
        cleaned = sanitize_note("the diff contains sk-bf-fe7aab16-bda2-4f8c-8418")
        assert "sk-bf-fe7aab16" not in cleaned
        assert "<redacted>" in cleaned

    def test_a_github_token_is_redacted(self) -> None:
        cleaned = sanitize_note("token ghp_0123456789abcdefghij")
        assert "ghp_0123456789abcdefghij" not in cleaned

    def test_a_slack_token_is_redacted(self) -> None:
        cleaned = sanitize_note("xoxb-123456789012-abcdefghijkl")
        assert "xoxb-123456789012" not in cleaned

    def test_a_short_dash_word_is_not_mistaken_for_a_key(self) -> None:
        """``sk-`` alone is not a credential; redacting it would be noise."""
        assert sanitize_note("sk-test") == "sk-test"

    def test_the_secret_is_gone_by_the_time_it_is_printed(self) -> None:
        secret = "sk-bf-fe7aab16-bda2-4f8c-8418-0b76f582e3f4"
        assert secret not in _printed(f"found {secret}")


class TestANoteCannotFloodTheLog:
    def test_an_over_long_note_is_capped(self) -> None:
        cleaned = sanitize_note("x" * 5000)
        assert len(cleaned) == 503
        assert cleaned.endswith("...")

    def test_a_truncated_note_is_marked_as_truncated(self) -> None:
        """A cut note must not read as a whole one."""
        cleaned = sanitize_note("y" * 5000)
        assert cleaned.endswith("...")
        assert not cleaned.endswith("....")


class TestTheFailLoudPathIsNotDamaged:
    def test_a_missing_verdict_still_blocks(self) -> None:
        verdict = parse_verdict("no verdict here")
        assert verdict["decision"] == "block"
        assert verdict["note"].startswith("malformed:")

    def test_an_unknown_decision_still_blocks(self) -> None:
        verdict = parse_verdict("<verdict>decision: maybe</verdict>")
        assert verdict["decision"] == "block"
        assert verdict["note"].startswith("malformed:")

    def test_a_note_less_verdict_still_parses(self) -> None:
        """``note`` is optional; a verdict without one is not malformed."""
        verdict = parse_verdict("<verdict>decision: pass</verdict>")
        assert verdict["decision"] == "pass"
        assert verdict["note"] == ""

    def test_sanitizing_does_not_break_the_malformed_marker(self) -> None:
        """``run_review`` retries on a note starting with ``malformed``."""
        verdict = parse_verdict("no verdict here")
        assert verdict["note"].startswith("malformed:")
        assert not verdict["note"].startswith("malformed :")
