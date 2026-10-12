"""Regression tests for `scripts/regenerate_plan_index.py` frontmatter extraction.

These tests guard against the bug class that surfaced on 2026-10-12:
multiline unquoted YAML values with embedded `': '` characters were
mis-parsed by ``yaml.safe_load`` because the non-greedy regex
``_FRONTMATTER_RE`` matched the first ``---`` line in the truncated
4096-byte head as the frontmatter closer.

Per plan ``docs/plans/2026-10-12-plan-index-sync-script-hardening.md``.
Phase 1 (REQ-IDX-001, REQ-IDX-004) ships the data fix; Phases 2 and 3
(REQ-IDX-002/005, REQ-IDX-003/006) ship the script hardening.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# These 3 drafts had YAML-invalid frontmatter pre-Phase 1. They are quoted
# in commit 1/2/3 of the plan and must parse cleanly afterward.
DRAFTS = [
    "docs/plans/drafts/2026-09-27-akosha-eval-metric-sink.md",
    "docs/plans/drafts/2026-09-27-akosha-tool-call-feed-lifecycle.md",
    "docs/plans/drafts/2026-09-26-eval-methodology.md",
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _split_frontmatter(text: str) -> str:
    """Line-anchored frontmatter extraction. Mirrors the Phase 2 design
    in `scripts/regenerate_plan_index.py` (which this test pre-dates).
    """
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        raise AssertionError("missing opening frontmatter fence")
    end = next(
        (i for i in range(1, len(lines)) if lines[i].rstrip() == "---"),
        None,
    )
    if end is None:
        raise AssertionError("missing closing frontmatter fence")
    return "\n".join(lines[1:end])


@pytest.mark.req(["REQ-IDX-001", "REQ-IDX-004"])
@pytest.mark.parametrize("rel_path", DRAFTS)
def test_draft_frontmatter_parses(rel_path: str) -> None:
    """Each draft's frontmatter is YAML-valid (smoke for the 3 known-bad files)."""
    p = REPO_ROOT / rel_path
    fm_text = _split_frontmatter(p.read_text(encoding="utf-8"))
    parsed = yaml.safe_load(fm_text)
    assert isinstance(parsed, dict), (
        f"frontmatter in {rel_path} is not a mapping: {type(parsed).__name__}"
    )
    for required in ("status", "role", "kind", "date", "title"):
        assert required in parsed, (
            f"{rel_path} missing required frontmatter key: {required!r}"
        )


# ---------------------------------------------------------------------------
# Phase 2 — body `---` markers must not be mis-extracted as the closer.
# Characterization test: passes on the current lazy-regex implementation
# (because the lazy quantifier already picks the first closer) AND must
# continue to pass after the refactor to a line-anchored parser. The
# refactor itself is a robustness improvement, not a bug fix — but a
# future regression to a GREEDY regex would surface here.
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-IDX-002", "REQ-IDX-005"])
def test_extract_frontmatter_with_body_horizontal_rule_does_not_mis_extract() -> None:
    """`extract_frontmatter` returns only the real frontmatter when the body
    contains `---` markers (markdown horizontal rules)."""
    from scripts.regenerate_plan_index import extract_frontmatter

    text = (
        "---\n"
        "status: active\n"
        "title: Test\n"
        "---\n"
        "\n"
        "# Title\n"
        "\n"
        "Some body with a `---` in the middle.\n"
        "\n"
        "---\n"
        "\n"
        "More body.\n"
    )
    parsed = extract_frontmatter(text, yaml)
    assert isinstance(parsed, dict), (
        f"expected frontmatter dict, got {type(parsed).__name__}: {parsed!r}"
    )
    assert parsed.get("status") == "active"
    assert parsed.get("title") == "Test"
    # Body content must NOT be present in the parsed frontmatter.
    for forbidden in ("More body", "Some body", "Title\n"):
        assert forbidden not in parsed, (
            f"body content {forbidden!r} leaked into frontmatter parse: {parsed!r}"
        )
