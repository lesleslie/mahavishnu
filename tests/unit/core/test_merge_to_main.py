"""Tests for mahavishnu.core.merge_to_main — orchestration of the trunk-based
agent-review workflow (REQ-004, REQ-013, REQ-014).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.core.merge_to_main import (
    _CODE_QUALITY_AGENT,
    _check_pending_commit_eligibility,
    _check_sibling_worktree_state,
    _find_main_checkout_path,
    _list_repo_worktrees,
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
    run_squash_merge,
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


def test_run_crackerjack_gate_invokes_run_v_with_fast_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """REQ-013: subprocess runs ``crackerjack run -v -f`` in worktree.

    The merge gate uses the ``-f`` (fast hooks only) flag so the gate
    finishes in seconds rather than the ~5 minutes the comprehensive
    suite takes; the comprehensive suite is still expected to pass
    via the SessionEnd hook's pre-merge check (or CI), not on the
    merge path itself. The publish stage (``-p``) is still
    forbidden — see ``test_crackerjack_invocation_omits_publish_flag``.

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
    # Exact subprocess call per spec REQ-013: ``crackerjack run -v -f``.
    assert captured["cmd"] == ["crackerjack", "run", "-v", "-f"]
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
    # Stage 4.5 — pre-push consolidation gate (per new decision doc).
    # Default: gate passes (clears), no held-back siblings, no
    # ineligible commits. Tests that exercise the gate override these.
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main._run_consolidation_gate",
        lambda *args, **kwargs: (True, [], []),
    )
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main._write_held_back_log",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main._write_sticky_failure_marker",
        lambda *args, **kwargs: None,
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
    real_crackerjack_called = lambda *a, **kw: (crackerjack_called.append(True) or 0, "")
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


# ── run_pipeline: stage 4.5 pre-push consolidation gate ────────────────
# Per `docs/decisions/2026-10-13-prepushconsolidationgate.md`.


def test_run_pipeline_proceeds_when_consolidation_gate_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Gate clears → stage 5 push runs → EXIT_OK.

    Stub: gate returns ``(True, [], [])`` — no held-back siblings, no
    ineligible commits. Pipeline continues to push + cleanup; final
    return is ``EXIT_OK``.
    """
    _stub_helpers_for_pipeline(
        monkeypatch,
        verdicts=[
            {"agent": "python-pro", "decision": "pass", "note": ""},
            {"agent": "critical-audit-specialist", "decision": "pass", "note": ""},
            {"agent": "performance-review-specialist", "decision": "pass", "note": ""},
        ],
    )
    rc = run_pipeline(tmp_path, branch="feat-test", base="main")
    assert rc == EXIT_OK


def test_run_pipeline_holds_back_when_consolidation_gate_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Gate holds back → push NOT invoked → stage 6 cleanup NOT invoked
    → pipeline returns EXIT_OK (held back is not a failure).

    The held-back path writes the dev-log entry via
    ``_write_held_back_log`` and the sticky-failure marker via
    ``_write_sticky_failure_marker``; both are verified by recorder.
    """
    _stub_helpers_for_pipeline(
        monkeypatch,
        verdicts=[
            {"agent": "python-pro", "decision": "pass", "note": ""},
            {"agent": "critical-audit-specialist", "decision": "pass", "note": ""},
            {"agent": "performance-review-specialist", "decision": "pass", "note": ""},
        ],
    )
    held_back_siblings = ["sibling .worktrees/repo/b: branch 'feat-wip' has unmerged commits"]
    ineligible_commits = ["deadbeef0000"]
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main._run_consolidation_gate",
        lambda *a, **kw: (False, held_back_siblings, ineligible_commits),
    )
    log_writes: list[dict[str, object]] = []
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main._write_held_back_log",
        lambda *a, **kw: log_writes.append({"args": a, "kwargs": kw}),
    )
    sticky_writes: list[dict[str, object]] = []
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main._write_sticky_failure_marker",
        lambda *a, **kw: sticky_writes.append({"args": a, "kwargs": kw}),
    )

    push_called: list[bool] = []
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.run_push",
        lambda *a, **kw: (push_called.append(True) or 0, ""),
    )
    cleanup_called: list[bool] = []
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main._run_cleanup",
        lambda *a, **kw: (cleanup_called.append(True) or 0, ""),
    )

    rc = run_pipeline(tmp_path, branch="feat-test", base="main")
    assert rc == EXIT_OK, "held back returns EXIT_OK (squash-merge succeeded locally)"
    assert push_called == [], "stage 5 push must not run after gate hold-back"
    assert cleanup_called == [], "stage 6 cleanup must not run after gate hold-back"
    assert len(log_writes) == 1, "dev-log entry must be written on hold-back"
    assert len(sticky_writes) == 1, "sticky-failure marker must be written on hold-back"


def test_run_pipeline_consolidation_gate_bypassed_via_no_consolidation_gate_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``no_consolidation_gate=True`` → gate NOT invoked → push runs.

    Per the decision doc: ``/merge-to-main --no-consolidation-gate`` is
    the operator escape hatch (e.g., emergency hotfix). The gate
    function must not be called when this flag is set.
    """
    _stub_helpers_for_pipeline(
        monkeypatch,
        verdicts=[
            {"agent": "python-pro", "decision": "pass", "note": ""},
            {"agent": "critical-audit-specialist", "decision": "pass", "note": ""},
            {"agent": "performance-review-specialist", "decision": "pass", "note": ""},
        ],
    )
    gate_called: list[bool] = []
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main._run_consolidation_gate",
        lambda *a, **kw: (gate_called.append(True) or True, [], []),
    )

    rc = run_pipeline(
        tmp_path, branch="feat-test", base="main", no_consolidation_gate=True,
    )
    assert rc == EXIT_OK
    assert gate_called == [], "gate must not run when no_consolidation_gate=True"


def test_run_pipeline_consolidation_gate_runs_regardless_of_no_push(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``no_push=True`` → gate STILL runs (the gate is independent of
    the push step).

    Per the decision doc: the gate is a pre-push check that evaluates
    co-located worktrees and pending commits. Whether the user opts
    to push does not change whether the gate should evaluate. If the
    gate holds back with ``no_push=True``, the pipeline still returns
    EXIT_OK (the held-back state is recorded but push was not going
    to fire anyway).
    """
    _stub_helpers_for_pipeline(
        monkeypatch,
        verdicts=[
            {"agent": "python-pro", "decision": "pass", "note": ""},
            {"agent": "critical-audit-specialist", "decision": "pass", "note": ""},
            {"agent": "performance-review-specialist", "decision": "pass", "note": ""},
        ],
    )
    gate_called: list[bool] = []
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main._run_consolidation_gate",
        lambda *a, **kw: (gate_called.append(True) or True, [], []),
    )

    rc = run_pipeline(tmp_path, branch="feat-test", base="main", no_push=True)
    assert rc == EXIT_OK
    assert gate_called == [True], (
        "gate is a pre-push check independent of push; it evaluates "
        "regardless of --no-push"
    )


def test_consolidation_gate_sibling_worktree_check_passes_on_merged_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """State (a1): sibling branch HEAD ancestor of local main → passes.

    Verifies ``_check_sibling_worktree_state`` returns ``None`` when
    the sibling is listed in ``git worktree list --porcelain`` and
    its branch HEAD is an ancestor of local main (regular merge or
    fast-forward case).
    """
    sibling = tmp_path / "sibling-a"
    sibling.mkdir()
    worktree_list_output = f"worktree {sibling.resolve()}\nHEAD refs/heads/feat-merged\n"

    def fake_run(args, **kwargs):
        if "merge-base" in args:
            return _FakeProc(returncode=0, stdout="")  # ancestor → rc 0
        if "rev-parse" in args:
            return _FakeProc(returncode=0, stdout="feat-merged")
        if "log" in args:
            return _FakeProc(returncode=0, stdout="")  # no squash-merge commit
        return _FakeProc(returncode=0, stdout="")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = _check_sibling_worktree_state(tmp_path, sibling, "main", worktree_list_output)
    assert result is None, "merged sibling (state a1) must pass the gate"


def test_consolidation_gate_sibling_worktree_check_passes_on_squash_merge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """State (a2): squash-merge commit on local main with subject
    ``merge: <branch> -> main`` → passes.

    The branch HEAD is NOT an ancestor of local main (squash-merge
    creates a new commit), but the squash-merge commit's subject
    matches the canonical template, so the branch is "merged" via
    the squash-merge convention.
    """
    sibling = tmp_path / "sibling-sq"
    sibling.mkdir()
    worktree_list_output = f"worktree {sibling.resolve()}\nHEAD refs/heads/feat-squash\n"

    def fake_run(args, **kwargs):
        if "merge-base" in args:
            return _FakeProc(returncode=1, stdout="")  # NOT an ancestor
        if "rev-parse" in args:
            return _FakeProc(returncode=0, stdout="feat-squash")
        if "log" in args:
            # Local main has the squash-merge commit with matching subject
            return _FakeProc(
                returncode=0,
                stdout="abc1234 merge: feat-squash -> main\ndef5678 other commit",
            )
        return _FakeProc(returncode=0, stdout="")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = _check_sibling_worktree_state(tmp_path, sibling, "main", worktree_list_output)
    assert result is None, (
        "squash-merged sibling (state a2 via commit subject match) must pass the gate"
    )


def test_consolidation_gate_sibling_worktree_check_holds_back_on_unrelated_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Negative case: branch not ancestor AND no matching squash-merge
    commit → holds back.

    Regression test for the squash-merge detection: even though the
    new (a2) check recognizes squash-merge commits, it must NOT
    treat an unrelated branch as merged just because a different
    squash-merge commit is on local main.
    """
    sibling = tmp_path / "sibling-x"
    sibling.mkdir()
    worktree_list_output = f"worktree {sibling.resolve()}\nHEAD refs/heads/feat-unrelated\n"

    def fake_run(args, **kwargs):
        if "merge-base" in args:
            return _FakeProc(returncode=1, stdout="")  # NOT an ancestor
        if "rev-parse" in args:
            return _FakeProc(returncode=0, stdout="feat-unrelated")
        if "log" in args:
            # Local main has a squash-merge for a DIFFERENT branch
            return _FakeProc(
                returncode=0,
                stdout="abc1234 merge: feat-other -> main",
            )
        return _FakeProc(returncode=0, stdout="")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = _check_sibling_worktree_state(tmp_path, sibling, "main", worktree_list_output)
    assert result is not None
    assert "feat-unrelated" in result


def test_consolidation_gate_sibling_worktree_check_fails_on_wip_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """State (no-match): sibling branch HEAD NOT ancestor of main →
    holds back.

    Verifies ``_check_sibling_worktree_state`` returns a reason
    string when the sibling has unmerged WIP.
    """
    sibling = tmp_path / "sibling-wip"
    sibling.mkdir()
    worktree_list_output = f"worktree {sibling.resolve()}\nHEAD refs/heads/feat-wip\n"

    def fake_run(args, **kwargs):
        if "rev-parse" in args:
            return _FakeProc(returncode=0, stdout="feat-wip")
        if "merge-base" in args:
            return _FakeProc(returncode=1, stdout="")
        return _FakeProc(returncode=0, stdout="")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = _check_sibling_worktree_state(tmp_path, sibling, "main", worktree_list_output)
    assert result is not None
    assert "feat-wip" in result


def test_consolidation_gate_sibling_worktree_check_passes_on_sticky_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """State (d): sibling has ``.review-state.json`` with
    ``stage_failed`` non-null → passes (explicitly abandoned).
    """
    sibling = tmp_path / "sibling-d"
    sibling.mkdir()
    state_path = sibling / ".review-state.json"
    state_path.write_text(
        '{"schema_version": 1, "stage_failed": "user_abandoned"}',
    )
    worktree_list_output = f"worktree {sibling.resolve()}\nHEAD refs/heads/feat-x\n"

    # rev-parse / merge-base would fail (WIP), but state (d) short-circuits
    # before they run. So no subprocess mocking needed.
    result = _check_sibling_worktree_state(tmp_path, sibling, "main", worktree_list_output)
    assert result is None


def test_consolidation_gate_sibling_worktree_check_passes_on_no_worktree_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """State (b): sibling appears in ``<worktree-base>/<basename>/`` but
    NOT in ``git worktree list --porcelain`` → passes (pruned).
    """
    sibling = tmp_path / "sibling-b"
    sibling.mkdir()
    # Worktree list is empty (sibling was pruned from git but the
    # directory still exists on disk — the gate tolerates this).
    worktree_list_output = ""
    result = _check_sibling_worktree_state(tmp_path, sibling, "main", worktree_list_output)
    assert result is None


def test_consolidation_gate_lineage_check_passes_on_squash_merge_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pending commit with subject ``merge: <branch> -> <base>``
    (squash-merge template from ``run_squash_merge``) → eligible.

    Verifies the (α) eligibility-check accepts the squash-merge
    shape produced by stage 4.
    """
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _FakeProc(
            returncode=0,
            stdout="abc123|merge: feat-x -> main\ndef456|merge: feat-y -> main",
        ),
    )
    ineligible = _check_pending_commit_eligibility("origin/main")
    assert ineligible == []


def test_consolidation_gate_lineage_check_fails_on_unauthorized_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pending commit with subject NOT matching squash template →
    ineligible (held back unless ``--no-consolidation-gate``).

    For v1: any commit whose subject does not start with
    ``merge: `` is ineligible.
    """
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: _FakeProc(
            returncode=0,
            stdout="abc123|merge: feat-x -> main\ndef456|wip: typo\n",
        ),
    )
    ineligible = _check_pending_commit_eligibility("origin/main")
    assert ineligible == ["def456"]


def test_list_repo_worktrees_finds_siblings_excluding_self(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``_list_repo_worktrees`` returns siblings from the parent
    directory (the repo dir under the worktree base), excluding the
    cwd worktree itself.

    Setup: ``<base>/<repo>/a`` + ``<base>/<repo>/b`` + ``<base>/<repo>/c``;
    cwd is ``<base>/<repo>/b``. Expected: ``[a, c]``.
    """
    base = tmp_path / "worktrees"
    repo_dir = base / "test-repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / "a").mkdir()
    (repo_dir / "b").mkdir()
    (repo_dir / "c").mkdir()

    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.get_worktree_base_path",
        lambda: base,
    )
    cwd = repo_dir / "b"
    siblings = _list_repo_worktrees(cwd)
    sibling_names = [s.name for s in siblings]
    assert sibling_names == ["a", "c"]
    assert cwd not in siblings


def test_list_repo_worktrees_returns_empty_for_worktree_outside_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Worktrees NOT under the configured base return no siblings
    (no false positives for fresh checkouts or non-Vishnu worktrees).
    """
    base = tmp_path / "worktrees"
    base.mkdir()
    # Worktree path is at tmp_path/foo, NOT under base/
    cwd = tmp_path / "foo"
    cwd.mkdir()

    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.get_worktree_base_path",
        lambda: base,
    )
    siblings = _list_repo_worktrees(cwd)
    assert siblings == []


# ── run_squash_merge: lands on local main, not detached HEAD ─────────────
# The historical implementation did ``git checkout <base>`` (default
# ``origin/main``) inside the worktree. That detached HEAD, so the
# squash-merge commit landed on a floating detached ref that got
# garbage-collected on cleanup. The fix relocates the squash-merge
# to the main checkout, where ``main`` is checked out as a real branch.


def test_run_squash_merge_lands_commit_on_main_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Stages 3-5 (checkout, merge --squash, commit) run in main checkout.

    Without this, ``run_squash_merge`` does everything in
    ``worktree_root``. With ``base=origin/main`` (the default), the
    worktree's ``git checkout origin/main`` is a detached HEAD — the
    squash commit lands there and is GC'd on cleanup. The pipeline
    returns exit 0 but main is never updated.
    """
    worktree = tmp_path / "worktree"
    main_checkout = tmp_path / "main"
    worktree.mkdir()
    main_checkout.mkdir()

    # Pre-rebase SHA re-verification is skipped by leaving the state
    # file empty (read_review_state returns None → no SHA check).
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.read_review_state",
        lambda *a, **kw: {},
    )

    # Capture every subprocess.run invocation so we can assert cwd.
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> _FakeProc:
        calls.append((cmd, kwargs))
        return _FakeProc(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.subprocess.run", fake_run
    )

    # Tell the production code where the real main checkout is.
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main._find_main_checkout_path",
        lambda worktree_root: main_checkout,
    )

    rc, _stderr = run_squash_merge(worktree, "origin/main", "feature-x")

    assert rc == 0

    # Index the calls by argv for easy lookup.
    by_argv: dict[tuple[str, ...], dict[str, object]] = {}
    for cmd, kwargs in calls:
        by_argv[tuple(cmd)] = kwargs

    # The rebase (step 1) still happens in the worktree.
    rebase = by_argv.get(("git", "rebase", "origin/main"))
    assert rebase is not None, "rebase step missing"
    assert rebase["cwd"] == worktree

    # The checkout (step 3) now happens in the main checkout.
    checkout = by_argv.get(("git", "checkout", "origin/main"))
    assert checkout is not None, "checkout step missing"
    assert checkout["cwd"] == main_checkout, (
        f"checkout must run in main checkout, got cwd={checkout['cwd']!r}"
    )

    # The squash-merge (step 4) and commit (step 5) also run there.
    squash = by_argv.get(("git", "merge", "--squash", "feature-x"))
    assert squash is not None, "merge --squash step missing"
    assert squash["cwd"] == main_checkout, (
        f"merge --squash must run in main checkout, got cwd={squash['cwd']!r}"
    )

    # Commit argv is ``["git", "commit", "-m", "merge: feature-x -> origin/main"]``
    commit_calls = [
        (cmd, kw) for cmd, kw in calls
        if len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "commit"
    ]
    assert len(commit_calls) == 1, (
        f"expected exactly one commit call, got {len(commit_calls)}: "
        f"{[c[0] for c in commit_calls]}"
    )
    assert commit_calls[0][1]["cwd"] == main_checkout, (
        f"commit must run in main checkout, got cwd={commit_calls[0][1]['cwd']!r}"
    )


def test_find_main_checkout_path_returns_none_when_no_main_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No worktree has ``main`` checked out → return None.

    Squash-merge can only land where a real ``main`` branch is
    checked out. A bare repo, a repo where main is detached, or a
    repo with no main at all returns None and the pipeline surfaces
    EXIT_REBASE_CONFLICT.
    """
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    # Simulate `git worktree list --porcelain` output with no main branch.
    porcelain = (
        f"worktree {tmp_path / 'worktree'}\n"
        "HEAD abc123\n"
        "detached\n"
        f"worktree {tmp_path / 'other'}\n"
        "HEAD def456\n"
        "branch refs/heads/feature\n"
    )

    def fake_run(cmd: list[str], **kwargs: object) -> _FakeProc:
        return _FakeProc(returncode=0, stdout=porcelain, stderr="")

    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.subprocess.run", fake_run
    )

    result = _find_main_checkout_path(worktree)
    assert result is None


def test_find_main_checkout_path_returns_main_checkout_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Finds the worktree whose branch is ``refs/heads/main``."""
    worktree = tmp_path / "worktree"
    main_path = tmp_path / "main"
    other_path = tmp_path / "other"

    porcelain = (
        f"worktree {main_path}\n"
        "HEAD aaa111\n"
        "branch refs/heads/main\n"
        f"worktree {other_path}\n"
        "HEAD bbb222\n"
        "branch refs/heads/feature\n"
        f"worktree {worktree}\n"
        "HEAD ccc333\n"
        "branch refs/heads/fix/squash-merge-local-main\n"
    )

    def fake_run(cmd: list[str], **kwargs: object) -> _FakeProc:
        return _FakeProc(returncode=0, stdout=porcelain, stderr="")

    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.subprocess.run", fake_run
    )

    result = _find_main_checkout_path(worktree)
    assert result == main_path


# Helper subprocess result class used by the consolidation-gate tests.
class _FakeProc:
    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_subprocess(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    branch_probe_rc: int = 0,
) -> _FakeProc:
    """Returns a single _FakeProc; tests that need branching
    behavior should define their own fake_run instead."""
    return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)
