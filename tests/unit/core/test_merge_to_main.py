"""Tests for mahavishnu.core.merge_to_main — orchestration of the trunk-based
agent-review workflow (REQ-004, REQ-013, REQ-014).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.core.merge_to_main import (
    _CODE_QUALITY_AGENT,
    AGENT_POOL,
    CRACKERJACK_INVOCATION,
    EXIT_CRACKERJACK_FAILURE,
    EXIT_OK,
    EXIT_REVIEW_FAILURE,
    REVIEW_STATE_SCHEMA_VERSION,
    aggregate_verdicts,
    parse_verdict,
    read_review_state,
    run_crackerjack_gate,
    run_pipeline,
    run_review,
    write_review_state,
)


def test_review_state_round_trip(tmp_path: Path) -> None:
    """write_review_state then read_review_state returns equivalent dict."""
    state = {
        "schema_version": REVIEW_STATE_SCHEMA_VERSION,
        "ephemeral_branch": "fix-ty",
        "base": "origin/main",
        "pre_rebase_base_sha": "b116d395",
        "stages_completed": ["stage_1_worktree", "stage_2_review"],
        "current_stage": "stage_3_gate",
        "stage_failed": None,
        "reviewers_invoked": [
            {"agent": "python-pro", "verdict": "pass", "timestamp": "2026-10-03T15:32:11Z"}
        ],
        "audit_log_path": None,
        "session_buddy_reflection_id": None,
    }
    write_review_state(tmp_path, state)
    loaded = read_review_state(tmp_path)
    assert loaded == state


def test_read_review_state_corrupt_json_returns_none(tmp_path: Path) -> None:
    """Corrupt JSON falls back to None (spec REQ-014 graceful handling)."""
    (tmp_path / ".review-state.json").write_text("not valid json {{{")
    assert read_review_state(tmp_path) is None


def test_read_review_state_missing_returns_none(tmp_path: Path) -> None:
    """Missing file returns None."""
    assert read_review_state(tmp_path) is None


def test_parse_verdict_pass_block() -> None:
    """Well-formed <verdict>decision: pass</verdict> returns decision='pass'."""
    response = (
        "Reviewed the diff; no issues found.\n"
        "<verdict>\n"
        "  decision: pass\n"
        "  note: Looks correct, types check out.\n"
        "</verdict>\n"
    )
    result = parse_verdict(response)
    assert result["decision"] == "pass"
    assert "Looks correct" in result["note"]


def test_parse_verdict_block_decision() -> None:
    """Well-formed block decision returns decision='block' (not a parse error)."""
    response = (
        "<verdict>\n"
        "  decision: block\n"
        "  note: Security vulnerability in auth path.\n"
        "</verdict>\n"
    )
    result = parse_verdict(response)
    assert result["decision"] == "block"
    assert "Security" in result["note"]


def test_parse_verdict_missing_block_returns_block() -> None:
    """Missing <verdict> block returns block decision (fail-loud per spec §4.4)."""
    response = "No verdict marker here, just prose with no closing tag."
    result = parse_verdict(response)
    assert result["decision"] == "block"
    assert "malformed" in result["note"].lower()


def test_parse_verdict_invalid_decision_returns_block() -> None:
    """<verdict> block with unknown decision value returns block (fail-loud)."""
    response = (
        "<verdict>\n"
        "  decision: maybe\n"
        "  note: not sure\n"
        "</verdict>\n"
    )
    result = parse_verdict(response)
    assert result["decision"] == "block"
    assert "malformed" in result["note"].lower()


def test_parse_verdict_needs_adjustment() -> None:
    text = (
        "<verdict>\n"
        "  decision: needs_adjustment\n"
        "  note: missing type hints on public functions\n"
        "</verdict>\n"
    )
    assert parse_verdict(text) == {
        "decision": "needs_adjustment",
        "note": "missing type hints on public functions",
    }


def test_run_review_three_agents_in_dispatch_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_review dispatches to domain + code-quality + random generalist in order.

    Each agent's response is parsed via parse_verdict. The generalist is
    drawn from the supplied pool via random.choice; monkeypatched here to
    a known agent for determinism.
    """
    domain = "python-pro"
    pool = ["performance-review-specialist", "test-coverage-review-specialist"]
    monkeypatch.setattr("mahavishnu.core.merge_to_main.random.choice", lambda _: pool[1])

    canned = {
        domain: "<verdict>decision: pass note: looks good</verdict>",
        _CODE_QUALITY_AGENT: "<verdict>decision: needs_adjustment note: lint</verdict>",
        pool[1]: "<verdict>decision: pass note: ok</verdict>",
    }
    calls: list[tuple[str, str]] = []

    def dispatcher(agent: str, prompt: str) -> str:
        calls.append((agent, prompt))
        return canned[agent]

    results = run_review(domain, pool, "review this diff", dispatcher)

    assert calls == [
        (domain, "review this diff"),
        (_CODE_QUALITY_AGENT, "review this diff"),
        (pool[1], "review this diff"),
    ]
    assert results == [
        {"agent": domain, "decision": "pass", "note": "looks good"},
        {"agent": _CODE_QUALITY_AGENT, "decision": "needs_adjustment", "note": "lint"},
        {"agent": pool[1], "decision": "pass", "note": "ok"},
    ]
    assert len(AGENT_POOL) == 7
    # The spec allows _CODE_QUALITY_AGENT to overlap with AGENT_POOL; we don't
    # assert membership either way, but we do confirm the pool is the documented size.


def test_aggregate_any_block_blocks() -> None:
    verdicts = [
        {"decision": "pass", "note": ""},
        {"decision": "block", "note": "x"},
        {"decision": "pass", "note": ""},
    ]
    assert aggregate_verdicts(verdicts) == "block"


def test_aggregate_two_pass_proceeds() -> None:
    verdicts = [
        {"decision": "pass", "note": ""},
        {"decision": "pass", "note": ""},
        {"decision": "needs_adjustment", "note": "minor"},
    ]
    assert aggregate_verdicts(verdicts) == "proceed"


def test_aggregate_one_pass_iterates() -> None:
    verdicts = [
        {"decision": "pass", "note": ""},
        {"decision": "needs_adjustment", "note": "x"},
        {"decision": "needs_adjustment", "note": "y"},
    ]
    assert aggregate_verdicts(verdicts) == "iterate"


def test_aggregate_all_needs_adjustment_iterates() -> None:
    verdicts = [
        {"decision": "needs_adjustment", "note": "a"},
        {"decision": "needs_adjustment", "note": "b"},
        {"decision": "needs_adjustment", "note": "c"},
    ]
    assert aggregate_verdicts(verdicts) == "iterate"


def test_crackerjack_invocation_pinned_to_run_v() -> None:
    """REQ-013 CI guard: invocation starts with `crackerjack run -v ` and lacks `-p`.

    The publish stage (`-p`) must never fire on the merge path; this
    assertion is the regex-equivalent of the spec invariant
    "any -p anywhere → fail".
    """
    assert CRACKERJACK_INVOCATION.startswith("crackerjack run -v ")
    assert "-p" not in CRACKERJACK_INVOCATION


def test_run_crackerjack_gate_invokes_run_v_with_exitcode_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """REQ-013: subprocess runs `crackerjack run -v --exitcode 0` in worktree.

    Monkeypatches ``subprocess.run`` so the test does not actually
    invoke crackerjack (operator-driven; would require a full venv +
    fixtures the test env cannot reproduce cheaply).
    """
    captured: dict[str, object] = {}

    class _Result:
        returncode = 0
        stderr = ""

    def fake_run(cmd: list[str], **kwargs: object) -> _Result:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.subprocess.run", fake_run
    )

    rc, stderr = run_crackerjack_gate(tmp_path)

    assert rc == 0
    assert stderr == ""
    # Exact subprocess call per spec REQ-013: `crackerjack run -v --exitcode 0`.
    assert captured["cmd"] == ["crackerjack", "run", "-v", "--exitcode", "0"]
    assert captured["kwargs"]["cwd"] == tmp_path
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True


def test_run_crackerjack_gate_propagates_returncode_and_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Non-zero exit and stderr propagate to the caller; the function does not
    re-interpret them. The merge-gate decision is made at the call site
    (which maps any non-zero exit to ``EXIT_CRACKERJACK_FAILURE = 2``).
    """
    class _Result:
        returncode = 7
        stderr = "ruff: 3 errors found\n"

    def fake_run(cmd: list[str], **kwargs: object) -> _Result:
        return _Result()

    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.subprocess.run", fake_run
    )

    rc, stderr = run_crackerjack_gate(tmp_path)
    assert rc == 7
    assert stderr == "ruff: 3 errors found\n"


# ── run_pipeline: stage-2 verdict mapping (REQ-004) ─────────────────────


def _stub_helpers_for_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    verdicts: list[dict[str, str]],
) -> None:
    """Stub the helpers ``run_pipeline`` composes so the test exercises
    only the stage-2 verdict → exit-code mapping.

    The stubs for stages 3-6 are always-success (``(0, "")``) so the
    only variable in the test is the canned ``verdicts`` list. The
    ``run_review`` stub returns the canned list verbatim; the real
    ``aggregate_verdicts`` is invoked to apply the spec §4.4 rule order.
    """
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.run_review",
        lambda *args, **kwargs: verdicts,
    )
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.run_crackerjack_gate",
        lambda *args, **kwargs: (0, ""),
    )
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.run_squash_merge",
        lambda *args, **kwargs: (0, ""),
    )
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.run_push",
        lambda *args, **kwargs: (0, ""),
    )
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main._run_cleanup",
        lambda *args, **kwargs: (0, ""),
    )


def test_run_pipeline_proceeds_when_review_three_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Three ``pass`` verdicts → aggregate returns ``"proceed"`` → EXIT_OK.

    The pipeline continues to stages 3-6 (all stubbed to success) and
    returns ``EXIT_OK = 0``. Asserts the spec §4.4 rule
    "≥2 pass → proceed" via the exit code.
    """
    verdicts = [
        {"agent": "python-pro", "decision": "pass", "note": "ok"},
        {"agent": "critical-audit-specialist", "decision": "pass", "note": "ok"},
        {"agent": "performance-review-specialist", "decision": "pass", "note": "ok"},
    ]
    _stub_helpers_for_pipeline(monkeypatch, verdicts=verdicts)

    rc = run_pipeline(tmp_path, branch="feat-test", base="main")
    assert rc == EXIT_OK


def test_run_pipeline_iterates_when_no_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One ``pass`` + two ``needs_adjustment`` → iterate → EXIT_REVIEW_FAILURE.

    The pipeline aborts at stage 2 with no progress made. Stages 3-6
    are not invoked (the verdict gate short-circuits).
    """
    verdicts = [
        {"agent": "python-pro", "decision": "pass", "note": "ok"},
        {"agent": "critical-audit-specialist", "decision": "needs_adjustment", "note": "lint"},
        {"agent": "performance-review-specialist", "decision": "needs_adjustment", "note": "x"},
    ]
    _stub_helpers_for_pipeline(monkeypatch, verdicts=verdicts)

    # Track whether stage 3 was reached.
    crackerjack_called: list[bool] = []
    real_crackerjack_called = lambda *a, **kw: (crackerjack_called.append(True) or 0, "")  # noqa: E731
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.run_crackerjack_gate",
        real_crackerjack_called,
    )

    rc = run_pipeline(tmp_path, branch="feat-test", base="main")
    assert rc == EXIT_REVIEW_FAILURE
    assert crackerjack_called == [], "stage 3 must not run after iterate verdict"


def test_run_pipeline_blocks_on_any_block_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Any single ``block`` → aggregate returns ``"block"`` → EXIT_REVIEW_FAILURE.

    Per spec §4.4 rule order: any block is highest-priority; the pipeline
    aborts at stage 2 regardless of the other two verdicts. Stages 3-6
    are not invoked.
    """
    verdicts = [
        {"agent": "python-pro", "decision": "block", "note": "security"},
        {"agent": "critical-audit-specialist", "decision": "pass", "note": "ok"},
        {"agent": "performance-review-specialist", "decision": "pass", "note": "ok"},
    ]
    _stub_helpers_for_pipeline(monkeypatch, verdicts=verdicts)

    crackerjack_called: list[bool] = []
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.run_crackerjack_gate",
        lambda *a, **kw: (crackerjack_called.append(True) or 0, ""),
    )

    rc = run_pipeline(tmp_path, branch="feat-test", base="main")
    assert rc == EXIT_REVIEW_FAILURE
    assert crackerjack_called == [], "stage 3 must not run after block verdict"


def test_run_pipeline_review_none_skips_stage_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--review none`` skips stage 2 entirely (user responsibility).

    The pipeline runs stages 3-6 directly. With all-stub-success
    helpers, returns ``EXIT_OK = 0``. Asserts that ``run_review`` is
    never invoked.
    """
    _stub_helpers_for_pipeline(monkeypatch, verdicts=[])

    review_called: list[bool] = []
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.run_review",
        lambda *a, **kw: (review_called.append(True) or []),
    )

    rc = run_pipeline(
        tmp_path, branch="feat-test", base="main", review_mode="none"
    )
    assert rc == EXIT_OK
    assert review_called == [], "stage 2 must not run when review_mode='none'"


def test_run_pipeline_crackerjack_failure_blocks_merge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Non-zero crackerjack gate → ``EXIT_CRACKERJACK_FAILURE = 2``.

    Stages 2 (review) and 3 (gate) are stubbed to return success / fail
    respectively. Stages 4-6 must not run after a non-zero gate.
    """
    _stub_helpers_for_pipeline(
        monkeypatch,
        verdicts=[
            {"agent": "python-pro", "decision": "pass", "note": "ok"},
            {"agent": "critical-audit-specialist", "decision": "pass", "note": "ok"},
            {"agent": "performance-review-specialist", "decision": "pass", "note": "ok"},
        ],
    )
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.run_crackerjack_gate",
        lambda *a, **kw: (7, "ruff: 3 errors\n"),
    )

    squash_called: list[bool] = []
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.run_squash_merge",
        lambda *a, **kw: (squash_called.append(True) or 0, ""),
    )

    rc = run_pipeline(tmp_path, branch="feat-test", base="main")
    assert rc == EXIT_CRACKERJACK_FAILURE
    assert squash_called == [], "stage 4 must not run after crackerjack failure"
