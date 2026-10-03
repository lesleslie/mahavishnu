"""Tests for mahavishnu.core.merge_to_main — orchestration of the trunk-based
agent-review workflow (REQ-004, REQ-013, REQ-014).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.core.merge_to_main import (
    _CODE_QUALITY_AGENT,
    AGENT_POOL,
    REVIEW_STATE_SCHEMA_VERSION,
    parse_verdict,
    read_review_state,
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
