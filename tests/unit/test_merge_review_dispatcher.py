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

from mahavishnu.core.merge_review_dispatcher import (
    _extract_agent_text,
    _extract_reply_text,
    _parse_pool_result,
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
