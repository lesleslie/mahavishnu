"""Unit tests for the security-finding-gate skill.

The skill is instruction, not code, so these tests pin the parts that other
surfaces depend on: that the file exists and is well-formed, that it states
the two rules the gate exists to enforce, and that the two inbound
references (agent and workflow) resolve.

A skill that silently loses its counts requirement or its evidence
requirement is a gate that no longer gates anything, and that failure is
invisible in review output. These tests make it loud.
"""

from __future__ import annotations

from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "security-finding-gate" / "SKILL.md"
AGENT_PATH = REPO_ROOT / ".claude" / "agents" / "api-security-specialist.md"
WORKFLOW_PATH = REPO_ROOT / ".claude" / "commands" / "workflows" / "multi-stage-code-review.md"

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _flatten(text: str) -> str:
    """Collapse whitespace so a phrase split across a markdown line wrap
    still matches."""
    return re.sub(r"\s+", " ", text)


def _frontmatter() -> str:
    match = FRONTMATTER_RE.match(_skill_text())
    assert match is not None, "skill must open with a YAML frontmatter block"
    return match.group(1)


class TestSkillFile:
    def test_skill_exists(self) -> None:
        assert SKILL_PATH.is_file(), f"missing skill file: {SKILL_PATH}"

    def test_frontmatter_declares_name_and_description(self) -> None:
        frontmatter = _frontmatter()
        assert re.search(r"^name:\s*security-finding-gate\s*$", frontmatter, re.MULTILINE)
        assert re.search(r"^description:", frontmatter, re.MULTILINE)

    def test_description_is_scoped_to_finding_triage(self) -> None:
        """The description is the routing surface; it must not read as a
        general instruction to act on the filesystem or the network."""
        frontmatter = _frontmatter()
        lowered = frontmatter.lower()
        for forbidden in ("rm -", "curl ", "http://", "https://", "delete the", "push to"):
            assert forbidden not in lowered, f"description mentions {forbidden!r}"


class TestEvidenceRequirement:
    """REQ-FIND-001 — dismissal requires recorded evidence."""

    def test_skill_requires_evidence_to_dismiss(self) -> None:
        # req: REQ-FIND-001
        text = _flatten(_skill_text())
        assert "Evidence required to dismiss" in text
        assert "recorded evidence" in text

    def test_skill_forbids_pattern_similarity_dismissal(self) -> None:
        text = _flatten(_skill_text())
        assert "Pattern similarity alone is insufficient" in text

    def test_skill_requires_end_to_end_data_flow(self) -> None:
        text = _skill_text()
        assert "data flow" in text.lower()


class TestCountsRequirement:
    """REQ-FIND-002 — the report states true/false-positive counts."""

    def test_skill_requires_the_count_format(self) -> None:
        # req: REQ-FIND-002
        text = _flatten(_skill_text())
        assert "X TRUE POSITIVES, Y FALSE POSITIVES" in text

    def test_skill_requires_claim_articulation_before_verdict(self) -> None:
        text = _skill_text()
        assert "Articulate the claim" in text


class TestInboundReferences:
    """REQ-FIND-003 — the gate is reachable from an agent and a workflow."""

    def test_project_agent_references_the_skill(self) -> None:
        # req: REQ-FIND-003
        assert AGENT_PATH.is_file(), f"missing agent: {AGENT_PATH}"
        assert "security-finding-gate" in AGENT_PATH.read_text(encoding="utf-8")

    def test_review_workflow_references_the_skill(self) -> None:
        assert WORKFLOW_PATH.is_file(), f"missing workflow: {WORKFLOW_PATH}"
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        assert "security-finding-gate" in text
        assert "true/false-positive counts" in text.lower()

    def test_skill_is_discoverable_by_name(self) -> None:
        """The skill directory name and the frontmatter name must agree, or
        the loader will expose it under a different name than the references
        use."""
        assert SKILL_PATH.parent.name == "security-finding-gate"
