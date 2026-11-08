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
from typing import Any, Self

import pytest

from mahavishnu.core.merge_review_dispatcher import (
    REVIEW_DISPATCH_TIMEOUT,
    _extract_agent_text,
    _extract_reply_text,
    _parse_pool_result,
    _pool_failure_message,
    dispatch_review_async,
)
from mahavishnu.core.merge_to_main import parse_verdict

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
        assert name == "pool_route_execute"
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
            "mcp_common.clients.common_mcp_client.CommonMCPClient",
            lambda **kwargs: _FakeClient(envelope),
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
            "mcp_common.clients.common_mcp_client.CommonMCPClient",
            lambda **kwargs: _FakeClient(envelope),
        )
        reply = await dispatch_review_async("python-pro", "review this")
        verdict = parse_verdict(reply)
        assert verdict["decision"] == "pass"
        assert verdict["note"] == "smoke test"


class TestTheReviewBudget:
    def test_the_budget_outlasts_a_real_review(self) -> None:
        """A review of a multi-commit diff takes minutes, not seconds.

        At 300 s the worker was cut off mid-review; the pool reported a
        timeout with a partial pane, the reply carried no verdict, and
        every merge blocked on a "malformed verdict" that was really a
        reviewer that never finished.
        """
        assert REVIEW_DISPATCH_TIMEOUT >= 900
