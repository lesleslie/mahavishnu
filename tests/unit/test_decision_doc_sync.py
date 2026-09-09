"""Sync tests for `.claude/decisions/worktree-cleanup-policy.md`.

These tests guard doc/code parity so that the decision doc stays the canonical
exposition of the worktree cleanup policy. If the Tier literal, the
PLAN_ORPHAN_PATTERNS tuple, or the negative-rule count drifts in code, the
doc must be updated to match.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.core.worktree_scan import (
    PLAN_ORPHAN_PATTERNS,
    Tier,
)


DECISION_DOC = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "decisions"
    / "worktree-cleanup-policy.md"
)


def _doc_text() -> str:
    return DECISION_DOC.read_text()


def _tier_table_rows(doc: str) -> str:
    """Extract the Decision rule § tier rubric table from the doc."""
    marker = "## Decision rule"
    start = doc.find(marker)
    assert start != -1, "Decision rule section not found in decision doc"
    end = doc.find("##", start + len(marker))
    if end == -1:
        end = len(doc)
    return doc[start:end]


def test_decision_doc_lists_current_tiers() -> None:
    """Every tier in the `Tier` Literal (except `unknown`) must appear in § Decision rule."""
    doc = _doc_text()
    section = _tier_table_rows(doc)

    expected_tiers = [t for t in __import__("typing").get_args(Tier) if t != "unknown"]
    missing: list[str] = []
    for tier in expected_tiers:
        # Each tier should appear as a row label (e.g., `| **A-merged** |` or `| **X** |`)
        if tier not in section:
            missing.append(tier)

    assert not missing, (
        f"Decision doc § Decision rule table missing tier rows: {missing}. "
        f"Update {DECISION_DOC.name} to keep doc/code parity."
    )


def test_doc_lists_current_plan_orphan_patterns() -> None:
    """Every PLAN_ORPHAN_PATTERNS entry's prefix must appear in the doc's plan-orphan section."""
    doc = _doc_text()

    # Locate the "Plan-orphan patterns" subsection.
    marker = "### Plan-orphan patterns"
    start = doc.find(marker)
    assert start != -1, "Plan-orphan patterns subsection not found in decision doc"
    end = doc.find("##", start + len(marker))
    if end == -1:
        end = len(doc)
    section = doc[start:end]

    missing: list[str] = []
    for pattern in PLAN_ORPHAN_PATTERNS:
        # Patterns may have a leading `^` anchor; strip it for the doc check.
        prefix = pattern.lstrip("^")
        if prefix not in section:
            missing.append(pattern)

    assert not missing, (
        f"Decision doc § Plan-orphan patterns missing prefixes: {missing}. "
        f"Update {DECISION_DOC.name} to keep doc/code parity."
    )


def test_doc_has_negative_rules() -> None:
    """The decision doc must enumerate ≥ 8 `Don't` negative rules."""
    doc = _doc_text()
    count = sum(
        1
        for line in doc.splitlines()
        if line.lstrip().startswith(("- **Don't", "- **DON'T"))
    )
    assert count >= 8, (
        f"Decision doc has only { count } 'Don't' rules (≥ 8 expected). "
        f"Update {DECISION_DOC.name}."
    )
