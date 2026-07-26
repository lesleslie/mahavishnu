from __future__ import annotations

import pytest

from mahavishnu.workers.generic_shell import GenericShellWorker


def _make_worker(completion_markers: list[str]) -> GenericShellWorker:
    """Bypass __init__ to call the instance method directly.

    The brief assumed a class-level signature; the actual signature is
    an instance method that reads self.config.{completion_markers,
    error_markers, complete_on_valid_json}. ``object.__new__`` plus a
    minimal config stub exercises the method without invoking the real
    constructor.
    """
    worker = object.__new__(GenericShellWorker)
    worker.config = type(
        "Config",
        (),
        {
            "completion_markers": completion_markers,
            "error_markers": [],
            "complete_on_valid_json": False,
        },
    )()
    return worker


def test_check_json_completion_recognises_result_type() -> None:
    """Top-level Claude stream-json result events signal completion
    even when finish_reason is absent.
    """
    output = (
        '{"type":"system","subtype":"init","cwd":"/x"}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}\n'
        '{"type":"result","result":"done","duration_ms":12}\n'
    )

    completed, _ = _make_worker(["finish_reason"])._check_json_completion(output)
    assert completed is True


def test_result_with_parent_tool_use_id_does_not_complete() -> None:
    """Tool-result blocks carry a parent_tool_use_id and must NOT complete
    the worker — only top-level result events do. Locks the
    ``parent_tool_use_id is None`` guard against future regressions.
    """
    output = (
        '{"type":"assistant","message":{}}\n'
        '{"type":"result","result":"tool output","parent_tool_use_id":"toolu_abc"}\n'
    )

    completed, _ = _make_worker(
        ["finish_reason"]
    )._check_json_completion(output)
    assert completed is False
