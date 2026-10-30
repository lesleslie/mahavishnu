"""Unit tests for the workflow-id path guard.

A workflow id is spliced into a substrate key path
(``workflow-results/{workflow_id}/``), so it must be a safe single path
segment. The character class alone is not enough: "." and ".." both
match it but are traversal segments, and a trailing newline slips past
``re.match`` because ``$`` also matches before one.
"""

from __future__ import annotations

import pytest

from mahavishnu.mcp.tools._workflow_id_guard import (
    FORBIDDEN_WORKFLOW_ID_SEGMENTS,
    validate_workflow_id,
)


@pytest.mark.unit
def test_a_normal_workflow_id_is_accepted() -> None:
    assert validate_workflow_id("wf_1a2b3c4d_code_review") is True
    assert validate_workflow_id("wf-abc.def") is True


@pytest.mark.unit
def test_dot_segments_are_rejected() -> None:
    """They match the character class but are traversal segments."""
    assert validate_workflow_id(".") is False
    assert validate_workflow_id("..") is False
    assert FORBIDDEN_WORKFLOW_ID_SEGMENTS == {".", ".."}


@pytest.mark.unit
def test_a_trailing_newline_is_rejected() -> None:
    """``re.match`` would accept this: ``$`` also matches before a newline."""
    assert validate_workflow_id("wf_abc\n") is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    ["wf abc", "wf/abc", "wf\\abc", "wf\x00abc", "", "x" * 129],
)
def test_malformed_ids_are_rejected(value: str) -> None:
    assert validate_workflow_id(value) is False


@pytest.mark.unit
def test_the_guard_agrees_with_session_buddy() -> None:
    """The two repos must reject the same values.

    session-buddy validates the id at the link channel; mahavishnu
    validates it where it is consumed. If they disagree, a value one
    side accepts would be rejected by the other at the worst moment.
    """
    try:
        from session_buddy.mcp.tools.tasks_models import (
            WORKFLOW_ID_FORBIDDEN_SEGMENTS,
            WORKFLOW_ID_PATTERN,
        )
    except ImportError:
        pytest.skip("session-buddy does not expose the task-system models")

    for value in ("wf_ok-1.2", ".", "..", "wf abc", "wf_abc\n", ""):
        upstream_ok = value not in WORKFLOW_ID_FORBIDDEN_SEGMENTS and bool(
            WORKFLOW_ID_PATTERN.fullmatch(value)
        )
        local_ok = validate_workflow_id(value)
        assert upstream_ok == local_ok, f"the repos disagree on {value!r}"
