"""The stage-2 review dispatcher must reach the agent's actual reply text.

A worker runs Claude Code with ``--output-format stream-json``, so what
the pool captures is a JSON fragment of that stream, not prose. The
agent's reply lives in the stream's ``"result"`` field, JSON-escaped.

Before this was extracted, the escaped verdict block reached
``merge_to_main.parse_verdict`` verbatim. The regex looks for
``<verdict>`` followed by whitespace and then ``decision:`` — but the
escaped form has a literal backslash-n between them — so **every**
review parsed as malformed, and a malformed verdict is a fail-loud
``block``. A reviewer that returned ``decision: pass`` gated the merge
as a block.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Self

import pytest

from mahavishnu.core.merge_review_dispatcher import (
    REVIEW_DISPATCH_TIMEOUT,
    REVIEW_REPLY_BUDGET_CHARS,
    _call_tool_over_http,
    _extract_agent_text,
    _extract_reply_text,
    _parse_pool_result,
    _pool_failure_message,
    build_review_prompt,
    dispatch_review_async,
    ensure_review_pool_async,
)
from mahavishnu.core.merge_to_main import MAX_NOTE_LENGTH, parse_verdict

#: The tail of Claude Code's stream-json result line, as the pool
#: captures it: the head is a cut window, and the ``"result"`` field
#: carries the agent's reply with escaped newlines.
STREAM_FRAGMENT = (
    '...,"result":"<verdict>\\ndecision: pass\\nnote: smoke test\\n</verdict>",'
    '"ttft_ms":17210,"type":"result"}'
)


class _Text:
    def __init__(self, text: str) -> None:
        self.text = text


class _CallResult:
    """A stand-in for the MCP ``CallToolResult``."""

    def __init__(self, text: str) -> None:
        self.content = [_Text(text)]


def _envelope(output: str) -> str:
    """The ``pool_route_execute`` result envelope, JSON-encoded."""
    return json.dumps(
        {
            "pool_id": "mahavishnu_1",
            "worker_id": "worker-1",
            "status": "completed",
            "output": output,
        }
    )



def _fake_call(envelope: str) -> Any:
    """A stand-in for the dispatch's MCP call, returning ``envelope``."""

    async def _call(
        url: str,
        name: str,
        arguments: dict[str, Any],
        *,
        read_timeout: float,
    ) -> _CallResult:
        return _CallResult(envelope)

    return _call


class TestTheAgentTextIsExtracted:
    def test_the_result_field_becomes_the_reply_text(self) -> None:
        assert _extract_agent_text(STREAM_FRAGMENT) == (
            "<verdict>\ndecision: pass\nnote: smoke test\n</verdict>"
        )

    def test_a_plain_reply_is_returned_unchanged(self) -> None:
        plain = "just some prose from a worker"
        assert _extract_agent_text(plain) == plain

    def test_a_reply_with_no_result_field_is_returned_unchanged(self) -> None:
        fragment = '{"type":"assistant","message":{"content":"hello"}}'
        assert _extract_agent_text(fragment) == fragment

    def test_an_empty_result_field_does_not_blank_the_reply(self) -> None:
        # An empty ``result`` is not the agent's text; keep whatever else
        # the worker said rather than returning nothing.
        fragment = '"result":"","type":"result"}'
        assert _extract_agent_text(fragment) == fragment

    def test_an_earlier_turns_result_is_not_the_answer(self) -> None:
        """The last result event is the one that answers this dispatch.

        The capture reads the pane's scrollback rather than one
        screenful, so a session that ran more than one turn carries
        more than one result event. The reply is written last, so the
        last event is the answer -- taking the first would report an
        earlier turn's verdict as this dispatch's.
        """
        pane = (
            '{"type":"result","result":"<verdict>decision: block note: '
            'the first turn</verdict>"}'
            '{"type":"result","result":"<verdict>decision: pass note: '
            'the second turn</verdict>"}'
        )

        extracted = _extract_agent_text(pane)

        assert "the second turn" in extracted
        assert "the first turn" not in extracted

    def test_a_result_key_inside_a_tool_result_is_not_the_answer(self) -> None:
        """Only the stream's own result event is the reply.

        A tool result can *carry* a ``result`` key -- a reviewer that
        reads a file quoting a verdict block puts one in the pane --
        and a plain search for the last ``"result"`` key picks that
        one up, because it comes later in the text. Parsing the events
        keeps it out: the quoted key is nested inside a tool result,
        not a field of a result event.

        The shape here is a session whose second turn was cut short:
        the first turn's result event is the last answer the stream
        produced, and the capture ends inside the second turn.
        """
        pane = "\n".join(
            [
                json.dumps(
                    {
                        "type": "result",
                        "result": (
                            "<verdict>decision: pass note: the real answer</verdict>"
                        ),
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_result",
                                    "content": {
                                        "result": (
                                            "<verdict>decision: block note: "
                                            "quoted from a file</verdict>"
                                        )
                                    },
                                }
                            ]
                        },
                    }
                ),
            ]
        )

        extracted = _extract_agent_text(pane)

        assert "the real answer" in extracted
        assert "quoted from a file" not in extracted


class TestTheVerdictBecomesParseable:
    def test_the_composed_path_yields_a_pass_verdict(self) -> None:
        """The whole shape: MCP envelope -> pool output -> agent text."""
        reply = _extract_reply_text(_CallResult(_envelope(STREAM_FRAGMENT)))
        parsed = _parse_pool_result(reply)
        verdict = parse_verdict(_extract_agent_text(parsed))
        assert verdict["decision"] == "pass"
        assert verdict["note"] == "smoke test"

    def test_a_block_verdict_still_blocks(self) -> None:
        fragment = (
            '..."result":"<verdict>\\ndecision: block\\nnote: not good\\n'
            '</verdict>","type":"result"}'
        )
        reply = _extract_reply_text(_CallResult(_envelope(fragment)))
        verdict = parse_verdict(_extract_agent_text(_parse_pool_result(reply)))
        assert verdict["decision"] == "block"
        assert verdict["note"] == "not good"


class TestTheFailureReasonSurvives:
    """A run that did not finish must say why.

    The pool's status lives in its *envelope*; the worker's output is a
    separate field of that envelope. Reducing the envelope to the output
    first -- which is what the verdict path does -- throws the status
    away, and a reviewer that timed out then read as a "malformed
    verdict": a review that was cut off looked like a review that had
    no opinion.
    """

    def test_a_timeout_names_the_timeout(self) -> None:
        envelope = json.dumps(
            {
                "pool_id": "mahavishnu_1",
                "worker_id": "worker-1",
                "status": "timeout",
                "output": "partial stream, no verdict here",
                "error": "CLI did not emit any completion marker within 300.0s",
            }
        )
        message = _pool_failure_message(envelope)
        assert message is not None
        assert "completion marker" in message

    def test_a_timeout_without_an_error_still_names_the_timeout(self) -> None:
        message = _pool_failure_message(json.dumps({"status": "timeout"}))
        assert message is not None
        assert "timeout" in message.lower()

    def test_a_failed_run_reports_its_error(self) -> None:
        envelope = json.dumps(
            {
                "status": "failed",
                "output": "partial stream, no verdict here",
                "error": "the worker died",
            }
        )
        assert _pool_failure_message(envelope) == "the worker died"

    def test_a_completed_run_has_no_failure_message(self) -> None:
        envelope = json.dumps({"status": "completed", "output": "the verdict"})
        assert _pool_failure_message(envelope) is None

    def test_the_envelope_is_checked_before_the_output_is_reduced(self) -> None:
        """The status is in the envelope; the output has no status."""
        envelope = json.dumps(
            {
                "status": "failed",
                "output": "partial stream, no verdict here",
                "error": "the worker died",
            }
        )
        assert _parse_pool_result(envelope) == "partial stream, no verdict here"
        assert _pool_failure_message(envelope) == "the worker died"


class _FakeClient:
    """A stand-in for ``CommonMCPClient`` that returns a fixed payload."""

    def __init__(self, payload: str) -> None:
        self._payload = payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> _CallResult:
        assert name == "mahavishnu_pool_route_execute"
        assert arguments
        return _CallResult(self._payload)


class TestTheDispatchReportsWhyItFailed:
    @pytest.mark.asyncio
    async def test_a_timed_out_review_blocks_with_the_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        envelope = json.dumps(
            {
                "pool_id": "mahavishnu_1",
                "status": "timeout",
                "output": "partial stream, no verdict here",
                "error": "CLI did not emit any completion marker within 900.0s",
            }
        )
        monkeypatch.setattr(
            "mahavishnu.core.merge_review_dispatcher._call_tool_over_http",
            _fake_call(envelope),
        )
        reply = await dispatch_review_async("python-pro", "review this")
        verdict = parse_verdict(reply)
        assert verdict["decision"] == "block"
        assert "completion marker" in verdict["note"]

    @pytest.mark.asyncio
    async def test_a_finished_review_still_yields_its_verdict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        envelope = _envelope(STREAM_FRAGMENT)
        monkeypatch.setattr(
            "mahavishnu.core.merge_review_dispatcher._call_tool_over_http",
            _fake_call(envelope),
        )
        reply = await dispatch_review_async("python-pro", "review this")
        verdict = parse_verdict(reply)
        assert verdict["decision"] == "pass"
        assert verdict["note"] == "smoke test"


class TestTheReviewBudget:
    def test_the_server_side_budget_outlasts_a_real_review(self) -> None:
        """The ceiling the pool enforces has to carry a full review.

        At 300 s the worker was cut off mid-review; the pool reported a
        timeout with a partial pane, the reply carried no verdict, and
        every merge blocked on a "malformed verdict" that was really a
        reviewer that never finished. At 900 s the reviewer was still
        reading the changed files, so the budget has to carry a full
        read of the diff with room to spare. At 1800 s the domain
        specialist was still reading them -- it made eighty tool calls
        at about twenty seconds each.
        """
        assert REVIEW_DISPATCH_TIMEOUT >= 3600

    def test_the_prompt_states_the_budget_the_reviewer_really_has(self) -> None:
        """The reviewer is told the budget that is real.

        The prompt used to say "about three minutes" and to claim the
        transport cut the reviewer off. Neither was true. The
        dispatch's budget is ``REVIEW_DISPATCH_TIMEOUT`` -- an hour --
        and the transport's read timeout is a *per-event* timeout that
        the server's heartbeats keep from firing; reviews in this repo
        have run to 855 s and 1168 s and finished.

        A prompt that states a budget three times too short makes a
        reviewer rush, and a reviewer that rushes writes a long reply
        to compensate -- which is what pushes it past the capture
        bound. So the number the prompt states has to be the number
        the dispatch enforces.
        """
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))

        assert f"{int(REVIEW_DISPATCH_TIMEOUT // 60)} minutes" in prompt
        assert "read only the files you need" in prompt

    def test_the_prompt_does_not_claim_a_cut_off_that_does_not_happen(self) -> None:
        """The prompt must not assert a cut-off that never fires.

        Telling a reviewer it will be torn down after three minutes
        makes it treat a full read of the diff as a luxury, and the
        verdict it then produces is the one the merge is judged on.
        """
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))

        assert "about three minutes" not in prompt
        assert "cut off after that" not in prompt

    def test_the_prompt_does_not_assert_an_unconfirmed_mechanism(self) -> None:
        """The prompt states a ceiling; it does not claim what enforces it.

        The client's httpx read timeout is 300 s on a quiet stream,
        and the server's dispatch heartbeat is a no-op for a client
        that sends no progress token -- which this one does not. So
        "the transport is not what cuts you off" was a specific claim
        about a mechanism that was never confirmed. What was measured
        is that the call survives: a call held open for 420 s came
        back with its payload intact.
        """
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))

        assert "the transport is not what cuts you off" not in prompt
        assert "do not plan on spending it" in prompt

    def test_the_constant_does_not_assert_the_mechanism_either(self) -> None:
        """The prompt and the constant it reads must not disagree.

        A reviewer caught the prompt claiming an hour while the
        constant's own comment said the transport cut a reviewer off
        and that "the budget the reviewer actually has is minutes, not
        an hour". Nothing reads that comment but a human, so the stale
        claim is pinned here.
        """
        import inspect

        from mahavishnu.core import merge_review_dispatcher

        source = inspect.getsource(merge_review_dispatcher)

        assert "minutes, not an hour" not in source

    def test_the_budget_is_stated_even_without_a_diff_summary(self) -> None:
        """The budget is a property of the dispatch, not the summary."""
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))

        assert "could not be summarized automatically" in prompt
        assert f"{int(REVIEW_DISPATCH_TIMEOUT // 60)} minutes" in prompt


class TestTheReplyBudget:
    """The prompt's reply budget has to match what the capture can hold.

    The reply is read back out of the worker's terminal pane. The
    prompt used to state a budget of "about 1,500 characters" and
    explain it as "the pool captures the last screenful of your
    terminal" -- which described the capture accurately at the time,
    but also told the reviewer to write a reply that would exactly
    fill a screenful. The capture now reads the scrollback, so the
    budget is larger; and the note length the prompt quotes was 600
    while the sanitizer caps a note at 500.
    """

    def test_the_note_length_the_prompt_gives_is_the_cap_that_is_enforced(self) -> None:
        """One source of truth for the note length.

        A reviewer that trusted the prompt's 600 characters could
        write a note that the sanitizer then truncated.
        """
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))

        assert f"under {MAX_NOTE_LENGTH} characters" in prompt

    def test_the_prompt_does_not_describe_the_capture_by_its_old_shape(self) -> None:
        """The prompt must not explain the budget by the capture's shape.

        It used to say the pool "captures the last screenful of your
        terminal". The capture no longer reads one screenful, and a
        prompt that describes it that way tells a reviewer its reply
        is cut at a screenful's worth -- which is the belief that
        produced the long replies. What the reviewer needs to know is
        that the read is bounded, and by how much.
        """
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))

        assert "captures the last screenful" not in prompt
        assert "the read is bounded" in prompt

    def test_the_prompt_still_asks_for_the_verdict_block_last(self) -> None:
        """The block stays last: the read-back is bounded at the end.

        The capture keeps the newest bytes, so a reply that runs past
        the bound loses its beginning. The verdict block is the one
        part of the reply that must never be the part that is lost.
        """
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))

        assert "verdict block LAST" in prompt

    def test_the_reply_budget_fits_what_the_smallest_capture_holds(self) -> None:
        """The advice has to fit a capture smaller than this repo's.

        The capture reads the pane's scrollback, so the reply could be
        far longer than the prompt's budget. The budget is the advice
        that keeps a review inside its budget, and it has to survive a
        capture that is smaller than the one this repo runs: the
        visible pane is 24 rows of 80 columns, and a reply past about
        that used to arrive with its opening cut off -- which reads as
        a malformed verdict and blocks the merge on a review that ran
        perfectly well.
        """
        assert REVIEW_REPLY_BUDGET_CHARS <= 24 * 80


class TestTheReviewPrompt:
    """The prompt has to bound the work, not just describe it.

    A reviewer that runs the test suite spends its whole budget there:
    the first reviewer on this branch spent ten of its fourteen minutes
    in ``pytest`` runs, over a suite the merge pipeline runs again as
    its own quality gate. The prompt says the suite is not the
    reviewer's job.
    """

    def test_the_prompt_keeps_the_suite_out_of_the_review(self) -> None:
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))
        assert "merge pipeline runs the quality gate" in prompt

    def test_the_prompt_names_the_runners_to_avoid(self) -> None:
        """Naming them is what stops the agent that runs gates by habit.

        The domain specialist's own agent definition tells it to run
        the quality gates, so "do not run the test suite" alone did not
        stop it: it ran five pytest invocations and burned the budget
        on the pipeline's own work.
        """
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))
        lowered = prompt.lower()
        assert "pytest" in lowered
        assert "crackerjack" in lowered

    def test_the_prompt_keeps_the_reviewer_read_only(self) -> None:
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))
        assert "do not modify" in prompt.lower()

    def test_the_prompt_says_how_to_run_the_version_control_commands(
        self,
    ) -> None:
        """A refused command leaves the review with nothing to judge.

        The reviewers run under the harness's permission check, which
        refuses a command that changes directory before a
        version-control command, and refuses a command it cannot check
        before running it -- a ``cd ... && git ...`` chain, a ``;``
        chain, or a shell variable. A reviewer's ``git diff`` was
        refused that way, and the reviewer had no diff to judge, so it
        replied without a verdict: an unreadable verdict, which is a
        block. The prompt has to say how to run the commands instead.
        """
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))
        lowered = prompt.lower()
        assert "no `cd` in front" in lowered
        assert "one command at a time" in lowered
        assert "no verdict at all" in lowered

    def test_the_prompt_still_asks_for_the_verdict_block(self) -> None:
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))
        assert "<verdict>" in prompt
        assert "decision: pass|needs_adjustment|block" in prompt

    def test_a_quoted_verdict_block_does_not_hide_the_real_one(self) -> None:
        """The last verdict block is the answer, not the first.

        The prompt lets the reviewer put its analysis before the verdict
        block, and an analysis that quotes a line of code carries a
        literal ``<verdict>...</verdict>`` in it. A review of this
        branch quoted the integration test's own reply-builder line, and
        the parser took the quote as the verdict: the reviewer had said
        ``decision: pass``, and the merge read a note that was a
        fragment of Python.
        """
        reply = (
            "The reply builder in the test reads\n"
            '    return "<verdict>decision: pass note: " + '
            'body[:REPLY_LENGTH] + "</verdict>"\n'
            "which is fine.\n"
            "<verdict>decision: needs_adjustment "
            "note: the capture still cuts the reply</verdict>"
        )

        verdict = parse_verdict(reply)

        assert verdict["decision"] == "needs_adjustment"
        assert verdict["note"] == "the capture still cuts the reply"

    def test_a_verdict_block_with_no_known_decision_does_not_win(self) -> None:
        """Prose that opens a block without a decision is skipped.

        A reviewer that writes ``<verdict>`` in its analysis and does
        not name a decision in it would otherwise swallow the real
        block that follows, and the review would read as malformed.
        The block needs a decision right after the tag to match at all.
        """
        reply = (
            "The prompt shows a <verdict> block like this\n"
            "<verdict>decision: needs_adjustment note: the real one</verdict>"
        )

        verdict = parse_verdict(reply)

        assert verdict["decision"] == "needs_adjustment"
        assert verdict["note"] == "the real one"

    def test_a_typo_in_the_last_block_is_not_papered_over(self) -> None:
        """A decision the pipeline does not know is a malformed verdict.

        Reading an earlier block instead would report a quote as the
        reviewer's answer and hide the answer it did give -- and the
        review would pass on the strength of a line of code.
        """
        reply = (
            "<verdict>decision: pass note: an earlier quote</verdict>\n"
            "<verdict>decision: maybe</verdict>"
        )

        verdict = parse_verdict(reply)

        assert verdict["decision"] == "block"
        assert "unknown decision" in verdict["note"]

    def test_the_prompt_bounds_the_reply_to_the_capture_window(self) -> None:
        """The reply has to fit inside the capture's bound.

        The capture reads the worker's terminal scrollback and keeps
        the newest bytes inside a fixed bound. A reply that runs past
        the bound arrives with its opening cut off, and the verdict
        cannot be parsed. So the reply has to be the block, and short
        enough to fit.
        """
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))
        assert "nothing outside it" in prompt.lower()
        assert f"under {MAX_NOTE_LENGTH} characters" in prompt
        assert f"under about {REVIEW_REPLY_BUDGET_CHARS:,} characters" in prompt

    def test_the_prompt_still_points_at_the_worktree(self) -> None:
        """Whichever branch the diff takes, the reviewer is sent to the tree."""
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))
        assert "Worktree: /tmp" in prompt
        assert "worktree path above" in prompt

    def test_the_prompt_pins_every_path_to_the_worktree(self) -> None:
        """The reviewer's shell starts in an isolated checkout.

        The pool launches the worker's CLI in the worktree it created
        for this review -- a different directory holding the same
        commit as the branch under review. It is no longer the server's
        working directory, so the prompt says so: a reviewer that
        reads a relative path would review whatever its shell happens
        to be in, so every path is spelled out.
        """
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))
        assert "isolated checkout of the branch under review" in prompt
        assert "absolute path under the worktree path above" in prompt

    def test_the_prompt_requires_the_verdict_block_last(self) -> None:
        """The capture keeps the tail, so the block has to be at the end.

        The capture reads the worker's terminal scrollback and keeps
        the newest bytes within its bound. A verdict block written
        before that cut is simply gone, so the block must be the last
        thing the reviewer writes.
        """
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))
        assert "verdict block LAST" in prompt
        assert "before it, never after it" in prompt


class TestTheRepositoryTokenRoundTrips:
    """The prompt's repository token and the pool's reader agree.

    The cross-repo fix is a seam between two sides: the merge pipeline
    writes the repository into the prompt, and the pool reads it back
    out to know where to fork the reviewer's worktree. A test on
    either side alone would pass while the seam was broken — and the
    seam is the whole fix. A merge reviewing a branch in another
    repository asked for a worktree of a branch that did not exist
    there, and every cross-repo merge died at stage 2.
    """

    @pytest.mark.asyncio
    async def test_the_token_the_prompt_writes_is_the_one_the_pool_reads(
        self, tmp_path: Path
    ) -> None:
        from mahavishnu.mcp.tools.pool_tools import _resolve_repo_nickname

        repo = tmp_path / "crackerjack"
        repo.mkdir()

        prompt = build_review_prompt("feat/x", "main", tmp_path, repo)

        assert f"Repository: {repo}/.git" in prompt
        nickname = await _resolve_repo_nickname(prompt)
        assert Path(nickname) == repo

    def test_without_a_repository_the_prompt_names_none(self) -> None:
        """The prompt says nothing about a repository it was not told."""
        prompt = build_review_prompt("feat/x", "main", Path("/tmp"))

        assert "Repository:" not in prompt


class _PoolClient:
    """A ``CommonMCPClient`` stand-in that answers the pool tools.

    It models what the server does: a successful spawn puts the new
    pool in the listing, so the next list call reports a pool that
    can honour a working directory.
    """

    def __init__(self, pools: list[dict[str, Any]]) -> None:
        self._pools = pools
        #: Every tool call made, so a test can assert what the
        #: dispatcher asked the server for.
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> _CallResult:
        self.calls.append((name, arguments))
        if name == "mahavishnu_pool_list":
            return _CallResult(json.dumps(self._pools))
        self._pools.append(
            {
                "name": arguments.get("name"),
                "supports_working_directory": True,
            }
        )
        return _CallResult(json.dumps({"status": "spawned"}))


class TestTheReviewPoolIsProvisioned:
    """Isolation needs a pool that can honour a working directory.

    Only a one-shot SHELL worker starts its session when the task
    arrives, so it can start *in* the worktree. The auto-spawned pool
    is a pre-spawned shepherd pool, which cannot — so a merge that
    asked for isolation found no pool able to honour the directory and
    every merge stopped at stage 2 with an instruction to spawn one by
    hand. The pipeline knows it needs the capability, so the pipeline
    provides it.
    """

    @pytest.mark.asyncio
    async def test_the_review_pool_is_spawned_when_it_is_not_registered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _PoolClient([{"name": "default", "supports_working_directory": False}])
        monkeypatch.setattr(
            "mcp_common.clients.common_mcp_client.CommonMCPClient",
            lambda **kwargs: client,
        )

        assert await ensure_review_pool_async() is True

        spawns = [c for c in client.calls if c[0] == "mahavishnu_pool_spawn"]
        assert len(spawns) == 1
        _name, args = spawns[0]
        assert args["name"] == "merge-review"
        assert args["worker_type"] == "terminal-claude"

    @pytest.mark.asyncio
    async def test_a_registered_review_pool_is_left_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pool is created once, not once per merge."""
        client = _PoolClient(
            [{"name": "merge-review", "supports_working_directory": True}]
        )
        monkeypatch.setattr(
            "mcp_common.clients.common_mcp_client.CommonMCPClient",
            lambda **kwargs: client,
        )

        assert await ensure_review_pool_async() is True

        assert [c for c in client.calls if c[0] == "mahavishnu_pool_spawn"] == []

    @pytest.mark.asyncio
    async def test_the_check_is_by_name_not_by_capability(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The client does not need the server to report the capability.

        The capability belongs to the server, which is where the
        routing happens. A client that had to read a capability field
        would break against a server that does not carry it, and the
        merge would stop at stage 2 for a reason that has nothing to
        do with the code being merged.
        """
        client = _PoolClient([{"name": "merge-review"}])
        monkeypatch.setattr(
            "mcp_common.clients.common_mcp_client.CommonMCPClient",
            lambda **kwargs: client,
        )

        assert await ensure_review_pool_async() is True

        assert [c for c in client.calls if c[0] == "mahavishnu_pool_spawn"] == []

    @pytest.mark.asyncio
    async def test_a_server_that_cannot_be_reached_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The dispatch that follows reports the real error.

        A provisioning failure that masked the dispatch's own error
        would replace the reason with a misleading one.
        """

        class _Broken:
            async def __aenter__(self) -> Self:
                raise RuntimeError("the server is down")

            async def __aexit__(self, *exc_info: object) -> None:
                return None

            async def call_tool(
                self, name: str, arguments: dict[str, Any]
            ) -> _CallResult:
                raise RuntimeError("the server is down")

        monkeypatch.setattr(
            "mcp_common.clients.common_mcp_client.CommonMCPClient",
            lambda **kwargs: _Broken(),
        )

        assert await ensure_review_pool_async() is False


class TestTheProvisioningOutcomeIsChecked:
    """The spawn tool reports failure as data, not as an exception.

    ``mahavishnu_pool_spawn`` never raises: it returns
    ``{"status": "failed", "error": "..."}``. A provisioning step that
    ignored that data would report success for a pool that was never
    created, and the operator would then be told to spawn one by hand
    — advice the pipeline had already tried.
    """

    @pytest.mark.asyncio
    async def test_a_failed_spawn_is_not_reported_as_provisioned(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The spawn's own reason survives, and success is not claimed.

        The failure the operator has to act on is the spawn's, not a
        later, vaguer one. Logging "provisioned" for a pool that was
        never created would send them looking in the wrong place.
        """

        class _FailingSpawn(_PoolClient):
            async def call_tool(
                self, name: str, arguments: dict[str, Any]
            ) -> _CallResult:
                self.calls.append((name, arguments))
                if name == "mahavishnu_pool_list":
                    return _CallResult(json.dumps([]))
                return _CallResult(
                    json.dumps({"status": "failed", "error": "no capacity"})
                )

        client = _FailingSpawn([])
        monkeypatch.setattr(
            "mcp_common.clients.common_mcp_client.CommonMCPClient",
            lambda **kwargs: client,
        )

        with caplog.at_level(logging.WARNING):
            assert await ensure_review_pool_async() is False

        assert "no capacity" in caplog.text, "the spawn's reason was lost"
        assert "provisioned the" not in caplog.text, "success was claimed"

    @pytest.mark.asyncio
    async def test_a_pool_of_that_name_in_the_wrong_form_is_the_servers_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The client cannot tell, so the server refuses and says so.

        A pool named ``merge-review`` that cannot honour a directory
        is a real state — the operator may have created it as a
        shepherd pool. The client cannot see that, but the server can,
        and the server's refusal names the pool and the remedy. What
        the client must not do is report success it did not verify.
        """

        class _IncapablePool(_PoolClient):
            async def call_tool(
                self, name: str, arguments: dict[str, Any]
            ) -> _CallResult:
                self.calls.append((name, arguments))
                if name == "mahavishnu_pool_list":
                    return _CallResult(
                        json.dumps(
                            [
                                {
                                    "name": "merge-review",
                                    "supports_working_directory": False,
                                }
                            ]
                        )
                    )
                return _CallResult(json.dumps({"status": "exists"}))

        client = _IncapablePool([])
        monkeypatch.setattr(
            "mcp_common.clients.common_mcp_client.CommonMCPClient",
            lambda **kwargs: client,
        )

        # The pool exists, so the client has nothing to provision and
        # does not claim to have provisioned anything.
        assert await ensure_review_pool_async() is True


class TestTheRefusalLabelsAreTheOnesTheCodeEmits:
    """A dashboard query written from the docs has to match.

    The counter's reason labels are documented in the metrics module
    and cited by the runbook. They drifted from the code once already:
    the comment said ``repo_unresolved`` and ``repo_not_authorized``
    while the code emitted ``unresolved`` and ``not_authorized``, so
    two of the five labels never appeared on the counter the runbook
    told the on-call engineer to read.
    """

    def test_the_documented_labels_are_the_emitted_ones(self) -> None:
        from mahavishnu.core import _producer_metrics
        from mahavishnu.mcp.tools.pool_tools import (
            REPO_NOT_A_GIT_REPO,
            REPO_NOT_AUTHORIZED,
            REPO_SETTINGS_UNAVAILABLE,
            REPO_UNRESOLVED,
        )

        emitted = {
            REPO_UNRESOLVED,
            REPO_NOT_AUTHORIZED,
            REPO_NOT_A_GIT_REPO,
            REPO_SETTINGS_UNAVAILABLE,
            "no_capable_pool",
            "pool_cannot_honour_cwd",
        }
        source = Path(_producer_metrics.__file__).read_text()

        for label in emitted:
            assert f"#     {label} " in source, (
                f"{label!r} is emitted but not documented in the metrics module"
            )

    def test_the_runbook_cites_only_emitted_labels(self) -> None:
        from pathlib import Path as _Path

        from mahavishnu.mcp.tools.pool_tools import (
            REPO_NOT_A_GIT_REPO,
            REPO_NOT_AUTHORIZED,
            REPO_SETTINGS_UNAVAILABLE,
            REPO_UNRESOLVED,
        )

        emitted = {
            REPO_UNRESOLVED,
            REPO_NOT_AUTHORIZED,
            REPO_NOT_A_GIT_REPO,
            REPO_SETTINGS_UNAVAILABLE,
            "no_capable_pool",
            "pool_cannot_honour_cwd",
        }
        runbook = _Path("docs/runbooks/WORKTREE_ISOLATION.md").read_text()

        for label in emitted:
            assert f'reason="{label}"' in runbook, (
                f"{label!r} is emitted but the runbook does not cite it"
            )


class _FakeHttpClient:
    """An httpx client stand-in that records the timeout it was built with."""

    def __init__(self, *, timeout: Any = None, **kwargs: Any) -> None:
        captured_timeouts.append(timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _FakeSession:
    """An MCP session stand-in."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def initialize(self) -> None:
        return None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        called_tools.append(name)
        return "ok"


class _FakeStreams:
    """The transport's stand-in: it yields the two streams, and nothing else."""

    def __init__(self, value: Any) -> None:
        self._value = value

    async def __aenter__(self) -> Any:
        return self._value

    async def __aexit__(self, *exc_info: object) -> None:
        return None


#: The timeouts the fake HTTP clients were built with, and the tools
#: the fake sessions were asked for.
captured_timeouts: list[Any] = []
called_tools: list[str] = []


def _patch_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the transport and the SDK's client stand-ins."""

    def _fake_transport(url: str, *, http_client: Any = None, **kwargs: Any) -> Any:
        return _FakeStreams((object(), object()))

    monkeypatch.setattr("httpx2.AsyncClient", _FakeHttpClient)
    monkeypatch.setattr(
        "mcp.client.streamable_http.streamable_http_client", _fake_transport
    )
    monkeypatch.setattr("mcp.client.session.ClientSession", _FakeSession)


class TestTheTransportCarriesTheBudget:
    """The call must last as long as the review does.

    The MCP SDK builds its default HTTP client with a 300 s read
    timeout, and the shared client only hands its own ``timeout`` to
    that client when the server requires a token. A review dispatch is
    idle for minutes while the reviewer reads the diff and thinks, and
    an idle stream is exactly what a read timeout cuts: the call comes
    back with no reply and the review reads as a malformed verdict
    rather than as a reviewer that ran out of time.

    Measured: a dispatch whose worker slept 420 s was cut at 324 s,
    before the work was done.
    """

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        captured_timeouts.clear()
        called_tools.clear()

    async def test_the_read_timeout_is_the_one_the_caller_asked_for(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The transport is built with the budget, not with a default."""
        _patch_transport(monkeypatch)

        result = await _call_tool_over_http(
            "http://localhost:8680/mcp",
            "mahavishnu_pool_route_execute",
            {"prompt": "review this"},
            read_timeout=3600.0,
        )

        assert result == "ok"
        assert called_tools == ["mahavishnu_pool_route_execute"]
        assert captured_timeouts, "the transport was built with no timeout"
        timeout = captured_timeouts[0]
        assert timeout.read == 3600.0, (
            "the read timeout is the budget the review was given"
        )

    async def test_the_transport_does_not_fall_back_to_the_sdk_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The SDK's 300 s default must not be what a review runs on."""
        import mcp.shared._httpx_utils as httpx_utils

        _patch_transport(monkeypatch)

        await _call_tool_over_http(
            "http://localhost:8680/mcp",
            "mahavishnu_pool_route_execute",
            {},
            read_timeout=REVIEW_DISPATCH_TIMEOUT,
        )

        assert captured_timeouts[0].read == REVIEW_DISPATCH_TIMEOUT
        assert captured_timeouts[0].read != httpx_utils.MCP_DEFAULT_SSE_READ_TIMEOUT
