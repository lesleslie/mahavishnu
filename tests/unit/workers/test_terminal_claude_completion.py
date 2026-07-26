from __future__ import annotations

from mahavishnu.workers.generic_shell import GenericShellWorker


def test_check_json_completion_recognises_result_type() -> None:
    """Claude stream-json result events signal completion without finish_reason."""
    output = (
        '{"type":"system","subtype":"init","cwd":"/x"}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}\n'
        '{"type":"result","result":"done","duration_ms":12}\n'
    )

    worker = object.__new__(GenericShellWorker)
    worker.config = type(
        "Config",
        (),
        {
            "completion_markers": ["finish_reason"],
            "error_markers": [],
            "complete_on_valid_json": False,
        },
    )()

    completed, _ = worker._check_json_completion(output)
    assert completed is True
