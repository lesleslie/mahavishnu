"""Structural validator for ``.claude/decisions/tool-description-rubric.md``.

REQ-TSQ-010 from ``docs/plans/2026-09-26-tool-surface-quality.md`` Task 2.2:
the rubric decision file MUST exist and MUST contain six named sections,
each with one **PASS** example and one **FAIL** example. This test pins
that structural contract so the rubric itself is a regression-tested
artifact (not a freeform prose file that drifts over time).

Per-tool compliance (does every ``@mcp.tool()`` description meet all
six criteria?) is intentionally NOT covered here — those criteria are
qualitative and belong in code review, not automated tests. See the
rubric's "Why no automated per-tool enforcement" section for the
rationale.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

RUBRIC_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".claude"
    / "decisions"
    / "tool-description-rubric.md"
)


# The six criterion headings — locked to the names in the rubric's
# "Decision rule" section. Each ``### N. <name>`` heading corresponds to
# a numbered criterion in the plan §5 Task 2.2.
EXPECTED_CRITERION_HEADINGS: ClassVar[list[str]] = [
    "When *not* to use the tool (negative cases)",
    "Common failure modes",
    "Return shape hint",
    "Model-side language (active voice, second-person imperatives, no marketing prose)",
    "Side-effect caveat (filesystem / network / external state)",
    "No internal disclosure",
]


@pytest.fixture(scope="module")
def rubric_text() -> str:
    """Read the rubric once per module — content is static on disk."""
    assert RUBRIC_PATH.exists(), (
        f"rubric decision file missing at {RUBRIC_PATH}; "
        f"Phase 2 Task 2.2 requires this file to exist"
    )
    return RUBRIC_PATH.read_text(encoding="utf-8")


def test_rubric_file_exists() -> None:
    """Phase 2 Task 2.2 acceptance criterion #1: file exists."""
    assert RUBRIC_PATH.exists(), (
        f"rubric missing at {RUBRIC_PATH}; "
        f"create it under .claude/decisions/ with the 6-criterion structure"
    )


def test_rubric_frontmatter_is_well_formed() -> None:
    """YAML frontmatter has status/role/kind/date/topic — sibling to other decision files."""
    text = RUBRIC_PATH.read_text(encoding="utf-8")
    assert text.startswith("---"), "rubric must start with YAML frontmatter"
    # Frontmatter ends with the first "---" on its own line.
    end = text.find("\n---\n", 4)
    assert end > 0, "rubric frontmatter must close with --- on its own line"
    fm = text[4:end]
    for required_key in ("status:", "role:", "kind:", "date:", "topic:"):
        assert required_key in fm, f"missing frontmatter key: {required_key}"


def test_rubric_contains_all_six_criterion_headings(rubric_text: str) -> None:
    """All six named ``### N. <name>`` headings present in order.

    Order matters: the criterion-numbering is part of the contract.
    Adding a section before criterion 1 or skipping a number would
    silently shift references in the validator test.
    """
    lines = rubric_text.splitlines()
    headings: list[str] = []
    for line in lines:
        # Match "### 1. When *not* to use the tool (negative cases)"
        if line.startswith("### ") and "." in line:
            # Strip the "### N. " prefix.
            tail = line[4:]
            # Find the first "." after the number prefix.
            dot_idx = tail.find(". ")
            if dot_idx > 0:
                # Sanity: must start with a digit (the criterion number).
                number_prefix = tail[:dot_idx]
                if number_prefix.isdigit():
                    headings.append(tail[dot_idx + 2 :])

    assert headings == EXPECTED_CRITERION_HEADINGS, (
        f"rubric must contain exactly the 6 expected criterion headings "
        f"in order. Expected: {EXPECTED_CRITERION_HEADINGS}; got: {headings}"
    )


@pytest.mark.parametrize("heading", EXPECTED_CRITERION_HEADINGS)
def test_rubric_each_criterion_has_pass_example(rubric_text: str, heading: str) -> None:
    """Every criterion has a 'PASS' example line.

    The structural contract requires each criterion to have a passing
    and a failing example so the rubric is not just a list of rules but
    a teaching artifact. A criterion without a PASS example is not
    actionable.
    """
    section = _extract_section(rubric_text, heading)
    assert "**PASS**" in section, (
        f"criterion '{heading}' is missing a PASS example; "
        f"every criterion needs at least one passing pattern"
    )


@pytest.mark.parametrize("heading", EXPECTED_CRITERION_HEADINGS)
def test_rubric_each_criterion_has_fail_example(rubric_text: str, heading: str) -> None:
    """Every criterion has a 'FAIL' example line.

    Symmetric to the PASS check — a criterion without a FAIL example
    leaves contributors guessing what NOT to do.
    """
    section = _extract_section(rubric_text, heading)
    assert "**FAIL**" in section, (
        f"criterion '{heading}' is missing a FAIL example; "
        f"every criterion needs at least one failing pattern"
    )


def test_rubric_explains_why_no_automated_enforcement(rubric_text: str) -> None:
    """The rubric documents WHY per-tool enforcement isn't automated.

    Future contributors may be tempted to write a test that asserts
    every @mcp.tool() description meets all six criteria. The rubric
    must explain why that's a bad idea so the temptation gets redirected
    to code review instead of brittle heuristics.
    """
    # Look for the section heading in any case (titles are written in
    # markdown as "## Why no automated per-tool enforcement").
    lowered = rubric_text.lower()
    assert "why no automated" in lowered or "no automated per-tool" in lowered, (
        "rubric must explain why per-tool enforcement is not automated; "
        "see 'Why no automated per-tool enforcement' section"
    )


def test_rubric_states_scope_and_activation(rubric_text: str) -> None:
    """The rubric has both a Scope and an Activation section."""
    lowered = rubric_text.lower()
    assert "## scope" in lowered, "rubric must have a '## Scope' section"
    assert "## activation" in lowered, (
        "rubric must have an '## Activation' section so future "
        "contributors know when Task 2.3 (top-10 rewrite) unblocks"
    )


def test_rubric_links_back_to_parent_plan(rubric_text: str) -> None:
    """The rubric references its source plan so reviewers can trace provenance."""
    assert "2026-09-26-tool-surface-quality" in rubric_text, (
        "rubric must reference its parent plan file so reviewers can "
        "trace the criterion set back to REQ-TSQ-010"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_section(text: str, heading: str) -> str:
    """Return the text of the ``### <heading>`` section.

    Sections are delimited by the next ``## `` heading (subsection
    boundary). Returns the body of the matching section, or empty
    string if not found.
    """
    lines = text.splitlines()
    section_lines: list[str] = []
    in_section = False
    for line in lines:
        if line.startswith("### ") and heading in line:
            in_section = True
            continue
        if in_section:
            # Section ends at the next ## (next-level) heading.
            if line.startswith("## "):
                break
            section_lines.append(line)
    return "\n".join(section_lines)
