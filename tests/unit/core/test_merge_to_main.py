"""Tests for mahavishnu.core.merge_to_main — orchestration of the trunk-based
agent-review workflow (REQ-004, REQ-013, REQ-014).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mahavishnu.core.merge_to_main import (
    REVIEW_STATE_SCHEMA_VERSION,
    read_review_state,
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
