"""Tests for ``scripts/tool_frontmatter_validator.py``.

These tests pin two pre-existing bugs in the validator that were
discovered during the T3.3 review (see
``.claude/decisions/technical-debt-roadmap.md``):

1. ``parse_frontmatter`` only accepted the ``---`` delimiter, but the
   repo's tool files use a 70-underscore delimiter. The validator was
   silently returning ``(None, content)`` for every real file.

2. ``report_results`` calls
   ``result.file_path.relative_to(self.tools_dir.parent)`` which raises
   ``ValueError`` when the file isn't under the (non-existent)
   ``commands/`` directory — triggered by the ``validate <file>``
   subcommand for any file outside ``commands/tools/``.
"""

from __future__ import annotations

from pathlib import Path

# ``scripts/`` is added to ``sys.path`` by the root ``conftest.py`` so we
# can ``import tool_frontmatter_validator`` directly without installing
# it as a package.
from tool_frontmatter_validator import ToolFrontmatterValidator  # noqa: E402


# A representative sample of the real frontmatter used in the repo.
# Captured verbatim from
# .claude/commands/tools/deployment/release-management.md
# (line 1 is a 70-underscore delimiter).
REAL_TOOL_FRONTMATTER_LINES = [
    "_" * 70,
    "title: Release Management Playbook",
    "owner: Delivery Operations",
    "last_reviewed: 2025-02-06",
    "status: active",
    "id: 01HQZ4K9M3R7T8B5N2W1V0A3F4P",  # 26-char ULID
    "category: deployment",
    "_" * 70,
    "",
    "Body text.",
]


def _write_real_style_tool(tmp_path: Path) -> Path:
    """Write a tool file using the repo's actual 70-underscore delimiter."""
    p = tmp_path / "tool.md"
    p.write_text("\n".join(REAL_TOOL_FRONTMATTER_LINES) + "\n")
    return p


def _write_classic_tool(tmp_path: Path) -> Path:
    """Write a tool file using the classic ``---`` delimiter."""
    p = tmp_path / "tool.md"
    p.write_text(
        "---\n"
        "title: Test\n"
        "owner: Delivery Operations\n"
        "last_reviewed: 2025-02-06\n"
        "status: active\n"
        "id: 01HQZ4K9M3R7T8B5N2W1V0A3F4P\n"
        "category: deployment\n"
        "---\n"
        "\n"
        "Body.\n"
    )
    return p


# --- Bug #1: parse_frontmatter delimiter ---------------------------------


def test_parse_frontmatter_accepts_70_underscore_delimiter(tmp_path: Path) -> None:
    """The repo's actual frontmatter style (70 underscores) must parse."""
    tool = _write_real_style_tool(tmp_path)
    validator = ToolFrontmatterValidator(tools_dir=tmp_path)

    frontmatter, body = validator.parse_frontmatter(tool)

    assert frontmatter is not None, (
        "parse_frontmatter returned None for the 70-underscore delimiter "
        "style — the validator is a no-op on real files"
    )
    assert frontmatter["title"] == "Release Management Playbook"
    assert frontmatter["status"] == "active"
    assert body.strip() == "Body text."


def test_parse_frontmatter_still_accepts_classic_dash_delimiter(tmp_path: Path) -> None:
    """Backward compatibility: the original ``---`` style must keep working."""
    tool = _write_classic_tool(tmp_path)
    validator = ToolFrontmatterValidator(tools_dir=tmp_path)

    frontmatter, body = validator.parse_frontmatter(tool)

    assert frontmatter is not None
    assert frontmatter["title"] == "Test"
    assert body.strip() == "Body."


def test_validate_tool_recognises_real_style_frontmatter(tmp_path: Path) -> None:
    """End-to-end: a valid 70-underscore tool must validate as valid.

    If ``parse_frontmatter`` is broken, ``validate_tool`` will report
    ``"No valid YAML frontmatter found"`` as a critical issue for every
    real file in the repo.
    """
    tool = _write_real_style_tool(tmp_path)
    validator = ToolFrontmatterValidator(tools_dir=tmp_path)

    result = validator.validate_tool(tool)

    critical = [i for i in result.issues if i.severity == "critical"]
    assert critical == [], (
        f"Expected no critical issues for a fully-valid tool, got: "
        f"{[(i.field, i.message) for i in critical]}"
    )
    assert result.valid is True


def test_parse_frontmatter_returns_none_for_file_without_frontmatter(
    tmp_path: Path,
) -> None:
    """A markdown file with no frontmatter at all must still return ``None``."""
    p = tmp_path / "no_frontmatter.md"
    p.write_text("# Just a heading\n\nNo frontmatter here.\n")
    validator = ToolFrontmatterValidator(tools_dir=tmp_path)

    frontmatter, body = validator.parse_frontmatter(p)

    assert frontmatter is None
    assert "Just a heading" in body


# --- Bug #2: validate <file> crash on out-of-tree files ------------------


def test_report_results_does_not_crash_on_out_of_tree_file(
    tmp_path: Path, capsys
) -> None:
    """The ``validate <file>`` subcommand reports on a single file.

    ``report_results`` must not raise when the file is outside the
    configured ``tools_dir.parent`` (i.e. anywhere in the user's
    checkout), regardless of where the file actually lives.

    The file uses the classic ``---`` delimiter so this test isolates
    Bug #2 from Bug #1.
    """
    tool = _write_classic_tool(tmp_path)
    # Deliberately point ``tools_dir`` somewhere unrelated to ``tmp_path``
    # so the file is "out of tree" from the validator's perspective.
    validator = ToolFrontmatterValidator(
        tools_dir=Path("/nonexistent/commands/tools")
    )

    result = validator.validate_tool(tool)
    # The bug surfaces here — this call raises ValueError today.
    validator.report_results([result])

    # The file should be mentioned in the output (path display works).
    captured = capsys.readouterr()
    assert "tool.md" in captured.out
